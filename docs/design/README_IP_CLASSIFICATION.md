# IPClassifier Design Documentation

**Status**: Design Complete ✅
**Date**: 2025-11-10
**Timeline**: 3-4 weeks implementation
**Cost**: $0/month (all free data sources)

## Quick Links

- **[Service Specification](ip_classifier_service_specification.md)** - Complete technical design (50+ pages)
- **[Implementation Guide](ip_classifier_implementation_guide.md)** - Step-by-step build instructions
- **[Enrichment Integration](ip_classifier_enrichment_integration.md)** - How it plugs into existing workflows

## What This Solves

**Problem**: snapshot_ip_type is 0% populated, blocking 5-8 critical infrastructure features for snowshoe spam detection

**Solution**: Free IP classification service that identifies:
- TOR exit nodes (95%+ accuracy)
- Cloud providers: AWS, Azure, GCP, CloudFlare (99%+ accuracy)
- Datacenters and hosting providers (70-80% accuracy)
- Residential ISPs via ASN heuristics (70-80% accuracy)

**Impact**:
- snapshot_ip_type coverage: 0% → 90%+
- Infrastructure features: 2 viable → 15-18 viable
- Feature discrimination: 0.145 → 0.8+ (5.5x improvement)
- Cost: $0/month (all free data sources)

## Architecture Summary

### Three-Tier Enrichment (ADR-007)

```
Tier 1: ASN Inventory
└─ Organization metadata (yearly updates)

Tier 2: IP Inventory ← IPClassifier runs here (Pass 4)
├─ Pass 1: MaxMind GeoIP (offline)
├─ Pass 2: Team Cymru ASN (online)
├─ Pass 3: GreyNoise (online)
└─ Pass 4: IPClassifier (NEW)
    ├─ Priority: TOR → Cloud → Datacenter → Residential → Unknown
    ├─ Cache: Redis L1 (1-24h) → DB L2 (7d) → Disk L3 (30d)
    └─ Output: enrichment['ip_classification']
              ├─ ip_type: "cloud"
              ├─ provider: "aws"
              ├─ confidence: 0.99
              └─ source: "cloud_ranges_aws"

Tier 3: Session Summaries
└─ Immutable snapshots from ip_inventory.ip_type (hybrid property)
   └─ snapshot_ip_type = ip_inventory.ip_type (auto-populated)
```

### Integration Points

**IPClassifier runs INSIDE CascadeEnricher as Pass 4** - NOT as a separate step after.

**Automatically invoked by**:
1. **Bulk Load** (`cowrie-loader bulk`) - reads ip_inventory.ip_type for snapshots
2. **Delta Load** (`cowrie-loader delta`) - same as bulk
3. **Refresh** (`cowrie-enrich refresh --ips N`) - calls CascadeEnricher for stale IPs
4. **Backfill** (`scripts/backfill_ip_classification.py`) - one-time enrichment of 38K IPs + 1.68M sessions

## Key Components

### 1. Data Models (`models.py`)
```python
class IPType(str, Enum):
    TOR = "tor"
    CLOUD = "cloud"
    DATACENTER = "datacenter"
    RESIDENTIAL = "residential"
    UNKNOWN = "unknown"

@dataclass(slots=True, frozen=True)
class IPClassification:
    ip_type: IPType
    provider: Optional[str]
    confidence: float  # 0.0 to 1.0
    source: str
    classified_at: datetime
```

### 2. IP Matchers (`matchers.py`)
- **TorExitNodeMatcher**: O(1) set lookup, hourly updates
- **CloudProviderMatcher**: PyTricia trees for AWS/Azure/GCP/CloudFlare, daily updates
- **DatacenterMatcher**: PyTricia tree for hosting providers, weekly updates
- **ResidentialHeuristic**: Regex patterns on ASN names (telecom, broadband, mobile)

### 3. Multi-Tier Cache (`cache.py`)
- **L1 (Redis)**: 1h TTL (TOR/Unknown), 24h TTL (Cloud/DC/Residential)
- **L2 (Database)**: 7-day TTL in enrichment_cache table
- **L3 (Disk)**: 30-day TTL, sharded by IP octets (e.g., 1.2.3.4 → cache_dir/1/2/3/4.json)
- **Cache warming**: Upper tiers populated on lower hits
- **Hit rate target**: >95% after warmup

