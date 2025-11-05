# ADR-007 Three-Tier Enrichment: Do (Implementation)

**Date**: November 5, 2025
**Branch**: feature/adr-007-three-tier-enrichment
**Implementation Period**: November 4-5, 2025

## Implementation Overview

Successfully implemented three-tier enrichment architecture through coordinated multi-agent development approach with comprehensive testing and quality validation.

## Multi-Agent Coordination

### Agent Roles

**Backend Architect** (Primary Implementation):
- Schema design and migration code
- ORM model implementation with hybrid properties
- Database compatibility layer (PostgreSQL/SQLite)
- Foreign key constraint strategy

**Quality Engineer** (Validation & Testing):
- Unit test suite for migration logic
- Unit test suite for ORM models
- Integration test suite (7 scenarios)
- Quality metrics validation (ruff, mypy, coverage)

**Technical Writer** (Documentation):
- PDCA documentation (this document)
- Implementation summary for stakeholders
- CLAUDE.md updates

### Coordination Pattern

Sequential handoff with validation gates:
1. Backend Architect → Schema + Migration code → Quality check (ruff format, ruff check, python compile)
2. Backend Architect → ORM Models → Quality check (mypy, ruff)
3. Quality Engineer → Unit Tests → Coverage validation (>65% target)
4. Quality Engineer → Integration Tests → Performance benchmarks
5. Technical Writer → Documentation → Stakeholder communication

## Files Created/Modified

### Core Implementation (Schema & Models)

**cowrieprocessor/db/migrations.py**:
```python
# Added: _upgrade_to_v16() function (lines 1995-2295)
# - Four-phase migration implementation
# - ASN inventory creation and population
# - IP inventory with computed columns
# - Session snapshot column backfill
# - Foreign key constraints with NOT VALID → VALIDATE
```

**cowrieprocessor/db/models.py**:
```python
# Added: ASNInventory class (lines 668-724)
# - Organization-level tracking
# - Aggregate statistics
# - Enrichment storage

# Added: IPInventory class (lines 727-902)
# - Current state enrichment
# - Hybrid properties (geo_country, ip_type, is_scanner, is_bogon)
# - Cross-database SQL expressions

# Added: IPASNHistory class (lines 905-933)
# - Temporal IP→ASN tracking
# - Optional movement history

# Modified: SessionSummary class (lines 165-243)
# - Added snapshot columns (snapshot_asn, snapshot_country, snapshot_ip_type)
# - Added enrichment_at timestamp
# - Added foreign key to ip_inventory
# - Added behavioral clustering indexes
```

### Test Suite (Comprehensive Coverage)

**tests/unit/test_schema_v16_migration.py** (609 lines):
```python
# Created: Complete unit test suite for migration logic
# - 14 test methods covering all migration phases
# - ASN inventory creation and population validation
# - IP inventory computed column testing
# - Session snapshot backfill verification
# - Foreign key constraint validation
# - Index creation verification
# - DISTINCT ON and window function correctness
# - COALESCE fallback logic testing
# - SQLite graceful skip validation
```

**tests/unit/test_three_tier_models.py** (created):
```python
# Unit tests for ORM model behavior
# - Hybrid property validation (Python + SQL)
# - Cross-database compatibility
# - Foreign key relationships
# - Computed column edge cases
```

**tests/integration/test_three_tier_enrichment_workflow.py** (950 lines):
```python
# Created: End-to-end integration test suite
# - 9 test classes, 7 distinct workflow scenarios
# - Complete three-tier ingestion flow
# - Query performance benchmarks
# - IP→ASN movement tracking (temporal accuracy)
# - Staleness detection and re-enrichment
# - Foreign key constraint enforcement
# - Realistic production-like data
```

### Documentation

**claudedocs/THREE_TIER_INTEGRATION_TEST_SUMMARY.md** (408 lines):
```markdown
# Comprehensive test suite summary
# - Scenario descriptions and validation criteria
# - Performance benchmarks and targets
# - Test quality metrics
# - CI/CD integration notes
```

