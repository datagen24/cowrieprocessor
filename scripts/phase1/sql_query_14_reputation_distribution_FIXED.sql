-- ============================================================================
-- QUERY 14: DShield Reputation Score Distribution (FIXED)
-- ============================================================================
-- PURPOSE: Prioritize response based on DShield attack history and reputation
-- EXPECTED: ~5-10 rows (reputation score buckets)
-- EXECUTION TIME: ~5-10 seconds
-- CSV: results/14_reputation_distribution.csv
-- DATE RANGE: 2024-11-01 to 2025-11-01 (1 year)
-- FIX: Corrected GROUP BY to repeat CASE expression (PostgreSQL requirement)
-- ============================================================================

\echo 'Executing Query 14: DShield Reputation Distribution (FIXED)'
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
-- FIX: Repeat CASE expression in GROUP BY (cannot use alias)
GROUP BY
    CASE
        WHEN enrichment->'dshield'->>'attacks' IS NULL THEN 'no_data'
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) = 0 THEN '0_first_time'
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) BETWEEN 1 AND 10 THEN '1-10_low'
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) BETWEEN 11 AND 100 THEN '11-100_medium'
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) BETWEEN 101 AND 1000 THEN '101-1000_high'
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) > 1000 THEN '1000+_very_high'
        ELSE 'unknown'
    END
ORDER BY
    CASE
        WHEN enrichment->'dshield'->>'attacks' IS NULL THEN 0
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) = 0 THEN 1
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) BETWEEN 1 AND 10 THEN 2
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) BETWEEN 11 AND 100 THEN 3
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) BETWEEN 101 AND 1000 THEN 4
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) > 1000 THEN 5
        ELSE 6
    END;

\echo ''
\echo 'Query 14 complete!'
\echo 'Reputation score distribution should be visible above'
\echo '======================================================================'
