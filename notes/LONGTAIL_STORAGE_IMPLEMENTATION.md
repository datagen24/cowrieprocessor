# Longtail Storage Implementation - Complete

## Summary

Successfully implemented comprehensive database storage for longtail threat analysis results. The system now properly persists:

- **Analysis metadata** (window, metrics, performance stats)
- **Individual detections** (rare commands, outlier sessions, etc.)
- **Session linking** (Many-to-Many relationships via junction table)
- **Command vectors** (TF-IDF vectors for similarity analysis)
- **Analysis checkpoints** (for incremental analysis optimization)

## What Was Fixed

### 1. JSON Serialization Issues ✅
**Problem**: `datetime` and `numpy.int64` objects couldn't be serialized to JSON  
**Solution**: Added `_serialize_for_json()` helper that handles:
- `datetime` objects → ISO format strings
- `numpy` scalars (`int64`, `float64`) → Python native types
- Recursive serialization for nested dicts/lists

### 2. Vector Table Schema ✅
**Problem**: `command_sequence_vectors` table missing `analysis_id` column  
**Solution**: 
- Created v14 migration to add `analysis_id` column
- Added foreign key constraint to `longtail_analysis(id)`
- Created indexes for query performance
- Provided hot patch SQL script for existing databases

### 3. Storage Architecture ✅
**Problem**: Persistence logic isolated in CLI, not reusable  
**Solution**:
- Created `cowrieprocessor/threat_detection/storage.py` module
- Centralized storage logic for all entry points
- Proper session linking via `longtail_detection_sessions` junction table
- Runtime pgvector detection for PostgreSQL

### 4. Database Schema ✅
**Problem**: Missing junction table and checkpoint tracking  
**Solution**:
- Added `longtail_detection_sessions` junction table (v13)
- Added `longtail_analysis_checkpoints` table (v13)
- Added `analysis_id` to vector tables (v14)
- Proper indexes for all tables

## Files Modified

### New Files
1. `cowrieprocessor/threat_detection/storage.py` - Storage layer
2. `tests/integration/test_longtail_storage.py` - Integration tests
3. `hotpatch_add_analysis_id_to_vectors.sql` - Hot patch SQL
4. `HOTPATCH_README.md` - Hot patch documentation

### Modified Files
1. `cowrieprocessor/db/migrations.py`:
   - Schema version: 12 → 14
   - Added `_upgrade_to_v13()` - Junction table and checkpoints
   - Added `_upgrade_to_v14()` - Vector table analysis_id
   
2. `cowrieprocessor/db/models.py`:
   - Added `LongtailDetectionSession` ORM model
   - Added `LongtailAnalysisCheckpoint` ORM model
   
3. `cowrieprocessor/threat_detection/longtail.py`:
   - Updated `run_longtail_analysis()` to call storage layer
   
4. `cowrieprocessor/cli/analyze.py`:
   - Removed old `_store_longtail_result()` function
   - Updated to use new storage module
   
5. `process_cowrie.py`:
   - Fixed `store_results` flag handling
   - Defaults to `store_results=True` for automation

6. `tests/unit/test_ssh_key_extractor.py`:
   - Added `# noqa: E501` to long SSH key strings

## Database Schema Changes

### Schema Version Timeline
- **v12**: Initial longtail tables
- **v13**: Junction table + checkpoints (NEW)
- **v14**: Vector table analysis_id (NEW)

### New Tables (v13)

#### `longtail_detection_sessions`
Many-to-Many junction table linking detections to sessions:
```sql
CREATE TABLE longtail_detection_sessions (
    detection_id INTEGER NOT NULL REFERENCES longtail_detections(id) ON DELETE CASCADE,
    session_id VARCHAR(64) NOT NULL REFERENCES session_summaries(session_id) ON DELETE CASCADE,
    PRIMARY KEY (detection_id, session_id)
);
CREATE INDEX ix_longtail_detection_sessions_detection ON longtail_detection_sessions(detection_id);
CREATE INDEX ix_longtail_detection_sessions_session ON longtail_detection_sessions(session_id);
```

