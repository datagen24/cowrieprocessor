"""Schema migration helpers for the Cowrie processor database."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator, cast

from sqlalchemy import Table, inspect, select, text, update
from sqlalchemy.engine import Connection, Engine

from .base import Base
from .models import SchemaState

SCHEMA_VERSION_KEY = "schema_version"
CURRENT_SCHEMA_VERSION = 9

logger = logging.getLogger(__name__)


def _safe_execute_sql(connection: Connection, sql: str, description: str = "") -> bool:
    """Safely execute SQL with error handling and logging.

    Args:
        connection: Database connection
        sql: SQL statement to execute
        description: Description for logging

    Returns:
        True if successful, False otherwise
    """
    try:
        connection.execute(text(sql))
        if description:
            logger.info(f"Successfully executed: {description}")
        return True
    except Exception as e:
        logger.error(f"Failed to execute SQL: {description} - {e}")
        # Rollback the transaction to clean state
        try:
            connection.rollback()
        except Exception as rollback_error:
            logger.error(f"Failed to rollback transaction: {rollback_error}")
        return False


def _table_exists(connection: Connection, table_name: str) -> bool:
    """Check if a table exists in the database.

    Args:
        connection: Database connection
        table_name: Name of the table to check

    Returns:
        True if table exists, False otherwise
    """
    inspector = inspect(connection)
    return inspector.has_table(table_name)


def _column_exists(connection: Connection, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table.

    Args:
        connection: Database connection
        table_name: Name of the table
        column_name: Name of the column

    Returns:
        True if column exists, False otherwise
    """
    if not _table_exists(connection, table_name):
        return False

    inspector = inspect(connection)
    columns = {col["name"] for col in inspector.get_columns(table_name)}
    return column_name in columns


def _is_generated_column(connection: Connection, table_name: str, column_name: str) -> bool:
    """Check if a column is a generated column in SQLite.

    Args:
        connection: Database connection
        table_name: Name of the table
        column_name: Name of the column

    Returns:
        True if column is generated, False otherwise
    """
    if connection.dialect.name != "sqlite":
        return False

    try:
        # Use PRAGMA table_xinfo to get detailed column information
        result = connection.execute(text(f"PRAGMA table_xinfo({table_name})")).fetchall()

        for row in result:
            if row[1] == column_name:  # Column name is in position 1
                # In SQLite, generated columns have a non-null "hidden" value (position 5)
                # Position 5 is "hidden" - 0 for regular columns, > 0 for generated columns
                return row[5] > 0  # hidden column indicates generated column

        return False
    except Exception:
        # If we can't determine, assume it's not generated
        return False


@contextmanager
def begin_connection(engine: Engine) -> Iterator[Connection]:
    """Context manager that yields a transactional connection."""
    with engine.begin() as connection:
        yield connection


def _get_schema_version(connection: Connection) -> int:
    result = connection.execute(
        select(SchemaState.value).where(SchemaState.key == SCHEMA_VERSION_KEY)
    ).scalar_one_or_none()
    if result is None:
        return 0
    try:
        return int(result)
    except (TypeError, ValueError):
        return 0


def _set_schema_version(connection: Connection, version: int) -> None:
    stmt = update(SchemaState).where(SchemaState.key == SCHEMA_VERSION_KEY).values(value=str(version))
    result = connection.execute(stmt)
    if result.rowcount == 0:
        schema_table = cast(Table, SchemaState.__table__)
        insert_stmt = schema_table.insert().values(key=SCHEMA_VERSION_KEY, value=str(version))
        connection.execute(insert_stmt)


