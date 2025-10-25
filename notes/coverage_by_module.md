# Coverage Baseline Analysis
**Date**: 2025-10-18  
**Test Command**: `uv run pytest tests/unit/ --cov=cowrieprocessor`  
**Overall Coverage**: **32%** (3,261 / 10,146 lines)

## Executive Summary
Current coverage is **32%**, significantly below the 80% target. This represents an opportunity for **48 percentage points** of improvement. Priority modules (CLI, Loader, DB critical path) average only **15-20%** coverage.

## Critical Path Modules (Priority 1 - 0-10% Coverage)

### Completely Untested (0% Coverage)
| Module | Lines | Priority Score | Notes |
|--------|-------|---------------|-------|
| `cli/analyze.py` | 512 | 10,000 | Threat detection CLI |
| `cli/enrich_ssh_keys.py` | 375 | 10,000 | SSH key enrichment CLI |
| `cli/file_organizer.py` | 103 | 900 | File organization utility |
| `loader/cowrie_schema.py` | 210 | 10,000 | **CRITICAL** - Event validation |
| `loader/improved_hybrid.py` | 167 | 6,300 | Hybrid JSON loader |
| `loader/dlq_cli.py` | 160 | 900 | DLQ CLI |
| `loader/dlq_enhanced_cli.py` | 160 | 900 | Enhanced DLQ CLI |
| `loader/dlq_stored_proc_cli.py` | 95 | N/A | Stored proc CLI |
| `db/enhanced_dlq_migration.py` | 48 | TBD | DLQ migration (clarify: one-time vs runtime) |
| `db/enhanced_dlq_models.py` | 119 | 0 | DLQ models |
| `db/enhanced_stored_procedures.py` | 40 | TBD | Stored procedures (clarify: PostgreSQL vs cross-DB) |
| `db/stored_procedures.py` | 35 | 1,600 | Base stored procedures |
| `threat_detection/storage.py` | 207 | 0 | Threat storage |

**Total untested lines in critical modules**: ~2,231 lines

### Low Coverage (<25%)
| Module | Lines | Miss | Coverage | Priority Score | Notes |
|--------|-------|------|----------|---------------|-------|
| `cli/cowrie_db.py` | 1,308 | 1,071 | 18% | 8,200 | Database CLI |
| `cli/enrich_passwords.py` | 672 | 590 | 12% | 8,800 | Password enrichment CLI |
| `cli/ingest.py` | 74 | 56 | **24%** | **10,000** | **PRIMARY ENTRY POINT** |
| `cli/db_config.py` | 39 | 30 | 23% | 8,000 | Config resolver |
| `cli/report.py` | 380 | 295 | 22% | 7,800 | Reporting CLI |
| `loader/bulk.py` | 599 | 465 | 22% | 7,800 | Bulk loader |
| `loader/delta.py` | 258 | 222 | 14% | 8,600 | Delta loader |
| `loader/dlq_processor.py` | 429 | 322 | 25% | 7,500 | DLQ processor |
| `db/migrations.py` | 491 | 348 | 29% | 7,100 | Schema migrations |
| `enrichment/legacy_adapter.py` | 57 | 41 | 28% | 5,600 | Enrichment adapter |
| `enrichment/ssh_key_analytics.py` | 176 | 127 | 28% | 6,480 | SSH analytics |
| `threat_detection/botnet.py` | 262 | 231 | 12% | 8,800 | Botnet detection |
| `threat_detection/longtail.py` | 602 | 518 | 14% | 8,600 | Longtail analysis |

**Total low-coverage lines**: ~4,780 lines missed