#### `longtail_analysis_checkpoints`
Tracks analysis runs for incremental processing:
```sql
CREATE TABLE longtail_analysis_checkpoints (
    id INTEGER PRIMARY KEY,
    checkpoint_date DATE NOT NULL UNIQUE,
    window_start TIMESTAMP NOT NULL,
    window_end TIMESTAMP NOT NULL,
    sessions_analyzed INTEGER NOT NULL,
    vocabulary_hash VARCHAR(64) NOT NULL,
    last_analysis_id INTEGER REFERENCES longtail_analysis(id),
    completed_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_longtail_checkpoints_date ON longtail_analysis_checkpoints(checkpoint_date);
CREATE INDEX ix_longtail_checkpoints_window ON longtail_analysis_checkpoints(window_start, window_end);
```

### Modified Tables (v14)

#### `command_sequence_vectors` (PostgreSQL + pgvector only)
Added `analysis_id` column:
```sql
ALTER TABLE command_sequence_vectors 
ADD COLUMN analysis_id INTEGER REFERENCES longtail_analysis(id) ON DELETE CASCADE;
CREATE INDEX ix_command_sequence_vectors_analysis ON command_sequence_vectors(analysis_id);
```

#### `behavioral_vectors` (PostgreSQL + pgvector only)
Added `analysis_id` column:
```sql
ALTER TABLE behavioral_vectors 
ADD COLUMN analysis_id INTEGER REFERENCES longtail_analysis(id) ON DELETE CASCADE;
CREATE INDEX ix_behavioral_vectors_analysis ON behavioral_vectors(analysis_id);
```

## Usage

### CLI (Primary Method)
```bash
# Run longtail analysis with storage
uv run cowrie-analyze longtail --lookback-days 7 --store-results

# Run without storage
uv run cowrie-analyze longtail --lookback-days 7
```

### Automation (Legacy)
```bash
# Enable longtail analysis in automation
export RUN_LONGTAIL_ANALYSIS=true
export LONGTAIL_STORE_RESULTS=true  # Default
python process_cowrie.py
```

### Programmatic
```python
from cowrieprocessor.threat_detection.longtail import run_longtail_analysis

result = run_longtail_analysis(
    db_url="postgresql://...",
    lookback_days=7,
    store_results=True,  # Persist to database
)
```

## Verification

### Check Stored Data
```sql
-- Count analyses
SELECT COUNT(*) FROM longtail_analysis;

-- Count detections
SELECT COUNT(*) FROM longtail_detections;

-- Count detection-session links
SELECT COUNT(*) FROM longtail_detection_sessions;

-- Latest analysis with metrics
SELECT 
    id,
    window_start,
    window_end,
    rare_command_count,
    outlier_session_count,
    confidence_score
FROM longtail_analysis
ORDER BY id DESC
LIMIT 1;

-- Detections with session links
SELECT 
    ld.id,
    ld.detection_type,
    ld.detection_data->>'command' as command,
    COUNT(lds.session_id) as session_count
FROM longtail_detections ld
LEFT JOIN longtail_detection_sessions lds ON ld.id = lds.detection_id
GROUP BY ld.id, ld.detection_type, command
ORDER BY session_count DESC
LIMIT 10;

-- Vectors with analysis links (PostgreSQL only)
SELECT 
    COUNT(*) as vector_count,
    COUNT(DISTINCT analysis_id) as unique_analyses
FROM command_sequence_vectors
WHERE analysis_id IS NOT NULL;
```

## Hot Patch Instructions

### For Existing Databases

If you have an existing database with vector tables but missing `analysis_id`:

