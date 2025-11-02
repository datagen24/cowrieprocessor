# Archived Tests

This directory contains test files for legacy code that has been moved to `archive/`.

## Archived: 2025-10-25 (Day 23 - Test Suite Refactor)

### Reason for Archiving

These tests were written for legacy code that has been deprecated and moved to `archive/`:
- `process_cowrie.py` → replaced by `cowrie-loader` CLI
- `refresh_cache_and_reports.py` → replaced by modern CLI tools
- `enrichment_handlers.py` → migrated to `cowrieprocessor/enrichment/` package
- `secrets_resolver.py` → migrated to `cowrieprocessor/utils/secrets.py`
- `session_enumerator.py` → migrated to `cowrieprocessor/loader/session_parser.py`

### Test Files Archived

**Unit Tests** (8 files):
- `test_enrichment_handlers.py` - Tests legacy enrichment_handlers module
- `test_process_cowrie.py` - Tests legacy process_cowrie.py main functions
- `test_process_cowrie_simple.py` - Simple smoke tests for process_cowrie
- `test_process_cowrie_types.py` - Type annotation tests for process_cowrie
- `test_refresh_cache_simple.py` - Tests legacy refresh_cache_and_reports.py
- `test_refresh_cache_types.py` - Type tests for refresh_cache_and_reports
- `test_secrets_resolver.py` - Tests old secrets_resolver module
- `test_session_enumerator.py` - Tests old session_enumerator module

**Integration Tests** (5 files):
- `test_enrichment_flow.py` - End-to-end enrichment with legacy handlers
- `test_enrichment_integration.py` - Integration tests for legacy enrichment
- `test_process_cowrie_sqlalchemy2.py` - SQLAlchemy 2.0 migration tests
- `test_refresh_cache_sqlalchemy2.py` - Refresh cache SQLAlchemy tests
- `test_virustotal_integration.py` - VirusTotal integration (legacy)

### Modern Test Replacements

The functionality tested by these archived tests is now covered by:

**Modern Unit Tests**:
- `test_bulk_loader.py` - Tests new ORM-based bulk loader
- `test_delta_loader.py` - Tests new incremental loader
- `test_virustotal_handler.py` - Tests modern VT handler (vt-py SDK)
- `test_hibp_client.py` - Tests HIBP password enrichment
- `test_ssh_key_extractor.py` - Tests SSH key intelligence
- `test_virustotal_quota.py` - Tests VT quota management
- `test_secrets.py` - Tests modern secrets management (utils package)

**Modern Integration Tests**:
- `test_loader_integration.py` - End-to-end ORM loader tests
- `test_enrichment_pipeline.py` - Modern enrichment pipeline tests

### Status

These tests are **deprecated and not maintained**. They will:
- ❌ NOT run in CI/CD pipelines
- ❌ NOT block merges if failing
- ❌ NOT be updated for new features
- ✅ Remain for historical reference only

### Future Action

If legacy code is needed again:
1. Restore code from `archive/` to main codebase
2. Restore corresponding tests from `archive/tests/`
3. Update tests to match current architecture
4. Integrate with modern test suite

Otherwise, these can be **deleted after 6 months** (2026-04-25) if not needed.

---

**Archived by**: Claude Code (Test Suite Refactor Campaign)
**Date**: October 25, 2025
**Branch**: Test-Suite-refactor
**Related**: Phase 3 Refactoring (commits da40dc7, 41fe59b)
