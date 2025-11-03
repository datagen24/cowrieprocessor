# ASN and Geo Enrichment Design v2.0

**Status**: Design Review - Incorporating Operational Feedback
**Date**: 2025-11-03
**Branch**: scp-snowshoe

---

## Revision Notes

**v2.0 Changes** (addressing technical review feedback):
- ✅ Added asyncio DNS bulk operations for Team Cymru
- ✅ Integrated 3-tier cache strategy (Redis→DB→Disk) with per-source TTLs
- ✅ Added comprehensive error handling and monitoring
- ✅ Clarified GreyNoise backfill vs real-time strategy
- ✅ Added MaxMind update monitoring and corruption checks
- ✅ Added `enrichment_sources` computed column for gap analysis
- ✅ Revised implementation priority (Cymru PoC first)
- ✅ Added DNS rate limit protection with semaphore and backoff

---

## Executive Summary

Designing a **multi-source IP enrichment system** with **3-tier caching** to address DShield's coverage gaps ("XX" countries, "Not Routed" ASNs) and add RFC1918/bogon detection for spoofing identification.

**Primary Goal**: Achieve >95% IP classification coverage with multiple fallback sources
**Secondary Goal**: Detect non-routable IPs indicating spoofing/misconfiguration
**Operational Goal**: Zero-cost, fault-tolerant, production-grade enrichment

---

## Recommended Data Sources (Unchanged)

| Source | Cost | Coverage | Use Case |
|--------|------|----------|----------|
| **MaxMind GeoLite2** | $0 | 99%+ | Primary geo + ASN (offline) |
| **Team Cymru** | $0 | 100% | ASN fallback (DNS/whois) |
| **GreyNoise Community** | $0 | Selective | Scanner classification |
| **RFC1918/Bogon (local)** | $0 | 100% | Spoofing detection |

---

## Architecture Changes (v2.0)

### 3-Tier Cache Integration

**Existing Cache System** (already implemented):
```
Redis L1 (fast, volatile)
  ↓ miss
Database L2 (durable, queryable)
  ↓ miss
Filesystem L3 (archival, bulk import)
  ↓ miss
External API call
```

**Cache Strategy Per Source**:

| Source | Redis L1 | DB L2 | Disk L3 | TTL | Rationale |
|--------|----------|-------|---------|-----|-----------|
| **RFC1918** | ❌ Skip | ❌ Skip | ❌ Skip | N/A | Static validation, no cache needed |
| **MaxMind** | ❌ Skip | ✅ Yes | ✅ Yes | Infinite | Offline DB, cache enrichment results |
| **Team Cymru** | ✅ Yes | ✅ Yes | ✅ Yes | Infinite | ASN/geo rarely change, cache forever |
| **GreyNoise** | ✅ Yes | ✅ Yes | ✅ Yes | **7 days** | Scanner status changes frequently |
| **DShield** | ✅ Yes | ✅ Yes | ✅ Yes | 7 days | Existing implementation (unchanged) |

**Key Differences**:
- **MaxMind**: No Redis cache (offline DB is already fast)
- **GreyNoise**: Short TTL (7 days) - scanner classifications change
- **Cymru**: Infinite TTL - BGP ASN assignments are stable
- **RFC1918**: No cache - instant local validation

---

## Revised Data Flow

