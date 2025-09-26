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
- Expose telemetry that clearly distinguishes ingest (bulk/delta) and reporting phases, with visibility into queue health, WAL checkpoints, JSON parsing, index efficiency, distributed traces, hostile-content risk scores, and neutralization effectiveness.
- Deliver a migration path and tooling to hydrate Postgres from SQLite when teams outgrow the single-file setup, including safety parity across engines.

## Proposed Phases

### Phase 0 – Discovery and Technical Design
- Inventory current ingest/report flows, entry points, ORM touchpoints, security boundaries, and how they interact with SQLite and the Elastic exporter today.
- Assess existing schema, migrations, PRAGMA settings, and storage patterns to determine compatibility with JSON columns, generated columns, and WAL mode.
- Evaluate ORM adoption (SQLAlchemy) for schema management, migrations, dual-target support (SQLite + Postgres), connection pooling, and raw-SQL escape hatches for hot paths.
- Define data retention, partitioning, indexing strategy, privacy requirements, hostile-content mitigation expectations, and observability targets (metrics, tracing, logging, alerting).
- Document operational constraints (dataset sizes, deployment environments, concurrency expectations) and initial Postgres migration considerations/mapping needs.
- Introduce supply-chain safeguards: dependency/SBOM inventory, vulnerability scanning requirements, library pinning strategy for ORM and security tooling, and cadence for updates.

### Phase 1 – Raw Event Storage Layer
- Design a `raw_events` table with JSON payload, canonical event metadata (session ID, timestamps, eventid, source file), generated/virtual columns for indexed JSON paths, and uniqueness constraints.
- Add supporting summary tables (e.g., `sessions`, `command_stats`) maintained via ingest-time processing or triggers and compatible with Elastic exporter expectations.
- Incorporate PRAGMA defaults (`journal_mode=WAL`, `synchronous=NORMAL`, `cache_size=-64000`) with configuration and fallback to `journal_mode=DELETE` where required.
- Define schema migrations, versioning, and rollback strategy, including ORM migration scripts, JSON schema validation before inserts, schema registry/version tracking for event evolution, multi-stage decoding prior to neutralization, and database triggers to audit access to sensitive columns.

### Phase 1.5 – Security & Data Integrity Layer
- Implement cryptographic integrity checksums (BLAKE3) per raw event batch and store verification metadata for tamper detection.
- Add row-level audit trails capturing actor, timestamp, and mutation type for critical tables, with zero-trust enforcement on privileged operations.
- Enforce strict JSON schema validation, anomaly detection hooks, malicious-pattern scanning, and neutralization effectiveness tracking before persistence; quarantine or reject hostile payloads.
- Establish referential integrity between `raw_events` and session summaries, with automated reconciliation jobs and audit reporting.

### Phase 2 – Bulk Loader Implementation
- Implement a streaming bulk loader that reads historical Cowrie logs, normalizes events, validates JSON, neutralizes hostile inputs, and batches inserts into `raw_events` using prepared statements and ORM sessions.
- Provide an optional raw-SQL bypass mode for bulk ingest when ORM overhead is prohibitive; document optimization patterns for JSON path operations.
- Build a hostile input pipeline: schema validation, prompt-injection scoring, multi-stage decoding, command neutralization (store sanitized command plus hashed original), exploit signature detection, and quarantine handling with DLQ metadata.
- Add batched quarantine workflows: when a batch risk threshold is exceeded, isolate the batch in a guarded transaction, emit a structured risk report, and require manual review/approval before commit.
- Track neutralization effectiveness metrics (success vs quarantine rates, false positives, signature update latency) and integrate them into telemetry.
- Optimize adaptive batching based on memory pressure and I/O throughput, leveraging parallel parsing with controlled write locks and connection pooling.
- Capture ingest checkpoints (file offsets, session boundaries), hostile-content metrics, telemetry (rows/sec, batch latency, checksum status, JSON failures, injection scores, neutralization cache hits), and distribute OpenTelemetry spans.
- Seed summary tables, run data quality checks, verify Elastic exporter compatibility, and fail secure on untrusted payloads.
- **Status:** Completed. Bulk loader in place with neutralization, checkpoints, telemetry metrics, and regression coverage.

### Phase 3 – Delta Loader Implementation
- Build a state tracker recording last processed file, timestamp, and session boundaries to ensure idempotent incremental ingest.
- Implement validation and deduplication using unique constraints plus ORM transactions; add a dead letter queue for malformed/rejected events and alternate review workflows.
- Provide restart/recovery logic, configurable backpressure mechanisms, rate limiting, and isolation/locking strategy for concurrent bulk/delta operations.
- Layer anomaly detection for live traffic (spikes in injection attempts, new exploit signatures, geographic intelligence, velocity shifts) with automated alerts, throttling, and feedback into neutralization rules.
- Surface telemetry on queue depth, retry counts, DLQ volume, anomaly signals, distributed trace spans, hostile-content statistics, and geographic intelligence; add circuit breakers when downstream systems (Elastic, Postgres) are unavailable.
- **Status:** Completed. Delta loader implemented with ingest cursors, rotation handling, hostile-content DLQ, and comprehensive tests. Telemetry/alert integration remains outstanding.

