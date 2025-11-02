"""Integration tests for HybridEnrichmentCache with Redis L1 and filesystem L2."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import Mock, patch

import pytest

from cowrieprocessor.enrichment.cache import EnrichmentCacheManager
from cowrieprocessor.enrichment.hybrid_cache import (
    CacheTierStats,
    HybridCacheStats,
    HybridEnrichmentCache,
    create_redis_client,
)


@pytest.fixture
def temp_cache_dir(tmp_path: Path) -> Path:
    """Create temporary cache directory."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


@pytest.fixture
def filesystem_cache(temp_cache_dir: Path) -> EnrichmentCacheManager:
    """Create filesystem cache manager for L2."""
    return EnrichmentCacheManager(base_dir=temp_cache_dir)


@pytest.fixture
def mock_redis_client() -> Mock:
    """Create mock Redis client for testing."""
    mock_client = Mock()
    mock_client.get = Mock(return_value=None)
    mock_client.setex = Mock(return_value=True)
    mock_client.ping = Mock(return_value=True)
    mock_client.close = Mock()
    mock_client.scan = Mock(return_value=(0, []))
    mock_client.delete = Mock(return_value=0)
    return mock_client


@pytest.fixture
def hybrid_cache_with_mock_redis(
    filesystem_cache: EnrichmentCacheManager,
    mock_redis_client: Mock,
) -> HybridEnrichmentCache:
    """Create hybrid cache with mock Redis client."""
    return HybridEnrichmentCache(
        filesystem_cache=filesystem_cache,
        redis_client=mock_redis_client,
        redis_ttl=3600,
    )


@pytest.fixture
def hybrid_cache_without_redis(
    filesystem_cache: EnrichmentCacheManager,
) -> HybridEnrichmentCache:
    """Create hybrid cache without Redis (filesystem-only mode)."""
    return HybridEnrichmentCache(
        filesystem_cache=filesystem_cache,
        redis_client=None,
        enable_redis=False,
    )


class TestCacheTierStats:
    """Test cache tier statistics tracking."""

    def test_initial_state(self) -> None:
        """Test initial state of cache tier stats."""
        stats = CacheTierStats()
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.stores == 0
        assert stats.errors == 0
        assert stats.total_latency_ms == 0.0

    def test_record_hit(self) -> None:
        """Test recording cache hits."""
        stats = CacheTierStats()
        stats.record_hit(latency_ms=1.5)
        assert stats.hits == 1
        assert stats.total_latency_ms == 1.5

    def test_record_miss(self) -> None:
        """Test recording cache misses."""
        stats = CacheTierStats()
        stats.record_miss(latency_ms=2.0)
        assert stats.misses == 1
        assert stats.total_latency_ms == 2.0

    def test_record_store(self) -> None:
        """Test recording cache stores."""
        stats = CacheTierStats()
        stats.record_store(latency_ms=0.5)
        assert stats.stores == 1
        assert stats.total_latency_ms == 0.5

    def test_record_error(self) -> None:
        """Test recording cache errors."""
        stats = CacheTierStats()
        stats.record_error()
        assert stats.errors == 1

    def test_get_hit_rate(self) -> None:
        """Test hit rate calculation."""
        stats = CacheTierStats()
        assert stats.get_hit_rate() == 0.0

        stats.record_hit()
        stats.record_hit()
        stats.record_miss()
        # 2 hits out of 3 total = 66.67%
        assert abs(stats.get_hit_rate() - 66.67) < 0.01

    def test_get_avg_latency(self) -> None:
        """Test average latency calculation."""
        stats = CacheTierStats()
        assert stats.get_avg_latency_ms() == 0.0

        stats.record_hit(latency_ms=1.0)
        stats.record_miss(latency_ms=2.0)
        stats.record_store(latency_ms=3.0)
        # Total: 6.0ms across 3 operations = 2.0ms average
        assert stats.get_avg_latency_ms() == 2.0


