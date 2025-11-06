"""Integration tests for Team Cymru ASN enrichment.

These tests use known public IPs with stable ASN assignments.
Tests are designed to work with real DNS/netcat lookups when network is available,
and can also work with mocked responses for CI/CD environments.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from cowrieprocessor.enrichment.cache import EnrichmentCacheManager
from cowrieprocessor.enrichment.cymru_client import CymruClient
from cowrieprocessor.enrichment.rate_limiting import RateLimiter

# Known stable IP-to-ASN mappings for testing
KNOWN_IPS = {
    "8.8.8.8": {"asn": 15169, "org_contains": "GOOGLE", "country": "US", "registry": "arin"},
    "1.1.1.1": {"asn": 13335, "org_contains": "CLOUDFLARE", "country": "US", "registry": "arin"},
    "54.239.28.85": {"asn": 16509, "org_contains": "AMAZON", "country": "US", "registry": "arin"},
}

# Environment variable to force mock mode (useful for CI)
USE_MOCK = os.environ.get("USE_MOCK_APIS", "false").lower() == "true"


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    """Create temporary cache directory."""
    cache_path = tmp_path / "cymru_cache"
    cache_path.mkdir(parents=True, exist_ok=True)
    return cache_path


@pytest.fixture
def cache_manager(cache_dir: Path) -> EnrichmentCacheManager:
    """Create cache manager for testing."""
    return EnrichmentCacheManager(base_dir=cache_dir)


@pytest.fixture
def rate_limiter() -> RateLimiter:
    """Create rate limiter for testing."""
    # Use generous rate limit for integration tests
    return RateLimiter(rate=10.0, burst=10)


@pytest.fixture
def cymru_client(cache_manager: EnrichmentCacheManager, rate_limiter: RateLimiter) -> CymruClient:
    """Create Cymru client for testing."""
    return CymruClient(cache=cache_manager, rate_limiter=rate_limiter, ttl_days=90)


def mock_dns_response(ip_address: str) -> list[Mock]:
    """Create mock DNS response for known IPs."""
    if ip_address not in KNOWN_IPS:
        raise ValueError(f"Unknown test IP: {ip_address}")

    expected = KNOWN_IPS[ip_address]
    mock_rdata = Mock()
    mock_rdata.strings = [
        f"{expected['asn']} | {ip_address}/24 | {expected['country']} | {expected['registry']} | 2000-01-01".encode()
    ]
    return [mock_rdata]


def mock_netcat_response(ip_addresses: list[str]) -> bytes:
    """Create mock netcat response for known IPs."""
    lines = [
        "Bulk mode; whois.cymru.com [2025-11-05 12:34:56 +0000]",
        "AS      | IP               | BGP Prefix          | CC | Registry | Allocated  | AS Name",
    ]
    for ip_address in ip_addresses:
        if ip_address in KNOWN_IPS:
            expected = KNOWN_IPS[ip_address]
            lines.append(
                f"{expected['asn']:<8}| {ip_address:<17}| {ip_address}/24{' ':<10}| "
                f"{expected['country']:<3}| {expected['registry']:<9}| 2000-01-01 | "
                f"{expected['org_contains']}"
            )

    return "\n".join(lines).encode('utf-8')


@pytest.mark.integration
class TestDNSIntegration:
    """Integration tests for DNS lookups."""

    @pytest.mark.skipif(USE_MOCK, reason="Skipping real DNS in mock mode")
    def test_real_dns_google(self, cymru_client: CymruClient) -> None:
        """Test real DNS lookup for Google DNS (8.8.8.8)."""
        result = cymru_client.lookup_asn("8.8.8.8")

        assert result is not None
        assert result.ip_address == "8.8.8.8"
        assert result.asn == KNOWN_IPS["8.8.8.8"]["asn"]
        assert result.country_code == KNOWN_IPS["8.8.8.8"]["country"]
        assert result.registry == KNOWN_IPS["8.8.8.8"]["registry"]
        assert result.source == "cymru"

    @pytest.mark.skipif(USE_MOCK, reason="Skipping real DNS in mock mode")
    def test_real_dns_cloudflare(self, cymru_client: CymruClient) -> None:
        """Test real DNS lookup for Cloudflare DNS (1.1.1.1)."""
        result = cymru_client.lookup_asn("1.1.1.1")

        assert result is not None
        assert result.ip_address == "1.1.1.1"
        assert result.asn == KNOWN_IPS["1.1.1.1"]["asn"]
        assert result.country_code == KNOWN_IPS["1.1.1.1"]["country"]

    @patch('dns.resolver.resolve')
    def test_mock_dns_google(
        self,
        mock_resolve: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test mocked DNS lookup for Google DNS."""
        mock_resolve.return_value = mock_dns_response("8.8.8.8")

        result = cymru_client.lookup_asn("8.8.8.8")

        assert result is not None
        assert result.ip_address == "8.8.8.8"
        assert result.asn == KNOWN_IPS["8.8.8.8"]["asn"]
        assert result.country_code == KNOWN_IPS["8.8.8.8"]["country"]
        assert cymru_client.stats['dns_success'] == 1

    @patch('dns.resolver.resolve')
    def test_mock_dns_multiple_ips(
        self,
        mock_resolve: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test mocked DNS lookups for multiple IPs."""

        def dns_side_effect(query_name: str, record_type: str) -> list[Mock]:
            # Extract IP from query name (e.g., "8.8.8.8.origin.asn.cymru.com")
            ip = query_name.split('.origin.asn.cymru.com')[0]
            return mock_dns_response(ip)

        mock_resolve.side_effect = dns_side_effect

        results = []
        for ip in ["8.8.8.8", "1.1.1.1"]:
            result = cymru_client.lookup_asn(ip)
            assert result is not None
            results.append(result)

        assert len(results) == 2
        assert all(r.asn is not None for r in results)
        assert cymru_client.stats['dns_success'] == 2


@pytest.mark.integration
class TestNetcatIntegration:
    """Integration tests for netcat bulk interface lookups."""

    @pytest.mark.skipif(USE_MOCK, reason="Skipping real netcat in mock mode")
    def test_real_netcat_google(self, cymru_client: CymruClient) -> None:
        """Test real netcat bulk interface lookup for Google DNS."""
        # Force DNS to fail to test netcat fallback
        with patch.object(cymru_client, '_lookup_dns', return_value=None):
            result = cymru_client.lookup_asn("8.8.8.8")

        assert result is not None
        assert result.ip_address == "8.8.8.8"
        assert result.asn == KNOWN_IPS["8.8.8.8"]["asn"]
        expected_org: str = str(KNOWN_IPS["8.8.8.8"]["org_contains"])
        assert result.asn_org is not None and expected_org in result.asn_org

    @patch('socket.socket')
    def test_mock_netcat_single_ip(
        self,
        mock_socket_class: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test mocked netcat bulk interface lookup for single IP."""
        mock_sock = Mock()
        mock_sock.recv.side_effect = [mock_netcat_response(["8.8.8.8"]), b'']
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)
        mock_socket_class.return_value = mock_sock

        # Force DNS to fail to test netcat fallback
        with patch.object(cymru_client, '_lookup_dns', return_value=None):
            result = cymru_client.lookup_asn("8.8.8.8")

        assert result is not None
        assert result.ip_address == "8.8.8.8"
        assert result.asn == KNOWN_IPS["8.8.8.8"]["asn"]
        assert result.asn_org == KNOWN_IPS["8.8.8.8"]["org_contains"]
        assert cymru_client.stats['netcat_success'] == 1


