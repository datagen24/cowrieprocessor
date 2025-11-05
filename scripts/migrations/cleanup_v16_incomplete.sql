-- Cleanup script for incomplete ADR-007 v16 migration
-- Run this if migration failed partway through and left incomplete tables
--
-- Usage:
--   psql $DATABASE_URL -f scripts/migrations/cleanup_v16_incomplete.sql
--
-- What this does:
--   1. Drops ip_asn_history table (if exists)
--   2. Drops ip_inventory table (if exists) - may have incomplete GENERATED columns
--   3. Drops asn_inventory table (if exists) - may have incomplete schema
--   4. Removes source_ip column from session_summaries (will be re-added in Phase 1)
--   5. Resets schema version to v15 so migration can run fresh
--
-- After running this, execute: uv run cowrie-db migrate

BEGIN;

-- Drop tables in reverse dependency order
DROP TABLE IF EXISTS ip_asn_history CASCADE;
DROP TABLE IF EXISTS ip_inventory CASCADE;
DROP TABLE IF EXISTS asn_inventory CASCADE;

-- Remove source_ip column if it was added
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'session_summaries' AND column_name = 'source_ip'
    ) THEN
        ALTER TABLE session_summaries DROP COLUMN source_ip;
        RAISE NOTICE 'Dropped source_ip column from session_summaries';
    END IF;
END $$;

-- Remove snapshot columns if they were added
DO $$
DECLARE
    col TEXT;
BEGIN
    FOR col IN
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'session_summaries'
          AND column_name IN ('enrichment_at', 'snapshot_asn', 'snapshot_country', 'snapshot_ip_types')
    LOOP
        EXECUTE format('ALTER TABLE session_summaries DROP COLUMN %I', col);
        RAISE NOTICE 'Dropped snapshot column: %', col;
    END LOOP;
END $$;

-- Remove indexes that may have been created
DROP INDEX IF EXISTS idx_session_source_ip;
DROP INDEX IF EXISTS idx_session_first_event_brin;
DROP INDEX IF EXISTS idx_session_last_event_brin;
DROP INDEX IF EXISTS idx_session_snapshot_asn;
DROP INDEX IF EXISTS idx_session_snapshot_country;

-- Reset schema version to v15 (pre-ADR-007)
-- Note: Uses schema_state table (not schema_metadata)
UPDATE schema_state SET value = '15' WHERE key = 'schema_version';

COMMIT;

-- Verify cleanup
SELECT 'Cleanup complete. Current schema version: ' || value as status
FROM schema_state WHERE key = 'schema_version';
