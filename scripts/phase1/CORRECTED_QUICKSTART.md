# Phase 1A.1 Feature Discovery - CORRECTED Quick Start

## ⚠️ Important: Schema Issue Resolved

The original SQL queries had incorrect schema assumptions. **Use the corrected version:**

✅ **Use**: `sql_analysis_queries_v2.sql` (corrected for actual schema)
❌ **Don't use**: `sql_analysis_queries.sql` (incorrect schema)

See `SCHEMA_FIX_NOTES.md` for technical details.

---

## Quick Start (Corrected Workflow)

### Step 1: Execute Corrected SQL Queries (30 minutes)

**File**: `scripts/phase1/sql_analysis_queries_v2.sql`

```bash
# 1. Create results directory
mkdir -p results/

# 2. Open sql_analysis_queries_v2.sql in PGAdmin

# 3. Execute each query (10 total) and export to CSV:
#    - Query 1 → results/01_session_activity_patterns.csv
#    - Query 2 → results/02_ssh_key_reuse.csv (GOLD MINE!)
#    - Query 3 → results/03_command_patterns.csv
#    - Query 4 → results/04_temporal_behavioral_patterns.csv
#    - Query 5 → results/05_password_patterns.csv
#    - Query 6 → results/06_enrichment_analysis.csv
#    - Query 7 → results/07_high_activity_sessions.csv
#    - Query 8 → results/08_session_feature_vectors.csv
#    - Query 9 → results/09_ssh_key_associations.csv
#    - Query 10 → results/10_weekly_campaign_patterns.csv
```

**Date Range**: All queries use `2024-11-01` to `2025-11-01` (1 year of data)

### Step 2: Run Python Analysis (5 minutes)

```bash
# Python script automatically updated for new CSV filenames
uv run python scripts/phase1/analyze_feature_importance.py --verbose
```

### Step 3: Review Analysis Report (15 minutes)

Open `docs/phase1/feature_discovery_analysis.md` and review:
- Top 20-40 features ranked by discrimination score
- Feature categories (TTP, Temporal, Infrastructure, etc.)
- Recommended feature count for Phase 1B

---

## Key Differences from Original Queries

| Aspect | Original (Wrong) | Corrected (V2) |
|--------|-----------------|----------------|
| **Column names** | `start_time`, `end_time` | `first_event_at`, `last_event_at` |
| **SSH keys** | Queried from session table | Queries `ssh_key_intelligence` table |
| **Passwords** | Queried from session table | Queries `password_tracking` table |
| **Commands** | Individual command lists | Queries `command_stats` table |
| **Enrichment** | Separate columns | Extracted from `enrichment` JSON |
| **Source IPs** | Direct column | Not directly available (in raw_events JSON) |

---

## Schema Cheat Sheet

### SessionSummary (Main aggregation table)
- `session_id` - Primary key
- `first_event_at` / `last_event_at` - Session timing
- `command_count` - Total commands in session
- `login_attempts` - Authentication attempt count
- `file_downloads` - Downloaded file count
- `ssh_key_injections` - SSH key injection attempts
- `vt_flagged` / `dshield_flagged` - Threat detection flags
- `enrichment` JSON - DShield/SPUR data

### SSHKeyIntelligence (Actor tracking - GOLD MINE)
- `key_fingerprint` - SSH key identifier
- `key_type` / `key_bits` - Key specifications
- `first_seen` / `last_seen` - Campaign timeline
- `unique_sources` - Number of unique IPs using this key
- `unique_sessions` - Number of sessions with this key
- `total_attempts` - Total authentication attempts

### PasswordTracking (Credential stuffing analysis)
- `password_hash` - Password identifier
- `first_seen` / `last_seen` - Usage timeline
- `attempt_count` - Total attempts
- `session_count` - Successful logins
- `hibp_breach_count` - HIBP breach count

### CommandStats (Command pattern analysis)
- `command` - Command text
- `count` - Occurrence count
- `sensor` - Source sensor
- `last_seen` - Last usage date

---

## Expected Results

After running all 10 queries, you should see:

- **Query 1**: ~365 rows (daily session activity)
- **Query 2 (SSH Keys)**: ~50-200 rows (multi-IP campaigns)
- **Query 3 (Commands)**: ~100-500 rows (top commands)
- **Query 4 (Behavioral)**: ~1000-5000 rows (active sessions)
- **Query 5 (Passwords)**: ~500-2000 rows (reused passwords)
- **Query 6 (Enrichment)**: ~1000-5000 rows (with ASN/country data)
- **Query 7 (High Activity)**: ~100-500 rows (sophisticated actors)
- **Query 8 (Feature Vectors)**: ~365 rows (daily aggregates)
- **Query 9 (SSH Associations)**: ~200-1000 rows (key-session mappings)
- **Query 10 (Weekly)**: ~52 rows (weekly rollups)

---

## Troubleshooting

### Error: "column does not exist"
✅ **Solution**: You're using the old `sql_analysis_queries.sql` file. Switch to `sql_analysis_queries_v2.sql`

### Error: "operator does not exist: json -> text"
✅ **Solution**: Query 6 uses PostgreSQL JSON operators. This error means you're on SQLite (not supported for this query)

### Error: "table ssh_key_intelligence does not exist"
✅ **Solution**: Your database schema may be outdated. Run migrations: `uv run cowrie-db migrate`

---

## Success Criteria

Phase 1A.1 is complete when:

✅ All 10 queries execute without errors
✅ 10 CSV files exported to `results/` directory
✅ Python analysis runs successfully
✅ Feature discovery report generated
✅ Recommended 20-40 features identified

---

## Next Steps

After completing Phase 1A.1:

1. **Review Results**: Examine feature discovery report
2. **Phase 1A.2**: Analyze your SSH persistent campaign writeups
3. **Phase 1B**: Implement MITRE ATT&CK mapper
4. **Phase 1C**: Train Random Forest on selected features

---

**File Locations**:
- **SQL Queries**: `scripts/phase1/sql_analysis_queries_v2.sql` (USE THIS)
- **Python Analyzer**: `scripts/phase1/analyze_feature_importance.py` (updated)
- **Schema Notes**: `scripts/phase1/SCHEMA_FIX_NOTES.md` (technical details)
- **Output**: `docs/phase1/feature_discovery_analysis.md` (generated report)

---

**Status**: ✅ Schema issue resolved, corrected queries ready
**Action Required**: Execute `sql_analysis_queries_v2.sql` in PGAdmin
**Timeline**: 50 minutes (30m SQL + 5m Python + 15m review)