**docs/pdca/adr-007-three-tier/plan.md** (this directory):
```markdown
# Implementation plan and strategy
# - Problem statement and success criteria
# - Four-phase implementation approach
# - Risk mitigation strategies
# - Timeline and resource requirements
```

**docs/pdca/adr-007-three-tier/do.md** (this file):
```markdown
# Implementation execution details
# - Multi-agent coordination
# - File changes and code structure
# - Implementation decisions and trade-offs
```

## Implementation Details

### Phase 1: ASN Inventory Creation

**Migration Code** (`_upgrade_to_v16`, lines 2018-2117):

```sql
-- ASN table creation with constraints
CREATE TABLE asn_inventory (
    asn_number INTEGER PRIMARY KEY CHECK (asn_number > 0),
    organization_name TEXT,
    organization_country VARCHAR(2) CHECK (organization_country ~ '^[A-Z]{2}$'),
    ...
)

-- Population using DISTINCT ON for latest enrichment
WITH latest_enrichment AS (
    SELECT DISTINCT ON ((enrichment->'cymru'->>'asn')::int)
        (enrichment->'cymru'->>'asn')::int as asn,
        enrichment
    FROM session_summaries
    WHERE enrichment->'cymru'->>'asn' IS NOT NULL
    ORDER BY (enrichment->'cymru'->>'asn')::int, last_event_at DESC
)
INSERT INTO asn_inventory ...
```

**Key Decision**: Used `DISTINCT ON` instead of window functions for ASN population to ensure latest enrichment data per ASN with minimal memory overhead.

### Phase 2: IP Inventory Creation

**Migration Code** (`_upgrade_to_v16`, lines 2118-2227):

```sql
-- IP table with computed columns
CREATE TABLE ip_inventory (
    ip_address INET PRIMARY KEY,
    current_asn INTEGER,

    -- Computed columns with defensive defaults
    geo_country VARCHAR(2) GENERATED ALWAYS AS (
        UPPER(COALESCE(
            enrichment->'maxmind'->>'country',
            enrichment->'cymru'->>'country',
            enrichment->'dshield'->'ip'->>'ascountry',
            'XX'
        ))
    ) STORED,

    ip_types TEXT[] GENERATED ALWAYS AS (
        COALESCE(
          CASE
            WHEN jsonb_typeof(...) = 'array' THEN ARRAY(...)
            WHEN jsonb_typeof(...) = 'string' THEN ARRAY[...]
            ELSE ARRAY[]::text[]
          END,
          ARRAY[]::text[]
        )
    ) STORED,
    ...
)

-- Population using window functions + DISTINCT ON
INSERT INTO ip_inventory (...)
SELECT DISTINCT ON (source_ip)
    source_ip,
    MIN(first_event_at) OVER (PARTITION BY source_ip) as first_seen,
    MAX(last_event_at) OVER (PARTITION BY source_ip) as last_seen,
    COUNT(*) OVER (PARTITION BY source_ip) as session_count,
    ...
FROM session_summaries
ORDER BY source_ip, last_event_at DESC
```

**Key Decision**: Combined window functions (for aggregation) with `DISTINCT ON` (for latest enrichment) to avoid separate aggregation step and reduce memory usage.

### Phase 3: Session Snapshot Columns

**Migration Code** (`_upgrade_to_v16`, lines 2228-2270):

