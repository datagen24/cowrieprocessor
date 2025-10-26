# Cowrie Processor Root Directory Refactoring Recommendations

**Generated**: 2025-10-25
**Branch**: Test-Suite-refactor
**Purpose**: Address technical debt from legacy monolithic code and prepare for production deployment

---

## Executive Summary

After 4 weeks of intensive refactoring toward a modular ORM-based architecture, **28 Python scripts remain in the root directory** with varying levels of relevance. Analysis reveals:

- **CRITICAL ISSUE**: New modular code (`cowrieprocessor/cli/`, `cowrieprocessor/enrichment/`) still imports legacy utilities from root (`enrichment_handlers.py`, `session_enumerator.py`), creating circular dependencies and sync issues
- **13 scripts are obsolete** (deprecated, one-time migrations, or superseded by CLI commands)
- **3 core utilities must be migrated** to `cowrieprocessor/utils/` to break dependency cycles
- **1 production tool** (`orchestrate_sensors.py`) calls deprecated `process_cowrie.py` and needs modernization

---

## Dependency Graph (Current State)

```
┌─────────────────────────────────────────────┐
│ NEW MODULAR SYSTEM                          │
├─────────────────────────────────────────────┤
│ cowrieprocessor/cli/ingest.py              │──┐
│ cowrieprocessor/cli/enrich_passwords.py    │  │
│ cowrieprocessor/enrichment/legacy_adapter.py│  │
└─────────────────────────────────────────────┘  │
                    │                             │
                    │ IMPORTS FROM ROOT (BAD!)    │
                    ▼                             │
┌─────────────────────────────────────────────┐  │
│ LEGACY ROOT UTILITIES                       │◄─┘
├─────────────────────────────────────────────┤
│ enrichment_handlers.py  ◄─── IMPORTED BY 3 NEW MODULES
│ session_enumerator.py   ◄─── USED BY process_cowrie.py
│ secrets_resolver.py     ◄─── USED BY orchestrate_sensors.py
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│ DEPRECATED MONOLITH                         │
├─────────────────────────────────────────────┤
│ process_cowrie.py (2000+ lines)            │
│ orchestrate_sensors.py (calls above)       │
└─────────────────────────────────────────────┘
```

**Problem**: The new system cannot fully replace the old system while it depends on old utilities.

---

## Script Inventory by Category

### 🔴 CRITICAL - Break Dependency Cycles (Priority 1)

| Script | Lines | Issue | Action |
|--------|-------|-------|--------|
| **enrichment_handlers.py** | 500+ | Imported by `cowrieprocessor/cli/ingest.py`, `enrich_passwords.py`, `legacy_adapter.py` | Migrate to `cowrieprocessor/enrichment/handlers.py` |
| **session_enumerator.py** | 400+ | Core session parsing logic used by legacy processor | Migrate to `cowrieprocessor/loader/session_parser.py` |
| **secrets_resolver.py** | 150+ | Multi-backend secret resolver (1Password, AWS, Vault, SOPS) | Migrate to `cowrieprocessor/utils/secrets.py` |

**Impact**: Until these are migrated, the new CLI tools cannot be fully independent.

---

### 🟡 MEDIUM PRIORITY - Deprecate Legacy Processor (Priority 2)

| Script | Status | Modern Replacement | Action |
|--------|--------|-------------------|--------|
| **process_cowrie.py** | 2000+ lines, partially refactored | `cowrie-loader` CLI | Add deprecation warning, update docs, keep for 1-2 releases |
| **orchestrate_sensors.py** | Production tool | None yet | Modernize to call `cowrie-loader` instead of `process_cowrie.py` |
| **es_reports.py** | Has explicit deprecation warning | `cowrie-report` CLI | Move to `/archive/` |
| **submit_vtfiles.py** | Manual VT submission | Should be in enrichment pipeline | Deprecate or integrate into `cowrie-enrich` |
| **cowrie_malware_enrichment.py** | Legacy enrichment | New enrichment pipeline | Move to `/archive/` |
| **refresh_cache_and_reports.py** | Manual cache refresh | `cowrie-enrich refresh` + `cowrie-report` | Move to `/archive/` |

---

### 🟢 LOW PRIORITY - Consolidate Utilities (Priority 3)

#### Production Monitoring Tools (Keep 1-2, consolidate rest)
| Script | Purpose | Recommendation |
|--------|---------|---------------|
| **monitor_progress.py** | Real-time bulk load monitoring | **KEEP** - Most featured, documented in CLAUDE.md |
| **status_dashboard.py** | Simple status file viewer | REMOVE - Redundant with `monitor_progress.py` |

