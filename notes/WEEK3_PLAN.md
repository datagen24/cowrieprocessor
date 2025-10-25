# Week 3 Plan - Coverage Improvement Project

**Week 3 Dates**: Days 11-15 (Monday-Friday)
**Starting Coverage**: 53%
**Target Coverage**: 63-65%
**Expected Gain**: +10-12%

---

## Week 3 Overview

Week 3 has **two critical phases**:

### Phase 1: Fix Test Suite (Days 11-12)
**CRITICAL PRIORITY** - Fix 97 pre-existing test failures

**Expected Impact**: +8-10% total coverage (unmasking existing coverage)
**Target Coverage After Fixes**: ~61%

### Phase 2: Continue Module Coverage (Days 13-15)
Continue improving module coverage with new tests

**Expected Impact**: +2-4% additional coverage
**Target Coverage Week 3 End**: 63-65%

---

## Phase 1: Fix Test Suite (Days 11-12)

### Day 11 (Monday) - Analysis & Initial Fixes

**Morning Session (4 hours)**:

1. **Analyze failing tests** (1 hour)
   ```bash
   # Run full test suite and capture failures
   uv run pytest tests/unit/ -v --tb=short > test_failures_analysis.txt

   # Extract failure patterns
   grep "FAILED" test_failures_analysis.txt | wc -l
   grep "FAILED" test_failures_analysis.txt | cut -d':' -f2 | sort | uniq -c
   ```

2. **Categorize failures** (1 hour)
   - Database/fixture issues
   - Import errors
   - Assertion errors
   - Setup/teardown issues
   - Mock configuration issues

3. **Document failure patterns** (1 hour)
   Create `test_failures_categorized.md`:
   - List all 97 failures
   - Group by category
   - Identify root causes
   - Plan fix strategy

4. **Begin systematic fixes** (1 hour)
   - Start with most common pattern
   - Fix 10-15 tests

**Afternoon Session (4 hours)**:

5. **Continue fixing tests** (3 hours)
   - Target: Fix 30-40 more tests
   - Run tests incrementally to verify fixes
   - Document any code issues discovered

6. **Mid-week checkpoint** (1 hour)
   - Count remaining failures
   - Assess progress
   - Adjust Day 12 plan if needed

**Day 11 Target**:
- ✅ 50-60 of 97 tests fixed
- ✅ Failure patterns documented
- ✅ Strategy for Day 12 clear

---

### Day 12 (Tuesday) - Complete Test Fixes

**Morning Session (4 hours)**:

1. **Continue fixing tests** (3 hours)
   - Fix remaining 40-50 tests
   - Target: All tests passing by lunch

2. **Verify fixes** (1 hour)
   ```bash
   # Run full test suite
   uv run pytest tests/unit/ -v

   # Should see: ALL TESTS PASSING
   # Example: 750 passed, 0 failed
   ```

**Afternoon Session (4 hours)**:

3. **Run comprehensive coverage** (1 hour)
   ```bash
   # Clean slate
   rm -f .coverage .coverage.*

   # Run full suite with coverage
   uv run coverage run --source=cowrieprocessor -m pytest tests/unit/

   # Generate report
   uv run coverage report > coverage_after_test_fixes.txt

   # Check total coverage - should be ~61%!
   cat coverage_after_test_fixes.txt | grep "TOTAL"
   ```

4. **Analyze coverage jump** (1 hour)
   - Compare before/after fixing tests
   - Document which modules gained coverage
   - Verify Week 1 and Week 2 work is now visible

5. **Create test fix summary** (2 hours)
   Create `test_fixes_summary.md`:
   - List all fixes applied
   - Document coverage gain (+8-10% expected)
   - Identify any remaining issues
   - Validate Week 1 and Week 2 achievements

**Day 12 Target**:
- ✅ All 97 test failures fixed
- ✅ Total coverage ~61% (up from 53%)
- ✅ Full test suite passing (750/750)
- ✅ Ready for Phase 2

---

## Phase 2: Module Coverage (Days 13-15)

### Day 13 (Wednesday) - migrations.py

**Target**: migrations.py 47% → 60% (+13%)

**Morning Session**:

1. **Analyze migrations.py functions** (1 hour)
   ```bash
   # Find all functions
   grep -n "^def " cowrieprocessor/db/migrations.py

   # Document function sizes
   # Create day13_migrations_analysis.md
   ```

2. **Identify PRIORITY functions** (30 min)
   - PRIORITY 1: Functions >80 lines
   - PRIORITY 2: Functions 60-80 lines
   - Document sizes and test plans

3. **Write 5-6 tests** (2.5 hours)
   - Focus on largest functions first
   - Target: +6-7% coverage

**Afternoon Session**:

4. **Write 5-6 more tests** (3 hours)
   - Continue with PRIORITY 2 functions
   - Target: Additional +6-7% coverage

