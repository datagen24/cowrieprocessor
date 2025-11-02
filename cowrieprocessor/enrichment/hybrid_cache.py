"""Hybrid three-tier caching system with Redis L1, Database L2, and filesystem L3."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import redis
from redis.connection import ConnectionPool

from cowrieprocessor.enrichment.cache import EnrichmentCacheManager

LOGGER = logging.getLogger(__name__)

# Redis configuration from environment variables
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
ENABLE_REDIS_CACHE = os.getenv("ENABLE_REDIS_CACHE", "true").lower() in ("true", "1", "yes")
REDIS_TTL_SECONDS = int(os.getenv("REDIS_TTL_SECONDS", "3600"))  # 1 hour default


def create_redis_client(
    host: str = REDIS_HOST,
    port: int = REDIS_PORT,
    password: Optional[str] = REDIS_PASSWORD,
    db: int = REDIS_DB,
    max_connections: int = 50,
    socket_timeout: float = 5.0,
    socket_connect_timeout: float = 5.0,
    retry_on_timeout: bool = True,
) -> Optional[redis.Redis]:
    """Create a Redis client with connection pooling and graceful degradation.

    Args:
        host: Redis server hostname
        port: Redis server port
        password: Optional Redis password
        db: Redis database number
        max_connections: Maximum connections in the pool
        socket_timeout: Socket timeout in seconds
        socket_connect_timeout: Connection timeout in seconds
        retry_on_timeout: Whether to retry on timeout

    Returns:
        Redis client instance, or None if connection fails
    """
    try:
        pool = ConnectionPool(
            host=host,
            port=port,
            password=password,
            db=db,
            max_connections=max_connections,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout,
            retry_on_timeout=retry_on_timeout,
            decode_responses=True,  # Auto-decode bytes to strings
        )
        client = redis.Redis(connection_pool=pool)

        # Test connection with ping
        client.ping()
        LOGGER.info(
            "Redis connection established: %s:%d (db=%d, pool_size=%d)",
            host,
            port,
            db,
            max_connections,
        )
        return client

    except redis.ConnectionError as e:
        LOGGER.warning("Redis connection failed (%s:%d): %s - falling back to filesystem cache only", host, port, e)
        return None
    except redis.TimeoutError as e:
        LOGGER.warning("Redis connection timeout (%s:%d): %s - falling back to filesystem cache only", host, port, e)
        return None
    except Exception as e:
        LOGGER.error("Unexpected error creating Redis client: %s - falling back to filesystem cache only", e)
        return None


@dataclass
class CacheTierStats:
    """Statistics for a single cache tier."""

    hits: int = 0
    misses: int = 0
    stores: int = 0
    errors: int = 0
    total_latency_ms: float = 0.0

    def record_hit(self, latency_ms: float = 0.0) -> None:
        """Record a cache hit."""
        self.hits += 1
        self.total_latency_ms += latency_ms

    def record_miss(self, latency_ms: float = 0.0) -> None:
        """Record a cache miss."""
        self.misses += 1
        self.total_latency_ms += latency_ms

    def record_store(self, latency_ms: float = 0.0) -> None:
        """Record a cache store operation."""
        self.stores += 1
        self.total_latency_ms += latency_ms

    def record_error(self) -> None:
        """Record a cache error."""
        self.errors += 1

    def get_hit_rate(self) -> float:
        """Calculate hit rate as percentage."""
        total = self.hits + self.misses
        return (self.hits / total * 100.0) if total > 0 else 0.0

    def get_avg_latency_ms(self) -> float:
        """Calculate average latency in milliseconds."""
        total = self.hits + self.misses + self.stores
        return (self.total_latency_ms / total) if total > 0 else 0.0


@dataclass
class HybridCacheStats:
    """Statistics for the hybrid cache system."""

    l1_redis: CacheTierStats = field(default_factory=CacheTierStats)
    l2_filesystem: CacheTierStats = field(default_factory=CacheTierStats)  # Combined DB + filesystem stats
    l3_api: int = 0  # API calls made (cache misses on all tiers)

    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary for reporting."""
        return {
            "l1_redis": {
                "hits": self.l1_redis.hits,
                "misses": self.l1_redis.misses,
                "stores": self.l1_redis.stores,
                "errors": self.l1_redis.errors,
                "hit_rate_percent": self.l1_redis.get_hit_rate(),
                "avg_latency_ms": self.l1_redis.get_avg_latency_ms(),
            },
            "l2_filesystem": {
                "hits": self.l2_filesystem.hits,
                "misses": self.l2_filesystem.misses,
                "stores": self.l2_filesystem.stores,
                "errors": self.l2_filesystem.errors,
                "hit_rate_percent": self.l2_filesystem.get_hit_rate(),
                "avg_latency_ms": self.l2_filesystem.get_avg_latency_ms(),
            },
            "l3_api_calls": self.l3_api,
            "total_cache_hits": self.l1_redis.hits + self.l2_filesystem.hits,
            "total_cache_misses": self.l3_api,
            "overall_hit_rate_percent": self._calculate_overall_hit_rate(),
        }

    def _calculate_overall_hit_rate(self) -> float:
        """Calculate overall cache hit rate across both tiers."""
        total_hits = self.l1_redis.hits + self.l2_filesystem.hits
        total_requests = total_hits + self.l3_api
        return (total_hits / total_requests * 100.0) if total_requests > 0 else 0.0


