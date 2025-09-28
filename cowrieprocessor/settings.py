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

    @classmethod
    def from_sources(
        cls,
        config: Mapping[str, Any] | None = None,
        env_prefix: str = "COWRIEPROC_",
    ) -> "DatabaseSettings":
        """Build settings from defaults, optional config mapping, and environment variables."""
        cfg: dict[str, Any] = {
            "url": f"sqlite:///{_DEFAULT_DB_PATH.resolve()}",
            "echo": False,
            "pool_size": None,
            "pool_timeout": 30,
            "sqlite_wal": True,
            "sqlite_cache_size": -64000,
            "sqlite_synchronous": "NORMAL",
            "sqlite_journal_fallback": "DELETE",
        }

        if config:
            cfg.update({k: v for k, v in config.items() if v is not None})

        env = os.environ
        prefix = env_prefix.upper()

        url_override = env.get(f"{prefix}DB_URL")
        if url_override:
            cfg["url"] = url_override
        else:
            path_override = env.get(f"{prefix}DB_PATH")
            if path_override:
                cfg["url"] = f"sqlite:///{Path(path_override).resolve()}"

        cfg["echo"] = _coerce_bool(env.get(f"{prefix}DB_ECHO"), bool(cfg["echo"]))

        pool_size = env.get(f"{prefix}DB_POOL_SIZE")
        if pool_size is not None:
            cfg["pool_size"] = _coerce_int(pool_size, cfg["pool_size"] or 0) or None

        cfg["pool_timeout"] = _coerce_int(env.get(f"{prefix}DB_POOL_TIMEOUT"), int(cfg["pool_timeout"]))
        cfg["sqlite_wal"] = _coerce_bool(env.get(f"{prefix}DB_SQLITE_WAL"), bool(cfg["sqlite_wal"]))
        cfg["sqlite_cache_size"] = _coerce_int(env.get(f"{prefix}DB_SQLITE_CACHE_SIZE"), int(cfg["sqlite_cache_size"]))

        sqlite_sync_override = env.get(f"{prefix}DB_SQLITE_SYNCHRONOUS")
        if sqlite_sync_override:
            cfg["sqlite_synchronous"] = sqlite_sync_override.strip().upper()

        journal_fallback_override = env.get(f"{prefix}DB_SQLITE_JOURNAL_FALLBACK")
        if journal_fallback_override:
            cfg["sqlite_journal_fallback"] = journal_fallback_override.strip().upper()

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
