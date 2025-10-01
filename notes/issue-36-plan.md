# Issue #36 Implementation Plan: Files Table Backfill & Schema Alignment

## Overview
**Problem**: Current v3 ORM schema does not define a dedicated `files` table, causing VirusTotal enrichment data to persist only in cache. Historical load pipelines report "files downloaded" counts by scanning `raw_events`, but per-hash metadata (VT descriptions, first seen, etc.) has no persistent home.

**Impact**: No place to persist refreshed VirusTotal metadata or flagged counts per hash. Reports/queries relying on `files` need to compute on-the-fly each time (expensive on a 39 GB dataset). Cache-only VT enrichment limits long-term analytics (no historical change tracking, no DB-backed joins with sessions).

## Current Status
- ✅ Issue #36 pulled from GitHub
- 🔄 **PENDING**: Feature branch creation and implementation planning
- 🔄 **PENDING**: Schema design and migration strategy
- 🔄 **PENDING**: Loader enhancements for file processing
- 🔄 **PENDING**: Enrichment pipeline re-enablement

## Implementation Phases

### Phase 1: Schema Design and Migration Strategy
**Objective**: Design the v4 schema with normalized `files` table and create migration path.

**Tasks**:
- [ ] Design `files` table schema with proper columns and indexes
- [ ] Create migration script from v3 to v4 schema
- [ ] Implement backfill logic from `raw_events` (event `cowrie.session.file_download`)
- [ ] Add deduplication logic by hash to prevent duplicates
- [ ] Create schema versioning mechanism (`SCHEMA_VERSION` tracking)
- [ ] Add proper indexes for performance (hash lookup, session joins, VT flags)
- [ ] Design batch processing for large dataset backfill (39 GB)

**Files to Create/Modify**:
- `cowrieprocessor/db/models.py` - Add `Files` table model
- `cowrieprocessor/db/migrations.py` - Add v3→v4 migration logic
- `scripts/migrate_to_v4_schema.py` (NEW) - Schema migration script
- `scripts/backfill_files_table.py` (NEW) - Backfill script for historical data

**Schema Design**:
```python
class Files(Base):
    """Normalized files table with VirusTotal enrichment data."""
    
    __tablename__ = "files"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), nullable=False, index=True)
    shasum = Column(String(64), nullable=False, index=True)  # SHA-256 hash
    filename = Column(String(512), nullable=True)
    file_size = Column(BigInteger, nullable=True)
    download_url = Column(String(1024), nullable=True)
    
    # VirusTotal enrichment fields
    vt_classification = Column(String(128), nullable=True)
    vt_description = Column(Text, nullable=True)
    vt_malicious = Column(Boolean, nullable=False, server_default="0")
    vt_first_seen = Column(DateTime(timezone=True), nullable=True)
    vt_last_analysis = Column(DateTime(timezone=True), nullable=True)
    vt_positives = Column(Integer, nullable=True)
    vt_total = Column(Integer, nullable=True)
    vt_scan_date = Column(DateTime(timezone=True), nullable=True)
    
    # Metadata
    first_seen = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_updated = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    enrichment_status = Column(String(32), nullable=False, server_default="pending")
    
    __table_args__ = (
        UniqueConstraint("session_id", "shasum", name="uq_files_session_hash"),
        Index("ix_files_shasum", "shasum"),
        Index("ix_files_vt_malicious", "vt_malicious"),
        Index("ix_files_enrichment_status", "enrichment_status"),
        Index("ix_files_first_seen", "first_seen"),
    )
```

**Dependencies**:
- `sqlalchemy` for schema management
- `alembic` for migration framework (if adopted)
- `cowrieprocessor.db` models and engine
- `cowrieprocessor.settings` for database configuration

### Phase 2: Loader Enhancements
**Objective**: Update bulk/delta loaders to populate the new `files` table during ingest.

**Tasks**:
- [ ] Extend `BulkLoader` to detect and process `cowrie.session.file_download` events
- [ ] Extend `DeltaLoader` to handle file download events in streaming mode
- [ ] Implement file metadata extraction from Cowrie event payloads
- [ ] Add optional parsing of sensor `downloads/` directory for offline artifacts
- [ ] Create file deduplication logic (same hash across multiple sessions)
- [ ] Add batch processing for file inserts during bulk operations
- [ ] Implement proper error handling for malformed file events
- [ ] Add telemetry for file processing statistics

**Files to Create/Modify**:
- `cowrieprocessor/loader/bulk.py` - Add file processing logic
- `cowrieprocessor/loader/delta.py` - Add streaming file processing
- `cowrieprocessor/loader/file_processor.py` (NEW) - Shared file processing logic
- `tests/unit/test_file_processing.py` (NEW) - Unit tests for file processing