@pytest.mark.integration
class TestBulkIntegration:
    """Integration tests for bulk lookups."""

    @pytest.mark.skipif(USE_MOCK, reason="Skipping real bulk in mock mode")
    def test_real_bulk_multiple_ips(self, cymru_client: CymruClient) -> None:
        """Test real bulk lookup for multiple known IPs."""
        ips = list(KNOWN_IPS.keys())
        results = cymru_client.bulk_lookup(ips)

        assert len(results) >= 2  # At least some should succeed
        for ip, result in results.items():
            if ip in KNOWN_IPS:
                assert result.asn == KNOWN_IPS[ip]["asn"]
                assert result.country_code == KNOWN_IPS[ip]["country"]

    @patch('socket.socket')
    def test_mock_bulk_multiple_ips(
        self,
        mock_socket_class: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test mocked bulk lookup for multiple IPs."""
        ips = list(KNOWN_IPS.keys())
        mock_sock = Mock()
        mock_sock.recv.side_effect = [mock_netcat_response(ips), b'']
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)
        mock_socket_class.return_value = mock_sock

        results = cymru_client.bulk_lookup(ips)

        assert len(results) == len(ips)
        for ip in ips:
            assert ip in results
            assert results[ip].asn == KNOWN_IPS[ip]["asn"]

    @patch('socket.socket')
    def test_mock_bulk_large_batch(
        self,
        mock_socket_class: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test mocked bulk lookup with large batch (>500 IPs)."""
        # Generate 750 IPs using pattern from KNOWN_IPS
        base_ips = list(KNOWN_IPS.keys())
        large_batch = base_ips * 250  # 3 IPs * 250 = 750 IPs

        # Mock will be called for each batch
        mock_sock = Mock()
        mock_sock.recv.side_effect = [mock_netcat_response(base_ips), b'']
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)
        mock_socket_class.return_value = mock_sock

        _ = cymru_client.bulk_lookup(large_batch)

        # Should have made multiple netcat calls due to batching
        assert mock_socket_class.call_count >= 2


