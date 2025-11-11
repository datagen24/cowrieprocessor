# IP Classifier Service - Architecture Design

**Date**: 2025-11-10
**Purpose**: Technical architecture for free IP infrastructure classification
**Target**: Populate `snapshot_ip_type` with 90%+ coverage

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    IP Classifier Service                         │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │             Classification Pipeline                       │  │
│  │                                                            │  │
│  │   1. TOR Exit Node Check                                  │  │
│  │   2. Cloud Provider Match (AWS/Azure/GCP/CloudFlare)     │  │
│  │   3. Datacenter/Hosting Match                             │  │
│  │   4. Residential Heuristic (ASN name patterns)            │  │
│  │   5. Unknown (fallback)                                   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Data Sources (All FREE)                      │  │
│  │                                                            │  │
│  │  • Tor Project Bulk Exit List (hourly)                    │  │
│  │  • rezmoss/cloud-provider-ip-addresses (daily)            │  │
│  │  • jhassine/server-ip-addresses (daily)                   │  │
│  │  • client9/ipcat (weekly)                                 │  │
│  │  • ASN name heuristics (static patterns)                  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │           Cache Layer (Fast Lookup)                       │  │
│  │                                                            │  │
│  │  Development: SQLite (ip_classification_cache table)      │  │
│  │  Production:  Redis (in-memory, TTL-based)                │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         │                        │                        │
         ▼                        ▼                        ▼
   ┌─────────┐            ┌──────────────┐        ┌──────────────┐
   │ bulk.py │            │ enricher.py  │        │ backfill.py  │
   │ (loader)│            │ (real-time)  │        │ (historical) │
   └─────────┘            └──────────────┘        └──────────────┘
```

---

## 📦 Component Design

### 1. IPClassifier (Main Service)

**File**: `cowrieprocessor/enrichment/ip_classifier.py`

```python
from dataclasses import dataclass
from enum import Enum
from ipaddress import IPv4Address, IPv4Network
from typing import Optional

class IPType(Enum):
    """IP infrastructure classification types."""
    TOR = "tor"
    CLOUD = "cloud"
    DATACENTER = "datacenter"
    RESIDENTIAL = "residential"
    UNKNOWN = "unknown"

@dataclass
class IPClassification:
    """Result of IP classification."""
    ip_type: IPType
    provider: Optional[str]  # e.g., "aws", "azure", "gcp", "tor", AS name
    confidence: float  # 0.0 to 1.0
    source: str  # Data source used for classification

