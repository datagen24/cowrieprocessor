# ADR 005: Hybrid Database + Redis Enrichment Cache Architecture

**Status**: Proposed
**Date**: 2025-11-01
**Context**: Enrichment Recovery & Performance Optimization - Milestone 2
**Deciders**: Architecture Review
**Related ADRs**:
- **ADR-002**: Multi-Container Service Architecture (Redis shared service, cache layer foundation)
- **ADR-003**: SQLite Deprecation (Database cache requires PostgreSQL JSONB, concurrent writes)

## Context and Problem Statement

The current enrichment system uses filesystem-based caching (`EnrichmentCacheManager`) with service-specific directory layouts (sharded hexadecimal for VirusTotal, IP octets for DShield, SHA-1 prefixes for HIBP). While this approach works, it has significant limitations:

### Current Architecture Issues

1. **Cache Fragility**:
   - Lost cache data on system failures
   - No backup/recovery mechanism
   - Difficult to migrate between systems
   - No atomic operations (race conditions possible)

2. **Performance Bottleneck**:
   - Disk I/O overhead for every cache lookup
   - No in-memory fast path for frequently accessed items
   - Sequential processing with repeated cache hits still hits disk
   - TTL validation requires filesystem metadata checks

3. **Operational Complexity**:
   - Manual cache directory management
   - Cleanup requires scanning entire filesystem
   - No centralized monitoring/metrics
   - Difficult to analyze cache effectiveness

4. **Enrichment Run Context**:
   - **Key Insight**: During enrichment runs, some records are accessed multiple times within the same batch
   - Example: 100 sessions from same IP → 100 DShield lookups → should hit memory cache after first
   - Example: Common malware hashes → repeated VirusTotal queries in same batch
   - Current system: Each lookup hits disk, even for identical keys within same run

### Deployment Context

- **Database Diversity**: PostgreSQL (production), SQLite (development/research - see ADR-003 for deprecation timeline)
- **Scale**: 1.43M+ raw events, ~500K sessions, growing daily
- **API Rate Limits**: VirusTotal (4 req/min), DShield (30 req/min), HIBP (k-anonymity unlimited)
- **Cache Size**: Current filesystem cache ~2.5GB across all services
- **Access Patterns**:
  - Bulk enrichment: High cache hit rate (70-90% for IPs, 30-50% for file hashes)
  - Real-time processing: Lower hit rate (10-30%)
  - Intra-batch repeats: Common (20-40% of requests in same batch)

### Multi-Container Architecture Alignment (ADR-002)

This ADR builds upon the multi-container architecture proposed in **ADR-002**, which already includes:

1. **Redis Shared Service**: ADR-002 specifies Redis for job queue management and caching
2. **Data Loader Containers**: Multiple loaders processing enrichment concurrently (requires atomic cache operations)
3. **Analysis Worker Containers**: CPU-intensive workers benefit from fast cache lookups
4. **PostgreSQL Primary + Read Replicas**: Database infrastructure to support durable cache layer

**Key Synergies**:
- **Redis already planned**: ADR-002 includes Redis as a shared service, this ADR extends its use to enrichment caching
- **Concurrent access**: Multiple data loader containers require atomic cache operations (database UPSERT) instead of filesystem race conditions
- **Worker efficiency**: Analysis workers benefit from sub-millisecond Redis cache hits during bulk processing
- **Shared infrastructure**: Leverages existing PostgreSQL and Redis from multi-container deployment