```
┌─────────────────────────────────────────────────────────┐
│ 0. IP VALIDATION (Local, instant, no cache)            │
│    Python ipaddress.is_private(), is_reserved(), etc.  │
│    └─> RFC1918/Bogon → enrichment['validation']        │
│    └─> is_bogon=true → SKIP all external lookups       │
└──────────────────┬──────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 1. MAXMIND GEOLITE2 (Offline DB, no external cache)    │
│    Direct DB query: SELECT * FROM maxmind_city/asn     │
│    WHERE ip BETWEEN range_start AND range_end          │
│    └─> Success (99%) → enrichment['maxmind']           │
│    └─> Cache result in DB L2 (enrichment JSON column)  │
│    └─> Miss (1%) → Continue to Tier 2                  │
└──────────────────┬──────────────────────────────────────┘
                   │ (only if MaxMind ASN is null)
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 2. TEAM CYMRU (DNS/whois, 3-tier cache)                │
│    Cache check: Redis L1 → DB L2 → Disk L3             │
│    Cache miss:                                          │
│      - Bulk mode: whois -h whois.cymru.com (100 IPs)   │
│      - Real-time: asyncio DNS with aiodns (10 concurrent)│
│    └─> Success → enrichment['cymru'], cache forever    │
│    └─> Empty response → Mark as "unrouted/bogon"       │
└──────────────────┬──────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 3. GREYNOISE (REST API, 3-tier cache, 7-day TTL)       │
│    Cache check: Redis L1 → DB L2 → Disk L3             │
│    Cache miss + budget available (10K/day):             │
│      - GET /v3/community/{ip}                           │
│    └─> Success → enrichment['greynoise'], 7-day TTL    │
│    └─> Skip if: backfill mode OR budget exhausted      │
└──────────────────┬──────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 4. ENRICHMENT STATUS TRACKING (NEW)                    │
│    enrichment['_meta'] = {                              │
│      "sources_attempted": ["maxmind", "cymru"],         │
│      "sources_succeeded": ["maxmind"],                  │
│      "sources_failed": [],                              │
│      "enrichment_timestamp": "2025-11-03T12:00:00Z",    │
│      "cache_hits": {"cymru": "redis_l1"}                │
│    }                                                     │
└─────────────────────────────────────────────────────────┘
```

---

## Team Cymru Bulk Operations (DETAILED)

### Method 1: Whois Bulk Interface (Recommended for Backfill)

**Advantages**:
- ✅ Send 100+ IPs in single request
- ✅ No DNS resolver rate limits
- ✅ Simple TCP connection, easy error handling

**Implementation**:
```python
import socket

def cymru_bulk_lookup(ip_list: list[str]) -> dict[str, dict]:
    """Query Team Cymru whois for bulk IP-to-ASN mapping.

    Args:
        ip_list: List of IP addresses (max 100 recommended)

    Returns:
        Dict mapping IP to {"asn": int, "prefix": str, "country": str, ...}
    """
    # Format: "begin\nverbose\n{ip1}\n{ip2}\n...\nend\n"
    query = "begin\nverbose\n" + "\n".join(ip_list) + "\nend\n"

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)  # 10 second timeout

    try:
        sock.connect(("whois.cymru.com", 43))
        sock.sendall(query.encode())

        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk

    finally:
        sock.close()

    return _parse_cymru_response(response.decode())

def _parse_cymru_response(response: str) -> dict[str, dict]:
    """Parse Cymru whois response.

    Response format:
    AS      | IP               | BGP Prefix          | CC | Registry | Allocated
    13335   | 1.0.0.1          | 1.0.0.0/24         | US | arin     | 2010-07-14
    """
    results = {}
    for line in response.split("\n"):
        if "|" not in line or line.startswith("AS"):
            continue

        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 6:
            asn, ip, prefix, cc, registry, allocated = parts[:6]
            results[ip] = {
                "asn": int(asn) if asn.isdigit() else None,
                "bgp_prefix": prefix,
                "country": cc,
                "registry": registry,
                "allocated": allocated
            }

    return results
```

**Batch Size**: 100 IPs per request (Cymru recommendation)
**Rate Limit**: No official limit, suggest 10 requests/second max
**Timeout**: 10 seconds per batch
**Error Handling**: Retry failed batches with exponential backoff

---

### Method 2: Asyncio DNS (Recommended for Real-Time)

**Advantages**:
- ✅ Fast for small batches (<100 IPs)
- ✅ Concurrent queries reduce latency
- ✅ Standard DNS protocol (no special client)