class IPClassifier:
    """Classify IPs into infrastructure categories using free data sources."""

    def __init__(
        self,
        cache_backend: str = "sqlite",  # "sqlite" or "redis"
        tor_list_url: str = "https://check.torproject.org/torbulkexitlist",
        cloud_ranges_url_base: str = "https://raw.githubusercontent.com/rezmoss/cloud-provider-ip-addresses/main",
        datacenter_ranges_url: str = "https://raw.githubusercontent.com/jhassine/server-ip-addresses/main/data/datacenters.csv",
        update_interval_hours: int = 24,
    ):
        """Initialize classifier with data sources and cache."""
        self.cache_backend = cache_backend
        self.tor_checker = TorExitNodeChecker(tor_list_url)
        self.cloud_matcher = CloudProviderMatcher(cloud_ranges_url_base)
        self.datacenter_matcher = DatacenterMatcher(datacenter_ranges_url)
        self.residential_heuristic = ResidentialHeuristic()
        self.cache = self._init_cache(cache_backend)

    def classify(self, ip: str, asn: Optional[int] = None, as_name: Optional[str] = None) -> IPClassification:
        """Classify an IP address into infrastructure category.

        Args:
            ip: IP address to classify (string format)
            asn: Optional ASN number for heuristic classification
            as_name: Optional AS name for heuristic classification

        Returns:
            IPClassification with type, provider, confidence, and source

        Example:
            >>> classifier = IPClassifier()
            >>> result = classifier.classify("1.2.3.4", asn=15169, as_name="GOOGLE")
            >>> print(result.ip_type, result.confidence)
            IPType.CLOUD 0.99
        """
        # 1. Check cache first (fast path)
        cached = self.cache.get(ip)
        if cached and not self._is_stale(cached):
            return cached

        # 2. Classification pipeline (priority order)

        # Priority 1: TOR (highest confidence)
        if self.tor_checker.is_tor_exit(ip):
            result = IPClassification(
                ip_type=IPType.TOR,
                provider="tor",
                confidence=0.95,
                source="tor_project_bulk_list"
            )
            self.cache.set(ip, result, ttl=3600)  # 1 hour
            return result

        # Priority 2: Cloud providers (high confidence)
        cloud_match = self.cloud_matcher.match(ip)
        if cloud_match:
            result = IPClassification(
                ip_type=IPType.CLOUD,
                provider=cloud_match.provider,  # "aws", "azure", "gcp", "cloudflare"
                confidence=0.99,
                source=f"cloud_ranges_{cloud_match.provider}"
            )
            self.cache.set(ip, result, ttl=86400)  # 24 hours
            return result

        # Priority 3: Datacenter/Hosting (medium confidence)
        datacenter_match = self.datacenter_matcher.match(ip)
        if datacenter_match:
            result = IPClassification(
                ip_type=IPType.DATACENTER,
                provider=datacenter_match.provider,
                confidence=0.75,
                source="datacenter_community_lists"
            )
            self.cache.set(ip, result, ttl=86400)  # 24 hours
            return result

        # Priority 4: Residential heuristic (low-medium confidence)
        if asn and as_name:
            if self.residential_heuristic.is_residential(as_name):
                result = IPClassification(
                    ip_type=IPType.RESIDENTIAL,
                    provider=as_name,
                    confidence=0.70,
                    source="asn_name_heuristic"
                )
                self.cache.set(ip, result, ttl=86400)  # 24 hours
                return result

        # Priority 5: Unknown (fallback)
        result = IPClassification(
            ip_type=IPType.UNKNOWN,
            provider=None,
            confidence=0.0,
            source="none"
        )
        self.cache.set(ip, result, ttl=3600)  # 1 hour (may resolve later)
        return result

    def bulk_classify(self, ips: list[tuple[str, Optional[int], Optional[str]]]) -> dict[str, IPClassification]:
        """Classify multiple IPs in batch for efficiency.

        Args:
            ips: List of (ip, asn, as_name) tuples

        Returns:
            Dictionary mapping IP to IPClassification
        """
        results = {}
        for ip, asn, as_name in ips:
            results[ip] = self.classify(ip, asn, as_name)
        return results
```

---

### 2. TorExitNodeChecker

**File**: `cowrieprocessor/enrichment/tor_checker.py`

```python
class TorExitNodeChecker:
    """Check if IP is a TOR exit node using official Tor Project data."""

    def __init__(self, bulk_list_url: str):
        self.bulk_list_url = bulk_list_url
        self.exit_nodes: set[str] = set()
        self.last_update: Optional[datetime] = None
        self.update_interval = timedelta(hours=1)  # Hourly updates

    def is_tor_exit(self, ip: str) -> bool:
        """Check if IP is in TOR exit node list."""
        self._maybe_update()
        return ip in self.exit_nodes

    def _maybe_update(self) -> None:
        """Update list if stale (>1 hour old)."""
        if self.last_update is None or datetime.now() - self.last_update > self.update_interval:
            self._download_exit_nodes()

    def _download_exit_nodes(self) -> None:
        """Download latest TOR exit node list from Tor Project."""
        try:
            response = requests.get(self.bulk_list_url, timeout=30)
            response.raise_for_status()
            self.exit_nodes = set(response.text.strip().splitlines())
            self.last_update = datetime.now()
            logger.info(f"Updated TOR exit nodes: {len(self.exit_nodes)} nodes")
        except Exception as e:
            logger.error(f"Failed to update TOR exit nodes: {e}")
            # Keep existing list if update fails
```

---

### 3. CloudProviderMatcher

**File**: `cowrieprocessor/enrichment/cloud_matcher.py`

```python
@dataclass
class CloudMatch:
    provider: str  # "aws", "azure", "gcp", "cloudflare"
    region: Optional[str]
    service: Optional[str]

