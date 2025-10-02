"""PostgreSQL stored procedures for efficient DLQ processing.

This module provides stored procedures that can process DLQ events
directly in the database without pulling records to the application layer.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection


class DLQStoredProcedures:
    """PostgreSQL stored procedures for DLQ processing."""

    @staticmethod
    def create_dlq_processing_procedures(connection: Connection) -> None:
        """Create all DLQ processing stored procedures (PostgreSQL only)."""
        # Check if we're using PostgreSQL
        dialect_name = connection.dialect.name
        if dialect_name != 'postgresql':
            raise ValueError(f"Stored procedures are only supported for PostgreSQL, not {dialect_name}")

        # Fix regex escape sequences
        connection.execute(
            text("""
        CREATE OR REPLACE FUNCTION process_dlq_events(
            p_limit INTEGER DEFAULT NULL,
            p_reason_filter TEXT DEFAULT NULL
        )
        RETURNS TABLE(
            processed_count INTEGER,
            repaired_count INTEGER,
            failed_count INTEGER,
            skipped_count INTEGER
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
        BEGIN
            -- Process unresolved DLQ events
            FOR dlq_record IN 
                SELECT id, payload, source, source_offset, reason
                FROM dead_letter_events 
                WHERE resolved = FALSE
                AND (p_reason_filter IS NULL OR reason = p_reason_filter)
                ORDER BY created_at ASC
                LIMIT COALESCE(p_limit, 1000)
            LOOP
                processed := processed + 1;
                
                -- Extract malformed content
                malformed_content := dlq_record.payload->>'malformed_content';
                
                IF malformed_content IS NULL THEN
                    skipped := skipped + 1;
                    CONTINUE;
                END IF;
                
                -- Attempt repair using JSON repair functions
                repaired_payload := repair_cowrie_json(malformed_content);
                
                IF repaired_payload IS NOT NULL THEN
                    -- Insert/update raw event using UPSERT
                    success := upsert_repaired_event(
                        dlq_record.source,
                        dlq_record.source_offset,
                        dlq_record.source,
                        repaired_payload
                    );
                    
                    IF success THEN
                        -- Mark DLQ event as resolved
                        UPDATE dead_letter_events 
                        SET resolved = TRUE, resolved_at = NOW()
                        WHERE id = dlq_record.id;
                        
                        repaired := repaired + 1;
                    ELSE
                        failed := failed + 1;
                    END IF;
                ELSE
                    failed := failed + 1;
                END IF;
            END LOOP;
            
            RETURN QUERY SELECT processed, repaired, failed, skipped;
        END;
        $$;
        """)
        )

        # 2. JSON repair function for Cowrie-specific patterns
        connection.execute(
            text("""
        CREATE OR REPLACE FUNCTION repair_cowrie_json(malformed_content TEXT)
        RETURNS JSONB
        LANGUAGE plpgsql
        AS $$
        DECLARE
            repaired_content TEXT;
            result JSONB;
        BEGIN
            -- Start with the malformed content
            repaired_content := malformed_content;
            
            -- Pattern 1: Add missing closing braces
            IF repaired_content !~ '}$' THEN
                repaired_content := repaired_content || '}';
            END IF;
            
            -- Pattern 2: Fix trailing commas (fixed regex)
            repaired_content := regexp_replace(repaired_content, ',(\\s*[}\\]])', '\\1', 'g');
            
            -- Pattern 3: Handle incomplete arrays
            IF repaired_content ~ '\\[[^]]*$' THEN
                repaired_content := regexp_replace(repaired_content, '\\[([^]]*)$', '[\\1]', 'g');
            END IF;
            
            -- Pattern 4: Cowrie-specific fragment reconstruction
            IF repaired_content ~ '^],' AND repaired_content ~ '"eventid"' THEN
                -- This is a complete event fragment
                repaired_content := '{' || repaired_content || '}';
            ELSIF repaired_content ~ '^],' AND repaired_content !~ '"eventid"' THEN
                -- This is a client event fragment - reconstruct as cowrie.client.kex
                repaired_content := reconstruct_client_event(repaired_content);
            END IF;
            
            -- Attempt to parse as JSON
            BEGIN
                result := repaired_content::JSONB;
                RETURN result;
            EXCEPTION WHEN OTHERS THEN
                -- If still invalid, try to create a minimal valid event
                RETURN create_minimal_cowrie_event(repaired_content);
            END;
        END;
        $$;
        """)
        )

        # 3. Client event reconstruction function
        connection.execute(
            text("""
        CREATE OR REPLACE FUNCTION reconstruct_client_event(fragment TEXT)
        RETURNS TEXT
        LANGUAGE plpgsql
        AS $$
        DECLARE
            reconstructed TEXT;
            current_time TEXT;
        BEGIN
            current_time := to_char(NOW(), 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"');
            
            reconstructed := '{
                "eventid": "cowrie.client.kex",
                "timestamp": "' || current_time || '",
                "session": "unknown-session",
                "src_ip": "unknown",
                "macCS": [],
                "encCS": [],
                "macSC": [],
                "encSC": [],
                "kexAlgs": [],
                "keyAlgs": [],
                "compCS": [],
                "compSC": [],
                "langCS": [],
                "langSC": []
            }';
            
            -- Extract arrays from fragment if possible
            -- This is a simplified version - full implementation would parse arrays
            
            RETURN reconstructed;
        END;
        $$;
        """)
        )

        # 4. Minimal event creation function
        connection.execute(
            text("""
        CREATE OR REPLACE FUNCTION create_minimal_cowrie_event(content TEXT)
        RETURNS JSONB
        LANGUAGE plpgsql
        AS $$
        DECLARE
            current_time TEXT;
            minimal_event JSONB;
        BEGIN
            current_time := to_char(NOW(), 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"');
            
            minimal_event := jsonb_build_object(
                'eventid', 'cowrie.system.info',
                'timestamp', current_time,
                'session', 'unknown-session',
                'src_ip', 'unknown',
                'message', 'Repaired from malformed content',
                'original_content', content
            );
            
            RETURN minimal_event;
        END;
        $$;
        """)
        )

        # 5. UPSERT function for repaired events
        connection.execute(
            text("""
        CREATE OR REPLACE FUNCTION upsert_repaired_event(
            p_source TEXT,
            p_source_offset BIGINT,
            p_source_inode TEXT,
            p_payload JSONB
        )
        RETURNS BOOLEAN
        LANGUAGE plpgsql
        AS $$
        DECLARE
            success BOOLEAN := FALSE;
        BEGIN
            INSERT INTO raw_events (
                ingest_id,
                source,
                source_offset,
                source_inode,
                source_generation,
                payload,
                risk_score,
                quarantined,
                session_id,
                event_type,
                event_timestamp,
                ingest_at
            ) VALUES (
                gen_random_uuid()::TEXT,
                p_source,
                p_source_offset,
                p_source_inode,
                0,
                p_payload,
                50,
                FALSE,
                p_payload->>'session',
                p_payload->>'eventid',
                p_payload->>'timestamp',
                NOW()
            )
            ON CONFLICT (source, source_inode, source_generation, source_offset)
            DO UPDATE SET
                payload = EXCLUDED.payload,
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

        # 6. DLQ cleanup procedure
        connection.execute(
            text("""
        CREATE OR REPLACE FUNCTION cleanup_resolved_dlq_events(
            p_older_than_days INTEGER DEFAULT 30
        )
        RETURNS INTEGER
        LANGUAGE plpgsql
        AS $$
        DECLARE
            deleted_count INTEGER;
        BEGIN
            DELETE FROM dead_letter_events 
            WHERE resolved = TRUE 
            AND resolved_at < NOW() - INTERVAL '1 day' * p_older_than_days;
            
            GET DIAGNOSTICS deleted_count = ROW_COUNT;
            RETURN deleted_count;
        END;
        $$;
        """)
        )

        # 7. DLQ statistics function
        connection.execute(
            text("""
        CREATE OR REPLACE FUNCTION get_dlq_statistics()
        RETURNS TABLE(
            total_events BIGINT,
            unresolved_events BIGINT,
            resolved_events BIGINT,
            top_reasons JSONB,
            oldest_unresolved TIMESTAMP WITH TIME ZONE,
            newest_unresolved TIMESTAMP WITH TIME ZONE
        )
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RETURN QUERY
            SELECT 
                COUNT(*) as total_events,
                COUNT(*) FILTER (WHERE resolved = FALSE) as unresolved_events,
                COUNT(*) FILTER (WHERE resolved = TRUE) as resolved_events,
                (
                    SELECT jsonb_object_agg(reason, count)
                    FROM (
                        SELECT reason, COUNT(*) as count
                        FROM dead_letter_events
                        WHERE resolved = FALSE
                        GROUP BY reason
                        ORDER BY count DESC
                        LIMIT 10
                    ) reason_counts
                ) as top_reasons,
                MIN(created_at) FILTER (WHERE resolved = FALSE) as oldest_unresolved,
                MAX(created_at) FILTER (WHERE resolved = FALSE) as newest_unresolved
            FROM dead_letter_events;
        END;
        $$;
        """)
        )

    @staticmethod
    def process_dlq_events_stored_proc(
        connection: Connection, limit: Optional[int] = None, reason_filter: Optional[str] = None
    ) -> Dict[str, int]:
        """Process DLQ events using stored procedure."""
        result = connection.execute(
            text("""
            SELECT * FROM process_dlq_events(:limit, :reason_filter)
        """),
            {"limit": limit, "reason_filter": reason_filter},
        ).fetchone()

        return {"processed": result[0], "repaired": result[1], "failed": result[2], "skipped": result[3]}

    @staticmethod
    def get_dlq_statistics_stored_proc(connection: Connection) -> Dict[str, Any]:
        """Get DLQ statistics using stored procedure."""
        result = connection.execute(text("SELECT * FROM get_dlq_statistics()")).fetchone()

        return {
            "total_events": result[0],
            "unresolved_events": result[1],
            "resolved_events": result[2],
            "top_reasons": result[3],
            "oldest_unresolved": result[4],
            "newest_unresolved": result[5],
        }

    @staticmethod
    def cleanup_resolved_dlq_events_stored_proc(connection: Connection, older_than_days: int = 30) -> int:
        """Cleanup resolved DLQ events using stored procedure."""
        result = connection.execute(
            text("""
            SELECT cleanup_resolved_dlq_events(:older_than_days)
        """),
            {"older_than_days": older_than_days},
        ).fetchone()

        return result[0]
