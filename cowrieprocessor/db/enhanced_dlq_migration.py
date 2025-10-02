"""Database migration for enhanced DLQ models.

This migration adds security, audit, and operational enhancements to the DLQ system.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection


def upgrade_to_enhanced_dlq(connection: Connection) -> None:
    """Upgrade DLQ tables with enhanced features."""
    # Check if we're using PostgreSQL
    dialect_name = connection.dialect.name
    if dialect_name != 'postgresql':
        print(f"Skipping enhanced DLQ migration for {dialect_name} - PostgreSQL only")
        return

    print("Upgrading to enhanced DLQ models...")

    # 1. Add new columns to dead_letter_events table
    connection.execute(
        text("""
        ALTER TABLE dead_letter_events 
        ADD COLUMN IF NOT EXISTS payload_checksum VARCHAR(64),
        ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0,
        ADD COLUMN IF NOT EXISTS error_history JSONB,
        ADD COLUMN IF NOT EXISTS processing_attempts JSONB,
        ADD COLUMN IF NOT EXISTS resolution_method VARCHAR(64),
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128),
        ADD COLUMN IF NOT EXISTS processing_lock UUID,
        ADD COLUMN IF NOT EXISTS lock_expires_at TIMESTAMP WITH TIME ZONE,
        ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 5,
        ADD COLUMN IF NOT EXISTS classification VARCHAR(32),
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        ADD COLUMN IF NOT EXISTS last_processed_at TIMESTAMP WITH TIME ZONE;
    """)
    )

    # 2. Create indexes for new columns
    connection.execute(
        text("""
        CREATE INDEX IF NOT EXISTS ix_dead_letter_events_payload_checksum 
        ON dead_letter_events (payload_checksum);
        
        CREATE INDEX IF NOT EXISTS ix_dead_letter_events_retry_count 
        ON dead_letter_events (retry_count);
        
        CREATE INDEX IF NOT EXISTS ix_dead_letter_events_idempotency_key 
        ON dead_letter_events (idempotency_key);
        
        CREATE INDEX IF NOT EXISTS ix_dead_letter_events_processing_lock 
        ON dead_letter_events (processing_lock);
        
        CREATE INDEX IF NOT EXISTS ix_dead_letter_events_lock_expires 
        ON dead_letter_events (lock_expires_at);
        
        CREATE INDEX IF NOT EXISTS ix_dead_letter_events_classification 
        ON dead_letter_events (classification);
        
        CREATE INDEX IF NOT EXISTS ix_dead_letter_events_resolved_created 
        ON dead_letter_events (resolved, created_at);
        
        CREATE INDEX IF NOT EXISTS ix_dead_letter_events_priority_resolved 
        ON dead_letter_events (priority, resolved);
    """)
    )

    # 3. Add constraints
    connection.execute(
        text("""
        ALTER TABLE dead_letter_events 
        ADD CONSTRAINT IF NOT EXISTS ck_retry_count_positive 
        CHECK (retry_count >= 0);
        
        ALTER TABLE dead_letter_events 
        ADD CONSTRAINT IF NOT EXISTS ck_priority_range 
        CHECK (priority BETWEEN 1 AND 10);
        
        ALTER TABLE dead_letter_events 
        ADD CONSTRAINT IF NOT EXISTS uq_idempotency_key 
        UNIQUE (idempotency_key);
    """)
    )

    # 4. Create processing metrics table
    connection.execute(
        text("""
        CREATE TABLE IF NOT EXISTS dlq_processing_metrics (
            id SERIAL PRIMARY KEY,
            processing_session_id VARCHAR(64) NOT NULL,
            processing_method VARCHAR(32) NOT NULL,
            batch_size INTEGER NOT NULL,
            processed_count INTEGER NOT NULL,
            repaired_count INTEGER NOT NULL,
            failed_count INTEGER NOT NULL,
            skipped_count INTEGER NOT NULL,
            processing_duration_ms INTEGER NOT NULL,
            avg_processing_time_ms INTEGER,
            peak_memory_mb INTEGER,
            circuit_breaker_triggered BOOLEAN NOT NULL DEFAULT FALSE,
            rate_limit_hits INTEGER NOT NULL DEFAULT 0,
            lock_timeout_count INTEGER NOT NULL DEFAULT 0,
            started_at TIMESTAMP WITH TIME ZONE NOT NULL,
            completed_at TIMESTAMP WITH TIME ZONE NOT NULL
        );
    """)
    )

    # 5. Create indexes for metrics table
    connection.execute(
        text("""
        CREATE INDEX IF NOT EXISTS ix_dlq_metrics_session 
        ON dlq_processing_metrics (processing_session_id);
        
        CREATE INDEX IF NOT EXISTS ix_dlq_metrics_method 
        ON dlq_processing_metrics (processing_method);
        
        CREATE INDEX IF NOT EXISTS ix_dlq_metrics_started 
        ON dlq_processing_metrics (started_at);
    """)
    )

    # 6. Create circuit breaker state table
    connection.execute(
        text("""
        CREATE TABLE IF NOT EXISTS dlq_circuit_breaker_state (
            id SERIAL PRIMARY KEY,
            breaker_name VARCHAR(64) NOT NULL UNIQUE,
            state VARCHAR(16) NOT NULL,
            failure_count INTEGER NOT NULL DEFAULT 0,
            last_failure_time TIMESTAMP WITH TIME ZONE,
            next_attempt_time TIMESTAMP WITH TIME ZONE,
            failure_threshold INTEGER NOT NULL DEFAULT 5,
            timeout_seconds INTEGER NOT NULL DEFAULT 60,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        );
    """)
    )

    # 7. Create indexes for circuit breaker table
    connection.execute(
        text("""
        CREATE INDEX IF NOT EXISTS ix_circuit_breaker_state 
        ON dlq_circuit_breaker_state (state);
        
        CREATE INDEX IF NOT EXISTS ix_circuit_breaker_next_attempt 
        ON dlq_circuit_breaker_state (next_attempt_time);
    """)
    )

    # 8. Create health monitoring view
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

    # 9. Create function to update updated_at timestamp
    connection.execute(
        text("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)
    )

    # 10. Create trigger for updated_at
    connection.execute(
        text("""
        DROP TRIGGER IF EXISTS update_dead_letter_events_updated_at ON dead_letter_events;
        CREATE TRIGGER update_dead_letter_events_updated_at
            BEFORE UPDATE ON dead_letter_events
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    """)
    )

    # 11. Create trigger for circuit breaker updated_at
    connection.execute(
        text("""
        DROP TRIGGER IF EXISTS update_circuit_breaker_updated_at ON dlq_circuit_breaker_state;
        CREATE TRIGGER update_circuit_breaker_updated_at
            BEFORE UPDATE ON dlq_circuit_breaker_state
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    """)
    )

    # 12. Populate checksums for existing records
    connection.execute(
        text("""
        UPDATE dead_letter_events 
        SET payload_checksum = encode(digest(payload::TEXT, 'sha256'), 'hex')
        WHERE payload_checksum IS NULL;
    """)
    )

    # 13. Generate idempotency keys for existing records
    connection.execute(
        text("""
        UPDATE dead_letter_events 
        SET idempotency_key = encode(digest(
            COALESCE(source, '') || ':' || 
            COALESCE(source_offset::TEXT, '') || ':' || 
            COALESCE(payload_checksum, ''), 'sha256'
        ), 'hex')
        WHERE idempotency_key IS NULL;
    """)
    )

    print("✅ Enhanced DLQ migration completed successfully")


def downgrade_from_enhanced_dlq(connection: Connection) -> None:
    """Downgrade from enhanced DLQ models."""
    dialect_name = connection.dialect.name
    if dialect_name != 'postgresql':
        print(f"Skipping enhanced DLQ downgrade for {dialect_name} - PostgreSQL only")
        return

    print("Downgrading from enhanced DLQ models...")

    # Drop views
    connection.execute(text("DROP VIEW IF EXISTS dlq_health;"))

    # Drop triggers
    connection.execute(text("DROP TRIGGER IF EXISTS update_dead_letter_events_updated_at ON dead_letter_events;"))
    connection.execute(text("DROP TRIGGER IF EXISTS update_circuit_breaker_updated_at ON dlq_circuit_breaker_state;"))

    # Drop functions
    connection.execute(text("DROP FUNCTION IF EXISTS update_updated_at_column();"))

    # Drop tables
    connection.execute(text("DROP TABLE IF EXISTS dlq_circuit_breaker_state;"))
    connection.execute(text("DROP TABLE IF EXISTS dlq_processing_metrics;"))

    # Drop indexes
    connection.execute(text("DROP INDEX IF EXISTS ix_dead_letter_events_payload_checksum;"))
    connection.execute(text("DROP INDEX IF EXISTS ix_dead_letter_events_retry_count;"))
    connection.execute(text("DROP INDEX IF EXISTS ix_dead_letter_events_idempotency_key;"))
    connection.execute(text("DROP INDEX IF EXISTS ix_dead_letter_events_processing_lock;"))
    connection.execute(text("DROP INDEX IF EXISTS ix_dead_letter_events_lock_expires;"))
    connection.execute(text("DROP INDEX IF EXISTS ix_dead_letter_events_classification;"))
    connection.execute(text("DROP INDEX IF EXISTS ix_dead_letter_events_resolved_created;"))
    connection.execute(text("DROP INDEX IF EXISTS ix_dead_letter_events_priority_resolved;"))

    # Drop constraints
    connection.execute(text("ALTER TABLE dead_letter_events DROP CONSTRAINT IF EXISTS ck_retry_count_positive;"))
    connection.execute(text("ALTER TABLE dead_letter_events DROP CONSTRAINT IF EXISTS ck_priority_range;"))
    connection.execute(text("ALTER TABLE dead_letter_events DROP CONSTRAINT IF EXISTS uq_idempotency_key;"))

    # Drop columns
    connection.execute(
        text("""
        ALTER TABLE dead_letter_events 
        DROP COLUMN IF EXISTS payload_checksum,
        DROP COLUMN IF EXISTS retry_count,
        DROP COLUMN IF EXISTS error_history,
        DROP COLUMN IF EXISTS processing_attempts,
        DROP COLUMN IF EXISTS resolution_method,
        DROP COLUMN IF EXISTS idempotency_key,
        DROP COLUMN IF EXISTS processing_lock,
        DROP COLUMN IF EXISTS lock_expires_at,
        DROP COLUMN IF EXISTS priority,
        DROP COLUMN IF EXISTS classification,
        DROP COLUMN IF EXISTS updated_at,
        DROP COLUMN IF EXISTS last_processed_at;
    """)
    )

    print("✅ Enhanced DLQ downgrade completed successfully")
