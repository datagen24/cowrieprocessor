-- Investigation: Why are 1267 records still problematic?

-- 1. Confirm total count of problematic records
SELECT COUNT(*) as problematic_count
FROM raw_events
WHERE payload::text ~ '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]';

-- 2. Check ID ranges of problematic records (are they new records added after sanitization?)
SELECT 
    MIN(id) as min_id,
    MAX(id) as max_id,
    COUNT(*) as count
FROM raw_events
WHERE payload::text ~ '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]';

-- 3. Sample problematic records to see patterns
SELECT 
    id, 
    sensor,
    eventid,
    created_at,
    updated_at,
    LEFT(payload::text, 100) as payload_sample
FROM raw_events
WHERE payload::text ~ '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]'
ORDER BY id
LIMIT 10;

-- 4. Check total raw_events count (did database grow after sanitization?)
SELECT COUNT(*) as total_records FROM raw_events;

-- 5. Check when problematic records were last updated
SELECT 
    DATE_TRUNC('hour', updated_at) as update_hour,
    COUNT(*) as count
FROM raw_events
WHERE payload::text ~ '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]'
GROUP BY update_hour
ORDER BY update_hour DESC
LIMIT 20;

-- 6. Check specific escape sequences present
SELECT 
    SUBSTRING(payload::text FROM '\\u00[0-9a-fA-F]{2}') as escape_seq,
    COUNT(*) as count
FROM raw_events
WHERE payload::text ~ '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]'
GROUP BY escape_seq
ORDER BY count DESC;