**File Processing Logic**:
```python
def process_file_download_event(event_payload: dict, session_id: str) -> Optional[dict]:
    """Extract file metadata from cowrie.session.file_download event."""
    if event_payload.get("eventid") != "cowrie.session.file_download":
        return None
    
    return {
        "session_id": session_id,
        "shasum": event_payload.get("shasum"),
        "filename": event_payload.get("filename"),
        "file_size": event_payload.get("size"),
        "download_url": event_payload.get("url"),
        "first_seen": parse_timestamp(event_payload.get("timestamp")),
    }
```

**Validation Commands**:
```bash
# Test file processing on sample data
uv run python -c "
from cowrieprocessor.loader.bulk import BulkLoader
from cowrieprocessor.db.engine import get_engine

loader = BulkLoader(get_engine())
# Test with sample file download events
"

# Validate file extraction logic
uv run python -c "
from cowrieprocessor.loader.file_processor import process_file_download_event
# Test with known file download events
"
```

### Phase 3: Enrichment Pipeline Re-enablement
**Objective**: Re-enable file enrichment in `enrichment_refresh.py` once the table exists.

**Tasks**:
- [ ] Update `enrichment_refresh.py` to process files table instead of skipping
- [ ] Implement batch file enrichment with proper rate limiting
- [ ] Add VirusTotal API integration for file hash lookups
- [ ] Ensure cache + DB remain in sync (VT TTLs, retry queues)
- [ ] Add enrichment status tracking (`pending`, `enriched`, `failed`, `skipped`)
- [ ] Implement retry logic for failed enrichments
- [ ] Add progress tracking for large file enrichment batches
- [ ] Create enrichment validation and testing framework

**Files to Create/Modify**:
- `scripts/enrichment_refresh.py` - Re-enable file enrichment
- `cowrieprocessor/enrichment/virustotal.py` (NEW) - VT file enrichment handler
- `cowrieprocessor/enrichment/file_enrichment.py` (NEW) - File enrichment orchestration
- `tests/integration/test_file_enrichment.py` (NEW) - Integration tests

**Enrichment Query Updates**:
```python
# Update FILE_QUERY to use new files table
FILE_QUERY = """
    SELECT DISTINCT shasum, filename, session_id
    FROM files
    WHERE shasum IS NOT NULL 
      AND shasum != ''
      AND enrichment_status IN ('pending', 'failed')
    ORDER BY first_seen ASC
"""
```

**Rate Limiting Strategy**:
- Implement token bucket rate limiter (4 requests/second for VT)
- Add exponential backoff for failed requests
- Cache enrichment results to minimize API calls
- Batch similar requests when possible

### Phase 4: Testing & Migration
**Objective**: Comprehensive testing and safe migration for large datasets.

**Tasks**:
- [ ] Create unit tests for file processing logic
- [ ] Create integration tests for end-to-end file enrichment
- [ ] Add performance tests for large dataset backfill
- [ ] Create migration tooling for production deployment
- [ ] Implement progress logging and resumable backfill
- [ ] Add validation scripts to verify data integrity
- [ ] Create rollback procedures for failed migrations
- [ ] Document migration procedures and troubleshooting

**Files to Create/Modify**:
- `tests/unit/test_files_table.py` (NEW) - Unit tests
- `tests/integration/test_files_enrichment_flow.py` (NEW) - Integration tests
- `tests/performance/test_files_backfill.py` (NEW) - Performance tests
- `scripts/validate_files_migration.py` (NEW) - Migration validation
- `docs/files_table_migration.md` (NEW) - Migration documentation

**Test Commands**:
```bash
# Unit tests for file processing
uv run pytest tests/unit/test_files_table.py -v

# Integration tests for enrichment flow
uv run pytest tests/integration/test_files_enrichment_flow.py -v

# Performance test for backfill
uv run pytest tests/performance/test_files_backfill.py -v

# Validate migration on sample data
uv run python scripts/validate_files_migration.py --sample-data
```

### Phase 5: Production Deployment
**Objective**: Safely deploy the files table to production with the 39 GB dataset.

**Tasks**:
- [ ] Create comprehensive backup of production database
- [ ] Run migration script on production database
- [ ] Execute backfill script for historical file data
- [ ] Re-enable file enrichment with monitoring
- [ ] Validate data integrity post-migration
- [ ] Monitor system performance during and after migration
- [ ] Update reporting queries to use new files table
- [ ] Coordinate with reporting consumers (dashboard queries, ES mappings)

**Production Commands**:
```bash
# IMPORTANT: Always specify the production database path explicitly!
# NOTE: Long-running commands require explicit authorization

# Backup production database
cp /mnt/dshield/data/db/cowrieprocessor.sqlite /mnt/dshield/data/db/cowrieprocessor.sqlite.backup.$(date +%Y%m%d_%H%M%S)

# Run schema migration
uv run python scripts/migrate_to_v4_schema.py --db "sqlite:////mnt/dshield/data/db/cowrieprocessor.sqlite"

# Backfill files table from historical data
uv run python scripts/backfill_files_table.py --db "sqlite:////mnt/dshield/data/db/cowrieprocessor.sqlite" --batch-size 10000

# Validate migration results
uv run python scripts/validate_files_migration.py --db "sqlite:////mnt/dshield/data/db/cowrieprocessor.sqlite"

# Re-enable file enrichment
uv run python scripts/enrichment_refresh.py --files --db "sqlite:////mnt/dshield/data/db/cowrieprocessor.sqlite"
```

