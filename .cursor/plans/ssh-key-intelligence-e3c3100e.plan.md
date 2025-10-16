<!-- e3c3100e-c07b-437c-ab93-c8cbe7fd9b75 7d3e6ad1-a045-4e62-ade5-59c6126f297d -->
# SSH Key Intelligence Tracking Implementation

## Overview

Implement comprehensive SSH key intelligence tracking following the password enrichment pattern (issue #38). Extract SSH keys from `authorized_keys` manipulation commands, track them across sessions and IPs, and enable campaign correlation analysis.

## Database Schema (Migration v11)

### New Tables

1. **`ssh_key_intelligence`** - Core key tracking with fingerprints, metadata, and temporal patterns
2. **`session_ssh_keys`** - Junction table linking keys to sessions with injection details
3. **`ssh_key_associations`** - Track keys used together (co-occurrence patterns)

### Session Summary Updates

- Add `ssh_key_injections` (INTEGER) - count of key injection attempts
- Add `unique_ssh_keys` (INTEGER) - count of unique keys in session

## Implementation Components

### 1. SSH Key Extractor (`cowrieprocessor/enrichment/ssh_key_extractor.py`)

**Pattern**: Follow `password_extractor.py` structure

**Key Features**:

- Extract keys from direct echo/printf commands
- Detect base64-encoded key injection
- Parse heredoc patterns (`cat << EOF`)
- Support all SSH key types (RSA, Ed25519, ECDSA, DSS)
- Calculate SHA-256 fingerprints (SSH standard)
- Generate deduplication hashes

**Core Methods**:

- `extract_keys_from_command(command: str) -> List[ExtractedSSHKey]`
- `extract_keys_from_events(events: List[RawEvent]) -> List[ExtractedSSHKey]`
- `_extract_direct_keys()`, `_extract_base64_keys()`, `_extract_heredoc_keys()`

### 2. Database Models (`cowrieprocessor/db/models.py`)

**Add three new model classes**:

```python
class SSHKeyIntelligence(Base):
    """Track SSH public keys with intelligence metadata."""
    # Fields: key_type, key_data, key_fingerprint, key_hash, key_comment
    # Temporal: first_seen, last_seen, total_attempts
    # Aggregates: unique_sources, unique_sessions, key_bits

class SessionSSHKeys(Base):
    """Link SSH keys to sessions with injection context."""
    # FKs: session_id, ssh_key_id
    # Context: command_text, injection_method, timestamp, source_ip

class SSHKeyAssociations(Base):
    """Track keys used together (campaign correlation)."""
    # FKs: key_id_1, key_id_2
    # Metrics: co_occurrence_count, same_session_count, same_ip_count
```

### 3. Database Migration (`cowrieprocessor/db/migrations.py`)

**Add `_upgrade_to_v11()` function**:

- Create three new tables with proper indexes
- Alter `session_summaries` to add SSH key columns
- Update `CURRENT_SCHEMA_VERSION = 11`
- Follow existing migration patterns (v8-v10)

### 4. Integration with Loader (`cowrieprocessor/loader/`)

**Real-time extraction during ingestion**:

- Import `SSHKeyExtractor` in loader module
- Extract keys from events containing `authorized_keys`
- Store in database during session processing
- Update session summary counters

**Files to modify**:

- Find the session processing logic (likely in `cowrieprocessor/loader/`)
- Add SSH key extraction step after event ingestion
- Follow password enrichment integration pattern

### 5. CLI Commands

#### A. Enrichment Command (`cowrieprocessor/cli/enrich_ssh_keys.py`)

**New command**: `cowrie-enrich ssh-keys`

**Configuration**: Read database settings from `sensors.toml` (MANDATORY per project rules)

- Use `cowrieprocessor.settings` module to load configuration
- Support both SQLite and PostgreSQL backends
- Follow same pattern as `cowrie-enrich passwords` command

**Subcommands**:

- `backfill` - Process existing events for SSH keys
  - `--sensor NAME` - Sensor name from sensors.toml (required)
  - `--days-back N` - Process last N days (default: all records from earliest)
  - `--batch-size N` - Process in batches (default 100)
  - `--status-dir PATH` - Status output directory (optional override)

- `export` - Export all keys for analysis
  - `--sensor NAME` - Sensor name from sensors.toml (required)
  - `--format csv|json` - Output format (default: json)
  - `--output FILE` - Output file (default: stdout)
  - `--days-back N` - Export keys from last N days (default: all)

**Database Support**:

- SQLite: Use file path from sensors.toml
- PostgreSQL: Use connection string from sensors.toml
- Leverage existing `cowrieprocessor.db.engine` utilities

**Register in `pyproject.toml`**:

```toml
cowrie-enrich-ssh-keys = "cowrieprocessor.cli.enrich_ssh_keys:main"
```

#### B. Report Tool Extension (`cowrieprocessor/cli/report.py`)

**Add new SSH key report types** to existing `cowrie-report` command:

- `ssh-key-summary` - Overview of SSH key activity
  - `--days-back N` - Report period (default: 30)
  - `--output FILE` - Output file
  - Shows: total keys, unique sources, top keys by usage

- `ssh-key-campaigns` - Identify coordinated campaigns
  - `--min-attempts N` - Minimum key usage (default 5)
  - `--min-ips N` - Minimum unique IPs (default 3)
  - `--days-back N` - Analysis period (default: 90)
  - `--output FILE` - Export results

- `ssh-key-detail` - Detailed analysis of specific key
  - `--fingerprint SHA256:...` - Key fingerprint (required)
  - `--show-timeline` - Display usage timeline
  - `--show-associations` - Show related keys
  - `--output FILE` - Output file

**Integration approach**: Add new report handlers to existing report.py module following current pattern

### 6. Analytics Module (`cowrieprocessor/enrichment/ssh_key_analytics.py`)

**Campaign detection and analysis**:

- `identify_campaigns()` - Find coordinated key-based attacks
- `get_key_timeline()` - Usage patterns over time
- `find_related_keys()` - Co-occurrence analysis
- `calculate_geographic_spread()` - IP diversity metrics

### 7. Status Emitter Integration

**Use `StatusEmitter` for all logging** (MANDATORY per project rules):

- Import from `cowrieprocessor.status_emitter`
- Emit metrics during backfill operations
- Record checkpoints for progress tracking
- Log dead letters for extraction failures

## Testing Requirements

### Unit Tests (`tests/unit/test_ssh_key_extractor.py`)

- Test key extraction patterns (direct, base64, heredoc)
- Test all SSH key types (RSA, Ed25519, ECDSA)
- Test fingerprint calculation
- Test invalid input handling
- Test deduplication logic

### Integration Tests (`tests/integration/test_ssh_key_enrichment.py`)

- Test full extraction → storage → retrieval flow
- Test backfill with sample database
- Test campaign detection with mock data
- Test CLI commands end-to-end

### Performance Tests (`tests/performance/test_ssh_key_backfill.py`)

- Test backfill with 10k+ events
- Verify memory usage stays bounded
- Target: 10k events/minute processing

**Coverage Target**: ≥80% (project standard)

## Implementation Order

1. **Database Schema** (1 day)

   - Create model classes in `models.py`
   - Write migration function `_upgrade_to_v11()`
   - Test migration on sample database

2. **SSH Key Extractor** (2-3 days)

   - Implement extraction patterns
   - Add fingerprint calculation
   - Write comprehensive unit tests
   - Test with real Cowrie command samples

3. **Loader Integration** (1 day)

   - Find session processing entry point
   - Add SSH key extraction step
   - Update session summaries
   - Test with sample log files

4. **CLI Command** (2 days)

   - Implement backfill subcommand
   - Implement campaigns subcommand
   - Implement track-key and export
   - Add to pyproject.toml scripts

5. **Analytics Module** (2 days)

   - Campaign detection logic
   - Timeline analysis
   - Association tracking
   - Geographic spread calculation

6. **Testing & Documentation** (2 days)

   - Complete test suite
   - Integration tests
   - Update README with examples
   - Add docstrings and type hints

**Total Estimated Effort**: ~10-11 days

## Key Files to Create/Modify

### New Files

- `cowrieprocessor/enrichment/ssh_key_extractor.py`
- `cowrieprocessor/enrichment/ssh_key_analytics.py`
- `cowrieprocessor/cli/enrich_ssh_keys.py`
- `tests/unit/test_ssh_key_extractor.py`
- `tests/integration/test_ssh_key_enrichment.py`

### Modified Files

- `cowrieprocessor/db/models.py` - Add 3 new model classes
- `cowrieprocessor/db/migrations.py` - Add v11 migration, update CURRENT_SCHEMA_VERSION
- `cowrieprocessor/db/__init__.py` - Export new models
- `pyproject.toml` - Add CLI script entry point
- Loader module (TBD - need to identify exact file during implementation)

## Success Criteria

- ✓ Extract 95%+ of SSH keys from authorized_keys commands
- ✓ Correctly identify key type, fingerprint, and size
- ✓ Detect key reuse across sessions/IPs with 99% accuracy
- ✓ Campaign detection identifies coordinated attacks
- ✓ Backfill processes ≥10k events/minute
- ✓ All tests pass with ≥80% coverage
- ✓ Migration runs cleanly on existing databases

## Security Considerations

- Never log full SSH private keys (only public keys are extracted)
- Sanitize command text before logging (may contain sensitive data)
- Use parameterized SQL queries (SQLAlchemy ORM handles this)
- Validate all extracted key data before storage
- Rate limit any external API calls (if future enhancement)

## Future Enhancements (Post-Implementation)

- Key rotation detection
- Weak key identification (small RSA keys)
- Known attacker key database integration
- ML-based campaign classification
- Real-time alerting for novel keys
- Correlation with malware C2 infrastructure

### To-dos

- [ ] Create database models for SSH key intelligence tables (SSHKeyIntelligence, SessionSSHKeys, SSHKeyAssociations)
- [ ] Write migration v11 to create tables and update session_summaries schema
- [ ] Implement SSHKeyExtractor class with pattern matching for direct, base64, and heredoc key injection
- [ ] Write comprehensive unit tests for SSH key extraction patterns
- [ ] Integrate SSH key extraction into loader pipeline for real-time processing
- [ ] Implement cowrie-enrich ssh-keys backfill command for existing data
- [ ] Create ssh_key_analytics.py with campaign detection and timeline analysis
- [ ] Implement campaigns, track-key, and export subcommands in CLI
- [ ] Write integration tests for full extraction-storage-retrieval flow
- [ ] Update README and add usage examples for SSH key intelligence features