# ADR 008: Multi-Source Enrichment Fallback Strategy

**Status**: Accepted
**Date**: 2025-11-03
**Approved**: 2025-11-05 (Business Panel Review)
**Context**: ASN/Geo Enrichment Architecture - Phase 2 Data Source Integration
**Deciders**: Architecture Review
**Related ADRs**:
- [ADR-007: IP Inventory Enrichment Normalization](007-ip-inventory-enrichment-normalization.md) (Prerequisite)
- [ADR-001: JSONB for Vector Metadata](001-jsonb-vector-metadata-no-fk.md) (Pattern reference)

## Context and Problem Statement

The cowrieprocessor system enriches IP addresses with geolocation and ASN data to enable threat intelligence analysis. Currently, the system relies primarily on DShield API for IP enrichment, which has significant coverage gaps:

- **DShield coverage**: ~60-70% of observed IPs have data
- **Missing ASN data**: Critical for infrastructure analysis and snowshoe detection
- **No geolocation**: GeoIP data is essential for geographic threat patterns
- **No offline capability**: All enrichment requires API calls

**Core Challenge**: How do we achieve >95% enrichment coverage while maintaining zero cost, minimizing API calls, and preserving data provenance for analysis?

### Decision Drivers

1. **Coverage Target**: Achieve >95% coverage for ASN and country fields
2. **Zero Cost Constraint**: All data sources must be free (no API fees)
3. **API Efficiency**: Minimize external API calls (75%+ reduction target)
4. **Data Provenance**: Track which source provided each data point for quality assessment
5. **Fault Tolerance**: System must gracefully handle source failures
6. **Staleness Management**: Balance freshness vs API cost with source-specific TTLs
7. **Offline Capability**: Support air-gapped/offline deployments for MaxMind
8. **Storage Efficiency**: Avoid redundant data storage across sources

## Considered Options

### Option A: Single Source with Best Coverage (REJECTED)

**Description**: Replace DShield with MaxMind GeoLite2 as single source

**Pros**:
- ✅ Simple implementation (single code path)
- ✅ 99%+ coverage for geolocation
- ✅ Offline capability (no API calls)
- ✅ Zero cost (free license)

**Cons**:
- ❌ Loses existing DShield threat intelligence integration
- ❌ No ASN data in GeoLite2-City (requires separate GeoLite2-ASN DB)
- ❌ No scanner classification (GreyNoise provides this)
- ❌ Wastes existing DShield cache (>1M entries)
- ❌ Single point of failure (no fallback if DB corrupted/stale)

### Option B: Parallel Enrichment with Majority Vote (REJECTED)

**Description**: Query all sources simultaneously, use majority vote to resolve conflicts

**Pros**:
- ✅ Maximum data quality (consensus-based)
- ✅ Conflict detection capability
- ✅ Comprehensive data provenance

**Cons**:
- ❌ **API cost explosion**: 3-4× API calls vs sequential fallback
- ❌ Violates zero-cost constraint (GreyNoise 10K/day limit exhausted quickly)
- ❌ Slower enrichment (wait for all sources)
- ❌ Complex conflict resolution logic
- ❌ Wastes API quota on redundant queries

**Performance Impact**:
```
198K sessions → ~50K unique IPs
Parallel: 50K × 4 sources = 200K API calls (vs 12.5K with sequential fallback)
GreyNoise budget: 10K/day → 20 days to enrich vs 1-2 days
```

### Option C: Sequential Cascade with Source Priority (ACCEPTED)

**Description**: Attempt sources in priority order, stop at first success with COALESCE fallback

**Priority Order**:
1. **RFC1918/Bogon Validation** (local, instant)
2. **MaxMind GeoLite2** (offline DB, 99% coverage, primary)
3. **Team Cymru** (DNS/whois, 100% ASN coverage, fallback for ASN)
4. **GreyNoise Community** (API, selective scanner classification)
5. **DShield** (existing cache reuse only, no new API calls)

**Pros**:
- ✅ **82% API reduction**: 300K calls → 54K calls (198K sessions → 50K unique IPs)
- ✅ >95% coverage target (MaxMind 99% + Cymru 1% gap)
- ✅ Zero cost (all sources free)
- ✅ Fault tolerant (graceful degradation through cascade)
- ✅ Preserves existing DShield cache (reuse without new calls)
- ✅ Source-specific staleness policies optimize freshness vs cost
- ✅ Data provenance tracked in `enrichment._meta`
- ✅ Offline capability via MaxMind

