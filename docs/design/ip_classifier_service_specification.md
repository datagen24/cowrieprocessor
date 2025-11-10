# IPClassifier Service - Technical Design Specification

**Version**: 1.0
**Date**: 2025-11-10
**Status**: Design Review
**Compliance**: ADR-007 (Three-Tier Enrichment), ADR-008 (Rate Limiting), Project Coding Standards

---

## 1. Executive Summary

### 1.1 Purpose
Design a production-grade IP classification service that populates `snapshot_ip_type` with infrastructure categories (TOR, Cloud, Datacenter, Residential, Unknown) using **100% free data sources** and adhering to cowrieprocessor's established patterns.

### 1.2 Key Requirements
- **Multi-Tier Caching**: Redis L1 → Database L2 → Disk L3 (matching HybridEnrichmentCache pattern)
- **Free Data Sources**: $0/month cost (Tor Project, GitHub open-source lists)
- **Coverage Target**: 90%+ of IPs classified
- **Performance Target**: <10ms lookup (99th percentile, cached)
- **Project Standards**: Follow cascade_enricher.py, hybrid_cache.py, db_cache.py patterns

### 1.3 Success Criteria
1. ✅ Integrated with CascadeEnricher (Pass 4 enrichment)
2. ✅ Multi-tier cache with hit rate >95% (after warmup)
3. ✅ Zero external API costs (all free data sources)
4. ✅ Type safety with complete type hints (mypy strict)
5. ✅ Test coverage ≥85% (matching project standards)
6. ✅ Google-style docstrings for all public APIs

---

## 2. Architecture Overview

### 2.1 System Context

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CascadeEnricher                             │
│                                                                       │
│  Pass 1: MaxMind GeoIP     (geo_country, geo_city)                  │
│  Pass 2: Team Cymru ASN    (asn, as_name, as_country)               │
│  Pass 3: GreyNoise         (scanner flags, tags)                    │
│  Pass 4: IPClassifier ← NEW (ip_type, ip_type_provider)         │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        IPClassifier Service                          │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │          Classification Pipeline (Priority Order)            │  │
│  │                                                                │  │
│  │  1. TOR Exit Node Check       (95%+ accuracy)                 │  │
│  │  2. Cloud Provider Match       (99%+ accuracy)                 │  │
│  │  3. Datacenter/Hosting Match   (70-80% accuracy)               │  │
│  │  4. Residential Heuristic      (70-80% accuracy)               │  │
│  │  5. Unknown Fallback           (0% confidence)                 │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │        Multi-Tier Cache (HybridClassificationCache)          │  │
│  │                                                                │  │
│  │  L1: Redis (in-memory, <1ms, TTL: 1-24h)                     │  │
│  │  L2: Database (enrichment_cache table, <10ms, TTL: 7 days)   │  │
│  │  L3: Disk (filesystem cache, <50ms, TTL: 30 days)            │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │           Data Sources (IP Range Matchers)                   │  │
│  │                                                                │  │
│  │  • TorExitNodeMatcher    (PySet lookup, O(1))                 │  │
│  │  • CloudProviderMatcher  (PyTricia CIDR tree, O(log n))       │  │
│  │  • DatacenterMatcher     (PyTricia CIDR tree, O(log n))       │  │
│  │  • ResidentialHeuristic  (Regex ASN name, O(n patterns))      │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │        Data Update Service (Background Cron Jobs)            │  │
│  │                                                                │  │
│  │  • TOR list:        Hourly   (tor_updater.py)                 │  │
│  │  • Cloud ranges:    Daily    (cloud_updater.py)               │  │
│  │  • Datacenter list: Weekly   (datacenter_updater.py)          │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Component Diagram

```
cowrieprocessor/enrichment/
├── ip_classification/              # NEW package
│   ├── __init__.py                 # Public API exports
│   ├── classifier.py               # IPClassifier main service
│   ├── matchers.py                 # IP range matchers (TOR, Cloud, DC, Residential)
│   ├── cache.py                    # HybridClassificationCache
│   ├── models.py                   # Data models (IPClassification, IPType enum)
│   ├── updaters.py                 # Data source update logic
│   └── factory.py                  # create_ip_classifier() factory
├── cascade_enricher.py             # MODIFIED: Add Pass 4 (IP classification)
├── cascade_factory.py              # MODIFIED: Wire IPClassifier in factory
└── hybrid_cache.py                 # REFERENCE: Cache pattern model
```

---

## 3. Detailed Component Design

### 3.1 Data Models (`models.py`)

#### 3.1.1 IPType Enum

```python
from enum import Enum

class IPType(str, Enum):
    """IP infrastructure classification types.

    Values:
        TOR: Tor exit node (anonymization network)
        CLOUD: Cloud provider (AWS, Azure, GCP, CloudFlare)
        DATACENTER: Hosting provider, VPS, colocation
        RESIDENTIAL: ISP/Telecom residential or mobile network
        UNKNOWN: Unable to classify with confidence
    """

    TOR = "tor"
    CLOUD = "cloud"
    DATACENTER = "datacenter"
    RESIDENTIAL = "residential"
    UNKNOWN = "unknown"
```

#### 3.1.2 IPClassification Dataclass

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

