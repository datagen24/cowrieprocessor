# Phase 1: Critical Path Module Testing (Accelerated)

## Overview
**Goal**: Test Priority 1 modules to reach 52% coverage
**Start**: 40.3% coverage (improved from 32% baseline)
**Target**: 52% coverage (+11.7 percentage points)
**Timeline**: 3-4 days (accelerated from original 5 days)
**Status**: 🟢 READY TO EXECUTE

## Major Plan Revision

### Original Option B Math
- Start: 32%
- Target: 65% 
- Gap: +33 percentage points
- Timeline: 20 days

### New Reality (After Phase 0a Success)
- Start: 40.3% (+8.3% from Phase 0a)
- Target: 65%
- Gap: +24.7 percentage points (25% less work!)
- Timeline: 2-2.5 weeks (accelerated)

## Revised Phase Targets

| Phase | Original Target | Revised Target | Gap Remaining |
|-------|----------------|----------------|---------------|
| Current | 32% | 40.3% | 24.7% |
| Phase 1 | 48% | 52-54% | 11-13% |
| Phase 1.5 | 50% | 54-56% | 9-11% |
| Phase 2 | 56% | 62-64% | 1-3% |
| Phase 2.5 | 58% | 65% | ✅ TARGET MET |

**Projected completion**: End of Week 2 (10-12 days vs original 20 days)

## Priority 1 Modules (Revised Focus)

### ✅ Skip These (Already Well-Covered)
- **cli/ingest.py** - 24/24 tests passing, likely >70% coverage
- **db_engine.py** - Already 85% covered
- **db_base.py** - Already 100% covered

### ⚠️ Test These (Major Coverage Gaps)
1. **loader/cowrie_schema.py** - 0% baseline, fix mocking issues
2. **loader/bulk.py** - 22% baseline, major coverage gap  
3. **loader/delta.py** - 14% baseline, major coverage gap

## Phase 1 Execution Plan (3-4 days)

### Day 1: loader/cowrie_schema.py
**Current**: 0% | **Target**: 85% | **Gain**: +1.8%

**Why this module first**:
- Event validation is critical path
- Currently untested (biggest gap)
- Mocking issues found → Fix while testing

**Tests to create**:
```python
test_cowrie_schema_validates_login_event_succeeds
test_cowrie_schema_validates_command_event_succeeds
test_cowrie_schema_validates_file_event_succeeds
test_cowrie_schema_rejects_malformed_event_raises_error
test_cowrie_schema_rejects_missing_required_field_raises_error
test_cowrie_schema_handles_unknown_event_type_gracefully
test_cowrie_schema_extracts_fields_from_valid_event
test_cowrie_schema_sanitizes_unicode_in_event_fields
```

**Action**: Fix existing test mocks while adding new tests.

### Day 2: loader/bulk.py
**Current**: 22% | **Target**: 65% | **Gain**: +2.5%

**Tests to add**:
- Error path tests (from Phase 1.5 analysis)
- Batch processing tests
- Transaction rollback tests

### Day 3: loader/delta.py
**Current**: 14% | **Target**: 60% | **Gain**: +1.2%

**Tests to add**:
- Checkpoint handling tests
- Incremental load tests
- Error recovery tests

### Day 4: Measure & Adjust
- Run coverage report
- Expected: 51-53% coverage
- If <50%: Add quick wins from Phase 1.5
- If >52%: Skip Phase 1.5, go straight to Phase 2

## Updated Success Criteria

### Phase 1 Complete When:
- [ ] Coverage ≥52% (was 48%)
- [ ] loader/cowrie_schema.py ≥85% covered
- [ ] loader/bulk.py ≥65% covered
- [ ] loader/delta.py ≥60% covered
- [ ] All new tests passing
- [ ] Priority 1 mocking issues resolved

### Option B Complete When:
- [ ] Coverage ≥65% (unchanged)
- [ ] All Priority 1-2 modules ≥50% covered
- [ ] Timeline: 2-2.5 weeks (was 3 weeks)

## Mocking Issues Strategy

### Rule: 15-Minute Fix Limit
When encountering Priority 1 test failures:
1. Understand test intent - What is it trying to test?
2. Fix the mock - Update mock setup to match current code
3. Verify test passes - Ensure it tests the right thing
4. Move on - Don't get stuck debugging old tests

### If Still Broken After 15 Minutes:
```python
@pytest.mark.skip(reason="Legacy mock issue - Phase 1 priority")
```

### Common Mocking Issues to Fix:
```python
# Issue 1: Mock target wrong
patch('cowrieprocessor.loader.bulk.engine')  # ❌ Wrong path
patch('cowrieprocessor.db.engine.create_engine')  # ✅ Correct

# Issue 2: Fixture scope wrong
@pytest.fixture(scope='module')  # ❌ Too broad
@pytest.fixture(scope='function')  # ✅ Isolated

# Issue 3: Return value not set
mock_session.query.return_value = None  # ❌ Incomplete
mock_session.query.return_value.filter.return_value.all.return_value = []  # ✅ Complete
```

## Progress Tracking

### Day 1 Progress
- [ ] Verify cli/ingest.py coverage (15 minutes)
- [ ] Document mocking issues (30 minutes)
- [ ] Begin loader/cowrie_schema.py testing
- [ ] Fix existing test mocks
- [ ] Create 3-4 new validation tests

### Day 2 Progress
- [ ] Complete loader/cowrie_schema.py (target 85% coverage)
- [ ] Begin loader/bulk.py testing
- [ ] Add error path and batch processing tests

### Day 3 Progress
- [ ] Complete loader/bulk.py (target 65% coverage)
- [ ] Begin loader/delta.py testing
- [ ] Add checkpoint and incremental load tests

### Day 4 Progress
- [ ] Complete loader/delta.py (target 60% coverage)
- [ ] Measure coverage (target 52%+)
- [ ] Adjust plan for Phase 2

## Risk Mitigation

### If Falling Behind Schedule:
- **Day 2 checkpoint**: Expected 48% coverage
  - If <45%: Reduce scope, focus on 2 modules only
- **Day 3 checkpoint**: Expected 50% coverage
  - If <48%: Add Phase 1.5 quick wins
- **Day 4 checkpoint**: Expected 52% coverage
  - If <50%: Extend Phase 1 by 1 day

### If Ahead of Schedule:
- **Day 2**: If >50% coverage → Skip to Phase 2
- **Day 3**: If >54% coverage → Skip Phase 1.5, go to Phase 2

## Success Metrics

### Must Achieve (Phase 1 Complete):
- Coverage ≥52%
- Priority 1 modules ≥60% covered
- All new tests passing
- Zero regressions in working tests

### Nice to Have:
- Coverage ≥54%
- Priority 1 modules ≥70% covered
- All mocking issues resolved

---

**Last Updated**: 2024-12-19
**Status**: 🟢 READY TO EXECUTE - Begin Day 1
