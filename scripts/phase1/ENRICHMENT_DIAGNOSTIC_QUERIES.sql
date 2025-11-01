-- ============================================================================
-- ENRICHMENT DATA DIAGNOSTIC QUERIES
-- ============================================================================
-- PURPOSE: Diagnose enrichment data completeness and identify gaps
-- DATE: 2025-11-01
-- CONTEXT: User reported "enrichment data has a lot of nulls"
-- ACTION: Run these queries to understand enrichment coverage
-- ============================================================================

-- ============================================================================
-- QUERY 1: Session Enrichment Completeness
-- ============================================================================
-- PURPOSE: Check what percentage of sessions have enrichment data
-- EXPECTED: Should be >90% for recent sessions if backfill is working

SELECT
    COUNT(*) as total_sessions,
    COUNT(enrichment) as enriched_sessions,
    COUNT(*) - COUNT(enrichment) as null_enrichment,
    ROUND(100.0 * COUNT(enrichment) / NULLIF(COUNT(*), 0), 2) as enrichment_percentage,
    COUNT(CASE WHEN vt_flagged THEN 1 END) as vt_flagged_count,
    COUNT(CASE WHEN dshield_flagged THEN 1 END) as dshield_flagged_count
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND first_event_at < '2025-11-01';

-- ============================================================================
-- QUERY 2: Enrichment by Service (PostgreSQL JSON Operators)
-- ============================================================================
-- PURPOSE: Check which enrichment services have the most nulls
-- EXPECTED: DShield should have highest coverage, SPUR may be lowest (requires API key)

SELECT
    COUNT(*) as total_enriched_sessions,
    COUNT(enrichment->'dshield') as dshield_count,
    COUNT(enrichment->'urlhaus') as urlhaus_count,
    COUNT(enrichment->'spur') as spur_count,
    ROUND(100.0 * COUNT(enrichment->'dshield') / NULLIF(COUNT(*), 0), 2) as dshield_pct,
    ROUND(100.0 * COUNT(enrichment->'urlhaus') / NULLIF(COUNT(*), 0), 2) as urlhaus_pct,
    ROUND(100.0 * COUNT(enrichment->'spur') / NULLIF(COUNT(*), 0), 2) as spur_pct
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND first_event_at < '2025-11-01'
  AND enrichment IS NOT NULL;

-- ============================================================================
-- QUERY 3: Enrichment by Time Period (Detect Backfill Gaps)
-- ============================================================================
-- PURPOSE: Check if recent sessions have better enrichment than older sessions
-- EXPECTED: If backfill is working, coverage should improve over time

SELECT
    DATE_TRUNC('week', first_event_at) as week,
    COUNT(*) as total_sessions,
    COUNT(enrichment) as enriched,
    ROUND(100.0 * COUNT(enrichment) / NULLIF(COUNT(*), 0), 2) as enrichment_pct,
    COUNT(enrichment->'dshield') as dshield_count,
    COUNT(enrichment->'urlhaus') as urlhaus_count,
    COUNT(enrichment->'spur') as spur_count
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND first_event_at < '2025-11-01'
GROUP BY DATE_TRUNC('week', first_event_at)
ORDER BY week DESC
LIMIT 10;

-- ============================================================================
-- QUERY 4: File Enrichment Completeness (VirusTotal)
-- ============================================================================
-- PURPOSE: Check what percentage of files have VirusTotal analysis
-- EXPECTED: Should be >80% if VirusTotal API key is configured

SELECT
    COUNT(*) as total_files,
    COUNT(vt_analysis) as vt_enriched,
    COUNT(*) - COUNT(vt_analysis) as null_vt,
    ROUND(100.0 * COUNT(vt_analysis) / NULLIF(COUNT(*), 0), 2) as vt_enrichment_pct,
    COUNT(CASE WHEN (vt_analysis->>'malicious')::int > 0 THEN 1 END) as malicious_files,
    COUNT(CASE WHEN (vt_analysis->>'suspicious')::int > 0 THEN 1 END) as suspicious_files
