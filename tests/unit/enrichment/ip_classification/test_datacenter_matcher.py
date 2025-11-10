"""Unit tests for datacenter and hosting provider matcher."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

try:
    import pytricia

    PYTRICIA_AVAILABLE = True
except ImportError:
    PYTRICIA_AVAILABLE = False

from cowrieprocessor.enrichment.ip_classification.datacenter_matcher import DatacenterMatcher
from tests.fixtures.ip_classification_fixtures import (
    MOCK_DIGITALOCEAN_CSV,
    MOCK_LINODE_CSV,
    SAMPLE_DIGITALOCEAN_IP,
    SAMPLE_LINODE_IP,
    SAMPLE_UNKNOWN_IP,
)


@pytest.mark.skipif(not PYTRICIA_AVAILABLE, reason="pytricia not installed")
class TestDatacenterMatcher:
    """Test DatacenterMatcher class."""

    @pytest.fixture
    def datacenter_matcher(self, tmp_path: Path) -> DatacenterMatcher:
        """Create datacenter matcher with temp cache directory."""
        return DatacenterMatcher(
            data_url="https://raw.githubusercontent.com/jhassine/server-ip-addresses/main",
            update_interval_seconds=604800,
            cache_dir=tmp_path,
            request_timeout=30,
        )

    def test_matcher_initialization(self, datacenter_matcher: DatacenterMatcher) -> None:
        """Test matcher initialization."""
        assert datacenter_matcher.update_interval_seconds == 604800
        assert datacenter_matcher.request_timeout == 30
        assert not datacenter_matcher._data_loaded
        assert datacenter_matcher.trie is not None

    def test_initialization_without_pytricia(self, tmp_path: Path) -> None:
        """Test initialization without pytricia raises ImportError."""
        with patch.dict("sys.modules", {"pytricia": None}):
            with patch("cowrieprocessor.enrichment.ip_classification.datacenter_matcher.pytricia", None):
                with pytest.raises(ImportError, match="pytricia is required"):
                    DatacenterMatcher(cache_dir=tmp_path)

    def test_match_digitalocean_ip(self, datacenter_matcher: DatacenterMatcher, mock_all_network_requests) -> None:
        """Test matching a DigitalOcean IP address."""
        # Use _update_data to properly set _data_loaded flag
        datacenter_matcher._update_data(force=True)

        result = datacenter_matcher.match(SAMPLE_DIGITALOCEAN_IP)

        assert result is not None
        assert result["provider"] == "digitalocean"
        assert result["region"] == "nyc1"

    @patch("cowrieprocessor.enrichment.ip_classification.datacenter_matcher.requests.get")
    def test_match_linode_ip(self, mock_get: Mock, datacenter_matcher: DatacenterMatcher) -> None:
        """Test matching a Linode IP address."""
        # Mock unified CSV with Linode entry (provider,cidr format)
        unified_csv = "provider,cidr\nLinode,45.79.0.0/16\n"
        mock_response = Mock()
        mock_response.text = unified_csv
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        datacenter_matcher._download_data()
        datacenter_matcher._data_loaded = True
        datacenter_matcher.last_update = datetime.now(timezone.utc)

        result = datacenter_matcher.match(SAMPLE_LINODE_IP)

        assert result is not None
        assert result["provider"] == "linode"

    @patch("cowrieprocessor.enrichment.ip_classification.datacenter_matcher.requests.get")
    def test_match_non_datacenter_ip(self, mock_get: Mock, datacenter_matcher: DatacenterMatcher) -> None:
        """Test matching a non-datacenter IP returns None."""
        mock_response = Mock()
        mock_response.text = MOCK_DIGITALOCEAN_CSV
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        datacenter_matcher._download_data()

        result = datacenter_matcher.match(SAMPLE_UNKNOWN_IP)

        assert result is None

    @patch("cowrieprocessor.enrichment.ip_classification.datacenter_matcher.requests.get")
    def test_partial_provider_failure(self, mock_get: Mock, datacenter_matcher: DatacenterMatcher) -> None:
        """Test partial provider failures allow continuation."""

        def mock_get_side_effect(url: str, **kwargs):
            if "digitalocean" in url:
                mock_response = Mock()
                mock_response.text = MOCK_DIGITALOCEAN_CSV
                mock_response.raise_for_status = Mock()
                return mock_response
            else:
                raise Exception("Provider unavailable")

        mock_get.side_effect = mock_get_side_effect

        datacenter_matcher._download_data()

        assert datacenter_matcher._provider_cidr_counts["digitalocean"] == 2

    def test_get_stats(self, datacenter_matcher: DatacenterMatcher, mock_all_network_requests) -> None:
        """Test get_stats() returns correct statistics."""
        # Use _update_data to properly set _data_loaded flag
        datacenter_matcher._update_data(force=True)

        datacenter_matcher.match(SAMPLE_DIGITALOCEAN_IP)
        datacenter_matcher.match(SAMPLE_UNKNOWN_IP)

        stats = datacenter_matcher.get_stats()
        assert stats["data_loaded"] is True
        # Total CIDRs from all 5 providers (digitalocean=2, linode=2, ovh=2, hetzner=2, vultr=2)
        assert stats["total_cidrs"] == 10
        assert stats["lookups"] == 2
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5
