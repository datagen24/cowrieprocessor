# Work Plan: Issue #17 - Split loader/reporting workflows and use SQLite JSON for sessions

## Context
- Issue #17 calls for decoupling ingestion from reporting and persisting raw Cowrie sessions in SQLite JSON columns for scalable analytics.
- Current pipeline reprocesses raw logs for reports, lacks clear ingest/report boundaries, and cannot efficiently handle 180-day backfills or incremental updates.
- Existing schema stores derived data but not the original event stream, limiting future reprocessing, telemetry, and integrations like the Elastic exporter.
- The refactor must keep the Elastic exporter in sync, adopt an ORM (SQLAlchemy) for database portability, and prepare for optional Postgres deployments alongside SQLite.

## Objectives
- Persist raw Cowrie events in SQLite with JSON columns plus generated/virtual columns for key fields, and build indexed summary tables for session-level metrics.
- Provide a high-throughput bulk loader for historical ranges and a delta loader that resumes from the last successful ingest while enforcing validation and integrity safeguards.
- Rewrite reporting to rely on the SQLite/ORM data model instead of raw file scans, producing daily/weekly/monthly outputs and keeping Elastic exporter consumers aligned.
- Expose telemetry that clearly distinguishes ingest (bulk/delta) and reporting phases, with visibility into queue health, WAL checkpoints, JSON parsing, index efficiency, and distributed traces.
- Deliver a migration path and tooling to hydrate Postgres from SQLite when teams outgrow the single-file setup.

## Proposed Phases

### Phase 0 – Discovery and Technical Design
- Inventory current ingest/report flows, entry points, ORM touchpoints, and how they interact with SQLite and the Elastic exporter today.
- Assess existing schema, migrations, PRAGMA settings, and storage patterns to determine compatibility with JSON columns, generated columns, and WAL mode.
- Evaluate ORM adoption (SQLAlchemy) for schema management, migrations, dual-target support (SQLite + Postgres), connection pooling, and raw-SQL escape hatches for hot paths.
- Define data retention, partitioning, indexing strategy, privacy requirements, and observability expectations (metrics, tracing, logging) for raw events and summary tables.
- Document operational constraints (dataset sizes, deployment environments, concurrency expectations) and initial Postgres migration considerations/mapping needs.

### Phase 1 – Raw Event Storage Layer
- Design a `raw_events` table with JSON payload, canonical event metadata (session ID, timestamps, eventid, source file), generated/virtual columns for indexed JSON paths, and uniqueness constraints.
- Add supporting summary tables (e.g., `sessions`, `command_stats`) maintained via ingest-time processing or triggers and compatible with Elastic exporter expectations.
- Incorporate PRAGMA defaults (`journal_mode=WAL`, `synchronous=NORMAL`, `cache_size=-64000`) with configuration and fallback to `journal_mode=DELETE` where required.
- Define schema migrations, versioning, and rollback strategy, including ORM migration scripts, JSON schema validation before inserts, and schema registry/version tracking for event evolution.

### Phase 1.5 – Security & Data Integrity Layer
- Implement cryptographic integrity checksums (BLAKE3) per raw event batch and store verification metadata for tamper detection.
- Add row-level audit trails capturing actor, timestamp, and mutation type for critical tables.
- Enforce strict JSON schema validation and anomaly detection hooks to prevent malformed or malicious payloads.
- Establish referential integrity between `raw_events` and session summaries, with automated reconciliation jobs.

### Phase 2 – Bulk Loader Implementation
- Implement a streaming bulk loader that reads historical Cowrie logs, normalizes events, validates JSON, and batches inserts into `raw_events` using prepared statements and ORM sessions.
- Provide an optional raw-SQL bypass mode for bulk ingest when ORM overhead is prohibitive; document optimization patterns for JSON path operations.
- Optimize adaptive batching based on memory pressure and I/O throughput, leveraging parallel parsing with controlled write locks and connection pooling.
- Capture ingest checkpoints (file offsets, session boundaries) and telemetry (rows/sec, batch latency, checksum status, JSON failures).
- Seed summary tables, run data quality checks, and ensure Elastic exporter dependencies are satisfied.

### Phase 3 – Delta Loader Implementation
- Build a state tracker recording last processed file, timestamp, and session boundaries to ensure idempotent incremental ingest.
- Implement validation and deduplication using unique constraints plus ORM transactions; add a dead letter queue for malformed/rejected events.
- Provide restart/recovery logic, configurable backpressure mechanisms, rate limiting, and isolation/locking strategy for concurrent bulk/delta operations.
- Surface telemetry on queue depth, retry counts, DLQ volume, and distributed trace spans for ingest paths; add circuit breakers when downstream systems (Elastic) are unavailable.

