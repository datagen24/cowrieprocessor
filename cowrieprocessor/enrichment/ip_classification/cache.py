"""Multi-tier cache for IP classification results.

Implements 3-tier caching following cowrieprocessor/enrichment/hybrid_cache.py pattern:
- L1: Redis (in-memory, <1ms, TTL: 1-24h based on IP type)
- L2: Database (enrichment_cache table, <10ms, TTL: 7 days)
- L3: Disk (filesystem sharded by IP octets, <50ms, TTL: 30 days)

Thread Safety:
    This class is thread-safe for read operations. Write operations should be
    serialized externally if needed (database transactions handle DB writes).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Union

from sqlalchemy.engine import Connection, Engine

from ..db_cache import DatabaseCache
from ..hybrid_cache import ENABLE_REDIS_CACHE, create_redis_client
from .models import IPClassification, IPType

logger = logging.getLogger(__name__)


@dataclass
class IPClassificationCacheStats:
    """Statistics for multi-tier IP classification cache.

    Attributes:
        redis_hits: Cache hits from Redis (L1)
        redis_misses: Cache misses from Redis
        database_hits: Cache hits from database (L2)
        database_misses: Cache misses from database
        disk_hits: Cache hits from disk (L3)
        disk_misses: Cache misses from disk
        stores: Total number of classification results stored
    """

    redis_hits: int = 0
    redis_misses: int = 0
    database_hits: int = 0
    database_misses: int = 0
    disk_hits: int = 0
    disk_misses: int = 0
    stores: int = 0

    @property
    def total_lookups(self) -> int:
        """Total cache lookups across all tiers."""
        return self.redis_hits + self.database_hits + self.disk_hits + self.disk_misses

    @property
    def hit_rate(self) -> float:
        """Overall cache hit rate (0.0 to 1.0)."""
        if self.total_lookups == 0:
            return 0.0
        hits = self.redis_hits + self.database_hits + self.disk_hits
        return hits / self.total_lookups


class HybridIPClassificationCache:
    """Multi-tier cache for IP classification results.

    Cache hierarchy (checked in order):
    1. Redis (L1): Fast in-memory cache with type-specific TTLs
       - TOR: 1 hour (exit nodes change frequently)
       - Cloud: 24 hours (IP ranges change daily)
       - Datacenter: 24 hours (community lists update daily)
       - Residential: 24 hours (ASN names stable)
       - Unknown: 1 hour (may resolve later)

    2. Database (L2): enrichment_cache table
       - Service: "ip_classification"
       - TTL: 7 days (balance freshness vs DB load)

    3. Disk (L3): Filesystem cache sharded by IP octets
       - Path: {cache_dir}/ip_classification/{octet1}/{octet2}/{octet3}/{octet4}.json
       - TTL: 30 days (long-term fallback)

    Example:
        >>> from pathlib import Path
        >>> from cowrieprocessor.db.engine import get_engine
        >>>
        >>> engine = get_engine("postgresql://...")
        >>> cache = HybridIPClassificationCache(
        ...     cache_dir=Path("/mnt/dshield/data/cache"),
        ...     db_engine=engine,
        ...     enable_redis=True
        ... )
        >>>
        >>> # Get cached result (checks all 3 tiers)
        >>> classification = cache.get("1.2.3.4")
        >>>
        >>> # Store new result (writes to all 3 tiers)
        >>> from cowrieprocessor.enrichment.ip_classification.models import IPType
        >>> classification = IPClassification(
        ...     ip_type=IPType.CLOUD,
        ...     provider="aws",
        ...     confidence=0.99,
        ...     source="cloud_ranges_aws"
        ... )
        >>> cache.store("52.0.0.1", classification)
    """

    # TTLs per IP type (seconds)
    REDIS_TTLS = {
        IPType.TOR: 3600,  # 1 hour (changes frequently)
        IPType.CLOUD: 86400,  # 24 hours (daily updates)
        IPType.DATACENTER: 86400,  # 24 hours
        IPType.RESIDENTIAL: 86400,  # 24 hours
        IPType.UNKNOWN: 3600,  # 1 hour (may resolve later)
    }

    DATABASE_TTL = 7 * 86400  # 7 days
    DISK_TTL = 30 * 86400  # 30 days

    def __init__(
        self,
        cache_dir: Path,
        db_engine: Union[Engine, Connection],
        enable_redis: bool = ENABLE_REDIS_CACHE,
    ) -> None:
        """Initialize multi-tier IP classification cache.

        Args:
            cache_dir: Base directory for disk cache (L3)
            db_engine: SQLAlchemy engine or connection for database cache (L2)
            enable_redis: Enable Redis cache (L1), default from config

        Example:
            >>> from pathlib import Path
            >>> from cowrieprocessor.db.engine import get_engine
            >>> engine = get_engine("sqlite:///test.db")
            >>> cache = HybridIPClassificationCache(
            ...     cache_dir=Path("/tmp/cache"),
            ...     db_engine=engine,
            ...     enable_redis=False
            ... )
        """
        self.cache_dir = cache_dir / "ip_classification"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.db_cache = DatabaseCache(db_engine, ttl_seconds=self.DATABASE_TTL)

        self.redis_client = create_redis_client() if enable_redis else None
        self.stats = IPClassificationCacheStats()

    def get(self, ip: str) -> Optional[IPClassification]:
        """Retrieve IP classification from cache (3-tier lookup).

        Args:
            ip: IP address string (e.g., "1.2.3.4")

        Returns:
            IPClassification if cached and fresh, None otherwise

        Cache Lookup Order:
            1. Redis (L1): <1ms lookup
            2. Database (L2): <10ms lookup
            3. Disk (L3): <50ms lookup
            If all tiers miss, returns None (caller must classify and store)

        Example:
            >>> result = cache.get("52.0.0.1")
            >>> if result:
            ...     print(f"Cached: {result.ip_type.value} ({result.provider})")
            ... else:
            ...     print("Cache miss - need to classify")
        """
        # L1: Redis (fastest)
        if self.redis_client:
            redis_result = self._get_from_redis(ip)
            if redis_result:
                self.stats.redis_hits += 1
                return redis_result
            self.stats.redis_misses += 1

        # L2: Database
        db_result = self._get_from_database(ip)
        if db_result:
            self.stats.database_hits += 1
            # Populate Redis for future lookups (cache warming)
            if self.redis_client:
                self._store_to_redis(ip, db_result)
            return db_result
        self.stats.database_misses += 1

        # L3: Disk
        disk_result = self._get_from_disk(ip)
        if disk_result:
            self.stats.disk_hits += 1
            # Warm upper cache tiers
            if self.redis_client:
                self._store_to_redis(ip, disk_result)
            self._store_to_database(ip, disk_result)
            return disk_result
        self.stats.disk_misses += 1

        return None  # Complete cache miss

    def store(self, ip: str, classification: IPClassification) -> None:
        """Store IP classification to all cache tiers.

        Args:
            ip: IP address string
            classification: Classification result to cache

        Writes to:
            - Redis (L1): With type-specific TTL
            - Database (L2): With 7-day TTL
            - Disk (L3): With 30-day TTL

        Example:
            >>> from cowrieprocessor.enrichment.ip_classification.models import IPType
            >>> classification = IPClassification(
            ...     ip_type=IPType.CLOUD,
            ...     provider="aws",
            ...     confidence=0.99,
            ...     source="cloud_ranges_aws"
            ... )
            >>> cache.store("52.0.0.1", classification)
        """
        self.stats.stores += 1

        # Write to all tiers (fire-and-forget for speed)
        if self.redis_client:
            self._store_to_redis(ip, classification)

        self._store_to_database(ip, classification)
        self._store_to_disk(ip, classification)

    def get_stats(self) -> IPClassificationCacheStats:
        """Return cache statistics snapshot.

        Returns:
            IPClassificationCacheStats with current hit/miss counts

        Example:
            >>> stats = cache.get_stats()
            >>> print(f"Hit rate: {stats.hit_rate:.2%}")
            >>> print(f"Total lookups: {stats.total_lookups}")
        """
        return IPClassificationCacheStats(
            redis_hits=self.stats.redis_hits,
            redis_misses=self.stats.redis_misses,
            database_hits=self.stats.database_hits,
            database_misses=self.stats.database_misses,
            disk_hits=self.stats.disk_hits,
            disk_misses=self.stats.disk_misses,
            stores=self.stats.stores,
        )

    # --- Private: Redis (L1) ---

    def _redis_key(self, ip: str) -> str:
        """Generate Redis key for IP.

        Args:
            ip: IP address

        Returns:
            Redis key string (e.g., "ipclass:1.2.3.4")
        """
        return f"ipclass:{ip}"

    def _get_from_redis(self, ip: str) -> Optional[IPClassification]:
        """Get from Redis L1 cache.

        Args:
            ip: IP address

        Returns:
            IPClassification if found and valid, None otherwise
        """
        if not self.redis_client:
            return None

        try:
            key = self._redis_key(ip)
            data = self.redis_client.get(key)
            if not data:
                return None

            # Redis returns string (decode_responses=True in hybrid_cache.py)
            # Explicit cast for type checker - synchronous redis.get() returns str | None
            return self._deserialize(str(data))

        except Exception as e:
            logger.warning(f"Redis get failed for {ip}: {e}")
            return None

    def _store_to_redis(self, ip: str, classification: IPClassification) -> None:
        """Store to Redis L1 cache with type-specific TTL.

        Args:
            ip: IP address
            classification: Classification to store
        """
        if not self.redis_client:
            return

        try:
            key = self._redis_key(ip)
            value = self._serialize(classification)
            ttl = self.REDIS_TTLS[classification.ip_type]

            self.redis_client.setex(key, ttl, value)

        except Exception as e:
            logger.warning(f"Redis store failed for {ip}: {e}")

    # --- Private: Database (L2) ---

    def _get_from_database(self, ip: str) -> Optional[IPClassification]:
        """Get from Database L2 cache.

        Args:
            ip: IP address

        Returns:
            IPClassification if found and valid, None otherwise
        """
        try:
            data = self.db_cache.get(service="ip_classification", cache_key=ip)
            if not data:
                return None

            # DatabaseCache returns dict, convert to JSON string for deserialize
            return self._deserialize(json.dumps(data))

        except Exception as e:
            logger.warning(f"Database get failed for {ip}: {e}")
            return None

    def _store_to_database(self, ip: str, classification: IPClassification) -> None:
        """Store to Database L2 cache.

        Args:
            ip: IP address
            classification: Classification to store
        """
        try:
            # Serialize to JSON string, then parse to dict for DatabaseCache
            data_str = self._serialize(classification)
            data_dict = json.loads(data_str)
            self.db_cache.set(
                service="ip_classification",
                cache_key=ip,
                cache_value=data_dict,
                ttl_seconds=self.DATABASE_TTL,
            )

        except Exception as e:
            logger.warning(f"Database store failed for {ip}: {e}")

    # --- Private: Disk (L3) ---

    def _disk_path(self, ip: str) -> Path:
        """Generate disk cache path sharded by IP octets.

        Sharding scheme:
            IPv4: {cache_dir}/{octet1}/{octet2}/{octet3}/{octet4}.json
            Example: "1.2.3.4" → {cache_dir}/1/2/3/4.json

            IPv6/Invalid: {cache_dir}/invalid/{hash}.json
            Example: "2001:db8::1" → {cache_dir}/invalid/a1b2c3d4.json

        Args:
            ip: IP address

        Returns:
            Path to disk cache file
        """
        octets = ip.split(".")
        if len(octets) != 4:
            # Fallback to hash-based path for IPv6 or invalid IPs
            digest = hashlib.sha256(ip.encode("utf-8")).hexdigest()[:8]
            return self.cache_dir / "invalid" / f"{digest}.json"

        return self.cache_dir / octets[0] / octets[1] / octets[2] / f"{octets[3]}.json"

    def _get_from_disk(self, ip: str) -> Optional[IPClassification]:
        """Get from Disk L3 cache.

        Args:
            ip: IP address

        Returns:
            IPClassification if found, valid, and not expired, None otherwise
        """
        try:
            path = self._disk_path(ip)
            if not path.exists():
                return None

            # Check TTL based on file modification time
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            age = datetime.now(timezone.utc) - mtime
            if age > timedelta(seconds=self.DISK_TTL):
                path.unlink()  # Expired, delete
                return None

            data = path.read_text(encoding="utf-8")
            return self._deserialize(data)

        except Exception as e:
            logger.warning(f"Disk get failed for {ip}: {e}")
            return None

    def _store_to_disk(self, ip: str, classification: IPClassification) -> None:
        """Store to Disk L3 cache.

        Args:
            ip: IP address
            classification: Classification to store
        """
        try:
            path = self._disk_path(ip)
            path.parent.mkdir(parents=True, exist_ok=True)

            data = self._serialize(classification)
            path.write_text(data, encoding="utf-8")

        except Exception as e:
            logger.warning(f"Disk store failed for {ip}: {e}")

    # --- Private: Serialization ---

    def _serialize(self, classification: IPClassification) -> str:
        """Serialize IPClassification to JSON string.

        Args:
            classification: Classification to serialize

        Returns:
            JSON string representation
        """
        return json.dumps(
            {
                "ip_type": classification.ip_type.value,
                "provider": classification.provider,
                "confidence": classification.confidence,
                "source": classification.source,
                "classified_at": classification.classified_at.isoformat() if classification.classified_at else None,
            }
        )

    def _deserialize(self, data: str) -> IPClassification:
        """Deserialize JSON string to IPClassification.

        Args:
            data: JSON string

        Returns:
            IPClassification instance

        Raises:
            ValueError: If JSON is malformed or missing required fields
        """
        obj = json.loads(data)
        return IPClassification(
            ip_type=IPType(obj["ip_type"]),
            provider=obj.get("provider"),
            confidence=obj["confidence"],
            source=obj["source"],
            classified_at=(datetime.fromisoformat(obj["classified_at"]) if obj.get("classified_at") else None),
        )

    def close(self) -> None:
        """Close cache connections (Redis, Database).

        Call this when done with the cache to clean up resources.
        """
        if self.redis_client:
            self.redis_client.close()
        self.db_cache.close()

    def __enter__(self) -> HybridIPClassificationCache:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()
