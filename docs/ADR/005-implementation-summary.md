# ADR-005 Implementation Summary

**Milestone**: [ADR-005: Hybrid Cache & Adaptive Rate Limiting](https://github.com/datagen24/cowrieprocessor/milestone/3)
**Status**: Ready for Implementation
**Branch**: `scp-snowshoe` (not merged to main)
**Target Completion**: December 15, 2025

## Overview

ADR-005 addresses critical enrichment failures and implements a hybrid caching architecture to improve performance and reliability.

**Critical Issue**: Enrichment refresh jobs failing with "too many requests" from DShield API due to improper rate limiting and backoff handling.

## Milestone Structure

### Phase 1A: Immediate Backoff Fix (P0-Critical)
**Target**: Week 1 (immediate)
**Priority**: Fixes production enrichment failures

| Issue | Title | Description |
|-------|-------|-------------|
| [#113](https://github.com/datagen24/cowrieprocessor/issues/113) | **[Phase 1A] Parent** | Implement Adaptive Rate Limiting with Retry-After Support |
| [#114](https://github.com/datagen24/cowrieprocessor/issues/114) | Task 1 | Implement `_get_retry_after_seconds()` helper |
| [#115](https://github.com/datagen24/cowrieprocessor/issues/115) | Task 2 | Add `AdaptiveRateLimiter` class |
| [#116](https://github.com/datagen24/cowrieprocessor/issues/116) | Task 3 | Update `with_retries` decorator |
| [#117](https://github.com/datagen24/cowrieprocessor/issues/117) | Task 4 | Update `dshield_query` to use adaptive retry |
| [#118](https://github.com/datagen24/cowrieprocessor/issues/118) | Task 5 | Integration tests for 401/429 handling |

**Acceptance Criteria**:
- ✅ Enrichment refresh jobs complete without rate limit errors
- ✅ HTTP `Retry-After` headers honored (seconds + HTTP-date formats)
- ✅ Consecutive 401/429 errors trigger exponential backoff (60s → 120s → 240s → max 1hr)
- ✅ Successful requests reset failure counter

**Files Modified**:
- `cowrieprocessor/enrichment/rate_limiting.py`
- `cowrieprocessor/enrichment/handlers.py`
- `tests/unit/test_rate_limiting.py`
- `tests/integration/test_enrichment_flow.py`

### Phase 1B: Redis L1 Cache Integration (P1-High)
**Target**: Weeks 1-2 (parallel to 1A)
**Priority**: Significant performance improvement

| Issue | Title | Description |
|-------|-------|-------------|
| [#119](https://github.com/datagen24/cowrieprocessor/issues/119) | **[Phase 1B] Parent** | Redis L1 Cache Layer Integration |
| [#120](https://github.com/datagen24/cowrieprocessor/issues/120) | Task 1 | Implement `HybridEnrichmentCache` class |
| [#121](https://github.com/datagen24/cowrieprocessor/issues/121) | Task 2 | Redis client initialization with graceful degradation |
| [#122](https://github.com/datagen24/cowrieprocessor/issues/122) | Task 3 | Update `EnrichmentOrchestrator` to use hybrid cache |
| [#123](https://github.com/datagen24/cowrieprocessor/issues/123) | Task 4 | Add cache tier metrics to telemetry |
| [#124](https://github.com/datagen24/cowrieprocessor/issues/124) | Task 5 | Integration tests for hybrid cache |

**Architecture**:
```
Enrichment Request
    ↓
L1: Redis (sub-ms) → 80%+ intra-batch hits
    ↓ miss
L2: Filesystem (5-15ms) → Existing durable cache
    ↓ miss
L3: API Call (100-500ms) → DShield, VirusTotal, etc.
```

**Acceptance Criteria**:
- ✅ Redis operational as L1 cache
- ✅ >80% hit rate for repeated keys in same enrichment batch
- ✅ Cache lookups <1ms (Redis) vs 5-15ms (filesystem)
- ✅ Graceful degradation when Redis unavailable
- ✅ Cache tier metrics in telemetry

**Files Created/Modified**:
- `cowrieprocessor/enrichment/hybrid_cache.py` (NEW)
- `cowrieprocessor/enrichment/handlers.py`
- `cowrieprocessor/enrichment/telemetry.py`
- `tests/integration/test_hybrid_cache.py` (NEW)

**Dependencies**:
- ✅ Redis container running on port 6379 (deployed)

### Phase 2: Database Cache Layer (P2-Medium)
**Target**: Q1 2026 (after Phase 1A+1B)
**Priority**: Important for multi-container, not blocking

| Issue | Title | Description |
|-------|-------|-------------|
| [#125](https://github.com/datagen24/cowrieprocessor/issues/125) | **[Phase 2] Parent** | Database Cache Layer (L2 Tier) |
| [#126](https://github.com/datagen24/cowrieprocessor/issues/126) | Task 1 | Add `EnrichmentCache` ORM model |
| [#127](https://github.com/datagen24/cowrieprocessor/issues/127) | Task 2 | Create schema migration (v11→v12) |
| [#128](https://github.com/datagen24/cowrieprocessor/issues/128) | Task 3 | Implement `DatabaseCache` class |
| [#129](https://github.com/datagen24/cowrieprocessor/issues/129) | Task 4 | Wire into `HybridEnrichmentCache` |
| [#130](https://github.com/datagen24/cowrieprocessor/issues/130) | Task 5 | Automatic cache cleanup function |

**Architecture Evolution**:
```
After Phase 2:
L1: Redis (1hr TTL, sub-ms)
L2: PostgreSQL (30d TTL, durable, 1-3ms)
L3: Filesystem (deprecated, fallback only)
```

**Acceptance Criteria**:
- ✅ `enrichment_cache` table created
- ✅ DatabaseCache class implements get/set/delete
- ✅ Schema migration (v11→v12) working
- ✅ Hybrid cache uses database as L2 tier
- ✅ Automatic cleanup function operational

**Files Created/Modified**:
- `cowrieprocessor/db/models.py` (add EnrichmentCache model)
- `cowrieprocessor/db/migrations.py` (schema v12)
- `cowrieprocessor/enrichment/db_cache.py` (NEW)
- `cowrieprocessor/enrichment/hybrid_cache.py`
- `tests/integration/test_db_cache.py` (NEW)

**Dependencies**:
- PostgreSQL required (per ADR-003, SQLite deprecated V4.5)
- Phase 1A+1B complete
- Multi-container architecture (ADR-002)

## Quick Start for Implementation Teams

### Immediate Priority (Phase 1A)

**Problem**: Production enrichment jobs failing with rate limit errors.

**Solution**: Implement adaptive rate limiting with Retry-After support.

**Start Here**:
1. **Issue #114**: Implement `_get_retry_after_seconds()` helper
   - Parse HTTP `Retry-After` headers (seconds + HTTP-date)
   - File: `cowrieprocessor/enrichment/rate_limiting.py`
   - Estimated: 2-3 hours

2. **Issue #115**: Add `AdaptiveRateLimiter` class
   - Track consecutive failures
   - Apply backoff before requests
   - Estimated: 4-6 hours

3. **Issue #116**: Update `with_retries` decorator
   - Add `respect_retry_after` parameter
   - Honor server backoff requests
   - Estimated: 3-4 hours

4. **Issue #117**: Update `dshield_query()`
   - Use enhanced retry decorator
   - Trigger retry on 401/429
   - Estimated: 1-2 hours

5. **Issue #118**: Integration tests
   - Mock DShield 401/429 responses
   - Verify backoff behavior
   - Estimated: 4-6 hours

**Total Estimated Time**: 14-21 hours (2-3 days)

### High Priority (Phase 1B)

**Benefit**: 30-50% faster enrichment through Redis L1 cache.

**Prerequisites**: Redis deployed on port 6379 (✅ completed)

**Start Here**:
1. **Issue #120**: Implement `HybridEnrichmentCache`
2. **Issue #121**: Redis client with graceful degradation
3. **Issue #122**: Update orchestrator to use hybrid cache

**Total Estimated Time**: 16-24 hours (3-4 days)

## Configuration

### Environment Variables (Phase 1B+)

```bash
# Redis Configuration
REDIS_HOST=localhost  # Or K3s service DNS
REDIS_PORT=6379
REDIS_PASSWORD=changeme  # Set via secret
REDIS_DB=0
ENABLE_REDIS_CACHE=true  # Set false to use filesystem only

# Rate Limiting
DSHIELD_RATE_LIMIT=0.5  # 0.5 req/sec = 30/min
DSHIELD_BURST=1
RESPECT_RETRY_AFTER=true
```

### sensors.toml (Phase 1B+)

```toml
[enrichment.cache]
enabled = true
redis_enabled = true
redis_host = "localhost"
redis_port = 6379
redis_max_memory = "256mb"
redis_ttl_seconds = 3600  # 1 hour hot cache

[enrichment.rate_limits]
dshield_rate = 0.5
dshield_burst = 1
dshield_respect_retry_after = true
```

## Testing Strategy

### Phase 1A Tests
- **Unit**: Retry-After parsing (seconds, HTTP-date, invalid)
- **Unit**: AdaptiveRateLimiter backoff logic
- **Unit**: with_retries Retry-After support
- **Integration**: Mock DShield 401/429 responses
- **Integration**: End-to-end enrichment with rate limiting

### Phase 1B Tests
- **Unit**: HybridEnrichmentCache tier fallback
- **Integration**: Redis hit/miss scenarios
- **Integration**: Redis unavailable graceful degradation
- **Integration**: Intra-batch optimization (100 sessions, 10 IPs → 90 Redis hits)
- **Performance**: Benchmark L1 vs L2 latency

### Phase 2 Tests
- **Unit**: EnrichmentCache model CRUD
- **Unit**: DatabaseCache get/set/delete
- **Integration**: 3-tier cache hierarchy
- **Integration**: Database cleanup function
- **Migration**: Schema v11→v12 on PostgreSQL and SQLite

## Success Metrics

### Phase 1A (Critical)
- ✅ **Zero enrichment failures** due to rate limiting
- ✅ **Retry-After honored** in 100% of 401/429 responses
- ✅ **Backoff adapts** based on consecutive failures
- ✅ **All existing tests pass** (no regressions)

### Phase 1B (Performance)
- ✅ **Redis hit rate >80%** for intra-batch requests
- ✅ **Cache latency <1ms** for Redis hits
- ✅ **30-50% faster** enrichment job duration
- ✅ **Graceful degradation** when Redis unavailable

### Phase 2 (Long-term)
- ✅ **Database cache operational** as L2 tier
- ✅ **Multi-container deployments** share cache atomically
- ✅ **Filesystem cache deprecated** (L3 fallback only)
- ✅ **90-95% reduction** in repeated API calls

## Related Documentation

- **ADR-005**: [Full ADR Document](./005-enrichment-cache-database-redis-hybrid.md)
- **ADR-002**: [Multi-Container Architecture](./002-multi-container-service-architecture.md)
- **ADR-003**: [SQLite Deprecation](./003-sqlite-deprecation-postgresql-only.md)
- **GitHub Milestone**: https://github.com/datagen24/cowrieprocessor/milestone/3

## Timeline

```
Week 1 (Immediate):
  ├─ Phase 1A: Adaptive rate limiting implementation
  └─ Phase 1B: Redis integration start

Week 2-3:
  └─ Phase 1B: Complete Redis L1 cache integration

Q1 2026:
  └─ Phase 2: Database cache layer (after multi-container architecture)
```

## Team Coordination

**Phase 1A**: Single developer, sequential tasks (dependency chain)
**Phase 1B**: Can parallelize Tasks 1-2, then Tasks 3-5
**Phase 2**: Requires database expertise, coordinate with ADR-003 migration

## Rollback Plan

### Phase 1A
- Revert `rate_limiting.py` changes if issues occur
- Existing rate limiting still functional
- No data loss risk

### Phase 1B
- Set `ENABLE_REDIS_CACHE=false` to revert to filesystem-only
- No data loss (filesystem cache remains operational)
- Redis is additive, not destructive

### Phase 2
- Database migration reversible (drop `enrichment_cache` table)
- Filesystem cache remains as fallback
- No impact on core enrichment functionality

---

**Last Updated**: 2025-11-02
**Status**: All issues created, ready for implementation
**Next Steps**: Assign Phase 1A issues to implementation team
