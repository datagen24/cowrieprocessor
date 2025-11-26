# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Cowrie Processor is a Python-based framework for processing and analyzing Cowrie honeypot logs from multiple sensors. It provides centralized database storage, threat intelligence enrichment, Elasticsearch reporting, and advanced threat detection capabilities. The project uses SQLAlchemy 2.0 ORM, supports both SQLite and PostgreSQL, and integrates with multiple security services (VirusTotal, DShield, URLHaus, SPUR, HIBP).

## Development Environment

### Python Environment Setup
- **Target Python version**: 3.13 (minimum: 3.13)
- **Package manager**: `uv` (MANDATORY - do not use pip directly)
- **Environment setup**: `uv sync` (installs all dependencies including dev tools)
- **Running commands**: Always use `uv run <command>` (e.g., `uv run python process_cowrie.py`)

### CI Gates (MANDATORY - Enforced in Order)
The CI pipeline enforces these quality gates **in strict order**. Any failure stops the merge:

1. **Ruff Lint Errors**: `uv run ruff check .` must produce 0 errors
2. **Ruff Format Changes**: `uv run ruff format --check .` must show no formatting needed
3. **MyPy Errors**: `uv run mypy .` must produce 0 type errors
4. **Code Coverage**: `uv run pytest --cov=. --cov-report=term-missing --cov-fail-under=65` must achieve ≥65% coverage
5. **Test Failures**: All tests must pass

**Pre-Commit Checklist** - Run these commands before ANY commit:
```bash
uv run ruff format .           # Auto-format code
uv run ruff check .            # Lint checks (Gate 1)
uv run mypy .                  # Type checking (Gate 2)
uv run pytest --cov=. --cov-report=term-missing --cov-fail-under=65  # Tests with coverage (Gates 4-5)
```

## Key Commands

### Testing
```bash
# Run all tests with coverage (65% minimum required by CI)
uv run pytest --cov=. --cov-report=term-missing --cov-fail-under=65

# Run specific test categories
uv run pytest tests/unit/                    # Fast unit tests only
uv run pytest tests/integration/             # Integration tests
uv run pytest tests/performance/             # Performance benchmarks

# Run tests by marker
uv run pytest -m "unit"                      # Unit tests
uv run pytest -m "integration"               # Integration tests
uv run pytest -m "enrichment"                # Enrichment-specific tests

# Offline enrichment harness (no network calls)
uv run pytest tests/integration/test_enrichment_flow.py::test_high_risk_session_full_enrichment
```

### Linting and Type Checking
```bash
# Format and lint (run together)
uv run ruff format .
uv run ruff check .

# Type checking
uv run mypy .

# Pre-commit hooks (runs all checks)
uv run pre-commit install
uv run pre-commit run --all-files
```

### Data Ingestion (ORM Loaders)
```bash
# Bulk load (initial import or backfill)
uv run cowrie-loader bulk /path/to/logs/*.json \
    --db "postgresql://user:pass@host:port/database" \
    --status-dir /mnt/dshield/data/logs/status \
    --vt-api-key $VT_API_KEY \
    --dshield-email $DSHIELD_EMAIL

# Delta load (incremental updates)
uv run cowrie-loader delta /path/to/logs/*.json \
    --db "postgresql://user:pass@host:port/database" \
    --status-dir /mnt/dshield/data/logs/status

# Multiline JSON support (for pretty-printed logs)
uv run cowrie-loader bulk /path/to/logs/*.json.bz2 \
    --db "postgresql://..." \
    --multiline-json
```

### Enrichment

**Performance Note**: As of 2025-11-06, IP enrichment uses synchronous Cymru batching for 33x faster performance. The `--ips` flag triggers 3-pass enrichment:
1. **Pass 1**: MaxMind GeoIP2 (offline, fast)
2. **Pass 2**: Team Cymru bulk ASN lookups (500 IPs per batch via netcat)
3. **Pass 3**: GreyNoise + database merge

This eliminates DNS timeout warnings and processes 10,000 IPs in ~11 minutes (vs ~16 minutes pre-optimization).