**Multi-Container Cache Flow**:
```
┌──────────────────────────────────────────────────────────────┐
│ Multi-Container Deployment (ADR-002)                         │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │Data Loader 1│  │Data Loader 2│  │Data Loader N│         │
│  │ (Sensor A)  │  │ (Sensor B)  │  │ (Sensor X)  │         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         │                │                │                 │
│         └────────────────┼────────────────┘                 │
│                          │                                  │
│              ┌───────────▼───────────┐                      │
│              │  Redis Cache (L1)     │ ← Shared, atomic     │
│              │  (Hot enrichment data)│                      │
│              └───────────┬───────────┘                      │
│                          │                                  │
│              ┌───────────▼───────────┐                      │
│              │  PostgreSQL (L2)      │ ← Durable, JSONB     │
│              │  enrichment_cache tbl │                      │
│              └───────────┬───────────┘                      │
│                          │                                  │
│                    [External APIs]                          │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**Why Database Cache Requires PostgreSQL** (per ADR-003):

Multi-container enrichment requires PostgreSQL for the database cache layer:

1. **Concurrent Writes**: Multiple data loader containers writing to cache simultaneously
   - PostgreSQL: `ON CONFLICT DO UPDATE` (atomic UPSERT)
   - SQLite: `database is locked` errors with concurrent writers

2. **JSONB Support**: Efficient storage and querying of enrichment payloads
   - PostgreSQL: Native `JSONB` type with operators (`->`, `->>`, `@>`)
   - SQLite: `TEXT` JSON storage with slower `json_extract()` functions

3. **Network Access**: Cloud-deployed workers need remote database access
   - PostgreSQL: TCP/IP client-server architecture
   - SQLite: File-based, requires filesystem mount (not feasible for distributed workers)

4. **Read Replicas**: MCP API container queries cache without blocking writes
   - PostgreSQL: Streaming replication for read replicas
   - SQLite: No replication mechanism

**Timeline Alignment**: This cache migration work should target **V4.5** (Q3 2026) when SQLite is deprecated for monolithic deployments. This allows:
- V4.0 (Q1 2026): Multi-container launches with Redis job queue, filesystem cache operational
- V4.5 (Q3 2026): Database cache + Redis L1 deployed, filesystem cache deprecated alongside SQLite
- V5.0 (Q4 2026): Filesystem cache removed entirely with SQLite removal

## Decision Drivers

1. **Durability**: Cache must survive system restarts and failures
2. **Performance**: Sub-millisecond cache lookups for hot data
3. **Intra-Batch Optimization**: Eliminate repeated disk I/O within single enrichment run
4. **Portability**: Must work on PostgreSQL and SQLite
5. **Operational Simplicity**: Easy backup, monitoring, cleanup
6. **Cost Efficiency**: Minimize API quota usage through better cache hit rates
7. **Atomicity**: Prevent race conditions during cache updates
8. **Observability**: Centralized metrics for cache effectiveness

## Considered Options

### Option A: Keep Filesystem Cache (Status Quo - REJECTED)

**Current Implementation** (`cowrieprocessor/enrichment/cache.py`):
```python
class EnrichmentCacheManager:
    base_dir: Path  # /mnt/dshield/data/cache
    ttls: Dict[str, int]  # virustotal: 30d, dshield: 7d, hibp: 60d

    def get_cached(service: str, key: str) -> Optional[dict]:
        # Disk lookup with TTL validation
        cache_path = self._paths_for_key(service, key)
        if not cache_path.exists() or not self._is_valid(cache_path, service):
            return None
        return json.loads(cache_path.read_text())
```

**Pros**:
- ✅ No schema changes required
- ✅ Works today

**Cons**:
- ❌ Lost cache on disk failure
- ❌ Disk I/O for every lookup (even repeated keys)
- ❌ No atomic operations
- ❌ No centralized monitoring
- ❌ Manual cleanup required
- ❌ No protection against intra-batch repeated lookups

### Option B: Pure Database Cache (REJECTED)

**Schema**:
```sql
CREATE TABLE enrichment_cache (
    id SERIAL PRIMARY KEY,
    service VARCHAR(32) NOT NULL,
    cache_key VARCHAR(512) NOT NULL,
    cache_value JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    UNIQUE (service, cache_key)
);
CREATE INDEX idx_cache_expiry ON enrichment_cache (service, expires_at);
```

**Pros**:
- ✅ Durable (database backups)
- ✅ Atomic operations (UPSERT)
- ✅ Easy cleanup (DELETE WHERE expires_at < NOW())
- ✅ Centralized monitoring

**Cons**:
- ❌ Database query overhead for every lookup
- ❌ No in-memory fast path
- ❌ Repeated queries within same batch still hit database
- ❌ Increased database load during bulk enrichment
- ❌ Network latency for remote databases

### Option C: Pure Redis Cache (REJECTED)

**Implementation**:
```python
# Redis with automatic TTL
redis.setex(f"{service}:{key}", ttl_seconds, json.dumps(data))
result = redis.get(f"{service}:{key}")
```

**Pros**:
- ✅ In-memory speed (sub-millisecond)
- ✅ Built-in TTL support
- ✅ Atomic operations
- ✅ High throughput

**Cons**:
- ❌ Volatile (lost on Redis restart unless persistence configured)
- ❌ Additional infrastructure dependency
- ❌ Memory limits (eviction policies needed)
- ❌ Not available in SQLite development environments
- ❌ Operational overhead (monitoring, backup, cluster management)

### Option D: Hybrid Database + Redis (3-Tier) - **ACCEPTED**

**Architecture**:
```
┌─────────────────────────────────────────────────────────┐
│ Enrichment Service Request                              │
└─────────────────────┬───────────────────────────────────┘
                      ▼
         ┌────────────────────────┐
         │ L1: Redis Hot Cache    │ ← Session-scoped, batch-aware
         │ TTL: 1 hour            │   (Intra-batch optimization)
         │ Size: 100MB limit      │
         └────────┬───────────────┘
                  │ Miss ▼
         ┌────────────────────────┐
         │ L2: Database Cache     │ ← Durable, shared across runs
         │ TTL: Service-specific  │   (30d VT, 7d DShield, 60d HIBP)
         │ Size: Unlimited        │
         └────────┬───────────────┘
                  │ Miss ▼
         ┌────────────────────────┐
         │ L3: External API       │ ← VirusTotal, DShield, HIBP, etc.
         │ Rate limited           │
         └────────────────────────┘
