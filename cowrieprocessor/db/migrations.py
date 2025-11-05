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
CURRENT_SCHEMA_VERSION = 16

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
                hidden_value = row[5]
                return bool(hidden_value > 0)  # hidden column indicates generated column

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

        if version < 10:
            _upgrade_to_v10(connection)
            _set_schema_version(connection, 10)
            version = 10

        if version < 11:
            _upgrade_to_v11(connection)
            _set_schema_version(connection, 11)
            version = 11

        if version < 12:
            _upgrade_to_v12(connection)
            _set_schema_version(connection, 12)
            version = 12

        if version < 13:
            _upgrade_to_v13(connection)
            _set_schema_version(connection, 13)
            version = 13

        if version < 14:
            _upgrade_to_v14(connection)
            _set_schema_version(connection, 14)
            version = 14

        if version < 15:
            _upgrade_to_v15(connection)
            _set_schema_version(connection, 15)
            version = 15

        if version < 16:
            _upgrade_to_v16(connection)
            _set_schema_version(connection, 16)
            version = 16

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
        # Use MetaData.create_all() instead of Table.create()
        from sqlalchemy import MetaData

        metadata = MetaData()
        # Cast to Table type since we know Files.__table__ is a Table
        from sqlalchemy import Table

        files_table = Files.__table__
        assert isinstance(files_table, Table), "Files.__table__ should be a Table"
        metadata.create_all(connection, tables=[files_table], checkfirst=True)
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

    dialect_name = connection.dialect.name

    # Create snowshoe_detections table with database-specific syntax
    if dialect_name == "postgresql":
        # PostgreSQL syntax with TIMESTAMP WITH TIME ZONE and JSON
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
            "Create snowshoe_detections table (PostgreSQL)",
        )
    else:
        # SQLite syntax with TEXT for timestamps and JSON, INTEGER for booleans
        _safe_execute_sql(
            connection,
            """
            CREATE TABLE IF NOT EXISTS snowshoe_detections (
                id INTEGER PRIMARY KEY,
                detection_time TEXT NOT NULL,
                window_start TEXT NOT NULL,
                window_end TEXT NOT NULL,
                confidence_score VARCHAR(10) NOT NULL,
                unique_ips INTEGER NOT NULL,
                single_attempt_ips INTEGER NOT NULL,
                geographic_spread VARCHAR(10) NOT NULL,
                indicators TEXT NOT NULL,
                is_likely_snowshoe INTEGER NOT NULL DEFAULT 0,
                coordinated_timing INTEGER NOT NULL DEFAULT 0,
                recommendation TEXT,
                analysis_metadata TEXT,
                created_at TEXT NOT NULL
            )
            """,
            "Create snowshoe_detections table (SQLite)",
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
                "Create longtail_analysis table",
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
                "Create longtail_analysis table",
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
                connection, f"CREATE INDEX IF NOT EXISTS {index_name} ON {index_def}", f"Create {index_name} index"
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
                "Create longtail_detections table",
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
                "Create longtail_detections table",
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
                connection, f"CREATE INDEX IF NOT EXISTS {index_name} ON {index_def}", f"Create {index_name} index"
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
                    "Create command_sequence_vectors table",
                )

                # Create HNSW index for fast similarity search
                _safe_execute_sql(
                    connection,
                    """
                    CREATE INDEX ON command_sequence_vectors USING hnsw (sequence_vector vector_cosine_ops);
                    """,
                    "Create HNSW index for command sequence vectors",
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
                    "Create behavioral_vectors table",
                )

                # Create IVFFlat index for behavioral clustering
                _safe_execute_sql(
                    connection,
                    """
                    CREATE INDEX ON behavioral_vectors
                    USING ivfflat (behavioral_vector vector_l2_ops) WITH (lists = 100);
                    """,
                    "Create IVFFlat index for behavioral vectors",
                )

                logger.info("pgvector tables created successfully")
            else:
                logger.info("pgvector extension not available, skipping vector tables")
        except Exception as e:
            logger.warning(f"Failed to create pgvector tables: {e}")

    logger.info("Longtail analysis schema migration (v9) completed successfully")