#### PostgreSQL Monitoring (Consolidate into CLI)
| Script | Purpose | Recommendation |
|--------|---------|---------------|
| **collect_postgresql_stats.py** | Stats collector with status emitter | Migrate to `cowrie-db stats --collect` |
| **monitor_postgresql_loading.py** | Real-time PG loading stats | Migrate to `cowrie-db stats --monitor` |
| **quick_pg_stats.py** | Quick stats viewer | Migrate to `cowrie-db stats --quick` |
| **show_pg_stats.py** | One-shot stats display | Migrate to `cowrie-db stats` |
| **enhance_status_files.py** | Augment status with DB metrics | Integrate into status emitter |

**Proposal**: Create `cowrieprocessor/cli/db_stats.py` to consolidate all PostgreSQL monitoring.

---

### ⚪ ARCHIVE - One-Time Use Scripts (Priority 4)

#### Migration Scripts (Move to `/migrations/archive/`)
- `production_migration.py` - SQLite → PostgreSQL migration
- `robust_migration.py` - Enhanced migration with JSON repair
- `test_migration.py` - Migration testing harness
- `cleanup_migration.py` - Migration state reset

#### Test/Debug Scripts (Move to `/scripts/debug/` or delete)
- `test_cowrie_repair.py` - DLQ repair testing
- `test_array_extraction.py` - Array extraction debug
- `test_client_fragment_repair.py` - Fragment repair testing
- `debug_stuck_session.py` - Database lock investigation
- `analyze_performance.py` - Static performance analysis
- `diagnose_enrichment_performance.py` - Live enrichment diagnostics
- `optimize_hibp_client.py` - Code generation for HIBP improvements
- `calculate_migration_function_sizes.py` - Test planning utility

---

## Proposed Directory Structure (After Refactoring)

```
cowrieprocessor/
├── pyproject.toml
├── README.md
├── CLAUDE.md
├── REFACTORING_RECOMMENDATIONS.md  ← This document
│
├── cowrieprocessor/               ← Main package (no changes to structure)
│   ├── cli/
│   │   ├── ingest.py
│   │   ├── report.py
│   │   ├── cowrie_db.py
│   │   ├── db_stats.py           ← NEW: Consolidated PG monitoring
│   │   └── ...
│   ├── db/
│   ├── loader/
│   │   ├── bulk.py
│   │   ├── delta.py
│   │   ├── session_parser.py     ← MIGRATED from session_enumerator.py
│   │   └── ...
│   ├── enrichment/
│   │   ├── handlers.py            ← MIGRATED from enrichment_handlers.py
│   │   ├── virustotal_handler.py
│   │   └── ...
│   ├── utils/
│   │   ├── secrets.py             ← MIGRATED from secrets_resolver.py
│   │   └── ...
│   └── ...
│
├── scripts/                       ← NEW: Non-package scripts
│   ├── production/
│   │   ├── orchestrate_sensors.py ← UPDATED to use cowrie-loader
│   │   ├── monitor_progress.py
│   │   └── sensors.example.toml
│   ├── debug/                     ← Optional: Dev tools
│   │   ├── test_cowrie_repair.py
│   │   ├── debug_stuck_session.py
│   │   └── ...
│   └── migrations/                ← One-time use
│       └── archive/
│           ├── production_migration.py
│           ├── robust_migration.py
│           └── ...
│
├── archive/                       ← Deprecated but preserved
│   ├── process_cowrie.py          ← Legacy processor (deprecated)
│   ├── es_reports.py
│   ├── submit_vtfiles.py
│   ├── cowrie_malware_enrichment.py
│   ├── refresh_cache_and_reports.py
│   └── README.md                  ← Explains what's here and why
│
└── tests/
    └── ...
```

---

## Migration Plan (4-Phase Approach)

### Phase 1: Break Dependency Cycles (Week 1) ⚠️ BLOCKING

**Goal**: Make new CLI tools independent of root directory

1. **Migrate `secrets_resolver.py`**
   ```bash
   git mv secrets_resolver.py cowrieprocessor/utils/secrets.py
   # Update imports in orchestrate_sensors.py
   # Add re-export in cowrieprocessor/__init__.py for compatibility
   ```

2. **Migrate `session_enumerator.py`**
   ```bash
   git mv session_enumerator.py cowrieprocessor/loader/session_parser.py
   # Update imports in process_cowrie.py (if keeping temporarily)
   # Update type hints and add comprehensive tests
   ```

3. **Migrate `enrichment_handlers.py`**
   ```bash
   git mv enrichment_handlers.py cowrieprocessor/enrichment/handlers.py
   # Update imports in:
   #   - cowrieprocessor/cli/ingest.py
   #   - cowrieprocessor/cli/enrich_passwords.py
   #   - cowrieprocessor/enrichment/legacy_adapter.py
   # Remove sys.path hacks in CLI files
   ```

