-- IMMEDIATE FIX: Direct PostgreSQL sanitization (bypasses slow Python loop)
-- Estimated time: 5-10 seconds for ~1,267 problematic records
-- Run this in psql or your PostgreSQL client

-- ============================================================================
-- STEP 1: CHECK CURRENT STATE
-- ============================================================================

-- Count problematic records
SELECT COUNT(*) as problematic_records
FROM raw_events
WHERE payload::text ~ '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]';
-- Expected output: ~1,267

-- Sample problematic records
SELECT
    id,
    sensor,
    LEFT(payload::text, 100) as payload_sample
FROM raw_events
WHERE payload::text ~ '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]'
LIMIT 5;


-- ============================================================================
-- STEP 2: BACKUP PROBLEMATIC RECORDS (RECOMMENDED!)
-- ============================================================================

-- Create backup table
CREATE TABLE IF NOT EXISTS raw_events_unicode_backup AS
SELECT * FROM raw_events WHERE 1=0;  -- Empty table with same schema

-- Backup problematic records before fixing
INSERT INTO raw_events_unicode_backup
SELECT * FROM raw_events
WHERE payload::text ~ '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]';

-- Verify backup
SELECT COUNT(*) FROM raw_events_unicode_backup;
-- Should match problematic_records count above


-- ============================================================================
-- STEP 3: FIX USING POSTGRESQL REGEX REPLACE
-- ============================================================================

-- Option A: Remove specific control characters one by one
-- (More precise, shows exactly what's being fixed)

BEGIN;

-- Fix \u0000 (null byte)
UPDATE raw_events
SET payload = CAST(
    regexp_replace(payload::text, '\\u0000', '', 'g')
AS jsonb)
WHERE payload::text ~ '\\u0000';

-- Fix \u0001 (SOH - Start of Heading)
UPDATE raw_events
SET payload = CAST(
    regexp_replace(payload::text, '\\u0001', '', 'g')
AS jsonb)
WHERE payload::text ~ '\\u0001';

-- Fix \u0002 (STX - Start of Text)
UPDATE raw_events
SET payload = CAST(
    regexp_replace(payload::text, '\\u0002', '', 'g')
AS jsonb)
WHERE payload::text ~ '\\u0002';

-- Add more as needed based on what you find in your data...

COMMIT;


-- Option B: Remove ALL problematic control characters at once
-- (Faster, but less precise - removes all matching patterns)

BEGIN;

-- Single UPDATE with comprehensive regex
UPDATE raw_events
SET payload = CAST(
    regexp_replace(
        payload::text,
        '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]',
        '',
        'g'
    )
AS jsonb)
WHERE payload::text ~ '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]';

COMMIT;


-- ============================================================================
-- STEP 4: VERIFY FIX
-- ============================================================================

-- Should return 0 if successful
SELECT COUNT(*) as remaining_problematic
FROM raw_events
WHERE payload::text ~ '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]';

-- Compare before/after for a few records
SELECT
    'BEFORE' as status,
    id,
    LEFT(payload::text, 100) as payload_sample
FROM raw_events_unicode_backup
LIMIT 5

UNION ALL

SELECT
    'AFTER' as status,
    id,
    LEFT(payload::text, 100) as payload_sample
FROM raw_events
WHERE id IN (SELECT id FROM raw_events_unicode_backup LIMIT 5);


-- ============================================================================
-- STEP 5: CLEANUP (OPTIONAL)
-- ============================================================================

-- If everything looks good, you can drop the backup table
-- DROP TABLE raw_events_unicode_backup;

-- Or keep it for a while for safety
-- (PostgreSQL will automatically VACUUM the space eventually)


-- ============================================================================
-- PERFORMANCE NOTES
-- ============================================================================

-- This direct SQL approach:
-- ✅ Bypasses slow Python OFFSET pagination
-- ✅ Only processes ~1,267 problematic records (0.01% of table)
-- ✅ Uses PostgreSQL's native regex engine (highly optimized)
-- ✅ Completes in 5-10 seconds instead of 20+ hours
--
-- The Python implementation was:
-- ❌ Processing ALL 12.4M records with OFFSET
-- ❌ OFFSET gets slower with each batch (O(n) complexity)
-- ❌ Individual UPDATE statements (1,267 separate transactions)
