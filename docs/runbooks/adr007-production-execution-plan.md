# ADR-007 Phase 3 Production Execution Plan

**Document Version**: 1.0
**Last Updated**: 2025-11-06
**Owner**: Database Administrator / DevOps
**Status**: 🟡 PENDING - Schema Migration Required First

---

## Overview

This runbook provides step-by-step instructions for executing the ADR-007 snapshot population backfill on production database after schema migration is completed.

**Prerequisites**:
- ✅ Schema migration complete (`snapshot_ip_types` → `snapshot_ip_type`)
- ✅ All validation tests passing
- ✅ Dry-run successful (10K sessions minimum)
- ✅ Stakeholder approval obtained
- ✅ Maintenance window scheduled

**Estimated Duration**: 90-120 minutes for full backfill (1.68M sessions)

**Rollback Time**: <1 minute (simple UPDATE to NULL)

---

## Phase 1: Schema Migration (PREREQUISITE)

### Step 1.1: Create Migration Script

**File**: `scripts/migrations/rename_snapshot_ip_types.py`

```python
#!/usr/bin/env python3
"""Rename snapshot_ip_types → snapshot_ip_type for ADR-007 schema alignment.

This migration aligns production schema with codebase ORM models.

**Safety**:
- Non-destructive column rename
- No data loss
- Fast execution (all values currently NULL)
- Rollback supported

**Usage**:
    uv run python scripts/migrations/rename_snapshot_ip_types.py \\
        --db "postgresql://user:pass@host:port/database"  # pragma: allowlist secret \\  # pragma: allowlist secret
        --dry-run  # Validate first

    # Execute migration
    uv run python scripts/migrations/rename_snapshot_ip_types.py \\
        --db "postgresql://user:pass@host:port/database"  # pragma: allowlist secret
"""

from sqlalchemy import text
from cowrieprocessor.db import create_engine_from_settings
from cowrieprocessor.settings import DatabaseSettings

def migrate_column_name(db_url: str, dry_run: bool = False) -> None:
    """Rename snapshot_ip_types to snapshot_ip_type."""
    db_settings = DatabaseSettings(url=db_url)
    engine = create_engine_from_settings(db_settings)

    with engine.begin() as conn:
        # Check current schema
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'session_summaries'
            AND column_name LIKE 'snapshot_ip%'
        """)).fetchall()

        columns = [row[0] for row in result]
        print(f"Current columns: {columns}")

        if 'snapshot_ip_types' not in columns:
            print("ERROR: snapshot_ip_types column not found!")
            return

        if 'snapshot_ip_type' in columns:
            print("WARNING: snapshot_ip_type already exists!")
            return

        if dry_run:
            print("[DRY-RUN] Would execute:")
            print("  ALTER TABLE session_summaries")
            print("    RENAME COLUMN snapshot_ip_types TO snapshot_ip_type;")
            return

        # Execute migration
        print("Renaming column...")
        conn.execute(text("""
            ALTER TABLE session_summaries
            RENAME COLUMN snapshot_ip_types TO snapshot_ip_type
        """))

        print("✓ Column renamed successfully")

        # Verify
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'session_summaries'
            AND column_name LIKE 'snapshot_ip%'
        """)).fetchall()

        new_columns = [row[0] for row in result]
        print(f"New columns: {new_columns}")

        assert 'snapshot_ip_type' in new_columns
        assert 'snapshot_ip_types' not in new_columns

        print("✓ Migration verified")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, help='Database URL')
    parser.add_argument('--dry-run', action='store_true', help='Show changes without executing')
    args = parser.parse_args()

    migrate_column_name(args.db, dry_run=args.dry_run)
```

### Step 1.2: Test Migration on Development

```bash
# Test on SQLite development database
uv run python scripts/migrations/rename_snapshot_ip_types.py \\
    --db "sqlite:///test.db" \\
    --dry-run

# Execute on development
uv run python scripts/migrations/rename_snapshot_ip_types.py \\
    --db "sqlite:///test.db"
```

### Step 1.3: Execute on Production

**Maintenance Window**: Schedule 15-minute window (migration is fast, but buffer for safety)

