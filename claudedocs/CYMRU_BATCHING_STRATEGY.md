# Cymru Batching Strategy - Synchronous Implementation + Async Milestone 2

**Date**: 2025-11-06
**Context**: Task 1.3 optimization - eliminate DNS timeout issues with Cymru lookups
**Status**: 🔄 Synchronous batching (in progress) → 📋 Async batching (Milestone 2 backlog)

---

## Problem Statement

### Current Bottleneck

**Observed behavior** (user testing with 10,000 IPs):
```
2025-11-06 15:54:19,772 - cymru_client - WARNING - DNS timeout for 103.176.138.117, retrying in 1.0s
2025-11-06 15:54:34,498 - cymru_client - WARNING - DNS timeout for 103.176.138.18, retrying in 1.0s
```

**Root cause**: `CascadeEnricher.enrich_ip()` calls Cymru individually (line 192):
```python
cymru_result = self.cymru.lookup_asn(ip_address)  # ⚠️ Individual DNS lookup
```

**Performance impact**:
- 10,000 IPs × ~100ms DNS timeout = **~16 minutes** just for Cymru
- DNS lookups fail frequently → retry delays → poor user experience
- Inefficient: `CymruClient.bulk_lookup()` exists but unused (batches 500 IPs via netcat)

---

## Solution Architecture

### Phase 1: Synchronous Batching (Current Sprint - Task 1.3)

**Status**: 🔄 In Progress
**Target**: Eliminate DNS timeouts, reduce Cymru enrichment time by 50%
**Complexity**: Low (2 hours implementation)
**Risk**: Low (no async/threading, clear transaction boundaries)

#### Implementation Plan

**Location**: `cowrieprocessor/cli/enrich_passwords.py` (lines 1435-1530)

**New Flow** (replaces single-pass `enrich_ip()` loop):

```python
# PASS 1: MaxMind enrichment (offline, fast ~1ms per IP)
# ========================================================
logger.info("Pass 1/3: MaxMind GeoIP enrichment (offline)...")
maxmind_results = {}
ips_needing_cymru = []

for idx, ip_address in enumerate(ips_to_enrich):
    try:
        maxmind_result = cascade.maxmind.lookup_ip(ip_address)
        maxmind_results[ip_address] = maxmind_result

        # Track IPs missing ASN data (need Cymru)
        if not maxmind_result or maxmind_result.asn is None:
            ips_needing_cymru.append(ip_address)

        # Status emitter update every 100 IPs
        if (idx + 1) % 100 == 0:
            status_emitter.record_metrics({
                "pass": "maxmind",
                "ips_processed": idx + 1,
                "ips_total": len(ips_to_enrich),
            })
    except Exception as e:
        logger.warning(f"MaxMind lookup failed for {ip_address}: {e}")

logger.info(f"Pass 1 complete: {len(ips_needing_cymru)} IPs need Cymru ASN enrichment")


# PASS 2: Cymru bulk enrichment (netcat batches of 500)
# =======================================================
logger.info(f"Pass 2/3: Cymru ASN enrichment ({len(ips_needing_cymru)} IPs, batched)...")
cymru_results = {}

if ips_needing_cymru:
    batch_size = 500  # Cymru bulk interface max
    num_batches = (len(ips_needing_cymru) + batch_size - 1) // batch_size

    for batch_idx in range(num_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, len(ips_needing_cymru))
        batch = ips_needing_cymru[start:end]

        try:
            # Use bulk_lookup() - netcat interface, no DNS timeouts!
            batch_results = cascade.cymru.bulk_lookup(batch)
            cymru_results.update(batch_results)

            logger.info(f"Cymru batch {batch_idx + 1}/{num_batches}: {len(batch_results)} IPs enriched")

            # Status emitter
            status_emitter.record_metrics({
                "pass": "cymru",
                "batch": batch_idx + 1,
                "batches_total": num_batches,
                "ips_enriched": len(cymru_results),
            })
        except Exception as e:
            logger.error(f"Cymru batch {batch_idx + 1} failed: {e}")

logger.info(f"Pass 2 complete: {len(cymru_results)} IPs enriched via Cymru")


# PASS 3: Merge results and GreyNoise enrichment
# ================================================
logger.info("Pass 3/3: Merging results and GreyNoise enrichment...")

for idx, ip_address in enumerate(ips_to_enrich):
    try:
        # Get results from previous passes
        maxmind_result = maxmind_results.get(ip_address)
        cymru_result = cymru_results.get(ip_address)

        # GreyNoise (independent, always attempt)
        greynoise_result = None
        try:
            greynoise_result = cascade.greynoise.lookup_ip(ip_address)
        except Exception as e:
            logger.warning(f"GreyNoise lookup failed for {ip_address}: {e}")

        # Merge into IP inventory
        cached = session.query(IPInventory).filter(IPInventory.ip_address == ip_address).first()
        merged = cascade._merge_results(cached, maxmind_result, cymru_result, greynoise_result, ip_address)

        # Update database
        if cached:
            cached.enrichment = merged.enrichment
            cached.enrichment_updated_at = datetime.now(timezone.utc)
            cached.current_asn = merged.current_asn
            # ... other fields
        else:
            session.add(merged)

        ip_count += 1

        # Batch commit every 100 IPs
        if ip_count % args.commit_interval == 0:
            session.commit()
            logger.info(f"[ips] committed {ip_count} rows...")

            status_emitter.record_metrics({
                "pass": "merge",
                "ips_processed": ip_count,
                "ips_total": len(ips_to_enrich),
            })
    except Exception as e:
        logger.error(f"Enrichment failed for {ip_address}: {e}")
        ip_errors += 1

# Final commit
session.commit()
logger.info(f"Pass 3 complete: {ip_count} IPs enriched, {ip_errors} errors")
```

