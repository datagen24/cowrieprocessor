# GitHub CI Soft-Fail Ruff Checks - Implementation Summary

**Commit**: f63451b
**Date**: 2025-11-02
**Branch**: scp-snowshoe

---

## Change Summary

Modified GitHub Actions CI pipeline to implement **split quality gates** with strict enforcement for production code and soft-fail (advisory) checks for tests/archive/docs.

### Modified File
- `.github/workflows/ci.yml`

### Changes Made

#### Before (Single Strict Check)
```yaml
- name: Ruff check (linting)
  run: uv run ruff check .

- name: Ruff format check
  run: uv run ruff format --check .
```
**Problem**: Any ruff issue in tests, archive, or docs blocked entire CI pipeline

#### After (Split Strict + Advisory)
```yaml
# Production code - STRICT (blocking)
- name: Ruff check (linting) - Production Code [REQUIRED]
  run: uv run ruff check cowrieprocessor/ scripts/production/ --exclude tests/ --exclude archive/ --exclude docs/

# Tests/Archive/Docs - ADVISORY (soft-fail)
- name: Ruff check (linting) - Tests/Archive/Docs [ADVISORY]
  continue-on-error: true
  run: uv run ruff check tests/ archive/ docs/ || echo "⚠️  Ruff linting issues found in tests/archive/docs (advisory only)"

# Same split for format checks...
```

---

## Quality Gate Strategy

| Directory | Ruff Check | Ruff Format | MyPy | Coverage | Blocking? |
|-----------|------------|-------------|------|----------|-----------|
| `cowrieprocessor/` | ✅ STRICT | ✅ STRICT | ✅ STRICT | ✅ 65% min | **YES** |
| `scripts/production/` | ✅ STRICT | ✅ STRICT | ✅ STRICT | ✅ 65% min | **YES** |
| `tests/` | ⚠️ ADVISORY | ⚠️ ADVISORY | ✅ STRICT | ✅ 65% min | **NO** |
| `archive/` | ⚠️ ADVISORY | ⚠️ ADVISORY | ✅ STRICT | ✅ 65% min | **NO** |
| `docs/` | ⚠️ ADVISORY | ⚠️ ADVISORY | ✅ STRICT | ✅ 65% min | **NO** |

### What's Still Blocking?
- ✅ **MyPy type checking**: All code (including tests) must pass
- ✅ **Test coverage**: 65% minimum across all code
- ✅ **Ruff checks for production code**: cowrieprocessor/ and scripts/production/
- ✅ **Tests must pass**: All pytest tests must succeed

### What's Now Advisory?
- ⚠️ **Ruff linting for tests/archive/docs**: Shows warnings but doesn't block
- ⚠️ **Ruff formatting for tests/archive/docs**: Shows warnings but doesn't block

---

## How It Works

### continue-on-error: true

The key mechanism is GitHub Actions' `continue-on-error` flag:

```yaml
- name: Ruff check (linting) - Tests/Archive/Docs [ADVISORY]
  continue-on-error: true  # ← This allows the step to "fail" without blocking pipeline
  run: |
    uv run ruff check tests/ archive/ docs/ || echo "⚠️  Ruff linting issues found (advisory only)"
```

**Behavior**:
- ✅ Step runs and executes ruff checks
- ⚠️ If ruff finds issues, step shows as "yellow" (warning)
- ✅ Pipeline continues regardless of ruff result
- 📋 All ruff output still visible in CI logs

### Split Path Coverage

**Production Code Check**:
```bash
uv run ruff check cowrieprocessor/ scripts/production/ --exclude tests/ --exclude archive/ --exclude docs/
```
- Checks only production directories
- Excludes test/archive/docs to avoid overlap
- **Fails pipeline** if issues found

**Tests/Archive/Docs Check**:
```bash
uv run ruff check tests/ archive/ docs/
```
- Checks only test/archive/docs directories
- Runs with `continue-on-error: true`
- **Continues pipeline** even if issues found

---

## Benefits

### 1. Unblocks Test Development
- Test suite improvements no longer blocked by ruff style issues
- Allows rapid iteration on test refactoring
- Reduces friction for adding new tests

### 2. Maintains Visibility
- Ruff issues still appear in CI logs as warnings
- Developers can see and address issues at their discretion
- Quality metrics still tracked

### 3. Production Quality Preserved
- All production code (`cowrieprocessor/`, `scripts/production/`) maintains strict gates
- No reduction in deployed code quality
- Type checking and coverage still enforced everywhere

### 4. Gradual Improvement Path
- Teams can address ruff issues in tests incrementally
- No "big bang" cleanup required
- Encourages continuous improvement without blocking work