def _upgrade_to_v10(connection: Connection) -> None:
    """Upgrade to schema version 10: Add password_statistics table for HIBP enrichment."""
    logger.info("Starting password statistics schema migration (v10)...")

    dialect_name = connection.dialect.name

    # Create password_statistics table if it doesn't exist
    if not _table_exists(connection, 'password_statistics'):
        if dialect_name == 'postgresql':
            # PostgreSQL syntax
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE password_statistics (
                    id SERIAL PRIMARY KEY,
                    date DATE NOT NULL UNIQUE,
                    total_attempts INTEGER NOT NULL DEFAULT 0,
                    unique_passwords INTEGER NOT NULL DEFAULT 0,
                    breached_count INTEGER NOT NULL DEFAULT 0,
                    novel_count INTEGER NOT NULL DEFAULT 0,
                    max_prevalence INTEGER,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """,
                "Create password_statistics table (PostgreSQL)",
            ):
                raise Exception("Failed to create password_statistics table")

            # Create index for created_at (date has unique constraint)
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_password_statistics_created ON password_statistics(created_at)",
                "Create created_at index on password_statistics",
            )
        else:
            # SQLite syntax
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE password_statistics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL UNIQUE,
                    total_attempts INTEGER NOT NULL DEFAULT 0,
                    unique_passwords INTEGER NOT NULL DEFAULT 0,
                    breached_count INTEGER NOT NULL DEFAULT 0,
                    novel_count INTEGER NOT NULL DEFAULT 0,
                    max_prevalence INTEGER,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """,
                "Create password_statistics table (SQLite)",
            ):
                raise Exception("Failed to create password_statistics table")

            # Create index for created_at (date has unique constraint)
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_password_statistics_created ON password_statistics(created_at)",
                "Create created_at index on password_statistics",
            )

        logger.info("password_statistics table created successfully")
    else:
        logger.info("password_statistics table already exists, skipping creation")

    # Create password_tracking table if it doesn't exist
    if not _table_exists(connection, 'password_tracking'):
        if dialect_name == 'postgresql':
            # PostgreSQL syntax
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE password_tracking (
                    id SERIAL PRIMARY KEY,
                    password_hash VARCHAR(64) NOT NULL UNIQUE,
                    password_text TEXT NOT NULL,
                    breached BOOLEAN NOT NULL DEFAULT FALSE,
                    breach_prevalence INTEGER,
                    last_hibp_check TIMESTAMP WITH TIME ZONE,
                    first_seen TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    last_seen TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    times_seen INTEGER NOT NULL DEFAULT 1,
                    unique_sessions INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """,
                "Create password_tracking table (PostgreSQL)",
            ):
                raise Exception("Failed to create password_tracking table")

            # Create indexes
            _safe_execute_sql(
                connection,
                "CREATE UNIQUE INDEX ix_password_tracking_hash ON password_tracking(password_hash)",
                "Create hash index on password_tracking",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_password_tracking_last_seen ON password_tracking(last_seen)",
                "Create last_seen index on password_tracking",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_password_tracking_breached ON password_tracking(breached)",
                "Create breached index on password_tracking",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_password_tracking_times_seen ON password_tracking(times_seen)",
                "Create times_seen index on password_tracking",
            )
        else:
            # SQLite syntax
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE password_tracking (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    password_hash VARCHAR(64) NOT NULL UNIQUE,
                    password_text TEXT NOT NULL,
                    breached BOOLEAN NOT NULL DEFAULT 0,
                    breach_prevalence INTEGER,
                    last_hibp_check TIMESTAMP,
                    first_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    times_seen INTEGER NOT NULL DEFAULT 1,
                    unique_sessions INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """,
                "Create password_tracking table (SQLite)",
            ):
                raise Exception("Failed to create password_tracking table")

            # Create indexes
            _safe_execute_sql(
                connection,
                "CREATE UNIQUE INDEX ix_password_tracking_hash ON password_tracking(password_hash)",
                "Create hash index on password_tracking",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_password_tracking_last_seen ON password_tracking(last_seen)",
                "Create last_seen index on password_tracking",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_password_tracking_breached ON password_tracking(breached)",
                "Create breached index on password_tracking",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_password_tracking_times_seen ON password_tracking(times_seen)",
                "Create times_seen index on password_tracking",
            )

        logger.info("password_tracking table created successfully")
    else:
        logger.info("password_tracking table already exists, skipping creation")

    # Create password_session_usage table if it doesn't exist
    if not _table_exists(connection, 'password_session_usage'):
        if dialect_name == 'postgresql':
            # PostgreSQL syntax
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE password_session_usage (
                    id SERIAL PRIMARY KEY,
                    password_id INTEGER NOT NULL REFERENCES password_tracking(id) ON DELETE CASCADE,
                    session_id VARCHAR(64) NOT NULL REFERENCES session_summaries(session_id),
                    username VARCHAR(256),
                    success BOOLEAN NOT NULL DEFAULT FALSE,
                    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                    UNIQUE(password_id, session_id)
                )
                """,
                "Create password_session_usage table (PostgreSQL)",
            ):
                raise Exception("Failed to create password_session_usage table")

            # Create indexes
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_password_session_password ON password_session_usage(password_id)",
                "Create password_id index on password_session_usage",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_password_session_session ON password_session_usage(session_id)",
                "Create session_id index on password_session_usage",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_password_session_timestamp ON password_session_usage(timestamp)",
                "Create timestamp index on password_session_usage",
            )
        else:
            # SQLite syntax
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE password_session_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    password_id INTEGER NOT NULL REFERENCES password_tracking(id) ON DELETE CASCADE,
                    session_id VARCHAR(64) NOT NULL REFERENCES session_summaries(session_id),
                    username VARCHAR(256),
                    success BOOLEAN NOT NULL DEFAULT 0,
                    timestamp TIMESTAMP NOT NULL,
                    UNIQUE(password_id, session_id)
                )
                """,
                "Create password_session_usage table (SQLite)",
            ):
                raise Exception("Failed to create password_session_usage table")

            # Create indexes
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_password_session_password ON password_session_usage(password_id)",
                "Create password_id index on password_session_usage",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_password_session_session ON password_session_usage(session_id)",
                "Create session_id index on password_session_usage",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_password_session_timestamp ON password_session_usage(timestamp)",
                "Create timestamp index on password_session_usage",
            )

        logger.info("password_session_usage table created successfully")
    else:
        logger.info("password_session_usage table already exists, skipping creation")

    logger.info("Password statistics schema migration (v10) completed successfully")


