# Work Plan: Issue #17 - Split loader/reporting workflows and use SQLite JSON for sessions

## Context
- Issue #17 calls for decoupling ingestion from reporting and persisting raw Cowrie sessions in SQLite JSON columns for scalable analytics.
- Current pipeline reprocesses raw logs for reports, lacks clear ingest/report boundaries, and cannot efficiently handle 180-day backfills or incremental updates.
- Existing schema stores derived data but not the original event stream, limiting future reprocessing and telemetry.

## Objectives
- Persist raw Cowrie events in SQLite with JSON columns and build indexed summary tables for session-level metrics.
- Provide a high-throughput bulk loader for historical ranges and a delta loader that resumes from the last successful ingest.
- Rewrite reporting to rely on the SQLite data model instead of raw file scans, producing daily/weekly/monthly outputs.
- Expose telemetry that clearly distinguishes ingest (bulk/delta) and reporting phases.

## Proposed Phases

### Phase 0 – Discovery and Technical Design
- Inventory current ingest/report flows, job entry points, and how they interact with SQLite today.
- Assess existing schema, migrations, and storage patterns to determine compatibility with JSON columns and WAL mode.
- Define data retention, partitioning, and indexing strategy for raw events and summary tables.
- Document operational constraints (dataset sizes, deployment environments, concurrency expectations).

### Phase 1 – Raw Event Storage Layer
- Design `raw_events` table with JSON payload, canonical event metadata (session ID, timestamps, source file), and indexing for lookups.
- Add supporting summary tables (e.g., `sessions`, `command_stats`) fed via triggers or post-ingest processing.
- Plan schema migrations, versioning, and rollback strategy; prototype WAL/synchronous settings for concurrent reads.

### Phase 2 – Bulk Loader Implementation
- Implement a streaming loader that reads historical Cowrie logs, normalizes events, and batches inserts into `raw_events`.
- Optimize transaction sizing, parallelism, and memory usage to handle 180-day imports.
- Capture ingest checkpoints (file offsets, timestamps) and telemetry (rows/s, phase progress).

### Phase 3 – Delta Loader Implementation
- Build a state tracker that records last processed file/timestamp session-wise.
- Implement incremental ingestion that only processes new files/events, with idempotency checks against unique constraints.
- Add restart/recovery logic and validation ensuring parity with bulk loads over overlapping windows.

### Phase 4 – Reporting Tool Rewrite
- Create a reporting module that queries summary tables/JSON to produce daily, weekly, and monthly reports without re-reading logs.
- Support streaming pagination for large result sets and configurable output formats (text first, extensible later).
- Validate report outputs against legacy implementation for correctness.

### Phase 5 – Telemetry & Operational Hardening
- Extend status telemetry to include phase markers (bulk ingest, delta ingest, reporting), timestamps, and metrics.
- Integrate instrumentation for loader throughput, queue depths, and DB health (WAL checkpoints, cache hits).
- Update documentation and deployment scripts for new modes and monitoring.

### Phase 6 – Validation & Rollout
- Create unit/integration tests covering raw event persistence, loader workflows, and reporting queries.
- Benchmark bulk vs delta performance on representative datasets; define acceptance thresholds.
- Stage rollout plan with feature flags or configuration toggles, plus migration/backfill instructions.

## Open Questions & Risks
- Do we need to support non-WAL environments or alternative storage backends?
- What retention policy governs raw events—do we prune, archive, or partition old data?
- How do enrichments and existing downstream consumers adapt to the new data model?
- Are there compliance or privacy considerations when storing full raw session JSON long-term?

## Deliverables
- Schema migration scripts and documentation for the new raw event and summary tables.
- Bulk and delta loader implementations with operator/runbooks.
- Report generation tool and updated CLI/automation entry points.
- Telemetry dashboards or JSON samples showing phase separation.
- Comprehensive tests, benchmarks, and rollout checklist.
