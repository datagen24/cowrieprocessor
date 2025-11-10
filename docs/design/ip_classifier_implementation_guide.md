# IPClassifier Implementation Guide

**Status**: Implementation Ready
**Target Timeline**: 3-4 weeks
**Team Size**: 1-2 developers
**Complexity**: Moderate

## Overview

This guide provides step-by-step implementation instructions for the IPClassifier service, designed to populate the `snapshot_ip_type` field and enable infrastructure-based threat detection features.

## Prerequisites

### Dependencies to Add

Update `pyproject.toml`:

```toml
[project]
dependencies = [
    # ... existing dependencies ...
    "pytricia>=1.0.0",      # CIDR prefix tree for fast IP matching
    "aiohttp>=3.9.0",       # Async HTTP for data source downloads
]

[project.optional-dependencies]
dev = [
    # ... existing dev dependencies ...
    "pytest-asyncio>=0.21.0",  # Async test support
    "responses>=0.24.0",       # HTTP request mocking
]
```

### External Data Sources

Verify access to these free data sources:
- Tor Project: https://check.torproject.org/torbulkexitlist (no auth required)
- Cloud Ranges: https://github.com/rezmoss/cloud-provider-ip-addresses (public repo)
- Datacenter Lists: https://github.com/jhassine/server-ip-addresses (public repo)

## Phase 1: Core Data Structures (Week 1, Days 1-2)

### Task 1.1: Implement Data Models

**File**: `cowrieprocessor/enrichment/ip_classification/models.py`

**Steps**:
1. Create the `IPType` enum with all classification categories
2. Create the `IPClassification` dataclass with validation
3. Add type hints for all fields
4. Write unit tests validating enum values and dataclass construction

**Validation Checklist**:
- [ ] All IPType values are lowercase strings
- [ ] IPClassification.confidence is between 0.0 and 1.0
- [ ] IPClassification.classified_at defaults to current UTC time
- [ ] Frozen dataclass prevents mutation
- [ ] Type hints pass `mypy --strict`

**Test Coverage Target**: 100%

**Example Test**:
```python
def test_ip_classification_validation():
    with pytest.raises(ValueError, match="confidence must be between 0.0 and 1.0"):
        IPClassification(
            ip_type=IPType.CLOUD,
            provider="aws",
            confidence=1.5,  # Invalid
            source="test"
        )
```

### Task 1.2: Implement Base Matcher Interface

**File**: `cowrieprocessor/enrichment/ip_classification/matchers.py`

**Steps**:
1. Create `IPMatcher` abstract base class with `match()` method
2. Add `_download_data()` helper with retry logic
3. Add `_update_data()` method with update frequency check
4. Write unit tests mocking HTTP downloads

**Validation Checklist**:
- [ ] IPMatcher is abstract (cannot instantiate directly)
- [ ] All matchers implement `match(ip: str) -> Optional[dict]`
- [ ] Download retry uses exponential backoff (3 attempts max)
- [ ] Update frequency respects `update_interval_seconds`
- [ ] Type hints pass `mypy --strict`

**Test Coverage Target**: 95%

### Task 1.3: Implement TorExitNodeMatcher

**File**: `cowrieprocessor/enrichment/ip_classification/matchers.py`

**Steps**:
1. Implement O(1) set-based IP lookup
2. Add hourly update logic (3600 seconds)
3. Handle download failures gracefully (use stale data)
4. Write unit tests with mocked Tor bulk list

**Validation Checklist**:
- [ ] Downloads from https://check.torproject.org/torbulkexitlist
- [ ] Updates hourly (can be forced with `force_update=True`)
- [ ] Returns `{'provider': 'tor'}` for matches
- [ ] Returns `None` for non-matches
- [ ] Handles network failures without crashing

**Test Coverage Target**: 95%

