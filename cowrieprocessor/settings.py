"""Runtime configuration helpers for the Cowrie processor refactor."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping

from cowrieprocessor.enrichment import EnrichmentCacheManager

_DEFAULT_DB_PATH = Path("cowrieprocessor.sqlite")


def _coerce_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    return default


def _coerce_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


@dataclass(slots=True)
class DatabaseSettings:
    """Normalized database configuration used across loaders and reporters."""

    url: str
    echo: bool = False
    pool_size: int | None = None
    pool_timeout: int = 30
    sqlite_wal: bool = True
    sqlite_cache_size: int = -64000
    sqlite_synchronous: str = "NORMAL"
    sqlite_journal_fallback: str = "DELETE"
    enable_orm_sanitization: bool = True  # Phase 2: ORM-level Unicode sanitization

    @classmethod
    def from_sources(
        cls,
        config: Mapping[str, Any] | None = None,
        env_prefix: str = "COWRIEPROC_",
    ) -> "DatabaseSettings":
        """Build settings from defaults, optional config mapping, and environment variables.

        Precedence order (highest to lowest):
        1. Explicit config mapping values
        2. Environment variables
        3. Default values
        """
        cfg: dict[str, Any] = {
            "url": f"sqlite:///{_DEFAULT_DB_PATH.resolve()}",
            "echo": False,
            "pool_size": None,
            "pool_timeout": 30,
            "sqlite_wal": True,
            "sqlite_cache_size": -64000,
            "sqlite_synchronous": "NORMAL",
            "sqlite_journal_fallback": "DELETE",
            "enable_orm_sanitization": True,
        }

        # Track which keys were explicitly provided in config
        config_keys: set[str] = set()
        if config:
            config_keys = {k for k, v in config.items() if v is not None}
            cfg.update({k: v for k, v in config.items() if v is not None})

        env = os.environ
        prefix = env_prefix.upper()

        # Only apply env overrides for keys not in config
        if "url" not in config_keys:
            url_override = env.get(f"{prefix}DB_URL")
            if url_override:
                cfg["url"] = url_override
            else:
                path_override = env.get(f"{prefix}DB_PATH")
                if path_override:
                    cfg["url"] = f"sqlite:///{Path(path_override).resolve()}"

        if "echo" not in config_keys:
            cfg["echo"] = _coerce_bool(env.get(f"{prefix}DB_ECHO"), bool(cfg["echo"]))

        if "pool_size" not in config_keys:
            pool_size = env.get(f"{prefix}DB_POOL_SIZE")
            if pool_size is not None:
                coerced = _coerce_int(pool_size, -1)
                cfg["pool_size"] = coerced if coerced >= 0 else None

        if "pool_timeout" not in config_keys:
            cfg["pool_timeout"] = _coerce_int(env.get(f"{prefix}DB_POOL_TIMEOUT"), int(cfg["pool_timeout"]))

        if "sqlite_wal" not in config_keys:
            cfg["sqlite_wal"] = _coerce_bool(env.get(f"{prefix}DB_SQLITE_WAL"), bool(cfg["sqlite_wal"]))

        if "sqlite_cache_size" not in config_keys:
            cfg["sqlite_cache_size"] = _coerce_int(
                env.get(f"{prefix}DB_SQLITE_CACHE_SIZE"), int(cfg["sqlite_cache_size"])
            )

        if "sqlite_synchronous" not in config_keys:
            sqlite_sync_override = env.get(f"{prefix}DB_SQLITE_SYNCHRONOUS")
            if sqlite_sync_override:
                cfg["sqlite_synchronous"] = sqlite_sync_override.strip().upper()

        if "sqlite_journal_fallback" not in config_keys:
            journal_fallback_override = env.get(f"{prefix}DB_SQLITE_JOURNAL_FALLBACK")
            if journal_fallback_override:
                cfg["sqlite_journal_fallback"] = journal_fallback_override.strip().upper()

        if "enable_orm_sanitization" not in config_keys:
            cfg["enable_orm_sanitization"] = _coerce_bool(
                env.get(f"{prefix}ENABLE_ORM_SANITIZATION"), bool(cfg["enable_orm_sanitization"])
            )

        return cls(**cfg)


def load_database_settings(
    config: Mapping[str, Any] | None = None,
    env_prefix: str = "COWRIEPROC_",
) -> DatabaseSettings:
    """Convenience wrapper used by CLI entry points."""
    return DatabaseSettings.from_sources(config=config, env_prefix=env_prefix)


@dataclass(slots=True)
class EnrichmentSettings:
    """Runtime configuration controlling enrichment behaviour."""

    cache_dir: Path = Path.home() / ".cache" / "cowrieprocessor"
    cache_ttls: Dict[str, int] = field(default_factory=lambda: dict(EnrichmentCacheManager.DEFAULT_TTLS))
    rate_limits: Dict[str, int] = field(
        default_factory=lambda: {
            'virustotal': 4,
            'dshield': 100,
            'urlhaus': 60,
            'spur': 30,
        }
    )


__all__ = ["DatabaseSettings", "load_database_settings", "EnrichmentSettings"]
