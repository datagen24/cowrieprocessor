# ASN Inventory Statistics Tracking - Design Document

## Problem Statement

The `asn_inventory` table has two aggregate fields that are always 0:
- `unique_ip_count`: Number of distinct IPs observed from this ASN
- `total_session_count`: Total attack sessions from this ASN

These fields were initialized with a comment "Will be updated by database triggers or queries" but no such triggers were ever implemented.

**Current State**:
```python
# cascade_enricher.py:671-672
unique_ip_count=0,  # Will be updated by database triggers or queries
total_session_count=0,
```

**Impact**: ASN-level analytics and reporting are broken. Queries like "top 10 ASNs by attack volume" return incorrect results.

## Requirements

1. **Database Compatibility**: Must work on both SQLite (dev) and PostgreSQL (prod)
2. **Performance**: Minimal overhead on high-volume enrichment operations (1000+ sessions/hour)
3. **Accuracy**: Real-time statistics with drift correction mechanisms
4. **Concurrency**: Handle concurrent updates safely in multi-threaded environments
5. **Testability**: Solution must be unit-testable and verifiable

## Design Options Analysis

### Option A: Database Triggers (PostgreSQL-only) ❌ REJECTED

**Implementation**: Create PostgreSQL triggers on `ip_inventory` table to update `asn_inventory` counters.

**Rejection Reason**: Violates SQLite compatibility requirement. SQLite triggers cannot reliably update other tables in the same transaction.

### Option B: Application-level Updates ✅ PRIMARY APPROACH

**Implementation**: Modify `CascadeEnricher.enrich_ip()` to update ASN statistics incrementally.

**Pros**:
- Database-agnostic (works on SQLite and PostgreSQL)
- Real-time statistics
- Integrated with existing enrichment workflow
- SQLAlchemy ORM handles all updates (trackable, testable)

**Cons**:
- Requires ASN change tracking (previous vs current ASN)
- Multiple database updates per enrichment call (~20% overhead)
- Race conditions need row-level locking

### Option C: CLI Refresh Tool ✅ SECONDARY APPROACH

**Implementation**: Create `cowrie-db refresh-asn-stats` command for periodic reconciliation.

**Pros**:
- Simple implementation (aggregation queries)
- Database-agnostic
- Self-healing (catches drift from crashes, rollbacks)
- No hot-path impact

**Cons**:
- Eventually consistent (stale between runs)
- Full table scans on large datasets
- Requires scheduling (cron)

### Option D: Combination Approach (B + C) ✅ RECOMMENDED

**Strategy**: Use application-level incremental updates for real-time accuracy, plus periodic CLI refresh for validation.

**Benefits**:
- Real-time statistics (Option B)
- Self-healing drift correction (Option C)
- Database-agnostic
- Auditability (CLI can report discrepancies)

## Recommended Solution: Option D (Two-Phase Implementation)

### Phase 1: Application-level Incremental Updates (PR-BLOCKING)

Modify `CascadeEnricher.enrich_ip()` to track and update ASN statistics.

#### Data Flow

```
Session Processing → enrich_ip(source_ip) →
  1. Query IPInventory (get previous ASN if exists)
  2. Enrich IP (MaxMind/Cymru → new ASN)
  3. Compare previous_asn vs current_asn:
     a. If ASN changed (or new IP):
        - Increment new ASN.unique_ip_count
        - Decrement old ASN.unique_ip_count (if exists)
     b. Always:
        - Increment current ASN.total_session_count
        - Increment IP.session_count
  4. Update database with row-level locks
```

#### Implementation Sketch

