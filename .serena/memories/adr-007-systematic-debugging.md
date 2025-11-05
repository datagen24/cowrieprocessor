# ADR-007 Systematic Debugging Session

**Date**: 2025-11-05
**Branch**: feature/adr-007-three-tier-enrichment
**Status**: In progress - iterative bug fixing

## Issues Found and Fixed (In Order)

### Issue 1: Phase Ordering Bug (Commit 5e37ed8)
**Error**: `column "source_ip" does not exist`
**Cause**: Phases 1 & 2 tried to use source_ip before Phase 3 created it
**Fix**: Reordered phases - add source_ip first (new Phase 1)

### Issue 2: Schema State Table Name (Commit 0d8ec9e)
**Error**: `column "key" does not exist` in cleanup script
**Cause**: Cleanup script used wrong table name (schema_metadata vs schema_state)
**Fix**: Updated all references to use schema_state table

### Issue 3: Incomplete Table Persistence (Commit 8bf3a02)
**Error**: Migration detects incomplete table but requires manual cleanup
**Cause**: Previous migration created ip_inventory but failed before adding GENERATED columns
**Fix**: Auto-repair - migration now drops and recreates incomplete tables

### Issue 4: GENERATED Column Subquery (Commit 971bf5e)
**Error**: `cannot use subquery in column generation expression`
**Cause**: ip_types used ARRAY(SELECT ...) which isn't allowed in GENERATED columns
**Fix**: Changed ip_types from GENERATED to regular column with DEFAULT

### Issue 5: VARCHAR to INET Type Mismatch (Commit 26f80f0)
**Error**: `column "ip_address" is of type inet but expression is of type character varying`
**Cause**: session_summaries.source_ip is VARCHAR(45), ip_inventory.ip_address is INET
**Fix**: Cast source_ip to inet in INSERT: `source_ip::inet`

## Pattern Recognition

**Root Cause Analysis**:
All issues stem from:
1. Incomplete testing on actual database (schema differences)
2. PostgreSQL limitations not caught in initial design
3. Failed migrations leaving partial state

**Systematic Approach**:
1. User reports error with full stack trace
2. I identify root cause from error message
3. Apply targeted fix and commit
4. User tests, reports next error
5. Repeat until migration completes

**Why So Many Issues?**:
- Original migration (Phase 1) wasn't tested on actual database
- Each fix revealed next issue (cascading errors)
- Transaction rollback on first error hid subsequent issues

## Current Status

**Fixed (7 commits)**:
- ✅ Phase ordering
- ✅ Schema state table name
- ✅ Incomplete table handling
- ✅ GENERATED column limitations
- ✅ Type casting

**Pending**:
- ⏳ User testing commit 26f80f0 (inet cast fix)
- ⏳ Validation of complete 5-phase migration

## Lessons Learned

1. **Test migrations on actual database schema**: Don't assume column types/names
2. **PostgreSQL GENERATED limitations**: No subqueries, no set-returning functions
3. **Type compatibility**: Always check column types when inserting across tables
4. **Incremental validation**: Test each phase independently when possible
5. **Auto-recovery**: Self-healing migrations are more robust than manual cleanup

## Next Steps

1. User runs: `uv run cowrie-db migrate`
2. If successful: Validate 5 phases completed
3. If error: Debug and fix next issue
4. Once complete: Update tests and PDCA documentation
