# CowrieProcessor Database Schema Reference

## Critical Schema Knowledge - MEMORIZE THIS

**IMPORTANT**: This database uses a **normalized, multi-table schema**. DO NOT assume all session data is in one table!

## Core Tables Overview

### 1. SessionSummary (session_summaries)
**Purpose**: Aggregated session-level metrics computed during ingest

**Key Columns**:
- `session_id` VARCHAR(64) PRIMARY KEY
- `first_event_at` DATETIME - ✅ USE THIS (not "start_time")
- `last_event_at` DATETIME - ✅ USE THIS (not "end_time")
- `event_count` INTEGER - Total events in session
- `command_count` INTEGER - ✅ Aggregate count (not command list!)
- `file_downloads` INTEGER - Count of file downloads
- `login_attempts` INTEGER - Authentication attempt count
- `ssh_key_injections` INTEGER - SSH key injection attempts
- `unique_ssh_keys` INTEGER - Count of unique keys used
- `vt_flagged` BOOLEAN - VirusTotal detection flag
- `dshield_flagged` BOOLEAN - DShield detection flag
- `risk_score` INTEGER - Computed risk score (0-100)
- `matcher` VARCHAR(32) - Detection matcher used
- `source_files` JSON - List of source log files
- `enrichment` JSON - ✅ Contains DShield/SPUR/VT data (extract with ->>, ->)
- `created_at` DATETIME
- `updated_at` DATETIME

**IMPORTANT**: SessionSummary has NO src_ip, NO password columns, NO command arrays!
These are in RawEvent.payload JSON or specialized tracking tables.

### 2. RawEvent (raw_events)
**Purpose**: Immutable append-only storage of raw Cowrie JSON events

**Key Columns**:
- `id` INTEGER PRIMARY KEY
- `ingest_id` VARCHAR(64)
- `ingest_at` DATETIME
- `source` VARCHAR(512) - Log file path
- `source_offset` BIGINT
- `source_inode` VARCHAR(128)
- `payload` JSON - ✅ Contains src_ip, commands, passwords, etc.
- `payload_hash` VARCHAR(64)
- `session_id` VARCHAR(64) - Links to SessionSummary
- `event_type` VARCHAR(128) - cowrie.session.connect, cowrie.command.input, etc.
- `event_timestamp` DATETIME - ✅ Use for event-level queries
- `risk_score` INTEGER
- `quarantined` BOOLEAN

**Payload JSON Structure** (examples):
```json
// Connection event
{
  "eventid": "cowrie.session.connect",
  "src_ip": "192.168.1.1",
  "src_port": 51234,
  "dst_ip": "10.0.0.1",
  "dst_port": 22,
  "sensor": "honeypot-a",
  "session": "abc123def456",
  "timestamp": "2024-11-01T12:34:56.789Z"
}

// Command event
{
  "eventid": "cowrie.command.input",
  "input": "ls -la",              // ✅ Command text here
  "input_safe": "ls -la",
  "session": "abc123def456",
  "sensor": "honeypot-a",
  "timestamp": "2024-11-01T12:35:01.123Z"
}

// Login event
{
  "eventid": "cowrie.login.success",
  "username": "root",
  "password": "admin",            // ✅ Password here
  "session": "abc123def456",
  "sensor": "honeypot-a"
}

// Download event
{
  "eventid": "cowrie.session.file_download",
  "url": "http://example.com/malware.sh",
  "shasum": "abc123...",
  "session": "abc123def456"
}
```

**CRITICAL FOR COMMAND ANALYSIS**: To get command text, query RawEvent with:
```sql
SELECT payload->>'input' as command
FROM raw_events
WHERE event_type ILIKE '%command%'
  AND payload->>'input' IS NOT NULL
```

### 3. SSHKeyIntelligence (ssh_key_intelligence) - GOLD MINE
**Purpose**: SSH key tracking for persistent actor identification

**Key Columns**:
- `id` INTEGER PRIMARY KEY
- `key_type` VARCHAR(32) - ssh-rsa, ecdsa-sha2-nistp256, etc.
- `key_data` TEXT - Base64 encoded key
- `key_fingerprint` VARCHAR(64) - ✅ PRIMARY ACTOR IDENTIFIER
- `key_hash` VARCHAR(64)
- `key_comment` TEXT
- `first_seen` DATETIME
- `last_seen` DATETIME
- `total_attempts` INTEGER - Total auth attempts with this key
- `unique_sources` INTEGER - ✅ Number of unique IPs (multi-IP = campaign)
- `unique_sessions` INTEGER - Number of sessions
- `key_bits` INTEGER - Key size (2048, 4096, etc.)
- `pattern_type` VARCHAR(32)
- `target_path` TEXT
- `created_at` DATETIME
- `updated_at` DATETIME

**CRITICAL**: Query this table directly for SSH key analysis. Don't try to join with SessionSummary!

### 4. SessionSSHKeys (session_ssh_keys) - Junction table
Links sessions to SSH keys (many-to-many)
- `id` INTEGER PRIMARY KEY
- `session_id` VARCHAR(64) FK → session_summaries
- `key_id` INTEGER FK → ssh_key_intelligence
- `observed_at` DATETIME

