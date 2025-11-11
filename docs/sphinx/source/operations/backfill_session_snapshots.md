# Backfill Session Snapshots Runbook

## Overview

This runbook documents the operational procedure for backfilling snapshot columns in the `session_summaries` table using the `backfill_session_snapshots.py` migration script (Phase 2 of ADR-007).

**Purpose**: Populate 5 snapshot columns (source_ip, snapshot_asn, snapshot_country, snapshot_ip_type, enrichment_at) for 1.68M existing sessions that lack snapshot data despite having IP inventory enrichment.

**Design Reference**: `docs/designs/adr007-snapshot-population-fix.md` (Phase 2 section)

## Prerequisites

### Environment Requirements
- **Python**: 3.13+
- **Database**: PostgreSQL 13+ (recommended) or SQLite 3.35+
- **Disk Space**: ~500MB for checkpoint files and logs
- **Memory**: 2GB+ recommended for batch processing
- **Network**: None required (operates on existing database data)

### Access Requirements
- **Database credentials**: Read/write access to `session_summaries` and `ip_inventory` tables
- **File system**: Write access to checkpoint directory (default: `/tmp/`)
- **Status directory** (optional): Write access to `/mnt/dshield/data/logs/status/`

### Pre-Flight Checks

```bash
# 1. Check database connectivity
uv run python -c "from cowrieprocessor.settings import DatabaseSettings; \
from cowrieprocessor.db import create_engine_from_settings; \
engine = create_engine_from_settings(DatabaseSettings(url='YOUR_DB_URI')); \
print(f'Connected: {engine.dialect.name}')"

# 2. Verify sessions needing backfill
uv run python -c "from cowrieprocessor.db import create_engine_from_settings, create_session_maker; \
from cowrieprocessor.db.models import SessionSummary; \
from cowrieprocessor.settings import DatabaseSettings; \
from sqlalchemy import func; \
engine = create_engine_from_settings(DatabaseSettings(url='YOUR_DB_URI')); \
session = create_session_maker(engine)(); \
count = session.query(func.count(SessionSummary.session_id)).filter(SessionSummary.source_ip.is_(None)).scalar(); \
print(f'Sessions needing backfill: {count:,}')"

# 3. Verify IP inventory enrichment coverage
uv run python -c "from cowrieprocessor.db import create_engine_from_settings, create_session_maker; \
from cowrieprocessor.db.models import IPInventory; \
from cowrieprocessor.settings import DatabaseSettings; \
from sqlalchemy import func; \
engine = create_engine_from_settings(DatabaseSettings(url='YOUR_DB_URI')); \
session = create_session_maker(engine)(); \
count = session.query(func.count(IPInventory.ip_address)).scalar(); \
print(f'Enriched IPs in inventory: {count:,}')"

# 4. Check database schema version
uv run cowrie-db check --verbose
```

## Execution Phases

### Phase 1: Dry-Run Validation

**Purpose**: Validate script logic and database connectivity without making changes.

**Command**:
```bash
uv run python scripts/migrations/backfill_session_snapshots.py \
    --db "postgresql://user:pass@host:port/database" \
    --batch-size 1000 \
    --dry-run \
    --progress
```

**Expected Output**:
```
2025-11-06 12:00:00 [    INFO] __main__: Connected to database: cowrie_prod (postgresql)
2025-11-06 12:00:01 [    INFO] __main__: Found 1,680,000 sessions needing snapshot backfill
2025-11-06 12:00:01 [    INFO] __main__: DRY RUN MODE - no changes will be made
2025-11-06 12:00:05 [    INFO] __main__: DRY RUN - Batch 1: Would update 1000 sessions (987/1000 IPs found in inventory)
...
2025-11-06 12:05:00 [    INFO] __main__: ========================================
2025-11-06 12:05:00 [    INFO] __main__: Backfill complete!
2025-11-06 12:05:00 [    INFO] __main__: Sessions updated: 1,680,000 / 1,680,000
2025-11-06 12:05:00 [    INFO] __main__: Batches processed: 1680
2025-11-06 12:05:00 [    INFO] __main__: Failed batches: 0
2025-11-06 12:05:00 [    INFO] __main__: Total time: 300.0 seconds (5.0 minutes)
2025-11-06 12:05:00 [    INFO] __main__: Average rate: 5600.0 sessions/second
2025-11-06 12:05:00 [    INFO] __main__: ========================================
```

