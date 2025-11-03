-- Inspect Actual SPUR JSON Structure
-- This will show us what paths SPUR data is actually stored at

\echo '============================================================================'
\echo 'SPUR JSON Structure Investigation'
\echo '============================================================================'
\echo ''

\echo 'Sample 1: First enriched session with non-empty spur'
\echo '----------------------------------------------------------------------------'
SELECT
    session_id,
    (enrichment->'spur')::text as spur_structure
FROM session_summaries
WHERE enrichment->'spur' IS NOT NULL
  AND enrichment->'spur'::text != '{}'
  AND enrichment->'spur'::text != 'null'
LIMIT 1;

\echo ''
\echo 'Sample 2: Check all top-level keys in spur object'
\echo '----------------------------------------------------------------------------'
SELECT DISTINCT
    json_object_keys(enrichment->'spur') as spur_keys
FROM session_summaries
WHERE enrichment->'spur' IS NOT NULL
LIMIT 20;

\echo ''
\echo 'Sample 3: Check common SPUR fields at different paths'
\echo '----------------------------------------------------------------------------'
SELECT
    session_id,
    -- Try direct paths
    enrichment->'spur'->>'is_vpn' as is_vpn_direct,
    enrichment->'spur'->>'is_proxy' as is_proxy_direct,
    enrichment->'spur'->>'is_tor' as is_tor_direct,
    enrichment->'spur'->>'client' as client_direct,
    -- Try nested under ip key (like DShield)
    enrichment->'spur'->'ip'->>'is_vpn' as is_vpn_nested,
    enrichment->'spur'->'ip'->>'is_proxy' as is_proxy_nested,
    enrichment->'spur'->'ip'->>'is_tor' as is_tor_nested,
    enrichment->'spur'->'ip'->>'client' as client_nested
FROM session_summaries
WHERE enrichment->'spur' IS NOT NULL
LIMIT 5;

\echo ''
\echo '============================================================================'
