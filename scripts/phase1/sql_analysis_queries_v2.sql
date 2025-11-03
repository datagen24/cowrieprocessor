-- ============================================================================
-- Phase 1A Feature Discovery - SQL Analysis Queries (CORRECTED for actual schema)
-- ============================================================================
--
-- PURPOSE: Identify discriminative features for threat actor clustering
--
-- SCHEMA NOTES:
-- - SessionSummary: Aggregated metrics (first_event_at, last_event_at, command_count, etc.)
-- - RawEvent: Raw JSON payloads (src_ip, commands, passwords in JSON)
-- - SSHKeyIntelligence: SSH key tracking
-- - CommandStat: Command statistics
-- - PasswordTracking: Password tracking
--
-- DATE RANGE: 2024-11-01 to 2025-11-01 (1 year of data)
-- ============================================================================

-- ============================================================================
-- QUERY 1: Session Activity Patterns (SessionSummary-based)
-- ============================================================================
-- PURPOSE: Identify daily attack patterns using aggregated session metrics
-- EXPECTED: ~365 rows (1 year of daily data)
-- EXECUTION TIME: ~5-10 seconds
-- CSV: results/01_session_activity_patterns.csv
-- ============================================================================

SELECT
    DATE(first_event_at) as attack_date,
    COUNT(DISTINCT session_id) as session_count,
    SUM(command_count) as total_commands,
    AVG(command_count) as avg_commands_per_session,
    SUM(file_downloads) as total_file_downloads,
    SUM(login_attempts) as total_login_attempts,
    SUM(ssh_key_injections) as total_ssh_key_injections,
    SUM(CASE WHEN vt_flagged THEN 1 ELSE 0 END) as vt_flagged_sessions,
    SUM(CASE WHEN dshield_flagged THEN 1 ELSE 0 END) as dshield_flagged_sessions,
    AVG(EXTRACT(EPOCH FROM (last_event_at - first_event_at))) as avg_duration_seconds,
    STDDEV(command_count) as command_count_stddev
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND first_event_at < '2025-11-01'
GROUP BY DATE(first_event_at)
ORDER BY attack_date DESC;

-- ============================================================================
-- QUERY 2: SSH Key Reuse Analysis (GOLD MINE for persistent actors)
-- ============================================================================
-- PURPOSE: Track threat actors by SSH key fingerprints
-- EXPECTED: ~50-200 rows (unique SSH keys with multiple uses)
-- EXECUTION TIME: ~2-5 seconds
-- CSV: results/02_ssh_key_reuse.csv
-- MITRE: T1098 (Account Manipulation), T1078 (Valid Accounts)
-- ============================================================================

SELECT
    key_fingerprint,
    key_type,
    key_bits,
    pattern_type,
    first_seen,
    last_seen,
    (last_seen - first_seen) as campaign_duration,
    total_attempts,
    unique_sources as unique_ips,
    unique_sessions,
    CAST(unique_sessions AS FLOAT) / NULLIF(total_attempts, 0) as session_efficiency_ratio,
    EXTRACT(EPOCH FROM (last_seen - first_seen)) / NULLIF(total_attempts, 0) as avg_time_between_attempts
FROM ssh_key_intelligence
WHERE first_seen >= '2024-11-01'
  AND unique_sources >= 3  -- Multi-IP campaigns only
ORDER BY unique_sources DESC, total_attempts DESC
LIMIT 200;

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


-- ============================================================================
-- QUERY 4: Session Duration and Command Velocity Patterns
-- ============================================================================
-- PURPOSE: Identify behavioral timing patterns for actor fingerprinting
-- EXPECTED: ~1000-5000 rows (sessions with sufficient activity)
-- EXECUTION TIME: ~10-20 seconds
-- CSV: results/04_temporal_behavioral_patterns.csv
-- ============================================================================

