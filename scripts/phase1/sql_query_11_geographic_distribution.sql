-- ============================================================================
-- QUERY 11: Geographic Distribution Analysis
-- ============================================================================
-- PURPOSE: Analyze geographic patterns for nation-state vs cybercrime distinction
-- EXPECTED: ~50-200 rows (top countries)
-- EXECUTION TIME: ~10-15 seconds
-- CSV: results/11_geographic_distribution.csv
-- DATE RANGE: 2024-11-01 to 2025-11-01 (1 year)
-- ============================================================================
--
-- USAGE:
--   psql -h 10.130.30.89 -U username -d dshield \
--        -f scripts/phase1/sql_query_11_geographic_distribution.sql \
--        -o results/11_geographic_distribution.csv
--
-- OR with CSV format:
--   psql -h 10.130.30.89 -U username -d dshield \
--        -f scripts/phase1/sql_query_11_geographic_distribution.sql \
--        --csv > results/11_geographic_distribution.csv
-- ============================================================================

\echo 'Executing Query 11: Geographic Distribution Analysis'
\echo 'Expected runtime: 10-15 seconds'
\echo '======================================================================'

SELECT
    enrichment->'dshield'->'ip'->>'ascountry' as country,
    COUNT(DISTINCT session_id) as session_count,
    COUNT(DISTINCT enrichment->'dshield'->'ip'->>'asn') as unique_asns,
    COUNT(DISTINCT DATE(first_event_at)) as days_active,
    MIN(first_event_at) as first_seen,
    MAX(first_event_at) as last_seen,
    ROUND(AVG(command_count), 2) as avg_commands_per_session,
    SUM(file_downloads) as total_file_downloads,
    SUM(CASE WHEN vt_flagged THEN 1 ELSE 0 END) as vt_flagged_count,
    SUM(CASE WHEN dshield_flagged THEN 1 ELSE 0 END) as dshield_flagged_count,
    -- Calculate geographic concentration percentage
    ROUND(
        100.0 * COUNT(DISTINCT session_id)::numeric /
        (SELECT COUNT(*) FROM session_summaries
         WHERE first_event_at >= '2024-11-01'
           AND first_event_at < '2025-11-01'
           AND enrichment->'dshield'->'ip'->>'ascountry' IS NOT NULL),
        2
    ) as country_percentage,
    -- Calculate ASN diversity (lower = more concentrated)
    ROUND(
        COUNT(DISTINCT enrichment->'dshield'->'ip'->>'asn')::numeric /
        NULLIF(COUNT(DISTINCT session_id), 0),
        3
    ) as asn_diversity_ratio
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND first_event_at < '2025-11-01'
  AND enrichment->'dshield'->'ip'->>'ascountry' IS NOT NULL
GROUP BY enrichment->'dshield'->'ip'->>'ascountry'
HAVING COUNT(DISTINCT session_id) >= 100  -- Min 100 sessions per country
ORDER BY session_count DESC
LIMIT 200;

\echo ''
\echo 'Query 11 complete!'
\echo 'Top countries by session count should be visible above'
\echo '======================================================================'
