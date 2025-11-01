# Special Considerations and Guidelines

## Critical Rules

### 1. Package Manager: uv Only
- **MANDATORY**: Always use `uv` for package management
- **NEVER** use pip directly
- **Commands**: `uv sync`, `uv run <command>`
- **Rationale**: Project uses uv for dependency resolution and virtual environment management

### 2. Pre-Commit Checklist (NON-NEGOTIABLE)
**CI gates enforce these in strict order. Any failure stops the merge:**

1. `uv run ruff format .` (auto-format)
2. `uv run ruff check .` (0 errors required)
3. `uv run mypy .` (0 type errors required)
4. `uv run pytest --cov=. --cov-report=term-missing --cov-fail-under=65` (≥65% coverage)
5. All tests must pass

### 3. Git Workflow Safety
- **ALWAYS** check status and branch first: `git status && git branch`
- **NEVER** work directly on main/master branch
- **ALWAYS** create feature branches: `git checkout -b feature/name`
- **ALWAYS** use Conventional Commits format

### 4. Archive Directory (CRITICAL)
- **archive/** contains deprecated legacy code (Phase 3 refactoring, Oct 2025)
- **NEVER** modify code in archive/ - use package code instead
- **Migration Status**: 13 legacy test files need import path updates
- **Purpose**: Emergency rollback only - not actively maintained

## Database Compatibility

### SQLite vs PostgreSQL
- **SQLite**: Development, single-sensor deployments
- **PostgreSQL**: Production, multi-sensor deployments
- **JSON Handling Differences**:
  - SQLite: Uses `json_extract()` function
  - PostgreSQL: Uses `->` and `->>` operators
- **Detection**: Use `get_dialect_name_from_engine()` to detect database type
- **JSON Columns**: Use SQLAlchemy's `JSON` type (handles both databases)

### Schema Migrations
When modifying database schema:
1. Update ORM models in `cowrieprocessor/db/models.py`
2. Add migration logic to `cowrieprocessor/db/migrations.py`
3. Increment `TARGET_SCHEMA_VERSION` constant
4. Test on BOTH SQLite and PostgreSQL
5. Update `docs/data_dictionary.md`

## Enrichment Services

### Active Services (Require API Keys)
- **VirusTotal**: File hash analysis (30-day cache, 4 req/min rate limit)
- **DShield**: IP reputation (7-day cache, 30 req/min)
- **URLHaus**: Malware URL detection (3-day cache, 30 req/min)

### Mocked Services (No API Keys for Testing)
- **SPUR**: Mock implementation in test fixtures
- **OTX**: Mock implementation ready for activation
- **AbuseIPDB**: Mock implementation ready for activation

### Testing Enrichment
- All enrichment tests MUST pass without network access
- Use mock fixtures in `tests/fixtures/enrichment_fixtures.py`
- Set `USE_MOCK_APIS=true` to force mock API usage

## Secret Management

Secrets can be sourced from multiple backends using URI notation:
- `env:VARIABLE_NAME` - Environment variable
- `file:/path/to/secret` - File contents
- `op://vault/item/field` - 1Password CLI
- `aws-sm://[region/]secret_id[#json_key]` - AWS Secrets Manager
- `vault://path[#field]` - HashiCorp Vault (KV v2)
- `sops://path[#json.key]` - SOPS-encrypted files

Common environment variables:
- `VT_API_KEY` - VirusTotal
- `URLHAUS_API_KEY` - URLHaus
- `SPUR_API_KEY` - SPUR.us
- `DSHIELD_EMAIL` - DShield
- `ES_HOST`, `ES_USERNAME`, `ES_PASSWORD`, `ES_API_KEY`, `ES_CLOUD_ID` - Elasticsearch

## Type Hints and Docstrings

### Type Hints (MANDATORY)
- ALL functions, methods, and classes MUST have complete type hints
- Use `from __future__ import annotations` for forward references
- NO `Any` types without explicit justification comment

### Docstrings (MANDATORY)
- ALL modules, classes, methods, and functions MUST have Google-style docstrings
- Include `Args`, `Returns`, `Raises`, and `Examples` sections where applicable

Example:
```python
from __future__ import annotations

def process_session(session_id: str, enrichment_level: int = 1) -> dict[str, Any]:
    """Process a Cowrie session with optional enrichment.
    
    Args:
        session_id: Unique session identifier
        enrichment_level: Enrichment depth (0=none, 1=basic, 2=full)
        
    Returns:
        Dictionary with session data and enrichment results
        
    Raises:
        ValueError: If session_id is invalid
        DatabaseError: If database connection fails
        
    Examples:
        >>> process_session("abc123", enrichment_level=2)
        {'session_id': 'abc123', 'ip': '1.2.3.4', ...}
    """
    # Implementation
```

## Testing Strategy

### Test Categories
1. **Unit tests** (`tests/unit/`): Fast, isolated, no external dependencies
2. **Integration tests** (`tests/integration/`): End-to-end workflows with test database
3. **Performance tests** (`tests/performance/`): Benchmark critical paths
4. **Enrichment harness** (`tests/integration/test_enrichment_flow.py`): Offline API tests

### Coverage Requirements
- **Minimum**: 65% (CI gate)
- **Target for new features**: 80%+
- **Bug fixes**: MUST include regression tests

### Running Tests
```bash
# All tests with coverage
uv run pytest --cov=. --cov-report=term-missing --cov-fail-under=65

# Specific categories
uv run pytest tests/unit/           # Unit tests only
uv run pytest tests/integration/    # Integration tests
uv run pytest tests/performance/    # Benchmarks

# By marker
uv run pytest -m "unit"             # Unit marker
uv run pytest -m "enrichment"       # Enrichment marker
```

## Design Patterns

### 1. ORM-First Approach
- All database operations use SQLAlchemy 2.0 ORM
- No raw SQL except stored procedures
- Prefer ORM queries for cross-database compatibility

### 2. Enrichment Pipeline
- All API enrichments flow through unified caching layer
- TTL-based cache invalidation
- Token bucket rate limiting
- OpenTelemetry tracing for observability

### 3. Status Emitter Pattern
- Long-running operations emit JSON status files
- Enables real-time monitoring without database locks
- Status files in `/mnt/dshield/data/logs/status/`

### 4. Dead Letter Queue (DLQ)
- Failed events tracked with reason/payload
- Enables graceful degradation and replay
- DLQ processing via `cowrieprocessor/loader/dlq_processor.py`

### 5. Dependency Injection
- Services use constructor injection for testability
- Mock implementations for offline testing

## macOS-Specific Notes

The project is developed on macOS (Darwin), so:
- **BSD Commands**: `ls`, `find`, `grep` use BSD variants (not GNU)
- **System Commands**: `ps aux`, `top`, standard BSD utilities
- **Case Sensitivity**: macOS default is case-insensitive filesystem
- **Python**: Use system Python 3.13 or uv-managed version

## Common Pitfalls to Avoid

1. **Don't use pip**: Always use `uv`
2. **Don't skip pre-commit checklist**: CI will reject your PR
3. **Don't modify archive/**: Use package code instead
4. **Don't commit secrets**: Use secret management URIs
5. **Don't skip type hints**: MyPy will fail
6. **Don't skip docstrings**: Ruff will fail
7. **Don't work on main branch**: Create feature branches
8. **Don't ignore warnings**: Fix or document why safe to ignore
9. **Don't use raw SQL**: Use ORM for cross-database compatibility
10. **Don't skip tests**: Coverage below 65% will fail CI

## Project Context (October 2025)

- **Current Focus**: Multi-container architecture (K3s deployment)
- **Recent Work**: Sphinx documentation, ADR integration, Docker/K3s deployment guides
- **Refactoring Status**: Phase 3 complete - legacy code archived
- **Migration Path**: 13 test files need import path updates from legacy to package structure
- **Branch**: main (feature/multi-container-architecture merged)