**Example Test**:
```python
@pytest.fixture
def mock_tor_list():
    return "1.2.3.4\n5.6.7.8\n9.10.11.12\n"

def test_tor_exit_node_match(mock_tor_list, responses):
    responses.add(
        responses.GET,
        "https://check.torproject.org/torbulkexitlist",
        body=mock_tor_list,
        status=200
    )

    matcher = TorExitNodeMatcher()
    matcher._update_data(force=True)

    assert matcher.match("1.2.3.4") == {'provider': 'tor'}
    assert matcher.match("1.2.3.5") is None
```

## Phase 2: IP Matching Components (Week 1, Days 3-5)

### Task 2.1: Implement CloudProviderMatcher

**File**: `cowrieprocessor/enrichment/ip_classification/matchers.py`

**Steps**:
1. Create 4 PyTricia trees (AWS, Azure, GCP, CloudFlare)
2. Download CSV files from GitHub repo
3. Parse CIDR blocks and populate tries
4. Add daily update logic (86400 seconds)
5. Write unit tests with sample CIDR blocks

**Validation Checklist**:
- [ ] Downloads from https://raw.githubusercontent.com/rezmoss/cloud-provider-ip-addresses/main/
- [ ] Creates separate tries for aws, azure, gcp, cloudflare
- [ ] Updates daily (86400 seconds)
- [ ] Returns `{'provider': <name>, 'region': <region>}` for matches
- [ ] Handles malformed CIDR blocks without crashing
- [ ] Performance: <1ms for O(log n) lookup

**Test Coverage Target**: 90%

**Example Test**:
```python
def test_cloud_provider_match_aws(responses):
    mock_csv = "52.0.0.0/8,us-east-1,ec2\n"
    responses.add(
        responses.GET,
        "https://raw.githubusercontent.com/rezmoss/cloud-provider-ip-addresses/main/aws/ipv4.csv",
        body=mock_csv,
        status=200
    )

    matcher = CloudProviderMatcher()
    matcher._update_data(force=True)

    result = matcher.match("52.1.2.3")
    assert result['provider'] == 'aws'
    assert result['region'] == 'us-east-1'
```

### Task 2.2: Implement DatacenterMatcher

**File**: `cowrieprocessor/enrichment/ip_classification/matchers.py`

**Steps**:
1. Create PyTricia tree for datacenter CIDR blocks
2. Download from jhassine/server-ip-addresses
3. Add weekly update logic (604800 seconds)
4. Write unit tests with sample datacenter ranges

**Validation Checklist**:
- [ ] Downloads from https://raw.githubusercontent.com/jhassine/server-ip-addresses/main/data/datacenters.csv
- [ ] Updates weekly (604800 seconds)
- [ ] Returns `{'provider': <name>}` for matches
- [ ] Handles overlapping CIDR blocks (most specific match wins)

**Test Coverage Target**: 90%

### Task 2.3: Implement ResidentialHeuristic

**File**: `cowrieprocessor/enrichment/ip_classification/matchers.py`

**Steps**:
1. Define regex patterns for residential ASN names
2. Implement AS name pattern matching
3. Add confidence scoring based on pattern strength
4. Write unit tests with diverse ASN names

**Validation Checklist**:
- [ ] Matches patterns: telecom, mobile, broadband, wireless, cable
- [ ] Excludes patterns: hosting, datacenter, server, cloud, colocation
- [ ] Returns `{'asn': <asn>, 'as_name': <name>}` for matches
- [ ] Confidence: 0.7 for strong match, 0.5 for weak match
- [ ] Handles missing ASN data gracefully (returns None)

**Test Coverage Target**: 95%

**Example Test**:
```python
@pytest.mark.parametrize("as_name,expected_match", [
    ("Verizon Wireless", True),
    ("AT&T Broadband", True),
    ("Amazon Web Services", False),
    ("DigitalOcean Hosting", False),
    ("Comcast Cable", True),
])
def test_residential_heuristic(as_name, expected_match):
    heuristic = ResidentialHeuristic()
    result = heuristic.match("1.2.3.4", asn=12345, as_name=as_name)

    if expected_match:
        assert result is not None
        assert result['as_name'] == as_name
    else:
        assert result is None
```

