# ADR-007 Schema State Table Fix

**Date**: 2025-11-05
**Branch**: feature/adr-007-three-tier-enrichment
**Commit**: 0d8ec9e

## Cleanup Script Table Name Error

### Problem

User ran cleanup script which failed with:
```
psql:cleanup_v16_incomplete.sql:59: ERROR: column "key" does not exist
LINE 1: UPDATE schema_metadata SET value = '15' WHERE key = 'schema_...
ROLLBACK
```

**Root Cause**: 
- Cleanup script used wrong table name: `schema_metadata`
- Actual table used by migrations: `schema_state`

**Database Schema**:
```python
# models.py shows TWO tables:

class SchemaState(Base):
    """Key/value metadata for schema versions"""
    __tablename__ = "schema_state"
    key = Column(String(128), primary_key=True)
    value = Column(String(256), nullable=False)

class SchemaMetadata(Base):
    """Track schema version and features"""  
    __tablename__ = "schema_metadata"
    id = Column(Integer, primary_key=True)
    version = Column(Integer, nullable=False)
    database_type = Column(String(16), nullable=False)
    features = Column(JSON, nullable=False)
```

**Migrations use SchemaState** (confirmed in migrations.py):
```python
from .models import SchemaState

SCHEMA_VERSION_KEY = "schema_version"

def _get_schema_version(connection):
    select(SchemaState.value).where(SchemaState.key == SCHEMA_VERSION_KEY)

def _set_schema_version(connection, version):
    update(SchemaState).where(SchemaState.key == SCHEMA_VERSION_KEY)
```

### Fix Applied (Commit 0d8ec9e)

**Files Updated**:

1. **scripts/migrations/cleanup_v16_incomplete.sql**
   - Changed `schema_metadata` → `schema_state` (2 places)
   - Added clarifying comment

2. **claudedocs/ADR-007-MIGRATION-RECOVERY.md**
   - Added single-line manual cleanup command as fallback
   - Updated all references to use `schema_state` table
   - Added "(uses schema_state table)" comments throughout

### Corrected Commands

**Option 1: Fixed cleanup script**
```bash
psql -h hostname -U username -d database -f scripts/migrations/cleanup_v16_incomplete.sql
```

**Option 2: Single-line manual cleanup (fallback)**
```bash
psql -h hostname -U username -d database -c "
DROP TABLE IF EXISTS ip_asn_history CASCADE;
DROP TABLE IF EXISTS ip_inventory CASCADE;
DROP TABLE IF EXISTS asn_inventory CASCADE;
ALTER TABLE session_summaries DROP COLUMN IF EXISTS source_ip CASCADE;
UPDATE schema_state SET value = '15' WHERE key = 'schema_version';
SELECT 'Cleanup complete. Schema version: ' || value FROM schema_state WHERE key = 'schema_version';
"
```

**Then re-run migration**:
```bash
uv run cowrie-db migrate
```

## Verification Commands

```bash
# Check schema version (should show 15 after cleanup, 16 after migration)
psql -h hostname -U username -d database -c \
  "SELECT key, value FROM schema_state WHERE key = 'schema_version'"

# Check tables dropped (should be empty after cleanup)
psql -h hostname -U username -d database -c \
  "\dt asn_inventory ip_inventory ip_asn_history"
```

## Current Status

✅ **Fixed**: Cleanup script now uses correct table name
⏳ **Pending**: User needs to run corrected cleanup
⏳ **Pending**: Re-run migration after cleanup

## Why This Happened

**Documentation confusion**: Two similar table names exist in models.py:
- `schema_state` - Actually used by migrations (key/value store)
- `schema_metadata` - Different structure (id/version/database_type/features)

The cleanup script author used the wrong table name from the models file.

**Prevention**: Added comments to cleanup script and recovery guide clarifying which table is used.