class TestHybridCacheStats:
    """Test hybrid cache statistics aggregation."""

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        stats = HybridCacheStats()
        stats.l1_redis.record_hit(latency_ms=0.5)
        stats.l2_filesystem.record_miss(latency_ms=10.0)
        stats.l3_api = 1

        result = stats.to_dict()

        assert result["l1_redis"]["hits"] == 1
        assert result["l1_redis"]["avg_latency_ms"] == 0.5
        assert result["l2_filesystem"]["misses"] == 1
        assert result["l2_filesystem"]["avg_latency_ms"] == 10.0
        assert result["l3_api_calls"] == 1
        assert result["total_cache_hits"] == 1
        assert result["total_cache_misses"] == 1

    def test_overall_hit_rate_calculation(self) -> None:
        """Test overall hit rate across all tiers."""
        stats = HybridCacheStats()

        # 7 Redis hits + 2 filesystem hits + 1 API call = 90% hit rate
        for _ in range(7):
            stats.l1_redis.record_hit()
        for _ in range(2):
            stats.l2_filesystem.record_hit()
        stats.l3_api = 1

        result = stats.to_dict()
        assert result["total_cache_hits"] == 9
        assert result["total_cache_misses"] == 1
        assert abs(result["overall_hit_rate_percent"] - 90.0) < 0.01


class TestRedisClientFactory:
    """Test Redis client factory and connection handling."""

    @patch("cowrieprocessor.enrichment.hybrid_cache.ConnectionPool")
    @patch("cowrieprocessor.enrichment.hybrid_cache.redis.Redis")
    def test_successful_connection(self, mock_redis_class: Mock, mock_pool: Mock) -> None:
        """Test successful Redis connection."""
        mock_client = Mock()
        mock_client.ping = Mock(return_value=True)
        mock_redis_class.return_value = mock_client

        client = create_redis_client(host="localhost", port=6379)

        assert client is not None
        mock_client.ping.assert_called_once()

    @patch("cowrieprocessor.enrichment.hybrid_cache.ConnectionPool")
    @patch("cowrieprocessor.enrichment.hybrid_cache.redis.Redis")
    def test_connection_failure_graceful_degradation(self, mock_redis_class: Mock, mock_pool: Mock) -> None:
        """Test graceful degradation on Redis connection failure."""
        import redis as redis_module

        mock_client = Mock()
        mock_client.ping = Mock(side_effect=redis_module.ConnectionError("Connection refused"))
        mock_redis_class.return_value = mock_client

        client = create_redis_client(host="localhost", port=6379)

        assert client is None  # Graceful degradation


