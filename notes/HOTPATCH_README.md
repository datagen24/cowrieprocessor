# Hot Patch: Add analysis_id to Vector Tables

## Problem

The `command_sequence_vectors` and `behavioral_vectors` tables were missing the `analysis_id` column, which is required to link vector records to their corresponding longtail analysis runs.

## Solution

This hot patch adds the missing `analysis_id` column to both vector tables and creates appropriate indexes.

## Prerequisites

- PostgreSQL database with pgvector extension
- Vector tables already exist (`command_sequence_vectors`, `behavioral_vectors`)
- `longtail_analysis` table exists
- Database connection with ALTER TABLE privileges

## Apply Hot Patch

### Option 1: Direct SQL Execution

```bash
# Connect to your database and run the hot patch script
psql "postgresql://user:pass@host:port/dbname" -f hotpatch_add_analysis_id_to_vectors.sql
```

### Option 2: Run Migrations (Automatic)

The migration system will automatically apply the v14 migration when you run:

```bash
uv run cowrie-db upgrade
```

The migration will:
1. Detect if vector tables exist
2. Check if `analysis_id` column already exists
3. Add the column if missing
4. Create indexes for performance
5. Update schema version to 14

## Verification

After applying the hot patch, verify the schema:

```sql
-- Check command_sequence_vectors schema
\d command_sequence_vectors

-- Expected output should include:
-- analysis_id | integer | references longtail_analysis(id)

-- Check behavioral_vectors schema
\d behavioral_vectors

-- Expected output should include:
-- analysis_id | integer | references longtail_analysis(id)

-- Verify indexes exist
SELECT tablename, indexname 
FROM pg_indexes 
WHERE tablename IN ('command_sequence_vectors', 'behavioral_vectors')
  AND indexname LIKE '%analysis%';

-- Expected output:
-- command_sequence_vectors | ix_command_sequence_vectors_analysis
-- behavioral_vectors | ix_behavioral_vectors_analysis
```

## Post-Patch Behavior

### Existing Records
- Existing vector records will have `NULL` for `analysis_id`
- This is acceptable and won't cause issues
- Old vectors remain queryable

### New Records
- New vector records will properly link to their analysis via `analysis_id`
- Enables queries like: "Show all vectors from analysis run #5"
- Enables cascading deletes when an analysis is removed

## Test Vector Storage

After applying the hot patch, test that vector storage works:

```bash
# Run longtail analysis with vector storage
uv run cowrie-analyze longtail --lookback-days 7 --store-results

# Verify vectors were stored
psql "postgresql://..." -c "
SELECT 
    csv.id,
    csv.analysis_id,
    la.window_start,
    la.window_end
FROM command_sequence_vectors csv
JOIN longtail_analysis la ON csv.analysis_id = la.id
ORDER BY csv.id DESC
LIMIT 5;
"
```

## Rollback (If Needed)

If you need to rollback the hot patch:

```sql
-- Remove analysis_id column from command_sequence_vectors
ALTER TABLE command_sequence_vectors DROP COLUMN IF EXISTS analysis_id CASCADE;

-- Remove analysis_id column from behavioral_vectors
ALTER TABLE behavioral_vectors DROP COLUMN IF EXISTS analysis_id CASCADE;

-- Update schema version back to 13
UPDATE schema_metadata SET value = '13' WHERE key = 'schema_version';
```

## Migration Details

- **Migration Version**: v14
- **Schema Version**: 13 → 14
- **Tables Modified**:
  - `command_sequence_vectors` (added `analysis_id` column + index)
  - `behavioral_vectors` (added `analysis_id` column + index)
- **Backward Compatible**: Yes (existing vectors have NULL analysis_id)
- **Forward Compatible**: Yes (new code expects analysis_id column)

## Troubleshooting

### Error: "column already exists"
This means the hot patch was already applied or the migration ran successfully. No action needed.

### Error: "table does not exist"
Vector tables only exist on PostgreSQL databases with pgvector extension. This is expected for:
- SQLite databases (no pgvector support)
- PostgreSQL databases without pgvector installed
- Fresh databases that haven't run longtail analysis yet

### Error: "permission denied"
You need ALTER TABLE privileges to run this hot patch. Connect as database owner or superuser.

## Contact

For issues or questions about this hot patch, refer to the migration code in:
- `cowrieprocessor/db/migrations.py` (function `_upgrade_to_v14`)





