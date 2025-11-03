# Essential Commands for Cowrie Processor

## Environment Setup
```bash
# Install dependencies (MANDATORY - use uv, not pip)
uv sync

# Always run commands through uv
uv run <command>
```

## Pre-Commit Checklist (MANDATORY - Run Before Every Commit)
**CI gates enforce these in strict order. Any failure stops the merge:**

```bash
# 1. Format code (auto-fix)
uv run ruff format .

# 2. Lint checks (Gate #1 - must pass with 0 errors)
uv run ruff check .

# 3. Type checking (Gate #2 - must pass with 0 errors)
uv run mypy .

# 4. Tests with coverage (Gates #4-5 - ≥65% coverage required, all tests must pass)
uv run pytest --cov=. --cov-report=term-missing --cov-fail-under=65
```

## Testing Commands
```bash
# Run all tests with coverage (65% minimum)
uv run pytest --cov=. --cov-report=term-missing --cov-fail-under=65

# Run specific test categories
uv run pytest tests/unit/                    # Fast unit tests
uv run pytest tests/integration/             # Integration tests
uv run pytest tests/performance/             # Performance benchmarks

# Run by marker
uv run pytest -m "unit"                      # Unit tests only
uv run pytest -m "integration"               # Integration tests only
uv run pytest -m "enrichment"                # Enrichment-specific tests

# Offline enrichment testing (no network)
uv run pytest tests/integration/test_enrichment_flow.py::test_high_risk_session_full_enrichment
```

## Data Ingestion (ORM Loaders)
```bash
# Bulk load (initial import)
uv run cowrie-loader bulk /path/to/logs/*.json \
    --db "postgresql://user:pass@host:port/database" \
    --status-dir /mnt/dshield/data/logs/status \
    --vt-api-key $VT_API_KEY \
    --dshield-email $DSHIELD_EMAIL

# Delta load (incremental updates)
uv run cowrie-loader delta /path/to/logs/*.json \
    --db "postgresql://user:pass@host:port/database" \
    --status-dir /mnt/dshield/data/logs/status

# Multiline JSON support
uv run cowrie-loader bulk /path/to/logs/*.json.bz2 \
    --db "postgresql://..." \
    --multiline-json
```

## Enrichment Commands
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

## Database Management
```bash
# Run schema migrations
uv run cowrie-db migrate

# Check database health
uv run cowrie-db check --verbose

# Create backup
uv run cowrie-db backup --output /backups/cowrie_$(date +%Y%m%d).sqlite

# Optimize database
uv run cowrie-db optimize

# Check integrity
uv run cowrie-db integrity
```

## Reporting
```bash
# Daily reports
uv run cowrie-report daily 2025-09-14 --db "postgresql://..." --all-sensors --publish

# Weekly rollup
uv run cowrie-report weekly 2025-W37 --db "postgresql://..." --publish

# Monthly aggregation
uv run cowrie-report monthly 2025-09 --db "postgresql://..." --publish
```

## Health Monitoring
```bash
# Health check
uv run cowrie-health --db "postgresql://..." --verbose

# Monitor progress (real-time)
uv run python scripts/production/monitor_progress.py \
    --status-dir /mnt/dshield/data/logs/status \
    --refresh 2
```

## Multi-Sensor Orchestration
```bash
# Modern mode (uses cowrie-loader CLI - RECOMMENDED)
uv run python scripts/production/orchestrate_sensors.py --config config/sensors.toml

# Legacy mode (if needed for rollback)
USE_LEGACY_PROCESSOR=true uv run python scripts/production/orchestrate_sensors.py --config config/sensors.toml
# Or: uv run python scripts/production/orchestrate_sensors.py --config config/sensors.toml --legacy
```

## Git Workflow
```bash
# Always check status and branch first
git status && git branch

# Create feature branch (NEVER work on main)
git checkout -b feature/your-feature-name

# Commit with conventional commit format
git commit -m "feat(scope): description"
# Types: feat, fix, docs, style, refactor, perf, test, build, ci, chore
```

## macOS-Specific Commands
```bash
# List files (BSD version)
ls -la

# Find files (BSD find)
find . -name "*.py" -type f

# Grep (BSD grep - consider using rg/ripgrep for better performance)
grep -r "pattern" .

# Monitor processes
ps aux | grep cowrie
```
