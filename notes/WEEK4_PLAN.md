# Week 4 Plan: Coverage Push to 65%

**Date Range**: October 25-29, 2025 (Days 16-20)
**Starting Coverage**: 55%
**Target Coverage**: 62-65%
**Required Gain**: 7-10 percentage points
**Days Available**: 5 days

---

## Executive Summary

Week 4 represents the final push of the 4-week test coverage campaign. With a starting point of 55% and a target of 62-65%, this week requires strategic focus on high-ROI modules. The plan prioritizes CLI modules with substantial uncovered code and clear test boundaries.

### Week 4 Strategy

**Approach**: Quality over quantity, continued strategic module selection
**Key Principle**: Focus on modules with 30-60% coverage (highest ROI)
**Risk Management**: Adjust targets daily based on actual progress

---

## Current State Assessment

### Week 3 End Status
- **Overall Coverage**: 55% (10,239 statements, 4,595 missed)
- **Tests Created Week 3**: 52 new tests (100% passing)
- **Test Suite Health**: 801 passing, 92 failing (documented technical debt)
- **Momentum**: Strong (exceeded Day 14 target by 43 points)

### High-Value Target Modules

Based on coverage analysis, the following modules offer best ROI:

#### Priority 1: report.py (Target: Days 16-17)
```
Module: cowrieprocessor/cli/report.py
Current Coverage: 63% (380 statements, 140 missed)
Target Coverage: 85%
Potential Gain: +22% module coverage
Overall Impact: ~2.0% project coverage
Estimated Tests: 25-30 tests
Complexity: Medium-High
```

**Why Priority 1**:
- Large module (380 statements)
- Already 63% covered (existing foundation)
- CLI testing patterns established
- Clear test boundaries (report generation functions)
- High impact on project coverage (~2%)

**Functions to Target**:
- Report generation and formatting
- Elasticsearch integration
- Per-sensor reporting
- Aggregate reporting
- JSON/HTML output formatting

---

#### Priority 2: analyze.py (Target: Day 18)
```
Module: cowrieprocessor/cli/analyze.py
Current Coverage: 27% (512 statements, 375 missed)
Target Coverage: 60%
Potential Gain: +33% module coverage
Overall Impact: ~2.5% project coverage
Estimated Tests: 30-35 tests
Complexity: Medium
```

**Why Priority 2**:
- Very large module (512 statements)
- Low current coverage (27%) = high ROI
- Longtail analysis CLI (recently built, should be testable)
- High impact potential (~2.5% project coverage)

**Functions to Target**:
- Longtail query and analysis commands
- Session filtering and analysis
- Detection summary printing
- Anomaly reporting

---

#### Priority 3: cowrie_db.py (Target: Day 19)
```
Module: cowrieprocessor/cli/cowrie_db.py
Current Coverage: 49% (1,308 statements, 664 missed)
Target Coverage: 65%
Potential Gain: +16% module coverage
Overall Impact: ~2.5% project coverage
Estimated Tests: 25-30 tests
Complexity: Medium-High
```

**Why Priority 3**:
- Largest single module (1,308 statements)
- Already 49% covered (foundation exists)
- Database operations are testable
- Massive impact potential (~2.5% project coverage)
- Some tests exist (92 failures include cowrie_db tests)

**Functions to Target**:
- Migration operations
- Database validation
- Backup/restore operations
- Health checks
- Schema verification

---

#### Priority 4: enrich_passwords.py (Backup - Day 20)
```
Module: cowrieprocessor/cli/enrich_passwords.py
Current Coverage: 35% (672 statements, 434 missed)
Target Coverage: 60%
Potential Gain: +25% module coverage
Overall Impact: ~2.0% project coverage
Estimated Tests: 25-30 tests
Complexity: Medium
```

**Why Priority 4 (Backup)**:
- Large module (672 statements)
- HIBP password enrichment (recent feature)
- Moderate current coverage (35%)
- Good ROI (~2% project coverage)

**Functions to Target**:
- Password enrichment commands
- HIBP API integration
- Password pruning
- Top passwords reporting

---

## Day-by-Day Plan

### Day 16 (October 25): report.py Part 1

**Target**: +1.0% overall coverage (55% → 56%)

**Work Plan**:
1. **Analysis** (30 minutes):
   - Read cowrieprocessor/cli/report.py (380 lines)
   - Identify top 5-7 uncovered functions
   - Review existing report CLI tests

2. **Test Implementation** (2.5 hours):
   - Create/extend tests/unit/test_report_cli.py
   - Target: 15-18 tests for core report generation
   - Focus areas:
     - Report building and formatting
     - Per-sensor vs aggregate reports
     - JSON output formatting
     - Error handling

3. **Expected Outcome**:
   - report.py: 63% → 75% (+12%)
   - Overall: 55% → 56% (+1%)