@dataclass(slots=True, frozen=True)
class IPClassification:
    """Result of IP infrastructure classification.

    Attributes:
        ip_type: Infrastructure category (TOR, CLOUD, DATACENTER, RESIDENTIAL, UNKNOWN)
        provider: Provider name (e.g., "aws", "azure", "tor", AS name) or None
        confidence: Classification confidence score (0.0 to 1.0)
        source: Data source used for classification (e.g., "tor_bulk_list", "cloud_ranges_aws")
        classified_at: UTC timestamp when classification was performed

    Example:
        >>> classification = IPClassification(
        ...     ip_type=IPType.CLOUD,
        ...     provider="aws",
        ...     confidence=0.99,
        ...     source="cloud_ranges_aws",
        ...     classified_at=datetime.now(timezone.utc)
        ... )
        >>> print(classification.ip_type.value, classification.provider)
        cloud aws
    """

    ip_type: IPType
    provider: Optional[str]
    confidence: float  # 0.0 to 1.0
    source: str
    classified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        """Validate classification confidence is in [0.0, 1.0] range."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be in [0.0, 1.0], got {self.confidence}")
```

---

### 3.2 IP Matchers (`matchers.py`)

#### 3.2.1 Base Interface

```python
from abc import ABC, abstractmethod
from typing import Optional

class IPMatcher(ABC):
    """Abstract base for IP range matchers.

    All matchers follow a common interface for consistency and testing.
    """

    @abstractmethod
    def match(self, ip: str) -> Optional[dict[str, str]]:
        """Check if IP matches this matcher's criteria.

        Args:
            ip: IP address string (e.g., "1.2.3.4")

        Returns:
            Match metadata dict (provider, region, etc.) or None if no match

        Example:
            >>> matcher = CloudProviderMatcher(...)
            >>> result = matcher.match("52.0.0.1")
            >>> print(result)
            {'provider': 'aws', 'region': 'us-east-1', 'service': 'ec2'}
        """
        pass

    @abstractmethod
    def update(self) -> None:
        """Update data source (download latest ranges/lists).

        Raises:
            UpdateError: If update fails and no fallback data exists
        """
        pass

    @abstractmethod
    def get_stats(self) -> dict[str, int]:
        """Return matcher statistics (lookups, hits, updates).

        Returns:
            Statistics dictionary with keys: lookups, hits, misses, last_update_ts
        """
        pass
```

#### 3.2.2 TorExitNodeMatcher

```python
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

class TorExitNodeMatcher(IPMatcher):
    """Match IPs against Tor Project's official exit node list.

    Data Source:
        Official Tor Project Bulk Exit List
        URL: https://check.torproject.org/torbulkexitlist
        Update Frequency: Hourly
        Accuracy: 95%+ (official source)

    Thread Safety:
        This class is NOT thread-safe. Use separate instances per thread or add locking.

    Example:
        >>> matcher = TorExitNodeMatcher(
        ...     bulk_list_url="https://check.torproject.org/torbulkexitlist",
        ...     update_interval_hours=1
        ... )
        >>> matcher.update()  # Download latest list
        >>> result = matcher.match("1.2.3.4")
        >>> if result:
        ...     print(f"TOR exit node: {result}")
    """

    def __init__(
        self,
        bulk_list_url: str = "https://check.torproject.org/torbulkexitlist",
        update_interval_hours: int = 1,
        request_timeout: int = 30,
    ) -> None:
        """Initialize TOR exit node matcher.

        Args:
            bulk_list_url: URL to download TOR exit node list
            update_interval_hours: Hours between automatic updates (default: 1)
            request_timeout: HTTP request timeout in seconds (default: 30)
        """
        self.bulk_list_url = bulk_list_url
        self.update_interval = timedelta(hours=update_interval_hours)
        self.request_timeout = request_timeout

        self.exit_nodes: set[str] = set()
        self.last_update: Optional[datetime] = None
        self._stats = {
            'lookups': 0,
            'hits': 0,
            'misses': 0,
            'last_update_ts': 0,
            'update_failures': 0,
        }

    def match(self, ip: str) -> Optional[dict[str, str]]:
        """Check if IP is a TOR exit node.

        Args:
            ip: IP address string

        Returns:
            {'provider': 'tor'} if match, None otherwise
        """
        self._maybe_update()
        self._stats['lookups'] += 1

        if ip in self.exit_nodes:
            self._stats['hits'] += 1
            return {'provider': 'tor'}

        self._stats['misses'] += 1
        return None

    def update(self) -> None:
        """Download latest TOR exit node list.

        Raises:
            requests.RequestException: If download fails
        """
        try:
            response = requests.get(self.bulk_list_url, timeout=self.request_timeout)
            response.raise_for_status()

            new_nodes = set(response.text.strip().splitlines())
            self.exit_nodes = new_nodes
            self.last_update = datetime.now(timezone.utc)
            self._stats['last_update_ts'] = int(self.last_update.timestamp())

            logger.info(f"Updated TOR exit nodes: {len(self.exit_nodes)} nodes")

        except requests.RequestException as e:
            self._stats['update_failures'] += 1
            logger.error(f"Failed to update TOR exit nodes: {e}")
            # Keep existing list if update fails (graceful degradation)
            if not self.exit_nodes:
                raise  # Re-raise if no fallback data exists

    def get_stats(self) -> dict[str, int]:
        """Return matcher statistics."""
        return dict(self._stats)

    def _maybe_update(self) -> None:
        """Trigger update if stale (>1 hour old)."""
        if self.last_update is None or datetime.now(timezone.utc) - self.last_update > self.update_interval:
            try:
                self.update()
            except requests.RequestException:
                # Already logged in update(), continue with stale data
                pass
```

#### 3.2.3 CloudProviderMatcher

```python
from typing import Optional

import pytricia  # type: ignore
import requests

class CloudProviderMatcher(IPMatcher):
    """Match IPs to cloud provider ranges (AWS, Azure, GCP, CloudFlare).

    Data Source:
        GitHub: rezmoss/cloud-provider-ip-addresses
        License: CC0 1.0 Universal (Public Domain)
        Update Frequency: Daily (automated)
        Accuracy: 99%+ (official provider IP ranges)

    Performance:
        Uses PyTricia prefix tree for O(log n) CIDR lookups.
        Average lookup: <1ms for 20,000 CIDRs.

    Example:
        >>> matcher = CloudProviderMatcher(
        ...     base_url="https://raw.githubusercontent.com/rezmoss/cloud-provider-ip-addresses/main"
        ... )
        >>> matcher.update()
        >>> result = matcher.match("52.0.0.1")
        >>> print(result)
        {'provider': 'aws', 'region': 'us-east-1', 'service': 'ec2'}
    """

    PROVIDERS = ["aws", "azure", "gcp", "cloudflare"]

    def __init__(
        self,
        base_url: str = "https://raw.githubusercontent.com/rezmoss/cloud-provider-ip-addresses/main",
        update_interval_hours: int = 24,
        request_timeout: int = 30,
    ) -> None:
        """Initialize cloud provider matcher.

        Args:
            base_url: Base URL for GitHub repository
            update_interval_hours: Hours between updates (default: 24)
            request_timeout: HTTP timeout in seconds (default: 30)
        """
        self.base_url = base_url
        self.update_interval = timedelta(hours=update_interval_hours)
        self.request_timeout = request_timeout

        # One PyTricia tree per provider for fast lookups
        self.tries: dict[str, pytricia.PyTricia] = {
            provider: pytricia.PyTricia() for provider in self.PROVIDERS
        }

        self.last_update: Optional[datetime] = None
        self._stats = {
            'lookups': 0,
            'hits': 0,
            'misses': 0,
            'last_update_ts': 0,
            'update_failures': 0,
        }

    def match(self, ip: str) -> Optional[dict[str, str]]:
        """Check if IP belongs to a cloud provider.

        Args:
            ip: IP address string

        Returns:
            {'provider': str, 'region': str, 'service': str} if match, None otherwise
        """
        self._maybe_update()
        self._stats['lookups'] += 1

        for provider, trie in self.tries.items():
            if ip in trie:
                metadata = trie[ip]
                self._stats['hits'] += 1
                return {
                    'provider': provider,
                    'region': metadata.get('region', 'unknown'),
                    'service': metadata.get('service', 'unknown'),
                }

        self._stats['misses'] += 1
        return None

    def update(self) -> None:
        """Download latest IP ranges for all cloud providers.

        Downloads CSV files for each provider and rebuilds PyTricia trees.

        Raises:
            requests.RequestException: If any provider download fails
        """
        for provider in self.PROVIDERS:
            try:
                self._update_provider(provider)
            except requests.RequestException as e:
                logger.error(f"Failed to update {provider} ranges: {e}")
                self._stats['update_failures'] += 1
                # Continue updating other providers (partial success allowed)

        self.last_update = datetime.now(timezone.utc)
        self._stats['last_update_ts'] = int(self.last_update.timestamp())

    def _update_provider(self, provider: str) -> None:
        """Update IP ranges for a single provider.

        Args:
            provider: Provider name ("aws", "azure", "gcp", "cloudflare")

        Raises:
            requests.RequestException: If download fails
        """
        url = f"{self.base_url}/{provider}/ipv4.csv"
        response = requests.get(url, timeout=self.request_timeout)
        response.raise_for_status()

        # Parse CSV: ip_prefix,region,service
        new_trie = pytricia.PyTricia()
        for line in response.text.strip().splitlines()[1:]:  # Skip header
            parts = line.split(',')
            if len(parts) >= 3:
                prefix = parts[0].strip()
                region = parts[1].strip()
                service = parts[2].strip()

                try:
                    new_trie[prefix] = {'region': region, 'service': service}
                except ValueError as e:
                    logger.warning(f"Invalid CIDR {prefix} for {provider}: {e}")
                    continue

        self.tries[provider] = new_trie
        logger.info(f"Updated {provider} ranges: {len(new_trie)} CIDRs")

    def get_stats(self) -> dict[str, int]:
        """Return matcher statistics."""
        stats = dict(self._stats)
        stats['total_cidrs'] = sum(len(trie) for trie in self.tries.values())
        return stats

    def _maybe_update(self) -> None:
        """Trigger update if stale (>24 hours old)."""
        if self.last_update is None or datetime.now(timezone.utc) - self.last_update > self.update_interval:
            try:
                self.update()
            except requests.RequestException:
                pass  # Graceful degradation with stale data
```

*(DatacenterMatcher and ResidentialHeuristic follow similar patterns - see full implementation file)*

---

### 3.3 Multi-Tier Cache (`cache.py`)

Following `HybridEnrichmentCache` pattern with adaptations for IP classification:

```python
"""Multi-tier cache for IP classification results.