**Implementation**:
```python
import asyncio
import aiodns
from typing import Optional

class CymruDNSResolver:
    def __init__(self, concurrency_limit: int = 10):
        self.resolver = aiodns.DNSResolver()
        self.semaphore = asyncio.Semaphore(concurrency_limit)

    async def lookup_ip(self, ip: str) -> Optional[dict]:
        """Async DNS query for single IP."""
        # Reverse IP: 1.2.3.4 → 4.3.2.1.origin.asn.cymru.com
        reversed_ip = ".".join(ip.split(".")[::-1])
        query_domain = f"{reversed_ip}.origin.asn.cymru.com"

        async with self.semaphore:  # Rate limit concurrent queries
            try:
                # Query TXT record
                result = await asyncio.wait_for(
                    self.resolver.query(query_domain, "TXT"),
                    timeout=3.0  # 3 second timeout per query
                )

                # Parse response: "13335 | 1.0.0.0/24 | US | arin | 2010-07-14"
                txt_value = result[0].text.decode()
                parts = [p.strip() for p in txt_value.split("|")]

                return {
                    "asn": int(parts[0]) if parts[0].isdigit() else None,
                    "bgp_prefix": parts[1],
                    "country": parts[2],
                    "registry": parts[3],
                    "allocated": parts[4]
                }

            except asyncio.TimeoutError:
                # DNS timeout - might be rate limiting or network issue
                await asyncio.sleep(0.5)  # Backoff
                return None
            except Exception as e:
                # DNS error (NXDOMAIN = unrouted/bogon)
                return None

    async def lookup_batch(self, ip_list: list[str]) -> dict[str, dict]:
        """Lookup multiple IPs concurrently."""
        tasks = [self.lookup_ip(ip) for ip in ip_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            ip: result
            for ip, result in zip(ip_list, results)
            if result and not isinstance(result, Exception)
        }

# Usage:
async def enrich_with_cymru(ip_list: list[str]) -> dict:
    resolver = CymruDNSResolver(concurrency_limit=10)
    return await resolver.lookup_batch(ip_list)
```

**Concurrency Limit**: 10 concurrent DNS queries (via semaphore)
**Timeout**: 3 seconds per query
**Backoff**: 500ms delay after timeout (rate limit signal)
**Error Handling**: NXDOMAIN → unrouted/bogon, timeout → retry with backoff

---

## Error Handling & Monitoring

### Enrichment Status Tracking

**New Schema Addition**:
```python
# In enrichment JSON column:
{
  "maxmind": {...},
  "cymru": {...},
  "greynoise": {...},
  "_meta": {
    "enrichment_version": "2.0",
    "enrichment_timestamp": "2025-11-03T12:00:00Z",
    "sources_attempted": ["maxmind", "cymru", "greynoise"],
    "sources_succeeded": ["maxmind", "cymru"],
    "sources_failed": ["greynoise"],
    "failure_reasons": {
      "greynoise": "rate_limit_exceeded"
    },
    "cache_hits": {
      "cymru": "redis_l1",
      "maxmind": "db_query"
    },
    "total_duration_ms": 245
  }
}
```

### Error Categories and Handling

| Error Type | Source | Handling | Fallback |
|------------|--------|----------|----------|
| **MaxMind DB Missing** | MaxMind | Log error, skip MaxMind | → Cymru ASN |
| **MaxMind DB Corrupted** | MaxMind | Alert, use previous DB | → Cymru ASN |
| **DNS Timeout** | Cymru | Retry with backoff (3x) | → Mark ASN unknown |
| **DNS NXDOMAIN** | Cymru | Expected (unrouted IP) | → is_bogon=true |
| **GreyNoise Rate Limit** | GreyNoise | Skip, log budget exhausted | → Skip enrichment |
| **GreyNoise Network Error** | GreyNoise | Retry (3x), then skip | → Skip enrichment |
| **Redis Unavailable** | All | Skip L1, use L2/L3 | → DB/Disk cache |

### Monitoring Metrics

**Prometheus-style metrics** (integrate with existing telemetry):
```python
# Success rates per source
enrichment_source_success_total{source="maxmind"} = 198000
enrichment_source_failures_total{source="cymru"} = 24

# Cache hit rates
enrichment_cache_hits_total{source="cymru", tier="redis_l1"} = 150000
enrichment_cache_hits_total{source="cymru", tier="db_l2"} = 40000

# Coverage metrics
enrichment_coverage_ratio{field="country"} = 0.987
enrichment_coverage_ratio{field="asn"} = 0.992

# Performance
enrichment_duration_seconds{source="maxmind", percentile="p95"} = 0.05
enrichment_duration_seconds{source="cymru", percentile="p95"} = 2.3
```