---

### Day 17 (October 26): report.py Part 2 + analyze.py Start

**Target**: +1.5% overall coverage (56% → 57.5%)

**Work Plan**:
1. **Complete report.py** (1.5 hours):
   - Add 10-12 more tests
   - Target: report.py 75% → 85% (+10%)
   - Focus areas:
     - Elasticsearch publishing
     - HTML report generation
     - Edge cases and error paths

2. **Start analyze.py** (1.5 hours):
   - Read cowrieprocessor/cli/analyze.py (512 lines)
   - Identify priority functions
   - Create initial 10-12 tests
   - Target: analyze.py 27% → 40% (+13%)

3. **Expected Outcome**:
   - report.py: 75% → 85% (+10%)
   - analyze.py: 27% → 40% (+13%)
   - Overall: 56% → 57.5% (+1.5%)

---

### Day 18 (October 27): analyze.py Complete

**Target**: +2.0% overall coverage (57.5% → 59.5%)

**Work Plan**:
1. **Complete analyze.py** (3 hours):
   - Add 20-25 more tests
   - Target: analyze.py 40% → 60% (+20%)
   - Focus areas:
     - Longtail query functions
     - Session analysis and filtering
     - Detection summary printing
     - Anomaly reporting
     - Command-line parsing

2. **Expected Outcome**:
   - analyze.py: 40% → 60% (+20%)
   - Overall: 57.5% → 59.5% (+2%)

---

### Day 19 (October 28): cowrie_db.py

**Target**: +1.5% overall coverage (59.5% → 61%)

**Work Plan**:
1. **cowrie_db.py testing** (3 hours):
   - Focus on untested/failing functions
   - Target: cowrie_db.py 49% → 65% (+16%)
   - Add 20-25 tests covering:
     - Database validation functions
     - Backup operations
     - Health check functions
     - Schema verification
     - Note: Some tests may already exist (92 failures)

2. **Expected Outcome**:
   - cowrie_db.py: 49% → 65% (+16%)
   - Overall: 59.5% → 61% (+1.5%)

---

### Day 20 (October 29): Polish, Buffer, and Summary

**Target**: Reach 62% minimum, ideally 63-65%

**Work Plan**:
1. **Coverage Gap Analysis** (30 minutes):
   - Run final coverage report
   - Identify any quick wins for remaining gap

2. **Option A - If at 61%** (2 hours):
   - Add 10-15 tests to enrich_passwords.py
   - Target: +1-2% overall coverage
   - Final: 62-63%

3. **Option B - If at 60% or below** (2.5 hours):
   - Focus on highest ROI remaining functions
   - Mix of enrich_passwords.py and other CLI modules
   - Target: +2% overall coverage
   - Final: 62%

4. **Week 4 Summary Creation** (1 hour):
   - Comprehensive Week 4 documentation
   - 4-week campaign retrospective
   - Maintenance strategy planning

5. **Expected Outcome**:
   - Overall: 61% → 62-65%
   - Week 4 and full campaign summary complete

---

## Projected Outcomes

### Conservative Estimate
```
Day 16: 55% → 56% (+1.0%)  [report.py Part 1]
Day 17: 56% → 57.5% (+1.5%) [report.py + analyze.py start]
Day 18: 57.5% → 59.5% (+2.0%) [analyze.py complete]
Day 19: 59.5% → 61% (+1.5%)  [cowrie_db.py]
Day 20: 61% → 62% (+1.0%)    [buffer + polish]

Final: 62% total coverage (+7% from Week 3 end)
```

### Optimistic Estimate
```
Day 16: 55% → 56.5% (+1.5%)  [report.py Part 1 + bonus]
Day 17: 56.5% → 58% (+1.5%)  [report.py + analyze.py]
Day 18: 58% → 60.5% (+2.5%)  [analyze.py + overflow]
Day 19: 60.5% → 62.5% (+2.0%) [cowrie_db.py + bonus]
Day 20: 62.5% → 65% (+2.5%)  [enrich_passwords.py]

Final: 65% total coverage (+10% from Week 3 end)
```

### Realistic Target: **62-63%**
Week 4 will likely land in the 62-63% range, representing a successful 4-week campaign (49% → 62%, +13% total gain).

---

## Risk Assessment

### High-Risk Factors

1. **Pre-existing Test Failures**:
   - **Risk**: 92 failing tests may interfere with new test execution
   - **Impact**: Medium
   - **Mitigation**: Isolate new tests in separate files, use tmp_path fixtures

2. **CLI Complexity**:
   - **Risk**: CLI modules may have complex dependencies
   - **Impact**: Medium
   - **Mitigation**: Use mocking for external dependencies, focus on core logic

3. **Time Constraints**:
   - **Risk**: Large modules may take longer than estimated
   - **Impact**: High
   - **Mitigation**: Adjust targets daily, focus on highest-ROI functions first

