"""Unit tests for 3-tier IP classification cache (Redis, Database, Disk)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from cowrieprocessor.enrichment.ip_classification.cache import HybridIPClassificationCache
from cowrieprocessor.enrichment.ip_classification.models import IPClassification, IPType


@pytest.fixture
def cache_no_redis(tmp_path: Path, mock_db_engine):
    """Create cache without Redis for testing."""
    return HybridIPClassificationCache(
        cache_dir=tmp_path,
        db_engine=mock_db_engine,
        enable_redis=False,
    )


@pytest.fixture
def sample_classification() -> IPClassification:
    """Create sample classification for testing."""
    return IPClassification(
        ip_type=IPType.CLOUD,
        provider="aws",
        confidence=0.99,
        source="cloud_ranges_aws",
        classified_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )


class TestHybridIPClassificationCache:
    """Test 3-tier cache system."""

    def test_cache_initialization(self, cache_no_redis: HybridIPClassificationCache, tmp_path: Path) -> None:
        """Test cache initialization creates directories."""
        assert cache_no_redis.cache_dir == tmp_path / "ip_classification"
        assert cache_no_redis.cache_dir.exists()
        assert cache_no_redis.redis_client is None
        assert cache_no_redis.db_cache is not None
        assert cache_no_redis.stats.redis_hits == 0

    def test_store_and_get_disk_only(
        self, cache_no_redis: HybridIPClassificationCache, sample_classification: IPClassification
    ) -> None:
        """Test storing and retrieving from disk cache."""
        ip = "52.0.0.1"

        cache_no_redis.store(ip, sample_classification)

        result = cache_no_redis.get(ip)
        assert result is not None
        assert result.ip_type == IPType.CLOUD
        assert result.provider == "aws"
        assert result.confidence == 0.99

    def test_disk_path_ipv4(self, cache_no_redis: HybridIPClassificationCache) -> None:
        """Test disk path generation for IPv4."""
        path = cache_no_redis._disk_path("52.0.0.1")
        assert path == cache_no_redis.cache_dir / "52" / "0" / "0" / "1.json"

    def test_disk_path_invalid_ip(self, cache_no_redis: HybridIPClassificationCache) -> None:
        """Test disk path generation for invalid IP."""
        path = cache_no_redis._disk_path("2001:db8::1")
        assert "invalid" in str(path)

    def test_serialization(
        self, cache_no_redis: HybridIPClassificationCache, sample_classification: IPClassification
    ) -> None:
        """Test classification serialization."""
        serialized = cache_no_redis._serialize(sample_classification)
        data = json.loads(serialized)

        assert data["ip_type"] == "cloud"
        assert data["provider"] == "aws"
        assert data["confidence"] == 0.99
        assert data["source"] == "cloud_ranges_aws"

    def test_deserialization(self, cache_no_redis: HybridIPClassificationCache) -> None:
        """Test classification deserialization."""
        json_data = json.dumps(
            {
                "ip_type": "cloud",
                "provider": "aws",
                "confidence": 0.99,
                "source": "cloud_ranges_aws",
                "classified_at": "2025-01-01T12:00:00+00:00",
            }
        )

        result = cache_no_redis._deserialize(json_data)
        assert result.ip_type == IPType.CLOUD
        assert result.provider == "aws"
        assert result.confidence == 0.99

    def test_cache_miss(self, cache_no_redis: HybridIPClassificationCache) -> None:
        """Test cache miss returns None."""
        result = cache_no_redis.get("1.2.3.4")
        assert result is None

    def test_statistics_tracking(
        self, cache_no_redis: HybridIPClassificationCache, sample_classification: IPClassification
    ) -> None:
        """Test cache statistics tracking."""
        cache_no_redis.store("52.0.0.1", sample_classification)
        cache_no_redis.get("52.0.0.1")  # Should hit database cache
        cache_no_redis.get("1.2.3.4")  # Should miss all caches

        stats = cache_no_redis.get_stats()
        assert stats.stores == 1
        # With database cache working, we get database hits instead of disk hits
        assert stats.database_hits == 1
        assert stats.database_misses == 1
        assert stats.total_lookups == 2
        assert stats.hit_rate == 0.5

    def test_redis_ttl_per_ip_type(self, cache_no_redis: HybridIPClassificationCache) -> None:
        """Test Redis TTL configuration per IP type."""
        assert cache_no_redis.REDIS_TTLS[IPType.TOR] == 3600
        assert cache_no_redis.REDIS_TTLS[IPType.CLOUD] == 86400
        assert cache_no_redis.REDIS_TTLS[IPType.DATACENTER] == 86400
        assert cache_no_redis.REDIS_TTLS[IPType.RESIDENTIAL] == 86400
        assert cache_no_redis.REDIS_TTLS[IPType.UNKNOWN] == 3600

    def test_database_ttl(self, cache_no_redis: HybridIPClassificationCache) -> None:
        """Test database TTL constant."""
        assert cache_no_redis.DATABASE_TTL == 7 * 86400

    def test_disk_ttl(self, cache_no_redis: HybridIPClassificationCache) -> None:
        """Test disk TTL constant."""
        assert cache_no_redis.DISK_TTL == 30 * 86400

    def test_context_manager(self, tmp_path: Path, mock_db_engine) -> None:
        """Test cache as context manager."""
        with HybridIPClassificationCache(tmp_path, mock_db_engine, enable_redis=False) as cache:
            assert cache is not None
        # Should close without error

    @patch("cowrieprocessor.enrichment.ip_classification.cache.create_redis_client")
    def test_redis_cache_hit(
        self, mock_redis_factory, tmp_path: Path, mock_db_engine, sample_classification: IPClassification
    ) -> None:
        """Test Redis L1 cache hit."""
        mock_redis = Mock()
        mock_redis.get.return_value = json.dumps(
            {
                "ip_type": "cloud",
                "provider": "aws",
                "confidence": 0.99,
                "source": "cloud_ranges_aws",
                "classified_at": "2025-01-01T12:00:00+00:00",
            }
        )
        mock_redis_factory.return_value = mock_redis

        cache = HybridIPClassificationCache(tmp_path, mock_db_engine, enable_redis=True)
        result = cache.get("52.0.0.1")

        assert result is not None
        assert result.ip_type == IPType.CLOUD
        assert cache.stats.redis_hits == 1

    def test_close_without_redis(self, cache_no_redis: HybridIPClassificationCache) -> None:
        """Test closing cache without Redis."""
        cache_no_redis.close()  # Should not raise

    @patch("cowrieprocessor.enrichment.ip_classification.cache.create_redis_client")
    def test_close_with_redis(self, mock_redis_factory, tmp_path: Path, mock_db_engine) -> None:
        """Test closing cache with Redis."""
        mock_redis = Mock()
        mock_redis_factory.return_value = mock_redis

        cache = HybridIPClassificationCache(tmp_path, mock_db_engine, enable_redis=True)
        cache.close()

        mock_redis.close.assert_called_once()
