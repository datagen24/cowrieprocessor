# Files Table Backfill & Schema Alignment

## Problem Statement
- Current v3 ORM schema (see `cowrieprocessor/db/models.py`) does **not** define a dedicated `files` table.
- Historical load pipelines still report “files downloaded” counts by scanning `raw_events`, so the metric exists but the per-hash metadata (VT descriptions, first seen, etc.) has no persistent home.
- `scripts/enrichment_refresh.py` correctly skips file enrichment because the table is absent, leaving VirusTotal enrichment data only in cache.

## Impact
- No place to persist refreshed VirusTotal metadata or flagged counts per hash.
- Reports/queries relying on `files` need to compute on-the-fly each time (expensive on a 39 GB dataset).
- Cache-only VT enrichment limits long-term analytics (no historical change tracking, no DB-backed joins with sessions).

## Proposed Actions
1. **Schema Rev (v4)**
   - Introduce a normalized `files` table with columns for `session_id`, `shasum`, `filename`, `vt_classification`, `vt_description`, `vt_malicious`, `vt_first_seen`, timestamps, etc.
   - Provide a migration path that backfills from `raw_events` (event `cowrie.session.file_download`) and deduplicates by hash.
2. **Loader Enhancements**
   - Update bulk/delta loaders to populate the new table during ingest.
   - Optionally parse the sensor `downloads/` directory for offline artifacts (hash + metadata) to seed the table beyond Cowrie logs.
3. **Refresh Pipeline**
   - Re-enable file enrichment in `enrichment_refresh.py` once the table exists.
   - Ensure cache + DB remain in sync (VT TTLs, retry queues).
4. **Testing & Migration**
   - End-to-end tests covering: backfilled schema, loader writes, enrichment refresh, report generation.
   - Migration tooling to handle large datasets (streaming backfill, progress logging).

## Notes
- Keep `USE_NEW_ENRICHMENT` flag to stage safely.
- Plan for the 39 GB dataset: backfilling the `files` table must be batched and likely reuses the warmed VT cache to avoid hammering APIs.
- Coordinate with reporting consumers once the schema lands (dashboard queries, Elasticsearch mappings).