Implements 3-tier caching matching cowrieprocessor/enrichment/hybrid_cache.py pattern:
- L1: Redis (in-memory, <1ms, TTL: 1-24h based on IP type)
- L2: Database (enrichment_cache table, <10ms, TTL: 7 days)
- L3: Disk (filesystem sharded by IP octets, <50ms, TTL: 30 days)

Thread Safety:
    This class is thread-safe for read operations. Write operations should be
    serialized externally if needed (database transactions handle DB writes).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from .models import IPClassification, IPType
from ..db_cache import DatabaseCache
from ..hybrid_cache import create_redis_client, ENABLE_REDIS_CACHE

logger = logging.getLogger(__name__)

@dataclass
class IPClassificationCacheStats:
    """Statistics for multi-tier IP classification cache.

    Attributes:
        redis_hits: Cache hits from Redis (L1)
        redis_misses: Cache misses from Redis
        database_hits: Cache hits from database (L2)
        database_misses: Cache misses from database
        disk_hits: Cache hits from disk (L3)
        disk_misses: Cache misses from disk
        stores: Total number of classification results stored
        total_lookups: Total lookup requests
    """

    redis_hits: int = 0
    redis_misses: int = 0
    database_hits: int = 0
    database_misses: int = 0
    disk_hits: int = 0
    disk_misses: int = 0
    stores: int = 0

    @property
    def total_lookups(self) -> int:
        """Total cache lookups across all tiers."""
        return self.redis_hits + self.database_hits + self.disk_hits + self.disk_misses

    @property
    def hit_rate(self) -> float:
        """Overall cache hit rate (0.0 to 1.0)."""
        if self.total_lookups == 0:
            return 0.0
        hits = self.redis_hits + self.database_hits + self.disk_hits
        return hits / self.total_lookups