**Alerting Thresholds**:
- ⚠️ Warning: Coverage drops below 95% for any field
- 🚨 Critical: MaxMind DB not updated in 10+ days
- 🚨 Critical: Any source fails >10% of attempts
- ⚠️ Warning: GreyNoise daily budget 90% exhausted

---

## GreyNoise Rate Limit Strategy

### Backfill vs Real-Time

**Backfill Mode** (historical data enrichment):
```python
# SKIP GreyNoise entirely during backfill
enrichment_service = EnrichmentService(
    skip_greynoise=True  # Flag to disable GreyNoise
)

# Why: 10K/day limit insufficient for 198K+ sessions
# 198K sessions ÷ 10K/day = 20 days to backfill
# Not worth the wait for optional scanner classification
```

**Real-Time Mode** (new sessions):
```python
# Enable GreyNoise with smart filtering
enrichment_service = EnrichmentService(
    greynoise_enabled=True,
    greynoise_filter=lambda session: session.command_count >= 10
)

# Budget tracking
class GreyNoiseRateLimiter:
    def __init__(self, daily_limit: int = 10000):
        self.daily_limit = daily_limit
        self.daily_usage = 0
        self.reset_time = datetime.now() + timedelta(days=1)

    def allow_request(self) -> bool:
        if datetime.now() >= self.reset_time:
            self.daily_usage = 0
            self.reset_time = datetime.now() + timedelta(days=1)

        if self.daily_usage >= self.daily_limit:
            return False

        self.daily_usage += 1
        return True
```

**Filtering Strategy**:
- ✅ Include: Sessions with ≥10 commands (likely active attackers)
- ✅ Include: IPs with ≥5 file downloads
- ✅ Include: IPs flagged by VirusTotal
- ❌ Exclude: Single-command sessions (likely scans)
- ❌ Exclude: IPs already classified in cache

**Expected Usage**:
- Typical daily sessions: ~5,000-10,000
- After filtering (≥10 commands): ~500-1,000
- Well within 10K/day free tier ✅

---

## MaxMind Update Automation

### Weekly Update Script

```bash
#!/bin/bash
# scripts/production/refresh_maxmind.sh

set -euo pipefail

MAXMIND_LICENSE_KEY="${MAXMIND_LICENSE_KEY:?ERROR: MAXMIND_LICENSE_KEY not set}"
MAXMIND_DIR="/mnt/dshield/data/maxmind"
BACKUP_DIR="/mnt/dshield/data/maxmind_backups"
ALERT_EMAIL="admin@example.com"

log() {
    echo "[$(date -Iseconds)] $*" | tee -a "${MAXMIND_DIR}/update.log"
}

alert() {
    log "ALERT: $*"
    echo "$*" | mail -s "MaxMind Update Alert" "$ALERT_EMAIL"
}

# 1. Download new databases
log "Downloading MaxMind GeoLite2 databases..."
for db in GeoLite2-City GeoLite2-ASN; do
    curl -o "${MAXMIND_DIR}/${db}.tar.gz" \
        "https://download.maxmind.com/app/geoip_download?edition_id=${db}&license_key=${MAXMIND_LICENSE_KEY}&suffix=tar.gz"

    if [ $? -ne 0 ]; then
        alert "Failed to download ${db}"
        exit 1
    fi
done

# 2. Extract archives
log "Extracting databases..."
cd "$MAXMIND_DIR"
for db in GeoLite2-City GeoLite2-ASN; do
    tar -xzf "${db}.tar.gz"

    # Move .mmdb file to standard location
    find . -name "${db}.mmdb" -exec mv {} "${db}.mmdb.new" \;
done

# 3. Validate new databases
log "Validating new databases..."
for db in GeoLite2-City GeoLite2-ASN; do
    # Test database integrity (try to lookup known IP)
    if ! python3 -c "
import geoip2.database
reader = geoip2.database.Reader('${db}.mmdb.new')
reader.city('8.8.8.8')  # Google DNS should always resolve
reader.close()
    "; then
        alert "Validation failed for ${db}.mmdb.new"
        rm "${db}.mmdb.new"
        exit 1
    fi
done

# 4. Backup current databases
log "Backing up current databases..."
mkdir -p "$BACKUP_DIR/$(date +%Y%m%d)"
for db in GeoLite2-City GeoLite2-ASN; do
    if [ -f "${db}.mmdb" ]; then
        cp "${db}.mmdb" "$BACKUP_DIR/$(date +%Y%m%d)/${db}.mmdb"
    fi
done

# 5. Atomic swap (rename new → current)
log "Activating new databases..."
for db in GeoLite2-City GeoLite2-ASN; do
    mv "${db}.mmdb.new" "${db}.mmdb"
done

# 6. Cleanup old backups (keep last 4 weeks)
find "$BACKUP_DIR" -type d -mtime +28 -exec rm -rf {} \;

log "MaxMind update completed successfully"
```

