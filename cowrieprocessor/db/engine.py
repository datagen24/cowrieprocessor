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


def detect_postgresql_support() -> bool:
    """Detect if PostgreSQL driver is available.

    Returns:
        True if psycopg driver is installed, False otherwise.
    """
    try:
        import psycopg  # noqa: F401

        return True
    except ImportError:
        return False


def _is_postgresql_url(url: str) -> bool:
    """Check if URL is a PostgreSQL connection string."""
    return url.startswith("postgresql://") or url.startswith("postgres://")


def create_engine_with_fallback(settings: DatabaseSettings) -> Engine:
    """Create engine with graceful PostgreSQL fallback.

    Args:
        settings: Database configuration settings.

    Returns:
        Configured SQLAlchemy engine.

    Raises:
        ValueError: If PostgreSQL URL is provided but driver is not installed.
    """
    if _is_postgresql_url(settings.url) and not detect_postgresql_support():
        raise ValueError("PostgreSQL driver not installed. Install with: uv pip install -e '.[postgres]'")
    return create_engine_from_settings(settings)


def _is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite:")


def _needs_static_pool(url: str) -> bool:
    return any(identifier in url for identifier in _SQLITE_MEMORY_IDENTIFIERS)


def _sqlite_on_connect(settings: DatabaseSettings):
    def configure(dbapi_connection: sqlite3.Connection, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=5000")
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
    url = settings.url
    
    # Convert PostgreSQL URLs to use psycopg driver explicitly
    if _is_postgresql_url(url) and not url.startswith("postgresql+psycopg://"):
        url = url.replace("postgresql://", "postgresql+psycopg://").replace("postgres://", "postgresql+psycopg://")
    
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

    if _is_sqlite_url(url):
        connect_args["check_same_thread"] = False
        if _needs_static_pool(url):
            engine_kwargs["poolclass"] = StaticPool
            # Remove pool_timeout for StaticPool as it's not supported
            engine_kwargs.pop("pool_timeout", None)
        engine = create_engine(url, connect_args=connect_args, **engine_kwargs)
        event.listen(engine, "connect", _sqlite_on_connect(settings))
        return engine

    engine = create_engine(url, connect_args=connect_args, **engine_kwargs)
    return engine


def create_session_maker(engine: Engine) -> sessionmaker[Session]:
    """Return a configured session factory for the given engine."""
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, future=True)


__all__ = [
    "create_engine_from_settings",
    "create_session_maker",
    "detect_postgresql_support",
    "create_engine_with_fallback",
]
