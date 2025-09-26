# Phase 6 Validation Checklist – Real-World & Performance Testing

This checklist expands Phase 6 objectives into actionable test runs. Complete each section before promoting the new architecture beyond staging.

## 1. Environment Preparation
- [ ] Confirm the telemetry docs (`docs/telemetry-operations.md`) are deployed alongside the environment runbooks.
- [ ] Set OTEL variables for trace exports (see `deployment_configs.md`).
- [ ] Ensure `/mnt/dshield/data/logs/status/` is writable and monitored.
- [ ] Capture baseline database size and WAL settings (`sqlite3 .config`, `PRAGMA journal_mode`).

## 2. Dataset Selection / Generation
- [ ] Select at least 24h of real Cowrie JSON logs per sensor **or** generate synthetic load:
  ```bash
  ./scripts/generate_synthetic_cowrie.py data/synthetic/day01.json.gz \
      --sessions 5000 --commands-per-session 4 --downloads-per-session 2 \
      --sensor honeypot-a --sensor honeypot-b --seed 17
  ```
- [ ] Record dataset provenance (sensor list, time window, compression, total events).
- [ ] Verify hostile-content samples are represented (command injection, encoded payloads, large downloads).

## 3. Bulk Loader Validation
- [ ] Run bulk ingest against a clean database copy:
  ```bash
  uv run cowrie-loader bulk data/synthetic/day01.json.gz \
      --db tmp/phase6.sqlite --status-dir /mnt/dshield/data/logs/status
  ```
- [ ] For pretty-printed JSON files (2025-02 to 2025-03 range), use multiline parsing:
  ```bash
  uv run cowrie-loader bulk data/pretty-printed-logs.json \
      --db tmp/phase6.sqlite --status-dir /mnt/dshield/data/logs/status \
      --multiline-json
  ```
- [ ] Capture runtime, `events_read`, `events_inserted`, `events_quarantined`, and any DLQ inserts.
- [ ] Export OTEL traces for `cowrie.bulk.load` and attach screenshots or URLs.
- [ ] Inspect `tmp/phase6.sqlite` for row counts (`SELECT COUNT(*) FROM raw_events;`).

## 4. Delta Loader & Cursor Resilience
- [ ] Seed second dataset (new log chunk with overlap).
- [ ] Execute delta loader twice (back-to-back) to confirm idempotence:
  ```bash
  uv run cowrie-loader delta data/synthetic/day02.json.gz \
      --db tmp/phase6.sqlite --status-dir /mnt/dshield/data/logs/status
  ```
- [ ] Simulate failure mid-run (`kill -9`) and rerun to verify cursor recovery and DLQ replay.
- [ ] Validate status emitter reflects phase changes and last offset progression.

## 5. Reporting CLI / Elastic Export
- [ ] Generate daily/weekly/monthly reports for the validation window:
  ```bash
  uv run cowrie-report daily 2025-01-05 --db tmp/phase6.sqlite --all-sensors \
      --status-dir /mnt/dshield/data/logs/status --output reports/daily.json
  uv run cowrie-report weekly 2025-W01 --db tmp/phase6.sqlite --publish
  ```
- [ ] Confirm OTEL spans (`cowrie.reporting.run`, `cowrie.reporting.repo.*`) contain sensor/date attributes.
- [ ] If publishing to Elasticsearch, verify documents land in the `cowrie.reports.*` indices with expected counts.

## 6. Performance Benchmarks
- [ ] Bulk loader throughput ≥ 10k events/sec (document dataset volume, wall time, hardware).
- [ ] Delta loader latency: <5s from new log line to DB persistence (sample via status timestamps).
- [ ] Reporting CLI monthly run completes <30s with top-N queries (note actual duration).
- [ ] Record CPU, memory, and IO utilization snapshots.

## 7. Chaos & Failure Injection
- [ ] Interrupt bulk ingest mid-flush and validate circuit breaker cooldown + restart behaviour.
- [ ] Force write failure (toggle filesystem read-only or `sqlite3` lock) and ensure DLQ + retries behave.
- [ ] Introduce malformed/hostile payloads and confirm quarantine pipeline metrics spike and DLQ captures originals.

## 8. Data Consistency Checks
- [ ] Compare aggregate counts between raw_events and session_summaries (SQL reconciliation).
- [ ] Rebuild reports from the same dataset using the legacy pipeline (if available) and diff outputs.
- [ ] Run schema migration / downgrade rehearsal (SQLite → Postgres hydration sample if feasible).

## 9. Multiline JSON Format Handling
- [ ] Test with historical pretty-printed Cowrie logs (2025-02 to 2025-03 range):
  ```bash
  # Without multiline parsing (should produce validation DLQ entries)
  uv run cowrie-loader bulk data/historical/2025-02-logs.json --db tmp/test.sqlite
  
  # With multiline parsing (should ingest successfully)
  uv run cowrie-loader bulk data/historical/2025-02-logs.json --db tmp/test.sqlite --multiline-json
  ```
- [ ] Verify that multiline parsing reduces validation DLQ entries from ~135M to near zero for affected date ranges.
- [ ] Confirm that both single-line JSONL and multiline JSON formats are handled correctly.
- [ ] Document any preprocessing steps needed for non-standard JSON formats in deployment runbooks.

## 10. Sign-off Artifacts
- [ ] Archive status telemetry snapshots, OTEL traces, and report outputs in `/reports/phase6-validation/` (or similar).
- [ ] Update `notes/issue-17-plan.md` with benchmark numbers and remaining risks.

Completion of all checkboxes indicates readiness to transition from Phase 5 hardening to Phase 6 rollout drills.