## High Coverage Modules (>80% - Maintain)
| Module | Lines | Miss | Coverage | Notes |
|--------|-------|------|----------|-------|
| `db/base.py` | 7 | 0 | **100%** | ✅ Well tested |
| `db/json_utils.py` | 52 | 0 | **100%** | ✅ Well tested |
| `db/models.py` | 281 | 11 | **96%** | ✅ Strong coverage |
| `loader/file_processor.py` | 67 | 0 | **100%** | ✅ Well tested |
| `loader/defanging.py` | 131 | 5 | **96%** | ✅ Strong coverage |
| `enrichment/password_extractor.py` | 24 | 0 | **100%** | ✅ Well tested |
| `enrichment/virustotal_quota.py` | 101 | 3 | **97%** | ✅ Strong coverage |
| `enrichment/telemetry.py` | 91 | 5 | **95%** | ✅ Strong coverage |
| `enrichment/ssh_key_extractor.py` | 172 | 22 | **87%** | ✅ Good coverage |
| `enrichment/hibp_client.py` | 68 | 7 | **90%** | ✅ Good coverage |
| `enrichment/cache.py` | 177 | 30 | **83%** | ✅ Good coverage |
| `enrichment/virustotal_handler.py` | 142 | 26 | **82%** | ✅ Good coverage |
| `db/engine.py` | 110 | 17 | **85%** | ✅ Good coverage |
| `db/type_guards.py` | 58 | 9 | **84%** | ✅ Good coverage |
| `reporting/dal.py` | 121 | 2 | **98%** | ✅ Strong coverage |
| `reporting/builders.py` | 95 | 10 | **89%** | ✅ Good coverage |
| `reporting/es_publisher.py` | 27 | 2 | **93%** | ✅ Strong coverage |
| `threat_detection/snowshoe.py` | 181 | 14 | **92%** | ✅ Strong coverage |
| `utils/unicode_sanitizer.py` | 109 | 8 | **93%** | ✅ Strong coverage |
| `settings.py` | 68 | 7 | **90%** | ✅ Good coverage |
| `status_emitter.py` | 121 | 29 | **76%** | 🟡 Expand edge cases |

## Medium Coverage (25-75% - Expand)
| Module | Lines | Miss | Coverage | Actions |
|--------|-------|------|----------|---------|
| `cli/health.py` | 99 | 40 | 60% | Add error path tests |
| `enrichment/rate_limiting.py` | 92 | 29 | 68% | Test edge cases |
| `threat_detection/metrics.py` | 111 | 44 | 60% | Expand calculations |
| `telemetry/otel.py` | 25 | 13 | 48% | Test span creation |
| `__init__.py` | 7 | 4 | 43% | Minor |

## Top 10 Lowest Coverage Modules (Priority Targets)
1. **`cli/analyze.py`**: 0% (512 lines) - Priority Score: 10,000
2. **`cli/enrich_ssh_keys.py`**: 0% (375 lines) - Priority Score: 10,000
3. **`loader/cowrie_schema.py`**: 0% (210 lines) - Priority Score: 10,000 ⚠️  **CRITICAL**
4. **`threat_detection/storage.py`**: 0% (207 lines) - Priority Score: 0
5. **`loader/improved_hybrid.py`**: 0% (167 lines) - Priority Score: 6,300
6. **`loader/dlq_cli.py`**: 0% (160 lines) - Priority Score: 900
7. **`loader/dlq_enhanced_cli.py`**: 0% (160 lines) - Priority Score: 900
8. **`db/enhanced_dlq_models.py`**: 0% (119 lines) - Priority Score: 0
9. **`cli/file_organizer.py`**: 0% (103 lines) - Priority Score: 900
10. **`loader/dlq_stored_proc_cli.py`**: 0% (95 lines) - Priority Score: N/A

## Coverage Gain Estimates (REVISED FROM BASELINE)

### Phase 1 (Priority 1 Modules)
**Target Modules**: 4
- `cli/ingest.py` (24% → 90%): +50 lines = +0.5%
- `loader/cowrie_schema.py` (0% → 95%): +200 lines = +2.0%
- `db/engine.py` (85% → 95%): +10 lines = +0.1%
- `db/base.py` (100% → 100%): Already perfect

**Expected Gain**: +2.6% → **34.6% coverage**

### Phase 1.5 (Parallel - Expand Existing Tests)
**Target**: Edge cases, error paths in existing 428 passing tests
- Expand `settings.py` (90% → 95%): +3 lines = +0.03%
- Expand `status_emitter.py` (76% → 85%): +10 lines = +0.1%
- Expand `enrichment/rate_limiting.py` (68% → 85%): +15 lines = +0.15%
- Expand `enrichment/cache.py` (83% → 90%): +12 lines = +0.12%
- Review 72 test files for missing edge cases: +~100 lines = +1.0%