**Cron Schedule**: Weekly on Wednesdays at 2 AM
```cron
0 2 * * 3 /mnt/dshield/scripts/production/refresh_maxmind.sh
```

### Graceful Fallback on MaxMind Failure

```python
class MaxMindHandler:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.reader = None
        self.last_error = None

    def _load_db(self):
        """Load MaxMind database with error handling."""
        try:
            self.reader = geoip2.database.Reader(self.db_path)
            self.last_error = None
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"MaxMind DB load failed: {e}")
            # Emit metric for monitoring
            prometheus_client.Counter(
                "enrichment_maxmind_load_failures_total"
            ).inc()

    def lookup(self, ip: str) -> Optional[dict]:
        """Lookup IP with automatic fallback."""
        if not self.reader:
            self._load_db()

        if not self.reader:
            # MaxMind unavailable, skip to Cymru fallback
            return None

        try:
            response = self.reader.city(ip)
            return {
                "country": response.country.iso_code,
                "city": response.city.name,
                "asn": response.traits.autonomous_system_number,
                "as_org": response.traits.autonomous_system_organization
            }
        except geoip2.errors.AddressNotFoundError:
            # IP not in database (expected for some IPs)
            return None
        except Exception as e:
            # Unexpected error - DB might be corrupted
            logger.error(f"MaxMind lookup error: {e}")
            self.reader = None  # Force reload on next call
            return None
```

---

## Schema Additions

### Computed Columns

```sql
-- Enrichment source tracking
ALTER TABLE session_summaries ADD COLUMN
  enrichment_sources TEXT[] GENERATED ALWAYS AS (
    ARRAY(
      SELECT jsonb_object_keys(enrichment)
      WHERE jsonb_typeof(enrichment) = 'object'
        AND key NOT IN ('_meta')  -- Exclude metadata
    )
  ) STORED;

-- Multi-source fallback for country
ALTER TABLE session_summaries ADD COLUMN
  geo_country VARCHAR(2) GENERATED ALWAYS AS (
    COALESCE(
      enrichment->'maxmind'->>'country',
      enrichment->'cymru'->>'country',
      enrichment->'dshield'->'ip'->>'ascountry',
      'XX'
    )
  ) STORED;

-- Multi-source fallback for ASN
ALTER TABLE session_summaries ADD COLUMN
  asn INTEGER GENERATED ALWAYS AS (
    COALESCE(
      (enrichment->'maxmind'->>'asn')::integer,
      (enrichment->'cymru'->>'asn')::integer,
      (enrichment->'dshield'->'ip'->>'asn')::integer
    )
  ) STORED;

-- Spoofing detection
ALTER TABLE session_summaries ADD COLUMN
  is_bogon BOOLEAN GENERATED ALWAYS AS (
    COALESCE(
      (enrichment->'validation'->>'is_bogon')::boolean,
      false
    )
  ) STORED;

-- Scanner classification (new)
ALTER TABLE session_summaries ADD COLUMN
  is_scanner BOOLEAN GENERATED ALWAYS AS (
    COALESCE(
      (enrichment->'greynoise'->>'noise')::boolean,
      false
    )
  ) STORED;

-- Enrichment completeness (percentage of sources succeeded)
ALTER TABLE session_summaries ADD COLUMN
  enrichment_completeness DECIMAL(5,2) GENERATED ALWAYS AS (
    CASE
      WHEN enrichment->'_meta'->'sources_attempted' IS NULL THEN 0
      ELSE ROUND(
        100.0 * jsonb_array_length(enrichment->'_meta'->'sources_succeeded') /
        NULLIF(jsonb_array_length(enrichment->'_meta'->'sources_attempted'), 0),
        2
      )
    END
  ) STORED;
```

