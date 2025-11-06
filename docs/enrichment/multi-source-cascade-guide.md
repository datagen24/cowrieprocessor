# Multi-Source Enrichment Cascade Guide

## Overview

The multi-source enrichment cascade (ADR-008) provides high-coverage IP enrichment (>95%) with minimal API costs through intelligent sequential fallback across three complementary data sources:

1. **MaxMind GeoLite2** (Primary): Offline geo + ASN data for 99% of IPs
2. **Team Cymru** (ASN Fallback): Fills ~1% ASN gap via netcat bulk interface
3. **GreyNoise Community** (Threat Intel): Scanner/bot classification with RIOT benign service detection

**Key Benefits**:
- **Coverage**: >95% enrichment success rate (targeting 99.5%)
- **Cost**: $0/month (all free tiers)
- **Performance**: <100ms P95 latency (offline MaxMind primary)
- **API Efficiency**: 82% reduction (300K → 54K Cymru calls via early termination)

## Architecture

### Sequential Cascade Pattern

```
┌─────────────────────────────────────────────────────────────┐
│                    CascadeEnricher                          │
│                   (Orchestrator)                            │
└─────────────────────────────────────────────────────────────┘
                            │
                            ├─> Cache Check (ip_inventory)
                            │   └─> If fresh, return cached
                            │
                            ├─> MaxMind Lookup (offline)
                            │   ├─> Geo + ASN (99% coverage)
                            │   └─> Early termination if ASN found
                            │
                            ├─> Cymru Lookup (online, conditional)
                            │   ├─> Only if MaxMind ASN missing
                            │   ├─> Netcat bulk (whois.cymru.com:43)
                            │   └─> 90-day cache TTL
                            │
                            └─> GreyNoise Lookup (online, optional)
                                ├─> Scanner/bot classification
                                ├─> RIOT benign service detection
                                ├─> 7-day cache TTL
                                └─> Graceful degradation if quota exhausted
```

### Data Flow

```
IP Address → Cache Check → MaxMind → [Cymru?] → [GreyNoise?] → IPInventory
              (fresh?)      (offline)   (ASN gap)   (scanner)     (database)
                 │             │            │            │
                 ├─ Yes ──────┘            │            │
                 │                         │            │
                 └─ No ────> Lookup ───────┼───────────┐│
                               │           │           ││
                               └─ ASN? ────┼───────────┘│
                                  Yes      │            │
                                    │      │            │
                                    └──────┼────────────┘
                                           │
                                    No ────┘
```

## Components

### 1. MaxMindClient

**Purpose**: Offline geo + ASN enrichment via local GeoLite2 databases

**Database Files**:
- `GeoLite2-City.mmdb`: Geo data (country, city, coordinates)
- `GeoLite2-ASN.mmdb`: ASN data (AS number, organization)

**Location**: `/mnt/dshield/data/cache/maxmind/`

**Key Features**:
- Offline operation (zero API calls)
- Automatic weekly database updates (requires license key)
- ~200MB memory footprint (both databases loaded)
- <5ms lookup latency (disk-based)

**Usage**:
```python
from pathlib import Path
from cowrieprocessor.enrichment.maxmind_client import MaxMindClient

with MaxMindClient(
    db_path=Path("/mnt/dshield/data/cache/maxmind"),
    license_key="your_maxmind_license_key"
) as client:
    result = client.lookup_ip("8.8.8.8")
    if result:
        print(f"Country: {result.country_name}")
        print(f"City: {result.city}")
        print(f"ASN: {result.asn} ({result.asn_org})")

    # Check database age
    age = client.get_database_age()
    print(f"Database age: {age.days} days")

    # Update databases (if license key provided)
    if client.should_update():
        client.update_database()
```

**Configuration**:
```bash
# Environment variables
export MAXMIND_LICENSE_KEY="your_key_here"

# Database paths
/mnt/dshield/data/cache/maxmind/GeoLite2-City.mmdb
/mnt/dshield/data/cache/maxmind/GeoLite2-ASN.mmdb
```

