"""Schema migration helpers for the Cowrie processor database."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, cast

from sqlalchemy import Table, inspect, select, text, update
from sqlalchemy.engine import Connection, Engine

from .base import Base
from .models import SchemaState

SCHEMA_VERSION_KEY = "schema_version"
CURRENT_SCHEMA_VERSION = 5


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
    return version


def _upgrade_to_v2(connection: Connection) -> None:
    inspector = inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("raw_events")}
    if "source_generation" not in columns:
        connection.execute(text("ALTER TABLE raw_events ADD COLUMN source_generation INTEGER NOT NULL DEFAULT 0"))
    connection.execute(text("UPDATE raw_events SET source_generation=0 WHERE source_generation IS NULL"))
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_events_source_gen "
            "ON raw_events(source, source_inode, source_generation, source_offset)"
        )
    )


def _upgrade_to_v3(connection: Connection) -> None:
    inspector = inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("session_summaries")}
    if "enrichment" in columns:
        return

    dialect_name = connection.dialect.name
    if dialect_name == "postgresql":
        column_type = "JSONB"
    else:
        column_type = "JSON"

    connection.execute(text(f"ALTER TABLE session_summaries ADD COLUMN enrichment {column_type}"))


def _upgrade_to_v4(connection: Connection) -> None:
    """Upgrade to v4 schema by creating the files table."""
    inspector = inspect(connection)

    # Check if files table already exists
    if "files" in inspector.get_table_names():
        return

    # Create the files table using SQLAlchemy's create_all
    # This will create the table with all the proper constraints and indexes
    from .models import Files

    Files.__table__.create(connection, checkfirst=True)


def _upgrade_to_v5(connection: Connection) -> None:
    """Upgrade to v5 schema by adding real columns for extracted JSON fields.
    
    This migration replaces SQLite-specific computed columns with real columns
    that work across both SQLite and PostgreSQL backends.
    """
    inspector = inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("raw_events")}
    
    # Add real columns for extracted JSON fields if they don't exist
    if "session_id" not in columns:
        connection.execute(text("ALTER TABLE raw_events ADD COLUMN session_id VARCHAR(64)"))
        connection.execute(text("CREATE INDEX ix_raw_events_session_id ON raw_events(session_id)"))
    
    if "event_type" not in columns:
        connection.execute(text("ALTER TABLE raw_events ADD COLUMN event_type VARCHAR(128)"))
        connection.execute(text("CREATE INDEX ix_raw_events_event_type ON raw_events(event_type)"))
    
    if "event_timestamp" not in columns:
        connection.execute(text("ALTER TABLE raw_events ADD COLUMN event_timestamp VARCHAR(64)"))
        connection.execute(text("CREATE INDEX ix_raw_events_event_timestamp ON raw_events(event_timestamp)"))
    
    # Populate the new columns with data extracted from JSON payload
    # This uses SQLite's json_extract function for backward compatibility
    connection.execute(text("""
        UPDATE raw_events 
        SET session_id = json_extract(payload, '$.session')
        WHERE session_id IS NULL
    """))
    
    connection.execute(text("""
        UPDATE raw_events 
        SET event_type = json_extract(payload, '$.eventid')
        WHERE event_type IS NULL
    """))
    
    connection.execute(text("""
        UPDATE raw_events 
        SET event_timestamp = json_extract(payload, '$.timestamp')
        WHERE event_timestamp IS NULL
    """))


__all__ = ["apply_migrations", "CURRENT_SCHEMA_VERSION", "SCHEMA_VERSION_KEY"]