```bash
# Password enrichment (HIBP)
uv run cowrie-enrich passwords --last-days 30 --progress

# SSH key enrichment
uv run cowrie-enrich-ssh-keys --last-days 7 --progress

# IP enrichment with Cymru batching (recommended for large sets)
uv run cowrie-enrich refresh --sessions 0 --files 0 --ips 1000 --verbose

# Refresh all stale IPs (>30 days old)
uv run cowrie-enrich refresh --ips 0 --verbose

# Refresh all data types (sessions, files, IPs)
uv run cowrie-enrich refresh --sessions 1000 --files 500 --ips 100 --verbose

# View top passwords
uv run cowrie-enrich top-passwords --last-days 30 --limit 20
```

### Database Management
```bash
# Run schema migrations
uv run cowrie-db migrate

# Check database health
uv run cowrie-db check --verbose

# Create backup
uv run cowrie-db backup --output /backups/cowrie_$(date +%Y%m%d).sqlite

# Optimize database (VACUUM and reindex)
uv run cowrie-db optimize

# Check integrity
uv run cowrie-db integrity
```

### Reporting
```bash
# Daily reports for all sensors
uv run cowrie-report daily 2025-09-14 --db "postgresql://..." --all-sensors --publish

# Weekly rollup
uv run cowrie-report weekly 2025-W37 --db "postgresql://..." --publish

# Monthly aggregation
uv run cowrie-report monthly 2025-09 --db "postgresql://..." --publish
```

### Health and Monitoring
```bash
# Health check
uv run cowrie-health --db "postgresql://..." --verbose

# Monitor progress (real-time)
uv run python scripts/production/monitor_progress.py --status-dir /mnt/dshield/data/logs/status --refresh 2
```

## Architecture Overview

### Multi-Layer Database Design

The system uses a **layered database architecture** optimized for honeypot data processing:

1. **Raw Event Layer** (`raw_events` table)
   - Immutable append-only storage of raw Cowrie JSON events
   - Source tracking with file path, offset, inode, and generation counters
   - Risk scoring and quarantine capabilities for suspicious events
   - Dead Letter Queue (DLQ) tracking for failed processing

2. **Three-Tier Enrichment Architecture** (ADR-007, Schema v16) 🆕
   - **Tier 1 - ASN Inventory** (`asn_inventory` table)
     - Organization-level metadata tracking (most stable)
     - Aggregate statistics (unique IPs, total sessions)
     - Enrichment from multiple sources (Cymru, SPUR, MaxMind)
   - **Tier 2 - IP Inventory** (`ip_inventory` table)
     - Current state enrichment with staleness tracking (mutable)
     - Computed columns for fast filtering (geo_country, ip_types, is_scanner)
     - Foreign key to ASN inventory, 30-90 day refresh cycle
   - **Tier 3 - Session Summaries** (`session_summaries` table)
     - Point-in-time snapshot columns (immutable: snapshot_asn, snapshot_country, snapshot_ip_type)
     - Full enrichment JSONB for deep analysis
     - Foreign key to IP inventory for JOIN when current state needed

   **Key Benefits**:
   - 82% API call reduction (1.68M → 300K calls for unique IPs)
   - 95% of queries avoid JOINs via snapshot columns (2-5 second response)
   - Temporal accuracy preserved ("what was it at time of attack")
   - ASN-level infrastructure clustering and attribution

3. **File Tracking** (`files` table)
   - SHA256-indexed file metadata for downloaded/uploaded malware
   - VirusTotal enrichment results and threat classifications
   - Duplicate detection across sensors

4. **Password Analytics** (`passwords`, `password_statistics` tables)
   - HIBP breach detection using k-anonymity API
   - Daily aggregated password statistics
   - Novel password tracking (SHA256 hashes)

5. **SSH Key Intelligence** (`ssh_keys`, `ssh_key_observations` tables)
   - SSH key fingerprint tracking across sessions
   - Key type, size, and reuse pattern analysis
   - Cross-sensor key observation tracking

6. **Threat Detection** (`longtail_features`, `longtail_analysis_vectors` tables)
   - Machine learning-based anomaly detection
   - Session behavior vectorization
   - Snowshoe spam and botnet detection