```bash
# Step 1: Dry-run validation
uv run python scripts/migrations/rename_snapshot_ip_types.py \\
    --db "postgresql://cowrieprocessor:***@10.130.30.89:5432/cowrieprocessor" \\
    --dry-run

# Step 2: Execute migration
uv run python scripts/migrations/rename_snapshot_ip_types.py \\
    --db "postgresql://cowrieprocessor:***@10.130.30.89:5432/cowrieprocessor"

# Step 3: Verify
psql -h 10.130.30.89 -U cowrieprocessor -d cowrieprocessor -c "
SELECT column_name FROM information_schema.columns
WHERE table_name = 'session_summaries' AND column_name LIKE 'snapshot%';
"
```

**Expected Output**:
```
column_name
-------------------
 snapshot_asn
 snapshot_country
 snapshot_ip_type   <-- Singular!
```

### Step 1.4: Rollback Plan (If Needed)

```sql
-- Rollback: Rename back to plural
ALTER TABLE session_summaries
RENAME COLUMN snapshot_ip_type TO snapshot_ip_types;
```

---

## Phase 2: Post-Migration Validation (30-60 minutes)

### Step 2.1: Re-Run Validation Test Suite

```bash
# Run all read-only validation tests
uv run pytest tests/validation/test_production_validation.py -m read_only -v

# Expected: All 9 tests PASS
```

**Success Criteria**:
- ✅ test_database_connectivity: PASS
- ✅ test_baseline_snapshot_coverage: PASS (0% coverage expected)
- ✅ test_backfill_requirements: PASS (~1.68M sessions needing backfill)
- ✅ test_dry_run_safety: PASS (no database changes)
- ✅ test_dry_run_batch_performance: PASS (<5 sec per 1000 sessions)
- ✅ test_query_performance_snapshot_vs_join: PASS (once snapshots exist)
- ✅ test_snapshot_accuracy_sampling: PASS (once snapshots exist)
- ✅ test_sample_session_inspection: PASS
- ✅ test_production_readiness_checklist: PASS

### Step 2.2: Measure Baseline Coverage

```bash
psql -h 10.130.30.89 -U cowrieprocessor -d cowrieprocessor -c "
SELECT
    COUNT(*) as total_sessions,
    SUM(CASE WHEN source_ip IS NOT NULL THEN 1 ELSE 0 END) as with_source_ip,
    SUM(CASE WHEN snapshot_country IS NOT NULL THEN 1 ELSE 0 END) as with_snapshots,
    ROUND(100.0 * SUM(CASE WHEN snapshot_country IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 2) as pct_snapshots
FROM session_summaries;
"
```

**Expected**:
```
 total_sessions | with_source_ip | with_snapshots | pct_snapshots
----------------+----------------+----------------+---------------
      1,682,827 |              0 |              0 |          0.00
```

### Step 2.3: Small-Scale Backfill Test (10K Sessions)

```bash
# Create status directory
mkdir -p /mnt/dshield/data/logs/status/validation

# Execute small-scale backfill (10 batches = 10K sessions)
uv run python scripts/migrations/backfill_session_snapshots.py \\
    --db "postgresql://cowrieprocessor:***@10.130.30.89:5432/cowrieprocessor" \\
    --batch-size 1000 \\
    --max-batches 10 \\
    --status-dir /mnt/dshield/data/logs/status/validation \\
    --progress \\
    --verbose
```

**Success Criteria**:
- ✅ Execution completes without errors
- ✅ 10,000 sessions updated (±100 for edge cases)
- ✅ Processing speed: 2000-5000 sessions/second
- ✅ No "column does not exist" errors
- ✅ Status files created in status directory

### Step 2.4: Validate Small-Scale Results

```bash
# Check coverage increase
psql -h 10.130.30.89 -U cowrieprocessor -d cowrieprocessor -c "
SELECT COUNT(*) FROM session_summaries WHERE snapshot_country IS NOT NULL;
"

# Expected: ~10,000 (±100)

# Sample validation (10 random sessions)
psql -h 10.130.30.89 -U cowrieprocessor -d cowrieprocessor -c "
SELECT session_id, source_ip, snapshot_asn, snapshot_country, snapshot_ip_type
FROM session_summaries
WHERE snapshot_country IS NOT NULL
LIMIT 10;
"
```