```python
# cowrieprocessor/enrichment/cascade_enricher.py

def enrich_ip(self, ip_address: str) -> IPInventory:
    """Sequential cascade enrichment with ASN statistics tracking."""
    self._stats.total_ips += 1
    now = datetime.now(timezone.utc)

    # Step 1: Check cache and track previous ASN
    cached = self.session.query(IPInventory).filter(
        IPInventory.ip_address == ip_address
    ).first()

    previous_asn = cached.current_asn if cached else None

    if cached and self._is_fresh(cached):
        logger.debug(f"Cache hit for {ip_address} (fresh data)")
        self._stats.cache_hits += 1

        # Still increment session count for cached IPs
        self._update_session_counts(cached.current_asn, increment=1)
        cached.session_count = (cached.session_count or 0) + 1
        cached.last_seen = now
        self.session.flush()
        return cached

    # Step 2: Cascade enrichment (existing logic)
    maxmind_result = self.maxmind.lookup_ip(ip_address)
    cymru_result = None
    if not maxmind_result or maxmind_result.asn is None:
        cymru_result = self.cymru.lookup_asn(ip_address)

    # ... (GreyNoise enrichment)

    # Step 3: Merge results (existing logic)
    merged = self._merge_results(cached, maxmind_result, cymru_result,
                                  greynoise_result, ip_address)
    current_asn = merged.current_asn

    # Step 4: Update ASN statistics
    if cached:
        # Update existing IP
        self._update_asn_statistics(
            previous_asn=previous_asn,
            current_asn=current_asn,
            is_new_ip=False
        )

        cached.enrichment = merged.enrichment
        cached.enrichment_updated_at = now
        cached.current_asn = current_asn
        cached.asn_last_verified = now
        cached.last_seen = now
        cached.session_count = (cached.session_count or 0) + 1
        self.session.flush()
        return cached
    else:
        # New IP
        self._update_asn_statistics(
            previous_asn=None,
            current_asn=current_asn,
            is_new_ip=True
        )

        setattr(merged, "created_at", now)
        setattr(merged, "updated_at", now)
        setattr(merged, "enrichment_updated_at", now)
        setattr(merged, "asn_last_verified", now)
        setattr(merged, "first_seen", now)
        setattr(merged, "last_seen", now)
        setattr(merged, "session_count", 1)
        self.session.add(merged)
        self.session.flush()
        return merged


def _update_asn_statistics(
    self,
    previous_asn: int | None,
    current_asn: int | None,
    is_new_ip: bool
) -> None:
    """Update ASN inventory statistics for IP assignment changes.

    Args:
        previous_asn: ASN IP was previously assigned to (None if new IP)
        current_asn: ASN IP is now assigned to (None if no ASN found)
        is_new_ip: True if this is a new IP being tracked

    Logic:
        - New IP with ASN: increment unique_ip_count, total_session_count
        - ASN changed: decrement old ASN unique_ip_count, increment new ASN unique_ip_count
        - Same ASN: only increment total_session_count
        - No ASN: no updates
    """
    if current_asn is None:
        return  # No ASN to update

    # Use row-level lock to prevent race conditions
    stmt = select(ASNInventory).where(
        ASNInventory.asn_number == current_asn
    ).with_for_update()
    current_asn_record = self.session.execute(stmt).scalar_one_or_none()

    if not current_asn_record:
        logger.warning(f"ASN {current_asn} not found in inventory during stats update")
        return

    # Handle IP count changes
    if is_new_ip or (previous_asn != current_asn):
        # New IP or ASN migration
        current_asn_record.unique_ip_count += 1
        logger.debug(f"Incremented unique_ip_count for ASN {current_asn} → {current_asn_record.unique_ip_count}")

        # Decrement previous ASN if IP migrated
        if previous_asn and previous_asn != current_asn:
            prev_stmt = select(ASNInventory).where(
                ASNInventory.asn_number == previous_asn
            ).with_for_update()
            prev_asn_record = self.session.execute(prev_stmt).scalar_one_or_none()
            if prev_asn_record and prev_asn_record.unique_ip_count > 0:
                prev_asn_record.unique_ip_count -= 1
                logger.debug(f"Decremented unique_ip_count for ASN {previous_asn} → {prev_asn_record.unique_ip_count}")

    # Always increment session count for current ASN
    current_asn_record.total_session_count += 1
    logger.debug(f"Incremented total_session_count for ASN {current_asn} → {current_asn_record.total_session_count}")

    self.session.flush()


def _update_session_counts(self, asn: int | None, increment: int = 1) -> None:
    """Increment session count for an ASN (used for cache hits).

    Args:
        asn: ASN number to update
        increment: Number of sessions to add (default 1)
    """
    if asn is None:
        return

    stmt = select(ASNInventory).where(
        ASNInventory.asn_number == asn
    ).with_for_update()
    asn_record = self.session.execute(stmt).scalar_one_or_none()

    if asn_record:
        asn_record.total_session_count += increment
        self.session.flush()
```