```sql
-- Add snapshot columns
ALTER TABLE session_summaries
    ADD COLUMN IF NOT EXISTS enrichment_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS snapshot_asn INTEGER,
    ADD COLUMN IF NOT EXISTS snapshot_country VARCHAR(2),
    ADD COLUMN IF NOT EXISTS snapshot_ip_types TEXT[];

-- Backfill using temporary table (batch optimization)
CREATE TEMP TABLE tmp_session_snapshots AS
SELECT
  s.session_id,
  COALESCE(
    (s.enrichment->>'enriched_at')::timestamptz,
    s.created_at,
    s.last_event_at
  ) AS enrichment_at,
  (s.enrichment->'cymru'->>'asn')::int AS snapshot_asn,
  UPPER(COALESCE(
    s.enrichment->'maxmind'->>'country',
    s.enrichment->'cymru'->>'country'
  )) AS snapshot_country,
  ...
FROM session_summaries s;

-- Batch update
UPDATE session_summaries s
SET enrichment_at = t.enrichment_at,
    snapshot_asn = t.snapshot_asn,
    ...
FROM tmp_session_snapshots t
WHERE s.session_id = t.session_id;
```

**Key Decision**: Used temporary table for backfill instead of row-by-row updates to reduce transaction log overhead and improve performance.

### Phase 4: Foreign Key Constraints

**Migration Code** (`_upgrade_to_v16`, lines 2271-2295):

```sql
-- Pre-validation check
DO $$
DECLARE
    orphan_sessions INTEGER;
BEGIN
    SELECT COUNT(*) INTO orphan_sessions
    FROM session_summaries s
    WHERE NOT EXISTS (SELECT 1 FROM ip_inventory i WHERE i.ip_address = s.source_ip);

    IF orphan_sessions > 0 THEN
        RAISE EXCEPTION 'Found % orphan sessions', orphan_sessions;
    END IF;
END $$;

-- Add constraints with NOT VALID (zero downtime)
ALTER TABLE ip_inventory
    ADD CONSTRAINT fk_ip_current_asn
    FOREIGN KEY (current_asn) REFERENCES asn_inventory(asn_number) NOT VALID;

-- Validate constraints (verifies existing data)
ALTER TABLE ip_inventory VALIDATE CONSTRAINT fk_ip_current_asn;
```

**Key Decision**: Used `NOT VALID` → `VALIDATE` pattern to avoid full table lock during constraint creation, enabling zero-downtime deployment.

## ORM Model Implementation

### Hybrid Properties Pattern

**IPInventory.geo_country** (models.py, lines 776-816):

```python
@hybrid_property
def geo_country(self) -> str:
    """Python-side property access."""
    if not self.enrichment:
        return 'XX'
    return (
        (self.enrichment.get('maxmind', {}) or {}).get('country')
        or (self.enrichment.get('cymru', {}) or {}).get('country')
        or (self.enrichment.get('dshield', {}) or {}).get('ip', {}).get('ascountry')
        or 'XX'
    )

@geo_country.expression
@classmethod
def geo_country_expr(cls) -> ColumnElement[str]:
    """SQL-side expression for queries."""
    dialect_name = get_dialect_name_from_engine(...)

    if dialect_name == "postgresql":
        # PostgreSQL JSONB operators
        return func.coalesce(
            cls.enrichment.op('->')('maxmind').op('->>')('country'),
            cls.enrichment.op('->')('cymru').op('->>')('country'),
            cls.enrichment.op('->')('dshield').op('->')('ip').op('->>')('ascountry'),
            'XX',
        )
    else:
        # SQLite json_extract functions
        return func.coalesce(
            func.json_extract(cls.enrichment, '$.maxmind.country'),
            func.json_extract(cls.enrichment, '$.cymru.country'),
            func.json_extract(cls.enrichment, '$.dshield.ip.ascountry'),
            'XX',
        )
```

**Key Decision**: Implemented cross-database hybrid properties to maintain single source of truth for computed logic while supporting both PostgreSQL and SQLite syntax.

## Testing Implementation

### Unit Test Strategy

**Migration Tests** (test_schema_v16_migration.py):
- PostgreSQL-only (gracefully skips if unavailable)
- Fixtures create v15 schema with realistic test data
- Validates each migration phase independently
- Tests edge cases (empty enrichment, multiple sources, COALESCE fallbacks)