### Indexes for Performance

```sql
-- Fast queries on computed columns
CREATE INDEX idx_session_geo_country ON session_summaries(geo_country);
CREATE INDEX idx_session_asn ON session_summaries(asn);
CREATE INDEX idx_session_is_bogon ON session_summaries(is_bogon) WHERE is_bogon = true;
CREATE INDEX idx_session_is_scanner ON session_summaries(is_scanner) WHERE is_scanner = true;

-- Enrichment gap analysis
CREATE INDEX idx_session_enrichment_sources ON session_summaries USING GIN(enrichment_sources);
CREATE INDEX idx_session_enrichment_completeness ON session_summaries(enrichment_completeness)
  WHERE enrichment_completeness < 100;
```

---

## Revised Implementation Plan

### **Phase 0: PoC - Team Cymru (1-2 hours)** ⭐ NEW PRIORITY

**Why First**: Simplest to implement, proves fallback architecture

**Work Ticket**: `feat(enrichment): Team Cymru IP-to-ASN PoC`

**Tasks**:
1. Implement asyncio DNS resolver with aiodns
2. Add concurrency semaphore (10 concurrent queries)
3. Integrate with 3-tier cache (Redis→DB→Disk, infinite TTL)
4. Add `enrichment['cymru']` field
5. Test with 1,000 IPs from current dataset
6. Measure cache hit rates and performance

**Success Criteria**:
- [ ] 100% ASN coverage for routable IPs
- [ ] <3 seconds for 100 IPs (with cold cache)
- [ ] <0.5 seconds for 100 IPs (with warm cache)
- [ ] NXDOMAIN responses correctly identify bogons

**Deliverable**: Working Cymru enrichment with cache integration

---

### **Phase 1: RFC1918/Bogon Detection (1 hour)**

**Work Ticket**: `feat(enrichment): add RFC1918/bogon IP validation`

**Tasks**:
1. Create `cowrieprocessor/enrichment/ip_validator.py`
2. Add `validate_ip()` function using Python `ipaddress` library
3. Check: `is_private`, `is_reserved`, `is_loopback`, `is_multicast`, `is_bogon`
4. Return early if bogon (skip all external enrichments)
5. Add `enrichment['validation']` field
6. Add test cases for all RFC ranges

**Success Criteria**:
- [ ] RFC1918 IPs detected (192.168.x.x, 10.x.x.x, 172.16-31.x.x)
- [ ] Bogons detected (0.0.0.0/8, 127.0.0.0/8, 169.254.0.0/16, etc.)
- [ ] All bogons skip external API calls (performance optimization)

---

### **Phase 2: MaxMind GeoLite2 Integration (2-3 hours)**

**Work Ticket**: `feat(enrichment): integrate MaxMind GeoLite2 offline DB`

**Tasks**:
1. Download MaxMind GeoLite2 City + ASN databases
2. Implement `cowrieprocessor/enrichment/maxmind_handler.py`
3. Add database loading with corruption detection
4. Store results in `enrichment['maxmind']`
5. Cache results in DB L2 (enrichment JSON column)
6. Create `scripts/production/refresh_maxmind.sh` with monitoring
7. Set up weekly cron job

**Success Criteria**:
- [ ] 99%+ country coverage
- [ ] 95%+ ASN coverage
- [ ] <50ms query latency
- [ ] Graceful fallback to Cymru on MaxMind failure

---

### **Phase 3: Enrichment Status Tracking (1 hour)**

**Work Ticket**: `feat(enrichment): add enrichment metadata and monitoring`

**Tasks**:
1. Add `enrichment['_meta']` field with source tracking
2. Record attempted/succeeded/failed sources
3. Add cache hit tracking per source
4. Implement Prometheus metrics for monitoring
5. Create computed columns: `enrichment_sources`, `enrichment_completeness`
6. Add alerting thresholds (coverage <95%, failures >10%)

