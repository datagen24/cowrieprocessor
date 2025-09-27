# Cowrie Processor

[![Lint and Type Check](https://github.com/datagen24/cowrieprocessor/actions/workflows/ci.yml/badge.svg)](https://github.com/datagen24/cowrieprocessor/actions/workflows/ci.yml)
Note: If you are working in a fork, update the badge URLs to your `owner/repo`.

A centralized Python framework for processing and analyzing Cowrie honeypot logs from multiple sensors, with integration to various security services and Elasticsearch reporting.

## Project Evolution

This project began as a fork of the original [cowrieprocessor](https://github.com/jslagrew/cowrieprocessor) by Jessie Lagrew, which was designed to process Cowrie logs on individual DShield honeypots. The current implementation has diverged substantially from the original work, evolving into a comprehensive centralized processing framework that:

- Supports multi-sensor deployment with centralized SQLite database
- Provides orchestration capabilities for managing multiple honeypot sensors
- Implements sophisticated caching and rate limiting for API integrations
- Includes Elasticsearch reporting and ILM integration
- Offers enterprise-grade secret management options
- Provides reliability features like retries, backoff, and bulk loading

## Features

### Core Processing
- Process Cowrie JSON log files (including bzip2/gzip compressed files)
- Multi-sensor support with centralized SQLite database
- Session analysis and command tracking
- File download/upload tracking
- Abnormal attack detection
- Configurable TTLs and caching strategies

### Security Service Integrations
- **VirusTotal**: File hash analysis with intelligent caching
- **DShield**: IP reputation lookup
- **URLhaus**: Malware URL detection
- **SPUR.us**: Enhanced IP intelligence
- **Dropbox**: Report upload capability

### Enterprise Features
- **Orchestration**: TOML-based multi-sensor management
- **Elasticsearch Reporting**: Daily/weekly/monthly aggregations with ILM
- **Secret Management**: Support for environment variables, files, 1Password, AWS Secrets Manager, HashiCorp Vault, and SOPS
- **Reliability**: Configurable timeouts, retries with exponential backoff, rate limiting
- **Performance**: Bulk loading mode, parallel processing support, intelligent caching

## Requirements

- Python 3.9 or higher
- Virtual environment (recommended)
- SQLite3
- For Elasticsearch reporting:
  - `elasticsearch>=8,<9`
  - `tomli` (if Python < 3.11)

## Installation

1. Clone the repository:
```bash
git clone git@github.com:datagen24/cowrieprocessor.git
cd cowrieprocessor
```

2. Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Linux/Mac
# or
.\venv\Scripts\activate  # On Windows
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Architecture Overview

### Centralized Database Design
The system uses a central SQLite database to aggregate data from multiple honeypot sensors. Each sensor is identified by a unique name, allowing for both aggregate and per-sensor analysis.

### Directory Structure
```
/mnt/dshield/
├── data/
│   ├── db/                    # Central SQLite database
│   ├── cache/                 # API response caches
│   ├── temp/                  # Temporary processing files
│   └── logs/                  # Application logs and status files
├── reports/
│   ├── honeypot-a/           # Per-sensor report directories
│   │   └── 2025-09-14-201530/
│   └── honeypot-b/
│       └── 2025-09-14-201530/
└── [sensor-dirs]/             # Raw Cowrie logs per sensor
    ├── a/NSM/cowrie/
    └── b/NSM/cowrie/
```

## Usage Guide

### Single Sensor Processing

Basic usage:
```bash
python process_cowrie.py \
    --logpath /path/to/cowrie/logs \
    --email your.email@example.com \
    --sensor honeypot-a
```

With full enrichment:
```bash
python process_cowrie.py \
    --logpath /mnt/dshield/a/NSM/cowrie \
    --email your.email@example.com \
    --sensor honeypot-a \
    --db /mnt/dshield/data/db/cowrieprocessor.sqlite \
    --summarizedays 1 \
    --vtapi $VT_API_KEY \
    --urlhausapi $URLHAUS_API_KEY \
    --spurapi $SPUR_API_KEY
```

### Multi-Sensor Orchestration

Create a `sensors.toml` configuration:
```toml
[global]
db = "/mnt/dshield/data/db/cowrieprocessor.sqlite"
report_dir = "/mnt/dshield/reports"

[[sensor]]
name = "honeypot-a"
logpath = "/mnt/dshield/a/NSM/cowrie"
summarizedays = 1
vtapi = "env:VT_API_KEY"
urlhausapi = "op://Security/URLhaus/api"
spurapi = "aws-sm://us-east-1/spur#api_key"
email = "file:/run/secrets/dshield_email"

[[sensor]]
name = "honeypot-b"
logpath = "/mnt/dshield/b/NSM/cowrie"
summarizedays = 1
# Inherits global settings
```

Run the orchestrator:
```bash
python orchestrate_sensors.py --config sensors.toml
```

### Performance Optimization

For large backfills or initial imports:
```bash
# Fast initial ingest without enrichment
python process_cowrie.py \
    --sensor honeypot-a \
    --logpath /mnt/dshield/a/NSM/cowrie \
    --db /mnt/dshield/data/db/cowrieprocessor.sqlite \
    --bulk-load \
    --skip-enrich \
    --buffer-bytes 8388608 \
    --summarizedays 90

# Later, refresh cache and generate reports
python refresh_cache_and_reports.py \
    --db /mnt/dshield/data/db/cowrieprocessor.sqlite \
    --vtapi $VT_API_KEY \
    --email your.email@example.com
```

### Synthetic Data Generator (Phase 6 prep)

Generate large validation datasets without exposing live honeypot logs:

```bash
./scripts/generate_synthetic_cowrie.py data/synthetic/day01.json.gz \
    --sessions 5000 --commands-per-session 4 --downloads-per-session 2 \
    --sensor honeypot-a --sensor honeypot-b --seed 17
```

Use the output with `cowrie-loader bulk` / `cowrie-loader delta` to rehearse Phase 6 performance and chaos drills (see `notes/phase6-validation-checklist.md`).

### Telemetry-Enabled Loader CLI

The new ingestion CLI streams loader metrics, checkpoints, and dead-letter statistics to `/mnt/dshield/data/logs/status/` so `monitor_progress.py` (or other observers) can display real-time progress.

Bulk ingest example:
```bash
cowrie-loader bulk \
    /mnt/dshield/a/NSM/cowrie/*.json \
    --db /mnt/dshield/data/db/cowrieprocessor.sqlite \
    --status-dir /mnt/dshield/data/logs/status
```

Incremental ingest (delta) example:
```bash
cowrie-loader delta \
    /mnt/dshield/a/NSM/cowrie/*.json \
    --db /mnt/dshield/data/db/cowrieprocessor.sqlite \
    --status-dir /mnt/dshield/data/logs/status
```

Monitor progress in another terminal:
```bash
python monitor_progress.py
```

The status output now includes phase (`bulk_ingest`/`delta_ingest`), event throughput, last checkpoint (source + offset), and dead-letter totals.

To forward traces, export standard OTEL variables (for example `OTEL_EXPORTER_OTLP_ENDPOINT`) before running loaders or the reporting CLI. Spans are emitted under the `cowrie.bulk.*`, `cowrie.delta.*`, and `cowrie.reporting.*` namespaces so slow batches and SQL calls surface in your APM tooling. Dashboards, alert thresholds, and incident-response drills are captured in `docs/telemetry-operations.md`.

### Multiline JSON Support

For historical Cowrie logs that are pretty-printed (formatted with indentation across multiple lines), use the `--multiline-json` flag to enable proper parsing:

```bash
# Process pretty-printed JSON files (2025-02 to 2025-03 range)
cowrie-loader bulk \
    /mnt/dshield/aws-eastus-dshield/NSM/cowrie/cowrie.json.2025-02-25.bz2 \
    --db /mnt/dshield/data/db/cowrieprocessor.sqlite \
    --status-dir /mnt/dshield/data/logs/status \
    --multiline-json

# Delta processing with multiline JSON support
cowrie-loader delta \
    /mnt/dshield/aws-eastus-dshield/NSM/cowrie/cowrie.json.2025-03-*.bz2 \
    --db /mnt/dshield/data/db/cowrieprocessor.sqlite \
    --status-dir /mnt/dshield/data/logs/status \
    --multiline-json
```

**When to use `--multiline-json`:**
- Historical Cowrie logs from 2025-02 to 2025-03 that were pretty-printed
- Files that produce large numbers of validation DLQ entries when processed normally
- Any JSON files where objects span multiple lines with indentation

**DLQ Reprocessing:**
If you have existing dead letter queue entries from pretty-printed files, you can reprocess them:

```bash
# 1. Identify files with validation DLQ entries
sqlite3 /mnt/dshield/data/db/cowrieprocessor.sqlite "
SELECT DISTINCT source, COUNT(*) as dlq_count 
FROM dead_letter_events 
WHERE reason='validation' 
AND (source LIKE '%.2025-02%' OR source LIKE '%.2025-03%')
GROUP BY source 
ORDER BY dlq_count DESC;
"

# 2. Clear DLQ entries for a specific file
sqlite3 /mnt/dshield/data/db/cowrieprocessor.sqlite "
DELETE FROM dead_letter_events 
WHERE source='/path/to/file.json.bz2' AND reason='validation';
"

# 3. Reprocess with multiline JSON support
cowrie-loader bulk /path/to/file.json.bz2 \
    --db /mnt/dshield/data/db/cowrieprocessor.sqlite \
    --multiline-json
```

This feature can eliminate millions of validation DLQ entries and recover valid Cowrie events from previously malformed pretty-printed JSON files.

## Database Management

### `cowrie-db` - Database Administration

The `cowrie-db` CLI provides comprehensive database management capabilities for production deployments:

```bash
# Check database health and schema version
cowrie-db check --verbose

# Run schema migrations (safe to run multiple times)
cowrie-db migrate

# Optimize database (VACUUM and reindex)
cowrie-db optimize

# Create database backup with integrity verification
cowrie-db backup --output /backups/cowrie_backup_$(date +%Y%m%d_%H%M%S).sqlite

# Check database integrity and detect corruption
cowrie-db integrity

# Display database statistics and health information
cowrie-db info
```

**Database Management Commands:**
- `migrate`: Run schema migrations with advisory locking to prevent concurrent DDL operations
- `check`: Validate schema version and health, display statistics
- `optimize`: Run VACUUM and reindex operations for maintenance
- `backup`: Create verified backups with integrity checking
- `integrity`: Perform comprehensive integrity checks and corruption detection
- `info`: Display database metadata and performance statistics

**Key Features:**
- **Advisory Locking**: Prevents concurrent migrations that could cause database locks
- **Backup Verification**: Automatic integrity checking of created backups
- **Corruption Detection**: Comprehensive integrity checks with recovery recommendations
- **Performance Monitoring**: Database size, session counts, and optimization suggestions
- **Safe Operations**: All operations include proper error handling and rollback capabilities

## Command Line Reference

### Core Arguments
- `--logpath`: Path to Cowrie JSON logs
- `--sensor`: Sensor identifier (defaults to hostname)
- `--db`: Central SQLite database path
- `--email`: Email for DShield lookups
- `--summarizedays`: Number of days to analyze

### API Keys (use environment variables when possible)
- `--vtapi`: VirusTotal API key
- `--urlhausapi`: URLhaus API key  
- `--spurapi`: SPUR.us API key
- `--dbxapi`, `--dbxkey`, `--dbxsecret`, `--dbxrefreshtoken`: Dropbox credentials

### ORM Loader Enrichment
The `cowrie-loader` ORM ingestion CLI accepts dedicated enrichment options that
mirror the legacy processor flags while sourcing defaults from the same
environment variables:

- `--vt-api-key` (uses `VT_API_KEY` when omitted)
- `--dshield-email` (uses `DSHIELD_EMAIL` when omitted)
- `--urlhaus-api-key` (uses `URLHAUS_API_KEY` when omitted)
- `--spur-api-key` (uses `SPUR_API_KEY` when omitted)
- `--cache-dir` to override the enrichment cache location
- `--skip-enrich` to disable all enrichment lookups for the current run

These options feed the new enrichment pipeline that materialises VirusTotal and
DShield flags in the ORM `session_summaries` table for downstream reporting.

Daily JSON reports now include an `enrichments.flagged` section summarising the
sessions that triggered VirusTotal or DShield hits, including the top source IP
intelligence and associated file hash verdicts.

### Performance Tuning
- `--bulk-load`: Enable bulk loading mode
- `--skip-enrich`: Skip API enrichments
- `--buffer-bytes`: Read buffer size (default: 1MB)
- `--api-timeout`: HTTP timeout (default: 15s)
- `--api-retries`: Max retry attempts (default: 3)
- `--api-backoff`: Exponential backoff base (default: 2.0)

### Loader Options
- `--multiline-json`: Enable multiline JSON parsing for pretty-printed Cowrie logs
- `--batch-size`: Number of events to process per batch (default: 500)
- `--quarantine-threshold`: Risk score above which events are quarantined (default: 80)

### Cache Management
- `--hash-ttl-days`: TTL for file hash lookups (default: 30)
- `--hash-unknown-ttl-hours`: Recheck unknown hashes (default: 12)
- `--ip-ttl-hours`: TTL for IP lookups (default: 12)

### Rate Limiting
- `--rate-vt`: VirusTotal requests/minute (default: 4)
- `--rate-dshield`: DShield requests/minute (default: 30)
- `--rate-urlhaus`: URLhaus requests/minute (default: 30)
- `--rate-spur`: SPUR requests/minute (default: 30)

## Elasticsearch Integration

### Setup
Configure environment variables:
```bash
export ES_HOST=https://elasticsearch.example.com:9200
export ES_USERNAME=elastic
export ES_PASSWORD=file:/run/secrets/es_password
# OR use API key (also supports secret references such as op:// vault paths)
export ES_API_KEY=op://Elastic/cowrie-reporting/api_key
# OR use Elastic Cloud
export ES_CLOUD_ID=deployment:region:id
```

### Generate Reports
```bash
# Daily reports for all sensors
cowrie-report daily 2025-09-14 \
    --db /mnt/dshield/data/db/cowrieprocessor.sqlite \
    --all-sensors --publish

# Weekly rollup
cowrie-report weekly 2025-W37 \
    --db /mnt/dshield/data/db/cowrieprocessor.sqlite \
    --publish

# Backfill historical data (loop over days)
for day in $(seq 0 13); do
  cowrie-report daily "$(date -u -d "2025-09-14 - ${day} day" +%F)" \
    --db /mnt/dshield/data/db/cowrieprocessor.sqlite --all-sensors --publish
done
```

### Index Lifecycle Management
Reports are written to ILM-managed indices:
- Daily: `cowrie.reports.daily-write` (cold after 7 days)
- Weekly: `cowrie.reports.weekly-write` (cold after 30 days)
- Monthly: `cowrie.reports.monthly-write` (cold after 90 days)

## Secret Management

### Supported Backends
Secrets can be sourced from multiple backends using URI notation:
- `env:VARIABLE_NAME` - Environment variable
- `file:/path/to/secret` - File contents
- `op://vault/item/field` - 1Password CLI
- `aws-sm://[region/]secret_id[#json_key]` - AWS Secrets Manager
- `vault://path[#field]` - HashiCorp Vault (KV v2)
- `sops://path[#json.key]` - SOPS-encrypted files

### Environment Variables
Common environment variables used:
```bash
VT_API_KEY          # VirusTotal
URLHAUS_API_KEY     # URLhaus
SPUR_API_KEY        # SPUR.us
DSHIELD_EMAIL       # DShield
DROPBOX_ACCESS_TOKEN, DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN
ES_HOST, ES_USERNAME, ES_PASSWORD, ES_API_KEY, ES_CLOUD_ID
```

## Monitoring

### Status Dashboard
Monitor processing progress in real-time:
```bash
# One-shot view
python status_dashboard.py --status-dir /mnt/dshield/data/logs/status --oneshot

# Live updates
python status_dashboard.py --status-dir /mnt/dshield/data/logs/status --refresh 2
```

- `status.json` aggregates bulk/delta/reporting metrics (throughput, failure counters)
- Phase-specific files (`bulk_ingest.json`, `delta_ingest.json`, `reporting.json`) provide granular detail
- `cowrie-health` CLI performs integrity and telemetry checks (see Health Check below)

### Tracing (Optional)
OpenTelemetry spans are emitted when the SDK is available:
```bash
pip install opentelemetry-api opentelemetry-sdk

export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318

cowrie-loader bulk /var/log/cowrie/json.log --db /mnt/dshield/data/db/cowrieprocessor.sqlite
```

## Development

### Code Quality
The project uses Ruff for linting and MyPy for type checking:
```bash
# Install tools
pip install ruff==0.12.11 mypy==1.14.1 types-requests==2.32.0.20240914

# Run checks
ruff check .
mypy .
```

### Pre-commit Hooks
```bash
pip install pre-commit==3.8.0
pre-commit install
pre-commit run --all-files
```

### Testing

The project includes comprehensive test coverage for all enrichment workflows with 80%+ coverage requirement.

#### Test Structure

```
tests/
├── unit/                    # Fast, isolated unit tests
│   ├── test_enrichment_handlers.py      # Core enrichment function tests
│   ├── test_mock_enrichment_handlers.py # Mock service tests
│   └── test_*.py                        # Other unit tests
├── integration/             # End-to-end integration tests
│   ├── test_enrichment_integration.py   # Enrichment workflow tests
│   ├── test_enrichment_reports.py       # Report generation tests
│   └── test_*.py                        # Other integration tests
├── performance/             # Performance and benchmark tests
│   ├── test_enrichment_performance.py   # Enrichment performance tests
│   └── test_*.py                        # Other performance tests
├── fixtures/                # Test data and mock services
│   ├── enrichment_fixtures.py           # Mock API responses
│   ├── mock_enrichment_handlers.py      # Mock service implementations
│   ├── mock_enrichment_server.py        # Mock HTTP server
│   └── statistical_analysis.py          # Analysis tools
└── conftest.py              # Shared test fixtures
```

#### Running Tests

```bash
# Install dependencies (including test dependencies)
uv sync

# Run all tests
uv run pytest

# Run specific test categories
uv run pytest tests/unit/                    # Unit tests only
uv run pytest tests/integration/             # Integration tests only
uv run pytest tests/performance/             # Performance tests only

# Run with coverage (80%+ required)
uv run pytest --cov=. --cov-report=term-missing --cov-fail-under=80

# Run specific test markers
uv run pytest -m "unit"                     # Unit tests
uv run pytest -m "integration"              # Integration tests
uv run pytest -m "performance"              # Performance tests
uv run pytest -m "enrichment"               # Enrichment-specific tests

# Run with mock APIs (for testing without external dependencies)
USE_MOCK_APIS=true uv run pytest

# Performance benchmarking
uv run pytest tests/performance/ --benchmark-only
```

#### Test Coverage Requirements

- **Minimum 80% code coverage** across the entire codebase
- **New features require 90%+ coverage**
- **Bug fixes must include regression tests**
- **All enrichment workflows** must have comprehensive test coverage

#### Mock Testing Infrastructure

The project includes comprehensive mock infrastructure for testing without external API dependencies:

- **Mock enrichment handlers** for OTX, AbuseIPDB, and statistical analysis
- **Mock HTTP server** for simulating API responses
- **Pre-configured test fixtures** with realistic API responses
- **Performance testing** with concurrent access simulation

#### Enrichment Services Tested

| Service | Status | Test Coverage | Notes |
|---------|--------|---------------|-------|
| VirusTotal | ✅ Active | 100% | File hash analysis, caching, rate limiting |
| DShield | ✅ Active | 100% | IP reputation, ASN lookup, caching |
| URLHaus | ✅ Active | 100% | Malicious URL detection, tag parsing |
| SPUR.us | ⚠️ Mocked | 100% | No license - comprehensive mock implementation |
| OTX | 🔧 Ready | 100% | Mock implementation ready for API key |
| AbuseIPDB | 🔧 Ready | 100% | Mock implementation ready for API key |

#### Test Data and Fixtures

Test fixtures include realistic API responses for all services:

- **VirusTotal**: Malware, clean, and unknown hash responses
- **DShield**: Datacenter, residential, and VPN IP responses
- **URLHaus**: Malicious URL and tag responses
- **SPUR**: Infrastructure classification responses
- **OTX**: IP reputation and threat intelligence
- **AbuseIPDB**: IP abuse scoring and categorization

#### CI/CD Integration

All tests run automatically in CI/CD with:

- **Multi-Python version testing** (3.9-3.13)
- **Coverage reporting** with Codecov integration
- **Mock server integration** for external API testing
- **Performance benchmarking** with historical comparison
- **Security testing** for API key handling and data validation

## Output Files

### Reports
- `<sensor>/<timestamp>/<datetime>_<days>_report.txt` - Full attack summary
- `<sensor>/<timestamp>/<datetime>_abnormal_<days>_report.txt` - Unusual attacks

### Cache Files  
- `cache/vt/<hash>` - VirusTotal results
- `cache/uh/<ip>` - URLhaus results
- `cache/spur/<ip>` - SPUR.us results

### Database
Central SQLite database contains:
- `sessions` - Attack session metadata
- `commands` - Commands executed per session
- `files` - Files downloaded/uploaded
- `indicator_cache` - API response cache

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Run tests and linting
4. Commit your changes (`git commit -m 'Add some amazing feature'`)
5. Push to the branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request

## License

This project is licensed under the BSD 4-Clause License - see the LICENSE file for details.

## Attribution

This is a fork of the original [cowrieprocessor](https://github.com/jslagrew/cowrieprocessor) project by Jessie Lagrew. The original author's work focused on processing Cowrie logs for individual DShield honeypots. The original author's work is not covered by this license. This license only applies to modifications made by Steven Peterson.

The current implementation represents a substantial evolution from the original codebase, transforming it from a single-honeypot processor into a comprehensive multi-sensor framework with centralized processing, orchestration, and enterprise-grade features.
