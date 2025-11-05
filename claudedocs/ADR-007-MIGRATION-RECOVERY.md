# ADR-007 Migration Recovery Guide

**Date**: 2025-11-05
**Branch**: feature/adr-007-three-tier-enrichment
**Status**: Active troubleshooting

## Problem Description

The v16 migration (ADR-007 three-tier enrichment) can fail partway through, leaving incomplete table schemas. Subsequent migration attempts fail with errors like:

```
Failed to execute SQL: Create idx_ip_geo_country index -
(psycopg.errors.UndefinedColumn) column "geo_country" does not exist

Can't operate on closed transaction inside context manager
```

**Root Cause**: Failed migrations leave tables (asn_inventory, ip_inventory) without GENERATED columns. Subsequent runs skip table creation but try to create indexes on missing columns.

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

## Contact

If recovery fails or you encounter unexpected issues:
- Check git log for recent commits (c62a233, 5e37ed8)
- Review migration code: `cowrieprocessor/db/migrations.py` (_upgrade_to_v16)
- Check unit tests: `tests/unit/test_schema_v16_migration.py`