**Maintenance**:
- Database updates: Weekly (automatic if license key configured)
- Staleness threshold: 7 days
- Update via: `client.update_database()` or manual download from MaxMind

### 2. CymruClient

**Purpose**: ASN fallback via Team Cymru's official netcat bulk interface

**⚠️ CRITICAL**: Use netcat interface ONLY. HTTP API abuse results in null-routing per Team Cymru documentation.

**Protocol**:
- **Primary**: Netcat bulk (`whois.cymru.com:43`)
- **Fallback**: DNS TXT queries (`<ip>.origin.asn.cymru.com`)

**Netcat Query Format**:
```
begin
verbose
8.8.8.8
1.1.1.1
end
```

**Response Format**:
```
Bulk mode; whois.cymru.com [2025-11-05 12:34:56 +0000]
AS      | IP               | BGP Prefix          | CC | Registry | Allocated  | AS Name
15169   | 8.8.8.8          | 8.8.8.0/24          | US | arin     | 1992-12-01 | GOOGLE, US
13335   | 1.1.1.1          | 1.1.1.0/24          | AU | apnic    | 2011-08-11 | CLOUDFLARENET, US
```

**Usage**:
```python
from cowrieprocessor.enrichment.cymru_client import CymruClient
from cowrieprocessor.enrichment.cache import EnrichmentCacheManager

cache = EnrichmentCacheManager(cache_dir=Path("/mnt/dshield/data/cache"))
client = CymruClient(cache=cache, ttl_days=90)

# Single IP lookup (DNS fallback)
result = client.lookup_asn("8.8.8.8")
if result:
    print(f"ASN: {result.asn}")
    print(f"Org: {result.asn_org}")
    print(f"Country: {result.country_code}")
    print(f"Registry: {result.registry}")

# Bulk lookup (netcat)
ips = ["8.8.8.8", "1.1.1.1", "54.239.28.85"]
results = client.bulk_lookup(ips)
for ip, result in results.items():
    print(f"{ip}: AS{result.asn} ({result.asn_org})")
```

**Rate Limiting**:
- Default: 100 req/sec throttle
- Bulk queries: Max 500 IPs per request
- Exponential backoff: 1s, 2s, 4s retries

**Cache TTL**: 90 days (per ADR-008 specification)

### 3. GreyNoiseClient

**Purpose**: Scanner/bot classification via GreyNoise Community API

**API Endpoint**: `https://api.greynoise.io/v3/community/{ip}`

**Key Features**:
- 10,000 requests/day quota (resets midnight UTC)
- RIOT classification (benign services: CDNs, cloud providers)
- Malicious scanner detection (Shodan, Censys, etc.)

**Usage**:
```python
from cowrieprocessor.enrichment.greynoise_client import GreyNoiseClient
from cowrieprocessor.enrichment.cache import EnrichmentCacheManager

cache = EnrichmentCacheManager(cache_dir=Path("/mnt/dshield/data/cache"))
client = GreyNoiseClient(
    api_key="your_greynoise_api_key",
    cache=cache,
    ttl_days=7
)

# Check if IP is known scanner
result = client.lookup_ip("104.131.0.69")  # Shodan scanner
if result:
    print(f"Noise: {result.noise}")  # True = known scanner
    print(f"RIOT: {result.riot}")    # False = not benign service
    print(f"Classification: {result.classification}")  # "malicious"
    if result.last_seen:
        print(f"Last seen: {result.last_seen}")

# Check benign service
result = client.lookup_ip("8.8.8.8")  # Google DNS
if result:
    print(f"RIOT: {result.riot}")    # True = benign service
    print(f"Name: {result.name}")    # "Google Public DNS"

# Check quota remaining
remaining = client.get_remaining_quota()
print(f"API calls remaining today: {remaining}/10000")
```

