"""Unit tests for main IPClassifier service."""

from __future__ import annotations

from pathlib import Path

import pytest

from cowrieprocessor.enrichment.ip_classification.classifier import IPClassifier
from cowrieprocessor.enrichment.ip_classification.models import IPType
from tests.fixtures.ip_classification_fixtures import (
    SAMPLE_AWS_IP,
    SAMPLE_DIGITALOCEAN_IP,
    SAMPLE_TOR_IP,
    SAMPLE_UNKNOWN_IP,
)


@pytest.fixture
def classifier(tmp_path: Path, mock_db_engine):
    """Create classifier with temp cache and no Redis."""
    return IPClassifier(
        cache_dir=tmp_path,
        db_engine=mock_db_engine,
        enable_redis=False,
    )


class TestIPClassifier:
    """Test IPClassifier main service."""

    def test_initialization(self, classifier: IPClassifier) -> None:
        """Test classifier initialization."""
        assert classifier.cache is not None
        assert classifier.tor_matcher is not None
        assert classifier.cloud_matcher is not None
        assert classifier.datacenter_matcher is not None
        assert classifier.residential_heuristic is not None
        assert classifier._stats["classifications"] == 0

    def test_classify_tor_priority(self, classifier: IPClassifier, mock_all_network_requests) -> None:
        """Test TOR classification has highest priority."""
        result = classifier.classify(SAMPLE_TOR_IP)

        assert result.ip_type == IPType.TOR
        assert result.provider == "tor"
        assert result.confidence == 0.95
        assert result.source == "tor_bulk_list"

    def test_classify_cloud_priority(self, classifier: IPClassifier, mock_all_network_requests) -> None:
        """Test cloud classification priority (after TOR)."""
        result = classifier.classify(SAMPLE_AWS_IP)

        assert result.ip_type == IPType.CLOUD
        assert result.provider == "aws"
        assert result.confidence == 0.99

    def test_classify_datacenter_priority(self, classifier: IPClassifier, mock_all_network_requests) -> None:
        """Test datacenter classification priority (after TOR, Cloud)."""
        result = classifier.classify(SAMPLE_DIGITALOCEAN_IP)

        assert result.ip_type == IPType.DATACENTER
        assert result.provider == "digitalocean"
        assert result.confidence == 0.75

    def test_classify_residential_heuristic(self, classifier: IPClassifier, mock_all_network_requests) -> None:
        """Test residential classification via heuristic."""
        result = classifier.classify("1.2.3.4", asn=7922, as_name="Comcast Cable Communications")

        assert result.ip_type == IPType.RESIDENTIAL
        assert result.provider == "Comcast Cable Communications"
        assert result.confidence >= 0.7

    def test_classify_unknown_fallback(self, classifier: IPClassifier, mock_all_network_requests) -> None:
        """Test unknown classification as fallback."""
        result = classifier.classify(SAMPLE_UNKNOWN_IP)

        assert result.ip_type == IPType.UNKNOWN
        assert result.provider is None
        assert result.confidence == 0.0
        assert result.source == "none"

    def test_classify_uses_cache(self, classifier: IPClassifier, mock_all_network_requests) -> None:
        """Test that classify uses cache on second call."""
        # First call - cache miss
        result1 = classifier.classify(SAMPLE_TOR_IP)
        assert classifier._stats["cache_misses"] == 1

        # Second call - cache hit
        result2 = classifier.classify(SAMPLE_TOR_IP)
        assert result1.ip_type == result2.ip_type
        assert classifier._stats["cache_hits"] == 1

    def test_bulk_classify(self, classifier: IPClassifier, mock_all_network_requests) -> None:
        """Test bulk classification."""
        ips = [
            (SAMPLE_UNKNOWN_IP, None, None),
            ("1.2.3.4", 7922, "Comcast Cable"),
        ]

        results = classifier.bulk_classify(ips)

        assert len(results) == 2
        assert SAMPLE_UNKNOWN_IP in results
        assert "1.2.3.4" in results
        assert results["1.2.3.4"].ip_type == IPType.RESIDENTIAL

    def test_get_stats(self, classifier: IPClassifier, mock_all_network_requests) -> None:
        """Test get_stats returns statistics."""
        classifier.classify(SAMPLE_UNKNOWN_IP)

        stats = classifier.get_stats()
        assert stats["classifications"] == 1
        assert stats["cache_misses"] == 1
        assert stats["unknown_matches"] == 1

    def test_update_all_sources(self, classifier: IPClassifier, mock_all_network_requests) -> None:
        """Test updating all data sources."""
        # Should complete without raising exceptions
        classifier.update_all_sources()

        # Verify data was loaded by checking provider counts (not _data_loaded flag)
        # Note: update_all_sources() calls _download_data() directly, which doesn't set _data_loaded
        assert classifier.tor_matcher.exit_nodes is not None and len(classifier.tor_matcher.exit_nodes) > 0
        assert len(classifier.cloud_matcher._provider_cidr_counts) > 0
        assert len(classifier.datacenter_matcher._provider_cidr_counts) > 0

    def test_context_manager(self, tmp_path: Path, mock_db_engine) -> None:
        """Test classifier as context manager."""
        with IPClassifier(tmp_path, mock_db_engine, enable_redis=False) as clf:
            assert clf is not None
        # Should close without error

    def test_statistics_increments(self, classifier: IPClassifier, mock_all_network_requests) -> None:
        """Test that statistics increment correctly."""
        assert classifier._stats["classifications"] == 0

        classifier.classify(SAMPLE_UNKNOWN_IP)
        assert classifier._stats["classifications"] == 1
        assert classifier._stats["unknown_matches"] == 1

        classifier.classify("1.2.3.4", asn=7922, as_name="Comcast Cable")
        assert classifier._stats["classifications"] == 2
        assert classifier._stats["residential_matches"] == 1