```

#### Tier 1: Redis Hot Cache (In-Memory)

**Purpose**: Eliminate intra-batch repeated lookups
- **Scope**: Single enrichment run or batch processing session
- **TTL**: Short (1 hour) - just enough for batch completion
- **Eviction**: LRU when memory limit reached
- **Availability**: Optional (degrades gracefully if Redis unavailable)

**Use Case Example**:
```python
# Enrichment batch: 1000 sessions from 50 unique IPs
# Without Redis: 1000 DShield lookups (990 hit DB cache)
# With Redis: 50 DShield lookups (950 hit Redis, 50 hit DB/API)
```

#### Tier 2: Database Cache (Durable)

**Purpose**: Long-term, durable cache shared across all enrichment runs

**PostgreSQL Schema**:
```sql
CREATE TABLE enrichment_cache (
    id BIGSERIAL PRIMARY KEY,
    service VARCHAR(32) NOT NULL,          -- 'virustotal', 'dshield', 'hibp', etc.
    cache_key VARCHAR(512) NOT NULL,       -- Hash, IP, SHA-1 prefix, etc.
    cache_value JSONB NOT NULL,            -- Service response payload
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  -- Track hot keys
    expires_at TIMESTAMPTZ NOT NULL,       -- Service-specific TTL
    hit_count INTEGER NOT NULL DEFAULT 0,  -- Observability metric

    CONSTRAINT uq_enrichment_cache_service_key UNIQUE (service, cache_key)
);

CREATE INDEX idx_enrichment_cache_expiry ON enrichment_cache (service, expires_at);
CREATE INDEX idx_enrichment_cache_accessed ON enrichment_cache (accessed_at DESC);
CREATE INDEX idx_enrichment_cache_hits ON enrichment_cache (hit_count DESC);

-- Automatic cleanup function
CREATE OR REPLACE FUNCTION cleanup_expired_cache()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM enrichment_cache WHERE expires_at < NOW();
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;
```

**SQLite Schema** (compatible subset):
```sql
CREATE TABLE enrichment_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    cache_value TEXT NOT NULL,             -- JSON text instead of JSONB
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    accessed_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0,

    UNIQUE (service, cache_key)
);

CREATE INDEX idx_enrichment_cache_expiry ON enrichment_cache (service, expires_at);
CREATE INDEX idx_enrichment_cache_accessed ON enrichment_cache (accessed_at DESC);
CREATE INDEX idx_enrichment_cache_hits ON enrichment_cache (hit_count DESC);
```

#### Tier 3: External APIs (Rate Limited)

**Purpose**: Source of truth when cache misses

**Flow**: On cache miss → API call → Store in DB cache → Store in Redis cache → Return to caller

#### Implementation Strategy

```python
from __future__ import annotations
from typing import Optional, Protocol
import json
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