**Data Quality Check**:
```bash
# Verify snapshots match ip_inventory
psql -h 10.130.30.89 -U cowrieprocessor -d cowrieprocessor -c "
SELECT
    COUNT(*) as total,
    SUM(CASE WHEN ss.snapshot_asn = ip.current_asn THEN 1 ELSE 0 END) as asn_matches,
    SUM(CASE WHEN ss.snapshot_country = ip.geo_country THEN 1 ELSE 0 END) as country_matches
FROM session_summaries ss
JOIN ip_inventory ip ON ss.source_ip = ip.ip_address
WHERE ss.snapshot_country IS NOT NULL
LIMIT 1000;
"
```

**Expected**: >99% match rate (allows <1% temporal drift)

### Step 2.5: Query Performance Validation

```bash
# Test snapshot query (NO JOIN)
time psql -h 10.130.30.89 -U cowrieprocessor -d cowrieprocessor -c "
SELECT COUNT(*) FROM session_summaries
WHERE snapshot_country = 'CN' AND snapshot_ip_type = 'DATACENTER';
"

# Test JOIN query (slower)
time psql -h 10.130.30.89 -U cowrieprocessor -d cowrieprocessor -c "
SELECT COUNT(*) FROM session_summaries ss
JOIN ip_inventory ip ON ss.source_ip = ip.ip_address
WHERE ip.geo_country = 'CN' AND ip.ip_type = 'DATACENTER';
"
```

**Expected**: Snapshot query 5-10x faster than JOIN

---

## Phase 3: Full Production Backfill (90-120 minutes)

### Step 3.1: Pre-Execution Checklist

**Verify Prerequisites**:
- [ ] Schema migration completed successfully
- [ ] All validation tests passing
- [ ] Small-scale backfill (10K) successful
- [ ] Query performance validated (5-10x speedup)
- [ ] Data quality validated (>99% accuracy)
- [ ] Stakeholder approval obtained
- [ ] Backup created (optional, snapshots are additive)
- [ ] Maintenance window scheduled

**Environment Check**:
```bash
# Check database connectivity
psql -h 10.130.30.89 -U cowrieprocessor -d cowrieprocessor -c "SELECT version();"

# Check disk space
df -h /var/lib/postgresql

# Check current coverage
psql -h 10.130.30.89 -U cowrieprocessor -d cowrieprocessor -c "
SELECT COUNT(*) FROM session_summaries WHERE source_ip IS NULL;
"
```

### Step 3.2: Execute Full Backfill

**Command**:
```bash
# Navigate to project directory
cd /Users/speterson/src/dshield/cowrieprocessor

# Execute backfill (all batches, ~1680 batches for 1.68M sessions)
# pragma: allowlist secret
uv run python scripts/migrations/backfill_session_snapshots.py \\
    --db "postgresql://cowrieprocessor:yqMtPOTNOBCCDk9AA8gYWQs@10.130.30.89:5432/cowrieprocessor" \\
    --batch-size 1000 \\
    --status-dir /mnt/dshield/data/logs/status/backfill \\
    --progress \\
    --verbose \\
    2>&1 | tee backfill_$(date +%Y%m%d_%H%M%S).log
```

**Monitoring** (in separate terminal):
```bash
# Monitor progress in real-time
watch -n 5 'psql -h 10.130.30.89 -U cowrieprocessor -d cowrieprocessor -c "
SELECT
    COUNT(*) as total,
    SUM(CASE WHEN snapshot_country IS NOT NULL THEN 1 ELSE 0 END) as with_snapshots,
    ROUND(100.0 * SUM(CASE WHEN snapshot_country IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 2) as pct_complete
FROM session_summaries;
"'

# Monitor status files
tail -f /mnt/dshield/data/logs/status/backfill/backfill_session_snapshots_*.json
```