def _upgrade_to_v11(connection: Connection) -> None:
    """Upgrade to schema version 11: Add SSH key intelligence tracking tables."""
    logger.info("Starting SSH key intelligence schema migration (v11)...")

    dialect_name = connection.dialect.name

    # Create ssh_key_intelligence table if it doesn't exist
    if not _table_exists(connection, 'ssh_key_intelligence'):
        if dialect_name == 'postgresql':
            # PostgreSQL syntax
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE ssh_key_intelligence (
                    id SERIAL PRIMARY KEY,
                    key_type VARCHAR(32) NOT NULL,
                    key_data TEXT NOT NULL,
                    key_fingerprint VARCHAR(64) NOT NULL,
                    key_hash VARCHAR(64) NOT NULL UNIQUE,
                    key_comment TEXT,
                    first_seen TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    last_seen TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    total_attempts INTEGER NOT NULL DEFAULT 1,
                    unique_sources INTEGER NOT NULL DEFAULT 1,
                    unique_sessions INTEGER NOT NULL DEFAULT 1,
                    key_bits INTEGER,
                    key_full TEXT NOT NULL,
                    pattern_type VARCHAR(32) NOT NULL,
                    target_path TEXT,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """,
                "Create ssh_key_intelligence table (PostgreSQL)",
            ):
                raise Exception("Failed to create ssh_key_intelligence table")

            # Create indexes
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_ssh_key_fingerprint ON ssh_key_intelligence(key_fingerprint)",
                "Create fingerprint index on ssh_key_intelligence",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_ssh_key_type ON ssh_key_intelligence(key_type)",
                "Create type index on ssh_key_intelligence",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_ssh_key_timeline ON ssh_key_intelligence(first_seen, last_seen)",
                "Create timeline index on ssh_key_intelligence",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_ssh_key_attempts ON ssh_key_intelligence(total_attempts)",
                "Create attempts index on ssh_key_intelligence",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_ssh_key_sources ON ssh_key_intelligence(unique_sources)",
                "Create sources index on ssh_key_intelligence",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_ssh_key_sessions ON ssh_key_intelligence(unique_sessions)",
                "Create sessions index on ssh_key_intelligence",
            )
        else:
            # SQLite syntax
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE ssh_key_intelligence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_type VARCHAR(32) NOT NULL,
                    key_data TEXT NOT NULL,
                    key_fingerprint VARCHAR(64) NOT NULL,
                    key_hash VARCHAR(64) NOT NULL UNIQUE,
                    key_comment TEXT,
                    first_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    total_attempts INTEGER NOT NULL DEFAULT 1,
                    unique_sources INTEGER NOT NULL DEFAULT 1,
                    unique_sessions INTEGER NOT NULL DEFAULT 1,
                    key_bits INTEGER,
                    key_full TEXT NOT NULL,
                    pattern_type VARCHAR(32) NOT NULL,
                    target_path TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """,
                "Create ssh_key_intelligence table (SQLite)",
            ):
                raise Exception("Failed to create ssh_key_intelligence table")

            # Create indexes
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_ssh_key_fingerprint ON ssh_key_intelligence(key_fingerprint)",
                "Create fingerprint index on ssh_key_intelligence",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_ssh_key_type ON ssh_key_intelligence(key_type)",
                "Create type index on ssh_key_intelligence",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_ssh_key_timeline ON ssh_key_intelligence(first_seen, last_seen)",
                "Create timeline index on ssh_key_intelligence",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_ssh_key_attempts ON ssh_key_intelligence(total_attempts)",
                "Create attempts index on ssh_key_intelligence",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_ssh_key_sources ON ssh_key_intelligence(unique_sources)",
                "Create sources index on ssh_key_intelligence",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_ssh_key_sessions ON ssh_key_intelligence(unique_sessions)",
                "Create sessions index on ssh_key_intelligence",
            )

        logger.info("ssh_key_intelligence table created successfully")
    else:
        logger.info("ssh_key_intelligence table already exists, skipping creation")

    # Create session_ssh_keys table if it doesn't exist
    if not _table_exists(connection, 'session_ssh_keys'):
        if dialect_name == 'postgresql':
            # PostgreSQL syntax
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE session_ssh_keys (
                    id SERIAL PRIMARY KEY,
                    session_id VARCHAR(64) NOT NULL,
                    ssh_key_id INTEGER NOT NULL REFERENCES ssh_key_intelligence(id),
                    command_text TEXT,
                    command_hash VARCHAR(64),
                    injection_method VARCHAR(32) NOT NULL,
                    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    source_ip VARCHAR(45),
                    successful_injection BOOLEAN NOT NULL DEFAULT FALSE
                )
                """,
                "Create session_ssh_keys table (PostgreSQL)",
            ):
                raise Exception("Failed to create session_ssh_keys table")

            # Create indexes
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_session_ssh_keys_session ON session_ssh_keys(session_id)",
                "Create session index on session_ssh_keys",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_session_ssh_keys_timestamp ON session_ssh_keys(timestamp)",
                "Create timestamp index on session_ssh_keys",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_session_ssh_keys_ssh_key ON session_ssh_keys(ssh_key_id)",
                "Create ssh_key index on session_ssh_keys",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_session_ssh_keys_source_ip ON session_ssh_keys(source_ip)",
                "Create source_ip index on session_ssh_keys",
            )
        else:
            # SQLite syntax
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE session_ssh_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id VARCHAR(64) NOT NULL,
                    ssh_key_id INTEGER NOT NULL,
                    command_text TEXT,
                    command_hash VARCHAR(64),
                    injection_method VARCHAR(32) NOT NULL,
                    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    source_ip VARCHAR(45),
                    successful_injection BOOLEAN NOT NULL DEFAULT 0,
                    FOREIGN KEY (ssh_key_id) REFERENCES ssh_key_intelligence(id)
                )
                """,
                "Create session_ssh_keys table (SQLite)",
            ):
                raise Exception("Failed to create session_ssh_keys table")

            # Create indexes
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_session_ssh_keys_session ON session_ssh_keys(session_id)",
                "Create session index on session_ssh_keys",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_session_ssh_keys_timestamp ON session_ssh_keys(timestamp)",
                "Create timestamp index on session_ssh_keys",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_session_ssh_keys_ssh_key ON session_ssh_keys(ssh_key_id)",
                "Create ssh_key index on session_ssh_keys",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_session_ssh_keys_source_ip ON session_ssh_keys(source_ip)",
                "Create source_ip index on session_ssh_keys",
            )

        logger.info("session_ssh_keys table created successfully")
    else:
        logger.info("session_ssh_keys table already exists, skipping creation")

    # Create ssh_key_associations table if it doesn't exist
    if not _table_exists(connection, 'ssh_key_associations'):
        if dialect_name == 'postgresql':
            # PostgreSQL syntax
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE ssh_key_associations (
                    id SERIAL PRIMARY KEY,
                    key_id_1 INTEGER NOT NULL REFERENCES ssh_key_intelligence(id),
                    key_id_2 INTEGER NOT NULL REFERENCES ssh_key_intelligence(id),
                    co_occurrence_count INTEGER NOT NULL DEFAULT 1,
                    first_seen TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    last_seen TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    same_session_count INTEGER NOT NULL DEFAULT 0,
                    same_ip_count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(key_id_1, key_id_2)
                )
                """,
                "Create ssh_key_associations table (PostgreSQL)",
            ):
                raise Exception("Failed to create ssh_key_associations table")

            # Create indexes
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_ssh_key_associations_keys ON ssh_key_associations(key_id_1, key_id_2)",
                "Create keys index on ssh_key_associations",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_ssh_key_associations_co_occurrence ON ssh_key_associations(co_occurrence_count)",
                "Create co_occurrence index on ssh_key_associations",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_ssh_key_associations_timeline ON ssh_key_associations(first_seen, last_seen)",
                "Create timeline index on ssh_key_associations",
            )
        else:
            # SQLite syntax
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE ssh_key_associations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_id_1 INTEGER NOT NULL,
                    key_id_2 INTEGER NOT NULL,
                    co_occurrence_count INTEGER NOT NULL DEFAULT 1,
                    first_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    same_session_count INTEGER NOT NULL DEFAULT 0,
                    same_ip_count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(key_id_1, key_id_2),
                    FOREIGN KEY (key_id_1) REFERENCES ssh_key_intelligence(id),
                    FOREIGN KEY (key_id_2) REFERENCES ssh_key_intelligence(id)
                )
                """,
                "Create ssh_key_associations table (SQLite)",
            ):
                raise Exception("Failed to create ssh_key_associations table")

            # Create indexes
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_ssh_key_associations_keys ON ssh_key_associations(key_id_1, key_id_2)",
                "Create keys index on ssh_key_associations",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_ssh_key_associations_co_occurrence ON ssh_key_associations(co_occurrence_count)",
                "Create co_occurrence index on ssh_key_associations",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_ssh_key_associations_timeline ON ssh_key_associations(first_seen, last_seen)",
                "Create timeline index on ssh_key_associations",
            )

        logger.info("ssh_key_associations table created successfully")
    else:
        logger.info("ssh_key_associations table already exists, skipping creation")

    # Add SSH key columns to session_summaries if they don't exist
    if not _column_exists(connection, 'session_summaries', 'ssh_key_injections'):
        if dialect_name == 'postgresql':
            _safe_execute_sql(
                connection,
                "ALTER TABLE session_summaries ADD COLUMN ssh_key_injections INTEGER NOT NULL DEFAULT 0",
                "Add ssh_key_injections column to session_summaries",
            )
        else:
            _safe_execute_sql(
                connection,
                "ALTER TABLE session_summaries ADD COLUMN ssh_key_injections INTEGER NOT NULL DEFAULT 0",
                "Add ssh_key_injections column to session_summaries",
            )
        logger.info("Added ssh_key_injections column to session_summaries")
    else:
        logger.info("ssh_key_injections column already exists in session_summaries")

    if not _column_exists(connection, 'session_summaries', 'unique_ssh_keys'):
        if dialect_name == 'postgresql':
            _safe_execute_sql(
                connection,
                "ALTER TABLE session_summaries ADD COLUMN unique_ssh_keys INTEGER NOT NULL DEFAULT 0",
                "Add unique_ssh_keys column to session_summaries",
            )
        else:
            _safe_execute_sql(
                connection,
                "ALTER TABLE session_summaries ADD COLUMN unique_ssh_keys INTEGER NOT NULL DEFAULT 0",
                "Add unique_ssh_keys column to session_summaries",
            )
        logger.info("Added unique_ssh_keys column to session_summaries")
    else:
        logger.info("unique_ssh_keys column already exists in session_summaries")

    # Create index on ssh_key_injections column
    if not _column_exists(connection, 'session_summaries', 'ssh_key_injections'):
        # Index will be created only if column was just added
        pass
    else:
        # Check if index exists and create if needed
        _safe_execute_sql(
            connection,
            "CREATE INDEX IF NOT EXISTS ix_session_summaries_ssh_keys ON session_summaries(ssh_key_injections)",
            "Create ssh_keys index on session_summaries",
        )

    logger.info("SSH key intelligence schema migration (v11) completed successfully")


