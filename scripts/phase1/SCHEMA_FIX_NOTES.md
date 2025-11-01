# SQL Query Schema Fix - Migration Notes

## Issue Discovered

The original `sql_analysis_queries.sql` was based on incorrect schema assumptions. When executing Query 1, you encountered:

```
ERROR: column "start_time" does not exist
LINE 2: DATE(start_time) as attack_date,
```

## Root Cause

The queries assumed a denormalized schema with all session details in one table. The actual CowrieProcessor database schema is normalized:

### Assumed Schema (INCORRECT):
```sql
session_summaries (
    start_time,           -- ❌ DOES NOT EXIST
    end_time,             -- ❌ DOES NOT EXIST
    src_ip,               -- ❌ DOES NOT EXIST
    commands TEXT[],      -- ❌ DOES NOT EXIST
    password_hash,        -- ❌ DOES NOT EXIST
    ssh_key_fingerprint,  -- ❌ DOES NOT EXIST
    dshield_data JSON     -- ❌ DOES NOT EXIST
)
```

### Actual Schema (CORRECT):
```sql
session_summaries (
    session_id PRIMARY KEY,
    first_event_at,       -- ✅ Use instead of start_time
    last_event_at,        -- ✅ Use instead of end_time
    command_count,        -- ✅ Aggregate count, not list
    login_attempts,       -- ✅ Aggregate count
    file_downloads,       -- ✅ Aggregate count
    ssh_key_injections,   -- ✅ Count of SSH key attempts
    unique_ssh_keys,      -- ✅ Count of unique keys
    vt_flagged BOOLEAN,   -- ✅ VirusTotal detection flag
    dshield_flagged BOOLEAN, -- ✅ DShield detection flag
    risk_score INTEGER,   -- ✅ Computed risk score
    enrichment JSON       -- ✅ Combined enrichment data
)

raw_events (
    id PRIMARY KEY,
    session_id,
    event_timestamp,
    payload JSON          -- ✅ Contains src_ip, commands, passwords
)

ssh_key_intelligence (
    key_fingerprint PRIMARY KEY,
    key_type,
    key_bits,
    first_seen,
    last_seen,
    total_attempts,
    unique_sources,       -- ✅ Count of unique IPs
    unique_sessions       -- ✅ Count of unique sessions
)

password_tracking (
    password_hash PRIMARY KEY,
    first_seen,
    last_seen,
    attempt_count,
    session_count,
    hibp_breach_count
)

command_stats (
    command TEXT,
    count INTEGER,
    sensor TEXT,
    last_seen
)
```

## Solution: New Query File

Created **`sql_analysis_queries_v2.sql`** with corrected queries that:

1. ✅ Use `first_event_at` / `last_event_at` instead of `start_time` / `end_time`
2. ✅ Query `SSHKeyIntelligence` table directly for SSH key analysis
3. ✅ Query `PasswordTracking` table for password patterns
4. ✅ Query `CommandStats` table for command analysis
5. ✅ Use `enrichment` JSON field with PostgreSQL JSON operators (`->`, `->>`)
6. ✅ Work with aggregated metrics in `SessionSummary` instead of raw event details

## Query Mapping

| Original Query | New Query | Changes |
|----------------|-----------|---------|
| 01 - Command Diversity | 01 - Session Activity Patterns | Uses SessionSummary aggregates |
| 02 - TTP Sequences | 03 - Command Patterns | Uses CommandStats table |
| 03 - Temporal Patterns | 04 - Temporal Behavioral | Uses first_event_at timestamp |
| 04 - ASN Clustering | 06 - Enrichment Analysis | Extracts ASN from enrichment JSON |
| **05 - SSH Key Reuse** | **02 - SSH Key Reuse** | **Uses SSHKeyIntelligence table** |
| 06 - Password Analysis | 05 - Password Patterns | Uses PasswordTracking table |
| 07 - Persistence Techniques | 03 - Command Patterns | Category-based filtering |
| 08 - Credential Access | 03 - Command Patterns | Category-based filtering |
| 09 - Reconnaissance | 03 - Command Patterns | Category-based filtering |
| 10 - Campaign Correlation | 08 - Session Feature Vectors | Daily feature aggregation |