5. **Verify and document** (1 hour)
   - Run tests: `uv run pytest tests/unit/test_migrations.py -v`
   - Check coverage: `uv run coverage report --include="**/migrations.py"`
   - Target: migrations.py at 60%+

**Day 13 Target**:
- ✅ 10-12 tests added for migrations.py
- ✅ migrations.py: 47% → 60%
- ✅ All tests passing, 0 errors

---

### Day 14 (Thursday) - ssh_key_analytics.py

**Target**: ssh_key_analytics.py 32% → 55% (+23%)

**Morning Session**:

1. **Analyze ssh_key_analytics.py** (1 hour)
   ```bash
   grep -n "^def " cowrieprocessor/enrichment/ssh_key_analytics.py
   # Create day14_ssh_key_analytics_analysis.md
   ```

2. **Write 6-8 tests** (3 hours)
   - Focus on largest analytical functions
   - Target: +12-15% coverage

**Afternoon Session**:

3. **Write 6-8 more tests** (3 hours)
   - Continue with medium-large functions
   - Target: Additional +8-10% coverage

4. **Verify and document** (1 hour)
   - Run tests and check coverage
   - Target: ssh_key_analytics.py at 55%+

**Day 14 Target**:
- ✅ 12-16 tests added for ssh_key_analytics.py
- ✅ ssh_key_analytics.py: 32% → 55%
- ✅ Total coverage: ~63%

---

### Day 15 (Friday) - Week 3 Wrap-Up

**Option A: Continue longtail.py** (if ahead of schedule)

**Target**: longtail.py 61% → 70% (+9%)

**Work**:
- Add 8-10 tests for remaining medium functions
- Target untested functions 40-60 lines
- Goal: Push longtail.py to 70%

**Option B: Continue botnet.py** (if need more coverage)

**Target**: botnet.py 45% → 60% (+15%)

**Work**:
- Add 10-12 tests for helper functions
- Test the 11 small functions (<60 lines)
- Goal: Push botnet.py to 60%

**Option C: Week 3 Summary** (if targets met)

**Activities**:
1. Create comprehensive Week 3 summary
2. Document test fixes in detail
3. Plan Week 4 (final week)
4. Assess project completion trajectory

**Day 15 Target**:
- ✅ Week 3 summary created
- ✅ Total coverage: 63-65%
- ✅ Week 4 plan ready
- ✅ All tests passing

---

## Week 3 Success Criteria

### Minimum Success (Pass)
- ✅ All 97 test failures fixed
- ✅ Total coverage: 61% (after test fixes)
- ✅ Total coverage: 63% (after new tests)
- ✅ migrations.py: 60%+
- ✅ 100% test pass rate

### Target Success (Good)
- ✅ Total coverage: 63%
- ✅ migrations.py: 60%+
- ✅ ssh_key_analytics.py: 55%+
- ✅ 25-30 tests added
- ✅ 0 quality errors

### Stretch Success (Exceptional)
- ✅ Total coverage: 65%
- ✅ migrations.py: 65%+
- ✅ ssh_key_analytics.py: 60%+
- ✅ longtail.py or botnet.py improved further
- ✅ 30-35 tests added

---

## Critical Success Factors

### Phase 1 Critical Factors

1. **Systematic Approach**: Don't rush fixes, analyze patterns first
2. **Test Incrementally**: Fix a few, test, repeat
3. **Document Thoroughly**: Track what was fixed and why
4. **Verify Coverage Jump**: Confirm +8-10% gain after fixes

### Phase 2 Critical Factors

1. **Maintain Quality**: Keep 100% pass rate
2. **Target Large Functions**: Continue >60 line focus
3. **Efficient Testing**: Aim for 7-10 lines/test
4. **Daily Progress**: Don't fall behind schedule

---

## Risk Mitigation

### Potential Risks

1. **Test Fixes Take Longer**: May need more than 2 days
   - **Mitigation**: Start Day 11 with good analysis
   - **Backup**: Adjust Phase 2 schedule if needed

2. **Coverage Jump Less Than Expected**: May only gain +5-6%
   - **Mitigation**: Focus on high-value modules in Phase 2
   - **Backup**: Add Day 16 if Week 3 extends

3. **Complex Test Failures**: Some may require code changes
   - **Mitigation**: Document code issues, fix incrementally
   - **Backup**: Skip truly difficult tests, mark as known issues

4. **Time Pressure**: May not complete all planned modules
   - **Mitigation**: Prioritize migrations.py (highest value)
   - **Backup**: Move some work to Week 4

---

## Week 3 Daily Checklist

### Day 11 Checklist
- [ ] Run full test suite, capture failures
- [ ] Categorize all 97 failures
- [ ] Document failure patterns
- [ ] Fix 50-60 tests
- [ ] Create mid-week checkpoint