**Configuration**:
```bash
# Environment variable
export GREYNOISE_API_KEY="your_key_here"
```

**Quota Management**:
- Daily limit: 10,000 requests
- Reset time: Midnight UTC
- Tracking: Automatic via cache
- Exhaustion behavior: Graceful degradation (return None)

**Cache TTL**: 7 days (per ADR-008 specification)

### 4. CascadeEnricher

**Purpose**: Orchestrate sequential enrichment across all sources

**Key Methods**:
- `enrich_ip(ip_address)`: Single IP enrichment with full cascade
- `enrich_session_ips(session_id)`: Enrich all IPs in a session
- `backfill_missing_asns(limit)`: Find and enrich IPs with NULL ASN
- `refresh_stale_data(source, limit)`: Refresh stale enrichment data

**Usage**:
```python
from cowrieprocessor.enrichment.cascade_enricher import CascadeEnricher
from cowrieprocessor.enrichment.maxmind_client import MaxMindClient
from cowrieprocessor.enrichment.cymru_client import CymruClient
from cowrieprocessor.enrichment.greynoise_client import GreyNoiseClient
from cowrieprocessor.db.engine import create_engine_from_settings, create_session_maker
from cowrieprocessor.settings import DatabaseSettings

# Initialize database
settings = DatabaseSettings(url="postgresql://user:pass@host/db")
engine = create_engine_from_settings(settings)
SessionMaker = create_session_maker(engine)

# Initialize clients
maxmind = MaxMindClient(
    db_path=Path("/mnt/dshield/data/cache/maxmind"),
    license_key=os.getenv("MAXMIND_LICENSE_KEY")
)
cymru = CymruClient(cache=cache, ttl_days=90)
greynoise = GreyNoiseClient(
    api_key=os.getenv("GREYNOISE_API_KEY"),
    cache=cache,
    ttl_days=7
)

# Create cascade enricher
with SessionMaker() as session:
    cascade = CascadeEnricher(
        maxmind=maxmind,
        cymru=cymru,
        greynoise=greynoise,
        session=session,
    )

    # Enrich single IP
    inventory = cascade.enrich_ip("8.8.8.8")
    print(f"Country: {inventory.geo_country}")
    print(f"ASN: {inventory.asn_number}")
    print(f"Scanner: {inventory.is_scanner}")

    # Enrich session IPs
    session_ips = cascade.enrich_session_ips(session_id=12345)
    for ip, inventory in session_ips.items():
        print(f"{ip}: {inventory.geo_country}, AS{inventory.asn_number}")

    # Backfill missing ASNs
    count = cascade.backfill_missing_asns(limit=1000)
    print(f"Backfilled {count} ASNs")

    # Refresh stale data
    stats = cascade.refresh_stale_data(source="cymru", limit=500)
    print(f"Refreshed {stats['cymru_refreshed']} Cymru records")

    session.commit()
```

## Cascade Logic

### Freshness Checks

The cascade uses source-specific TTLs to determine if cached data is fresh:

```python
def _is_fresh(inventory: IPInventory) -> bool:
    now = datetime.utcnow()

    # MaxMind: Check database age (updated weekly)
    if inventory.source == "maxmind":
        db_age = maxmind.get_database_age()
        return db_age < timedelta(days=7)

    # Cymru: 90-day TTL
    if inventory.asn_source == "cymru":
        if inventory.enrichment_ts:
            return (now - inventory.enrichment_ts) < timedelta(days=90)

    # GreyNoise: 7-day TTL
    if inventory.scanner_source == "greynoise":
        if inventory.scanner_ts:
            return (now - inventory.scanner_ts) < timedelta(days=7)

    return False
```

### Early Termination

The cascade stops when the primary source (MaxMind) provides complete data:

```python
def enrich_ip(ip_address: str) -> IPInventory:
    # Step 1: Cache check
    cached = session.query(IPInventory).filter_by(ip_address=ip).first()
    if cached and _is_fresh(cached):
        return cached  # Fresh cache hit

    # Step 2: MaxMind lookup (offline, always fast)
    maxmind_result = maxmind.lookup_ip(ip)

    # Step 3: Cymru fallback (only if MaxMind ASN missing)
    if maxmind_result and maxmind_result.asn is None:
        cymru_result = cymru.lookup_asn(ip)
    else:
        cymru_result = None  # Early termination (99% of cases)

    # Step 4: GreyNoise classification (if quota available)
    if greynoise.get_remaining_quota() > 0:
        gn_result = greynoise.lookup_ip(ip)
    else:
        gn_result = None  # Graceful degradation

    # Step 5: Merge and update database
    inventory = _merge_results(cached, maxmind_result, cymru_result, gn_result)
    if cached:
        session.merge(inventory)
    else:
        session.add(inventory)

    return inventory
```

### Source Priority Rules

When merging data from multiple sources:

1. **Geo Data**: MaxMind ONLY (most accurate, never overwrite)
2. **ASN Data**: MaxMind preferred, Cymru fallback
3. **Scanner Classification**: GreyNoise ONLY (not in other sources)
4. **Timestamps**: Separate per source (`enrichment_ts`, `scanner_ts`)

## Database Schema

### IPInventory Table

```sql
CREATE TABLE ip_inventory (
    ip_address VARCHAR(45) PRIMARY KEY,

    -- Geo data (MaxMind only)
    geo_country VARCHAR(2),
    geo_city VARCHAR(100),
    geo_latitude FLOAT,
    geo_longitude FLOAT,

    -- ASN data (MaxMind > Cymru)
    asn_number INTEGER,
    asn_org VARCHAR(200),
    asn_source VARCHAR(20),  -- "maxmind" or "cymru"

    -- Scanner classification (GreyNoise only)
    is_scanner BOOLEAN GENERATED ALWAYS AS (
        enrichment->>'greynoise'->>'noise' = 'true'
    ) STORED,

    -- Enrichment metadata
    enrichment JSON,  -- Source-specific data
    enrichment_ts TIMESTAMP,  -- MaxMind/Cymru timestamp
    scanner_ts TIMESTAMP,     -- GreyNoise timestamp

    -- Observation tracking
    observation_count INTEGER DEFAULT 1,
    first_seen_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### Enrichment JSON Structure

```json
{
  "maxmind": {
    "country_code": "US",
    "country_name": "United States",
    "city": "Mountain View",
    "latitude": 37.4056,
    "longitude": -122.0775,
    "asn": 15169,
    "asn_org": "GOOGLE",
    "accuracy_radius": 1000,
    "cached_at": "2025-11-05T12:34:56Z"
  },
  "cymru": {
    "asn": 15169,
    "asn_org": "GOOGLE, US",
    "country_code": "US",
    "registry": "arin",
    "cached_at": "2025-11-05T12:35:01Z"
  },
  "greynoise": {
    "noise": false,
    "riot": true,
    "classification": "benign",
    "name": "Google Public DNS",
    "last_seen": "2025-11-04T08:22:15Z",
    "cached_at": "2025-11-05T12:35:05Z"
  }
}
```

## Operations

### Production Deployment

1. **Install Dependencies**:
```bash
uv pip install -e '.[enrichment]'
# Installs: geoip2>=4.7.0, dnspython>=2.4.0
```

2. **Download MaxMind Databases**:
```bash
# Register for free license key at https://www.maxmind.com/
mkdir -p /mnt/dshield/data/cache/maxmind
cd /mnt/dshield/data/cache/maxmind

# Download databases (requires license key)
wget "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&license_key=YOUR_KEY&suffix=tar.gz" -O GeoLite2-City.tar.gz
wget "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-ASN&license_key=YOUR_KEY&suffix=tar.gz" -O GeoLite2-ASN.tar.gz