4. **Validation**
   ```bash
   uv run pytest --cov=cowrieprocessor --cov-fail-under=80
   uv run mypy cowrieprocessor/
   uv run ruff check .
   ```

**Success Criteria**: No imports from root directory in `cowrieprocessor/` package

---

### Phase 2: Modernize Production Tools (Week 2)

**Goal**: Update active production tools to use new CLI commands

1. **Update `orchestrate_sensors.py`**
   - Replace `process_cowrie.py` calls with `cowrie-loader delta`
   - Update configuration format to support new flags
   - Add backward compatibility mode (env var `USE_LEGACY_PROCESSOR=true`)
   - Update `sensors.example.toml` with new options

2. **Create `cowrieprocessor/cli/db_stats.py`**
   - Consolidate all PostgreSQL monitoring tools
   - Support modes: `--collect`, `--monitor`, `--quick`, `--one-shot`
   - Integrate into `cowrie-db` command group

3. **Update Documentation**
   - Mark `process_cowrie.py` as deprecated in CLAUDE.md
   - Document migration path for existing deployments
   - Update all examples to use `cowrie-loader`

**Success Criteria**: Production deployments can run without `process_cowrie.py`

---

### Phase 3: Archive Legacy Code (Week 3)

**Goal**: Clean up root directory and preserve history

1. **Create Directory Structure**
   ```bash
   mkdir -p scripts/production scripts/debug scripts/migrations/archive archive
   ```

2. **Move Files**
   ```bash
   # Production tools
   git mv orchestrate_sensors.py scripts/production/
   git mv monitor_progress.py scripts/production/
   git mv sensors.example.toml scripts/production/

   # Migration scripts
   git mv *_migration.py scripts/migrations/archive/

   # Deprecated tools
   git mv process_cowrie.py archive/
   git mv es_reports.py archive/
   git mv submit_vtfiles.py archive/
   git mv cowrie_malware_enrichment.py archive/
   git mv refresh_cache_and_reports.py archive/

   # Optional: Debug tools (or delete)
   git mv test_*.py debug_*.py analyze_*.py diagnose_*.py scripts/debug/
   ```

3. **Create Archive README**
   ```bash
   cat > archive/README.md << 'EOF'
   # Archived Legacy Code

   This directory contains deprecated code preserved for reference.

   ## process_cowrie.py
   **Deprecated**: 2025-10-25
   **Replacement**: `cowrie-loader` CLI
   **Last Working Version**: v0.9.0

   ## es_reports.py
   **Deprecated**: 2025-09-15
   **Replacement**: `cowrie-report` CLI
   ...
   EOF
   ```

4. **Update Entry Points**
   - Remove deprecated commands from `pyproject.toml`
   - Add deprecation warnings to archived scripts
   - Update PATH references in deployment docs

**Success Criteria**: Root directory contains only essential files (pyproject.toml, README.md, CLAUDE.md, CONTRIBUTING.md)

---

### Phase 4: Test & Deploy (Week 4)

**Goal**: Validate changes in production-like environment

1. **Integration Testing**
   ```bash
   # Test full workflow with new CLI
   uv run cowrie-loader bulk /path/to/logs/*.json --db sqlite:///test.db
   uv run cowrie-enrich passwords --last-days 7
   uv run cowrie-report daily 2025-10-25 --publish

   # Test orchestration
   uv run python scripts/production/orchestrate_sensors.py --config test.toml
   ```

2. **Performance Validation**
   - Compare bulk load times: old vs new
   - Verify enrichment cache hit rates
   - Check database query performance

3. **Documentation Updates**
   - Update all README files
   - Create migration guide for users
   - Update deployment automation

4. **Release Notes**
   - Document breaking changes
   - Provide rollback procedure
   - Update compatibility matrix

**Success Criteria**:
- All tests pass (80%+ coverage)
- No regressions in performance
- Documentation complete
- Deployment automation updated

---

## Breaking Changes & Migration Guide

### For Users Currently Running `process_cowrie.py`

**Old Command**:
```bash
python process_cowrie.py \
    --logpath /srv/cowrie/var/log/cowrie \
    --sensor honeypot-a \
    --db /path/to/db.sqlite \
    --email your.email@example.com \
    --summarizedays 1
```

**New Command**:
```bash
uv run cowrie-loader delta /srv/cowrie/var/log/cowrie/*.json \
    --db sqlite:////path/to/db.sqlite \
    --sensor honeypot-a \
    --dshield-email your.email@example.com \
    --status-dir /mnt/dshield/data/logs/status
```

**Key Differences**:
1. Use `uv run` prefix
2. Specify `bulk` or `delta` mode explicitly
3. Database URI format: `sqlite:////absolute/path` or `postgresql://user:pass@host/db`
4. `--email` → `--dshield-email`
5. `--summarizedays` → handled by `--last-days` or file glob patterns