### 4. Main Classifier (`classifier.py`)
```python
class IPClassifier:
    def classify(
        self,
        ip: str,
        asn: Optional[int] = None,
        as_name: Optional[str] = None,
    ) -> IPClassification:
        # Priority 1: Check cache (3-tier)
        cached = self.cache.get(ip)
        if cached:
            return cached

        # Priority 2: TOR (95%+ accuracy)
        if self.tor_matcher.match(ip):
            result = IPClassification(IPType.TOR, "tor", 0.95, "tor_bulk_list")
            self.cache.store(ip, result)
            return result

        # Priority 3: Cloud (99%+ accuracy)
        cloud_match = self.cloud_matcher.match(ip)
        if cloud_match:
            result = IPClassification(IPType.CLOUD, cloud_match['provider'], 0.99, f"cloud_ranges_{provider}")
            self.cache.store(ip, result)
            return result

        # Priority 4: Datacenter (70-80% accuracy)
        # Priority 5: Residential (70-80% accuracy)
        # Priority 6: Unknown fallback
```

## Free Data Sources

| Source | Provider | Update | Accuracy | Cost |
|--------|----------|--------|----------|------|
| TOR Exit Nodes | Tor Project | Hourly | 95%+ | $0 |
| AWS/Azure/GCP | GitHub: rezmoss/cloud-provider-ip-addresses | Daily | 99%+ | $0 |
| Datacenters | GitHub: jhassine/server-ip-addresses | Daily | 70-80% | $0 |
| Residential | ASN name heuristics | N/A | 70-80% | $0 |

**Total Cost**: $0/month ✅

## Performance Targets

| Operation | Target (p50) | Target (p99) |
|-----------|--------------|--------------|
| Classify (Redis hit) | <1ms | <2ms |
| Classify (DB hit) | <5ms | <15ms |
| Classify (uncached) | <8ms | <20ms |
| Bulk classify 1K IPs (95% cached) | <100ms | <300ms |
| Backfill 38,864 IPs | 6-10 hours | N/A |
| Backfill 1.68M sessions | 2-4 hours | N/A |

## Implementation Roadmap

### Week 1: Core Components
- [ ] Implement data models (IPType, IPClassification)
- [ ] Implement all IP matchers (TOR, Cloud, Datacenter, Residential)
- [ ] Unit tests (95% coverage target)

### Week 2: Cache + Service
- [ ] Implement multi-tier cache (L1/L2/L3)
- [ ] Implement main IPClassifier service
- [ ] Integrate with CascadeEnricher as Pass 4
- [ ] Update cascade_factory.py

### Week 3: Integration + Backfill
- [ ] Modify `cowrie-enrich refresh` to add --ips flag
- [ ] Create backfill script (38K IPs + 1.68M sessions)
- [ ] Execute backfill on production database
- [ ] Validate snapshot_ip_type coverage (90%+ target)

### Week 4: Validation + Deployment
- [ ] Re-run Query 15 with populated snapshot_ip_type
- [ ] Extract 5 new infrastructure features
- [ ] Validate discrimination scores (0.7+ target)
- [ ] Set up cron jobs for data source updates
- [ ] Create ADR documentation
- [ ] Close GitHub issues #60, #61

## Usage Examples

### 1. Initial Backfill (One-Time)
```bash
# Enrich all IPs and populate snapshots (8-14 hours total)
uv run python scripts/backfill_ip_classification.py \
    --db "postgresql://user:pass@host:port/cowrieprocessor" \ <!-- pragma: allowlist secret Documentation example -->
    --cache-dir /mnt/dshield/data/cache/ip_classification \
    --batch-size 10000 \
    --progress
```

### 2. Refresh Stale IPs (Ongoing)
```bash
# Refresh all stale IPs (>30 days old)
uv run cowrie-enrich refresh \
    --sessions 0 \
    --files 0 \
    --ips 0 \
    --verbose

# Refresh top 1,000 most active IPs
uv run cowrie-enrich refresh \
    --sessions 0 \
    --files 0 \
    --ips 1000 \
    --progress
```

### 3. Bulk Load (After Enrichment)
```bash
# Normal bulk load - automatically reads snapshot_ip_type
uv run cowrie-loader bulk /path/to/logs/*.json \
    --db "postgresql://user:pass@host:port/cowrieprocessor" \ <!-- pragma: allowlist secret -->
    --status-dir /mnt/dshield/data/logs/status
```

## Success Criteria

### Functional (All Must Pass)
- [x] Design complete with all specifications
- [ ] All 65 unit tests pass (95%+ coverage)
- [ ] All 15 integration tests pass
- [ ] Backfill completes successfully (1.68M sessions)
- [ ] snapshot_ip_type coverage ≥90% (from 0%)

### Performance (All Must Meet Targets)
- [ ] Cache hit rate ≥95% after warmup
- [ ] Classification latency p99 <20ms
- [ ] Bulk load performance unchanged (<5s per 1K sessions)

### Accuracy (Validated on 100 Samples)
- [ ] TOR classification ≥95% accurate
- [ ] Cloud classification ≥99% accurate
- [ ] Datacenter classification ≥70% accurate
- [ ] Residential classification ≥70% accurate

