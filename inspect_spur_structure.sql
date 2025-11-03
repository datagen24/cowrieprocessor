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
    (enrichment->'spur')::text as spur_structure,
    json_typeof(enrichment->'spur') as spur_type
FROM session_summaries
WHERE enrichment->'spur' IS NOT NULL
  AND enrichment->'spur'::text NOT IN ('[]', 'null', '{}')
LIMIT 1;

\echo ''
\echo 'Sample 2: Check SPUR data type and array elements'
\echo '----------------------------------------------------------------------------'
SELECT
    session_id,
    json_typeof(enrichment->'spur') as data_type,
    json_array_length(enrichment->'spur') as array_length,
    enrichment->'spur'->0 as first_element
FROM session_summaries
WHERE enrichment->'spur' IS NOT NULL
  AND json_typeof(enrichment->'spur') = 'array'
  AND json_array_length(enrichment->'spur') > 0
LIMIT 5;

\echo ''
\echo 'Sample 3: Check if SPUR is empty arrays'
\echo '----------------------------------------------------------------------------'
SELECT
    COUNT(*) as total_with_spur,
    SUM(CASE WHEN enrichment->'spur'::text = '[]' THEN 1 ELSE 0 END) as empty_array_count,
    SUM(CASE WHEN json_array_length(enrichment->'spur') > 0 THEN 1 ELSE 0 END) as non_empty_array_count,
    ROUND(100.0 * SUM(CASE WHEN enrichment->'spur'::text = '[]' THEN 1 ELSE 0 END) / COUNT(*), 2) as empty_array_pct
FROM session_summaries
WHERE enrichment->'spur' IS NOT NULL
  AND first_event_at >= '2024-11-01';

\echo ''
\echo 'Sample 4: If array elements exist, show their structure'
\echo '----------------------------------------------------------------------------'
SELECT
    session_id,
    json_array_length(enrichment->'spur') as array_len,
    (enrichment->'spur'->0)::text as first_elem_raw,
    json_typeof(enrichment->'spur'->0) as first_elem_type,
    -- Try accessing fields if first element is an object
    enrichment->'spur'->0->>'is_vpn' as is_vpn,
    enrichment->'spur'->0->>'is_proxy' as is_proxy,
    enrichment->'spur'->0->>'client' as client
FROM session_summaries
WHERE enrichment->'spur' IS NOT NULL
  AND json_typeof(enrichment->'spur') = 'array'
  AND json_array_length(enrichment->'spur') > 0
LIMIT 5;

\echo ''
\echo '============================================================================'
\echo 'INTERPRETATION:'
\echo '- If Sample 3 shows ~100% empty arrays: SPUR enrichment returned no data'
\echo '- If Sample 4 returns rows: SPUR data exists as array of objects'
\echo '- Empty SPUR likely means: No API key, API quota exceeded, or free tier'
\echo '============================================================================'
