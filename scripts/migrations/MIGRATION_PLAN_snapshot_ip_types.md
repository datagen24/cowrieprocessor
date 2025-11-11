# Migration Plan: Fix snapshot_ip_types Schema Mismatch

**Migration ID**: fix_snapshot_ip_types_schema
**Created**: 2025-11-07
**Target Schema**: v16 (fix existing deployment)
**Database**: PostgreSQL 17.6 @ 10.130.30.89:5432
**Dataset Size**: 1,682,827 sessions

## Problem Statement

**Root Cause**: Original ADR-007 migration (commit dca6f82) created column with wrong name and type:
- **Production DB**: `snapshot_ip_types TEXT[]` (array, plural)
- **All Code**: Expects `snapshot_ip_type TEXT` (scalar, singular)

**Impact**:
- 29 files reference `snapshot_ip_type` column
- All snapshot operations fail with "column does not exist" error
- 0% data coverage (all values NULL) - no data loss risk

**Discovery**: Phase 3 production validation testing

## Migration Strategy

### Approach
Two-step schema fix:
1. **Type Conversion**: `TEXT[]` array → `TEXT` scalar (extract first element)
2. **Column Rename**: `snapshot_ip_types` → `snapshot_ip_type`

### Safety Guarantees
- ✅ **No Data Loss**: 0% coverage (all NULL) means safe conversion
- ✅ **Instant Execution**: Column rename is metadata-only operation
- ✅ **Rollback Ready**: Simple reverse operations documented
- ✅ **Transaction Safety**: All changes in single transaction with rollback on error
- ✅ **Dry-Run Validation**: Test before execution

## Pre-Migration Checklist

### 1. Database Backup
```bash
# Create backup before migration
pg_dump -h 10.130.30.89 -U cowrieprocessor -d cowrieprocessor \
    -t session_summaries \
    --schema-only > backup_session_summaries_schema_$(date +%Y%m%d_%H%M%S).sql

# Or use pg_basebackup for full cluster backup
pg_basebackup -h 10.130.30.89 -U replication_user -D /backup/postgres_$(date +%Y%m%d) -Fp -Xs -P
```

**Recommendation**: Coordinate with database administrator for backup strategy.

### 2. Verify Prerequisites
```bash
# Check current schema version
psql postgresql://cowrieprocessor:***@10.130.30.89:5432/cowrieprocessor -c \
    "SELECT value FROM schema_state WHERE key = 'schema_version';"
# Expected: 16

# Verify column exists with array type
psql postgresql://cowrieprocessor:***@10.130.30.89:5432/cowrieprocessor -c \
    "\d session_summaries" | grep snapshot_ip_types
# Expected: snapshot_ip_types | text[] |

# Count non-NULL values (expect 0)
psql postgresql://cowrieprocessor:***@10.130.30.89:5432/cowrieprocessor -c \
    "SELECT COUNT(*) FROM session_summaries WHERE snapshot_ip_types IS NOT NULL;"
# Expected: 0
```

### 3. Code Readiness
```bash
# Rebuild package with fixed migrations.py
cd /Users/speterson/src/dshield/cowrieprocessor
uv sync

# Verify import works
uv run python -c "from cowrieprocessor.db.migrations import _migrate_to_v16; print('OK')"
```

### 4. Maintenance Window (Optional)
**Recommendation**: Run during low-traffic period
- **Estimated Duration**: < 5 minutes
- **Downtime Required**: No (schema change is instant)
- **Risk Level**: LOW (reversible, no data modification)

## Execution Steps

### Step 1: Dry-Run Validation (5 minutes)
```bash
# Test migration logic without applying changes
uv run python scripts/migrations/fix_snapshot_ip_types_schema.py \
    --config config/sensors.toml \
    --sensor production \
    --dry-run

# Expected output:
# ✅ Precondition validation successful
# [DRY RUN] Would execute type conversion
# [DRY RUN] Would execute column rename
# ✅ DRY RUN COMPLETED SUCCESSFULLY
```

**Decision Gate**: Proceed only if dry-run succeeds without errors.

### Step 2: Execute Migration (2 minutes)
```bash
# Execute actual migration with auto-confirmation
uv run python scripts/migrations/fix_snapshot_ip_types_schema.py \
    --config config/sensors.toml \
    --sensor production \
    --confirm

# Expected output:
# ✅ Precondition validation successful
# ✅ Column type converted from TEXT[] to TEXT
# ✅ Column renamed to 'snapshot_ip_type'
# ✅ Postcondition validation successful
# ✅ MIGRATION COMPLETED SUCCESSFULLY
```

**Monitoring**: Watch for errors in log output. Migration will auto-rollback on failure.

### Step 3: Validation Testing (10 minutes)
```bash
# Run production validation tests
uv run pytest tests/validation/test_production_validation.py -v

# Expected: 9/9 tests pass (including schema validation)

# Test ORM query compatibility
psql postgresql://cowrieprocessor:***@10.130.30.89:5432/cowrieprocessor -c \
    "SELECT snapshot_ip_type FROM session_summaries LIMIT 5;"
# Expected: 5 rows with NULL values (no error)

# Verify old column removed
psql postgresql://cowrieprocessor:***@10.130.90.89:5432/cowrieprocessor -c \
    "\d session_summaries" | grep snapshot_ip_types
# Expected: (no output - column should not exist)
```

### Step 4: Application Restart (5 minutes)
```bash
# Restart any services using the database
# (adjust for your deployment)
systemctl restart cowrie-enrichment
systemctl restart cowrie-loader

# Monitor logs for schema-related errors
journalctl -u cowrie-enrichment -f --since "5 minutes ago" | grep -i snapshot
# Expected: no "column does not exist" errors
```

