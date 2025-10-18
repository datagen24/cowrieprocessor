<!-- f885bd8e-2cca-47e5-b0a8-6d1b03c5c438 15adb96c-5dc2-47f4-bfad-9c1e9d3470a5 -->
# MyPy Type Error Remediation Plan

## Problem Statement

The codebase has accumulated **1053 mypy type errors** across 117 files due to bypassed pre-commit checks during complex agent-driven development sessions. This violates the mandatory project rules requiring complete type hints and puts code quality at risk.

## Error Distribution Analysis

- **Total errors**: 1053 across 117 files
- **Core package errors**: 378 in `cowrieprocessor/` (priority target)
- **Test errors**: ~400 in `tests/` (defer to later phase)
- **Root scripts**: ~275 in utility scripts (defer to later phase)

### Top Error Categories (Core Package)

1. **Assignment errors** (81) - Type mismatches in variable assignments
2. **Any type issues** (55) - Functions returning or using `Any` without proper typing
3. **Unreachable code** (45) - Dead code from type guards
4. **Index errors** (37) - SQLAlchemy Column/dict confusion
5. **No-untyped-def** (32) - Missing type annotations
6. **arg-type** (39) - Incorrect argument types
7. **no-any-return** (35) - Functions returning Any need explicit types

### Most Problematic Core Modules

1. `cowrieprocessor/cli/cowrie_db.py` - 50 errors
2. `cowrieprocessor/threat_detection/longtail.py` - 47 errors
3. `cowrieprocessor/loader/dlq_processor.py` - 41 errors
4. `cowrieprocessor/cli/enrich_ssh_keys.py` - 30 errors
5. `cowrieprocessor/enrichment/ssh_key_analytics.py` - 26 errors
6. `cowrieprocessor/db/enhanced_dlq_models.py` - 24 errors
7. `cowrieprocessor/cli/enrich_passwords.py` - 22 errors

## Remediation Strategy

### Phase 0: Preparation (Session 1)

- Temporarily disable mypy in `.pre-commit-config.yaml`
- Create tracking baseline with error counts per file
- Document current mypy configuration
- Set up session-by-session progress tracking

### Phase 1: Database Layer (Session 1-2)

**Target**: `cowrieprocessor/db/` - ~70 errors in 7 files

Fix foundational database modules that other layers depend on:

1. **db/json_utils.py** (5 errors)

   - Fix SQLAlchemy `Column[Any]` vs `BinaryExpression[Any]` typing
   - Add proper return types for JSON query builders
   - Fix `BooleanClauseList` vs `BinaryExpression` return type mismatches

2. **db/models.py** (1 error)

   - Fix `Function[Any]` vs `Cast[Any]` assignment in SQLAlchemy model

3. **db/engine.py** (1 error)

   - Add return type annotation to database connection function

4. **db/migrations.py** (2 errors)

   - Fix `FromClause.create` attribute error (likely needs SQLAlchemy API correction)
   - Fix `no-any-return` in boolean check function

5. **db/enhanced_dlq_models.py** (24 errors)

   - Add type annotations to model classes
   - Fix SQLAlchemy relationship typing
   - Resolve `Column` type mismatches

6. **db/enhanced_stored_procedures.py** (16 errors)

   - Add function type annotations
   - Fix stored procedure return type declarations

7. **db/stored_procedures.py** (9 errors)

   - Mirror fixes from enhanced version

**Success Criteria**: All `db/` modules pass mypy; run `uv run mypy cowrieprocessor/db/`

### Phase 2: Data Loading Layer (Session 2-3)

**Target**: `cowrieprocessor/loader/` - ~110 errors in 9 files

Fix data ingestion modules that depend on db layer:

1. **loader/defanging.py** (1 error)

   - Fix `no-any-return` in boolean function

2. **loader/cowrie_schema.py** (6 errors)

   - Add type annotations to validation functions
   - Fix `no-redef` issue with ValidationError
   - Fix `no-any-return` for list return type

3. **loader/file_processor.py** (1 error)

   - Fix unreachable code statement

4. **loader/dlq_processor.py** (41 errors - CRITICAL)

   - Fix `int | None` comparisons (operator errors)
   - Fix `list[str]` assigned to `str` type mismatches (~10 occurrences)
   - Add missing function type annotations
   - Fix `no-redef` with tomllib import
   - Fix SQLAlchemy filter boolean type errors
   - Fix `Column[bool]` vs `bool` assignment errors
   - Fix dict indexing on SQLAlchemy Row objects

5. **loader/improved_hybrid.py** (4 errors)

   - Fix `no-any-return` for dict return types
   - Fix unreachable code

6. **loader/bulk.py** (8 errors)

   - Add missing argument type annotations
   - Fix `FromClause.insert` attribute errors (SQLAlchemy API usage)
   - Fix `Result[Any].rowcount` attribute access

7. **loader/delta.py** (5 errors)

   - Fix unreachable code from SQLAlchemy type guards
   - Fix `Column[Any]` vs `dict` subclass impossibility errors