class HybridEnrichmentCache:
    """Three-tier caching system: Redis (L1) → Database (L2) → Filesystem (L3) → API (L4).

    This class provides a hybrid caching strategy with automatic fallback:
    - L1 (Redis): Sub-millisecond lookups, 1-hour TTL, optimized for intra-batch hits
    - L2 (Database): 1-3ms lookups, 30-day TTL, durable multi-container cache
    - L3 (Filesystem): 5-15ms lookups, service-specific TTLs (3-60 days), fallback only
    - L4 (API): Fallback to external API calls when all caches miss

    Graceful degradation: If Redis/Database unavailable, falls back to next tier.
    """

    def __init__(
        self,
        filesystem_cache: EnrichmentCacheManager,
        redis_client: Optional[redis.Redis] = None,
        database_cache: Optional[Any] = None,  # DatabaseCache instance
        redis_ttl: int = REDIS_TTL_SECONDS,
        enable_redis: bool = ENABLE_REDIS_CACHE,
    ) -> None:
        """Initialize hybrid cache with Redis L1, Database L2, and filesystem L3.

        Args:
            filesystem_cache: EnrichmentCacheManager instance for L3 cache
            redis_client: Optional Redis client; if None, will attempt to create one
            database_cache: Optional DatabaseCache instance for L2 tier
            redis_ttl: TTL for Redis cache entries in seconds (default: 1 hour)
            enable_redis: Whether to enable Redis cache (default: from env)
        """
        self.filesystem_cache = filesystem_cache
        self.database_cache = database_cache
        self.redis_ttl = redis_ttl
        self.stats = HybridCacheStats()

        # Initialize Redis client with graceful degradation
        if enable_redis:
            if redis_client is None:
                redis_client = create_redis_client()
            self.redis_client = redis_client
        else:
            self.redis_client = None
            LOGGER.info("Redis cache disabled by configuration")

        if self.redis_client is None and enable_redis:
            LOGGER.warning("Redis cache unavailable - operating without L1 tier")

        if self.database_cache is None:
            LOGGER.info("Database cache not configured - operating without L2 tier")

    def _redis_key(self, service: str, key: str) -> str:
        """Generate Redis key with service prefix.

        Args:
            service: Service name (e.g., 'dshield', 'virustotal')
            key: Cache key (e.g., IP address, file hash)

        Returns:
            Redis key with format: cowrie:enrichment:{service}:{key}
        """
        return f"cowrie:enrichment:{service}:{key}"

    def get_cached(self, service: str, key: str) -> Optional[dict]:
        """Retrieve cached data from L1 (Redis), L2 (Database), or L3 (filesystem).

        Cache lookup sequence:
        1. Check Redis (L1) - sub-millisecond lookup
        2. On L1 miss, check Database (L2) - 1-3ms lookup
        3. On L2 miss, check filesystem (L3) - 5-15ms lookup
        4. On L2/L3 hit, backfill upper tiers for future requests
        5. On all misses, return None (caller should fetch from API)

        Args:
            service: Service name (e.g., 'dshield', 'virustotal')
            key: Cache key (e.g., IP address, file hash)

        Returns:
            Cached data as dict, or None if not found
        """
        # L1: Try Redis first
        if self.redis_client is not None:
            start_time = time.time()
            try:
                redis_key = self._redis_key(service, key)
                cached_json = self.redis_client.get(redis_key)
                latency_ms = (time.time() - start_time) * 1000

                if cached_json and isinstance(cached_json, str):
                    # Redis hit
                    data = json.loads(cached_json)
                    if not isinstance(data, dict):
                        self.stats.l1_redis.record_error()
                        LOGGER.warning("Invalid non-dict data in Redis cache for %s/%s", service, key)
                    else:
                        self.stats.l1_redis.record_hit(latency_ms)
                        LOGGER.debug("L1 cache hit: %s/%s (%.2fms)", service, key, latency_ms)
                        return data
                else:
                    # Redis miss
                    self.stats.l1_redis.record_miss(latency_ms)
                    LOGGER.debug("L1 cache miss: %s/%s (%.2fms)", service, key, latency_ms)

            except redis.RedisError as e:
                self.stats.l1_redis.record_error()
                LOGGER.warning("Redis error for %s/%s: %s", service, key, e)
                # Fall through to L2 on Redis error

            except json.JSONDecodeError as e:
                self.stats.l1_redis.record_error()
                LOGGER.warning("Invalid JSON in Redis cache for %s/%s: %s", service, key, e)
                # Fall through to L2 on decode error

        # L2: Try database
        if self.database_cache is not None:
            start_time = time.time()
            try:
                data = self.database_cache.get(service, key)
                latency_ms = (time.time() - start_time) * 1000

                if data is not None:
                    # Database hit - backfill Redis for future requests
                    self.stats.l2_filesystem.record_hit(latency_ms)  # Track as L2 hit
                    LOGGER.debug("L2 cache hit (database): %s/%s (%.2fms)", service, key, latency_ms)

                    # Backfill L1 (Redis) asynchronously
                    if self.redis_client is not None:
                        try:
                            redis_key = self._redis_key(service, key)
                            self.redis_client.setex(redis_key, self.redis_ttl, json.dumps(data))
                            LOGGER.debug("Backfilled L1 cache: %s/%s", service, key)
                        except redis.RedisError as e:
                            LOGGER.debug("Failed to backfill Redis for %s/%s: %s", service, key, e)

                    return dict(data)  # Return a dict copy for type safety
                else:
                    # Database miss
                    self.stats.l2_filesystem.record_miss(latency_ms)
                    LOGGER.debug("L2 cache miss (database): %s/%s (%.2fms)", service, key, latency_ms)

            except Exception as e:
                self.stats.l2_filesystem.record_error()
                LOGGER.warning("Database cache error for %s/%s: %s", service, key, e)

        # L3: Try filesystem
        start_time = time.time()
        try:
            data = self.filesystem_cache.get_cached(service, key)
            latency_ms = (time.time() - start_time) * 1000

            if data is not None:
                # Filesystem hit - backfill upper tiers for future requests
                self.stats.l2_filesystem.record_hit(latency_ms)  # Combined L2/L3 stats
                LOGGER.debug("L3 cache hit (filesystem): %s/%s (%.2fms)", service, key, latency_ms)

                # Backfill L2 (Database) if available
                if self.database_cache is not None:
                    try:
                        self.database_cache.set(service, key, data)
                        LOGGER.debug("Backfilled L2 database cache: %s/%s", service, key)
                    except Exception as e:
                        LOGGER.debug("Failed to backfill database for %s/%s: %s", service, key, e)

                # Backfill L1 (Redis) if available
                if self.redis_client is not None:
                    try:
                        redis_key = self._redis_key(service, key)
                        self.redis_client.setex(redis_key, self.redis_ttl, json.dumps(data))
                        LOGGER.debug("Backfilled L1 cache: %s/%s", service, key)
                    except redis.RedisError as e:
                        LOGGER.debug("Failed to backfill Redis for %s/%s: %s", service, key, e)

                return dict(data)  # Return a dict copy for type safety
            else:
                # Filesystem miss
                self.stats.l2_filesystem.record_miss(latency_ms)
                LOGGER.debug("L3 cache miss (filesystem): %s/%s (%.2fms)", service, key, latency_ms)

        except Exception as e:
            self.stats.l2_filesystem.record_error()
            LOGGER.warning("Filesystem cache error for %s/%s: %s", service, key, e)

        # All caches missed - increment L3 API call counter
        self.stats.l3_api += 1
        return None

    def store_cached(self, service: str, key: str, data: dict) -> None:
        """Store data in all cache tiers (L1/L2/L3).

        This method performs write-through caching:
        1. Store in Redis (L1) with short TTL (1 hour)
        2. Store in Database (L2) with medium TTL (30 days)
        3. Store in filesystem (L3) with longer TTL (service-specific)

        All stores are best-effort; failures are logged but don't raise exceptions.

        Args:
            service: Service name (e.g., 'dshield', 'virustotal')
            key: Cache key (e.g., IP address, file hash)
            data: Data to cache (must be JSON-serializable dict)
        """
        # L1: Store in Redis
        if self.redis_client is not None:
            start_time = time.time()
            try:
                redis_key = self._redis_key(service, key)
                json_data = json.dumps(data)
                self.redis_client.setex(redis_key, self.redis_ttl, json_data)
                latency_ms = (time.time() - start_time) * 1000
                self.stats.l1_redis.record_store(latency_ms)
                LOGGER.debug("Stored in L1 cache: %s/%s (%.2fms)", service, key, latency_ms)

            except redis.RedisError as e:
                self.stats.l1_redis.record_error()
                LOGGER.warning("Failed to store in Redis for %s/%s: %s", service, key, e)

            except (TypeError, ValueError) as e:
                self.stats.l1_redis.record_error()
                LOGGER.warning("Invalid data for Redis cache %s/%s: %s", service, key, e)

        # L2: Store in database
        if self.database_cache is not None:
            start_time = time.time()
            try:
                success = self.database_cache.set(service, key, data)
                latency_ms = (time.time() - start_time) * 1000
                if success:
                    self.stats.l2_filesystem.record_store(latency_ms)
                    LOGGER.debug("Stored in L2 cache (database): %s/%s (%.2fms)", service, key, latency_ms)
                else:
                    self.stats.l2_filesystem.record_error()

            except Exception as e:
                self.stats.l2_filesystem.record_error()
                LOGGER.warning("Failed to store in database cache for %s/%s: %s", service, key, e)

        # L3: Store in filesystem
        start_time = time.time()
        try:
            self.filesystem_cache.store_cached(service, key, data)
            latency_ms = (time.time() - start_time) * 1000
            self.stats.l2_filesystem.record_store(latency_ms)
            LOGGER.debug("Stored in L3 cache (filesystem): %s/%s (%.2fms)", service, key, latency_ms)

        except Exception as e:
            self.stats.l2_filesystem.record_error()
            LOGGER.warning("Failed to store in filesystem cache for %s/%s: %s", service, key, e)

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive cache statistics for all tiers.

        Returns:
            Dictionary with statistics for L1 (Redis), L2 (Database/filesystem), and L3 (API)
        """
        return self.stats.to_dict()

    def snapshot(self) -> Dict[str, int]:
        """Return cache statistics in legacy format for backward compatibility.

        Returns:
            Dictionary with 'hits', 'misses', and 'stores' keys
        """
        stats = self.get_stats()
        return {
            "hits": stats["total_cache_hits"],
            "misses": stats["total_cache_misses"],
            "stores": stats["l1_redis"]["stores"] + stats["l2_filesystem"]["stores"],
        }

    def clear_redis(self) -> int:
        """Clear all Redis cache entries for this application.

        Returns:
            Number of keys deleted, or 0 if Redis unavailable
        """
        if self.redis_client is None:
            LOGGER.warning("Cannot clear Redis cache - client not available")
            return 0

        try:
            pattern = "cowrie:enrichment:*"
            cursor = 0
            deleted_count = 0

            while True:
                scan_result = self.redis_client.scan(cursor, match=pattern, count=100)
                cursor, keys = scan_result if isinstance(scan_result, tuple) else (0, [])
                if keys:
                    delete_result = self.redis_client.delete(*keys)
                    if isinstance(delete_result, int):
                        deleted_count += delete_result
                if cursor == 0:
                    break

            LOGGER.info("Cleared %d Redis cache entries", deleted_count)
            return deleted_count

        except redis.RedisError as e:
            LOGGER.error("Failed to clear Redis cache: %s", e)
            return 0

    def close(self) -> None:
        """Close Redis connection and cleanup resources."""
        if self.redis_client is not None:
            try:
                self.redis_client.close()
                LOGGER.debug("Closed Redis connection")
            except Exception as e:
                LOGGER.warning("Error closing Redis connection: %s", e)

    def __enter__(self) -> 'HybridEnrichmentCache':
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit with cleanup."""
        self.close()


__all__ = [
    "HybridEnrichmentCache",
    "HybridCacheStats",
    "CacheTierStats",
    "create_redis_client",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_PASSWORD",
    "REDIS_DB",
    "ENABLE_REDIS_CACHE",
    "REDIS_TTL_SECONDS",
]
