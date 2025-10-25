# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Cowrie Processor is a Python-based framework for processing and analyzing Cowrie honeypot logs from multiple sensors. It provides centralized database storage, threat intelligence enrichment, Elasticsearch reporting, and advanced threat detection capabilities. The project uses SQLAlchemy 2.0 ORM, supports both SQLite and PostgreSQL, and integrates with multiple security services (VirusTotal, DShield, URLHaus, SPUR, HIBP).

## Development Environment

### Python Environment Setup
- **Target Python version**: 3.13 (minimum: 3.9)
- **Package manager**: `uv` (MANDATORY - do not use pip directly)
- **Environment setup**: `uv sync` (installs all dependencies including dev tools)
- **Running commands**: Always use `uv run <command>` (e.g., `uv run python process_cowrie.py`)

### Required Pre-Commit Checks
Before ANY commit, these commands MUST pass:
```bash
uv run ruff format .           # Auto-format code
uv run ruff check .            # Lint checks
uv run mypy .                  # Type checking
uv run pytest --cov=. --cov-report=term-missing --cov-fail-under=80  # Tests with 80% coverage
```

## Key Commands

### Testing
```bash
# Run all tests with coverage (80% minimum required)
uv run pytest --cov=. --cov-report=term-missing --cov-fail-under=80

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
```bash
# Password enrichment (HIBP)
uv run cowrie-enrich passwords --last-days 30 --progress

# SSH key enrichment
uv run cowrie-enrich-ssh-keys --last-days 7 --progress

# Refresh existing enrichments
uv run cowrie-enrich refresh --sessions 0 --files 0 --verbose

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
uv run python monitor_progress.py --status-dir /mnt/dshield/data/logs/status --refresh 2
```

## Architecture Overview

### Multi-Layer Database Design

The system uses a **layered database architecture** optimized for honeypot data processing:

1. **Raw Event Layer** (`raw_events` table)
   - Immutable append-only storage of raw Cowrie JSON events
   - Source tracking with file path, offset, inode, and generation counters
   - Risk scoring and quarantine capabilities for suspicious events
   - Dead Letter Queue (DLQ) tracking for failed processing

2. **Session Aggregation Layer** (`session_summaries` table)
   - Aggregates events into logical attack sessions
   - Stores enrichment data (VirusTotal, DShield, URLHaus, SPUR, HIBP)
   - Computed flags for malware/reputation detection (`vt_flagged`, `dshield_flagged`)
   - Tracks commands, file operations, and authentication attempts per session

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

### Key Design Patterns

1. **Enrichment Pipeline**: All API enrichments flow through a unified caching layer with TTLs, rate limiting, and telemetry
2. **ORM-First**: All database operations use SQLAlchemy 2.0 ORM (no raw SQL except stored procedures)
3. **Status Emitter**: All long-running operations emit JSON status files for real-time monitoring
4. **Dead Letter Queue**: Failed events are tracked with reason/payload for reprocessing
5. **Feature Flags**: `USE_NEW_ENRICHMENT` environment variable controls enrichment pipeline routing
6. **Dependency Injection**: Services use constructor injection for testability

## Code Quality Standards

### Mandatory Requirements (NON-NEGOTIABLE)

1. **Type Hints**: ALL functions, methods, and classes MUST have complete type hints
   - Use `from __future__ import annotations` for forward references
   - NO `Any` types without explicit justification comment

2. **Docstrings**: ALL modules, classes, methods, and functions MUST have Google-style docstrings
   - Include `Args`, `Returns`, `Raises`, and `Examples` sections where applicable

3. **Testing**: Minimum 80% code coverage required
   - New features require 90%+ coverage
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
1. Update ORM models in `cowrieprocessor/db/models.py`
2. Add migration logic to `cowrieprocessor/db/migrations.py`
3. Increment `TARGET_SCHEMA_VERSION` constant
4. Test migration on both SQLite and PostgreSQL
5. Update data dictionary in `docs/data_dictionary.md`

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

### Running Legacy Processor (DEPRECATED)

⚠️ **DEPRECATED**: The original `process_cowrie.py` script is being phased out. Use `cowrie-loader` instead.

For backward compatibility, it remains functional but will be removed in a future release:
```bash
# DEPRECATED - Use cowrie-loader instead!
uv run python process_cowrie.py \
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

For managing multiple sensors, use `orchestrate_sensors.py` with a TOML configuration:
```bash
# Uses cowrie-loader by default (NEW mode)
uv run python orchestrate_sensors.py --config sensors.toml

# Force legacy mode if needed
USE_LEGACY_PROCESSOR=true uv run python orchestrate_sensors.py --config sensors.toml
# Or: uv run python orchestrate_sensors.py --config sensors.toml --legacy
```

See `sensors.example.toml` for configuration format.

**New in orchestrate_sensors.py**:
- **Default**: Uses `cowrie-loader delta` (modern CLI)
- **Legacy mode**: Set `USE_LEGACY_PROCESSOR=true` or `--legacy` flag to use `process_cowrie.py`
- **Bulk vs Delta**: Pass `--bulk-load` for initial imports, omit for incremental
- **Backward compatible**: Existing TOML configs work with both modes