def apply_migrations(engine: Engine) -> int:
    """Create or upgrade database schema and return the resulting version."""
    version = 0
    with begin_connection(engine) as connection:
        Base.metadata.create_all(bind=connection)
        version = _get_schema_version(connection)

        if version < 1:
            _set_schema_version(connection, 1)
            version = 1

        if version < 2:
            _upgrade_to_v2(connection)
            _set_schema_version(connection, 2)
            version = 2

        if version < 3:
            _upgrade_to_v3(connection)
            _set_schema_version(connection, 3)
            version = 3

        if version < 4:
            _upgrade_to_v4(connection)
            _set_schema_version(connection, 4)
            version = 4

        if version < 5:
            _upgrade_to_v5(connection)
            _set_schema_version(connection, 5)
            version = 5

        if version < 6:
            _upgrade_to_v6(connection)
            _set_schema_version(connection, 6)
            version = 6

        if version < 7:
            _upgrade_to_v7(connection)
            _set_schema_version(connection, 7)
            version = 7

        if version < 8:
            _upgrade_to_v8(connection)
            _set_schema_version(connection, 8)
            version = 8

        if version < 9:
            _upgrade_to_v9(connection)
            _set_schema_version(connection, 9)
            version = 9

    return version


def _upgrade_to_v2(connection: Connection) -> None:
    """Upgrade to v2 schema by adding source_generation column and unique index."""
    if not _column_exists(connection, "raw_events", "source_generation"):
        _safe_execute_sql(
            connection,
            "ALTER TABLE raw_events ADD COLUMN source_generation INTEGER NOT NULL DEFAULT 0",
            "Add source_generation column",
        )

    _safe_execute_sql(
        connection,
        "UPDATE raw_events SET source_generation=0 WHERE source_generation IS NULL",
        "Set default source_generation values",
    )

    _safe_execute_sql(
        connection,
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_events_source_gen "
        "ON raw_events(source, source_inode, source_generation, source_offset)",
        "Create unique index on raw_events",
    )


def _upgrade_to_v3(connection: Connection) -> None:
    """Upgrade to v3 schema by adding enrichment column to session_summaries."""
    if _column_exists(connection, "session_summaries", "enrichment"):
        return  # Already exists

    dialect_name = connection.dialect.name
    if dialect_name == "postgresql":
        column_type = "JSONB"
    else:
        column_type = "JSON"

    _safe_execute_sql(
        connection,
        f"ALTER TABLE session_summaries ADD COLUMN enrichment {column_type}",
        f"Add enrichment column ({column_type})",
    )


def _upgrade_to_v4(connection: Connection) -> None:
    """Upgrade to v4 schema by creating the files table."""
    if _table_exists(connection, "files"):
        return  # Already exists

    # Create the files table using SQLAlchemy's create_all
    # This will create the table with all the proper constraints and indexes
    from .models import Files

    try:
        Files.__table__.create(connection, checkfirst=True)
        logger.info("Successfully created files table")
    except Exception as e:
        logger.warning(f"Failed to create files table: {e}")


def _upgrade_to_v6(connection: Connection) -> None:
    """Upgrade to schema version 6: Fix boolean defaults from string to proper boolean."""
    dialect_name = connection.dialect.name

    # Define boolean columns to update
    boolean_updates = [
        ("raw_events", "quarantined"),
        ("session_summaries", "vt_flagged"),
        ("session_summaries", "dshield_flagged"),
        ("command_stats", "high_risk"),
        ("dead_letter_events", "resolved"),
        ("files", "vt_malicious"),
    ]

    for table_name, column_name in boolean_updates:
        if not _table_exists(connection, table_name):
            logger.info(f"Table {table_name} does not exist, skipping boolean default update")
            continue

        if not _column_exists(connection, table_name, column_name):
            logger.info(f"Column {table_name}.{column_name} does not exist, skipping")
            continue

        if dialect_name == "postgresql":
            # PostgreSQL: Update boolean columns to use proper boolean defaults
            _safe_execute_sql(
                connection,
                f"ALTER TABLE {table_name} ALTER COLUMN {column_name} SET DEFAULT false",
                f"Update {table_name}.{column_name} default to false (PostgreSQL)",
            )
        else:
            # SQLite: Update boolean columns to use proper boolean defaults
            # SQLite doesn't support ALTER COLUMN SET DEFAULT, so we need to recreate the table
            # This is a complex operation, so we'll just log a warning for now
            # In practice, the new schema will be created with proper defaults
            logger.info(f"SQLite boolean defaults for {table_name}.{column_name} will be set on next schema creation")