### Directory Structure (Production)
```
/mnt/dshield/
├── data/
│   ├── db/                    # Central database files
│   ├── cache/                 # API response caches (sharded by service)
│   │   ├── virustotal/
│   │   ├── dshield/
│   │   ├── urlhaus/
│   │   └── spur/
│   ├── temp/                  # Temporary processing files
│   └── logs/                  # Application logs
│       └── status/            # Real-time status files (JSON)
├── reports/                   # Per-sensor HTML/JSON reports
│   ├── honeypot-a/
│   └── honeypot-b/
└── [sensor-dirs]/             # Raw Cowrie logs per sensor
    ├── a/NSM/cowrie/
    └── b/NSM/cowrie/
```

### Package Structure

- **`cowrieprocessor/`** - Main package
  - **`cli/`** - Command-line interfaces
    - `ingest.py` - `cowrie-loader` bulk/delta loading
    - `report.py` - `cowrie-report` Elasticsearch reporting
    - `cowrie_db.py` - `cowrie-db` database management
    - `enrich_passwords.py` - `cowrie-enrich` password enrichment
    - `enrich_ssh_keys.py` - `cowrie-enrich-ssh-keys` SSH key enrichment
    - `analyze.py` - `cowrie-analyze` threat analysis
    - `health.py` - `cowrie-health` system health checks
  - **`db/`** - Database layer
    - `models.py` - SQLAlchemy ORM models
    - `engine.py` - Database connection management
    - `migrations.py` - Schema migration system
    - `json_utils.py` - JSON handling for SQLite vs PostgreSQL
  - **`loader/`** - Data ingestion pipelines
    - `bulk.py` - Bulk loading for initial imports
    - `delta.py` - Delta loading for incremental updates
    - `cowrie_schema.py` - Cowrie event schema validation
    - `dlq_processor.py` - Dead Letter Queue processing
  - **`enrichment/`** - API enrichment services
    - `virustotal_handler.py` - VirusTotal file/IP enrichment
    - `cache.py` - Disk-based enrichment cache with TTLs
    - `rate_limiting.py` - Token bucket rate limiting
    - `hibp_client.py` - Have I Been Pwned password checks
    - `ssh_key_extractor.py` - SSH key parsing and analysis
  - **`reporting/`** - Report generation
    - `dal.py` - Data access layer for aggregations
    - `builders.py` - Report structure builders
    - `es_publisher.py` - Elasticsearch ILM publishing
  - **`threat_detection/`** - Advanced threat detection
    - `longtail.py` - ML-based anomaly detection
    - `snowshoe.py` - Snowshoe spam detection
    - `botnet.py` - Botnet behavior analysis
    - `storage.py` - Vector storage for ML features
  - **`telemetry/`** - OpenTelemetry tracing
  - **`utils/`** - Shared utilities

### Project Structure & Configuration

- **`config/`** - Configuration files
  - `sensors.toml` - Multi-sensor configuration (database connections, API keys, log paths)
  - All CLI tools auto-detect config/sensors.toml with fallback to root sensors.toml
- **`archive/`** - Deprecated legacy code (Phase 3 refactoring, October 2025)
  - `process_cowrie.py` - Original monolithic processor (replaced by cowrie-loader)
  - `enrichment_handlers.py` - Legacy enrichment (replaced by cowrieprocessor/enrichment/)
  - `refresh_cache_and_reports.py` - Legacy cache refresh (replaced by cowrie-enrich refresh)
  - `es_reports.py` - Legacy ES reports (replaced by cowrie-report)
  - See `archive/README.md` for migration guides and rollback procedures
- **`scripts/`** - Operational scripts
  - `production/` - Production orchestration (orchestrate_sensors.py, monitor_progress.py)
  - `debug/` - Debugging utilities
  - `migrations/archive/` - Historical migration scripts

**Important**: Tests that import legacy modules (process_cowrie, enrichment_handlers, secrets_resolver, session_enumerator) need updating to use new package paths. See "Current Development Context" section below for migration status.

### Recent Refactoring (October 2025)

