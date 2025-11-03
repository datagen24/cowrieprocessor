-- ============================================================================
-- QUERY 13: VPN/Proxy/Tor Anonymization Analysis
-- ============================================================================
-- PURPOSE: Measure adversary operational security via anonymization techniques
-- EXPECTED: ~365 rows (daily anonymization statistics)
-- EXECUTION TIME: ~10-15 seconds
-- CSV: results/13_anonymization_analysis.csv
-- DATE RANGE: 2024-11-01 to 2025-11-01 (1 year)
-- ============================================================================
--
-- USAGE:
--   psql -h 10.130.30.89 -U username -d dshield \
--        -f scripts/phase1/sql_query_13_anonymization_analysis.sql \
--        -o results/13_anonymization_analysis.csv
--
-- OR with CSV format:
--   psql -h 10.130.30.89 -U username -d dshield \
--        -f scripts/phase1/sql_query_13_anonymization_analysis.sql \
--        --csv > results/13_anonymization_analysis.csv
-- ============================================================================

\echo 'Executing Query 13: VPN/Proxy/Tor Anonymization Analysis'
\echo 'Expected runtime: 10-15 seconds'
\echo '======================================================================'

SELECT
    DATE(first_event_at) as attack_date,
    COUNT(DISTINCT session_id) as total_sessions,

    -- VPN detection (from SPUR enrichment)
    SUM(CASE WHEN enrichment->'spur'->>'is_vpn' = 'true' OR
                  enrichment->>'is_vpn' = 'true' THEN 1 ELSE 0 END) as vpn_sessions,
    ROUND(
        100.0 * SUM(CASE WHEN enrichment->'spur'->>'is_vpn' = 'true' OR
                              enrichment->>'is_vpn' = 'true' THEN 1 ELSE 0 END)::numeric /
        NULLIF(COUNT(*), 0),
        2
    ) as vpn_ratio,

    -- Proxy detection (from SPUR enrichment)
    SUM(CASE WHEN enrichment->'spur'->>'is_proxy' = 'true' OR
                  enrichment->>'is_proxy' = 'true' THEN 1 ELSE 0 END) as proxy_sessions,
    ROUND(
        100.0 * SUM(CASE WHEN enrichment->'spur'->>'is_proxy' = 'true' OR
                              enrichment->>'is_proxy' = 'true' THEN 1 ELSE 0 END)::numeric /
        NULLIF(COUNT(*), 0),
        2
    ) as proxy_ratio,

    -- Tor detection (from SPUR enrichment)
    SUM(CASE WHEN enrichment->'spur'->>'is_tor' = 'true' OR
                  enrichment->>'is_tor' = 'true' THEN 1 ELSE 0 END) as tor_sessions,
    ROUND(
        100.0 * SUM(CASE WHEN enrichment->'spur'->>'is_tor' = 'true' OR
                              enrichment->>'is_tor' = 'true' THEN 1 ELSE 0 END)::numeric /
        NULLIF(COUNT(*), 0),
        2
    ) as tor_ratio,

    -- Any anonymization detected
    SUM(CASE WHEN enrichment->'spur'->>'is_vpn' = 'true' OR
                  enrichment->'spur'->>'is_proxy' = 'true' OR
                  enrichment->'spur'->>'is_tor' = 'true' OR
                  enrichment->>'is_vpn' = 'true' OR
                  enrichment->>'is_proxy' = 'true' OR
                  enrichment->>'is_tor' = 'true' THEN 1 ELSE 0 END) as anonymized_sessions,
    ROUND(
        100.0 * SUM(CASE WHEN enrichment->'spur'->>'is_vpn' = 'true' OR
                              enrichment->'spur'->>'is_proxy' = 'true' OR
                              enrichment->'spur'->>'is_tor' = 'true' OR
                              enrichment->>'is_vpn' = 'true' OR
                              enrichment->>'is_proxy' = 'true' OR
                              enrichment->>'is_tor' = 'true' THEN 1 ELSE 0 END)::numeric /
        NULLIF(COUNT(*), 0),
        2
    ) as anonymization_ratio,

    -- SPUR client type distribution (if available)
    COUNT(CASE WHEN enrichment->'spur'->>'client' = 'RESIDENTIAL' THEN 1 END) as residential_count,
    COUNT(CASE WHEN enrichment->'spur'->>'client' = 'DATACENTER' THEN 1 END) as datacenter_count,
    COUNT(CASE WHEN enrichment->'spur'->>'client' = 'HOSTING' THEN 1 END) as hosting_count,
    COUNT(CASE WHEN enrichment->'spur'->>'client' = 'MOBILE' THEN 1 END) as mobile_count,

    -- Infrastructure ratios
    ROUND(
        100.0 * COUNT(CASE WHEN enrichment->'spur'->>'client' = 'RESIDENTIAL' THEN 1 END)::numeric /
        NULLIF(COUNT(CASE WHEN enrichment->'spur'->>'client' IS NOT NULL THEN 1 END), 0),
        2
    ) as residential_ratio,
    ROUND(
        100.0 * COUNT(CASE WHEN enrichment->'spur'->>'client' = 'DATACENTER' THEN 1 END)::numeric /
        NULLIF(COUNT(CASE WHEN enrichment->'spur'->>'client' IS NOT NULL THEN 1 END), 0),
        2
    ) as datacenter_ratio

FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND first_event_at < '2025-11-01'
  AND enrichment IS NOT NULL
GROUP BY DATE(first_event_at)
ORDER BY attack_date DESC;

\echo ''
\echo 'Query 13 complete!'
\echo 'Anonymization trends by day should be visible above'
\echo '======================================================================'