def _upgrade_to_v5(connection: Connection) -> None:
    """Upgrade to v5 schema by adding real columns for extracted JSON fields.

    This migration replaces SQLite-specific computed columns with real columns
    that work across both SQLite and PostgreSQL backends.
    """
    dialect_name = connection.dialect.name

    # Check if columns are already generated columns (SQLite-specific)
    session_id_generated = _is_generated_column(connection, "raw_events", "session_id")
    event_type_generated = _is_generated_column(connection, "raw_events", "event_type")
    event_timestamp_generated = _is_generated_column(connection, "raw_events", "event_timestamp")

    # Add real columns for extracted JSON fields if they don't exist and aren't generated
    if not _column_exists(connection, "raw_events", "session_id") and not session_id_generated:
        _safe_execute_sql(
            connection, "ALTER TABLE raw_events ADD COLUMN session_id VARCHAR(64)", "Add session_id column"
        )
        _safe_execute_sql(
            connection, "CREATE INDEX ix_raw_events_session_id ON raw_events(session_id)", "Create session_id index"
        )

    if not _column_exists(connection, "raw_events", "event_type") and not event_type_generated:
        _safe_execute_sql(
            connection, "ALTER TABLE raw_events ADD COLUMN event_type VARCHAR(128)", "Add event_type column"
        )
        _safe_execute_sql(
            connection, "CREATE INDEX ix_raw_events_event_type ON raw_events(event_type)", "Create event_type index"
        )

    if not _column_exists(connection, "raw_events", "event_timestamp") and not event_timestamp_generated:
        _safe_execute_sql(
            connection, "ALTER TABLE raw_events ADD COLUMN event_timestamp VARCHAR(64)", "Add event_timestamp column"
        )
        _safe_execute_sql(
            connection,
            "CREATE INDEX ix_raw_events_event_timestamp ON raw_events(event_timestamp)",
            "Create event_timestamp index",
        )

    # Populate the new columns with data extracted from JSON payload
    # Only populate if columns are not generated (generated columns are auto-computed)
    if not session_id_generated and _column_exists(connection, "raw_events", "session_id"):
        if dialect_name == "postgresql":
            # PostgreSQL JSON extraction
            _safe_execute_sql(
                connection,
                "UPDATE raw_events SET session_id = payload->>'session' WHERE session_id IS NULL",
                "Populate session_id from JSON (PostgreSQL)",
            )
        else:
            # SQLite JSON extraction
            _safe_execute_sql(
                connection,
                "UPDATE raw_events SET session_id = json_extract(payload, '$.session') WHERE session_id IS NULL",
                "Populate session_id from JSON (SQLite)",
            )

    if not event_type_generated and _column_exists(connection, "raw_events", "event_type"):
        if dialect_name == "postgresql":
            _safe_execute_sql(
                connection,
                "UPDATE raw_events SET event_type = payload->>'eventid' WHERE event_type IS NULL",
                "Populate event_type from JSON (PostgreSQL)",
            )
        else:
            _safe_execute_sql(
                connection,
                "UPDATE raw_events SET event_type = json_extract(payload, '$.eventid') WHERE event_type IS NULL",
                "Populate event_type from JSON (SQLite)",
            )

    if not event_timestamp_generated and _column_exists(connection, "raw_events", "event_timestamp"):
        if dialect_name == "postgresql":
            _safe_execute_sql(
                connection,
                "UPDATE raw_events SET event_timestamp = payload->>'timestamp' WHERE event_timestamp IS NULL",
                "Populate event_timestamp from JSON (PostgreSQL)",
            )
        else:
            _safe_execute_sql(
                connection,
                "UPDATE raw_events SET event_timestamp = "
                "json_extract(payload, '$.timestamp') WHERE event_timestamp IS NULL",
                "Populate event_timestamp from JSON (SQLite)",
            )


