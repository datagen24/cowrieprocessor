<!-- 1f71695a-3ed7-4f7b-8744-226518721d95 db6f1b1a-6c0c-4ca0-b441-7299270a04a1 -->
# Centralize SQL Operations in Database Abstraction Layer

## Current State Analysis

The codebase has SQL scattered across multiple layers:

**Raw SQL with `text()` found in:**

- `cli/cowrie_db.py` - 72+ raw SQL queries for data quality repairs, backfills, and maintenance
- `cli/enrich_passwords.py` - 19+ queries for session/file enrichment iteration
- `cli/health.py` - Health check queries (PRAGMA, SELECT 1)
- `threat_detection/longtail.py` - 7+ queries for command extraction and analysis
- `enrichment/cache.py` - 6+ queries for cache management
- `loader/bulk.py`, `loader/delta.py` - Dialect-specific INSERT operations

**ORM queries with `session.query()` found in:**

- All CLI modules, loaders, enrichment, threat detection, reporting

**Existing DAL components:**

- `db/models.py` - SQLAlchemy ORM models
- `db/engine.py` - Engine creation and configuration
- `db/migrations.py` - Schema migrations
- `db/stored_procedures.py` - PostgreSQL stored procedures (not wrapped)
- `reporting/dal.py` - Reporting repository (good example of DAL pattern)

## Architecture Goals

1. **Centralize complex queries** - Move raw SQL and complex query logic to repository classes
2. **Maintain simple ORM** - Allow `session.query(Model).filter()` in business logic
3. **Database abstraction** - Hide dialect-specific SQL behind repository methods
4. **Gradual migration** - Add deprecation warnings, maintain backward compatibility
5. **Clear boundaries** - Establish when to use DAL vs direct ORM

## Implementation Plan

### Phase 1: Establish Repository Pattern & Core Infrastructure

**Create base repository class** (`db/repository_base.py`):

- Abstract base class with common patterns (dialect detection, session management)
- Utility methods for safe query execution with error handling
- Deprecation warning decorator for marking legacy patterns

**Extend existing reporting DAL** (`reporting/dal.py`):

- Already follows repository pattern - use as reference
- Add deprecation warnings to any raw SQL in CLI that duplicates this

### Phase 2: Create Domain-Specific Repositories

**Create `db/repositories/session_repository.py`:**

- `get_sessions_for_enrichment(limit, filters)` - replaces raw SQL in `cli/enrich_passwords.py`
- `get_sessions_by_time_window(start, end, sensor)` - for threat detection
- `extract_ip_from_session(session_id)` - safe IP extraction with Unicode handling
- `get_session_statistics(filters)` - aggregation queries

**Create `db/repositories/raw_event_repository.py`:**

- `get_events_by_session(session_ids, event_types)` - for analysis modules
- `get_commands_for_sessions(session_ids)` - replaces longtail raw SQL
- `bulk_insert_events(records, conflict_strategy)` - wraps dialect-specific inserts
- `extract_field_from_payload(field, filters)` - safe JSON extraction

**Create `db/repositories/file_repository.py`:**

- `get_files_for_enrichment(limit, status_filter)` - replaces raw SQL in enrichment CLI
- `update_enrichment_status(file_hash, status, data)` - atomic updates
- `bulk_insert_files(files, conflict_strategy)` - wraps loader operations

**Create `db/repositories/dlq_repository.py`:**

- `get_unresolved_events(limit, reason_filter)` - DLQ queries
- `mark_resolved(event_id, repaired_payload)` - atomic resolution
- `insert_dead_letter(record)` - standardized DLQ insertion
- `call_stored_procedure(proc_name, params)` - wraps stored procedure calls

**Create `db/repositories/maintenance_repository.py`:**

- `repair_missing_fields(batch_size, dry_run)` - from `cowrie_db.py`
- `backfill_extracted_columns(batch_size)` - data quality operations
- `vacuum_analyze()` - database maintenance
- `get_health_metrics()` - health check queries

**Create `db/repositories/enrichment_cache_repository.py`:**

- `get_cached_enrichment(service, key)` - cache lookups
- `store_cached_enrichment(service, key, data, ttl)` - cache storage
- `cleanup_expired_cache(service, cutoff_date)` - cache maintenance
- `get_cache_statistics()` - cache metrics

### Phase 3: Update Modules to Use Repositories

**Update `cli/enrich_passwords.py`:**

- Replace `get_session_query()` with `SessionRepository.get_sessions_for_enrichment()`
- Replace `_extract_ip_from_raw_events()` with `SessionRepository.extract_ip_from_session()`
- Replace `get_file_query()` with `FileRepository.get_files_for_enrichment()`
- Add deprecation warnings to old functions, keep as thin wrappers initially

**Update `cli/cowrie_db.py`:**

- Replace `_repair_missing_fields()` raw SQL with `MaintenanceRepository.repair_missing_fields()`
- Replace backfill operations with `MaintenanceRepository.backfill_extracted_columns()`
- Keep CLI as orchestration layer, move SQL to repository
- Maintain existing CLI interface for backward compatibility

**Update `threat_detection/longtail.py`:**

- Replace `_extract_commands_for_sessions()` raw SQL with `RawEventRepository.get_commands_for_sessions()`
- Replace read-only transaction setup with repository method
- Keep analysis logic in detector, move data access to repository

**Update `loader/bulk.py` and `loader/delta.py`:**

