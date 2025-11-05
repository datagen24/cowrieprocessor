# ADR-007 Migration Recovery Guide

**Date**: 2025-11-05
**Branch**: feature/adr-007-three-tier-enrichment
**Status**: ✅ **RESOLVED** - Migration successful after 12 iterations

## Problem Description

The v16 migration (ADR-007 three-tier enrichment) initially failed with type mismatch errors between ORM models and migration SQL. This guide documents the debugging process and recovery procedures.

### Common Error Patterns

**Type Mismatch Errors**:
```
(psycopg.errors.DatatypeMismatch) foreign key constraint "fk_session_source_ip" cannot be implemented
DETAIL: Key columns "source_ip" and "ip_address" are of incompatible types: character varying and inet.

(psycopg.errors.UndefinedFunction) operator does not exist: inet = character varying
HINT: No operator matches the given name and argument types. You might need to add explicit type casts.
```

**Incomplete Schema Errors**:
```
Failed to execute SQL: Create idx_ip_geo_country index -
(psycopg.errors.UndefinedColumn) column "geo_country" does not exist

Can't operate on closed transaction inside context manager
```

### Root Causes (Resolved in Commit f7f2b68)

**Primary Issue**: ORM-Migration Type Mismatch
- ORM models defined `ip_address` as `Column(String(45))` (VARCHAR)
- Migration originally created `ip_address` as `INET` type
- PostgreSQL cannot create foreign keys between incompatible types (VARCHAR ≠ INET)
- **Fix**: Changed migration to use `VARCHAR(45)` matching ORM models

**Secondary Issue**: Failed migrations leave incomplete tables
- Partial migrations create tables without GENERATED columns
- Subsequent runs skip table creation but try to use missing columns
- **Fix**: Added auto-healing logic to detect and recreate incomplete tables

## Quick Recovery (Automated)

Use the provided cleanup script to reset to v15 schema:

```bash
# Option 1: Using psql directly
psql $DATABASE_URL -f scripts/migrations/cleanup_v16_incomplete.sql

# Option 2: With explicit connection parameters
psql -h hostname -U username -d database -f scripts/migrations/cleanup_v16_incomplete.sql

# Option 3: Single-line manual cleanup (if script fails)
psql -h hostname -U username -d database -c "
DROP TABLE IF EXISTS ip_asn_history CASCADE;
DROP TABLE IF EXISTS ip_inventory CASCADE;
DROP TABLE IF EXISTS asn_inventory CASCADE;
ALTER TABLE session_summaries DROP COLUMN IF EXISTS source_ip CASCADE;
UPDATE schema_state SET value = '15' WHERE key = 'schema_version';
SELECT 'Cleanup complete. Schema version: ' || value FROM schema_state WHERE key = 'schema_version';
"
```

**What the script does**:
1. ✅ Drops ip_asn_history, ip_inventory, asn_inventory tables (CASCADE)
2. ✅ Removes source_ip column from session_summaries
3. ✅ Removes snapshot columns (enrichment_at, snapshot_asn, etc.)
4. ✅ Drops related indexes
5. ✅ Resets schema_metadata to v15

**After cleanup**, re-run migration:
```bash
uv run cowrie-db migrate
```

## Manual Recovery (Step-by-Step)

If you prefer manual cleanup or the script fails:

### 1. Connect to Database
```bash
psql $DATABASE_URL
```

### 2. Check Current State
```sql
-- Check schema version (uses schema_state table)
SELECT * FROM schema_state WHERE key = 'schema_version';

-- Check if problematic tables exist
\dt asn_inventory ip_inventory ip_asn_history

-- Check if source_ip column exists
\d session_summaries
```

### 3. Drop Incomplete Tables
```sql
DROP TABLE IF EXISTS ip_asn_history CASCADE;
DROP TABLE IF EXISTS ip_inventory CASCADE;
DROP TABLE IF EXISTS asn_inventory CASCADE;
```

### 4. Remove Partial Columns (if added)
```sql
-- Remove source_ip if it was added in Phase 1
ALTER TABLE session_summaries DROP COLUMN IF EXISTS source_ip;

-- Remove snapshot columns if they were added in Phase 4
ALTER TABLE session_summaries DROP COLUMN IF EXISTS enrichment_at;
ALTER TABLE session_summaries DROP COLUMN IF EXISTS snapshot_asn;
ALTER TABLE session_summaries DROP COLUMN IF EXISTS snapshot_country;
ALTER TABLE session_summaries DROP COLUMN IF EXISTS snapshot_ip_types;
```

