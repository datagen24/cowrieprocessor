# Plan: IPClassifier Service Implementation

**Date**: 2025-11-10
**Feature**: IP Infrastructure Classification Service
**Timeline**: 3-4 weeks (18 implementation tasks)
**Cost**: $0/month (all free data sources)

## Hypothesis

**What**: Implement free IP classification service to populate `snapshot_ip_type` field, enabling 5-8 new infrastructure features for snowshoe spam detection.

**Why This Approach**:
1. **Zero Cost**: All data sources are free (TOR Project, GitHub repos)
2. **ADR-007 Compliant**: Integrates as Pass 4 inside CascadeEnricher
3. **High Accuracy**: 70-99% accuracy across categories
4. **Multi-Tier Caching**: >95% cache hit rate for performance
5. **Proven Patterns**: Follows existing HybridEnrichmentCache pattern

**Design Documents**:
- `docs/design/README_IP_CLASSIFICATION.md` (executive summary)
- `docs/design/ip_classifier_service_specification.md` (50+ pages technical spec)
- `docs/design/ip_classifier_implementation_guide.md` (step-by-step instructions)
- `docs/design/ip_classifier_enrichment_integration.md` (pipeline integration)

## Expected Outcomes (Quantitative)

### Coverage & Accuracy
| Metric | Before | After | Target |
|--------|--------|-------|--------|
| snapshot_ip_type coverage | 0% | 90%+ | ✅ 90% |
| TOR classification accuracy | N/A | 95%+ | ✅ 95% |
| Cloud classification accuracy | N/A | 99%+ | ✅ 99% |
| Datacenter accuracy | N/A | 70-80% | ✅ 70% |
| Residential accuracy | N/A | 70-80% | ✅ 70% |

### Feature Discovery Impact
| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Viable infrastructure features | 2 | 15-18 | 7.5-9x |
| Infrastructure discrimination | 0.145 | 0.8+ | 5.5x |
| Overall discrimination | 0.380 | 0.65+ | 1.7x |
| Feature count | 10-12 | 15-18 | +50% |

### Performance
| Operation | Target (p50) | Target (p99) |
|-----------|--------------|--------------|
| Classify (Redis hit) | <1ms | <2ms |
| Classify (DB hit) | <5ms | <15ms |
| Classify (uncached) | <8ms | <20ms |
| Cache hit rate | >95% | >95% |
| Backfill 38,864 IPs | 6-10 hours | 10 hours |
| Backfill 1.68M sessions | 2-4 hours | 4 hours |

### Testing
| Test Type | Coverage Target | Tests Count |
|-----------|-----------------|-------------|
| Unit tests | 95% | ~65 tests |
| Integration tests | 85% | ~15 tests |
| Performance tests | N/A | ~5 benchmarks |

## Architecture Overview

### Three-Tier Enrichment (ADR-007)

```
Tier 2: IP Inventory ← IPClassifier runs here (Pass 4)
├─ Pass 1: MaxMind GeoIP (offline)
├─ Pass 2: Team Cymru ASN (online)
├─ Pass 3: GreyNoise (online)
└─ Pass 4: IPClassifier (NEW)
    ├─ Priority: TOR → Cloud → Datacenter → Residential → Unknown
    ├─ Cache: Redis L1 (1-24h) → DB L2 (7d) → Disk L3 (30d)
    └─ Output: enrichment['ip_classification']

Tier 3: Session Summaries
└─ snapshot_ip_type = ip_inventory.ip_type (auto-populated)
```

### Components to Implement

1. **Data Models** (`models.py`):
   - `IPType` enum (tor/cloud/datacenter/residential/unknown)
   - `IPClassification` dataclass (frozen, slots)

2. **IP Matchers** (`matchers.py`):
   - `IPMatcher` abstract base class
   - `TorExitNodeMatcher` (O(1) set lookup, hourly updates)
   - `CloudProviderMatcher` (PyTricia trees, daily updates)
   - `DatacenterMatcher` (PyTricia tree, weekly updates)
   - `ResidentialHeuristic` (regex patterns on ASN names)

3. **Multi-Tier Cache** (`cache.py`):
   - `_RedisCache` (L1: 1-24h TTL by type)
   - `_DatabaseCache` (L2: 7-day TTL)
   - `_DiskCache` (L3: 30-day TTL, sharded by IP octets)
   - `HybridIPClassificationCache` (orchestrates L1/L2/L3)

4. **Main Service** (`classifier.py`):
   - `IPClassifier` (priority-ordered classification)
   - Context manager for resource cleanup
   - Statistics tracking

5. **Factory** (`factory.py`):
   - `create_ip_classifier()` (dependency injection)

6. **Integration**:
   - Modify `CascadeEnricher` (add Pass 4)
   - Modify `cascade_factory.py` (wire IPClassifier)
   - Modify `enrich_passwords.py` (add --ips flag)
   - Create `backfill_ip_classification.py` script

## Implementation Phases

### Week 1: Core Components (Days 1-5)
- **Day 1-2**: Data models + base IPMatcher
- **Day 3**: TorExitNodeMatcher
- **Day 4**: CloudProviderMatcher
- **Day 5**: DatacenterMatcher + ResidentialHeuristic

### Week 2: Cache + Service (Days 6-10)
- **Day 6-7**: Multi-tier cache (L1/L2/L3)
- **Day 8-9**: Main IPClassifier service
- **Day 10**: Factory function + unit tests