## Phase 3: Multi-Tier Cache (Week 2, Days 1-2)

### Task 3.1: Implement Disk Cache (L3)

**File**: `cowrieprocessor/enrichment/ip_classification/cache.py`

**Steps**:
1. Create `_DiskCache` class with sharded directory structure
2. Implement `get()`, `set()`, `delete()` methods
3. Add TTL enforcement (30 days)
4. Add cleanup of expired entries
5. Write unit tests with temporary directories

**Validation Checklist**:
- [ ] Shards by IP octets (e.g., 1.2.3.4 → cache_dir/1/2/3/4.json)
- [ ] Creates directories automatically
- [ ] Enforces 30-day TTL on reads
- [ ] JSON serialization uses ISO8601 for timestamps
- [ ] Handles missing files gracefully (returns None)
- [ ] Performance: <50ms for disk I/O

**Test Coverage Target**: 95%

### Task 3.2: Implement Database Cache (L2)

**File**: `cowrieprocessor/enrichment/ip_classification/cache.py`

**Steps**:
1. Create `_DatabaseCache` class using existing `enrichment_cache` table
2. Implement `get()`, `set()`, `delete()` methods
3. Use service name `"ip_classification"`
4. Enforce 7-day TTL
5. Write unit tests with test database

**Validation Checklist**:
- [ ] Uses `service = "ip_classification"`
- [ ] Cache key is IP address
- [ ] Stores IPClassification as JSON in `response_data` column
- [ ] Enforces 7-day TTL on reads
- [ ] Performance: <10ms for database query

**Test Coverage Target**: 95%

### Task 3.3: Implement Redis Cache (L1)

**File**: `cowrieprocessor/enrichment/ip_classification/cache.py`

**Steps**:
1. Create `_RedisCache` class with type-specific TTLs
2. Implement `get()`, `set()`, `delete()` methods
3. Add Redis connection management (auto-reconnect)
4. Handle Redis unavailability gracefully
5. Write unit tests with mock Redis client

**Validation Checklist**:
- [ ] TTLs: TOR=1h, Cloud=24h, Datacenter=24h, Residential=24h, Unknown=1h
- [ ] Key format: `ip_classification:{ip_address}`
- [ ] Serializes IPClassification to JSON
- [ ] Returns None if Redis unavailable (fail-safe)
- [ ] Performance: <1ms for Redis GET

**Test Coverage Target**: 90%

### Task 3.4: Implement HybridIPClassificationCache

**File**: `cowrieprocessor/enrichment/ip_classification/cache.py`

**Steps**:
1. Wire L1/L2/L3 caches together
2. Implement cascading `get()` (L1 → L2 → L3 → None)
3. Implement cascading `set()` (write to all tiers)
4. Add cache warming (populate upper tiers on lower hits)
5. Add statistics tracking (hits/misses per tier)
6. Write integration tests

**Validation Checklist**:
- [ ] Check L1 (Redis) first, then L2 (DB), then L3 (Disk)
- [ ] Warm upper tiers on L2/L3 hits
- [ ] Track stats: cache_hits, cache_misses, l1_hits, l2_hits, l3_hits
- [ ] Return None on complete miss
- [ ] Handle tier failures gracefully (skip to next tier)

**Test Coverage Target**: 90%

**Example Test**:
```python
def test_hybrid_cache_l2_hit_warms_l1(test_db_session, tmp_path):
    cache = HybridIPClassificationCache(
        cache_dir=tmp_path,
        db_session=test_db_session,
        enable_redis=True
    )

    classification = IPClassification(
        ip_type=IPType.CLOUD,
        provider="aws",
        confidence=0.99,
        source="cloud_ranges_aws"
    )

    # Store in L2 only (bypass L1)
    cache._db_cache.set("1.2.3.4", classification)

    # Get should hit L2 and warm L1
    result = cache.get("1.2.3.4")
    assert result == classification
    assert cache._stats['l2_hits'] == 1

    # Second get should hit L1
    result2 = cache.get("1.2.3.4")
    assert result2 == classification
    assert cache._stats['l1_hits'] == 1
```