class HybridIPClassificationCache:
    """Multi-tier cache for IP classification results.

    Cache hierarchy (checked in order):
    1. Redis (L1): Fast in-memory cache with short TTLs
       - TOR: 1 hour (exit nodes change frequently)
       - Cloud: 24 hours (IP ranges change daily)
       - Datacenter: 24 hours (community lists lag)
       - Residential: 24 hours (ASN names stable)

    2. Database (L2): enrichment_cache table
       - Service: "ip_classification"
       - TTL: 7 days (balance freshness vs DB load)

    3. Disk (L3): Filesystem cache sharded by IP octets
       - Path: {cache_dir}/ip_classification/{octet1}/{octet2}/{octet3}/{octet4}.json
       - TTL: 30 days (long-term fallback)

    Example:
        >>> from pathlib import Path
        >>> from sqlalchemy.orm import Session
        >>> from cowrieprocessor.db.engine import get_engine
        >>>
        >>> engine = get_engine("postgresql://...")
        >>> with Session(engine) as session:
        ...     cache = HybridIPClassificationCache(
        ...         cache_dir=Path("/mnt/dshield/data/cache"),
        ...         db_session=session,
        ...         enable_redis=True
        ...     )
        ...
        ...     # Get cached result (checks all 3 tiers)
        ...     classification = cache.get("1.2.3.4")
        ...
        ...     # Store new result (writes to all 3 tiers)
        ...     cache.store("1.2.3.4", IPClassification(...))
    """

    # TTLs per IP type (seconds)
    REDIS_TTLS = {
        IPType.TOR: 3600,           # 1 hour (changes frequently)
        IPType.CLOUD: 86400,        # 24 hours (daily updates)
        IPType.DATACENTER: 86400,   # 24 hours
        IPType.RESIDENTIAL: 86400,  # 24 hours
        IPType.UNKNOWN: 3600,       # 1 hour (may resolve later)
    }

    DATABASE_TTL = 7 * 86400  # 7 days
    DISK_TTL = 30 * 86400     # 30 days

    def __init__(
        self,
        cache_dir: Path,
        db_session: Session,
        enable_redis: bool = ENABLE_REDIS_CACHE,
    ) -> None:
        """Initialize multi-tier IP classification cache.

        Args:
            cache_dir: Base directory for disk cache (L3)
            db_session: Active SQLAlchemy session for database cache (L2)
            enable_redis: Enable Redis cache (L1), default from config

        Example:
            >>> cache = HybridIPClassificationCache(
            ...     cache_dir=Path("/mnt/dshield/data/cache"),
            ...     db_session=session,
            ...     enable_redis=True
            ... )
        """
        self.cache_dir = cache_dir / "ip_classification"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.db_cache = DatabaseCache(db_session.get_bind(), default_ttl=self.DATABASE_TTL)
        self.db_session = db_session

        self.redis_client = create_redis_client() if enable_redis else None
        self.stats = IPClassificationCacheStats()

    def get(self, ip: str) -> Optional[IPClassification]:
        """Retrieve IP classification from cache (3-tier lookup).

        Args:
            ip: IP address string (e.g., "1.2.3.4")

        Returns:
            IPClassification if cached and fresh, None otherwise

        Cache Lookup Order:
            1. Redis (L1): <1ms lookup
            2. Database (L2): <10ms lookup
            3. Disk (L3): <50ms lookup
            If all tiers miss, returns None (caller must classify and store)

        Example:
            >>> result = cache.get("52.0.0.1")
            >>> if result:
            ...     print(f"Cached: {result.ip_type.value} ({result.provider})")
            ... else:
            ...     print("Cache miss - need to classify")
        """
        # L1: Redis (fastest)
        if self.redis_client:
            redis_result = self._get_from_redis(ip)
            if redis_result:
                self.stats.redis_hits += 1
                return redis_result
            self.stats.redis_misses += 1

        # L2: Database
        db_result = self._get_from_database(ip)
        if db_result:
            self.stats.database_hits += 1
            # Populate Redis for future lookups (cache warming)
            if self.redis_client:
                self._store_to_redis(ip, db_result)
            return db_result
        self.stats.database_misses += 1

        # L3: Disk
        disk_result = self._get_from_disk(ip)
        if disk_result:
            self.stats.disk_hits += 1
            # Warm upper cache tiers
            if self.redis_client:
                self._store_to_redis(ip, disk_result)
            self._store_to_database(ip, disk_result)
            return disk_result
        self.stats.disk_misses += 1

        return None  # Complete cache miss

    def store(self, ip: str, classification: IPClassification) -> None:
        """Store IP classification to all cache tiers.

        Args:
            ip: IP address string
            classification: Classification result to cache

        Writes to:
            - Redis (L1): With type-specific TTL
            - Database (L2): With 7-day TTL
            - Disk (L3): With 30-day TTL

        Example:
            >>> classification = IPClassification(
            ...     ip_type=IPType.CLOUD,
            ...     provider="aws",
            ...     confidence=0.99,
            ...     source="cloud_ranges_aws"
            ... )
            >>> cache.store("52.0.0.1", classification)
        """
        self.stats.stores += 1

        # Write to all tiers (async-friendly, no dependencies)
        if self.redis_client:
            self._store_to_redis(ip, classification)

        self._store_to_database(ip, classification)
        self._store_to_disk(ip, classification)

    def get_stats(self) -> IPClassificationCacheStats:
        """Return cache statistics snapshot."""
        return IPClassificationCacheStats(**self.stats.__dict__)

    # --- Private: Redis (L1) ---

    def _redis_key(self, ip: str) -> str:
        """Generate Redis key for IP."""
        return f"ipclass:{ip}"

    def _get_from_redis(self, ip: str) -> Optional[IPClassification]:
        """Get from Redis L1 cache."""
        if not self.redis_client:
            return None

        try:
            key = self._redis_key(ip)
            data = self.redis_client.get(key)
            if not data:
                return None

            return self._deserialize(data.decode('utf-8'))

        except Exception as e:
            logger.warning(f"Redis get failed for {ip}: {e}")
            return None

    def _store_to_redis(self, ip: str, classification: IPClassification) -> None:
        """Store to Redis L1 cache with type-specific TTL."""
        if not self.redis_client:
            return

        try:
            key = self._redis_key(ip)
            value = self._serialize(classification)
            ttl = self.REDIS_TTLS[classification.ip_type]

            self.redis_client.setex(key, ttl, value)

        except Exception as e:
            logger.warning(f"Redis store failed for {ip}: {e}")

    # --- Private: Database (L2) ---

    def _get_from_database(self, ip: str) -> Optional[IPClassification]:
        """Get from Database L2 cache."""
        try:
            data = self.db_cache.get(service="ip_classification", cache_key=ip)
            if not data:
                return None

            return self._deserialize(data)

        except Exception as e:
            logger.warning(f"Database get failed for {ip}: {e}")
            return None

    def _store_to_database(self, ip: str, classification: IPClassification) -> None:
        """Store to Database L2 cache."""
        try:
            data = self._serialize(classification)
            self.db_cache.set(
                service="ip_classification",
                cache_key=ip,
                response_data=data,
                ttl_seconds=self.DATABASE_TTL
            )

        except Exception as e:
            logger.warning(f"Database store failed for {ip}: {e}")

    # --- Private: Disk (L3) ---

    def _disk_path(self, ip: str) -> Path:
        """Generate disk cache path sharded by IP octets.

        Example:
            "1.2.3.4" → {cache_dir}/1/2/3/4.json
        """
        octets = ip.split('.')
        if len(octets) != 4:
            # Fallback to hash-based path for invalid IPs
            digest = hashlib.sha256(ip.encode('utf-8')).hexdigest()[:8]
            return self.cache_dir / "invalid" / f"{digest}.json"

        return self.cache_dir / octets[0] / octets[1] / octets[2] / f"{octets[3]}.json"

    def _get_from_disk(self, ip: str) -> Optional[IPClassification]:
        """Get from Disk L3 cache."""
        try:
            path = self._disk_path(ip)
            if not path.exists():
                return None

            # Check TTL
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            age = datetime.now(timezone.utc) - mtime
            if age > timedelta(seconds=self.DISK_TTL):
                path.unlink()  # Expired, delete
                return None

            data = path.read_text(encoding='utf-8')
            return self._deserialize(data)

        except Exception as e:
            logger.warning(f"Disk get failed for {ip}: {e}")
            return None

    def _store_to_disk(self, ip: str, classification: IPClassification) -> None:
        """Store to Disk L3 cache."""
        try:
            path = self._disk_path(ip)
            path.parent.mkdir(parents=True, exist_ok=True)

            data = self._serialize(classification)
            path.write_text(data, encoding='utf-8')

        except Exception as e:
            logger.warning(f"Disk store failed for {ip}: {e}")

    # --- Private: Serialization ---

    def _serialize(self, classification: IPClassification) -> str:
        """Serialize IPClassification to JSON string."""
        return json.dumps({
            'ip_type': classification.ip_type.value,
            'provider': classification.provider,
            'confidence': classification.confidence,
            'source': classification.source,
            'classified_at': classification.classified_at.isoformat(),
        })

    def _deserialize(self, data: str) -> IPClassification:
        """Deserialize JSON string to IPClassification."""
        obj = json.loads(data)
        return IPClassification(
            ip_type=IPType(obj['ip_type']),
            provider=obj['provider'],
            confidence=obj['confidence'],
            source=obj['source'],
            classified_at=datetime.fromisoformat(obj['classified_at']),
        )

    def close(self) -> None:
        """Close cache connections (Redis, Database)."""
        if self.redis_client:
            self.redis_client.close()
        self.db_cache.close()

    def __enter__(self) -> HybridIPClassificationCache:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
