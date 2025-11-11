# ADR-007 Snapshot Fix - Session Kickoff

**Date**: 2025-11-06
**GitHub Issue**: #141
**Branch**: (to be created)
**Status**: Ready to implement

## Issue Details

**Title**: Fix ADR-007 snapshot population in session_summaries
**Priority**: P1 - High
**Labels**: bug, area:enrichment, area:database
**URL**: https://github.com/datagen24/cowrieprocessor/issues/141

## Problem Summary

1.68M production sessions have 0% snapshot population despite 100% IP inventory enrichment. Loader never populates snapshot columns during ingestion.

## Implementation Scope

### Affected Files
- `cowrieprocessor/loader/bulk.py` - Primary fix location
- `cowrieprocessor/loader/delta.py` - Verification (delegates to bulk)
- `scripts/migrations/backfill_session_snapshots.py` - New file
- `tests/unit/test_snapshot_population.py` - New file
- `tests/integration/test_snapshot_backfill.py` - New file

### Key Changes
1. SessionAggregate: Add `canonical_source_ip` field
2. BulkLoader: Add `_lookup_ip_snapshots()` helper method
3. BulkLoader._upsert_session_summaries(): Populate 5 snapshot fields
4. Backfill script: Update 1.68M existing sessions

## Estimated Timeline

- Phase 1 (Code): 6-8 hours
- Phase 2 (Backfill): 2-3 hours
- Phase 3 (Validation): 1 hour
- **Total**: 9-12 hours

## Next Steps

1. Create feature branch: `feature/adr007-snapshot-population-fix`
2. Start Phase 1: SessionAggregate enhancement
3. Implement _lookup_ip_snapshots() helper
4. Update _upsert_session_summaries()
5. Write unit tests
6. Write backfill script
7. Test on staging
8. Deploy to production
9. Run backfill
10. Validate results

## Success Criteria

- ≥95% snapshot coverage in production
- 5-10x query performance improvement
- All tests passing (85%+ coverage)
- Immutability verified
- Production backfill completes successfully

## Resources

- Design Doc: `docs/designs/adr007-snapshot-population-fix.md`
- Memory: `adr007_snapshot_fix_design`
- Production Discovery: `milestone1_feature_discovery`