# Extract
tar -xzf GeoLite2-City.tar.gz --strip-components=1 "*/GeoLite2-City.mmdb"
tar -xzf GeoLite2-ASN.tar.gz --strip-components=1 "*/GeoLite2-ASN.mmdb"
```

3. **Configure API Keys**:
```bash
# Add to environment
export MAXMIND_LICENSE_KEY="your_maxmind_key"
export GREYNOISE_API_KEY="your_greynoise_key"

# Or use sensors.toml
[sensors.production]
maxmind_license_key = "env:MAXMIND_LICENSE_KEY"
greynoise_api_key = "env:GREYNOISE_API_KEY"
```

4. **Test Cascade**:
```bash
# Python shell
python3 << EOF
from cowrieprocessor.enrichment.cascade_enricher import CascadeEnricher
# ... initialize clients ...
inventory = cascade.enrich_ip("8.8.8.8")
print(f"ASN: {inventory.asn_number}, Country: {inventory.geo_country}")
EOF
```

### Backfill Workflow

Enrich existing IPs with missing ASN data:

```bash
# Python script
from cowrieprocessor.enrichment.cascade_enricher import CascadeEnricher

with SessionMaker() as session:
    cascade = CascadeEnricher(maxmind, cymru, greynoise, session)

    # Backfill in batches
    total = 0
    while True:
        count = cascade.backfill_missing_asns(limit=1000)
        total += count
        print(f"Backfilled {count} ASNs (total: {total})")
        session.commit()

        if count < 1000:
            break  # All done
```

### Refresh Stale Data

Update enrichment data that has exceeded TTL:

```bash
# Python script
from cowrieprocessor.enrichment.cascade_enricher import CascadeEnricher

with SessionMaker() as session:
    cascade = CascadeEnricher(maxmind, cymru, greynoise, session)

    # Refresh stale Cymru ASN data (>90 days old)
    stats = cascade.refresh_stale_data(source="cymru", limit=1000)
    print(f"Refreshed {stats['cymru_refreshed']} Cymru records")

    # Refresh stale GreyNoise scanner data (>7 days old)
    stats = cascade.refresh_stale_data(source="greynoise", limit=500)
    print(f"Refreshed {stats['greynoise_refreshed']} GreyNoise records")

    session.commit()
```

## Monitoring

### Health Checks

```python
from cowrieprocessor.enrichment.cascade_enricher import CascadeEnricher

# Check MaxMind database age
db_age = maxmind.get_database_age()
if db_age > timedelta(days=14):
    alert("MaxMind database >14 days old")

# Check GreyNoise quota
remaining = greynoise.get_remaining_quota()
if remaining < 2000:
    alert(f"GreyNoise quota low: {remaining}/10000")

# Check enrichment coverage
with SessionMaker() as session:
    total_ips = session.query(func.count(IPInventory.ip_address)).scalar()
    enriched = session.query(func.count(IPInventory.ip_address)).filter(
        IPInventory.asn_number.isnot(None)
    ).scalar()

    coverage = (enriched / total_ips) * 100
    if coverage < 90:
        alert(f"Enrichment coverage low: {coverage:.1f}%")
```

### Statistics Tracking

```python
# Cascade statistics
stats = cascade.get_stats()
print(f"Total IPs: {stats['total_ips']}")
print(f"Cache hits: {stats['cache_hits']} ({stats['cache_hit_rate']:.1f}%)")
print(f"MaxMind hits: {stats['maxmind_hits']}")
print(f"Cymru hits: {stats['cymru_hits']}")
print(f"GreyNoise hits: {stats['greynoise_hits']}")
print(f"Errors: {stats['errors']}")

# Client statistics
maxmind_stats = maxmind.get_stats()
print(f"MaxMind lookups: {maxmind_stats['lookups']}")
print(f"MaxMind hits: {maxmind_stats['hits']}")