### 5. Drop Orphaned Indexes
```sql
DROP INDEX IF EXISTS idx_session_source_ip;
DROP INDEX IF EXISTS idx_session_first_event_brin;
DROP INDEX IF EXISTS idx_session_last_event_brin;
DROP INDEX IF EXISTS idx_session_snapshot_asn;
DROP INDEX IF EXISTS idx_session_snapshot_country;
```

### 6. Reset Schema Version
```sql
-- Note: Uses schema_state table (not schema_metadata)
UPDATE schema_state SET value = '15' WHERE key = 'schema_version';
```

### 7. Verify Clean State
```sql
-- Should return v15
SELECT value FROM schema_state WHERE key = 'schema_version';

-- Should show no ADR-007 tables
\dt asn_inventory ip_inventory ip_asn_history

-- Should show original session_summaries structure (no source_ip)
\d session_summaries
```

### 8. Exit and Re-run Migration
```bash
\q
uv run cowrie-db migrate
```

## Expected Migration Output (Success)

After cleanup, migration should show:

```
Phase 1: Adding source_ip column to session_summaries...
Populating source_ip from enrichment data...
Create index on source_ip

Phase 2: Creating ASN inventory table...
Created asn_inventory table successfully
Create idx_asn_org_name index
Populating ASN inventory from existing session data...

Phase 3: Creating IP inventory table...
Created ip_inventory table successfully
Create idx_ip_geo_country index
Populating IP inventory from existing session data...

Phase 4: Adding remaining snapshot columns to session_summaries...
Backfilling snapshot columns (this may take a while)...

Phase 5: Adding foreign key constraints...
Pre-validate foreign key integrity
Add ip_inventory → asn_inventory FK (NOT VALID)
Add session_summaries → ip_inventory FK (NOT VALID)
```

## Prevention (For Future Migrations)

The migration now includes defensive checks:

1. **Schema Validation**: Detects incomplete ip_inventory table (missing geo_country)
2. **Column Existence Checks**: Skips index creation if columns don't exist
3. **Clear Error Messages**: Tells you exactly what to drop and why

If you see this error:
```
Incomplete ip_inventory schema detected. Drop table and re-run migration.
```

It means the table exists but is missing GENERATED columns. Follow the recovery steps above.

## Troubleshooting Common Issues

### Issue: "relation ip_inventory does not exist"
**Cause**: Table was successfully dropped
**Solution**: This is expected. Re-run `uv run cowrie-db migrate`

### Issue: "cannot drop table because other objects depend on it"
**Cause**: Foreign keys from session_summaries reference ip_inventory
**Solution**: Use `CASCADE` in DROP statement (included in cleanup script)

### Issue: "schema version is still v16 after cleanup"
**Cause**: Schema version wasn't reset
**Solution**: Manually update:
```sql
-- Note: Uses schema_state table (not schema_metadata)
UPDATE schema_state SET value = '15' WHERE key = 'schema_version';
```