**Validation Criteria**:
- ✅ Connection successful
- ✅ Sessions found > 0
- ✅ IP inventory coverage > 95%
- ✅ No Python exceptions
- ✅ Batch processing rate: 2000-5000 sessions/second
- ✅ Failed batches: 0

### Phase 2: Production Backfill

**Purpose**: Execute backfill on production database with progress tracking and resume capability.

**Preparation**:
1. **Schedule maintenance window** (recommended but not required - no table locks)
2. **Create database backup** (optional for rollback capability)
3. **Clear checkpoint file** if starting fresh:
   ```bash
   rm -f /tmp/snapshot_backfill.json
   ```

**Command**:
```bash
# Production execution with progress tracking
uv run python scripts/migrations/backfill_session_snapshots.py \
    --db "postgresql://user:pass@host:port/database" \
    --batch-size 1000 \
    --status-dir /mnt/dshield/data/logs/status \
    --progress \
    --checkpoint-file /mnt/dshield/data/logs/status/snapshot_backfill.json \
    2>&1 | tee /mnt/dshield/data/logs/snapshot_backfill_$(date +%Y%m%d_%H%M%S).log
```

**Command Breakdown**:
- `--db`: Database connection string
- `--batch-size 1000`: Process 1000 sessions per batch (tune based on database performance)
- `--status-dir`: Enable StatusEmitter for real-time monitoring
- `--progress`: Log progress updates every 10 batches
- `--checkpoint-file`: Enable resume capability
- `tee`: Write logs to file while displaying to console

**Expected Timeline** (1.68M sessions):
- **Batch processing rate**: 2000-5000 sessions/second
- **Total time**: 60-90 minutes
- **Peak memory**: <500MB
- **Database load**: Moderate (read-heavy with periodic write bursts)

**Monitoring**:
```bash
# Real-time progress monitoring (separate terminal)
watch -n 5 'cat /mnt/dshield/data/logs/status/snapshot_backfill.json | python -m json.tool'

# Alternative: Monitor via log file
tail -f /mnt/dshield/data/logs/snapshot_backfill_*.log

# Database query progress (separate terminal)
uv run python -c "from cowrieprocessor.db import create_engine_from_settings, create_session_maker; \
from cowrieprocessor.db.models import SessionSummary; \
from cowrieprocessor.settings import DatabaseSettings; \
from sqlalchemy import func; \
engine = create_engine_from_settings(DatabaseSettings(url='YOUR_DB_URI')); \
session = create_session_maker(engine)(); \
total = session.query(func.count(SessionSummary.session_id)).scalar(); \
remaining = session.query(func.count(SessionSummary.session_id)).filter(SessionSummary.source_ip.is_(None)).scalar(); \
filled = total - remaining; \
percent = (filled / total * 100) if total > 0 else 0; \
print(f'Progress: {filled:,}/{total:,} ({percent:.1f}%) | Remaining: {remaining:,}')"
```

### Phase 3: Resume After Interruption

**Purpose**: Resume backfill if interrupted (network issue, kill signal, etc.).

**Detection**:
- Checkpoint file exists: `/mnt/dshield/data/logs/status/snapshot_backfill.json`
- Log file shows incomplete execution
- Database query shows sessions still missing snapshots

**Command**:
```bash
uv run python scripts/migrations/backfill_session_snapshots.py \
    --db "postgresql://user:pass@host:port/database" \
    --batch-size 1000 \
    --resume \
    --checkpoint-file /mnt/dshield/data/logs/status/snapshot_backfill.json \
    --status-dir /mnt/dshield/data/logs/status \
    --progress \
    2>&1 | tee -a /mnt/dshield/data/logs/snapshot_backfill_resume_$(date +%Y%m%d_%H%M%S).log
```

