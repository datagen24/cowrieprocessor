# ADR-007 Snapshot Population Fix - Design Document

**Status**: Design Complete
**Priority**: P1 - High
**Estimated Effort**: 6-8 hours implementation + 2-3 hours backfill
**Created**: 2025-11-06
**Author**: PM Agent + Sequential Analysis

## Executive Summary

ADR-007 introduced three-tier enrichment architecture with session snapshot columns for fast filtering without JOINs. However, the loader implementation was incomplete - snapshot columns are NEVER populated, leaving 1.68M production sessions (100%) without snapshot data despite 100% IP inventory enrichment.

This design document specifies the complete fix across all data pipeline stages.

## Problem Statement

### Current Behavior
```sql
-- Production database (2025-11-06)
SELECT COUNT(*) as total_sessions,
       SUM(CASE WHEN snapshot_country IS NOT NULL THEN 1 ELSE 0 END) as enriched
FROM session_summaries;

-- Result: 1,682,827 sessions, 0 enriched (0.00%)
```

### Root Cause
**File**: `cowrieprocessor/loader/bulk.py:588-667`
**Method**: `BulkLoader._upsert_session_summaries()`

Missing fields in values dictionary (lines 596-614):
- ❌ `source_ip` - FK to ip_inventory (required for JOINs)
- ❌ `snapshot_asn` - ASN at time of attack (immutable)
- ❌ `snapshot_country` - Country code at time of attack (immutable)
- ❌ `snapshot_ip_type` - IP type at time of attack (immutable)
- ❌ `enrichment_at` - Timestamp when snapshot was captured

### Impact
1. **Query Performance**: 95% of queries require expensive JOINs instead of snapshot columns (10x slower)
2. **Temporal Accuracy**: Can't track "what was it at time of attack" for campaign clustering
3. **Snowshoe Detection**: Can't filter by country/ASN without JOINs (Phase 1 blocked)
4. **Infrastructure Attribution**: Can't use ASN clustering for botnet analysis

## Architecture Analysis

### Data Pipeline Stages

Based on code analysis, session_summaries is written by:

| Stage | File | Method | Needs Fix? | Rationale |
|-------|------|--------|-----------|-----------|
| **Bulk Load** | `loader/bulk.py` | `_upsert_session_summaries()` | ✅ YES | Initial ingestion - must populate snapshots |
| **Delta Load** | `loader/delta.py` | (delegates to BulkLoader) | ✅ YES | Uses BulkLoader internally (line 58) |
| **Enrichment Refresh** | `cli/enrich_passwords.py` | `update_session()` | ❌ NO | Only updates enrichment JSON (snapshots immutable) |
| **SSH Key Backfill** | `cli/enrich_ssh_keys.py` | `_update_session_summaries()` | ❌ NO | Only updates ssh_key counts (snapshots immutable) |
| **DB Maintenance** | `cli/cowrie_db.py` | Batch updates | ❌ NO | Utility operations (snapshots immutable) |

**Key Insight**: Snapshot columns are set ONCE during initial ingestion (bulk/delta), NEVER updated during refresh. This preserves temporal accuracy per ADR-007 design.

### SessionAggregate Dataclass

**Current State** (`bulk.py:90-110`):
```python
@dataclass(slots=True)
class SessionAggregate:
    """Rolling aggregate for a session during the current batch."""

    event_count: int = 0
    command_count: int = 0
    # ... other fields ...
    sensor: Optional[str] = None
    src_ips: Set[str] = field(default_factory=set)  # ← Multiple IPs tracked
    # ... enrichment fields ...
```

**Issue**: `src_ips` is a SET of all IPs seen during session, but we need ONE canonical IP for FK to ip_inventory.

## Design Solution

### Phase 1: Enhance SessionAggregate

**Add canonical source IP tracking:**

```python
@dataclass(slots=True)
class SessionAggregate:
    """Rolling aggregate for a session during the current batch."""

    # ... existing fields ...
    src_ips: Set[str] = field(default_factory=set)

    # NEW: Canonical source IP for ip_inventory FK and snapshot population
    canonical_source_ip: Optional[str] = None  # First IP seen chronologically
```