```

---

### 3.4 IPClassifier Service (`classifier.py`)

Main service orchestrating matchers and cache:

```python
"""IP classification service with multi-tier caching.

This module provides the main IPClassifier service that coordinates IP range matchers,
multi-tier caching, and classification logic following ADR-007 (Three-Tier Enrichment).

Example:
    >>> from pathlib import Path
    >>> from sqlalchemy.orm import Session
    >>> from cowrieprocessor.db.engine import get_engine
    >>>
    >>> engine = get_engine("postgresql://...")
    >>> with Session(engine) as session:
    ...     classifier = IPClassifier(
    ...         cache_dir=Path("/mnt/dshield/data/cache"),
    ...         db_session=session,
    ...         enable_redis=True
    ...     )
    ...
    ...     # Classify single IP
    ...     result = classifier.classify("52.0.0.1", asn=16509, as_name="AMAZON-02")
    ...     print(f"{result.ip_type.value}: {result.provider}")
    ...
    ...     # Bulk classify
    ...     results = classifier.bulk_classify([
    ...         ("1.2.3.4", None, None),
    ...         ("8.8.8.8", 15169, "GOOGLE"),
    ...     ])
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from .cache import HybridIPClassificationCache
from .matchers import (
    TorExitNodeMatcher,
    CloudProviderMatcher,
    DatacenterMatcher,
    ResidentialHeuristic,
)
from .models import IPClassification, IPType

logger = logging.getLogger(__name__)


class IPClassifier:
    """Main IP classification service with multi-tier caching.

    Classifies IPs into infrastructure categories using priority-ordered matchers:
    1. TOR Exit Nodes (95%+ accuracy, official Tor Project data)
    2. Cloud Providers (99%+ accuracy, official AWS/Azure/GCP/CloudFlare ranges)
    3. Datacenters (70-80% accuracy, community-maintained hosting lists)
    4. Residential (70-80% accuracy, ASN name heuristics)
    5. Unknown (fallback when no match)

    Thread Safety:
        This class is thread-safe for read operations. Write operations (cache stores)
        are thread-safe via database transactions. Matcher updates should be serialized
        externally (cron jobs).

    Performance:
        - Cached lookups: <1ms (Redis L1)
        - Uncached lookups: <10ms (PyTricia CIDR trees + heuristics)
        - Bulk classify (1000 IPs): <1s (parallel classification)

    Example:
        >>> classifier = IPClassifier(
        ...     cache_dir=Path("/mnt/dshield/data/cache"),
        ...     db_session=session,
        ...     enable_redis=True
        ... )
        >>> result = classifier.classify("1.2.3.4")
        >>> print(f"{result.ip_type.value} ({result.confidence:.2f})")
    """

    def __init__(
        self,
        cache_dir: Path,
        db_session: Session,
        enable_redis: bool = True,
        tor_url: str = "https://check.torproject.org/torbulkexitlist",
        cloud_base_url: str = "https://raw.githubusercontent.com/rezmoss/cloud-provider-ip-addresses/main",
        datacenter_url: str = "https://raw.githubusercontent.com/jhassine/server-ip-addresses/main/data/datacenters.csv",
    ) -> None:
        """Initialize IP classifier with all matchers and cache.

        Args:
            cache_dir: Base directory for disk cache (L3)
            db_session: Active SQLAlchemy session for database cache (L2)
            enable_redis: Enable Redis cache (L1), default True
            tor_url: URL for TOR exit node list (default: Tor Project bulk list)
            cloud_base_url: Base URL for cloud provider IP ranges (default: rezmoss/GitHub)
            datacenter_url: URL for datacenter IP ranges (default: jhassine/GitHub)

        Example:
            >>> from pathlib import Path
            >>> from sqlalchemy.orm import Session
            >>>
            >>> classifier = IPClassifier(
            ...     cache_dir=Path("/mnt/dshield/data/cache"),
            ...     db_session=session
            ... )
        """
        # Initialize cache
        self.cache = HybridIPClassificationCache(
            cache_dir=cache_dir,
            db_session=db_session,
            enable_redis=enable_redis,
        )

        # Initialize matchers (lazy-loaded on first use for startup performance)
        self.tor_matcher = TorExitNodeMatcher(bulk_list_url=tor_url)
        self.cloud_matcher = CloudProviderMatcher(base_url=cloud_base_url)
        self.datacenter_matcher = DatacenterMatcher(ranges_url=datacenter_url)
        self.residential_heuristic = ResidentialHeuristic()

        self._stats = {
            'classifications': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'tor_matches': 0,
            'cloud_matches': 0,
            'datacenter_matches': 0,
            'residential_matches': 0,
            'unknown_matches': 0,
        }

    def classify(
        self,
        ip: str,
        asn: Optional[int] = None,
        as_name: Optional[str] = None,
    ) -> IPClassification:
        """Classify an IP address into infrastructure category.

        Classification Pipeline (priority order):
        1. Check cache (3-tier: Redis → Database → Disk)
        2. TOR exit node check (highest confidence)
        3. Cloud provider match (AWS, Azure, GCP, CloudFlare)
        4. Datacenter/hosting match (community lists)
        5. Residential heuristic (ASN name patterns)
        6. Unknown fallback

        Args:
            ip: IP address string (e.g., "1.2.3.4")
            asn: Optional ASN number for heuristic classification
            as_name: Optional AS name for heuristic classification

        Returns:
            IPClassification with type, provider, confidence, and source

        Example:
            >>> result = classifier.classify("52.0.0.1", asn=16509, as_name="AMAZON-02")
            >>> print(f"{result.ip_type.value}: {result.provider} ({result.confidence})")
            cloud: aws (0.99)
        """
        self._stats['classifications'] += 1

        # Priority 1: Check cache (all 3 tiers)
        cached = self.cache.get(ip)
        if cached:
            self._stats['cache_hits'] += 1
            return cached

        self._stats['cache_misses'] += 1

        # Priority 2: TOR (highest confidence, official data)
        tor_match = self.tor_matcher.match(ip)
        if tor_match:
            self._stats['tor_matches'] += 1
            classification = IPClassification(
                ip_type=IPType.TOR,
                provider="tor",
                confidence=0.95,
                source="tor_bulk_list",
            )
            self.cache.store(ip, classification)
            return classification

        # Priority 3: Cloud providers (high confidence, official ranges)
        cloud_match = self.cloud_matcher.match(ip)
        if cloud_match:
            self._stats['cloud_matches'] += 1
            classification = IPClassification(
                ip_type=IPType.CLOUD,
                provider=cloud_match['provider'],
                confidence=0.99,
                source=f"cloud_ranges_{cloud_match['provider']}",
            )
            self.cache.store(ip, classification)
            return classification

        # Priority 4: Datacenters (medium confidence, community lists)
        datacenter_match = self.datacenter_matcher.match(ip)
        if datacenter_match:
            self._stats['datacenter_matches'] += 1
            classification = IPClassification(
                ip_type=IPType.DATACENTER,
                provider=datacenter_match.get('provider'),
                confidence=0.75,
                source="datacenter_community_lists",
            )
            self.cache.store(ip, classification)
            return classification

        # Priority 5: Residential heuristic (low-medium confidence)
        if asn and as_name and self.residential_heuristic.is_residential(as_name):
            self._stats['residential_matches'] += 1
            classification = IPClassification(
                ip_type=IPType.RESIDENTIAL,
                provider=as_name,
                confidence=0.70,
                source="asn_name_heuristic",
            )
            self.cache.store(ip, classification)
            return classification

        # Priority 6: Unknown (fallback)
        self._stats['unknown_matches'] += 1
        classification = IPClassification(
            ip_type=IPType.UNKNOWN,
            provider=None,
            confidence=0.0,
            source="none",
        )
        # Cache for 1 hour (may resolve later with updates)
        self.cache.store(ip, classification)
        return classification

    def bulk_classify(
        self,
        ips: list[tuple[str, Optional[int], Optional[str]]],
    ) -> dict[str, IPClassification]:
        """Classify multiple IPs in batch for efficiency.

        Args:
            ips: List of (ip, asn, as_name) tuples

        Returns:
            Dictionary mapping IP to IPClassification

        Example:
            >>> results = classifier.bulk_classify([
            ...     ("1.2.3.4", None, None),
            ...     ("52.0.0.1", 16509, "AMAZON-02"),
            ...     ("8.8.8.8", 15169, "GOOGLE"),
            ... ])
            >>> for ip, classification in results.items():
            ...     print(f"{ip}: {classification.ip_type.value}")
        """
        results = {}
        for ip, asn, as_name in ips:
            results[ip] = self.classify(ip, asn, as_name)
        return results

    def update_all_sources(self) -> None:
        """Update all data sources (TOR, Cloud, Datacenter).

        Should be called by cron jobs:
        - TOR: Hourly
        - Cloud: Daily
        - Datacenter: Weekly

        Raises:
            requests.RequestException: If any update fails
        """
        logger.info("Updating all IP classification data sources...")

        self.tor_matcher.update()
        self.cloud_matcher.update()
        self.datacenter_matcher.update()

        logger.info("All data sources updated successfully")

    def get_stats(self) -> dict[str, int]:
        """Return classifier statistics.

        Returns:
            Statistics dict with keys:
            - classifications: Total classification requests
            - cache_hits: Cache hits across all tiers
            - cache_misses: Complete cache misses
            - tor_matches: IPs classified as TOR
            - cloud_matches: IPs classified as cloud
            - datacenter_matches: IPs classified as datacenter
            - residential_matches: IPs classified as residential
            - unknown_matches: IPs classified as unknown

        Example:
            >>> stats = classifier.get_stats()
            >>> hit_rate = stats['cache_hits'] / stats['classifications']
            >>> print(f"Cache hit rate: {hit_rate:.2%}")
        """
        return dict(self._stats)

    def close(self) -> None:
        """Close cache connections and cleanup resources."""
        self.cache.close()

    def __enter__(self) -> IPClassifier:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
```

---

## 4. Integration Points

### 4.1 CascadeEnricher Integration (Pass 4)

**File**: `cowrieprocessor/enrichment/cascade_enricher.py`

**Modification**:

```python
class CascadeEnricher:
    def __init__(
        self,
        maxmind: MaxMindClient,
        cymru: CymruClient,
        greynoise: GreyNoiseClient,
        ip_classifier: IPClassifier,  # NEW parameter
        session: Session,
    ) -> None:
        """Initialize cascade enricher with all clients and database session.

        Args:
            maxmind: MaxMind GeoLite2 client (offline database lookups)
            cymru: Team Cymru client (online whois lookups)
            greynoise: GreyNoise Community API client (online scanner checks)
            ip_classifier: IP classification service (infrastructure types)  # NEW
            session: Active SQLAlchemy session for database operations
        """
        self.maxmind = maxmind
        self.cymru = cymru
        self.greynoise = greynoise
        self.ip_classifier = ip_classifier  # NEW
        self.session = session
        self._stats = CascadeStats()

    def refresh_stale_data(
        self,
        ip_inventory_record: IPInventory,
        force_refresh: bool = False,
    ) -> None:
        """Refresh stale enrichment data through 4-pass cascade.

        Pass 1: MaxMind GeoIP (offline, always fresh)
        Pass 2: Team Cymru ASN (online, batched, 30-90 day TTL)
        Pass 3: GreyNoise (online, 7-14 day TTL)
        Pass 4: IP Classification (mixed, type-specific TTLs)  # NEW

        Args:
            ip_inventory_record: IP inventory record to enrich
            force_refresh: Force refresh even if data is fresh

        Example:
            >>> enricher = CascadeEnricher(...)
            >>> ip_record = session.query(IPInventory).filter_by(ip_address="1.2.3.4").first()
            >>> enricher.refresh_stale_data(ip_record)
            >>> print(ip_record.enrichment['ip_type'])  # "cloud"
        """
        ip_address = ip_inventory_record.ip_address
        enrichment = ip_inventory_record.enrichment or {}

        # Pass 1: MaxMind GeoIP (always fresh, offline)
        self._enrich_pass1_maxmind(ip_address, enrichment)

        # Pass 2: Team Cymru ASN (if stale or missing)
        if self._is_stale(enrichment, 'cymru', ttl_days=30) or force_refresh:
            self._enrich_pass2_cymru(ip_address, enrichment)

        # Pass 3: GreyNoise (if stale or missing)
        if self._is_stale(enrichment, 'greynoise', ttl_days=7) or force_refresh:
            self._enrich_pass3_greynoise(ip_address, enrichment)

        # Pass 4: IP Classification (if stale or missing)  # NEW
        if self._is_stale(enrichment, 'ip_classification', ttl_days=1) or force_refresh:
            self._enrich_pass4_ip_classification(ip_address, enrichment)

        # Update database record
        ip_inventory_record.enrichment = enrichment
        ip_inventory_record.enrichment_at = datetime.now(timezone.utc)

    def _enrich_pass4_ip_classification(
        self,
        ip_address: str,
        enrichment: dict,
    ) -> None:
        """Pass 4: IP infrastructure classification.

        Uses IPClassifier service to determine infrastructure type
        (TOR, Cloud, Datacenter, Residential, Unknown).

        Args:
            ip_address: IP to classify
            enrichment: Enrichment dict to update (modified in-place)

        Side Effects:
            Updates enrichment dict with:
            - enrichment['ip_classification']['ip_type']: str
            - enrichment['ip_classification']['provider']: Optional[str]
            - enrichment['ip_classification']['confidence']: float
            - enrichment['ip_classification']['source']: str
            - enrichment['ip_classification']['classified_at']: str (ISO 8601)
        """
        try:
            # Get ASN data from Pass 2 for heuristic classification
            asn = enrichment.get('cymru', {}).get('asn')
            as_name = enrichment.get('cymru', {}).get('as_name')

            # Classify IP
            classification = self.ip_classifier.classify(
                ip=ip_address,
                asn=asn,
                as_name=as_name,
            )

            # Store in enrichment dict
            enrichment['ip_classification'] = {
                'ip_type': classification.ip_type.value,
                'provider': classification.provider,
                'confidence': classification.confidence,
                'source': classification.source,
                'classified_at': classification.classified_at.isoformat(),
            }

            self._stats.pass4_classifications += 1

        except Exception as e:
            logger.error(f"IP classification failed for {ip_address}: {e}")
            self._stats.pass4_errors += 1
            # Don't re-raise - graceful degradation (missing ip_type is acceptable)
```

---

### 4.2 Factory Function (`factory.py`)

**File**: `cowrieprocessor/enrichment/ip_classification/factory.py`

```python
"""Factory function for creating IPClassifier with proper dependency injection."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from .classifier import IPClassifier