8. **loader/dlq_cli.py** (5 errors)

   - Add missing type annotations for CLI functions

9. **loader/dlq_enhanced_cli.py** (5 errors)

   - Mirror fixes from dlq_cli.py

10. **loader/dlq_stored_proc_cli.py** (4 errors)

    - Mirror fixes from other CLI modules

**Success Criteria**: All `loader/` modules pass mypy; run `uv run mypy cowrieprocessor/loader/`

### Phase 3: Enrichment Layer (Session 3-4)

**Target**: `cowrieprocessor/enrichment/` - ~40 errors in 5 files

Fix intelligence enrichment modules:

1. **enrichment/init.py** (1 error)

   - Add missing return type annotation

2. **enrichment/legacy_adapter.py** (2 errors)

   - Fix `no-any-return` for dict return types

3. **enrichment/virustotal_handler.py** (5 errors)

   - Fix `no-redef` for quota_manager attribute
   - Remove unreachable code
   - Fix `no-any-return` for dict and bool functions

4. **enrichment/ssh_key_analytics.py** (26 errors)

   - Add comprehensive type annotations to analytics functions
   - Fix return types for statistical analysis functions
   - Resolve type mismatches in data processing

**Success Criteria**: All `enrichment/` modules pass mypy; run `uv run mypy cowrieprocessor/enrichment/`

### Phase 4: Threat Detection Layer (Session 4-5)

**Target**: `cowrieprocessor/threat_detection/` - ~75 errors in 5 files

Fix security analysis modules:

1. **threat_detection/metrics.py** (6 errors)

   - Fix `None` assigned to `list[str]` type errors
   - Remove unreachable code statements

2. **threat_detection/snowshoe.py** (1 error)

   - Fix `no-any-return` for optional string return

3. **threat_detection/botnet.py** (9 errors)

   - Fix `dict[<type>, <type>]` type annotation requirements
   - Fix SQLAlchemy `Column[Any]` vs `dict[str, Any]` argument type errors
   - Fix unreachable code from type guard impossibilities
   - Fix `list[Column[str]]` vs `list[str]` return type mismatch

4. **threat_detection/storage.py** (9 errors)

   - Add type annotations for storage functions
   - Fix SQLAlchemy model typing

5. **threat_detection/longtail.py** (47 errors - CRITICAL)

   - Comprehensive type annotation overhaul
   - Fix complex statistical analysis return types
   - Resolve SQLAlchemy query result typing
   - Fix data structure type mismatches

**Success Criteria**: All `threat_detection/` modules pass mypy; run `uv run mypy cowrieprocessor/threat_detection/`

### Phase 5: CLI Layer (Session 5-6)

**Target**: `cowrieprocessor/cli/` - ~130 errors in 9 files

Fix command-line interface modules:

1. **cli/db_config.py** (1 error)

   - Add missing type annotation

2. **cli/health.py** (1 error)

   - Add missing type annotation

3. **cli/analyze.py** (5 errors)

   - Add type annotations to analysis functions

4. **cli/file_organizer.py** (7 errors)

   - Fix `dict[<type>, <type>]` annotation requirement
   - Fix `Path` object iteration type errors
   - Add type annotations for result tracking

5. **cli/report.py** (12 errors)

   - Fix `ElasticsearchPublisher` constructor argument errors
   - Fix missing attribute errors (`.can_publish`, `.publish_report`, `.get_available_sensors`)
   - Fix `BaseReportBuilder.build_report` attribute error
   - Fix `no-any-return` errors

6. **cli/enrich_passwords.py** (22 errors)

   - Add comprehensive type annotations
   - Fix data processing type mismatches

7. **cli/enrich_ssh_keys.py** (30 errors)

   - Add comprehensive type annotations
   - Fix enrichment pipeline typing

8. **cli/cowrie_db.py** (50 errors - CRITICAL)

   - Major type annotation overhaul needed
   - Fix database operation return types
   - Resolve CLI argument processing types
   - Fix SQLAlchemy query result typing

**Success Criteria**: All `cli/` modules pass mypy; run `uv run mypy cowrieprocessor/cli/`

### Phase 6: Utilities & Supporting (Session 6)

**Target**: `cowrieprocessor/utils/`, `cowrieprocessor/reporting/`, `cowrieprocessor/telemetry/`

1. **utils/unicode_sanitizer.py** (6 errors)

   - Fix unreachable code statements
   - Add missing type annotations
   - Fix `no-any-return` for dict functions

2. **reporting/es_publisher.py**, **reporting/builders.py**, **reporting/dal.py**

   - Add missing attributes that CLI expects
   - Fix type annotations

3. **telemetry/otel.py**

   - Verify type annotations complete

**Success Criteria**: All utility modules pass mypy

### Phase 7: Root-Level Scripts (Session 7+)

**Target**: Root-level automation scripts - ~275 errors

Fix in priority order:

1. `process_cowrie.py` (65 errors)
2. `enrichment_handlers.py` (various errors)
3. `es_reports.py` (30+ errors)
4. Other utility scripts

### Phase 8: Test Suite (Deferred)

**Target**: `tests/` - ~400 errors

Fix test files after core logic is stable:

- `tests/fixtures/` - Mock server type annotations
- `tests/integration/` - Integration test typing
- `tests/performance/` - Performance test typing
- `tests/unit/` - Unit test typing

### Phase 9: Re-enable & Validate (Final Session)

- Re-enable mypy in `.pre-commit-config.yaml`
- Run full mypy check: `uv run mypy .`
- Verify zero errors
- Update pre-commit: `pre-commit run --all-files`
- Document remediation in CHANGELOG.md
- Create summary report of changes

## Common Error Patterns & Solutions

### Pattern 1: Missing Type Annotations

```python
# BEFORE
def process_data(input):
    return result

# AFTER
def process_data(input: dict[str, Any]) -> dict[str, Any]:
    return result
```

### Pattern 2: SQLAlchemy Column vs Python Type

```python
# BEFORE - Treating Column as dict
if isinstance(enrichment_data, dict) and "virustotal" in enrichment_data:

# AFTER - Proper SQLAlchemy typing
from sqlalchemy.orm import Mapped
enrichment_data: Mapped[dict[str, Any]]
```

### Pattern 3: Optional Parameters Without None Default

```python
# BEFORE
def func(param: Callable[[], Session] = None):  # Error!

# AFTER
def func(param: Callable[[], Session] | None = None):
```

### Pattern 4: Returning Any

```python
# BEFORE
def get_data() -> dict[str, Any]:
    return json.loads(text)  # Returns Any

# AFTER
def get_data() -> dict[str, Any]:
    result: dict[str, Any] = json.loads(text)
    return result
```

### Pattern 5: Unreachable Code from Type Guards

```python
# BEFORE
if isinstance(x, Column) and isinstance(x, dict):  # Impossible!
    do_something()

# AFTER - Fix logic
if isinstance(x, Column):
    # Handle Column case
elif isinstance(x, dict):
    # Handle dict case
```

## Validation at Each Phase

After completing each phase:

1. Run `uv run mypy <module>/` to verify zero errors in that module
2. Run `uv run ruff check .` to ensure no new lint issues
3. Run `uv run pytest tests/unit/` to ensure tests still pass
4. Document error count reduction in progress tracker

## Progress Tracking

Create `docs/mypy-remediation-progress.md`:

```markdown
# MyPy Remediation Progress

## Baseline
- Total errors: 1053
- Date: 2025-10-17

## Phase 1: Database Layer
- [ ] db/json_utils.py: 5 → 0
- [ ] db/models.py: 1 → 0
...
- **Phase Total**: 70 → 0
- **Remaining**: 983

## Phase 2: Data Loading Layer
...
```

## Session Management

Each session should:

1. Focus on 1-2 modules with ~30-50 errors max
2. Run validation commands after each file
3. Commit working changes with message: `fix(types): resolve mypy errors in <module>`
4. Update progress tracker
5. Document any architectural issues discovered

## Risk Mitigation

- **Breaking changes**: All changes are type-annotation only; no logic changes
- **Testing**: Run unit tests after each module to catch regressions
- **Rollback**: Each phase committed separately for easy rollback
- **Documentation**: Complex typing decisions documented inline with comments

## Timeline Estimate

- **Phase 0-1**: 2 hours (1 session)
- **Phase 2**: 3 hours (1 session)
- **Phase 3**: 2 hours (1 session)
- **Phase 4**: 3 hours (1 session)
- **Phase 5**: 4 hours (2 sessions)
- **Phase 6**: 1 hour (1 session)
- **Phase 7**: 3 hours (1-2 sessions)
- **Phase 8**: 4 hours (deferred)
- **Phase 9**: 1 hour (1 session)

**Total core remediation**: ~19 hours across 7-9 sessions

### To-dos

- [ ] Phase 0: Preparation - Disable mypy in pre-commit, create baseline tracking
- [ ] Phase 1: Database Layer - Fix 70 errors in cowrieprocessor/db/ modules
- [ ] Phase 2: Data Loading Layer - Fix 110 errors in cowrieprocessor/loader/ modules
- [ ] Phase 3: Enrichment Layer - Fix 40 errors in cowrieprocessor/enrichment/ modules
- [ ] Phase 4: Threat Detection Layer - Fix 75 errors in cowrieprocessor/threat_detection/ modules
- [ ] Phase 5: CLI Layer - Fix 130 errors in cowrieprocessor/cli/ modules
- [ ] Phase 6: Utilities & Supporting - Fix remaining cowrieprocessor/ errors
- [ ] Phase 7: Root-Level Scripts - Fix 275 errors in automation scripts
- [ ] Phase 8: Test Suite - Fix 400 errors in tests/ (deferred to later)
- [ ] Phase 9: Re-enable & Validate - Re-enable mypy, verify zero errors, update docs