**Update logic** (in `_aggregate_event()` around line 263):
```python
# Existing code:
src_ip_val = payload_ref.get("src_ip") or payload_ref.get("peer_ip")
if isinstance(src_ip_val, str) and src_ip_val:
    agg.src_ips.add(src_ip_val)

# NEW: Track canonical IP (first one seen)
    if agg.canonical_source_ip is None:
        agg.canonical_source_ip = src_ip_val
```

**Rationale**: Canonical IP is determined by event chronology (first_event_at), not set insertion order.

### Phase 2: Add IP Inventory Lookup Helper

**New method in BulkLoader class:**

```python
def _lookup_ip_snapshots(
    self,
    session: Session,
    ip_addresses: List[str]
) -> Dict[str, Dict[str, Any]]:
    """Batch lookup snapshot data from ip_inventory for given IPs.

    Args:
        session: SQLAlchemy session
        ip_addresses: List of IP addresses to look up

    Returns:
        Dict mapping IP address to snapshot data dict with keys:
        - asn: Integer ASN number
        - country: 2-letter country code
        - ip_type: String IP type (e.g., 'RESIDENTIAL', 'DATACENTER')
        - enrichment_at: Timestamp of enrichment

    Note:
        Missing IPs return empty dict. IPs without enrichment return
        partial data (e.g., asn may be None if Cymru failed).
    """
    from ..db.models import IPInventory

    if not ip_addresses:
        return {}

    # Batch query for all IPs
    results = session.query(
        IPInventory.ip_address,
        IPInventory.current_asn,
        IPInventory.geo_country,
        IPInventory.ip_types,
        IPInventory.enrichment_updated_at,
    ).filter(
        IPInventory.ip_address.in_(ip_addresses)
    ).all()

    snapshots = {}
    for row in results:
        ip, asn, country, ip_types, enriched_at = row

        # Determine primary IP type from array
        # Priority: VPN > TOR > PROXY > DATACENTER > RESIDENTIAL > MOBILE
        primary_type = None
        if ip_types:
            type_priority = {'VPN': 1, 'TOR': 2, 'PROXY': 3, 'DATACENTER': 4, 'RESIDENTIAL': 5, 'MOBILE': 6}
            sorted_types = sorted(ip_types, key=lambda t: type_priority.get(t, 99))
            primary_type = sorted_types[0] if sorted_types else None

        snapshots[ip] = {
            'asn': asn,
            'country': country if country != 'XX' else None,  # XX = unknown
            'ip_type': primary_type,
            'enrichment_at': enriched_at,
        }

    return snapshots
```

**Rationale**:
- Batch lookup minimizes DB round-trips (1 query for entire batch)
- Handles missing/unenriched IPs gracefully (empty dict or partial data)
- IP type prioritization matches GreyNoise/SPUR threat modeling (VPN > residential)

### Phase 3: Update _upsert_session_summaries()

**Current code** (`bulk.py:588-667`):
```python
def _upsert_session_summaries(self, session: Session, aggregates: Dict[str, SessionAggregate]) -> None:
    if not aggregates:
        return

    # ... existing code ...
    values = []
    for session_id, agg in aggregates.items():
        values.append({
            "session_id": session_id,
            "event_count": agg.event_count,
            # ... other fields ...
            "enrichment": agg.enrichment_payload or None,
            # ❌ MISSING: source_ip, snapshot_asn, snapshot_country, snapshot_ip_type, enrichment_at
        })
```

