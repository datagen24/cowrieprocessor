# Day 24-25 High-Priority Coverage Targets

**Date**: October 25, 2025
**Sprint**: Week 5-6 (Day 24-25)
**Current Coverage**: 54% (5,990/10,994 statements)
**Target**: 62-63% (+8-9%)
**Statements Needed**: ~900 statements

---

## Coverage Analysis Summary

**Total Tests Run** (unit tests only): 893 tests (58 failed, 835 passed)
**Coverage Method**: `uv run coverage run --source=cowrieprocessor -m pytest tests/unit/`

**Note**: Integration tests will add additional coverage - full test suite being measured separately.

---

## High-Priority Targets (>100 statements, <30% coverage)

### Tier 1: CRITICAL (0% coverage, modern code)

| Module | Statements | Coverage | Priority | Rationale |
|--------|-----------|----------|----------|-----------|
| **cli/enrich_ssh_keys.py** | 375 | 0% | ⭐⭐⭐⭐⭐ | CLI command for SSH key enrichment - production code |
| **loader/session_parser.py** | 190 | 0% | ⭐⭐⭐⭐ | Core loader component - migrated from session_enumerator |
| **loader/dlq_cli.py** | 160 | 0% | ⭐⭐⭐ | DLQ command-line interface |
| **loader/dlq_enhanced_cli.py** | 160 | 0% | ⭐⭐⭐ | Enhanced DLQ CLI |
| **loader/improved_hybrid.py** | 167 | 0% | ⭐⭐⭐ | Hybrid loader implementation |
| **cli/file_organizer.py** | 103 | 0% | ⭐⭐ | File organization utility |
| **db/enhanced_dlq_models.py** | 119 | 0% | ⭐⭐ | Enhanced DLQ database models |

### Tier 2: LOW COVERAGE (>10%, <30%)

| Module | Statements | Coverage | Priority | Rationale |
|--------|-----------|----------|----------|-----------|
| **enrichment/handlers.py** | 498 | 13.05% | ⭐⭐⭐⭐⭐ | HIGHEST VALUE - Modern enrichment orchestration (old tests archived) |

---

## Recommended Day 24-25 Strategy

### Day 24 Focus (6-8 hours)

**Target #1: enrichment/handlers.py (498 statements, 13% → 60%)**
- **Rationale**: Largest module, modern code, old tests archived
- **Expected Gain**: ~235 statements (+2.1% project coverage)
- **Tests to Write**: 15-20 comprehensive tests
- **Effort**: High (complex enrichment orchestration)

**Target #2: cli/enrich_ssh_keys.py (375 statements, 0% → 50%)**
- **Rationale**: CLI command, production code, medium complexity
- **Expected Gain**: ~188 statements (+1.7% project coverage)
- **Tests to Write**: 12-15 CLI integration tests
- **Effort**: Medium (CLI testing patterns established)

**Day 24 Total Expected**: +423 statements (+3.8% coverage) → **57.8%**

### Day 25 Focus (6-8 hours)

**Target #3: loader/session_parser.py (190 statements, 0% → 70%)**
- **Rationale**: Core loader component, migrated from legacy
- **Expected Gain**: ~133 statements (+1.2% project coverage)
- **Tests to Write**: 10-12 parser tests
- **Effort**: Medium (parser logic testing)

**Target #4: loader/dlq_cli.py + dlq_enhanced_cli.py (320 statements combined, 0% → 50%)**
- **Rationale**: DLQ CLI tools, complementary functionality
- **Expected Gain**: ~160 statements (+1.5% project coverage)
- **Tests to Write**: 10-12 CLI tests
- **Effort**: Medium (similar to enrich_ssh_keys patterns)

**Day 25 Total Expected**: +293 statements (+2.7% coverage) → **60.5%**

**Days 24-25 Combined**: +716 statements (+6.5% coverage) → **60.5% total**

---

## Secondary Targets (If Time Permits)

| Module | Statements | Coverage | Potential Gain |
|--------|-----------|----------|----------------|
| loader/improved_hybrid.py | 167 | 0% | +84 statements (50% target) |
| db/enhanced_dlq_models.py | 119 | 0% | +60 statements (50% target) |
| cli/file_organizer.py | 103 | 0% | +52 statements (50% target) |