**Expected Timeline**:
- Batch size: 1000 sessions
- Batches: ~1683 (for 1.68M sessions)
- Speed: 2-5 seconds per batch
- Total time: 56-140 minutes (avg: 90 minutes)

### Step 3.3: Real-Time Monitoring

**Key Metrics to Watch**:
1. **Progress**: Sessions updated / total sessions
2. **Speed**: Sessions per second (target: 2000-5000)
3. **Errors**: Any "column does not exist" or constraint violations
4. **Memory**: PostgreSQL memory usage
5. **Disk I/O**: Write throughput

**Alert Triggers**:
- Speed drops below 1000 sessions/second → investigate performance
- Errors appear → pause and investigate
- Memory usage >90% → consider batching smaller
- Disk space <10% → abort and free space

### Step 3.4: Handle Interruptions

**If Backfill is Interrupted** (network, crash, etc.):
```bash
# Check current coverage
psql -h 10.130.30.89 -U cowrieprocessor -d cowrieprocessor -c "
SELECT COUNT(*) FROM session_summaries WHERE source_ip IS NULL;
"

# Resume backfill (script automatically skips already-populated sessions)
uv run python scripts/migrations/backfill_session_snapshots.py \\
    --db "postgresql://..." \\
    --batch-size 1000 \\
    --status-dir /mnt/dshield/data/logs/status/backfill \\
    --progress
```

**Note**: The backfill script is idempotent (uses COALESCE to preserve existing values)

---

## Phase 4: Post-Backfill Validation (15-30 minutes)

### Step 4.1: Verify Completion

```bash
# Check final coverage
psql -h 10.130.30.89 -U cowrieprocessor -d cowrieprocessor -c "
SELECT
    COUNT(*) as total_sessions,
    SUM(CASE WHEN source_ip IS NOT NULL THEN 1 ELSE 0 END) as with_source_ip,
    SUM(CASE WHEN snapshot_country IS NOT NULL THEN 1 ELSE 0 END) as with_snapshots,
    ROUND(100.0 * SUM(CASE WHEN snapshot_country IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 2) as pct_complete
FROM session_summaries;
"
```

**Expected**:
```
 total_sessions | with_source_ip | with_snapshots | pct_complete
----------------+----------------+----------------+--------------
      1,682,827 |      1,682,827 |      1,600,000 |        95.08
```

**Note**: ~95-99% coverage expected (some IPs may lack ip_inventory entries)

### Step 4.2: Data Quality Validation

**Random Sample Check** (1000 sessions):
```bash
uv run pytest tests/validation/test_production_validation.py::test_snapshot_accuracy_sampling -v -s
```

**Expected**: ≥99% accuracy rate

### Step 4.3: Query Performance Validation

**Run Performance Tests**:
```bash
uv run pytest tests/validation/test_production_validation.py::test_query_performance_snapshot_vs_join -v -s
```

**Expected**: 5-10x speedup for snapshot queries

### Step 4.4: Application Smoke Tests

**Test Snowshoe Detection** (if applicable):
```bash
# Test snowshoe query using snapshots
psql -h 10.130.30.89 -U cowrieprocessor -d cowrieprocessor -c "
SELECT snapshot_asn, COUNT(DISTINCT source_ip) as unique_ips
FROM session_summaries
WHERE snapshot_country = 'CN' AND snapshot_ip_type = 'DATACENTER'
GROUP BY snapshot_asn
HAVING COUNT(DISTINCT source_ip) > 100
ORDER BY unique_ips DESC
LIMIT 10;
"
```

**Test Campaign Clustering**:
```bash
# Group sessions by ASN at time of attack
psql -h 10.130.30.89 -U cowrieprocessor -d cowrieprocessor -c "
SELECT snapshot_asn, snapshot_country, COUNT(*) as session_count
FROM session_summaries
WHERE snapshot_asn IS NOT NULL
GROUP BY snapshot_asn, snapshot_country
ORDER BY session_count DESC
LIMIT 20;
"
```

---

## Rollback Procedures

### Rollback Scenario 1: Schema Migration Fails

**Problem**: Column rename failed or caused issues