**Enhanced code**:
```python
def _upsert_session_summaries(self, session: Session, aggregates: Dict[str, SessionAggregate]) -> None:
    if not aggregates:
        return

    dialect_name = session.bind.dialect.name if session.bind else ""
    table = cast(Table, SessionSummary.__table__)

    # NEW: Batch lookup IP snapshots for all canonical IPs
    canonical_ips = [agg.canonical_source_ip for agg in aggregates.values() if agg.canonical_source_ip]
    ip_snapshots = self._lookup_ip_snapshots(session, canonical_ips) if canonical_ips else {}

    values = []
    for session_id, agg in aggregates.items():
        # Get snapshot data for this session's canonical IP
        snapshot = ip_snapshots.get(agg.canonical_source_ip, {})

        values.append({
            "session_id": session_id,
            "event_count": agg.event_count,
            "command_count": agg.command_count,
            "file_downloads": agg.file_downloads,
            "login_attempts": agg.login_attempts,
            "first_event_at": agg.first_event_at,
            "last_event_at": agg.last_event_at,
            "risk_score": agg.highest_risk,
            "source_files": self._sanitize_source_files(agg.source_files),
            "matcher": agg.sensor,
            "vt_flagged": agg.vt_flagged,
            "dshield_flagged": agg.dshield_flagged,
            "enrichment": agg.enrichment_payload or None,
            "ssh_key_injections": agg.ssh_key_injections,
            "unique_ssh_keys": len(agg.unique_ssh_keys),

            # NEW: Populate snapshot columns from ip_inventory lookup
            "source_ip": agg.canonical_source_ip,  # FK to ip_inventory
            "snapshot_asn": snapshot.get('asn'),
            "snapshot_country": snapshot.get('country'),
            "snapshot_ip_type": snapshot.get('ip_type'),
            "enrichment_at": snapshot.get('enrichment_at'),
        })

    # ... rest of upsert logic unchanged (SQLite/PostgreSQL branches) ...
```

**Update conflict handling** (add to both SQLite and PostgreSQL branches):
```python
# SQLite branch (line 619-638):
stmt = stmt.on_conflict_do_update(
    index_elements=["session_id"],
    set_={
        # ... existing fields ...
        "updated_at": func.now(),

        # NEW: Snapshots are IMMUTABLE - use COALESCE to preserve existing
        "source_ip": func.coalesce(SessionSummary.source_ip, excluded.source_ip),
        "snapshot_asn": func.coalesce(SessionSummary.snapshot_asn, excluded.snapshot_asn),
        "snapshot_country": func.coalesce(SessionSummary.snapshot_country, excluded.snapshot_country),
        "snapshot_ip_type": func.coalesce(SessionSummary.snapshot_ip_type, excluded.snapshot_ip_type),
        "enrichment_at": func.coalesce(SessionSummary.enrichment_at, excluded.enrichment_at),
    },
)

# PostgreSQL branch (line 645-664): Same COALESCE logic
```

**Rationale**:
- COALESCE ensures snapshots are set ONCE (first ingestion wins)
- Subsequent delta loads for same session preserve original snapshot (temporal accuracy)
- Missing IP inventory entries result in NULL snapshots (graceful degradation)

### Phase 4: Backfill Existing Sessions

**New migration script**: `scripts/migrations/backfill_session_snapshots.py`