## Phase 4: Main Classifier Service (Week 2, Days 3-5)

### Task 4.1: Implement IPClassifier

**File**: `cowrieprocessor/enrichment/ip_classification/classifier.py`

**Steps**:
1. Create IPClassifier class with all matchers
2. Implement priority-ordered `classify()` method
3. Add cache integration
4. Add statistics tracking
5. Add resource cleanup via context manager
6. Write comprehensive unit tests

**Validation Checklist**:
- [ ] Constructor accepts cache_dir, db_session, enable_redis, URLs
- [ ] Priority order: TOR → Cloud → Datacenter → Residential → Unknown
- [ ] Checks cache before matching
- [ ] Stores results in cache after classification
- [ ] Returns IPClassification for all inputs (never None)
- [ ] Tracks stats: total_lookups, cache_hits, tor_classifications, etc.

**Test Coverage Target**: 95%

**Example Test**:
```python
def test_classifier_priority_tor_over_cloud(mocker, test_db_session, tmp_path):
    # IP that matches both TOR and AWS
    ip = "52.1.2.3"

    mock_tor = mocker.Mock()
    mock_tor.match.return_value = {'provider': 'tor'}

    mock_cloud = mocker.Mock()
    mock_cloud.match.return_value = {'provider': 'aws', 'region': 'us-east-1'}

    classifier = IPClassifier(cache_dir=tmp_path, db_session=test_db_session)
    classifier.tor_matcher = mock_tor
    classifier.cloud_matcher = mock_cloud

    result = classifier.classify(ip)

    # Should return TOR (higher priority)
    assert result.ip_type == IPType.TOR
    assert result.confidence == 0.95

    # Should not check cloud matcher (TOR matched first)
    mock_cloud.match.assert_not_called()
```

### Task 4.2: Implement Factory Function

**File**: `cowrieprocessor/enrichment/ip_classification/factory.py`

**Steps**:
1. Create `create_ip_classifier()` function
2. Add default URL resolution
3. Add dependency injection for testability
4. Write unit tests verifying wiring

**Validation Checklist**:
- [ ] Returns fully initialized IPClassifier
- [ ] Uses default URLs if not provided
- [ ] Accepts optional custom matchers for testing
- [ ] Type hints pass `mypy --strict`

**Test Coverage Target**: 100%

## Phase 5: CascadeEnricher Integration (Week 3, Days 1-2)

### Task 5.1: Add Pass 4 to CascadeEnricher

**File**: `cowrieprocessor/enrichment/cascade_enricher.py`

**Steps**:
1. Add `ip_classifier: IPClassifier` parameter to `__init__()`
2. Create `_enrich_pass4_ip_classification()` method
3. Add Pass 4 call in `refresh_stale_data()`
4. Pass ASN data from Pass 2 to IP classifier
5. Store results in `enrichment['ip_classification']` dict
6. Update unit tests

**Validation Checklist**:
- [ ] Pass 4 runs after Pass 3 (GreyNoise)
- [ ] Passes asn and as_name from Cymru enrichment
- [ ] Stores ip_type, provider, confidence, source, classified_at
- [ ] Uses 1-day staleness check (24 hours)
- [ ] Respects force_refresh parameter

**Test Coverage Target**: 90%

