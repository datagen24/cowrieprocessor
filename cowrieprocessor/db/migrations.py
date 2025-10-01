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
CURRENT_SCHEMA_VERSION = 6

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
        logger.warning(f"Failed to execute SQL ({description}): {e}")
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
    return version


def _upgrade_to_v2(connection: Connection) -> None:
    """Upgrade to v2 schema by adding source_generation column and unique index."""
    if not _column_exists(connection, "raw_events", "source_generation"):
        _safe_execute_sql(
            connection,
            "ALTER TABLE raw_events ADD COLUMN source_generation INTEGER NOT NULL DEFAULT 0",
            "Add source_generation column"
        )
    
    _safe_execute_sql(
        connection,
        "UPDATE raw_events SET source_generation=0 WHERE source_generation IS NULL",
        "Set default source_generation values"
    )
    
    _safe_execute_sql(
        connection,
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_events_source_gen "
        "ON raw_events(source, source_inode, source_generation, source_offset)",
        "Create unique index on raw_events"
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
        f"Add enrichment column ({column_type})"
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
                f"Update {table_name}.{column_name} default to false (PostgreSQL)"
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
    
    # Add real columns for extracted JSON fields if they don't exist
    if not _column_exists(connection, "raw_events", "session_id"):
        _safe_execute_sql(
            connection,
            "ALTER TABLE raw_events ADD COLUMN session_id VARCHAR(64)",
            "Add session_id column"
        )
        _safe_execute_sql(
            connection,
            "CREATE INDEX ix_raw_events_session_id ON raw_events(session_id)",
            "Create session_id index"
        )
    
    if not _column_exists(connection, "raw_events", "event_type"):
        _safe_execute_sql(
            connection,
            "ALTER TABLE raw_events ADD COLUMN event_type VARCHAR(128)",
            "Add event_type column"
        )
        _safe_execute_sql(
            connection,
            "CREATE INDEX ix_raw_events_event_type ON raw_events(event_type)",
            "Create event_type index"
        )
    
    if not _column_exists(connection, "raw_events", "event_timestamp"):
        _safe_execute_sql(
            connection,
            "ALTER TABLE raw_events ADD COLUMN event_timestamp VARCHAR(64)",
            "Add event_timestamp column"
        )
        _safe_execute_sql(
            connection,
            "CREATE INDEX ix_raw_events_event_timestamp ON raw_events(event_timestamp)",
            "Create event_timestamp index"
        )
    
    # Populate the new columns with data extracted from JSON payload
    # Use dialect-aware JSON extraction
    if dialect_name == "postgresql":
        # PostgreSQL JSON extraction
        _safe_execute_sql(
            connection,
            "UPDATE raw_events SET session_id = payload->>'session' WHERE session_id IS NULL",
            "Populate session_id from JSON (PostgreSQL)"
        )
        
        _safe_execute_sql(
            connection,
            "UPDATE raw_events SET event_type = payload->>'eventid' WHERE event_type IS NULL",
            "Populate event_type from JSON (PostgreSQL)"
        )
        
        _safe_execute_sql(
            connection,
            "UPDATE raw_events SET event_timestamp = payload->>'timestamp' WHERE event_timestamp IS NULL",
            "Populate event_timestamp from JSON (PostgreSQL)"
        )
    else:
        # SQLite JSON extraction
        _safe_execute_sql(
            connection,
            "UPDATE raw_events SET session_id = json_extract(payload, '$.session') WHERE session_id IS NULL",
            "Populate session_id from JSON (SQLite)"
        )
        
        _safe_execute_sql(
            connection,
            "UPDATE raw_events SET event_type = json_extract(payload, '$.eventid') WHERE event_type IS NULL",
            "Populate event_type from JSON (SQLite)"
        )
        
        _safe_execute_sql(
            connection,
            "UPDATE raw_events SET event_timestamp = json_extract(payload, '$.timestamp') WHERE event_timestamp IS NULL",
            "Populate event_timestamp from JSON (SQLite)"
        )


__all__ = ["apply_migrations", "CURRENT_SCHEMA_VERSION", "SCHEMA_VERSION_KEY"]