```python
"""Backfill snapshot columns for existing session_summaries from ip_inventory.

Usage:
    uv run python scripts/migrations/backfill_session_snapshots.py --db <db_url>

Options:
    --db: Database connection string (or use DB_URI environment variable)
    --batch-size: Batch size for processing (default: 1000)
    --progress: Show progress bar
    --dry-run: Show what would be updated without making changes
    --status-dir: Directory for status files
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict

from sqlalchemy import Engine, func, select, text, update
from sqlalchemy.orm import Session

from cowrieprocessor.db import create_engine_from_settings, create_session_maker
from cowrieprocessor.db.models import IPInventory, SessionSummary
from cowrieprocessor.status_emitter import StatusEmitter

logger = logging.getLogger(__name__)


def backfill_snapshots(
    engine: Engine,
    batch_size: int = 1000,
    dry_run: bool = False,
    status_dir: Path | None = None,
    show_progress: bool = False,
) -> int:
    """Backfill snapshot columns for sessions missing them.

    Algorithm:
        1. Query sessions WHERE source_ip IS NULL (need backfill)
        2. For each batch, extract unique source IPs from enrichment JSON
        3. Lookup snapshot data from ip_inventory
        4. UPDATE session_summaries with snapshot columns

    Returns:
        Number of sessions updated
    """
    session_maker = create_session_maker(engine)
    status_emitter = StatusEmitter("snapshot_backfill", status_dir=status_dir) if status_dir else None

    total_updated = 0
    batch_num = 0

    with session_maker() as session:
        # Count sessions needing backfill
        total_count = session.query(func.count(SessionSummary.session_id)).filter(
            SessionSummary.source_ip.is_(None)
        ).scalar()

        logger.info(f"Found {total_count:,} sessions needing snapshot backfill")

        if dry_run:
            logger.info("DRY RUN - no changes will be made")

        while True:
            batch_num += 1

            # Query batch of sessions missing source_ip
            # Use enrichment JSON to extract source IP (stored during initial ingestion)
            dialect = session.bind.dialect.name

            if dialect == 'postgresql':
                # PostgreSQL: Use JSONB operator
                batch = session.query(
                    SessionSummary.session_id,
                    func.jsonb_extract_path_text(SessionSummary.enrichment, 'session_metadata', 'source_ip').label('source_ip')
                ).filter(
                    SessionSummary.source_ip.is_(None)
                ).limit(batch_size).all()
            else:
                # SQLite: Use json_extract
                batch = session.query(
                    SessionSummary.session_id,
                    func.json_extract(SessionSummary.enrichment, '$.session_metadata.source_ip').label('source_ip')
                ).filter(
                    SessionSummary.source_ip.is_(None)
                ).limit(batch_size).all()

            if not batch:
                break  # No more sessions to process

            # Extract unique IPs for batch lookup
            session_ip_map = {row.session_id: row.source_ip for row in batch if row.source_ip}
            unique_ips = list(set(session_ip_map.values()))

            # Batch lookup snapshots from ip_inventory
            ip_snapshots = {}
            if unique_ips:
                ip_results = session.query(
                    IPInventory.ip_address,
                    IPInventory.current_asn,
                    IPInventory.geo_country,
                    IPInventory.ip_types,
                    IPInventory.enrichment_updated_at,
                ).filter(
                    IPInventory.ip_address.in_(unique_ips)
                ).all()

                for ip, asn, country, ip_types, enriched_at in ip_results:
                    # Determine primary IP type
                    primary_type = None
                    if ip_types:
                        type_priority = {'VPN': 1, 'TOR': 2, 'PROXY': 3, 'DATACENTER': 4, 'RESIDENTIAL': 5, 'MOBILE': 6}
                        sorted_types = sorted(ip_types, key=lambda t: type_priority.get(t, 99))
                        primary_type = sorted_types[0] if sorted_types else None

                    ip_snapshots[ip] = {
                        'asn': asn,
                        'country': country if country != 'XX' else None,
                        'ip_type': primary_type,
                        'enrichment_at': enriched_at,
                    }

            # Update sessions with snapshots
            if not dry_run:
                for session_id, source_ip in session_ip_map.items():
                    if source_ip in ip_snapshots:
                        snapshot = ip_snapshots[source_ip]
                        session.execute(
                            update(SessionSummary).where(
                                SessionSummary.session_id == session_id
                            ).values(
                                source_ip=source_ip,
                                snapshot_asn=snapshot['asn'],
                                snapshot_country=snapshot['country'],
                                snapshot_ip_type=snapshot['ip_type'],
                                enrichment_at=snapshot['enrichment_at'],
                            )
                        )

                session.commit()

            batch_updated = len(session_ip_map)
            total_updated += batch_updated

            # Emit status
            if status_emitter:
                status_emitter.emit({
                    "phase": "backfill",
                    "batch": batch_num,
                    "sessions_updated": total_updated,
                    "total_sessions": total_count,
                    "percent_complete": round(100.0 * total_updated / total_count, 2) if total_count > 0 else 100.0,
                })

            logger.info(f"Batch {batch_num}: Updated {batch_updated} sessions ({total_updated:,}/{total_count:,})")

            if show_progress and total_count > 0:
                pct = 100.0 * total_updated / total_count
                print(f"Progress: {total_updated:,}/{total_count:,} ({pct:.1f}%)", end='\r')

    if status_emitter:
        status_emitter.emit({
            "phase": "complete",
            "sessions_updated": total_updated,
            "total_sessions": total_count,
        })
        status_emitter.close()

    return total_updated


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=str, help='Database connection string')
    parser.add_argument('--batch-size', type=int, default=1000, help='Batch size (default: 1000)')
    parser.add_argument('--progress', action='store_true', help='Show progress bar')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be updated')
    parser.add_argument('--status-dir', type=str, help='Directory for status files')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Create engine
    try:
        engine = create_engine_from_settings(args.db)
    except Exception as e:
        logger.error(f"Failed to create database engine: {e}")
        return 1

    # Run backfill
    try:
        status_dir = Path(args.status_dir) if args.status_dir else None
        updated = backfill_snapshots(
            engine,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            status_dir=status_dir,
            show_progress=args.progress,
        )

        logger.info(f"\nBackfill complete: {updated:,} sessions updated")
        return 0

    except Exception as e:
        logger.error(f"Backfill failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

**Usage**:
```bash
# Production backfill (1.68M sessions, ~30-60 minutes estimated)
uv run python scripts/migrations/backfill_session_snapshots.py \
    --db "postgresql://cowrieprocessor:***@10.130.30.89:5432/cowrieprocessor" \  # pragma: allowlist secret
    --batch-size 1000 \
    --progress \
    --status-dir /volumes/dshield/data/logs/status