FROM files;

-- ============================================================================
-- QUERY 5: Enrichment Flags vs Enrichment Data Consistency
-- ============================================================================
-- PURPOSE: Check if vt_flagged/dshield_flagged are set without enrichment data
-- EXPECTED: Flags should only be set when enrichment data exists

SELECT
    'vt_flagged without enrichment' as issue_type,
    COUNT(*) as count
FROM session_summaries
WHERE vt_flagged = true
  AND (enrichment IS NULL OR enrichment->'virustotal' IS NULL)
  AND first_event_at >= '2024-11-01'
UNION ALL
SELECT
    'dshield_flagged without enrichment' as issue_type,
    COUNT(*) as count
FROM session_summaries
WHERE dshield_flagged = true
  AND (enrichment IS NULL OR enrichment->'dshield' IS NULL)
  AND first_event_at >= '2024-11-01'
UNION ALL
SELECT
    'enrichment without flags' as issue_type,
    COUNT(*) as count
FROM session_summaries
WHERE enrichment IS NOT NULL
  AND vt_flagged = false
  AND dshield_flagged = false
  AND first_event_at >= '2024-11-01';

-- ============================================================================
-- QUERY 6: Sample Enriched vs Non-Enriched Sessions
-- ============================================================================
-- PURPOSE: Get sample session IDs to inspect enrichment data structure
-- EXPECTED: Enriched sessions should have complete JSON structure

-- Sample enriched sessions
SELECT
    session_id,
    first_event_at,
    enrichment->'dshield'->>'country' as country,
    enrichment->'dshield'->>'asn' as asn,
    enrichment->'urlhaus'->>'threat_level' as urlhaus_threat,
    enrichment->'spur'->>'client' as spur_client,
    vt_flagged,
    dshield_flagged
FROM session_summaries
WHERE enrichment IS NOT NULL
  AND first_event_at >= '2024-11-01'
ORDER BY first_event_at DESC
LIMIT 10;

-- Sample non-enriched sessions
SELECT
    session_id,
    first_event_at,
    command_count,
    file_downloads,
    login_attempts,
    enrichment
FROM session_summaries
WHERE enrichment IS NULL
  AND first_event_at >= '2024-11-01'
ORDER BY first_event_at DESC
LIMIT 10;

-- ============================================================================
-- QUERY 7: Enrichment by Sensor
-- ============================================================================
-- PURPOSE: Check if enrichment gaps are sensor-specific
-- EXPECTED: All sensors should have similar enrichment coverage

SELECT
    enrichment->>'sensor' as sensor,
    COUNT(*) as total_sessions,
    COUNT(enrichment->'dshield') as dshield_count,
    COUNT(enrichment->'urlhaus') as urlhaus_count,
    COUNT(enrichment->'spur') as spur_count,
    ROUND(100.0 * COUNT(enrichment->'dshield') / NULLIF(COUNT(*), 0), 2) as dshield_pct
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND first_event_at < '2025-11-01'
  AND enrichment IS NOT NULL
GROUP BY enrichment->>'sensor'
ORDER BY total_sessions DESC;

-- ============================================================================
-- QUERY 8: High-Value Sessions Without Enrichment
-- ============================================================================
-- PURPOSE: Find high-activity sessions that should be prioritized for backfill
-- EXPECTED: These are the sessions we most want enriched

SELECT
    session_id,
    first_event_at,
    command_count,
    file_downloads,
    login_attempts,
    ssh_key_injections,
    risk_score
FROM session_summaries
WHERE enrichment IS NULL
  AND first_event_at >= '2024-11-01'
  AND (
    command_count > 10
    OR file_downloads > 0
    OR ssh_key_injections > 0
    OR risk_score > 0.5
  )
ORDER BY risk_score DESC, command_count DESC
LIMIT 100;

