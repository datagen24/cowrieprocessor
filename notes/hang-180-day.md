# Bulk Load Hang (180-day ingest)

## Context
- Observed during a `process_cowrie.py` run with `--bulk-load` and a 180-day dataset.
- All log files were discovered and opened, but processing stalled while writing the first few sessions.
- The SQLite database stopped growing, suggesting the pipeline is blocked before/while committing rows.

## Debugging Checklist
1. **Capture full runtime logs**
   - For direct processor runs, use `scripts/run_processor_debug.sh` to wrap `process_cowrie.py` with unbuffered output.
   - For orchestrated runs (recommended), use `scripts/run_orchestrator_debug.sh`:
     ```bash
     scripts/run_orchestrator_debug.sh \
         --config sensors.toml \
         --bulk-load --days 180 \
         --buffer-bytes 67108864 \
         --status-poll-seconds 15 \
         --skip-enrich
     ```
- The scripts write logs to `debug-logs/<entrypoint>-<timestamp>.log` for sharing and post-mortem analysis.
- `PYTHONFAULTHANDLER=1` is enabled, so you can dump live stack traces with `kill -USR1 <pid>`.
- Status JSON now reports additional fields (`log_entries`, `log_entries_indexed`, `total_sessions`, `sessions_processed`, `elapsed_secs`) as the job moves through reading, indexing, and session analysis phases.

2. **Watch SQLite activity**
   - Keep `sqlite3` open on the target DB (`.dbinfo`, `.schema sessions`, count rows) to monitor whether inserts resume.
   - If the job stalls again, capture `PRAGMA wal_checkpoint;` output and `sqlite_master` metadata.

3. **Monitor status files**
   - Tail the per-sensor status JSON (e.g. `/mnt/dshield/data/logs/status/<sensor>.json`) to confirm whether `processed_files` advances.
   - Capture a snapshot when the hang occurs.

4. **Inspect rate-limit and cache code paths**
   - Enable additional logging around `with_timeout`, `rate_limit`, and cache hits/misses to ensure they are not blocking.
   - If needed, instrument `write_status` to include phase markers (e.g. "loading sessions", "writing DB").

5. **Collect system metrics**
   - When the stall happens, record `ps aux`, `lsof -p <pid>`, and `strace -p <pid> -f -tt -o strace.log` for short intervals.

## Next Steps
- Reproduce the hang using the debug script and attach the generated log plus DB snapshots to the issue.
- Prioritize examining long-running DB transactions and SPUR/URLHaus enrichments, as they historically delay session finalization.
- After enrichment refactors land, re-run the scenario to confirm whether the hang persists.