**Cons**:
- More complex implementation (multi-source coordination)
- Requires 3-tier cache management per source
- Need source-specific error handling

**COALESCE Fallback Pattern** (stored in computed columns):
```sql
geo_country AS (
    COALESCE(
        enrichment->'maxmind'->>'country',    -- Primary (99%)
        enrichment->'cymru'->>'country',      -- Fallback (0.9%)
        enrichment->'dshield'->'ip'->>'ascountry',  -- Legacy cache (0.1%)
        'XX'                                   -- Unknown
    )
) STORED
```

### Option D: Smart Hybrid with Cost-Aware Routing (CONSIDERED)

**Description**: Option C + dynamic source selection based on cost budget and session priority

**Enhancements**:
- High-risk sessions (malware downloads, long duration) → query all sources
- Low-risk sessions (automated scans) → skip GreyNoise to preserve quota
- Budget tracking: pause GreyNoise when daily quota 90% exhausted

**Pros**:
- ✅ All benefits of Option C
- ✅ Optimizes GreyNoise quota for high-value targets
- ✅ Enables future tiered enrichment strategies

**Cons**:
- Significantly more complex (heuristics, budget tracking, session scoring)
- Risk of over-optimization (premature complexity)

**Decision**: **Implement Option C first**, add Option D enhancements in Phase 3 after validating base cascade.

## Decision Outcome

**Chosen Option**: Option C - Sequential Cascade with Source Priority

### Implementation Strategy

#### Phase 1: IP Inventory Foundation (ADR-007)

**Prerequisites** (must complete first):
- Implement three-tier architecture (ASN inventory, IP inventory, Session summaries)
- Deploy lightweight snapshot columns for JOIN-free queries
- Migrate existing session enrichment data to IP inventory

#### Phase 2: Multi-Source Integration (This ADR)

**Data Sources**:

| Source | Type | Coverage | Cost | TTL | Role |
|--------|------|----------|------|-----|------|
| **RFC1918/Bogon** | Local validation | 5% | $0 | N/A | Skip external lookups |
| **MaxMind GeoLite2** | Offline DB | 99%+ | $0 | Infinite* | Primary geo + ASN |
| **Team Cymru** | DNS/whois | 100% ASN | $0 | 90 days | ASN fallback |
| **GreyNoise Community** | REST API | Selective | $0 (10K/day) | 7 days | Scanner classification |
| **DShield** | REST API | 60-70% | $0 | 7 days | Legacy cache reuse only |

*MaxMind DB refreshed weekly via cron (GeoIP2 package auto-update)

**Enrichment Workflow**:

```python
def _multi_source_enrich(ip_address: str, session_id: str = None) -> dict:
    """
    Sequential cascade enrichment with early termination.

    Returns:
        {
            "validation": {...},      # RFC1918/Bogon
            "maxmind": {...},         # GeoLite2 (geo + ASN)
            "cymru": {...},           # Only if MaxMind ASN missing
            "greynoise": {...},       # Only if high-activity session + quota available
            "_meta": {
                "enrichment_version": "2.2",
                "sources_attempted": ["maxmind", "cymru"],
                "sources_succeeded": ["maxmind"],
                "sources_failed": [],
                "sources_skipped": ["greynoise"],
                "skip_reasons": {"greynoise": "low_activity_filter"},
                "failure_reasons": {},
                "cache_hits": {"maxmind": "db_query"},
                "total_duration_ms": 245
            }
        }
    """

    # Step 1: RFC1918/Bogon validation (local, instant)
    if is_bogon(ip_address):
        return {"validation": {"is_bogon": True}, "_meta": {...}}

    # Step 2: MaxMind GeoLite2 (offline DB, fast, primary)
    maxmind_result = maxmind_handler.lookup(ip_address)

    # Step 3: Team Cymru (only if MaxMind ASN missing)
    if not maxmind_result.get("asn"):
        cymru_result = cymru_cache.get_or_fetch(ip_address, ttl=90*86400)

    # Step 4: GreyNoise (filtered by session activity, rate-limited)
    if _should_query_greynoise(session_id) and greynoise_rate_limiter.allow():
        greynoise_result = greynoise_cache.get_or_fetch(ip_address, ttl=7*86400)

    return merge_enrichment(...)
```