-- ============================================================================
-- QUERY 9: Enrichment Error Patterns (DLQ Check)
-- ============================================================================
-- PURPOSE: Check if enrichment failures are being tracked in DLQ
-- EXPECTED: DLQ should capture API failures for retry

SELECT
    COUNT(*) as total_dlq_entries,
    COUNT(CASE WHEN reason ILIKE '%enrich%' THEN 1 END) as enrichment_failures,
    COUNT(CASE WHEN reason ILIKE '%virustotal%' THEN 1 END) as vt_failures,
    COUNT(CASE WHEN reason ILIKE '%dshield%' THEN 1 END) as dshield_failures,
    COUNT(CASE WHEN reason ILIKE '%urlhaus%' THEN 1 END) as urlhaus_failures,
    COUNT(CASE WHEN reason ILIKE '%spur%' THEN 1 END) as spur_failures
FROM dead_letter_queue
WHERE created_at >= '2024-11-01';

-- ============================================================================
-- QUERY 10: Password Enrichment Completeness (HIBP)
-- ============================================================================
-- PURPOSE: Check if passwords are being enriched with HIBP breach data
-- EXPECTED: Should be >80% for recent passwords

SELECT
    COUNT(*) as total_passwords,
    COUNT(CASE WHEN last_hibp_check IS NOT NULL THEN 1 END) as hibp_checked,
    COUNT(CASE WHEN breached = true THEN 1 END) as breached_passwords,
    ROUND(100.0 * COUNT(CASE WHEN last_hibp_check IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as hibp_coverage_pct,
    ROUND(100.0 * COUNT(CASE WHEN breached = true THEN 1 END) / NULLIF(COUNT(CASE WHEN last_hibp_check IS NOT NULL THEN 1 END), 0), 2) as breach_rate_pct
FROM password_tracking
WHERE first_seen >= '2024-11-01';

-- ============================================================================
-- EXECUTION INSTRUCTIONS
-- ============================================================================
-- 1. Run in PGAdmin against production database
-- 2. Save results to spreadsheet or markdown for analysis
-- 3. Focus on queries 1-3 first (session enrichment completeness)
-- 4. If enrichment <90%, run backfill: cowrie-enrich refresh --sessions 0 --files 0
-- 5. Check cache directory: du -sh /mnt/dshield/data/cache/*
-- 6. Review logs: grep -i "enrichment" /var/log/cowrieprocessor/*.log
-- ============================================================================

-- ============================================================================
-- INTERPRETATION GUIDE
-- ============================================================================
-- Query 1: If enrichment_percentage < 90%, backfill is needed
-- Query 2: If dshield_pct < 95%, API key or rate limiting issues
-- Query 3: If recent weeks have lower enrichment, backfill stopped working
-- Query 4: If vt_enrichment_pct < 80%, VirusTotal API key issue
-- Query 5: If flags set without enrichment, data integrity issue
-- Query 6: Inspect JSON structure for completeness
-- Query 7: If one sensor has low enrichment, sensor-specific issue
-- Query 8: Priority sessions for immediate backfill
-- Query 9: If many DLQ entries, check error handling
-- Query 10: If hibp_coverage_pct < 80%, password enrichment not running
-- ============================================================================

-- ============================================================================
-- EXPECTED RESULTS (Healthy System)
-- ============================================================================
-- Query 1: enrichment_percentage > 90%
-- Query 2: dshield_pct > 95%, urlhaus_pct > 90%, spur_pct > 80%
-- Query 3: Enrichment percentage stable or increasing over time
-- Query 4: vt_enrichment_pct > 80%
-- Query 5: Zero flags set without enrichment data
-- Query 6: Complete JSON structures with all expected fields
-- Query 7: Similar enrichment coverage across all sensors
-- Query 8: <100 high-value sessions without enrichment
-- Query 9: <1% DLQ entries related to enrichment
-- Query 10: hibp_coverage_pct > 80%, breach_rate_pct > 50%
-- ============================================================================
