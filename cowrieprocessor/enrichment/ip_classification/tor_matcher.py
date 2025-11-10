"""TOR exit node matcher for IP classification.

This module provides matching against the official Tor Project exit node list
with O(1) set lookups and hourly update capability.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from .matchers import IPMatcher

logger = logging.getLogger(__name__)


class TorExitNodeMatcher(IPMatcher):
    """Match IPs against Tor Project's official exit node list.

    Data Source:
        Official Tor Project Bulk Exit List
        URL: https://check.torproject.org/torbulkexitlist
        Update Frequency: Hourly (3600 seconds)
        Accuracy: 95%+ (official source)

    Performance:
        - O(1) set lookup
        - ~2000 exit nodes typical
        - <1ms per lookup

    Thread Safety:
        This class is NOT thread-safe. Use separate instances per thread
        or add external locking.

    Example:
        >>> from pathlib import Path
        >>> matcher = TorExitNodeMatcher(
        ...     data_url="https://check.torproject.org/torbulkexitlist",
        ...     update_interval_seconds=3600,
        ...     cache_dir=Path("/tmp/ip_classification")
        ... )
        >>> matcher._ensure_data_loaded()  # Download latest list
        >>> result = matcher.match("1.2.3.4")
        >>> if result:
        ...     print(f"TOR exit node: {result}")
    """

    def __init__(
        self,
        data_url: str = "https://check.torproject.org/torbulkexitlist",
        update_interval_seconds: int = 3600,  # 1 hour
        cache_dir: Path = Path.home() / ".cache" / "cowrieprocessor" / "ip_classification",
        request_timeout: int = 30,
    ) -> None:
        """Initialize TOR exit node matcher.

        Args:
            data_url: URL to download TOR exit node list
            update_interval_seconds: Seconds between updates (default: 3600 = 1 hour)
            cache_dir: Directory to cache downloaded data
            request_timeout: HTTP request timeout in seconds (default: 30)
        """
        super().__init__(
            data_url=data_url,
            update_interval_seconds=update_interval_seconds,
            cache_dir=cache_dir,
        )
        self.request_timeout = request_timeout
        self.exit_nodes: set[str] = set()

        # Statistics tracking
        self._stats_lookups = 0
        self._stats_hits = 0
        self._stats_misses = 0

    def match(self, ip: str) -> Optional[Dict[str, str]]:
        """Check if IP is a TOR exit node.

        This method performs O(1) set lookup after ensuring data is loaded.
        Safe to call repeatedly - will only update data when stale.

        Args:
            ip: IPv4 or IPv6 address to check

        Returns:
            {'provider': 'tor'} if IP is TOR exit node, None otherwise

        Note:
            Automatically triggers data update if stale (>1 hour old).
            Uses graceful degradation if update fails.
        """
        self._ensure_data_loaded()
        self._stats_lookups += 1

        if ip in self.exit_nodes:
            self._stats_hits += 1
            return {"provider": "tor"}

        self._stats_misses += 1
        return None

    def _download_data(self) -> None:
        """Download and parse TOR exit node list.

        Downloads plain text IP list from Tor Project, parses into set,
        and caches to disk. Updates self.exit_nodes in-place.

        Data Format:
            Plain text file with one IP per line
            Example:
                1.2.3.4
                5.6.7.8
                2001:db8::1

        Raises:
            requests.RequestException: If HTTP request fails
            ValueError: If response is empty or malformed

        Note:
            Called automatically by _ensure_data_loaded() when stale.
            Safe to call manually for force refresh.
        """
        logger.info(f"Downloading TOR exit node list from {self.data_url} (timeout: {self.request_timeout}s)")

        response = requests.get(self.data_url, timeout=self.request_timeout)
        response.raise_for_status()

        if not response.text:
            raise ValueError("Empty response from TOR exit node list")

        # Parse plain text IP list (one IP per line)
        new_nodes = set(line.strip() for line in response.text.splitlines() if line.strip())

        if not new_nodes:
            raise ValueError("No valid IPs found in TOR exit node list")

        # Cache to disk
        cache_file = self.cache_dir / "tor_exit_nodes.txt"
        cache_file.write_text(response.text)
        logger.debug(f"Cached TOR exit nodes to {cache_file}")

        # Update in-memory set
        self.exit_nodes = new_nodes
        logger.info(f"Loaded {len(self.exit_nodes)} TOR exit nodes")

    def get_stats(self) -> Dict[str, Any]:
        """Get matcher statistics including lookups and hit rate.

        Returns:
            Dict with statistics:
                - data_loaded: Whether data has been loaded
                - last_update: Timestamp of last update (None if never)
                - is_stale: Whether data is currently stale
                - age_seconds: Age of data in seconds (None if never loaded)
                - update_interval_seconds: Configured update interval
                - exit_node_count: Number of TOR exit nodes
                - lookups: Total number of match() calls
                - hits: Number of successful matches
                - misses: Number of non-matches
                - hit_rate: Percentage of lookups that matched (0.0-1.0)
        """
        base_stats = super().get_stats()
        base_stats.update(
            {
                "exit_node_count": len(self.exit_nodes),
                "lookups": self._stats_lookups,
                "hits": self._stats_hits,
                "misses": self._stats_misses,
                "hit_rate": (self._stats_hits / self._stats_lookups if self._stats_lookups > 0 else 0.0),
            }
        )
        return base_stats