SELECT
    session_id,
    first_event_at,
    last_event_at,
    EXTRACT(EPOCH FROM (last_event_at - first_event_at)) as duration_seconds,
    command_count,
    login_attempts,
    file_downloads,
    ssh_key_injections,
    -- Calculate command velocity (commands per minute)
    CASE
        WHEN EXTRACT(EPOCH FROM (last_event_at - first_event_at)) > 0
        THEN CAST(command_count AS FLOAT) / (EXTRACT(EPOCH FROM (last_event_at - first_event_at)) / 60.0)
        ELSE 0
    END as commands_per_minute,
    -- Time of day analysis
    EXTRACT(HOUR FROM first_event_at) as hour_of_day,
    EXTRACT(DOW FROM first_event_at) as day_of_week,
    -- Risk indicators
    vt_flagged,
    dshield_flagged,
    risk_score
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND first_event_at < '2025-11-01'
  AND command_count >= 3  -- Filter out very short sessions
ORDER BY first_event_at DESC
LIMIT 5000;

-- ============================================================================
-- QUERY 5: Password Tracking Analysis (CORRECTED)
-- ============================================================================
-- PURPOSE: Identify credential stuffing patterns and password strategies
-- EXPECTED: ~500-2000 rows (unique passwords with multiple uses)
-- EXECUTION TIME: ~5-10 seconds
-- CSV: results/05_password_patterns.csv
-- MITRE: T1110 (Brute Force), T1078 (Valid Accounts)
-- ============================================================================

SELECT
    password_hash,
    first_seen,
    last_seen,
    (last_seen - first_seen) as reuse_duration,
    times_seen,  -- ✅ Correct: not "attempt_count"
    unique_sessions,  -- ✅ Correct: not "session_count"
    breached,  -- ✅ Boolean flag if password is in breach database
    breach_prevalence,  -- ✅ Correct: not "hibp_breach_count"
    last_hibp_check,  -- ✅ Correct: not "hibp_checked_at"
    -- Calculate password reuse metrics
    CAST(unique_sessions AS FLOAT) / NULLIF(times_seen, 0) as success_ratio,
    EXTRACT(EPOCH FROM (last_seen - first_seen)) / NULLIF(times_seen, 0) as avg_time_between_attempts,
    -- Additional useful metrics
    CASE WHEN breached THEN 'breached' ELSE 'not_breached' END as breach_status
FROM password_tracking
WHERE first_seen >= '2024-11-01'
  AND times_seen >= 3  -- Multiple uses only
ORDER BY times_seen DESC, unique_sessions DESC
LIMIT 2000;

-- ============================================================================
-- NOTES FOR QUERY 5
-- ============================================================================
-- PasswordTracking schema (actual columns):
--   - password_hash: VARCHAR(64) - SHA256 hash
--   - times_seen: INTEGER (not "attempt_count")
--   - unique_sessions: INTEGER (not "session_count")
--   - breached: BOOLEAN (not "is_novel")
--   - breach_prevalence: INTEGER (not "hibp_breach_count")
--   - last_hibp_check: DATETIME (not "hibp_checked_at")
--   - password_text: TEXT (plaintext, use with caution)
--
-- No "unique_sensors" field exists. If needed, calculate from PasswordSessionUsage joins.
-- ============================================================================

-- ============================================================================
-- QUERY 6: Enrichment Data Analysis (DShield/SPUR patterns)
-- ============================================================================
-- PURPOSE: Extract infrastructure and reputation features from enrichment data
-- EXPECTED: ~1000-5000 rows (sessions with enrichment data)
-- EXECUTION TIME: ~10-20 seconds
-- CSV: results/06_enrichment_analysis.csv
-- ============================================================================

SELECT
    session_id,
    first_event_at,
    command_count,
    login_attempts,
    vt_flagged,
    dshield_flagged,
    -- Extract enrichment JSON fields (PostgreSQL JSON operators)
    enrichment->>'country' as country,
    enrichment->>'asn' as asn,
    enrichment->>'as_name' as as_name,
    enrichment->>'is_vpn' as is_vpn,
    enrichment->>'is_proxy' as is_proxy,
    enrichment->>'is_tor' as is_tor,
    enrichment->>'organization' as organization,
    enrichment->>'threat_level' as threat_level,
    -- Parse nested JSON if present
    enrichment->'dshield'->>'attacks' as dshield_attacks,
    enrichment->'dshield'->>'count' as dshield_count,
    enrichment->'spur'->>'client' as spur_client_type
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND first_event_at < '2025-11-01'
  AND enrichment IS NOT NULL
