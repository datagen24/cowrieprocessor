# ADR-008 Multi-Source Enrichment Implementation Plan

## Executive Summary

**Objective**: Implement sequential cascade enrichment pattern to achieve >95% coverage with 82% API reduction

**Sources**:
1. **MaxMind GeoLite2** (Primary): 99% coverage, offline DB lookup, zero cost
2. **Team Cymru** (ASN Fallback): 1% gap coverage, DNS/whois, free
3. **GreyNoise** (Scanner Intel): Community API, 10K/day limit, free

**Success Metrics**:
- Coverage: >95% (target: 99.5%)
- API Reduction: 82% (300K → 54K Cymru calls)
- Cost: $0 (all free tiers)
- Performance: <100ms P95 latency

## Phase 2a: MaxMind GeoLite2 Integration

### Implementation Files
- `cowrieprocessor/enrichment/maxmind_client.py` (NEW)
- `cowrieprocessor/enrichment/handlers.py` (MODIFY)
- `tests/unit/test_maxmind_client.py` (NEW)
- `tests/integration/test_maxmind_enrichment.py` (NEW)

### Technical Specifications

**MaxMind Client Class**:
```python
class MaxMindClient:
    """Offline GeoLite2 database client with automatic updates."""
    
    def __init__(self, db_path: Path, license_key: str | None = None):
        """Initialize with local database path and optional license key for auto-updates."""
        
    def lookup_ip(self, ip_address: str) -> MaxMindResult | None:
        """Return geo/ASN data or None if not found."""
        
    def update_database(self) -> bool:
        """Download latest GeoLite2-City.mmdb and GeoLite2-ASN.mmdb."""
        
    def get_database_age(self) -> timedelta:
        """Return age of current database for staleness monitoring."""
```

**MaxMindResult Structure**:
```python
@dataclass
class MaxMindResult:
    ip_address: str
    country_code: str | None
    country_name: str | None
    city: str | None
    latitude: float | None
    longitude: float | None
    asn: int | None
    asn_org: str | None
    accuracy_radius: int | None
    source: str = "maxmind"
    cached_at: datetime = field(default_factory=datetime.utcnow)
```