**Source-Specific Error Handling**:

| Error Category | MaxMind | Cymru | GreyNoise | Action |
|----------------|---------|-------|-----------|--------|
| **Network timeout** | N/A (offline) | NXDOMAIN → skip | 504 → skip | Continue cascade |
| **Rate limit** | N/A | N/A | 429 → skip | Preserve quota, skip source |
| **Malformed response** | Log + skip | Log + skip | Log + skip | Continue cascade |
| **Complete failure** | **CRITICAL** | Warning | Warning | MaxMind failure → alert |

**GreyNoise Activity Filter** (preserve 10K/day quota):

```python
def _should_query_greynoise(session: SessionSummary) -> bool:
    """
    Query GreyNoise only for high-value targets.

    Prioritizes:
    - High-activity sessions (manual attackers, not automated scans)
    - Malware downloads (confirmed threats)
    - Long-duration sessions (persistent access)
    """
    return any([
        session.command_count >= 10,            # High activity
        session.file_downloads >= 5,            # Multiple malware downloads
        session.vt_flagged,                     # VirusTotal confirmed malware
        session.duration_seconds >= 300,        # 5+ minute sessions (manual)
    ])
```

#### Phase 3: Staleness-Aware Re-Enrichment

**Source-Specific TTL Policies**:

| Source | TTL | Rationale |
|--------|-----|-----------|
| **RFC1918** | N/A (never stale) | Static validation |
| **MaxMind** | Infinite (DB refresh weekly) | Offline DB, no per-IP staleness |
| **Team Cymru** | **90 days** | ASN assignments change quarterly |
| **GreyNoise** | **7 days** | Scanner status changes frequently |
| **DShield** | 7 days | Existing policy (unchanged) |

**Staleness Check Logic**:

```python
def _enrichment_is_stale(ip_record) -> bool:
    """
    Determine if re-enrichment needed based on source-specific TTLs.

    Returns:
        True if any source data is stale and warrants refresh
    """
    if not ip_record.enrichment_updated_at:
        return True  # Never enriched

    age = now() - ip_record.enrichment_updated_at
    enrichment = ip_record.enrichment

    # GreyNoise stale check (7-day TTL)
    if enrichment.get('greynoise') and age > timedelta(days=7):
        return True

    # Cymru/MaxMind stale check (90-day TTL)
    if (enrichment.get('cymru') or enrichment.get('maxmind')) and age > timedelta(days=90):
        return True

    # No enrichment or empty
    if not enrichment or enrichment == {}:
        return True

    return False  # Enrichment is fresh
```

**Re-Enrichment Trigger Points**:

1. **Real-time** (during session ingestion):
   - New IP appears → immediate enrichment
   - Stale IP (per TTL policy) → re-enrichment during session insert

2. **Batch** (daily cron):
   ```bash
   # Find and re-enrich stale IPs (>90 days old, active in last 30 days)
   0 3 * * * cd /path/to/cowrieprocessor && \
       uv run python -c "from cowrieprocessor.enrichment import backfill_stale_ips; \
                         backfill_stale_ips(max_age_days=90, batch_size=1000)"
   ```

3. **On-demand** (manual):
   ```bash
   # Re-enrich specific IP
   uv run cowrie-enrich refresh --ip 192.168.1.1

   # Re-enrich all IPs from specific country
   uv run cowrie-enrich refresh --country CN

   # Re-enrich all IPs from specific ASN
   uv run cowrie-enrich refresh --asn 4134
   ```

### Data Provenance and Quality Tracking

**Enrichment Metadata Structure**:

```json
{
  "validation": {
    "is_private": false,
    "is_bogon": false,
    "is_reserved": false
  },
  "maxmind": {
    "country": "US",
    "city": "Mountain View",
    "asn": 15169,
    "asn_org": "Google LLC",
    "latitude": 37.4056,
    "longitude": -122.0775
  },
  "cymru": null,  // Skipped (MaxMind had ASN)
  "greynoise": {
    "noise": true,
    "classification": "benign",
    "name": "Googlebot"
  },
  "_meta": {
    "enrichment_version": "2.2",
    "enrichment_timestamp": "2025-11-03T12:34:56Z",
    "sources_attempted": ["maxmind", "greynoise"],
    "sources_succeeded": ["maxmind", "greynoise"],
    "sources_failed": [],
    "sources_skipped": ["cymru"],
    "skip_reasons": {
      "cymru": "maxmind_asn_available"
    },
    "failure_reasons": {},
    "cache_hits": {
      "maxmind": "db_query",
      "greynoise": "redis_l1"
    },
    "total_duration_ms": 245
  }
}
```

