"""Unit tests for cloud provider matcher (AWS, Azure, GCP, CloudFlare)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Check if pytricia is available
try:
    import pytricia

    PYTRICIA_AVAILABLE = True
except ImportError:
    PYTRICIA_AVAILABLE = False

from cowrieprocessor.enrichment.ip_classification.cloud_matcher import CloudProviderMatcher
from tests.fixtures.ip_classification_fixtures import (
    MOCK_AWS_CSV,
    MOCK_AZURE_CSV,
    MOCK_CLOUDFLARE_CSV,
    MOCK_GCP_CSV,
    SAMPLE_AWS_IP,
    SAMPLE_AZURE_IP,
    SAMPLE_CLOUDFLARE_IP,
    SAMPLE_GCP_IP,
    SAMPLE_UNKNOWN_IP,
)


@pytest.mark.skipif(not PYTRICIA_AVAILABLE, reason="pytricia not installed")
class TestCloudProviderMatcher:
    """Test CloudProviderMatcher class."""

    @pytest.fixture
    def cloud_matcher(self, tmp_path: Path) -> CloudProviderMatcher:
        """Create cloud matcher with temp cache directory."""
        return CloudProviderMatcher(
            data_url="https://raw.githubusercontent.com/rezmoss/cloud-provider-ip-addresses/main",
            update_interval_seconds=86400,
            cache_dir=tmp_path,
            request_timeout=30,
        )

    def test_matcher_initialization(self, cloud_matcher: CloudProviderMatcher) -> None:
        """Test matcher initialization."""
        assert cloud_matcher.update_interval_seconds == 86400
        assert cloud_matcher.request_timeout == 30
        assert not cloud_matcher._data_loaded
        assert len(cloud_matcher.tries) == 4
        assert "aws" in cloud_matcher.tries
        assert "azure" in cloud_matcher.tries
        assert "gcp" in cloud_matcher.tries
        assert "cloudflare" in cloud_matcher.tries

    def test_initialization_without_pytricia(self, tmp_path: Path) -> None:
        """Test initialization without pytricia raises ImportError."""
        with patch.dict("sys.modules", {"pytricia": None}):
            with patch("cowrieprocessor.enrichment.ip_classification.cloud_matcher.pytricia", None):
                with pytest.raises(ImportError, match="pytricia is required"):
                    CloudProviderMatcher(cache_dir=tmp_path)

    def test_download_data_all_providers(self, cloud_matcher: CloudProviderMatcher, mock_all_network_requests) -> None:
        """Test downloading data for all providers."""
        # Use _update_data to properly set _data_loaded flag
        cloud_matcher._update_data(force=True)

        assert cloud_matcher._data_loaded
        assert cloud_matcher._provider_cidr_counts["aws"] == 3
        assert cloud_matcher._provider_cidr_counts["azure"] == 2
        assert cloud_matcher._provider_cidr_counts["gcp"] == 2
        assert cloud_matcher._provider_cidr_counts["cloudflare"] == 2

    @patch("cowrieprocessor.enrichment.ip_classification.cloud_matcher.requests.get")
    def test_match_aws_ip(self, mock_get: Mock, cloud_matcher: CloudProviderMatcher) -> None:
        """Test matching an AWS IP address."""
        mock_response = Mock()
        mock_response.text = MOCK_AWS_CSV
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Load only AWS data for this test
        cloud_matcher._update_provider("aws")
        cloud_matcher._data_loaded = True  # Prevent _ensure_data_loaded() from loading all providers
        cloud_matcher.last_update = datetime.now(timezone.utc)

        result = cloud_matcher.match(SAMPLE_AWS_IP)

        assert result is not None
        assert result["provider"] == "aws"
        assert result["region"] == "us-east-1"
        assert result["service"] == "ec2"

    @patch("cowrieprocessor.enrichment.ip_classification.cloud_matcher.requests.get")
    def test_match_azure_ip(self, mock_get: Mock, cloud_matcher: CloudProviderMatcher) -> None:
        """Test matching an Azure IP address."""
        mock_response = Mock()
        mock_response.text = MOCK_AZURE_CSV
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        cloud_matcher._update_provider("azure")
        cloud_matcher._data_loaded = True  # Prevent _ensure_data_loaded() from loading all providers
        cloud_matcher.last_update = datetime.now(timezone.utc)

        result = cloud_matcher.match(SAMPLE_AZURE_IP)

        assert result is not None
        assert result["provider"] == "azure"
        assert result["region"] == "eastus"
        assert result["service"] == "compute"

    @patch("cowrieprocessor.enrichment.ip_classification.cloud_matcher.requests.get")
    def test_match_gcp_ip(self, mock_get: Mock, cloud_matcher: CloudProviderMatcher) -> None:
        """Test matching a GCP IP address."""
        mock_response = Mock()
        mock_response.text = MOCK_GCP_CSV
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        cloud_matcher._update_provider("gcp")
        cloud_matcher._data_loaded = True  # Prevent _ensure_data_loaded() from loading all providers
        cloud_matcher.last_update = datetime.now(timezone.utc)

        result = cloud_matcher.match(SAMPLE_GCP_IP)

        assert result is not None
        assert result["provider"] == "gcp"
        assert result["region"] == "us-central1"
        assert result["service"] == "compute"

    @patch("cowrieprocessor.enrichment.ip_classification.cloud_matcher.requests.get")
    def test_match_cloudflare_ip(self, mock_get: Mock, cloud_matcher: CloudProviderMatcher) -> None:
        """Test matching a CloudFlare IP address."""
        mock_response = Mock()
        mock_response.text = MOCK_CLOUDFLARE_CSV
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        cloud_matcher._update_provider("cloudflare")
        cloud_matcher._data_loaded = True  # Prevent _ensure_data_loaded() from loading all providers
        cloud_matcher.last_update = datetime.now(timezone.utc)

        result = cloud_matcher.match(SAMPLE_CLOUDFLARE_IP)

        assert result is not None
        assert result["provider"] == "cloudflare"
        assert result["region"] == "global"
        assert result["service"] == "cdn"

    @patch("cowrieprocessor.enrichment.ip_classification.cloud_matcher.requests.get")
    def test_match_non_cloud_ip(self, mock_get: Mock, cloud_matcher: CloudProviderMatcher) -> None:
        """Test matching a non-cloud IP returns None."""
        mock_response = Mock()
        mock_response.text = MOCK_AWS_CSV
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        cloud_matcher._update_provider("aws")

        result = cloud_matcher.match(SAMPLE_UNKNOWN_IP)

        assert result is None

    @patch("cowrieprocessor.enrichment.ip_classification.cloud_matcher.requests.get")
    def test_partial_provider_failure_continues(self, mock_get: Mock, cloud_matcher: CloudProviderMatcher) -> None:
        """Test that partial provider failures allow continuation."""

        def mock_get_side_effect(url: str, **kwargs):
            if "aws" in url:
                mock_response = Mock()
                mock_response.text = MOCK_AWS_CSV
                mock_response.raise_for_status = Mock()
                return mock_response
            else:
                raise Exception("Provider unavailable")

        mock_get.side_effect = mock_get_side_effect

        # Should not raise, just log errors for failed providers
        cloud_matcher._download_data()

        # AWS should have loaded
        assert cloud_matcher._provider_cidr_counts["aws"] == 3

    @patch("cowrieprocessor.enrichment.ip_classification.cloud_matcher.requests.get")
    def test_all_providers_fail(self, mock_get: Mock, cloud_matcher: CloudProviderMatcher) -> None:
        """Test that all providers failing raises ValueError."""
        mock_get.side_effect = Exception("Network error")

        with pytest.raises(ValueError, match="No valid CIDRs loaded from any cloud provider"):
            cloud_matcher._download_data()

    @patch("cowrieprocessor.enrichment.ip_classification.cloud_matcher.requests.get")
    def test_invalid_csv_format(self, mock_get: Mock, cloud_matcher: CloudProviderMatcher) -> None:
        """Test handling of invalid CSV format."""
        mock_response = Mock()
        mock_response.text = "invalid,csv,format\nno,headers,here"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(ValueError, match="No valid CIDRs parsed"):
            cloud_matcher._update_provider("aws")

    def test_get_stats(self, cloud_matcher: CloudProviderMatcher, mock_all_network_requests) -> None:
        """Test get_stats() returns correct statistics."""
        # Use _update_data to load all providers properly
        cloud_matcher._update_data(force=True)

        cloud_matcher.match(SAMPLE_AWS_IP)
        cloud_matcher.match(SAMPLE_UNKNOWN_IP)

        stats = cloud_matcher.get_stats()
        assert stats["data_loaded"] is True
        # Total CIDRs from all 4 providers (aws=3, azure=2, gcp=2, cloudflare=2)
        assert stats["total_cidrs"] == 9
        assert stats["provider_cidrs"]["aws"] == 3
        assert stats["lookups"] == 2
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    @patch("cowrieprocessor.enrichment.ip_classification.cloud_matcher.requests.get")
    def test_caches_to_disk(self, mock_get: Mock, cloud_matcher: CloudProviderMatcher) -> None:
        """Test that downloaded data is cached to disk."""
        mock_response = Mock()
        mock_response.text = MOCK_AWS_CSV
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        cloud_matcher._update_provider("aws")

        cache_file = cloud_matcher.cache_dir / "aws_ipv4.csv"
        assert cache_file.exists()
        assert cache_file.read_text() == MOCK_AWS_CSV
