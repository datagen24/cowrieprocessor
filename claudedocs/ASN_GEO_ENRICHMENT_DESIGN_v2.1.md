# ASN and Geo Enrichment Design v2.1 (PRODUCTION READY)

**Status**: Final Design - Incorporating Technical Review Feedback
**Date**: 2025-11-03
**Branch**: scp-snowshoe
**Review**: All critical feedback addressed

---

## Revision History

**v2.1 Changes** (technical review feedback):
- ✅ Added `ip_inventory` table for centralized enrichment (75% API call reduction)
- ✅ Changed Cymru cache TTL: infinite → 90 days (catches ASN transfers)
- ✅ Enhanced Cymru whois parser for edge cases (NA fields, NXDOMAIN)
- ✅ Added backfill concurrency control (PostgreSQL advisory locks)
- ✅ Fixed `enrichment_completeness` calculation (excludes intentional skips)
- ✅ Revised backfill estimates (whois bulk: 6-7 hours vs DNS: 16-20 hours)
- ✅ Enhanced GreyNoise filtering heuristics (variety, malware, duration)
- ✅ Comprehensive MaxMind validation (build date, file size, sanity checks)
- ✅ Added cache age metrics for staleness monitoring
- ✅ Fixed `enrichment_sources` SQL bug (jsonb_object_keys usage)
- ✅ GreyNoise UTC midnight reset (predictable budget window)
- ✅ IPv6 deferral documented (Cowrie upstream doesn't support yet)

**Key Architecture Decision**:
- **IP inventory table** as central enrichment store
- **Session-level denormalization** for fast queries
- **Always-current enrichment** (no historical snapshots)

---

## Executive Summary

Designing a **multi-source IP enrichment system** with **IP inventory normalization** and **3-tier caching** to address DShield's coverage gaps ("XX" countries, "Not Routed" ASNs) and add RFC1918/bogon detection for spoofing identification.

**Primary Goal**: Achieve >95% IP classification coverage with multiple fallback sources
**Secondary Goal**: Detect non-routable IPs indicating spoofing/misconfiguration
**Operational Goal**: Zero-cost, fault-tolerant, production-grade enrichment
**Efficiency Goal**: 75% reduction in API calls via IP normalization

---

## Recommended Data Sources (Unchanged)

| Source | Cost | Coverage | Use Case |
|--------|------|----------|----------|
| **MaxMind GeoLite2** | $0 | 99%+ | Primary geo + ASN (offline) |
| **Team Cymru** | $0 | 100% | ASN fallback (DNS/whois) |
| **GreyNoise Community** | $0 | Selective | Scanner classification |
| **RFC1918/Bogon (local)** | $0 | 100% | Spoofing detection |

---

## Architecture: IP Inventory Table (NEW)

### Rationale

**Problem**: Session-level enrichment duplicates work
- Same IP appears in multiple sessions (avg 4 sessions/IP)
- 198K sessions ÷ ~50K unique IPs = 4x redundant API calls
- Enrichment JSON duplicated across sessions (990MB storage)

**Solution**: Centralize enrichment in `ip_inventory` table

**Benefits**:
- ✅ **75% reduction in API calls** (50K vs 198K)
- ✅ **73% reduction in storage** (270MB vs 990MB)
- ✅ **Longitudinal IP analysis** (first_seen, last_seen, session_count)
- ✅ **Single source of truth** for enrichment
- ✅ **Targeted re-enrichment** based on staleness

---

### Schema Design

```sql
-- ============================================================================
-- IP Inventory Table - Centralized Enrichment Store
-- ============================================================================

CREATE TABLE ip_inventory (
    -- Primary key
    ip_address INET PRIMARY KEY,

    -- Temporal tracking
    first_seen TIMESTAMP NOT NULL,
    last_seen TIMESTAMP NOT NULL,
    session_count INTEGER DEFAULT 1,

    -- Enrichment data (normalized, shared across sessions)
    enrichment JSONB NOT NULL DEFAULT '{}'::jsonb,
    enrichment_updated_at TIMESTAMP,
    enrichment_version VARCHAR(10) DEFAULT '2.1',

    -- Computed columns (multi-source fallback)
    geo_country VARCHAR(2) GENERATED ALWAYS AS (
        COALESCE(
            enrichment->'maxmind'->>'country',
            enrichment->'cymru'->>'country',
            enrichment->'dshield'->'ip'->>'ascountry',
            'XX'
        )
    ) STORED,

    asn INTEGER GENERATED ALWAYS AS (
        COALESCE(
            (enrichment->'maxmind'->>'asn')::integer,
            (enrichment->'cymru'->>'asn')::integer,
            (enrichment->'dshield'->'ip'->>'asn')::integer
        )
    ) STORED,

    is_bogon BOOLEAN GENERATED ALWAYS AS (
        COALESCE(
            (enrichment->'validation'->>'is_bogon')::boolean,
            false
        )
    ) STORED,

    is_scanner BOOLEAN GENERATED ALWAYS AS (
        COALESCE(
            (enrichment->'greynoise'->>'noise')::boolean,
            false
        )
    ) STORED,

    -- Enrichment source tracking
    enrichment_sources TEXT[] GENERATED ALWAYS AS (
        ARRAY(
            SELECT key
            FROM jsonb_object_keys(enrichment) AS key
            WHERE key NOT IN ('_meta', 'dshield')  -- Exclude metadata and legacy
        )
    ) STORED,

    -- Enrichment completeness percentage
    enrichment_completeness DECIMAL(5,2) GENERATED ALWAYS AS (
        CASE
            WHEN enrichment->'_meta'->'sources_attempted' IS NULL THEN 0
            ELSE ROUND(
                100.0 *
                jsonb_array_length(enrichment->'_meta'->'sources_succeeded') /
                NULLIF(
                    jsonb_array_length(enrichment->'_meta'->'sources_attempted') -
                    jsonb_array_length(COALESCE(enrichment->'_meta'->'sources_skipped', '[]'::jsonb)),
                    0
                ),
                2
            )
        END
    ) STORED,

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- Indexes for Performance
-- ============================================================================

-- Temporal queries
CREATE INDEX idx_ip_inventory_last_seen
    ON ip_inventory(last_seen);
CREATE INDEX idx_ip_inventory_first_seen
    ON ip_inventory(first_seen);

-- Geographic/ASN analysis
CREATE INDEX idx_ip_inventory_geo_country
    ON ip_inventory(geo_country);
CREATE INDEX idx_ip_inventory_asn
    ON ip_inventory(asn);

-- Threat detection
CREATE INDEX idx_ip_inventory_is_bogon
    ON ip_inventory(is_bogon)
    WHERE is_bogon = true;
CREATE INDEX idx_ip_inventory_is_scanner
    ON ip_inventory(is_scanner)
    WHERE is_scanner = true;

-- Activity analysis
CREATE INDEX idx_ip_inventory_session_count
    ON ip_inventory(session_count);

-- Enrichment gap analysis
CREATE INDEX idx_ip_inventory_enrichment_sources
    ON ip_inventory USING GIN(enrichment_sources);
CREATE INDEX idx_ip_inventory_enrichment_completeness
    ON ip_inventory(enrichment_completeness)
    WHERE enrichment_completeness < 100;

-- Staleness tracking
CREATE INDEX idx_ip_inventory_enrichment_updated_at
    ON ip_inventory(enrichment_updated_at);

-- Full enrichment queries
CREATE INDEX idx_ip_inventory_enrichment
    ON ip_inventory USING GIN(enrichment);

-- ============================================================================
-- Triggers
-- ============================================================================

CREATE TRIGGER update_ip_inventory_updated_at
    BEFORE UPDATE ON ip_inventory
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- Session Summaries Integration
-- ============================================================================

-- Foreign key constraint (ensure referential integrity)
ALTER TABLE session_summaries
    ADD CONSTRAINT fk_source_ip
    FOREIGN KEY (source_ip) REFERENCES ip_inventory(ip_address);

-- Index for JOIN performance
CREATE INDEX idx_session_summaries_source_ip
    ON session_summaries(source_ip);
```

---

### Data Flow with IP Inventory

```
┌─────────────────────────────────────────────────────────┐
│ 0. IP VALIDATION (Local, instant, no cache)            │
│    Python ipaddress.is_private(), is_reserved(), etc.  │
│    └─> RFC1918/Bogon → ip_inventory.enrichment['validation']│
│    └─> is_bogon=true → SKIP all external lookups       │
└──────────────────┬──────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 1. IP INVENTORY CHECK (Staleness-aware)                │
│    SELECT * FROM ip_inventory WHERE ip_address = :ip   │
│    └─> Exists & Fresh → REUSE enrichment (no API call!)│
│    └─> Exists & Stale → Continue to enrichment         │
│    └─> Not Exists → Continue to enrichment             │
└──────────────────┬──────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 2. MAXMIND GEOLITE2 (Offline DB, no external cache)    │
│    Direct DB query: SELECT * FROM maxmind_city/asn     │
│    WHERE ip BETWEEN range_start AND range_end          │
│    └─> Success (99%) → enrichment['maxmind']           │
│    └─> UPSERT into ip_inventory                        │
│    └─> Miss (1%) → Continue to Tier 3                  │
└──────────────────┬──────────────────────────────────────┘
                   │ (only if MaxMind ASN is null)
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 3. TEAM CYMRU (DNS/whois, 3-tier cache, 90-day TTL)    │
│    Cache check: Redis L1 → DB L2 → Disk L3             │
│    Cache miss:                                          │
│      - Bulk mode: whois -h whois.cymru.com (100 IPs)   │
│      - Real-time: asyncio DNS with aiodns (10 concurrent)│
│    └─> Success → enrichment['cymru'], cache 90 days    │
│    └─> UPSERT into ip_inventory                        │
│    └─> Empty response → Mark as "unrouted/bogon"       │
└──────────────────┬──────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 4. GREYNOISE (REST API, 3-tier cache, 7-day TTL)       │
│    Cache check: Redis L1 → DB L2 → Disk L3             │
│    Filter: High-activity sessions only (see heuristics)│
│    Budget check: Daily rate limiter (10K/day UTC reset)│
│    Cache miss + budget available:                       │
│      - GET /v3/community/{ip}                           │
│    └─> Success → enrichment['greynoise'], 7-day TTL    │
│    └─> UPSERT into ip_inventory                        │
│    └─> Skip if: backfill mode OR budget exhausted      │
└──────────────────┬──────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 5. ENRICHMENT METADATA TRACKING                        │
│    enrichment['_meta'] = {                              │
│      "enrichment_version": "2.1",                       │
│      "enrichment_timestamp": "2025-11-03T12:00:00Z",    │
│      "sources_attempted": ["maxmind", "cymru"],         │
│      "sources_succeeded": ["maxmind"],                  │
│      "sources_failed": [],                              │
│      "sources_skipped": ["greynoise"],                  │
│      "skip_reasons": {"greynoise": "low_activity_filter"},│
│      "failure_reasons": {},                             │
│      "cache_hits": {"maxmind": "db_query"},             │
│      "total_duration_ms": 245                           │
│    }                                                     │
│    └─> UPSERT into ip_inventory                        │
└─────────────────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 6. SESSION TEMPORAL TRACKING UPDATE                    │
│    UPDATE ip_inventory SET                              │
│      last_seen = NOW(),                                 │
│      session_count = session_count + 1                  │
│    WHERE ip_address = :ip                               │
└─────────────────────────────────────────────────────────┘
```

---

## Cache Strategy (Updated)

| Source | Redis L1 | DB L2 | Disk L3 | TTL | Rationale |
|--------|----------|-------|---------|-----|-----------|
| **RFC1918** | ❌ Skip | ❌ Skip | ❌ Skip | N/A | Static validation, no cache needed |
| **MaxMind** | ❌ Skip | ✅ ip_inventory | ✅ Yes | Infinite | Offline DB, cache enrichment results forever |
| **Team Cymru** | ✅ Yes | ✅ ip_inventory | ✅ Yes | **90 days** | ASN assignments change quarterly |
| **GreyNoise** | ✅ Yes | ✅ ip_inventory | ✅ Yes | **7 days** | Scanner status changes frequently |
| **DShield** | ✅ Yes | ✅ Yes | ✅ Yes | 7 days | Existing implementation (unchanged) |

**Key Change**: Cymru TTL changed from infinite → **90 days** to catch ASN transfers/acquisitions.

---

## Team Cymru Implementation (DETAILED)

### Method 1: Whois Bulk Interface (Backfill)

```python
import socket
from typing import Optional

def cymru_bulk_lookup(ip_list: list[str], timeout: int = 10) -> dict[str, Optional[dict]]:
    """Query Team Cymru whois for bulk IP-to-ASN mapping.

    Args:
        ip_list: List of IP addresses (max 100 recommended)
        timeout: Socket timeout in seconds

    Returns:
        Dict mapping IP to {"asn": int, "prefix": str, "country": str, ...}
        Returns None for IPs that are unallocated/bogon.
    """
    # Format: "begin\nverbose\n{ip1}\n{ip2}\n...\nend\n"
    query = "begin\nverbose\n" + "\n".join(ip_list) + "\nend\n"

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)

    try:
        sock.connect(("whois.cymru.com", 43))
        sock.sendall(query.encode())

        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk

    except socket.timeout:
        logger.error(f"Cymru whois timeout after {timeout}s")
        return {}
    except Exception as e:
        logger.error(f"Cymru whois connection error: {e}")
        return {}
    finally:
        sock.close()

    return _parse_cymru_response(response.decode())


def _parse_cymru_response(response: str) -> dict[str, Optional[dict]]:
    """Parse Cymru whois response with robust error handling.

    Response format:
    AS      | IP               | BGP Prefix          | CC | Registry | Allocated
    13335   | 1.0.0.1          | 1.0.0.0/24         | US | arin     | 2010-07-14
    NA      | 192.168.1.1      | NA                 | NA | NA       | NA

    Edge cases:
    - Unallocated IPs: ASN="NA", all fields "NA"
    - Bogons: "No ASN" or "not routed" messages
    - Reserved: Special handling for RFC1918 (should be pre-filtered)
    """
    results = {}

    for line in response.split("\n"):
        # Skip header and empty lines
        if "|" not in line or line.startswith("AS"):
            continue

        # Check for error messages
        if "No ASN" in line or "not routed" in line.lower():
            # Extract IP from error message if present
            # Example: "No ASN available for 192.168.1.1"
            continue

        parts = [p.strip() for p in line.split("|")]

        if len(parts) >= 6:
            asn_str, ip, prefix, cc, registry, allocated = parts[:6]

            # Skip if ASN is "NA" (unallocated) - return None for this IP
            if asn_str == "NA":
                results[ip] = None
                continue

            results[ip] = {
                "asn": int(asn_str) if asn_str.isdigit() else None,
                "bgp_prefix": prefix if prefix != "NA" else None,
                "country": cc if cc != "NA" and len(cc) == 2 else None,
                "registry": registry if registry != "NA" else None,
                "allocated": allocated if allocated != "NA" else None
            }

    return results
```

---

### Method 2: Asyncio DNS (Real-Time)

```python
import asyncio
import aiodns
from typing import Optional

class CymruDNSResolver:
    """Async DNS resolver for Team Cymru IP-to-ASN lookups.

    Features:
    - Concurrent queries with semaphore rate limiting
    - 3-second timeout per query
    - Exponential backoff on DNS timeouts
    - 90-day cache TTL integration
    """

    def __init__(self, concurrency_limit: int = 10):
        self.resolver = aiodns.DNSResolver()
        self.semaphore = asyncio.Semaphore(concurrency_limit)
        self.cache_ttl_days = 90

    async def lookup_ip(self, ip: str) -> Optional[dict]:
        """Async DNS query for single IP with error handling."""
        # Reverse IP: 1.2.3.4 → 4.3.2.1.origin.asn.cymru.com
        reversed_ip = ".".join(ip.split(".")[::-1])
        query_domain = f"{reversed_ip}.origin.asn.cymru.com"

        async with self.semaphore:  # Rate limit concurrent queries
            try:
                # Query TXT record with timeout
                result = await asyncio.wait_for(
                    self.resolver.query(query_domain, "TXT"),
                    timeout=3.0  # 3 second timeout per query
                )

                # Parse response: "13335 | 1.0.0.0/24 | US | arin | 2010-07-14"
                txt_value = result[0].text.decode()
                parts = [p.strip() for p in txt_value.split("|")]

                if len(parts) >= 5:
                    asn_str, prefix, cc, registry, allocated = parts[:5]

                    # Check for "NA" (unallocated)
                    if asn_str == "NA":
                        return None

                    return {
                        "asn": int(asn_str) if asn_str.isdigit() else None,
                        "bgp_prefix": prefix if prefix != "NA" else None,
                        "country": cc if cc != "NA" and len(cc) == 2 else None,
                        "registry": registry if registry != "NA" else None,
                        "allocated": allocated if allocated != "NA" else None
                    }
                else:
                    logger.warning(f"Cymru response malformed for {ip}: {txt_value}")
                    return None

            except asyncio.TimeoutError:
                # DNS timeout - might be rate limiting or network issue
                logger.warning(f"Cymru DNS timeout for {ip}")
                await asyncio.sleep(0.5)  # Backoff before next query
                return None
            except aiodns.error.DNSError as e:
                # NXDOMAIN = unrouted/bogon (expected for invalid IPs)
                if e.args[0] == aiodns.error.ARES_ENOTFOUND:
                    logger.debug(f"Cymru NXDOMAIN for {ip} (unrouted/bogon)")
                    return None
                else:
                    logger.error(f"Cymru DNS error for {ip}: {e}")
                    return None
            except Exception as e:
                logger.error(f"Unexpected Cymru error for {ip}: {e}")
                return None

    async def lookup_batch(self, ip_list: list[str]) -> dict[str, Optional[dict]]:
        """Lookup multiple IPs concurrently with semaphore rate limiting."""
        tasks = [self.lookup_ip(ip) for ip in ip_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            ip: result
            for ip, result in zip(ip_list, results)
            if not isinstance(result, Exception)
        }
```

---

## Enrichment Workflow (IP Inventory Integration)

### Enrichment Function

```python
from datetime import datetime, timedelta, timezone
import json

def enrich_ip(ip_address: str, session_id: str = None) -> dict:
    """Enrich IP with multi-source data using IP inventory.

    Workflow:
    1. Check ip_inventory for existing enrichment
    2. Determine if re-enrichment needed (staleness check)
    3. If needed, enrich with RFC1918 → MaxMind → Cymru → GreyNoise
    4. UPSERT into ip_inventory
    5. Return enrichment data

    Args:
        ip_address: IP to enrich
        session_id: Optional session ID for temporal tracking

    Returns:
        Complete enrichment dict from ip_inventory
    """

    # Step 1: Check ip_inventory
    ip_record = db.execute(
        "SELECT * FROM ip_inventory WHERE ip_address = :ip",
        {"ip": ip_address}
    ).fetchone()

    # Step 2: Staleness check
    needs_enrichment = (
        ip_record is None or
        ip_record.enrichment_updated_at is None or
        _enrichment_is_stale(ip_record)
    )

    if needs_enrichment:
        logger.info(f"Enriching {ip_address} (stale or missing)")

        # Step 3: Perform multi-source enrichment
        enrichment = _multi_source_enrich(ip_address, session_id)

        # Step 4: UPSERT into ip_inventory
        now = datetime.now(timezone.utc)
        db.execute("""
            INSERT INTO ip_inventory (
                ip_address, first_seen, last_seen,
                session_count, enrichment, enrichment_updated_at, enrichment_version
            )
            VALUES (:ip, :now, :now, 1, :enrichment, :now, '2.1')
            ON CONFLICT (ip_address) DO UPDATE SET
                last_seen = :now,
                session_count = ip_inventory.session_count + 1,
                enrichment = :enrichment,
                enrichment_updated_at = :now,
                enrichment_version = '2.1',
                updated_at = :now
        """, {
            "ip": ip_address,
            "now": now,
            "enrichment": json.dumps(enrichment)
        })
        db.commit()

        # Reload to get computed columns
        ip_record = db.execute(
            "SELECT * FROM ip_inventory WHERE ip_address = :ip",
            {"ip": ip_address}
        ).fetchone()

    else:
        # Just update temporal tracking (no re-enrichment needed)
        logger.debug(f"Reusing enrichment for {ip_address} (fresh)")
        now = datetime.now(timezone.utc)
        db.execute("""
            UPDATE ip_inventory SET
                last_seen = :now,
                session_count = session_count + 1,
                updated_at = :now
            WHERE ip_address = :ip
        """, {"ip": ip_address, "now": now})
        db.commit()

    return ip_record


def _enrichment_is_stale(ip_record) -> bool:
    """Determine if enrichment needs refresh based on source-specific TTLs.

    TTL Strategy:
    - GreyNoise: 7 days (scanner status changes)
    - Cymru: 90 days (ASN assignments change quarterly)
    - MaxMind: Infinite (offline DB, refresh via weekly cron)
    - RFC1918: Never stale (static validation)
    """
    if not ip_record.enrichment_updated_at:
        return True

    age = datetime.now(timezone.utc) - ip_record.enrichment_updated_at
    enrichment = ip_record.enrichment

    # GreyNoise exists and is stale (7-day TTL)
    if enrichment.get('greynoise'):
        if age > timedelta(days=7):
            logger.debug(f"GreyNoise stale for {ip_record.ip_address} (age: {age.days} days)")
            return True

    # Cymru/MaxMind exists but is stale (90-day TTL)
    if enrichment.get('cymru') or enrichment.get('maxmind'):
        if age > timedelta(days=90):
            logger.info(f"Cymru/MaxMind stale for {ip_record.ip_address} (age: {age.days} days)")
            return True

    # No enrichment at all
    if not enrichment or enrichment == {}:
        return True

    # Enrichment is fresh
    return False


def _multi_source_enrich(ip_address: str, session_id: str = None) -> dict:
    """Perform multi-source enrichment with fallback chain.

    Order:
    1. RFC1918/Bogon validation (local, instant)
    2. MaxMind GeoLite2 (offline DB, fast)
    3. Team Cymru (DNS/whois, free)
    4. GreyNoise (API, rate-limited, filtered)

    Returns:
        Complete enrichment dict with _meta tracking
    """
    enrichment = {}
    meta = {
        "enrichment_version": "2.1",
        "enrichment_timestamp": datetime.now(timezone.utc).isoformat(),
        "sources_attempted": [],
        "sources_succeeded": [],
        "sources_failed": [],
        "sources_skipped": [],
        "skip_reasons": {},
        "failure_reasons": {},
        "cache_hits": {},
        "total_duration_ms": 0
    }

    start_time = datetime.now()

    # 1. RFC1918/Bogon Validation
    validation = validate_ip(ip_address)
    enrichment["validation"] = validation

    if validation["is_bogon"]:
        logger.info(f"{ip_address} is bogon, skipping external enrichment")
        meta["sources_skipped"] = ["maxmind", "cymru", "greynoise"]
        meta["skip_reasons"] = {
            "maxmind": "bogon_detected",
            "cymru": "bogon_detected",
            "greynoise": "bogon_detected"
        }
        enrichment["_meta"] = meta
        return enrichment

    # 2. MaxMind GeoLite2
    meta["sources_attempted"].append("maxmind")
    maxmind_result = maxmind_handler.lookup(ip_address)

    if maxmind_result:
        enrichment["maxmind"] = maxmind_result
        meta["sources_succeeded"].append("maxmind")
        meta["cache_hits"]["maxmind"] = "db_query"
    else:
        meta["sources_failed"].append("maxmind")
        meta["failure_reasons"]["maxmind"] = "ip_not_found_or_db_unavailable"

    # 3. Team Cymru (fallback if MaxMind ASN missing)
    if not enrichment.get("maxmind", {}).get("asn"):
        meta["sources_attempted"].append("cymru")

        # Check 3-tier cache first
        cymru_cached = cache_manager.get_cached("cymru", ip_address)

        if cymru_cached:
            enrichment["cymru"] = cymru_cached
            meta["sources_succeeded"].append("cymru")
            meta["cache_hits"]["cymru"] = "redis_l1"  # Or "db_l2", "disk_l3"
        else:
            # Cache miss - query Cymru
            cymru_result = cymru_resolver.lookup_ip(ip_address)

            if cymru_result:
                enrichment["cymru"] = cymru_result
                meta["sources_succeeded"].append("cymru")

                # Cache for 90 days
                cache_manager.store_cached(
                    "cymru",
                    ip_address,
                    cymru_result,
                    ttl_seconds=90 * 86400
                )
            else:
                meta["sources_failed"].append("cymru")
                meta["failure_reasons"]["cymru"] = "nxdomain_or_timeout"

    # 4. GreyNoise (filtered, rate-limited)
    if _should_query_greynoise(session_id):
        meta["sources_attempted"].append("greynoise")

        if greynoise_rate_limiter.allow_request():
            # Check cache first
            greynoise_cached = cache_manager.get_cached("greynoise", ip_address)

            if greynoise_cached:
                enrichment["greynoise"] = greynoise_cached
                meta["sources_succeeded"].append("greynoise")
                meta["cache_hits"]["greynoise"] = "redis_l1"
            else:
                # Cache miss - query API
                greynoise_result = greynoise_handler.lookup(ip_address)

                if greynoise_result:
                    enrichment["greynoise"] = greynoise_result
                    meta["sources_succeeded"].append("greynoise")

                    # Cache for 7 days
                    cache_manager.store_cached(
                        "greynoise",
                        ip_address,
                        greynoise_result,
                        ttl_seconds=7 * 86400
                    )
                else:
                    meta["sources_failed"].append("greynoise")
                    meta["failure_reasons"]["greynoise"] = "api_error"
        else:
            meta["sources_skipped"].append("greynoise")
            meta["skip_reasons"]["greynoise"] = "daily_budget_exhausted"
    else:
        meta["sources_skipped"].append("greynoise")
        meta["skip_reasons"]["greynoise"] = "low_activity_filter"

    # Record duration
    duration = (datetime.now() - start_time).total_seconds() * 1000
    meta["total_duration_ms"] = round(duration, 2)

    enrichment["_meta"] = meta
    return enrichment


def _should_query_greynoise(session_id: str = None) -> bool:
    """Enhanced filter for GreyNoise queries.

    Prioritizes:
    - High-activity sessions (manual attackers, not automated scans)
    - Command variety (sophisticated attacks)
    - Malware downloads (confirmed threats)
    - Long-duration sessions (persistent access)

    Returns:
        True if session warrants GreyNoise lookup
    """
    if not session_id:
        return False

    session = db.execute(
        "SELECT * FROM session_summaries WHERE session_id = :id",
        {"id": session_id}
    ).fetchone()

    if not session:
        return False

    return any([
        session.command_count >= 10,            # High activity
        session.file_download_count >= 5,       # Multiple malware downloads
        session.vt_flagged,                     # VirusTotal confirmed malware
        session.duration_seconds >= 300,        # 5+ minute sessions (manual)
        session.unique_commands >= 5            # Command variety suggests sophistication
    ])
```

---

## GreyNoise Rate Limiter (UTC Reset)

```python
from datetime import datetime, timedelta, timezone

class GreyNoiseRateLimiter:
    """Daily rate limiter for GreyNoise Community API (10K/day free tier).

    Features:
    - UTC midnight reset (predictable budget window)
    - Persistent counter (survives process restarts)
    - 90% warning threshold
    """

    def __init__(self, daily_limit: int = 10000):
        self.daily_limit = daily_limit
        self.daily_usage = self._load_usage()
        self.reset_time = self._calculate_next_reset()

    def _calculate_next_reset(self) -> datetime:
        """Calculate next UTC midnight."""
        now = datetime.now(tz=timezone.utc)
        next_midnight = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        return next_midnight

    def _load_usage(self) -> int:
        """Load daily usage from persistent storage (Redis or DB)."""
        today_key = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        usage = cache_manager.get(f"greynoise_usage:{today_key}")
        return int(usage) if usage else 0

    def _save_usage(self):
        """Save daily usage to persistent storage."""
        today_key = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        cache_manager.set(
            f"greynoise_usage:{today_key}",
            self.daily_usage,
            ttl_seconds=86400  # Expire after 24 hours
        )

    def allow_request(self) -> bool:
        """Check if request is allowed within daily budget.

        Returns:
            True if budget allows, False if exhausted
        """
        now = datetime.now(tz=timezone.utc)

        # Reset counter if past midnight UTC
        if now >= self.reset_time:
            self.daily_usage = 0
            self.reset_time = self._calculate_next_reset()

        # Check if budget exhausted
        if self.daily_usage >= self.daily_limit:
            logger.warning(f"GreyNoise daily budget exhausted ({self.daily_usage}/{self.daily_limit})")
            return False

        # Warning at 90% usage
        if self.daily_usage >= self.daily_limit * 0.9:
            logger.warning(f"GreyNoise budget 90% exhausted ({self.daily_usage}/{self.daily_limit})")

        # Increment and allow
        self.daily_usage += 1
        self._save_usage()

        return True
```

---

## MaxMind Validation (Comprehensive)

```python
import os
from datetime import datetime
import geoip2.database

def validate_maxmind_db(db_path: str) -> bool:
    """Validate MaxMind DB integrity with comprehensive checks.

    Checks:
    1. Known IP resolves correctly (8.8.8.8 → US)
    2. Database build date is recent (< 30 days old)
    3. File size sanity check (GeoLite2-City ~70MB, ASN ~5MB)

    Returns:
        True if validation passed, False otherwise
    """
    try:
        reader = geoip2.database.Reader(db_path)

        # Test 1: Known IP resolves correctly
        result = reader.city('8.8.8.8')
        if result.country.iso_code != 'US':
            logger.error(f"MaxMind sanity check failed: 8.8.8.8 returned {result.country.iso_code}, expected US")
            reader.close()
            return False

        # Test 2: Database build date is recent (< 30 days old)
        metadata = reader.metadata()
        build_date = datetime.fromtimestamp(metadata.build_epoch)
        age_days = (datetime.now() - build_date).days

        if age_days > 30:
            logger.error(f"MaxMind DB is {age_days} days old (stale, expected <30 days)")
            reader.close()
            return False

        # Test 3: File size sanity check
        file_size_mb = os.path.getsize(db_path) / (1024 * 1024)

        if "City" in db_path:
            expected_min_size = 50  # GeoLite2-City ~70MB
        elif "ASN" in db_path:
            expected_min_size = 3   # GeoLite2-ASN ~5MB
        else:
            expected_min_size = 1   # Generic minimum

        if file_size_mb < expected_min_size:
            logger.error(f"MaxMind DB suspiciously small: {file_size_mb:.1f}MB (expected >{expected_min_size}MB)")
            reader.close()
            return False

        reader.close()
        logger.info(f"MaxMind DB validation passed: {db_path} ({file_size_mb:.1f}MB, {age_days} days old)")
        return True

    except Exception as e:
        logger.error(f"MaxMind validation failed: {e}")
        return False
```

---

## Backfill Strategy

### Backfill with Advisory Lock

```python
import asyncio
from typing import Optional

async def backfill_multi_source_enrichment(
    batch_size: int = 1000,
    skip_greynoise: bool = True,  # Skip during backfill
    method: str = "whois"  # "whois" or "dns"
):
    """Backfill existing IPs with multi-source enrichment.

    Uses PostgreSQL advisory lock to prevent concurrent runs.
    """

    # Try to acquire lock, skip if another process is running
    lock_acquired = db.execute(
        "SELECT pg_try_advisory_lock(hashtext('enrichment_backfill'))"
    ).scalar()

    if not lock_acquired:
        logger.info("Another backfill process is running, exiting")
        return

    try:
        logger.info("Starting backfill with advisory lock acquired")

        while True:
            # Find IPs needing enrichment (prioritize by activity)
            query = """
                SELECT ip_address, session_count
                FROM ip_inventory
                WHERE
                    (enrichment_updated_at IS NULL
                     OR enrichment_updated_at < NOW() - INTERVAL '90 days')
                    AND last_seen > NOW() - INTERVAL '30 days'  -- Active in last 30 days
                ORDER BY session_count DESC, last_seen DESC
                LIMIT :batch_size
            """

            ips = db.execute(query, {"batch_size": batch_size}).fetchall()

            if not ips:
                logger.info("No more IPs to enrich")
                break

            ip_list = [ip.ip_address for ip in ips]
            logger.info(f"Enriching batch of {len(ip_list)} IPs (method: {method})")

            # Batch enrich
            if method == "whois" and len(ip_list) >= 100:
                # Use whois bulk for large batches (faster)
                cymru_results = cymru_bulk_lookup(ip_list)
            else:
                # Use async DNS for small batches
                cymru_results = await cymru_resolver.lookup_batch(ip_list)

            # Process results
            for ip_address in ip_list:
                try:
                    enrichment = _multi_source_enrich(
                        ip_address,
                        session_id=None  # No specific session for backfill
                    )

                    # UPSERT into ip_inventory
                    db.execute("""
                        UPDATE ip_inventory SET
                            enrichment = :enrichment,
                            enrichment_updated_at = NOW(),
                            enrichment_version = '2.1',
                            updated_at = NOW()
                        WHERE ip_address = :ip
                    """, {
                        "ip": ip_address,
                        "enrichment": json.dumps(enrichment)
                    })

                except Exception as e:
                    logger.error(f"Enrichment failed for {ip_address}: {e}")
                    continue

            db.commit()
            logger.info(f"Enriched {len(ip_list)} IPs")

            # Brief pause between batches
            await asyncio.sleep(1)

    finally:
        # Always release lock
        db.execute("SELECT pg_advisory_unlock(hashtext('enrichment_backfill'))")
        logger.info("Backfill complete, lock released")
```

### Estimated Backfill Time

**Scenario**: 198K sessions → ~50K unique IPs

| Method | Cache State | Time Estimate | Rationale |
|--------|-------------|---------------|-----------|
| **Whois Bulk** | Cold (0% cache) | **6-7 hours** | 50K IPs ÷ 100/batch = 500 batches × 50s/batch |
| **Whois Bulk** | Warm (80% cache) | **1-2 hours** | Only 10K IPs need API calls |
| **Async DNS** | Cold (0% cache) | 16-20 hours | 50K IPs ÷ 100/batch = 500 batches × 3min/batch (cold DNS) |
| **Async DNS** | Warm (80% cache) | **10-15 minutes** | Mostly cache hits, <100ms/IP |

**Recommendation**: Use **whois bulk for initial backfill**, then switch to async DNS for daily incremental updates.

---

## Monitoring Metrics (Enhanced)

### Prometheus Metrics

```python
from prometheus_client import Counter, Histogram, Gauge

# Success/failure rates per source
enrichment_source_success_total = Counter(
    'enrichment_source_success_total',
    'Successful enrichments by source',
    ['source']
)

enrichment_source_failures_total = Counter(
    'enrichment_source_failures_total',
    'Failed enrichments by source',
    ['source', 'reason']
)

# Cache hit rates by tier
enrichment_cache_hits_total = Counter(
    'enrichment_cache_hits_total',
    'Cache hits by source and tier',
    ['source', 'tier']
)

# Cache age (staleness monitoring) ⭐ NEW
enrichment_cache_age_seconds = Histogram(
    'enrichment_cache_age_seconds',
    'Age of cached enrichment data',
    ['source'],
    buckets=[
        3600,      # 1 hour
        86400,     # 1 day
        604800,    # 7 days
        2592000,   # 30 days
        5184000,   # 60 days
        7776000,   # 90 days
        15552000   # 180 days
    ]
)

# Coverage metrics
enrichment_coverage_ratio = Gauge(
    'enrichment_coverage_ratio',
    'Percentage of IPs with valid data',
    ['field']
)

# Performance
enrichment_duration_seconds = Histogram(
    'enrichment_duration_seconds',
    'Time to enrich IP',
    ['source'],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
)

# IP inventory stats ⭐ NEW
ip_inventory_total_ips = Gauge(
    'ip_inventory_total_ips',
    'Total unique IPs in inventory'
)

ip_inventory_enriched_ips = Gauge(
    'ip_inventory_enriched_ips',
    'IPs with non-empty enrichment'
)

ip_inventory_stale_ips = Gauge(
    'ip_inventory_stale_ips',
    'IPs needing re-enrichment (>90 days)'
)


def record_enrichment_metrics(ip_record, enrichment):
    """Record metrics after enrichment."""

    # Record cache age if enrichment existed
    if ip_record and ip_record.enrichment_updated_at:
        for source in enrichment.get("_meta", {}).get("sources_succeeded", []):
            age_seconds = (datetime.now(timezone.utc) - ip_record.enrichment_updated_at).total_seconds()
            enrichment_cache_age_seconds.labels(source=source).observe(age_seconds)

    # Record success/failure
    for source in enrichment.get("_meta", {}).get("sources_succeeded", []):
        enrichment_source_success_total.labels(source=source).inc()

    for source, reason in enrichment.get("_meta", {}).get("failure_reasons", {}).items():
        enrichment_source_failures_total.labels(source=source, reason=reason).inc()

    # Record cache hits
    for source, tier in enrichment.get("_meta", {}).get("cache_hits", {}).items():
        enrichment_cache_hits_total.labels(source=source, tier=tier).inc()

    # Update coverage metrics (run periodically)
    update_coverage_metrics()


def update_coverage_metrics():
    """Update coverage metrics from ip_inventory (run every 5 minutes)."""

    stats = db.execute("""
        SELECT
            COUNT(*) as total_ips,
            COUNT(*) FILTER (WHERE geo_country != 'XX') as has_country,
            COUNT(*) FILTER (WHERE asn IS NOT NULL) as has_asn,
            COUNT(*) FILTER (WHERE enrichment != '{}'::jsonb) as enriched,
            COUNT(*) FILTER (WHERE enrichment_updated_at < NOW() - INTERVAL '90 days') as stale
        FROM ip_inventory
    """).fetchone()

    # Update gauges
    ip_inventory_total_ips.set(stats.total_ips)
    ip_inventory_enriched_ips.set(stats.enriched)
    ip_inventory_stale_ips.set(stats.stale)

    # Coverage ratios
    if stats.total_ips > 0:
        enrichment_coverage_ratio.labels(field="country").set(stats.has_country / stats.total_ips)
        enrichment_coverage_ratio.labels(field="asn").set(stats.has_asn / stats.total_ips)
```

---

## Alert Thresholds

### Prometheus Alerting Rules

```yaml
groups:
  - name: enrichment_alerts
    interval: 5m
    rules:
      # Coverage alerts
      - alert: EnrichmentCoverageLow
        expr: enrichment_coverage_ratio{field="country"} < 0.95
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Country enrichment coverage below 95%"
          description: "Only {{ $value | humanizePercentage }} of IPs have country data"

      - alert: EnrichmentASNCoverageLow
        expr: enrichment_coverage_ratio{field="asn"} < 0.95
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "ASN enrichment coverage below 95%"
          description: "Only {{ $value | humanizePercentage }} of IPs have ASN data"

      # Source failure alerts
      - alert: EnrichmentSourceFailureRateHigh
        expr: |
          rate(enrichment_source_failures_total[5m]) /
          (rate(enrichment_source_success_total[5m]) + rate(enrichment_source_failures_total[5m])) > 0.10
        for: 15m
        labels:
          severity: critical
        annotations:
          summary: "{{ $labels.source }} enrichment failure rate >10%"
          description: "Source {{ $labels.source }} failing {{ $value | humanizePercentage }} of requests"

      # MaxMind DB staleness
      - alert: MaxMindDBStale
        expr: |
          (time() - max_over_time(maxmind_db_build_timestamp[1h])) / 86400 > 30
        for: 1h
        labels:
          severity: critical
        annotations:
          summary: "MaxMind DB not updated in >30 days"
          description: "MaxMind database is {{ $value }} days old"

      # GreyNoise budget
      - alert: GreyNoiseBudgetNearExhausted
        expr: greynoise_daily_usage / greynoise_daily_limit > 0.90
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "GreyNoise daily budget 90% exhausted"
          description: "Used {{ $value | humanizePercentage }} of daily 10K quota"

      # Cache staleness (Cymru) ⭐ NEW
      - alert: CymruCacheStale
        expr: |
          histogram_quantile(0.95, enrichment_cache_age_seconds{source="cymru"}) / 86400 > 80
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Cymru cache age p95 >80 days"
          description: "95th percentile cache age is {{ $value }} days (approaching 90-day TTL)"

      # IP inventory completeness ⭐ NEW
      - alert: IPInventoryCompletenessLow
        expr: |
          (
            SELECT AVG(enrichment_completeness)
            FROM ip_inventory
            WHERE last_seen > NOW() - INTERVAL '7 days'
          ) < 80
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "IP inventory enrichment completeness <80% for active IPs"
          description: "Average completeness is {{ $value }}% for IPs active in last 7 days"
```

---

## Revised Implementation Plan

### **Phase 0.5: IP Inventory Table (2 hours)** ⭐ FIRST PRIORITY

**Work Ticket**: `feat(db): add ip_inventory table for centralized enrichment`

**Tasks**:
1. Create `ip_inventory` schema with computed columns
2. Add foreign key constraint from `session_summaries` to `ip_inventory`
3. Create indexes for common query patterns
4. Add `update_updated_at_column()` trigger function
5. Write migration script to populate from existing `session_summaries`
6. Verify migration: check `session_count` accuracy
7. Document enrichment workflow changes

**Success Criteria**:
- [ ] All unique IPs from sessions migrated to `ip_inventory`
- [ ] `session_count` matches actual session count per IP
- [ ] Enrichment data preserved from most recent sessions
- [ ] Foreign key constraint enforced
- [ ] Query performance validated (JOIN vs denormalized columns)

**Deliverable**: Populated `ip_inventory` table ready for enrichment workflow

**Migration Script**:
```sql
-- Populate ip_inventory from session_summaries
INSERT INTO ip_inventory (
    ip_address,
    first_seen,
    last_seen,
    session_count,
    enrichment,
    enrichment_updated_at,
    enrichment_version
)
SELECT
    source_ip,
    MIN(first_event_at) as first_seen,
    MAX(last_event_at) as last_seen,
    COUNT(*) as session_count,
    -- Use most recent non-empty enrichment
    (
        SELECT enrichment
        FROM session_summaries s2
        WHERE s2.source_ip = s1.source_ip
          AND s2.enrichment IS NOT NULL
          AND s2.enrichment != '{}'::jsonb
        ORDER BY s2.last_event_at DESC
        LIMIT 1
    ) as enrichment,
    MAX(last_event_at) as enrichment_updated_at,
    '2.1' as enrichment_version
FROM session_summaries s1
GROUP BY source_ip
ON CONFLICT (ip_address) DO NOTHING;
```

---

### **Phase 0: Team Cymru PoC (2 hours)** ⭐ SECOND PRIORITY

**Work Ticket**: `feat(enrichment): Team Cymru IP-to-ASN PoC with ip_inventory`

**Tasks**:
1. Implement asyncio DNS resolver with `aiodns`
2. Implement whois bulk method for large batches
3. Add edge case handling (NA fields, NXDOMAIN)
4. Add concurrency semaphore (10 concurrent queries)
5. Integrate with `ip_inventory` (UPSERT enrichment)
6. Integrate with 3-tier cache (Redis→DB→Disk, 90-day TTL)
7. Add staleness checking before re-enrichment
8. Test with 1,000 IPs from `ip_inventory`
9. Measure cache hit rates, performance, and API call reduction

**Success Criteria**:
- [ ] 100% ASN coverage for routable IPs
- [ ] <3 seconds for 100 IPs (whois bulk, cold cache)
- [ ] <0.5 seconds for 100 IPs (async DNS, warm cache)
- [ ] NXDOMAIN responses correctly identify bogons
- [ ] 75%+ reduction in API calls vs session-level enrichment
- [ ] NA field handling doesn't crash parser

**Deliverable**: Working Cymru enrichment with `ip_inventory` integration

---

### **Phase 1: RFC1918/Bogon Detection (1 hour)**

**Work Ticket**: `feat(enrichment): add RFC1918/bogon IP validation`

**Tasks**:
1. Create `cowrieprocessor/enrichment/ip_validator.py`
2. Add `validate_ip()` function using Python `ipaddress` library
3. Check: `is_private`, `is_reserved`, `is_loopback`, `is_multicast`, `is_bogon`
4. Return early if bogon (skip all external enrichments)
5. Add `enrichment['validation']` field to `ip_inventory`
6. Add IPv6 deferral comment (Cowrie upstream doesn't support yet)
7. Add test cases for all RFC ranges (RFC1918, RFC5735, etc.)

**Success Criteria**:
- [ ] RFC1918 IPs detected (192.168.x.x, 10.x.x.x, 172.16-31.x.x)
- [ ] Bogons detected (0.0.0.0/8, 127.0.0.0/8, 169.254.0.0/16, etc.)
- [ ] All bogons skip external API calls (performance optimization)
- [ ] Validation results stored in `ip_inventory`

---

### **Phase 2: MaxMind GeoLite2 Integration (2-3 hours)**

**Work Ticket**: `feat(enrichment): integrate MaxMind GeoLite2 offline DB`

**Tasks**:
1. Download MaxMind GeoLite2 City + ASN databases
2. Implement `cowrieprocessor/enrichment/maxmind_handler.py`
3. Add comprehensive database validation (build date, file size, sanity checks)
4. Add graceful fallback to Cymru on MaxMind failure
5. Store results in `ip_inventory` enrichment JSON
6. Cache results in `ip_inventory` (infinite TTL for MaxMind)
7. Create `scripts/production/refresh_maxmind.sh` with enhanced validation
8. Set up weekly cron job with email alerts

**Success Criteria**:
- [ ] 99%+ country coverage
- [ ] 95%+ ASN coverage
- [ ] <50ms query latency
- [ ] Graceful fallback to Cymru on MaxMind failure
- [ ] DB validation catches corruption and staleness (build date <30 days)
- [ ] File size sanity check (City >50MB, ASN >3MB)

---

### **Phase 3: Enrichment Status Tracking (1 hour)**

**Work Ticket**: `feat(enrichment): add enrichment metadata and monitoring`

**Tasks**:
1. Add `enrichment['_meta']` field with source tracking
2. Record attempted/succeeded/failed/**skipped** sources
3. Add `skip_reasons` for transparency (low_activity_filter, bogon_detected, etc.)
4. Add `failure_reasons` with detailed error context
5. Add cache hit tracking per source (redis_l1, db_l2, disk_l3)
6. Implement Prometheus metrics for monitoring (including cache age)
7. Update computed columns: add `enrichment_sources`, fix `enrichment_completeness`
8. Add alerting thresholds (coverage <95%, failures >10%, cache staleness)

**Success Criteria**:
- [ ] Can query: "Which IPs only have DShield data?"
- [ ] `enrichment_completeness` calculation excludes intentional skips
- [ ] Metrics show cache hit rates and freshness per source
- [ ] Alerts fire on MaxMind DB staleness (>30 days)
- [ ] Cache age p95 metric tracks Cymru staleness

---

### **Phase 4: GreyNoise Scanner Detection (2 hours)**

**Work Ticket**: `feat(enrichment): add GreyNoise scanner classification`

**Tasks**:
1. Implement `cowrieprocessor/enrichment/greynoise_handler.py`
2. Add REST API client with 3-tier cache (7-day TTL)
3. Implement daily rate limiter with UTC midnight reset
4. Add enhanced filtering heuristics:
   - `≥10 commands` OR
   - `≥5 file downloads` OR
   - `vt_flagged = true` OR
   - `duration ≥300 seconds` OR
   - `unique_commands ≥5`
5. Add backfill skip flag (`skip_greynoise=True`)
6. Store results in `ip_inventory` enrichment JSON
7. Add re-enrichment query for active scanners (last 7 days)

**Success Criteria**:
- [ ] Scanner tags for high-activity IPs
- [ ] Daily budget never exceeded (monitor at 90% warning)
- [ ] Backfill mode skips GreyNoise entirely
- [ ] Enhanced filter reduces false positives (no trivial scans)
- [ ] UTC midnight reset works predictably

---

### **Phase 5: Database Migration and Computed Columns (1 hour)**

**Work Ticket**: `feat(db): add multi-source enrichment computed columns to session_summaries`

**Tasks**:
1. Create migration for computed columns in `session_summaries`
2. Fix `enrichment_sources` extraction bug (proper `jsonb_object_keys` usage)
3. Update `enrichment_completeness` formula (exclude skipped sources)
4. Add indexes on `geo_country`, `asn`, `is_bogon`, `is_scanner`
5. Add partial indexes for gap analysis
6. Add index on `source_ip` for JOIN performance
7. Update schema version to 11
8. Test computed column fallback logic (MaxMind → Cymru → DShield)
9. Verify query performance improvement vs JSON path extraction

---

### **Phase 6: Query Updates (1 hour)**

**Work Ticket**: `fix(queries): use multi-source enrichment fallback with ip_inventory`

**Tasks**:
1. Update Query 11: Use `geo_country` with JOIN to `ip_inventory`
2. Update Query 12: Use `asn` computed column with JOIN
3. Create Query 15: Spoofing analysis (`WHERE is_bogon = true`)
4. Create Query 16: Scanner classification (`WHERE is_scanner = true`)
5. Create Query 17: IP reputation dashboard (direct `ip_inventory` query)
6. Create Query 18: Botnet detection (ASN clustering analysis)
7. Test all queries with updated schema
8. Document JOIN vs denormalized column performance trade-offs

---

### **Phase 7: Backfill Execution (Variable Time)**

**Work Ticket**: `ops(enrichment): backfill historical data with multi-source enrichment`

**Tasks**:
1. Implement advisory lock for backfill process (prevent concurrent runs)
2. Use **whois bulk** for initial cold-cache enrichment (6-7 hours)
3. Run backfill in batches of 1000 IPs (prioritize by session_count DESC)
4. Monitor progress and cache hit rates
5. Switch to async DNS for daily incremental updates (<500 new IPs/day)
6. Re-run for stale enrichments (>90 days) monthly
7. Verify coverage targets achieved (>95% country/ASN)

**Estimated Duration**:
- First backfill (cold cache, whois bulk): **6-7 hours**
- Subsequent backfills (warm cache): **10-15 minutes**

---

## Performance Impact Analysis

### Storage Savings

**Before** (session-level enrichment):
```
session_summaries: 198K rows × 5KB enrichment = 990 MB
```

**After** (IP inventory):
```
ip_inventory: ~50K unique IPs × 5KB enrichment = 250 MB
session_summaries: 198K rows × 100 bytes (FK + denormalized fields) = 20 MB
Total: 270 MB (73% reduction)
```

### API Call Reduction

**Before**: 198K sessions to enrich = 198K API calls
**After**: ~50K unique IPs = 50K API calls (**75% reduction**)

### Query Performance

**Fast queries** (no JOIN needed):
```sql
-- Session filters using denormalized columns
SELECT session_id
FROM session_summaries
WHERE geo_country = 'CN'  -- Uses computed column + index
  AND asn = 4134
  AND is_bogon = false;
```

**Full enrichment queries** (requires JOIN):
```sql
-- Session queries with full enrichment data
SELECT s.session_id, i.enrichment, i.geo_country, i.asn
FROM session_summaries s
JOIN ip_inventory i ON s.source_ip = i.ip_address
WHERE s.first_event_at >= '2024-11-01';
```

**IP reputation dashboard** (direct ip_inventory):
```sql
-- Top attacking IPs (no JOIN needed)
SELECT ip_address, session_count, geo_country, asn, is_scanner
FROM ip_inventory
ORDER BY session_count DESC
LIMIT 100;
```

---

## New Analysis Capabilities

### 1. Top Attacking IPs

```sql
SELECT
    ip_address,
    session_count,
    geo_country,
    asn,
    is_scanner,
    is_bogon,
    first_seen,
    last_seen,
    ROUND(EXTRACT(EPOCH FROM (last_seen - first_seen)) / 86400, 1) as days_active,
    ROUND(session_count::numeric / NULLIF(EXTRACT(EPOCH FROM (last_seen - first_seen)) / 86400, 0), 2) as sessions_per_day
FROM ip_inventory
WHERE session_count >= 5
  AND is_bogon = false
ORDER BY session_count DESC
LIMIT 100;
```

---

### 2. Botnet Detection (ASN Clustering)

```sql
SELECT
    asn,
    enrichment->'maxmind'->>'as_org' as as_org,
    COUNT(DISTINCT ip_address) as ip_count,
    SUM(session_count) as total_sessions,
    ARRAY_AGG(ip_address ORDER BY session_count DESC) FILTER (WHERE session_count >= 5) as top_ips,
    geo_country
FROM ip_inventory
WHERE
    asn IS NOT NULL
    AND last_seen > NOW() - INTERVAL '7 days'
    AND is_bogon = false
GROUP BY asn, enrichment->'maxmind'->>'as_org', geo_country
HAVING COUNT(DISTINCT ip_address) >= 10  -- ASN with 10+ attacking IPs
ORDER BY total_sessions DESC
LIMIT 50;
```

---

### 3. Persistent Attackers (Long-term Activity)

```sql
SELECT
    ip_address,
    first_seen,
    last_seen,
    session_count,
    ROUND(EXTRACT(EPOCH FROM (last_seen - first_seen)) / 86400, 1) as days_active,
    ROUND(session_count::numeric / NULLIF(EXTRACT(EPOCH FROM (last_seen - first_seen)) / 86400, 0), 2) as sessions_per_day,
    geo_country,
    asn,
    enrichment->'greynoise'->>'classification' as scanner_type
FROM ip_inventory
WHERE
    last_seen - first_seen > INTERVAL '30 days'  -- Active >30 days
    AND session_count >= 10
    AND is_bogon = false
ORDER BY sessions_per_day DESC
LIMIT 100;
```

---

### 4. Enrichment Gap Analysis

```sql
-- IPs with missing or incomplete enrichment
SELECT
    ip_address,
    session_count,
    last_seen,
    enrichment_completeness,
    enrichment_sources,
    CASE WHEN enrichment->'maxmind' IS NULL THEN false ELSE true END as has_maxmind,
    CASE WHEN enrichment->'cymru' IS NULL THEN false ELSE true END as has_cymru,
    geo_country,
    asn
FROM ip_inventory
WHERE
    (geo_country = 'XX' OR asn IS NULL)  -- Missing critical data
    AND is_bogon = false                  -- Exclude invalid IPs
    AND last_seen > NOW() - INTERVAL '30 days'  -- Active recently
ORDER BY session_count DESC
LIMIT 500;
```

---

### 5. Stale Enrichment Report

```sql
-- IPs needing re-enrichment (>90 days stale)
SELECT
    ip_address,
    session_count,
    last_seen,
    enrichment_updated_at,
    ROUND(EXTRACT(EPOCH FROM (NOW() - enrichment_updated_at)) / 86400, 1) as enrichment_age_days,
    enrichment_sources,
    geo_country,
    asn
FROM ip_inventory
WHERE
    enrichment_updated_at < NOW() - INTERVAL '90 days'
    AND last_seen > NOW() - INTERVAL '30 days'  -- Still active
ORDER BY session_count DESC
LIMIT 1000;
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| IP inventory adds complexity | Medium | Low | Comprehensive testing, phased rollout |
| Migration takes longer than expected | Low | Low | Can run incrementally, non-blocking |
| 90-day Cymru TTL too short | Low | Low | Monitoring will reveal, easy to adjust |
| Whois bulk parsing errors | Low | Medium | Extensive test cases, fallback to DNS |
| Foreign key constraint issues | Low | Medium | Thorough migration testing first |
| MaxMind DB corruption | Low | Medium | Comprehensive validation, graceful fallback |
| GreyNoise API changes | Medium | Low | Optional service, graceful skip |

**Overall Risk**: **LOW** - Changes are incremental, testable, and reversible.

---

## Summary

**Status**: Production-ready design incorporating all technical review feedback

**Key Changes from v2.0**:
- ✅ IP inventory table (75% API call reduction, 73% storage reduction)
- ✅ Cymru cache TTL: 90 days (catches ASN transfers quarterly)
- ✅ Enhanced error handling (NA fields, NXDOMAIN, timeouts)
- ✅ Backfill concurrency control (advisory locks)
- ✅ Enrichment completeness fix (excludes intentional skips)
- ✅ Realistic backfill estimates (whois bulk: 6-7 hours)
- ✅ Enhanced GreyNoise filtering (variety, malware, duration)
- ✅ Comprehensive MaxMind validation (build date, file size, sanity)
- ✅ Cache staleness metrics (p95 age monitoring)
- ✅ GreyNoise UTC midnight reset (predictable budget)
- ✅ IPv6 deferral documented (upstream doesn't support)

**Cost**: $0 (all free sources)
**Implementation**: 9-11 hours (phased rollout)
**Expected Coverage**: Country 98-99%, ASN 99-100%, spoofing detection, scanner classification

**Recommended Next Step**: Phase 0.5 (IP inventory table) - 2 hours to prove normalization benefits

Ready to proceed with implementation?