4. **Database Operations**:
   - **Risk**: cowrie_db.py testing may reveal architectural issues
   - **Impact**: Medium
   - **Mitigation**: Start with simpler functions, escalate blockers immediately

### Mitigation Strategies

1. **Daily Progress Reviews**:
   - Review coverage gains at end of each day
   - Adjust Day N+1 plan based on Day N results
   - Be willing to swap Priority 2/3/4 modules

2. **Test Isolation**:
   - Continue using tmp_path for database fixtures
   - Avoid mocking own code
   - Create separate test files to avoid interference

3. **ROI Focus**:
   - Always test highest-ROI functions first
   - If module proves difficult, move to next priority
   - Track actual vs estimated time for each module

4. **Buffer Day Strategy**:
   - Day 20 is explicitly a buffer/polish day
   - Can be used to fill coverage gaps
   - Ensures Week 4 ends successfully even if Days 16-19 underperform

---

## Success Criteria

### Minimum Success (Must-Have)
- ✅ Reach 62% overall coverage
- ✅ All new tests passing (100% success rate)
- ✅ Week 4 comprehensive summary document
- ✅ 4-week campaign retrospective

### Target Success (Should-Have)
- ✅ Reach 63-64% overall coverage
- ✅ report.py: 63% → 85%
- ✅ analyze.py: 27% → 60%
- ✅ cowrie_db.py: 49% → 65%
- ✅ 90-110 new tests created in Week 4

### Stretch Success (Nice-to-Have)
- ✅ Reach 65% overall coverage
- ✅ enrich_passwords.py: 35% → 60%
- ✅ Fix 5-10 pre-existing test failures
- ✅ Maintenance strategy document

---

## Testing Patterns & Best Practices

Continue Week 3's successful patterns:

### Test Characteristics
1. **Real Database Fixtures**: Use tmp_path with actual databases
2. **No Mocking Own Code**: Only mock external dependencies
3. **Type Safety**: Full type annotations
4. **Clear Documentation**: Google-style docstrings with Given-When-Then
5. **Test Isolation**: Each test creates its own fixtures

### Test Naming Convention
```python
def test_<module>_<function>_<behavior>(tmp_path: Path) -> None:
    """Test <function> <behavior>.

    Given: <initial conditions>
    When: <action taken>
    Then: <expected outcome>
    """
```

### Module Test File Pattern
```
tests/unit/test_report_cli.py
tests/unit/test_analyze_cli.py
tests/unit/test_cowrie_db_cli.py  (may already exist)
tests/unit/test_enrich_passwords_cli.py  (may already exist)
```

---

## Daily Workflow

### Morning (Start of Day)
1. Review previous day's results
2. Adjust current day's plan if needed
3. Read target module(s) thoroughly
4. Identify top 5-7 functions to test

### During Implementation
1. Create tests in batches of 5-7
2. Run tests after each batch
3. Fix failures immediately
4. Run coverage after each batch
5. Track actual vs estimated time

### Evening (End of Day)
1. Run full coverage report
2. Document day's achievements
3. Update overall Week 4 progress
4. Plan next day's work
5. Commit all changes

---

## Contingency Plans

### If Behind Schedule (Day 18 checkpoint)

**Scenario**: Day 18 ends at 58% instead of 59.5%

**Action Plan**:
1. Skip cowrie_db.py (Priority 3)
2. Day 19: Focus on enrich_passwords.py (smaller, higher ROI)
3. Day 20: Identify 3-5 quick-win functions across modules
4. Revised target: 61-62%

---

### If Ahead of Schedule (Day 18 checkpoint)

**Scenario**: Day 18 ends at 60.5% instead of 59.5%

**Action Plan**:
1. Continue with cowrie_db.py as planned (Day 19)
2. Day 20: Complete enrich_passwords.py fully
3. Stretch goal: Fix 5-10 pre-existing test failures
4. Revised target: 64-65%

---

### If Module Proves Difficult

**Scenario**: report.py takes 1.5x estimated time on Day 16

**Action Plan**:
1. Set hard time limit (4 hours max per module)
2. Test highest-ROI functions first
3. If time expires, move to next priority module
4. Return to difficult module on Day 20 if time permits
5. Document blockers for future work

---

## Module Analysis Details

### report.py (Priority 1)

**Current State**:
```python
# cowrieprocessor/cli/report.py
Statements: 380
Missed: 140
Coverage: 63%
```

**Key Functions** (estimated):
1. `build_report()` - Main report builder (high priority)
2. `format_json_output()` - JSON formatting
3. `format_html_output()` - HTML formatting
4. `publish_to_elasticsearch()` - ES integration
5. `generate_per_sensor_report()` - Per-sensor logic
6. `generate_aggregate_report()` - Aggregate logic
7. Helper functions for metrics calculation

