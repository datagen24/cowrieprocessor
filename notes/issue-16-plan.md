# Work Plan: Issue #16 - Speed up session reporting and fix session enumeration

## Context
- Issue #16 highlights inaccurate session counts and very slow reporting after ingesting large datasets.
- Current reporting walks in-memory event lists repeatedly, causing multi-hour runs and undercounted sessions when the session collector misses events.
- Recent recommendations emphasize structured telemetry, schema versioning, and performance benchmarking to ensure durable improvements.

## Objectives
- Restore accurate session enumeration across the ingest pipeline.
- Move per-session metrics to SQLite-backed structures consumed by the reporting step.
- Improve progress telemetry with clearer timestamps, counters, and phase markers.
- Adopt resilience and benchmarking practices so improvements are measurable and maintainable.

## Proposed Phases

### Phase 0 - Discovery and Baseline
- Audit session collection logic to understand why events without both `da39a3ee5e6b4b0d3255bfef95601890afd80709` and delimiter markers are ignored.
- Capture a representative dataset (existing 180-day sample) to confirm current session counts and timing.
- Inventory the current SQLite schema, journaling mode, and ingest write pattern.
- Record baseline metrics: total sessions detected, reporting runtime, telemetry cadence.

### Phase 1 - Fix Session Enumeration
- Implement a session validation pipeline with priority-based matchers so sessions are captured even when delimiters are missing:
  - `full_delimited`: current delimiter-based handler.
  - `session_id_only`: ensure events with `session` fields are recorded.
  - `event_session`: fall back to event-specific identifiers when needed.
- Add guards around sentinel filtering so alternate matchers populate the session map.
- Write unit tests covering missing delimiters, duplicate sessions, and partial events.
- Confirm that updated logic feeds downstream ingest stages without breaking expectations.

### Phase 2 - Persist Per-Session Metrics During Ingest
- Design or extend SQLite tables (e.g., `session_metrics`, `session_activity`) that consolidate command counts, timestamps, and VT/DShield flags.
- Add composite indexes for common lookups (time range, flagged sessions) and evaluate partial indexes where beneficial.
- Enable WAL mode with `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL` to support concurrent reads during ingest.
- Batch writes in transactions of roughly 1000-5000 records to balance throughput and memory footprint.
- Describe schema migrations, including version checks and upgrade paths, in the plan for rollout.

### Phase 3 - Rewrite Reporting to Stream From SQLite
- Replace in-memory scans with SQL queries that aggregate metrics from the new tables.
- Leverage window functions or incremental queries to stream cumulative statistics without loading entire datasets.
- Keep report outputs backward compatible; highlight any adjusted fields for documentation.
- Benchmark large ingests (including the 180-day dataset) to confirm reporting completes within the target window.

### Phase 4 - Enhance Status Telemetry
- Extend status JSON updates to include ISO timestamps, phase names, elapsed totals, and progress objects (`current`, `total`, `percent`, `rate_per_sec`).
- Surface resource metrics such as memory usage when available and estimate remaining time based on throughput.
- Increase default heartbeat intervals and thresholds so updates continue on large session counts.
- Validate telemetry consumers (dashboards, scripts) and update them if needed.

## Resilience and Operational Enhancements
- Add periodic checkpoints during long ingests that sync WAL state and persist offsets/session IDs for restart safety.
- Evaluate a parser -> queue -> enrichment workers -> DB writer pipeline so CPU-heavy enrichments run in parallel while writes stay serialized.
- Introduce versioned schema migrations (`SCHEMA_VERSION`, `run_migrations`) to manage deployment upgrades cleanly.
- Expose optional progress callbacks/hooks so external monitors can subscribe to ingest and reporting milestones.

## Validation Plan
- Unit tests exercising each session matcher path and ensuring accurate aggregation into SQLite tables.
- Performance regression test processing at least 1M events to hit the <5 minute reporting target.
- Integration test using the 180-day dataset to compare session counts before and after changes.
- Telemetry verification that elapsed time, progress percentages, and rate calculations remain consistent under load.
- Monitoring of SQLite transaction times, queue depth, and memory usage during test runs.

## Open Questions and Risks
- Can WAL mode and batched transactions sustain peak ingest volumes, or do we need sharding or further partitioning?
- What is the production deployment story for schema upgrades and how do we roll back if necessary?
- Do existing telemetry consumers tolerate the richer JSON payload, or do we need version negotiation?
- Does parallel enrichment introduce ordering or dependency concerns that need coordination mechanisms?

## Deliverables
- Ingest pipeline updates reflecting the new session matcher pipeline and SQLite writing strategy.
- Updated database schema definitions, migration scripts, and operational docs for enabling WAL.
- Reporting module rewritten to stream from SQLite and produce optimized summaries.
- Enhanced telemetry outputs with documentation and example payloads.
- Test suites and benchmark scripts demonstrating correctness and performance gains.
- Checkpointing utilities and monitoring hooks to support long-running ingest operations.