def _upgrade_to_v12(connection: Connection) -> None:
    """Upgrade to schema version 12: Convert event_timestamp from VARCHAR to TIMESTAMP WITH TIME ZONE."""
    logger.info("Starting event_timestamp type conversion migration (v12)...")

    dialect_name = connection.dialect.name

    # Check if event_timestamp column exists and is currently VARCHAR
    if _column_exists(connection, "raw_events", "event_timestamp"):
        if dialect_name == "postgresql":
            # PostgreSQL: Convert VARCHAR to TIMESTAMP WITH TIME ZONE
            logger.info("Converting event_timestamp from VARCHAR to TIMESTAMP WITH TIME ZONE (PostgreSQL)")

            try:
                # First, add a temporary column with the correct type
                if not _safe_execute_sql(
                    connection,
                    "ALTER TABLE raw_events ADD COLUMN event_timestamp_new TIMESTAMP WITH TIME ZONE",
                    "Add temporary event_timestamp_new column",
                ):
                    raise Exception("Failed to add temporary event_timestamp_new column")

                # Populate the new column by converting the string values
                # Handle empty strings and invalid formats gracefully
                if not _safe_execute_sql(
                    connection,
                    """
                    UPDATE raw_events 
                    SET event_timestamp_new = event_timestamp::TIMESTAMP WITH TIME ZONE 
                    WHERE event_timestamp IS NOT NULL 
                    AND event_timestamp != ''
                    AND event_timestamp != 'null'
                    AND length(trim(event_timestamp)) > 0
                    AND event_timestamp ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
                    """,
                    "Convert string timestamps to datetime",
                ):
                    raise Exception("Failed to convert valid timestamps")

                # Set NULL for invalid/empty timestamps
                if not _safe_execute_sql(
                    connection,
                    """
                    UPDATE raw_events 
                    SET event_timestamp_new = NULL 
                    WHERE event_timestamp IS NULL 
                    OR event_timestamp = ''
                    OR event_timestamp = 'null'
                    OR length(trim(event_timestamp)) = 0
                    OR event_timestamp !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
                    """,
                    "Set NULL for invalid timestamps",
                ):
                    raise Exception("Failed to set NULL for invalid timestamps")

                # Drop the old column and rename the new one
                if not _safe_execute_sql(
                    connection, "ALTER TABLE raw_events DROP COLUMN event_timestamp", "Drop old event_timestamp column"
                ):
                    raise Exception("Failed to drop old event_timestamp column")

                if not _safe_execute_sql(
                    connection,
                    "ALTER TABLE raw_events RENAME COLUMN event_timestamp_new TO event_timestamp",
                    "Rename new column to event_timestamp",
                ):
                    raise Exception("Failed to rename new column to event_timestamp")

                # Recreate the index
                if not _safe_execute_sql(
                    connection, "DROP INDEX IF EXISTS ix_raw_events_event_timestamp", "Drop old event_timestamp index"
                ):
                    logger.warning("Failed to drop old event_timestamp index - continuing")

                if not _safe_execute_sql(
                    connection,
                    "CREATE INDEX ix_raw_events_event_timestamp ON raw_events(event_timestamp)",
                    "Create new event_timestamp index",
                ):
                    raise Exception("Failed to create new event_timestamp index")

                logger.info("PostgreSQL event_timestamp conversion completed successfully")

            except Exception as e:
                logger.error(f"PostgreSQL event_timestamp conversion failed: {e}")
                # Try to clean up the temporary column if it exists
                try:
                    _safe_execute_sql(
                        connection,
                        "ALTER TABLE raw_events DROP COLUMN IF EXISTS event_timestamp_new",
                        "Clean up temporary column",
                    )
                except Exception:
                    pass  # Ignore cleanup errors
                raise

        else:
            # SQLite: Keep as string for compatibility
            logger.info("SQLite detected - keeping event_timestamp as string for compatibility")

            # SQLite doesn't support changing column types easily, so we'll keep it as string
            # but we can add a computed column for datetime operations if needed
            logger.info("SQLite event_timestamp remains as VARCHAR for compatibility")

    else:
        logger.warning("event_timestamp column not found - skipping conversion")

    logger.info("Event timestamp type conversion migration (v12) completed successfully")