class CacheBackend(Protocol):
    """Protocol for cache backend implementations."""
    def get(self, service: str, key: str) -> Optional[dict]: ...
    def set(self, service: str, key: str, value: dict, ttl_seconds: int) -> None: ...
    def delete(self, service: str, key: str) -> None: ...

@dataclass
class RedisCache:
    """Redis L1 cache implementation."""
    client: Redis  # type: ignore[name-defined]
    prefix: str = "cowrie:cache"

    def get(self, service: str, key: str) -> Optional[dict]:
        redis_key = f"{self.prefix}:{service}:{key}"
        data = self.client.get(redis_key)
        return json.loads(data) if data else None

    def set(self, service: str, key: str, value: dict, ttl_seconds: int) -> None:
        redis_key = f"{self.prefix}:{service}:{key}"
        self.client.setex(redis_key, ttl_seconds, json.dumps(value))

@dataclass
class DatabaseCache:
    """Database L2 cache implementation."""
    session: Session  # SQLAlchemy session

    def get(self, service: str, key: str) -> Optional[dict]:
        from cowrieprocessor.db.models import EnrichmentCache

        cache_entry = (
            self.session.query(EnrichmentCache)
            .filter(
                EnrichmentCache.service == service,
                EnrichmentCache.cache_key == key,
                EnrichmentCache.expires_at > datetime.now(timezone.utc)
            )
            .first()
        )

        if cache_entry:
            # Update access metrics
            cache_entry.accessed_at = datetime.now(timezone.utc)
            cache_entry.hit_count += 1
            self.session.commit()
            return cache_entry.cache_value  # JSONB auto-deserializes

        return None

    def set(self, service: str, key: str, value: dict, ttl_seconds: int) -> None:
        from cowrieprocessor.db.models import EnrichmentCache

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

        # UPSERT using PostgreSQL ON CONFLICT or SQLite INSERT OR REPLACE
        cache_entry = EnrichmentCache(
            service=service,
            cache_key=key,
            cache_value=value,
            expires_at=expires_at,
        )

        self.session.merge(cache_entry)
        self.session.commit()

class HybridEnrichmentCache:
    """3-tier hybrid cache: Redis (L1) → Database (L2) → API (L3)."""

    def __init__(
        self,
        db_cache: DatabaseCache,
        redis_cache: Optional[RedisCache] = None,
        ttls: Optional[dict[str, int]] = None,
    ):
        self.db_cache = db_cache
        self.redis_cache = redis_cache
        self.ttls = ttls or {
            "virustotal": 30 * 24 * 3600,      # 30 days
            "virustotal_unknown": 12 * 3600,   # 12 hours
            "dshield": 7 * 24 * 3600,          # 7 days
            "urlhaus": 3 * 24 * 3600,          # 3 days
            "spur": 14 * 24 * 3600,            # 14 days
            "hibp": 60 * 24 * 3600,            # 60 days
        }
        self.stats = {
            "redis_hits": 0,
            "redis_misses": 0,
            "db_hits": 0,
            "db_misses": 0,
            "api_calls": 0,
        }

    def get_cached(self, service: str, key: str) -> Optional[dict]:
        """Get from L1 (Redis) → L2 (DB) → None."""

        # L1: Try Redis (hot cache)
        if self.redis_cache:
            data = self.redis_cache.get(service, key)
            if data is not None:
                self.stats["redis_hits"] += 1
                return data
            self.stats["redis_misses"] += 1

        # L2: Try Database (durable cache)
        data = self.db_cache.get(service, key)
        if data is not None:
            self.stats["db_hits"] += 1

            # Promote to Redis for intra-batch optimization
            if self.redis_cache:
                redis_ttl = min(self.ttls.get(service, 3600), 3600)  # Max 1 hour in Redis
                self.redis_cache.set(service, key, data, redis_ttl)

            return data

        self.stats["db_misses"] += 1
        return None

    def store_cached(self, service: str, key: str, data: dict) -> None:
        """Store in L2 (DB) and L1 (Redis)."""
        ttl_seconds = self.ttls.get(service, 7 * 24 * 3600)

        # Always store in database (durable)
        self.db_cache.set(service, key, data, ttl_seconds)

        # Also store in Redis with shorter TTL (1 hour max)
        if self.redis_cache:
            redis_ttl = min(ttl_seconds, 3600)
            self.redis_cache.set(service, key, data, redis_ttl)

        self.stats["api_calls"] += 1