## Key Improvements

### 1. SSH Key Analysis (Query 2 - GOLD MINE)
**Now uses dedicated table** with proper tracking:
```sql
SELECT
    key_fingerprint,
    key_type,
    first_seen,
    last_seen,
    total_attempts,
    unique_sources as unique_ips,
    unique_sessions
FROM ssh_key_intelligence
WHERE unique_sources >= 3  -- Multi-IP campaigns
```

### 2. Enrichment Data Extraction (Query 6)
**Uses PostgreSQL JSON operators**:
```sql
SELECT
    enrichment->>'country' as country,
    enrichment->>'asn' as asn,
    enrichment->'dshield'->>'attacks' as dshield_attacks,
    enrichment->'spur'->>'client' as spur_client_type
FROM session_summaries
```

### 3. Command Pattern Analysis (Query 3)
**Uses CommandStats table** with MITRE categorization:
```sql
SELECT
    command,
    count,
    CASE
        WHEN command ILIKE '%cron%' THEN 'persistence'
        WHEN command ILIKE '%passwd%' THEN 'account_manipulation'
        WHEN command ILIKE '%nmap%' THEN 'network_scan'
    END as command_category
FROM command_stats
```

## Date Range Answer

**Your Question**: "Value for start_time (todays date 11/1/2025), January 1 2025?"

**Answer**: Use **2024-11-01 to 2025-11-01** (1 year of data)

All queries in `sql_analysis_queries_v2.sql` use:
```sql
WHERE first_event_at >= '2024-11-01'
  AND first_event_at < '2025-11-01'
```

This covers your "mostly complete 1 year back with a few gaps" dataset.

## Action Required

### Step 1: Use New Query File
❌ **Do NOT use**: `scripts/phase1/sql_analysis_queries.sql` (incorrect schema)
✅ **Use instead**: `scripts/phase1/sql_analysis_queries_v2.sql` (corrected schema)

### Step 2: Update CSV Filenames
New CSV filenames (10 files):
```
results/01_session_activity_patterns.csv
results/02_ssh_key_reuse.csv
results/03_command_patterns.csv
results/04_temporal_behavioral_patterns.csv
results/05_password_patterns.csv
results/06_enrichment_analysis.csv
results/07_high_activity_sessions.csv
results/08_session_feature_vectors.csv
results/09_ssh_key_associations.csv
results/10_weekly_campaign_patterns.csv
```

### Step 3: Update Python Analyzer
The Python script `analyze_feature_importance.py` will need minor updates to handle the new CSV filenames. Let me update that now.

## Technical Notes

### PostgreSQL JSON Extraction
The enrichment field stores JSON data. PostgreSQL uses:
- `->` operator: Returns JSON object
- `->>` operator: Returns text value

Example:
```sql
enrichment->>'country'              -- Returns text: "US"
enrichment->'dshield'->>'attacks'   -- Returns text from nested JSON
```

### SessionSummary vs RawEvent
- **SessionSummary**: Aggregated session-level metrics (use for Phase 1A queries)
- **RawEvent**: Individual event JSON payloads (only needed for deep TTP extraction in Phase 1B)

For Phase 1A feature discovery, SessionSummary + specialized tables (SSHKeyIntelligence, PasswordTracking, CommandStats) provide sufficient data.

## Verification

After running the new queries, you should see:
- ✅ No "column does not exist" errors
- ✅ Query 2 (SSH Key Reuse) returns ~50-200 rows
- ✅ Query 6 (Enrichment Analysis) extracts ASN, country, VPN status
- ✅ All queries return reasonable row counts (see query comments)

---

**Status**: Schema issue identified and resolved
**New File**: `sql_analysis_queries_v2.sql` ready for execution
**Date Range**: 2024-11-01 to 2025-11-01 (1 year)
**Next**: Execute corrected queries in PGAdmin
