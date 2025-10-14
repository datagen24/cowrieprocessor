"""Caching helpers for enrichment services."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path
from typing import Callable, ClassVar, Dict, Optional, Tuple

HEX_DIGITS = set("0123456789abcdefABCDEF")
CachePathBuilder = Callable[[str, str], Optional[Path]]


def _normalize_component(component: str, fallback: str = "__") -> str:
    """Return a filesystem-safe directory component.

    Args:
        component: Raw fragment that may be empty or contain whitespace.
        fallback: Placeholder to use when the component is empty.

    Returns:
        Sanitized component suitable for Path construction.
    """
    value = component.strip()
    return value if value else fallback


def _hibp_path_builder(cache_key: str, digest: str) -> Optional[Path]:
    """Return a three-level directory tree for HIBP SHA-1 prefixes.

    Args:
        cache_key: Original cache key (expected to be a 5-character SHA-1 prefix).
        digest: SHA-256 of the cache key used for compatibility fallbacks.

    Returns:
        Relative path inside the service directory, or None to defer to the default layout.
    """
    prefix = cache_key.strip().upper()
    if len(prefix) != 5 or any(ch not in HEX_DIGITS for ch in prefix):
        prefix = digest[:5].upper()

    part_one = _normalize_component(prefix[:2])
    part_two = _normalize_component(prefix[2:4])
    part_three = _normalize_component(prefix[4:])

    return Path(part_one) / part_two / part_three / f"{prefix}.json"


def _dshield_path_builder(cache_key: str, digest: str) -> Optional[Path]:
    """Return IPv4 octet directories for DShield cache keys when possible.

    Args:
        cache_key: DShield cache key, typically an IP address.
        digest: SHA-256 of the cache key used for compatibility fallbacks.

    Returns:
        Relative path inside the service directory, or None to fall back to the default layout.
    """
    try:
        ip_obj = ip_address(cache_key.strip())
    except ValueError:
        return None

    if ip_obj.version != 4:
        return None

    octets = str(ip_obj).split('.')
    return Path(octets[0]) / octets[1] / octets[2] / f"{octets[3]}.json"


def _hex_sharded_builder(cache_key: str, digest: str) -> Optional[Path]:
    """Shard hexadecimal identifiers (e.g., VirusTotal hashes) by byte pairs.

    Args:
        cache_key: Cache key expected to be a hexadecimal string.
        digest: SHA-256 of the cache key used for compatibility fallbacks.

    Returns:
        Relative path inside the service directory, or None to defer to the default layout.
    """
    key = cache_key.strip().lower()
    if not key or any(ch not in HEX_DIGITS for ch in key):
        return None

    parts = [key[i : i + 2] for i in range(0, min(len(key), 8), 2)]
    parts = [_normalize_component(part) for part in parts]
    filename = f"{key}.json"
    return Path(*parts) / filename


@dataclass(slots=True)
class EnrichmentCacheManager:
    """Manage on-disk caches for enrichment responses with service-specific layouts."""

    base_dir: Path
    ttls: Dict[str, int] = field(default_factory=dict)
    stats: Dict[str, int] = field(default_factory=lambda: {"hits": 0, "misses": 0, "stores": 0})

    DEFAULT_TTLS: ClassVar[Dict[str, int]] = {
        "virustotal": 30 * 24 * 3600,
        "virustotal_unknown": 12 * 3600,
        "dshield": 7 * 24 * 3600,
        "urlhaus": 3 * 24 * 3600,
        "spur": 14 * 24 * 3600,
        "hibp": 60 * 24 * 3600,  # 60 days - passwords don't change often
    }

    PATH_BUILDERS: ClassVar[Dict[str, CachePathBuilder]] = {
        "hibp": _hibp_path_builder,
        "dshield": _dshield_path_builder,
        "virustotal": _hex_sharded_builder,
        "virustotal_unknown": _hex_sharded_builder,
    }

    def __post_init__(self) -> None:
        """Ensure cache directory exists and merge TTL defaults."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        merged_ttls = dict(self.DEFAULT_TTLS)
        merged_ttls.update(self.ttls)
        self.ttls = merged_ttls

    def get_path(self, service: str, cache_key: str) -> Path:
        """Return the primary filesystem path for a given service/key pair."""
        primary, _, _ = self._paths_for_key(service, cache_key)
        return primary

    def load_text(self, service: str, cache_key: str) -> str | None:
        """Return cached payload if present and within the TTL budget."""
        primary, legacy, _ = self._paths_for_key(service, cache_key)
        cache_path = self._resolve_existing_path(primary, legacy)
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

    def get_cached(self, service: str, key: str) -> Optional[dict]:
        """Return cached JSON data as deep copy to prevent mutation.

        Args:
            service: The enrichment service name (e.g., 'dshield', 'virustotal').
            key: The cache key for the data.

        Returns:
            Deep copy of the cached JSON data, or None if not found/expired.
        """
        primary, legacy, _ = self._paths_for_key(service, key)
        cache_path = self._resolve_existing_path(primary, legacy)
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
            data = json.loads(payload)
            self.stats["hits"] += 1
            return copy.deepcopy(data)
        except (OSError, json.JSONDecodeError):
            self.stats["misses"] += 1
            return None

    def store_cached(self, service: str, key: str, data: dict) -> None:
        """Store JSON data in cache.

        Args:
            service: The enrichment service name.
            key: The cache key for the data.
            data: The JSON data to store.
        """
        try:
            payload = json.dumps(data, separators=(',', ':'))
            self.store_text(service, key, payload)
        except (TypeError, ValueError):
            # Data not JSON serializable - skip caching
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

            for cache_file in service_dir.rglob("*.json"):
                if not cache_file.is_file():
                    continue
                stats["scanned"] += 1
                try:
                    if cache_file.stat().st_mtime < cutoff:
                        cache_file.unlink()
                        stats["deleted"] += 1
                except FileNotFoundError:
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

    def _paths_for_key(self, service: str, cache_key: str) -> Tuple[Path, Path, str]:
        """Return the primary path, legacy path, and digest for ``cache_key``."""
        digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
        relative = self._build_relative_path(service, cache_key, digest)
        primary = self.base_dir / service / relative
        legacy = self.base_dir / service / digest[:2] / f"{digest}.json"
        return primary, legacy, digest

    def _build_relative_path(self, service: str, cache_key: str, digest: str) -> Path:
        """Return a service-aware sub-path for ``cache_key``."""
        builder = self.PATH_BUILDERS.get(service)
        candidate: Optional[Path] = None
        if builder:
            try:
                candidate = builder(cache_key, digest)
            except Exception:
                candidate = None
        if candidate:
            return candidate
        return Path(digest[:2]) / f"{digest}.json"

    def _resolve_existing_path(self, primary: Path, legacy: Path) -> Path:
        """Return existing cache path, migrating legacy layouts when possible."""
        if primary.exists():
            return primary
        if primary != legacy and legacy.exists():
            try:
                primary.parent.mkdir(parents=True, exist_ok=True)
                legacy.replace(primary)
                return primary
            except OSError:
                return legacy
        return primary


__all__ = ["EnrichmentCacheManager"]
