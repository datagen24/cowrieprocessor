# Plan: Cymru Batching Optimization

**Date**: 2025-11-06
**Feature**: Synchronous Cymru batching for IP enrichment
**PM Agent**: Orchestrating implementation via specialized sub-agents

---

## Hypothesis

**Statement**: Implementing synchronous batching for Cymru ASN lookups will eliminate DNS timeout issues and reduce IP enrichment time by 30-50% for large-scale operations.

**Current State**:
```
Problem: Individual DNS lookups per IP
Symptom: "DNS timeout for X.X.X.X, retrying in 1.0s"
Impact: 10,000 IPs taking ~16 minutes with frequent retries
```

**Target State**:
```
Solution: Batch netcat interface (500 IPs per call)
Expected: Zero DNS timeouts
Impact: 10,000 IPs in ~11 minutes (31% faster)
```

**Root Cause**:
- `CascadeEnricher.enrich_ip()` calls `cymru.lookup_asn()` individually (line 192)
- This method tries DNS first, falls back to netcat for single IP
- `CymruClient.bulk_lookup()` exists but is unused (can batch 500 IPs via port 43)

---

## Design: 3-Pass Enrichment Architecture

### Current Flow (Broken)
```python
for ip in ips_to_enrich:
    maxmind_result = cascade.maxmind.lookup_ip(ip)
    cymru_result = cascade.cymru.lookup_asn(ip)  # ⚠️ Individual DNS
    greynoise_result = cascade.greynoise.lookup_ip(ip)
    merge_and_commit(ip, maxmind, cymru, greynoise)
```

### New Flow (3-Pass)
```python
# Pass 1: MaxMind (offline, collect IPs needing Cymru)
ips_needing_cymru = []
for ip in ips_to_enrich:
    maxmind_result = cascade.maxmind.lookup_ip(ip)
    if not maxmind_result or maxmind_result.asn is None:
        ips_needing_cymru.append(ip)

# Pass 2: Cymru bulk lookup (batches of 500 via netcat)
cymru_results = {}
for batch in chunked(ips_needing_cymru, 500):
    batch_results = cascade.cymru.bulk_lookup(batch)  # ✅ Efficient
    cymru_results.update(batch_results)

# Pass 3: Merge + GreyNoise (sequential)
for ip in ips_to_enrich:
    greynoise_result = cascade.greynoise.lookup_ip(ip)
    merge_and_commit(ip, maxmind, cymru, greynoise)
```

---

## Expected Outcomes (Quantitative)

| Metric | Current (1-by-1) | Target (Batched) | Improvement |
|--------|------------------|------------------|-------------|
| **Total Time (10K IPs)** | ~16 minutes | ~11 minutes | **31% faster** |
| **Cymru Phase** | ~16 min (DNS) | ~100 sec (netcat) | **90% faster** |
| **DNS Timeouts** | Frequent | **Zero** | **100% eliminated** |
| **API Efficiency** | 1 IP/call | **500 IPs/call** | **500× better** |
| **User Experience** | Retry warnings | Clean execution | Quality boost |

**Performance Breakdown**:
```
Pass 1 (MaxMind): ~10 seconds (10,000 × 1ms offline lookup)
Pass 2 (Cymru):   ~100 seconds (8,500 IPs ÷ 500 batch × 5s per batch)
Pass 3 (Merge):   ~1,000 seconds (GreyNoise rate-limited 10 req/sec)
Total:            ~19 minutes (vs 27 minutes current)
```

---

## Implementation Strategy

### Sub-Agent Delegation

**1. Backend-Architect** (Primary Implementation)
- **Task**: Refactor `enrich_passwords.py` refresh command (lines 1435-1530)
- **Deliverable**: 3-pass enrichment logic with proper error handling
- **Standards**:
  - SQLAlchemy 2.0 ORM patterns
  - Complete type hints
  - Google-style docstrings
  - Status emitter integration

**2. Quality-Engineer** (Testing & Validation)
- **Task**: Comprehensive test suite for batching logic
- **Deliverables**:
  - Unit tests: Mock `bulk_lookup()` responses
  - Integration tests: 100 IPs on test database
  - Performance test: Measure actual time savings
  - Validation: No DNS timeout warnings in logs
- **Standards**:
  - ≥65% code coverage maintained
  - pytest-mock for API stubbing
  - Offline test execution (no network calls)

