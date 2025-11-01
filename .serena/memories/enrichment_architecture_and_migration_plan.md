# Enrichment Architecture and Database Cache Migration Plan

## Current Enrichment Architecture (Disk-Based Cache)

### Cache Implementation
**Location**: `cowrieprocessor/enrichment/cache.py`
**Class**: `EnrichmentCacheManager` (dataclass, 207 lines)

**Cache Storage**:
- **Location**: `/mnt/dshield/data/cache/` (configurable)
- **Structure**: Service-specific sharded directories
  - `virustotal/` - SHA256 file hash results
  - `dshield/` - IP reputation and geolocation
  - `urlhaus/` - Malware URL detection
  - `spur/` - IP intelligence
  - `hibp/` - Password breach data (k-anonymity hashes)

**Sharding Strategy**:
- VirusTotal: `{service}/{hash[:2]}/{hash}.json`
- DShield: `{service}/{normalized_ip}/{ip}.json`
- HIBP: `{service}/{prefix[:2]}/{prefix}.json`
- URLHaus/SPUR: Similar hex-sharded layouts

**TTL Configuration**:
```python
DEFAULT_TTLS = {
    "virustotal": 30 * 24 * 3600,        # 30 days
    "virustotal_unknown": 12 * 3600,     # 12 hours (for unknown files)
    "dshield": 7 * 24 * 3600,            # 7 days
    "urlhaus": 3 * 24 * 3600,            # 3 days
    "spur": 14 * 24 * 3600,              # 14 days
    "hibp": 60 * 24 * 3600,              # 60 days
}
```

### Enrichment Services
**Location**: `cowrieprocessor/enrichment/handlers.py`
**Class**: `EnrichmentService`

**Active Services**:
1. **VirusTotal** - File hash analysis, IP reputation
2. **DShield** - IP geolocation, ASN, attack counts
3. **URLHaus** - Malware URL detection and classification
4. **SPUR** - IP intelligence (VPN, proxy, hosting detection)
5. **HIBP** - Password breach detection (k-anonymity API)

**Service Integration**:
- Session enrichment: `enrich_session(session_id, src_ip)` → DShield, URLHaus, SPUR
- File enrichment: `enrich_file(file_hash, filename)` → VirusTotal
- Password enrichment: Separate CLI (`cowrie-enrich passwords`)
- SSH key enrichment: Separate CLI (`cowrie-enrich-ssh-keys`)

### Backfill Process
**Command**: `cowrie-enrich refresh`
**Location**: `cowrieprocessor/cli/enrich_passwords.py::refresh_enrichment()`

**Process Flow**:
1. Load database settings and API credentials
2. Initialize `EnrichmentCacheManager` with cache directory
3. Initialize `EnrichmentService` with API keys
4. Iterate through sessions: `iter_sessions(engine, session_limit)`
5. For each session: `service.enrich_session(session_id, src_ip)`
6. Update `session_summaries.enrichment` JSON field
7. Iterate through files: `iter_files(engine, file_limit)`
8. For each file: `service.enrich_file(file_hash, filename)`
9. Update `files.vt_analysis` JSON field

**Commit Strategy**:
- Batch commits every 100 items (configurable `--commit-interval`)
- Status emitter for real-time monitoring
- Cache statistics tracking (hits, misses, stores)

### Current Issues (User-Reported)

**Problem**: Enrichment data has lots of nulls in production database

**Possible Root Causes**:
1. **API Failures**: Rate limiting, timeouts, invalid API keys
2. **Backfill Not Running**: `cowrie-enrich refresh` not scheduled/automated
3. **Cache Misses**: Expired TTLs not being refilled
4. **Ingestion Gaps**: New sessions not being enriched during initial load
5. **Service Availability**: DShield, URLHaus, SPUR API downtime
6. **Error Handling**: Silent failures not being logged/tracked

**Diagnostic Questions**:
- What percentage of sessions have null enrichment data?
- Which services have the most nulls? (DShield vs URLHaus vs SPUR)
- Are older sessions enriched but newer sessions missing data?
- Are cache directories being populated? (disk space issues?)
- Are API credentials configured correctly in production?
- Is `cowrie-enrich refresh` running on a schedule?

## Why Database-Backed Cache for Milestone 2?

### Current Disk-Based Cache Limitations

**1. No Distributed Access**:
- File-based cache is local to each processing node
- Multiple workers can't share cache without network filesystem
- Cache coherency issues across distributed systems

**2. No Atomic Operations**:
- File writes are not transactional
- Race conditions possible with concurrent access
- No ACID guarantees for cache updates

**3. Limited Queryability**:
- Can't query "all cached IPs from China"
- Can't find "all files flagged by VirusTotal in last 7 days"
- No aggregate statistics without filesystem scan