### Phase 4 – Reporting Tool Rewrite
- Create a reporting CLI/service that queries summary tables (and JSON as needed) via the ORM to produce daily, weekly, and monthly reports without re-reading logs.
- Support streaming pagination for large result sets, configurable output formats, and a compatibility layer for legacy report consumers including the Elastic exporter.
- Validate report outputs against the legacy implementation to guarantee parity and document ORM optimization strategies or raw SQL usage for heavy aggregations.
- Add health-check endpoints and graceful shutdown hooks ensuring report jobs flush checkpoints on termination.

### Phase 5 – Telemetry & Operational Hardening
- Extend status telemetry to include phase markers (bulk ingest, delta ingest, reporting), timestamps, throughput, resource usage, JSON parsing failures, index hit ratios, WAL checkpoint intervals/durations, and queue saturation.
- Integrate OpenTelemetry tracing for loader and reporting workflows, with guidance on cardinality management.
- Implement automated backpressure/throttling, circuit breakers, and rate limiting when approaching resource limits or downstream outages.
- Update documentation, dashboards, log aggregation strategy, and deployment scripts for new modes, telemetry fields, and configuration knobs.

### Phase 6 – Validation, Migration & Rollout
- Develop unit/integration tests for raw event persistence, loader workflows, reporting queries, JSON validation, and schema registry flows.
- Add performance regression suites covering 180-day bulk loads (>10K events/sec target), delta ingest latency (<5s log-to-query target), report generation (<30s monthly target), and JSON lookup latency (<100ms).
- Run chaos tests (e.g., `kill -9` during writes) to validate recovery, plus data consistency checks comparing bulk vs delta results and SQLite vs Postgres reconciliations.
- Ship feature flags, backward compatibility layers, and A/B testing hooks for phased rollout, including Elastic exporter schema version locks.
- Provide a migration command to hydrate Postgres from existing SQLite databases, mapping JSON1 columns to JSONB, generated columns to computed columns, and PRAGMAs to Postgres configs; document rollback procedures (bidirectional sync, pg_dump strategies).
- Finalize retention/archival strategy (compression, cold storage) with configurable policies, cascade deletes, and privacy/PII redaction options.

## Cross-Cutting Concerns
- Data lifecycle management: implement configurable retention, archival/compression, cascade deletes for expired raw events, and automated reconciliation jobs.
- Privacy compliance: add optional PII detection/redaction hooks prior to persistence; document regulatory considerations.
- Schema evolution: leverage schema registry/versioning, ORM migrations, and compatibility validation when adding JSON fields or summary tables.
- Concurrency control: document isolation levels, lock management, connection pooling, and ORM vs raw-SQL usage for mixed workloads.
- Observability: define metrics, traces, logs, and dashboards; ensure log aggregation strategy covers migration windows.
- Elastic exporter alignment: ensure schema changes and summary tables remain compatible, with regression tests and versioned contracts.

## Open Questions & Risks
- Which environments lack WAL support, and how should the system auto-negotiate alternative journal modes?
- What retention defaults satisfy operational and compliance requirements, and how do we expose tuning knobs to operators?
- How will privacy/PII detection integrate with existing enrichment workflows without impacting throughput?
- What level of Postgres support (managed vs self-hosted) do downstream teams expect, and how do we validate ORM abstractions across engines?
- How do we manage ORM lock-in while retaining flexibility for performance-critical raw SQL paths?
- How do we monitor and mitigate JSON index bloat, Elastic schema drift, and migration rollback complexity during rollout?

## Deliverables
- ORM-based schema definitions, migration scripts, schema registry tooling, and validation utilities for SQLite and Postgres.
- `raw_events`, summary tables, security/audit layers, anomaly detection routines, and retention management documentation.
- Bulk and delta loader implementations with checkpoints, DLQ, telemetry, circuit breakers, and operator runbooks.
- Reporting CLI/service plus updated Elastic exporter integrations, health checks, and compatibility notes.
- Telemetry dashboards, OpenTelemetry instrumentation samples, and logging/metrics configuration guides.
- Comprehensive test suites (unit, integration, performance, chaos), baseline benchmarks, reconciliation scripts, and rollout checklist with feature flags and rollback steps.
- Migration utility for seeding Postgres from SQLite, including JSON1→JSONB mappings, and guidance for long-term archival/storage strategies.
- Data quality assurance artifacts (referential integrity checks, anomaly detectors, reconciliation reports) covering SQLite/Postgres parity.
