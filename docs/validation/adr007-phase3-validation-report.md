# ADR-007 Phase 3 Production Validation Report

**Date**: 2025-11-06
**Author**: Quality Engineer (Claude Code)
**Status**: ⚠️ BLOCKED - Critical Schema Mismatch Discovered
**Recommendation**: DO NOT PROCEED with backfill until schema alignment completed

---

## Executive Summary

Production validation of ADR-007 snapshot population backfill has uncovered a **critical schema mismatch** between codebase models and production database. This blocks execution of Phase 3 backfill until resolved.

**Key Findings**:
- ✅ Database connectivity successful (1.68M sessions, 38.9K IPs)
- ✅ Validation test framework operational
- ⚠️ **CRITICAL**: Production schema has `snapshot_ip_types` (plural) vs code expects `snapshot_ip_type` (singular)
- ❌ **BLOCKER**: Backfill script and ORM models incompatible with production schema
- ❌ Cannot execute backfill without schema migration

**Impact**:
- All snapshot-related queries will fail with "column does not exist" error
- Backfill script cannot populate `snapshot_ip_type` column (doesn't exist in production)
- Phase 3 validation blocked until schema alignment

**Required Actions**:
1. **IMMEDIATE**: Schema migration to align production with codebase
2. Re-run validation tests after schema alignment
3. Execute production backfill only after successful validation

---

## Validation Test Results

### Test 1: Database Connectivity ✅ PASS

**Objective**: Verify production database access and basic health

**Results**:
```
Database Health: PASS
  Sessions: 1,682,827
  IPs: 38,864
  Orphan sessions: 0
  Version: PostgreSQL 17.6 (Debian 17.6-1.pgdg12+1)
```

**Analysis**:
- Production database accessible and healthy
- Dataset size matches expectations (>1M sessions, >30K IPs)
- Zero orphan sessions (all session IPs exist in ip_inventory)
- PostgreSQL 17.6 running on production server 10.130.30.89:5432

**Status**: ✅ PASS

---

### Test 2: Schema Compatibility Check ❌ FAIL

**Objective**: Verify codebase models match production schema

**Discovery Process**:
1. Validation tests failed with `sqlalchemy.exc.ProgrammingError`
2. Error: "column session_summaries.snapshot_ip_type does not exist"
3. PostgreSQL hint: "Perhaps you meant to reference the column 'session_summaries.snapshot_ip_types'"
4. Direct schema query confirmed production has `snapshot_ip_types` (plural)

**Production Schema**:
```sql
SELECT column_name FROM information_schema.columns
WHERE table_name='session_summaries' AND column_name LIKE 'snapshot%';

column_name
-------------------
 snapshot_asn
 snapshot_country
 snapshot_ip_types  -- NOTE: Plural!
(3 rows)
```

**Codebase Model** (`cowrieprocessor/db/models.py`):
```python
snapshot_ip_type = Column(
    Text, nullable=True,
    doc="IP type at time of attack (e.g., 'RESIDENTIAL', 'DATACENTER', 'VPN')"
)
```

**Root Cause**:
The production database schema diverged from codebase models. Possible causes:
- Manual schema modification on production without updating models
- Earlier migration used incorrect column name
- Schema file drift between development and production

**Impact Severity**: 🔴 **CRITICAL BLOCKER**
- All snapshot validation queries fail
- Backfill script will fail attempting to UPDATE non-existent column
- Query performance tests cannot execute
- Data quality validation impossible

**Status**: ❌ FAIL - Blocks all subsequent validation

---

### Test 3: Baseline Snapshot Coverage ⚠️ PARTIAL

**Objective**: Measure current snapshot coverage before backfill

**Attempted Query**:
```sql
SELECT COUNT(*) FROM session_summaries WHERE snapshot_ip_type IS NOT NULL
```

**Result**: Query failed due to schema mismatch (see Test 2)

**Expected Coverage** (once schema fixed):
- Total sessions: 1,682,827
- Current coverage: 0% (all sessions lack snapshots)
- Target coverage: ≥95% after backfill

**Estimated Backfill Requirements**:
- Sessions needing snapshots: ~1.68M
- Batches required (1000/batch): ~1,683 batches
- Estimated time (3 sec/batch): ~84 minutes

**Status**: ⚠️ BLOCKED by schema mismatch

---

### Test 4: Dry-Run Safety Validation ❌ NOT EXECUTED

**Objective**: Verify `--dry-run` makes no database modifications

**Blocker**: Cannot execute backfill script until schema mismatch resolved

**Validation Plan** (once schema fixed):
```bash
# Measure before state
psql -c "SELECT COUNT(*) FROM session_summaries WHERE source_ip IS NULL"

# Run dry-run (100 sessions)
uv run python scripts/migrations/backfill_session_snapshots.py \
    --db "postgresql://..." \
    --batch-size 100 \
    --dry-run \
    --verbose

# Verify unchanged
psql -c "SELECT COUNT(*) FROM session_summaries WHERE source_ip IS NULL"
```

**Expected Outcome**:
- Dry-run completes in <10 seconds
- Zero sessions modified
- No errors in output

**Status**: ❌ NOT EXECUTED - Blocked by schema mismatch

---

### Test 5: Query Performance Comparison ❌ NOT EXECUTED

**Objective**: Measure speedup (snapshot vs JOIN)

**Blocker**: Cannot query `snapshot_ip_type` column (doesn't exist)

**Validation Plan** (once schema fixed):
```python
# Query 1: Snapshot (NO JOIN)
SELECT COUNT(*) FROM session_summaries
WHERE snapshot_country = 'CN' AND snapshot_ip_type = 'DATACENTER';

# Query 2: JOIN (slower)
SELECT COUNT(*) FROM session_summaries ss
JOIN ip_inventory ip ON ss.source_ip = ip.ip_address
WHERE ip.geo_country = 'CN' AND ip.ip_type = 'DATACENTER';

# Measure speedup ratio
```

**Expected Outcome**:
- Snapshot query: 2-5 seconds
- JOIN query: 10-50 seconds
- Speedup: 5-10x faster

**Status**: ❌ NOT EXECUTED - Blocked by schema mismatch

---

### Test 6: Data Quality Sampling ❌ NOT EXECUTED

**Objective**: Validate snapshot accuracy on 1000 random sessions

**Blocker**: Cannot access snapshot columns

**Validation Plan** (once schema fixed):
```python
# Sample 1000 random sessions
# Verify snapshot_asn matches ip_inventory.current_asn
# Verify snapshot_country matches ip_inventory.geo_country
# Verify snapshot_ip_type matches ip_inventory.ip_type
# Target: ≥99% accuracy (allows <1% temporal drift)
```

**Status**: ❌ NOT EXECUTED - Blocked by schema mismatch

---

## Schema Mismatch Analysis

### Detected Inconsistencies

| Component | Expected Name | Production Name | Status |
|-----------|---------------|-----------------|--------|
| ORM Model | `snapshot_ip_type` | `snapshot_ip_types` | ❌ MISMATCH |
| Index | `ix_session_summaries_snapshot_ip_type` | Unknown | ❓ UNKNOWN |
| Backfill Script | `snapshot_ip_type` | `snapshot_ip_types` | ❌ MISMATCH |

### Impact Scope

**Affected Components**:
1. **ORM Models** (`cowrieprocessor/db/models.py`)
   - SessionSummary.snapshot_ip_type column definition
   - Index definition: `ix_session_summaries_snapshot_ip_type`

2. **Backfill Script** (`scripts/migrations/backfill_session_snapshots.py`)
   - UPDATE statement references non-existent column
   - Will fail with "column does not exist" error

3. **Validation Tests** (`tests/validation/`)
   - All queries filtering by `snapshot_ip_type` fail
   - Performance comparison tests blocked
   - Data quality sampling blocked

4. **Production Queries**
   - Any application code using `snapshot_ip_type` will fail
   - Snowshoe detection queries may be broken
   - Campaign clustering queries affected

**Components NOT Affected**:
- `snapshot_asn` column (correct)
- `snapshot_country` column (correct)
- `source_ip` column (correct)
- `enrichment` JSONB column (correct)

### Resolution Options

**Option 1: Rename Production Column (RECOMMENDED)**
```sql
-- Migration: Rename snapshot_ip_types → snapshot_ip_type (singular)
ALTER TABLE session_summaries
    RENAME COLUMN snapshot_ip_types TO snapshot_ip_type;

-- Update index name for consistency
DROP INDEX IF EXISTS ix_session_summaries_snapshot_ip_types;
CREATE INDEX ix_session_summaries_snapshot_ip_type
    ON session_summaries(snapshot_ip_type);
```

**Pros**:
- Aligns production with codebase (single source of truth)
- No code changes required
- Backfill script works as-is
- Validation tests work as-is

**Cons**:
- Requires production schema modification
- Brief downtime for ALTER TABLE (should be fast with NULL values)

**Option 2: Update Codebase to Use Plural**
```python
# Update ORM model
snapshot_ip_types = Column(
    Text, nullable=True,
    doc="IP types at time of attack"
)
```

**Pros**:
- No production schema changes

**Cons**:
- Requires updating all code references
- Index names need updating
- Backfill script needs modification
- Validation tests need modification
- More code churn, higher risk

**Option 3: Dual-Column Support (NOT RECOMMENDED)**

Maintain both columns for compatibility

**Pros**:
- No immediate breaking changes

**Cons**:
- Technical debt
- Confusing API
- Waste of storage
- Deferred problem

---

## Production Readiness Assessment

### Readiness Checklist

| Criterion | Target | Current | Status |
|-----------|--------|---------|--------|
| Database connectivity | Online | ✅ Online | PASS |
| Schema compatibility | 100% match | ❌ Column mismatch | FAIL |
| Dry-run validation | Passes | ⚠️ Not executed | BLOCKED |
| Query performance | 5-10x speedup | ⚠️ Cannot measure | BLOCKED |
| Data quality | ≥95% accuracy | ⚠️ Cannot validate | BLOCKED |
| Backfill script | Executes cleanly | ❌ Will fail | FAIL |

### Risk Assessment

**Current Risk Level**: 🔴 **HIGH - Production Execution Not Recommended**

**Critical Risks**:
1. **Schema Mismatch** (Severity: CRITICAL)
   - Backfill will fail immediately
   - No rollback needed (no changes made)
   - Requires schema migration before retry

2. **Unknown Production State** (Severity: HIGH)
   - Cannot measure current snapshot coverage
   - Unknown if partial backfill already executed
   - Cannot validate data quality

3. **Query Breakage** (Severity: MEDIUM)
   - Existing queries using `snapshot_ip_type` may be failing
   - Snowshoe detection potentially broken
   - Campaign analysis affected

**Mitigated Risks**:
- Database health: Verified healthy, no orphan sessions
- Connection stability: Successful test connection
- Data volume: Within expected range (1.68M sessions)

### Go/No-Go Decision

**Recommendation**: 🔴 **NO-GO** - Do not proceed with production backfill

**Blockers**:
1. Schema mismatch must be resolved
2. Post-migration validation required
3. Dry-run must pass
4. Query performance must be validated

**Prerequisites for GO**:
1. ✅ Execute schema migration (Option 1 recommended)
2. ✅ Re-run validation Test Suite (all tests must pass)
3. ✅ Dry-run validation (100-1000 sessions)
4. ✅ Query performance validation (≥5x speedup confirmed)
5. ✅ Data quality sampling (≥95% accuracy)
6. ✅ Stakeholder approval for production execution

---

## Validation Test Framework

### Test Suite Components

**Created Artifacts**:
1. **`tests/validation/validation_helpers.py`** (442 lines)
   - Database connection management
   - Coverage analysis functions
   - Query performance measurement
   - Data quality sampling
   - Health checks

2. **`tests/validation/test_production_validation.py`** (560 lines)
   - 9 validation tests
   - Production database markers
   - Read-only and write-protected tests
   - Comprehensive reporting

3. **`pytest.ini`** (updated)
   - Added `production`, `read_only`, `allow_production_writes` markers
   - Safety controls for production testing

**Test Execution**:
```bash
# Read-only validation (safe for production)
uv run pytest tests/validation/ -m read_only -v

# With production writes (requires explicit approval)
uv run pytest tests/validation/ -m allow_production_writes -v
```

**Safety Features**:
- Read-only by default
- Explicit `--allow-production-writes` marker required for modifications
- Transaction rollback on errors
- Comprehensive logging for audit trail

### Test Coverage

**Implemented Tests**:
- ✅ Database connectivity and health
- ✅ Schema compatibility check
- ⚠️ Baseline snapshot coverage (blocked)
- ⚠️ Backfill requirements calculation (blocked)
- ⚠️ Dry-run safety validation (blocked)
- ⚠️ Batch performance measurement (blocked)
- ⚠️ Query performance comparison (blocked)
- ⚠️ Snapshot accuracy sampling (blocked)
- ✅ Production readiness assessment

**Test Status**: 2/9 passing, 7/9 blocked by schema mismatch

---

## Next Steps

### Immediate Actions (This Week)

1. **Schema Migration** (Priority: CRITICAL)
   - [ ] Create migration script: `rename_snapshot_ip_types.py`
   - [ ] Test migration on development database
   - [ ] Schedule production migration window
   - [ ] Execute migration with rollback plan
   - [ ] Verify column renamed successfully

2. **Post-Migration Validation** (Priority: HIGH)
   - [ ] Re-run Test 2: Schema compatibility check
   - [ ] Execute Test 3: Baseline snapshot coverage
   - [ ] Execute Test 4: Dry-run safety (100-1000 sessions)
   - [ ] Execute Test 5: Query performance comparison
   - [ ] Execute Test 6: Data quality sampling

3. **Production Backfill** (Priority: MEDIUM)
   - [ ] Small-scale test (10K sessions)
   - [ ] Measure actual performance
   - [ ] Validate data quality
   - [ ] Get stakeholder approval
   - [ ] Execute full backfill (1.68M sessions)

### Documentation Updates

- [ ] Document schema migration in ADR-007
- [ ] Update runbook with schema prerequisites
- [ ] Create schema validation checklist
- [ ] Document rollback procedures

### Monitoring

- [ ] Set up alerts for backfill progress
- [ ] Monitor query performance post-backfill
- [ ] Track snapshot coverage growth
- [ ] Validate application functionality

---

## Conclusion

Production validation uncovered a critical schema mismatch that blocks ADR-007 Phase 3 backfill execution. While the validation test framework is operational and database connectivity is confirmed, the column naming discrepancy (`snapshot_ip_type` vs `snapshot_ip_types`) must be resolved before proceeding.

**Recommendation**: Execute Option 1 (rename production column to singular) followed by complete re-validation before attempting production backfill.

**Estimated Timeline**:
- Schema migration: 1-2 hours (including testing)
- Post-migration validation: 2-3 hours
- Production backfill: 90-120 minutes (1.68M sessions)
- Total: 4-6 hours end-to-end

**Risk Level After Migration**: 🟡 MEDIUM (manageable with proper validation)

---

## Appendix A: Test Execution Logs

### Test 1: Database Connectivity

```
============================= test session starts ==============================
tests/validation/test_production_validation.py::test_database_connectivity

Database Health:
  Sessions: 1,682,827
  IPs: 38,864
  Orphan sessions: 0
  Version: PostgreSQL 17.6 (Debian 17.6-1.pgdg12+1) on x86_64-pc-linux-gnu

PASSED
```

### Test 2: Schema Compatibility

```
E   sqlalchemy.exc.ProgrammingError: (psycopg.errors.UndefinedColumn)
E   column session_summaries.snapshot_ip_type does not exist
E   LINE 3: WHERE session_summaries.snapshot_ip_type IS NOT NULL
E                 ^
E   HINT:  Perhaps you meant to reference the column "session_summaries.snapshot_ip_types".
```

---

## Appendix B: Production Environment Details

**Database**: PostgreSQL 17.6
**Host**: 10.130.30.89:5432
**Database**: cowrieprocessor
**User**: cowrieprocessor

**Dataset Statistics** (as of 2025-11-06):
- Total sessions: 1,682,827
- Total IPs: 38,864
- Orphan sessions: 0 (100% IP inventory coverage)

**Production Schema** (snapshot columns):
```sql
snapshot_asn         | integer
snapshot_country     | character varying(2)
snapshot_ip_types    | text  -- NOTE: Plural!
```

**Expected Schema** (from codebase):
```sql
snapshot_asn         | integer
snapshot_country     | character varying(2)
snapshot_ip_type     | text  -- Singular
```

---

**Report Generated**: 2025-11-06
**Validation Framework Version**: 1.0
**Test Suite**: ADR-007 Phase 3 Production Validation
**Status**: BLOCKED - Schema migration required