**Resume Behavior**:
- Loads checkpoint state (last batch, total updated)
- Continues from next incomplete batch
- Accumulates total_updated count
- Preserves started_at timestamp

## Performance Tuning

### Batch Size Optimization

**Default**: 1000 sessions/batch

**Tuning Guidelines**:
- **Small databases (<100K sessions)**: `--batch-size 500`
- **Medium databases (100K-1M sessions)**: `--batch-size 1000` (default)
- **Large databases (>1M sessions)**: `--batch-size 2000`
- **Slow network/disk**: Reduce to `--batch-size 500`
- **Fast SSD/local DB**: Increase to `--batch-size 5000`

**Monitoring Metrics**:
- **Batch processing time**: 2-3 seconds per batch (target)
- **Sessions/second**: 2000-5000 (target)
- **Database CPU**: <50% (sustainable)
- **Memory usage**: <500MB (stable)

**Adjustments**:
```bash
# If batch processing > 5 seconds:
--batch-size 500

# If batch processing < 1 second:
--batch-size 2000
```

### Database-Specific Optimizations

**PostgreSQL**:
```sql
-- Disable autovacuum during migration (optional)
ALTER TABLE session_summaries SET (autovacuum_enabled = false);

-- Re-enable after migration
ALTER TABLE session_summaries SET (autovacuum_enabled = true);

-- Analyze table after completion
ANALYZE session_summaries;
```

**SQLite**:
```sql
-- Disable synchronous writes during migration (optional, risky)
PRAGMA synchronous = OFF;

-- Re-enable after migration
PRAGMA synchronous = FULL;

-- Optimize after completion
PRAGMA optimize;
```

## Validation

### Post-Migration Verification

**Step 1: Count sessions with snapshots**
```bash
uv run python -c "from cowrieprocessor.db import create_engine_from_settings, create_session_maker; \
from cowrieprocessor.db.models import SessionSummary; \
from cowrieprocessor.settings import DatabaseSettings; \
from sqlalchemy import func; \
engine = create_engine_from_settings(DatabaseSettings(url='YOUR_DB_URI')); \
session = create_session_maker(engine)(); \
total = session.query(func.count(SessionSummary.session_id)).scalar(); \
filled = session.query(func.count(SessionSummary.session_id)).filter(SessionSummary.source_ip.isnot(None)).scalar(); \
percent = (filled / total * 100) if total > 0 else 0; \
print(f'Snapshot coverage: {filled:,}/{total:,} ({percent:.1f}%)')"
```

**Expected**: >95% coverage (some sessions may have no IP inventory match)

**Step 2: Sample snapshot data quality**
```sql
-- PostgreSQL
SELECT
    session_id,
    source_ip,
    snapshot_asn,
    snapshot_country,
    snapshot_ip_type,
    enrichment_at
FROM session_summaries
WHERE source_ip IS NOT NULL
LIMIT 10;
```

**Expected**: All snapshot columns populated, no NULL values for matched IPs

**Step 3: Verify temporal accuracy**
```sql
-- Check snapshot vs current IP state divergence
SELECT
    ss.session_id,
    ss.source_ip,
    ss.snapshot_asn AS snapshot_asn,
    ip.current_asn AS current_asn,
    ss.snapshot_country AS snapshot_country,
    ip.geo_country AS current_country,
    ss.first_event_at
FROM session_summaries ss
JOIN ip_inventory ip ON ss.source_ip = ip.ip_address
WHERE ss.snapshot_asn != ip.current_asn
LIMIT 10;
```

**Expected**: Some divergence (IPs move between ASNs), snapshots preserve historical state

**Step 4: Performance validation**
```sql
-- Test query performance WITHOUT JOIN (using snapshots)
EXPLAIN ANALYZE
SELECT session_id, snapshot_country, snapshot_asn
FROM session_summaries
WHERE snapshot_country = 'CN' AND snapshot_asn = 4134;
```