**Testing Strategy**:
- Use real database fixtures with test data
- Mock Elasticsearch client (external dependency)
- Test report output validation (JSON/HTML structure)
- Test per-sensor vs aggregate logic differences

---

### analyze.py (Priority 2)

**Current State**:
```python
# cowrieprocessor/cli/analyze.py
Statements: 512
Missed: 375
Coverage: 27%
```

**Key Functions** (estimated):
1. `query_sessions_for_analysis()` - Main query function
2. `print_longtail_summary()` - Output formatting
3. `analyze_rare_commands()` - Rare command detection
4. `filter_sessions_by_criteria()` - Session filtering
5. CLI argument parsing and validation
6. Error handling and reporting

**Testing Strategy**:
- Create database fixtures with longtail analysis data
- Test query filtering logic (days_back, sensor_filter)
- Test output formatting (various detection types)
- Test CLI argument combinations

---

### cowrie_db.py (Priority 3)

**Current State**:
```python
# cowrieprocessor/cli/cowrie_db.py
Statements: 1,308
Missed: 664
Coverage: 49%
```

**Key Functions** (estimated):
1. `validate_schema()` - Schema validation
2. `create_backup()` - Database backup
3. `restore_backup()` - Database restore
4. `check_integrity()` - Database health check
5. `optimize_database()` - Performance optimization
6. `analyze_data_quality()` - Data quality checks
7. `migrate_to_postgresql()` - PostgreSQL migration

**Testing Strategy**:
- Use tmp_path for isolated database testing
- Test backup/restore roundtrip
- Test schema validation logic
- Test database health checks
- May need to work around existing 92 test failures

**Note**: Some tests may already exist but are failing. Review existing test_cowrie_db_cli.py before creating new tests.

---

## Documentation Requirements

### Daily Summaries (Optional)
- Brief progress notes
- Coverage gains
- Issues encountered
- Time actual vs estimated

### Week 4 Summary (Required - Day 20)
Must include:
1. Overall Week 4 metrics
2. Day-by-day progress breakdown
3. Module-specific achievements
4. Challenges and solutions
5. Comparison to Week 3

### 4-Week Campaign Retrospective (Required - Day 20)
Must include:
1. Total coverage gain (49% → final%)
2. Tests created across all 4 weeks
3. Key achievements and milestones
4. Lessons learned
5. Production bugs discovered
6. Technical debt status
7. Maintenance strategy going forward

---

## Post-Week 4 Planning

### Maintenance Strategy

**Goal**: Maintain 62-65% coverage as code evolves

**Approach**:
1. **New Code Coverage Rule**: All new features require 70%+ test coverage
2. **Pre-commit Hooks**: Run coverage on changed files
3. **Monthly Reviews**: Review overall coverage trends
4. **Technical Debt Sprints**: Quarterly sprints to fix failing tests

### Technical Debt Strategy

**92 Failing Tests**:
1. Categorize failures by severity (blocker, major, minor)
2. Create GitHub issues for each category
3. Assign to future sprints (Weeks 5-6)
4. Prioritize blockers that prevent new feature testing

### Future Coverage Goals

**Long-term targets**:
- **3 months**: 70% coverage
- **6 months**: 75% coverage
- **12 months**: 80% coverage

**Approach**:
- Sustainable pace (2-3 percentage points per month)
- Focus on new features
- Incremental technical debt reduction

---

## Key Metrics to Track

### Daily Metrics
- Overall coverage percentage
- Module coverage percentages
- Tests created
- Tests passing/failing
- Time spent vs estimated

### Weekly Metrics
- Week 4 coverage gain (+X%)
- Total tests created in Week 4
- Test success rate (should be 100%)
- Module completion (# of Priority 1-4 completed)

### Campaign Metrics (4 weeks total)
- Total coverage gain (49% → final%)
- Total tests created (all 4 weeks)
- Production bugs discovered
- Technical debt documented
- Overall campaign ROI

---

## Conclusion

Week 4 represents the culmination of a month-long test coverage campaign. With a realistic target of 62-63% (optimistic 65%), success depends on:

1. **Strategic Focus**: Prioritize high-ROI modules (report.py, analyze.py, cowrie_db.py)
2. **Quality Maintenance**: Continue 100% test success rate from Week 3
3. **Flexibility**: Adjust daily plans based on actual progress
4. **Documentation**: Comprehensive summaries enable future work

The plan is designed to be achievable while maintaining the quality standards established in Week 3. By focusing on CLI modules with substantial uncovered code, Week 4 can deliver measurable value and position the project for sustainable long-term coverage growth.

**Week 4 Status**: 🎯 READY TO BEGIN

---

*Document created: October 24, 2025*
*Author: Claude Code (AI Assistant)*
*Project: cowrieprocessor test coverage improvement campaign*
