# Phase 4 – ORM-Based Reporting Rewrite

## Objectives
- Replace the SQLite cursor-heavy logic in `es_reports.py` with ORM-backed queries that stream from the `raw_events`, `session_summaries`, and `command_stats` tables.
- Preserve Elasticsearch indexing targets (daily/weekly/monthly) while making the output renderer pluggable so we can emit JSON or CLI summaries without Elasticsearch.
- Eliminate redundant aggregations by relying on precomputed `session_summaries` and incremental views fed by the loaders.
- Expose reporting metrics via `StatusEmitter` (phase = `reporting`) so operations can monitor report generation progress similar to ingest.

## Proposed Components

### 1. Reporting Data Access Layer (`cowrieprocessor/reporting/dal.py`)
- SQLAlchemy ORM session factory reuse (`create_session_maker`).
- Reusable query helpers that accept time windows and optional sensor filters.
- Convenience iterators (`iter_sessions`, `iter_commands`, `iter_files`) that yield batches (e.g., 1k rows) for streaming.

### 2. Report Builders (`cowrieprocessor/reporting/builders.py`)
- `DailyReportBuilder`, `WeeklyReportBuilder`, `MonthlyReportBuilder` classes encapsulating aggregation logic.
- Configurable output format (structured dict for ES, optional CLI JSON).
- Incorporate enrichment flags (VT recent, DShield hits) sourced from `session_summaries` and future materialized views.

### 3. Elasticsearch Publisher (`cowrieprocessor/reporting/es_publisher.py`)
- Small wrapper around `Elasticsearch` client, supporting bulk indexing with backoff.
- Optional dry-run mode for local testing (writes JSON to stdout/files).

### 4. CLI Entry (`cowrieprocessor/cli/report.py`)
- Accept report type(s), date ranges, sensor filters, and output destinations.
- Wire `StatusEmitter` phase `reporting` to publish progress per batch.
- Integrate secrets resolver for ES credentials (reuse existing helper).

## Data Model Enhancements
- Add materialized views or tables as needed for report-time metrics (e.g., pivoted command stats, file download counts); keep loaders responsible for populating them where practical.
- Ensure migrations cover new reporting tables with backward-compatible defaults.

## Telemetry & Monitoring
- Status payload should include current report type, date range, batch counters, index attempts, and error details.
- Extend `monitor_progress.py` to display reporting phase output (done automatically once emitter used).

## Testing Strategy
- Unit tests for DAL queries using temporary SQLite (fixtures populating `session_summaries`, `command_stats`).
- Integration tests for report builders validating JSON structure vs legacy outputs.
- Mocked Elasticsearch publisher tests ensuring retry/backoff logic and proper payload shape.
- CLI smoke test that runs daily report in dry-run mode and verifies status file updates.

## Migration Plan
1. Land reporting DAL + builders with parity tests (without ES publishing) and enable CLI dry-run.
2. Introduce ES publisher & CLI wiring, maintaining old `es_reports.py` as fallback with deprecation warning.
3. Update orchestration docs/scripts to call new CLI.
4. Remove legacy script once validated in staging.