## Risk Assessment

### High Risk Items:
- **Database migration failure**: 39GB database schema change could fail partway through
- **Data loss during backfill**: Historical file data might not be properly extracted
- **Performance impact**: Large backfill operations could impact system performance
- **API rate limiting**: VirusTotal enrichment could hit rate limits during bulk operations
- **Cache/DB sync issues**: Enrichment cache might become inconsistent with database

### Mitigation Strategies:
- Comprehensive backup before any destructive operations
- Extensive testing on non-production data first
- Batch processing with progress tracking and resume capability
- Rate limiting and retry logic for API calls
- Validation scripts to ensure data integrity
- Monitoring throughout the migration process
- Staged rollout with feature flags (`USE_NEW_ENRICHMENT`)

## Success Criteria

### Must-Have (Critical):
- [ ] Files table successfully created with proper schema
- [ ] Historical file data backfilled from raw_events
- [ ] File enrichment re-enabled and working
- [ ] No data loss during migration
- [ ] VirusTotal enrichment persisting to database
- [ ] Reports can query files table efficiently

### Should-Have (Important):
- [ ] Migration completes within reasonable time (target: <24 hours)
- [ ] File enrichment rate meets API limits (4 req/sec for VT)
- [ ] Comprehensive test coverage added
- [ ] Monitoring and alerting in place
- [ ] Documentation updated for new schema

### Nice-to-Have (Enhancement):
- [ ] Resume capability for interrupted backfills
- [ ] Parallel processing for improved performance
- [ ] Web interface for monitoring migration progress
- [ ] Automated file enrichment scheduling

## Timeline Estimate

### Week 1:
- [ ] Complete Phase 1 (Schema Design and Migration Strategy)
- [ ] Create migration scripts and backfill logic
- [ ] Unit tests for file processing

### Week 2:
- [ ] Complete Phase 2 (Loader Enhancements)
- [ ] Complete Phase 3 (Enrichment Pipeline Re-enablement)
- [ ] Integration tests for file enrichment flow

### Week 3:
- [ ] Complete Phase 4 (Testing & Migration)
- [ ] Complete Phase 5 (Production Deployment)
- [ ] Validation and monitoring setup

## Dependencies and Blocking Issues

### This Issue Enables:
- Persistent VirusTotal file enrichment data
- Efficient file-based reporting and analytics
- Historical change tracking for file classifications
- Database-backed joins between files and sessions

### Dependencies:
- Database access and permissions for migration
- Backup infrastructure for production safety
- Testing environment with sample data
- VirusTotal API access for enrichment testing

## Communication Plan

### Status Updates:
- Daily standup updates during active development
- Weekly summary for stakeholders
- Immediate notification if critical issues discovered during migration

### Documentation:
- Update `CHANGELOG.md` when files table is deployed
- Create `docs/files_table_migration.md` for migration procedures
- Update database schema documentation
- Update enrichment documentation

## Rollback Plan

### If Migration Issues Discovered:
1. Stop all processing immediately
2. Restore from backup
3. Investigate root cause with full diagnostics
4. Fix issues and retest thoroughly
5. Resume with improved monitoring

### If Enrichment Issues Discovered:
1. Disable file enrichment via feature flag
2. Revert to cache-only enrichment temporarily
3. Investigate and fix enrichment issues
4. Re-enable with monitoring

### Emergency Contacts:
- Development team lead
- Database administrator
- Infrastructure team
- VirusTotal API support (if needed)

## Notes and Observations

### Key Technical Details:
- **Production Database Path**: `/mnt/dshield/data/db/cowrieprocessor.sqlite`
- **Database Size**: 39GB affected database
- **VirusTotal Rate Limit**: 4 requests/second (500 requests/day free tier)
- **File Download Events**: `cowrie.session.file_download` in raw_events
- **Enrichment Cache**: Currently in memory only, needs DB persistence
- **Schema Version**: Moving from v3 to v4 with files table

### Testing Considerations:
- Need representative sample data with file download events
- Must validate file hash extraction accuracy
- Performance testing critical for large dataset backfill
- Edge cases: duplicate files, malformed events, missing hashes

### Future Improvements:
- Consider implementing file deduplication across sessions
- Add support for other file enrichment sources beyond VirusTotal
- Implement file reputation scoring based on multiple sources
- Add file analysis pipeline for downloaded artifacts

### Security Considerations:
- Validate file hashes to prevent injection attacks
- Sanitize filenames and URLs before storage
- Implement proper access controls for file metadata
- Monitor for suspicious file download patterns

### Performance Considerations:
- Index strategy for efficient hash lookups
- Batch processing for large backfill operations
- Memory management for file enrichment operations
- Connection pooling for database operations during migration
