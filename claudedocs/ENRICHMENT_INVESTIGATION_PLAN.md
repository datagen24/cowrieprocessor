# Enrichment Investigation and Database Cache Migration Plan

**Date**: 2025-11-01
**Context**: User reported "enrichment data has a lot of nulls" in production database
**Mission**: Diagnose enrichment gaps and plan migration to database-backed cache for Milestone 2

---

## Executive Summary

The enrichment subsystem currently uses **disk-based caching** with individual JSON files sharded across service-specific directories. User reports indicate **many null enrichment values** in the production database, suggesting backfill processes may not be working correctly.

Additionally, for **Milestone 2 (distributed processing)**, we need to **migrate from disk-based to database-backed caching** to support:
- Distributed worker nodes sharing a single cache
- Atomic cache operations with ACID guarantees
- SQL-based cache analytics and invalidation
- Centralized cache management and monitoring

---

## Current Architecture (Disk-Based Cache)

### Cache Implementation
**Location**: `cowrieprocessor/enrichment/cache.py`
**Class**: `EnrichmentCacheManager` (207 lines)

**Cache Storage**:
```
/mnt/dshield/data/cache/
├── virustotal/          # File hash results (30-day TTL)
├── dshield/            # IP reputation/geolocation (7-day TTL)
├── urlhaus/            # Malware URL detection (3-day TTL)
├── spur/               # IP intelligence (14-day TTL)
└── hibp/               # Password breach data (60-day TTL)
```

**Sharding Strategy**:
- Files stored as `{service}/{hash[:2]}/{hash}.json`
- Prevents excessive files-per-directory issues
- Each service has custom path builder for optimal layout

### Enrichment Services
**Location**: `cowrieprocessor/enrichment/handlers.py`
**Class**: `EnrichmentService`

**Active Services**:
1. **VirusTotal** - File hash analysis, IP reputation
2. **DShield** - IP geolocation, ASN, attack counts
3. **URLHaus** - Malware URL detection
4. **SPUR** - IP intelligence (VPN/proxy detection)
5. **HIBP** - Password breach detection (k-anonymity API)

### Backfill Process
**Command**: `cowrie-enrich refresh`
**Location**: `cowrieprocessor/cli/enrich_passwords.py::refresh_enrichment()`

**Process**:
1. Iterate through sessions with `iter_sessions(engine, limit)`
2. Call `service.enrich_session(session_id, src_ip)` for each
3. Update `session_summaries.enrichment` JSON field
4. Iterate through files with `iter_files(engine, limit)`
5. Call `service.enrich_file(file_hash, filename)` for each
6. Update `files.vt_analysis` JSON field

**Current Issues**:
- Backfill may not be running on schedule
- API failures may be silently ignored
- Cache TTLs may be expiring without refills
- Rate limiting may be blocking enrichment

---

## Diagnostic Investigation

### Created Diagnostic Queries
**File**: `scripts/phase1/ENRICHMENT_DIAGNOSTIC_QUERIES.sql`

**10 Diagnostic Queries**:
1. **Session Enrichment Completeness** - Overall enrichment percentage
2. **Enrichment by Service** - Which services (DShield, URLHaus, SPUR) have gaps
3. **Enrichment by Time Period** - Detect when backfill stopped working
4. **File Enrichment Completeness** - VirusTotal coverage
5. **Enrichment Flags vs Data Consistency** - Detect data integrity issues
6. **Sample Sessions** - Inspect enrichment JSON structure
7. **Enrichment by Sensor** - Check for sensor-specific issues
8. **High-Value Sessions Without Enrichment** - Priority backfill targets
9. **Enrichment Error Patterns (DLQ)** - Check Dead Letter Queue for failures
10. **Password Enrichment (HIBP)** - Check HIBP breach data coverage

### Expected Healthy Results
- **Session enrichment**: >90% coverage
- **DShield**: >95% (free API, should be highest)
- **URLHaus**: >90%
- **SPUR**: >80% (requires API key, may be lower)
- **VirusTotal**: >80% for files
- **HIBP**: >80% for passwords

### Interpretation Guide
- **Query 1 < 90%**: Immediate backfill needed
- **Query 2 dshield < 95%**: API key or rate limiting issues
- **Query 3 declining trend**: Backfill stopped working
- **Query 4 < 80%**: VirusTotal API key issue
- **Query 9 high DLQ entries**: Error handling problems