**Expected Gain**: +1.4% → **36% coverage**

### Phase 2 (Priority 2 Modules)
**Target Modules**: 6
- `cli/db_config.py` (23% → 90%): +26 lines = +0.26%
- `loader/improved_hybrid.py` (0% → 90%): +150 lines = +1.48%
- `enrichment/legacy_adapter.py` (28% → 90%): +35 lines = +0.35%
- `loader/bulk.py` (22% → 60%): +230 lines = +2.27%
- `loader/delta.py` (14% → 60%): +120 lines = +1.18%
- `cli/enrich_passwords.py` (12% → 60%): +320 lines = +3.15%

**Expected Gain**: +8.69% → **44.7% coverage**

### Phase 3 (Priority 3 Modules - IF NEEDED)
**Target Modules**: 4
- `cli/analyze.py` (0% → 70%): +360 lines = +3.55%
- `cli/enrich_ssh_keys.py` (0% → 70%): +262 lines = +2.58%
- `loader/dlq_processor.py` (25% → 70%): +190 lines = +1.87%
- `threat_detection/botnet.py` (12% → 70%): +150 lines = +1.48%

**Expected Gain**: +9.48% → **54.2% coverage**

### Phase 4 (Priority 4 Modules - FILL REMAINING GAP)
**Target**: All remaining 0% modules + expand medium coverage
- 11 remaining untested modules: ~1,200 lines at 60% = +720 lines = +7.1%
- Expand medium coverage modules: ~300 lines = +3.0%
- Integration tests (8 new): ~400 lines indirect coverage = +3.9%

**Expected Gain**: +14% → **68% coverage**

### Phase 5 (Final Push to 80%)
- Deep coverage of high-priority partially-tested modules
- Complex edge cases and error paths
- PostgreSQL-specific tests
- Performance test scenarios

**Expected Gain**: +12% → **80%+ coverage**

## Test Failures (98 failed)
Most failures are due to:
1. **Migration issues**: SQLite vs PostgreSQL syntax (`NOW()`, `TIMESTAMP WITH TIME ZONE`)
2. **Transaction context errors**: "Can't operate on closed transaction" - needs fixture refactoring
3. **Async resource leaks**: Unclosed aiohttp connectors
4. **Module-level execution**: `process_cowrie.py` runs on import

**Action**: These are existing issues, not blockers for new test creation. Fix in parallel.

## Clarifications Required (From Plan)

### 1. `db/enhanced_dlq_migration.py` (48 lines, 0% coverage)
**Question**: One-time schema migration or runtime migration code?
- **If one-time**: Priority 4, test basic execution only
- **If runtime**: Priority 2 (Score ~5,000), test thoroughly

**Recommendation**: Check if it's imported/called during normal operation or just during DB setup.

### 2. `db/stored_procedures.py` & `enhanced_stored_procedures.py` (75 lines, 0% coverage)
**Question**: PostgreSQL-specific or cross-database?
- **If PostgreSQL-only**: Mark `@pytest.mark.postgresql`, Phase 5
- **If cross-database**: Priority 4, test with SQLite

**Recommendation**: Check imports - if `psycopg2` or `CREATE FUNCTION`, it's PostgreSQL-only.

## Next Steps

1. ✅ **Phase 0 Complete**: Baseline measured at 32%
2. **Clarify**: Answer 2 questions above
3. **Phase 1**: Begin with Priority 1 modules (target: 34.6%)
4. **Phase 1.5** (parallel): Expand existing test edge cases (target: 36%)
5. **Phase 2**: Priority 2 modules (target: 44.7%)
6. **Phase 3**: Priority 3 modules (target: 54.2%)
7. **Phase 4**: Fill remaining gap (target: 68%)
8. **Phase 5**: Final push to 80%+

## Success Metrics
- **Current**: 32% (3,261 lines covered)
- **Phase 1 Target**: 35% (3,550 lines)
- **Phase 2 Target**: 45% (4,565 lines)
- **Phase 3 Target**: 55% (5,580 lines)
- **Phase 4 Target**: 70% (7,102 lines)
- **Final Target**: 80%+ (8,117+ lines)

**Gap to close**: 4,856 lines of new test coverage needed