#### Edge Cases Handled

1. **New IP with ASN**: Increment both `unique_ip_count` and `total_session_count`
2. **Existing IP, same ASN**: Only increment `total_session_count`
3. **IP migrated to new ASN**: Decrement old ASN `unique_ip_count`, increment new ASN `unique_ip_count` and `total_session_count`
4. **IP with no ASN**: No updates (graceful degradation)
5. **Cache hits**: Increment `total_session_count` without re-enrichment
6. **Race conditions**: Use `with_for_update()` for row-level locking
7. **ASN record missing**: Log warning and continue (defensive programming)

#### Testing Strategy

```python
# tests/unit/enrichment/test_cascade_asn_statistics.py

def test_new_ip_increments_asn_counts(cascade, session):
    """New IP should increment both unique_ip_count and total_session_count."""
    result = cascade.enrich_ip("8.8.8.8")  # Google DNS

    asn_record = session.query(ASNInventory).filter(
        ASNInventory.asn_number == result.current_asn
    ).first()

    assert asn_record.unique_ip_count == 1
    assert asn_record.total_session_count == 1


def test_existing_ip_same_asn_increments_session_count(cascade, session):
    """Existing IP with same ASN should only increment session count."""
    cascade.enrich_ip("8.8.8.8")  # First enrichment
    cascade.enrich_ip("8.8.8.8")  # Second enrichment

    asn_record = session.query(ASNInventory).filter(
        ASNInventory.asn_number == 15169  # Google ASN
    ).first()

    assert asn_record.unique_ip_count == 1  # Still 1 unique IP
    assert asn_record.total_session_count == 2  # 2 sessions


def test_ip_asn_migration_updates_both_asns(cascade, session):
    """IP migrating ASNs should update both old and new ASN counts."""
    # Simulate IP initially in ASN 123
    cascade.enrich_ip("1.2.3.4")
    asn_123 = session.query(ASNInventory).filter(ASNInventory.asn_number == 123).first()
    assert asn_123.unique_ip_count == 1

    # Mock ASN change to 456
    # (In reality, this requires mocking MaxMind/Cymru to return new ASN)
    # ... migration logic ...

    asn_123_after = session.query(ASNInventory).filter(ASNInventory.asn_number == 123).first()
    asn_456_after = session.query(ASNInventory).filter(ASNInventory.asn_number == 456).first()

    assert asn_123_after.unique_ip_count == 0  # Decremented
    assert asn_456_after.unique_ip_count == 1  # Incremented


def test_concurrent_updates_with_locking(cascade, session):
    """Test row-level locking prevents race conditions."""
    # Use threading to simulate concurrent enrichments
    # Verify final counts are correct (no lost updates)
    # ...
```

### Phase 2: CLI Refresh Tool (FOLLOW-UP WORK)

Create maintenance command for periodic reconciliation.

#### Implementation Sketch