ORDER BY first_event_at DESC
LIMIT 5000;

-- ============================================================================
-- QUERY 7: High-Activity Sessions (Potential Advanced Actors)
-- ============================================================================
-- PURPOSE: Identify sessions with sophisticated attack patterns
-- EXPECTED: ~100-500 rows (top percentile of activity)
-- EXECUTION TIME: ~5-10 seconds
-- CSV: results/07_high_activity_sessions.csv
-- ============================================================================

SELECT
    session_id,
    first_event_at,
    last_event_at,
    EXTRACT(EPOCH FROM (last_event_at - first_event_at)) as duration_seconds,
    command_count,
    login_attempts,
    file_downloads,
    ssh_key_injections,
    unique_ssh_keys,
    vt_flagged,
    dshield_flagged,
    risk_score,
    -- Calculate activity density
    CASE
        WHEN EXTRACT(EPOCH FROM (last_event_at - first_event_at)) > 0
        THEN CAST(command_count AS FLOAT) / (EXTRACT(EPOCH FROM (last_event_at - first_event_at)) / 60.0)
        ELSE 0
    END as commands_per_minute,
    -- Sophistication indicators
    CASE WHEN file_downloads > 0 THEN 1 ELSE 0 END as has_downloads,
    CASE WHEN ssh_key_injections > 0 THEN 1 ELSE 0 END as has_ssh_injection,
    CASE WHEN unique_ssh_keys > 1 THEN 1 ELSE 0 END as multiple_ssh_keys
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND first_event_at < '2025-11-01'
  AND (
      command_count >= 20  -- High command count
      OR file_downloads >= 2  -- Multiple downloads
      OR ssh_key_injections >= 1  -- SSH key injection
      OR risk_score >= 70  -- High risk score
  )
ORDER BY command_count DESC, file_downloads DESC
LIMIT 500;

-- ============================================================================
-- QUERY 8: Session Clustering by Session Summary Features
-- ============================================================================
-- PURPOSE: Calculate session similarity for campaign correlation
-- EXPECTED: ~365 rows (daily aggregates for clustering)
-- EXECUTION TIME: ~10-15 seconds
-- CSV: results/08_session_feature_vectors.csv
-- ============================================================================

SELECT
    DATE(first_event_at) as attack_date,
    -- Aggregate behavioral features
    COUNT(DISTINCT session_id) as session_count,
    AVG(command_count) as avg_commands,
    STDDEV(command_count) as stddev_commands,
    AVG(login_attempts) as avg_login_attempts,
    AVG(file_downloads) as avg_file_downloads,
    AVG(ssh_key_injections) as avg_ssh_injections,
    -- Activity ratios
    SUM(CASE WHEN vt_flagged THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(*), 0) as vt_flagged_ratio,
    SUM(CASE WHEN dshield_flagged THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(*), 0) as dshield_flagged_ratio,
    SUM(CASE WHEN file_downloads > 0 THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(*), 0) as download_ratio,
    SUM(CASE WHEN ssh_key_injections > 0 THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(*), 0) as ssh_injection_ratio,
    -- Duration statistics
    AVG(EXTRACT(EPOCH FROM (last_event_at - first_event_at))) as avg_duration_seconds,
    STDDEV(EXTRACT(EPOCH FROM (last_event_at - first_event_at))) as stddev_duration_seconds,
    -- Risk metrics
    AVG(risk_score) as avg_risk_score,
    MAX(risk_score) as max_risk_score
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND first_event_at < '2025-11-01'
GROUP BY DATE(first_event_at)
ORDER BY attack_date DESC;

-- ============================================================================
-- QUERY 9: SSH Key to Session Mapping (CORRECTED)
-- ============================================================================
-- PURPOSE: Track sessions using the same SSH keys (actor clustering)
-- EXPECTED: ~200-1000 rows (SSH key to session mappings)
-- EXECUTION TIME: ~5-10 seconds
-- CSV: results/09_ssh_key_associations.csv
-- ============================================================================

