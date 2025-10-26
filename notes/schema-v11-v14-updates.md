# Schema v11-v14 Updates for Data Dictionary

**Purpose**: Document schema changes v11-v14 to be incorporated into `data_dictionary.md`
**Date**: October 25, 2025
**Source**: `cowrieprocessor/db/migrations.py` (lines 1250-1900)

---

## Schema v11: SSH Key Intelligence Tracking

**Migration**: `_upgrade_to_v11()` (line 1250)
**Description**: Add SSH key intelligence tracking tables

###Table: ssh_key_intelligence

**Purpose**: Track SSH public keys attempted in login sessions

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL / INTEGER | NO | auto | Primary key |
| key_type | VARCHAR(32) | NO | - | SSH key type (rsa, ed25519, ecdsa, etc.) |
| key_data | TEXT | NO | - | Base64-encoded key data |
| key_fingerprint | VARCHAR(64) | NO | - | Key fingerprint (MD5 or SHA256) |
| key_hash | VARCHAR(64) | NO | - | Unique hash of key (UNIQUE constraint) |
| key_comment | TEXT | YES | - | Comment field from SSH key |
| first_seen | TIMESTAMP WITH TIME ZONE / TIMESTAMP | NO | NOW() / CURRENT_TIMESTAMP | First observation of this key |
| last_seen | TIMESTAMP WITH TIME ZONE / TIMESTAMP | NO | NOW() / CURRENT_TIMESTAMP | Most recent observation |
| total_attempts | INTEGER | NO | 1 | Total login attempts with this key |
| unique_sources | INTEGER | NO | 1 | Number of unique source IPs |
| unique_sessions | INTEGER | NO | 1 | Number of unique sessions |
| key_bits | INTEGER | YES | - | Key size in bits |
| key_full | TEXT | NO | - | Complete SSH public key |
| pattern_type | VARCHAR(32) | NO | - | Pattern classification |
| target_path | TEXT | YES | - | Target path for key injection |
| created_at | TIMESTAMP WITH TIME ZONE / TIMESTAMP | NO | NOW() / CURRENT_TIMESTAMP | Record creation time |
| updated_at | TIMESTAMP WITH TIME ZONE / TIMESTAMP | NO | NOW() / CURRENT_TIMESTAMP | Last record update |

**Indexes**:
- Primary key on `id`
- Unique constraint on `key_hash`
- `ix_ssh_key_fingerprint` on `key_fingerprint`
- `ix_ssh_key_type` on `key_type`
- `ix_ssh_key_timeline` on `(first_seen, last_seen)`
- `ix_ssh_key_attempts` on `total_attempts`
- `ix_ssh_key_sources` on `unique_sources`
- `ix_ssh_key_sessions` on `unique_sessions`

**Usage**: Central repository for all observed SSH keys, supporting campaign detection and key reuse analysis.

---

### Table: session_ssh_keys

**Purpose**: Link SSH keys to specific sessions

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL / INTEGER | NO | auto | Primary key |
| session_id | VARCHAR(64) | NO | - | Session identifier |
| ssh_key_id | INTEGER | NO | - | Foreign key to ssh_key_intelligence(id) |
| command_text | TEXT | YES | - | Command text associated with key use |
| command_hash | VARCHAR(64) | YES | - | Hash of command |
| injection_method | VARCHAR(32) | NO | - | Method of key injection |
| timestamp | TIMESTAMP WITH TIME ZONE / TIMESTAMP | NO | NOW() / CURRENT_TIMESTAMP | Time of key usage |
| source_ip | VARCHAR(45) | YES | - | Source IP address |
| successful_injection | BOOLEAN | NO | FALSE / 0 | Whether key injection succeeded |

**Foreign Keys**:
- `ssh_key_id` REFERENCES `ssh_key_intelligence(id)`

**Indexes**:
- Primary key on `id`
- `ix_session_ssh_keys_session` on `session_id`
- `ix_session_ssh_keys_timestamp` on `timestamp`
- `ix_session_ssh_keys_ssh_key` on `ssh_key_id`
- `ix_session_ssh_keys_source_ip` on `source_ip`

**Usage**: Tracks individual uses of SSH keys within sessions, supporting temporal analysis.

---

### Table: ssh_key_associations

**Purpose**: Track co-occurrence and associations between SSH keys

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL / INTEGER | NO | auto | Primary key |
| key_id_1 | INTEGER | NO | - | Foreign key to ssh_key_intelligence(id) |
| key_id_2 | INTEGER | NO | - | Foreign key to ssh_key_intelligence(id) |
| co_occurrence_count | INTEGER | NO | 1 | Number of co-occurrences |
| first_seen | TIMESTAMP WITH TIME ZONE / TIMESTAMP | NO | NOW() / CURRENT_TIMESTAMP | First co-occurrence |
| last_seen | TIMESTAMP WITH TIME ZONE / TIMESTAMP | NO | NOW() / CURRENT_TIMESTAMP | Most recent co-occurrence |
| same_session_count | INTEGER | NO | 0 | Keys used in same session |
| same_ip_count | INTEGER | NO | 0 | Keys used from same IP |

**Foreign Keys**:
- `key_id_1` REFERENCES `ssh_key_intelligence(id)`
- `key_id_2` REFERENCES `ssh_key_intelligence(id)`

**Constraints**:
- Unique constraint on `(key_id_1, key_id_2)`

**Indexes**:
- Primary key on `id`
- `ix_ssh_key_associations_key1` on `key_id_1`
- `ix_ssh_key_associations_key2` on `key_id_2`
- `ix_ssh_key_associations_timeline` on `(first_seen, last_seen)`