**3. Technical-Writer** (Documentation)
- **Task**: Update project documentation
- **Deliverables**:
  - Update CLAUDE.md with batching patterns
  - Usage examples for refresh command
  - Migration guide for existing users
  - Performance comparison table
- **Standards**:
  - Clear, concise language
  - Code examples with comments
  - Before/after comparisons

---

## Code Quality Standards (MANDATORY)

### CI Gates (Must Pass in Order)
1. **Ruff Lint**: `uv run ruff check .` → 0 errors
2. **Ruff Format**: `uv run ruff format --check .` → no changes needed
3. **MyPy**: `uv run mypy .` → 0 type errors
4. **Coverage**: `uv run pytest --cov=. --cov-fail-under=65` → ≥65%
5. **Tests**: All tests must pass

### Code Standards
- **Type Hints**: ALL functions, methods, classes fully typed
- **Docstrings**: Google-style for ALL public methods
- **No `Any` types**: Explicit types or justified comments
- **Error Handling**: Graceful degradation, no silent failures
- **Logging**: Clear progress messages with structured data

---

## ADR Compliance Checklist

### ADR-007: Three-Tier Enrichment Architecture ✅
- [ ] Properly updates `ip_inventory` table (Tier 2)
- [ ] Maintains `enrichment_updated_at` staleness tracking
- [ ] Preserves foreign key to `asn_inventory` (Tier 1)
- [ ] Does not break snapshot columns in `session_summaries` (Tier 3)

### ADR-008: Multi-Source Enrichment Cascade ✅
- [ ] MaxMind → Cymru → GreyNoise order preserved
- [ ] Cache-first strategy maintained (`_is_fresh()` checks)
- [ ] TTL policies respected (MaxMind 7 days, Cymru 90 days, GreyNoise 7 days)
- [ ] Rate limiting enforced (Cymru 100 req/sec, GreyNoise 10 req/sec)