def _upgrade_to_v7(connection: Connection) -> None:
    """Upgrade to v7 schema: Enhanced DLQ processing with security and audit features.

    This migration adds comprehensive security, audit, and operational enhancements
    to the Dead Letter Queue processing system for production environments.
    """
    dialect_name = connection.dialect.name

    # Only apply enhanced DLQ features for PostgreSQL
    if dialect_name != "postgresql":
        logger.info("Enhanced DLQ features (v7) are PostgreSQL-only, skipping for SQLite")
        return

    logger.info("Applying enhanced DLQ schema migration (v7)...")

    # 1. Add new columns to dead_letter_events table
    enhanced_columns = [
        ("payload_checksum", "VARCHAR(64)"),
        ("retry_count", "INTEGER NOT NULL DEFAULT 0"),
        ("error_history", "JSONB"),
        ("processing_attempts", "JSONB"),
        ("resolution_method", "VARCHAR(64)"),
        ("idempotency_key", "VARCHAR(128)"),
        ("processing_lock", "UUID"),
        ("lock_expires_at", "TIMESTAMP WITH TIME ZONE"),
        ("priority", "INTEGER NOT NULL DEFAULT 5"),
        ("classification", "VARCHAR(32)"),
        ("updated_at", "TIMESTAMP WITH TIME ZONE DEFAULT NOW()"),
        ("last_processed_at", "TIMESTAMP WITH TIME ZONE"),
    ]

    for column_name, column_type in enhanced_columns:
        if not _column_exists(connection, "dead_letter_events", column_name):
            _safe_execute_sql(
                connection,
                f"ALTER TABLE dead_letter_events ADD COLUMN {column_name} {column_type}",
                f"Add {column_name} column to dead_letter_events",
            )

    # 2. Create indexes for new columns
    enhanced_indexes = [
        ("ix_dead_letter_events_payload_checksum", "dead_letter_events", "payload_checksum"),
        ("ix_dead_letter_events_retry_count", "dead_letter_events", "retry_count"),
        ("ix_dead_letter_events_idempotency_key", "dead_letter_events", "idempotency_key"),
        ("ix_dead_letter_events_processing_lock", "dead_letter_events", "processing_lock"),
        ("ix_dead_letter_events_lock_expires", "dead_letter_events", "lock_expires_at"),
        ("ix_dead_letter_events_classification", "dead_letter_events", "classification"),
        ("ix_dead_letter_events_resolved_created", "dead_letter_events", "resolved, created_at"),
        ("ix_dead_letter_events_priority_resolved", "dead_letter_events", "priority, resolved"),
    ]

    for index_name, table_name, columns in enhanced_indexes:
        _safe_execute_sql(
            connection,
            f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({columns})",
            f"Create {index_name} index",
        )

    # 3. Add constraints (PostgreSQL doesn't support IF NOT EXISTS with ADD CONSTRAINT)
    constraints = [
        ("ck_retry_count_positive", "dead_letter_events", "retry_count >= 0"),
        ("ck_priority_range", "dead_letter_events", "priority BETWEEN 1 AND 10"),
    ]

    for constraint_name, table_name, constraint_def in constraints:
        # Check if constraint already exists
        constraint_exists = connection.execute(
            text(f"""
            SELECT 1 FROM information_schema.table_constraints 
            WHERE constraint_name = '{constraint_name}' 
            AND table_name = '{table_name}'
        """)
        ).fetchone()

        if not constraint_exists:
            _safe_execute_sql(
                connection,
                f"ALTER TABLE {table_name} ADD CONSTRAINT {constraint_name} CHECK ({constraint_def})",
                f"Add {constraint_name} constraint",
            )

    # Add unique constraint for idempotency_key
    unique_constraint_exists = connection.execute(
        text("""
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'uq_idempotency_key' 
        AND table_name = 'dead_letter_events'
    """)
    ).fetchone()

    if not unique_constraint_exists:
        _safe_execute_sql(
            connection,
            "ALTER TABLE dead_letter_events ADD CONSTRAINT uq_idempotency_key UNIQUE (idempotency_key)",
            "Add uq_idempotency_key unique constraint",
        )

    # 4. Create processing metrics table
    if not _table_exists(connection, "dlq_processing_metrics"):
        _safe_execute_sql(
            connection,
            """
            CREATE TABLE dlq_processing_metrics (
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
            )
            """,
            "Create dlq_processing_metrics table",
        )

        # Create indexes for metrics table
        metrics_indexes = [
            ("ix_dlq_metrics_session", "dlq_processing_metrics", "processing_session_id"),
            ("ix_dlq_metrics_method", "dlq_processing_metrics", "processing_method"),
            ("ix_dlq_metrics_started", "dlq_processing_metrics", "started_at"),
        ]

        for index_name, table_name, columns in metrics_indexes:
            _safe_execute_sql(
                connection,
                f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({columns})",
                f"Create {index_name} index",
            )

    # 5. Create circuit breaker state table
    if not _table_exists(connection, "dlq_circuit_breaker_state"):
        _safe_execute_sql(
            connection,
            """
            CREATE TABLE dlq_circuit_breaker_state (
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
            )
            """,
            "Create dlq_circuit_breaker_state table",
        )

        # Create indexes for circuit breaker table
        breaker_indexes = [
            ("ix_circuit_breaker_state", "dlq_circuit_breaker_state", "state"),
            ("ix_circuit_breaker_next_attempt", "dlq_circuit_breaker_state", "next_attempt_time"),
        ]

        for index_name, table_name, columns in breaker_indexes:
            _safe_execute_sql(
                connection,
                f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({columns})",
                f"Create {index_name} index",
            )

    # 6. Create health monitoring view
    _safe_execute_sql(
        connection,
        """
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
        FROM dead_letter_events
        """,
        "Create dlq_health monitoring view",
    )

    # 7. Create function to update updated_at timestamp
    _safe_execute_sql(
        connection,
        """
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql'
        """,
        "Create update_updated_at_column function",
    )

    # 8. Create triggers for updated_at
    triggers = [
        ("update_dead_letter_events_updated_at", "dead_letter_events"),
        ("update_circuit_breaker_updated_at", "dlq_circuit_breaker_state"),
    ]

    for trigger_name, table_name in triggers:
        _safe_execute_sql(
            connection,
            f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name}",
            f"Drop existing {trigger_name} trigger",
        )

        _safe_execute_sql(
            connection,
            f"""
            CREATE TRIGGER {trigger_name}
                BEFORE UPDATE ON {table_name}
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column()
            """,
            f"Create {trigger_name} trigger",
        )

    # 9. Check if pgcrypto extension is available
    pgcrypto_available = connection.execute(
        text("""
        SELECT 1 FROM pg_extension WHERE extname = 'pgcrypto'
    """)
    ).fetchone()

    if pgcrypto_available:
        # Populate checksums for existing records
        _safe_execute_sql(
            connection,
            """
            UPDATE dead_letter_events 
            SET payload_checksum = encode(digest(payload::TEXT, 'sha256'), 'hex')
            WHERE payload_checksum IS NULL
            """,
            "Populate payload checksums for existing records",
        )

        # Generate idempotency keys for existing records
        _safe_execute_sql(
            connection,
            """
            UPDATE dead_letter_events 
            SET idempotency_key = encode(digest(
                COALESCE(source, '') || ':' || 
                COALESCE(source_offset::TEXT, '') || ':' || 
                COALESCE(payload_checksum, ''), 'sha256'
            ), 'hex')
            WHERE idempotency_key IS NULL
            """,
            "Generate idempotency keys for existing records",
        )
    else:
        logger.warning("pgcrypto extension not available, skipping checksum and idempotency key population")

    logger.info("Enhanced DLQ schema migration (v7) completed successfully")