### 5. SSHKeyAssociations (ssh_key_associations) - Campaign clustering
Links SSH keys to sessions for campaign analysis
- `id` INTEGER PRIMARY KEY  
- `key_fingerprint` VARCHAR(64)
- `session_id` VARCHAR(64)
- `observed_at` DATETIME

### 6. PasswordTracking (password_tracking)
**Purpose**: Password reuse and credential stuffing analysis

**Key Columns**:
- `password_hash` VARCHAR(64) PRIMARY KEY - SHA256 hash
- `first_seen` DATETIME
- `last_seen` DATETIME
- `attempt_count` INTEGER - Total attempts across all sessions
- `session_count` INTEGER - Successful logins
- `unique_sensors` INTEGER - Number of sensors seeing this password
- `is_novel` BOOLEAN - First time seen in dataset
- `hibp_breach_count` INTEGER - HIBP breach count
- `hibp_checked_at` DATETIME
- `created_at` DATETIME
- `updated_at` DATETIME

### 7. PasswordSessionUsage (password_session_usage) - Junction table
- `id` INTEGER PRIMARY KEY
- `password_hash` VARCHAR(64) FK → password_tracking
- `session_id` VARCHAR(64) FK → session_summaries
- `username` VARCHAR(256)
- `timestamp` DATETIME

### 8. CommandStat (command_stats) - ⚠️ PER-SESSION, NOT GLOBAL
**Purpose**: Per-session command tracking (NOT global aggregates!)

**Key Columns**:
- `id` INTEGER PRIMARY KEY
- `session_id` VARCHAR(64) - ✅ Links to specific session
- `command_normalized` TEXT - ✅ Not "command"!
- `occurrences` INTEGER - ✅ Not "count"!
- `first_seen` DATETIME
- `last_seen` DATETIME
- `high_risk` BOOLEAN

**CRITICAL MISCONCEPTION**:
- ❌ This is NOT a global command statistics table
- ❌ It does NOT have "command" or "count" columns
- ❌ It does NOT have "sensor" field
- ✅ It tracks commands PER SESSION, not globally
- ✅ For global command stats, query RawEvent.payload JSON

**CORRECT WAY to get command statistics**:
```sql
-- ✅ CORRECT: Extract from RawEvent payload
SELECT
    payload->>'input' as command,
    COUNT(*) as occurrences,
    COUNT(DISTINCT session_id) as session_count
FROM raw_events
WHERE event_type ILIKE '%command%'
  AND payload->>'input' IS NOT NULL
GROUP BY payload->>'input'
ORDER BY COUNT(*) DESC;

-- ❌ WRONG: Query command_stats expecting global aggregates
SELECT command, count, sensor  -- These columns don't exist!
FROM command_stats;
```

### 9. Files (files)
**Purpose**: Downloaded/uploaded file tracking

**Key Columns**:
- `id` INTEGER PRIMARY KEY
- `shasum` VARCHAR(64) UNIQUE - SHA256 hash
- `url` TEXT
- `filename` VARCHAR(256)
- `size` BIGINT
- `first_seen` DATETIME
- `last_seen` DATETIME
- `vt_result` JSON - VirusTotal scan results
- `download_count` INTEGER
- `session_count` INTEGER

## Common Query Patterns

### ✅ CORRECT: Query session aggregates
```sql
SELECT 
    session_id,
    first_event_at,
    last_event_at,
    command_count,
    vt_flagged
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
```

### ✅ CORRECT: Extract enrichment JSON
```sql
SELECT
    session_id,
    enrichment->>'country' as country,           -- Text extraction
    enrichment->>'asn' as asn,
    enrichment->'dshield'->>'attacks' as attacks -- Nested extraction
FROM session_summaries
WHERE enrichment IS NOT NULL
```

### ✅ CORRECT: Extract commands from RawEvent
```sql
SELECT
    payload->>'input' as command,
    COUNT(*) as occurrences,
    COUNT(DISTINCT session_id) as unique_sessions
FROM raw_events
WHERE event_timestamp >= '2024-11-01'
  AND event_type ILIKE '%command%'
  AND payload->>'input' IS NOT NULL
GROUP BY payload->>'input'
ORDER BY COUNT(*) DESC
LIMIT 100;
```

### ✅ CORRECT: Query SSH key tracking
```sql
SELECT
    key_fingerprint,
    key_type,
    unique_sources,
    total_attempts
FROM ssh_key_intelligence
WHERE unique_sources >= 3  -- Multi-IP campaigns
```

### ❌ WRONG: Assuming denormalized schema
```sql
-- ❌ DOES NOT WORK - these columns don't exist in session_summaries
SELECT 
    start_time,        -- ❌ NO! Use first_event_at
    end_time,          -- ❌ NO! Use last_event_at
    src_ip,            -- ❌ NO! In raw_events.payload JSON
    commands,          -- ❌ NO! command_count is an integer
    password_hash,     -- ❌ NO! In password_tracking table
    ssh_key_fingerprint -- ❌ NO! In ssh_key_intelligence table
FROM session_summaries
```