SELECT
    ski.key_fingerprint,
    ski.key_type,
    ski.key_bits,
    ss.session_id,
    ss.first_event_at,
    ss.last_event_at,
    ss.command_count,
    ss.login_attempts,
    ss.vt_flagged,
    ss.dshield_flagged,
    EXTRACT(EPOCH FROM (ss.last_event_at - ss.first_event_at)) as session_duration_seconds,
    ssk.injection_method,
    ssk.successful_injection
FROM session_ssh_keys ssk  -- ✅ Correct junction table
JOIN ssh_key_intelligence ski ON ssk.ssh_key_id = ski.id  -- ✅ Correct join on ID
JOIN session_summaries ss ON ssk.session_id = ss.session_id  -- ✅ Correct join
WHERE ss.first_event_at >= '2024-11-01'
  AND ss.first_event_at < '2025-11-01'
  AND ski.unique_sources >= 3  -- Multi-IP campaigns only
ORDER BY ski.key_fingerprint, ss.first_event_at
LIMIT 1000;

-- ============================================================================
-- NOTES FOR QUERY 9
-- ============================================================================
-- session_ssh_keys is the junction table linking sessions to SSH keys:
--   - session_id → session_summaries.session_id
--   - ssh_key_id → ssh_key_intelligence.id (NOT key_fingerprint!)
--
-- ssh_key_associations is a DIFFERENT table for key co-occurrence tracking:
--   - key_id_1, key_id_2: Which keys appear together
--   - co_occurrence_count: How often they co-occur
--   - This is NOT what we want for session-to-key mapping
-- ============================================================================

-- ============================================================================
-- QUERY 10: Weekly Activity Rollup (Campaign Timeline)
-- ============================================================================
-- PURPOSE: Identify week-long campaign patterns
-- EXPECTED: ~52 rows (weekly aggregates for 1 year)
-- EXECUTION TIME: ~5-10 seconds
-- CSV: results/10_weekly_campaign_patterns.csv
-- ============================================================================

SELECT
    DATE_TRUNC('week', first_event_at) as week_start,
    COUNT(DISTINCT session_id) as session_count,
    SUM(command_count) as total_commands,
    AVG(command_count) as avg_commands_per_session,
    SUM(file_downloads) as total_downloads,
    SUM(login_attempts) as total_login_attempts,
    SUM(ssh_key_injections) as total_ssh_injections,
    -- Calculate week-over-week changes
    SUM(command_count) - LAG(SUM(command_count)) OVER (ORDER BY DATE_TRUNC('week', first_event_at)) as command_count_delta,
    -- Sophistication metrics
    SUM(CASE WHEN vt_flagged THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(*), 0) as vt_flagged_ratio,
    SUM(CASE WHEN dshield_flagged THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(*), 0) as dshield_flagged_ratio,
    AVG(risk_score) as avg_risk_score
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND first_event_at < '2025-11-01'
GROUP BY DATE_TRUNC('week', first_event_at)
ORDER BY week_start DESC;

-- ============================================================================
-- EXECUTION INSTRUCTIONS
-- ============================================================================
-- 1. Create results directory: mkdir -p results/
-- 2. Run each query in PGAdmin
-- 3. Export results to CSV with corresponding filenames
-- 4. Run Python analysis: uv run python scripts/phase1/analyze_feature_importance.py
-- 5. Review report: docs/phase1/feature_discovery_analysis.md
-- ============================================================================

-- ============================================================================
-- NOTES
-- ============================================================================
-- - Date range: 2024-11-01 to 2025-11-01 (1 year of data)
-- - Query 2 (SSH Key Reuse) is the GOLD MINE for persistent actor tracking
-- - Query 6 (Enrichment Analysis) requires PostgreSQL JSON operators (->>, ->)
-- - Some queries use NULLIF to prevent division by zero
-- - All queries have LIMIT clauses to prevent excessive result sets
-- ============================================================================