**4. No Centralized Management**:
- Each node has separate cache state
- No central cache invalidation mechanism
- Cleanup requires cron job per node

**5. Filesystem Overhead**:
- Millions of small JSON files cause inode exhaustion
- Sharding helps but doesn't eliminate problem
- Directory traversal slow for cleanup operations

### Database-Backed Cache Advantages

**1. Distributed Access**:
- Single source of truth for all worker nodes
- Concurrent access with row-level locking
- Connection pooling for efficient access

**2. Transactional Semantics**:
- ACID guarantees for cache updates
- Atomic compare-and-swap operations
- Optimistic locking for race condition prevention

**3. Queryability**:
- SQL queries for cache analytics
- Find all cached entries by service, TTL, timestamp
- Join enrichment cache with session data for analysis

**4. Centralized Management**:
- Single TTL enforcement mechanism
- Central cache invalidation (DELETE WHERE service = 'dshield')
- Unified monitoring and alerting

**5. Scalability**:
- Database handles millions of rows efficiently
- Indexed lookups (service + cache_key)
- Automatic cleanup via PostgreSQL partitioning/TTL

## Proposed Database Cache Schema

### EnrichmentCache Table

```sql
CREATE TABLE enrichment_cache (
    id BIGSERIAL PRIMARY KEY,
    
    -- Cache key (service + identifier)
    service VARCHAR(32) NOT NULL,          -- 'virustotal', 'dshield', 'urlhaus', 'spur', 'hibp'
    cache_key VARCHAR(128) NOT NULL,       -- IP address, file hash, HIBP prefix
    cache_key_hash CHAR(64) NOT NULL,      -- SHA256(cache_key) for fast lookups
    
    -- Cached payload
    payload JSONB NOT NULL,                -- Enrichment response data
    response_status VARCHAR(32),           -- 'success', 'not_found', 'error', 'rate_limited'
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    accessed_at TIMESTAMP NOT NULL DEFAULT NOW(),  -- Updated on cache hit
    expires_at TIMESTAMP NOT NULL,         -- TTL expiration
    
    -- Metadata
    api_response_code INTEGER,             -- HTTP status code
    api_latency_ms INTEGER,                -- Response time for monitoring
    error_message TEXT,                    -- Error details if failed
    
    -- Statistics
    hit_count INTEGER NOT NULL DEFAULT 0,  -- Cache hit counter
    
    UNIQUE(service, cache_key_hash)
);

-- Indexes for performance
CREATE INDEX idx_enrichment_cache_lookup ON enrichment_cache(service, cache_key_hash);
CREATE INDEX idx_enrichment_cache_expires ON enrichment_cache(expires_at) WHERE expires_at < NOW();
CREATE INDEX idx_enrichment_cache_service ON enrichment_cache(service);
CREATE INDEX idx_enrichment_cache_payload_gin ON enrichment_cache USING GIN(payload);  -- For JSON queries

-- Automatic cleanup (PostgreSQL only)
CREATE INDEX idx_enrichment_cache_cleanup ON enrichment_cache(expires_at) WHERE expires_at < NOW();
```

### Cache Statistics Table (Optional)

```sql
CREATE TABLE enrichment_cache_stats (
    id SERIAL PRIMARY KEY,
    service VARCHAR(32) NOT NULL,
    
    -- Daily aggregates
    date DATE NOT NULL,
    cache_hits INTEGER NOT NULL DEFAULT 0,
    cache_misses INTEGER NOT NULL DEFAULT 0,
    cache_stores INTEGER NOT NULL DEFAULT 0,
    api_calls INTEGER NOT NULL DEFAULT 0,
    api_failures INTEGER NOT NULL DEFAULT 0,
    
    -- Performance metrics
    avg_api_latency_ms INTEGER,
    max_api_latency_ms INTEGER,
    
    -- Storage metrics
    total_entries INTEGER,
    expired_entries INTEGER,
    
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    UNIQUE(service, date)
);
```

## Migration Strategy

### Phase 1: Implement Database Cache Backend

**Tasks**:
1. Create `EnrichmentDatabaseCache` class in `cowrieprocessor/enrichment/db_cache.py`
2. Implement same interface as `EnrichmentCacheManager`:
   - `get_cached(service, key) -> Optional[dict]`
   - `store_cached(service, key, data) -> None`
   - `load_text(service, key) -> Optional[str]`
   - `store_text(service, key, payload) -> None`
3. Add migration script to create `enrichment_cache` table
4. Add configuration flag: `USE_DATABASE_CACHE` (environment variable)

### Phase 2: Dual-Cache Mode (Transition)