#### Performance Projection (10,000 IPs)

| Phase | Current (1-by-1) | Synchronous Batching | Improvement |
|-------|------------------|----------------------|-------------|
| **Pass 1: MaxMind** | ~10 seconds | ~10 seconds | Same (offline) |
| **Pass 2: Cymru** | **~16 minutes** (DNS timeouts) | **~100 seconds** (20 batches × 5s) | **90% faster** |
| **Pass 3: GreyNoise** | ~1,000 seconds | ~1,000 seconds | Same (rate limited) |
| **TOTAL** | **~27 minutes** | **~19 minutes** | **30% faster** |

**Key wins**:
- ✅ Eliminates DNS timeout warnings
- ✅ Uses efficient netcat bulk interface (500 IPs per batch)
- ✅ Predictable execution time (no retry delays)
- ✅ Better progress visibility (3 clear phases)

#### Testing Plan

1. **Unit test**: Mock `bulk_lookup()` responses
   ```python
   def test_refresh_cymru_batching(mocker):
       mock_bulk = mocker.patch("CymruClient.bulk_lookup")
       mock_bulk.return_value = {"8.8.8.8": CymruResult(asn=15169, ...)}

       # Run refresh with --ips 1000
       # Verify bulk_lookup called with batches, not individual lookups
       assert mock_bulk.call_count == 2  # 1000 IPs / 500 batch size
   ```

2. **Integration test**: Run with `--ips 100` on test database
   ```bash
   uv run cowrie-enrich refresh --ips 100 --verbose --db "sqlite:///test.db"
   # Expected logs:
   # Pass 1/3: MaxMind GeoIP enrichment (offline)...
   # Pass 1 complete: 87 IPs need Cymru ASN enrichment
   # Pass 2/3: Cymru ASN enrichment (87 IPs, batched)...
   # Cymru batch 1/1: 87 IPs enriched
   # Pass 3/3: Merging results and GreyNoise enrichment...
   ```

3. **Performance test**: Compare before/after on 1,000 IPs
   - Before: Check for DNS timeout warnings
   - After: Verify no DNS timeouts, faster execution

---

### Phase 2: Async Batching (Milestone 2 - Multi-Container Scheduler)

**Status**: 📋 Backlog
**Target**: Further optimize with true parallel processing
**Complexity**: High (async/await refactor, scheduler integration)
**Risk**: Medium (race conditions, transaction management)
**Prerequisites**: Full scheduler system, async SQLAlchemy sessions

#### Architectural Vision

**Context**: Milestone 2 introduces multi-container architecture with dedicated scheduler:
- Container 1: FastAPI web service (status queries, on-demand enrichment)
- Container 2: Celery worker (scheduled enrichment jobs)
- Container 3: Redis (task queue + L1 cache)
- Container 4: PostgreSQL (persistent storage)

**Async enrichment flow**:
```python
# Scheduler triggers enrichment job
@celery.task
async def enrich_ips_batch(ip_list: list[str]):
    # Create async enrichment tasks
    tasks = [
        enrich_maxmind_async(ip_list),      # All IPs, parallel
        enrich_cymru_async(ip_sublist),     # Only IPs needing ASN, batched
        enrich_greynoise_async(ip_list),    # All IPs, rate-limited
    ]

    # Run in parallel with asyncio.gather()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge results into database (single transaction)
    async with async_session_maker() as session:
        for ip, merged_result in merge_all_results(results):
            await session.merge(merged_result)
        await session.commit()
```

