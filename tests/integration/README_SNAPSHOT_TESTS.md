# PostgreSQL Integration Tests for Snapshot Population (ADR-007)

## Overview

The snapshot population integration tests (`test_snapshot_population_integration.py`) validate the ADR-007 fix using a real PostgreSQL database. These tests cannot run against SQLite because they require hybrid property queries (`geo_country`, `ip_type`) which only work in PostgreSQL.

## Why Integration Tests?

**Problem**: Unit tests in `test_snapshot_population.py` hit SQLite limitations:
- SQLite cannot evaluate hybrid properties in queries (tries to call `.get()` on Column objects)
- Production uses PostgreSQL with JSONB operators (`->`, `->>`)
- Need to validate SQL correctness and FK relationships

**Solution**: Integration tests using PostgreSQL test database

## Setup Requirements

### 1. Create PostgreSQL Test Database

```bash
# Create database
createdb cowrie_test

# Verify connection
psql -d cowrie_test -c "SELECT version();"
```

### 2. Run Schema Migrations

```bash
# Migrate to ADR-007 schema (v16)
# pragma: allowlist secret
TEST_DATABASE_URL="postgresql://user:***@localhost/cowrie_test" uv run cowrie-db migrate

# Verify schema version
psql -d cowrie_test -c "SELECT * FROM schema_version ORDER BY id DESC LIMIT 1;"
# Should show: version=16, description includes "ADR-007"
```

### 3. Run Integration Tests

```bash
# Run all snapshot integration tests
TEST_DATABASE_URL="postgresql://user:pass@localhost/cowrie_test" uv run pytest tests/integration/test_snapshot_population_integration.py -v

# Run specific test
TEST_DATABASE_URL="postgresql://user:pass@localhost/cowrie_test" uv run pytest tests/integration/test_snapshot_population_integration.py::test_hybrid_property_queries_in_lookup -v
```

## Test Coverage

### Core Functionality Tests
1. **FK Relationship** (`test_canonical_ip_foreign_key_relationship`): Validates `session_summaries.source_ip` FK to `ip_inventory.ip_address`
2. **Hybrid Properties** (`test_hybrid_property_queries_in_lookup`): Validates PostgreSQL JSONB queries for `geo_country` and `ip_type`
3. **Immutability** (`test_snapshot_immutability_with_coalesce`): Validates COALESCE preserves first snapshot on conflict
4. **IP Type Priority** (`test_ip_type_priority_handling`): Validates extraction from SPUR enrichment
5. **Missing IPs** (`test_missing_ip_graceful_handling`): Validates graceful handling when IP not in ip_inventory
6. **Unknown Country** (`test_country_code_unknown_handling`): Validates XX converted to NULL
7. **Batch Performance** (`test_batch_lookup_performance`): Validates single query for batch (not N+1)
8. **Timestamp Preservation** (`test_enrichment_timestamp_preservation`): Validates enrichment_at copied correctly

## Test Database Configuration

**Environment Variable**: `TEST_DATABASE_URL`

**Format**: `postgresql://user:password@host:port/database`

**Example**: `postgresql://cowrieprocessor:***@localhost:5432/cowrie_test`  # pragma: allowlist secret

**Important**: DO NOT use production database - tests INSERT/UPDATE data

## Continuous Integration

For CI/CD pipelines, add PostgreSQL service:

```yaml
# GitHub Actions example
services:
  postgres:
    image: postgres:16
    env:
      POSTGRES_DB: cowrie_test
      POSTGRES_USER: cowrieprocessor
      POSTGRES_PASSWORD: testpass
    options: >-
      --health-cmd pg_isready
      --health-interval 10s
      --health-timeout 5s
      --health-retries 5

- name: Run integration tests
  env:
    # pragma: allowlist secret
    TEST_DATABASE_URL: postgresql://cowrieprocessor:***@localhost:5432/cowrie_test
  run: |
    uv run cowrie-db migrate
    uv run pytest tests/integration/test_snapshot_population_integration.py -v
```

## Troubleshooting

### Tests Skip with "PostgreSQL integration tests require TEST_DATABASE_URL"
**Cause**: `TEST_DATABASE_URL` not set or doesn't contain "postgresql"
**Fix**: Set environment variable: `export TEST_DATABASE_URL="postgresql://user:pass@localhost/cowrie_test"`

### Connection Refused
**Cause**: PostgreSQL not running or wrong connection details
**Fix**:
```bash
# Start PostgreSQL
pg_ctl -D /usr/local/var/postgres start

# Verify service
psql -l
```

### Schema Version Mismatch
**Cause**: Database not migrated to v16 (ADR-007)
**Fix**: `TEST_DATABASE_URL="..." uv run cowrie-db migrate`

### Foreign Key Constraint Violations
**Cause**: Test data doesn't match schema constraints
**Fix**: Check that enrichment JSON structure matches simplified format in `create_ip_inventory_entry()`

## Local Development Workflow

```bash
# One-time setup
createdb cowrie_test
export TEST_DATABASE_URL="postgresql://$(whoami):***@localhost/cowrie_test"  # pragma: allowlist secret
uv run cowrie-db migrate

# Daily workflow
uv run pytest tests/integration/test_snapshot_population_integration.py -v

# After schema changes
uv run cowrie-db migrate
uv run pytest tests/integration/test_snapshot_population_integration.py -v
```

## Performance Notes

- **Test isolation**: Each test uses transaction rollback (no cross-test contamination)
- **Cleanup**: Transactions rolled back after each test (no manual cleanup needed)
- **Speed**: ~2-3 seconds for full suite (8 tests)
- **Parallelization**: Safe to run with `pytest-xdist` (-n auto)

## Related Documentation

- **Design**: `docs/designs/adr007-snapshot-population-fix.md` (Phase 1: Implementation)
- **ADR**: `docs/adr/007-three-tier-enrichment-architecture.md`
- **Unit Tests**: `tests/unit/test_snapshot_population.py` (SQLite-compatible tests)
- **GitHub Issue**: #141 (P0: Snapshot Population Bug)
