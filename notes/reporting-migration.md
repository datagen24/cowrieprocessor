# Migrating from `es_reports.py` to `cowrie-report`

The Phase 4 ORM rewrite replaces the legacy `es_reports.py` script with the
new `cowrie-report` CLI. This document walks through the migration steps,
highlights behavioural differences, and outlines the removal plan for the
legacy implementation.

## Why the change?

- Align reporting with the ORM/SQLite schema used by the loaders.
- Avoid rescanning raw log files and duplicated aggregation logic.
- Share telemetry, StatusEmitter checkpoints, and configuration with the
  ingest pipeline.
- Enable future Postgres support and richer report outputs without
  hand-written SQL.

## Step-by-step migration

1. **Install/upgrade the package**
   - Deploy the refactored `cowrieprocessor` code (or install it into the
     virtual environment). The entrypoint `cowrie-report` is registered via
     `pyproject.toml`.

2. **Review environment variables & secrets**
   - Configure `ES_HOST`, `ES_USERNAME`, `ES_PASSWORD`, `ES_API_KEY`,
     `ES_CLOUD_ID`, and `ES_VERIFY_SSL` via the environment. Each value may be
     a direct string or a secret reference recognised by `secrets_resolver`
     (`env:NAME`, `file:/path`, `op://vault/item/field`, `aws-sm://…`, etc.).
   - Optional overrides: `ES_INDEX_PREFIX` (defaults to `cowrie.reports`) and
     `ES_INGEST_PIPELINE` for ingest pipelines.

3. **Update automation**
   - Replace invocations of `python es_reports.py ...` with
     `cowrie-report <mode> <date>`.
   - Provide the database location explicitly (`--db /path/to/db.sqlite`).
   - Add `--all-sensors --publish` for daily jobs that previously used
     `--all-sensors` and published to Elasticsearch.
   - Weekly and monthly jobs require an ISO week (`2024-W50`) or `YYYY-MM`
     string; the CLI normalises them to the correct window.
   - `refresh_cache_and_reports.py` has been updated to call the new CLI;
     ensure any custom automation copies this change.

4. **Manual usage differences**
   - The positional `<date>` argument is required. Use `$(date -u +%F)` in cron
     or wrapper scripts to emit the current UTC day.
   - Use `--sensor <name>` for a single sensor, or omit the flag for the
     aggregate view.
   - Include `--publish` when you expect the run to index documents. Without
     credentials the CLI falls back to a dry-run that prints JSON to stdout or
     `--output`.
   - Elasticsearch credentials are sourced from environment variables or secret
     references; they are no longer accepted on the command line.

5. **Backfill strategy**
   - The ORM CLI does not yet expose a dedicated `backfill` subcommand.
     Loop over the required date range and invoke `cowrie-report daily …` for
     each day, optionally in parallel. Example:

     ```bash
     for day in $(seq 0 29); do
       cowrie-report daily "$(date -u -d "2025-01-31 - ${day} day" +%F)" \
         --db /mnt/dshield/data/db/cowrieprocessor.sqlite \
         --all-sensors --publish
     done
     ```

## Behavioural differences

| Topic | `es_reports.py` | `cowrie-report` |
|-------|-----------------|-----------------|
| Data source | Raw SQLite queries against legacy tables | SQLAlchemy ORM over `raw_events` and `session_summaries` |
| Output fields | Included enrichments, alerts, protocol breakdown | Sessions, command top-N, file download top-N (enrichments/alerts pending) |
| Doc IDs | `sensor:date_utc` | `sensor:report_type:date` |
| Index alias | `cowrie.reports.<type>-write` | Same (managed via helpers.bulk) |
| Status telemetry | None | Writes `status_dir/reporting.json` via `StatusEmitter` |
| Backfill command | `backfill --start/--end` | Loop daily invocations (future enhancement) |

## Validation checklist

- Run `cowrie-report daily <date> --db <path> --all-sensors --publish` and
  verify the JSON payload when `--output` or stdout is used.
- Confirm documents land in `cowrie.reports.daily-write` with `_id`
  `sensor:daily:<date>`.
- Monitor `/mnt/dshield/data/logs/status/reporting.json` (or the configured
  status directory) for metrics/checkpoints emitted by the CLI.
- Update Kibana visualisations to read the `date` field instead of
  `date_utc` and to use `sensor.keyword` filters.

## Deprecation plan for `es_reports.py`

- **Now (Phase 4 rollout):** `es_reports.py` emits a runtime warning pointing
  operators to `cowrie-report`. Automation has been updated to the new CLI.
- **Staging bake (2 weeks):** run both pipelines side-by-side via manual
  spot-checks. Capture any parity gaps (command counts, unique IPs).
- **Production cutover:** once staging parity is accepted, remove scheduled
  jobs calling `es_reports.py` and archive legacy dashboards.
- **Removal target:** delete `es_reports.py` and associated docs in Phase 5
  (after telemetry improvements) or the next minor release, whichever comes
  first.

Track cutover status in `notes/issue-17-plan.md` and open follow-up issues for
any missing features (alerts, enrichments, dedicated backfill command).