**Strategy**: Write-through cache (database primary, filesystem fallback)

**Implementation**:
1. Create `HybridCacheManager` that wraps both disk and DB caches
2. Read: Try database cache first, fallback to disk cache
3. Write: Write to both database and disk cache
4. Gradual migration: `cowrie-enrich migrate-cache --from-disk --to-database`

**Benefits**:
- Zero downtime migration
- Rollback capability if issues found
- Performance comparison (disk vs DB)

### Phase 3: Database-Only Mode

**Cutover**:
1. Verify database cache working in production (1-2 weeks)
2. Monitor cache hit rates, API call rates, performance
3. Set `USE_DATABASE_CACHE=true`, `DISABLE_DISK_CACHE=true`
4. Archive disk cache to backup location
5. Remove `EnrichmentCacheManager` disk-based code (future)

### Phase 4: Advanced Features

**Enhancements** (Post-Migration):
1. **Cache warming**: Pre-populate cache with known IPs/hashes
2. **Intelligent TTL**: Adjust TTL based on data volatility
3. **Cache analytics**: Query cache for threat intelligence insights
4. **Distributed invalidation**: Coordinate cache invalidation across workers
5. **Cache compression**: JSONB compression for storage efficiency

## Implementation Checklist

### Database Schema
- [ ] Create `enrichment_cache` table schema
- [ ] Create indexes for performance
- [ ] Create `enrichment_cache_stats` table (optional)
- [ ] Add schema migration script to `cowrieprocessor/db/migrations.py`
- [ ] Update `TARGET_SCHEMA_VERSION` constant

### Database Cache Implementation
- [ ] Create `EnrichmentDatabaseCache` class
- [ ] Implement `get_cached()` method with SQLAlchemy
- [ ] Implement `store_cached()` method with TTL calculation
- [ ] Implement `cleanup_expired()` method (DELETE WHERE expires_at < NOW())
- [ ] Add connection pooling configuration
- [ ] Add comprehensive error handling

### Hybrid Cache Manager
- [ ] Create `HybridCacheManager` wrapper class
- [ ] Implement read path (DB first, disk fallback)
- [ ] Implement write path (both DB and disk)
- [ ] Add configuration flags for cache backend selection
- [ ] Add metrics for cache source tracking

### Migration Tool
- [ ] Create `cowrie-enrich migrate-cache` command
- [ ] Implement disk-to-database migration script
- [ ] Add progress bar and status reporting
- [ ] Add validation and rollback capability
- [ ] Add dry-run mode for testing

### Testing
- [ ] Unit tests for `EnrichmentDatabaseCache`
- [ ] Integration tests for hybrid cache manager
- [ ] Performance benchmarks (disk vs DB)
- [ ] Load testing with concurrent workers
- [ ] Migration script testing

### Documentation
- [ ] ADR documenting cache migration decision
- [ ] Update CLAUDE.md with new cache architecture
- [ ] Update enrichment documentation
- [ ] Create runbook for cache migration
- [ ] Document rollback procedure

### Monitoring
- [ ] Add cache hit/miss metrics to telemetry
- [ ] Add cache size monitoring
- [ ] Add TTL expiration monitoring
- [ ] Add API call rate monitoring
- [ ] Create Grafana dashboard for cache analytics

## Diagnostic Queries (Current Issues)

### Check Enrichment Data Completeness

```sql
-- Session enrichment completeness
SELECT
    COUNT(*) as total_sessions,
    COUNT(enrichment) as enriched_sessions,
    COUNT(*) - COUNT(enrichment) as null_enrichment,
    ROUND(100.0 * COUNT(enrichment) / COUNT(*), 2) as enrichment_percentage
FROM session_summaries
WHERE first_event_at >= '2024-11-01';

-- Enrichment by service (PostgreSQL JSON operators)
SELECT
    COUNT(*) as total,
    COUNT(enrichment->'dshield') as dshield_count,
    COUNT(enrichment->'urlhaus') as urlhaus_count,
    COUNT(enrichment->'spur') as spur_count,
    ROUND(100.0 * COUNT(enrichment->'dshield') / COUNT(*), 2) as dshield_pct,
    ROUND(100.0 * COUNT(enrichment->'urlhaus') / COUNT(*), 2) as urlhaus_pct,
    ROUND(100.0 * COUNT(enrichment->'spur') / COUNT(*), 2) as spur_pct
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND enrichment IS NOT NULL;

-- File enrichment completeness
SELECT
    COUNT(*) as total_files,
    COUNT(vt_analysis) as vt_enriched,
    COUNT(*) - COUNT(vt_analysis) as null_vt,
    ROUND(100.0 * COUNT(vt_analysis) / COUNT(*), 2) as vt_enrichment_pct
FROM files;
```