logger = logging.getLogger(__name__)


def create_ip_classifier(
    cache_dir: Path,
    db_session: Session,
    enable_redis: bool = True,
    tor_url: Optional[str] = None,
    cloud_base_url: Optional[str] = None,
    datacenter_url: Optional[str] = None,
) -> IPClassifier:
    """Create fully initialized IPClassifier service.

    Args:
        cache_dir: Base directory for disk cache (L3)
        db_session: Active SQLAlchemy session for database cache (L2)
        enable_redis: Enable Redis cache (L1), default True
        tor_url: Optional custom TOR exit node list URL
        cloud_base_url: Optional custom cloud provider IP ranges URL
        datacenter_url: Optional custom datacenter IP ranges URL

    Returns:
        IPClassifier instance ready for use

    Example:
        >>> from pathlib import Path
        >>> from sqlalchemy.orm import Session
        >>> from cowrieprocessor.db.engine import get_engine
        >>>
        >>> engine = get_engine("postgresql://...")
        >>> with Session(engine) as session:
        ...     classifier = create_ip_classifier(
        ...         cache_dir=Path("/mnt/dshield/data/cache"),
        ...         db_session=session
        ...     )
        ...     result = classifier.classify("1.2.3.4")
    """
    classifier = IPClassifier(
        cache_dir=cache_dir,
        db_session=db_session,
        enable_redis=enable_redis,
        tor_url=tor_url or "https://check.torproject.org/torbulkexitlist",
        cloud_base_url=cloud_base_url or "https://raw.githubusercontent.com/rezmoss/cloud-provider-ip-addresses/main",
        datacenter_url=datacenter_url or "https://raw.githubusercontent.com/jhassine/server-ip-addresses/main/data/datacenters.csv",
    )

    logger.info("IPClassifier initialized successfully")
    return classifier
