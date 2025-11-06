r"""Team Cymru whois client for ASN enrichment with DNS and netcat fallback.

Team Cymru provides IP to ASN mapping via DNS TXT records and netcat bulk interface.
This client implements both methods with automatic fallback for reliability.

DNS Query Format:
    Reverse IP: 8.8.8.8 → 8.8.8.8.origin.asn.cymru.com
    Response: "15169 | 8.8.8.0/24 | US | arin | 1992-12-01"

Netcat Bulk Interface Format:
    Host: whois.cymru.com:43
    Query: begin\nverbose\n<IP1>\n<IP2>\n...\nend\n
    Response: AS | IP | BGP Prefix | CC | Registry | Allocated | AS Name

WARNING: Do NOT use HTTP API for bulk queries - Team Cymru will null-route abusers.
Use netcat bulk interface (port 43) for all bulk operations.

Cache TTL: 90 days per ADR-008 specification
"""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import dns.resolver

from .cache import EnrichmentCacheManager
from .rate_limiting import RateLimiter

logger = logging.getLogger(__name__)


@dataclass
class CymruResult:
    """Result from Team Cymru ASN lookup.

    Attributes:
        ip_address: The IP address that was looked up
        asn: Autonomous System Number
        asn_org: AS organization name
        country_code: ISO 3166-1 alpha-2 country code
        registry: Regional Internet Registry (ARIN, RIPE, APNIC, LACNIC, AFRINIC)
        prefix: BGP prefix containing the IP address (CIDR notation)
        allocation_date: Date when ASN was allocated (ISO format)
        source: Data source identifier (always "cymru")
        cached_at: Timestamp when result was retrieved
        ttl_days: Cache time-to-live in days
    """

    ip_address: str
    asn: int | None
    asn_org: str | None
    country_code: str | None
    registry: str | None
    prefix: str | None = None
    allocation_date: str | None = None
    source: str = "cymru"
    cached_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_days: int = 90


