# Migration Type Mismatch Debugging - ADR-007 (Nov 2025)

## Critical Learning: ORM-Migration Type Alignment

### Root Cause (12 Iterations to Discover)
**Problem**: Migration created `ip_inventory.ip_address` as **INET** type, but ORM models defined it as **String(45)** (VARCHAR).

**Impact**: PostgreSQL cannot create foreign keys between incompatible types (VARCHAR ≠ INET), causing constraint failures regardless of query-level casting.

### Why It Was Hard to Find
1. **Symptom Fixing**: First 10 commits fixed casting errors in queries, not the underlying type mismatch
2. **Split Information**: Type definition in migration SQL, ORM models in separate file
3. **Deferred Validation**: FK constraint creation happens late in migration (Phase 5)
4. **Error Message Misleading**: "operator does not exist: inet = character varying" suggests query fix, not schema fix

### The Winning Fix (Commit f7f2b68)
```python
# BEFORE (broken):
CREATE TABLE ip_inventory (
    ip_address INET PRIMARY KEY,  # ❌ Doesn't match ORM
    ...
)

# AFTER (fixed):
CREATE TABLE ip_inventory (
    ip_address VARCHAR(45) PRIMARY KEY,  # ✅ Matches ORM models
    ...
)
```

## Validation Checklist for Future Migrations

### Before Writing Migration Code
1. **Read ORM Models First**: Check `cowrieprocessor/db/models.py` for actual column types
2. **Match Types Exactly**: Migration SQL types must match SQLAlchemy Column types:
   - `Column(String(45))` → `VARCHAR(45)` (NOT INET, NOT TEXT)
   - `Column(Integer)` → `INTEGER` (NOT INT, NOT BIGINT unless specified)
   - `Column(JSON)` → `JSON` (NOT JSONB unless model specifies)
3. **Cross-Database Check**: Verify types work in both SQLite (dev) and PostgreSQL (prod)
4. **FK Compatibility**: Ensure foreign key columns have identical types (no casting allowed)

### During Migration Development
1. **Type Consistency Audit**: Search for all references to new columns, verify type consistency
2. **No Type Casts in Schema DDL**: If you need `::inet` or `::integer` casts, types are wrong
3. **Test FK Creation Early**: Don't wait until Phase 5 to discover type mismatches
4. **Package Rebuild**: Always run `uv sync` after migration code changes before testing

### PostgreSQL Type System Constraints
1. **Foreign Keys Require Exact Type Match**: VARCHAR(45) can only reference VARCHAR(45)
2. **INET vs VARCHAR**: INET is PostgreSQL-specific network type, not compatible with VARCHAR
3. **JSON vs JSONB**: Different types with different function sets (`jsonb_typeof()` only works with JSONB)
4. **No Implicit Casting**: Even compatible types (TEXT vs VARCHAR) may require explicit casts

## Migration Commits History (ADR-007)
1. `5e37ed8` - Phase ordering (source_ip before usage)
2. `0d8ec9e` - Table name fix (schema_state not schema_metadata)
3. `8bf3a02` - Auto-heal incomplete tables
4. `971bf5e` - GENERATED column subquery limitation
5. `26f80f0` - ❌ Symptom fix: VARCHAR→INET cast in INSERT
6. `6fab83d` - Nullable source_ip
7. `d804e67` - ❌ Symptom fix: JSON vs JSONB function mismatch
8. `ae6f02b` - ❌ Symptom fix: FK validation query cast + mypy
9. `f7f2b68` - ✅ **ROOT CAUSE FIX**: VARCHAR type consistency

**Pattern Recognition**: Commits 5, 7, 8 were all symptom fixes adding type casts. Commit 9 fixed the root cause by aligning schema types with ORM models.

## Prevention Strategy

### Pre-Migration Code Review Checklist
```bash
# 1. Extract column types from ORM models
grep -A 2 "class IPInventory\|class SessionSummary" cowrieprocessor/db/models.py

# 2. Compare with migration CREATE TABLE statements
grep -A 20 "CREATE TABLE ip_inventory\|CREATE TABLE asn_inventory" cowrieprocessor/db/migrations.py

# 3. Check for type casts in migration (red flag)
grep "::inet\|::integer\|::jsonb" cowrieprocessor/db/migrations.py

# 4. Validate FK column types match
grep "ForeignKey\|FOREIGN KEY" cowrieprocessor/db/models.py cowrieprocessor/db/migrations.py
```

### Migration Testing Protocol
1. **Unit Tests**: Test migration on empty database (fast iteration)
2. **Type Validation**: Query information_schema to verify created column types
3. **FK Creation Test**: Isolate FK constraint creation, test independently
4. **Cross-Database**: Test on both SQLite and PostgreSQL before committing

## Command Reference

### Check Actual Column Types in PostgreSQL
```sql
SELECT column_name, data_type, character_maximum_length
FROM information_schema.columns
WHERE table_name IN ('session_summaries', 'ip_inventory', 'asn_inventory')
ORDER BY table_name, ordinal_position;
```

### Verify Foreign Key Types Match
```sql
SELECT 
    tc.constraint_name,
    tc.table_name,
    kcu.column_name,
    ccu.table_name AS foreign_table_name,
    ccu.column_name AS foreign_column_name,
    c1.data_type as local_type,
    c2.data_type as foreign_type
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
  ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage AS ccu
  ON ccu.constraint_name = tc.constraint_name
JOIN information_schema.columns c1
  ON c1.table_name = tc.table_name AND c1.column_name = kcu.column_name
JOIN information_schema.columns c2
  ON c2.table_name = ccu.table_name AND c2.column_name = ccu.column_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_name = 'session_summaries';
```

## Time Cost
- **Total Iterations**: 12 attempts over ~4 hours
- **Commits**: 11 (9 symptom fixes, 1 root cause fix, 1 mypy fix)
- **Lesson**: Validate ORM-migration alignment BEFORE writing migration logic (saves hours)