### CLAUDE.md Standards ✅
- [ ] SQLAlchemy 2.0 ORM usage (no raw SQL)
- [ ] Status emitter integration (JSON progress files)
- [ ] Proper batch commits (every 100 records)
- [ ] Transaction rollback on errors
- [ ] Graceful degradation (GreyNoise failures don't stop workflow)

### Project Conventions ✅
- [ ] Use `uv run` for all commands
- [ ] Test with `USE_MOCK_APIS=true` for offline validation
- [ ] Follow existing `enrich_passwords.py` patterns
- [ ] Maintain backward compatibility (no breaking changes)

---

## Risks & Mitigation

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|-----------|
| **Breaking existing workflows** | High | Low | Add feature flag, parallel testing with small batches |
| **Performance regression** | High | Low | Benchmark with 1,000 IPs before/after, rollback if slower |
| **Database transaction deadlocks** | Medium | Low | Proper commit batching (100 records), rollback on error |
| **Status emitter confusion** | Low | Medium | Clear phase labels ("Pass 1/3: MaxMind...") |
| **GreyNoise quota exhaustion** | Medium | Medium | Already rate-limited to 10 req/sec, existing safeguard |
| **MyPy type errors** | Low | Medium | Ensure all new code has complete type hints |

---

## Success Criteria

### Must Have (MVP)
- [ ] **Zero DNS timeout warnings** in logs (primary goal)
- [ ] **30%+ faster enrichment** time measured with 1,000 IPs
- [ ] **All CI gates pass** (ruff, mypy, coverage ≥65%)
- [ ] **Unit tests** for batch logic (mock `bulk_lookup()`)
- [ ] **Integration test** with 100 IPs on test database
- [ ] **Documentation** updated in CLAUDE.md

### Should Have
- [ ] Performance benchmark table in documentation
- [ ] User-facing migration guide
- [ ] Detailed timing logs per phase

### Nice to Have
- [ ] Configurable batch size (default 500, CLI override)
- [ ] Grafana metrics for batch performance
- [ ] Phase-level progress bars

---

## Timeline Estimate

| Phase | Sub-Agent | Time | Deliverable |
|-------|-----------|------|-------------|
| **Planning** | PM Agent | 30 min | This document ✅ |
| **Implementation** | backend-architect | 2-3 hours | 3-pass enrichment in `enrich_passwords.py` |
| **Unit Tests** | quality-engineer | 1 hour | Mock-based batch validation |
| **Integration Tests** | quality-engineer | 1 hour | 100 IPs on test database |
| **Documentation** | technical-writer | 30 min | CLAUDE.md updates |
| **Quality Gates** | quality-engineer | 30 min | Ruff, MyPy, coverage validation |
| **TOTAL** | | **5-7 hours** | Production-ready batching |

---

## Execution Plan

### Phase 1: Implementation (backend-architect)
```yaml
1. Create feature branch:
   git checkout -b feature/cymru-batch-optimization

2. Modify enrich_passwords.py:
   - Lines 1435-1530: Refactor to 3-pass flow
   - Add batch collection logic
   - Integrate bulk_lookup() calls
   - Update status emitter messages

3. Self-validation:
   - Run mypy on modified file (zero errors)
   - Run ruff format and ruff check
   - Verify type hints on all new functions
```

### Phase 2: Testing (quality-engineer)
```yaml
1. Unit tests (tests/unit/test_cymru_batching.py):
   - Mock CymruClient.bulk_lookup()
   - Verify batch sizes (500 IPs per call)
   - Test error handling (partial batch failures)

2. Integration tests (tests/integration/test_refresh_batching.py):
   - Run with --ips 100 on test database
   - Capture logs, verify no DNS timeouts
   - Measure execution time vs baseline

3. Coverage validation:
   - Run pytest with coverage report
   - Ensure ≥65% maintained
   - Add tests for any uncovered branches
```

### Phase 3: Documentation (technical-writer)
```yaml
1. CLAUDE.md updates:
   - Add "Cymru Batching" section to Architecture Overview
   - Update Enrichment section with performance notes
   - Add usage example with --ips flag

2. Create user guide:
   - claudedocs/CYMRU_BATCHING_USER_GUIDE.md
   - Before/after performance comparison
   - Troubleshooting tips
```

### Phase 4: Quality Gates (quality-engineer)
```yaml
1. Pre-commit checks:
   uv run ruff format .
   uv run ruff check .
   uv run mypy .
   uv run pytest --cov=. --cov-fail-under=65

2. Manual validation:
   - Review all warning/error messages
   - Verify deprecation warnings addressed
   - Check for TODO comments (none allowed)

3. Git commit:
   - Conventional commit message
   - Reference CYMRU_BATCHING_STRATEGY.md
   - Include performance benchmark data
```

---

## Monitoring & Validation

### Pre-Implementation Baseline
```bash
# Measure current performance with 1,000 IPs
time uv run cowrie-enrich refresh --ips 1000 --verbose --db "sqlite:///test.db"

# Count DNS timeout warnings
uv run cowrie-enrich refresh --ips 1000 --verbose 2>&1 | grep "DNS timeout" | wc -l
```

### Post-Implementation Validation
```bash
# Measure new performance with 1,000 IPs
time uv run cowrie-enrich refresh --ips 1000 --verbose --db "sqlite:///test.db"

# Verify zero DNS timeouts
uv run cowrie-enrich refresh --ips 1000 --verbose 2>&1 | grep "DNS timeout"
# Expected: No output

# Verify batch messages appear
uv run cowrie-enrich refresh --ips 1000 --verbose 2>&1 | grep "Cymru batch"
# Expected: "Cymru batch 1/2: 500 IPs enriched"
```

### Success Metrics Dashboard
```yaml
Performance:
  - Baseline: 16 minutes for 10K IPs
  - Target: ≤11 minutes for 10K IPs
  - Measured: [TBD after implementation]

Reliability:
  - DNS Timeouts: 0 (was: frequent)
  - Batch Success Rate: >95%
  - Error Recovery: Graceful degradation

Quality:
  - Test Coverage: ≥65%
  - Type Safety: 100% (mypy passing)
  - Documentation: Complete
```

---

## Next Actions

1. **PM Agent**: Create `execution/[feature]/do.md` for implementation log
2. **Delegate to backend-architect**: Begin implementation phase
3. **PM Agent**: Monitor progress via checkpoints every 30 minutes
4. **Continuous logging**: Update `do.md` with trials, errors, solutions

---

**Status**: ✅ Plan Complete
**Next Phase**: Do (Implementation)
**Responsible**: backend-architect sub-agent
**PM Agent Monitoring**: Active
