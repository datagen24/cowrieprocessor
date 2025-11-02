"""Shared database configuration for CLI tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..settings import DatabaseSettings, load_database_settings


def _load_sensors_config() -> dict[str, str] | None:
    """Load database configuration from sensors.toml if available.

    Returns:
        Database configuration dict with 'url' key, or None if not found
    """
    # Try config/ directory first, then fall back to current directory
    sensors_file = Path("config/sensors.toml")
    if not sensors_file.exists():
        sensors_file = Path("sensors.toml")
    if not sensors_file.exists():
        return None

    try:
        # Try tomllib first (Python 3.11+)
        try:
            import tomllib

            toml_loader = tomllib
        except ImportError:
            # Fall back to tomli for older Python versions
            import tomli

            toml_loader = tomli

        with sensors_file.open("rb") as handle:
            data = toml_loader.load(handle)

        # Check for global database configuration
        global_config = data.get("global", {})
        db_url = global_config.get("db")
        if db_url:
            return {"url": db_url}

    except Exception:
        # If sensors.toml doesn't exist or can't be parsed, fall back to default
        pass

    return None


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
