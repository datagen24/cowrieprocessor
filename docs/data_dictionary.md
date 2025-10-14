# Cowrie Processor Database Data Dictionary

## Overview

This data dictionary provides comprehensive documentation for all tables, columns, and relationships in the Cowrie Processor database. The system supports both PostgreSQL and SQLite backends with different feature sets.

**Current Schema Version**: 10  
**Supported Databases**: PostgreSQL 12+, SQLite 3.8+  
**Last Updated**: October 2025

---

## Table of Contents

1. [Core Schema Management](#core-schema-management)
2. [Raw Event Storage](#raw-event-storage)
3. [Session Aggregation](#session-aggregation)
4. [Command Statistics](#command-statistics)
5. [File Management](#file-management)
6. [Ingest Tracking](#ingest-tracking)
7. [Dead Letter Queue](#dead-letter-queue)
8. [Analysis Tables](#analysis-tables)
9. [Password Statistics](#password-statistics)
10. [Vector Tables](#vector-tables)
11. [Legacy Tables](#legacy-tables)

---

## Core Schema Management

### schema_state

**Purpose**: Key/value metadata used to track schema versions and flags.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| key | VARCHAR(128) | NO | - | Primary key for configuration setting |
| value | VARCHAR(256) | NO | - | Configuration value |

**Indexes**: Primary key on `key`

**Usage**: Stores schema version, feature flags, and configuration settings.

---

### schema_metadata

**Purpose**: Track schema version and available features.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| version | INTEGER | NO | - | Schema version number |
| database_type | VARCHAR(16) | NO | - | 'postgresql' or 'sqlite' |
| features | JSONB/TEXT | NO | - | Available features as JSON |
| upgraded_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | When schema was upgraded |

**Indexes**: 
- Primary key on `id`
- `ix_schema_metadata_version` on `version`
- `ix_schema_metadata_database_type` on `database_type`

**Usage**: Tracks schema evolution and database-specific features.

---

## Raw Event Storage

### raw_events

**Purpose**: Persistent copy of raw Cowrie events with JSON payloads and extracted columns.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| ingest_id | VARCHAR(64) | YES | - | Unique identifier for ingest batch |
| ingest_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | When event was ingested |
| source | VARCHAR(512) | NO | - | Source file path |
| source_offset | BIGINT | YES | - | Byte offset in source file |
| source_inode | VARCHAR(128) | YES | - | File system inode |
| source_generation | INTEGER | NO | 0 | File generation counter |
| payload | JSONB/TEXT | NO | - | Raw event JSON payload |
| payload_hash | VARCHAR(64) | YES | - | SHA-256 hash of payload |
| risk_score | INTEGER | YES | - | Calculated risk score |
| quarantined | BOOLEAN | NO | FALSE | Whether event is quarantined |
| session_id | VARCHAR(64) | YES | - | Extracted session ID |
| event_type | VARCHAR(128) | YES | - | Extracted event type |
| event_timestamp | VARCHAR(64) | YES | - | Extracted timestamp |

**Indexes**:
- Primary key on `id`
- `ix_raw_events_ingest_at` on `ingest_at`
- `ix_raw_events_session_id` on `session_id`
- `ix_raw_events_event_type` on `event_type`
- `ix_raw_events_event_timestamp` on `event_timestamp`
- Unique constraint `uq_raw_events_source_offset` on `(source, source_inode, source_generation, source_offset)`

**Usage**: Primary storage for all Cowrie events with both raw JSON and extracted fields for performance.

---

## Session Aggregation

### session_summaries

**Purpose**: Aggregated per-session metrics derived during ingest.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| session_id | VARCHAR(64) | NO | - | Primary key - session identifier |
| first_event_at | TIMESTAMP WITH TIME ZONE | YES | - | First event timestamp |
| last_event_at | TIMESTAMP WITH TIME ZONE | YES | - | Last event timestamp |
| event_count | INTEGER | NO | 0 | Total number of events |
| command_count | INTEGER | NO | 0 | Number of commands executed |
| file_downloads | INTEGER | NO | 0 | Number of file downloads |
| login_attempts | INTEGER | NO | 0 | Number of login attempts |
| vt_flagged | BOOLEAN | NO | FALSE | Flagged by VirusTotal |
| dshield_flagged | BOOLEAN | NO | FALSE | Flagged by DShield |
| risk_score | INTEGER | YES | - | Calculated risk score |
| matcher | VARCHAR(32) | YES | - | Matching algorithm used |
| source_files | JSONB/TEXT | YES | - | Source file metadata |
| enrichment | JSONB/TEXT | YES | - | Enrichment data |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | When record was created |
| updated_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | When record was last updated |

**Indexes**:
- Primary key on `session_id`
- `ix_session_summaries_first_event` on `first_event_at`
- `ix_session_summaries_last_event` on `last_event_at`
- `ix_session_summaries_flags` on `(vt_flagged, dshield_flagged)`

**Usage**: Aggregated metrics for reporting and analysis, updated during event processing.

---

## Command Statistics

### command_stats

**Purpose**: Per-session command aggregation used by reporting workflows.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| session_id | VARCHAR(64) | NO | - | Session identifier |
| command_normalized | TEXT | NO | - | Normalized command text |
| occurrences | INTEGER | NO | 0 | Number of times command was executed |
| first_seen | TIMESTAMP WITH TIME ZONE | YES | - | First occurrence timestamp |
| last_seen | TIMESTAMP WITH TIME ZONE | YES | - | Last occurrence timestamp |
| high_risk | BOOLEAN | NO | FALSE | Whether command is high risk |

**Indexes**:
- Primary key on `id`
- Unique constraint `uq_command_stats_session_command` on `(session_id, command_normalized)`
- `ix_command_stats_session` on `session_id`
- `ix_command_stats_command` on `command_normalized`

**Usage**: Command frequency analysis and risk assessment.

---

## File Management

### files

**Purpose**: Normalized files table with VirusTotal enrichment data.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| session_id | VARCHAR(64) | NO | - | Session identifier |
| shasum | VARCHAR(64) | NO | - | SHA-256 hash of file |
| filename | VARCHAR(512) | YES | - | Original filename |
| file_size | BIGINT | YES | - | File size in bytes |
| download_url | VARCHAR(1024) | YES | - | Download URL |
| vt_classification | VARCHAR(128) | YES | - | VirusTotal classification |
| vt_description | TEXT | YES | - | VirusTotal description |
| vt_malicious | BOOLEAN | NO | FALSE | Whether file is malicious |
| vt_first_seen | TIMESTAMP WITH TIME ZONE | YES | - | First seen by VirusTotal |
| vt_last_analysis | TIMESTAMP WITH TIME ZONE | YES | - | Last analysis timestamp |
| vt_positives | INTEGER | YES | - | Number of positive detections |
| vt_total | INTEGER | YES | - | Total number of engines |
| vt_scan_date | TIMESTAMP WITH TIME ZONE | YES | - | Scan date |
| first_seen | TIMESTAMP WITH TIME ZONE | NO | NOW() | First seen in system |
| last_updated | TIMESTAMP WITH TIME ZONE | NO | NOW() | Last update timestamp |
| enrichment_status | VARCHAR(32) | NO | 'pending' | Enrichment status |

**Indexes**:
- Primary key on `id`
- Unique constraint `uq_files_session_hash` on `(session_id, shasum)`
- `ix_files_shasum` on `shasum`
- `ix_files_vt_malicious` on `vt_malicious`
- `ix_files_enrichment_status` on `enrichment_status`
- `ix_files_first_seen` on `first_seen`
- `ix_files_session_id` on `session_id`

**Usage**: File tracking with VirusTotal enrichment and threat intelligence.

---

## Ingest Tracking

### ingest_cursors

**Purpose**: Tracks the last processed offset for delta ingestion per source file.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| source | VARCHAR(512) | NO | - | Primary key - source file path |
| inode | VARCHAR(128) | YES | - | File system inode |
| last_offset | INTEGER | NO | -1 | Last processed byte offset |
| last_ingest_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Last ingest timestamp |
| last_ingest_id | VARCHAR(64) | YES | - | Last ingest batch ID |
| metadata_json | JSONB/TEXT | YES | - | Additional metadata |

**Indexes**:
- Primary key on `source`
- `ix_ingest_cursors_offset` on `last_offset`

**Usage**: Enables incremental processing and prevents duplicate ingestion.

---

## Dead Letter Queue

### dead_letter_events

**Purpose**: Stores hostile or invalid events encountered during ingestion.

**PostgreSQL Enhanced Features** (v7+):
- Security and audit enhancements
- Processing locks and retry logic
- Priority and classification system
- Circuit breaker integration

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| ingest_id | VARCHAR(64) | YES | - | Ingest batch identifier |
| source | VARCHAR(512) | YES | - | Source file path |
| source_offset | INTEGER | YES | - | Byte offset in source |
| source_inode | VARCHAR(128) | YES | - | File system inode (PostgreSQL only) |
| reason | VARCHAR(128) | NO | - | Failure reason |
| payload | JSONB/TEXT | NO | - | Failed event payload |
| metadata_json | JSONB/TEXT | YES | - | Additional metadata |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | When event was created |
| resolved | BOOLEAN | NO | FALSE | Whether event was resolved |
| resolved_at | TIMESTAMP WITH TIME ZONE | YES | - | Resolution timestamp |
| payload_checksum | VARCHAR(64) | YES | - | SHA-256 checksum (PostgreSQL only) |
| retry_count | INTEGER | NO | 0 | Number of retry attempts (PostgreSQL only) |
| error_history | JSONB | YES | - | Error history log (PostgreSQL only) |
| processing_attempts | JSONB | YES | - | Processing attempt log (PostgreSQL only) |
| resolution_method | VARCHAR(64) | YES | - | How event was resolved (PostgreSQL only) |
| idempotency_key | VARCHAR(128) | YES | - | Unique reprocessing key (PostgreSQL only) |
| processing_lock | UUID | YES | - | Processing lock identifier (PostgreSQL only) |
| lock_expires_at | TIMESTAMP WITH TIME ZONE | YES | - | Lock expiration (PostgreSQL only) |
| priority | INTEGER | NO | 5 | Processing priority 1-10 (PostgreSQL only) |
| classification | VARCHAR(32) | YES | - | Event classification (PostgreSQL only) |
| updated_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Last update timestamp (PostgreSQL only) |
| last_processed_at | TIMESTAMP WITH TIME ZONE | YES | - | Last processing attempt (PostgreSQL only) |

**Indexes**:
- Primary key on `id`
- `ix_dead_letter_events_created` on `created_at`
- `ix_dead_letter_events_source` on `source`
- **PostgreSQL Enhanced**:
  - `ix_dead_letter_events_payload_checksum` on `payload_checksum`
  - `ix_dead_letter_events_retry_count` on `retry_count`
  - `ix_dead_letter_events_idempotency_key` on `idempotency_key`
  - `ix_dead_letter_events_processing_lock` on `processing_lock`
  - `ix_dead_letter_events_lock_expires` on `lock_expires_at`
  - `ix_dead_letter_events_classification` on `classification`
  - `ix_dead_letter_events_resolved_created` on `(resolved, created_at)`
  - `ix_dead_letter_events_priority_resolved` on `(priority, resolved)`

**Constraints** (PostgreSQL only):
- `ck_retry_count_positive`: retry_count >= 0
- `ck_priority_range`: priority BETWEEN 1 AND 10
- `uq_idempotency_key`: Unique idempotency keys

**Usage**: Failed event processing with retry logic and audit trails.

---

### dlq_processing_metrics (PostgreSQL Only)

**Purpose**: Metrics table for DLQ processing performance tracking.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| processing_session_id | VARCHAR(64) | NO | - | Processing session identifier |
| processing_method | VARCHAR(32) | NO | - | Processing method used |
| batch_size | INTEGER | NO | - | Number of events in batch |
| processed_count | INTEGER | NO | - | Successfully processed count |
| repaired_count | INTEGER | NO | - | Repaired and processed count |
| failed_count | INTEGER | NO | - | Failed processing count |
| skipped_count | INTEGER | NO | - | Skipped events count |
| processing_duration_ms | INTEGER | NO | - | Total processing time |
| avg_processing_time_ms | INTEGER | YES | - | Average processing time |
| peak_memory_mb | INTEGER | YES | - | Peak memory usage |
| circuit_breaker_triggered | BOOLEAN | NO | FALSE | Whether circuit breaker triggered |
| rate_limit_hits | INTEGER | NO | 0 | Number of rate limit hits |
| lock_timeout_count | INTEGER | NO | 0 | Number of lock timeouts |
| started_at | TIMESTAMP WITH TIME ZONE | NO | - | Processing start time |
| completed_at | TIMESTAMP WITH TIME ZONE | NO | - | Processing completion time |

**Indexes**:
- Primary key on `id`
- `ix_dlq_metrics_session` on `processing_session_id`
- `ix_dlq_metrics_method` on `processing_method`
- `ix_dlq_metrics_started` on `started_at`

**Usage**: Performance monitoring and optimization of DLQ processing.

---

### dlq_circuit_breaker_state (PostgreSQL Only)

**Purpose**: Circuit breaker state for DLQ processing.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| breaker_name | VARCHAR(64) | NO | - | Circuit breaker name |
| state | VARCHAR(16) | NO | - | Current state (closed/open/half_open) |
| failure_count | INTEGER | NO | 0 | Current failure count |
| last_failure_time | TIMESTAMP WITH TIME ZONE | YES | - | Last failure timestamp |
| next_attempt_time | TIMESTAMP WITH TIME ZONE | YES | - | Next attempt timestamp |
| failure_threshold | INTEGER | NO | 5 | Failure threshold |
| timeout_seconds | INTEGER | NO | 60 | Timeout in seconds |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Creation timestamp |
| updated_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Last update timestamp |

**Indexes**:
- Primary key on `id`
- Unique constraint on `breaker_name`
- `ix_circuit_breaker_state` on `state`
- `ix_circuit_breaker_next_attempt` on `next_attempt_time`

**Usage**: Failure protection and recovery for DLQ processing.

---

## Analysis Tables

### snowshoe_detections

**Purpose**: Stores snowshoe attack detection results and analysis metadata.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| detection_time | TIMESTAMP WITH TIME ZONE | NO | NOW() | When detection was made |
| window_start | TIMESTAMP WITH TIME ZONE | NO | - | Analysis window start |
| window_end | TIMESTAMP WITH TIME ZONE | NO | - | Analysis window end |
| confidence_score | VARCHAR(10) | NO | - | Confidence score (stored as string) |
| unique_ips | INTEGER | NO | - | Number of unique IPs |
| single_attempt_ips | INTEGER | NO | - | IPs with single attempts |
| geographic_spread | VARCHAR(10) | NO | - | Geographic spread score |
| indicators | JSONB/TEXT | NO | - | Detection indicators |
| is_likely_snowshoe | BOOLEAN | NO | FALSE | Whether attack is likely snowshoe |
| coordinated_timing | BOOLEAN | NO | FALSE | Whether timing is coordinated |
| recommendation | TEXT | YES | - | Recommended action |
| analysis_metadata | JSONB/TEXT | YES | - | Additional analysis data |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Creation timestamp |

**Indexes**:
- Primary key on `id`
- `ix_snowshoe_detections_detection_time` on `detection_time`
- `ix_snowshoe_detections_window` on `(window_start, window_end)`
- `ix_snowshoe_detections_confidence` on `confidence_score`
- `ix_snowshoe_detections_likely` on `is_likely_snowshoe`
- `ix_snowshoe_detections_created` on `created_at`

**Usage**: Snowshoe attack detection and analysis.

---

### longtail_analysis

**Purpose**: Store longtail analysis results and metadata.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| analysis_time | TIMESTAMP WITH TIME ZONE | NO | NOW() | When analysis was performed |
| window_start | TIMESTAMP WITH TIME ZONE | NO | - | Analysis window start |
| window_end | TIMESTAMP WITH TIME ZONE | NO | - | Analysis window end |
| lookback_days | INTEGER | NO | - | Number of days analyzed |
| confidence_score | FLOAT/REAL | NO | - | Analysis confidence score |
| total_events_analyzed | INTEGER | NO | - | Total events analyzed |
| rare_command_count | INTEGER | NO | 0 | Rare commands found |
| anomalous_sequence_count | INTEGER | NO | 0 | Anomalous sequences found |
| outlier_session_count | INTEGER | NO | 0 | Outlier sessions found |
| emerging_pattern_count | INTEGER | NO | 0 | Emerging patterns found |
| high_entropy_payload_count | INTEGER | NO | 0 | High entropy payloads |
| analysis_results | JSONB/TEXT | NO | - | Analysis results |
| statistical_summary | JSONB/TEXT | YES | - | Statistical summary |
| recommendation | TEXT | YES | - | Recommended action |
| analysis_duration_seconds | FLOAT/REAL | YES | - | Analysis duration |
| memory_usage_mb | FLOAT/REAL | YES | - | Memory usage during analysis |
| data_quality_score | FLOAT/REAL | YES | - | Data quality score |
| enrichment_coverage | FLOAT/REAL | YES | - | Enrichment coverage |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Creation timestamp |

**Indexes**:
- Primary key on `id`
- `ix_longtail_analysis_time` on `analysis_time`
- `ix_longtail_analysis_window` on `(window_start, window_end)`
- `ix_longtail_analysis_confidence` on `confidence_score`
- `ix_longtail_analysis_created` on `created_at`

**Usage**: Longtail analysis for detecting emerging threats and patterns.

---

### longtail_detections

**Purpose**: Store individual longtail detections.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| analysis_id | INTEGER | NO | - | Foreign key to longtail_analysis |
| detection_type | VARCHAR(32) | NO | - | Type of detection |
| session_id | VARCHAR(64) | YES | - | Session identifier |
| event_id | INTEGER | YES | - | Foreign key to raw_events |
| detection_data | JSONB/TEXT | NO | - | Detection details |
| confidence_score | FLOAT/REAL | NO | - | Detection confidence |
| severity_score | FLOAT/REAL | NO | - | Detection severity |
| timestamp | TIMESTAMP WITH TIME ZONE | NO | - | Detection timestamp |
| source_ip | VARCHAR(45) | YES | - | Source IP address |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Creation timestamp |

**Indexes**:
- Primary key on `id`
- `ix_longtail_detections_analysis` on `analysis_id`
- `ix_longtail_detections_type` on `detection_type`
- `ix_longtail_detections_session` on `session_id`
- `ix_longtail_detections_timestamp` on `timestamp`
- `ix_longtail_detections_created` on `created_at`

**Foreign Keys**:
- `analysis_id` → `longtail_analysis(id)` ON DELETE CASCADE
- `event_id` → `raw_events(id)`

**Usage**: Individual detections from longtail analysis.

---

## Password Statistics

### password_statistics

**Purpose**: Aggregated password breach statistics by date for HIBP enrichment tracking.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| date | DATE | NO | - | Date for statistics (unique) |
| total_attempts | INTEGER | NO | 0 | Total password attempts on this date |
| unique_passwords | INTEGER | NO | 0 | Number of unique passwords |
| breached_count | INTEGER | NO | 0 | Number of breached passwords found |
| novel_count | INTEGER | NO | 0 | Number of novel (non-breached) passwords |
| max_prevalence | INTEGER | YES | - | Maximum breach prevalence seen |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Creation timestamp |
| updated_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Last update timestamp |

**Indexes**:
- Primary key on `id`
- Unique constraint on `date`
- `ix_password_statistics_created` on `created_at`

**Usage**: Daily aggregation of password enrichment statistics from HIBP API. Tracks credential stuffing trends vs novel password usage. Used for analyzing attacker behavior patterns and identifying shifts from breached to custom passwords.

**Related Enrichment Data**: Password statistics are also stored per-session in `SessionSummary.enrichment['password_stats']` JSON field, which includes:
- `total_attempts`: Number of login attempts
- `unique_passwords`: Unique passwords used
- `breached_passwords`: Count of breached passwords
- `breach_prevalence_max`: Maximum times any password appeared in breaches
- `novel_password_hashes`: SHA-256 hashes of non-breached passwords
- `password_details`: Array of password attempt details (username, hash, breach status, timestamp)

**Security Notes**:
- Passwords in enrichment JSON are stored as SHA-256 hashes only
- Uses HIBP k-anonymity API (only 5-char SHA-1 prefix sent)
- Tracks attacker passwords from honeypot (not legitimate credentials)

---

### password_tracking

**Purpose**: Track individual passwords with HIBP results and temporal usage patterns.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| password_hash | VARCHAR(64) | NO | - | SHA-256 hash of password (unique) |
| password_text | TEXT | NO | - | Actual password text (attacker credential) |
| breached | BOOLEAN | NO | FALSE | Whether password found in HIBP breaches |
| breach_prevalence | INTEGER | YES | - | Times password appeared in breaches |
| last_hibp_check | TIMESTAMP WITH TIME ZONE | YES | - | Last HIBP API check timestamp |
| first_seen | TIMESTAMP WITH TIME ZONE | NO | NOW() | First time password was seen |
| last_seen | TIMESTAMP WITH TIME ZONE | NO | NOW() | Last time password was seen |
| times_seen | INTEGER | NO | 1 | Total occurrences across all sessions |
| unique_sessions | INTEGER | NO | 1 | Number of unique sessions using password |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Creation timestamp |
| updated_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Last update timestamp |

**Indexes**:
- Primary key on `id`
- Unique index `ix_password_tracking_hash` on `password_hash`
- `ix_password_tracking_last_seen` on `last_seen`
- `ix_password_tracking_breached` on `breached`
- `ix_password_tracking_times_seen` on `times_seen`

**Usage**: Temporal tracking of individual passwords for trend analysis. Enables queries like "most-used passwords", "newly emerged passwords", and "password lifecycle analysis". Pruned automatically via `cowrie-enrich prune` (180-day default retention).

**Pruning Strategy**: Passwords not seen in 180 days are removed to manage table size. Cascade delete removes associated `password_session_usage` records.

---

### password_session_usage

**Purpose**: Junction table linking passwords to sessions for detailed tracking and pivot queries.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| password_id | INTEGER | NO | - | Foreign key to password_tracking.id |
| session_id | VARCHAR(64) | NO | - | Foreign key to session_summaries.session_id |
| username | VARCHAR(256) | YES | - | Username from login attempt |
| success | BOOLEAN | NO | FALSE | Whether login was successful |
| timestamp | TIMESTAMP WITH TIME ZONE | NO | - | Timestamp of login attempt |

**Indexes**:
- Primary key on `id`
- Unique constraint `uq_password_session` on `(password_id, session_id)`
- `ix_password_session_password` on `password_id`
- `ix_password_session_session` on `session_id`
- `ix_password_session_timestamp` on `timestamp`

**Foreign Keys**:
- `password_id` → `password_tracking(id)` ON DELETE CASCADE
- `session_id` → `session_summaries(session_id)`

**Usage**: Enables pivot queries from passwords to sessions and vice versa. Supports queries like "which sessions used password X" and "which passwords were used in session Y". Automatically cleaned when passwords are pruned (cascade delete).

---

## Vector Tables (PostgreSQL with pgvector extension)

### command_sequence_vectors

**Purpose**: Command sequence vectors for similarity search.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| session_id | VARCHAR(64) | NO | - | Session identifier |
| command_sequence | TEXT | NO | - | Command sequence text |
| sequence_vector | VECTOR(128) | YES | - | TF-IDF vectorized commands |
| timestamp | TIMESTAMP WITH TIME ZONE | NO | - | Event timestamp |
| source_ip | INET | NO | - | Source IP address |

**Indexes**:
- Primary key on `id`
- HNSW index on `sequence_vector` for fast similarity search

**Usage**: Vector similarity search for command sequences.

---

### behavioral_vectors

**Purpose**: Behavioral pattern vectors for clustering.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| session_id | VARCHAR(64) | NO | - | Session identifier |
| behavioral_vector | VECTOR(64) | YES | - | Session characteristics vector |
| session_metadata | JSONB | YES | - | Session metadata |
| timestamp | TIMESTAMP WITH TIME ZONE | NO | - | Event timestamp |

**Indexes**:
- Primary key on `id`
- IVFFlat index on `behavioral_vector` for clustering

**Usage**: Behavioral clustering and pattern analysis.

---

## Legacy Tables

### sessions (Legacy)

**Purpose**: Legacy session table from process_cowrie.py.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| session | TEXT | NO | - | Session identifier |
| session_duration | INTEGER | YES | - | Session duration |
| protocol | TEXT | YES | - | Protocol used |
| username | TEXT | YES | - | Username |
| password | TEXT | YES | - | Password |
| timestamp | INTEGER | YES | - | Timestamp |
| source_ip | TEXT | YES | - | Source IP |
| urlhaus_tag | TEXT | YES | - | URLhaus tag |
| asname | TEXT | YES | - | AS name |
| ascountry | TEXT | YES | - | AS country |
| spur_asn | TEXT | YES | - | SPUR ASN |
| spur_asn_organization | TEXT | YES | - | SPUR ASN organization |
| spur_organization | TEXT | YES | - | SPUR organization |
| spur_infrastructure | TEXT | YES | - | SPUR infrastructure |
| spur_client_behaviors | TEXT | YES | - | SPUR client behaviors |
| spur_client_proxies | TEXT | YES | - | SPUR client proxies |
| spur_client_types | TEXT | YES | - | SPUR client types |
| spur_client_count | TEXT | YES | - | SPUR client count |
| spur_client_concentration | TEXT | YES | - | SPUR client concentration |
| spur_client_countries | TEXT | YES | - | SPUR client countries |
| spur_geospread | TEXT | YES | - | SPUR geospread |
| spur_risks | TEXT | YES | - | SPUR risks |
| spur_services | TEXT | YES | - | SPUR services |
| spur_location | TEXT | YES | - | SPUR location |
| spur_tunnel_anonymous | TEXT | YES | - | SPUR tunnel anonymous |
| spur_tunnel_entries | TEXT | YES | - | SPUR tunnel entries |
| spur_tunnel_operator | TEXT | YES | - | SPUR tunnel operator |
| spur_tunnel_type | TEXT | YES | - | SPUR tunnel type |
| total_commands | INTEGER | YES | - | Total commands |
| added | INTEGER | YES | - | Added timestamp |
| hostname | TEXT | YES | - | Hostname |

**Usage**: Legacy compatibility with old process_cowrie.py schema.

---

### commands (Legacy)

**Purpose**: Legacy commands table from process_cowrie.py.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| session | TEXT | NO | - | Session identifier |
| command | TEXT | NO | - | Command text |
| timestamp | INTEGER | YES | - | Timestamp |
| added | INTEGER | YES | - | Added timestamp |
| hostname | TEXT | YES | - | Hostname |

**Usage**: Legacy compatibility with old process_cowrie.py schema.

---

### files_legacy (Legacy)

**Purpose**: Legacy files table from process_cowrie.py.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| session | TEXT | NO | - | Session identifier |
| download_url | TEXT | YES | - | Download URL |
| hash | TEXT | YES | - | File hash |
| file_path | TEXT | YES | - | File path |
| vt_description | TEXT | YES | - | VirusTotal description |
| vt_threat_classification | TEXT | YES | - | VirusTotal classification |
| vt_first_submission | INTEGER | YES | - | VirusTotal first submission |
| vt_hits | INTEGER | YES | - | VirusTotal hits |
| src_ip | TEXT | YES | - | Source IP |
| urlhaus_tag | TEXT | YES | - | URLhaus tag |
| asname | TEXT | YES | - | AS name |
| ascountry | TEXT | YES | - | AS country |
| spur_asn | TEXT | YES | - | SPUR ASN |
| spur_asn_organization | TEXT | YES | - | SPUR ASN organization |
| spur_organization | TEXT | YES | - | SPUR organization |
| spur_infrastructure | TEXT | YES | - | SPUR infrastructure |
| spur_client_behaviors | TEXT | YES | - | SPUR client behaviors |
| spur_client_proxies | TEXT | YES | - | SPUR client proxies |
| spur_client_types | TEXT | YES | - | SPUR client types |
| spur_client_count | TEXT | YES | - | SPUR client count |
| spur_client_concentration | TEXT | YES | - | SPUR client concentration |
| spur_client_countries | TEXT | YES | - | SPUR client countries |
| spur_geospread | TEXT | YES | - | SPUR geospread |
| spur_risks | TEXT | YES | - | SPUR risks |
| spur_services | TEXT | YES | - | SPUR services |
| spur_location | TEXT | YES | - | SPUR location |
| spur_tunnel_anonymous | TEXT | YES | - | SPUR tunnel anonymous |
| spur_tunnel_entries | TEXT | YES | - | SPUR tunnel entries |
| spur_tunnel_operator | TEXT | YES | - | SPUR tunnel operator |
| spur_tunnel_type | TEXT | YES | - | SPUR tunnel type |
| transfer_method | TEXT | YES | - | Transfer method |
| added | INTEGER | YES | - | Added timestamp |
| hostname | TEXT | YES | - | Hostname |

**Usage**: Legacy compatibility with old process_cowrie.py schema.

---

## Views

### dlq_health (PostgreSQL Only)

**Purpose**: Real-time health monitoring for dead letter queue processing.

| Column | Type | Description |
|--------|------|-------------|
| pending_events | BIGINT | Number of unresolved events |
| processed_events | BIGINT | Number of resolved events |
| avg_resolution_time_seconds | NUMERIC | Average resolution time |
| oldest_unresolved_event | TIMESTAMP WITH TIME ZONE | Oldest unresolved event |
| high_retry_events | BIGINT | Events with >5 retries |
| locked_events | BIGINT | Currently locked events |
| malicious_events | BIGINT | Events classified as malicious |
| high_priority_events | BIGINT | High priority events (priority <= 3) |

**Usage**: Monitoring DLQ processing health and performance.

---

## Data Types

### PostgreSQL vs SQLite Differences

| Feature | PostgreSQL | SQLite | Notes |
|---------|------------|--------|-------|
| JSON Storage | JSONB | TEXT | PostgreSQL has native JSON with indexing |
| Boolean | BOOLEAN | INTEGER | SQLite uses 0/1 for boolean values |
| Timestamps | TIMESTAMP WITH TIME ZONE | TIMESTAMP | PostgreSQL has timezone support |
| UUID | UUID | TEXT | PostgreSQL has native UUID type |
| IP Addresses | INET | TEXT | PostgreSQL has native IP type |
| Vectors | VECTOR | N/A | PostgreSQL with pgvector extension |
| Constraints | Full support | Limited | PostgreSQL has comprehensive constraints |
| Triggers | Full support | Limited | PostgreSQL has advanced trigger features |
| Views | Full support | Basic | PostgreSQL has advanced view features |

---

## Relationships

### Primary Relationships

1. **raw_events** → **session_summaries**: One-to-one via `session_id`
2. **raw_events** → **command_stats**: One-to-many via `session_id`
3. **raw_events** → **files**: One-to-many via `session_id`
4. **raw_events** → **longtail_detections**: One-to-many via `event_id`
5. **longtail_analysis** → **longtail_detections**: One-to-many via `analysis_id`

### Foreign Key Constraints

- `longtail_detections.analysis_id` → `longtail_analysis.id` ON DELETE CASCADE
- `longtail_detections.event_id` → `raw_events.id`

---

## Indexes

### Performance Indexes

- **Time-based queries**: `ingest_at`, `created_at`, `timestamp` columns
- **Session-based queries**: `session_id` columns
- **Event type queries**: `event_type` columns
- **Risk assessment**: `risk_score`, `vt_malicious`, `high_risk` columns
- **DLQ processing**: `resolved`, `priority`, `retry_count` columns
- **Vector search**: HNSW and IVFFlat indexes for similarity search

---

## Security Considerations

### Data Protection

- **Payload Checksums**: SHA-256 verification for data integrity
- **Idempotency Keys**: Safe reprocessing with unique identifiers
- **Processing Locks**: Prevent concurrent processing conflicts
- **Audit Trails**: Complete error history and processing attempts

### Access Control

- **User Permissions**: Separate read/write permissions
- **Schema Isolation**: Database-level access control
- **API Security**: Secure API endpoints for data access

---

## Maintenance

### Regular Maintenance Tasks

1. **Index Maintenance**: Rebuild indexes for optimal performance
2. **Statistics Updates**: Update table statistics for query optimization
3. **Vacuum Operations**: Clean up dead tuples and update statistics
4. **Backup Operations**: Regular database backups
5. **Monitoring**: Monitor DLQ health and processing metrics

### Performance Optimization

1. **Query Optimization**: Use appropriate indexes for common queries
2. **Batch Processing**: Process events in batches for efficiency
3. **Connection Pooling**: Use connection pooling for high concurrency
4. **Partitioning**: Consider table partitioning for large datasets

---

## Migration Notes

### Schema Evolution

- **Version 1-6**: Basic schema with core tables
- **Version 7**: Enhanced DLQ features (PostgreSQL only)
- **Version 8**: Snowshoe detection tables
- **Version 9**: Longtail analysis and vector tables
- **Version 10**: Password statistics for HIBP enrichment (October 2025)

### Backward Compatibility

- **Legacy Tables**: Maintained for compatibility with old process_cowrie.py
- **Hybrid Properties**: Backward compatibility for computed columns
- **Migration Path**: Automatic migration from older versions

---

This data dictionary provides comprehensive documentation for the Cowrie Processor database schema. For specific implementation details, refer to the source code in the `cowrieprocessor/db/` directory.


