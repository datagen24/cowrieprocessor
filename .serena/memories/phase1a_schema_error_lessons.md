# Phase 1A Schema Error - Critical Lessons Learned

## Incident Report: 2025-11-01

### What Happened
User attempted to execute SQL Query 1 from `sql_analysis_queries.sql` and received error:
```
ERROR: column "start_time" does not exist
LINE 2: DATE(start_time) as attack_date,
```

### Root Cause Analysis

**Assumption Made**: Database has denormalized schema with all session data in `session_summaries` table including:
- `start_time` / `end_time` columns
- `src_ip` column
- `commands` array
- `password_hash` column
- `ssh_key_fingerprint` column
- `dshield_data` JSON column

**Reality**: Database uses normalized multi-table schema:
- `SessionSummary`: Aggregated metrics with `first_event_at` / `last_event_at`
- `RawEvent`: Raw JSON payloads with src_ip in payload
- `SSHKeyIntelligence`: Dedicated SSH key tracking
- `PasswordTracking`: Dedicated password tracking
- `CommandStats`: Aggregated command statistics

### Impact
- All 10 SQL queries were incorrect
- Required complete rewrite of queries
- Delayed Phase 1A.1 by ~2 hours
- Cost: User time wasted trying to execute broken queries

### Why This Happened

1. **Did not verify schema**: Wrote queries based on assumptions without checking ORM models
2. **Insufficient context review**: Previous milestone work didn't require deep schema knowledge
3. **Time pressure**: Tried to move fast through Phase 1A without validation

### Prevention Checklist

Before writing ANY SQL queries in the future:

1. ✅ **Check ORM models first**:
   ```python
   from cowrieprocessor.db.models import SessionSummary
   print([col.name for col in SessionSummary.__table__.columns])
   ```

2. ✅ **Review existing queries** in codebase:
   ```bash
   rg "SELECT.*FROM session_summaries" --type py
   ```

3. ✅ **Test query on database** before creating large SQL files:
   ```sql
   SELECT * FROM session_summaries LIMIT 1;
   ```

4. ✅ **Read memory files**:
   - `database_schema_reference` - Complete schema documentation
   - `cowrieprocessor_architecture_patterns` - Query patterns

5. ✅ **Ask user** if uncertain about schema structure

### Corrective Actions Taken

1. ✅ Created `sql_analysis_queries_v2.sql` with corrected queries
2. ✅ Updated `analyze_feature_importance.py` for new CSV filenames
3. ✅ Created comprehensive schema memory (`database_schema_reference`)
4. ✅ Created architecture patterns memory (`cowrieprocessor_architecture_patterns`)
5. ✅ Created mission context memory (`phase1_ttp_profiling_mission`)
6. ✅ Created this lessons learned memory

### Golden Rules for Future Work

#### Rule 1: Schema First
**ALWAYS** verify schema before writing queries. Never assume column names.

```bash
# Quick schema check
uv run python -c "from cowrieprocessor.db.models import SessionSummary; print('\n'.join([f'{c.name}: {c.type}' for c in SessionSummary.__table__.columns]))"
```

#### Rule 2: Memory Files Are Truth
If memory file exists for schema/patterns, READ IT FIRST. Don't rely on assumptions.

```bash
# List available memories
mcp__serena__list_memories

# Read schema memory
mcp__serena__read_memory("database_schema_reference")
```

#### Rule 3: Test Before Scale
Write ONE test query, execute it, verify it works, THEN write 10 queries.

#### Rule 4: Column Name Mapping
Common mistakes to avoid:
- ❌ `start_time` → ✅ `first_event_at`
- ❌ `end_time` → ✅ `last_event_at`
- ❌ `src_ip` → ✅ In `raw_events.payload` JSON
- ❌ `commands` array → ✅ `command_count` integer
- ❌ `password_hash` → ✅ In `password_tracking` table
- ❌ `ssh_key_fingerprint` → ✅ In `ssh_key_intelligence` table

#### Rule 5: Verify Expected Tables
Before querying specialized tables, verify they exist:
```sql
SELECT table_name 
FROM information_schema.tables 
WHERE table_name IN ('ssh_key_intelligence', 'password_tracking', 'command_stats');
```

### Schema Verification Commands

**Python verification**:
```python
# Check all tables
from cowrieprocessor.db import models
print([c for c in dir(models) if c[0].isupper()])

# Check specific table columns
from cowrieprocessor.db.models import SessionSummary
for col in SessionSummary.__table__.columns:
    print(f"{col.name}: {col.type}")
```

**SQL verification**:
```sql
-- List all columns in session_summaries
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'session_summaries'
ORDER BY ordinal_position;

-- Check if table exists
SELECT EXISTS (
    SELECT FROM information_schema.tables 
    WHERE table_name = 'ssh_key_intelligence'
);
```

### Cost-Benefit Analysis

**Time Lost**: 2 hours
- Writing incorrect queries: 1h
- User encountering error: 5m
- Investigating issue: 15m
- Rewriting queries: 30m
- Creating memories: 15m

**Time Saved in Future**: 10+ hours
- Prevented similar errors in Phase 1B: 2h
- Prevented errors in Phase 1C: 2h
- Prevented errors in Phase 2-6: 6h+

**ROI**: 5x+ return on time invested in memories

### Red Flags to Watch For

When writing queries, these are danger signs:

🚩 **Using column names without verifying**: STOP, check schema first
🚩 **Assuming denormalized structure**: CowrieProcessor is normalized
🚩 **Writing 10+ queries without testing one**: Test first query first
🚩 **Ignoring "column does not exist" errors**: Don't guess, verify
🚩 **Not reading memories before starting**: Memories exist for a reason

### Success Criteria for Future Queries

Before considering SQL queries "ready to execute":

✅ All column names verified in ORM models
✅ At least one query tested on actual database
✅ Foreign key relationships understood
✅ JSON extraction syntax validated (PostgreSQL vs SQLite)
✅ Expected result row counts documented
✅ CSV export filenames specified

### Phase-Specific Application

**Phase 1B (MITRE Mapper)**:
- Will need to query `RawEvent.payload` JSON for command extraction
- Must verify payload structure before writing extraction logic
- Test on 1 session before processing thousands

**Phase 1C (Random Forest)**:
- Will need to join multiple tables
- Must verify join columns exist and have correct types
- Test feature extraction on sample data first

**Phase 2+ (Production)**:
- Schema may evolve with migrations
- Always check current schema version
- Test queries after schema migrations

### Memory Refresh Schedule

These memory files should be reviewed:

**Before every SQL query writing session**:
- `database_schema_reference` - Complete schema
- `phase1_ttp_profiling_mission` - Mission context

**Before architecture decisions**:
- `cowrieprocessor_architecture_patterns` - Code patterns

**Monthly review**:
- Verify schema hasn't changed (new migrations)
- Update memories if schema evolves
- Archive outdated information

### Final Takeaway

**The 2-minute rule**: Spend 2 minutes verifying schema before writing queries, save 2 hours debugging incorrect queries.

> "Slow is smooth, smooth is fast" - Check schema first, move faster overall.

---

**Incident Date**: 2025-11-01
**Status**: Resolved
**Prevention**: Memories created, checklist established
**Cost**: 2 hours lost, 10+ hours saved in future
**Key Learning**: Always verify schema before writing queries
