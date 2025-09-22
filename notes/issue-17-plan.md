# Work Plan: Issue #17 - Split loader/reporting workflows and use SQLite JSON for sessions

## Context
- Issue #17 calls for decoupling ingestion from reporting and persisting raw Cowrie sessions in SQLite JSON columns for scalable analytics.
- Current pipeline reprocesses raw logs for reports, lacks clear ingest/report boundaries, and cannot efficiently handle 180-day backfills or incremental updates.
- Existing schema stores derived data but not the original event stream, limiting future reprocessing, telemetry, and integrations like the Elastic exporter.
- The refactor must keep the Elastic exporter in sync, adopt an ORM (SQLAlchemy) for database portability, prepare for optional Postgres deployments alongside SQLite, and layer in hostile-content defenses.

## Objectives
- Persist raw Cowrie events in SQLite with JSON columns plus generated/virtual columns for key fields, and build indexed summary tables for session-level metrics.
- Provide a high-throughput bulk loader for historical ranges and a delta loader that resumes from the last successful ingest while enforcing validation, integrity, and hostile-content safeguards.
- Rewrite reporting to rely on the SQLite/ORM data model instead of raw file scans, producing daily/weekly/monthly outputs, keeping Elastic exporter consumers aligned, and delivering report artifacts free of dangerous payloads.
- Expose telemetry that clearly distinguishes ingest (bulk/delta) and reporting phases, with visibility into queue health, WAL checkpoints, JSON parsing, index efficiency, distributed traces, and hostile-content risk scores.
- Deliver a migration path and tooling to hydrate Postgres from SQLite when teams outgrow the single-file setup, including safety parity across engines.

## Proposed Phases

### Phase 0 – Discovery and Technical Design
- Inventory current ingest/report flows, entry points, ORM touchpoints, security boundaries, and how they interact with SQLite and the Elastic exporter today.
- Assess existing schema, migrations, PRAGMA settings, and storage patterns to determine compatibility with JSON columns, generated columns, and WAL mode.
- Evaluate ORM adoption (SQLAlchemy) for schema management, migrations, dual-target support (SQLite + Postgres), connection pooling, and raw-SQL escape hatches for hot paths.
- Define data retention, partitioning, indexing strategy, privacy requirements, hostile-content mitigation expectations, and observability targets (metrics, tracing, logging, alerting).
- Document operational constraints (dataset sizes, deployment environments, concurrency expectations) and initial Postgres migration considerations/mapping needs.

### Phase 1 – Raw Event Storage Layer
- Design a `raw_events` table with JSON payload, canonical event metadata (session ID, timestamps, eventid, source file), generated/virtual columns for indexed JSON paths, and uniqueness constraints.
- Add supporting summary tables (e.g., `sessions`, `command_stats`) maintained via ingest-time processing or triggers and compatible with Elastic exporter expectations.
- Incorporate PRAGMA defaults (`journal_mode=WAL`, `synchronous=NORMAL`, `cache_size=-64000`) with configuration and fallback to `journal_mode=DELETE` where required.
- Define schema migrations, versioning, and rollback strategy, including ORM migration scripts, JSON schema validation before inserts, schema registry/version tracking for event evolution, and database triggers to audit access to sensitive columns.

### Phase 1.5 – Security & Data Integrity Layer
- Implement cryptographic integrity checksums (BLAKE3) per raw event batch and store verification metadata for tamper detection.
- Add row-level audit trails capturing actor, timestamp, and mutation type for critical tables, with zero-trust enforcement on privileged operations.
- Enforce strict JSON schema validation, anomaly detection hooks, and malicious-pattern scanning before persistence; quarantine or reject hostile payloads.
- Establish referential integrity between `raw_events` and session summaries, with automated reconciliation jobs and audit reporting.

### Phase 2 – Bulk Loader Implementation
- Implement a streaming bulk loader that reads historical Cowrie logs, normalizes events, validates JSON, neutralizes hostile inputs, and batches inserts into `raw_events` using prepared statements and ORM sessions.
- Provide an optional raw-SQL bypass mode for bulk ingest when ORM overhead is prohibitive; document optimization patterns for JSON path operations.
- Build a hostile input pipeline: schema validation, prompt-injection scoring, command neutralization (store sanitized command plus hashed original), exploit signature detection, and quarantine handling with DLQ metadata.
- Optimize adaptive batching based on memory pressure and I/O throughput, leveraging parallel parsing with controlled write locks and connection pooling.
- Capture ingest checkpoints (file offsets, session boundaries), hostile-content metrics, telemetry (rows/sec, batch latency, checksum status, JSON failures, injection scores), and distribute OpenTelemetry spans.
- Seed summary tables, run data quality checks, verify Elastic exporter compatibility, and fail secure on untrusted payloads.

### Phase 3 – Delta Loader Implementation
- Build a state tracker recording last processed file, timestamp, and session boundaries to ensure idempotent incremental ingest.
- Implement validation and deduplication using unique constraints plus ORM transactions; add a dead letter queue for malformed/rejected events and alternate review workflows.
- Provide restart/recovery logic, configurable backpressure mechanisms, rate limiting, and isolation/locking strategy for concurrent bulk/delta operations.
- Surface telemetry on queue depth, retry counts, DLQ volume, distributed trace spans, and hostile-content statistics; add circuit breakers when downstream systems (Elastic, Postgres) are unavailable.