### Operational (Production Ready)
- [ ] Zero-cost data sources verified ($0/month)
- [ ] Automated daily/weekly updates working
- [ ] Monitoring alerts configured
- [ ] Rollback procedures tested

## Rollback Plan

If critical issues occur after deployment:

1. **Disable Pass 4**:
   ```python
   # In cascade_factory.py, comment out ip_classifier
   # OR: export DISABLE_IP_CLASSIFICATION=true
   ```

2. **Revert snapshots**:
   ```sql
   UPDATE session_summaries SET snapshot_ip_type = NULL;
   ```

3. **Stop cron jobs**:
   ```bash
   sudo mv /etc/cron.d/ip_classification_updates /etc/cron.d/ip_classification_updates.disabled
   ```

4. **Clear caches**:
   ```bash
   redis-cli KEYS "ip_classification:*" | xargs redis-cli DEL
   rm -rf /mnt/dshield/data/cache/ip_classification/*
   ```

## Expected Outcomes

### Feature Discovery Impact
- **Before**: 2 viable infrastructure features (28.6% success rate)
- **After**: 15-18 viable features (>70% success rate)
- **Improvement**: 7.5x to 9x increase

### Discrimination Score Improvement
- **Before**: Infrastructure features = 0.145 (poor discrimination)
- **After**: Infrastructure features = 0.8+ (excellent discrimination)
- **Improvement**: 5.5x increase

### New Features Unlocked
1. **pct_tor**: % sessions from TOR (anonymization indicator)
2. **pct_cloud**: % sessions from AWS/Azure/GCP (botnet infrastructure)
3. **pct_datacenter**: % sessions from hosting (attack infrastructure)
4. **pct_residential**: % sessions from ISPs (legitimate vs botnet)
5. **infrastructure_entropy**: Shannon entropy of IP types (diversity indicator)
6. **anonymization_score**: (tor + vpn) / total (sophistication metric)
7. **cloud_concentration**: max(aws, azure, gcp) / total (multi-cloud indicator)
8. **residential_datacenter_ratio**: residential / datacenter (legitimacy indicator)

### Snowshoe Detection Enhancement
- Distinguish cloud-based botnets from residential compromises
- Identify TOR-based anonymization campaigns
- Detect multi-cloud snowshoe patterns
- Filter residential botnets vs datacenter attacks

## Questions and Clarifications

### Q: Where exactly does IPClassifier run in the pipeline?
**A**: INSIDE CascadeEnricher.enrich_ip() as Pass 4, NOT as a separate step after. It runs automatically whenever CascadeEnricher is called.

### Q: Do I need to modify bulk/delta loaders?
**A**: NO. They already read ip_inventory.ip_type (hybrid property) which will be populated by Pass 4.

### Q: How do I trigger IP classification?
**A**: Three ways:
1. `cowrie-enrich refresh --ips N` (ongoing maintenance)
2. `scripts/backfill_ip_classification.py` (one-time backfill)
3. Automatic during future enrichment (Pass 4 always runs)

### Q: What if I want to disable IP classification?
**A**: Set `DISABLE_IP_CLASSIFICATION=true` or comment out ip_classifier in cascade_factory.py

### Q: How long does backfill take?
**A**:
- IP enrichment: 6-10 hours (38,864 IPs, network-bound)
- Session updates: 2-4 hours (1.68M sessions, database-bound)
- Total: 8-14 hours

### Q: What happens to existing workflows?
**A**: They continue to work unchanged. Bulk/delta loaders automatically read snapshot_ip_type once populated.

### Q: How do I monitor it?
**A**:
- Cache hit rate: `redis-cli INFO stats | grep keyspace_hits` (target: >95%)
- Latency: Check logs for "ip_classification_latency" (target: p99 <20ms)
- Coverage: Query snapshot_ip_type NULL count (target: <10%)
- Updates: Check /var/log/ip_classification/*.log (target: 100% success)

## Next Steps

1. **Review Design**: Stakeholder review of all 3 design documents
2. **Approve Design**: Sign-off from tech lead / product owner
3. **Begin Implementation**: Week 1 - Core components (models + matchers)
4. **Iterative Development**: Weekly reviews and adjustments
5. **Testing**: Comprehensive unit, integration, and performance tests
6. **Deployment**: Staged rollout with monitoring

---

**For detailed information, see**:
- [Technical Specification](ip_classifier_service_specification.md) - Complete API and code design
- [Implementation Guide](ip_classifier_implementation_guide.md) - Step-by-step build instructions
- [Enrichment Integration](ip_classifier_enrichment_integration.md) - Pipeline integration details

**Document Version**: 1.0
**Last Updated**: 2025-11-10
**Author**: CowrieProcessor Team
**Status**: Ready for Implementation