```

## Decision

**Accept Option D: Hybrid Database + Redis (3-Tier) Architecture**

### Implementation Phases

#### Phase 1: Database Cache Foundation (Week 1-2)
1. Add `EnrichmentCache` ORM model to `cowrieprocessor/db/models.py`
2. Create migration in `cowrieprocessor/db/migrations.py` (bump schema version to 12)
3. Implement `DatabaseCache` class
4. Add database cleanup scheduled task
5. **Backward Compatibility**: Keep filesystem cache operational, add database layer alongside
6. **Migration Path**: New enrichments use database, existing filesystem cache gradually expires

#### Phase 2: Redis Hot Cache Layer (Week 3)
1. Add optional Redis support with graceful degradation
2. Implement `RedisCache` class
3. Add `HybridEnrichmentCache` orchestrator
4. Configure Redis connection via environment variables
5. **Optional Deployment**: Redis optional, system works without it (degrades to DB-only)

#### Phase 3: Migration & Deprecation (Week 4)
1. Add migration script to import existing filesystem cache to database
2. Add metrics dashboard for cache effectiveness
3. Remove filesystem cache code after 30-day transition period
4. Update documentation and deployment guides

### Configuration

**Environment Variables**:
```bash
# Redis (optional)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=<secret>
REDIS_MAX_MEMORY=100mb
REDIS_EVICTION_POLICY=allkeys-lru

# Cache TTLs (override defaults)
CACHE_TTL_VIRUSTOTAL=2592000  # 30 days
CACHE_TTL_DSHIELD=604800      # 7 days
CACHE_TTL_HIBP=5184000        # 60 days
```

**`sensors.toml` Configuration**:
```toml
[cache]
enabled = true
redis_enabled = true
redis_host = "localhost"
redis_port = 6379
redis_max_memory = "100mb"

[cache.ttls]
virustotal = 2592000        # 30 days
virustotal_unknown = 43200  # 12 hours
dshield = 604800            # 7 days
urlhaus = 259200            # 3 days
spur = 1209600              # 14 days
hibp = 5184000              # 60 days
```

### Performance Impact Analysis

**Current (Filesystem)**:
- Cache lookup: 5-15ms (disk I/O)
- Intra-batch repeated key: 5-15ms × N repeats
- Example: 1000 sessions from 50 IPs = 50ms + (950 × 5ms) = 4.8 seconds wasted

**Proposed (Hybrid)**:
- L1 (Redis) hit: 0.1-0.5ms (in-memory)
- L2 (DB) hit: 1-3ms (indexed query)
- Intra-batch repeated key: 0.1-0.5ms × N repeats
- Same example: 50ms (initial) + (950 × 0.1ms) = 145ms total = **97% reduction**

**Expected Improvements**:
- **Intra-batch optimization**: 90-95% reduction in repeated lookup time
- **Overall enrichment speed**: 30-50% faster bulk enrichment runs
- **API quota savings**: Better cache hit rates reduce API costs
- **Durability**: Zero cache loss on system failures

### Observability & Monitoring

**Metrics to Track**:
```python
cache_metrics = {
    # Hit rates by tier
    "redis_hit_rate": redis_hits / (redis_hits + redis_misses),
    "db_hit_rate": db_hits / (db_hits + db_misses),
    "overall_hit_rate": (redis_hits + db_hits) / total_requests,

    # Performance
    "avg_redis_latency_ms": avg_redis_lookup_time,
    "avg_db_latency_ms": avg_db_lookup_time,
    "avg_api_latency_ms": avg_api_call_time,

    # Cost efficiency
    "api_calls_saved": total_requests - api_calls,
    "quota_utilization": api_calls / api_quota_limit,

    # Cache health
    "cache_size_mb": db_cache_size + redis_cache_size,
    "expired_entries_cleaned": cleanup_count,
    "hottest_keys": top_keys_by_hit_count,
}
```

**Dashboard Queries**:
```sql
-- Top cached items by hit count (find hot keys)
SELECT service, cache_key, hit_count, accessed_at
FROM enrichment_cache
ORDER BY hit_count DESC
LIMIT 100;