---

### For Users Running `orchestrate_sensors.py`

**Current**: Calls `process_cowrie.py` for each sensor

**After Phase 2**: Will call `cowrie-loader delta` for each sensor

**No Configuration Changes Required**: The TOML format remains compatible, but new options will be available:
```toml
[global]
database = "postgresql://user:pass@host:5432/cowrieprocessor"
mode = "delta"  # or "bulk" for initial load

[[sensors]]
name = "honeypot-a"
logpath = "/mnt/dshield/a/NSM/cowrie"
```

---

## Risk Assessment

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| **Import errors after migration** | High | Medium | Comprehensive test suite, gradual rollout |
| **Performance regression** | Medium | Low | Benchmark before/after, optimize hotpaths |
| **Lost functionality** | High | Low | Feature parity checklist, user testing |
| **Deployment automation breaks** | Medium | Medium | Update CI/CD before release, test in staging |
| **User confusion** | Low | High | Clear migration guide, deprecation warnings |

---

## Testing Checklist

### Phase 1 (Dependency Migration)
- [ ] All imports from root removed from `cowrieprocessor/` package
- [ ] `uv run pytest --cov=cowrieprocessor --cov-fail-under=80` passes
- [ ] `uv run mypy cowrieprocessor/` passes with no errors
- [ ] Legacy `process_cowrie.py` still works (backward compatibility)
- [ ] New CLI commands work: `cowrie-loader`, `cowrie-enrich`, `cowrie-report`

### Phase 2 (Production Modernization)
- [ ] `orchestrate_sensors.py` works with `cowrie-loader`
- [ ] `cowrie-db stats` consolidates all PostgreSQL monitoring
- [ ] Documentation updated: CLAUDE.md, README.md, CONTRIBUTING.md
- [ ] Example configs updated: `sensors.example.toml`

### Phase 3 (Cleanup)
- [ ] Root directory contains only essential files
- [ ] Archived scripts have deprecation warnings
- [ ] Archive README documents all deprecated tools
- [ ] No broken imports or references

### Phase 4 (Validation)
- [ ] Integration tests pass in production-like environment
- [ ] Performance benchmarks show no regression
- [ ] Migration guide tested by external user
- [ ] Release notes complete

---

## Rollback Plan

If critical issues arise after deployment:

1. **Immediate Rollback** (< 1 hour)
   ```bash
   git revert <merge-commit>
   git push
   # Redeploy previous version
   ```

2. **Database Compatibility**
   - Schema migrations are designed to be backward compatible
   - Old `process_cowrie.py` can read new schema (within same major version)

3. **Archive Access**
   - Legacy tools remain in `/archive/` directory
   - Can be temporarily moved back to root if needed

---

## Success Metrics

### Quantitative
- **Code organization**: 0 Python files in root (except archived)
- **Dependency cleanliness**: 0 imports from root in `cowrieprocessor/` package
- **Test coverage**: Maintain 80%+ (currently 58%, target 65% by end of refactor)
- **Performance**: No regression > 5% in bulk load throughput

### Qualitative
- **Developer experience**: No confusion about which tool to use
- **Documentation clarity**: New users can follow migration guide successfully
- **Maintainability**: Clear separation between production, debug, and archived code

---

## Open Questions

1. **Should `monitor_progress.py` become a CLI command** (`cowrie-monitor`)?
   - **Pro**: Consistent interface, better integration
   - **Con**: It's a simple utility, may be overkill

2. **What to do with `submit_vtfiles.py`**?
   - **Option A**: Integrate into `cowrie-enrich` as `--submit-new-files` flag
   - **Option B**: Archive as manual utility
   - **Recommendation**: Option A - fits enrichment workflow

3. **Should PostgreSQL monitoring be part of `cowrie-db` or separate `cowrie-monitor` command**?
   - **Recommendation**: Part of `cowrie-db stats` for cohesion

4. **Timeline for removing `process_cowrie.py` completely**?
   - **Recommendation**: Keep in archive for 2 major versions (6-12 months), then remove

---

## Next Steps

1. **Review this document** with project stakeholders
2. **Prioritize phases** based on production needs
3. **Create GitHub issues** for each migration task
4. **Update project board** with timeline
5. **Begin Phase 1** migration work

---

## References

- **CLAUDE.md**: Project documentation and conventions
- **CONTRIBUTING.md**: Development workflow
- **Git History**: Original issue tracking for this refactor
- **Test Coverage Report**: Current state at 58%, targeting 65%+

---

**Document Author**: Claude Code Analysis
**Review Status**: Draft
**Target Completion**: Week of 2025-11-01
