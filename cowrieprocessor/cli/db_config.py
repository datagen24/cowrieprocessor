"""Shared database and cache configuration for CLI tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ..settings import DatabaseSettings, load_database_settings
from ..utils.config import _load_sensors_config, load_redis_config


def resolve_database_settings(db_arg: str | None = None) -> DatabaseSettings:
    """Resolve database settings from argument or configuration.

    This function provides a consistent way for all CLI tools to load database
    configuration. It follows this priority order:
    1. Explicit --db-url argument
    2. sensors.toml configuration file
    3. Environment variables (COWRIEPROC_DB_URL, COWRIEPROC_DB_PATH)
    4. Default SQLite database

    Args:
        db_arg: Database URL argument from CLI

    Returns:
        Database settings object configured for the target database
    """
    if not db_arg:
        # Try to load from sensors.toml first, then fall back to environment/default
        config = _load_sensors_config()
        if config:
            return load_database_settings(config=config)
        return load_database_settings()

    if db_arg.startswith("sqlite:"):
        return load_database_settings(config={"url": db_arg})

    db_path = Path(db_arg)
    if db_path.exists() or db_arg.endswith(".sqlite"):
        return DatabaseSettings(url=f"sqlite:///{db_path.resolve()}")

    return load_database_settings(config={"url": db_arg})


def add_database_argument(parser: Any, help_text: str | None = None) -> None:
    """Add standard database argument to an argument parser.

    Args:
        parser: ArgumentParser instance to add the argument to
        help_text: Custom help text for the database argument
    """
    default_help = (
        "Database connection URL (SQLite or PostgreSQL). If not provided, will read from sensors.toml or use default."
    )

    parser.add_argument("--db-url", default=None, help=help_text or default_help)


__all__ = ["resolve_database_settings", "add_database_argument", "load_redis_config"]
