-- Test query to verify refresh command will find sessions needing infrastructure enrichment
-- This matches the updated WHERE clause in get_session_query()

SELECT
    COUNT(*) as sessions_needing_enrichment,
    COUNT(CASE WHEN enrichment IS NULL THEN 1 END) as null_enrichment,
    COUNT(CASE WHEN enrichment->'password_stats' IS NOT NULL THEN 1 END) as has_password_stats,
    COUNT(CASE WHEN enrichment->'dshield' IS NULL THEN 1 END) as missing_dshield,
    COUNT(CASE WHEN enrichment->'spur' IS NULL THEN 1 END) as missing_spur,
    COUNT(CASE WHEN enrichment->'urlhaus' IS NULL THEN 1 END) as missing_urlhaus
FROM session_summaries
WHERE (enrichment IS NULL
       OR enrichment::text = 'null'
       OR enrichment::text = '{}'
       OR enrichment::text = ''
       OR enrichment->'dshield' IS NULL
       OR enrichment->'spur' IS NULL
       OR enrichment->'urlhaus' IS NULL)
  AND first_event_at >= '2024-11-01';

\echo ''
\echo 'Sample of 5 sessions that will be enriched:'
SELECT
    session_id,
    first_event_at,
    CASE
        WHEN enrichment IS NULL THEN 'NULL'
        WHEN enrichment->'password_stats' IS NOT NULL THEN 'Has password_stats'
        ELSE 'Empty/Unknown'
    END as current_enrichment_status,
    CASE
        WHEN enrichment->'dshield' IS NULL THEN 'Missing'
        ELSE 'Present'
    END as dshield_status,
    CASE
        WHEN enrichment->'spur' IS NULL THEN 'Missing'
        ELSE 'Present'
    END as spur_status
FROM session_summaries
WHERE (enrichment IS NULL
       OR enrichment::text = 'null'
       OR enrichment::text = '{}'
       OR enrichment::text = ''
       OR enrichment->'dshield' IS NULL
       OR enrichment->'spur' IS NULL
       OR enrichment->'urlhaus' IS NULL)
  AND first_event_at >= '2024-11-01'
ORDER BY first_event_at ASC
LIMIT 5;
