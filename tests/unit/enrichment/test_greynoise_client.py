"""Unit tests for GreyNoise Community API client."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
import requests

from cowrieprocessor.enrichment.cache import EnrichmentCacheManager
from cowrieprocessor.enrichment.greynoise_client import GreyNoiseClient, GreyNoiseResult
from cowrieprocessor.enrichment.rate_limiting import RateLimiter


@pytest.fixture
def cache_manager(tmp_path: Path) -> EnrichmentCacheManager:
    """Create EnrichmentCacheManager for testing."""
    return EnrichmentCacheManager(base_dir=tmp_path)


@pytest.fixture
def rate_limiter() -> RateLimiter:
    """Create RateLimiter for testing."""
    return RateLimiter(rate=100.0, burst=100)


@pytest.fixture
def greynoise_client(cache_manager: EnrichmentCacheManager, rate_limiter: RateLimiter) -> GreyNoiseClient:
    """Create GreyNoiseClient for testing."""
    return GreyNoiseClient(
        api_key="test_api_key_12345",
        cache=cache_manager,
        rate_limiter=rate_limiter,
        ttl_days=7,
    )


class TestGreyNoiseResult:
    """Test GreyNoiseResult dataclass."""

    def test_malicious_scanner_result(self) -> None:
        """Test result for known malicious scanner."""
        result = GreyNoiseResult(
            ip_address="104.131.0.69",
            noise=True,
            riot=False,
            classification="malicious",
            name=None,
            last_seen=datetime(2024, 11, 5, tzinfo=timezone.utc),
        )

        assert result.ip_address == "104.131.0.69"
        assert result.noise is True
        assert result.riot is False
        assert result.classification == "malicious"
        assert result.name is None
        assert result.source == "greynoise"
        assert result.ttl_days == 7

    def test_benign_riot_result(self) -> None:
        """Test result for benign RIOT service."""
        result = GreyNoiseResult(
            ip_address="8.8.8.8",
            noise=False,
            riot=True,
            classification="benign",
            name="Google Public DNS",
            last_seen=datetime(2024, 11, 5, tzinfo=timezone.utc),
        )

        assert result.ip_address == "8.8.8.8"
        assert result.noise is False
        assert result.riot is True
        assert result.classification == "benign"
        assert result.name == "Google Public DNS"

    def test_unknown_result(self) -> None:
        """Test result for unknown IP."""
        result = GreyNoiseResult(
            ip_address="192.168.1.1",
            noise=False,
            riot=False,
            classification="unknown",
            name=None,
            last_seen=None,
        )

        assert result.ip_address == "192.168.1.1"
        assert result.noise is False
        assert result.riot is False
        assert result.classification == "unknown"
        assert result.last_seen is None


class TestGreyNoiseClient:
    """Test GreyNoiseClient functionality."""

    def test_client_initialization(self, greynoise_client: GreyNoiseClient) -> None:
        """Test client initialization."""
        assert greynoise_client.api_key == "test_api_key_12345"
        assert greynoise_client.ttl_days == 7
        assert greynoise_client.DAILY_QUOTA == 10000
        assert greynoise_client.stats['lookups'] == 0

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_lookup_malicious_scanner(
        self,
        mock_get: Mock,
        greynoise_client: GreyNoiseClient,
    ) -> None:
        """Test lookup of known malicious scanner."""
        # Mock API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ip": "104.131.0.69",
            "noise": True,
            "riot": False,
            "classification": "malicious",
            "name": None,
            "link": "https://viz.greynoise.io/ip/104.131.0.69",
            "last_seen": "2024-11-05",
        }
        mock_get.return_value = mock_response

        # Lookup IP
        result = greynoise_client.lookup_ip("104.131.0.69")

        # Verify result
        assert result is not None
        assert result.ip_address == "104.131.0.69"
        assert result.noise is True
        assert result.riot is False
        assert result.classification == "malicious"
        assert result.source == "greynoise"

        # Verify stats
        assert greynoise_client.stats['lookups'] == 1
        assert greynoise_client.stats['cache_misses'] == 1
        assert greynoise_client.stats['api_success'] == 1

        # Verify API call
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "104.131.0.69" in call_args[0][0]
        assert call_args[1]['headers']['key'] == "test_api_key_12345"

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_lookup_benign_riot(
        self,
        mock_get: Mock,
        greynoise_client: GreyNoiseClient,
    ) -> None:
        """Test lookup of benign RIOT service."""
        # Mock API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ip": "8.8.8.8",
            "noise": False,
            "riot": True,
            "classification": "benign",
            "name": "Google Public DNS",
            "link": "https://viz.greynoise.io/riot/8.8.8.8",
            "last_seen": "2024-11-05",
        }
        mock_get.return_value = mock_response

        # Lookup IP
        result = greynoise_client.lookup_ip("8.8.8.8")

        # Verify result
        assert result is not None
        assert result.ip_address == "8.8.8.8"
        assert result.noise is False
        assert result.riot is True
        assert result.classification == "benign"
        assert result.name == "Google Public DNS"

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_lookup_not_found(
        self,
        mock_get: Mock,
        greynoise_client: GreyNoiseClient,
    ) -> None:
        """Test lookup of IP not in GreyNoise database."""
        # Mock 404 response
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        # Lookup IP
        result = greynoise_client.lookup_ip("192.168.1.1")

        # Verify result (should return unknown classification)
        assert result is not None
        assert result.ip_address == "192.168.1.1"
        assert result.noise is False
        assert result.riot is False
        assert result.classification == "unknown"
        assert greynoise_client.stats['api_success'] == 1

    def test_cache_hit(self, greynoise_client: GreyNoiseClient) -> None:
        """Test cache hit scenario."""
        # Store result in cache
        cached_data = {
            'ip_address': "8.8.8.8",
            'noise': False,
            'riot': True,
            'classification': "benign",
            'name': "Google Public DNS",
            'last_seen': "2024-11-05T00:00:00+00:00",
            'source': "greynoise",
            'cached_at': datetime.now(timezone.utc).isoformat(),
            'ttl_days': 7,
        }
        greynoise_client.cache.store_cached("greynoise", "8.8.8.8", cached_data)

        # Lookup IP (should hit cache)
        result = greynoise_client.lookup_ip("8.8.8.8")

        # Verify result
        assert result is not None
        assert result.ip_address == "8.8.8.8"
        assert result.riot is True
        assert result.name == "Google Public DNS"

        # Verify stats
        assert greynoise_client.stats['lookups'] == 1
        assert greynoise_client.stats['cache_hits'] == 1
        assert greynoise_client.stats['api_success'] == 0  # No API call

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_http_401_invalid_key(
        self,
        mock_get: Mock,
        greynoise_client: GreyNoiseClient,
    ) -> None:
        """Test HTTP 401 authentication failure."""
        # Mock 401 response
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        # Lookup IP
        result = greynoise_client.lookup_ip("8.8.8.8")

        # Verify failure
        assert result is None
        assert greynoise_client.stats['api_failures'] == 1
        assert greynoise_client.stats['errors'] == 1

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_http_429_rate_limit(
        self,
        mock_get: Mock,
        greynoise_client: GreyNoiseClient,
    ) -> None:
        """Test HTTP 429 rate limit exceeded."""
        # Mock 429 response
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_get.return_value = mock_response

        # Lookup IP
        result = greynoise_client.lookup_ip("8.8.8.8")

        # Verify failure
        assert result is None
        assert greynoise_client.stats['quota_exceeded'] == 3  # Incremented on each retry
        assert greynoise_client.stats['api_failures'] == 3  # Incremented on each retry

        # Verify retries (should retry 3 times)
        assert mock_get.call_count == 3

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_http_500_server_error(
        self,
        mock_get: Mock,
        greynoise_client: GreyNoiseClient,
    ) -> None:
        """Test HTTP 500 server error."""
        # Mock 500 response
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
        mock_get.return_value = mock_response

        # Lookup IP
        result = greynoise_client.lookup_ip("8.8.8.8")

        # Verify failure
        assert result is None
        assert greynoise_client.stats['api_failures'] == 1
        assert greynoise_client.stats['errors'] == 1

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_timeout_with_retry(
        self,
        mock_get: Mock,
        greynoise_client: GreyNoiseClient,
    ) -> None:
        """Test timeout with exponential backoff retry."""
        # Mock timeout
        mock_get.side_effect = requests.exceptions.Timeout("Connection timeout")

        # Lookup IP
        result = greynoise_client.lookup_ip("8.8.8.8")

        # Verify failure after retries
        assert result is None
        assert greynoise_client.stats['api_failures'] == 1
        assert mock_get.call_count == 3  # Should retry 3 times

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_connection_error(
        self,
        mock_get: Mock,
        greynoise_client: GreyNoiseClient,
    ) -> None:
        """Test connection error handling."""
        # Mock connection error
        mock_get.side_effect = requests.exceptions.ConnectionError("Network unreachable")

        # Lookup IP
        result = greynoise_client.lookup_ip("8.8.8.8")

        # Verify failure
        assert result is None
        assert greynoise_client.stats['api_failures'] == 1
        assert greynoise_client.stats['errors'] == 1

    def test_quota_tracking_fresh_day(self, greynoise_client: GreyNoiseClient) -> None:
        """Test quota tracking on fresh day."""
        # Check initial quota
        remaining = greynoise_client.get_remaining_quota()

        # Should have full quota
        assert remaining == 10000
        assert greynoise_client.stats['lookups'] == 0

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_quota_decrement(
        self,
        mock_get: Mock,
        greynoise_client: GreyNoiseClient,
    ) -> None:
        """Test quota decrements after successful API call."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ip": "8.8.8.8",
            "noise": False,
            "riot": True,
            "classification": "benign",
            "name": "Google Public DNS",
            "last_seen": "2024-11-05",
        }
        mock_get.return_value = mock_response

        # Initial quota
        initial_quota = greynoise_client.get_remaining_quota()
        assert initial_quota == 10000

        # Make API call
        result = greynoise_client.lookup_ip("8.8.8.8")
        assert result is not None

        # Check quota decreased
        remaining = greynoise_client.get_remaining_quota()
        assert remaining == 9999

    def test_quota_exhausted_blocks_lookup(
        self,
        greynoise_client: GreyNoiseClient,
    ) -> None:
        """Test quota exhaustion blocks new lookups."""
        # Simulate exhausted quota
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        quota_key = f"{greynoise_client.QUOTA_KEY_PREFIX}{today}"
        greynoise_client.cache.store_cached(
            "greynoise",
            quota_key,
            {'count': 10000, 'date': today},
        )

        # Check quota
        remaining = greynoise_client.get_remaining_quota()
        assert remaining == 0

        # Try lookup (should fail without API call)
        result = greynoise_client.lookup_ip("8.8.8.8")
        assert result is None
        assert greynoise_client.stats['quota_exceeded'] == 1

    def test_quota_reset_next_day(self, greynoise_client: GreyNoiseClient) -> None:
        """Test quota resets on new day."""
        # Simulate quota from yesterday
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d')
        quota_key_yesterday = f"{greynoise_client.QUOTA_KEY_PREFIX}{yesterday}"
        greynoise_client.cache.store_cached(
            "greynoise",
            quota_key_yesterday,
            {'count': 10000, 'date': yesterday},
        )

        # Check today's quota (should be full)
        remaining = greynoise_client.get_remaining_quota()
        assert remaining == 10000

    def test_result_serialization(self, greynoise_client: GreyNoiseClient) -> None:
        """Test result to dict conversion."""
        result = GreyNoiseResult(
            ip_address="8.8.8.8",
            noise=False,
            riot=True,
            classification="benign",
            name="Google Public DNS",
            last_seen=datetime(2024, 11, 5, tzinfo=timezone.utc),
        )

        # Convert to dict
        result_dict = greynoise_client._result_to_dict(result)

        # Verify fields
        assert result_dict['ip_address'] == "8.8.8.8"
        assert result_dict['noise'] is False
        assert result_dict['riot'] is True
        assert result_dict['classification'] == "benign"
        assert result_dict['name'] == "Google Public DNS"
        assert result_dict['last_seen'] == "2024-11-05T00:00:00+00:00"
        assert result_dict['source'] == "greynoise"
        assert 'cached_at' in result_dict
        assert result_dict['ttl_days'] == 7

    def test_result_deserialization(self, greynoise_client: GreyNoiseClient) -> None:
        """Test dict to result conversion."""
        data = {
            'ip_address': "8.8.8.8",
            'noise': False,
            'riot': True,
            'classification': "benign",
            'name': "Google Public DNS",
            'last_seen': "2024-11-05T00:00:00+00:00",
            'source': "greynoise",
            'cached_at': datetime.now(timezone.utc).isoformat(),
            'ttl_days': 7,
        }

        # Convert to result
        result = greynoise_client._dict_to_result(data)

        # Verify fields
        assert result.ip_address == "8.8.8.8"
        assert result.noise is False
        assert result.riot is True
        assert result.classification == "benign"
        assert result.name == "Google Public DNS"
        assert result.last_seen == datetime(2024, 11, 5, tzinfo=timezone.utc)
        assert result.source == "greynoise"
        assert result.ttl_days == 7

    def test_stats_tracking(self, greynoise_client: GreyNoiseClient) -> None:
        """Test statistics tracking."""
        # Initial stats
        stats = greynoise_client.get_stats()
        assert stats['lookups'] == 0
        assert stats['cache_hits'] == 0
        assert stats['api_success'] == 0

        # Reset stats
        greynoise_client.reset_stats()
        assert greynoise_client.stats['lookups'] == 0

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_malformed_json_response(
        self,
        mock_get: Mock,
        greynoise_client: GreyNoiseClient,
    ) -> None:
        """Test handling of malformed JSON response."""
        # Mock malformed response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_get.return_value = mock_response

        # Lookup IP
        result = greynoise_client.lookup_ip("8.8.8.8")

        # Verify failure
        assert result is None
        assert greynoise_client.stats['api_failures'] == 1
        assert greynoise_client.stats['errors'] == 1

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_missing_required_fields(
        self,
        mock_get: Mock,
        greynoise_client: GreyNoiseClient,
    ) -> None:
        """Test handling of response missing required fields."""
        # Mock incomplete response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ip": "8.8.8.8",
            # Missing noise, riot, classification
        }
        mock_get.return_value = mock_response

        # Lookup IP
        result = greynoise_client.lookup_ip("8.8.8.8")

        # Should still create result with defaults
        assert result is not None
        assert result.ip_address == "8.8.8.8"
        assert result.noise is False  # Default
        assert result.riot is False  # Default

    def test_invalid_last_seen_date(self, greynoise_client: GreyNoiseClient) -> None:
        """Test handling of invalid last_seen date format."""
        data = {
            "ip": "8.8.8.8",
            "noise": False,
            "riot": True,
            "classification": "benign",
            "name": "Google Public DNS",
            "last_seen": "invalid-date-format",
        }

        # Parse response (should handle gracefully)
        result = greynoise_client._parse_api_response("8.8.8.8", data)

        assert result is not None
        assert result.last_seen is None  # Invalid date should be None

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_cloudflare_dns_lookup(
        self,
        mock_get: Mock,
        greynoise_client: GreyNoiseClient,
    ) -> None:
        """Test lookup of Cloudflare DNS (1.1.1.1)."""
        # Mock API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ip": "1.1.1.1",
            "noise": False,
            "riot": True,
            "classification": "benign",
            "name": "Cloudflare Public DNS",
            "link": "https://viz.greynoise.io/riot/1.1.1.1",
            "last_seen": "2024-11-05",
        }
        mock_get.return_value = mock_response

        # Lookup IP
        result = greynoise_client.lookup_ip("1.1.1.1")

        # Verify result
        assert result is not None
        assert result.ip_address == "1.1.1.1"
        assert result.riot is True
        assert result.name == "Cloudflare Public DNS"
        assert result.classification == "benign"