def _upgrade_to_v8(connection: Connection) -> None:
    """Upgrade to schema version 8: Add snowshoe_detections table.
    
    Args:
        connection: Database connection
    """
    logger.info("Starting snowshoe detection schema migration (v8)")
    
    # Create snowshoe_detections table
    _safe_execute_sql(
        connection,
        """
        CREATE TABLE IF NOT EXISTS snowshoe_detections (
            id INTEGER PRIMARY KEY,
            detection_time TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            window_start TIMESTAMP WITH TIME ZONE NOT NULL,
            window_end TIMESTAMP WITH TIME ZONE NOT NULL,
            confidence_score VARCHAR(10) NOT NULL,
            unique_ips INTEGER NOT NULL,
            single_attempt_ips INTEGER NOT NULL,
            geographic_spread VARCHAR(10) NOT NULL,
            indicators JSON NOT NULL,
            is_likely_snowshoe BOOLEAN NOT NULL DEFAULT FALSE,
            coordinated_timing BOOLEAN NOT NULL DEFAULT FALSE,
            recommendation TEXT,
            analysis_metadata JSON,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
        """,
        "Create snowshoe_detections table",
    )
    
    # Create indexes for snowshoe_detections table
    indexes = [
        ("ix_snowshoe_detections_detection_time", "detection_time"),
        ("ix_snowshoe_detections_window", "window_start, window_end"),
        ("ix_snowshoe_detections_confidence", "confidence_score"),
        ("ix_snowshoe_detections_likely", "is_likely_snowshoe"),
        ("ix_snowshoe_detections_created", "created_at"),
    ]
    
    for index_name, columns in indexes:
        _safe_execute_sql(
            connection,
            f"CREATE INDEX IF NOT EXISTS {index_name} ON snowshoe_detections ({columns})",
            f"Create {index_name} index",
        )
    
    logger.info("Snowshoe detection schema migration (v8) completed successfully")