**Example Test**:
```python
def test_cascade_enricher_pass4_ip_classification(
    mock_maxmind, mock_cymru, mock_greynoise, mock_ip_classifier, test_db_session
):
    ip_inventory = IPInventory(ip_address="1.2.3.4")
    test_db_session.add(ip_inventory)
    test_db_session.commit()

    # Mock Cymru returning ASN data
    mock_cymru.enrich.return_value = {'asn': 12345, 'as_name': 'Verizon Wireless'}

    # Mock IP classifier
    mock_ip_classifier.classify.return_value = IPClassification(
        ip_type=IPType.RESIDENTIAL,
        provider=None,
        confidence=0.7,
        source="residential_heuristic"
    )

    enricher = CascadeEnricher(
        maxmind=mock_maxmind,
        cymru=mock_cymru,
        greynoise=mock_greynoise,
        ip_classifier=mock_ip_classifier,
        session=test_db_session
    )

    enricher.refresh_stale_data(ip_inventory, force_refresh=True)

    # Verify Pass 4 was called with ASN data
    mock_ip_classifier.classify.assert_called_once_with(
        ip="1.2.3.4",
        asn=12345,
        as_name="Verizon Wireless"
    )

    # Verify enrichment stored
    assert ip_inventory.enrichment['ip_classification']['ip_type'] == 'residential'
    assert ip_inventory.enrichment['ip_classification']['confidence'] == 0.7
```

### Task 5.2: Update CascadeEnricher Factory

**File**: `cowrieprocessor/enrichment/cascade_factory.py`

**Steps**:
1. Import `create_ip_classifier` function
2. Wire IPClassifier into `create_cascade_enricher()`
3. Add cache_dir parameter
4. Update unit tests

**Validation Checklist**:
- [ ] Calls `create_ip_classifier(cache_dir, db_session)`
- [ ] Passes ip_classifier to CascadeEnricher
- [ ] Uses default cache_dir if not provided
- [ ] Type hints pass `mypy --strict`

**Test Coverage Target**: 100%

## Phase 6: Bulk Processing Integration (Week 3, Days 3-4)

### Task 6.1: Update Bulk Loader

**File**: `cowrieprocessor/loader/bulk.py`

**Steps**:
1. Add IP classification call in `_upsert_session_summaries()`
2. Populate `snapshot_ip_type` field
3. Update unit tests

**Validation Checklist**:
- [ ] Classifies IP after ASN/country enrichment
- [ ] Sets session_summary.snapshot_ip_type to classification.ip_type
- [ ] Handles classification failures gracefully (set to "unknown")

**Test Coverage Target**: 85%

### Task 6.2: Create Backfill Script

**File**: `scripts/backfill_ip_classification.py`

**Steps**:
1. Query all IPs from ip_inventory (38,864 IPs)
2. Classify each IP using IPClassifier
3. Update snapshot_ip_type for sessions via JOIN
4. Commit in batches of 10,000
5. Add progress reporting
6. Write integration test

**Validation Checklist**:
- [ ] Processes all 38,864 unique IPs
- [ ] Updates 1.68M sessions via JOIN on source_ip
- [ ] Batch commits every 10,000 sessions
- [ ] Handles database errors gracefully
- [ ] Estimated runtime: 2-4 hours

**Test Coverage Target**: 80%

**Example Usage**:
```bash
uv run python scripts/backfill_ip_classification.py \
    --db "postgresql://user:pass@host:port/cowrieprocessor" \ <!-- pragma: allowlist secret Documentation not a secret -->
    --cache-dir /mnt/dshield/data/cache/ip_classification \
    --batch-size 10000 \
    --progress
```

## Phase 7: Testing and Validation (Week 3, Day 5)

### Task 7.1: Integration Testing

**File**: `tests/integration/test_ip_classification_flow.py`

**Steps**:
1. Test full pipeline: IP → Classify → Cache → Enrich → Session
2. Verify cache warming across all tiers
3. Verify snapshot_ip_type population
4. Test with 1,000+ sample IPs from production data

**Validation Checklist**:
- [ ] End-to-end flow completes without errors
- [ ] Cache hit rate >95% after warmup
- [ ] All IP types represented in results
- [ ] Performance: <10ms p99 latency for cached lookups

**Test Coverage Target**: 85%

### Task 7.2: Performance Benchmarking

**File**: `tests/performance/test_ip_classifier_performance.py`