**Usage**: Supports campaign detection by identifying keys used together (graph-based analysis).

---

## Schema v12: event_timestamp Type Conversion

**Migration**: `_upgrade_to_v12()` (line 1608)
**Description**: Convert event_timestamp from VARCHAR to proper TIMESTAMP type

### Changes to Table: raw_events

**Modified Column**:
- `event_timestamp`: Changed from VARCHAR(64) to TIMESTAMP WITH TIME ZONE (PostgreSQL) or TIMESTAMP (SQLite)

**Data Migration**:
- Valid ISO 8601 timestamps converted to datetime
- Invalid/empty timestamps set to NULL
- Handles edge cases: empty strings, 'null' strings, malformed dates

**Impact**:
- Better temporal query performance
- Proper timezone handling
- Type safety for timestamp operations

**Usage**: Enables efficient temporal queries on raw events table.

---

## Schema v13: Longtail Detection Enhancements

**Migration**: `_upgrade_to_v13()` (line 1717)
**Description**: Add longtail detection-session junction table and checkpoints

### Table: longtail_detection_sessions

**Purpose**: Junction table linking detections to sessions (many-to-many)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| detection_id | INTEGER | NO | - | Foreign key to longtail_detections(id), ON DELETE CASCADE |
| session_id | VARCHAR(64) | NO | - | Foreign key to session_summaries(session_id), ON DELETE CASCADE |

**Primary Key**: Composite (`detection_id`, `session_id`)

**Foreign Keys**:
- `detection_id` REFERENCES `longtail_detections(id)` ON DELETE CASCADE
- `session_id` REFERENCES `session_summaries(session_id)` ON DELETE CASCADE

**Indexes**:
- Primary key on `(detection_id, session_id)`
- `ix_longtail_detection_sessions_detection` on `detection_id`
- `ix_longtail_detection_sessions_session` on `session_id`

**Usage**: Links anomaly detections to the sessions that triggered them.

---

### Table: longtail_analysis_checkpoints

**Purpose**: Track analysis checkpoints for incremental processing

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL / INTEGER | NO | auto | Primary key |
| analysis_type | VARCHAR(64) | NO | - | Type of analysis |
| checkpoint_name | VARCHAR(128) | NO | - | Checkpoint identifier |
| checkpoint_value | TEXT | NO | - | Checkpoint data (JSON) |
| created_at | TIMESTAMP WITH TIME ZONE / TIMESTAMP | NO | NOW() / CURRENT_TIMESTAMP | Checkpoint creation time |
| updated_at | TIMESTAMP WITH TIME ZONE / TIMESTAMP | NO | NOW() / CURRENT_TIMESTAMP | Last checkpoint update |

**Indexes**:
- Primary key on `id`
- Unique constraint on `(analysis_type, checkpoint_name)`
- `ix_longtail_checkpoints_analysis_type` on `analysis_type`
- `ix_longtail_checkpoints_updated` on `updated_at`

**Usage**: Enables incremental longtail analysis, tracking last-processed timestamps.

---

## Schema v14: Vector Table Enhancement

**Migration**: `_upgrade_to_v14()` (line 1823)
**Description**: Add analysis_id to vector tables (PostgreSQL with pgvector only)

**Scope**: PostgreSQL databases with pgvector extension only (SQLite skipped)

### Changes to Table: command_sequence_vectors

**Added Column**:
- `analysis_id`: INTEGER, references `longtail_analysis(id)` ON DELETE CASCADE

**Added Index**:
- `ix_command_sequence_vectors_analysis` on `analysis_id`

**Usage**: Links command sequence vectors to specific analysis runs.

---

### Changes to Table: behavioral_vectors

**Added Column**:
- `analysis_id`: INTEGER, references `longtail_analysis(id)` ON DELETE CASCADE

**Added Index**:
- `ix_behavioral_vectors_analysis` on `analysis_id`

**Usage**: Links behavioral vectors to specific analysis runs.

---

## Summary of Schema Changes

### New Tables Added
1. **v11**: `ssh_key_intelligence`, `session_ssh_keys`, `ssh_key_associations`
2. **v13**: `longtail_detection_sessions`, `longtail_analysis_checkpoints`

### Modified Tables
1. **v12**: `raw_events` (event_timestamp type changed)
2. **v14**: `command_sequence_vectors`, `behavioral_vectors` (analysis_id added, PostgreSQL only)

### Total New Indexes
- **v11**: 15 indexes across 3 SSH key tables
- **v13**: 3 indexes for junction and checkpoints tables
- **v14**: 2 indexes for vector tables

### Schema Version Progression
- v10 → v11: SSH Key Intelligence
- v11 → v12: event_timestamp type conversion
- v12 → v13: Longtail detection enhancements
- v13 → v14: Vector table analysis tracking

---

## References

- Migration code: `cowrieprocessor/db/migrations.py` lines 1250-1900
- CHANGELOG: v3.0.0 section, [Unreleased] section
- Feature documentation:
  - SSH Key Intelligence: `notes/DAY14_SSH_ANALYTICS_SUMMARY.md`
  - Longtail Analysis: `notes/day8_botnet_analysis.md`
- Test coverage:
  - SSH keys: `tests/unit/test_ssh_key_analytics.py` (98% coverage)
  - Migrations: `tests/unit/test_migrations.py` (v2, v3, v4, v9, v11 tested)

---

*Document created: October 25, 2025*
*For incorporation into: `docs/data_dictionary.md`*
*Current data_dictionary version: 10 (outdated)*
*Target version: 14*
