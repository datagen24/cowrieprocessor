"""IP matching components for classification.

This module provides the abstract base class and concrete implementations for
matching IPs against various data sources (TOR, Cloud, Datacenter, Residential).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class IPMatcher(ABC):
    """Abstract base class for IP matchers.

    All matchers implement a common interface for matching IPs against their
    data sources, with automatic data updates and staleness checking.

    Subclasses must implement:
        - match(ip: str) -> Optional[Dict[str, str]]: Check if IP matches
        - _download_data() -> None: Download/parse data from source

    Attributes:
        data_url: URL to download data from
        update_interval_seconds: How often to update data
        cache_dir: Directory to cache downloaded data
        last_update: Timestamp of last successful update
        _data_loaded: Whether data has been loaded at least once

    Example:
        >>> class MyMatcher(IPMatcher):
        ...     def match(self, ip: str) -> Optional[Dict[str, str]]:
        ...         # Implementation
        ...         pass
        ...     def _download_data(self) -> None:
        ...         # Implementation
        ...         pass
    """

    def __init__(
        self,
        data_url: str,
        update_interval_seconds: int,
        cache_dir: Path,
    ) -> None:
        """Initialize matcher.

        Args:
            data_url: URL to download data from
            update_interval_seconds: How often to update data (seconds)
            cache_dir: Directory to cache downloaded data
        """
        self.data_url = data_url
        self.update_interval_seconds = update_interval_seconds
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.last_update: Optional[datetime] = None
        self._data_loaded = False

    @abstractmethod
    def match(self, ip: str) -> Optional[Dict[str, str]]:
        """Check if IP matches this matcher's type.

        Args:
            ip: IPv4 or IPv6 address to check

        Returns:
            Dict with match metadata if matched, None otherwise.
            Example: {'provider': 'aws', 'region': 'us-east-1'}

        Note:
            Implementations should call _ensure_data_loaded() before matching
            to guarantee fresh data is available.
        """
        pass

    @abstractmethod
    def _download_data(self) -> None:
        """Download and parse data from source.

        Must be implemented by subclasses. Should:
        1. Download data from self.data_url
        2. Parse and store data in memory structures
        3. Optionally cache to disk in self.cache_dir

        Raises:
            Exception: If download or parsing fails
        """
        pass

    def _is_stale(self) -> bool:
        """Check if data needs updating.

        Returns:
            True if data has never been loaded or is older than update_interval_seconds
        """
        if not self._data_loaded or self.last_update is None:
            return True

        age_seconds = (datetime.now(timezone.utc) - self.last_update).total_seconds()
        return age_seconds > self.update_interval_seconds

    def _ensure_data_loaded(self, force: bool = False) -> None:
        """Ensure data is loaded and fresh.

        Loads data if not yet loaded, or updates if stale. Safe to call
        repeatedly - will only download when necessary.

        Args:
            force: Force update even if not stale

        Raises:
            Exception: If download fails and no fallback data available
        """
        if not force and not self._is_stale():
            return  # Data is fresh, nothing to do

        self._update_data(force=force)

    def _update_data(self, force: bool = False) -> None:
        """Update data if stale or forced.

        Args:
            force: Force update even if not stale

        Raises:
            Exception: If download fails and no fallback data available
        """
        if not force and not self._is_stale():
            return

        try:
            logger.info(f"{self.__class__.__name__}: Updating data from {self.data_url}")
            self._download_data()
            self.last_update = datetime.now(timezone.utc)
            self._data_loaded = True
            logger.info(
                f"{self.__class__.__name__}: Data updated successfully (next update in {self.update_interval_seconds}s)"
            )
        except Exception as e:
            logger.error(f"{self.__class__.__name__}: Data update failed: {e}")
            if not self._data_loaded:
                # No fallback data available, must raise
                raise RuntimeError(f"{self.__class__.__name__}: Initial data load failed and no cache available") from e
            # Use stale data if available
            age_seconds = (
                (datetime.now(timezone.utc) - self.last_update).total_seconds() if self.last_update else float("inf")
            )
            logger.warning(
                f"{self.__class__.__name__}: Using stale data "
                f"(age: {age_seconds:.0f}s, last update: {self.last_update})"
            )

    def get_stats(self) -> Dict[str, Any]:
        """Get matcher statistics.

        Returns:
            Dict with statistics:
                - data_loaded: Whether data has been loaded
                - last_update: Timestamp of last update (None if never)
                - is_stale: Whether data is currently stale
                - age_seconds: Age of data in seconds (None if never loaded)
        """
        age_seconds = None
        if self.last_update:
            age_seconds = (datetime.now(timezone.utc) - self.last_update).total_seconds()

        return {
            "data_loaded": self._data_loaded,
            "last_update": self.last_update.isoformat() if self.last_update else None,
            "is_stale": self._is_stale(),
            "age_seconds": age_seconds,
            "update_interval_seconds": self.update_interval_seconds,
        }
