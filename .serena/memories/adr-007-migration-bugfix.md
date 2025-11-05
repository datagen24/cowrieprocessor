# ADR-007 Migration Phase Ordering Bugfix

**Date**: 2025-11-05
**Branch**: feature/adr-007-three-tier-enrichment
**Commit**: 5e37ed8

## Problem Identified

Migration v16 failed with critical error:
```
psycopg.errors.UndefinedColumn: column "source_ip" does not exist
LINE 7: COUNT(DISTINCT source_ip) as unique_ip_count...
```

**Root Cause**: Phase execution order bug in `_upgrade_to_v16()`:
- Phase 1 (ASN inventory population) used `COUNT(DISTINCT source_ip)`
- Phase 2 (IP inventory population) used `SELECT DISTINCT ON (source_ip)`  
- Phase 3 (session snapshots) never added source_ip column to session_summaries
- The column was assumed to exist but was never created

**Discovery**: 
- Current schema v15 has NO source_ip column in session_summaries
- IP stored in enrichment JSONB: `enrichment->'dshield'->'ip'->>'number'`
- Migration tried to reference non-existent column

## Solution Implemented

Reordered migration phases with new Phase 1:

**NEW Phase 1: Session Source IP Column**
- Add source_ip VARCHAR(45) column to session_summaries
- Populate from enrichment JSONB: `enrichment->'dshield'->'ip'->>'number'`
- Create idx_session_source_ip index for JOIN performance

**Phase 2: ASN Inventory** (formerly Phase 1)
- Now uses source_ip added in Phase 1
- COUNT(DISTINCT source_ip) works correctly

**Phase 3: IP Inventory** (formerly Phase 2)
- Now uses source_ip added in Phase 1
- SELECT DISTINCT ON (source_ip) works correctly

**Phase 4: Snapshot Columns** (formerly Phase 3)
- Adds remaining snapshot columns (enrichment_at, snapshot_asn, etc.)
- Removed duplicate idx_session_source_ip from index list

**Phase 5: Foreign Keys** (formerly Phase 4)
- No changes, just renumbered

## Testing Status

✅ **Code Quality**:
- ruff format: passed
- ruff check: passed
- mypy: passed (migrations.py has no errors)
- Python compilation: passed

⏳ **Functional Testing**:
- Ready for `uv run cowrie-db migrate` test
- Needs validation on development database

## Files Changed

- `cowrieprocessor/db/migrations.py` (+43 lines, -10 lines)
  - Added new Phase 1 with source_ip column creation/population
  - Renumbered all subsequent phases
  - Added comprehensive logging

## Next Steps

1. Test migration on development database
2. Validate all 5 phases execute without errors
3. Update unit tests to match new phase structure
4. Update PDCA documentation with bugfix details
