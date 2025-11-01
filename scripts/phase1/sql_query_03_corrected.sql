-- ============================================================================
-- QUERY 3: Command Pattern Analysis (CORRECTED)
-- ============================================================================
-- PURPOSE: Identify command patterns that distinguish threat actors
-- SOURCE: Extracts from RawEvent.payload JSON (following reporting/dal.py pattern)
-- EXPECTED: ~100-500 rows (most frequent commands)
-- EXECUTION TIME: ~30-60 seconds (queries raw events)
-- CSV: results/03_command_patterns.csv
-- MITRE: Various techniques based on command type
-- ============================================================================

SELECT
    payload->>'input' as command,
    COUNT(*) as occurrences,
    payload->>'sensor' as sensor,
    MAX(event_timestamp) as last_seen,
    MIN(event_timestamp) as first_seen,
    COUNT(DISTINCT session_id) as unique_sessions,
    -- Categorize command types for MITRE mapping
    CASE
        WHEN payload->>'input' ILIKE '%cron%' OR payload->>'input' ILIKE '%systemd%' OR payload->>'input' ILIKE '%systemctl%' THEN 'persistence'
        WHEN payload->>'input' ILIKE '%passwd%' OR payload->>'input' ILIKE '%useradd%' OR payload->>'input' ILIKE '%adduser%' THEN 'account_manipulation'
        WHEN payload->>'input' ILIKE '%cat /etc/%' OR payload->>'input' ILIKE '%cat /proc/%' THEN 'system_info_discovery'
        WHEN payload->>'input' ILIKE '%wget%' OR payload->>'input' ILIKE '%curl%' OR payload->>'input' ILIKE '%scp%' THEN 'resource_development'
        WHEN payload->>'input' ILIKE '%nmap%' OR payload->>'input' ILIKE '%masscan%' OR payload->>'input' ILIKE '%ping%' THEN 'network_scan'
        WHEN payload->>'input' ILIKE '%ssh%' OR payload->>'input' ILIKE '%telnet%' THEN 'lateral_movement'
        ELSE 'other'
    END as command_category
FROM raw_events
WHERE event_timestamp >= '2024-11-01'
  AND event_timestamp < '2025-11-01'
  AND event_type ILIKE '%command%'  -- Filter for command events only
  AND payload->>'input' IS NOT NULL  -- Exclude NULL commands
  AND payload->>'input' != ''        -- Exclude empty commands
GROUP BY payload->>'input', payload->>'sensor'
ORDER BY COUNT(*) DESC
LIMIT 500;

-- ============================================================================
-- NOTES
-- ============================================================================
-- 1. This query follows the pattern from cowrieprocessor/reporting/dal.py:top_commands()
-- 2. Extracts 'input' field from payload JSON (command text)
-- 3. Groups by command + sensor to see sensor-specific patterns
-- 4. Filters for command events (event_type contains 'command')
-- 5. MITRE categories based on command patterns:
--    - persistence: T1053 (cron), T1543 (systemd)
--    - account_manipulation: T1098, T1136 (useradd)
--    - system_info_discovery: T1082 (cat /etc/*, /proc/*)
--    - resource_development: T1583 (wget, curl downloads)
--    - network_scan: T1046 (nmap, masscan)
--    - lateral_movement: T1021 (ssh, telnet)
-- ============================================================================

-- Alternative: If you want global aggregates (no sensor breakdown):
--
-- SELECT
--     payload->>'input' as command,
--     COUNT(*) as total_occurrences,
--     COUNT(DISTINCT payload->>'sensor') as sensor_count,
--     COUNT(DISTINCT session_id) as session_count,
--     MAX(event_timestamp) as last_seen,
--     MIN(event_timestamp) as first_seen
-- FROM raw_events
-- WHERE event_timestamp >= '2024-11-01'
--   AND event_timestamp < '2025-11-01'
--   AND event_type ILIKE '%command%'
--   AND payload->>'input' IS NOT NULL
-- GROUP BY payload->>'input'
-- ORDER BY COUNT(*) DESC
-- LIMIT 500;