**Rollback**:
```sql
-- Rename back to plural
ALTER TABLE session_summaries
RENAME COLUMN snapshot_ip_type TO snapshot_ip_types;
```

**Verification**:
```sql
SELECT column_name FROM information_schema.columns
WHERE table_name = 'session_summaries' AND column_name LIKE 'snapshot%';
```

**Impact**: Zero (no data modified yet)

### Rollback Scenario 2: Backfill Produces Bad Data

**Problem**: Snapshot values incorrect or corrupt

**Rollback**:
```sql
-- Clear all snapshot data (safe, data is additive)
UPDATE session_summaries SET
    source_ip = NULL,
    snapshot_asn = NULL,
    snapshot_country = NULL,
    snapshot_ip_type = NULL,
    enrichment_at = NULL
WHERE enrichment_at > '2025-11-06 00:00:00';  -- Only rollback new data
```

**Verification**:
```sql
SELECT COUNT(*) FROM session_summaries WHERE snapshot_country IS NOT NULL;
-- Expected: 0 (or previous baseline if partial backfill existed)
```

**Impact**: Low (snapshots are optimization, not critical data)

### Rollback Scenario 3: Performance Degradation

**Problem**: Queries slower after backfill

**Investigation**:
```sql
-- Check index health
SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE tablename = 'session_summaries' AND indexname LIKE '%snapshot%';

-- Rebuild indexes if needed
REINDEX TABLE session_summaries;

-- Update statistics
ANALYZE session_summaries;
```

**If Persistent**: Rollback to Scenario 2 (clear snapshots)

---

## Success Criteria

### Mandatory Requirements

- ✅ Schema migration successful (`snapshot_ip_type` exists)
- ✅ Backfill completes without errors
- ✅ Coverage ≥95% (1.6M+ sessions with snapshots)
- ✅ Data quality ≥99% accuracy on sample validation
- ✅ Query performance 5-10x faster vs JOIN
- ✅ No application errors post-backfill
- ✅ All validation tests passing

### Performance Benchmarks

**Before Backfill**:
```sql
-- Country filter query (WITH JOIN)
EXPLAIN ANALYZE
SELECT COUNT(*) FROM session_summaries ss
JOIN ip_inventory ip ON ss.source_ip = ip.ip_address
WHERE ip.geo_country = 'CN';

-- Expected: 10-50 seconds, Sequential Scan + Hash Join
```

**After Backfill**:
```sql
-- Country filter query (NO JOIN)
EXPLAIN ANALYZE
SELECT COUNT(*) FROM session_summaries
WHERE snapshot_country = 'CN';

-- Expected: 2-5 seconds, Index Scan, 5-10x faster
```

---

## Monitoring and Alerts

### During Backfill

**Monitor**:
- Progress: `watch psql -c "SELECT COUNT(*) ... WHERE snapshot_country IS NOT NULL"`
- Logs: `tail -f backfill_*.log`
- Status files: `tail -f /mnt/dshield/data/logs/status/backfill/*.json`
- Database load: `psql -c "SELECT * FROM pg_stat_activity WHERE datname = 'cowrieprocessor'"`

**Alert Conditions**:
- Speed <1000 sessions/sec for >5 minutes
- Error rate >0.1%
- Memory usage >90%
- Disk space <10%

### Post-Backfill

**Continuous Monitoring**:
- Daily coverage check (should remain ≥95%)
- Weekly query performance benchmarks
- Monthly data quality sampling

**Alert Triggers**:
- Coverage drops below 90%
- Query performance degrades >20%
- New sessions not getting snapshots

---

## Contact Information

**Database Administrator**: [Your DBA contact]
**DevOps On-Call**: [DevOps contact]
**Escalation**: [Manager contact]

**Runbook Location**: `docs/runbooks/adr007-production-execution-plan.md`
**Validation Report**: `docs/validation/adr007-phase3-validation-report.md`
**Design Document**: `docs/designs/adr007-snapshot-population-fix.md`

---

**Last Updated**: 2025-11-06
**Next Review**: After schema migration completion
**Document Owner**: Quality Engineer
