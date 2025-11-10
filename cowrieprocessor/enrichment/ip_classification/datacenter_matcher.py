"""Datacenter and hosting provider IP matcher using PyTricia.

This module provides O(log n) CIDR matching for datacenter and hosting provider
IP ranges with weekly automated updates from community-maintained lists.
"""

from __future__ import annotations

import csv
import logging
from io import StringIO
from pathlib import Path
from typing import Any, Dict, Optional

import requests

try:
    import pytricia
except ImportError:
    pytricia = None

from .matchers import IPMatcher

logger = logging.getLogger(__name__)


class DatacenterMatcher(IPMatcher):
    """Match IPs to datacenter and hosting provider ranges.

    Data Source:
        GitHub: jhassine/server-ip-addresses
        License: MIT
        Update Frequency: Weekly (604800 seconds)
        Accuracy: 70-80% (community-maintained, varies by provider)

    Performance:
        Uses PyTricia prefix tree for O(log n) CIDR lookups.
        Average lookup: <1ms for 10,000+ CIDRs.
        Memory: ~2-3MB for datacenter ranges.

    Covered Providers:
        - DigitalOcean
        - Linode
        - OVH
        - Hetzner
        - Vultr
        - Other hosting providers

    Thread Safety:
        This class is NOT thread-safe. Use separate instances per thread
        or add external locking.

    Example:
        >>> from pathlib import Path
        >>> matcher = DatacenterMatcher(
        ...     data_url="https://raw.githubusercontent.com/jhassine/server-ip-addresses/master",
        ...     update_interval_seconds=604800,
        ...     cache_dir=Path("/tmp/ip_classification")
        ... )
        >>> matcher._ensure_data_loaded()
        >>> result = matcher.match("1.2.3.4")  # DigitalOcean IP
        >>> print(result)
        {'provider': 'digitalocean', 'region': 'nyc1'}
    """

    PROVIDERS = ["digitalocean", "linode", "ovh", "hetzner", "vultr"]

    def __init__(
        self,
        data_url: str = "https://raw.githubusercontent.com/jhassine/server-ip-addresses/master",
        update_interval_seconds: int = 604800,  # 7 days
        cache_dir: Path = Path.home() / ".cache" / "cowrieprocessor" / "ip_classification",
        request_timeout: int = 30,
    ) -> None:
        """Initialize datacenter matcher.

        Args:
            data_url: Base URL for GitHub repository
            update_interval_seconds: Seconds between updates (default: 604800 = 7 days)
            cache_dir: Directory to cache downloaded data
            request_timeout: HTTP timeout in seconds (default: 30)

        Raises:
            ImportError: If pytricia is not installed
        """
        if pytricia is None:
            raise ImportError("pytricia is required for DatacenterMatcher. Install with: uv pip install pytricia")

        super().__init__(
            data_url=data_url,
            update_interval_seconds=update_interval_seconds,
            cache_dir=cache_dir,
        )
        self.request_timeout = request_timeout

        # PyTricia tree for all datacenter providers
        self.trie: Any = pytricia.PyTricia()

        # Statistics tracking
        self._stats_lookups = 0
        self._stats_hits = 0
        self._stats_misses = 0
        self._provider_cidr_counts: Dict[str, int] = {provider: 0 for provider in self.PROVIDERS}
        self._total_cidrs_loaded = 0

    def match(self, ip: str) -> Optional[Dict[str, str]]:
        """Check if IP belongs to a datacenter or hosting provider.

        This method performs O(log n) CIDR tree lookup after ensuring data is loaded.

        Args:
            ip: IPv4 or IPv6 address to check

        Returns:
            Dict with provider metadata if match:
                {'provider': str, 'region': str}
            None if no match

        Note:
            Automatically triggers data update if stale (>7 days old).
            Uses graceful degradation if update fails.

        Example:
            >>> result = matcher.match("104.236.1.1")  # DigitalOcean
            >>> result
            {'provider': 'digitalocean', 'region': 'nyc1'}
        """
        self._ensure_data_loaded()
        self._stats_lookups += 1

        if ip in self.trie:
            metadata = self.trie[ip]
            self._stats_hits += 1
            return {
                "provider": metadata.get("provider", "unknown"),
                "region": metadata.get("region", "unknown"),
            }

        self._stats_misses += 1
        return None

    def _download_data(self) -> None:
        """Download and parse datacenter IP ranges from unified CSV file.

        Downloads single datacenters.csv file containing all hosting providers
        and builds a unified PyTricia prefix tree for fast CIDR matching.

        Data Format (CSV):
            Header: cidr,hostmin,hostmax,vendor
            Example: 104.236.0.0/16,104.236.0.0,104.236.255.255,DigitalOcean

        Providers Included:
            - AWS, DigitalOcean, Linode, OVH, Hetzner, Vultr, and many others
            - Total: ~47,000+ CIDRs across all cloud/datacenter providers

        Raises:
            requests.RequestException: If HTTP request fails
            ValueError: If CSV is malformed or empty

        Note:
            Single unified CSV file from jhassine/server-ip-addresses repository.
            File path: data/datacenters.csv
            Called automatically by _ensure_data_loaded() when stale.
        """
        url = f"{self.data_url}/data/datacenters.csv"
        logger.debug(f"Downloading datacenter ranges from {url}")

        response = requests.get(url, timeout=self.request_timeout)
        response.raise_for_status()

        if not response.text:
            raise ValueError("Empty response from datacenter IP ranges")

        # Cache to disk
        cache_file = self.cache_dir / "datacenters.csv"
        cache_file.write_text(response.text)

        # Parse CSV: cidr,hostmin,hostmax,vendor
        new_trie = pytricia.PyTricia()
        reader = csv.DictReader(StringIO(response.text))
        total_cidrs_loaded = 0
        self._provider_cidr_counts.clear()

        for row in reader:
            try:
                provider = row.get("vendor", "").strip().lower()
                cidr = row.get("cidr", "").strip()

                if not cidr or not provider:
                    continue

                # Store in trie with provider info
                new_trie[cidr] = {"provider": provider, "region": "unknown"}
                total_cidrs_loaded += 1

                # Track per-provider counts
                self._provider_cidr_counts[provider] = self._provider_cidr_counts.get(provider, 0) + 1

            except (ValueError, KeyError) as e:
                logger.warning(f"Invalid CIDR entry in datacenters.csv: {row} - {e}")
                continue

        if total_cidrs_loaded == 0:
            raise ValueError("No valid CIDRs loaded from datacenters.csv")

        # Replace old trie atomically
        self.trie = new_trie
        self._total_cidrs_loaded = total_cidrs_loaded

        logger.info(
            f"Datacenter ranges loaded: {total_cidrs_loaded} total CIDRs "
            f"from {len(self._provider_cidr_counts)} providers"
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get matcher statistics including per-provider CIDR counts.

        Returns:
            Dict with statistics:
                - data_loaded: Whether data has been loaded
                - last_update: Timestamp of last update (None if never)
                - is_stale: Whether data is currently stale
                - age_seconds: Age of data in seconds (None if never loaded)
                - update_interval_seconds: Configured update interval
                - total_cidrs: Total CIDRs across all providers
                - provider_cidrs: Dict of CIDR counts per provider
                - lookups: Total number of match() calls
                - hits: Number of successful matches
                - misses: Number of non-matches
                - hit_rate: Percentage of lookups that matched (0.0-1.0)
        """
        base_stats = super().get_stats()

        base_stats.update(
            {
                "total_cidrs": self._total_cidrs_loaded,
                "provider_cidrs": self._provider_cidr_counts.copy(),
                "lookups": self._stats_lookups,
                "hits": self._stats_hits,
                "misses": self._stats_misses,
                "hit_rate": (self._stats_hits / self._stats_lookups if self._stats_lookups > 0 else 0.0),
            }
        )
        return base_stats
