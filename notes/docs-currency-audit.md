# Documentation Currency Audit Report

**Date**: October 25, 2025
**Purpose**: Verify accuracy of existing markdown documentation before Sphinx migration
**Status**: 🔴 **CRITICAL ISSUES FOUND** - Several docs are outdated

---

## Executive Summary

**Findings**: Of 16 markdown files audited, **5 are critically outdated**, **3 are historical/completed**, and **8 appear current or acceptable**.

**Critical Issue**: `data_dictionary.md` (35KB, most important doc) claims "Current Schema Version: 10" but actual schema is **v14** (4 versions behind).

**Recommendation**: **Update outdated docs BEFORE Sphinx migration** to avoid publishing incorrect information.

---

## Audit Results by File

### 🔴 CRITICAL: Outdated and Needs Update

#### 1. data_dictionary.md (35K)
**Status**: ⚠️ **CRITICALLY OUTDATED**
**File Date**: October 14, 2025
**Claims**: Current Schema Version: 10
**Actual**: Current Schema Version: 14 (per migrations.py)
**Missing**: Schema v11, v12, v13, v14 tables and changes

**Impact**: HIGH - This is the primary database reference document

**Changes Needed**:
- Add SSH Key Intelligence tables (v11):
  - `ssh_key_intelligence`
  - `session_ssh_keys`
  - `ssh_key_associations`
- Document v12 changes (event_timestamp datetime conversion)
- Document v13 changes (if any)
- Document v14 changes (analysis_id to vector tables)
- Update schema version to 14
- Update "Last Updated" to current date

**Migrations to Review**:
```bash
# From CHANGELOG and code:
v11: SSH Key Intelligence tables (PR #63, Oct 2025)
v12: event_timestamp to datetime type (Oct 2025)
v13: Unknown
v14: analysis_id to vector tables
```

**Estimated Update Time**: 2-3 hours
**Verdict**: Update the Document, Full Conversion to RST
---

#### 2. schema-v7-migration.md (8.6K)
**Status**: ⚠️ **OUTDATED - Only covers v7**
**File Date**: October 2, 2025
**Claims**: Migration guide for schema v7
**Actual**: Current schema is v14

**Impact**: MEDIUM - Historical reference, but title is misleading

**Options**:
1. Rename to indicate it's historical (schema-v7-migration-historical.md)
2. Expand to cover v8-v14 migrations
3. Create comprehensive migration guide covering all versions

**Recommendation**: Rename as historical, create new comprehensive migration guide
**Verdict**: Archive
---

#### 3. enrichment_test_harness.md (3.0K)
**Status**: ⚠️ **NEEDS VERIFICATION**
**File Date**: September 29, 2025
**Content**: Testing guide for enrichment harness

**Concerns**:
- File date is pre-Week 3 test coverage work
- May not reflect current test patterns (Given-When-Then, no mocking own code)
- Should verify against current test practices

**Recommendation**: Review and update to match current testing standards
**Verdict**: Archive
---

#### 4. files_table_followup.md (2.1K)
**Status**: ⚠️ **NEEDS VERIFICATION**
**File Date**: September 29, 2025
**Content**: Files table follow-up work

**Concerns**:
- Old file date
- May reference completed work
- Unclear if still relevant

**Recommendation**: Review content, archive if completed work
**Verdict**: Archive

---

#### 5. telemetry-operations.md (4.7K)
**Status**: ⚠️ **NEEDS VERIFICATION**
**File Date**: September 29, 2025
**Content**: Telemetry operations guide

**Recommendation**: Verify current telemetry implementation matches documentation
**Verdict**: Keep, add tech-debt to validate
---

### 📚 HISTORICAL: Completed Work (Archive or Mark as Historical)

#### 6. MYPY-REMEDIATION-SUMMARY.md (8.7K)
**Status**: ✅ **HISTORICAL - COMPLETED**
**File Date**: October 18, 2025
**Content**: MyPy remediation summary

