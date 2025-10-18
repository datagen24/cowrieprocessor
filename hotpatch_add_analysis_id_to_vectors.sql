-- Hot Patch: Add analysis_id column to vector tables
-- This script adds the missing analysis_id column to the command_sequence_vectors table
-- Run this on existing databases to fix the schema before running migrations

-- ============================================================================
-- POSTGRESQL PATCH
-- ============================================================================

-- Add analysis_id column to command_sequence_vectors
ALTER TABLE command_sequence_vectors 
ADD COLUMN IF NOT EXISTS analysis_id INTEGER REFERENCES longtail_analysis(id) ON DELETE CASCADE;

-- Create index for analysis_id lookups
CREATE INDEX IF NOT EXISTS ix_command_sequence_vectors_analysis 
ON command_sequence_vectors(analysis_id);

-- Add analysis_id column to behavioral_vectors
ALTER TABLE behavioral_vectors 
ADD COLUMN IF NOT EXISTS analysis_id INTEGER REFERENCES longtail_analysis(id) ON DELETE CASCADE;

-- Create index for analysis_id lookups
CREATE INDEX IF NOT EXISTS ix_behavioral_vectors_analysis 
ON behavioral_vectors(analysis_id);

-- ============================================================================
-- VERIFICATION
-- ============================================================================

-- Verify the columns were added
SELECT 
    'command_sequence_vectors' as table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'command_sequence_vectors' 
  AND column_name = 'analysis_id';

SELECT 
    'behavioral_vectors' as table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'behavioral_vectors' 
  AND column_name = 'analysis_id';

-- Show indexes
SELECT 
    tablename,
    indexname,
    indexdef
FROM pg_indexes 
WHERE tablename IN ('command_sequence_vectors', 'behavioral_vectors')
  AND indexname LIKE '%analysis%';

-- ============================================================================
-- NOTES
-- ============================================================================
-- After running this hot patch:
-- 1. Existing vector records will have NULL analysis_id (acceptable)
-- 2. New vector records will properly link to their analysis
-- 3. The schema will match the v14 migration
-- 4. Run migrations to update schema_version to 14
-- ============================================================================





