"""GreyNoise Community API client for scanner/bot detection.

GreyNoise provides threat intelligence on internet scanning and mass exploitation activity.
The Community API provides free access to basic IP reputation data with a 10K/day rate limit.

API Documentation:
    https://docs.greynoise.io/docs/using-the-greynoise-community-api

Response Format:
    {
        "ip": "8.8.8.8",
        "noise": false,          # True if known scanner/malicious activity
        "riot": true,            # True if benign service (CDN, cloud, etc.)
        "classification": "benign",  # malicious, benign, or unknown
        "name": "Google Public DNS",
        "link": "https://viz.greynoise.io/riot/8.8.8.8",
        "last_seen": "2024-11-05"
    }

Cache TTL: 7 days per ADR-008 specification
Rate Limit: 10,000 requests/day, 10 requests/second throttle
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests

from .cache import EnrichmentCacheManager
from .rate_limiting import RateLimiter

logger = logging.getLogger(__name__)


@dataclass
class GreyNoiseResult:
    """Result from GreyNoise Community API lookup.

    Attributes:
        ip_address: The IP address that was looked up
        noise: True if IP is known scanner/malicious actor
        riot: True if IP is benign service (CDN, cloud provider, etc.)
        classification: Threat classification (malicious, benign, or unknown)
        name: Service name if RIOT (benign service)
        last_seen: Date when IP was last observed by GreyNoise
        source: Data source identifier (always "greynoise")
        cached_at: Timestamp when result was retrieved
        ttl_days: Cache time-to-live in days
    """

    ip_address: str
    noise: bool
    riot: bool
    classification: str | None
    name: str | None = None
    last_seen: datetime | None = None
    source: str = "greynoise"
    cached_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_days: int = 7


class GreyNoiseClient:
    """GreyNoise Community API client with 10K/day rate limit.

    Provides scanner/bot detection using GreyNoise's Community API with:
    - API: Community API endpoint (10K requests/day limit)
    - Cache: 7-day TTL per ADR-008 specification
    - Rate limiting: 10 requests/second throttle
    - Quota tracking: Daily usage counter with midnight UTC reset

    Usage:
        cache = EnrichmentCacheManager(base_dir=Path("/cache"))
        limiter = RateLimiter(rate=10.0)
        client = GreyNoiseClient(api_key="YOUR_KEY", cache=cache, rate_limiter=limiter)

        # Single lookup
        result = client.lookup_ip("8.8.8.8")
        if result:
            print(f"Noise: {result.noise}, RIOT: {result.riot}")

        # Check quota
        remaining = client.get_remaining_quota()
        print(f"Daily quota remaining: {remaining}")
    """

    # GreyNoise Community API endpoint
    API_BASE_URL = "https://api.greynoise.io/v3/community"

    # Daily quota limit
    DAILY_QUOTA = 10000

    # Retry configuration
    MAX_RETRIES = 3
    RETRY_DELAYS = [1.0, 2.0, 4.0]  # Exponential backoff

    # Quota cache key prefix
    QUOTA_KEY_PREFIX = "greynoise:quota:"

    def __init__(
        self,
        api_key: str,
        cache: EnrichmentCacheManager,
        rate_limiter: RateLimiter | None = None,
        ttl_days: int = 7,
    ) -> None:
        """Initialize GreyNoise Community API client.

        Args:
            api_key: GreyNoise Community API key
            cache: Cache manager for storing lookup results
            rate_limiter: Optional rate limiter (defaults to 10 req/sec)
            ttl_days: Cache TTL in days (default: 7)
        """
        self.api_key = api_key
        self.cache = cache
        self.rate_limiter = rate_limiter or RateLimiter(rate=10.0, burst=10)
        self.ttl_days = ttl_days

        # Statistics
        self.stats: dict[str, int] = {
            'lookups': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'api_success': 0,
            'api_failures': 0,
            'quota_exceeded': 0,
            'errors': 0,
        }

        logger.info("GreyNoise Community API client initialized with 7-day cache TTL")

    def lookup_ip(self, ip_address: str) -> GreyNoiseResult | None:
        """Check if IP is known scanner/bot with 7-day cache.

        Results are cached for 7 days per ADR-008 specification.
        Returns None if quota exhausted or lookup failed.

        Args:
            ip_address: IP address to look up (IPv4 or IPv6)

        Returns:
            GreyNoiseResult with threat data or None if lookup failed

        Examples:
            >>> client = GreyNoiseClient(api_key, cache, limiter)
            >>> result = client.lookup_ip("8.8.8.8")
            >>> if result:
            ...     print(f"RIOT: {result.riot}, Name: {result.name}")
            RIOT: True, Name: Google Public DNS
        """
        self.stats['lookups'] += 1

        # Check cache first
        cached_data = self.cache.get_cached("greynoise", ip_address)

        if cached_data:
            self.stats['cache_hits'] += 1
            logger.debug(f"Cache hit for {ip_address}")
            return self._dict_to_result(cached_data)

        self.stats['cache_misses'] += 1

        # Check daily quota
        if self.get_remaining_quota() <= 0:
            logger.warning("GreyNoise daily quota exceeded (10K/day limit)")
            self.stats['quota_exceeded'] += 1
            return None

        # Perform API lookup
        result = self._lookup_api(ip_address)

        # Cache successful result
        if result:
            result_dict = self._result_to_dict(result)
            self.cache.store_cached("greynoise", ip_address, result_dict)
            logger.debug(f"Cached result for {ip_address}")

            # Increment quota counter
            self._increment_quota()

        return result

    def get_remaining_quota(self) -> int:
        """Return daily API calls remaining (for monitoring).

        Quota counter resets at midnight UTC daily.

        Returns:
            Number of API calls remaining today (0-10000)

        Examples:
            >>> client = GreyNoiseClient(api_key, cache, limiter)
            >>> remaining = client.get_remaining_quota()
            >>> print(f"Calls remaining: {remaining}")
            Calls remaining: 9847
        """
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        quota_key = f"{self.QUOTA_KEY_PREFIX}{today}"

        # Get quota counter from cache
        quota_data = self.cache.get_cached("greynoise", quota_key)

        if quota_data and isinstance(quota_data, dict):
            used_today: int = int(quota_data.get('count', 0))
        else:
            used_today = 0

        return max(0, self.DAILY_QUOTA - used_today)

    def _lookup_api(self, ip_address: str) -> GreyNoiseResult | None:
        """Perform GreyNoise Community API lookup.

        Args:
            ip_address: IP address to look up

        Returns:
            GreyNoiseResult or None if lookup failed
        """
        url = f"{self.API_BASE_URL}/{ip_address}"
        headers = {
            'key': self.api_key,
            'Accept': 'application/json',
        }

        for attempt in range(self.MAX_RETRIES):
            try:
                # Rate limit API requests
                self.rate_limiter.acquire_sync()

                # Query GreyNoise API
                response = requests.get(url, headers=headers, timeout=10.0)

                # Handle specific status codes
                if response.status_code == 401:
                    logger.error("GreyNoise API authentication failed (invalid API key)")
                    self.stats['api_failures'] += 1
                    self.stats['errors'] += 1
                    return None

                if response.status_code == 429:
                    logger.warning("GreyNoise rate limit exceeded")
                    self.stats['quota_exceeded'] += 1
                    self.stats['api_failures'] += 1

                    # Retry with backoff if rate limited
                    if attempt < self.MAX_RETRIES - 1:
                        delay = self.RETRY_DELAYS[attempt]
                        logger.info(f"Rate limited, retrying in {delay}s")
                        time.sleep(delay)
                        continue

                    return None

                if response.status_code == 404:
                    # IP not found in GreyNoise database (treat as unknown)
                    logger.debug(f"IP {ip_address} not found in GreyNoise database")
                    unknown_result = GreyNoiseResult(
                        ip_address=ip_address,
                        noise=False,
                        riot=False,
                        classification="unknown",
                        name=None,
                        last_seen=None,
                        ttl_days=self.ttl_days,
                    )
                    self.stats['api_success'] += 1
                    return unknown_result

                # Raise for other HTTP errors
                response.raise_for_status()

                # Parse JSON response
                data = response.json()
                parsed_result = self._parse_api_response(ip_address, data)

                if parsed_result:
                    self.stats['api_success'] += 1
                    logger.debug(f"API success for {ip_address}")
                    return parsed_result

                # Invalid response format
                logger.warning(f"Invalid API response for {ip_address}: {data}")
                self.stats['api_failures'] += 1
                return None

            except requests.exceptions.Timeout:
                # HTTP timeout - retry with backoff
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_DELAYS[attempt]
                    logger.warning(f"API timeout for {ip_address}, retrying in {delay}s")
                    time.sleep(delay)
                else:
                    logger.error(f"API timeout for {ip_address} after {self.MAX_RETRIES} attempts")
                    self.stats['api_failures'] += 1
                    return None

            except requests.exceptions.RequestException as e:
                logger.error(f"API request failed for {ip_address}: {e}")
                self.stats['api_failures'] += 1
                self.stats['errors'] += 1
                return None

            except Exception as e:
                logger.error(f"API lookup failed for {ip_address}: {e}")
                self.stats['api_failures'] += 1
                self.stats['errors'] += 1
                return None

        return None

    def _parse_api_response(self, ip_address: str, data: dict[str, Any]) -> GreyNoiseResult | None:
        """Parse GreyNoise Community API response.

        Example response:
            {
                "ip": "8.8.8.8",
                "noise": false,
                "riot": true,
                "classification": "benign",
                "name": "Google Public DNS",
                "link": "https://viz.greynoise.io/riot/8.8.8.8",
                "last_seen": "2024-11-05"
            }

        Args:
            ip_address: Original IP address queried
            data: JSON response from API

        Returns:
            GreyNoiseResult or None if parsing failed
        """
        try:
            # Extract required fields
            noise = data.get('noise', False)
            riot = data.get('riot', False)
            classification = data.get('classification')
            name = data.get('name')
            last_seen_str = data.get('last_seen')

            # Parse last_seen date
            last_seen = None
            if last_seen_str:
                try:
                    # Parse ISO date format
                    last_seen = datetime.fromisoformat(last_seen_str).replace(tzinfo=timezone.utc)
                except (ValueError, AttributeError):
                    logger.warning(f"Failed to parse last_seen date: {last_seen_str}")

            return GreyNoiseResult(
                ip_address=ip_address,
                noise=noise,
                riot=riot,
                classification=classification,
                name=name,
                last_seen=last_seen,
                ttl_days=self.ttl_days,
            )

        except (KeyError, ValueError) as e:
            logger.error(f"Failed to parse API response for {ip_address}: {e}")
            return None

    def _increment_quota(self) -> None:
        """Increment daily quota counter.

        Counter is stored in cache with midnight UTC reset.
        """
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        quota_key = f"{self.QUOTA_KEY_PREFIX}{today}"

        # Get current count
        quota_data = self.cache.get_cached("greynoise", quota_key)

        if quota_data and isinstance(quota_data, dict):
            count = quota_data.get('count', 0) + 1
        else:
            count = 1

        # Store updated count (cache until end of day)
        self.cache.store_cached(
            "greynoise",
            quota_key,
            {'count': count, 'date': today},
        )

    def _result_to_dict(self, result: GreyNoiseResult) -> dict[str, Any]:
        """Convert GreyNoiseResult to dictionary for caching.

        Args:
            result: GreyNoiseResult object

        Returns:
            Dictionary representation
        """
        return {
            'ip_address': result.ip_address,
            'noise': result.noise,
            'riot': result.riot,
            'classification': result.classification,
            'name': result.name,
            'last_seen': result.last_seen.isoformat() if result.last_seen else None,
            'source': result.source,
            'cached_at': result.cached_at.isoformat(),
            'ttl_days': result.ttl_days,
        }

    def _dict_to_result(self, data: dict[str, Any]) -> GreyNoiseResult:
        """Convert cached dictionary to GreyNoiseResult.

        Args:
            data: Dictionary from cache

        Returns:
            GreyNoiseResult object
        """
        # Parse cached_at timestamp
        cached_at = data.get('cached_at')
        if isinstance(cached_at, str):
            cached_at = datetime.fromisoformat(cached_at)
        elif not isinstance(cached_at, datetime):
            cached_at = datetime.now(timezone.utc)

        # Parse last_seen timestamp
        last_seen = data.get('last_seen')
        if isinstance(last_seen, str):
            last_seen = datetime.fromisoformat(last_seen)
        elif not isinstance(last_seen, datetime):
            last_seen = None

        return GreyNoiseResult(
            ip_address=data['ip_address'],
            noise=data.get('noise', False),
            riot=data.get('riot', False),
            classification=data.get('classification'),
            name=data.get('name'),
            last_seen=last_seen,
            source=data.get('source', 'greynoise'),
            cached_at=cached_at,
            ttl_days=data.get('ttl_days', 7),
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


__all__ = ['GreyNoiseClient', 'GreyNoiseResult']
