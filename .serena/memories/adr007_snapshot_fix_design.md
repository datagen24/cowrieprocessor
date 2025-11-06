# ADR-007 Snapshot Population Fix - Design Summary

**Date**: 2025-11-06
**Status**: Design Complete
**Document**: docs/designs/adr007-snapshot-population-fix.md

## Problem
ADR-007 snapshot columns NEVER populated in 1.68M production sessions despite 100% IP inventory enrichment (0.00% snapshot coverage).

## Root Cause
`cowrieprocessor/loader/bulk.py:_upsert_session_summaries()` missing 5 fields in values dict:
- source_ip (FK to ip_inventory)
- snapshot_asn, snapshot_country, snapshot_ip_type (immutable snapshots)
- enrichment_at (timestamp)

## Pipeline Analysis
**Needs Fix**:
- ✅ BulkLoader._upsert_session_summaries() - initial ingestion
- ✅ DeltaLoader (delegates to BulkLoader)

**No Changes Needed** (snapshots immutable after ingestion):
- ❌ enrich_passwords.py - only updates enrichment JSON
- ❌ enrich_ssh_keys.py - only updates ssh_key counts
- ❌ cowrie_db.py - utility operations

## Solution Components

### 1. SessionAggregate Enhancement
Add `canonical_source_ip: Optional[str]` field to track first IP chronologically (for FK to ip_inventory).

### 2. IP Inventory Lookup Helper
New method `_lookup_ip_snapshots(session, ip_addresses)` for batch lookup:
- Single query per batch (not per session)
- Returns dict mapping IP → {asn, country, ip_type, enrichment_at}
- Handles missing/unenriched IPs gracefully

### 3. _upsert_session_summaries() Enhancement
- Batch lookup IP snapshots before values construction
- Populate 5 snapshot fields in values dict
- COALESCE in conflict resolution (snapshots immutable)

### 4. Backfill Migration Script
`scripts/migrations/backfill_session_snapshots.py`:
- Query sessions WHERE source_ip IS NULL
- Extract source IP from enrichment JSON
- Lookup snapshots from ip_inventory
- UPDATE with batch processing (1000 sessions/batch)
- Estimated time: 30-60 minutes for 1.68M sessions

## Implementation Effort
- Code changes: 6-8 hours
- Backfill script: 2-3 hours
- Testing/validation: 1 hour
- **Total**: 9-12 hours

## Success Metrics
- ≥95% snapshot population coverage
- 5-10x faster queries (snapshot vs JOIN)
- 100% unit test pass rate, 85%+ coverage
- Immutability verified (conflicts don't overwrite)

## Deployment
1. Deploy code changes (bulk.py + tests)
2. Run backfill on production (dry-run first)
3. Validate query performance improvement
4. Monitor new ingestion (snapshots populated)

## Key Design Decisions
- **Canonical IP**: First IP seen chronologically (not set insertion order)
- **Immutability**: COALESCE in conflict resolution preserves original snapshots
- **Graceful Degradation**: Missing IP inventory → NULL snapshots (acceptable)
- **IP Type Priority**: VPN > TOR > PROXY > DATACENTER > RESIDENTIAL (threat modeling)