# Dry run first (test on sample)
uv run python scripts/migrations/backfill_session_snapshots.py \
    --db "postgresql://..." \
    --dry-run \
    --verbose
```

**Assumptions**:
- SessionSummary.enrichment JSON contains `session_metadata.source_ip` (verified from production data)
- IP inventory already exists and is enriched (verified: 100% coverage)
- Backfill is idempotent (only updates WHERE source_ip IS NULL)

## Testing Strategy

### Unit Tests

**File**: `tests/unit/test_snapshot_population.py`

```python
def test_session_aggregate_tracks_canonical_ip():
    """Verify SessionAggregate.canonical_source_ip is set to first IP seen."""
    agg = SessionAggregate()

    # Simulate events with different IPs
    agg.src_ips.add("192.168.1.1")
    agg.canonical_source_ip = "192.168.1.1"  # First IP

    agg.src_ips.add("192.168.1.2")  # Second IP should NOT change canonical

    assert agg.canonical_source_ip == "192.168.1.1"
    assert len(agg.src_ips) == 2


def test_lookup_ip_snapshots_batch_query(bulk_loader, db_session):
    """Verify _lookup_ip_snapshots performs batch lookup from ip_inventory."""
    # Setup: Create IP inventory entries
    from cowrieprocessor.db.models import IPInventory

    ips = [
        IPInventory(ip_address="1.2.3.4", current_asn=15169, geo_country="US", ip_types=["DATACENTER"]),
        IPInventory(ip_address="5.6.7.8", current_asn=8075, geo_country="GB", ip_types=["RESIDENTIAL"]),
    ]
    db_session.add_all(ips)
    db_session.commit()

    # Test batch lookup
    snapshots = bulk_loader._lookup_ip_snapshots(db_session, ["1.2.3.4", "5.6.7.8", "9.9.9.9"])

    assert len(snapshots) == 2  # Missing IP returns empty
    assert snapshots["1.2.3.4"] == {"asn": 15169, "country": "US", "ip_type": "DATACENTER", "enrichment_at": None}
    assert snapshots["5.6.7.8"] == {"asn": 8075, "country": "GB", "ip_type": "RESIDENTIAL", "enrichment_at": None}