### Cache Statistics (Disk-Based)

```bash
# Check cache directory sizes
du -sh /mnt/dshield/data/cache/*

# Count cached files per service
find /mnt/dshield/data/cache/virustotal -name "*.json" | wc -l
find /mnt/dshield/data/cache/dshield -name "*.json" | wc -l
find /mnt/dshield/data/cache/urlhaus -name "*.json" | wc -l
find /mnt/dshield/data/cache/spur -name "*.json" | wc -l

# Check cache age distribution
find /mnt/dshield/data/cache -name "*.json" -mtime +30  # Older than 30 days
find /mnt/dshield/data/cache -name "*.json" -mtime -7   # Newer than 7 days
```

## Next Actions

### Immediate (Diagnostic)
1. Run enrichment completeness queries on production DB
2. Check cache directory statistics on production server
3. Review logs for enrichment API failures
4. Verify API credentials are configured correctly
5. Check if `cowrie-enrich refresh` is scheduled in cron

### Short-Term (Backfill)
1. Run manual backfill: `cowrie-enrich refresh --sessions 0 --files 0`
2. Monitor backfill progress and error rates
3. Identify specific services with high failure rates
4. Fix any API key or rate limiting issues

### Medium-Term (Database Cache Design)
1. Create ADR for cache migration decision
2. Design database schema with team review
3. Prototype `EnrichmentDatabaseCache` implementation
4. Benchmark performance (disk vs DB cache)

### Long-Term (Migration)
1. Implement hybrid cache manager
2. Create migration tooling
3. Test in staging environment
4. Gradual production rollout
5. Monitor and optimize

## Risks and Mitigation

**Risk 1: Database Performance**
- **Concern**: Database cache slower than disk cache
- **Mitigation**: Benchmark before migration, use connection pooling, optimize indexes
- **Fallback**: Hybrid mode with in-memory LRU cache layer

**Risk 2: Migration Complexity**
- **Concern**: Migrating millions of cached entries
- **Mitigation**: Gradual migration, write-through cache, validation tooling
- **Fallback**: Keep disk cache as fallback during transition

**Risk 3: Storage Costs**
- **Concern**: Database storage more expensive than disk
- **Mitigation**: Aggressive TTL management, JSONB compression, archival strategy
- **Fallback**: Tiered storage (hot in DB, cold on disk)

**Risk 4: Distributed Coordination**
- **Concern**: Cache invalidation across multiple workers
- **Mitigation**: Database transactions provide natural coordination
- **Fallback**: Short TTLs reduce stale data risk

## Success Metrics

**Enrichment Coverage**:
- Target: 95%+ of sessions with enrichment data
- Current: Unknown (needs diagnostic query)
- Improvement: Automated backfill on schedule

**Cache Performance**:
- Target: <10ms database cache lookup
- Baseline: <5ms disk cache lookup
- Trade-off: 2x latency acceptable for distributed benefits

**API Call Reduction**:
- Target: 90%+ cache hit rate
- Current: Unknown (needs monitoring)
- Improvement: Better TTL management, cache warming

**Operational Simplicity**:
- Target: Zero-maintenance cache cleanup
- Current: Cron jobs for disk cleanup
- Improvement: Database partitioning or scheduled DELETE

## Timeline Estimate

**Diagnostic Phase**: 2-3 days
- Run queries, analyze logs, identify root causes

**Backfill Phase**: 1-2 weeks
- Fix immediate issues, run manual backfills, monitor

**Design Phase**: 1 week
- ADR, schema design, team review, prototyping

**Implementation Phase**: 2-3 weeks
- Database cache, hybrid manager, migration tooling

**Testing Phase**: 1-2 weeks
- Unit tests, integration tests, performance benchmarks

**Migration Phase**: 2-4 weeks
- Staging deployment, production rollout, monitoring

**Total**: 7-13 weeks (1.5-3 months)

## References

**Code Locations**:
- `cowrieprocessor/enrichment/cache.py` - Current disk cache
- `cowrieprocessor/enrichment/handlers.py` - Enrichment services
- `cowrieprocessor/cli/enrich_passwords.py` - Backfill CLI

**Related ADRs**:
- ADR-002: Multi-Container Architecture (distributed processing context)
- ADR-003: Snowshoe Spam Detection (enrichment usage)
- ADR-004: K3s Architecture (distributed deployment)

**External References**:
- PostgreSQL JSONB Performance: https://www.postgresql.org/docs/current/datatype-json.html
- SQLAlchemy Connection Pooling: https://docs.sqlalchemy.org/en/20/core/pooling.html
- Redis vs PostgreSQL for Caching: https://redis.io/topics/lru-cache