```python
# cowrieprocessor/cli/cowrie_db.py

@click.command("refresh-asn-stats")
@click.option("--verbose", is_flag=True, help="Show detailed progress")
@click.option("--report-only", is_flag=True, help="Report discrepancies without fixing")
@click.pass_context
def refresh_asn_stats(ctx, verbose: bool, report_only: bool) -> None:
    """Recalculate ASN inventory statistics from IP inventory.

    This command performs a full reconciliation of ASN aggregate statistics
    by querying the ip_inventory table. Use this periodically to catch drift
    from application crashes, rollbacks, or race conditions.

    Recommended: Run weekly via cron.
    """
    engine = ctx.obj["engine"]

    with Session(engine) as session:
        # Query actual counts from ip_inventory
        actual_counts = session.query(
            IPInventory.current_asn,
            func.count(func.distinct(IPInventory.ip_address)).label("unique_ips"),
            func.sum(IPInventory.session_count).label("total_sessions")
        ).filter(
            IPInventory.current_asn.isnot(None)
        ).group_by(
            IPInventory.current_asn
        ).all()

        discrepancies = []

        for asn, actual_unique, actual_total in actual_counts:
            # Get current stored values
            asn_record = session.query(ASNInventory).filter(
                ASNInventory.asn_number == asn
            ).first()

            if not asn_record:
                click.echo(f"WARNING: ASN {asn} has IPs but no ASN record", err=True)
                continue

            # Check for discrepancies
            unique_diff = actual_unique - asn_record.unique_ip_count
            session_diff = actual_total - asn_record.total_session_count

            if unique_diff != 0 or session_diff != 0:
                discrepancies.append({
                    "asn": asn,
                    "org": asn_record.organization_name,
                    "unique_diff": unique_diff,
                    "session_diff": session_diff,
                    "stored_unique": asn_record.unique_ip_count,
                    "actual_unique": actual_unique,
                    "stored_sessions": asn_record.total_session_count,
                    "actual_sessions": actual_total
                })

                if not report_only:
                    # Fix discrepancies
                    asn_record.unique_ip_count = actual_unique
                    asn_record.total_session_count = actual_total
                    if verbose:
                        click.echo(f"Fixed ASN {asn}: unique {unique_diff:+d}, sessions {session_diff:+d}")

        if not report_only:
            session.commit()
            click.echo(f"✓ Updated {len(discrepancies)} ASN records")
        else:
            click.echo(f"Found {len(discrepancies)} discrepancies (use --report-only to fix)")

        if verbose and discrepancies:
            click.echo("\nDiscrepancies:")
            for disc in discrepancies:
                click.echo(f"  ASN {disc['asn']} ({disc['org']})")
                click.echo(f"    Unique IPs: {disc['stored_unique']} → {disc['actual_unique']} ({disc['unique_diff']:+d})")
                click.echo(f"    Sessions: {disc['stored_sessions']} → {disc['actual_sessions']} ({disc['session_diff']:+d})")
```

#### Scheduling

Add to production cron:
```bash
# Refresh ASN statistics weekly (Sunday 3am)
0 3 * * 0 /usr/bin/uv run cowrie-db refresh-asn-stats --verbose >> /var/log/cowrie/asn-refresh.log 2>&1
```

## Performance Analysis

### Current Performance (Baseline)

Per `enrich_ip()` call:
- 1 SELECT on `ip_inventory` (cache check)
- 1 SELECT on `asn_inventory` (with row lock in `_ensure_asn_inventory`)
- 1 UPDATE or INSERT on `ip_inventory`
- 1 UPDATE or INSERT on `asn_inventory` (if ASN created/updated)
- **Total: 4-6 database operations**

### With Phase 1 Changes

Per `enrich_ip()` call:
- 1 SELECT on `ip_inventory` (cache check)
- 1 SELECT on `asn_inventory` (with row lock in `_ensure_asn_inventory`)
- 1 UPDATE or INSERT on `ip_inventory`
- 1 UPDATE or INSERT on `asn_inventory` (if ASN created/updated)
- **1 additional SELECT + UPDATE on `asn_inventory` (statistics update with lock)**
- **Total: 5-7 database operations (~20% increase)**

### Volume Projections

**Development (SQLite)**:
- 10-100 sessions/hour
- Impact: Negligible (SQLite handles this easily)
- Table-level locking may cause slight contention

**Production (PostgreSQL)**:
- 1000+ sessions/hour
- 5000 DB ops/hour → 6000 DB ops/hour
- Row-level locking prevents contention
- PostgreSQL easily handles this load

### Optimization Opportunities (Future)

1. **Batch statistics updates**: Accumulate changes in memory, flush every N seconds
2. **Redis counter cache**: Use Redis INCR for hot ASNs, sync to database periodically
3. **Materialized views**: PostgreSQL materialized views for read-heavy analytics

## Database Compatibility

### SQLite Considerations

- `with_for_update()` uses `BEGIN EXCLUSIVE` (table-level lock)
- Safe for single-writer scenarios (development, single-sensor)
- May see contention with concurrent sessions (acceptable for dev)

### PostgreSQL Considerations

- `with_for_update()` uses `SELECT FOR UPDATE` (row-level lock)
- Excellent concurrency for multi-sensor production
- MVCC ensures ACID guarantees

## Migration Strategy

### Schema Changes: None Required

