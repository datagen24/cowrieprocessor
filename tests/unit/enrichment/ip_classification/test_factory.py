"""Unit tests for IPClassifier factory function."""

from __future__ import annotations

from pathlib import Path

from cowrieprocessor.enrichment.ip_classification.factory import create_ip_classifier


class TestCreateIPClassifier:
    """Test create_ip_classifier factory function."""

    def test_factory_creates_classifier(self, tmp_path: Path, mock_db_engine) -> None:
        """Test factory creates IPClassifier with default parameters."""
        classifier = create_ip_classifier(
            cache_dir=tmp_path,
            db_engine=mock_db_engine,
            enable_redis=False,
        )

        assert classifier is not None
        assert classifier.cache is not None
        assert classifier.tor_matcher is not None
        assert classifier.cloud_matcher is not None
        assert classifier.datacenter_matcher is not None
        assert classifier.residential_heuristic is not None

    def test_factory_default_urls(self, tmp_path: Path, mock_db_engine) -> None:
        """Test factory uses default URLs."""
        classifier = create_ip_classifier(
            cache_dir=tmp_path,
            db_engine=mock_db_engine,
            enable_redis=False,
        )

        assert "torproject.org" in classifier.tor_matcher.data_url
        assert "rezmoss" in classifier.cloud_matcher.data_url
        assert "jhassine" in classifier.datacenter_matcher.data_url

    def test_factory_custom_urls(self, tmp_path: Path, mock_db_engine) -> None:
        """Test factory accepts custom URLs."""
        classifier = create_ip_classifier(
            cache_dir=tmp_path,
            db_engine=mock_db_engine,
            enable_redis=False,
            tor_url="https://example.com/tor",
            cloud_base_url="https://example.com/cloud",
            datacenter_url="https://example.com/datacenter",
        )

        assert classifier.tor_matcher.data_url == "https://example.com/tor"
        assert classifier.cloud_matcher.data_url == "https://example.com/cloud"
        assert classifier.datacenter_matcher.data_url == "https://example.com/datacenter"

    def test_factory_enable_redis_parameter(self, tmp_path: Path, mock_db_engine) -> None:
        """Test factory respects enable_redis parameter."""
        classifier_no_redis = create_ip_classifier(
            cache_dir=tmp_path,
            db_engine=mock_db_engine,
            enable_redis=False,
        )

        assert classifier_no_redis.cache.redis_client is None

    def test_factory_returns_working_classifier(
        self, tmp_path: Path, mock_db_engine, mock_all_network_requests
    ) -> None:
        """Test factory returns a working classifier."""
        classifier = create_ip_classifier(
            cache_dir=tmp_path,
            db_engine=mock_db_engine,
            enable_redis=False,
        )

        # Should be able to classify without error
        result = classifier.classify("192.0.2.1")
        assert result is not None
        assert result.ip_type is not None