**Steps**:
1. Benchmark classify() with 10,000 IPs
2. Benchmark cache hit rates
3. Benchmark data source updates
4. Generate performance report

**Validation Checklist**:
- [ ] Classify (Redis hit): <1ms p50, <2ms p99
- [ ] Classify (DB hit): <5ms p50, <15ms p99
- [ ] Classify (uncached): <8ms p50, <20ms p99
- [ ] Bulk classify 1,000 IPs (95% cached): <100ms p50, <300ms p99

### Task 7.3: Data Quality Validation

**File**: `scripts/validate_ip_classification.py`

**Steps**:
1. Query 1,000 random classified IPs
2. Manually verify 100 samples across all types
3. Calculate accuracy per type
4. Generate validation report

**Validation Checklist**:
- [ ] TOR accuracy: ≥95%
- [ ] Cloud accuracy: ≥99%
- [ ] Datacenter accuracy: ≥70%
- [ ] Residential accuracy: ≥70%
- [ ] Overall coverage: ≥90%

## Phase 8: Documentation and Deployment (Week 4)

### Task 8.1: API Documentation

**File**: `docs/api/ip_classification.md`

**Steps**:
1. Document IPClassifier public API
2. Provide usage examples
3. Document configuration options
4. Add troubleshooting guide

**Deliverables**:
- [ ] Complete API reference
- [ ] 5+ usage examples
- [ ] Configuration guide
- [ ] Troubleshooting section

### Task 8.2: ADR Documentation

**File**: `docs/decisions/adr-NNN-infrastructure-enrichment.md`

**Steps**:
1. Document decision to add IP classification
2. Explain data source selection
3. Justify multi-tier cache design
4. Document performance characteristics

**Deliverables**:
- [ ] Complete ADR with context, decision, consequences
- [ ] Rationale for free data sources
- [ ] Performance benchmarks included

### Task 8.3: Deployment Checklist

**File**: `docs/deployment/ip_classification_deployment.md`

**Steps**:
1. Create pre-deployment checklist
2. Document cron job setup
3. Document monitoring setup
4. Create rollback procedures

**Deliverables**:
- [ ] Pre-deployment checklist (10+ items)
- [ ] Cron job configurations
- [ ] Monitoring alert thresholds
- [ ] Rollback procedures

### Task 8.4: Set Up Cron Jobs

**File**: `/etc/cron.d/ip_classification_updates`

**Steps**:
1. Create hourly TOR update job
2. Create daily cloud/datacenter update jobs
3. Add error notification
4. Test cron execution

**Cron Schedule**:
```cron
# TOR exit nodes - hourly
0 * * * * cowrie uv run python -m cowrieprocessor.enrichment.ip_classification.matchers update-tor >> /var/log/ip_classification/tor_update.log 2>&1

# Cloud providers - daily at 2 AM
0 2 * * * cowrie uv run python -m cowrieprocessor.enrichment.ip_classification.matchers update-cloud >> /var/log/ip_classification/cloud_update.log 2>&1

# Datacenters - weekly on Sunday at 3 AM
0 3 * * 0 cowrie uv run python -m cowrieprocessor.enrichment.ip_classification.matchers update-datacenter >> /var/log/ip_classification/datacenter_update.log 2>&1
```

**Validation Checklist**:
- [ ] Jobs run successfully in test environment
- [ ] Logs captured to /var/log/ip_classification/
- [ ] Error notifications sent to ops team
- [ ] Update success rate 100% over 1 week

## Success Criteria

### Functional Requirements
- [ ] All 65 unit tests pass (95%+ coverage)
- [ ] All 15 integration tests pass (85%+ coverage)
- [ ] Backfill completes successfully (1.68M sessions updated)
- [ ] snapshot_ip_type coverage ≥90% (from 0%)

### Performance Requirements
- [ ] Cache hit rate ≥95% after warmup
- [ ] Classification latency p99 <20ms
- [ ] Bulk classify 1,000 IPs <300ms (95% cached)
- [ ] Data source updates complete <5 minutes each