class CymruClient:
    """Team Cymru whois client with DNS and netcat bulk interface.

    Provides ASN enrichment using Team Cymru's free service with:
    - Primary: DNS TXT record lookups (fast, low latency)
    - Bulk: Netcat interface on port 43 (official bulk method)
    - Cache: 90-day TTL per ADR-008 specification
    - Rate limiting: 100 requests/second throttle

    WARNING: Do NOT use HTTP API - Team Cymru will null-route abusers.
    Use netcat bulk interface (whois.cymru.com:43) for all bulk operations.

    Usage:
        cache = EnrichmentCacheManager(base_dir=Path("/cache"))
        limiter = RateLimiter(rate=100.0)
        client = CymruClient(cache=cache, rate_limiter=limiter)

        # Single lookup (uses DNS)
        result = client.lookup_asn("8.8.8.8")
        if result and result.asn:
            print(f"ASN: {result.asn} ({result.asn_org})")

        # Bulk lookup (uses netcat interface)
        results = client.bulk_lookup(["8.8.8.8", "1.1.1.1"])
        for ip, result in results.items():
            print(f"{ip}: AS{result.asn}")
    """

    # Team Cymru DNS suffix
    DNS_SUFFIX = "origin.asn.cymru.com"

    # Netcat bulk interface
    WHOIS_HOST = "whois.cymru.com"
    WHOIS_PORT = 43

    # Batch size limits
    MAX_BULK_SIZE = 500

    # Retry configuration
    MAX_RETRIES = 3
    RETRY_DELAYS = [1.0, 2.0, 4.0]  # Exponential backoff

    # Socket timeout
    SOCKET_TIMEOUT = 30.0

    def __init__(
        self,
        cache: EnrichmentCacheManager,
        rate_limiter: RateLimiter | None = None,
        ttl_days: int = 90,
    ) -> None:
        """Initialize Team Cymru client.

        Args:
            cache: Cache manager for storing lookup results
            rate_limiter: Optional rate limiter (defaults to 100 req/sec)
            ttl_days: Cache TTL in days (default: 90)
        """
        self.cache = cache
        self.rate_limiter = rate_limiter or RateLimiter(rate=100.0, burst=100)
        self.ttl_days = ttl_days

        # Statistics
        self.stats: dict[str, int] = {
            'lookups': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'dns_success': 0,
            'dns_failures': 0,
            'netcat_success': 0,
            'netcat_failures': 0,
            'errors': 0,
        }

        logger.info("Team Cymru client initialized with netcat bulk interface and 90-day cache TTL")

    def lookup_asn(self, ip_address: str) -> CymruResult | None:
        """Look up ASN data for an IP address.

        Attempts DNS lookup first, falls back to netcat bulk interface on failure.
        Results are cached for 90 days per ADR-008 specification.

        Args:
            ip_address: IP address to look up (IPv4 or IPv6)

        Returns:
            CymruResult with ASN data or None if lookup failed

        Examples:
            >>> client = CymruClient(cache, limiter)
            >>> result = client.lookup_asn("8.8.8.8")
            >>> if result:
            ...     print(f"AS{result.asn}: {result.asn_org}")
            AS15169: GOOGLE
        """
        self.stats['lookups'] += 1

        # Check cache first
        cached_data = self.cache.get_cached("cymru", ip_address)

        if cached_data:
            self.stats['cache_hits'] += 1
            logger.debug(f"Cache hit for {ip_address}")
            return self._dict_to_result(cached_data)

        self.stats['cache_misses'] += 1

        # Try DNS lookup
        result = self._lookup_dns(ip_address)

        # Fall back to netcat bulk interface if DNS failed
        if result is None:
            logger.debug(f"DNS lookup failed for {ip_address}, trying netcat bulk interface")
            result = self._lookup_netcat_single(ip_address)

        # Cache successful result
        if result:
            result_dict = self._result_to_dict(result)
            self.cache.store_cached("cymru", ip_address, result_dict)
            logger.debug(f"Cached result for {ip_address}")

        return result

    def bulk_lookup(self, ip_addresses: list[str]) -> dict[str, CymruResult]:
        """Batch lookup for multiple IP addresses.

        Checks cache first, then queries remaining IPs via netcat bulk interface.
        Automatically splits requests into batches of 500 IPs.

        Args:
            ip_addresses: List of IP addresses to look up

        Returns:
            Dictionary mapping IP addresses to CymruResult objects

        Examples:
            >>> results = client.bulk_lookup(["8.8.8.8", "1.1.1.1"])
            >>> for ip, result in results.items():
            ...     print(f"{ip}: AS{result.asn}")
            8.8.8.8: AS15169
            1.1.1.1: AS13335
        """
        results: dict[str, CymruResult] = {}
        uncached_ips: list[str] = []

        # Check cache for all IPs
        for ip_address in ip_addresses:
            self.stats['lookups'] += 1

            cached_data = self.cache.get_cached("cymru", ip_address)
            if cached_data:
                self.stats['cache_hits'] += 1
                results[ip_address] = self._dict_to_result(cached_data)
            else:
                self.stats['cache_misses'] += 1
                uncached_ips.append(ip_address)

        if not uncached_ips:
            logger.debug(f"All {len(ip_addresses)} IPs found in cache")
            return results

        logger.info(f"Bulk lookup: {len(uncached_ips)} IPs not in cache")

        # Split into batches of MAX_BULK_SIZE
        for i in range(0, len(uncached_ips), self.MAX_BULK_SIZE):
            batch = uncached_ips[i : i + self.MAX_BULK_SIZE]
            batch_results = self._bulk_lookup_netcat(batch)

            # Cache and merge results
            for ip_address, result in batch_results.items():
                results[ip_address] = result
                result_dict = self._result_to_dict(result)
                self.cache.store_cached("cymru", ip_address, result_dict)

        return results

    def _lookup_dns(self, ip_address: str) -> CymruResult | None:
        """Perform DNS TXT record lookup.

        Args:
            ip_address: IP address to look up

        Returns:
            CymruResult or None if lookup failed
        """
        query_name = f"{ip_address}.{self.DNS_SUFFIX}"

        for attempt in range(self.MAX_RETRIES):
            try:
                # Rate limit DNS queries
                self.rate_limiter.acquire_sync()

                # Query DNS TXT record
                answers = dns.resolver.resolve(query_name, 'TXT')

                # Parse first TXT record
                for rdata in answers:
                    txt_data = b''.join(rdata.strings).decode('utf-8')
                    result = self._parse_dns_response(ip_address, txt_data)

                    if result:
                        self.stats['dns_success'] += 1
                        logger.debug(f"DNS success for {ip_address}")
                        return result

                # No valid data in TXT records
                self.stats['dns_failures'] += 1
                return None

            except dns.resolver.NXDOMAIN:
                # IP not found in Cymru database
                logger.debug(f"DNS NXDOMAIN for {ip_address}")
                self.stats['dns_failures'] += 1
                return None

            except dns.resolver.NoAnswer:
                # No TXT record available
                logger.debug(f"DNS NoAnswer for {ip_address}")
                self.stats['dns_failures'] += 1
                return None

            except dns.exception.Timeout:
                # DNS timeout - retry with backoff
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_DELAYS[attempt]
                    logger.warning(f"DNS timeout for {ip_address}, retrying in {delay}s")
                    time.sleep(delay)
                else:
                    logger.error(f"DNS timeout for {ip_address} after {self.MAX_RETRIES} attempts")
                    self.stats['dns_failures'] += 1
                    return None

            except Exception as e:
                logger.error(f"DNS lookup failed for {ip_address}: {e}")
                self.stats['dns_failures'] += 1
                self.stats['errors'] += 1
                return None

        return None

    def _lookup_netcat_single(self, ip_address: str) -> CymruResult | None:
        """Perform netcat bulk interface lookup for single IP.

        Args:
            ip_address: IP address to look up

        Returns:
            CymruResult or None if lookup failed
        """
        results = self._bulk_lookup_netcat([ip_address])
        return results.get(ip_address)

    def _bulk_lookup_netcat(self, ip_addresses: list[str]) -> dict[str, CymruResult]:
        """Perform netcat bulk interface lookup.

        Uses Team Cymru's official bulk interface on whois.cymru.com:43.
        This is the ONLY supported method for bulk queries to avoid null-routing.

        Args:
            ip_addresses: List of IP addresses (max 500)

        Returns:
            Dictionary mapping IP addresses to CymruResult objects
        """
        if len(ip_addresses) > self.MAX_BULK_SIZE:
            logger.warning(f"Bulk lookup size {len(ip_addresses)} exceeds max {self.MAX_BULK_SIZE}, truncating")
            ip_addresses = ip_addresses[: self.MAX_BULK_SIZE]

        results: dict[str, CymruResult] = {}

        for attempt in range(self.MAX_RETRIES):
            try:
                # Rate limit netcat requests
                self.rate_limiter.acquire_sync()

                # Build netcat query
                query = "begin\nverbose\n"
                query += "\n".join(ip_addresses)
                query += "\nend\n"

                # Connect to whois.cymru.com:43
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(self.SOCKET_TIMEOUT)
                    sock.connect((self.WHOIS_HOST, self.WHOIS_PORT))
                    sock.sendall(query.encode("utf-8"))

                    # Read response
                    response = b""
                    while True:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        response += chunk

                # Parse response
                results = self._parse_netcat_response(response.decode("utf-8"), ip_addresses)

                self.stats['netcat_success'] += len(results)
                logger.debug(f"Netcat bulk interface success: {len(results)} IPs")
                return results

            except socket.timeout:
                # Socket timeout - retry with backoff
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_DELAYS[attempt]
                    logger.warning(f"Netcat timeout, retrying in {delay}s")
                    time.sleep(delay)
                else:
                    logger.error(f"Netcat timeout after {self.MAX_RETRIES} attempts")
                    self.stats['netcat_failures'] += len(ip_addresses)
                    return results

            except (socket.error, OSError) as e:
                logger.error(f"Netcat connection failed: {e}")
                self.stats['netcat_failures'] += len(ip_addresses)
                self.stats['errors'] += 1
                return results

            except Exception as e:
                logger.error(f"Netcat bulk lookup failed: {e}")
                self.stats['netcat_failures'] += len(ip_addresses)
                self.stats['errors'] += 1
                return results

        return results

    def _parse_dns_response(self, ip_address: str, txt_record: str) -> CymruResult | None:
        """Parse DNS TXT record response.

        Format: "15169 | 8.8.8.0/24 | US | arin | 1992-12-01"
        Fields: ASN | Prefix | Country | Registry | Allocation Date

        Args:
            ip_address: Original IP address queried
            txt_record: DNS TXT record content

        Returns:
            CymruResult or None if parsing failed
        """
        try:
            # Split by pipe character
            parts = [p.strip() for p in txt_record.split('|')]

            if len(parts) < 4:
                logger.warning(f"Invalid DNS response format: {txt_record}")
                return None

            # Extract fields
            asn_str = parts[0]
            prefix = parts[1] if len(parts) > 1 else None
            country_code = parts[2] if len(parts) > 2 and parts[2] else None
            registry = parts[3] if len(parts) > 3 and parts[3] else None
            allocation_date = parts[4] if len(parts) > 4 and parts[4] else None

            # Parse ASN (may be "NA" for unallocated)
            if asn_str == "NA" or not asn_str.isdigit():
                return None

            asn = int(asn_str)

            return CymruResult(
                ip_address=ip_address,
                asn=asn,
                asn_org=None,  # DNS doesn't provide org name
                country_code=country_code,
                registry=registry.lower() if registry else None,
                prefix=prefix,
                allocation_date=allocation_date,
                ttl_days=self.ttl_days,
            )

        except (ValueError, IndexError) as e:
            logger.error(f"Failed to parse DNS response '{txt_record}': {e}")
            return None

    def _parse_netcat_response(self, response: str, queried_ips: list[str]) -> dict[str, CymruResult]:
        """Parse netcat bulk interface response.

        Format: "AS      | IP               | BGP Prefix          | CC | Registry | Allocated  | AS Name"
        Example: "15169   | 8.8.8.8          | 8.8.8.0/24         | US | arin     | 1992-12-01 | GOOGLE, US"

        Response includes:
        - Header line: "Bulk mode; whois.cymru.com [timestamp]"
        - Column header: "AS | IP | BGP Prefix | CC | Registry | Allocated | AS Name"
        - Data lines: One per IP with pipe-delimited fields

        Args:
            response: Full netcat response text
            queried_ips: List of IPs that were queried (for validation)

        Returns:
            Dictionary mapping IP addresses to CymruResult objects
        """
        results: dict[str, CymruResult] = {}
        lines = response.strip().split("\n")

        # Skip header lines (Bulk mode..., AS | IP | ...)
        # Data lines are those with "|" that don't start with "AS" (column header)
        data_lines = [
            line for line in lines if "|" in line and not line.strip().startswith("AS") and not line.startswith("Bulk")
        ]

        for line in data_lines:
            try:
                # Split by pipe character
                parts = [p.strip() for p in line.split('|')]

                if len(parts) < 6:
                    logger.warning(f"Invalid netcat response format: {line}")
                    continue

                # Extract fields
                asn_str = parts[0].strip()
                ip_address = parts[1].strip()
                prefix = parts[2].strip() if parts[2].strip() else None
                country_code = parts[3].strip() if parts[3].strip() else None
                registry = parts[4].strip() if parts[4].strip() else None
                allocation_date = parts[5].strip() if parts[5].strip() else None
                asn_org = parts[6].strip() if len(parts) > 6 and parts[6].strip() else None

                # Parse ASN (may be "NA" for unallocated)
                if asn_str == "NA" or not asn_str.isdigit():
                    continue

                asn = int(asn_str)

                # Verify IP was in our query list
                if ip_address not in queried_ips:
                    logger.warning(f"Unexpected IP in response: {ip_address}")
                    continue

                results[ip_address] = CymruResult(
                    ip_address=ip_address,
                    asn=asn,
                    asn_org=asn_org,
                    country_code=country_code,
                    registry=registry.lower() if registry else None,
                    prefix=prefix,
                    allocation_date=allocation_date,
                    ttl_days=self.ttl_days,
                )

            except (ValueError, IndexError) as e:
                logger.error(f"Failed to parse netcat response line '{line}': {e}")
                continue

        return results

    def _result_to_dict(self, result: CymruResult) -> dict[str, Any]:
        """Convert CymruResult to dictionary for caching.

        Args:
            result: CymruResult object

        Returns:
            Dictionary representation
        """
        return {
            'ip_address': result.ip_address,
            'asn': result.asn,
            'asn_org': result.asn_org,
            'country_code': result.country_code,
            'registry': result.registry,
            'prefix': result.prefix,
            'allocation_date': result.allocation_date,
            'source': result.source,
            'cached_at': result.cached_at.isoformat(),
            'ttl_days': result.ttl_days,
        }

    def _dict_to_result(self, data: dict[str, Any]) -> CymruResult:
        """Convert cached dictionary to CymruResult.

        Args:
            data: Dictionary from cache

        Returns:
            CymruResult object
        """
        # Parse cached_at timestamp
        cached_at = data.get('cached_at')
        if isinstance(cached_at, str):
            cached_at = datetime.fromisoformat(cached_at)
        elif not isinstance(cached_at, datetime):
            cached_at = datetime.now(timezone.utc)

        return CymruResult(
            ip_address=data['ip_address'],
            asn=data.get('asn'),
            asn_org=data.get('asn_org'),
            country_code=data.get('country_code'),
            registry=data.get('registry'),
            prefix=data.get('prefix'),
            allocation_date=data.get('allocation_date'),
            source=data.get('source', 'cymru'),
            cached_at=cached_at,
            ttl_days=data.get('ttl_days', 90),
        )

    def get_stats(self) -> dict[str, int]:
        """Get client statistics.

        Returns:
            Dictionary with lookup statistics
        """
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Reset statistics counters."""
        for key in self.stats:
            self.stats[key] = 0


__all__ = ['CymruClient', 'CymruResult']