class TestHybridEnrichmentCache:
    """Test hybrid cache with Redis L1 and filesystem L2."""

    def test_redis_key_generation(self, hybrid_cache_with_mock_redis: HybridEnrichmentCache) -> None:
        """Test Redis key generation with service prefix."""
        key = hybrid_cache_with_mock_redis._redis_key("dshield", "1.2.3.4")
        assert key == "cowrie:enrichment:dshield:1.2.3.4"

    def test_l1_cache_hit(self, hybrid_cache_with_mock_redis: HybridEnrichmentCache) -> None:
        """Test L1 (Redis) cache hit scenario."""
        # Configure mock to return cached data
        test_data = {"ip": "1.2.3.4", "reputation": "malicious"}
        hybrid_cache_with_mock_redis.redis_client.get = Mock(return_value=json.dumps(test_data))

        result = hybrid_cache_with_mock_redis.get_cached("dshield", "1.2.3.4")

        assert result == test_data
        assert hybrid_cache_with_mock_redis.stats.l1_redis.hits == 1
        assert hybrid_cache_with_mock_redis.stats.l1_redis.misses == 0
        assert hybrid_cache_with_mock_redis.stats.l2_filesystem.hits == 0

    def test_l1_miss_l2_hit_with_backfill(
        self,
        hybrid_cache_with_mock_redis: HybridEnrichmentCache,
        temp_cache_dir: Path,
    ) -> None:
        """Test L1 miss, L2 hit, and Redis backfill."""
        # Redis miss
        hybrid_cache_with_mock_redis.redis_client.get = Mock(return_value=None)

        # Filesystem hit - store data first
        test_data = {"ip": "1.2.3.4", "reputation": "suspicious"}
        hybrid_cache_with_mock_redis.filesystem_cache.store_cached("dshield", "1.2.3.4", test_data)

        result = hybrid_cache_with_mock_redis.get_cached("dshield", "1.2.3.4")

        assert result == test_data
        assert hybrid_cache_with_mock_redis.stats.l1_redis.hits == 0
        assert hybrid_cache_with_mock_redis.stats.l1_redis.misses == 1
        assert hybrid_cache_with_mock_redis.stats.l2_filesystem.hits == 1

        # Verify Redis backfill was attempted
        hybrid_cache_with_mock_redis.redis_client.setex.assert_called()

    def test_l1_miss_l2_miss(self, hybrid_cache_with_mock_redis: HybridEnrichmentCache) -> None:
        """Test both L1 and L2 cache misses."""
        # Redis miss
        hybrid_cache_with_mock_redis.redis_client.get = Mock(return_value=None)

        result = hybrid_cache_with_mock_redis.get_cached("dshield", "5.6.7.8")

        assert result is None
        assert hybrid_cache_with_mock_redis.stats.l1_redis.misses == 1
        assert hybrid_cache_with_mock_redis.stats.l2_filesystem.misses == 1
        assert hybrid_cache_with_mock_redis.stats.l3_api == 1  # API call needed

    def test_store_cached_both_tiers(self, hybrid_cache_with_mock_redis: HybridEnrichmentCache) -> None:
        """Test storing data in both L1 and L2 caches."""
        test_data = {"ip": "1.2.3.4", "reputation": "clean"}

        hybrid_cache_with_mock_redis.store_cached("dshield", "1.2.3.4", test_data)

        # Verify Redis store
        hybrid_cache_with_mock_redis.redis_client.setex.assert_called_once()
        call_args = hybrid_cache_with_mock_redis.redis_client.setex.call_args
        assert call_args[0][0] == "cowrie:enrichment:dshield:1.2.3.4"
        assert call_args[0][1] == 3600  # TTL
        assert json.loads(call_args[0][2]) == test_data

        # Verify filesystem store
        assert hybrid_cache_with_mock_redis.stats.l1_redis.stores == 1
        assert hybrid_cache_with_mock_redis.stats.l2_filesystem.stores == 1

    def test_redis_error_graceful_degradation(self, hybrid_cache_with_mock_redis: HybridEnrichmentCache) -> None:
        """Test graceful degradation when Redis fails."""
        import redis as redis_module

        # Redis error on get
        hybrid_cache_with_mock_redis.redis_client.get = Mock(side_effect=redis_module.RedisError("Connection lost"))

        # Store data in filesystem
        test_data = {"ip": "1.2.3.4", "reputation": "unknown"}
        hybrid_cache_with_mock_redis.filesystem_cache.store_cached("dshield", "1.2.3.4", test_data)

        result = hybrid_cache_with_mock_redis.get_cached("dshield", "1.2.3.4")

        # Should still get result from filesystem
        assert result == test_data
        assert hybrid_cache_with_mock_redis.stats.l1_redis.errors == 1
        assert hybrid_cache_with_mock_redis.stats.l2_filesystem.hits == 1

    def test_filesystem_only_mode(self, hybrid_cache_without_redis: HybridEnrichmentCache) -> None:
        """Test operation without Redis (filesystem-only mode)."""
        test_data = {"ip": "1.2.3.4", "reputation": "malicious"}

        # Store in filesystem
        hybrid_cache_without_redis.store_cached("dshield", "1.2.3.4", test_data)

        # Retrieve from filesystem
        result = hybrid_cache_without_redis.get_cached("dshield", "1.2.3.4")

        assert result == test_data
        # No Redis operations should have occurred
        assert hybrid_cache_without_redis.stats.l1_redis.hits == 0
        assert hybrid_cache_without_redis.stats.l1_redis.misses == 0
        assert hybrid_cache_without_redis.stats.l2_filesystem.hits == 1

    def test_intra_batch_optimization(self, hybrid_cache_with_mock_redis: HybridEnrichmentCache) -> None:
        """Test intra-batch cache hit rate optimization (80%+ target)."""
        # Simulate batch processing: 100 sessions with 10 unique IPs (90% duplicate rate)
        unique_ips = [f"1.2.3.{i}" for i in range(10)]
        all_requests = unique_ips * 10  # 100 total requests, 10 unique

        # First pass: All should be L2 hits (pre-populated filesystem cache)
        for ip in unique_ips:
            test_data = {"ip": ip, "reputation": "test"}
            hybrid_cache_with_mock_redis.filesystem_cache.store_cached("dshield", ip, test_data)

        # Reset stats for the batch simulation
        hybrid_cache_with_mock_redis.stats = HybridCacheStats()

        # Configure mock: First request per IP misses L1, subsequent requests hit L1
        hit_count: Dict[str, int] = {}

        def mock_redis_get(key: str) -> str | None:
            ip = key.split(":")[-1]
            if ip not in hit_count:
                hit_count[ip] = 0
                return None  # First request: L1 miss
            else:
                hit_count[ip] += 1
                # Subsequent requests: L1 hit (return cached data)
                return json.dumps({"ip": ip, "reputation": "test"})

        hybrid_cache_with_mock_redis.redis_client.get = Mock(side_effect=mock_redis_get)

        # Process batch
        for ip in all_requests:
            hybrid_cache_with_mock_redis.get_cached("dshield", ip)

        # Calculate hit rates
        stats = hybrid_cache_with_mock_redis.get_stats()
        overall_hit_rate = stats["overall_hit_rate_percent"]

        # Should achieve 90% overall hit rate (90 L1 hits + 10 L2 hits out of 100 requests)
        assert overall_hit_rate >= 80.0, f"Expected ≥80% hit rate, got {overall_hit_rate:.2f}%"
        assert stats["l1_redis"]["hits"] == 90  # 9 duplicates * 10 unique IPs
        assert stats["l2_filesystem"]["hits"] == 10  # 10 unique IPs

    def test_get_stats(self, hybrid_cache_with_mock_redis: HybridEnrichmentCache) -> None:
        """Test comprehensive statistics retrieval."""
        # Simulate some cache operations
        hybrid_cache_with_mock_redis.stats.l1_redis.record_hit(latency_ms=0.5)
        hybrid_cache_with_mock_redis.stats.l1_redis.record_miss(latency_ms=0.3)
        hybrid_cache_with_mock_redis.stats.l2_filesystem.record_hit(latency_ms=12.0)
        hybrid_cache_with_mock_redis.stats.l3_api = 1

        stats = hybrid_cache_with_mock_redis.get_stats()

        assert stats["l1_redis"]["hits"] == 1
        assert stats["l1_redis"]["misses"] == 1
        assert stats["l2_filesystem"]["hits"] == 1
        assert stats["l3_api_calls"] == 1
        assert stats["total_cache_hits"] == 2
        assert stats["total_cache_misses"] == 1
        assert abs(stats["overall_hit_rate_percent"] - 66.67) < 0.01

    def test_clear_redis(self, hybrid_cache_with_mock_redis: HybridEnrichmentCache) -> None:
        """Test clearing Redis cache."""
        # Configure mock to return some keys
        hybrid_cache_with_mock_redis.redis_client.scan = Mock(
            side_effect=[
                (10, ["key1", "key2", "key3"]),  # First scan
                (0, ["key4"]),  # Final scan (cursor=0)
            ]
        )
        hybrid_cache_with_mock_redis.redis_client.delete = Mock(
            side_effect=[3, 1]  # Delete counts
        )

        deleted_count = hybrid_cache_with_mock_redis.clear_redis()

        assert deleted_count == 4
        assert hybrid_cache_with_mock_redis.redis_client.scan.call_count == 2
        assert hybrid_cache_with_mock_redis.redis_client.delete.call_count == 2

    def test_context_manager(self, hybrid_cache_with_mock_redis: HybridEnrichmentCache) -> None:
        """Test context manager protocol."""
        with hybrid_cache_with_mock_redis as cache:
            assert cache is not None
            test_data = {"test": "data"}
            cache.store_cached("test_service", "test_key", test_data)

        # After context exit, close should have been called
        hybrid_cache_with_mock_redis.redis_client.close.assert_called_once()

    def test_json_encoding_error_handling(self, hybrid_cache_with_mock_redis: HybridEnrichmentCache) -> None:
        """Test handling of invalid JSON data."""

        # Store invalid data (with non-serializable object)
        class NonSerializable:
            pass

        invalid_data: Dict[str, Any] = {"obj": NonSerializable()}

        # Should not raise exception, but log error
        hybrid_cache_with_mock_redis.store_cached("test", "key", invalid_data)  # type: ignore[arg-type]

        # Redis store should not have been called due to JSON error
        hybrid_cache_with_mock_redis.redis_client.setex.assert_not_called()
        assert hybrid_cache_with_mock_redis.stats.l1_redis.errors == 1

    def test_redis_decode_error_fallback(self, hybrid_cache_with_mock_redis: HybridEnrichmentCache) -> None:
        """Test fallback to L2 when Redis returns invalid JSON."""
        # Redis returns malformed JSON
        hybrid_cache_with_mock_redis.redis_client.get = Mock(return_value="{ invalid json }")

        # Store valid data in filesystem
        test_data = {"ip": "1.2.3.4", "valid": "data"}
        hybrid_cache_with_mock_redis.filesystem_cache.store_cached("test", "key", test_data)

        result = hybrid_cache_with_mock_redis.get_cached("test", "key")

        # Should fall back to filesystem
        assert result == test_data
        assert hybrid_cache_with_mock_redis.stats.l1_redis.errors == 1
        assert hybrid_cache_with_mock_redis.stats.l2_filesystem.hits == 1
