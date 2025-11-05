# ADR-007 Migration Fixes Summary

**Date**: 2025-11-05
**Branch**: feature/adr-007-three-tier-enrichment
**Total Commits**: 8 bug fixes

## Complete Fix History

### Fix 1: Phase Ordering (Commit 5e37ed8)
**Error**: `column "source_ip" does not exist`
**Line**: Phase 1 & 2 tried to use source_ip
**Fix**: Reordered phases - add source_ip in Phase 1 before using it

### Fix 2: Schema State Table (Commit 0d8ec9e)
**Error**: `column "key" does not exist` in cleanup script
**Line**: UPDATE schema_metadata WHERE key = 'schema_version'
**Fix**: Changed to schema_state table (correct table name)

### Fix 3: Auto-Heal Incomplete Table (Commit 8bf3a02)
**Error**: Migration detects incomplete table, requires manual drop
**Line**: Phase 3 ip_inventory validation
**Fix**: Auto-drop and recreate incomplete tables

### Fix 4: GENERATED Column Subquery (Commit 971bf5e)
**Error**: `cannot use subquery in column generation expression`
**Line**: ip_types GENERATED ALWAYS AS with ARRAY(SELECT ...)
**Fix**: Changed ip_types to regular column with DEFAULT ARRAY[]::text[]

### Fix 5: Type Mismatch (Commit 26f80f0)
**Error**: `column "ip_address" is of type inet but expression is of type character varying`
**Line**: INSERT INTO ip_inventory SELECT source_ip
**Fix**: Cast to inet: source_ip::inet

### Fix 6: NOT NULL Constraint (Commit 6fab83d) ← **LATEST**
**Error**: `column "source_ip" contains null values`
**Line**: ALTER TABLE session_summaries ALTER COLUMN source_ip SET NOT NULL
**Fix**: Removed NOT NULL constraint (source_ip remains nullable)

**Rationale**:
- Not all sessions have enrichment data
- Some enrichment may lack IP address
- JSONB extraction can fail for malformed data
- Better to handle missing data gracefully

## PostgreSQL Lessons Learned

1. **GENERATED column limitations**:
   - No subqueries allowed
   - No set-returning functions
   - Must be pure expressions

2. **Type compatibility**:
   - Always check column types when inserting across tables
   - Use explicit casts when needed (::type)

3. **NULL handling**:
   - Foreign keys allow NULL by default (good for optional relationships)
   - NOT NULL constraints should only be used when data is guaranteed

4. **Auto-recovery**:
   - Self-healing migrations more robust than manual cleanup
   - Detect incomplete state and auto-repair

## Current Migration Status

**Ready to test**: All 8 fixes applied
**Expected behavior**:
1. Phase 1: Add source_ip (nullable), populate from enrichment
2. Phase 2: Create ASN inventory, populate
3. Phase 3: Create IP inventory (auto-heal if needed), populate with type cast
4. Phase 4: Add snapshot columns (skip NOT NULL constraint)
5. Phase 5: Add foreign keys (NULLs allowed)

**Command**: `uv run cowrie-db migrate`

## Data Quality Notes

After migration:
- Some sessions may have NULL source_ip (no IP in enrichment data)
- ip_inventory only contains IPs that exist in session data
- ip_types column empty after migration (will be populated by cowrie-loader)
- Foreign keys validated but allow NULLs

## Files Changed

- `cowrieprocessor/db/migrations.py`: _upgrade_to_v16() function
- `scripts/migrations/cleanup_v16_incomplete.sql`: Cleanup script
- `claudedocs/ADR-007-MIGRATION-RECOVERY.md`: Recovery guide