**Quality Metrics** (Prometheus):

```yaml
# Coverage by source
enrichment_coverage_ratio{field="country", source="maxmind"} 0.99
enrichment_coverage_ratio{field="asn", source="maxmind"} 0.95
enrichment_coverage_ratio{field="asn", source="cymru"} 0.04  # Fills MaxMind gap

# Success/failure rates
enrichment_source_success_total{source="maxmind"} 49500
enrichment_source_failures_total{source="cymru", reason="nxdomain"} 50

# Cache efficiency
enrichment_cache_hits_total{source="greynoise", tier="redis_l1"} 8500
```

### Migration Path

**Backward Compatibility**:

1. **Existing session enrichment data** preserved in `session_summaries.enrichment` (point-in-time snapshots)
2. **Existing DShield cache** reused via COALESCE fallback (no new API calls)
3. **Computed columns** provide multi-source fallback without application changes:
   ```sql
   -- Application code unchanged, reads computed column
   SELECT geo_country FROM session_summaries WHERE session_id = '...';

   -- Computed column handles fallback automatically
   geo_country AS (
       COALESCE(
           enrichment->'maxmind'->>'country',
           enrichment->'cymru'->>'country',
           enrichment->'dshield'->'ip'->>'ascountry',
           'XX'
       )
   ) STORED
   ```

**Rollback Capability**:

- IP inventory can be dropped without losing session enrichment data (snapshots remain)
- Source-specific caches can be cleared independently
- Computed columns provide graceful degradation (fallback to DShield if MaxMind fails)

## Consequences

### Positive

1. **Coverage Achievement**: >95% coverage for ASN and country (MaxMind 99% + Cymru 1%)
2. **API Efficiency**: 82% reduction (300K → 54K calls) via IP inventory deduplication
3. **Zero Cost**: All data sources free, GreyNoise quota managed via activity filter
4. **Fault Tolerance**: Graceful degradation through source cascade (5 → 4 → 3 → 2 → 1)
5. **Offline Capability**: MaxMind enables air-gapped deployments
6. **Data Provenance**: Complete audit trail of which source provided each field
7. **Staleness Optimization**: Source-specific TTLs balance freshness vs API cost
8. **Backward Compatible**: Existing DShield cache reused, session enrichment preserved
9. **Performance**: Computed columns enable JOIN-free queries for 80% of workloads

### Negative

1. **Implementation Complexity**: Multi-source coordination, 3-tier caching, error handling
2. **Operational Overhead**: MaxMind DB weekly updates, Cymru DNS monitoring, GreyNoise quota tracking
3. **Storage Cost**: +543 MB for IP inventory snapshot columns (acceptable, see ADR-007)
4. **Cache Management**: 5 distinct cache TTL policies to maintain
5. **Testing Complexity**: Need mock implementations for 4 external data sources
6. **Monitoring Requirements**: 15+ Prometheus metrics for source health and coverage

### Risks and Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **MaxMind DB corruption** | CRITICAL (99% coverage lost) | Low | Weekly validation script, auto-redownload on failure |
| **Cymru DNS timeout** | Low (1% coverage loss) | Medium | 3-tier cache, 90-day TTL reduces API dependency |
| **GreyNoise quota exhaustion** | Low (scanner classification only) | Medium | Activity filter, 90% warning threshold, skip when exhausted |
| **Multi-source data conflicts** | Medium (GeoIP discrepancies) | Low | Priority order favors most accurate source (MaxMind > Cymru) |
| **Cache stampede** | Medium (Cymru DNS overload) | Low | Advisory lock on backfill, staggered re-enrichment |

## Implementation Checklist