**Expected**: Index-only scan, <100ms for 1M+ sessions

## Rollback Procedures

### Scenario 1: Data Corruption Detected

**Symptoms**:
- Incorrect snapshot values
- NULL snapshots for IPs in inventory
- ASN/country mismatch with enrichment JSON

**Action**:
```sql
-- Clear snapshot columns
UPDATE session_summaries
SET
    source_ip = NULL,
    snapshot_asn = NULL,
    snapshot_country = NULL,
    snapshot_ip_type = NULL,
    enrichment_at = NULL
WHERE source_ip IS NOT NULL;

-- Verify rollback
SELECT COUNT(*) FROM session_summaries WHERE source_ip IS NOT NULL;
-- Expected: 0
```

**Recovery**: Re-run backfill script after identifying root cause

### Scenario 2: Database Backup Restore

**Only if database backup taken before migration**:
```bash
# PostgreSQL
pg_restore -d cowrie_prod /backups/cowrie_pre_snapshot_backfill.dump

# SQLite
cp /backups/cowrie_pre_snapshot_backfill.sqlite /path/to/cowrie.sqlite
```

## Troubleshooting

### Issue: Script hangs on batch

**Symptoms**:
- No progress updates for >60 seconds
- Checkpoint file not updating
- Database process shows long-running query

**Diagnosis**:
```bash
# Check database locks (PostgreSQL)
SELECT * FROM pg_stat_activity WHERE state = 'active';
```

**Resolution**:
1. Kill script (Ctrl+C)
2. Reduce `--batch-size` to 500
3. Resume with `--resume` flag

### Issue: Failed batches

**Symptoms**:
- Log shows "Error processing batch N"
- Failed batches count > 0

**Diagnosis**:
- Check log file for exception details
- Common causes: database connection timeout, transaction deadlock, corrupted enrichment JSON

**Resolution**:
1. Review error log for specific batch number
2. Manually inspect problematic sessions:
   ```sql
   SELECT * FROM session_summaries
   WHERE session_id IN (
       SELECT session_id FROM session_summaries
       WHERE source_ip IS NULL
       ORDER BY session_id
       LIMIT 1000 OFFSET (N-1)*1000  -- Replace N with failed batch number
   );
   ```
3. Fix data issue or skip batch manually
4. Resume backfill

### Issue: Low processing rate

**Symptoms**:
- Sessions/second < 500
- Batch processing time > 10 seconds

**Diagnosis**:
```bash
# Check database performance
# PostgreSQL: pg_stat_statements
# SQLite: PRAGMA stats
```

**Resolution**:
1. **Reduce batch size**: `--batch-size 500`
2. **Check database load**: Other processes contending?
3. **Network latency**: Move script closer to database
4. **Disable logging**: Remove `--progress` flag

## Success Criteria

**Migration considered successful when**:
- ✅ Snapshot coverage ≥ 95% (some sessions may lack IP inventory match)
- ✅ No failed batches
- ✅ Checkpoint file shows 100% completion
- ✅ Sample validation queries return expected data
- ✅ Query performance improved (index-only scans work)
- ✅ No data corruption detected
- ✅ Total execution time < 120 minutes

## Post-Migration Cleanup

```bash
# Remove checkpoint file after successful completion
rm /tmp/snapshot_backfill.json
rm /mnt/dshield/data/logs/status/snapshot_backfill.json

# Archive log files
mkdir -p /mnt/dshield/data/logs/archive/
mv /mnt/dshield/data/logs/snapshot_backfill_*.log /mnt/dshield/data/logs/archive/

# Update documentation
# Record final statistics: total sessions, coverage percentage, execution time
```

## Contacts

**Script Author**: ADR-007 Implementation Team
**Reference**: `docs/designs/adr007-snapshot-population-fix.md`
**Support**: Cowrie Processor GitHub Issues