cymru_stats = cymru.get_stats()
print(f"Cymru DNS success: {cymru_stats['dns_success']}")
print(f"Cymru netcat success: {cymru_stats['netcat_success']}")

gn_stats = greynoise.get_stats()
print(f"GreyNoise lookups: {gn_stats['lookups']}")
print(f"GreyNoise quota: {gn_stats['quota_remaining']}/10000")
```

## Troubleshooting

### MaxMind Database Missing

**Symptom**: `FileNotFoundError` when initializing MaxMindClient

**Solution**:
```bash
# Download databases manually
cd /mnt/dshield/data/cache/maxmind
wget "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&license_key=YOUR_KEY&suffix=tar.gz" -O GeoLite2-City.tar.gz
tar -xzf GeoLite2-City.tar.gz --strip-components=1 "*/GeoLite2-City.mmdb"
```

### Team Cymru Timeout

**Symptom**: `socket.timeout` errors from CymruClient

**Solution**:
```python
# Increase timeout (default: 30s)
client = CymruClient(cache=cache, ttl_days=90)
client._timeout = 60  # 60 seconds
```

### GreyNoise Quota Exhausted

**Symptom**: GreyNoise returns None, quota = 0

**Solution**:
```python
# Check when quota resets
import datetime
now = datetime.datetime.now(datetime.timezone.utc)
midnight_utc = now.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
time_until_reset = midnight_utc - now
print(f"Quota resets in {time_until_reset.seconds // 3600} hours")

# Cascader gracefully degrades (continues without GreyNoise)
```

### Stale ASN Data

**Symptom**: ASN data >90 days old

**Solution**:
```python
# Refresh stale Cymru data
with SessionMaker() as session:
    cascade = CascadeEnricher(maxmind, cymru, greynoise, session)
    stats = cascade.refresh_stale_data(source="cymru", limit=1000)
    print(f"Refreshed {stats['cymru_refreshed']} records")
    session.commit()
```

## Performance Optimization

### Batch Processing

Process multiple IPs efficiently:

```python
# Batch enrich session IPs
session_ids = [1, 2, 3, 4, 5]
for session_id in session_ids:
    ips = cascade.enrich_session_ips(session_id)
    print(f"Session {session_id}: {len(ips)} IPs enriched")
    session.commit()
```

### Cache Warming

Pre-populate cache with known IPs:

```python
# Warm cache with top IPs
top_ips = session.query(IPInventory.ip_address).limit(10000).all()
for (ip,) in top_ips:
    if not cascade._is_fresh(ip):
        cascade.enrich_ip(ip)
        session.commit()
```

### Parallel Enrichment

Use multiprocessing for large batches:

```python
from multiprocessing import Pool

def enrich_batch(ip_batch):
    with SessionMaker() as session:
        cascade = CascadeEnricher(maxmind, cymru, greynoise, session)
        for ip in ip_batch:
            cascade.enrich_ip(ip)
        session.commit()

# Split IPs into batches
ip_batches = [ips[i:i+100] for i in range(0, len(ips), 100)]

# Process in parallel
with Pool(processes=4) as pool:
    pool.map(enrich_batch, ip_batches)
```

## API Reference

See individual client documentation:
- [MaxMindClient API](../api/maxmind_client.md)
- [CymruClient API](../api/cymru_client.md)
- [GreyNoiseClient API](../api/greynoise_client.md)
- [CascadeEnricher API](../api/cascade_enricher.md)

## Related Documentation

- [ADR-008: Multi-Source Enrichment Fallback](../ADR/008-multi-source-enrichment-fallback.md)
- [ADR-007: Three-Tier Enrichment Architecture](../ADR/007-three-tier-enrichment.md)
- [Enrichment Cache Design](./cache-design.md)
- [Rate Limiting Strategy](./rate-limiting.md)