```

---

### 4.3 Cascade Factory Integration

**File**: `cowrieprocessor/enrichment/cascade_factory.py`

**Modification**:

```python
def create_cascade_enricher(
    cache_dir: Path,
    db_session: Session,
    config: dict,
    maxmind_license_key: str,
    enable_greynoise: bool = True,
    enable_redis: bool = True,  # NEW parameter
) -> CascadeEnricher:
    """Create fully initialized CascadeEnricher with all dependencies.

    Args:
        cache_dir: Base directory for enrichment caches
        db_session: Active SQLAlchemy session
        config: Configuration dict with API keys (secrets resolver URIs)
        maxmind_license_key: MaxMind license key (secrets resolver URI)
        enable_greynoise: Enable GreyNoise API (default True)
        enable_redis: Enable Redis cache for IP classifier (default True)  # NEW

    Returns:
        CascadeEnricher instance with all clients wired

    Example:
        >>> engine = get_engine("postgresql://...")
        >>> with Session(engine) as session:
        ...     cascade = create_cascade_enricher(
        ...         cache_dir=Path("/mnt/dshield/data/cache"),
        ...         db_session=session,
        ...         config={'greynoise_api': 'env:GREYNOISE_API_KEY'},
        ...         maxmind_license_key="env:MAXMIND_LICENSE_KEY",
        ...         enable_redis=True
        ...     )
    """
    # Initialize MaxMind (Pass 1)
    maxmind = MaxMindClient(...)

    # Initialize Cymru (Pass 2)
    cymru = CymruClient(...)

    # Initialize GreyNoise (Pass 3)
    if enable_greynoise:
        greynoise = GreyNoiseClient(...)
    else:
        greynoise = MockGreyNoiseClient()

    # Initialize IP Classifier (Pass 4)  # NEW
    ip_classifier = create_ip_classifier(
        cache_dir=cache_dir,
        db_session=db_session,
        enable_redis=enable_redis,
    )

    # Wire all dependencies into CascadeEnricher
    return CascadeEnricher(
        maxmind=maxmind,
        cymru=cymru,
        greynoise=greynoise,
        ip_classifier=ip_classifier,  # NEW parameter
        session=db_session,
    )
```

---

## 5. Testing Strategy

### 5.1 Unit Tests (95% Coverage Target)

**File**: `tests/unit/enrichment/test_ip_classifier.py`

```python
import pytest
from cowrieprocessor.enrichment.ip_classification import IPClassifier, IPType

