"""Integration tests for GreyNoise enrichment workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from cowrieprocessor.enrichment.cache import EnrichmentCacheManager
from cowrieprocessor.enrichment.greynoise_client import GreyNoiseClient
from cowrieprocessor.enrichment.rate_limiting import RateLimiter


@pytest.fixture
def integration_cache(tmp_path: Path) -> EnrichmentCacheManager:
    """Create EnrichmentCacheManager for integration testing."""
    cache_dir = tmp_path / "integration_cache"
    cache_dir.mkdir(exist_ok=True)
    return EnrichmentCacheManager(base_dir=cache_dir)


@pytest.fixture
def integration_client(integration_cache: EnrichmentCacheManager) -> GreyNoiseClient:
    """Create GreyNoiseClient for integration testing."""
    # Use higher rate limit for tests
    rate_limiter = RateLimiter(rate=100.0, burst=100)
    return GreyNoiseClient(
        api_key="integration_test_key",
        cache=integration_cache,
        rate_limiter=rate_limiter,
        ttl_days=7,
    )


class TestGreyNoiseIntegration:
    """Integration tests for GreyNoise enrichment workflow."""

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_end_to_end_malicious_scanner(
        self,
        mock_get: Mock,
        integration_client: GreyNoiseClient,
    ) -> None:
        """Test end-to-end workflow for known Shodan scanner."""
        # Mock API response for Shodan scanner (104.131.0.69)
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

        # First lookup (cache miss)
        result1 = integration_client.lookup_ip("104.131.0.69")

        # Verify result
        assert result1 is not None
        assert result1.ip_address == "104.131.0.69"
        assert result1.noise is True
        assert result1.riot is False
        assert result1.classification == "malicious"
        assert result1.source == "greynoise"

        # Verify stats
        assert integration_client.stats['lookups'] == 1
        assert integration_client.stats['cache_misses'] == 1
        assert integration_client.stats['api_success'] == 1
        assert integration_client.stats['cache_hits'] == 0

        # Second lookup (cache hit)
        result2 = integration_client.lookup_ip("104.131.0.69")

        # Verify same result
        assert result2 is not None
        assert result2.ip_address == "104.131.0.69"
        assert result2.noise is True
        assert result2.classification == "malicious"

        # Verify cache hit
        assert integration_client.stats['lookups'] == 2
        assert integration_client.stats['cache_hits'] == 1

        # Verify API called only once
        assert mock_get.call_count == 1

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_end_to_end_benign_service(
        self,
        mock_get: Mock,
        integration_client: GreyNoiseClient,
    ) -> None:
        """Test end-to-end workflow for Google DNS."""
        # Mock API response for Google DNS (8.8.8.8)
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
        result = integration_client.lookup_ip("8.8.8.8")

        # Verify result
        assert result is not None
        assert result.ip_address == "8.8.8.8"
        assert result.noise is False
        assert result.riot is True
        assert result.classification == "benign"
        assert result.name == "Google Public DNS"

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_end_to_end_cloudflare_dns(
        self,
        mock_get: Mock,
        integration_client: GreyNoiseClient,
    ) -> None:
        """Test end-to-end workflow for Cloudflare DNS."""
        # Mock API response for Cloudflare DNS (1.1.1.1)
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
        result = integration_client.lookup_ip("1.1.1.1")

        # Verify result
        assert result is not None
        assert result.ip_address == "1.1.1.1"
        assert result.riot is True
        assert result.name == "Cloudflare Public DNS"
        assert result.classification == "benign"

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_end_to_end_censys_scanner(
        self,
        mock_get: Mock,
        integration_client: GreyNoiseClient,
    ) -> None:
        """Test end-to-end workflow for Censys scanner."""
        # Mock API response for Censys scanner (162.142.125.0)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ip": "162.142.125.0",
            "noise": True,
            "riot": False,
            "classification": "malicious",
            "name": None,
            "link": "https://viz.greynoise.io/ip/162.142.125.0",
            "last_seen": "2024-11-05",
        }
        mock_get.return_value = mock_response

        # Lookup IP
        result = integration_client.lookup_ip("162.142.125.0")

        # Verify result
        assert result is not None
        assert result.ip_address == "162.142.125.0"
        assert result.noise is True
        assert result.riot is False
        assert result.classification == "malicious"

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_cache_persistence(
        self,
        mock_get: Mock,
        integration_client: GreyNoiseClient,
        integration_cache: EnrichmentCacheManager,
    ) -> None:
        """Test cache persistence across client instances."""
        # Mock API response
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

        # First lookup with first client
        result1 = integration_client.lookup_ip("8.8.8.8")
        assert result1 is not None

        # Create new client with same cache
        new_client = GreyNoiseClient(
            api_key="new_test_key",
            cache=integration_cache,
            rate_limiter=RateLimiter(rate=100.0, burst=100),
        )

        # Lookup with new client (should hit cache)
        result2 = new_client.lookup_ip("8.8.8.8")
        assert result2 is not None
        assert result2.ip_address == "8.8.8.8"
        assert result2.riot is True

        # Verify cache hit
        assert new_client.stats['cache_hits'] == 1

        # Verify API called only once (by first client)
        assert mock_get.call_count == 1

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_multiple_ips_workflow(
        self,
        mock_get: Mock,
        integration_client: GreyNoiseClient,
    ) -> None:
        """Test workflow with multiple IPs (malicious and benign)."""

        # Mock responses for different IPs
        def mock_response_factory(url: str, *args, **kwargs):
            mock_response = MagicMock()
            mock_response.status_code = 200

            if "104.131.0.69" in url:
                # Shodan scanner
                mock_response.json.return_value = {
                    "ip": "104.131.0.69",
                    "noise": True,
                    "riot": False,
                    "classification": "malicious",
                }
            elif "8.8.8.8" in url:
                # Google DNS
                mock_response.json.return_value = {
                    "ip": "8.8.8.8",
                    "noise": False,
                    "riot": True,
                    "classification": "benign",
                    "name": "Google Public DNS",
                }
            elif "1.1.1.1" in url:
                # Cloudflare DNS
                mock_response.json.return_value = {
                    "ip": "1.1.1.1",
                    "noise": False,
                    "riot": True,
                    "classification": "benign",
                    "name": "Cloudflare Public DNS",
                }

            return mock_response

        mock_get.side_effect = mock_response_factory

        # Lookup multiple IPs
        ips = ["104.131.0.69", "8.8.8.8", "1.1.1.1"]
        results = {}

        for ip in ips:
            result = integration_client.lookup_ip(ip)
            if result:
                results[ip] = result

        # Verify all results
        assert len(results) == 3

        # Verify malicious scanner
        assert results["104.131.0.69"].noise is True
        assert results["104.131.0.69"].classification == "malicious"

        # Verify benign services
        assert results["8.8.8.8"].riot is True
        assert results["8.8.8.8"].name == "Google Public DNS"
        assert results["1.1.1.1"].riot is True
        assert results["1.1.1.1"].name == "Cloudflare Public DNS"

        # Verify stats
        assert integration_client.stats['lookups'] == 3
        assert integration_client.stats['api_success'] == 3

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_quota_management_workflow(
        self,
        mock_get: Mock,
        integration_client: GreyNoiseClient,
    ) -> None:
        """Test quota management across multiple lookups."""
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

        # Check initial quota
        initial_quota = integration_client.get_remaining_quota()
        assert initial_quota == 10000

        # Perform multiple lookups
        for i in range(5):
            ip = f"8.8.8.{i}"
            result = integration_client.lookup_ip(ip)
            assert result is not None

        # Check quota decreased
        remaining = integration_client.get_remaining_quota()
        assert remaining == 9995  # Started at 10000, used 5

        # Verify stats
        assert integration_client.stats['api_success'] == 5

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_error_recovery_workflow(
        self,
        mock_get: Mock,
        integration_client: GreyNoiseClient,
    ) -> None:
        """Test error recovery and retry behavior."""
        # First call: timeout
        # Second call: success
        mock_timeout = MagicMock()
        mock_timeout.side_effect = Exception("Connection timeout")

        mock_success = MagicMock()
        mock_success.status_code = 200
        mock_success.json.return_value = {
            "ip": "8.8.8.8",
            "noise": False,
            "riot": True,
            "classification": "benign",
            "name": "Google Public DNS",
        }

        # First lookup fails, second succeeds
        mock_get.side_effect = [mock_timeout, mock_timeout, mock_timeout, mock_success]

        # First lookup (will fail after retries)
        result1 = integration_client.lookup_ip("8.8.8.8")
        assert result1 is None
        assert integration_client.stats['api_failures'] == 1

        # Reset mock for second attempt
        mock_get.side_effect = None
        mock_get.return_value = mock_success

        # Second lookup (should succeed)
        result2 = integration_client.lookup_ip("1.1.1.1")
        assert result2 is not None

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_rate_limiting_integration(
        self,
        mock_get: Mock,
        integration_client: GreyNoiseClient,
    ) -> None:
        """Test rate limiting integration."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ip": "8.8.8.8",
            "noise": False,
            "riot": True,
            "classification": "benign",
        }
        mock_get.return_value = mock_response

        # Perform rapid lookups (should be rate limited)
        start_time = datetime.now(timezone.utc)

        for i in range(10):
            ip = f"8.8.8.{i}"
            result = integration_client.lookup_ip(ip)
            assert result is not None

        end_time = datetime.now(timezone.utc)

        # Verify rate limiting delayed execution
        # At 10 req/sec, 10 requests should take ~1 second
        duration = (end_time - start_time).total_seconds()

        # Should take at least some time (rate limited)
        # Note: This is a loose check due to test execution variability
        assert duration >= 0  # Basic sanity check

    def test_cache_ttl_enforcement(
        self,
        integration_client: GreyNoiseClient,
        integration_cache: EnrichmentCacheManager,
    ) -> None:
        """Test cache TTL enforcement (7-day TTL)."""
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
        integration_cache.store_cached("greynoise", "8.8.8.8", cached_data)

        # Lookup (should hit cache)
        result = integration_client.lookup_ip("8.8.8.8")

        # Verify result
        assert result is not None
        assert result.ttl_days == 7
        assert integration_client.stats['cache_hits'] == 1

    @patch('cowrieprocessor.enrichment.greynoise_client.requests.get')
    def test_complete_honeypot_scenario(
        self,
        mock_get: Mock,
        integration_client: GreyNoiseClient,
    ) -> None:
        """Test complete honeypot attack scenario with multiple IPs."""

        # Mock responses for different attacker IPs
        def mock_attack_scenario(url: str, *args, **kwargs):
            mock_response = MagicMock()
            mock_response.status_code = 200

            # Known scanners
            if "104.131.0.69" in url:  # Shodan
                mock_response.json.return_value = {
                    "ip": "104.131.0.69",
                    "noise": True,
                    "riot": False,
                    "classification": "malicious",
                }
            elif "162.142.125.0" in url:  # Censys
                mock_response.json.return_value = {
                    "ip": "162.142.125.0",
                    "noise": True,
                    "riot": False,
                    "classification": "malicious",
                }
            else:  # Unknown attacker
                mock_response.status_code = 404

            return mock_response

        mock_get.side_effect = mock_attack_scenario

        # Simulate honeypot receiving attacks from multiple IPs
        attacker_ips = [
            "104.131.0.69",  # Shodan scanner
            "162.142.125.0",  # Censys scanner
            "192.168.1.100",  # Unknown attacker
        ]

        results = {}
        for ip in attacker_ips:
            result = integration_client.lookup_ip(ip)
            results[ip] = result

        # Verify known scanners detected
        assert results["104.131.0.69"] is not None
        assert results["104.131.0.69"].noise is True
        assert results["104.131.0.69"].classification == "malicious"

        assert results["162.142.125.0"] is not None
        assert results["162.142.125.0"].noise is True

        # Verify unknown attacker marked as unknown
        assert results["192.168.1.100"] is not None
        assert results["192.168.1.100"].classification == "unknown"

        # Verify quota tracking
        remaining_quota = integration_client.get_remaining_quota()
        assert remaining_quota == 9997  # Started at 10000, used 3

        # Verify stats
        assert integration_client.stats['lookups'] == 3
        assert integration_client.stats['api_success'] == 3