**Success Criteria**:
- [ ] Can query: "Which sessions only have DShield data?"
- [ ] Metrics show cache hit rates per source
- [ ] Alerts fire on MaxMind DB staleness

---

### **Phase 4: GreyNoise Scanner Detection (2 hours)**

**Work Ticket**: `feat(enrichment): add GreyNoise scanner classification`

**Tasks**:
1. Implement `cowrieprocessor/enrichment/greynoise_handler.py`
2. Add REST API client with 3-tier cache (7-day TTL)
3. Implement daily rate limiter (10K/day budget)
4. Add filtering: only query sessions with ≥10 commands
5. Add backfill skip flag (`skip_greynoise=True`)
6. Store results in `enrichment['greynoise']`

**Success Criteria**:
- [ ] Scanner tags for high-activity IPs
- [ ] Daily budget never exceeded
- [ ] Backfill mode skips GreyNoise entirely

---

### **Phase 5: Database Migration and Computed Columns (1 hour)**

**Work Ticket**: `feat(db): add multi-source enrichment computed columns`

**Tasks**:
1. Create migration for computed columns
2. Add indexes on `geo_country`, `asn`, `is_bogon`, `is_scanner`
3. Update schema to version 11
4. Test computed column fallback logic (MaxMind → Cymru → DShield)
5. Verify query performance improvement vs JSON path extraction

---

### **Phase 6: Query Updates (1 hour)**

**Work Ticket**: `fix(queries): use multi-source enrichment fallback`

**Tasks**:
1. Update Query 11: Use `geo_country` instead of DShield-only path
2. Update Query 12: Use `asn` computed column
3. Create Query 15: Spoofing analysis (`WHERE is_bogon = true`)
4. Create Query 16: Scanner classification (`WHERE is_scanner = true`)
5. Test all queries with updated schema

---

## Testing Strategy

### Unit Tests

```python
# tests/unit/test_ip_validator.py
def test_rfc1918_detection():
    assert validate_ip("192.168.1.1")["is_private"] == True
    assert validate_ip("10.0.0.1")["is_private"] == True
    assert validate_ip("8.8.8.8")["is_private"] == False

# tests/unit/test_cymru_handler.py
@pytest.mark.asyncio
async def test_cymru_dns_lookup():
    resolver = CymruDNSResolver()
    result = await resolver.lookup_ip("8.8.8.8")
    assert result["asn"] == 15169
    assert result["country"] == "US"

# tests/unit/test_maxmind_handler.py
def test_maxmind_graceful_fallback():
    handler = MaxMindHandler("/nonexistent/path")
    result = handler.lookup("8.8.8.8")
    assert result is None  # Should return None, not crash
```

### Integration Tests

```python
# tests/integration/test_multi_source_enrichment.py
def test_enrichment_fallback_chain(db_session):
    """Test MaxMind → Cymru → DShield fallback."""
    service = EnrichmentService(
        maxmind_db_path="/path/to/maxmind",
        enable_cymru=True,
        enable_greynoise=False
    )

    # Test IP not in MaxMind but in Cymru
    enrichment = service.enrich_session("203.0.113.1")

    assert enrichment["_meta"]["sources_attempted"] == ["maxmind", "cymru"]
    assert enrichment["_meta"]["sources_succeeded"] == ["cymru"]
    assert enrichment["cymru"]["asn"] is not None
```

### Performance Tests

```python
# tests/performance/test_enrichment_throughput.py
@pytest.mark.performance
async def test_cymru_concurrent_throughput():
    """Cymru should handle 100 IPs in <3 seconds."""
    resolver = CymruDNSResolver(concurrency_limit=10)
    ips = generate_test_ips(100)

    start = time.time()
    results = await resolver.lookup_batch(ips)
    duration = time.time() - start

    assert duration < 3.0, f"Took {duration}s, expected <3s"
    assert len(results) == 100
```

---

## Migration Path for Existing Data

### Backfill Strategy