### ❌ WRONG: Querying CommandStat for global stats
```sql
-- ❌ DOES NOT WORK - command_stats is per-session
SELECT command, count, sensor  -- These columns don't exist!
FROM command_stats
ORDER BY count DESC;
```

### ✅ CORRECT: Join sessions with SSH keys
```sql
SELECT
    ss.session_id,
    ss.first_event_at,
    ski.key_fingerprint,
    ski.unique_sources
FROM session_summaries ss
JOIN ssh_key_associations ska ON ss.session_id = ska.session_id
JOIN ssh_key_intelligence ski ON ska.key_fingerprint = ski.key_fingerprint
WHERE ss.first_event_at >= '2024-11-01'
```

## Critical Lessons Learned

### 2025-11-01: Schema Assumption Errors
**Error 1**: Wrote SQL queries assuming `start_time` column existed
**Reality**: Column is `first_event_at`

**Error 2**: Wrote SQL query assuming `command`, `count`, `sensor` columns in command_stats
**Reality**: command_stats has `command_normalized`, `occurrences`, `session_id` (per-session, not global)

**Cost**: Required multiple query rewrites
**Prevention**: ALWAYS check ORM models before writing queries

### How to Verify Schema
```python
# Check table columns in Python
from cowrieprocessor.db.models import SessionSummary, CommandStat, RawEvent
print("SessionSummary:", [col.name for col in SessionSummary.__table__.columns])
print("CommandStat:", [col.name for col in CommandStat.__table__.columns])
print("RawEvent:", [col.name for col in RawEvent.__table__.columns])

# Or via SQL
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'command_stats'
ORDER BY ordinal_position;
```

## Date Range Conventions

**Production Dataset**: 1 year of data with gaps
**Date Range for Queries**: `2024-11-01` to `2025-11-01`
**Always use**: 
- SessionSummary: `first_event_at >= '2024-11-01' AND first_event_at < '2025-11-01'`
- RawEvent: `event_timestamp >= '2024-11-01' AND event_timestamp < '2025-11-01'`

## JSON Operators (PostgreSQL)

- `->` : Returns JSON object (use for chaining)
- `->>` : Returns text value (use for final extraction)
- `#>` : Get JSON object at path (array notation)
- `#>>` : Get text at path

Examples:
```sql
enrichment->>'country'                    → "US"
enrichment->'dshield'->>'attacks'         → "42"
payload->>'input'                         → "ls -la"
payload->>'src_ip'                        → "192.168.1.1"
```

## Event Types in RawEvent

Common event_type values:
- `cowrie.session.connect` - Session started
- `cowrie.command.input` - Command executed (has `payload->>'input'`)
- `cowrie.login.success` - Successful login (has username/password)
- `cowrie.login.failed` - Failed login
- `cowrie.session.file_download` - File download (has URL/SHA)
- `cowrie.session.closed` - Session ended

## Key Relationships

```
RawEvent.session_id → SessionSummary.session_id
SessionSSHKeys.session_id → SessionSummary.session_id
SessionSSHKeys.key_id → SSHKeyIntelligence.id
SSHKeyAssociations.session_id → SessionSummary.session_id
SSHKeyAssociations.key_fingerprint → SSHKeyIntelligence.key_fingerprint
PasswordSessionUsage.session_id → SessionSummary.session_id
PasswordSessionUsage.password_hash → PasswordTracking.password_hash
CommandStat.session_id → SessionSummary.session_id
Files.shasum → (referenced in RawEvent.payload->>'shasum')
```

## Performance Indexes

Relevant indexes from schema:
- `ix_session_summaries_first_event` on first_event_at
- `ix_session_summaries_last_event` on last_event_at
- `ix_session_summaries_flags` on (vt_flagged, dshield_flagged)
- `ix_session_summaries_ssh_keys` on ssh_key_injections
- `ix_command_stats_session` on session_id
- `ix_command_stats_command` on command_normalized

## Summary: Golden Rules

1. ✅ **ALWAYS use `first_event_at` and `last_event_at`** (not start_time/end_time)
2. ✅ **Extract commands from RawEvent.payload JSON** (not from CommandStat)
3. ✅ **Query specialized tables** (SSHKeyIntelligence, PasswordTracking)
4. ✅ **Extract JSON with ->> and ->** for enrichment and payload data
5. ✅ **Use date range** 2024-11-01 to 2025-11-01 for production queries
6. ✅ **Check ORM models** before writing any SQL queries
7. ❌ **NEVER assume** src_ip, commands, passwords are in SessionSummary
8. ❌ **NEVER query** CommandStat expecting global aggregates (it's per-session!)
9. ❌ **NEVER use** column names without verifying they exist first

---

**Memory Updated**: 2025-11-01 (v2 - corrected CommandStat schema)
**Purpose**: Prevent schema assumption errors in Phase 1B and beyond
**Critical for**: SQL query writing, feature engineering, MITRE mapper implementation
