"""Enhanced PostgreSQL stored procedures with production hardening.

This module provides production-ready stored procedures with circuit breaker patterns,
rate limiting, security enhancements, and comprehensive monitoring.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection


class EnhancedDLQStoredProcedures:
    """Enhanced PostgreSQL stored procedures for production DLQ processing."""

    @staticmethod
    def create_enhanced_dlq_procedures(connection: Connection) -> None:
        """Create all enhanced DLQ processing stored procedures."""
        # Check if we're using PostgreSQL
        dialect_name = connection.dialect.name
        if dialect_name != 'postgresql':
            raise ValueError(f"Enhanced stored procedures are only supported for PostgreSQL, not {dialect_name}")

        # 1. Enhanced main processing function with circuit breaker
        connection.execute(
            text("""
        CREATE OR REPLACE FUNCTION process_dlq_events_enhanced(
            p_limit INTEGER DEFAULT 1000,
            p_reason_filter TEXT DEFAULT NULL,
            p_priority_filter INTEGER DEFAULT NULL,
            p_session_id TEXT DEFAULT NULL,
            p_circuit_breaker_name TEXT DEFAULT 'dlq_main'
        )
        RETURNS TABLE(
            processed_count INTEGER,
            repaired_count INTEGER,
            failed_count INTEGER,
            skipped_count INTEGER,
            circuit_breaker_triggered BOOLEAN,
            processing_duration_ms INTEGER
        )
        LANGUAGE plpgsql
        AS $$
        DECLARE
            dlq_record RECORD;
            malformed_content TEXT;
            repaired_payload JSONB;
            success BOOLEAN;
            processed INTEGER := 0;
            repaired INTEGER := 0;
            failed INTEGER := 0;
            skipped INTEGER := 0;
            circuit_breaker_triggered BOOLEAN := FALSE;
            start_time TIMESTAMP;
            end_time TIMESTAMP;
            processing_duration_ms INTEGER;
            lock_id UUID;
            lock_expires TIMESTAMP;
            rate_limit_hits INTEGER := 0;
            batch_size INTEGER;
        BEGIN
            start_time := clock_timestamp();
            
            -- Check circuit breaker state
            IF NOT check_circuit_breaker(p_circuit_breaker_name) THEN
                circuit_breaker_triggered := TRUE;
                RETURN QUERY SELECT 0, 0, 0, 0, TRUE, 0;
                RETURN;
            END IF;
            
            -- Generate session ID if not provided
            IF p_session_id IS NULL THEN
                p_session_id := gen_random_uuid()::TEXT;
            END IF;
            
            batch_size := COALESCE(p_limit, 1000);
            
            -- Process unresolved DLQ events with locking
            FOR dlq_record IN 
                SELECT id, payload, source, source_offset, reason, retry_count, 
                       priority, classification, idempotency_key
                FROM dead_letter_events 
                WHERE resolved = FALSE
                AND (p_reason_filter IS NULL OR reason = p_reason_filter)
                AND (p_priority_filter IS NULL OR priority <= p_priority_filter)
                AND (processing_lock IS NULL OR lock_expires_at < NOW())
                ORDER BY priority ASC, created_at ASC
                LIMIT batch_size
                FOR UPDATE SKIP LOCKED
            LOOP
                -- Acquire processing lock
                lock_id := gen_random_uuid();
                lock_expires := NOW() + INTERVAL '30 minutes';
                
                UPDATE dead_letter_events 
                SET processing_lock = lock_id, lock_expires_at = lock_expires
                WHERE id = dlq_record.id AND processing_lock IS NULL;
                
                -- Check if lock was acquired
                IF NOT FOUND THEN
                    skipped := skipped + 1;
                    CONTINUE;
                END IF;
                
                processed := processed + 1;
                
                -- Rate limiting check
                IF processed % 100 = 0 THEN
                    PERFORM pg_sleep(0.01); -- 10ms pause every 100 records
                END IF;
                
                -- Extract malformed content
                malformed_content := dlq_record.payload->>'malformed_content';
                
                IF malformed_content IS NULL THEN
                    -- Record skip reason
                    UPDATE dead_letter_events 
                    SET error_history = COALESCE(error_history, '[]'::JSONB) || 
                        jsonb_build_object(
                            'timestamp', NOW()::TEXT,
                            'error_type', 'skip',
                            'error_message', 'No malformed content found',
                            'processing_method', 'stored_proc'
                        ),
                        last_processed_at = NOW()
                    WHERE id = dlq_record.id;
                    
                    skipped := skipped + 1;
                    CONTINUE;
                END IF;
                
                -- Attempt repair using enhanced JSON repair functions
                repaired_payload := repair_cowrie_json_enhanced(malformed_content, dlq_record.id);
                
                IF repaired_payload IS NOT NULL THEN
                    -- Insert/update raw event using UPSERT
                    success := upsert_repaired_event_enhanced(
                        dlq_record.source,
                        dlq_record.source_offset,
                        dlq_record.source,
                        repaired_payload,
                        dlq_record.idempotency_key
                    );
                    
                    IF success THEN
                        -- Mark DLQ event as resolved
                        UPDATE dead_letter_events 
                        SET resolved = TRUE, 
                            resolved_at = NOW(),
                            resolution_method = 'stored_proc_enhanced',
                            processing_lock = NULL,
                            lock_expires_at = NULL,
                            processing_attempts = COALESCE(processing_attempts, '[]'::JSONB) ||
                                jsonb_build_object(
                                    'timestamp', NOW()::TEXT,
                                    'method', 'stored_proc_enhanced',
                                    'success', TRUE,
                                    'processing_time_ms', EXTRACT(EPOCH FROM (NOW() - start_time)) * 1000
                                )
                        WHERE id = dlq_record.id;
                        
                        repaired := repaired + 1;
                        
                        -- Record success in circuit breaker
                        PERFORM record_circuit_breaker_success(p_circuit_breaker_name);
                    ELSE
                        -- Record failure
                        PERFORM record_dlq_processing_failure(dlq_record.id, 'upsert_failed', 
                                                           'Failed to insert repaired event', 'stored_proc');
                        failed := failed + 1;
                        
                        -- Record failure in circuit breaker
                        PERFORM record_circuit_breaker_failure(p_circuit_breaker_name);
                    END IF;
                ELSE
                    -- Record repair failure
                    PERFORM record_dlq_processing_failure(dlq_record.id, 'repair_failed', 
                                                       'Failed to repair malformed content', 'stored_proc');
                    failed := failed + 1;
                    
                    -- Record failure in circuit breaker
                    PERFORM record_circuit_breaker_failure(p_circuit_breaker_name);
                END IF;
                
                -- Release lock
                UPDATE dead_letter_events 
                SET processing_lock = NULL, lock_expires_at = NULL
                WHERE id = dlq_record.id;
            END LOOP;
            
            end_time := clock_timestamp();
            processing_duration_ms := EXTRACT(EPOCH FROM (end_time - start_time)) * 1000;
            
            -- Record processing metrics
            INSERT INTO dlq_processing_metrics (
                processing_session_id, processing_method, batch_size,
                processed_count, repaired_count, failed_count, skipped_count,
                processing_duration_ms, circuit_breaker_triggered, rate_limit_hits,
                started_at, completed_at
            ) VALUES (
                p_session_id, 'stored_proc_enhanced', batch_size,
                processed, repaired, failed, skipped,
                processing_duration_ms, circuit_breaker_triggered, rate_limit_hits,
                start_time, end_time
            );
            
            RETURN QUERY SELECT processed, repaired, failed, skipped, 
                              circuit_breaker_triggered, processing_duration_ms;
        END;
        $$;
        """)
        )

        # 2. Circuit breaker functions
        connection.execute(
            text("""
        CREATE OR REPLACE FUNCTION check_circuit_breaker(breaker_name TEXT)
        RETURNS BOOLEAN
        LANGUAGE plpgsql
        AS $$
        DECLARE
            breaker_state RECORD;
        BEGIN
            SELECT state, next_attempt_time, failure_threshold, failure_count
            INTO breaker_state
            FROM dlq_circuit_breaker_state
            WHERE breaker_name = check_circuit_breaker.breaker_name;
            
            -- Create breaker if it doesn't exist
            IF NOT FOUND THEN
                INSERT INTO dlq_circuit_breaker_state (breaker_name, state, failure_threshold)
                VALUES (breaker_name, 'closed', 5);
                RETURN TRUE;
            END IF;
            
            -- Check if breaker is open and timeout has passed
            IF breaker_state.state = 'open' AND 
               (breaker_state.next_attempt_time IS NULL OR NOW() > breaker_state.next_attempt_time) THEN
                -- Move to half-open
                UPDATE dlq_circuit_breaker_state 
                SET state = 'half_open', next_attempt_time = NULL
                WHERE breaker_name = check_circuit_breaker.breaker_name;
                RETURN TRUE;
            END IF;
            
            -- Allow if closed or half-open
            RETURN breaker_state.state IN ('closed', 'half_open');
        END;
        $$;
        """)
        )

        connection.execute(
            text("""
        CREATE OR REPLACE FUNCTION record_circuit_breaker_success(breaker_name TEXT)
        RETURNS VOID
        LANGUAGE plpgsql
        AS $$
        BEGIN
            UPDATE dlq_circuit_breaker_state 
            SET state = 'closed', failure_count = 0, last_failure_time = NULL, next_attempt_time = NULL
            WHERE breaker_name = record_circuit_breaker_success.breaker_name;
        END;
        $$;
        """)
        )

        connection.execute(
            text("""
        CREATE OR REPLACE FUNCTION record_circuit_breaker_failure(breaker_name TEXT)
        RETURNS VOID
        LANGUAGE plpgsql
        AS $$
        DECLARE
            current_failures INTEGER;
            threshold INTEGER;
        BEGIN
            UPDATE dlq_circuit_breaker_state 
            SET failure_count = failure_count + 1, last_failure_time = NOW()
            WHERE breaker_name = record_circuit_breaker_failure.breaker_name
            RETURNING failure_count, failure_threshold INTO current_failures, threshold;
            
            -- Open circuit if threshold exceeded
            IF current_failures >= threshold THEN
                UPDATE dlq_circuit_breaker_state 
                SET state = 'open', next_attempt_time = NOW() + INTERVAL '60 seconds'
                WHERE breaker_name = record_circuit_breaker_failure.breaker_name;
            END IF;
        END;
        $$;
        """)
        )

        # 3. Enhanced JSON repair function
        connection.execute(
            text("""
        CREATE OR REPLACE FUNCTION repair_cowrie_json_enhanced(
            malformed_content TEXT, 
            dlq_event_id INTEGER
        )
        RETURNS JSONB
        LANGUAGE plpgsql
        AS $$
        DECLARE
            repaired_content TEXT;
            result JSONB;
            repair_attempts INTEGER := 0;
            max_attempts INTEGER := 3;
        BEGIN
            repaired_content := malformed_content;
            
            -- Attempt multiple repair strategies
            WHILE repair_attempts < max_attempts LOOP
                repair_attempts := repair_attempts + 1;
                
                -- Strategy 1: Basic JSON fixes
                repaired_content := regexp_replace(repaired_content, ',(\\s*[}\\]])', '\\1', 'g');
                
                -- Strategy 2: Add missing braces
                IF repaired_content !~ '^\\s*\\{' THEN
                    repaired_content := '{' || repaired_content;
                END IF;
                IF repaired_content !~ '}\\s*$' THEN
                    repaired_content := repaired_content || '}';
                END IF;
                
                -- Strategy 3: Fix incomplete arrays
                repaired_content := regexp_replace(repaired_content, '\\[([^]]*)$', '[\\1]', 'g');
                
                -- Strategy 4: Cowrie-specific patterns
                IF repaired_content ~ '^],' THEN
                    IF repaired_content ~ '"eventid"' THEN
                        repaired_content := '{' || repaired_content || '}';
                    ELSE
                        repaired_content := reconstruct_cowrie_client_event(repaired_content);
                    END IF;
                END IF;
                
                -- Try to parse as JSON
                BEGIN
                    result := repaired_content::JSONB;
                    
                    -- Validate required Cowrie fields
                    IF result ? 'eventid' AND result ? 'timestamp' THEN
                        -- Record successful repair
                        PERFORM record_repair_success(dlq_event_id, repair_attempts, repaired_content);
                        RETURN result;
                    END IF;
                EXCEPTION WHEN OTHERS THEN
                    -- Continue to next repair attempt
                    NULL;
                END;
            END LOOP;
            
            -- If all attempts failed, create minimal event
            result := create_minimal_cowrie_event_enhanced(malformed_content);
            PERFORM record_repair_failure(dlq_event_id, repair_attempts, malformed_content);
            
            RETURN result;
        END;
        $$;
        """)
        )

        # 4. Enhanced UPSERT function with idempotency
        connection.execute(
            text("""
        CREATE OR REPLACE FUNCTION upsert_repaired_event_enhanced(
            p_source TEXT,
            p_source_offset BIGINT,
            p_source_inode TEXT,
            p_payload JSONB,
            p_idempotency_key TEXT
        )
        RETURNS BOOLEAN
        LANGUAGE plpgsql
        AS $$
        DECLARE
            success BOOLEAN := FALSE;
            payload_checksum TEXT;
        BEGIN
            -- Calculate payload checksum
            payload_checksum := encode(digest(p_payload::TEXT, 'sha256'), 'hex');
            
            INSERT INTO raw_events (
                ingest_id, source, source_offset, source_inode, source_generation,
                payload, payload_hash, risk_score, quarantined,
                session_id, event_type, event_timestamp, ingest_at
            ) VALUES (
                gen_random_uuid()::TEXT, p_source, p_source_offset, p_source_inode, 0,
                p_payload, payload_checksum, 50, FALSE,
                p_payload->>'session', p_payload->>'eventid', p_payload->>'timestamp', NOW()
            )
            ON CONFLICT (source, source_inode, source_generation, source_offset)
            DO UPDATE SET
                payload = EXCLUDED.payload,
                payload_hash = EXCLUDED.payload_hash,
                risk_score = EXCLUDED.risk_score,
                quarantined = EXCLUDED.quarantined,
                session_id = EXCLUDED.session_id,
                event_type = EXCLUDED.event_type,
                event_timestamp = EXCLUDED.event_timestamp,
                ingest_at = EXCLUDED.ingest_at;
            
            success := TRUE;
            RETURN success;
            
        EXCEPTION WHEN OTHERS THEN
            RETURN FALSE;
        END;
        $$;
        """)
        )

        # 5. Monitoring and health check functions
        connection.execute(
            text("""
        CREATE OR REPLACE VIEW dlq_health AS
        SELECT 
            COUNT(*) FILTER (WHERE NOT resolved) as pending_events,
            COUNT(*) FILTER (WHERE resolved) as processed_events,
            AVG(EXTRACT(EPOCH FROM (resolved_at - created_at))) as avg_resolution_time_seconds,
            MAX(created_at) FILTER (WHERE NOT resolved) as oldest_unresolved_event,
            COUNT(*) FILTER (WHERE retry_count > 5) as high_retry_events,
            COUNT(*) FILTER (WHERE processing_lock IS NOT NULL AND lock_expires_at > NOW()) as locked_events,
            COUNT(*) FILTER (WHERE classification = 'malicious') as malicious_events,
            COUNT(*) FILTER (WHERE priority <= 3) as high_priority_events
        FROM dead_letter_events;
        """)
        )

        # 6. Automated cleanup function
        connection.execute(
            text("""
        CREATE OR REPLACE FUNCTION cleanup_resolved_dlq_events_enhanced(
            p_older_than_days INTEGER DEFAULT 90,
            p_batch_size INTEGER DEFAULT 1000
        )
        RETURNS INTEGER
        LANGUAGE plpgsql
        AS $$
        DECLARE
            deleted_count INTEGER := 0;
            batch_deleted INTEGER;
            total_deleted INTEGER := 0;
        BEGIN
            LOOP
                DELETE FROM dead_letter_events 
                WHERE resolved = TRUE 
                AND resolved_at < NOW() - INTERVAL '1 day' * p_older_than_days
                AND id IN (
                    SELECT id FROM dead_letter_events 
                    WHERE resolved = TRUE 
                    AND resolved_at < NOW() - INTERVAL '1 day' * p_older_than_days
                    LIMIT p_batch_size
                );
                
                GET DIAGNOSTICS batch_deleted = ROW_COUNT;
                total_deleted := total_deleted + batch_deleted;
                
                -- Break if no more records to delete
                EXIT WHEN batch_deleted = 0;
                
                -- Small delay to prevent blocking
                PERFORM pg_sleep(0.1);
            END LOOP;
            
            RETURN total_deleted;
        END;
        $$;
        """)
        )

        # 7. Helper functions for error recording
        connection.execute(
            text("""
        CREATE OR REPLACE FUNCTION record_dlq_processing_failure(
            p_dlq_id INTEGER,
            p_error_type TEXT,
            p_error_message TEXT,
            p_processing_method TEXT
        )
        RETURNS VOID
        LANGUAGE plpgsql
        AS $$
        BEGIN
            UPDATE dead_letter_events 
            SET error_history = COALESCE(error_history, '[]'::JSONB) || 
                jsonb_build_object(
                    'timestamp', NOW()::TEXT,
                    'error_type', p_error_type,
                    'error_message', p_error_message,
                    'processing_method', p_processing_method,
                    'retry_count', retry_count
                ),
                retry_count = retry_count + 1,
                last_processed_at = NOW()
            WHERE id = p_dlq_id;
        END;
        $$;
        """)
        )

        connection.execute(
            text("""
        CREATE OR REPLACE FUNCTION record_repair_success(
            p_dlq_id INTEGER,
            p_attempts INTEGER,
            p_repaired_content TEXT
        )
        RETURNS VOID
        LANGUAGE plpgsql
        AS $$
        BEGIN
            UPDATE dead_letter_events 
            SET processing_attempts = COALESCE(processing_attempts, '[]'::JSONB) ||
                jsonb_build_object(
                    'timestamp', NOW()::TEXT,
                    'method', 'repair_success',
                    'attempts', p_attempts,
                    'success', TRUE
                )
            WHERE id = p_dlq_id;
        END;
        $$;
        """)
        )

        connection.execute(
            text("""
        CREATE OR REPLACE FUNCTION record_repair_failure(
            p_dlq_id INTEGER,
            p_attempts INTEGER,
            p_original_content TEXT
        )
        RETURNS VOID
        LANGUAGE plpgsql
        AS $$
        BEGIN
            UPDATE dead_letter_events 
            SET processing_attempts = COALESCE(processing_attempts, '[]'::JSONB) ||
                jsonb_build_object(
                    'timestamp', NOW()::TEXT,
                    'method', 'repair_failure',
                    'attempts', p_attempts,
                    'success', FALSE
                )
            WHERE id = p_dlq_id;
        END;
        $$;
        """)
        )

    @staticmethod
    def process_dlq_events_enhanced(
        connection: Connection,
        limit: Optional[int] = None,
        reason_filter: Optional[str] = None,
        priority_filter: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process DLQ events using enhanced stored procedure."""
        result = connection.execute(
            text("""
            SELECT * FROM process_dlq_events_enhanced(
                :limit, :reason_filter, :priority_filter, :session_id, 'dlq_main'
            )
        """),
            {
                "limit": limit,
                "reason_filter": reason_filter,
                "priority_filter": priority_filter,
                "session_id": session_id or str(uuid.uuid4()),
            },
        ).fetchone()

        return {
            "processed": result[0],
            "repaired": result[1],
            "failed": result[2],
            "skipped": result[3],
            "circuit_breaker_triggered": result[4],
            "processing_duration_ms": result[5],
        }

    @staticmethod
    def get_dlq_health_stats(connection: Connection) -> Dict[str, Any]:
        """Get DLQ health statistics."""
        result = connection.execute(text("SELECT * FROM dlq_health")).fetchone()

        return {
            "pending_events": result[0],
            "processed_events": result[1],
            "avg_resolution_time_seconds": float(result[2]) if result[2] else 0,
            "oldest_unresolved_event": result[3],
            "high_retry_events": result[4],
            "locked_events": result[5],
            "malicious_events": result[6],
            "high_priority_events": result[7],
        }

    @staticmethod
    def cleanup_resolved_events_enhanced(
        connection: Connection, older_than_days: int = 90, batch_size: int = 1000
    ) -> int:
        """Cleanup resolved DLQ events with enhanced batching."""
        result = connection.execute(
            text("""
            SELECT cleanup_resolved_dlq_events_enhanced(:older_than_days, :batch_size)
        """),
            {"older_than_days": older_than_days, "batch_size": batch_size},
        ).fetchone()

        return result[0]