@pytest.mark.integration
class TestCacheIntegration:
    """Integration tests for cache functionality."""

    @patch('dns.resolver.resolve')
    def test_cache_persistence(
        self,
        mock_resolve: Mock,
        cache_manager: EnrichmentCacheManager,
        rate_limiter: RateLimiter,
    ) -> None:
        """Test that cache persists across client instances."""
        mock_resolve.return_value = mock_dns_response("8.8.8.8")

        # First client instance - cache miss
        client1 = CymruClient(cache=cache_manager, rate_limiter=rate_limiter)
        result1 = client1.lookup_asn("8.8.8.8")

        assert result1 is not None
        assert client1.stats['cache_misses'] == 1
        assert client1.stats['cache_hits'] == 0

        # Second client instance with same cache - cache hit
        client2 = CymruClient(cache=cache_manager, rate_limiter=rate_limiter)
        result2 = client2.lookup_asn("8.8.8.8")

        assert result2 is not None
        assert result2.asn == result1.asn
        assert client2.stats['cache_hits'] == 1
        assert client2.stats['cache_misses'] == 0
        assert mock_resolve.call_count == 1  # Only called once for first client

    @patch('dns.resolver.resolve')
    def test_cache_ttl_respected(
        self,
        mock_resolve: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test that cache TTL is set correctly."""
        mock_resolve.return_value = mock_dns_response("8.8.8.8")

        result = cymru_client.lookup_asn("8.8.8.8")

        assert result is not None
        assert result.ttl_days == 90

        # Verify cache entry has correct TTL
        cached_data = cymru_client.cache.get_cached("cymru", "8.8.8.8")
        assert cached_data is not None
        assert cached_data.get('ttl_days') == 90


@pytest.mark.integration
class TestFallbackIntegration:
    """Integration tests for DNS-to-netcat fallback."""

    @patch('dns.resolver.resolve')
    @patch('socket.socket')
    def test_dns_failure_netcat_fallback(
        self,
        mock_socket_class: Mock,
        mock_resolve: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test that netcat bulk interface is used when DNS fails."""
        # DNS fails
        import dns.resolver

        mock_resolve.side_effect = dns.resolver.NXDOMAIN()

        # Netcat succeeds
        mock_sock = Mock()
        mock_sock.recv.side_effect = [mock_netcat_response(["8.8.8.8"]), b'']
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)
        mock_socket_class.return_value = mock_sock

        result = cymru_client.lookup_asn("8.8.8.8")

        assert result is not None
        assert result.asn == KNOWN_IPS["8.8.8.8"]["asn"]
        assert cymru_client.stats['dns_failures'] == 1
        assert cymru_client.stats['netcat_success'] == 1

    @patch('dns.resolver.resolve')
    @patch('socket.socket')
    def test_dns_timeout_netcat_fallback(
        self,
        mock_socket_class: Mock,
        mock_resolve: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test netcat fallback when DNS times out."""
        # DNS times out after retries
        import dns.exception

        mock_resolve.side_effect = dns.exception.Timeout()

        # Netcat succeeds
        mock_sock = Mock()
        mock_sock.recv.side_effect = [mock_netcat_response(["8.8.8.8"]), b'']
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)
        mock_socket_class.return_value = mock_sock

        result = cymru_client.lookup_asn("8.8.8.8")

        assert result is not None
        assert result.asn == KNOWN_IPS["8.8.8.8"]["asn"]


@pytest.mark.integration
class TestStatisticsIntegration:
    """Integration tests for statistics tracking."""

    @patch('dns.resolver.resolve')
    @patch('socket.socket')
    def test_statistics_accuracy(
        self,
        mock_socket_class: Mock,
        mock_resolve: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test that statistics are accurately tracked."""
        # Setup mocks
        mock_resolve.return_value = mock_dns_response("8.8.8.8")

        mock_sock = Mock()
        mock_sock.recv.side_effect = [mock_netcat_response(["1.1.1.1"]), b'']
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)
        mock_socket_class.return_value = mock_sock

        # DNS success
        cymru_client.lookup_asn("8.8.8.8")
        assert cymru_client.stats['lookups'] == 1
        assert cymru_client.stats['dns_success'] == 1
        assert cymru_client.stats['cache_misses'] == 1

        # Cache hit
        cymru_client.lookup_asn("8.8.8.8")
        assert cymru_client.stats['lookups'] == 2
        assert cymru_client.stats['cache_hits'] == 1

        # DNS failure, netcat fallback
        import dns.resolver

        mock_resolve.side_effect = dns.resolver.NXDOMAIN()
        cymru_client.lookup_asn("1.1.1.1")

        assert cymru_client.stats['lookups'] == 3
        assert cymru_client.stats['dns_failures'] == 1
        assert cymru_client.stats['netcat_success'] == 1


@pytest.mark.integration
class TestErrorHandling:
    """Integration tests for error handling."""

    @patch('dns.resolver.resolve')
    @patch('socket.socket')
    def test_both_dns_and_netcat_fail(
        self,
        mock_socket_class: Mock,
        mock_resolve: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test behavior when both DNS and netcat fail."""
        # DNS fails
        import dns.resolver

        mock_resolve.side_effect = dns.resolver.NXDOMAIN()

        # Netcat fails
        import socket

        mock_socket_class.side_effect = socket.error("Connection failed")

        result = cymru_client.lookup_asn("192.0.2.1")

        assert result is None
        assert cymru_client.stats['dns_failures'] == 1
        assert cymru_client.stats['netcat_failures'] > 0
        assert cymru_client.stats['errors'] > 0

    def test_invalid_ip_address(self, cymru_client: CymruClient) -> None:
        """Test behavior with invalid IP address."""
        # This should fail gracefully without crashing
        result = cymru_client.lookup_asn("not-an-ip")

        # Result will be None due to DNS/HTTP failures
        assert result is None or result.asn is None