**Recommendation**: Archive or move to historical section - work completed
**Verdict**: Archive
---

#### 7. mypy-remediation-progress.md (9.5K)
**Status**: ✅ **HISTORICAL - COMPLETED**
**File Date**: October 18, 2025
**Content**: MyPy remediation progress tracking

**Recommendation**: Archive - work completed
**Verdict**: Archive
---

#### 8. PHASE-9-COMPLETION.md (6.5K)
**Status**: ✅ **HISTORICAL - COMPLETED**
**File Date**: October 18, 2025
**Content**: Phase 9 completion summary

**Recommendation**: Archive - historical milestone
**Verdict**: Archive
---

#### 9. sqlalchemy-2.0-migration.md (19K)
**Status**: ✅ **HISTORICAL - COMPLETED**
**File Date**: October 18, 2025
**Content**: SQLAlchemy 2.0 migration guide

**Recommendation**: Keep as reference for migration patterns, mark as historical
**Verdict**: Archive
---

### ✅ CURRENT: Appears Accurate (Verify Before Migration)

#### 10. dlq-processing-solution.md (14K)
**Status**: ✅ **APPEARS CURRENT**
**File Date**: October 2, 2025
**Content**: Dead Letter Queue processing solution

**Verification Needed**: Compare with current DLQ implementation in cowrieprocessor/loader/dlq_processor.py

**Coverage**: DLQ processor tested in Week 1, 55% coverage, so implementation should match
**Verdict**: Keep, add tech-debt to validate
---

#### 11. enhanced-dlq-production-ready.md (12K)
**Status**: ✅ **APPEARS CURRENT**
**File Date**: October 2, 2025
**Content**: Enhanced DLQ production readiness

**Verification Needed**: Compare with production DLQ deployment
**Verdict**: Keep, add tech-debt to validate
---

#### 12. enrichment-schemas.md (6.6K)
**Status**: ✅ **APPEARS CURRENT**
**File Date**: October 14, 2025
**Content**: Enrichment data schemas

**Verification Needed**: Compare with current enrichment implementations (VirusTotal, DShield, URLHaus, HIBP, SPUR)

**Note**: HIBP added in PR #62 (Oct 2025), should be included
**Verdict**: Keep, add tech-debt to validate
---

#### 13. postgresql-migration-guide.md (9.8K)
**Status**: ✅ **LIKELY CURRENT**
**File Date**: October 2, 2025
**Content**: PostgreSQL migration guide

