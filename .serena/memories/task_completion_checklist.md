# Task Completion Checklist

## Pre-Commit Requirements (MANDATORY)

**Must be executed in this exact order before ANY commit:**

### 1. Format Code (Auto-Fix)
```bash
uv run ruff format .
```
**Purpose**: Auto-format code to match project style  
**Gate**: CI Gate #2 (format check)

### 2. Lint Checks (0 Errors Required)
```bash
uv run ruff check .
```
**Purpose**: Static code analysis for errors, style violations  
**Gate**: CI Gate #1 (must produce 0 errors)  
**Failure**: Stops merge immediately

### 3. Type Checking (0 Errors Required)
```bash
uv run mypy .
```
**Purpose**: Static type checking with strict configuration  
**Gate**: CI Gate #2 (must produce 0 type errors)  
**Failure**: Stops merge immediately

### 4. Test Coverage (≥65% Required)
```bash
uv run pytest --cov=. --cov-report=term-missing --cov-fail-under=65
```
**Purpose**: Ensure test coverage meets minimum threshold  
**Gate**: CI Gate #4 (must achieve ≥65% coverage)  
**Target**: New features should aim for 80%+ coverage  
**Failure**: Stops merge immediately

### 5. All Tests Pass
**Purpose**: Validate functionality and prevent regressions  
**Gate**: CI Gate #5 (all tests must pass)  
**Failure**: Stops merge immediately

## Database Changes Workflow

When modifying database schema:

1. **Update ORM Models**
   - Edit `cowrieprocessor/db/models.py`
   - Add complete type hints and docstrings

2. **Create Migration**
   - Add migration logic to `cowrieprocessor/db/migrations.py`
   - Increment `TARGET_SCHEMA_VERSION` constant

3. **Test Both Databases**
   - Test migration on SQLite (development)
   - Test migration on PostgreSQL (production)

4. **Update Documentation**
   - Update `docs/data_dictionary.md` with schema changes
   - Document any breaking changes in CHANGELOG.md

## New Feature Workflow

1. **Create Feature Branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Write Tests First (TDD)**
   - Create test file in appropriate directory
   - Write failing tests for new functionality

3. **Implement Feature**
   - Add type hints and docstrings
   - Follow ORM-first approach
   - Use dependency injection for testability

4. **Achieve Test Coverage**
   - Target 80%+ coverage for new code
   - Include edge cases and error conditions

5. **Run Pre-Commit Checklist**
   - Execute all 5 checks above
   - Fix any issues before committing

6. **Commit with Conventional Format**
   ```bash
   git commit -m "feat(scope): clear description"
   ```

7. **Open Pull Request**
   - Provide clear description of changes
   - Reference any related issues
   - Wait for CI checks to pass

## Bug Fix Workflow

1. **Create Regression Test**
   - Write test that reproduces the bug
   - Verify test fails before fix

2. **Implement Fix**
   - Add type hints and docstrings
   - Follow project patterns

3. **Verify Test Passes**
   - Ensure regression test now passes
   - Run full test suite

4. **Run Pre-Commit Checklist**
   - Execute all 5 checks above

5. **Commit with Conventional Format**
   ```bash
   git commit -m "fix(scope): describe what was fixed"
   ```

## Enrichment Changes Workflow

When modifying enrichment pipelines:

1. **Update Mock Fixtures**
   - Edit `tests/fixtures/enrichment_fixtures.py`
   - Ensure offline tests work without network

2. **Test Cache Behavior**
   - Verify TTL handling
   - Test cache hit/miss scenarios

3. **Test Rate Limiting**
   - Verify token bucket behavior
   - Test backoff and retry logic

4. **Run Enrichment Harness**
   ```bash
   uv run pytest tests/integration/test_enrichment_flow.py
   ```

## Documentation Updates

When adding features or fixing bugs:

1. **Update CLAUDE.md**
   - Document new patterns or conventions
   - Add troubleshooting tips if applicable

2. **Update README.md**
   - Update feature list if new capability added
   - Update examples if usage changed

3. **Update Sphinx Docs**
   - Add docstrings to new modules/classes
   - Build docs locally to verify: `uv run sphinx-build docs docs/_build`

## Safety Checks

Before any commit:
- [ ] No credentials or secrets in code
- [ ] No absolute paths in code (use relative paths)
- [ ] Archive directory not modified (use package code instead)
- [ ] All new code has type hints and docstrings
- [ ] Tests included for new functionality
- [ ] CI pre-commit checklist passed