```python
# scripts/production/backfill_enrichment.py

async def backfill_multi_source_enrichment(
    batch_size: int = 1000,
    skip_greynoise: bool = True  # Skip during backfill
):
    """Backfill existing sessions with new enrichment sources."""

    # Find sessions missing new enrichment sources
    query = """
        SELECT session_id, source_ip
        FROM session_summaries
        WHERE enrichment->'maxmind' IS NULL
          AND enrichment->'cymru' IS NULL
          AND is_bogon IS NULL
        ORDER BY first_event_at DESC
        LIMIT :batch_size
    """

    while True:
        sessions = db.execute(query, {"batch_size": batch_size}).fetchall()
        if not sessions:
            break

        # Batch enrich
        for session in sessions:
            enrichment = await enrich_with_multi_source(
                session.source_ip,
                skip_greynoise=skip_greynoise
            )

            # Update session enrichment
            db.execute(
                "UPDATE session_summaries SET enrichment = :enrichment WHERE session_id = :id",
                {"enrichment": json.dumps(enrichment), "id": session.session_id}
            )

        db.commit()
        logger.info(f"Enriched {len(sessions)} sessions")
```

**Estimated Time**:
- 198K sessions ÷ 1K batch = 198 batches
- Cymru DNS: ~3 seconds per batch (with concurrency)
- Total: ~10 minutes for ASN backfill ⚡

---

## Cost-Benefit Analysis

### Current State (DShield Only):
```
Coverage:
  - Country: 70-80% ("XX" unknown: 20-30%)
  - ASN: 75-85% ("Not Routed": 15-25%)
  - Spoofing detection: None
  - Scanner classification: None

Cost: $0 (DShield free API)
```

### After Implementation (Multi-Source):
```
Coverage:
  - Country: 98-99% ("XX" unknown: 1-2%, bogons: 0.5%)
  - ASN: 99-100% ("Not Routed": 0.1%, bogons: 0.5%)
  - Spoofing detection: Yes (RFC1918/bogon)
  - Scanner classification: Yes (GreyNoise)

Cost: $0 (all free sources)
Effort: 9-11 hours implementation
Performance: <3s per 100 IPs (Cymru), <50ms per IP (MaxMind)
```

**ROI**: 25-30% coverage improvement, 100% free, <12 hours effort

---

## Risk Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| MaxMind license revoked | Low | High | Fallback to Cymru ASN |
| Cymru service outage | Low | Medium | Cache hit rate >80%, outage minimal impact |
| DNS resolver rate limits | Medium | Low | Semaphore limits, exponential backoff |
| GreyNoise API changes | Medium | Low | Optional service, graceful skip |
| Disk space (MaxMind DBs) | Low | Low | DBs are ~200MB, manageable |

**Overall Risk**: LOW - All sources are free, fallback chain ensures robustness

---

## Success Metrics

**Phase 0 (Cymru PoC)**:
- [ ] 100% ASN coverage for routable IPs
- [ ] <3 seconds per 100 IPs
- [ ] Cache integration working

**Phase 1-2 (Validation + MaxMind)**:
- [ ] >95% country coverage (down from 20-30% "XX")
- [ ] >95% ASN coverage (down from 15-25% "Not Routed")
- [ ] RFC1918/bogon detection operational

**Phase 3-4 (Monitoring + GreyNoise)**:
- [ ] Enrichment status tracked per session
- [ ] Scanner classification for high-activity IPs
- [ ] Coverage metrics exported to Prometheus

**Phase 5-6 (Schema + Queries)**:
- [ ] Computed columns improve query performance
- [ ] Infrastructure queries run with <1% "XX" countries
- [ ] New spoofing analysis query identifies invalid source IPs

---

## Timeline

**Aggressive** (full-time focus): 2-3 days
**Moderate** (2-3 hours/day): 1 week
**Conservative** (1 hour/day): 2 weeks

**Recommended**: Start with Phase 0 (Cymru PoC) - 2 hours to prove architecture, then decide if full implementation is worth effort.

---

## Next Actions

1. **Review v2.0 Design**: Approve technical approach and cache integration
2. **Phase 0 Implementation**: Build Cymru PoC to validate architecture (2 hours)
3. **Evaluate PoC Results**: Measure cache hit rates, coverage, performance
4. **Decision Point**: Proceed with full implementation or iterate on design

Ready to start Phase 0 (Cymru PoC)?