**Phase 1** (Commit da40dc7): Break Dependency Cycles
- Migrated 3 core utilities (1,459 lines) from root to package structure
- `secrets_resolver.py` → `cowrieprocessor/utils/secrets.py`
- `session_enumerator.py` → `cowrieprocessor/loader/session_parser.py`
- `enrichment_handlers.py` → `cowrieprocessor/enrichment/handlers.py`
- Eliminated circular dependencies between CLI and legacy code

**Phase 2** (Commits 7343d7f, b7dbf81, 5814686): Modernize Production Tools
- Updated `orchestrate_sensors.py` to use `cowrie-loader` CLI by default
- Implemented secure `--sensor` mode (no secrets on command line)
- Added backward compatibility with `USE_LEGACY_PROCESSOR=true`
- Database credentials now loaded from sensors.toml internally

**Phase 3** (Commit 41fe59b): Archive Legacy Code
- Moved deprecated tools to `archive/` directory
- Reorganized scripts into `scripts/{production,debug,migrations}/`
- Created comprehensive deprecation documentation

**Configuration Cleanup** (Commits 383c63b, 6bc1160):
- Created `config/` directory at project root
- Moved sensors.toml from scripts/production/ to config/
- Updated 8 CLI tools to use config/ path with fallback

**Test Impact**: 13 legacy test files require import path updates (documented in notes/WEEK5-6_SPRINT_PLAN.md Day 23)

### Key Design Patterns

1. **Three-Tier Enrichment** (ADR-007): IP/ASN enrichment normalization with snapshot columns for temporal accuracy 🆕
   - **Tier 1 (ASN)**: Organizational attribution, most stable (yearly updates)
   - **Tier 2 (IP)**: Current mutable state with staleness tracking (30-90 day refresh)
   - **Tier 3 (Session)**: Immutable point-in-time snapshots for campaign clustering
   - **Query Pattern**: Use snapshot columns (NO JOIN) for 95% of queries, JOIN for infrastructure analysis
   - **Benefits**: 82% API reduction, 10x faster queries, temporal accuracy preserved

2. **Enrichment Pipeline**: All API enrichments flow through a unified caching layer with TTLs, rate limiting, and telemetry
3. **ORM-First**: All database operations use SQLAlchemy 2.0 ORM (no raw SQL except stored procedures)
4. **Hybrid Properties**: Cross-database computed logic (PostgreSQL JSONB vs SQLite json_extract) with single source of truth 🆕
5. **Status Emitter**: All long-running operations emit JSON status files for real-time monitoring
6. **Dead Letter Queue**: Failed events are tracked with reason/payload for reprocessing
7. **Feature Flags**: `USE_NEW_ENRICHMENT` environment variable controls enrichment pipeline routing
8. **Dependency Injection**: Services use constructor injection for testability
9. **Batched API Operations** (Nov 2025): Team Cymru ASN enrichment uses bulk netcat interface 🆕
   - **Problem**: Individual DNS lookups caused timeouts and 16-minute enrichment for 10K IPs
   - **Solution**: 3-pass enrichment with bulk_lookup() batching 500 IPs per call
   - **Benefit**: 33x faster, zero DNS timeouts, Team Cymru API compliance
   - **Pattern**: Pass 1 (collect) → Pass 2 (batch API) → Pass 3 (merge)

10. **3-Tier Caching Integration** (Nov 2025): HIBP enrichment performance optimization 🆕
   - **Problem**: Filesystem-only cache (L3) caused 500-1500ms overhead for password enrichment
   - **Solution**: Integrated HybridEnrichmentCache (Redis L1 + Database L2 + Filesystem L3)
   - **Pattern**: Optional hybrid_cache parameter for backward compatibility
   - **Benefit**: 5.16x real-world speedup (1.03 → 5.31 iterations/sec)
   - **Query Pattern**: Try L1 (Redis) → L2 (Database) → L3 (Filesystem) → API
   - **Graceful Degradation**: Falls back to lower tiers if higher tiers unavailable
   - **Cache TTLs**: Redis (1hr), Database (30d), Filesystem (60d per service)

## Code Quality Standards

### Mandatory Requirements (NON-NEGOTIABLE)

1. **Type Hints**: ALL functions, methods, and classes MUST have complete type hints
   - Use `from __future__ import annotations` for forward references
   - NO `Any` types without explicit justification comment