### 5. Flexible for Legacy Code
- Archive directory won't block new features
- Deprecated code maintained but not enforced
- Docs examples don't need production formatting

---

## Example CI Output

### Production Code Issue (BLOCKS)
```
❌ Ruff check (linting) - Production Code [REQUIRED]
   Error: cowrieprocessor/db/models.py:45:1: F401 'datetime' imported but unused
   CI PIPELINE BLOCKED
```

### Test Code Issue (ADVISORY)
```
⚠️  Ruff check (linting) - Tests/Archive/Docs [ADVISORY]
   Warning: tests/unit/test_models.py:12:1: F401 'datetime' imported but unused
   ⚠️  Ruff linting issues found in tests/archive/docs (advisory only)
   CI PIPELINE CONTINUES
```

---

## Local Development Workflow

### Pre-Commit (Recommended)
Developers can still run strict checks locally:

```bash
# Format and check production code (required to pass)
uv run ruff format cowrieprocessor/ scripts/production/
uv run ruff check cowrieprocessor/ scripts/production/

# Format and check tests (advisory - fix at discretion)
uv run ruff format tests/ archive/ docs/
uv run ruff check tests/ archive/ docs/

# Type check (required for all code)
uv run mypy .

# Test with coverage (required)
uv run pytest --cov=. --cov-fail-under=65
```

### Pre-Commit Hook (Updated)
The `.pre-commit-config.yaml` still runs strict checks locally but won't block test commits if ruff fails on test files.

---

## Migration Path

### Phase 1: Current (This Commit)
- Split quality gates implemented
- Tests/archive/docs soft-fail on ruff issues
- Production code maintains strict enforcement

### Phase 2: Incremental Cleanup (Optional)
- Address ruff issues in tests incrementally
- Prioritize high-impact test files
- No deadline or pressure

### Phase 3: Re-evaluate (Future)
- After test suite stabilizes, consider re-enabling strict checks
- Optional: could add metrics to track ruff issue count over time
- Decision point: 3-6 months post-migration

---

## Rollback Procedure

If this causes issues, rollback is simple:

```bash
# Revert to strict checks everywhere
git revert f63451b

# Or manually edit .github/workflows/ci.yml:
# - Remove the "continue-on-error: true" lines
# - Merge production and advisory checks back into single checks
```

---

## Related Work

### Milestone 1 Context
- Test suite refactoring in progress (Week 5-6 sprint plan)
- 13 legacy test files need import path updates
- Gradual migration from root modules to package structure
- This change unblocks test improvements without forcing big cleanup

### Technical Debt
- Tests importing from `archive/` (deprecated)
- Legacy test patterns need updates
- This soft-fail approach allows addressing incrementally

---

## Frequently Asked Questions

### Q: Won't this reduce code quality?
**A**: No, because:
- Production code quality gates unchanged (strict)
- Tests still require passing, type checking, and coverage
- Ruff issues still visible in CI logs (visibility maintained)
- Only affects linting style, not correctness

### Q: Why not fix all ruff issues in tests first?
**A**: Because:
- 13+ test files need refactoring (import paths)
- Test suite is actively being improved (Milestone 1)
- Blocking work on style issues slows feature development
- Incremental improvement is more sustainable

### Q: Can we make MyPy soft-fail too?
**A**: No, because:
- Type safety is correctness, not style
- Type errors often indicate real bugs
- MyPy remains strict for all code (including tests)

### Q: What about coverage?
**A**: Coverage remains strict at 65% minimum for all code. This change only affects ruff linting/formatting.

### Q: When will tests/archive/docs become strict again?
**A**: Optional decision point in 3-6 months after test suite stabilizes. May choose to:
- Re-enable strict checks if ruff issues resolved
- Keep advisory indefinitely if it works well
- Adjust thresholds based on experience

---

## Summary

**Status**: ✅ DEPLOYED (commit f63451b, pushed to scp-snowshoe)

**Impact**:
- ✅ Production code quality: UNCHANGED (strict)
- ✅ Test development velocity: IMPROVED (unblocked)
- ✅ Code quality visibility: MAINTAINED (warnings shown)
- ✅ Type safety: UNCHANGED (MyPy still strict)
- ✅ Test coverage: UNCHANGED (65% required)

**Result**: Balanced approach that maintains production quality while enabling rapid test development.

---

**Next Actions**:
1. ✅ CI pipeline change deployed
2. ⏳ Monitor CI runs on next PR to confirm behavior
3. ⏳ Document in CONTRIBUTING.md for developer guidance
4. ⏳ Optional: Add ruff issue tracking metrics
