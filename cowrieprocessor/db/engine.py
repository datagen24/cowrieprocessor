"""Engine and session helpers for the refactored pipeline."""

from __future__ import annotations

import sqlite3
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from ..settings import DatabaseSettings

_SQLITE_MEMORY_IDENTIFIERS = {":memory:", "file::memory:"}


def _is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite:")


def _needs_static_pool(url: str) -> bool:
    return any(identifier in url for identifier in _SQLITE_MEMORY_IDENTIFIERS)


def _sqlite_on_connect(settings: DatabaseSettings):
    def configure(dbapi_connection: sqlite3.Connection, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            journal_mode = None
            if settings.sqlite_wal:
                try:
                    cursor.execute("PRAGMA journal_mode=WAL")
                    row = cursor.fetchone()
                    if row:
                        journal_mode = str(row[0]).upper()
                except sqlite3.DatabaseError:
                    journal_mode = None

            if journal_mode != "WAL" and settings.sqlite_journal_fallback:
                cursor.execute(f"PRAGMA journal_mode={settings.sqlite_journal_fallback}")
                cursor.fetchone()

            cursor.execute(f"PRAGMA synchronous={settings.sqlite_synchronous}")
            cursor.execute(f"PRAGMA cache_size={settings.sqlite_cache_size}")
        finally:
            cursor.close()

    return configure


def create_engine_from_settings(settings: DatabaseSettings) -> Engine:
    """Create a SQLAlchemy engine configured for the target backend."""
    engine_kwargs: dict[str, Any] = {
        "echo": settings.echo,
        "future": True,
        "pool_pre_ping": True,
    }

    if settings.pool_size:
        engine_kwargs["pool_size"] = settings.pool_size
    if settings.pool_timeout is not None:
        engine_kwargs["pool_timeout"] = settings.pool_timeout

    connect_args: dict[str, Any] = {}

    if _is_sqlite_url(settings.url):
        connect_args["check_same_thread"] = False
        if _needs_static_pool(settings.url):
            engine_kwargs["poolclass"] = StaticPool
        engine = create_engine(settings.url, connect_args=connect_args, **engine_kwargs)
        event.listen(engine, "connect", _sqlite_on_connect(settings))
        return engine

    engine = create_engine(settings.url, connect_args=connect_args or None, **engine_kwargs)
    return engine


def create_session_maker(engine: Engine) -> sessionmaker[Session]:
    """Return a configured session factory for the given engine."""
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, future=True)


__all__ = ["create_engine_from_settings", "create_session_maker"]