### Phase 4 – Reporting Tool Rewrite
- Create a reporting CLI/service that queries summary tables (and JSON as needed) via the ORM to produce daily, weekly, and monthly reports without re-reading logs.
- Deliver safe reporting outputs: neutralize or redact hostile commands, annotate risk levels, and maintain a sandboxed export pipeline; never expose raw attacker payloads by default.
- Support streaming pagination for large result sets, configurable output formats, and a compatibility layer for legacy report consumers including the Elastic exporter.
- Validate report outputs against the legacy implementation to guarantee parity; document ORM optimization strategies or raw SQL usage for heavy aggregations.
- Add health-check endpoints, graceful shutdown hooks ensuring report jobs flush checkpoints on termination, and content-security policies for any HTML outputs.

### Phase 5 – Telemetry & Operational Hardening
- Extend status telemetry to include phase markers (bulk ingest, delta ingest, reporting), timestamps, throughput, resource usage, hostile-content scores, JSON parsing failures, index hit ratios, WAL checkpoint intervals/durations, and queue saturation.
- Integrate OpenTelemetry tracing for loader and reporting workflows, with guidance on cardinality management; capture logs for neutralization/quarantine decisions.
- Implement automated backpressure/throttling, circuit breakers, rate limiting, and health check endpoints when approaching resource limits or downstream outages.
- Update documentation, dashboards, log aggregation strategy, alerting (prompt injection breakthroughs, command escape attempts, DLQ growth), and deployment scripts for new modes and telemetry fields.

### Phase 6 – Validation, Migration & Rollout
- Develop unit/integration tests for raw event persistence, loader workflows, reporting queries, JSON validation, hostile-content detection, neutralization routines, and schema registry flows.
- Add performance regression suites covering 180-day bulk loads (>10K events/sec target plus neutralization overhead), delta ingest latency (<5s log-to-query target), report generation (<30s monthly target), and JSON lookup latency (<100ms).
- Run chaos tests (e.g., `kill -9` during writes) to validate recovery, plus data consistency checks comparing bulk vs delta results and SQLite vs Postgres reconciliations.
- Execute prompt-injection red team exercises, command neutralization verification, and exploitation replay tests to validate the hostile-content posture.
- Ship feature flags, backward compatibility layers, A/B testing hooks, and Elastic exporter schema version locks for phased rollout.
- Provide a migration command to hydrate Postgres from existing SQLite databases, mapping JSON1 columns to JSONB, generated columns to computed columns, PRAGMAs to Postgres configs, and ensuring safety features port cleanly; document rollback procedures (bidirectional sync, pg_dump strategies).
- Finalize retention/archival strategy (compression, cold storage) with configurable policies, cascade deletes, privacy/PII redaction options, and encryption for at-rest hostile payloads.

## Cross-Cutting Concerns
- Data lifecycle management: implement configurable retention, archival/compression, cascade deletes for expired raw events, automated reconciliation jobs, and encrypted cold storage.
- Privacy compliance: add optional PII detection/redaction hooks prior to persistence; document regulatory considerations for long-term event storage and encrypted payload handling.
- Schema evolution: leverage schema registry/versioning, ORM migrations, compatibility validation, and automated migration generation when adding JSON fields or summary tables.
- Concurrency control: document isolation levels, lock management, connection pooling, and ORM vs raw-SQL usage for mixed workloads while maintaining hostile-content checks in every path.
- Observability: define metrics, traces, logs, dashboards, and alert thresholds; ensure log aggregation strategy covers migration windows and hostile-content events.
- Elastic exporter alignment: ensure schema changes and summary tables remain compatible, with regression tests, versioned contracts, and circuit breakers to prevent runaway exports.
- AI/LLM safety: deliver sanitized data feeds for any ML/LLM consumers, hardened prompt templates, output validation, and guardrails preventing model-assisted command execution or leakage of raw payloads.

## Open Questions & Risks
- Which environments lack WAL support, and how should the system auto-negotiate alternative journal modes?
- What retention defaults satisfy operational, compliance, and security requirements, and how do we expose tuning knobs to operators?
- How will privacy/PII detection and hostile-content neutralization integrate with existing enrichment workflows without impacting throughput beyond acceptable limits?
- What level of Postgres support (managed vs self-hosted) do downstream teams expect, and how do we validate ORM abstractions, safety features, and performance across engines?
- How do we manage ORM lock-in while retaining flexibility for performance-critical raw SQL paths and ensuring security logic is not bypassed?
- How do we monitor and mitigate JSON index bloat, Elastic schema drift, migration rollback complexity, and hostile-content false negatives during rollout?

## Deliverables
- ORM-based schema definitions, migration scripts, schema registry tooling, validation utilities, and hostile-content enforcement modules for SQLite and Postgres.
- `raw_events`, summary tables, security/audit layers, anomaly detection routines, neutralization/quarantine services, and retention management documentation.
- Bulk and delta loader implementations with checkpoints, DLQ, telemetry, circuit breakers, input-neutralization pipelines, and operator runbooks.
- Reporting CLI/service plus updated Elastic exporter integrations, health checks, hostile-content safe rendering, and compatibility notes.
- Telemetry dashboards, OpenTelemetry instrumentation samples, hostile-content alerting guides, and logging/metrics configuration references.
- Comprehensive test suites (unit, integration, performance, chaos, hostile-content), baseline benchmarks, reconciliation scripts, and rollout checklist with feature flags and rollback steps.
- Migration utility for seeding Postgres from SQLite, including JSON1→JSONB mappings, safety feature parity, and guidance for long-term archival/storage strategies.
- Data quality assurance artifacts (referential integrity checks, anomaly detectors, reconciliation reports) covering SQLite/Postgres parity and hostile-content detection efficacy.
- Risk matrix, hostile-content performance impact assessment, and continuous improvement plan for defensive controls.