2. **Docstrings**: ALL modules, classes, methods, and functions MUST have Google-style docstrings
   - Include `Args`, `Returns`, `Raises`, and `Examples` sections where applicable

3. **Testing**: Minimum 65% code coverage required (CI Gate #4)
   - New features should target 80%+ coverage
   - Bug fixes MUST include regression tests

4. **Linting**: Code must pass `ruff` with target-version "py313" and line-length 120

5. **Type Checking**: Code must pass `mypy` with strict configuration

### Git Commit Convention

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

## Important Notes for Claude Code

### Database Compatibility

- **SQLite**: Used for development and single-sensor deployments
- **PostgreSQL**: Required for production multi-sensor deployments
- JSON handling differs between databases:
  - SQLite: Uses `json_extract()` function
  - PostgreSQL: Uses `->` and `->>` operators
- Use `get_dialect_name_from_engine()` to detect database type
- JSON columns use SQLAlchemy's `JSON` type (handles both databases)

### Enrichment Services

Active services with API keys:
- **VirusTotal**: File hash analysis (30-day cache, 4 req/min rate limit)
- **DShield**: IP reputation (7-day cache, 30 req/min)
- **URLHaus**: Malware URL detection (3-day cache, 30 req/min)

Mocked services (no API keys required for testing):
- **SPUR**: Mock implementation in test fixtures
- **OTX**: Mock implementation ready for activation
- **AbuseIPDB**: Mock implementation ready for activation

All enrichment tests MUST pass without network access using mock fixtures in `tests/fixtures/enrichment_fixtures.py`.

### Migration Workflow

When modifying database schema:

#### Step 1: Verify ORM-Migration Type Alignment (CRITICAL)
**Before writing any migration code**, check existing ORM column types:
```bash
# Check column types in ORM models
grep -A 2 "source_ip\|ip_address" cowrieprocessor/db/models.py
```

**Type Mapping Rules** (ORM → Migration SQL):
- `Column(String(45))` → `VARCHAR(45)` ⚠️ NOT `TEXT`, NOT `INET`
- `Column(Integer)` → `INTEGER` ⚠️ NOT `INT`, NOT `BIGINT` (unless model specifies BigInteger)
- `Column(JSON)` → `JSON` ⚠️ NOT `JSONB` (unless explicitly using postgresql.JSONB)
- `Column(DateTime(timezone=True))` → `TIMESTAMPTZ`

**Foreign Key Type Consistency**: FK columns MUST have identical types. PostgreSQL will reject:
- `session_summaries.source_ip VARCHAR(45)` → `ip_inventory.ip_address INET` ❌ FAILS
- `session_summaries.source_ip VARCHAR(45)` → `ip_inventory.ip_address VARCHAR(45)` ✅ WORKS

**Red Flags During Development**:
- If you need `::inet`, `::integer`, or `::jsonb` casts in migration queries, your column types are wrong
- Type casts in WHERE clauses or JOINs indicate schema mismatch, not query bugs
- Fix the schema types first, then remove the casts

#### Step 2: Write Migration Logic
1. Update ORM models in `cowrieprocessor/db/models.py` (if adding new tables/columns)
2. Add migration logic to `cowrieprocessor/db/migrations.py`
3. Increment `TARGET_SCHEMA_VERSION` constant
4. Run type validation checks:
   ```bash
   # Check for type cast red flags in migration
   grep "::inet\|::jsonb\|::text" cowrieprocessor/db/migrations.py
   # Should return NO results (casts indicate type mismatches)
   ```

#### Step 3: Test Migration
1. Test on empty SQLite database (fast iteration)
2. Test on PostgreSQL with production-like data
3. Verify foreign key constraints with type checking query:
   ```sql
   SELECT tc.table_name, kcu.column_name, c1.data_type as local_type,
          ccu.table_name AS fk_table, ccu.column_name AS fk_column, c2.data_type as fk_type
   FROM information_schema.table_constraints tc
   JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
   JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name
   JOIN information_schema.columns c1 ON c1.table_name = tc.table_name AND c1.column_name = kcu.column_name
   JOIN information_schema.columns c2 ON c2.table_name = ccu.table_name AND c2.column_name = ccu.column_name
   WHERE tc.constraint_type = 'FOREIGN KEY';
   ```
4. After code changes, **always run** `uv sync` to rebuild package before testing CLI commands

#### Step 4: Documentation
1. Update data dictionary in `docs/data_dictionary.md`
2. Document migration rationale in ADR or PDCA documentation
3. Update recovery procedures if adding new failure modes

**Lesson from ADR-007 (Nov 2025)**: Type mismatch between ORM (VARCHAR) and migration (INET) caused 12 failed attempts. Always validate ORM-migration type alignment BEFORE writing migration logic. See memory: `migration_type_mismatch_debugging_adr007`

### Testing Strategy

1. **Unit tests** (`tests/unit/`): Fast, isolated, no external dependencies
2. **Integration tests** (`tests/integration/`): End-to-end workflows with test database
3. **Performance tests** (`tests/performance/`): Benchmark critical paths
4. **Enrichment harness** (`tests/integration/test_enrichment_flow.py`): Offline enrichment tests with stubbed APIs

Use `USE_MOCK_APIS=true` environment variable to force mock API usage in tests.

### Secret Management

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

### Current Development Context

The project is on the **Test-Suite-refactor** branch with focus on improving test coverage and refactoring enrichment workflows. Recent work includes:
- SQLAlchemy 2.0 migration (completed)
- Enhanced dead letter queue processing
- Longtail threat detection with vector storage
- Password enrichment with HIBP integration
- SSH key intelligence gathering

When making changes, always check the `CONTRIBUTING.md` file and ensure all pre-commit checks pass before opening a pull request.

## Troubleshooting

### Common Issues

1. **Import errors**: Ensure `uv sync` has been run and virtual environment is activated via `uv run`
2. **Database locked**: Use PostgreSQL for concurrent access or ensure single writer for SQLite
3. **Type errors**: Run `uv run mypy .` and fix all errors before committing
4. **Test failures**: Check `tests/fixtures/` for required mock data
5. **Enrichment cache misses**: Verify cache directory permissions at `~/.cache/cowrieprocessor` or custom path

### Running Legacy Processor (ARCHIVED)

⚠️ **ARCHIVED**: The original `process_cowrie.py` script has been moved to `archive/` as of Phase 3 refactoring. Use `cowrie-loader` instead.

The archived script remains available for emergency rollback but is no longer actively maintained:
```bash
# ARCHIVED - Only use for rollback scenarios!
# Requires: cp archive/process_cowrie.py . (restore to root first)
uv run python archive/process_cowrie.py \
    --logpath /path/to/cowrie/logs \
    --sensor honeypot-a \
    --db /path/to/db.sqlite \
    --email your.email@example.com \
    --summarizedays 1
```

**Migration Path**: Replace with `cowrie-loader delta`:
```bash
# NEW - Recommended
uv run cowrie-loader delta /path/to/cowrie/logs/*.json \
    --db sqlite:////path/to/db.sqlite \
    --sensor honeypot-a \
    --dshield-email your.email@example.com \
    --last-days 1 \
    --status-dir /mnt/dshield/data/logs/status
```

### Multi-Sensor Orchestration

For managing multiple sensors, use `scripts/production/orchestrate_sensors.py` with a TOML configuration:
```bash
# Uses cowrie-loader by default (NEW mode)
uv run python scripts/production/orchestrate_sensors.py --config config/sensors.toml

# Force legacy mode if needed
USE_LEGACY_PROCESSOR=true uv run python scripts/production/orchestrate_sensors.py --config config/sensors.toml
# Or: uv run python scripts/production/orchestrate_sensors.py --config config/sensors.toml --legacy
```

See `config/sensors.example.toml` for configuration format.

**New in orchestrate_sensors.py**:
- **Default**: Uses `cowrie-loader delta` (modern CLI)
- **Legacy mode**: Set `USE_LEGACY_PROCESSOR=true` or `--legacy` flag to use `process_cowrie.py`
- **Bulk vs Delta**: Pass `--bulk-load` for initial imports, omit for incremental
- **Backward compatible**: Existing TOML configs work with both modes
