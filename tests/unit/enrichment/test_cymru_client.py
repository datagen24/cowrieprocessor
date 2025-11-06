"""Unit tests for Team Cymru ASN enrichment client."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import dns.resolver
import pytest

from cowrieprocessor.enrichment.cache import EnrichmentCacheManager
from cowrieprocessor.enrichment.cymru_client import CymruClient, CymruResult
from cowrieprocessor.enrichment.rate_limiting import RateLimiter


@pytest.fixture
def cache_manager(tmp_path: Path) -> EnrichmentCacheManager:
    """Create cache manager for testing."""
    return EnrichmentCacheManager(base_dir=tmp_path / "cache")


@pytest.fixture
def rate_limiter() -> RateLimiter:
    """Create rate limiter for testing."""
    return RateLimiter(rate=100.0, burst=100)


@pytest.fixture
def cymru_client(cache_manager: EnrichmentCacheManager, rate_limiter: RateLimiter) -> CymruClient:
    """Create Cymru client for testing."""
    return CymruClient(cache=cache_manager, rate_limiter=rate_limiter, ttl_days=90)


class TestCymruResult:
    """Test CymruResult dataclass."""

    def test_result_creation(self) -> None:
        """Test creating a CymruResult."""
        result = CymruResult(
            ip_address="8.8.8.8",
            asn=15169,
            asn_org="GOOGLE",
            country_code="US",
            registry="arin",
            prefix="8.8.8.0/24",
            allocation_date="1992-12-01",
        )

        assert result.ip_address == "8.8.8.8"
        assert result.asn == 15169
        assert result.asn_org == "GOOGLE"
        assert result.country_code == "US"
        assert result.registry == "arin"
        assert result.prefix == "8.8.8.0/24"
        assert result.allocation_date == "1992-12-01"
        assert result.source == "cymru"
        assert result.ttl_days == 90
        assert isinstance(result.cached_at, datetime)

    def test_result_defaults(self) -> None:
        """Test CymruResult default values."""
        result = CymruResult(
            ip_address="8.8.8.8",
            asn=None,
            asn_org=None,
            country_code=None,
            registry=None,
        )

        assert result.ip_address == "8.8.8.8"
        assert result.asn is None
        assert result.asn_org is None
        assert result.source == "cymru"
        assert result.ttl_days == 90


class TestCymruClientInit:
    """Test CymruClient initialization."""

    def test_init_with_all_params(
        self,
        cache_manager: EnrichmentCacheManager,
        rate_limiter: RateLimiter,
    ) -> None:
        """Test client initialization with all parameters."""
        client = CymruClient(cache=cache_manager, rate_limiter=rate_limiter, ttl_days=90)

        assert client.cache == cache_manager
        assert client.rate_limiter == rate_limiter
        assert client.ttl_days == 90
        assert 'lookups' in client.stats
        assert 'cache_hits' in client.stats

    def test_init_with_default_rate_limiter(self, cache_manager: EnrichmentCacheManager) -> None:
        """Test client initialization with default rate limiter."""
        client = CymruClient(cache=cache_manager)

        assert client.rate_limiter is not None
        assert client.ttl_days == 90


class TestDNSLookup:
    """Test DNS TXT record lookups."""

    @patch('dns.resolver.resolve')
    def test_dns_success(
        self,
        mock_resolve: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test successful DNS lookup."""
        # Mock DNS response
        mock_rdata = Mock()
        mock_rdata.strings = [b"15169 | 8.8.8.0/24 | US | arin | 1992-12-01"]
        mock_resolve.return_value = [mock_rdata]

        result = cymru_client.lookup_asn("8.8.8.8")

        assert result is not None
        assert result.ip_address == "8.8.8.8"
        assert result.asn == 15169
        assert result.country_code == "US"
        assert result.registry == "arin"
        assert result.prefix == "8.8.8.0/24"
        assert result.allocation_date == "1992-12-01"
        assert cymru_client.stats['dns_success'] == 1
        assert cymru_client.stats['lookups'] == 1

    @patch('dns.resolver.resolve')
    @patch('socket.socket')
    def test_dns_nxdomain(
        self,
        mock_socket_class: Mock,
        mock_resolve: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test DNS NXDOMAIN (IP not found)."""
        mock_resolve.side_effect = dns.resolver.NXDOMAIN()

        # Mock netcat fallback to return None (empty response)
        mock_sock = Mock()
        mock_sock.recv.side_effect = [b'', b'']
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)
        mock_socket_class.return_value = mock_sock

        result = cymru_client.lookup_asn("192.0.2.1")

        assert result is None
        assert cymru_client.stats['dns_failures'] == 1

    @patch('dns.resolver.resolve')
    @patch('socket.socket')
    def test_dns_no_answer(
        self,
        mock_socket_class: Mock,
        mock_resolve: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test DNS NoAnswer (no TXT record)."""
        mock_resolve.side_effect = dns.resolver.NoAnswer()

        # Mock netcat fallback to return None (empty response)
        mock_sock = Mock()
        mock_sock.recv.side_effect = [b'', b'']
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)
        mock_socket_class.return_value = mock_sock

        result = cymru_client.lookup_asn("192.0.2.1")

        assert result is None
        assert cymru_client.stats['dns_failures'] == 1

    @patch('dns.resolver.resolve')
    @patch('time.sleep')
    def test_dns_timeout_retry(
        self,
        mock_sleep: Mock,
        mock_resolve: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test DNS timeout with retry."""
        # First two attempts timeout, third succeeds
        mock_rdata = Mock()
        mock_rdata.strings = [b"15169 | 8.8.8.0/24 | US | arin | 1992-12-01"]

        mock_resolve.side_effect = [
            dns.exception.Timeout(),
            dns.exception.Timeout(),
            [mock_rdata],
        ]

        result = cymru_client.lookup_asn("8.8.8.8")

        assert result is not None
        assert result.asn == 15169
        assert mock_sleep.call_count == 2  # Two retries with backoff
        assert cymru_client.stats['dns_success'] == 1

    @patch('dns.resolver.resolve')
    @patch('socket.socket')
    @patch('time.sleep')
    def test_dns_timeout_exhausted(
        self,
        mock_sleep: Mock,
        mock_socket_class: Mock,
        mock_resolve: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test DNS timeout with all retries exhausted."""
        mock_resolve.side_effect = dns.exception.Timeout()

        # Mock netcat fallback to return None (empty response)
        mock_sock = Mock()
        mock_sock.recv.side_effect = [b'', b'']
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)
        mock_socket_class.return_value = mock_sock

        result = cymru_client.lookup_asn("8.8.8.8")

        assert result is None
        assert mock_sleep.call_count == 2  # Retried twice
        assert cymru_client.stats['dns_failures'] == 1

    @patch('dns.resolver.resolve')
    @patch('socket.socket')
    def test_dns_invalid_response(
        self,
        mock_socket_class: Mock,
        mock_resolve: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test DNS with invalid response format."""
        # Mock invalid response (not enough fields)
        mock_rdata = Mock()
        mock_rdata.strings = [b"15169"]
        mock_resolve.return_value = [mock_rdata]

        # Mock netcat fallback to return None (empty response)
        mock_sock = Mock()
        mock_sock.recv.side_effect = [b'', b'']
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)
        mock_socket_class.return_value = mock_sock

        result = cymru_client.lookup_asn("8.8.8.8")

        assert result is None

    @patch('dns.resolver.resolve')
    @patch('socket.socket')
    def test_dns_unallocated_asn(
        self,
        mock_socket_class: Mock,
        mock_resolve: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test DNS with unallocated ASN (NA)."""
        mock_rdata = Mock()
        mock_rdata.strings = [b"NA | | | |"]
        mock_resolve.return_value = [mock_rdata]

        # Mock netcat fallback to return None (empty response)
        mock_sock = Mock()
        mock_sock.recv.side_effect = [b'', b'']
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)
        mock_socket_class.return_value = mock_sock

        result = cymru_client.lookup_asn("192.0.2.1")

        assert result is None


