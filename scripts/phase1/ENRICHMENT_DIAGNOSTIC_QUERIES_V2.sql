-- ============================================================================
-- ENRICHMENT DATA DIAGNOSTIC QUERIES V2 (CORRECTED)
-- ============================================================================
-- PURPOSE: Diagnose enrichment data completeness - CHECK NESTED JSON FIELDS
-- DATE: 2025-11-01
-- ISSUE: Query 1 was checking if enrichment column IS NULL, not if nested
--        fields within the JSON are NULL. This version checks actual data.
-- ============================================================================

-- ============================================================================
-- QUERY 1: Enrichment JSON Structure Analysis
-- ============================================================================
-- PURPOSE: Check if enrichment JSON exists but is empty/malformed
-- CRITICAL: This checks NESTED FIELDS, not just if enrichment IS NOT NULL

SELECT
    COUNT(*) as total_sessions,
    -- Check if enrichment column exists
    COUNT(enrichment) as enrichment_column_exists,
    COUNT(*) - COUNT(enrichment) as enrichment_column_null,

    -- Check if nested DShield fields are populated
    COUNT(CASE WHEN enrichment->'dshield'->>'country' IS NOT NULL THEN 1 END) as has_country,
    COUNT(CASE WHEN enrichment->'dshield'->>'asn' IS NOT NULL THEN 1 END) as has_asn,
    COUNT(CASE WHEN enrichment->'dshield'->>'as_name' IS NOT NULL THEN 1 END) as has_as_name,

    -- Check if nested URLHaus fields are populated
    COUNT(CASE WHEN enrichment->'urlhaus'->>'threat_level' IS NOT NULL THEN 1 END) as has_urlhaus,

    -- Check if nested SPUR fields are populated
    COUNT(CASE WHEN enrichment->'spur'->>'client' IS NOT NULL THEN 1 END) as has_spur,

    -- Calculate percentages
    ROUND(100.0 * COUNT(CASE WHEN enrichment->'dshield'->>'country' IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as country_pct,
    ROUND(100.0 * COUNT(CASE WHEN enrichment->'dshield'->>'asn' IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as asn_pct,
    ROUND(100.0 * COUNT(CASE WHEN enrichment->'urlhaus' IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as urlhaus_pct,
    ROUND(100.0 * COUNT(CASE WHEN enrichment->'spur' IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as spur_pct
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND first_event_at < '2025-11-01';

-- ============================================================================
-- QUERY 2: Sample Enrichment JSON Structures
-- ============================================================================
-- PURPOSE: Inspect actual enrichment JSON to see what's in it
-- EXPECTED: Should see either empty objects {} or populated nested data

-- Sample of sessions WITH enrichment column
SELECT
    session_id,
    first_event_at,
    enrichment::text as enrichment_json_raw,
    jsonb_typeof(enrichment) as json_type,
    jsonb_object_keys(enrichment) as enrichment_keys
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND enrichment IS NOT NULL
LIMIT 10;

-- ============================================================================
-- QUERY 3: Empty Enrichment Objects
-- ============================================================================
-- PURPOSE: Count sessions with empty enrichment JSON objects
-- EXPECTED: If enrichment exists but is {}, this is a backfill failure

SELECT
    COUNT(*) as sessions_with_empty_enrichment,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM session_summaries WHERE first_event_at >= '2024-11-01'), 2) as empty_pct
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND enrichment IS NOT NULL
  AND jsonb_typeof(enrichment) = 'object'
  AND jsonb_object_keys(enrichment) IS NULL;  -- No keys = empty object

-- ============================================================================
-- QUERY 4: Enrichment by Service Availability
-- ============================================================================
-- PURPOSE: Check which enrichment services have data
-- CRITICAL: Checks if nested service objects exist and have data

SELECT
    COUNT(*) as total_with_enrichment,

    -- Check if service objects exist (not NULL)
    COUNT(CASE WHEN enrichment->'dshield' IS NOT NULL THEN 1 END) as dshield_exists,
    COUNT(CASE WHEN enrichment->'urlhaus' IS NOT NULL THEN 1 END) as urlhaus_exists,
    COUNT(CASE WHEN enrichment->'spur' IS NOT NULL THEN 1 END) as spur_exists,
    COUNT(CASE WHEN enrichment->'virustotal' IS NOT NULL THEN 1 END) as virustotal_exists,

    -- Check if service objects have actual data (not empty)
    COUNT(CASE WHEN jsonb_typeof(enrichment->'dshield') = 'object' AND enrichment->'dshield'->>'country' IS NOT NULL THEN 1 END) as dshield_populated,
    COUNT(CASE WHEN jsonb_typeof(enrichment->'urlhaus') = 'object' AND enrichment->'urlhaus'->>'threat_level' IS NOT NULL THEN 1 END) as urlhaus_populated,
    COUNT(CASE WHEN jsonb_typeof(enrichment->'spur') = 'object' AND enrichment->'spur'->>'client' IS NOT NULL THEN 1 END) as spur_populated,

    -- Calculate percentages
    ROUND(100.0 * COUNT(CASE WHEN enrichment->'dshield'->>'country' IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as dshield_data_pct,
    ROUND(100.0 * COUNT(CASE WHEN enrichment->'urlhaus'->>'threat_level' IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as urlhaus_data_pct,
    ROUND(100.0 * COUNT(CASE WHEN enrichment->'spur'->>'client' IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as spur_data_pct
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND enrichment IS NOT NULL;

-- ============================================================================
-- QUERY 5: Enrichment Completeness Over Time
-- ============================================================================
-- PURPOSE: Detect when enrichment stopped working
-- EXPECTED: Should show declining percentages if backfill stopped

SELECT
    DATE_TRUNC('week', first_event_at) as week,
    COUNT(*) as total_sessions,
    COUNT(enrichment) as enrichment_exists,
    COUNT(CASE WHEN enrichment->'dshield'->>'country' IS NOT NULL THEN 1 END) as has_country,
    COUNT(CASE WHEN enrichment->'dshield'->>'asn' IS NOT NULL THEN 1 END) as has_asn,

    ROUND(100.0 * COUNT(enrichment) / NULLIF(COUNT(*), 0), 2) as enrichment_exists_pct,
    ROUND(100.0 * COUNT(CASE WHEN enrichment->'dshield'->>'country' IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as country_pct,
    ROUND(100.0 * COUNT(CASE WHEN enrichment->'dshield'->>'asn' IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as asn_pct
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND first_event_at < '2025-11-01'
GROUP BY DATE_TRUNC('week', first_event_at)
ORDER BY week DESC
LIMIT 12;  -- Last 12 weeks

-- ============================================================================
-- QUERY 6: Enrichment vs Non-Enrichment Session Comparison
-- ============================================================================
-- PURPOSE: Compare sessions with and without enrichment data
-- HYPOTHESIS: Maybe only certain session types get enriched?

SELECT
    'With enrichment data' as session_type,
    COUNT(*) as count,
    AVG(command_count) as avg_commands,
    AVG(login_attempts) as avg_logins,
    AVG(file_downloads) as avg_downloads
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND enrichment->'dshield'->>'country' IS NOT NULL

UNION ALL

SELECT
    'Enrichment exists but empty' as session_type,
    COUNT(*) as count,
    AVG(command_count) as avg_commands,
    AVG(login_attempts) as avg_logins,
    AVG(file_downloads) as avg_downloads
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND enrichment IS NOT NULL
  AND enrichment->'dshield'->>'country' IS NULL

UNION ALL

SELECT
    'No enrichment column' as session_type,
    COUNT(*) as count,
    AVG(command_count) as avg_commands,
    AVG(login_attempts) as avg_logins,
    AVG(file_downloads) as avg_downloads
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND enrichment IS NULL;

-- ============================================================================
-- QUERY 7: Source IP Analysis (Why no enrichment?)
-- ============================================================================
-- PURPOSE: Check if we can extract source IPs to understand enrichment gaps
-- NOTE: Source IPs are in raw_events payload, not session_summaries

SELECT
    session_id,
    first_event_at,
    enrichment->'dshield'->>'country' as country,
    enrichment->'dshield'->>'asn' as asn,
    -- Try to find source IP from raw_events (sample approach)
    (SELECT payload->>'src_ip' FROM raw_events WHERE raw_events.session_id = session_summaries.session_id LIMIT 1) as src_ip
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND enrichment IS NOT NULL
ORDER BY first_event_at DESC
LIMIT 100;

-- ============================================================================
-- QUERY 8: Check Recent Ingestion vs Enrichment
-- ============================================================================
-- PURPOSE: Are newly ingested sessions being enriched?
-- EXPECTED: If backfill is working, recent sessions should have enrichment

SELECT
    DATE(first_event_at) as date,
    COUNT(*) as sessions_ingested,
    COUNT(enrichment) as enrichment_exists,
    COUNT(CASE WHEN enrichment->'dshield'->>'country' IS NOT NULL THEN 1 END) as has_enrichment_data,
    ROUND(100.0 * COUNT(CASE WHEN enrichment->'dshield'->>'country' IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as enrichment_pct
FROM session_summaries
WHERE first_event_at >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY DATE(first_event_at)
ORDER BY date DESC;

-- ============================================================================
-- QUERY 9: File Enrichment (VirusTotal) Completeness
-- ============================================================================
-- PURPOSE: Check if file enrichment is also failing

SELECT
    COUNT(*) as total_files,
    COUNT(vt_analysis) as vt_analysis_exists,
    COUNT(CASE WHEN vt_analysis->>'malicious' IS NOT NULL THEN 1 END) as has_vt_data,
    ROUND(100.0 * COUNT(vt_analysis) / NULLIF(COUNT(*), 0), 2) as vt_exists_pct,
    ROUND(100.0 * COUNT(CASE WHEN vt_analysis->>'malicious' IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as vt_data_pct
FROM files;

-- ============================================================================
-- QUERY 10: Diagnostic Summary
-- ============================================================================
-- PURPOSE: Single-query summary of the enrichment problem

WITH enrichment_stats AS (
    SELECT
        COUNT(*) as total_sessions,
        COUNT(enrichment) as enrichment_col_exists,
        COUNT(CASE WHEN enrichment->'dshield'->>'country' IS NOT NULL THEN 1 END) as has_country_data
    FROM session_summaries
    WHERE first_event_at >= '2024-11-01'
)
SELECT
    total_sessions,
    enrichment_col_exists,
    has_country_data,
    ROUND(100.0 * enrichment_col_exists / NULLIF(total_sessions, 0), 2) as enrichment_col_pct,
    ROUND(100.0 * has_country_data / NULLIF(total_sessions, 0), 2) as actual_data_pct,
    CASE
        WHEN enrichment_col_exists = 0 THEN '🔴 CRITICAL: No enrichment column at all'
        WHEN has_country_data = 0 THEN '🔴 CRITICAL: Enrichment exists but ALL nested fields are NULL - backfill completely failed'
        WHEN has_country_data < enrichment_col_exists * 0.5 THEN '🟡 WARNING: <50% of sessions have actual enrichment data'
        WHEN has_country_data < enrichment_col_exists * 0.9 THEN '🟡 WARNING: <90% of sessions have enrichment data'
        ELSE '✅ OK: >90% enrichment coverage'
    END as diagnosis
FROM enrichment_stats;

-- ============================================================================
-- EXECUTION INSTRUCTIONS
-- ============================================================================
-- 1. Run Query 1 FIRST - this gives the overall picture
-- 2. Run Query 10 for quick diagnosis
-- 3. If Query 1 shows 0% data, run Query 2 to see JSON structure
-- 4. Run Query 5 to see when enrichment stopped working
-- 5. Run Query 8 to check if recent sessions are being enriched
--
-- EXPECTED RESULTS (Healthy System):
-- Query 1: country_pct > 90%, asn_pct > 90%
-- Query 4: dshield_data_pct > 95%, urlhaus_data_pct > 80%
-- Query 5: Stable or increasing percentages over time
-- Query 10: actual_data_pct > 90%
--
-- CURRENT ISSUE (Based on CSV analysis):
-- Query 1 will likely show: enrichment_column_exists = 30000, has_country = 0
-- This means enrichment JSON exists but nested fields are NULL
-- Root cause: Backfill process either not running or failing to write data
-- ============================================================================

-- ============================================================================
-- INTERPRETATION GUIDE (CORRECTED)
-- ============================================================================
-- Query 1 shows enrichment_column_exists but has_country = 0:
--   → Enrichment JSON exists but is empty or malformed
--   → Backfill process created the column but didn't populate nested fields
--   → URGENT: Check if cowrie-enrich refresh has ever been run
--   → URGENT: Check if API keys are configured
--
-- Query 2 shows enrichment = '{}':
--   → Empty JSON object - backfill wrote structure but no data
--   → API calls likely all failing (check logs)
--
-- Query 2 shows enrichment = '{"dshield": null, "urlhaus": null}':
--   → Service keys exist but values are null
--   → API calls may be failing or returning empty responses
--
-- Query 5 shows declining country_pct over time:
--   → Backfill stopped working at some point
--   → Check cron jobs, scheduler, or automation
--
-- Query 8 shows recent days have 0% enrichment:
--   → New sessions not being enriched during ingestion
--   → Backfill not running on schedule
-- ============================================================================
