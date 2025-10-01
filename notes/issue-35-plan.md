# Issue 35 Work Plan: PostgreSQL Support and Migration Path

**Issue**: [#35 - Add PostgreSQL Support and Migration Path](https://github.com/your-org/cowrieprocessor/issues/35)  
**Status**: In Progress (Phase 1, Day 1 Complete)  
**Priority**: High  
**Estimated Effort**: 3 weeks (15 days)  
**Dependencies**: Issues #28 (main refactoring), #30 (enrichment cache)  
**Current Branch**: `feature/postgresql-support`

## Overview

Implement full PostgreSQL support alongside existing SQLite functionality, enabling production deployments to use either database backend. This includes schema compatibility, query abstraction, and migration tooling.

## Current State Analysis

### ✅ What's Already Working
- `DatabaseSettings` supports arbitrary connection URLs
- SQLAlchemy engine creation is backend-agnostic
- Migration system has JSONB branching for Postgres
- Bulk loaders have dialect-specific UPSERT implementations
- Connection pooling configuration exists
- **NEW**: PostgreSQL driver detection and graceful fallback
- **NEW**: Optional PostgreSQL dependencies in pyproject.toml
- **NEW**: Runtime validation of PostgreSQL driver availability

### ❌ What Needs Fixing
- ~~No PostgreSQL driver in dependencies~~ ✅ **FIXED**: Optional dependencies added
- SQLite-specific `Computed` columns using `json_extract()`
- Boolean defaults as `"0"` instead of proper booleans
- Extensive `func.json_extract()` usage in reporting
- Direct `sqlite3` module calls in utility scripts
- Missing indexes for computed/virtual columns

## Work Plan

### Phase 1: Core Compatibility (Week 1 - Days 1-5)

#### Day 1: Dependencies & Configuration Setup ✅ COMPLETED
**Tasks:**
- [x] Add PostgreSQL dependencies as optional extras to `pyproject.toml`
  ```toml
  [project.optional-dependencies]
  postgres = [
      "psycopg[binary]>=3.1",
      "psycopg-pool>=3.1",
  ]
  ```
- [x] Implement runtime detection of PostgreSQL driver availability
- [x] Add graceful fallback when PostgreSQL driver is not installed
- [x] Update installation documentation with optional PostgreSQL setup
- [x] Add PostgreSQL connection string examples to `sensors.toml`
- [x] Test basic PostgreSQL connection in development environment

**Deliverables:**
- ✅ Updated `pyproject.toml` with optional PostgreSQL dependencies
- ✅ Runtime driver detection and graceful fallback
- ✅ Documentation for optional PostgreSQL installation
- ✅ Basic connection test script (temporary, removed after validation)

**Implementation Details:**
- Added `detect_postgresql_support()` function in `cowrieprocessor/db/engine.py`
- Added `create_engine_with_fallback()` function for graceful error handling
- Updated README.md with PostgreSQL installation instructions
- Updated sensors.example.toml with PostgreSQL connection examples
- Fixed SQLite StaticPool compatibility issue with pool_timeout
- Verified both default and PostgreSQL installations work correctly

#### Day 2: Schema Refactoring - Computed Columns
**Tasks:**
- [ ] Analyze current `Computed` column usage in `cowrieprocessor/db/models.py`
- [ ] Replace SQLite-specific computed columns with real columns
- [ ] Implement hybrid properties for backward compatibility
- [ ] Update model definitions for `RawEvent`, `SessionSummary`, etc.

**Files to Modify:**
- `cowrieprocessor/db/models.py`
- `cowrieprocessor/db/migrations.py`

**Deliverables:**
- Refactored models with real columns
- Backward compatibility layer
- Updated migration scripts

#### Day 3: Boolean Default Fixes
**Tasks:**
- [ ] Replace string defaults (`"0"`, `"1"`) with proper boolean types
- [ ] Update `server_default` values using SQLAlchemy expressions
- [ ] Test boolean handling across both backends
- [ ] Update migration scripts for boolean columns

**Files to Modify:**
- `cowrieprocessor/db/models.py`
- `cowrieprocessor/db/migrations.py`

**Deliverables:**
- Proper boolean column definitions
- Updated migrations for boolean handling
- Cross-backend compatibility tests

#### Day 4: JSON Access Abstraction Layer
**Tasks:**
- [ ] Create `cowrieprocessor/db/json_utils.py` module
- [ ] Implement `JSONAccessor` class for dialect-aware JSON operations
- [ ] Support both `json_extract()` (SQLite) and `->>` (PostgreSQL)
- [ ] Add comprehensive unit tests for JSON operations

**Files to Create/Modify:**
- `cowrieprocessor/db/json_utils.py` (new)
- `tests/unit/test_json_utils.py` (new)

**Deliverables:**
- JSON abstraction layer
- Comprehensive test coverage
- Documentation for JSON operations

#### Day 5: Migration System Updates
**Tasks:**
- [ ] Update migration scripts to handle both SQLite and PostgreSQL
- [ ] Add PostgreSQL-specific migration branches
- [ ] Test migration application on both backends
- [ ] Update migration documentation

**Files to Modify:**
- `cowrieprocessor/db/migrations.py`
- `cowrieprocessor/db/engine.py`

**Deliverables:**
- Updated migration system
- Cross-backend migration tests
- Migration documentation

### Phase 2: Query Abstraction (Week 2 - Days 6-10)

#### Day 6: Reporting Query Updates
**Tasks:**
- [ ] Update `cowrieprocessor/reporting/dal.py` to use JSON abstraction
- [ ] Replace direct `func.json_extract()` calls with `JSONAccessor`
- [ ] Test reporting queries on both backends
- [ ] Update query performance benchmarks

**Files to Modify:**
- `cowrieprocessor/reporting/dal.py`
- `cowrieprocessor/reporting/builders.py`

**Deliverables:**
- Backend-agnostic reporting queries
- Performance benchmarks
- Updated reporting tests

#### Day 7: CLI Tool Updates
**Tasks:**
- [ ] Update CLI tools to work with PostgreSQL
- [ ] Replace direct `sqlite3` module calls
- [ ] Add database backend detection
- [ ] Update CLI help documentation

**Files to Modify:**
- `cowrieprocessor/cli/cowrie_db.py`
- `cowrieprocessor/cli/report.py`
- `cowrieprocessor/cli/health.py`

**Deliverables:**
- PostgreSQL-compatible CLI tools
- Updated CLI documentation
- Cross-backend CLI tests

#### Day 8: Bulk Loader Enhancements
**Tasks:**
- [ ] Enhance bulk loaders for PostgreSQL-specific optimizations
- [ ] Implement PostgreSQL-specific UPSERT strategies
- [ ] Add connection pooling configuration
- [ ] Test bulk loading performance

**Files to Modify:**
- `cowrieprocessor/loader/bulk.py`
- `cowrieprocessor/loader/delta.py`

**Deliverables:**
- Optimized bulk loaders
- Performance improvements
- Connection pooling support

#### Day 9: Utility Script Updates
**Tasks:**
- [ ] Update utility scripts to work with PostgreSQL
- [ ] Replace hardcoded SQLite assumptions
- [ ] Add database backend configuration
- [ ] Test utility scripts on both backends

**Files to Modify:**
- `scripts/rebuild_session_summaries.py`
- `scripts/enrichment_refresh.py`
- `scripts/monitor_rebuild.py`

**Deliverables:**
- PostgreSQL-compatible utility scripts
- Updated script documentation
- Cross-backend utility tests

#### Day 10: Integration Testing Setup
**Tasks:**
- [ ] Set up test containers for PostgreSQL testing
- [ ] Create parametrized test fixtures
- [ ] Implement dual-backend test suite
- [ ] Add CI/CD configuration for both databases

**Files to Create/Modify:**
- `tests/conftest.py`
- `tests/integration/test_postgresql_compatibility.py` (new)
- `.github/workflows/ci.yml`

**Deliverables:**
- Comprehensive test suite
- CI/CD configuration
- Test documentation

### Phase 3: Migration & Utilities (Week 3 - Days 11-13)

#### Day 11: Migration Script Development
**Tasks:**
- [ ] Create `scripts/migrate_to_postgres.py`
- [ ] Implement data migration logic
- [ ] Add data validation and integrity checks
- [ ] Create rollback functionality

**Files to Create:**
- `scripts/migrate_to_postgres.py`
- `scripts/validate_migration.py`

**Deliverables:**
- Complete migration script
- Data validation tools
- Migration documentation

#### Day 12: Migration Testing & Validation
**Tasks:**
- [ ] Test migration with sample datasets
- [ ] Validate data integrity post-migration
- [ ] Test migration performance with large datasets
- [ ] Create migration troubleshooting guide

**Deliverables:**
- Validated migration process
- Performance benchmarks
- Troubleshooting documentation

#### Day 13: PostgreSQL Optimizations
**Tasks:**
- [ ] Implement PostgreSQL-specific stored procedures
- [ ] Add materialized views for reporting
- [ ] Create JSONB indexes for performance
- [ ] Add PostgreSQL-specific configuration options

**Files to Create/Modify:**
- `migrations/postgres/001_stored_procedures.sql` (new)
- `migrations/postgres/002_materialized_views.sql` (new)
- `cowrieprocessor/db/postgres_optimizations.py` (new)

**Deliverables:**
- PostgreSQL optimizations
- Performance improvements
- Optimization documentation

### Phase 4: Testing & Documentation (Days 14-15)

#### Day 14: Comprehensive Testing
**Tasks:**
- [ ] Run full test suite on both backends
- [ ] Performance testing and benchmarking
- [ ] Concurrent write testing
- [ ] Large dataset testing (39GB migration)
- [ ] Security testing for both backends

**Deliverables:**
- Complete test results
- Performance benchmarks
- Security validation

#### Day 15: Documentation & Finalization
**Tasks:**
- [ ] Update README with PostgreSQL instructions
- [ ] Create PostgreSQL deployment guide
- [ ] Update configuration documentation
- [ ] Create troubleshooting guide
- [ ] Final code review and cleanup

**Deliverables:**
- Complete documentation
- Deployment guides
- Troubleshooting resources

## Technical Implementation Details

### Dependencies Configuration
```toml
# pyproject.toml additions
[project.optional-dependencies]
postgres = [
    "psycopg[binary]>=3.1",
    "psycopg-pool>=3.1",
]

# Install with: uv pip install -e ".[postgres]"
# Default installation (SQLite only): uv pip install -e .
```

### Runtime Driver Detection
```python
# cowrieprocessor/db/engine.py
def detect_postgresql_support() -> bool:
    """Detect if PostgreSQL driver is available."""
    try:
        import psycopg
        return True
    except ImportError:
        return False

def create_engine_with_fallback(db_url: str):
    """Create engine with graceful PostgreSQL fallback."""
    if db_url.startswith("postgresql://") and not detect_postgresql_support():
        raise ValueError(
            "PostgreSQL driver not installed. Install with: uv pip install -e '.[postgres]'"
        )
    return create_engine(db_url)
```

### Schema Refactoring Example
```python
# cowrieprocessor/db/models.py
class RawEvent(Base):
    __tablename__ = "raw_events"
    
    # Replace Computed columns with real columns
    session_id = Column(String(64), nullable=True, index=True)
    event_type = Column(String(128), nullable=True, index=True)
    event_timestamp = Column(DateTime(timezone=True), nullable=True, index=True)
    
    @hybrid_property
    def session_id_computed(self):
        """Backward compatibility for computed access"""
        return self.session_id or (self.payload.get("session") if self.payload else None)
    
    @session_id_computed.expression
    def session_id_computed(cls):
        """SQL expression for backward compatibility"""
        return case(
            (cls.session_id.isnot(None), cls.session_id),
            else_=func.json_extract(cls.payload, "$.session")  # SQLite
        )
```

### JSON Access Abstraction
```python
# cowrieprocessor/db/json_utils.py
class JSONAccessor:
    """Backend-agnostic JSON field access"""
    
    @staticmethod
    def get_field(column, field: str, dialect_name: str):
        """Extract JSON field based on dialect"""
        if dialect_name == "postgresql":
            return column[field].astext
        else:
            return func.json_extract(column, f"$.{field}")
```

### Migration Script Structure
```python
# scripts/migrate_to_postgres.py
@click.command()
@click.option('--source-db', required=True, help='SQLite database path')
@click.option('--target-db', required=True, help='PostgreSQL connection string')
@click.option('--batch-size', default=10000)
def migrate(source_db: str, target_db: str, batch_size: int):
    """Migrate data from SQLite to PostgreSQL"""
    # Implementation details in issue description
```

## Testing Strategy

### Unit Tests
- [ ] JSON abstraction layer tests
- [ ] Model compatibility tests
- [ ] Migration script tests
- [ ] Utility function tests

### Integration Tests
- [ ] Dual-backend test suite
- [ ] Migration validation tests
- [ ] Performance comparison tests
- [ ] Concurrent access tests

### Performance Tests
- [ ] Bulk loading benchmarks
- [ ] Query performance comparison
- [ ] Large dataset migration tests
- [ ] Memory usage analysis

## Success Criteria

### Functional Requirements
- [ ] All existing SQLite functionality preserved
- [ ] PostgreSQL passes full test suite
- [ ] Migration tool handles 39GB database
- [ ] Query performance improved on Postgres
- [ ] Both backends supported in CI/CD

### Non-Functional Requirements
- [ ] Documentation for both backends
- [ ] Configuration examples provided
- [ ] Troubleshooting guides available
- [ ] Performance benchmarks documented
- [ ] Security validation completed

## Risk Mitigation

### Technical Risks
- **Data Loss During Migration**: Implement comprehensive validation and rollback
- **Performance Degradation**: Benchmark both backends extensively
- **Compatibility Issues**: Maintain backward compatibility layer
- **Test Coverage**: Ensure comprehensive test coverage for both backends

### Mitigation Strategies
- Keep SQLite as default backend initially
- PostgreSQL driver is optional - only installed when needed
- Runtime detection with graceful fallback for missing driver
- Maintain both code paths during transition
- Gradual migration with validation
- SQLite export tool always available

## Configuration Examples

### Environment Variables
```bash
# SQLite (default)
COWRIEPROC_DB_URL=sqlite:///cowrieprocessor.sqlite

# PostgreSQL
COWRIEPROC_DB_URL=postgresql://user:pass@localhost:5432/cowrie
COWRIEPROC_DB_POOL_SIZE=20
COWRIEPROC_DB_POOL_TIMEOUT=30
```

### Docker Compose
```yaml
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: cowrie
      POSTGRES_USER: cowrie
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
```

## Future Enhancements

### Phase 5: Advanced PostgreSQL Features
- PostgreSQL-specific features (partitioning, parallel queries)
- Read replicas for reporting
- Connection pooling with PgBouncer
- TimescaleDB for time-series optimization
- PostGIS for geographic analysis
- pg_stat_statements for query optimization

## Validation Commands

### Development Testing
```bash
# Default installation (SQLite only)
uv pip install -e .

# Optional PostgreSQL installation
uv pip install -e ".[postgres]"

# Run tests on both backends (requires PostgreSQL extras)
uv run pytest tests/integration/test_postgresql_compatibility.py

# Test migration script (requires PostgreSQL extras)
python scripts/migrate_to_postgres.py --source-db test.sqlite --target-db postgresql://user:pass@localhost:5432/test

# Performance benchmarking (requires PostgreSQL extras)
uv run pytest tests/performance/test_postgresql_performance.py
```

### Production Validation
```bash
# Validate migration
python scripts/validate_migration.py --source-db production.sqlite --target-db postgresql://user:pass@prod:5432/cowrie

# Run full test suite on production PostgreSQL
COWRIEPROC_DB_URL=postgresql://user:pass@prod:5432/cowrie uv run pytest

# Performance comparison
python scripts/benchmark_databases.py --sqlite production.sqlite --postgres postgresql://user:pass@prod:5432/cowrie
```

## Notes

- This work plan follows the project's security-focused development rules
- All database operations will use parameterized queries
- API keys and credentials will be managed through environment variables
- Comprehensive input validation will be implemented
- Security testing will be included in all phases

## Related Issues

- Issue #28: Main refactoring (dependency)
- Issue #30: Enrichment cache (dependency)
- Future: PostgreSQL-specific optimizations
- Future: Advanced PostgreSQL features

---

**Created**: 2025-01-27  
**Last Updated**: 2025-01-27 (Phase 1, Day 1 Complete)  
**Status**: In Progress - Phase 1, Day 2 Ready
