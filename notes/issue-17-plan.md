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
- Expose telemetry that clearly distinguishes ingest (bulk/delta) and reporting phases, with visibility into queue health, WAL checkpoints, JSON parsing, and index efficiency.
- Deliver a migration path and tooling to hydrate Postgres from SQLite when teams outgrow the single-file setup.

## Proposed Phases

### Phase 0 – Discovery and Technical Design
- Inventory current ingest/report flows, entry points, and how they interact with SQLite and the Elastic exporter today.
- Assess existing schema, migrations, PRAGMA settings, and storage patterns to determine compatibility with JSON columns, generated columns, and WAL mode.
- Evaluate ORM adoption (SQLAlchemy) for schema management, migrations, and dual-target support (SQLite + Postgres); outline abstraction boundaries.
- Define data retention, partitioning, indexing strategy, and privacy requirements for raw events and summary tables.
- Document operational constraints (dataset sizes, deployment environments, concurrency expectations) and initial Postgres migration considerations.

### Phase 1 – Raw Event Storage Layer
- Design a `raw_events` table with JSON payload, canonical event metadata (session ID, timestamps, eventid, source file), generated/virtual columns for indexed JSON paths, and uniqueness constraints.
- Add supporting summary tables (e.g., `sessions`, `command_stats`) maintained via ingest-time processing or triggers and compatible with Elastic exporter expectations.
- Incorporate PRAGMA defaults (`journal_mode=WAL`, `synchronous=NORMAL`, `cache_size=-64000`) with configuration and fallback to `journal_mode=DELETE` where required.
- Define schema migrations, versioning, and rollback strategy, including ORM migration scripts and automated JSON schema validation before inserts.

### Phase 1.5 – Security & Data Integrity Layer
- Implement cryptographic integrity checksums (BLAKE3) per raw event batch and store verification metadata for tamper detection.
- Add row-level audit trails capturing actor, timestamp, and mutation type for critical tables.
- Enforce strict JSON schema validation to prevent malformed or malicious payloads from entering storage.

### Phase 2 – Bulk Loader Implementation
- Implement a streaming bulk loader that reads historical Cowrie logs, normalizes events, validates JSON, and batches inserts into `raw_events` using prepared statements and ORM sessions.
- Optimize adaptive batching based on memory pressure and I/O throughput, leveraging parallel parsing with controlled write locks.
- Capture ingest checkpoints (file offsets, session boundaries) and telemetry (rows/sec, batch latency, checksum status).
- Seed summary tables and Elastic exporter dependencies as part of the ingest pipeline.

### Phase 3 – Delta Loader Implementation
- Build a state tracker recording last processed file, timestamp, and session boundaries to ensure idempotent incremental ingest.
- Implement validation and deduplication using unique constraints plus ORM transactions; add a dead letter queue for malformed/rejected events.
- Provide restart/recovery logic, configurable backpressure mechanisms, and isolation/locking strategy for concurrent bulk/delta operations.
- Surface telemetry on queue depth, retry counts, and DLQ volume.

### Phase 4 – Reporting Tool Rewrite
- Create a reporting CLI/service that queries summary tables (and JSON as needed) via the ORM to produce daily, weekly, and monthly reports without re-reading logs.
- Support streaming pagination for large result sets, configurable output formats, and a compatibility layer for legacy report consumers including the Elastic exporter.
- Validate report outputs against the legacy implementation to guarantee parity.

### Phase 5 – Telemetry & Operational Hardening
- Extend status telemetry to include phase markers (bulk ingest, delta ingest, reporting), timestamps, throughput, resource usage, JSON parsing failures, and index hit ratios.
- Instrument WAL checkpoint intervals/durations, queue saturation, checksum verification, and DLQ metrics.
- Implement automated backpressure and throttling when approaching resource limits.
- Update documentation, dashboards, and deployment scripts for new modes, telemetry fields, and configuration knobs.

### Phase 6 – Validation, Migration & Rollout
- Develop unit/integration tests for raw event persistence, loader workflows, reporting queries, and JSON validation.
- Add performance regression suites covering 180-day bulk loads, delta ingest parity, and reporting throughput; capture baseline metrics.
- Run chaos tests (e.g., `kill -9` during writes) to validate recovery, plus data consistency checks comparing bulk vs delta results.
- Ship feature flags and backward compatibility layers for phased rollout, including A/B testing of new telemetry/report outputs.
- Provide a migration command to hydrate Postgres from existing SQLite databases and document rollback procedures.
- Finalize retention/archival strategy (compression, cold storage) with configurable policies and referential integrity enforcement.

## Cross-Cutting Concerns
- Data lifecycle management: implement configurable retention with archival/compression and cascade deletes for expired raw events.
- Privacy compliance: add optional PII detection/redaction hooks prior to persistence.
- Schema evolution: outline strategy for adding JSON fields without breaking queries, leveraging ORM migrations and versioned schemas.
- Concurrency control: document isolation levels, lock management, and ORM session handling for mixed bulk/delta workloads.
- Elastic exporter alignment: ensure schema changes and summary tables remain compatible, with regression tests for exporter outputs.

## Open Questions & Risks
- Which environments lack WAL support, and how should the system auto-negotiate alternative journal modes?
- What retention defaults satisfy operational and compliance requirements, and how do we expose tuning knobs to operators?
- How will privacy/PII detection integrate with existing enrichment workflows without impacting throughput?
- What level of Postgres support (e.g., managed service vs self-hosted) do downstream teams expect, and how do we validate ORM abstractions across engines?

## Deliverables
- ORM-based schema definitions, migration scripts, and validation tooling for SQLite and Postgres.
- `raw_events`, summary tables, security/audit layers, and retention management documentation.
- Bulk and delta loader implementations with checkpoints, DLQ, telemetry, and operator runbooks.
- Reporting CLI/service plus updated Elastic exporter integrations and compatibility notes.
- Telemetry dashboards or JSON samples showing phase separation and new metrics.
- Comprehensive test suites (unit, integration, performance, chaos), baseline benchmarks, and rollout checklist with feature flags and rollback steps.
- Migration utility for seeding Postgres from SQLite and guidance for long-term archival/storage strategies.