### Phase 4 – Reporting Tool Rewrite
- Create a reporting CLI/service that queries summary tables (and JSON as needed) via the ORM to produce daily, weekly, and monthly reports without re-reading logs.
- Deliver safe reporting outputs: neutralize or redact hostile commands, annotate risk levels, maintain a sandboxed export pipeline, and never expose raw attacker payloads by default.
- Add compliance/evidence modes with chain-of-custody support: cryptographically seal original commands for legal retention, expose configurable redaction levels per consumer type, and log access attempts.
- Support streaming pagination for large result sets, configurable output formats, and a compatibility layer for legacy report consumers including the Elastic exporter.
- Validate report outputs against the legacy implementation to guarantee parity; document ORM optimization strategies or raw SQL usage for heavy aggregations.
- Add health-check endpoints, graceful shutdown hooks ensuring report jobs flush checkpoints on termination, and content-security policies for any HTML outputs.
- **Status:** ORM repository/builders, telemetry-enabled reporting CLI, and migration guidance (`notes/reporting-migration.md`) are in place. Remaining tasks: validate report parity vs legacy outputs, restore enrichments/alerts/backfill ergonomics, and remove `es_reports.py` once Phase 4 bake completes.

- **Phase 5 – Telemetry & Operational Hardening**
    - Extend status telemetry to include phase markers (bulk ingest, delta ingest, reporting), timestamps, throughput, resource usage, hostile-content scores, neutralization effectiveness, neutralization cache hit rate, time-to-detection metrics, false positive rates, JSON parsing failures, index hit ratios, WAL checkpoint intervals/durations, and queue saturation.
    - Integrate OpenTelemetry tracing for loader and reporting workflows, with guidance on cardinality management; capture logs for neutralization/quarantine decisions, compliance mode accesses, and geographic intelligence updates.
    - Implement automated backpressure/throttling, circuit breakers, rate limiting, health check endpoints, and emergency isolation mode when defenses detect zero-day exploits or downstream outages.
    - Update documentation, dashboards, log aggregation strategy, alerting (prompt injection breakthroughs, command escape attempts, DLQ growth, anomaly spikes), and deployment scripts for new modes, telemetry fields, and configuration knobs.
    - Deliver incident-response playbooks covering hostile-content bypass, neutralization failure, supply-chain alerts, and rollback procedures for loader/reporting components.
- Implement a shared status emitter that writes bulk and delta loader telemetry (phase marker, throughput, checkpoints, DLQ metrics) to `/mnt/dshield/data/logs/status/` so `monitor_progress.py` and other observers expose unified progress.
- **Status:** Circuit breaker/backpressure for loader flushes landed, status emitter now produces aggregate `status.json` with throughput metrics, and loader/reporting paths (including repository queries) emit OpenTelemetry spans when the SDK is installed. `docs/telemetry-operations.md` now documents dashboards, alerts, and incident-response runbooks. Remaining work: wire dashboards into deployment automation and continue tuning alert thresholds as telemetry volume grows.

- **Phase 6 – Validation, Migration & Rollout**
    - **Status:** Validation checklist (`notes/phase6-validation-checklist.md`) and synthetic dataset generator (`scripts/generate_synthetic_cowrie.py`) prepared. Ready to execute real-world benchmarks, chaos tests, and parity checks against legacy outputs.

### Phase 6 – Validation, Migration & Rollout
- Develop unit/integration tests for raw event persistence, loader workflows, reporting queries, JSON validation, hostile-content detection, neutralization routines, schema registry flows, compliance-mode behaviors, and geographic intelligence handling.
- Add performance regression suites covering 180-day bulk loads (>10K events/sec target plus neutralization overhead), delta ingest latency (<5s log-to-query target), report generation (<30s monthly target), JSON lookup latency (<100ms), worst-case hostile payload scenarios, and neutralization edge cases.
- Run chaos tests (e.g., `kill -9` during writes) to validate recovery, plus data consistency checks comparing bulk vs delta results and SQLite vs Postgres reconciliations.
- Execute prompt-injection red team exercises, command neutralization verification, exploitation replay tests, fuzzing campaigns targeting neutralization bypass, regression suites for previously observed exploits, and continuous validation pipelines (weekly red-team automation, monthly rule updates, quarterly posture reviews).
- Ship feature flags, backward compatibility layers, A/B testing hooks, and Elastic exporter schema version locks for phased rollout.
- Provide a migration command to hydrate Postgres from existing SQLite databases, mapping JSON1 columns to JSONB, generated columns to computed columns, PRAGMAs to Postgres configs, and ensuring safety features port cleanly; document rollback procedures (bidirectional sync, pg_dump strategies).
- Finalize retention/archival strategy (compression, cold storage) with configurable policies, cascade deletes, privacy/PII redaction options, encryption for at-rest hostile payloads, compliance audit trails, and evidence preservation guidelines.

