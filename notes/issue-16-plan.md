# Work Plan: Issue #16 - Speed up session reporting and fix session enumeration

## Context
- Issue #16 highlights inaccurate session counts and very slow reporting after ingesting large datasets.
- Current reporting walks in-memory event lists repeatedly, causing multi-hour runs and undercounted sessions when the session collector misses events.

## Objectives
- Restore accurate session enumeration across the ingest pipeline.
- Move per-session metrics to SQLite-backed structures consumed by the reporting step.
- Improve progress telemetry with clearer timestamps, counters, and phase markers.

## Proposed Phases

### Phase 0 - Discovery & Baseline
- Audit session collection logic to understand why events without both `da39a3ee5e6b4b0d3255bfef95601890afd80709` and delimiter markers are ignored.
- Capture a representative dataset (existing 180-day sample) to confirm current session counts and timing.
- Identify existing SQLite schema and how ingest currently persists data.

### Phase 1 - Fix Session Enumeration
- Trace where sessions are added in ingest to ensure every event with a session identifier is recorded.
- Add guard rails around sentinel-based filtering so sessions without both delimiters are still counted.
- Introduce focused unit/regression tests around session counting when delimiters are missing.

### Phase 2 - Persist Per-Session Metrics During Ingest
- Design new or updated SQLite tables (e.g., `session_metrics`, `session_activity`) to store command counts, first/last timestamps, and VT/DShield flags as ingest happens.
- Update ingest pipeline to write metrics incrementally while parsing events.
- Backfill data for existing entries during ingest runs and ensure indices support reporting queries.

### Phase 3 - Rewrite Reporting to Stream From SQLite
- Replace in-memory scans with SQL queries that aggregate session metrics directly from the new tables.
- Ensure reporting remains compatible with existing output formats and summaries.
- Benchmark large ingests to confirm runtime improvements.

### Phase 4 - Enhance Status Telemetry
- Extend status JSON updates to surface ISO timestamps, session counter progress, and phase names (`reading`, `indexing`, `session_metrics`, `report_generation`).
- Wire elapsed time calculations into telemetry output and optionally into CLI logging.
- Verify monitoring dashboards or scripts consume the new fields without breakage.

## Validation Plan
- Unit tests for session enumeration and new SQLite writers.
- Integration test (or scripted run) using the 180-day dataset to compare session counts before/after changes and measure runtime.
- Manual inspection of status telemetry output to ensure readability and correctness.

## Open Questions / Risks
- Do we have write-heavy concerns with SQLite when persisting per-session metrics for very large ingests?
- Is there an existing migration path for updating the SQLite schema in production environments?
- Are additional telemetry consumers relying on the current JSON format that could break?

## Deliverables
- Code updates covering ingest, reporting, and telemetry modules.
- Database schema migration or initialization scripts for new tables.
- Documentation updates summarizing the new reporting flow and telemetry fields.
- Test artifacts demonstrating correctness and performance gains.

