"""Schema migration helpers for the Cowrie processor database."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, cast

from sqlalchemy import Table, select, update
from sqlalchemy.engine import Connection, Engine

from .base import Base
from .models import SchemaState

SCHEMA_VERSION_KEY = "schema_version"
CURRENT_SCHEMA_VERSION = 1


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
    with begin_connection(engine) as connection:
        Base.metadata.create_all(bind=connection)
        version = _get_schema_version(connection)
        if version < CURRENT_SCHEMA_VERSION:
            _set_schema_version(connection, CURRENT_SCHEMA_VERSION)
            version = CURRENT_SCHEMA_VERSION
    return version


__all__ = ["apply_migrations", "CURRENT_SCHEMA_VERSION", "SCHEMA_VERSION_KEY"]