#### Async Implementation Design

**Component 1: Async CymruClient**
```python
class AsyncCymruClient:
    """Async Cymru client with connection pooling."""

    async def bulk_lookup_async(self, ip_addresses: list[str]) -> dict[str, CymruResult]:
        """Non-blocking bulk lookup via asyncio streams.

        Uses asyncio.open_connection() for netcat interface.
        Maintains connection pool for parallel batch requests.
        """
        # Split into batches of 500
        tasks = [self._batch_lookup_netcat_async(batch)
                 for batch in chunked(ip_addresses, 500)]

        # Run batches in parallel (limited concurrency)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return merge_results(results)

    async def _batch_lookup_netcat_async(self, batch: list[str]) -> dict[str, CymruResult]:
        """Single batch via asyncio streams."""
        reader, writer = await asyncio.open_connection('whois.cymru.com', 43)

        query = "begin\nverbose\n" + "\n".join(batch) + "\nend\n"
        writer.write(query.encode())
        await writer.drain()

        response = await reader.read()
        writer.close()
        await writer.wait_closed()

        return self._parse_netcat_response(response.decode())
```

**Component 2: Async CascadeEnricher**
```python
class AsyncCascadeEnricher:
    """Async cascade enricher with parallel source queries."""

    async def enrich_ips_batch(self, ip_addresses: list[str]) -> list[IPInventory]:
        """Batch enrich with parallel source queries.

        Strategy:
        1. MaxMind (offline) - process all IPs in parallel chunks
        2. Identify IPs needing Cymru (missing ASN)
        3. Batch Cymru lookups (500 per batch, parallel batches)
        4. GreyNoise (rate-limited) - parallel with semaphore
        5. Merge results in single transaction
        """
        # Phase 1: MaxMind (fast, parallel chunks)
        maxmind_tasks = [self.maxmind.lookup_ip_async(ip) for ip in ip_addresses]
        maxmind_results = await asyncio.gather(*maxmind_tasks)

        # Phase 2: Cymru (batched, parallel batches)
        ips_needing_cymru = [ip for ip, result in zip(ip_addresses, maxmind_results)
                              if not result or result.asn is None]

        if ips_needing_cymru:
            cymru_results = await self.cymru.bulk_lookup_async(ips_needing_cymru)

        # Phase 3: GreyNoise (rate-limited, parallel with semaphore)
        async with self.greynoise_semaphore:  # Max 10 concurrent
            greynoise_tasks = [self.greynoise.lookup_ip_async(ip) for ip in ip_addresses]
            greynoise_results = await asyncio.gather(*greynoise_tasks, return_exceptions=True)

        # Phase 4: Merge and persist (single transaction)
        async with self.async_session_maker() as session:
            inventories = []
            for ip, maxmind, cymru, greynoise in zip(...):
                merged = self._merge_results(ip, maxmind, cymru, greynoise)
                inventories.append(merged)
                session.add(merged)

            await session.commit()
            return inventories
```

**Component 3: Celery Scheduler Integration**
```python
# celery_tasks.py
@celery.task(bind=True)
def scheduled_ip_enrichment(self):
    """Scheduled job: Enrich stale IPs every 6 hours."""
    with SessionMaker() as session:
        # Find IPs needing enrichment (>7 days old OR missing MaxMind)
        stale_ips = session.query(SessionSummary.source_ip).distinct()...

        # Batch into chunks of 1000 IPs
        for chunk in chunked(stale_ips, 1000):
            # Dispatch async enrichment task
            enrich_ips_batch_async.delay(chunk)

@celery.task
def enrich_ips_batch_async(ip_list: list[str]):
    """Async enrichment task."""
    loop = asyncio.get_event_loop()
    cascade = AsyncCascadeEnricher(...)
    return loop.run_until_complete(cascade.enrich_ips_batch(ip_list))
```

#### Performance Projection (Async - 10,000 IPs)

| Phase | Synchronous Batching | Async Batching | Improvement |
|-------|----------------------|----------------|-------------|
| **MaxMind** | ~10 seconds (serial) | **~2 seconds** (parallel chunks) | 5× faster |
| **Cymru** | ~100 seconds (20 batches serial) | **~30 seconds** (parallel batches) | 3× faster |
| **GreyNoise** | ~1,000 seconds (rate-limited serial) | **~600 seconds** (parallel with semaphore) | 1.7× faster |
| **TOTAL** | **~19 minutes** | **~11 minutes** | **42% faster** |

