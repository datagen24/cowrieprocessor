-- Inspect Actual DShield JSON Structure
-- This will show us what paths DShield data is actually stored at

\echo '============================================================================'
\echo 'DShield JSON Structure Investigation'
\echo '============================================================================'
\echo ''

\echo 'Sample 1: First enriched session with non-empty dshield'
\echo '----------------------------------------------------------------------------'
SELECT
    session_id,
    (enrichment->'dshield')::text as dshield_structure
FROM session_summaries
WHERE enrichment->'dshield' IS NOT NULL
  AND enrichment->'dshield'::text != '{}'
  AND enrichment->'dshield'::text != 'null'
LIMIT 1;

\echo ''
\echo 'Sample 2: Check all top-level keys in dshield object'
\echo '----------------------------------------------------------------------------'
SELECT DISTINCT
    json_object_keys(enrichment->'dshield') as dshield_keys
FROM session_summaries
WHERE enrichment->'dshield' IS NOT NULL
LIMIT 20;

\echo ''
\echo 'Sample 3: Check if data is nested under "ip" key'
\echo '----------------------------------------------------------------------------'
SELECT
    session_id,
    enrichment->'dshield'->'ip'->>'ascountry' as country,
    enrichment->'dshield'->'ip'->>'asn' as asn,
    enrichment->'dshield'->'ip'->>'asname' as as_name,
    enrichment->'dshield'->'ip'->>'attacks' as attacks
FROM session_summaries
WHERE enrichment->'dshield'->'ip' IS NOT NULL
LIMIT 5;

\echo ''
\echo '============================================================================'