class CloudProviderMatcher:
    """Match IPs to cloud provider ranges (AWS, Azure, GCP, CloudFlare)."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.providers = {
            "aws": PyTricia(),     # Prefix tree for fast CIDR matching
            "azure": PyTricia(),
            "gcp": PyTricia(),
            "cloudflare": PyTricia(),
        }
        self.last_update: Optional[datetime] = None
        self.update_interval = timedelta(hours=24)  # Daily updates

    def match(self, ip: str) -> Optional[CloudMatch]:
        """Match IP to cloud provider range."""
        self._maybe_update()

        for provider, trie in self.providers.items():
            if ip in trie:
                metadata = trie[ip]
                return CloudMatch(
                    provider=provider,
                    region=metadata.get("region"),
                    service=metadata.get("service")
                )
        return None

    def _download_ranges(self, provider: str) -> list[dict]:
        """Download IP ranges for a specific provider."""
        url = f"{self.base_url}/{provider}/ipv4.csv"
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        # Parse CSV: ip_prefix,region,service
        ranges = []
        for line in response.text.strip().splitlines()[1:]:  # Skip header
            parts = line.split(',')
            if len(parts) >= 3:
                ranges.append({
                    "prefix": parts[0],
                    "region": parts[1],
                    "service": parts[2]
                })
        return ranges

    def _update_provider(self, provider: str) -> None:
        """Update ranges for a single provider."""
        try:
            ranges = self._download_ranges(provider)
            trie = PyTricia()
            for r in ranges:
                trie[r["prefix"]] = {"region": r["region"], "service": r["service"]}
            self.providers[provider] = trie
            logger.info(f"Updated {provider} ranges: {len(ranges)} CIDRs")
        except Exception as e:
            logger.error(f"Failed to update {provider} ranges: {e}")
```

---

### 4. DatacenterMatcher

**File**: `cowrieprocessor/enrichment/datacenter_matcher.py`

```python
class DatacenterMatcher:
    """Match IPs to datacenter/hosting provider ranges."""

    def __init__(self, ranges_url: str):
        self.ranges_url = ranges_url
        self.datacenter_trie = PyTricia()
        self.last_update: Optional[datetime] = None
        self.update_interval = timedelta(days=7)  # Weekly updates

    def match(self, ip: str) -> Optional[dict]:
        """Match IP to datacenter range."""
        self._maybe_update()

        if ip in self.datacenter_trie:
            return self.datacenter_trie[ip]
        return None
```

---

### 5. ResidentialHeuristic

**File**: `cowrieprocessor/enrichment/residential_heuristic.py`

```python
class ResidentialHeuristic:
    """Heuristic classification of residential IPs based on ASN name patterns."""

    RESIDENTIAL_PATTERNS = [
        r"telecom",
        r"broadband",
        r"mobile",
        r"wireless",
        r"cable",
        r"dsl",
        r"fiber",
        r"internet service",
        r"\bisp\b",
    ]

    DATACENTER_PATTERNS = [
        r"hosting",
        r"datacenter",
        r"data center",
        r"server",
        r"cloud",
        r"colocation",
        r"colo",
        r"vps",
        r"dedicated",
    ]

    def __init__(self):
        self.residential_regex = re.compile("|".join(self.RESIDENTIAL_PATTERNS), re.IGNORECASE)
        self.datacenter_regex = re.compile("|".join(self.DATACENTER_PATTERNS), re.IGNORECASE)

    def is_residential(self, as_name: str) -> bool:
        """Check if ASN name indicates residential network."""
        if not as_name:
            return False

        # Exclude datacenter patterns first (higher priority)
        if self.datacenter_regex.search(as_name):
            return False

        # Match residential patterns
        return bool(self.residential_regex.search(as_name))
```

---

## 🔄 Data Update Pipeline

### Cron Schedule

```bash
# /etc/cron.d/ip-classifier-updates

# TOR exit nodes (hourly)
0 * * * * /usr/local/bin/uv run python -m cowrieprocessor.enrichment.update_tor_nodes

# Cloud provider ranges (daily at 2 AM)
0 2 * * * /usr/local/bin/uv run python -m cowrieprocessor.enrichment.update_cloud_ranges

# Datacenter ranges (weekly on Sunday at 3 AM)
0 3 * * 0 /usr/local/bin/uv run python -m cowrieprocessor.enrichment.update_datacenter_ranges
```

---

## 💾 Cache Schema

### SQLite (Development)

```sql
CREATE TABLE ip_classification_cache (
    ip_address TEXT PRIMARY KEY,
    ip_type TEXT NOT NULL,  -- 'tor', 'cloud', 'datacenter', 'residential', 'unknown'
    provider TEXT,
    confidence REAL NOT NULL,
    source TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_ip_type ON ip_classification_cache(ip_type);
CREATE INDEX idx_updated_at ON ip_classification_cache(updated_at);
```

### Redis (Production)

```python
# Key format: "ipclass:{ip_address}"
# Value format: JSON
{
    "ip_type": "cloud",
    "provider": "aws",
    "confidence": 0.99,
    "source": "cloud_ranges_aws",
    "updated_at": "2025-11-10T10:00:00Z"
}

# TTL: 1 hour (TOR), 24 hours (others)
```

---

## 🔗 Integration Points

### 1. Cascade Enricher (Real-Time)

**File**: `cowrieprocessor/enrichment/cascade_enricher.py`

```python
class CascadeEnricher:
    def __init__(self, ...):
        # Add IP classifier
        self.ip_classifier = IPClassifier(cache_backend="redis")

    def refresh_stale_data(self, ...):
        # Existing Pass 1: MaxMind GeoIP
        # Existing Pass 2: Cymru ASN
        # Existing Pass 3: GreyNoise

        # NEW Pass 4: IP Classification
        if enrichment.asn:
            classification = self.ip_classifier.classify(
                ip=ip_address,
                asn=enrichment.asn,
                as_name=enrichment.as_name
            )
            enrichment.ip_type = classification.ip_type.value
            enrichment.ip_type_provider = classification.provider
            enrichment.ip_type_confidence = classification.confidence
```

### 2. Bulk Loader (Historical)

**File**: `cowrieprocessor/loader/bulk.py`

```python
def _upsert_session_summaries(self, ...):
    # Existing: snapshot_asn, snapshot_country from ip_inventory

    # NEW: snapshot_ip_type from IP classifier
    if ip_enrichment:
        classification = self.ip_classifier.classify(
            ip=session.source_ip,
            asn=ip_enrichment.asn,
            as_name=ip_enrichment.as_name
        )
        snapshot_values["snapshot_ip_type"] = classification.ip_type.value
```

### 3. Backfill Script (One-Time)

**File**: `scripts/backfill_ip_classification.py`

```python
def backfill_sessions():
    """Backfill snapshot_ip_type for 1.68M sessions."""
    ip_classifier = IPClassifier()

    # Query all IPs from ip_inventory
    ips = session.query(IPInventory).all()  # 38,864 IPs

    # Batch classify
    classifications = {}
    for ip_record in ips:
        result = ip_classifier.classify(
            ip=ip_record.ip_address,
            asn=ip_record.asn,
            as_name=ip_record.as_name
        )
        classifications[ip_record.ip_address] = result.ip_type.value

    # Update sessions in batches
    for ip_address, ip_type in classifications.items():
        session.execute(
            update(SessionSummary)
            .where(SessionSummary.source_ip == ip_address)
            .values(snapshot_ip_type=ip_type)
        )
        session.commit()
```

---

## 📊 Performance Characteristics

| Operation | Time | Notes |
|-----------|------|-------|
| Single IP lookup (cached) | <1ms | Redis/SQLite cache hit |
| Single IP lookup (uncached) | <10ms | CIDR trie lookup |
| Bulk classify (1000 IPs, cached) | <100ms | Batch processing |
| Bulk classify (1000 IPs, uncached) | <1s | Parallel classification |
| TOR list update | ~2s | Download 8,000 IPs |
| Cloud ranges update | ~5s | Download 20,000 CIDRs |
| Datacenter ranges update | ~3s | Download 10,000 CIDRs |
| Full backfill (38K IPs) | ~6 minutes | Lookup time only |
| Full backfill (1.68M sessions) | ~2-4 hours | Including DB updates |

---

## ✅ Testing Strategy

### Unit Tests
```python
# test_ip_classifier.py
def test_tor_classification():
    classifier = IPClassifier()
    result = classifier.classify("1.2.3.4")  # Known TOR exit
    assert result.ip_type == IPType.TOR
    assert result.confidence > 0.9

def test_aws_classification():
    classifier = IPClassifier()
    result = classifier.classify("52.0.0.0")  # AWS IP
    assert result.ip_type == IPType.CLOUD
    assert result.provider == "aws"

def test_residential_heuristic():
    heuristic = ResidentialHeuristic()
    assert heuristic.is_residential("Verizon Broadband")
    assert not heuristic.is_residential("Amazon Data Services")
```

### Integration Tests
```python
# test_classification_integration.py
def test_cascade_enricher_integration():
    enricher = CascadeEnricher()
    enrichment = enricher.refresh_stale_data(ip="1.2.3.4")
    assert enrichment.ip_type in ["tor", "cloud", "datacenter", "residential", "unknown"]
```

---

## 🎯 Success Metrics

1. **Coverage**: ≥90% of sessions have non-null `snapshot_ip_type`
2. **Accuracy**: ≥80% correct classification (validated on known samples)
3. **Performance**: <10ms average lookup time (99th percentile)
4. **Cache Hit Rate**: ≥95% (after warmup)
5. **Update Reliability**: 100% automated updates succeed
6. **Cost**: $0/month for data sources

---

**Status**: DESIGN COMPLETE
**Next**: Implementation Phase 1 (IPClassifier service)