**Additional wins**:
- ✅ True parallel processing (not blocked on I/O)
- ✅ Better resource utilization (CPU + network)
- ✅ Scheduler-driven automation (no manual triggering)
- ✅ Scalable to multiple worker containers

#### Implementation Challenges

1. **Async SQLAlchemy Sessions**
   - Requires `asyncpg` driver for PostgreSQL
   - All ORM operations need `await` (large refactor)
   - Transaction management across async operations

2. **Error Handling**
   - Partial batch failures need rollback logic
   - Exception handling in `asyncio.gather(return_exceptions=True)`
   - Dead Letter Queue for failed IPs

3. **Testing Complexity**
   - Async test fixtures required (`pytest-asyncio`)
   - Mock async context managers (`__aenter__`, `__aexit__`)
   - Race condition testing (harder to reproduce)

4. **Rate Limiting**
   - Semaphore for GreyNoise (max 10 concurrent)
   - Token bucket algorithm for Cymru (async-aware)
   - Global rate limits across workers (Redis-backed)

5. **Monitoring**
   - Async task progress tracking (Celery Flower)
   - Real-time status emitter updates (WebSocket?)
   - Distributed tracing (OpenTelemetry spans)

---

## Decision Matrix

| Criterion | Synchronous Batching | Async Batching |
|-----------|----------------------|----------------|
| **Performance Gain** | 30% faster (16min → 19min) | 60% faster (16min → 11min) |
| **Implementation Time** | 2 hours | 2-3 weeks |
| **Code Complexity** | Low (single file change) | High (async refactor) |
| **Testing Effort** | Low (standard fixtures) | High (async mocks) |
| **Production Risk** | Low (predictable flow) | Medium (race conditions) |
| **Maintenance** | Easy (sync patterns) | Moderate (async debugging) |
| **Scalability** | Single process | Multi-container |
| **Prerequisites** | None | Milestone 2 scheduler |

---

## Recommendations

### For Current Sprint (Task 1.3)

✅ **Implement synchronous batching**

**Rationale**:
- Solves immediate DNS timeout problem
- 30% performance improvement with minimal risk
- Production-ready in 2 hours
- Easy to test and maintain

**Deliverables**:
1. Modified `enrich_passwords.py` with 3-pass enrichment
2. Unit tests for batch logic
3. Integration test with 100 IPs
4. Documentation update (this file)

### For Milestone 2 (Multi-Container Scheduler)

📋 **Add async batching to backlog**

**Rationale**:
- Fits naturally with scheduler architecture
- Justifies async complexity (42% additional performance gain)
- Enables multi-worker scalability
- Better resource utilization

**Prerequisites** (must complete first):
1. Milestone 2 multi-container setup (FastAPI + Celery + Redis)
2. Async SQLAlchemy migration (switch to `asyncpg`)
3. Celery scheduler implementation
4. Redis integration for distributed rate limiting

**Estimated Effort**:
- Async client refactor: 3-5 days
- Async cascade enricher: 3-5 days
- Celery integration: 2-3 days
- Testing + debugging: 5-7 days
- **Total: 2-3 weeks**

---

## Testing Strategy

### Phase 1: Synchronous Batching Tests

**Unit Tests** (`tests/unit/test_cymru_batching.py`):
```python
def test_refresh_uses_bulk_lookup(mocker):
    """Verify refresh command uses bulk_lookup() instead of individual calls."""
    mock_bulk = mocker.patch("CymruClient.bulk_lookup")
    mock_bulk.return_value = {"8.8.8.8": CymruResult(asn=15169, ...)}

    # Run refresh with --ips 1000
    result = refresh_ips(ip_limit=1000)

    # Should batch in groups of 500
    assert mock_bulk.call_count == 2
    assert len(mock_bulk.call_args_list[0][0][0]) == 500
    assert len(mock_bulk.call_args_list[1][0][0]) == 500

def test_refresh_three_pass_flow(mocker):
    """Verify 3-pass enrichment flow executes in order."""
    maxmind_spy = mocker.spy(MaxMindClient, "lookup_ip")
    cymru_spy = mocker.spy(CymruClient, "bulk_lookup")
    greynoise_spy = mocker.spy(GreyNoiseClient, "lookup_ip")

    refresh_ips(ip_limit=100)

    # Verify call order
    assert maxmind_spy.call_count == 100  # Pass 1: All IPs
    assert cymru_spy.call_count == 1       # Pass 2: Batch call
    assert greynoise_spy.call_count == 100 # Pass 3: All IPs
```

