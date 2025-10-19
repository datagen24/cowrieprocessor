# Mocking Issues Analysis - Phase 1 Preparation

## Critical Findings

### 1. cli/ingest.py Coverage Status
**Finding**: Tests are heavily mocked and not actually testing the module
**Evidence**: Coverage report shows "No data to report" despite 24/24 tests passing
**Impact**: Module is likely untested despite having passing tests
**Decision**: ✅ **INCLUDE in Phase 1** - needs real test coverage

### 2. test_cowrie_schema.py Mocking Issues
**Primary Issue**: Tests calling methods that don't exist
**Example**: `test_extract_event_type_returns_correct_type` calls `schema.extract_event_type(event)` but method doesn't exist
**Root Cause**: Tests written before implementation or implementation changed
**Impact**: 5+ test failures in Priority 1 module

### 3. Top 3 Mocking Issues to Fix

#### Issue #1: Non-existent Method Calls
```python
# test_cowrie_schema.py
event_type = schema.extract_event_type(event)  # ❌ Method doesn't exist
```
**Fix**: Either implement the method or update test to use existing methods

#### Issue #2: Heavy Mocking in cli/ingest.py
```python
# All tests mock everything, no actual code execution
with patch('cowrieprocessor.cli.ingest.some_function') as mock_func:
    # Tests pass but no coverage collected
```
**Fix**: Add tests that actually execute the CLI code paths

#### Issue #3: Fixture/Mock Setup Issues
**Evidence**: Multiple test failures in bulk_loader and db_engine tests
**Likely Cause**: Mock objects not properly configured for current implementation
**Fix**: Update mock setup to match current code structure

## Phase 1 Strategy for Mocking Issues

### 15-Minute Fix Rule
For each failing test:
1. **Understand intent** - What is the test trying to verify?
2. **Fix the mock** - Update to match current implementation
3. **Verify passes** - Ensure it tests the right thing
4. **Move on** - Don't get stuck debugging

### If Unfixable in 15 Minutes
```python
@pytest.mark.skip(reason="Legacy mock issue - Phase 1 priority")
```

## Immediate Actions for Phase 1

### Day 1: loader/cowrie_schema.py
1. **Fix existing test mocks** (30 minutes)
   - Update method calls to match actual implementation
   - Fix fixture setup issues
2. **Add new validation tests** (2 hours)
   - Test actual event validation logic
   - Cover error paths and edge cases
3. **Target**: 85% coverage for this module

### Priority Order
1. **cli/ingest.py** - Add real tests (currently 0% actual coverage)
2. **loader/cowrie_schema.py** - Fix mocks + add new tests
3. **loader/bulk.py** - Fix mocks + add error path tests
4. **loader/delta.py** - Fix mocks + add checkpoint tests

## Success Metrics
- [ ] All Priority 1 modules have working tests
- [ ] Coverage collected for all Priority 1 modules
- [ ] Mocking issues resolved or skipped
- [ ] New tests cover critical code paths

---

**Last Updated**: 2024-12-19
**Status**: Ready for Phase 1 execution