### Day 12 Checklist
- [ ] Fix remaining 40-50 tests
- [ ] Verify all tests passing (750/750)
- [ ] Run full coverage measurement
- [ ] Confirm coverage ~61% (+8-10%)
- [ ] Create test fix summary document

### Day 13 Checklist
- [ ] Analyze migrations.py functions
- [ ] Write 10-12 tests for migrations.py
- [ ] Verify migrations.py at 60%+
- [ ] All tests passing, 0 errors
- [ ] Create day13 summary

### Day 14 Checklist
- [ ] Analyze ssh_key_analytics.py functions
- [ ] Write 12-16 tests for ssh_key_analytics.py
- [ ] Verify ssh_key_analytics.py at 55%+
- [ ] Check total coverage ~63%
- [ ] Create day14 summary

### Day 15 Checklist
- [ ] Choose Option A, B, or C based on progress
- [ ] Complete chosen work
- [ ] Create comprehensive Week 3 summary
- [ ] Plan Week 4 in detail
- [ ] Verify total coverage 63-65%

---

## Expected Outcomes

### Week 3 End Coverage Projection

```
Total Coverage:
Week 2 End:     53%
After Fixes:    61% (+8%)
After Tests:    63-65% (+2-4%)

Module Coverage:
longtail.py:         61% → 70% (if worked on)
botnet.py:           45% → 60% (if worked on)
report.py:           63% (stable)
migrations.py:       47% → 60-65%
ssh_key_analytics:   32% → 55-60%
dlq_processor.py:    55% (stable)
```

### Week 3 Test Statistics

```
Tests Added:         25-35
Tests Passing:       750/750 (all fixed)
Quality Errors:      0
Efficiency Target:   7-10 lines/test average
```

---

## Week 4 Preview

### Week 4 Goals

**Coverage Target**: 65-68% (project goal)

**Remaining Work**:
1. Polish existing modules to 65-70%
2. Address low-coverage modules (<40%)
3. Final quality sweep
4. Project completion documentation

**Expected Test Count**: 40-50 additional tests

---

## Communication Plan

### Daily Standups

**Each Morning**:
- Review previous day's achievements
- Identify any blockers
- Confirm day's plan

**Each Evening**:
- Document day's work in summary
- Update coverage tracking
- Plan next day

### Weekly Checkpoints

**Mid-Week (Day 12)**:
- Assess Phase 1 completion
- Adjust Phase 2 if needed

**End-Week (Day 15)**:
- Create comprehensive Week 3 summary
- Plan Week 4 in detail
- Assess project completion trajectory

---

## Tools & Resources

### Coverage Commands

```bash
# Clean coverage data
rm -f .coverage .coverage.*

# Run full test suite with coverage
uv run coverage run --source=cowrieprocessor -m pytest tests/unit/

# Generate report
uv run coverage report

# Check specific module
uv run coverage report --include="**/migrations.py"

# Save report
uv run coverage report > coverage_dayX_final.txt
```

### Test Commands

```bash
# Run all tests
uv run pytest tests/unit/ -v

# Run specific test file
uv run pytest tests/unit/test_migrations.py -v

# Run with coverage
uv run pytest tests/unit/test_migrations.py --cov=cowrieprocessor --cov-report=term

# Quick run (no output)
uv run pytest tests/unit/ -q
```

### Quality Commands

```bash
# Check linting
uv run ruff check tests/unit/test_migrations.py

# Fix linting issues
uv run ruff check --fix tests/unit/test_migrations.py

# Check types
uv run mypy tests/unit/test_migrations.py
```

---

## Success Tracking

### Week 3 Scorecard Template

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Test Fixes | 97 | TBD | ⏳ |
| Coverage After Fixes | 61% | TBD | ⏳ |
| migrations.py | 60% | TBD | ⏳ |
| ssh_key_analytics | 55% | TBD | ⏳ |
| Total Coverage End | 63-65% | TBD | ⏳ |
| Tests Added | 25-35 | TBD | ⏳ |
| Pass Rate | 100% | TBD | ⏳ |
| Quality Errors | 0 | TBD | ⏳ |

---

## Appendix: Module Priorities

### High Priority (Week 3)
1. **migrations.py** - Core database functionality (47% → 60%)
2. **ssh_key_analytics.py** - Security analysis feature (32% → 55%)

### Medium Priority (Week 3 if time)
3. **longtail.py** - Continue polish (61% → 70%)
4. **botnet.py** - Continue improvement (45% → 60%)

### Lower Priority (Week 4)
5. **analyze.py** - CLI module (27% → 45%)
6. **cowrie_db.py** - Large module (46% → 55%)
7. **enrich_passwords.py** - Enrichment module (35% → 50%)

---

**Document Version**: 1.0
**Created**: End of Week 2, Day 10
**Status**: Ready for Execution
**Next Review**: Week 3 End (Day 15)

---

# 🎯 WEEK 3 PLAN - READY TO EXECUTE! 🎯