## Cross-Cutting Concerns
- Data lifecycle management: implement configurable retention, archival/compression, cascade deletes for expired raw events, automated reconciliation jobs, encrypted cold storage, and evidence preservation options.
- Privacy compliance: add optional PII detection/redaction hooks prior to persistence; document regulatory considerations for long-term event storage and encrypted payload handling.
- Schema evolution: leverage schema registry/versioning, ORM migrations, compatibility validation, automated migration generation, and version-locked consumers when adding JSON fields or summary tables.
- Concurrency control: document isolation levels, lock management, connection pooling, and ORM vs raw-SQL usage for mixed workloads while maintaining hostile-content checks in every path.
- Observability: define metrics, traces, logs, dashboards, alert thresholds, and log aggregation coverage for migration windows and hostile-content events.
- Elastic exporter alignment: ensure schema changes and summary tables remain compatible, with regression tests, versioned contracts, and circuit breakers to prevent runaway exports.
- AI/LLM safety: deliver sanitized data feeds for any ML/LLM consumers, hardened prompt templates, output validation, and guardrails preventing model-assisted command execution or leakage of raw payloads.
- Incident response: maintain runbooks, escalation trees, emergency isolation controls, and postmortem processes for hostile-content breakthroughs, neutralization failures, and supply-chain incidents.
- Supply chain security: establish dependency scanning cadence, SBOM maintenance, vulnerability triage workflows, and alerting for ORM/security library updates.
- Intelligence sharing (future-ready): outline requirements for anonymized threat exports, STIX/TAXII integration, and community contribution channels.

## Open Questions & Risks
- Which environments lack WAL support, and how should the system auto-negotiate alternative journal modes?
- What retention defaults satisfy operational, compliance, security, and evidence-preservation requirements, and how do we expose tuning knobs to operators?
- How will privacy/PII detection and hostile-content neutralization integrate with existing enrichment workflows without impacting throughput beyond acceptable limits?
- What level of Postgres support (managed vs self-hosted) do downstream teams expect, and how do we validate ORM abstractions, safety features, and performance across engines?
- How do we manage ORM lock-in while retaining flexibility for performance-critical raw SQL paths and ensuring security logic is not bypassed?
- How do we monitor and mitigate JSON index bloat, Elastic schema drift, migration rollback complexity, hostile-content false negatives, neutralization bypass via encoding/obfuscation, and geographic anomaly false positives during rollout?
- What processes govern supply-chain security (dependency scanning cadence, SBOM updates) to keep ORM and security libraries patched?
- How do we operationalize continuous validation (weekly red teams, monthly rule updates, quarterly reviews) without overwhelming teams?
- What governance is required for future intelligence sharing to avoid leaking sensitive honeypot data while contributing to community defense?

## Deliverables
- ORM-based schema definitions, migration scripts, schema registry tooling, validation utilities, safety enforcement modules, SBOM/dependency documentation, and supply-chain monitoring procedures for SQLite and Postgres.
- `raw_events`, summary tables, security/audit layers, anomaly detection routines, neutralization/quarantine services, batch risk reporting, and retention management documentation.
- Bulk and delta loader implementations with checkpoints, DLQ, telemetry, circuit breakers, hostile-input pipelines, anomaly detection, geographic intelligence, and operator runbooks.
- Reporting CLI/service plus updated Elastic exporter integrations, health checks, compliance/evidence modes, hostile-content safe rendering, and compatibility notes.
- Telemetry dashboards, OpenTelemetry instrumentation samples, hostile-content alerting guides, metrics specifications (neutralization cache hit rate, detection latency, false positives), and logging configuration references.
- Comprehensive test suites (unit, integration, performance, chaos, hostile-content, fuzzing, regression, continuous validation), baseline benchmarks, reconciliation scripts, and rollout checklist with feature flags and rollback steps.
- Migration utility for seeding Postgres from SQLite, including JSON1→JSONB mappings, safety feature parity, and guidance for long-term archival/storage strategies.
- Data quality assurance artifacts (referential integrity checks, anomaly detectors, reconciliation reports) covering SQLite/Postgres parity, hostile-content detection efficacy, and compliance auditability.
- Security playbook outlining common attack patterns, neutralization examples, escalation procedures, compliance guidance, and continuous validation schedule.
- Risk matrix and continuous improvement plan tracking neutralization bypass, supply-chain vulnerabilities, geographic anomalies, and emergent threats.
- Future Phase 7 blueprint for intelligence sharing, including anonymization requirements, integration patterns (MISP/STIX/TAXII), and community contribution workflows.

## Implementation Timeline (Draft)
- Phases 0–1.5 (foundation + security hardening): ~3 weeks
- Phase 2 (bulk loader with hostile-content pipeline & metrics): ~3 weeks
- Phase 3 (delta loader with anomaly/geographic intelligence): ~2 weeks
- Phases 4–5 (reporting, telemetry, incident response tooling): ~3 weeks
- Phase 6 (validation, continuous testing setup, rollout prep): ~3 weeks
- Phase 7 (intelligence sharing enablement – future roadmap): scope separately post-MVP
