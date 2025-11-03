-- ============================================================================
-- QUERY 14: DShield Reputation Score Distribution
-- ============================================================================
-- PURPOSE: Prioritize response based on DShield attack history and reputation
-- EXPECTED: ~5-10 rows (reputation score buckets)
-- EXECUTION TIME: ~5-10 seconds
-- CSV: results/14_reputation_distribution.csv
-- DATE RANGE: 2024-11-01 to 2025-11-01 (1 year)
-- ============================================================================
--
-- USAGE:
--   psql -h 10.130.30.89 -U username -d dshield \
--        -f scripts/phase1/sql_query_14_reputation_distribution.sql \
--        -o results/14_reputation_distribution.csv
--
-- OR with CSV format:
--   psql -h 10.130.30.89 -U username -d dshield \
--        -f scripts/phase1/sql_query_14_reputation_distribution.sql \
--        --csv > results/14_reputation_distribution.csv
-- ============================================================================

\echo 'Executing Query 14: DShield Reputation Distribution'
\echo 'Expected runtime: 5-10 seconds'
\echo '======================================================================'

SELECT
    -- Bucket DShield attack counts into meaningful ranges
    CASE
        WHEN enrichment->'dshield'->>'attacks' IS NULL THEN 'no_data'
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) = 0 THEN '0_first_time'
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) BETWEEN 1 AND 10 THEN '1-10_low'
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) BETWEEN 11 AND 100 THEN '11-100_medium'
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) BETWEEN 101 AND 1000 THEN '101-1000_high'
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) > 1000 THEN '1000+_very_high'
        ELSE 'unknown'
    END as reputation_bucket,

    COUNT(DISTINCT session_id) as session_count,
    ROUND(AVG(command_count), 2) as avg_commands,
    SUM(file_downloads) as total_downloads,
    SUM(ssh_key_injections) as total_ssh_injections,
    SUM(CASE WHEN vt_flagged THEN 1 ELSE 0 END) as vt_flagged_count,
    SUM(CASE WHEN dshield_flagged THEN 1 ELSE 0 END) as dshield_flagged_count,

    -- Calculate percentage of total sessions
    ROUND(
        100.0 * COUNT(DISTINCT session_id)::numeric /
        (SELECT COUNT(*) FROM session_summaries
         WHERE first_event_at >= '2024-11-01'
           AND first_event_at < '2025-11-01'),
        2
    ) as percentage,

    -- Average attack count within bucket (for non-zero buckets)
    CASE
        WHEN enrichment->'dshield'->>'attacks' IS NULL THEN NULL
        ELSE ROUND(AVG(CAST(enrichment->'dshield'->>'attacks' AS INTEGER)), 2)
    END as avg_attack_count,

    -- Max attack count within bucket
    CASE
        WHEN enrichment->'dshield'->>'attacks' IS NULL THEN NULL
        ELSE MAX(CAST(enrichment->'dshield'->>'attacks' AS INTEGER))
    END as max_attack_count

FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND first_event_at < '2025-11-01'
GROUP BY reputation_bucket
ORDER BY
    CASE reputation_bucket
        WHEN 'no_data' THEN 0
        WHEN '0_first_time' THEN 1
        WHEN '1-10_low' THEN 2
        WHEN '11-100_medium' THEN 3
        WHEN '101-1000_high' THEN 4
        WHEN '1000+_very_high' THEN 5
        WHEN 'unknown' THEN 6
        ELSE 7
    END;

\echo ''
\echo 'Query 14 complete!'
\echo 'Reputation score distribution should be visible above'
\echo '======================================================================'