-- Cache effectiveness by service
SELECT
    service,
    COUNT(*) as total_entries,
    SUM(hit_count) as total_hits,
    AVG(hit_count) as avg_hits_per_entry,
    MAX(accessed_at) as last_access
FROM enrichment_cache
GROUP BY service;

-- Stale cache candidates (not accessed in 30 days)
SELECT service, COUNT(*) as stale_count
FROM enrichment_cache
WHERE accessed_at < NOW() - INTERVAL '30 days'
GROUP BY service;
```

## Consequences

### Positive

1. **Durability**: Cache survives system failures (database backups)
2. **Performance**: 90-95% reduction in intra-batch repeated lookups
3. **Cost Savings**: Better hit rates reduce API quota consumption
4. **Operational Simplicity**: Automatic cleanup, centralized monitoring
5. **Portability**: Works on PostgreSQL and SQLite
6. **Atomicity**: Database UPSERT prevents race conditions
7. **Observability**: Metrics for cache effectiveness and hot keys
8. **Graceful Degradation**: Works without Redis (DB-only mode)

### Negative

1. **Complexity**: Adds Redis dependency (optional but recommended)
2. **Migration Effort**: Need to migrate existing filesystem cache
3. **Database Load**: Additional table and queries (mitigated by Redis L1)
4. **Schema Change**: Requires schema version bump and migration

### Neutral

1. **Storage**: Database storage slightly larger than compressed JSON files
2. **Development**: SQLite environments work without Redis (DB-only mode)
3. **Maintenance**: Need Redis monitoring and backup procedures

## Risks and Mitigations

### Risk 1: Redis Unavailability
**Impact**: Degraded performance (no L1 cache)
**Mitigation**: Graceful degradation to DB-only mode, no functional impact
**Monitoring**: Alert on Redis connection failures

### Risk 2: Database Bloat
**Impact**: Cache table grows too large
**Mitigation**:
- Automatic cleanup function (daily cron)
- TTL-based expiration
- Monitor cache size growth trends
- LRU eviction for low-hit-count entries

### Risk 3: Migration Data Loss
**Impact**: Lose existing filesystem cache during migration
**Mitigation**:
- Keep filesystem cache operational during migration period
- Dual-write mode: write to both filesystem and database
- Gradual transition over 30-day TTL window
- Export/import script with validation

### Risk 4: Cache Poisoning
**Impact**: Bad API response cached and reused
**Mitigation**:
- Validate API responses before caching
- Track cache entry quality (errors, empty responses)
- Manual invalidation API for poisoned entries
- Per-service cache purge capability

## Alternatives Considered

### Alternative 1: Memcached Instead of Redis
**Rejected Because**:
- Less feature-rich (no TTL per key, no persistence)
- No data structure support
- Similar operational overhead to Redis
- Redis has broader adoption in our stack

### Alternative 2: Application-Level In-Memory Cache (dict)
**Rejected Because**:
- Lost on process restart
- No sharing across workers/processes
- Memory leak risk without proper eviction
- No durability or observability

### Alternative 3: CDN/Edge Caching
**Rejected Because**:
- Enrichment APIs are not HTTP-based
- Adds unnecessary network complexity
- Overkill for our use case

## References

### Related ADRs

- **ADR-001**: JSONB for flexible metadata storage (established pattern for JSON data in PostgreSQL)
- **ADR-002**: Multi-Container Service Architecture
  - Defines Redis as shared service for job queue and caching
  - Establishes PostgreSQL with read replicas architecture
  - Specifies data loader and analysis worker containers that benefit from shared cache
  - **This ADR extends ADR-002** by defining the enrichment cache layer using the shared Redis/PostgreSQL infrastructure
- **ADR-003**: SQLite Deprecation - PostgreSQL-Only Architecture
  - V4.0 (Q1 2026): Multi-container requires PostgreSQL
  - V4.5 (Q3 2026): SQLite deprecated in monolithic mode → **Target for database cache deployment**
  - V5.0 (Q4 2026): SQLite removed entirely → **Target for filesystem cache removal**
  - Database cache requires PostgreSQL for concurrent writes, JSONB, network access, read replicas

### Implementation References

- Current filesystem cache: `cowrieprocessor/enrichment/cache.py` (305 lines, to be deprecated)
- Enrichment handlers: `cowrieprocessor/enrichment/handlers.py`, `virustotal_handler.py`
- Database models: `cowrieprocessor/db/models.py` (will add `EnrichmentCache` model)
- Multi-container architecture: `docs/ADR/002-multi-container-service-architecture.md`

### Architectural Position

This ADR represents a **critical enhancement to the multi-container architecture** (ADR-002):

1. **Completes the Redis caching layer**: ADR-002 planned Redis for job queues, this extends it to enrichment caching
2. **Enables concurrent enrichment**: Multiple data loader containers can share cache atomically via PostgreSQL
3. **Optimizes worker performance**: Analysis workers get sub-millisecond cache hits via Redis L1
4. **Leverages shared infrastructure**: Uses existing PostgreSQL + Redis from multi-container deployment
5. **Aligns with SQLite deprecation**: Database cache requires PostgreSQL features (JSONB, concurrent writes) per ADR-003

## Implementation Checklist

- [ ] Phase 1: Database cache foundation
  - [ ] Add `EnrichmentCache` ORM model
  - [ ] Create migration script (schema v11 → v12)
  - [ ] Implement `DatabaseCache` class
  - [ ] Add cleanup scheduled task
  - [ ] Unit tests for DB cache operations
  - [ ] Integration tests with PostgreSQL and SQLite

- [ ] Phase 2: Redis hot cache layer
  - [ ] Add Redis client configuration
  - [ ] Implement `RedisCache` class
  - [ ] Implement `HybridEnrichmentCache` orchestrator
  - [ ] Add graceful degradation when Redis unavailable
  - [ ] Unit tests for Redis cache
  - [ ] Integration tests for hybrid cache

- [ ] Phase 3: Migration and monitoring
  - [ ] Filesystem-to-database migration script
  - [ ] Cache metrics dashboard
  - [ ] Performance benchmarks (before/after)
  - [ ] Documentation updates
  - [ ] Deployment guide with Redis setup
  - [ ] Remove filesystem cache code after transition

## V4.x Roadmap Integration

This ADR integrates with the overall V4.x multi-container architecture roadmap:

### V4.0.0 (Q1 2026) - Multi-Container Launch
- **ADR-002 Core**: Data loaders, analysis workers, MCP API, Redis job queue, PostgreSQL primary
- **Enrichment Cache**: Filesystem cache remains operational (no breaking changes)
- **Status**: Multi-container users can deploy, enrichment uses filesystem cache

### V4.5.0 (Q3 2026) - Cache Migration & SQLite Deprecation
- **ADR-005 Deployment**: Database cache + Redis L1 layer implemented
- **ADR-003 Phase 2**: SQLite deprecated with warnings for monolithic deployments
- **Migration Path**: Filesystem cache → Database cache migration tooling provided
- **Status**: Production deployments migrate to hybrid cache, 30-50% enrichment performance improvement

### V5.0.0 (Q4 2026) - Complete PostgreSQL Migration
- **ADR-003 Phase 3**: SQLite removed entirely
- **ADR-005 Complete**: Filesystem cache code removed (~305 lines deleted)
- **Status**: Single database (PostgreSQL), unified cache architecture (Redis L1 + DB L2)

**Timeline Rationale**:
- V4.0: Launch multi-container without breaking existing enrichment workflows
- V4.5: Deploy new cache alongside SQLite deprecation (both require PostgreSQL)
- V5.0: Remove all deprecated code (SQLite + filesystem cache) for clean codebase

## Approval

- [ ] Architecture Review
- [ ] Performance Testing (benchmark 97% reduction in intra-batch lookup time)
- [ ] Security Review (Redis authentication, cache poisoning mitigation)
- [ ] Operations Team Approval (Redis deployment, monitoring setup)
- [ ] Integration with ADR-002 validated (multi-container compatibility)
- [ ] Integration with ADR-003 validated (PostgreSQL requirements documented)
- [ ] Final Approval

---

**Next Actions**:
1. Review and approve ADR
2. Create implementation tickets for each phase (targeting V4.5.0 milestone)
3. Set up development Redis instance for testing
4. Begin Phase 1 implementation (database cache foundation)
5. Coordinate with ADR-002 Redis deployment (share infrastructure)
6. Plan migration tooling alongside ADR-003 SQLite deprecation timeline