**Integration Tests** (`tests/integration/test_refresh_batching.py`):
```python
def test_refresh_cymru_no_dns_timeouts(caplog):
    """Verify no DNS timeout warnings with batching."""
    with caplog.at_level(logging.WARNING):
        refresh_ips(ip_limit=100)

    # Should NOT see DNS timeout warnings
    assert "DNS timeout" not in caplog.text
    assert "Cymru batch 1/1: 87 IPs enriched" in caplog.text
```

### Phase 2: Async Batching Tests (Milestone 2)

**Async Unit Tests** (`tests/unit/test_async_cymru.py`):
```python
@pytest.mark.asyncio
async def test_async_bulk_lookup_parallel_batches(mocker):
    """Verify parallel batch execution."""
    client = AsyncCymruClient(...)

    # Mock netcat responses
    mock_connection = mocker.patch("asyncio.open_connection")

    # 1500 IPs = 3 batches of 500
    results = await client.bulk_lookup_async(["1.1.1.1"] * 1500)

    # Verify 3 parallel connections opened
    assert mock_connection.call_count == 3

@pytest.mark.asyncio
async def test_async_cascade_transaction_rollback(mocker):
    """Verify transaction rollback on partial failure."""
    cascade = AsyncCascadeEnricher(...)

    # Mock Cymru to fail mid-batch
    mocker.patch("AsyncCymruClient.bulk_lookup_async", side_effect=Exception("API error"))

    with pytest.raises(Exception):
        await cascade.enrich_ips_batch(["8.8.8.8"] * 100)

    # Verify database session rolled back
    assert session.in_transaction() == False
```

---

## Migration Path

### Step 1: Implement Synchronous Batching (Current)
- Modify `enrich_passwords.py` for 3-pass enrichment
- Add unit tests for batch logic
- Deploy to production, monitor performance

### Step 2: Validate Performance (1 week)
- Measure actual time savings with 10,000 IPs
- Confirm no DNS timeout warnings
- Collect user feedback from data center testing

### Step 3: Document Lessons Learned
- What worked well vs. expectations?
- Any unexpected bottlenecks?
- Recommended batch sizes for different IP volumes?

### Step 4: Design Async Architecture (Milestone 2 planning)
- Review Celery scheduler requirements
- Design async SQLAlchemy migration strategy
- Plan Redis integration for rate limiting

### Step 5: Implement Async Batching (Milestone 2 sprint)
- Refactor clients to async (MaxMind, Cymru, GreyNoise)
- Implement AsyncCascadeEnricher
- Integrate with Celery scheduler

### Step 6: A/B Testing (Milestone 2 validation)
- Run sync vs async enrichment side-by-side
- Compare performance, resource usage, error rates
- Gradual rollout (10% → 50% → 100% async)

---

## Related Documentation

- **Task 1.3 Completion**: `/claudedocs/TASK_1.3_COMPLETION.md`
- **Task 1.3 TTL Fix**: `/claudedocs/TASK_1.3_TTL_FIX.md`
- **Task 1.3 is_fresh Fix**: `/claudedocs/TASK_1.3_IS_FRESH_FIX.md`
- **Cascade Factory**: `/claudedocs/CASCADE_FACTORY_IMPLEMENTATION_SUMMARY.md`
- **ADR-008**: Multi-Source Enrichment Cascade specification

---

## Milestone 2 Backlog Item

**Title**: Async Cymru/GreyNoise Batching with Scheduler Integration

**Description**:
Refactor enrichment pipeline to use async/await for true parallel processing of Cymru bulk lookups and GreyNoise rate-limited queries. Integrate with Celery scheduler for automated enrichment jobs.

**Acceptance Criteria**:
- [ ] `AsyncCymruClient` with parallel batch support (500 IPs per batch)
- [ ] `AsyncCascadeEnricher` orchestrating parallel MaxMind/Cymru/GreyNoise
- [ ] Celery task for scheduled IP enrichment (every 6 hours)
- [ ] Async SQLAlchemy sessions with proper transaction management
- [ ] Redis-backed global rate limiting across workers
- [ ] 40-50% faster than synchronous batching (11 minutes for 10K IPs)
- [ ] Comprehensive async test suite (pytest-asyncio)
- [ ] OpenTelemetry distributed tracing

**Dependencies**:
- Milestone 2 multi-container architecture
- Async SQLAlchemy migration (asyncpg driver)
- Redis cluster deployment
- Celery + Flower monitoring

**Estimated Effort**: 2-3 weeks (1 engineer)

**Priority**: Medium (performance optimization, not critical path)

---

**Document Status**: ✅ Complete
**Next Action**: Implement synchronous batching in `enrich_passwords.py`
**Milestone 2 Tracking**: Added to backlog for scheduler sprint