**Secondary Targets Total**: +196 statements (+1.8% coverage) → **62.3% if all completed**

---

## Risk Assessment

### High-Confidence Targets ✅
- **enrichment/handlers.py**: Well-documented, clear functionality
- **cli/enrich_ssh_keys.py**: CLI patterns established in codebase
- **loader/session_parser.py**: Parser logic, testable

###Medium-Confidence Targets ⚠️
- **DLQ CLI tools**: May have complex dependencies
- **improved_hybrid.py**: "Improved" suggests experimental code

### Exclusions ❌
- **storage.py**: Shows 0% in unit tests, but 50% in integration tests (tested)
- **Deprecated modules**: Any modules in archive/ or referenced in archive/README.md

---

## Execution Plan

### Day 24 Morning (3 hours)
1. **Read and analyze enrichment/handlers.py** (30 min)
   - Identify main classes and functions
   - Map dependencies and external APIs
   - Plan test scenarios (happy path, error cases, edge cases)

2. **Write tests for enrichment/handlers.py** (2.5 hours)
   - Target: 15-20 tests
   - Focus: EnrichmentService class, handler orchestration
   - Aim: 13% → 60% coverage

### Day 24 Afternoon (4 hours)
3. **Read and analyze cli/enrich_ssh_keys.py** (30 min)
   - Understand CLI argument parsing
   - Identify main execution flow
   - Review existing CLI test patterns

4. **Write tests for cli/enrich_ssh_keys.py** (3 hours)
   - Target: 12-15 tests
   - Focus: CLI commands, argument validation, integration
   - Aim: 0% → 50% coverage

5. **Measure and commit Day 24 progress** (30 min)
   - Run coverage: `uv run coverage run -m pytest tests/unit/`
   - Verify: 54% → 57-58%
   - Commit: tests + summary

### Day 25 Morning (3 hours)
6. **Read and analyze loader/session_parser.py** (30 min)
7. **Write tests for session_parser.py** (2.5 hours)
   - Target: 10-12 tests
   - Aim: 0% → 70% coverage

### Day 25 Afternoon (4 hours)
8. **Write tests for DLQ CLI tools** (3 hours)
   - dlq_cli.py and dlq_enhanced_cli.py
   - Target: 10-12 tests
   - Aim: 0% → 50% coverage

9. **Measure and commit Day 25 progress** (1 hour)
   - Run coverage: verify 60-62%
   - Generate HTML report
   - Create DAY24-25_SUMMARY.md

---

## Success Criteria

**Minimum Success** (Days 24-25):
- ✅ Coverage: 54% → 60% (+6%)
- ✅ Tests written: 40-50 new tests
- ✅ All new tests passing
- ✅ Code quality maintained (type hints, docstrings)

**Target Success**:
- ✅ Coverage: 54% → 62% (+8%)
- ✅ Tests written: 50-60 new tests
- ✅ 100% pass rate

**Stretch Goal**:
- ✅ Coverage: 54% → 63% (+9%)
- ✅ Additional secondary targets completed
- ✅ Days 29-30 buffer reduced

---

## Dependencies and Blockers

**Potential Blockers**:
1. **enrichment/handlers.py complexity** - May require more time than estimated
2. **CLI testing environment** - May need database/config setup
3. **DLQ dependencies** - May require complex test fixtures

**Mitigation**:
- Start with highest-ROI target (handlers.py) to maximize early gains
- Use existing CLI test patterns from test_cowrie_db.py, test_analyze.py
- Create reusable fixtures for DLQ testing

---

## Post-Day-25 Assessment

After Day 25 completion:

**If 60-62% achieved** ✅:
- Proceed to Days 26-28 test fixes
- Plan Days 29-30 final push to 65%

**If <60% achieved** ⚠️:
- Reassess targets
- Consider extending coverage push to Day 26
- Adjust Week 6 timeline

**If >62% achieved** 🎉:
- Days 29-30 may not be needed
- Can focus entirely on test fixes in Days 26-28
- Potential early completion

---

**Report Generated**: 2025-10-25
**Author**: Claude Code (Day 24 Coverage Campaign)
**Status**: READY TO EXECUTE