### Accuracy Requirements
- [ ] TOR classification ≥95% accurate
- [ ] Cloud classification ≥99% accurate
- [ ] Datacenter classification ≥70% accurate
- [ ] Residential classification ≥70% accurate

### Operational Requirements
- [ ] Zero-cost data sources ($0/month verified)
- [ ] Automated daily/weekly updates working
- [ ] Monitoring alerts configured
- [ ] Rollback procedures tested

## Risk Mitigation

### Risk 1: Data Source Unavailability
**Mitigation**: Use stale data (up to 7 days) if updates fail, alert ops team

### Risk 2: Performance Degradation
**Mitigation**: Multi-tier caching with 95%+ hit rate target, monitoring on p99 latency

### Risk 3: Inaccurate Classifications
**Mitigation**: Manual validation of 100 samples per type, accuracy thresholds enforced

### Risk 4: Database Lock Contention
**Mitigation**: Batch commits in backfill (10K per batch), run during off-peak hours

### Risk 5: Redis Memory Pressure
**Mitigation**: Type-specific TTLs (1h for TOR/Unknown, 24h for stable types), monitor memory usage

## Rollback Procedures

### Rollback from Production

If critical issues occur after deployment:

1. **Disable IP Classification Enrichment**:
   ```python
   # In cascade_factory.py, comment out:
   # enricher.ip_classifier = create_ip_classifier(...)
   # OR set environment variable:
   export DISABLE_IP_CLASSIFICATION=true
   ```

2. **Revert snapshot_ip_type Column**:
   ```sql
   UPDATE session_summaries SET snapshot_ip_type = NULL;
   ```

3. **Stop Cron Jobs**:
   ```bash
   sudo systemctl stop cron
   sudo mv /etc/cron.d/ip_classification_updates /etc/cron.d/ip_classification_updates.disabled
   sudo systemctl start cron
   ```

4. **Clear Caches**:
   ```bash
   redis-cli FLUSHDB  # Clear Redis L1
   rm -rf /mnt/dshield/data/cache/ip_classification/*  # Clear disk L3
   # Database L2 will age out naturally
   ```

5. **Revert Code**:
   ```bash
   git revert <commit-hash>
   uv sync
   sudo systemctl restart cowrie-processor
   ```

### Rollback Testing

Before deployment, test rollback procedures in staging:
- [ ] Disable enrichment via feature flag
- [ ] Clear caches successfully
- [ ] Verify system operates without IP classification
- [ ] Re-enable and verify recovery

## Timeline Summary

| Week | Phase | Deliverables | Risk Level |
|------|-------|--------------|------------|
| 1 | Core Components | Models, Matchers, Tests | Low |
| 2 | Cache + Service | Multi-tier cache, IPClassifier | Medium |
| 3 | Integration | CascadeEnricher, Bulk, Backfill | High |
| 4 | Deployment | Docs, Cron, Monitoring | Medium |

**Total Estimated Effort**: 80-100 hours (1-2 developers, 3-4 weeks)

## Post-Deployment

### Week 1 After Deployment
- [ ] Monitor cache hit rates daily (target: ≥95%)
- [ ] Monitor classification latency (target: p99 <20ms)
- [ ] Verify data source updates succeed (target: 100%)
- [ ] Review error logs for unexpected failures

### Week 2-4 After Deployment
- [ ] Run Query 15 with populated snapshot_ip_type
- [ ] Extract 5 new infrastructure features
- [ ] Validate feature discrimination scores (target: ≥0.7)
- [ ] Update feature_discovery_analysis.md

### Month 2-3 After Deployment
- [ ] Test on 22-incident MVP dataset
- [ ] Compare before/after snowshoe detection accuracy
- [ ] Tune classification confidence thresholds if needed
- [ ] Close GitHub issues #60, #61

## Maintenance

### Daily Tasks
- Monitor data source update success rate
- Check cache hit rate metrics
- Review error logs