class TestNetcatLookup:
    """Test netcat bulk interface lookups."""

    @patch('socket.socket')
    def test_netcat_success(
        self,
        mock_socket_class: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test successful netcat bulk interface lookup."""
        # Mock socket response
        mock_sock = Mock()
        netcat_response = (
            "Bulk mode; whois.cymru.com [2025-11-05 12:34:56 +0000]\n"
            "AS      | IP               | BGP Prefix          | CC | Registry | Allocated  | AS Name\n"
            "15169   | 8.8.8.8          | 8.8.8.0/24          | US | arin     | 1992-12-01 | GOOGLE, US\n"
        )
        mock_sock.recv.side_effect = [netcat_response.encode('utf-8'), b'']
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)
        mock_socket_class.return_value = mock_sock

        # Force DNS to fail to test netcat fallback
        with patch.object(cymru_client, '_lookup_dns', return_value=None):
            result = cymru_client.lookup_asn("8.8.8.8")

        assert result is not None
        assert result.ip_address == "8.8.8.8"
        assert result.asn == 15169
        assert result.asn_org == "GOOGLE, US"
        assert result.country_code == "US"
        assert result.registry == "arin"
        assert cymru_client.stats['netcat_success'] == 1

    @patch('socket.socket')
    @patch('time.sleep')
    def test_netcat_timeout_retry(
        self,
        mock_sleep: Mock,
        mock_socket_class: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test netcat timeout with retry."""
        # First two attempts timeout, third succeeds
        mock_sock = Mock()
        netcat_response = (
            "Bulk mode; whois.cymru.com [2025-11-05 12:34:56 +0000]\n"
            "AS      | IP               | BGP Prefix          | CC | Registry | Allocated  | AS Name\n"
            "15169   | 8.8.8.8          | 8.8.8.0/24          | US | arin     | 1992-12-01 | GOOGLE, US\n"
        )
        mock_sock.recv.side_effect = [netcat_response.encode('utf-8'), b'']
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)

        import socket

        mock_socket_class.side_effect = [
            socket.timeout(),
            socket.timeout(),
            mock_sock,
        ]

        results = cymru_client._bulk_lookup_netcat(["8.8.8.8"])

        assert "8.8.8.8" in results
        assert results["8.8.8.8"].asn == 15169
        assert mock_sleep.call_count == 2

    @patch('socket.socket')
    @patch('time.sleep')
    def test_netcat_timeout_exhausted(
        self,
        mock_sleep: Mock,
        mock_socket_class: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test netcat timeout with all retries exhausted."""
        import socket

        mock_socket_class.side_effect = socket.timeout()

        results = cymru_client._bulk_lookup_netcat(["8.8.8.8"])

        assert len(results) == 0
        assert mock_sleep.call_count == 2
        assert cymru_client.stats['netcat_failures'] > 0

    @patch('socket.socket')
    def test_netcat_connection_error(
        self,
        mock_socket_class: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test netcat connection error."""
        import socket

        mock_socket_class.side_effect = socket.error("Connection refused")

        results = cymru_client._bulk_lookup_netcat(["8.8.8.8"])

        assert len(results) == 0
        assert cymru_client.stats['netcat_failures'] > 0
        assert cymru_client.stats['errors'] > 0

    @patch('socket.socket')
    def test_netcat_invalid_response(
        self,
        mock_socket_class: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test netcat with invalid response format."""
        mock_sock = Mock()
        mock_sock.recv.side_effect = [b"Invalid | Response", b'']
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)
        mock_socket_class.return_value = mock_sock

        results = cymru_client._bulk_lookup_netcat(["8.8.8.8"])

        assert len(results) == 0


class TestBulkLookup:
    """Test bulk lookup functionality."""

    @patch('socket.socket')
    def test_bulk_lookup_success(
        self,
        mock_socket_class: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test successful bulk lookup."""
        mock_sock = Mock()
        netcat_response = (
            "Bulk mode; whois.cymru.com [2025-11-05 12:34:56 +0000]\n"
            "AS      | IP               | BGP Prefix          | CC | Registry | Allocated  | AS Name\n"
            "15169   | 8.8.8.8          | 8.8.8.0/24          | US | arin     | 1992-12-01 | GOOGLE\n"
            "13335   | 1.1.1.1          | 1.1.1.0/24          | US | arin     | 2010-07-14 | CLOUDFLARENET\n"
        )
        mock_sock.recv.side_effect = [netcat_response.encode('utf-8'), b'']
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)
        mock_socket_class.return_value = mock_sock

        results = cymru_client.bulk_lookup(["8.8.8.8", "1.1.1.1"])

        assert len(results) == 2
        assert results["8.8.8.8"].asn == 15169
        assert results["1.1.1.1"].asn == 13335
        assert cymru_client.stats['lookups'] == 2

    @patch('socket.socket')
    def test_bulk_lookup_cache_hit(
        self,
        mock_socket_class: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test bulk lookup with cache hit."""
        # First lookup - cache miss
        mock_sock = Mock()
        netcat_response = (
            "Bulk mode; whois.cymru.com [2025-11-05 12:34:56 +0000]\n"
            "AS      | IP               | BGP Prefix          | CC | Registry | Allocated  | AS Name\n"
            "15169   | 8.8.8.8          | 8.8.8.0/24          | US | arin     | 1992-12-01 | GOOGLE\n"
        )
        mock_sock.recv.side_effect = [netcat_response.encode('utf-8'), b'']
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)
        mock_socket_class.return_value = mock_sock

        _ = cymru_client.bulk_lookup(["8.8.8.8"])
        assert cymru_client.stats['cache_misses'] == 1

        # Second lookup - cache hit
        second_results = cymru_client.bulk_lookup(["8.8.8.8"])

        assert second_results["8.8.8.8"].asn == 15169
        assert cymru_client.stats['cache_hits'] == 1
        assert mock_socket_class.call_count == 1  # Only called once

    @patch('socket.socket')
    def test_bulk_lookup_batching(
        self,
        mock_socket_class: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test bulk lookup with batching (>500 IPs)."""
        # Generate 750 IPs (should split into 2 batches: 500 + 250)
        ips = [f"192.0.2.{i % 256}" for i in range(750)]

        mock_sock = Mock()
        mock_sock.recv.side_effect = [b'', b'']
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)
        mock_socket_class.return_value = mock_sock

        _ = cymru_client.bulk_lookup(ips)

        # Should have made 2 netcat calls (500 + 250)
        assert mock_socket_class.call_count == 2

    @patch('socket.socket')
    def test_bulk_lookup_mixed_cache(
        self,
        mock_socket_class: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test bulk lookup with mixed cache hits/misses."""
        # Pre-populate cache with one IP
        mock_sock = Mock()
        netcat_response = (
            "Bulk mode; whois.cymru.com [2025-11-05 12:34:56 +0000]\n"
            "AS      | IP               | BGP Prefix          | CC | Registry | Allocated  | AS Name\n"
            "15169   | 8.8.8.8          | 8.8.8.0/24          | US | arin     | 1992-12-01 | GOOGLE\n"
        )
        mock_sock.recv.side_effect = [netcat_response.encode('utf-8'), b'']
        mock_sock.__enter__ = Mock(return_value=mock_sock)
        mock_sock.__exit__ = Mock(return_value=False)
        mock_socket_class.return_value = mock_sock

        cymru_client.bulk_lookup(["8.8.8.8"])

        # Now lookup two IPs (one cached, one not)
        mock_sock.recv.side_effect = [
            (
                "Bulk mode; whois.cymru.com [2025-11-05 12:34:56 +0000]\n"
                "AS      | IP               | BGP Prefix          | CC | Registry | Allocated  | AS Name\n"
                "13335   | 1.1.1.1          | 1.1.1.0/24          | US | arin     | 2010-07-14 | CLOUDFLARENET\n"
            ).encode('utf-8'),
            b'',
        ]

        results = cymru_client.bulk_lookup(["8.8.8.8", "1.1.1.1"])

        assert len(results) == 2
        assert cymru_client.stats['cache_hits'] >= 1
        assert cymru_client.stats['cache_misses'] >= 1


class TestCacheFunctionality:
    """Test cache integration."""

    @patch('dns.resolver.resolve')
    def test_cache_storage(
        self,
        mock_resolve: Mock,
        cymru_client: CymruClient,
    ) -> None:
        """Test that results are cached."""
        mock_rdata = Mock()
        mock_rdata.strings = [b"15169 | 8.8.8.0/24 | US | arin | 1992-12-01"]
        mock_resolve.return_value = [mock_rdata]

        # First lookup - cache miss
        result1 = cymru_client.lookup_asn("8.8.8.8")
        assert result1 is not None
        assert cymru_client.stats['cache_misses'] == 1

        # Second lookup - cache hit
        result2 = cymru_client.lookup_asn("8.8.8.8")
        assert result2 is not None
        assert result2.asn == result1.asn
        assert cymru_client.stats['cache_hits'] == 1
        assert mock_resolve.call_count == 1  # DNS only called once

    def test_dict_conversion(self, cymru_client: CymruClient) -> None:
        """Test result to dict and back conversion."""
        original = CymruResult(
            ip_address="8.8.8.8",
            asn=15169,
            asn_org="GOOGLE",
            country_code="US",
            registry="arin",
            prefix="8.8.8.0/24",
            allocation_date="1992-12-01",
            ttl_days=90,
        )

        # Convert to dict
        data = cymru_client._result_to_dict(original)

        assert data['ip_address'] == "8.8.8.8"
        assert data['asn'] == 15169
        assert data['asn_org'] == "GOOGLE"

        # Convert back to result
        restored = cymru_client._dict_to_result(data)

        assert restored.ip_address == original.ip_address
        assert restored.asn == original.asn
        assert restored.asn_org == original.asn_org
        assert restored.country_code == original.country_code


class TestStatistics:
    """Test statistics tracking."""

    def test_get_stats(self, cymru_client: CymruClient) -> None:
        """Test getting statistics."""
        stats = cymru_client.get_stats()

        assert 'lookups' in stats
        assert 'cache_hits' in stats
        assert 'cache_misses' in stats
        assert 'dns_success' in stats
        assert 'netcat_success' in stats

    def test_reset_stats(self, cymru_client: CymruClient) -> None:
        """Test resetting statistics."""
        cymru_client.stats['lookups'] = 10
        cymru_client.stats['cache_hits'] = 5

        cymru_client.reset_stats()

        assert cymru_client.stats['lookups'] == 0
        assert cymru_client.stats['cache_hits'] == 0


class TestParsingEdgeCases:
    """Test edge cases in response parsing."""

    def test_parse_dns_empty_fields(self, cymru_client: CymruClient) -> None:
        """Test parsing DNS response with empty fields."""
        result = cymru_client._parse_dns_response("8.8.8.8", "15169 |  |  |  | ")

        assert result is not None
        assert result.asn == 15169
        assert result.country_code is None
        assert result.registry is None

    def test_parse_netcat_empty_fields(self, cymru_client: CymruClient) -> None:
        """Test parsing netcat response with empty fields."""
        response = (
            "Bulk mode; whois.cymru.com [2025-11-05 12:34:56 +0000]\n"
            "AS      | IP               | BGP Prefix          | CC | Registry | Allocated  | AS Name\n"
            "15169   | 8.8.8.8          |                     |    |          |            | \n"
        )
        results = cymru_client._parse_netcat_response(response, ["8.8.8.8"])

        assert "8.8.8.8" in results
        assert results["8.8.8.8"].asn == 15169
        assert results["8.8.8.8"].asn_org is None

    def test_parse_dns_malformed(self, cymru_client: CymruClient) -> None:
        """Test parsing malformed DNS response."""
        result = cymru_client._parse_dns_response("8.8.8.8", "not a valid response")

        assert result is None

    def test_parse_netcat_malformed(self, cymru_client: CymruClient) -> None:
        """Test parsing malformed netcat response."""
        response = "not a valid response"
        results = cymru_client._parse_netcat_response(response, ["8.8.8.8"])

        assert len(results) == 0