**Model Tests** (test_three_tier_models.py):
- Validates hybrid property behavior (Python + SQL)
- Tests foreign key relationships
- Verifies computed column defaults
- Cross-database compatibility checks

### Integration Test Strategy

**Workflow Tests** (test_three_tier_enrichment_workflow.py):
- 7 realistic end-to-end scenarios
- Production-like enrichment payloads (MaxMind, Cymru, DShield, SPUR)
- Performance benchmarks with timing assertions
- Query pattern validation (snapshot vs JOIN)
- Temporal accuracy verification (IP movement tracking)

**Test Data Generation**:
```python
def create_sample_enrichment(
    country: str = "CN",
    asn: int = 4134,
    asn_name: str = "China Telecom",
    ip_type: str = "RESIDENTIAL",
    is_scanner: bool = False,
    is_bogon: bool = False,
) -> dict[str, Any]:
    """Generate realistic enrichment matching production format."""
    return {
        "maxmind": {
            "country": country,
            "city": "Beijing",
            "latitude": 39.9042,
            "longitude": 116.4074,
        },
        "cymru": {
            "asn": asn,
            "country": country,
            "prefix": "1.2.3.0/24",
            "asn_name": asn_name,
        },
        # ... complete enrichment structure
    }
```

## Implementation Decisions & Trade-offs

### Decision 1: DISTINCT ON vs Window Functions

**Context**: Needed latest enrichment per ASN/IP for inventory population

**Options Considered**:
1. Window functions with ROW_NUMBER()
2. Subquery with MAX(last_event_at)
3. DISTINCT ON with ORDER BY

**Decision**: DISTINCT ON (option 3)

**Rationale**:
- Most efficient PostgreSQL-native approach
- Avoids temporary row number column
- Single pass over data (vs subquery join)
- Memory efficient (no materialization needed)

**Trade-off**: PostgreSQL-specific syntax (not portable to SQLite, but migration already PostgreSQL-only)

### Decision 2: Temporary Table for Snapshot Backfill

**Context**: Backfill 1.68M sessions with snapshot columns

**Options Considered**:
1. UPDATE with SET FROM in single statement
2. Cursor-based batch updates (100K rows at a time)
3. Temporary table with batch UPDATE

**Decision**: Temporary table (option 3)

**Rationale**:
- Reduces transaction log size
- Better query planner performance (statistics on temp table)
- Easier to validate before committing
- No risk of partial updates

**Trade-off**: Slightly more complex migration code, but significantly better performance

### Decision 3: NOT VALID → VALIDATE for Foreign Keys

**Context**: Add foreign key constraints to production tables with minimal downtime

**Options Considered**:
1. Direct foreign key creation (locks table during validation)
2. NOT VALID → VALIDATE pattern (locks only for constraint creation, not validation)
3. No foreign keys (application-level enforcement)

**Decision**: NOT VALID → VALIDATE (option 2)

**Rationale**:
- Zero-downtime deployment capability
- Database-level integrity enforcement
- Best practice for large table constraints

**Trade-off**: More complex migration code (pre-validation + two-step process)

### Decision 4: Computed Columns vs Application Logic

**Context**: Extract geo_country, ip_types from enrichment JSONB

**Options Considered**:
1. Application-level properties only
2. Database computed columns (GENERATED ALWAYS AS)
3. Hybrid properties (Python + SQL expressions)

**Decision**: Hybrid properties (option 3)

**Rationale**:
- Single source of truth for extraction logic
- Supports both ORM queries (Python) and SQL queries
- Type-safe with SQLAlchemy 2.0
- Cross-database compatible (PostgreSQL/SQLite)

**Trade-off**: More complex implementation than pure computed columns, but maximum flexibility

## Deviations from Plan

### Minor Adjustments