1. **Apply Hot Patch SQL**:
   ```bash
   psql "postgresql://user:pass@host:port/dbname" -f hotpatch_add_analysis_id_to_vectors.sql
   ```

2. **OR Run Migrations**:
   ```bash
   uv run cowrie-db migrate
   ```

The migration will:
- Detect if vector tables exist
- Check if `analysis_id` already exists
- Add column + indexes if missing
- Skip gracefully if already applied

See `HOTPATCH_README.md` for detailed instructions.

## Testing

### Run Integration Tests
```bash
# All longtail storage tests
uv run pytest tests/integration/test_longtail_storage.py -v

# Specific test
uv run pytest tests/integration/test_longtail_storage.py::test_store_longtail_analysis_success -v
```

### Manual Verification
```bash
# Run analysis
uv run cowrie-analyze longtail --lookback-days 7 --store-results

# Check database
uv run python -c "
from sqlalchemy import create_engine, text
from process_cowrie import get_database_url
engine = create_engine(get_database_url())
with engine.connect() as conn:
    result = conn.execute(text('SELECT COUNT(*) FROM longtail_analysis'))
    print(f'Analyses stored: {result.scalar()}')
"
```

## Success Criteria

All success criteria have been met:

- ✅ Running `cowrie-analyze longtail --store-results` persists results to database
- ✅ `longtail_analysis` table contains analysis records with proper metrics
- ✅ `longtail_detections` table contains individual detections
- ✅ `longtail_detection_sessions` junction table links detections to sessions
- ✅ Can query: "Which sessions had rare command X?" via SQL joins
- ✅ Vector tables populated when using PostgreSQL + pgvector
- ✅ SQLite deployments work without pgvector (graceful degradation)
- ✅ CLI `cowrie-analyze longtail --store-results` works correctly
- ✅ Integration tests verify all storage paths
- ✅ No JSON serialization errors
- ✅ Proper session linking via junction table
- ✅ Vector tables have `analysis_id` for proper linking

## Performance Optimizations

### Incremental Analysis
The `longtail_analysis_checkpoints` table enables:
- Track which time windows have been analyzed
- Skip reprocessing of old sessions
- Detect when vocabulary changes require reanalysis
- Dramatically reduces memory usage for repeated runs

### Query Performance
All junction tables and foreign keys are properly indexed:
- `ix_longtail_detection_sessions_detection`
- `ix_longtail_detection_sessions_session`
- `ix_longtail_checkpoints_date`
- `ix_longtail_checkpoints_window`
- `ix_command_sequence_vectors_analysis`
- `ix_behavioral_vectors_analysis`

## Security Considerations

- ✅ No secrets in logs (all connection strings masked)
- ✅ Parameterized SQL queries (no injection risk)
- ✅ Proper error handling (storage failures don't crash analysis)
- ✅ Foreign key constraints (cascading deletes prevent orphans)
- ✅ JSON serialization sanitizes all data types

## Architecture Benefits

1. **Separation of Concerns**: Storage logic separated from analysis logic
2. **Reusability**: Same storage layer used by CLI and automation
3. **Modularity**: Easy to extend with new detection types
4. **Type Safety**: Full type hints throughout
5. **Testing**: Comprehensive integration tests
6. **Performance**: Optimized with indexes and checkpoints
7. **Flexibility**: Works with both PostgreSQL and SQLite

## Next Steps (Future Enhancements)

1. **Query API**: Add helper functions to query stored analyses
2. **Comparison**: Compare analyses across time windows
3. **Alerting**: Trigger alerts for high-severity detections
4. **Visualization**: Generate charts from stored metrics
5. **Export**: Export analyses in various formats
6. **Cleanup**: Automatic cleanup of old analyses

## Contact

For issues or questions:
- Check `cowrieprocessor/threat_detection/storage.py` for storage logic
- Check `cowrieprocessor/db/migrations.py` for schema definitions
- Check `tests/integration/test_longtail_storage.py` for usage examples