def _upgrade_to_v13(connection: Connection) -> None:
    """Upgrade to v13 schema by adding longtail detection-session junction table and checkpoints table."""
    dialect_name = connection.dialect.name

    # Create longtail_detection_sessions junction table
    if not _table_exists(connection, 'longtail_detection_sessions'):
        if dialect_name == 'postgresql':
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE longtail_detection_sessions (
                    detection_id INTEGER NOT NULL REFERENCES longtail_detections(id) ON DELETE CASCADE,
                    session_id VARCHAR(64) NOT NULL REFERENCES session_summaries(session_id) ON DELETE CASCADE,
                    PRIMARY KEY (detection_id, session_id)
                )
                """,
                "Create longtail_detection_sessions junction table (PostgreSQL)",
            ):
                raise Exception("Failed to create longtail_detection_sessions table")
        else:
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE longtail_detection_sessions (
                    detection_id INTEGER NOT NULL REFERENCES longtail_detections(id) ON DELETE CASCADE,
                    session_id VARCHAR(64) NOT NULL REFERENCES session_summaries(session_id) ON DELETE CASCADE,
                    PRIMARY KEY (detection_id, session_id)
                )
                """,
                "Create longtail_detection_sessions junction table (SQLite)",
            ):
                raise Exception("Failed to create longtail_detection_sessions table")
    else:
        logger.info("longtail_detection_sessions table already exists, skipping creation")

    # Create indexes for junction table
    if _table_exists(connection, 'longtail_detection_sessions'):
        indexes_to_create = [
            ("ix_longtail_detection_sessions_detection", "longtail_detection_sessions(detection_id)"),
            ("ix_longtail_detection_sessions_session", "longtail_detection_sessions(session_id)"),
        ]

        for index_name, index_def in indexes_to_create:
            if not _safe_execute_sql(
                connection, f"CREATE INDEX IF NOT EXISTS {index_name} ON {index_def}", f"Create {index_name} index"
            ):
                logger.warning(f"Failed to create index {index_name}, continuing...")

    # Create longtail_analysis_checkpoints table
    if not _table_exists(connection, 'longtail_analysis_checkpoints'):
        if dialect_name == 'postgresql':
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE longtail_analysis_checkpoints (
                    id SERIAL PRIMARY KEY,
                    checkpoint_date DATE NOT NULL UNIQUE,
                    window_start TIMESTAMP WITH TIME ZONE NOT NULL,
                    window_end TIMESTAMP WITH TIME ZONE NOT NULL,
                    sessions_analyzed INTEGER NOT NULL,
                    vocabulary_hash VARCHAR(64) NOT NULL,
                    last_analysis_id INTEGER REFERENCES longtail_analysis(id),
                    completed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """,
                "Create longtail_analysis_checkpoints table (PostgreSQL)",
            ):
                raise Exception("Failed to create longtail_analysis_checkpoints table")
        else:
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE longtail_analysis_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    checkpoint_date DATE NOT NULL UNIQUE,
                    window_start TIMESTAMP NOT NULL,
                    window_end TIMESTAMP NOT NULL,
                    sessions_analyzed INTEGER NOT NULL,
                    vocabulary_hash VARCHAR(64) NOT NULL,
                    last_analysis_id INTEGER REFERENCES longtail_analysis(id),
                    completed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """,
                "Create longtail_analysis_checkpoints table (SQLite)",
            ):
                raise Exception("Failed to create longtail_analysis_checkpoints table")
    else:
        logger.info("longtail_analysis_checkpoints table already exists, skipping creation")

    # Create indexes for checkpoints table
    if _table_exists(connection, 'longtail_analysis_checkpoints'):
        indexes_to_create = [
            ("ix_longtail_checkpoints_date", "longtail_analysis_checkpoints(checkpoint_date)"),
            ("ix_longtail_checkpoints_window", "longtail_analysis_checkpoints(window_start, window_end)"),
            ("ix_longtail_checkpoints_analysis", "longtail_analysis_checkpoints(last_analysis_id)"),
        ]

        for index_name, index_def in indexes_to_create:
            if not _safe_execute_sql(
                connection, f"CREATE INDEX IF NOT EXISTS {index_name} ON {index_def}", f"Create {index_name} index"
            ):
                logger.warning(f"Failed to create index {index_name}, continuing...")

    logger.info("Longtail detection-session linking and checkpoints migration (v13) completed successfully")


def _upgrade_to_v14(connection: Connection) -> None:
    """Upgrade to v14 schema by adding analysis_id to vector tables."""
    dialect_name = connection.dialect.name

    # Only apply to PostgreSQL databases (vector tables only exist on PostgreSQL with pgvector)
    if dialect_name != 'postgresql':
        logger.info("Skipping v14 migration (vector tables only exist on PostgreSQL)")
        return

    # Check if vector tables exist
    if not _table_exists(connection, 'command_sequence_vectors'):
        logger.info("Vector tables do not exist, skipping v14 migration")
        return

    logger.info("Upgrading to v14: Adding analysis_id to vector tables...")

    # Add analysis_id column to command_sequence_vectors
    if not _column_exists(connection, 'command_sequence_vectors', 'analysis_id'):
        if not _safe_execute_sql(
            connection,
            """
            ALTER TABLE command_sequence_vectors 
            ADD COLUMN analysis_id INTEGER REFERENCES longtail_analysis(id) ON DELETE CASCADE
            """,
            "Add analysis_id column to command_sequence_vectors",
        ):
            raise Exception("Failed to add analysis_id column to command_sequence_vectors")

        # Create index for analysis_id lookups
        if not _safe_execute_sql(
            connection,
            """
            CREATE INDEX ix_command_sequence_vectors_analysis 
            ON command_sequence_vectors(analysis_id)
            """,
            "Create index on command_sequence_vectors.analysis_id",
        ):
            logger.warning("Failed to create index on command_sequence_vectors.analysis_id")
    else:
        logger.info("analysis_id column already exists in command_sequence_vectors")

    # Add analysis_id column to behavioral_vectors
    if not _column_exists(connection, 'behavioral_vectors', 'analysis_id'):
        if not _safe_execute_sql(
            connection,
            """
            ALTER TABLE behavioral_vectors 
            ADD COLUMN analysis_id INTEGER REFERENCES longtail_analysis(id) ON DELETE CASCADE
            """,
            "Add analysis_id column to behavioral_vectors",
        ):
            raise Exception("Failed to add analysis_id column to behavioral_vectors")

        # Create index for analysis_id lookups
        if not _safe_execute_sql(
            connection,
            """
            CREATE INDEX ix_behavioral_vectors_analysis 
            ON behavioral_vectors(analysis_id)
            """,
            "Create index on behavioral_vectors.analysis_id",
        ):
            logger.warning("Failed to create index on behavioral_vectors.analysis_id")
    else:
        logger.info("analysis_id column already exists in behavioral_vectors")

    logger.info("Vector table analysis_id migration (v14) completed successfully")