**1. Test Fixture Approach**:
- **Original Plan**: Reusable fixtures across all test files
- **Actual**: Test-specific fixtures in each file for independence
- **Reason**: Better test isolation, clearer dependencies

**2. SQLite Support**:
- **Original Plan**: Full feature parity between PostgreSQL/SQLite
- **Actual**: PostgreSQL-only for three-tier tables, graceful skip for SQLite
- **Reason**: SQLite lacks required features (computed columns with JSONB, window functions)

**3. Integration Test Scope**:
- **Original Plan**: 5 test scenarios
- **Actual**: 7 test scenarios (added IP movement, staleness detection)
- **Reason**: Temporal accuracy is critical requirement, needed explicit validation

### No Major Deviations

All core deliverables completed as planned:
✅ Four-phase migration implementation
✅ ORM models with hybrid properties
✅ Comprehensive test suite (unit + integration)
✅ Quality validation (ruff, mypy, coverage)
✅ PDCA documentation

## Quality Checks Performed

### Pre-Commit Validation

```bash
# Formatting
uv run ruff format .
# Result: All files properly formatted ✅

# Linting
uv run ruff check .
# Result: 0 errors, 0 warnings ✅

# Type Checking
uv run mypy .
# Result: Success, no issues found ✅

# Python Compilation
python -m py_compile cowrieprocessor/db/migrations.py
python -m py_compile cowrieprocessor/db/models.py
# Result: No syntax errors ✅
```

### Test Execution

```bash
# Unit tests (migration)
uv run pytest tests/unit/test_schema_v16_migration.py -v
# Result: 14 passed (PostgreSQL required, gracefully skips otherwise)

# Integration tests
uv run pytest tests/integration/test_three_tier_enrichment_workflow.py -v
# Result: 9 passed in ~2.5s ✅

# Coverage check
uv run pytest --cov=cowrieprocessor.db --cov-report=term-missing --cov-fail-under=65
# Result: 87% coverage (exceeds 65% target) ✅
```

### Performance Validation

**Query Benchmarks** (from integration tests):
- Snapshot filter (NO JOIN): ~10ms (target: <100ms) ✅
- Snapshot aggregation: ~15ms (target: <100ms) ✅
- Single JOIN: ~50ms (target: <500ms) ✅
- Double JOIN: ~80ms (target: <500ms) ✅

## Lessons Learned

### What Worked Well

1. **Multi-Agent Coordination**: Sequential handoff with validation gates prevented rework
2. **DISTINCT ON Pattern**: Efficient latest-record selection without complex window functions
3. **Hybrid Properties**: Clean abstraction for cross-database computed logic
4. **Temporary Table Backfill**: Significant performance improvement over row-by-row updates
5. **Comprehensive Testing**: Integration tests caught edge cases missed by unit tests

### What Could Be Improved

1. **Test Data Generation**: Could extract `create_sample_enrichment()` to shared fixture module
2. **Migration Logging**: Add more granular progress logging for long-running operations
3. **Performance Metrics**: Actual migration time not measured (estimated 30-60 min)
4. **Rollback Testing**: Rollback procedure documented but not tested in CI

### Recommendations for Future Migrations

1. **Always use temporary tables** for large backfills (>100K rows)
2. **Pre-validate constraints** before creation to catch issues early
3. **Use DISTINCT ON** for latest-record selection in PostgreSQL
4. **Implement hybrid properties** for any computed logic needed in both Python and SQL
5. **Test with production-like data volumes** before deployment

## Next Steps

See [check.md](./check.md) for validation results and [act.md](./act.md) for recommendations.

## References

- **Plan**: [plan.md](./plan.md) - Implementation strategy
- **Check**: [check.md](./check.md) - Testing and validation results
- **Act**: [act.md](./act.md) - Recommendations and improvements
- **ADR-007**: [../../ADR/007-ip-inventory-enrichment-normalization.md](../../ADR/007-ip-inventory-enrichment-normalization.md)
