"""Tests for VirusTotal quota management."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import vt

from cowrieprocessor.enrichment.virustotal_quota import QuotaInfo, VirusTotalQuotaManager


class TestQuotaInfo:
    """Test QuotaInfo data class."""

    def test_quota_info_creation(self) -> None:
        """Test QuotaInfo creation and properties."""
        quota = QuotaInfo(
            daily_requests_used=100,
            daily_requests_limit=500,
            hourly_requests_used=50,
            hourly_requests_limit=200,
            monthly_requests_used=1000,
            monthly_requests_limit=5000,
            api_requests_used=250,
            api_requests_limit=1000,
        )

        assert quota.daily_remaining == 400
        assert quota.hourly_remaining == 150
        assert quota.api_remaining == 750
        assert quota.daily_usage_percent == 20.0
        assert quota.hourly_usage_percent == 25.0

    def test_quota_info_edge_cases(self) -> None:
        """Test QuotaInfo edge cases."""
        # Zero limits
        quota = QuotaInfo(
            daily_requests_used=0,
            daily_requests_limit=0,
            hourly_requests_used=0,
            hourly_requests_limit=0,
            monthly_requests_used=0,
            monthly_requests_limit=0,
            api_requests_used=0,
            api_requests_limit=0,
        )

        assert quota.daily_usage_percent == 100.0
        assert quota.hourly_usage_percent == 100.0

        # Over limit
        quota = QuotaInfo(
            daily_requests_used=600,
            daily_requests_limit=500,
            hourly_requests_used=250,
            hourly_requests_limit=200,
            monthly_requests_used=1000,
            monthly_requests_limit=5000,
            api_requests_used=250,
            api_requests_limit=1000,
        )

        assert quota.daily_remaining == 0
        assert quota.hourly_remaining == 0


class TestVirusTotalQuotaManager:
    """Test VirusTotalQuotaManager class."""

    def test_init(self) -> None:
        """Test QuotaManager initialization."""
        manager = VirusTotalQuotaManager("test-api-key", cache_ttl=600)

        assert manager.api_key == "test-api-key"
        assert manager.cache_ttl == 600
        assert manager._client is None
        assert manager._quota_cache is None
        assert manager._cache_timestamp == 0.0

    @patch('cowrieprocessor.enrichment.virustotal_quota.vt.Client')
    def test_get_quota_info_success(self, mock_client_class: Mock) -> None:
        """Test successful quota info retrieval."""
        # Mock client responses
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Mock user info response
        mock_client.get_json.side_effect = [
            # First call: /users/me
            {"data": {"id": "test-user-id"}},
            # Second call: /users/{id}/overall_quotas
            {
                "data": {
                    "attributes": {
                        "api_requests_daily": 500,
                        "api_requests_hourly": 200,
                        "api_requests_monthly": 5000,
                        "api_requests": 1000,
                    }
                }
            },
            # Third call: /users/{id}/api_usage
            {
                "data": {
                    "attributes": {
                        "api_requests_daily": 100,
                        "api_requests_hourly": 50,
                        "api_requests_monthly": 1000,
                        "api_requests": 250,
                    }
                }
            },
        ]

        manager = VirusTotalQuotaManager("test-api-key")
        quota_info = manager.get_quota_info()

        assert quota_info is not None
        assert quota_info.daily_requests_used == 100
        assert quota_info.daily_requests_limit == 500
        assert quota_info.hourly_requests_used == 50
        assert quota_info.hourly_requests_limit == 200
        assert quota_info.daily_usage_percent == 20.0
        assert quota_info.hourly_usage_percent == 25.0

    @patch('cowrieprocessor.enrichment.virustotal_quota.vt.Client')
    def test_get_quota_info_caching(self, mock_client_class: Mock) -> None:
        """Test quota info caching."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Mock successful response
        mock_client.get_json.side_effect = [
            {"data": {"id": "test-user-id"}},
            {
                "data": {
                    "attributes": {
                        "api_requests_daily": 500,
                        "api_requests_hourly": 200,
                        "api_requests_monthly": 5000,
                        "api_requests": 1000,
                    }
                }
            },
            {
                "data": {
                    "attributes": {
                        "api_requests_daily": 100,
                        "api_requests_hourly": 50,
                        "api_requests_monthly": 1000,
                        "api_requests": 250,
                    }
                }
            },
        ]

        manager = VirusTotalQuotaManager("test-api-key", cache_ttl=3600)

        # First call should hit the API
        quota_info1 = manager.get_quota_info()
        assert quota_info1 is not None
        assert mock_client.get_json.call_count == 3

        # Second call should use cache
        quota_info2 = manager.get_quota_info()
        assert quota_info2 is not None
        assert quota_info1 is quota_info2  # Same object from cache
        assert mock_client.get_json.call_count == 3  # No additional calls

    @patch('cowrieprocessor.enrichment.virustotal_quota.vt.Client')
    def test_get_quota_info_force_refresh(self, mock_client_class: Mock) -> None:
        """Test quota info force refresh."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Mock successful response
        mock_client.get_json.side_effect = [
            {"data": {"id": "test-user-id"}},
            {
                "data": {
                    "attributes": {
                        "api_requests_daily": 500,
                        "api_requests_hourly": 200,
                        "api_requests_monthly": 5000,
                        "api_requests": 1000,
                    }
                }
            },
            {
                "data": {
                    "attributes": {
                        "api_requests_daily": 100,
                        "api_requests_hourly": 50,
                        "api_requests_monthly": 1000,
                        "api_requests": 250,
                    }
                }
            },
            # Second round for force refresh
            {"data": {"id": "test-user-id"}},
            {
                "data": {
                    "attributes": {
                        "api_requests_daily": 500,
                        "api_requests_hourly": 200,
                        "api_requests_monthly": 5000,
                        "api_requests": 1000,
                    }
                }
            },
            {
                "data": {
                    "attributes": {
                        "api_requests_daily": 150,
                        "api_requests_hourly": 75,
                        "api_requests_monthly": 1500,
                        "api_requests": 350,
                    }
                }
            },
        ]

        manager = VirusTotalQuotaManager("test-api-key", cache_ttl=3600)

        # First call
        quota_info1 = manager.get_quota_info()
        assert quota_info1 is not None
        assert quota_info1.daily_requests_used == 100

        # Force refresh call
        quota_info2 = manager.get_quota_info(force_refresh=True)
        assert quota_info2 is not None
        assert quota_info2.daily_requests_used == 150
        assert mock_client.get_json.call_count == 6

    @patch('cowrieprocessor.enrichment.virustotal_quota.vt.Client')
    def test_get_quota_info_error(self, mock_client_class: Mock) -> None:
        """Test quota info retrieval with error."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Mock API error
        mock_client.get_json.side_effect = vt.APIError("Test error", "TestCode")

        manager = VirusTotalQuotaManager("test-api-key")
        quota_info = manager.get_quota_info()

        assert quota_info is None

    def test_can_make_request(self) -> None:
        """Test can_make_request logic."""
        manager = VirusTotalQuotaManager("test-api-key")

        # Test with no quota manager (should allow)
        assert manager.can_make_request() is True

        # Mock quota info
        quota_info = QuotaInfo(
            daily_requests_used=450,  # 90% of 500
            daily_requests_limit=500,
            hourly_requests_used=180,  # 90% of 200
            hourly_requests_limit=200,
            monthly_requests_used=1000,
            monthly_requests_limit=5000,
            api_requests_used=250,
            api_requests_limit=1000,
        )

        manager._quota_cache = quota_info
        manager._cache_timestamp = 1000.0

        # Should allow at 90% threshold (exactly 90% should be allowed)
        assert manager.can_make_request(90.0) is True

        # Should not allow at 85% threshold
        assert manager.can_make_request(85.0) is False

    def test_get_backoff_time(self) -> None:
        """Test backoff time calculation."""
        manager = VirusTotalQuotaManager("test-api-key")

        # Test with no quota manager
        assert manager.get_backoff_time() == 60.0

        # Test different usage levels
        test_cases = [
            (95, 3600.0),  # >= 95% -> 1 hour
            (90, 1800.0),  # >= 90% -> 30 minutes
            (80, 900.0),  # >= 80% -> 15 minutes
            (50, 60.0),  # < 80% -> 1 minute
        ]

        for usage_percent, expected_backoff in test_cases:
            quota_info = QuotaInfo(
                daily_requests_used=int(500 * usage_percent / 100),
                daily_requests_limit=500,
                hourly_requests_used=int(200 * usage_percent / 100),
                hourly_requests_limit=200,
                monthly_requests_used=1000,
                monthly_requests_limit=5000,
                api_requests_used=250,
                api_requests_limit=1000,
            )

            manager._quota_cache = quota_info
            manager._cache_timestamp = 1000.0

            assert manager.get_backoff_time() == expected_backoff

    def test_get_quota_summary(self) -> None:
        """Test quota summary generation."""
        manager = VirusTotalQuotaManager("test-api-key")

        # Test with no quota manager
        summary = manager.get_quota_summary()
        assert summary["status"] == "unknown"
        assert "message" in summary

        # Test with quota info
        quota_info = QuotaInfo(
            daily_requests_used=450,  # 90%
            daily_requests_limit=500,
            hourly_requests_used=180,  # 90%
            hourly_requests_limit=200,
            monthly_requests_used=1000,
            monthly_requests_limit=5000,
            api_requests_used=250,
            api_requests_limit=1000,
        )

        manager._quota_cache = quota_info
        manager._cache_timestamp = 1000.0

        summary = manager.get_quota_summary()

        assert summary["status"] == "warning"  # 90% usage
        assert summary["daily"]["usage_percent"] == 90.0
        assert summary["hourly"]["usage_percent"] == 90.0
        assert summary["can_make_request"] is True
        assert "recommended_backoff" in summary

        # Test critical status
        quota_info = QuotaInfo(
            daily_requests_used=475,  # 95%
            daily_requests_limit=500,
            hourly_requests_used=190,  # 95%
            hourly_requests_limit=200,
            monthly_requests_used=1000,
            monthly_requests_limit=5000,
            api_requests_used=250,
            api_requests_limit=1000,
        )

        manager._quota_cache = quota_info
        summary = manager.get_quota_summary()
        assert summary["status"] == "critical"


if __name__ == "__main__":
    pytest.main([__file__])
