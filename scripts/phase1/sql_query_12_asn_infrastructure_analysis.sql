-- ============================================================================
-- QUERY 12: ASN and Hosting Provider Analysis
-- ============================================================================
-- PURPOSE: Identify cloud provider abuse and hosting infrastructure patterns
-- EXPECTED: ~100-500 rows (top ASNs)
-- EXECUTION TIME: ~15-30 seconds
-- CSV: results/12_asn_infrastructure_analysis.csv
-- DATE RANGE: 2024-11-01 to 2025-11-01 (1 year)
-- ============================================================================
--
-- USAGE:
--   psql -h 10.130.30.89 -U username -d dshield \
--        -f scripts/phase1/sql_query_12_asn_infrastructure_analysis.sql \
--        -o results/12_asn_infrastructure_analysis.csv
--
-- OR with CSV format:
--   psql -h 10.130.30.89 -U username -d dshield \
--        -f scripts/phase1/sql_query_12_asn_infrastructure_analysis.sql \
--        --csv > results/12_asn_infrastructure_analysis.csv
-- ============================================================================

\echo 'Executing Query 12: ASN and Infrastructure Analysis'
\echo 'Expected runtime: 15-30 seconds'
\echo '======================================================================'

SELECT
    enrichment->'dshield'->>'asn' as asn,
    enrichment->'dshield'->>'as_name' as as_name,
    enrichment->'dshield'->>'country' as primary_country,
    COUNT(DISTINCT session_id) as session_count,
    COUNT(DISTINCT DATE(first_event_at)) as days_active,
    MIN(first_event_at) as first_seen,
    MAX(first_event_at) as last_seen,
    ROUND(AVG(command_count), 2) as avg_commands,
    SUM(file_downloads) as total_downloads,
    SUM(ssh_key_injections) as total_ssh_injections,
    SUM(CASE WHEN vt_flagged THEN 1 ELSE 0 END) as vt_flagged_sessions,
    SUM(CASE WHEN dshield_flagged THEN 1 ELSE 0 END) as dshield_flagged_sessions,
    -- Classify infrastructure type based on AS name patterns
    CASE
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%amazon%' OR
             enrichment->'dshield'->>'as_name' ILIKE '%aws%' THEN 'AWS'
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%microsoft%' OR
             enrichment->'dshield'->>'as_name' ILIKE '%azure%' THEN 'Azure'
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%google%' OR
             enrichment->'dshield'->>'as_name' ILIKE '%gcp%' THEN 'GCP'
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%digitalocean%' THEN 'DigitalOcean'
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%linode%' THEN 'Linode'
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%ovh%' THEN 'OVH'
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%hetzner%' THEN 'Hetzner'
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%alibaba%' THEN 'Alibaba Cloud'
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%vultr%' THEN 'Vultr'
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%telecom%' OR
             enrichment->'dshield'->>'as_name' ILIKE '%mobile%' OR
             enrichment->'dshield'->>'as_name' ILIKE '%broadband%' THEN 'ISP/Telecom'
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%hosting%' OR
             enrichment->'dshield'->>'as_name' ILIKE '%datacenter%' OR
             enrichment->'dshield'->>'as_name' ILIKE '%server%' THEN 'Hosting/Datacenter'
        ELSE 'Other/Unknown'
    END as infrastructure_type,
    -- Calculate session concentration within this ASN
    ROUND(
        100.0 * COUNT(DISTINCT session_id)::numeric /
        (SELECT COUNT(*) FROM session_summaries
         WHERE first_event_at >= '2024-11-01'
           AND first_event_at < '2025-11-01'
           AND enrichment->'dshield'->>'asn' IS NOT NULL),
        2
    ) as asn_percentage
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND first_event_at < '2025-11-01'
  AND enrichment->'dshield'->>'asn' IS NOT NULL
GROUP BY
    enrichment->'dshield'->>'asn',
    enrichment->'dshield'->>'as_name',
    enrichment->'dshield'->>'country'
HAVING COUNT(DISTINCT session_id) >= 50  -- Min 50 sessions per ASN
ORDER BY session_count DESC
LIMIT 500;

\echo ''
\echo 'Query 12 complete!'
\echo 'Top ASNs and cloud provider patterns should be visible above'
\echo '======================================================================'
