# Codebase Structure

## Top-Level Directories

```
/Users/speterson/src/dshield/cowrieprocessor/
├── cowrieprocessor/          # Main package
├── tests/                    # Test suite
├── scripts/                  # Operational scripts
├── config/                   # Configuration files
├── docs/                     # Sphinx documentation
├── archive/                  # Deprecated legacy code (Phase 3, Oct 2025)
├── data/                     # Runtime data (not in version control)
├── reports/                  # Generated reports (not in version control)
├── notes/                    # Development notes
└── .github/                  # GitHub Actions CI/CD
```

## Package Structure: `cowrieprocessor/`

```
cowrieprocessor/
├── cli/                      # Command-line interfaces
│   ├── ingest.py            # cowrie-loader (bulk/delta loading)
│   ├── report.py            # cowrie-report (Elasticsearch reporting)
│   ├── cowrie_db.py         # cowrie-db (database management)
│   ├── enrich_passwords.py  # cowrie-enrich (HIBP password enrichment)
│   ├── enrich_ssh_keys.py   # cowrie-enrich-ssh-keys (SSH key analysis)
│   ├── analyze.py           # cowrie-analyze (threat analysis)
│   └── health.py            # cowrie-health (system health checks)
├── db/                       # Database layer
│   ├── models.py            # SQLAlchemy ORM models
│   ├── engine.py            # Database connection management
│   ├── migrations.py        # Schema migration system
│   └── json_utils.py        # JSON handling (SQLite vs PostgreSQL)
├── loader/                   # Data ingestion pipelines
│   ├── bulk.py              # Bulk loading (initial imports)
│   ├── delta.py             # Delta loading (incremental updates)
│   ├── cowrie_schema.py     # Cowrie event schema validation
│   └── dlq_processor.py     # Dead Letter Queue processing
├── enrichment/              # API enrichment services
│   ├── virustotal_handler.py # VirusTotal file/IP enrichment
│   ├── cache.py             # Disk-based enrichment cache with TTLs
│   ├── rate_limiting.py     # Token bucket rate limiting
│   ├── hibp_client.py       # Have I Been Pwned password checks
│   └── ssh_key_extractor.py # SSH key parsing and analysis
├── reporting/               # Report generation
│   ├── dal.py               # Data access layer for aggregations
│   ├── builders.py          # Report structure builders
│   └── es_publisher.py      # Elasticsearch ILM publishing
├── threat_detection/        # Advanced threat detection
│   ├── longtail.py          # ML-based anomaly detection
│   ├── snowshoe.py          # Snowshoe spam detection
│   ├── botnet.py            # Botnet behavior analysis
│   └── storage.py           # Vector storage for ML features
├── telemetry/               # OpenTelemetry tracing
├── utils/                   # Shared utilities
├── settings.py              # Application settings
└── status_emitter.py        # Real-time status monitoring
```

## Test Structure: `tests/`

```
tests/
├── unit/                    # Fast, isolated unit tests
│   ├── test_db/            # Database layer tests
│   ├── test_enrichment/    # Enrichment logic tests
│   ├── test_loader/        # Loader logic tests
│   └── test_utils/         # Utility function tests
├── integration/             # End-to-end integration tests
│   ├── test_enrichment_flow.py  # Offline enrichment harness
│   └── test_full_pipeline.py   # Complete pipeline tests
├── performance/             # Performance benchmarks
├── fixtures/                # Test fixtures and mocks
│   └── enrichment_fixtures.py  # Mock API responses
├── debug/                   # Debugging test utilities
└── conftest.py             # pytest configuration
```

## Scripts: `scripts/`

```
scripts/
├── production/              # Production orchestration
│   ├── orchestrate_sensors.py  # Multi-sensor management
│   └── monitor_progress.py     # Real-time progress monitoring
├── debug/                   # Debugging utilities
└── migrations/              # Database migration scripts
    └── archive/             # Historical migrations
```

## Configuration: `config/`

```
config/
└── sensors.toml             # Multi-sensor configuration
    # Contains: database connections, API keys, log paths
    # Auto-detected by CLI tools with fallback to root sensors.toml
```

## Archive: `archive/` (Phase 3 Refactoring, Oct 2025)

**⚠️ ARCHIVED - Use package code instead**

```
archive/
├── process_cowrie.py        # Original monolithic processor → cowrie-loader
├── enrichment_handlers.py   # Legacy enrichment → cowrieprocessor/enrichment/
├── refresh_cache_and_reports.py  # Legacy cache refresh → cowrie-enrich
├── es_reports.py            # Legacy ES reports → cowrie-report
└── README.md                # Migration guides and rollback procedures
```

**Migration Status**: 13 legacy test files require import path updates (see notes/WEEK5-6_SPRINT_PLAN.md Day 23)

## Documentation: `docs/`

```
docs/
├── conf.py                  # Sphinx configuration
├── index.rst                # Documentation home
├── data_dictionary.md       # Database schema reference
├── api/                     # API documentation
└── adr/                     # Architecture Decision Records
```

## Entry Points (CLI Commands)

Defined in `pyproject.toml`:
- `cowrie-loader` → `cowrieprocessor.cli.ingest:main`
- `cowrie-report` → `cowrieprocessor.cli.report:main`
- `cowrie-health` → `cowrieprocessor.cli.health:main`
- `cowrie-db` → `cowrieprocessor.cli.cowrie_db:main`
- `cowrie-analyze` → `cowrieprocessor.cli.analyze:main`
- `cowrie-enrich` → `cowrieprocessor.cli.enrich_passwords:main`
- `cowrie-enrich-ssh-keys` → `cowrieprocessor.cli.enrich_ssh_keys:main`

## Key Files

- **pyproject.toml**: Project metadata, dependencies, tool configuration (ruff, mypy, coverage)
- **uv.lock**: Locked dependencies (managed by uv)
- **pytest.ini**: pytest configuration
- **.pre-commit-config.yaml**: Pre-commit hooks configuration
- **CLAUDE.md**: Comprehensive guide for AI assistants (this file!)
- **CONTRIBUTING.md**: Contribution guidelines
- **CHANGELOG.md**: Version history and changes
- **README.md**: Project overview and setup instructions

## Production Directory Structure

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

## Navigation Tips

**When exploring code**:
1. Start with `get_symbols_overview` for file structure
2. Use `find_symbol` with `depth=1` to see class methods
3. Only use `include_body=True` when you need implementation details
4. Use `find_referencing_symbols` to understand dependencies

**When modifying code**:
1. Check `archive/` is not modified (use package code instead)
2. Update tests in parallel with implementation
3. Run pre-commit checklist before committing
4. Use symbolic editing tools for symbol operations