### Weekly Tasks
- Validate classification accuracy (spot check 20 IPs)
- Review performance metrics (p99 latency trends)
- Check disk cache size (rotate if >10GB)

### Monthly Tasks
- Manual validation of 100 classified IPs
- Update ASN name patterns (new residential ISPs)
- Review and update datacenter lists
- Performance regression testing

## Support and Escalation

### Common Issues

**Issue**: Cache hit rate <80%
- **Cause**: Redis memory eviction or database purge
- **Fix**: Increase Redis memory limit or database TTL

**Issue**: Classification latency >50ms p99
- **Cause**: Network issues downloading data sources
- **Fix**: Check network connectivity, use stale data

**Issue**: Low TOR accuracy (<90%)
- **Cause**: Stale Tor bulk list (>24h old)
- **Fix**: Force update via `update-tor --force`

**Issue**: Backfill script fails at 50%
- **Cause**: Database lock contention or memory exhaustion
- **Fix**: Reduce batch size from 10K to 5K, run during off-peak

### Escalation Path

1. **Developer** (first 24 hours): Troubleshoot using logs and metrics
2. **Tech Lead** (24-48 hours): Architectural review, performance tuning
3. **Product Owner** (48+ hours): Decide on rollback vs fix-forward

## Appendix A: Code Review Checklist

Use this checklist during code reviews:

**General**:
- [ ] Type hints on all functions/methods
- [ ] Google-style docstrings with Args/Returns/Raises
- [ ] No `Any` types without justification
- [ ] Error handling for all external calls (HTTP, Redis, DB)

**Performance**:
- [ ] No N+1 query patterns
- [ ] Batch operations where possible
- [ ] Cache lookups before expensive operations
- [ ] Resource cleanup via context managers

**Testing**:
- [ ] Unit tests cover happy path + error cases
- [ ] Mocks used for external dependencies
- [ ] Integration tests verify end-to-end flow
- [ ] Performance tests validate latency targets

**Security**:
- [ ] No secrets in code (use environment variables)
- [ ] Input validation on all public APIs
- [ ] SQL injection prevention (use ORM)
- [ ] No arbitrary code execution

## Appendix B: Useful Commands

### Development
```bash
# Run all tests with coverage
uv run pytest tests/unit/enrichment/ip_classification/ --cov=cowrieprocessor.enrichment.ip_classification --cov-report=term-missing

# Run integration tests only
uv run pytest tests/integration/test_ip_classification_flow.py -v

# Type checking
uv run mypy cowrieprocessor/enrichment/ip_classification/

# Linting
uv run ruff check cowrieprocessor/enrichment/ip_classification/
uv run ruff format cowrieprocessor/enrichment/ip_classification/
```

### Debugging
```bash
# Check Redis cache
redis-cli KEYS "ip_classification:*"
redis-cli GET "ip_classification:1.2.3.4"

# Check database cache
psql -h ... -d cowrieprocessor -c "SELECT * FROM enrichment_cache WHERE service = 'ip_classification' ORDER BY created_at DESC LIMIT 10;"

# Check disk cache
ls -lah /mnt/dshield/data/cache/ip_classification/1/2/3/

# Force data source update
uv run python -c "from cowrieprocessor.enrichment.ip_classification.matchers import TorExitNodeMatcher; m = TorExitNodeMatcher(); m._update_data(force=True)"
```

### Monitoring
```bash
# Cache hit rate
redis-cli INFO stats | grep keyspace_hits

# Classification latency (from logs)
grep "ip_classification_latency" /var/log/cowrie-processor/enrichment.log | awk '{print $NF}' | sort -n | tail -n 100

# Data source update status
tail -f /var/log/ip_classification/tor_update.log
tail -f /var/log/ip_classification/cloud_update.log
```

---

**Document Version**: 1.0
**Last Updated**: 2025-11-10
**Author**: CowrieProcessor Team
**Status**: Ready for Implementation
