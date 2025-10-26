# Telemetry Operations & Incident Response Playbook

This guide explains how to use the Phase 5 telemetry outputs (status emitter, OpenTelemetry spans, and loader/reporting metrics) and how to respond when hostile content or ingestion failures are detected.

## 1. Telemetry Overview
- **Status files** — `status_emitter` now writes JSON snapshots to `/mnt/dshield/data/logs/status/` with `ingest_id`, throughput, quarantine counters, and last processed offsets. Use `monitor_progress.py` or the health CLI to inspect them quickly.
- **OpenTelemetry spans** — Loader and reporting paths instrument spans under the `cowrie.*` namespace:
  - `cowrie.bulk.load`, `cowrie.bulk.file`, `cowrie.bulk.flush`
  - `cowrie.delta.load`, `cowrie.delta.file`, `cowrie.delta.flush`
  - `cowrie.reporting.run`, `cowrie.reporting.build`, `cowrie.reporting.publish`
  - Repository-level spans (`cowrie.reporting.repo.*`) capture slow SQL calls.
- **Metrics cadence** — Bulk/delta loaders emit metrics every `telemetry_interval` batches; reporting updates metrics after every sensor context. Durations are captured so you can chart SLA regressions.

### Dashboards & Alerts
1. **Ingest Throughput** — Chart `events_read`, `events_inserted`, and `events_quarantined` per ingest ID. Alert when `events_quarantined / events_read > 10%` or `events_invalid` increases sharply.
2. **Flush Health** — Track `flush_failures`, `cooldowns_applied`, and circuit breaker activations. Alert immediately when the circuit breaker flag flips to true.
3. **Reporting Latency** — Use span durations for `cowrie.reporting.build` and `cowrie.reporting.repo.session_stats`. Set a warning threshold at 5s and a critical threshold at 15s.
4. **DLQ Growth** — Monitor the dead-letter table (delta loader) and publish alerts when growth exceeds 1000 records in an hour.
5. **Elasticsearch Publishing** — When `published_reports` stays at zero while `reports_generated` increases, alert operators to investigate pipeline connectivity.

## 2. Incident Response Runbooks

### A. Hostile Payload Detected / Quarantine Spike
1. **Confirm** — Review `events_quarantined` and `events_invalid` in status JSON; correlate with `cowrie.bulk.file` spans for the offending source path.
2. **Contain** — Enable emergency isolation via deployment tooling (stop loader service or switch to read-only mode).
3. **Inspect** — Pull dead-letter records for the ingest ID to analyse payload and update neutralisation signatures.
4. **Remediate** — Patch neutralisation rules, run unit tests (`tests/unit/test_bulk_loader.py`, `tests/unit/test_delta_loader.py`), and restart ingestion.
5. **Postmortem** — Log incident in the security runbook and update neutralisation heuristics.

### B. Neutralisation Failure / Prompt Injection Breakthrough
1. **Detect** — Look for spans marked with error status (`cowrie.bulk.flush`, `cowrie.delta.flush`, or `cowrie.reporting.build`).
2. **Isolate** — Trigger the circuit breaker if not already active by applying the `failure_cooldown_seconds` override or pausing the pipeline.
3. **Analyse** — Use `LoaderCheckpoint` outputs to replay the specific batch. Store original payload hashes in evidence storage.
4. **Patch & Validate** — Update sanitisation functions, add regression tests, and replay the quarantined batch from DLQ.
5. **Communicate** — Notify downstream consumers (Elastic, enrichment) about potential contamination and supply updated hashes.

### C. Supply Chain / Dependency Alert
1. **Assess** — Use `requirements.txt` and `uv.lock` to identify version exposure.
2. **Plan** — Schedule upgrade within the maintenance window; ensure new versions keep OTEL spans intact.
3. **Test** — Run `uv run pytest tests` and `uv run mypy .` before deployment.
4. **Deploy** — Roll out via existing automation; monitor spans for regressions in the first 30 minutes.

### D. Reporting Pipeline Freeze
1. **Verify** — Check `cowrie.reporting.run` spans; if missing or stalled, inspect CLI exit codes and the status emitter metrics.
2. **Fallback** — Disable publishing with `--publish` flag off, rerun reports locally to produce artifacts, and hand off to consumers.
3. **Repair** — Investigate repository spans (`cowrie.reporting.repo.*`) for slow SQL; add indices or vacuum as required.
4. **Resume** — Restore normal scheduling and confirm dashboards show expected throughput.

## 3. Operational Checklist
- Review dashboards daily; log anomalies even if auto-resolved.
- Run the health CLI (`uv run python -m cowrieprocessor.cli.health`) before major ingest waves.
- Rotate telemetry API keys and elastic credentials quarterly.
- Exercise the runbooks each quarter with a controlled chaos drill.
- Update this document whenever telemetry field names change.