- [ ] **Phase 1: IP Inventory** (ADR-007) - PREREQUISITE
  - [ ] Three-tier schema deployed (ASN inventory, IP inventory, Session summaries)
  - [ ] Lightweight snapshot columns added to `session_summaries`
  - [ ] Migration script tested on staging database

- [ ] **Phase 2a: MaxMind Integration**
  - [ ] GeoIP2 Python library installed (`pip install geoip2`)
  - [ ] MaxMind DB download automation (weekly cron)
  - [ ] Validation script (8.8.8.8 → US, build date <30 days, file size >50MB)
  - [ ] Offline lookup handler with error handling
  - [ ] Unit tests with fixture DB

- [ ] **Phase 2b: Team Cymru Integration**
  - [ ] Whois bulk interface for backfill (100 IPs/query)
  - [ ] Async DNS resolver for real-time (aiodns, 10 concurrent)
  - [ ] 3-tier cache integration (Redis L1, DB L2, Disk L3)
  - [ ] 90-day TTL policy
  - [ ] Error handling (NXDOMAIN, timeout, malformed response)
  - [ ] Unit tests with stubbed DNS responses

- [ ] **Phase 2c: GreyNoise Integration**
  - [ ] REST API client (Community endpoint)
  - [ ] Daily rate limiter (10K/day, UTC reset)
  - [ ] Activity filter heuristics
  - [ ] 7-day TTL policy
  - [ ] Quota tracking and warning (90% threshold)
  - [ ] Unit tests with mock API

- [ ] **Phase 2d: Multi-Source Orchestration**
  - [ ] Sequential cascade logic with early termination
  - [ ] Enrichment metadata tracking (`_meta`)
  - [ ] COALESCE fallback in computed columns
  - [ ] Source-specific error handling
  - [ ] Integration tests with all sources

- [ ] **Phase 3: Staleness Management**
  - [ ] Source-specific TTL logic
  - [ ] Daily backfill script (stale IPs, active in last 30 days)
  - [ ] On-demand re-enrichment CLI commands
  - [ ] Advisory lock for backfill coordination

- [ ] **Phase 4: Monitoring and Observability**
  - [ ] Prometheus metrics (15+ coverage, cache, performance)
  - [ ] Alerting rules (coverage <95%, source failures >10%, MaxMind DB stale)
  - [ ] Grafana dashboard (source health, cache efficiency, coverage trends)
  - [ ] Weekly coverage report

- [ ] **Phase 5: Documentation**
  - [ ] Update `cowrieprocessor/enrichment/README.md` with multi-source architecture
  - [ ] CLI usage examples for on-demand re-enrichment
  - [ ] Troubleshooting guide (source failures, cache misses, staleness)
  - [ ] Data dictionary updates (ip_inventory schema, enrichment metadata)

## Related Decisions

- **ADR-007**: IP Inventory Enrichment Normalization (prerequisite)
- **ADR-001**: JSONB for Vector Metadata (pattern reference for enrichment metadata)

## References

- [MaxMind GeoLite2 Free License](https://dev.maxmind.com/geoip/geolite2-free-geolocation-data)
- [Team Cymru IP-to-ASN Mapping](https://www.team-cymru.com/ip-asn-mapping)
- [GreyNoise Community API](https://docs.greynoise.io/docs/community-api)
- [ASN/Geo Enrichment Design v2.2](../../claudedocs/ASN_GEO_ENRICHMENT_DESIGN_v2.2.md)

---

**Decision Status**:
- [x] **Technical review** (COMPLETED - 2025-11-05)
- [x] **Implementation approved** (2025-11-05 - Business Panel Review)
- [ ] ADR-007 prerequisite completed (REQUIRED before implementation)

**Approval Conditions**:
- ✅ Phased implementation approved (ADR-007 validation → ADR-008 deployment)
- ✅ Success criteria defined (>95% coverage, >80% API reduction)
- ✅ Multi-source cascade strategy validated (MaxMind → Cymru → GreyNoise)
- ⚠️ **BLOCKING**: ADR-007 must be deployed and validated before starting ADR-008

**Next Steps**:
1. ✅ Complete technical review of ADR-008
2. ⏳ **WAIT**: Ensure ADR-007 is deployed and validated (prerequisite checkpoint)
3. Begin Phase 2a (MaxMind integration) after ADR-007 success validation
4. Incremental rollout (MaxMind → Cymru → GreyNoise → Monitoring)
