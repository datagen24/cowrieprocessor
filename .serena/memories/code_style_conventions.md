# Code Style and Conventions

## Mandatory Requirements (NON-NEGOTIABLE)

### 1. Type Hints
- ALL functions, methods, and classes MUST have complete type hints
- Use `from __future__ import annotations` for forward references
- NO `Any` types without explicit justification comment

### 2. Docstrings
- ALL modules, classes, methods, and functions MUST have Google-style docstrings
- Include `Args`, `Returns`, `Raises`, and `Examples` sections where applicable

### 3. Testing
- Minimum 65% code coverage required (CI Gate #4)
- New features should target 80%+ coverage
- Bug fixes MUST include regression tests

### 4. Linting & Formatting
- **Ruff Configuration**:
  - Line length: 120
  - Target version: py313
  - Select: E (errors), F (pyflakes), D (pydocstyle), I (isort)
  - Pydocstyle convention: Google
  - Quote style: preserve
  - Indent style: space

### 5. Type Checking
- **MyPy Configuration**:
  - Python version: 3.13
  - disallow_untyped_defs: true
  - disallow_incomplete_defs: true
  - check_untyped_defs: true
  - warn_unused_ignores: true
  - warn_redundant_casts: true
  - warn_unused_configs: true
  - warn_return_any: true
  - warn_unreachable: true
  - explicit_package_bases: true
  - strict_optional: true

## Naming Conventions
- **Functions/Variables**: snake_case (Python standard)
- **Classes**: PascalCase
- **Constants**: UPPER_SNAKE_CASE
- **Private members**: _leading_underscore
- **Descriptive names**: Files, functions, variables must clearly describe purpose

## Git Commit Convention
Use Conventional Commits format: `<type>(<scope>): <description>`

Valid types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Code style changes
- `refactor`: Code refactoring
- `perf`: Performance improvements
- `test`: Adding/updating tests
- `build`: Build system changes
- `ci`: CI configuration changes
- `chore`: Maintenance tasks

Examples:
- `feat(enrichment): add SPUR.us IP enrichment support`
- `fix(processor): handle corrupted bz2 files gracefully`
- `docs(api): update VirusTotal integration examples`

## Key Design Patterns

### 1. ORM-First Approach
- All database operations use SQLAlchemy 2.0 ORM
- No raw SQL except stored procedures
- JSON handling differs between SQLite and PostgreSQL:
  - SQLite: Uses `json_extract()` function
  - PostgreSQL: Uses `->` and `->>` operators

### 2. Enrichment Pipeline
- All API enrichments flow through unified caching layer with TTLs
- Rate limiting via token bucket algorithm
- OpenTelemetry tracing for observability

### 3. Status Emitter Pattern
- All long-running operations emit JSON status files for real-time monitoring
- Status files enable concurrent monitoring without database locks

### 4. Dead Letter Queue (DLQ)
- Failed events tracked with reason/payload for reprocessing
- DLQ enables graceful degradation and replay capabilities

### 5. Dependency Injection
- Services use constructor injection for testability
- Mock implementations for testing without network access

## File Organization
- **Tests**: `tests/{unit,integration,performance}/`
- **Scripts**: `scripts/{production,debug,migrations}/`
- **Documentation**: `docs/` (Sphinx-based with Read the Docs)
- **Configuration**: `config/` (sensors.toml)
- **Legacy Code**: `archive/` (Phase 3 refactoring, October 2025)

## Excluded Directories (Linting/Type Checking)
- `archive/`
- `scripts/debug/`
- `scripts/migrations/archive/`
- `docs/archive/`
- `notes/archive/`
- `fix_mypy_errors.py`

## Database Compatibility Notes
- Use `get_dialect_name_from_engine()` to detect database type
- JSON columns use SQLAlchemy's `JSON` type (handles both SQLite and PostgreSQL)
- Test migrations on both SQLite and PostgreSQL

## Testing Strategy
1. **Unit tests** (`tests/unit/`): Fast, isolated, no external dependencies
2. **Integration tests** (`tests/integration/`): End-to-end workflows with test database
3. **Performance tests** (`tests/performance/`): Benchmark critical paths
4. **Enrichment harness** (`tests/integration/test_enrichment_flow.py`): Offline tests with stubbed APIs

Use `USE_MOCK_APIS=true` environment variable to force mock API usage in tests.