### Week 3: Integration (Days 11-15)
- **Day 11-12**: CascadeEnricher Pass 4 integration
- **Day 13**: cowrie-enrich refresh --ips flag
- **Day 14**: backfill_ip_classification.py script
- **Day 15**: Integration tests

### Week 4: Validation (Days 16-18)
- **Day 16**: Execute backfill (38K IPs + 1.68M sessions)
- **Day 17**: Re-run Query 15, validate coverage
- **Day 18**: Performance testing, documentation

## Risks & Mitigation

### Risk 1: PyTricia Performance Issues
- **Probability**: Low
- **Impact**: Medium (affects classification speed)
- **Mitigation**: Benchmark early, use disk cache fallback if needed
- **Contingency**: Switch to netaddr library

### Risk 2: Data Source Unavailability
- **Probability**: Medium
- **Impact**: High (classification stale)
- **Mitigation**: Use stale data (up to 7 days), alert ops
- **Contingency**: Fallback to ASN-only classification

### Risk 3: Redis Memory Pressure
- **Probability**: Low
- **Impact**: Medium (reduced cache hit rate)
- **Mitigation**: Type-specific TTLs (1h for TOR, 24h for Cloud)
- **Contingency**: Disable Redis L1, rely on DB L2

### Risk 4: Backfill Takes >14 Hours
- **Probability**: Medium
- **Impact**: Low (operational inconvenience)
- **Mitigation**: Run during off-peak hours, batch commits
- **Contingency**: Split backfill into smaller chunks

### Risk 5: Test Coverage <65%
- **Probability**: Low
- **Impact**: High (CI gate failure)
- **Mitigation**: Write tests in parallel with implementation
- **Contingency**: Defer integration tests to Week 4

## Pre-Implementation Checklist

- [x] Design documents reviewed and approved
- [x] ADR-007 compliance verified (Pass 4 integration)
- [x] Free data sources validated (TOR, Cloud, Datacenter)
- [x] Existing enrichment patterns studied (HybridEnrichmentCache)
- [x] PDCA documentation structure created
- [ ] pyproject.toml updated with new dependencies
- [ ] Package structure created (cowrieprocessor/enrichment/ip_classification/)
- [ ] Git feature branch created (feature/ip-classifier-service)

## Quality Gates

### Phase 1 Gate (After Core Components)
- [ ] All unit tests pass (models, matchers)
- [ ] Type checking passes (mypy --strict)
- [ ] Code coverage ≥95% (core components)
- [ ] Manual validation: TOR matcher correctly identifies 10 known exit nodes

### Phase 2 Gate (After Cache + Service)
- [ ] Multi-tier cache unit tests pass
- [ ] IPClassifier unit tests pass
- [ ] Cache hit rate >90% in benchmark (1000 IPs, 2nd run)
- [ ] Classification latency <20ms p99 (uncached)

### Phase 3 Gate (After Integration)
- [ ] CascadeEnricher Pass 4 integration tests pass
- [ ] Refresh command --ips flag functional
- [ ] Backfill script dry-run successful (100 IPs)
- [ ] No regressions in existing enrichment workflows

### Phase 4 Gate (After Validation)
- [ ] snapshot_ip_type coverage ≥90%
- [ ] Manual validation: 100 random IPs classified correctly (80%+ accuracy)
- [ ] Performance targets met (cache hit rate >95%, latency <20ms p99)
- [ ] All CI gates pass (format, lint, type check, coverage, tests)

## Success Criteria

### Functional (All Must Pass)
1. All 65 unit tests pass (95%+ coverage)
2. All 15 integration tests pass (85%+ coverage)
3. Backfill completes successfully (1.68M sessions updated)
4. snapshot_ip_type coverage ≥90% (from 0%)
5. No regressions in existing enrichment workflows

### Performance (All Must Meet Targets)
1. Cache hit rate ≥95% after warmup
2. Classification latency p99 <20ms
3. Bulk load performance unchanged (<5s per 1K sessions)

### Accuracy (Validated on 100 Samples)
1. TOR classification ≥95% accurate
2. Cloud classification ≥99% accurate
3. Datacenter classification ≥70% accurate
4. Residential classification ≥70% accurate

### Operational (Production Ready)
1. Zero-cost data sources verified ($0/month)
2. Automated daily/weekly updates working
3. Monitoring alerts configured
4. Rollback procedures tested

## Next Actions

**Immediate** (After Plan Approval):
1. Create feature branch: `git checkout -b feature/ip-classifier-service`
2. Update pyproject.toml with dependencies (pytricia, aiohttp)
3. Create package structure: `cowrieprocessor/enrichment/ip_classification/`
4. Begin Phase 1: Implement data models

**Phase 1 Start** (Day 1):
1. Implement `IPType` enum
2. Implement `IPClassification` dataclass
3. Write unit tests for data models
4. Implement `IPMatcher` abstract base class

## References

- Design Specification: `docs/design/ip_classifier_service_specification.md`
- Implementation Guide: `docs/design/ip_classifier_implementation_guide.md`
- Enrichment Integration: `docs/design/ip_classifier_enrichment_integration.md`
- Brainstorming Research: `docs/brainstorming/infrastructure_enrichment_free_sources.md`
- ADR-007: Three-Tier Enrichment Architecture
- Feature Discovery Results: `results/feature_discovery_2025-11-10/15_snapshot_session_clustering.csv`

---

**Plan Status**: ✅ COMPLETE - Ready for Implementation
**Approval**: Pending user confirmation to proceed
**Timeline**: 3-4 weeks (18 tasks, phased approach)
**Risk Level**: Medium (mitigations in place)
