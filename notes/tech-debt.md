# Technical Debt Tracking

This file tracks known technical debt items that should be addressed in future sprints. Items here are candidates for conversion to GitHub issues.

**Status Legend**:
- 🔴 **Critical**: Impacts production functionality
- 🟡 **Medium**: Reduces effectiveness or maintainability
- 🟢 **Low**: Minor issues, quality improvements

---

## Table of Contents

1. [Production Bugs](#production-bugs)
2. [Test Suite Issues](#test-suite-issues)
3. [Code Quality Issues](#code-quality-issues)
4. [Performance Optimizations](#performance-optimizations)
5. [Documentation Gaps](#documentation-gaps)

---

## Production Bugs

### 🟡 SSH Key Analytics - unique_ips Never Populated
**File**: `cowrieprocessor/enrichment/ssh_key_analytics.py:409`
**Discovered**: October 23, 2025 (Week 3 Day 14)
**Severity**: Medium
**Status**: Documented, not yet fixed

**Description**:
In the `_find_connected_campaigns` method, the `unique_ips` set is initialized but never populated with data. This causes campaign filtering to fail when `min_ips > 0` is used.

**Code Location**:
```python
# Line 409 in ssh_key_analytics.py
unique_ips: set[str] = set()  # BUG: Initialized but never populated!

# Later at line 447:
if campaign.unique_ips >= min_ips:  # Always fails if min_ips > 0
    valid_campaigns.append(campaign)
```

**Impact**:
- Campaign detection effectiveness reduced
- Campaigns rejected when `min_ips > 0` parameter used
- Confidence scoring always gets `ip_spread=0`
- Campaigns with good key diversity can be missed

**Workaround**:
- Use `min_ips=0` in campaign detection calls
- Or use lower confidence thresholds

**Recommended Fix**:
```python
# Should populate unique_ips from session data:
for key_id in component:
    sessions = session.query(SessionSSHKeys).filter_by(ssh_key_id=key_id).all()
    for s in sessions:
        if s.source_ip:
            unique_ips.add(s.source_ip)

# Then update Campaign object:
campaign.unique_ips = len(unique_ips)
```

**Discovery Method**: Comprehensive test suite with real database fixtures

**References**:
- `notes/DAY14_SSH_ANALYTICS_SUMMARY.md` (lines 213-223, 461-501)
- `notes/WEEK3_SUMMARY.md` (lines 461-503)
- `notes/committed-notes.md` (Production Issues section)
- CHANGELOG [Unreleased] → Fixed (lines 32-36)

**GitHub Issue**: TODO - Create issue

---

## Test Suite Issues

### 🔴 Pre-existing Test Failures (91 failures)
**Discovered**: October 21-22, 2025 (Week 3 Days 11-12)
**Severity**: Critical (blocks accurate coverage measurement)
**Status**: Documented, categorized, not yet fixed

**Description**:
91 pre-existing test failures prevent accurate total coverage measurement and indicate architectural issues requiring refactoring.

**Failure Categories**:

1. **Enrichment Test Failures** (~35 tests)
   - Mock/patch issues with external APIs
   - Requires enrichment framework refactoring
   - File: `tests/unit/test_enrichment_*.py`

2. **Database Test Failures** (~25 tests)
   - SQLAlchemy session management
   - Transaction rollback issues
   - Files: `tests/unit/test_*_db.py`

3. **CLI Test Failures** (~20 tests)
   - Argument parser changes
   - Click framework integration
   - Files: `tests/unit/test_*_cli.py`

4. **Type System Failures** (~11 tests)
   - Return type mismatches
   - Optional vs required parameters
   - Various files

**Impact**:
- Total coverage measurement masked (~8-10% coverage hidden)
- Cannot run full test suite without failures
- Reduces confidence in regression testing
- Blocks CI/CD pipeline

**Estimated Effort**: 3-5 days (dedicated sprint)

**Strategy**:
1. Fix all enrichment tests first (highest count)
2. Fix database tests (medium count, high risk)
3. Fix CLI tests (medium count, lower risk)
4. Fix type system tests (low count, low risk)

**Expected Coverage Gain**: +8-10% total coverage (unmasking existing coverage)

**References**:
- `notes/week3_day11_failures_full.txt` (detailed failure output)
- `notes/day11_failure_categorization.md` (analysis)
- `notes/WEEK3_SUMMARY.md` (lines 574-597)
- `notes/committed-notes.md` (Technical Debt section)

**Recommendation**: Dedicated sprint in Week 5 or 6

**GitHub Issue**: TODO - Create epic with sub-issues per category

---

### 🟢 Test Coverage Gaps in Migrations
**File**: `cowrieprocessor/db/migrations.py`
**Current Coverage**: 58%
**Status**: Partial coverage, remaining migrations untested

**Description**:
Migrations v5, v6, v7, v8, v10, v12, v13, v14 are not yet covered by tests. Current test coverage focused on Priority 1 and 2 migrations (v2, v3, v4, v9, v11).

**Untested Migrations**:
- `_upgrade_to_v5`: Unknown size
- `_upgrade_to_v6`: Unknown size
- `_upgrade_to_v7`: 269 lines (PRIORITY 1)
- `_upgrade_to_v8`: Unknown size
- `_upgrade_to_v10`: 244 lines (PRIORITY 1)
- `_upgrade_to_v12`: 109 lines (PRIORITY 1)
- `_upgrade_to_v13`: Unknown size
- `_upgrade_to_v14`: Unknown size

**Impact**:
- Medium risk: Migrations not validated by tests
- Could cause issues in production deployments
- Idempotency not verified

**Estimated Effort**: 2-3 days (20-25 additional tests)

**Target Coverage**: 70-75% (from current 58%)

**References**:
- `notes/DAY13_MIGRATIONS_SUMMARY.md` (lines 100-115)
- `tests/unit/test_migrations.py` (existing tests as pattern)

**GitHub Issue**: TODO - Create issue for remaining migrations testing

---

## Code Quality Issues

### 🟢 Database Model Field Documentation
**Status**: Resolved (process improvement)
**Impact**: Low (only affects test development)

**Description**:
During Week 2 Days 8-9, tests failed due to incorrect assumptions about ORM model field names (e.g., `sensor_id`, `execution_count`, `analysis_results`).

**Resolution**:
- Added validation step to test development workflow
- Mandatory: Check `db/models.py` before writing tests
- Process documented in Week 2 summary

**Prevention**: Test development checklist includes model verification

**References**:
- `notes/WEEK2_SUMMARY.md` (lines 236-248)
- `notes/committed-notes.md` (Production Issues section)

**No GitHub issue needed** (process improvement, already resolved)

---

### 🟢 Coverage Measurement Protocol
**Status**: Resolved (process improvement)
**Impact**: Low (measurement issue, not code bug)

**Description**:
Week 2 Day 7-8 had coverage measurement errors due to using partial test file lists instead of full directory.

**Wrong Command**:
```bash
# WRONG - only tests specific files
pytest tests/unit/test_longtail.py tests/unit/test_dlq_processor.py ...
```

**Correct Command**:
```bash
# CORRECT - tests entire unit/ directory
rm -f .coverage
uv run coverage run --source=cowrieprocessor -m pytest tests/unit/
```

**Resolution**:
- Established mandatory coverage measurement protocol
- Documented in CLAUDE.md and testing guides

**References**:
- `notes/WEEK2_SUMMARY.md` (lines 218-233)
- `notes/committed-notes.md` (Production Issues section)

**No GitHub issue needed** (process improvement, already resolved)

---

## Performance Optimizations

### 🟢 Enrichment Cache Optimization Opportunities
**Status**: Working, but could be improved
**Impact**: Low (current performance acceptable)

**Description**:
Current enrichment cache achieves 70-90% API call reduction, but additional optimizations possible:
- Cache prewarming for known indicators
- Batch cache lookups
- Redis backend option for multi-process scenarios

**Current Performance**:
- VirusTotal: 30-day cache, 4 req/min rate limit (working well)
- DShield: 7-day cache, 30 req/min (working well)
- URLHaus: 3-day cache, 30 req/min (working well)

**Potential Improvements**:
1. Implement cache prewarming for common IPs/hashes
2. Add Redis backend option for shared cache
3. Implement batch lookup API for cache queries
4. Add cache statistics dashboard

**Estimated Effort**: 1-2 days per improvement

**Priority**: Low (current implementation works well)

**References**:
- `notes/ENRICHMENT_OPTIMIZATION_FIX.md`
- `notes/committed-notes.md` (Enrichment Framework section)

**GitHub Issue**: TODO - Create enhancement issue (low priority)

---

## Documentation Gaps

### 🟢 SSH Key Intelligence User Guide
**Status**: Technical docs exist, user guide missing
**Impact**: Low (feature works, but harder for users to discover/use)

**Description**:
SSH Key Intelligence feature (PR #63) has comprehensive technical documentation but lacks user-facing guide with examples and use cases.

**Existing Documentation**:
- `notes/DAY14_SSH_ANALYTICS_SUMMARY.md` (technical)
- `notes/committed-notes.md` (technical)
- CHANGELOG v3.0.0 (feature list)
- Code docstrings (API reference)

**Missing Documentation**:
- User guide with real-world examples
- Common use cases and workflows
- Tutorial for campaign detection
- Visualization examples

**Estimated Effort**: 1 day

**Priority**: Low (feature is documented, just needs user guide)

**GitHub Issue**: TODO - Create documentation issue

---

### 🟢 Testing Patterns Guide
**Status**: Patterns established, formal guide missing
**Impact**: Low (patterns documented in summaries, but not centralized)

**Description**:
Week 3 established excellent testing patterns (isolation, Given-When-Then, no mocking own code, etc.) but these are scattered across summary documents rather than in a centralized testing guide.

**Existing Documentation**:
- `notes/WEEK3_SUMMARY.md` (patterns described)
- `notes/committed-notes.md` (patterns documented)
- Individual test files (examples)

**Missing Documentation**:
- Formal testing guide in `docs/` or `CONTRIBUTING.md`
- Quick reference for new test developers
- Pattern examples in one place

**Estimated Effort**: 0.5 day

**Priority**: Low (patterns are being followed, just needs centralization)

**GitHub Issue**: TODO - Create documentation issue

---

## Documentation Validation Items

### 🟢 Docs Requiring Verification Before Sphinx Migration

**Added**: October 25, 2025 (from docs currency audit)
**Priority**: Medium
**Estimated Effort**: 2 hours total

**Files Needing Validation**:

1. **telemetry-operations.md** (4.7K)
   - Verify current telemetry implementation matches documentation
   - Check OpenTelemetry integration status
   - Estimated: 30 min

2. **dlq-processing-solution.md** (14K)
   - Compare with current DLQ implementation in `cowrieprocessor/loader/dlq_processor.py`
   - DLQ processor tested in Week 1 (55% coverage)
   - Estimated: 30 min

3. **enhanced-dlq-production-ready.md** (12K)
   - Verify production DLQ deployment status
   - Check against current configuration
   - Estimated: 30 min

4. **enrichment-schemas.md** (6.6K)
   - Verify VirusTotal, DShield, URLHaus, SPUR schemas current
   - **CRITICAL**: Ensure HIBP schema included (PR #62, Oct 2025)
   - Estimated: 30 min

5. **postgresql-migration-guide.md** (9.8K)
   - Verify against current PostgreSQL support (PRs #44, #48)
   - Check migration procedures
   - Estimated: 20 min

6. **postgresql-stored-procedures-dlq.md** (7.3K)
   - Check if stored procedures still in use
   - Verify syntax for current PostgreSQL version
   - Estimated: 20 min

**GitHub Issue**: TODO - Create "Documentation Validation Sprint" issue

---

## Items Ready for GitHub Issues

### High Priority (Create Soon)
1. 🔴 Pre-existing Test Failures (91 failures) - Epic with sub-issues
2. 🟡 SSH Key Analytics unique_ips bug - Bug fix
3. 🟢 Documentation Validation Sprint - Documentation (6 files, 2 hours)

### Medium Priority (Create This Month)
4. 🟢 Test Coverage Gaps in Migrations - Enhancement
5. 🟢 SSH Key Intelligence User Guide - Documentation

### Low Priority (Create When Time Permits)
6. 🟢 Enrichment Cache Optimization Opportunities - Enhancement
7. 🟢 Testing Patterns Guide - Documentation

---

## Maintenance Strategy

### Weekly Review
- Review this file for new items
- Update status of existing items
- Convert ready items to GitHub issues

### Monthly Review
- Archive resolved items
- Re-prioritize based on project needs
- Estimate effort for upcoming sprints

### Quarterly Review
- Technical debt sprint planning
- Evaluate impact vs. effort
- Schedule dedicated cleanup time

---

## Archive

### Resolved Items
Items marked as resolved will be moved here with resolution date:

*No archived items yet*

---

*Document created: October 25, 2025*
*Last updated: October 25, 2025*
*Status: Living document, updated as issues are discovered/resolved*