**Configuration**:
- Database path: `/mnt/dshield/data/cache/maxmind/GeoLite2-City.mmdb`
- Auto-update: Weekly check (7-day interval)
- License key: `env:MAXMIND_LICENSE_KEY` (optional, for updates)
- Fallback: If DB missing, skip to Cymru (don't fail)

### Testing Strategy
- Unit tests: Mock geoip2.database.Reader
- Integration tests: Use test database subset (1000 IPs)
- Coverage target: 95%
- Offline tests: No network calls required

## Phase 2b: Team Cymru Integration

### Implementation Files
- `cowrieprocessor/enrichment/cymru_client.py` (NEW)
- `cowrieprocessor/enrichment/handlers.py` (MODIFY)
- `tests/unit/test_cymru_client.py` (NEW)
- `tests/integration/test_cymru_enrichment.py` (NEW)

### Technical Specifications

**Cymru Client Class**:
```python
class CymruClient:
    """Team Cymru whois client with DNS and HTTP fallback."""
    
    def __init__(self, cache: EnrichmentCache, ttl_days: int = 90):
        """Initialize with 90-day TTL per ADR-008."""
        
    def lookup_asn(self, ip_address: str) -> CymruResult | None:
        """DNS lookup with HTTP API fallback, 90-day cache."""
        
    def bulk_lookup(self, ip_addresses: list[str]) -> dict[str, CymruResult]:
        """Batch lookup for efficiency (max 500 IPs per request)."""
```

**CymruResult Structure**:
```python
@dataclass
class CymruResult:
    ip_address: str
    asn: int | None
    asn_org: str | None
    country_code: str | None
    registry: str | None  # ARIN, RIPE, APNIC, etc.
    source: str = "cymru"
    cached_at: datetime = field(default_factory=datetime.utcnow)
    ttl_days: int = 90
```

**DNS Query Pattern**:
```python
# Reverse IP: 8.8.8.8 → 8.8.8.8.origin.asn.cymru.com
def _build_dns_query(ip: str) -> str:
    return f"{ip}.origin.asn.cymru.com"
    
# Parse response: "15169 | 8.8.8.0/24 | US | arin | 1992-12-01"
def _parse_dns_response(txt_record: str) -> CymruResult:
    ...
```

**Rate Limiting**:
- No published limit, but use 100 req/sec throttle
- Batch queries when possible (500 IPs max)
- Exponential backoff on failures

### Testing Strategy
- Unit tests: Mock DNS resolver
- Integration tests: Use known ASNs (Google AS15169, Cloudflare AS13335)
- Coverage target: 90%
- Offline tests: Mock DNS responses

## Phase 2c: GreyNoise Integration

### Implementation Files
- `cowrieprocessor/enrichment/greynoise_client.py` (NEW)
- `cowrieprocessor/enrichment/handlers.py` (MODIFY)
- `tests/unit/test_greynoise_client.py` (NEW)
- `tests/integration/test_greynoise_enrichment.py` (NEW)

### Technical Specifications

**GreyNoise Client Class**:
```python
class GreyNoiseClient:
    """GreyNoise Community API client with 10K/day rate limit."""
    
    def __init__(self, api_key: str, cache: EnrichmentCache, ttl_days: int = 7):
        """Initialize with Community API key and 7-day TTL."""
        
    def lookup_ip(self, ip_address: str) -> GreyNoiseResult | None:
        """Check if IP is known scanner/bot, 7-day cache."""
        
    def get_remaining_quota(self) -> int:
        """Return daily API calls remaining (for monitoring)."""
```

**GreyNoiseResult Structure**:
```python
@dataclass
class GreyNoiseResult:
    ip_address: str
    noise: bool  # True if known scanner
    riot: bool  # True if benign service (CDN, cloud provider)
    classification: str | None  # "malicious", "benign", "unknown"
    name: str | None  # Service name if RIOT
    last_seen: datetime | None
    source: str = "greynoise"
    cached_at: datetime = field(default_factory=datetime.utcnow)
    ttl_days: int = 7
```

**API Endpoints**:
- Community API: `https://api.greynoise.io/v3/community/{ip}`
- Rate limit: 10,000 requests/day
- Response format: JSON

**Rate Limiting Strategy**:
- Track daily quota in Redis/memory
- Fail gracefully if quota exhausted
- Reset counter at midnight UTC

### Testing Strategy
- Unit tests: Mock HTTP responses
- Integration tests: Use known scanners (Shodan, Censys IPs)
- Coverage target: 85%
- Offline tests: Mock API responses

## Phase 2d: Multi-Source Orchestration

### Implementation Files
- `cowrieprocessor/enrichment/cascade_enricher.py` (NEW)
- `cowrieprocessor/enrichment/handlers.py` (MODIFY)
- `tests/unit/test_cascade_enricher.py` (NEW)
- `tests/integration/test_cascade_flow.py` (NEW)

### Technical Specifications

**Cascade Enricher Class**:
```python
class CascadeEnricher:
    """Orchestrate sequential multi-source enrichment with early termination."""
    
    def __init__(
        self,
        maxmind: MaxMindClient,
        cymru: CymruClient,
        greynoise: GreyNoiseClient,
        session: Session,
    ):
        """Initialize with all enrichment clients and database session."""
        
    def enrich_ip(self, ip_address: str) -> IPInventory:
        """
        Sequential cascade enrichment with early termination:
        
        1. Check if IP exists in ip_inventory (cache check)
        2. If cached and fresh (< source TTL), return cached
        3. If missing or stale:
           a. Try MaxMind (offline, always succeeds or None)
           b. If MaxMind ASN missing, try Cymru (online, 90-day TTL)
           c. Try GreyNoise (online, 7-day TTL, quota-aware)
        4. Update ip_inventory with merged results
        5. Return IPInventory ORM object
        """
        
    def enrich_session_ips(self, session_id: int) -> dict[str, IPInventory]:
        """Enrich all IPs in a session (source_ip, dest_ip if present)."""
        
    def backfill_missing_asns(self, limit: int = 1000) -> int:
        """Find IPs with NULL asn_number, enrich with Cymru, return count."""
```

**Cascade Logic (Pseudo-code)**:
```python
def enrich_ip(self, ip: str) -> IPInventory:
    # Step 1: Cache check
    cached = self.session.query(IPInventory).filter_by(ip_address=ip).first()
    if cached and self._is_fresh(cached):
        return cached
    
    # Step 2: MaxMind lookup (primary source)
    maxmind_result = self.maxmind.lookup_ip(ip)
    merged = self._merge_results(cached, maxmind_result)
    
    # Step 3: Cymru fallback (if ASN missing)
    if merged.asn_number is None:
        cymru_result = self.cymru.lookup_asn(ip)
        merged = self._merge_results(merged, cymru_result)
    
    # Step 4: GreyNoise classification (if quota available)
    if self.greynoise.get_remaining_quota() > 0:
        gn_result = self.greynoise.lookup_ip(ip)
        merged = self._merge_results(merged, gn_result)
    
    # Step 5: Update database
    if cached:
        self._update_inventory(cached, merged)
    else:
        self.session.add(merged)
    
    return merged

def _is_fresh(self, inventory: IPInventory) -> bool:
    """Check if cached data is within TTL for each source."""
    now = datetime.utcnow()
    
    # MaxMind: Check DB age (updated weekly)
    if inventory.source == "maxmind":
        db_age = self.maxmind.get_database_age()
        if db_age < timedelta(days=7):
            return True
    
    # Cymru: 90-day TTL
    if inventory.asn_source == "cymru":
        if now - inventory.enrichment_ts < timedelta(days=90):
            return True
    
    # GreyNoise: 7-day TTL
    if inventory.scanner_source == "greynoise":
        if now - inventory.scanner_ts < timedelta(days=7):
            return True
    
    return False
```

**Source Priority Rules**:
1. **Geo data**: MaxMind only (don't overwrite with Cymru)
2. **ASN data**: MaxMind preferred, Cymru fallback
3. **Scanner classification**: GreyNoise only
4. **Timestamp tracking**: Separate timestamps per source (enrichment_ts, scanner_ts)

### Testing Strategy
- Unit tests: Mock all three clients
- Integration tests: End-to-end cascade flow with real test IPs
- Coverage target: 95%
- Test scenarios:
  - MaxMind success (no fallback)
  - MaxMind miss → Cymru success
  - MaxMind + Cymru + GreyNoise full cascade
  - GreyNoise quota exhausted
  - Stale cache refresh

## Phase 3: Staleness-Aware Re-enrichment

### Implementation Files
- `cowrieprocessor/enrichment/staleness_manager.py` (NEW)
- `cowrieprocessor/cli/enrich.py` (MODIFY - add refresh subcommand)
- `tests/unit/test_staleness_manager.py` (NEW)

### Technical Specifications

**Staleness Manager Class**:
```python
class StalenessManager:
    """Identify and refresh stale enrichment data based on source TTLs."""
    
    def __init__(self, session: Session, cascade: CascadeEnricher):
        """Initialize with database session and cascade enricher."""
        
    def find_stale_ips(self, source: str | None = None) -> list[str]:
        """
        Find IPs with stale enrichment data:
        - Cymru: Last enriched >90 days ago
        - GreyNoise: Last enriched >7 days ago
        - MaxMind: Never stale (weekly updates handled by client)
        """
        
    def refresh_stale_ips(self, batch_size: int = 1000) -> dict[str, int]:
        """
        Refresh stale IPs in batches:
        Returns: {"cymru_refreshed": 150, "greynoise_refreshed": 45}
        """
        
    def get_staleness_stats(self) -> dict[str, Any]:
        """
        Return staleness statistics for monitoring:
        {
            "total_ips": 38864,
            "stale_cymru": 1250,
            "stale_greynoise": 5600,
            "oldest_cymru": "2024-01-15",
            "oldest_greynoise": "2024-10-28"
        }
        """
```

**CLI Integration**:
```bash
# Refresh stale Cymru ASN data (>90 days old)
uv run cowrie-enrich refresh-asn --batch-size 1000 --progress

# Refresh stale GreyNoise scanner data (>7 days old)
uv run cowrie-enrich refresh-scanners --batch-size 500 --progress

# Check staleness statistics
uv run cowrie-enrich staleness-stats
```

**Database Queries**:
```sql
-- Find stale Cymru ASN data (>90 days)
SELECT ip_address 
FROM ip_inventory 
WHERE asn_source = 'cymru' 
  AND enrichment_ts < NOW() - INTERVAL '90 days'
LIMIT 1000;

-- Find stale GreyNoise scanner data (>7 days)
SELECT ip_address 
FROM ip_inventory 
WHERE scanner_source = 'greynoise' 
  AND scanner_ts < NOW() - INTERVAL '7 days'
LIMIT 500;
```

### Testing Strategy
- Unit tests: Mock database queries
- Integration tests: Create test IPs with old timestamps
- Coverage target: 90%

## Phase 4: Monitoring and Observability

### Implementation Files
- `cowrieprocessor/telemetry/enrichment_metrics.py` (MODIFY)
- `cowrieprocessor/cli/health.py` (MODIFY)
- `docs/runbooks/enrichment_monitoring.md` (NEW)

### Metrics to Track

**Coverage Metrics**:
- `enrichment.coverage.maxmind` (gauge): % of IPs enriched by MaxMind
- `enrichment.coverage.cymru` (gauge): % of IPs with Cymru ASN
- `enrichment.coverage.greynoise` (gauge): % of IPs classified by GreyNoise
- `enrichment.coverage.total` (gauge): Overall enrichment coverage %

**Performance Metrics**:
- `enrichment.latency.maxmind` (histogram): Lookup latency P50/P95/P99
- `enrichment.latency.cymru` (histogram): DNS query latency
- `enrichment.latency.greynoise` (histogram): API call latency
- `enrichment.latency.cascade` (histogram): Full cascade latency

**API Usage Metrics**:
- `enrichment.api_calls.cymru` (counter): Total Cymru queries
- `enrichment.api_calls.greynoise` (counter): Total GreyNoise queries
- `enrichment.api_calls.greynoise.quota_remaining` (gauge): Daily quota left
- `enrichment.cache_hit_rate` (gauge): % of cache hits vs lookups

**Staleness Metrics**:
- `enrichment.stale_ips.cymru` (gauge): Count of stale Cymru ASN data
- `enrichment.stale_ips.greynoise` (gauge): Count of stale GreyNoise data
- `enrichment.maxmind_db_age_days` (gauge): Age of MaxMind database

**Error Metrics**:
- `enrichment.errors.maxmind` (counter): MaxMind lookup failures
- `enrichment.errors.cymru` (counter): Cymru DNS failures
- `enrichment.errors.greynoise` (counter): GreyNoise API failures

### Health Check Integration
```bash
# Check enrichment health
uv run cowrie-health --enrichment --db "postgresql://..."

# Output:
# ✅ MaxMind database age: 3 days (updated 2025-11-02)
# ✅ Enrichment coverage: 99.2% (target: >95%)
# ✅ Cymru cache hit rate: 87.3%
# ⚠️  GreyNoise quota: 2,341/10,000 remaining (23%)
# ✅ Stale Cymru ASN data: 45 IPs (0.1%)
# ⚠️  Stale GreyNoise data: 1,250 IPs (3.2%)
```

### Alerting Thresholds
- **Critical**: Enrichment coverage <90% for 1 hour
- **Warning**: GreyNoise quota <1000 remaining
- **Warning**: MaxMind database >14 days old
- **Info**: Stale Cymru data >5% of IPs

## PDCA Implementation Plan

### Plan Phase (Week 1)
- [ ] Review ADR-008 with team
- [ ] Create feature branch: `feature/adr-008-multi-source-enrichment`
- [ ] Set up MaxMind license key and download GeoLite2 databases
- [ ] Configure GreyNoise Community API key
- [ ] Create stub files for all new classes
- [ ] Write comprehensive test fixtures

### Do Phase (Weeks 2-4)

**Week 2: Phase 2a - MaxMind Integration**
- [ ] Implement `MaxMindClient` with offline DB lookup
- [ ] Add automatic database update mechanism
- [ ] Write unit tests (95% coverage target)
- [ ] Write integration tests with real MaxMind DB
- [ ] Update `CascadeEnricher` to use MaxMind as primary source

**Week 3: Phase 2b - Cymru Integration**
- [ ] Implement `CymruClient` with DNS and HTTP fallback
- [ ] Add 90-day caching with TTL tracking
- [ ] Implement bulk lookup for efficiency
- [ ] Write unit tests (90% coverage target)
- [ ] Write integration tests with known ASNs
- [ ] Update `CascadeEnricher` to use Cymru as ASN fallback

**Week 4: Phase 2c - GreyNoise + Orchestration**
- [ ] Implement `GreyNoiseClient` with quota tracking
- [ ] Add 7-day caching with TTL tracking
- [ ] Complete `CascadeEnricher` orchestration logic
- [ ] Write unit tests (95% coverage target)
- [ ] Write end-to-end integration tests
- [ ] Add staleness-aware refresh commands

### Check Phase (Week 5)
- [ ] Run full test suite (target: >65% coverage)
- [ ] Benchmark enrichment latency (target: <100ms P95)
- [ ] Measure API reduction (target: 82%)
- [ ] Validate coverage improvement (target: >95%)
- [ ] Review code with team (peer review)
- [ ] Test staging deployment with 1000 sessions

### Act Phase (Week 6)
- [ ] Deploy to production with feature flag
- [ ] Monitor coverage metrics for 7 days
- [ ] Backfill missing ASNs with Cymru
- [ ] Refresh stale GreyNoise data
- [ ] Update MaxMind database weekly
- [ ] Document lessons learned
- [ ] Create runbook for operations team

## Success Criteria

### Technical Metrics
- ✅ Enrichment coverage: >95% (target: 99.5%)
- ✅ API call reduction: 82% (300K → 54K Cymru calls)
- ✅ Cost: $0 (all free tiers)
- ✅ Latency: <100ms P95 for full cascade
- ✅ Test coverage: >65% (stretch: 80%)

### Operational Metrics
- ✅ Zero production incidents during rollout
- ✅ MaxMind database auto-updates weekly
- ✅ GreyNoise quota stays above 20% (2K/day buffer)
- ✅ Cymru cache hit rate >85%
- ✅ Stale data refresh completes within 24 hours

## Risk Mitigation

### Risk 1: MaxMind Database Staleness
**Mitigation**: 
- Implement automatic weekly updates
- Alert if database >14 days old
- Fall back to Cymru if MaxMind unavailable

### Risk 2: GreyNoise Quota Exhaustion
**Mitigation**:
- Track daily quota consumption
- Alert at 20% remaining (2K calls)
- Gracefully degrade if quota exhausted
- Prioritize high-risk IPs for classification

### Risk 3: Cymru DNS Failures
**Mitigation**:
- Implement HTTP API fallback
- Exponential backoff on failures
- Cache successful lookups for 90 days
- Monitor failure rate (alert >5%)

### Risk 4: Performance Regression
**Mitigation**:
- Benchmark before/after deployment
- Use offline MaxMind DB (zero latency)
- Batch Cymru queries when possible
- Parallel enrichment for multiple IPs

## Prerequisites Verification

✅ **ADR-007 Deployed**: Confirmed by user validation queries
- Schema version 16
- ip_inventory table with 38,864 IPs
- asn_inventory table created
- Foreign keys active

✅ **Database Support**: PostgreSQL with GENERATED columns

✅ **ORM Models**: IPInventory and ASNInventory models ready

✅ **Enrichment Infrastructure**: Cache layer, rate limiting, DLQ processing

## References

- ADR-008: `/docs/ADR/008-multi-source-enrichment-fallback.md`
- ADR-007: `/docs/ADR/007-three-tier-enrichment.md`
- MaxMind GeoLite2: https://dev.maxmind.com/geoip/geolite2-free-geolocation-data
- Team Cymru: https://www.team-cymru.com/ip-asn-mapping
- GreyNoise Community: https://docs.greynoise.io/docs/community-api