---

## Immediate Action Plan (Diagnostic Phase)

### Step 1: Run Diagnostic Queries (30 minutes)
```bash
# Open PGAdmin, connect to production database
# Execute: scripts/phase1/ENRICHMENT_DIAGNOSTIC_QUERIES.sql
# Save results to spreadsheet or markdown
```

**Focus on queries 1-3 first** to understand overall enrichment health.

### Step 2: Check Cache Directory Statistics (15 minutes)
```bash
# SSH to production server
du -sh /mnt/dshield/data/cache/*
find /mnt/dshield/data/cache/virustotal -name "*.json" | wc -l
find /mnt/dshield/data/cache/dshield -name "*.json" | wc -l
find /mnt/dshield/data/cache/urlhaus -name "*.json" | wc -l
find /mnt/dshield/data/cache/spur -name "*.json" | wc -l

# Check cache age distribution
find /mnt/dshield/data/cache -name "*.json" -mtime +30  # Older than 30 days
find /mnt/dshield/data/cache -name "*.json" -mtime -7   # Newer than 7 days
```

### Step 3: Review Enrichment Logs (15 minutes)
```bash
# Check for enrichment errors
grep -i "enrichment" /var/log/cowrieprocessor/*.log | tail -500

# Check for API failures
grep -i "virustotal\|dshield\|urlhaus\|spur" /var/log/cowrieprocessor/*.log | grep -i "error\|fail"

# Check for rate limiting
grep -i "rate limit\|429\|quota" /var/log/cowrieprocessor/*.log
```

### Step 4: Verify API Credentials (10 minutes)
```bash
# Check if API keys are configured
grep -E "VT_API_KEY|DSHIELD_EMAIL|URLHAUS_API_KEY|SPUR_API_KEY" config/sensors.toml

# Test API connectivity (manual curl)
curl -H "x-apikey: $VT_API_KEY" https://www.virustotal.com/api/v3/files/hash
curl "https://isc.sans.edu/api/ip/$IP?json"
```

### Step 5: Run Manual Backfill (User Action)
```bash
# If diagnostic queries show <90% enrichment, run backfill
uv run cowrie-enrich refresh --sessions 0 --files 0 \
    --vt-api-key $VT_API_KEY \
    --dshield-email $DSHIELD_EMAIL \
    --urlhaus-api-key $URLHAUS_API_KEY \
    --spur-api-key $SPUR_API_KEY \
    --verbose

# Monitor progress
tail -f ~/.cache/cowrieprocessor/status/enrichment_refresh.json
```

**Expected Duration**: 1-24 hours depending on session count

---

## Database Cache Migration Plan

### Why Migrate to Database-Backed Cache?

**Current Disk-Based Limitations**:
1. **No distributed access** - Each worker has separate cache
2. **No atomic operations** - Race conditions possible
3. **Limited queryability** - Can't query cached data with SQL
4. **No centralized management** - Cleanup requires per-node cron jobs
5. **Filesystem overhead** - Millions of small files cause inode issues

**Database-Backed Advantages**:
1. **Single source of truth** - All workers share one cache
2. **ACID guarantees** - Transactional cache updates
3. **SQL queryability** - Cache analytics and monitoring
4. **Centralized management** - TTL enforcement, invalidation
5. **Scalability** - Database handles millions of rows efficiently

### Proposed Database Schema

```sql
CREATE TABLE enrichment_cache (
    id BIGSERIAL PRIMARY KEY,

    -- Cache key
    service VARCHAR(32) NOT NULL,          -- 'virustotal', 'dshield', etc.
    cache_key VARCHAR(128) NOT NULL,       -- IP address, file hash, HIBP prefix
    cache_key_hash CHAR(64) NOT NULL,      -- SHA256(cache_key) for fast lookups

    -- Cached payload
    payload JSONB NOT NULL,                -- Enrichment response data
    response_status VARCHAR(32),           -- 'success', 'not_found', 'error'

    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    accessed_at TIMESTAMP NOT NULL DEFAULT NOW(),  -- Updated on cache hit
    expires_at TIMESTAMP NOT NULL,         -- TTL expiration

    -- Metadata
    api_response_code INTEGER,             -- HTTP status code
    api_latency_ms INTEGER,                -- Response time
    error_message TEXT,                    -- Error details

    -- Statistics
    hit_count INTEGER NOT NULL DEFAULT 0,  -- Cache hit counter

    UNIQUE(service, cache_key_hash)
);

-- Indexes
CREATE INDEX idx_enrichment_cache_lookup ON enrichment_cache(service, cache_key_hash);
CREATE INDEX idx_enrichment_cache_expires ON enrichment_cache(expires_at);
CREATE INDEX idx_enrichment_cache_payload_gin ON enrichment_cache USING GIN(payload);
```