The `asn_inventory` table already has the required fields:
```sql
unique_ip_count INTEGER NOT NULL DEFAULT 0
total_session_count INTEGER NOT NULL DEFAULT 0
```

No schema migration needed.

### Data Backfill

For existing databases with ASNs already created:

```bash
# One-time backfill
uv run cowrie-db refresh-asn-stats --verbose
```

This will calculate actual counts from `ip_inventory` and populate the fields.

## Testing Requirements

### Unit Tests (Required for PR)

1. **New IP enrichment**: Verify both counters increment
2. **Existing IP re-enrichment**: Verify only session count increments
3. **ASN migration**: Verify old ASN decrements, new ASN increments
4. **Cache hits**: Verify session count increments without full enrichment
5. **No ASN**: Verify graceful degradation (no errors)
6. **Concurrent updates**: Verify locking prevents race conditions

### Integration Tests (Required for PR)

1. **Full enrichment flow**: Process 100 sessions, verify ASN counts match reality
2. **SQLite compatibility**: Run on SQLite, verify counts are correct
3. **PostgreSQL compatibility**: Run on PostgreSQL, verify row-level locking works

### Performance Tests (Optional)

1. **Benchmark overhead**: Measure 20% overhead claim
2. **Concurrent load**: 10 threads processing 100 sessions each

## Rollout Plan

### Phase 1: Current PR (PR-BLOCKING)

- [ ] Implement `_update_asn_statistics()` method
- [ ] Implement `_update_session_counts()` method
- [ ] Modify `enrich_ip()` to track previous ASN and call update methods
- [ ] Write unit tests for all edge cases
- [ ] Write integration tests for SQLite and PostgreSQL
- [ ] Update `CascadeStats` to track statistics update counts
- [ ] Document behavior in code comments and docstrings

**Success Criteria**: All tests pass, ASN statistics are accurate in real-time.

### Phase 2: Follow-up PR (POST-MERGE)

- [ ] Implement `cowrie-db refresh-asn-stats` CLI command
- [ ] Write tests for refresh logic
- [ ] Add discrepancy reporting
- [ ] Document cron scheduling recommendations
- [ ] Run one-time backfill on production databases

**Success Criteria**: Weekly cron job runs successfully, reports zero discrepancies.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Race conditions in concurrent updates | Data corruption (incorrect counts) | Use `with_for_update()` row-level locking |
| Performance regression on high-volume systems | Slower enrichment pipeline | Benchmark 20% overhead, acceptable for real-time stats |
| SQLite table-level lock contention | Slower dev/test environments | Document trade-off, production uses PostgreSQL |
| ASN count drift from crashes/rollbacks | Inaccurate statistics | Phase 2 CLI refresh tool for self-healing |
| Complexity increases maintenance burden | Harder to debug issues | Comprehensive unit tests, detailed logging |

## Alternatives Considered and Rejected

1. **PostgreSQL-only triggers**: Violates SQLite compatibility
2. **Materialized views**: Read-only, doesn't help with real-time updates
3. **Event-driven updates (message queue)**: Over-engineering for this use case
4. **Denormalization to session_summaries**: Breaks relational model, harder to query

## Success Metrics

**Phase 1 (Application-level)**:
- [ ] ASN statistics accuracy: 100% match with ground truth
- [ ] Performance overhead: ≤20% increase in database operations
- [ ] Test coverage: ≥80% for new code paths
- [ ] Zero race condition errors in production logs

**Phase 2 (CLI refresh)**:
- [ ] Weekly refresh completes in <5 minutes
- [ ] Discrepancy rate: <1% after 1 week of Phase 1
- [ ] Zero manual interventions required

## Conclusion

**Recommended Approach**: Option D (Combination of application-level incremental updates + periodic CLI refresh)

**PR-Blocking Work**: Phase 1 implementation (application-level updates in `enrich_ip()`)

**Follow-up Work**: Phase 2 implementation (`cowrie-db refresh-asn-stats` CLI tool)

This design provides:
- Real-time accurate ASN statistics
- Database compatibility (SQLite and PostgreSQL)
- Self-healing through periodic reconciliation
- Acceptable performance overhead (20%)
- Comprehensive testing strategy

The implementation is straightforward, testable, and aligns with existing code patterns in the codebase.