## Success Criteria

### Schema Validation
- ✅ Column `snapshot_ip_type` exists with type `TEXT` (not array)
- ✅ Column `snapshot_ip_types` does not exist
- ✅ All values remain NULL (no data loss)
- ✅ Query `SELECT snapshot_ip_type FROM session_summaries LIMIT 1` succeeds

### Application Validation
- ✅ ORM models can read/write to `snapshot_ip_type` column
- ✅ No "column does not exist" errors in application logs
- ✅ Validation tests pass (9/9)
- ✅ Enrichment workflows can update snapshot columns

### Performance Validation
- ✅ Migration completes in < 5 minutes
- ✅ No table locks or blocking queries
- ✅ No impact on concurrent read/write operations

## Rollback Procedure

**If Migration Fails or Needs Reversal:**

### Option 1: Automated Rollback (Preferred)
Migration script automatically rolls back on error within transaction.
No manual intervention needed if migration fails.

### Option 2: Manual Rollback
```sql
-- Step 1: Rename column back to plural
ALTER TABLE session_summaries
    RENAME COLUMN snapshot_ip_type TO snapshot_ip_types;

-- Step 2: Convert scalar type back to array
ALTER TABLE session_summaries
    ALTER COLUMN snapshot_ip_types TYPE TEXT[]
    USING CASE WHEN snapshot_ip_types IS NULL THEN NULL ELSE ARRAY[snapshot_ip_types] END;

-- Step 3: Verify rollback
\d session_summaries
-- Expected: snapshot_ip_types | text[] |
```

### Option 3: Restore from Backup
```bash
# Restore schema from backup
psql postgresql://cowrieprocessor:***@10.130.30.89:5432/cowrieprocessor \
    < backup_session_summaries_schema_YYYYMMDD_HHMMSS.sql
```

## Post-Migration Tasks

### 1. Update Documentation
- [x] Fix `migrations.py` source bug (commit: this PR)
- [ ] Update `data_dictionary.md` with correct column name
- [ ] Update ADR-007 with lessons learned
- [ ] Create memory file for migration debugging experience

### 2. Monitor Production
```bash
# Monitor for 24 hours after migration
watch -n 60 'psql postgresql://cowrieprocessor:***@10.130.30.89:5432/cowrieprocessor \
    -c "SELECT COUNT(*) as total, COUNT(snapshot_ip_type) as enriched FROM session_summaries"'

# Check application logs for errors
journalctl -u cowrie-* --since "1 hour ago" | grep -i "snapshot\|schema\|column"
```

### 3. Enable Enrichment (Future)
Once migration is validated, enable IP type enrichment:
```bash
# This will populate snapshot_ip_type with values like 'RESIDENTIAL', 'DATACENTER', etc.
uv run cowrie-enrich refresh --ips 1000 --verbose
```

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Migration fails | LOW | LOW | Automatic rollback in transaction |
| Data loss | NONE | N/A | 0% coverage (all NULL) |
| Downtime | NONE | N/A | Instant metadata-only operation |
| Application errors | LOW | MEDIUM | Validation tests before production use |
| Performance degradation | NONE | N/A | No indexes changed, no data modified |

**Overall Risk Level**: **LOW** - Safe operation with strong safeguards

## Timeline

| Phase | Duration | Status |
|-------|----------|--------|
| Pre-migration checks | 10 min | ⏳ Pending |
| Dry-run validation | 5 min | ⏳ Pending |
| Execute migration | 2 min | ⏳ Pending |
| Post-migration validation | 10 min | ⏳ Pending |
| Application restart | 5 min | ⏳ Pending |
| **Total Estimated Time** | **32 min** | |

**Recommended Execution Window**: Any time (no downtime required)

## Lessons Learned

### Root Cause Analysis
**Why did this happen?**
1. Migration created `snapshot_ip_types` (plural, array)
2. ORM model defined `snapshot_ip_type` (singular, scalar)
3. No validation test caught the mismatch until Phase 3 validation

**Prevention for Future:**
1. ✅ Add schema validation tests that compare ORM models to actual database schema
2. ✅ Require `test_production_validation.py` to pass before declaring schema migration complete
3. ✅ Add type checking for column definitions (array vs scalar)
4. ✅ Create migration test that validates ORM can query all new columns

### Key Takeaways
- **Always validate ORM-migration alignment** before deploying schema changes
- **0% coverage = safe migration** - perfect time to fix schema issues
- **Production validation tests are critical** - caught issue before data was enriched
- **Document rollback procedures upfront** - reduces stress during execution

## References

- **Migration Script**: `scripts/migrations/fix_snapshot_ip_types_schema.py`
- **Fixed Source**: `cowrieprocessor/db/migrations.py` (lines 2363, 2416)
- **ORM Model**: `cowrieprocessor/db/models.py` (line 216)
- **Validation Tests**: `tests/validation/test_production_validation.py`
- **Original ADR**: `docs/adr/ADR-007-ip-enrichment-three-tier-architecture.md`
- **Cleanup Script**: `scripts/migrations/cleanup_v16_incomplete.sql` (line 44)

## Approval Checklist

- [ ] Database backup created
- [ ] Dry-run validation successful
- [ ] Stakeholders notified (if applicable)
- [ ] Monitoring dashboard ready
- [ ] Rollback procedure tested
- [ ] Post-migration validation tests ready
- [ ] Migration window scheduled (optional)

**Approved By**: _________________
**Executed By**: _________________
**Execution Date**: _________________
**Completion Time**: _________________
**Validation Status**: _________________
