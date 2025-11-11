"""Configuration loading utilities for sensors.toml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _load_sensors_config() -> dict[str, Any] | None:
    """Load global configuration from sensors.toml if available.

    Returns:
        Configuration dict with 'url', 'data_dir', and optional 'cache' keys, or None if not found
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

        # Check for global configuration
        global_config = data.get("global", {})

        config: dict[str, Any] = {}

        # Load database configuration
        db_url = global_config.get("db")
        if db_url:
            config["url"] = db_url

        # Load data directory configuration
        data_dir = global_config.get("data_dir")
        if data_dir:
            config["data_dir"] = data_dir

        # Load cache configuration (Redis settings)
        cache_config = global_config.get("cache", {})
        if cache_config:
            config["cache"] = cache_config

        return config if config else None

    except (OSError, IOError) as e:
        # File not found or can't be read - fall back to default
        import logging

        logging.getLogger(__name__).debug(f"Could not read sensors.toml: {e}")
        return None
    except Exception as e:
        # TOML syntax errors or other parsing issues - log and fail gracefully
        import logging

        logging.getLogger(__name__).warning(f"Failed to parse sensors.toml: {e}. Using defaults.")
        return None


def load_redis_config() -> dict[str, Any]:
    """Load Redis and database cache configuration from sensors.toml or environment variables.

    Configuration priority:
    1. Environment variables (REDIS_*, ENABLE_DB_CACHE, etc.)
    2. sensors.toml [global.cache] section
    3. Default values

    Returns:
        Cache configuration dict with keys:
        - Redis settings: host, port, password, db, enabled, ttl
        - Database cache: db_cache_enabled
    """
    # Default configuration
    config = {
        "host": "localhost",
        "port": 6379,
        "password": None,
        "db": 0,
        "enabled": True,
        "ttl": 3600,
        "db_cache_enabled": True,  # NEW: Enable database L2 cache by default
    }

    # Load from sensors.toml if available
    toml_config = _load_sensors_config()
    if toml_config and "cache" in toml_config:
        cache_config = toml_config["cache"]

        if "redis_host" in cache_config:
            config["host"] = cache_config["redis_host"]
        if "redis_port" in cache_config:
            config["port"] = int(cache_config["redis_port"])
        if "redis_password" in cache_config:
            # Support secret references in password
            password = cache_config["redis_password"]
            if isinstance(password, str) and password.startswith("env:"):
                # Resolve environment variable reference
                env_var = password[4:]  # Remove "env:" prefix
                config["password"] = os.getenv(env_var)
            else:
                config["password"] = password
        if "redis_db" in cache_config:
            config["db"] = int(cache_config["redis_db"])
        if "redis_enabled" in cache_config:
            config["enabled"] = bool(cache_config["redis_enabled"])
        if "redis_ttl_seconds" in cache_config:
            config["ttl"] = int(cache_config["redis_ttl_seconds"])

        # NEW: Database cache configuration
        if "db_cache_enabled" in cache_config:
            config["db_cache_enabled"] = bool(cache_config["db_cache_enabled"])

    # Environment variables override TOML config
    redis_host = os.getenv("REDIS_HOST")
    if redis_host:
        config["host"] = redis_host
    redis_port = os.getenv("REDIS_PORT")
    if redis_port:
        config["port"] = int(redis_port)
    redis_password = os.getenv("REDIS_PASSWORD")
    if redis_password:
        config["password"] = redis_password
    redis_db = os.getenv("REDIS_DB")
    if redis_db:
        config["db"] = int(redis_db)
    if os.getenv("ENABLE_REDIS_CACHE"):
        config["enabled"] = os.getenv("ENABLE_REDIS_CACHE", "true").lower() in ("true", "1", "yes")
    redis_ttl = os.getenv("REDIS_TTL_SECONDS")
    if redis_ttl:
        config["ttl"] = int(redis_ttl)

    # NEW: Database cache environment variable override
    if os.getenv("ENABLE_DB_CACHE"):
        config["db_cache_enabled"] = os.getenv("ENABLE_DB_CACHE", "true").lower() in ("true", "1", "yes")

    return config


def get_data_dir() -> Path:
    """Get data directory from sensors.toml or return default.

    Returns:
        Path to data directory, defaulting to /mnt/dshield/data if not configured

    Example:
        >>> data_dir = get_data_dir()
        >>> cache_dir = data_dir / "cache"
        >>> status_dir = data_dir / "logs" / "status"
    """
    config = _load_sensors_config()
    if config and "data_dir" in config:
        return Path(config["data_dir"])
    return Path("/mnt/dshield/data")


__all__ = ["load_redis_config", "get_data_dir"]
