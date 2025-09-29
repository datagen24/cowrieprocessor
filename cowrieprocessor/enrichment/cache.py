"""Caching helpers for enrichment services."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, ClassVar, Dict


@dataclass(slots=True)
class EnrichmentCacheManager:
    """Manage on-disk caches for enrichment responses.

    The manager shards cache entries by service and the first bytes of a
    deterministic hash, applies per-service TTLs, and keeps simple hit/miss
    telemetry counters for status reporting.
    """

    base_dir: Path
    ttls: Dict[str, int] = field(default_factory=dict)
    stats: Dict[str, int] = field(default_factory=lambda: {"hits": 0, "misses": 0, "stores": 0})

    DEFAULT_TTLS: ClassVar[Dict[str, int]] = {
        "virustotal": 30 * 24 * 3600,
        "virustotal_unknown": 12 * 3600,
        "dshield": 7 * 24 * 3600,
        "urlhaus": 3 * 24 * 3600,
        "spur": 14 * 24 * 3600,
    }

    def __post_init__(self) -> None:
        """Ensure cache directory exists and merge TTL defaults."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        merged_ttls = dict(self.DEFAULT_TTLS)
        merged_ttls.update(self.ttls)
        self.ttls = merged_ttls

    def get_path(self, service: str, cache_key: str) -> Path:
        """Return the filesystem path for a given service/key pair."""
        digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
        shard = digest[:2]
        return self.base_dir / service / shard / f"{digest}.json"

    def load_text(self, service: str, cache_key: str) -> str | None:
        """Return cached payload if present and within the TTL budget."""
        cache_path = self.get_path(service, cache_key)
        if not cache_path.exists():
            self.stats["misses"] += 1
            return None
        if not self._is_valid(cache_path, service):
            self.stats["misses"] += 1
            try:
                cache_path.unlink()
            except OSError:
                pass
            return None
        try:
            payload = cache_path.read_text(encoding="utf-8")
        except OSError:
            self.stats["misses"] += 1
            return None
        self.stats["hits"] += 1
        return payload

    def store_text(self, service: str, cache_key: str, payload: str) -> None:
        """Persist payload to the cache."""
        cache_path = self.get_path(service, cache_key)
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(payload, encoding="utf-8")
            self.stats["stores"] += 1
        except OSError:
            # Cache writes are best-effort; caller should continue regardless.
            pass

    def snapshot(self) -> Dict[str, int]:
        """Return a copy of the current cache telemetry counters."""
        return dict(self.stats)

    def cleanup_expired(self, *, now: Callable[[], float] | None = None) -> Dict[str, int]:
        """Remove cache entries older than their configured TTLs.

        Args:
            now: Optional callable returning the current epoch timestamp. Primarily
                used by tests to provide deterministic timings.

        Returns:
            Dictionary summarising the cleanup activity with ``scanned`` and
            ``deleted`` counters plus ``errors`` encountered while deleting.
        """
        stats = {"scanned": 0, "deleted": 0, "errors": 0}
        timestamp = now() if now is not None else time.time()

        for service_dir in self.base_dir.iterdir():
            if not service_dir.is_dir():
                continue

            ttl_seconds = self.ttls.get(service_dir.name, self.ttls.get("default", 0))
            if ttl_seconds <= 0:
                continue

            cutoff = timestamp - ttl_seconds

            for shard_dir in service_dir.iterdir():
                if not shard_dir.is_dir():
                    continue

                for cache_file in shard_dir.glob("*.json"):
                    stats["scanned"] += 1
                    try:
                        if cache_file.stat().st_mtime < cutoff:
                            cache_file.unlink()
                            stats["deleted"] += 1
                    except FileNotFoundError:
                        # Raced with another cleanup or concurrent unlink; ignore.
                        continue
                    except OSError:
                        stats["errors"] += 1

        return stats

    def _is_valid(self, cache_path: Path, service: str) -> bool:
        """Return True if cache file is still within the TTL window."""
        ttl_seconds = self.ttls.get(service, self.ttls.get("default", 0))
        if ttl_seconds <= 0:
            return True
        try:
            mtime = cache_path.stat().st_mtime
        except OSError:
            return False
        age = datetime.now(timezone.utc).timestamp() - mtime
        return age < ttl_seconds


__all__ = ["EnrichmentCacheManager"]