- Replace `_bulk_insert_raw_events()` with `RawEventRepository.bulk_insert_events()`
- Replace `_bulk_insert_files()` with `FileRepository.bulk_insert_files()`
- Replace `_persist_dead_letters()` with `DLQRepository.insert_dead_letter()`
- Keep loader orchestration, delegate SQL to repositories

**Update `enrichment/cache.py`:**

- Move complex cache queries to `EnrichmentCacheRepository`
- Keep simple cache lookups in `EnrichmentCacheManager`
- Add repository as dependency injection to cache manager

**Update `cli/health.py`:**

- Replace raw health check queries with `MaintenanceRepository.get_health_metrics()`
- Keep lightweight health check logic in CLI

### Phase 4: Stored Procedure Integration

**Update `db/stored_procedures.py`:**

- Keep stored procedure definitions as-is (they're already in db/)
- Add wrapper methods in `DLQRepository` for calling procedures
- Example: `DLQRepository.process_dlq_with_stored_proc(limit, reason_filter)`

**Update `loader/dlq_stored_proc_cli.py`:**

- Replace direct `connection.execute(text("SELECT process_dlq_events..."))` 
- Use `DLQRepository.process_dlq_with_stored_proc()` instead
- Maintain CLI interface unchanged

### Phase 5: Documentation & Testing

**Create `docs/dal-architecture.md`:**

- Document repository pattern usage
- Guidelines for when to use DAL vs direct ORM
- Examples of proper repository usage
- Migration guide for developers

**Update existing tests:**

- Add repository unit tests in `tests/unit/test_repositories.py`
- Update integration tests to use repositories
- Ensure backward compatibility tests pass

**Add deprecation warnings:**

- Mark old raw SQL functions with `@deprecated` decorator
- Log warnings when legacy patterns are used
- Provide migration path in warning messages

## File Structure After Refactor

```
cowrieprocessor/
├── db/
│   ├── init.py (export repositories)
│   ├── repository_base.py (NEW - base class)
│   ├── repositories/
│   │   ├── __init__.py (NEW)
│   │   ├── session_repository.py (NEW)
│   │   ├── raw_event_repository.py (NEW)
│   │   ├── file_repository.py (NEW)
│   │   ├── dlq_repository.py (NEW)
│   │   ├── maintenance_repository.py (NEW)
│   │   └── enrichment_cache_repository.py (NEW)
│   ├── models.py (unchanged)
│   ├── engine.py (unchanged)
│   ├── migrations.py (unchanged)
│   ├── stored_procedures.py (unchanged - SQL definitions)
│   └── json_utils.py (unchanged)
├── reporting/
│   └── dal.py (reference implementation - minimal changes)
├── cli/ (updated to use repositories)
├── loader/ (updated to use repositories)
├── enrichment/ (updated to use repositories for complex queries)
└── threat_detection/ (updated to use repositories)
```

## Key Design Decisions

**What stays in modules:**

- Simple ORM queries: `session.query(Model).filter(Model.field == value).all()`
- Business logic and orchestration
- Domain-specific validation and processing

**What moves to DAL:**

- Raw SQL with `text()`
- Dialect-specific queries (PostgreSQL vs SQLite)
- Complex joins and aggregations
- Bulk operations with conflict handling
- JSON field extraction (dialect-dependent)

**Backward Compatibility:**

- Old functions become thin wrappers calling repositories
- Deprecation warnings logged but code still works
- No breaking changes to public APIs
- Gradual migration over multiple releases

## Benefits

1. **Maintainability** - SQL centralized, easier to find and modify
2. **Database Portability** - Dialect differences hidden in repositories
3. **Testability** - Repository methods easier to mock and test
4. **Performance** - Optimize queries in one place, benefits all callers
5. **Security** - Centralized input validation and parameterization
6. **Consistency** - Standard patterns for data access across codebase

## Migration Timeline

- **Phase 1-2**: Create repositories (1-2 weeks)
- **Phase 3**: Update modules gradually (2-3 weeks)
- **Phase 4**: Stored procedure integration (1 week)
- **Phase 5**: Documentation and testing (1 week)
- **Total**: 5-7 weeks for complete migration

### To-dos

- [ ] Create repository_base.py with abstract base class, common patterns, and deprecation decorator
- [ ] Create session_repository.py with methods for enrichment, time windows, IP extraction, and statistics
- [ ] Create raw_event_repository.py with methods for event queries, command extraction, and bulk inserts
- [ ] Create file_repository.py with methods for enrichment queries and bulk operations
- [ ] Create dlq_repository.py with methods for DLQ queries and stored procedure wrappers
- [ ] Create maintenance_repository.py with data quality repair and health check methods
- [ ] Create enrichment_cache_repository.py with cache lookup and maintenance methods
- [ ] Update cli/enrich_passwords.py to use SessionRepository and FileRepository
- [ ] Update cli/cowrie_db.py to use MaintenanceRepository for data quality operations
- [ ] Update threat_detection/longtail.py to use RawEventRepository for command extraction
- [ ] Update loader/bulk.py and loader/delta.py to use repositories for bulk operations
- [ ] Update enrichment/cache.py to use EnrichmentCacheRepository for complex queries
- [ ] Update cli/health.py to use MaintenanceRepository for health checks
- [ ] Add stored procedure wrapper methods to DLQRepository and update dlq_stored_proc_cli.py
- [ ] Create docs/dal-architecture.md with usage guidelines and migration guide
- [ ] Add repository unit tests and update integration tests for backward compatibility