class TestIPClassifier:
    """Unit tests for IPClassifier service."""

    def test_tor_classification(self, mock_tor_matcher, test_db_session):
        """Test TOR exit node classification."""
        mock_tor_matcher.match.return_value = {'provider': 'tor'}

        classifier = IPClassifier(
            cache_dir=Path("/tmp/test_cache"),
            db_session=test_db_session
        )
        classifier.tor_matcher = mock_tor_matcher

        result = classifier.classify("1.2.3.4")

        assert result.ip_type == IPType.TOR
        assert result.provider == "tor"
        assert result.confidence == 0.95
        assert result.source == "tor_bulk_list"

    def test_cloud_classification_aws(self, mock_cloud_matcher, test_db_session):
        """Test AWS cloud classification."""
        mock_cloud_matcher.match.return_value = {
            'provider': 'aws',
            'region': 'us-east-1',
            'service': 'ec2'
        }

        classifier = IPClassifier(
            cache_dir=Path("/tmp/test_cache"),
            db_session=test_db_session
        )
        classifier.cloud_matcher = mock_cloud_matcher

        result = classifier.classify("52.0.0.1")

        assert result.ip_type == IPType.CLOUD
        assert result.provider == "aws"
        assert result.confidence == 0.99

    def test_residential_heuristic(self, test_db_session):
        """Test residential classification via ASN name heuristic."""
        classifier = IPClassifier(
            cache_dir=Path("/tmp/test_cache"),
            db_session=test_db_session
        )

        result = classifier.classify("1.2.3.4", asn=7922, as_name="Comcast Cable")

        assert result.ip_type == IPType.RESIDENTIAL
        assert result.provider == "Comcast Cable"
        assert result.confidence == 0.70
        assert result.source == "asn_name_heuristic"

    def test_unknown_fallback(self, test_db_session):
        """Test unknown classification when no match."""
        classifier = IPClassifier(
            cache_dir=Path("/tmp/test_cache"),
            db_session=test_db_session
        )

        result = classifier.classify("1.2.3.4")  # No ASN data, no matches

        assert result.ip_type == IPType.UNKNOWN
        assert result.provider is None
        assert result.confidence == 0.0

    def test_cache_hit(self, test_db_session):
        """Test cache hit returns cached result."""
        classifier = IPClassifier(
            cache_dir=Path("/tmp/test_cache"),
            db_session=test_db_session
        )

        # First call: cache miss
        result1 = classifier.classify("52.0.0.1", asn=16509, as_name="AMAZON-02")

        # Second call: cache hit
        result2 = classifier.classify("52.0.0.1")

        assert result1.ip_type == result2.ip_type
        assert classifier._stats['cache_hits'] == 1
```

### 5.2 Integration Tests

**File**: `tests/integration/enrichment/test_cascade_with_ip_classifier.py`

```python
def test_cascade_enricher_with_ip_classification(live_db_session):
    """Test CascadeEnricher Pass 4 (IP classification) integration."""
    cascade = create_cascade_enricher(
        cache_dir=Path("/tmp/test_cache"),
        db_session=live_db_session,
        config={},
        maxmind_license_key="test",
        enable_redis=False
    )

    # Create IP inventory record
    ip_record = IPInventory(ip_address="52.0.0.1")
    live_db_session.add(ip_record)
    live_db_session.commit()

    # Enrich through cascade
    cascade.refresh_stale_data(ip_record)

    # Verify Pass 4 ran
    assert 'ip_classification' in ip_record.enrichment
    assert ip_record.enrichment['ip_classification']['ip_type'] in [
        'tor', 'cloud', 'datacenter', 'residential', 'unknown'
    ]
```

---

## 6. Performance Characteristics

| Operation | Latency (p50) | Latency (p99) | Notes |
|-----------|---------------|---------------|-------|
| Classify (Redis hit) | <1ms | <2ms | L1 cache, in-memory |
| Classify (DB hit) | <5ms | <15ms | L2 cache, database query |
| Classify (Disk hit) | <20ms | <60ms | L3 cache, filesystem read |
| Classify (uncached) | <8ms | <20ms | PyTricia CIDR lookup + heuristic |
| Bulk classify (1000 IPs, 95% cached) | ~100ms | ~300ms | Mostly cache hits |
| TOR list update | ~2s | ~5s | 8,000 IPs download |
| Cloud ranges update | ~5s | ~10s | 20,000 CIDRs download |
| Datacenter list update | ~3s | ~8s | 10,000 CIDRs download |

---

## 7. Deployment Checklist

### 7.1 Prerequisites
- [ ] PostgreSQL database (for L2 cache)
- [ ] Redis server (for L1 cache, optional but recommended)
- [ ] Disk space: 500MB for cache + 100MB for data sources
- [ ] Network access: GitHub (cloud/datacenter lists), Tor Project (exit nodes)

### 7.2 Installation
- [ ] Install Python dependencies: `pytricia`, `requests`
- [ ] Create cache directory: `/mnt/dshield/data/cache/ip_classification`
- [ ] Configure Redis connection (if enabled)
- [ ] Run initial data source updates

### 7.3 Cron Jobs
```bash
# /etc/cron.d/ip-classifier-updates

# TOR exit nodes (hourly)
0 * * * * /usr/local/bin/uv run python -m cowrieprocessor.enrichment.ip_classification.updaters tor

# Cloud provider ranges (daily at 2 AM)
0 2 * * * /usr/local/bin/uv run python -m cowrieprocessor.enrichment.ip_classification.updaters cloud

# Datacenter ranges (weekly on Sunday at 3 AM)
0 3 * * 0 /usr/local/bin/uv run python -m cowrieprocessor.enrichment.ip_classification.updaters datacenter
```

### 7.4 Monitoring
- [ ] Cache hit rate >95% (after warmup)
- [ ] Classification latency p99 <20ms
- [ ] Data source update success rate 100%
- [ ] Redis connection health
- [ ] Disk cache size <1GB

---

## 8. API Documentation

See autogenerated Sphinx docs:
- `IPClassifier` - Main service API
- `IPClassification` - Result data model
- `IPType` - Infrastructure type enum
- `HybridIPClassificationCache` - Multi-tier cache API

---

## 9. References

### 9.1 Internal Documentation
- ADR-007: Three-Tier Enrichment Architecture
- ADR-008: Rate Limiting and API Quota Management
- `docs/brainstorming/infrastructure_enrichment_free_sources.md`
- `docs/brainstorming/ip_classifier_architecture.md`

### 9.2 External Data Sources
- Tor Project Bulk Exit List: https://check.torproject.org/torbulkexitlist
- rezmoss/cloud-provider-ip-addresses: https://github.com/rezmoss/cloud-provider-ip-addresses
- jhassine/server-ip-addresses: https://github.com/jhassine/server-ip-addresses

---

**Status**: DESIGN COMPLETE ✅
**Next Phase**: Implementation (Week 1-2)
**Approver**: TBD
**Review Date**: 2025-11-10