def _upgrade_to_v15(connection: Connection) -> None:
    """Upgrade to schema version 15: Add enrichment_cache table for database L2 cache.

    This migration implements the database-backed L2 cache tier for the hybrid caching
    architecture: Redis L1 → Database L2 → Filesystem L3 fallback.

    The enrichment_cache table stores API responses from security services (VirusTotal,
    DShield, URLHaus, SPUR, HIBP) with configurable TTLs and automatic expiration.
    """
    logger.info("Starting enrichment_cache schema migration (v15)...")

    dialect_name = connection.dialect.name

    # Create enrichment_cache table if it doesn't exist
    if not _table_exists(connection, 'enrichment_cache'):
        if dialect_name == 'postgresql':
            # PostgreSQL syntax with JSONB for better performance
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE enrichment_cache (
                    id SERIAL PRIMARY KEY,
                    service VARCHAR(64) NOT NULL,
                    cache_key VARCHAR(256) NOT NULL,
                    cache_value JSONB NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    CONSTRAINT uq_enrichment_cache_service_key UNIQUE (service, cache_key)
                )
                """,
                "Create enrichment_cache table (PostgreSQL)",
            ):
                raise Exception("Failed to create enrichment_cache table")

            # Create indexes
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_enrichment_cache_service_key ON enrichment_cache(service, cache_key)",
                "Create composite index on enrichment_cache(service, cache_key)",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_enrichment_cache_expires_at ON enrichment_cache(expires_at)",
                "Create index on enrichment_cache.expires_at",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_enrichment_cache_created_at ON enrichment_cache(created_at)",
                "Create index on enrichment_cache.created_at",
            )
        else:
            # SQLite syntax with JSON
            if not _safe_execute_sql(
                connection,
                """
                CREATE TABLE enrichment_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service VARCHAR(64) NOT NULL,
                    cache_key VARCHAR(256) NOT NULL,
                    cache_value TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    CONSTRAINT uq_enrichment_cache_service_key UNIQUE (service, cache_key)
                )
                """,
                "Create enrichment_cache table (SQLite)",
            ):
                raise Exception("Failed to create enrichment_cache table")

            # Create indexes
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_enrichment_cache_service_key ON enrichment_cache(service, cache_key)",
                "Create composite index on enrichment_cache(service, cache_key)",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_enrichment_cache_expires_at ON enrichment_cache(expires_at)",
                "Create index on enrichment_cache.expires_at",
            )
            _safe_execute_sql(
                connection,
                "CREATE INDEX ix_enrichment_cache_created_at ON enrichment_cache(created_at)",
                "Create index on enrichment_cache.created_at",
            )

        logger.info("enrichment_cache table created successfully")
    else:
        logger.info("enrichment_cache table already exists, skipping creation")

    logger.info("Enrichment cache schema migration (v15) completed successfully")


def _upgrade_to_v16(connection: Connection) -> None:
    """Upgrade to schema version 16: Implement three-tier enrichment architecture (ADR-007).

    This migration implements the three-tier architecture for IP/ASN enrichment normalization:
    - Tier 1: ASN inventory (most stable, organization-level)
    - Tier 2: IP inventory (current state, mutable enrichment)
    - Tier 3: Session summaries (point-in-time snapshots, immutable)

    The migration follows a four-phase approach:
    1. Create and populate ASN inventory from existing session data
    2. Create and populate IP inventory with computed columns
    3. Add snapshot columns to session_summaries for fast queries
    4. Add foreign key constraints using NOT VALID → VALIDATE pattern
    """
    logger.info("Starting three-tier enrichment architecture migration (v16)...")

    dialect_name = connection.dialect.name

    # Only apply to PostgreSQL (SQLite doesn't support required features)
    if dialect_name != "postgresql":
        logger.info("Three-tier enrichment architecture (v16) requires PostgreSQL, skipping for SQLite")
        return

    # ==========================================
    # PHASE 1: SESSION SOURCE_IP COLUMN
    # ==========================================
    logger.info("Phase 1: Adding source_ip column to session_summaries...")

    # Add source_ip column first (required by later phases)
    if not _column_exists(connection, "session_summaries", "source_ip"):
        _safe_execute_sql(
            connection,
            "ALTER TABLE session_summaries ADD COLUMN source_ip VARCHAR(45)",
            "Add source_ip column to session_summaries",
        )

    # Populate source_ip from enrichment JSONB
    logger.info("Populating source_ip from enrichment data...")
    if not _safe_execute_sql(
        connection,
        """
        UPDATE session_summaries
        SET source_ip = enrichment->'dshield'->'ip'->>'number'
        WHERE source_ip IS NULL
          AND enrichment->'dshield'->'ip'->>'number' IS NOT NULL
        """,
        "Populate source_ip from DShield enrichment",
    ):
        logger.warning("Failed to populate source_ip - some sessions may lack IP data")

    # Create index on source_ip for JOIN performance (used by Phase 2 & 3)
    _safe_execute_sql(
        connection,
        "CREATE INDEX IF NOT EXISTS idx_session_source_ip ON session_summaries(source_ip)",
        "Create index on source_ip",
    )

    # ==========================================
    # PHASE 2: ASN INVENTORY TABLE
    # ==========================================
    logger.info("Phase 2: Creating ASN inventory table...")

    if not _table_exists(connection, "asn_inventory"):
        if not _safe_execute_sql(
            connection,
            """
            CREATE TABLE asn_inventory (
                asn_number            INTEGER PRIMARY KEY CHECK (asn_number > 0),
                organization_name     TEXT,
                organization_country  VARCHAR(2)
                    CHECK (organization_country IS NULL OR organization_country ~ '^[A-Z]{2}$'),
                registry              VARCHAR(10),
                asn_type              TEXT,
                is_known_hosting      BOOLEAN DEFAULT false,
                is_known_vpn          BOOLEAN DEFAULT false,

                -- Aggregate statistics
                first_seen            TIMESTAMPTZ NOT NULL,
                last_seen             TIMESTAMPTZ NOT NULL,
                unique_ip_count       INTEGER DEFAULT 0,
                total_session_count   INTEGER DEFAULT 0,

                -- Full enrichment
                enrichment            JSONB DEFAULT '{}'::jsonb,
                enrichment_updated_at TIMESTAMPTZ,

                created_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL,
                updated_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL
            )
            """,
            "Create asn_inventory table",
        ):
            raise Exception("Failed to create asn_inventory table")

        logger.info("Created asn_inventory table successfully")
    else:
        logger.info("asn_inventory table already exists, skipping creation")

    # Create indexes for ASN inventory
    asn_indexes = [
        ("idx_asn_org_name", "asn_inventory(organization_name)"),
        ("idx_asn_type", "asn_inventory(asn_type)"),
        ("idx_asn_session_count", "asn_inventory(total_session_count DESC)"),
    ]

    for index_name, index_def in asn_indexes:
        _safe_execute_sql(
            connection, f"CREATE INDEX IF NOT EXISTS {index_name} ON {index_def}", f"Create {index_name} index"
        )

    # Populate ASN inventory from session_summaries
    logger.info("Populating ASN inventory from existing session data...")

    if not _safe_execute_sql(
        connection,
        """
        WITH asn_aggregates AS (
            SELECT
                (enrichment->'cymru'->>'asn')::int as asn,
                MIN(first_event_at) as first_seen,
                MAX(last_event_at) as last_seen,
                COUNT(DISTINCT source_ip) as unique_ip_count,
                COUNT(*) as total_session_count
            FROM session_summaries
            WHERE enrichment->'cymru'->>'asn' IS NOT NULL
              AND (enrichment->'cymru'->>'asn')::int > 0
            GROUP BY (enrichment->'cymru'->>'asn')::int
        ),
        latest_enrichment AS (
            SELECT DISTINCT ON ((enrichment->'cymru'->>'asn')::int)
                (enrichment->'cymru'->>'asn')::int as asn,
                enrichment
            FROM session_summaries
            WHERE enrichment->'cymru'->>'asn' IS NOT NULL
              AND (enrichment->'cymru'->>'asn')::int > 0
            ORDER BY (enrichment->'cymru'->>'asn')::int, last_event_at DESC
        )
        INSERT INTO asn_inventory (
            asn_number, first_seen, last_seen, unique_ip_count, total_session_count,
            enrichment, enrichment_updated_at
        )
        SELECT
            a.asn,
            a.first_seen,
            a.last_seen,
            a.unique_ip_count,
            a.total_session_count,
            e.enrichment,
            NULL  -- Force re-enrichment for staleness tracking
        FROM asn_aggregates a
        JOIN latest_enrichment e ON a.asn = e.asn
        ON CONFLICT (asn_number) DO NOTHING
        """,
        "Populate ASN inventory from session summaries",
    ):
        logger.warning("Failed to populate ASN inventory - continuing with migration")

    # ==========================================
    # PHASE 3: IP INVENTORY TABLE
    # ==========================================
    logger.info("Phase 3: Creating IP inventory table...")

    if not _table_exists(connection, "ip_inventory"):
        if not _safe_execute_sql(
            connection,
            """
            CREATE TABLE ip_inventory (
                ip_address            INET PRIMARY KEY,

                -- Current ASN (mutable)
                current_asn           INTEGER,
                asn_last_verified     TIMESTAMPTZ,

                -- Temporal tracking
                first_seen            TIMESTAMPTZ NOT NULL,
                last_seen             TIMESTAMPTZ NOT NULL,
                session_count         INTEGER DEFAULT 1 CHECK (session_count >= 0),

                -- Current enrichment (MUTABLE)
                enrichment            JSONB NOT NULL DEFAULT '{}'::jsonb,
                enrichment_updated_at TIMESTAMPTZ,
                enrichment_version    VARCHAR(20) DEFAULT '2.2',

                -- Computed columns (defensive defaults)
                geo_country           VARCHAR(2) GENERATED ALWAYS AS (
                    UPPER(COALESCE(
                        enrichment->'maxmind'->>'country',
                        enrichment->'cymru'->>'country',
                        enrichment->'dshield'->'ip'->>'ascountry',
                        'XX'
                    ))
                ) STORED,

                ip_types              TEXT[] GENERATED ALWAYS AS (
                    COALESCE(
                      CASE
                        WHEN jsonb_typeof(enrichment->'spur'->'client'->'types') = 'array'
                          THEN ARRAY(SELECT jsonb_array_elements_text(enrichment->'spur'->'client'->'types'))
                        WHEN jsonb_typeof(enrichment->'spur'->'client'->'types') = 'string'
                          THEN ARRAY[(enrichment->'spur'->'client'->>'types')]
                        ELSE ARRAY[]::text[]
                      END,
                      ARRAY[]::text[]
                    )
                ) STORED,

                is_scanner            BOOLEAN GENERATED ALWAYS AS (
                    COALESCE((enrichment->'greynoise'->>'noise')::boolean, false)
                ) STORED,

                is_bogon              BOOLEAN GENERATED ALWAYS AS (
                    COALESCE((enrichment->'validation'->>'is_bogon')::boolean, false)
                ) STORED,

                created_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL,
                updated_at            TIMESTAMPTZ DEFAULT NOW() NOT NULL
            )
            """,
            "Create ip_inventory table",
        ):
            raise Exception("Failed to create ip_inventory table")

        logger.info("Created ip_inventory table successfully")
    else:
        logger.info("ip_inventory table already exists, skipping creation")

    # Create indexes for IP inventory
    ip_indexes = [
        ("idx_ip_current_asn", "ip_inventory(current_asn)"),
        ("idx_ip_geo_country", "ip_inventory(geo_country)"),
        ("idx_ip_session_count", "ip_inventory(session_count DESC)"),
        ("idx_ip_enrichment_updated", "ip_inventory(enrichment_updated_at)"),
        (
            "idx_ip_staleness_active",
            "ip_inventory(enrichment_updated_at, last_seen) WHERE enrichment_updated_at IS NOT NULL",
        ),
    ]

    for index_name, index_def in ip_indexes:
        _safe_execute_sql(
            connection, f"CREATE INDEX IF NOT EXISTS {index_name} ON {index_def}", f"Create {index_name} index"
        )

    # Populate IP inventory from session_summaries
    logger.info("Populating IP inventory from existing session data...")

    if not _safe_execute_sql(
        connection,
        """
        INSERT INTO ip_inventory (
            ip_address, first_seen, last_seen, session_count,
            current_asn, enrichment, enrichment_updated_at
        )
        SELECT DISTINCT ON (source_ip)
            source_ip,
            MIN(first_event_at) OVER (PARTITION BY source_ip) as first_seen,
            MAX(last_event_at) OVER (PARTITION BY source_ip) as last_seen,
            COUNT(*) OVER (PARTITION BY source_ip) as session_count,
            (enrichment->'cymru'->>'asn')::int as current_asn,
            enrichment,
            NULL as enrichment_updated_at
        FROM session_summaries
        WHERE source_ip IS NOT NULL
        ORDER BY source_ip, last_event_at DESC
        ON CONFLICT (ip_address) DO NOTHING
        """,
        "Populate IP inventory from session summaries",
    ):
        logger.warning("Failed to populate IP inventory - continuing with migration")

    # ==========================================
    # PHASE 4: SESSION SNAPSHOT COLUMNS
    # ==========================================
    logger.info("Phase 4: Adding remaining snapshot columns to session_summaries...")

    # Convert timestamp columns to TIMESTAMPTZ if needed
    _safe_execute_sql(
        connection,
        """
        ALTER TABLE session_summaries
          ALTER COLUMN first_event_at TYPE TIMESTAMPTZ USING first_event_at AT TIME ZONE 'UTC',
          ALTER COLUMN last_event_at TYPE TIMESTAMPTZ USING last_event_at AT TIME ZONE 'UTC'
        """,
        "Convert session timestamp columns to TIMESTAMPTZ",
    )

    # Add snapshot columns
    snapshot_columns = [
        ("enrichment_at", "TIMESTAMPTZ"),
        ("snapshot_asn", "INTEGER"),
        ("snapshot_country", "VARCHAR(2)"),
        ("snapshot_ip_types", "TEXT[]"),
    ]

    for column_name, column_type in snapshot_columns:
        if not _column_exists(connection, "session_summaries", column_name):
            _safe_execute_sql(
                connection,
                f"ALTER TABLE session_summaries ADD COLUMN {column_name} {column_type}",
                f"Add {column_name} column to session_summaries",
            )

    # Add constraints
    _safe_execute_sql(
        connection,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.check_constraints
                WHERE constraint_name = 'snapshot_country_iso'
            ) THEN
                ALTER TABLE session_summaries
                ADD CONSTRAINT snapshot_country_iso
                CHECK (snapshot_country IS NULL OR snapshot_country ~ '^[A-Z]{2}$');
            END IF;
        END $$
        """,
        "Add snapshot_country_iso constraint",
    )

    # Set source_ip NOT NULL
    _safe_execute_sql(
        connection,
        "ALTER TABLE session_summaries ALTER COLUMN source_ip SET NOT NULL",
        "Set source_ip as NOT NULL",
    )

    # Backfill snapshot columns
    logger.info("Backfilling snapshot columns (this may take a while)...")

    if not _safe_execute_sql(
        connection,
        """
        CREATE TEMP TABLE tmp_session_snapshots AS
        SELECT
          s.session_id,
          COALESCE(
            (s.enrichment->>'enriched_at')::timestamptz,
            s.created_at,
            s.last_event_at
          ) AS enrichment_at,
          (s.enrichment->'cymru'->>'asn')::int AS snapshot_asn,
          UPPER(COALESCE(
            s.enrichment->'maxmind'->>'country',
            s.enrichment->'cymru'->>'country'
          )) AS snapshot_country,
          COALESCE(
            CASE
              WHEN jsonb_typeof(s.enrichment->'spur'->'client'->'types') = 'array'
                THEN ARRAY(SELECT jsonb_array_elements_text(s.enrichment->'spur'->'client'->'types'))
              WHEN jsonb_typeof(s.enrichment->'spur'->'client'->'types') = 'string'
                THEN ARRAY[(s.enrichment->'spur'->'client'->>'types')]
              ELSE ARRAY[]::text[]
            END,
            ARRAY[]::text[]
          ) AS snapshot_ip_types
        FROM session_summaries s
        """,
        "Create temporary snapshot table",
    ):
        logger.warning("Failed to create temporary snapshot table")
    else:
        _safe_execute_sql(
            connection,
            """
            UPDATE session_summaries s
            SET enrichment_at = t.enrichment_at,
                snapshot_asn = t.snapshot_asn,
                snapshot_country = t.snapshot_country,
                snapshot_ip_types = t.snapshot_ip_types
            FROM tmp_session_snapshots t
            WHERE s.session_id = t.session_id
            """,
            "Backfill snapshot columns from temp table",
        )

        _safe_execute_sql(connection, "DROP TABLE tmp_session_snapshots", "Drop temporary snapshot table")

    # Create indexes for snapshot columns (source_ip index already created in Phase 1)
    snapshot_indexes = [
        ("idx_session_first_event_brin", "session_summaries USING brin (first_event_at)"),
        ("idx_session_last_event_brin", "session_summaries USING brin (last_event_at)"),
        ("idx_session_snapshot_asn", "session_summaries(snapshot_asn)"),
        ("idx_session_snapshot_country", "session_summaries(snapshot_country)"),
    ]

    for index_name, index_def in snapshot_indexes:
        _safe_execute_sql(
            connection, f"CREATE INDEX IF NOT EXISTS {index_name} ON {index_def}", f"Create {index_name} index"
        )

    # ==========================================
    # PHASE 5: FOREIGN KEY CONSTRAINTS
    # ==========================================
    logger.info("Phase 5: Adding foreign key constraints...")

    # Pre-validation to avoid orphans
    _safe_execute_sql(
        connection,
        """
        DO $$
        DECLARE
            orphan_sessions INTEGER;
            orphan_ips INTEGER;
        BEGIN
            SELECT COUNT(*) INTO orphan_sessions
            FROM session_summaries s
            WHERE NOT EXISTS (SELECT 1 FROM ip_inventory i WHERE i.ip_address = s.source_ip);

            IF orphan_sessions > 0 THEN
                RAISE WARNING 'Found % orphan sessions without IP inventory entries', orphan_sessions;
            END IF;

            SELECT COUNT(*) INTO orphan_ips
            FROM ip_inventory i
            WHERE current_asn IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM asn_inventory a WHERE a.asn_number = i.current_asn);

            IF orphan_ips > 0 THEN
                RAISE WARNING 'Found % IPs with invalid ASNs', orphan_ips;
            END IF;
        END $$
        """,
        "Pre-validate foreign key integrity",
    )

    # Add foreign keys using NOT VALID → VALIDATE pattern
    _safe_execute_sql(
        connection,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'fk_ip_current_asn'
            ) THEN
                ALTER TABLE ip_inventory
                ADD CONSTRAINT fk_ip_current_asn
                FOREIGN KEY (current_asn) REFERENCES asn_inventory(asn_number) NOT VALID;
            END IF;
        END $$
        """,
        "Add ip_inventory → asn_inventory FK (NOT VALID)",
    )

    _safe_execute_sql(
        connection,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'fk_session_source_ip'
            ) THEN
                ALTER TABLE session_summaries
                ADD CONSTRAINT fk_session_source_ip
                FOREIGN KEY (source_ip) REFERENCES ip_inventory(ip_address) NOT VALID;
            END IF;
        END $$
        """,
        "Add session_summaries → ip_inventory FK (NOT VALID)",
    )

    # Validate constraints
    _safe_execute_sql(
        connection, "ALTER TABLE ip_inventory VALIDATE CONSTRAINT fk_ip_current_asn", "Validate ASN FK constraint"
    )

    _safe_execute_sql(
        connection,
        "ALTER TABLE session_summaries VALIDATE CONSTRAINT fk_session_source_ip",
        "Validate IP FK constraint",
    )

    logger.info("Three-tier enrichment architecture migration (v16) completed successfully")