### Issue: "GENERATED columns can't be added with ALTER TABLE"
**Cause**: PostgreSQL limitation - GENERATED columns must be defined during CREATE TABLE
**Solution**: Must drop and recreate table (can't incrementally add GENERATED columns)

## Data Safety

**Important**: The cleanup script is **NON-DESTRUCTIVE** to your actual honeypot data:

✅ **Safe Operations**:
- Drops asn_inventory (will be repopulated from session_summaries)
- Drops ip_inventory (will be repopulated from session_summaries)
- Removes source_ip column (will be re-extracted from enrichment JSONB)

❌ **No Data Loss**:
- session_summaries table data is NEVER deleted
- Enrichment JSONB data remains intact
- All raw events preserved
- Files table untouched

The migration is designed to be **replayable** - it reconstructs inventory tables from existing session data.

## Testing After Recovery

After successful migration, validate:

```bash
# Check schema version
psql $DATABASE_URL -c "SELECT * FROM schema_state WHERE key = 'schema_version'"
# Should show: 16

# Check table counts
psql $DATABASE_URL -c "SELECT COUNT(*) FROM asn_inventory"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM ip_inventory"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM session_summaries WHERE source_ip IS NOT NULL"

# Validate GENERATED columns work
psql $DATABASE_URL -c "SELECT ip_address, geo_country, ip_types FROM ip_inventory LIMIT 5"
```

## Next Steps After Successful Migration

1. ✅ Validate checkpoint criteria (>90% coverage, >75% API reduction)
2. ✅ Run integration tests: `uv run pytest tests/integration/test_three_tier_enrichment_workflow.py`
3. ✅ Update PDCA documentation with troubleshooting learnings
4. ✅ Proceed to staging validation (production-scale testing)

## Debugging Lessons Learned (12 Iterations, Nov 2025)

### The Problem Pattern

**Symptom**: Type casting errors appearing in migration queries
**Underlying Cause**: Schema type mismatch between ORM models and migration SQL

**Why It Was Hard to Find**:
1. **Deferred Validation**: FK constraints created in Phase 5, but type mismatch was in Phase 3
2. **Misleading Errors**: "operator does not exist: inet = character varying" suggested query fix, not schema fix
3. **Split Information**: Column type defined in migration SQL, but reference type in ORM models (different files)
4. **Iterative Symptom Fixing**: First 10 commits added type casts to queries (treating symptoms, not cause)

### The Root Cause Fix (Commit f7f2b68)

**Before** (broken):
```sql
CREATE TABLE ip_inventory (
    ip_address INET PRIMARY KEY,  -- ❌ Doesn't match ORM Column(String(45))
    ...
)
```

**After** (fixed):
```sql
CREATE TABLE ip_inventory (
    ip_address VARCHAR(45) PRIMARY KEY,  -- ✅ Matches ORM models
    ...
)
```

**Key Insight**: If you need `::inet`, `::integer`, or `::jsonb` casts in migration queries, your column types are wrong. Fix the schema types first, then remove the casts.

### Prevention Checklist for Future Migrations

**Before Writing Migration Code**:
```bash
# 1. Check ORM column types
grep -A 2 "class IPInventory\|class SessionSummary" cowrieprocessor/db/models.py

# 2. Verify type mapping rules
# Column(String(45)) → VARCHAR(45)  NOT INET, NOT TEXT
# Column(Integer) → INTEGER  NOT INT, NOT BIGINT
# Column(JSON) → JSON  NOT JSONB (unless model uses postgresql.JSONB)

# 3. Validate FK type consistency
# Foreign key columns MUST have identical types (VARCHAR = VARCHAR, not VARCHAR = INET)
```

**During Migration Development**:
```bash
# Red flag check: Type casts indicate schema mismatch
grep "::inet\|::integer\|::jsonb" cowrieprocessor/db/migrations.py
# Should return NO results

# After code changes: Always rebuild package
uv sync
```

**After Migration Succeeds**:
```sql
-- Verify created column types match ORM models
SELECT table_name, column_name, data_type, character_maximum_length
FROM information_schema.columns
WHERE table_name IN ('session_summaries', 'ip_inventory', 'asn_inventory')
ORDER BY table_name, ordinal_position;

-- Verify FK type compatibility
SELECT tc.table_name, kcu.column_name, c1.data_type as local_type,
       ccu.table_name AS fk_table, ccu.column_name AS fk_column, c2.data_type as fk_type
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name
JOIN information_schema.columns c1 ON c1.table_name = tc.table_name AND c1.column_name = kcu.column_name
JOIN information_schema.columns c2 ON c2.table_name = ccu.table_name AND c2.column_name = ccu.column_name
WHERE tc.constraint_type = 'FOREIGN KEY';
```

### Commit History (11 Commits)

1. `5e37ed8` - Phase ordering (source_ip before usage)
2. `0d8ec9e` - Table name fix (schema_state not schema_metadata)
3. `8bf3a02` - Auto-heal incomplete tables
4. `971bf5e` - GENERATED column subquery limitation
5. `26f80f0` - ❌ Symptom: VARCHAR→INET cast in INSERT
6. `6fab83d` - Nullable source_ip
7. `d804e67` - ❌ Symptom: JSON vs JSONB function mismatch
8. `ae6f02b` - ❌ Symptom: FK validation query cast + mypy
9. `f7f2b68` - ✅ **ROOT CAUSE FIX: VARCHAR type consistency**

**Time Cost**: ~4 hours, 12 iterations
**Lesson**: Validate ORM-migration type alignment BEFORE writing migration logic (saves hours)

See also: Serena memory `migration_type_mismatch_debugging_adr007` for detailed analysis

## Contact

If recovery fails or you encounter unexpected issues:
- Check git log for recent commits (c62a233, 5e37ed8)
- Review migration code: `cowrieprocessor/db/migrations.py` (_upgrade_to_v16)
- Check unit tests: `tests/unit/test_schema_v16_migration.py`