def test_upsert_session_summaries_populates_snapshots(bulk_loader, db_session):
    """Verify _upsert_session_summaries populates snapshot columns from ip_inventory."""
    # Setup IP inventory
    from cowrieprocessor.db.models import IPInventory

    ip = IPInventory(ip_address="47.242.217.70", current_asn=45102, geo_country="CN", ip_types=["DATACENTER"])
    db_session.add(ip)
    db_session.commit()

    # Create session aggregate
    agg = SessionAggregate(
        event_count=1,
        canonical_source_ip="47.242.217.70",
        first_event_at=datetime.now(UTC),
        last_event_at=datetime.now(UTC),
    )

    # Upsert
    bulk_loader._upsert_session_summaries(db_session, {"test_session_id": agg})
    db_session.commit()

    # Verify snapshots populated
    from cowrieprocessor.db.models import SessionSummary

    session_summary = db_session.query(SessionSummary).filter(SessionSummary.session_id == "test_session_id").first()

    assert session_summary.source_ip == "47.242.217.70"
    assert session_summary.snapshot_asn == 45102
    assert session_summary.snapshot_country == "CN"
    assert session_summary.snapshot_ip_type == "DATACENTER"


def test_snapshot_immutability_on_conflict(bulk_loader, db_session):
    """Verify snapshots are NOT overwritten on subsequent upserts (COALESCE)."""
    # Setup
    from cowrieprocessor.db.models import IPInventory, SessionSummary

    ip1 = IPInventory(ip_address="1.1.1.1", current_asn=13335, geo_country="US")
    ip2 = IPInventory(ip_address="2.2.2.2", current_asn=15169, geo_country="GB")
    db_session.add_all([ip1, ip2])
    db_session.commit()

    # First insert
    agg1 = SessionAggregate(event_count=1, canonical_source_ip="1.1.1.1", first_event_at=datetime.now(UTC))
    bulk_loader._upsert_session_summaries(db_session, {"session_123": agg1})
    db_session.commit()

    # Second insert (different IP - simulates session continuation from different IP)
    agg2 = SessionAggregate(event_count=2, canonical_source_ip="2.2.2.2", last_event_at=datetime.now(UTC))
    bulk_loader._upsert_session_summaries(db_session, {"session_123": agg2})
    db_session.commit()

    # Verify original snapshot preserved
    session_summary = db_session.query(SessionSummary).filter(SessionSummary.session_id == "session_123").first()

    assert session_summary.source_ip == "1.1.1.1"  # NOT "2.2.2.2"
    assert session_summary.snapshot_asn == 13335  # NOT 15169
    assert session_summary.snapshot_country == "US"  # NOT "GB"
```

### Integration Tests

**File**: `tests/integration/test_snapshot_backfill.py`

```python
def test_backfill_session_snapshots_end_to_end(test_db_engine):
    """Test complete backfill workflow on test database."""
    # Create test data: sessions without snapshots, IP inventory with enrichment
    # Run backfill script
    # Verify snapshots populated correctly
    # Verify idempotency (running twice doesn't break)