### Migration Strategy (3-Phase Rollout)

**Phase 1: Implement Database Cache Backend** (2-3 weeks)
- Create `EnrichmentDatabaseCache` class in `cowrieprocessor/enrichment/db_cache.py`
- Implement same interface as `EnrichmentCacheManager`
- Add migration script for `enrichment_cache` table
- Add configuration flag: `USE_DATABASE_CACHE` (environment variable)

**Phase 2: Dual-Cache Mode (Transition)** (1-2 weeks)
- Create `HybridCacheManager` wrapper class
- Read: Try database cache first, fallback to disk cache
- Write: Write to both database and disk cache (write-through)
- Create migration tool: `cowrie-enrich migrate-cache --from-disk --to-database`
- Benefits: Zero downtime, rollback capability, performance comparison

**Phase 3: Database-Only Mode** (2-4 weeks)
- Monitor database cache in production (1-2 weeks validation)
- Set `USE_DATABASE_CACHE=true`, `DISABLE_DISK_CACHE=true`
- Archive disk cache to backup location
- Remove disk-based code (future cleanup)

### Migration Timeline

| Phase | Duration | Milestone |
|-------|----------|-----------|
| **Diagnostic** | 2-3 days | Understand current enrichment gaps |
| **Backfill** | 1-2 weeks | Fix immediate issues, run manual backfills |
| **Design** | 1 week | ADR, schema design, team review |
| **Implementation** | 2-3 weeks | Database cache, hybrid manager, migration tooling |
| **Testing** | 1-2 weeks | Unit tests, integration tests, benchmarks |
| **Migration** | 2-4 weeks | Staging deployment, production rollout |
| **Total** | **7-13 weeks** | **(1.5-3 months)** |

---

## Implementation Checklist

### Database Schema (Week 1)
- [ ] Create `enrichment_cache` table schema
- [ ] Create indexes for performance
- [ ] Add schema migration to `cowrieprocessor/db/migrations.py`
- [ ] Update `TARGET_SCHEMA_VERSION` constant
- [ ] Add rollback script

### Database Cache Implementation (Weeks 2-3)
- [ ] Create `EnrichmentDatabaseCache` class
- [ ] Implement `get_cached()` with SQLAlchemy
- [ ] Implement `store_cached()` with TTL calculation
- [ ] Implement `cleanup_expired()` method
- [ ] Add connection pooling configuration
- [ ] Add comprehensive error handling

### Hybrid Cache Manager (Week 4)
- [ ] Create `HybridCacheManager` wrapper
- [ ] Implement read path (DB first, disk fallback)
- [ ] Implement write path (both DB and disk)
- [ ] Add configuration flags
- [ ] Add cache source tracking metrics

### Migration Tool (Week 5)
- [ ] Create `cowrie-enrich migrate-cache` command
- [ ] Implement disk-to-database migration script
- [ ] Add progress bar and status reporting
- [ ] Add validation and rollback capability
- [ ] Add dry-run mode

### Testing (Weeks 6-7)
- [ ] Unit tests for `EnrichmentDatabaseCache`
- [ ] Integration tests for hybrid cache manager
- [ ] Performance benchmarks (disk vs DB)
- [ ] Load testing with concurrent workers
- [ ] Migration script testing

### Documentation (Week 8)
- [ ] Create ADR for cache migration decision
- [ ] Update CLAUDE.md with new cache architecture
- [ ] Update enrichment documentation
- [ ] Create runbook for cache migration
- [ ] Document rollback procedure

### Production Rollout (Weeks 9-13)
- [ ] Deploy to staging environment
- [ ] Run migration on staging
- [ ] Monitor staging for 1 week
- [ ] Deploy to production
- [ ] Run migration on production
- [ ] Monitor for 2-4 weeks