**Verification Needed**: Verify against current PostgreSQL support (PRs #44, #48)
**Verdict**: Keep, add tech-debt to validate
---

#### 14. postgresql-stored-procedures-dlq.md (7.3K)
**Status**: ✅ **LIKELY CURRENT**
**File Date**: October 2, 2025
**Content**: PostgreSQL stored procedures for DLQ

**Verification Needed**: Check if stored procedures still in use
**Verdict**: Keep, add tech-debt to validate
---

#### 15. snowshoe-phase0-research.md (50K)
**Status**: ✅ **RESEARCH NOTES**
**File Date**: October 14, 2025
**Content**: Snowshoe spam detection research

**Recommendation**: Keep as reference, mark as research notes
**Verdict**: Move to notes folder, Ensure meets notes requirements
---

#### 16. snowshoe-github-issues.md (29K)
**Status**: ✅ **ISSUE TRACKING**
**File Date**: October 14, 2025
**Content**: Snowshoe feature GitHub issues

**Recommendation**: Keep as reference or integrate with issue tracker
**Verdict**: Move to notes folder, Ensure meets notes requirements
---

## Subdirectories

### docs/ADR/ (Architecture Decision Records)
**Status**: Unknown (need to audit)
**Recommendation**: Keep as-is, migrate to sphinx as ADRs

### docs/db/
**Status**: Unknown (need to audit)
**Recommendation**: Review contents
**Verdict**: Review Folder, Should contain all Database Documentation

### docs/issues/
**Status**: Unknown (need to audit)
**Recommendation**: Review for currency
**Verdict**: Review Folder, Should contain issue Technical implmentation plans that align with Github Issues, may refrences notes

### docs/json/
**Status**: Unknown (need to audit)
**Content**: Likely JSON schema examples
**Recommendation**: Review and verify against current schemas
**Verdict**: Review Folder, Should contain all JSON schemas either exported on CLI or for JSON fields in the database

---

## Summary by Priority

### Priority 1: MUST UPDATE BEFORE MIGRATION

1. ✅ **data_dictionary.md** - Add v11-v14 schema changes (2-3 hours)
2. ⚠️ **enrichment-schemas.md** - Verify HIBP inclusion (30 min)
3. ⚠️ **enrichment_test_harness.md** - Update to current test patterns (1 hour)

**Total Estimated Time**: 3.5-4.5 hours

### Priority 2: SHOULD VERIFY BEFORE MIGRATION

4. ⚠️ **dlq-processing-solution.md** - Verify against current code (30 min)
5. ⚠️ **enhanced-dlq-production-ready.md** - Verify production state (30 min)
6. ⚠️ **postgresql-migration-guide.md** - Verify current PostgreSQL support (30 min)
7. ⚠️ **telemetry-operations.md** - Verify current telemetry (30 min)

**Total Estimated Time**: 2 hours

### Priority 3: MARK AS HISTORICAL/ARCHIVE

8. **MYPY-REMEDIATION-SUMMARY.md** - Archive
9. **mypy-remediation-progress.md** - Archive
10. **PHASE-9-COMPLETION.md** - Archive
11. **sqlalchemy-2.0-migration.md** - Mark as historical reference
12. **schema-v7-migration.md** - Rename as historical

**Total Estimated Time**: 30 min (just moving/renaming)

### Priority 4: KEEP AS-IS (Research/Reference)

13. **snowshoe-phase0-research.md** - Keep
14. **snowshoe-github-issues.md** - Keep
15. **postgresql-stored-procedures-dlq.md** - Keep
16. **files_table_followup.md** - Review content, then decide

---

## Critical Schema Changes Missing from data_dictionary.md

### Schema v11: SSH Key Intelligence (PR #63)

**New Tables**:
```sql
CREATE TABLE ssh_key_intelligence (
    id SERIAL PRIMARY KEY,
    key_fingerprint VARCHAR(64) NOT NULL,
    key_type VARCHAR(32) NOT NULL,
    key_size INTEGER,
    first_seen TIMESTAMP WITH TIME ZONE,
    last_seen TIMESTAMP WITH TIME ZONE,
    total_sessions INTEGER,
    total_attempts INTEGER,
    ...
);

CREATE TABLE session_ssh_keys (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    ssh_key_id INTEGER REFERENCES ssh_key_intelligence(id),
    command_text TEXT,
    ...
);

CREATE TABLE ssh_key_associations (
    id SERIAL PRIMARY KEY,
    key_id_1 INTEGER REFERENCES ssh_key_intelligence(id),
    key_id_2 INTEGER REFERENCES ssh_key_intelligence(id),
    co_occurrence_count INTEGER,
    ...
);
```

**Indexes**: 15+ indexes on these tables

**Source**: CHANGELOG v3.0.0, notes/DAY14_SSH_ANALYTICS_SUMMARY.md

---

### Schema v12: event_timestamp Conversion

**Change**: Convert `event_timestamp` from VARCHAR to proper TIMESTAMP type

**Impact**: Better temporal queries, timezone handling

**Source**: CHANGELOG [Unreleased], migration code

---

### Schema v13: Unknown

**Need to investigate**: Review migrations.py for v13 changes

---

### Schema v14: Vector Table Enhancement

**Change**: Add `analysis_id` to vector tables

**Impact**: Better tracking of longtail analysis runs

**Source**: migrations.py code

---

## Recommended Workflow

### Option A: Update First, Then Migrate (Recommended)

**Pros**:
- Ensures accurate documentation from day 1
- No risk of publishing outdated info
- Clean Sphinx migration

**Cons**:
- Delays Sphinx setup by 1-2 days

**Steps**:
1. Update data_dictionary.md with v11-v14 (2-3 hours)
2. Verify and update enrichment docs (1.5 hours)
3. Verify DLQ and PostgreSQL docs (2 hours)
4. Archive historical docs (30 min)
5. **THEN** set up Sphinx and migrate updated docs

**Total Delay**: 1-2 days

---

### Option B: Sphinx First, Update During Migration

**Pros**:
- Faster Sphinx setup
- Can update in Sphinx system directly

**Cons**:
- Risk of publishing outdated info initially
- Updates needed in new RST/markdown format

**Steps**:
1. Set up Sphinx (Phase 1)
2. Migrate current docs with "NEEDS UPDATE" warnings
3. Update docs in Sphinx format
4. Publish when ready

**Total Time**: Same overall, but phased differently

---

### Option C: Hybrid - API Docs First, Guides Later

**Pros**:
- API docs auto-generated (always current)
- Guides can be updated incrementally
- Quick win with API reference

**Cons**:
- Incomplete documentation initially
- Guides section marked "Coming Soon"

**Steps**:
1. Set up Sphinx with API docs only (Phase 1)
2. Publish API reference to ReadTheDocs
3. Update markdown docs in parallel
4. Add guides section when ready

**Total Time**: Fastest to first publish, iterative for guides

---

## Recommendations

### Immediate Action

**Recommended Approach**: **Option A - Update First, Then Migrate**

**Rationale**:
- data_dictionary.md is critically outdated (4 schema versions behind)
- Publishing outdated schema docs would harm credibility
- Better to delay 1-2 days and get it right
- Updates are straightforward (schema changes well-documented in CHANGELOG)

**Alternative**: **Option C - API Docs First** if you need documentation published quickly
- API docs are auto-generated from docstrings (always current)
- Gives users API reference immediately
- Buy time to update guides properly

---

### Update Priority List

**Day 1: Critical Updates** (3-4 hours)
1. Update data_dictionary.md:
   - Add SSH Key Intelligence tables (v11)
   - Add event_timestamp conversion (v12)
   - Add vector table changes (v14)
   - Investigate and add v13 changes
   - Update version number and last-updated date

2. Verify enrichment-schemas.md:
   - Ensure HIBP schema documented
   - Verify VirusTotal, DShield, URLHaus, SPUR schemas current

3. Update enrichment_test_harness.md:
   - Align with current test patterns (Given-When-Then, no mocking own code)
   - Reference Week 3 test standards

**Day 2: Verification and Cleanup** (2.5 hours)
4. Verify DLQ docs against current code
5. Verify PostgreSQL docs against current implementation
6. Verify telemetry docs
7. Archive historical docs (mypy remediation, phase completion)
8. Audit subdirectories (ADR/, db/, issues/, json/)

**Day 3: Sphinx Setup** (Begin Phase 1)
9. Set up Sphinx with verified, updated documentation
10. Migrate to Sphinx with confidence

---

## Next Steps

**Recommend**:
1. ✅ Approve audit findings
2. ✅ Choose workflow (A, B, or C)
3. ⏳ Update critical documents (if Option A)
4. ⏳ Set up Sphinx (Phase 1)
5. ⏳ Migrate verified documentation

**Question for User**:
- Do you want to update docs first (Option A), or proceed with Sphinx and update in parallel (Option B/C)?
- How critical is time-to-publish vs. accuracy?

---

*Audit completed: October 25, 2025*
*Auditor: Claude Code AI Assistant*
*Next review: After updates complete*