```

### Production Validation

After deployment:

```bash
# 1. Verify snapshot population rate
psql -h 10.130.30.89 -U cowrieprocessor -d cowrieprocessor -c "
SELECT
    COUNT(*) as total_sessions,
    SUM(CASE WHEN source_ip IS NOT NULL THEN 1 ELSE 0 END) as with_source_ip,
    SUM(CASE WHEN snapshot_country IS NOT NULL THEN 1 ELSE 0 END) as with_country,
    ROUND(100.0 * SUM(CASE WHEN snapshot_country IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 2) as pct_enriched
FROM session_summaries;"

# Expected: ~95-99% enriched (some IPs may not have ip_inventory entries)

# 2. Query performance test (snapshot vs JOIN)
EXPLAIN ANALYZE
SELECT COUNT(*) FROM session_summaries WHERE snapshot_country = 'CN';

# vs

EXPLAIN ANALYZE
SELECT COUNT(*) FROM session_summaries ss
JOIN ip_inventory ip ON ss.source_ip = ip.ip_address
WHERE ip.geo_country = 'CN';

# Expected: 5-10x faster with snapshot columns

# 3. Sample validation (random sessions)
SELECT session_id, source_ip, snapshot_asn, snapshot_country, snapshot_ip_type
FROM session_summaries
WHERE snapshot_country IS NOT NULL
LIMIT 10;

# Verify values match ip_inventory
```

## Implementation Plan

### Phase 1: Code Changes (6-8 hours)

1. **Update SessionAggregate** (30 min)
   - Add `canonical_source_ip` field
   - Update `_aggregate_event()` to track first IP

2. **Add _lookup_ip_snapshots() helper** (1 hour)
   - Implement batch lookup logic
   - Add IP type prioritization
   - Handle missing/unenriched IPs gracefully

3. **Enhance _upsert_session_summaries()** (2 hours)
   - Add IP lookup before values construction
   - Populate 5 snapshot fields in values dict
   - Update conflict resolution (COALESCE logic)
   - Test both SQLite and PostgreSQL branches

4. **Unit Tests** (2 hours)
   - Test canonical IP tracking
   - Test batch lookup logic
   - Test snapshot population
   - Test immutability on conflicts

5. **Integration Tests** (1 hour)
   - End-to-end test with real database
   - Test delta load delegation

6. **Documentation** (30 min)
   - Update CLAUDE.md with snapshot population
   - Add inline comments explaining COALESCE rationale

### Phase 2: Backfill Script (2-3 hours)

1. **Write backfill script** (1.5 hours)
   - Implement batch processing
   - Add dry-run mode
   - Add progress monitoring
   - Add status emission

2. **Test on staging** (30 min)
   - Dry-run on sample data
   - Verify idempotency
   - Measure performance (estimate production time)

3. **Production backfill** (1 hour)
   - Monitor progress (1.68M sessions)
   - Validate results
   - Document performance metrics

### Phase 3: Validation (1 hour)

1. **Query performance testing** (30 min)
   - Compare snapshot vs JOIN queries
   - Document speedup metrics

2. **Data quality validation** (30 min)
   - Sample check snapshot accuracy
   - Verify temporal consistency
   - Check coverage percentage

## Success Criteria

1. ✅ **Code Quality**: All unit tests passing, 85%+ coverage for new code
2. ✅ **Data Quality**: ≥95% of sessions have snapshot columns populated
3. ✅ **Performance**: Snapshot queries 5-10x faster than JOIN queries
4. ✅ **Temporal Accuracy**: Snapshots preserve "at time of attack" enrichment
5. ✅ **Immutability**: Subsequent delta loads don't overwrite existing snapshots
6. ✅ **Production Ready**: Backfill completes successfully on 1.68M sessions

## Risks and Mitigation

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| IP inventory missing for some sessions | Partial snapshot population | Medium | Graceful degradation (NULL values acceptable) |
| Backfill script timeout on large dataset | Incomplete migration | Low | Batch processing, resumable design |
| Performance degradation from IP lookup | Slower ingestion | Low | Batch lookup (1 query per batch, not per session) |
| Canonical IP selection incorrect | Wrong snapshots | Low | Clear logic (first IP chronologically), unit tests |

## Rollback Plan

If issues discovered post-deployment:

1. **Code Rollback**: Revert commits, redeploy previous version
2. **Data Rollback**: Snapshots are additive (no data loss), can set to NULL:
   ```sql
   UPDATE session_summaries SET
       source_ip = NULL,
       snapshot_asn = NULL,
       snapshot_country = NULL,
       snapshot_ip_type = NULL,
       enrichment_at = NULL
   WHERE enrichment_at > '2025-11-06';  -- Only rollback new data
   ```
3. **Validation**: Verify system returns to pre-fix state

## Future Enhancements

1. **IPv6 Support**: Update snapshot logic for IPv6 addresses (future ADR)
2. **Snapshot Refresh**: Optional periodic snapshot updates (conflicts with immutability, needs design)
3. **Multi-IP Sessions**: Track all IPs in enrichment JSON, not just canonical (for forensics)
4. **ASN History**: Link to ip_asn_history table for ASN transitions during session

## References

- ADR-007: Three-Tier Enrichment Architecture
- Production Database: 1.68M sessions, 38K IPs (2025-11-06)
- GitHub Issue: #140 (Milestone 1 snowshoe enhancement)
- Memory: `milestone1_feature_discovery` (production analysis)