---

## Risks and Mitigation

### Risk 1: Database Performance
- **Concern**: Database cache slower than disk cache
- **Mitigation**: Benchmark before migration, use connection pooling, optimize indexes
- **Fallback**: Hybrid mode with in-memory LRU cache layer

### Risk 2: Migration Complexity
- **Concern**: Migrating millions of cached entries
- **Mitigation**: Gradual migration, write-through cache, validation tooling
- **Fallback**: Keep disk cache as fallback during transition

### Risk 3: Storage Costs
- **Concern**: Database storage more expensive than disk
- **Mitigation**: Aggressive TTL management, JSONB compression, archival strategy
- **Fallback**: Tiered storage (hot in DB, cold on disk)

### Risk 4: Distributed Coordination
- **Concern**: Cache invalidation across multiple workers
- **Mitigation**: Database transactions provide natural coordination
- **Fallback**: Short TTLs reduce stale data risk

---

## Success Metrics

### Enrichment Coverage (Current Issue)
- **Target**: 95%+ of sessions with enrichment data
- **Current**: Unknown (run diagnostic queries)
- **Action**: Automated backfill on schedule

### Cache Performance (Post-Migration)
- **Target**: <10ms database cache lookup
- **Baseline**: <5ms disk cache lookup
- **Trade-off**: 2x latency acceptable for distributed benefits

### API Call Reduction
- **Target**: 90%+ cache hit rate
- **Current**: Unknown (needs monitoring)
- **Improvement**: Better TTL management, cache warming

### Operational Simplicity
- **Target**: Zero-maintenance cache cleanup
- **Current**: Cron jobs for disk cleanup
- **Improvement**: Database partitioning or scheduled DELETE

---

## Next Actions

### Immediate (You)
1. ✅ Run diagnostic queries in PGAdmin
2. ✅ Check cache directory statistics on production server
3. ✅ Review logs for enrichment API failures
4. ✅ Verify API credentials are configured
5. ✅ Run manual backfill if enrichment <90%

### Short-Term (1-2 weeks)
1. Monitor backfill progress and error rates
2. Identify specific services with high failure rates
3. Fix any API key or rate limiting issues
4. Schedule automated backfill (cron job)

### Medium-Term (1-2 months)
1. Create ADR for cache migration decision
2. Design database schema with team review
3. Prototype `EnrichmentDatabaseCache` implementation
4. Benchmark performance (disk vs DB cache)

### Long-Term (2-4 months)
1. Implement hybrid cache manager
2. Create migration tooling
3. Test in staging environment
4. Gradual production rollout
5. Monitor and optimize

---

## Files Created

### Diagnostic Tools
- ✅ `scripts/phase1/ENRICHMENT_DIAGNOSTIC_QUERIES.sql` - 10 diagnostic queries
- ✅ `claudedocs/ENRICHMENT_INVESTIGATION_PLAN.md` - This document

### Memory Files
- ✅ `enrichment_architecture_and_migration_plan` - Comprehensive technical reference

### Todo List
- ✅ Added enrichment investigation and migration tasks to TodoWrite

---

## Related Documentation

**Code Locations**:
- `cowrieprocessor/enrichment/cache.py` - Current disk cache (207 lines)
- `cowrieprocessor/enrichment/handlers.py` - Enrichment services (680 lines)
- `cowrieprocessor/cli/enrich_passwords.py` - Backfill CLI (1,580 lines)

**Related ADRs**:
- ADR-002: Multi-Container Architecture (distributed processing context)
- ADR-003: Snowshoe Spam Detection (enrichment usage)
- ADR-004: K3s Architecture (distributed deployment)
- **Future**: ADR-005: Database-Backed Enrichment Cache (to be created)

**CLAUDE.md References**:
- Line 146: "Enrichment Pipeline: All API enrichments flow through unified caching layer"
- Line 162: "ORM-First: All database operations use SQLAlchemy 2.0 ORM"
- Line 265: "DShield, URLHaus, SPUR, OTX, AbuseIPDB integration patterns"

---

**Status**: ✅ Diagnostic tools ready, investigation plan documented
**Next Action**: Run diagnostic queries in PGAdmin to understand enrichment gaps
**Timeline**: Diagnostic phase 2-3 days, full migration 1.5-3 months
