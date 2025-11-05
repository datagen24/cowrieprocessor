# ADR-007 Migration Recovery Work

**Date**: 2025-11-05
**Branch**: feature/adr-007-three-tier-enrichment
**Commits**: 5e37ed8, c62a233, 9f93548

## Second Migration Error (Incomplete Schema)

After fixing the phase ordering bug, user encountered a second error:

```
Failed to execute SQL: Create idx_ip_geo_country index - 
(psycopg.errors.UndefinedColumn) column "geo_country" does not exist
```

**Root Cause**: 
- First migration attempt created ip_inventory table but failed before completing schema
- Table exists but missing GENERATED columns (geo_country, ip_types, is_scanner, is_bogon)
- Second migration attempt skipped CREATE TABLE (table exists) but tried to create indexes on missing columns
- Transaction closed after first error, causing cascade of "closed transaction" errors

**GENERATED Column Issue**:
PostgreSQL GENERATED columns can't be added with ALTER TABLE ADD COLUMN. They must be defined during CREATE TABLE. This means:
- Can't incrementally add GENERATED columns to existing table
- Must drop and recreate table to add GENERATED columns
- Migration can't self-heal from incomplete schema

## Solutions Implemented

### 1. Schema Validation (Commit c62a233)

Added defensive checks to detect incomplete schema early:

**Early Detection**:
```python
# In Phase 3 (ip_inventory creation)
if table exists but geo_country column missing:
    logger.error("Incomplete schema - drop and recreate")
    raise Exception("Incomplete ip_inventory schema detected")
```

**Index Creation Guards**:
```python
# Before creating indexes, check if column exists
for index_name, index_def, column_name in indexes:
    if _column_exists(connection, table, column_name):
        create_index()
    else:
        logger.warning("Skipping index - column missing")
```

**Benefits**:
- Fails fast with clear error message
- Prevents cascade of transaction errors
- Guides user to recovery procedure

### 2. Automated Cleanup Script (Commit 9f93548)

**File**: `scripts/migrations/cleanup_v16_incomplete.sql`

**What it does**:
1. Drops ip_asn_history, ip_inventory, asn_inventory tables (CASCADE)
2. Removes source_ip column from session_summaries
3. Removes snapshot columns (enrichment_at, snapshot_asn, etc.)
4. Drops related indexes
5. Resets schema_metadata to v15

**Usage**:
```bash
psql $DATABASE_URL -f scripts/migrations/cleanup_v16_incomplete.sql
uv run cowrie-db migrate
```

**Data Safety**:
- Non-destructive to session_summaries data
- Enrichment JSONB preserved
- All tables reconstructed from existing data (replayable migration)

### 3. Recovery Documentation (Commit 9f93548)

**File**: `claudedocs/ADR-007-MIGRATION-RECOVERY.md`

**Contents**:
- Quick automated recovery (cleanup script)
- Manual step-by-step recovery procedures
- Troubleshooting common issues
- Data safety guarantees
- Testing validation steps
- Clear error explanations

## Technical Learnings

### GENERATED Column Constraints

**Problem**: Can't add GENERATED columns after CREATE TABLE
**PostgreSQL Behavior**:
```sql
-- This works
CREATE TABLE foo (
    x INT,
    y INT GENERATED ALWAYS AS (x * 2) STORED
);

-- This does NOT work
ALTER TABLE foo ADD COLUMN y INT GENERATED ALWAYS AS (x * 2) STORED;
-- Error: Cannot add GENERATED column to existing table
```

**Implications for Migrations**:
- Must create table with complete schema on first attempt
- Can't incrementally add GENERATED columns
- Failed migrations require drop/recreate, not ALTER TABLE fix

### Migration Idempotency Challenges

**Standard Pattern**:
```python
if not table_exists(table):
    create_table(schema)
# Assumption: if table exists, schema is complete
```

**Problem**: Doesn't handle partial migrations where table exists with incomplete schema

**Better Pattern**:
```python
if not table_exists(table):
    create_table(schema)
else:
    validate_schema_completeness()
    if incomplete:
        raise_error_with_recovery_instructions()
```

## Current Status

✅ **Completed**:
- Phase ordering bug fixed (source_ip before inventory population)
- Schema validation added (detect incomplete tables)
- Cleanup script created (automated recovery)
- Recovery guide written (comprehensive troubleshooting)

⏳ **Pending User Action**:
- Run cleanup script: `psql $DATABASE_URL -f scripts/migrations/cleanup_v16_incomplete.sql`
- Re-run migration: `uv run cowrie-db migrate`
- Validate success

## Next Steps After Successful Migration

1. Validate checkpoint criteria:
   - >90% IP coverage (country + ASN)
   - >75% API reduction
   - Zero data loss
   - Query performance <10 sec

2. Run integration tests:
   ```bash
   uv run pytest tests/integration/test_three_tier_enrichment_workflow.py
   ```

3. Update PDCA documentation with troubleshooting learnings

4. Proceed to staging validation (production-scale testing)

## Files Changed

**Migration Code** (c62a233):
- cowrieprocessor/db/migrations.py (+44, -17)

**Recovery Resources** (9f93548):
- scripts/migrations/cleanup_v16_incomplete.sql (NEW, 67 lines)
- claudedocs/ADR-007-MIGRATION-RECOVERY.md (NEW, 292 lines)

## Prevention for Future Migrations

1. **Test with partial failures**: Simulate failures at each phase
2. **Schema version granularity**: Track sub-phases for partial rollback
3. **Validation checkpoints**: Verify schema completeness at each phase
4. **Automated cleanup**: Provide recovery scripts with every migration
5. **Documentation first**: Write recovery guide before production deployment