def _upgrade_to_v9(connection: Connection) -> None:
    """Upgrade to schema version 9: Add longtail analysis tables with proper data types."""

    logger.info("Starting longtail analysis schema migration (v9)...")

    dialect_name = connection.dialect.name

    # Create longtail_analysis table with database-specific syntax
    if not _table_exists(connection, 'longtail_analysis'):
        if dialect_name == 'postgresql':
            # PostgreSQL syntax with JSONB and TIMESTAMP WITH TIME ZONE
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE longtail_analysis (
                    id SERIAL PRIMARY KEY,
                    analysis_time TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    window_start TIMESTAMP WITH TIME ZONE NOT NULL,
                    window_end TIMESTAMP WITH TIME ZONE NOT NULL,
                    lookback_days INTEGER NOT NULL,

                    -- Analysis results (proper Float types)
                    confidence_score REAL NOT NULL,
                    total_events_analyzed INTEGER NOT NULL,
                    rare_command_count INTEGER NOT NULL DEFAULT 0,
                    anomalous_sequence_count INTEGER NOT NULL DEFAULT 0,
                    outlier_session_count INTEGER NOT NULL DEFAULT 0,
                    emerging_pattern_count INTEGER NOT NULL DEFAULT 0,
                    high_entropy_payload_count INTEGER NOT NULL DEFAULT 0,

                    -- Results storage
                    analysis_results JSONB NOT NULL,
                    statistical_summary JSONB,
                    recommendation TEXT,

                    -- Performance metrics (proper Float types)
                    analysis_duration_seconds REAL,
                    memory_usage_mb REAL,

                    -- Quality metrics (proper Float types)
                    data_quality_score REAL,
                    enrichment_coverage REAL,

                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """,
                "Create longtail_analysis table"
            ):
                raise Exception("Failed to create longtail_analysis table")
        else:
            # SQLite syntax with JSON as TEXT and TIMESTAMP
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE longtail_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    window_start TIMESTAMP NOT NULL,
                    window_end TIMESTAMP NOT NULL,
                    lookback_days INTEGER NOT NULL,

                    -- Analysis results (proper Float types)
                    confidence_score REAL NOT NULL,
                    total_events_analyzed INTEGER NOT NULL,
                    rare_command_count INTEGER NOT NULL DEFAULT 0,
                    anomalous_sequence_count INTEGER NOT NULL DEFAULT 0,
                    outlier_session_count INTEGER NOT NULL DEFAULT 0,
                    emerging_pattern_count INTEGER NOT NULL DEFAULT 0,
                    high_entropy_payload_count INTEGER NOT NULL DEFAULT 0,

                    -- Results storage
                    analysis_results TEXT NOT NULL,  -- JSON as TEXT in SQLite
                    statistical_summary TEXT,  -- JSON as TEXT in SQLite
                    recommendation TEXT,

                    -- Performance metrics (proper Float types)
                    analysis_duration_seconds REAL,
                    memory_usage_mb REAL,

                    -- Quality metrics (proper Float types)
                    data_quality_score REAL,
                    enrichment_coverage REAL,

                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """,
                "Create longtail_analysis table"
            ):
                raise Exception("Failed to create longtail_analysis table")
    else:
        logger.info("longtail_analysis table already exists, skipping creation")

    # Create indexes for longtail_analysis (only if table exists)
    if _table_exists(connection, 'longtail_analysis'):
        indexes_to_create = [
            ("ix_longtail_analysis_time", "longtail_analysis(analysis_time)"),
            ("ix_longtail_analysis_window", "longtail_analysis(window_start, window_end)"),
            ("ix_longtail_analysis_confidence", "longtail_analysis(confidence_score)"),
            ("ix_longtail_analysis_created", "longtail_analysis(created_at)"),
        ]
        
        for index_name, index_def in indexes_to_create:
            if not _safe_execute_sql(
                connection,
                f"CREATE INDEX IF NOT EXISTS {index_name} ON {index_def}",
                f"Create {index_name} index"
            ):
                logger.warning(f"Failed to create index {index_name}, continuing...")

    # Create longtail_detections table with database-specific syntax
    if not _table_exists(connection, 'longtail_detections'):
        if dialect_name == 'postgresql':
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE longtail_detections (
                    id SERIAL PRIMARY KEY,
                    analysis_id INTEGER NOT NULL REFERENCES longtail_analysis(id) ON DELETE CASCADE,
                    detection_type VARCHAR(32) NOT NULL,
                    session_id VARCHAR(64),
                    event_id INTEGER REFERENCES raw_events(id),

                    -- Detection details (proper Float types)
                    detection_data JSONB NOT NULL,
                    confidence_score REAL NOT NULL,
                    severity_score REAL NOT NULL,

                    -- Context
                    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                    source_ip VARCHAR(45),

                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """,
                "Create longtail_detections table"
            ):
                raise Exception("Failed to create longtail_detections table")
        else:
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE longtail_detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_id INTEGER NOT NULL REFERENCES longtail_analysis(id) ON DELETE CASCADE,
                    detection_type VARCHAR(32) NOT NULL,
                    session_id VARCHAR(64),
                    event_id INTEGER REFERENCES raw_events(id),

                    -- Detection details (proper Float types)
                    detection_data TEXT NOT NULL,  -- JSON as TEXT in SQLite
                    confidence_score REAL NOT NULL,
                    severity_score REAL NOT NULL,

                    -- Context
                    timestamp TIMESTAMP NOT NULL,
                    source_ip VARCHAR(45),

                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """,
                "Create longtail_detections table"
            ):
                raise Exception("Failed to create longtail_detections table")
    else:
        logger.info("longtail_detections table already exists, skipping creation")

    # Create indexes for longtail_detections (only if table exists)
    if _table_exists(connection, 'longtail_detections'):
        indexes_to_create = [
            ("ix_longtail_detections_analysis", "longtail_detections(analysis_id)"),
            ("ix_longtail_detections_type", "longtail_detections(detection_type)"),
            ("ix_longtail_detections_session", "longtail_detections(session_id)"),
            ("ix_longtail_detections_timestamp", "longtail_detections(timestamp)"),
            ("ix_longtail_detections_created", "longtail_detections(created_at)"),
        ]
        
        for index_name, index_def in indexes_to_create:
            if not _safe_execute_sql(
                connection,
                f"CREATE INDEX IF NOT EXISTS {index_name} ON {index_def}",
                f"Create {index_name} index"
            ):
                logger.warning(f"Failed to create index {index_name}, continuing...")

    # Create pgvector tables if PostgreSQL and pgvector available
    if dialect_name == 'postgresql':
        try:
            # Check if pgvector extension is available
            result = connection.execute(text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')"))
            has_pgvector = result.scalar()

            if has_pgvector:
                logger.info("pgvector extension detected, creating vector tables...")

                # Create command sequence vectors table
                _safe_execute_sql(
                    connection,
                    """
                    CREATE TABLE command_sequence_vectors (
                        id SERIAL PRIMARY KEY,
                        session_id VARCHAR(64) NOT NULL,
                        command_sequence TEXT NOT NULL,
                        sequence_vector VECTOR(128),  -- TF-IDF vectorized commands
                        timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                        source_ip INET NOT NULL
                    )
                    """,
                    "Create command_sequence_vectors table"
                )

                # Create HNSW index for fast similarity search
                _safe_execute_sql(
                    connection,
                    """
                    CREATE INDEX ON command_sequence_vectors USING hnsw (sequence_vector vector_cosine_ops);
                    """,
                    "Create HNSW index for command sequence vectors"
                )

                # Create behavioral pattern vectors table
                _safe_execute_sql(
                    connection,
                    """
                    CREATE TABLE behavioral_vectors (
                        id SERIAL PRIMARY KEY,
                        session_id VARCHAR(64) NOT NULL,
                        behavioral_vector VECTOR(64),  -- Session characteristics vector
                        session_metadata JSONB,
                        timestamp TIMESTAMP WITH TIME ZONE NOT NULL
                    )
                    """,
                    "Create behavioral_vectors table"
                )

                # Create IVFFlat index for behavioral clustering
                _safe_execute_sql(
                    connection,
                    """
                    CREATE INDEX ON behavioral_vectors
                    USING ivfflat (behavioral_vector vector_l2_ops) WITH (lists = 100);
                    """,
                    "Create IVFFlat index for behavioral vectors"
                )

                logger.info("pgvector tables created successfully")
            else:
                logger.info("pgvector extension not available, skipping vector tables")
        except Exception as e:
            logger.warning(f"Failed to create pgvector tables: {e}")

    logger.info("Longtail analysis schema migration (v9) completed successfully")


def _downgrade_from_v9(connection: Connection) -> None:
    """Rollback v9 migration if needed."""
    logger.info("Rolling back longtail analysis tables...")

    try:
        # Drop tables in reverse order of dependencies
        _safe_execute_sql(
            connection,
            "DROP TABLE IF EXISTS longtail_detections CASCADE",
            "Drop longtail_detections table"
        )

        _safe_execute_sql(
            connection,
            "DROP TABLE IF EXISTS longtail_analysis CASCADE",
            "Drop longtail_analysis table"
        )

        # If using PostgreSQL with pgvector, drop vector tables
        if connection.dialect.name == 'postgresql':
            _safe_execute_sql(
                connection,
                "DROP TABLE IF EXISTS command_sequence_vectors CASCADE",
                "Drop command_sequence_vectors table"
            )

            _safe_execute_sql(
                connection,
                "DROP TABLE IF EXISTS behavioral_vectors CASCADE",
                "Drop behavioral_vectors table"
            )

        # Update schema version
        _safe_execute_sql(
            connection,
            f"UPDATE schema_metadata SET value = '8' WHERE key = '{SCHEMA_VERSION_KEY}'",
            "Update schema version to 8"
        )

        logger.info("Rollback to v8 complete")

    except Exception as e:
        logger.error(f"Rollback failed: {e}")


__all__ = ["apply_migrations", "CURRENT_SCHEMA_VERSION", "SCHEMA_VERSION_KEY"]