def _downgrade_from_v9(connection: Connection) -> None:
    """Rollback v9 migration if needed."""
    logger.info("Rolling back longtail analysis tables...")

    try:
        # Drop tables in reverse order of dependencies
        _safe_execute_sql(
            connection, "DROP TABLE IF EXISTS longtail_detections CASCADE", "Drop longtail_detections table"
        )

        _safe_execute_sql(connection, "DROP TABLE IF EXISTS longtail_analysis CASCADE", "Drop longtail_analysis table")

        # If using PostgreSQL with pgvector, drop vector tables
        if connection.dialect.name == 'postgresql':
            _safe_execute_sql(
                connection,
                "DROP TABLE IF EXISTS command_sequence_vectors CASCADE",
                "Drop command_sequence_vectors table",
            )

            _safe_execute_sql(
                connection, "DROP TABLE IF EXISTS behavioral_vectors CASCADE", "Drop behavioral_vectors table"
            )

        # Update schema version
        _safe_execute_sql(
            connection,
            f"UPDATE schema_metadata SET value = '8' WHERE key = '{SCHEMA_VERSION_KEY}'",
            "Update schema version to 8",
        )

        logger.info("Rollback to v8 complete")

    except Exception as e:
        logger.error(f"Rollback failed: {e}")


__all__ = ["apply_migrations", "CURRENT_SCHEMA_VERSION", "SCHEMA_VERSION_KEY"]
