# ADR 009: IP Infrastructure Classification Service for Snowshoe Spam Detection

**Status**: Accepted
**Date**: 2025-11-10
**Context**: IP Infrastructure Classification - Tier 2 Enrichment Enhancement
**Deciders**: Architecture Review
**Related ADRs**:
- **ADR-007**: Three-Tier Enrichment Architecture (IP classification integrates as Pass 4)
- **ADR-005**: Hybrid Database + Redis Enrichment Cache (classification uses same pattern)
- **ADR-002**: Multi-Container Service Architecture (stateless classifier design)

---

## Context and Problem Statement

The snowshoe spam detection system requires **infrastructure attribution** to identify distributed attack patterns across cloud/datacenter/residential networks. The critical `snapshot_ip_type` column in `session_summaries` is 0% populated, blocking 5-8 high-discrimination features (e.g., `ip_type_diversity`, `cloud_provider_diversity`, `tor_ip_ratio`) that are essential for distinguishing snowshoe spam campaigns from organic botnet activity.

### Current State

**What We Have**:
- Three-tier enrichment architecture (ADR-007) with ASN/IP/Session layers
- `ip_inventory.enrichment` stores JSONB data from multiple sources (MaxMind, Cymru, GreyNoise)
- `session_summaries.snapshot_ip_type` column exists but is **0% populated**

**What's Missing**:
- **No IP infrastructure classification**: Cannot determine if IPs are TOR/cloud/datacenter/residential
- **No provider attribution**: Cannot identify AWS vs Azure vs GCP vs residential ISPs
- **Blocked features**: 5-8 snowshoe spam detection features are non-functional
  - `ip_type_diversity`: Requires `snapshot_ip_type` to measure infrastructure variety
  - `cloud_provider_diversity`: Needs provider attribution (AWS, Azure, GCP, CloudFlare)
  - `tor_ip_ratio`: Requires TOR exit node identification
  - `datacenter_concentration`: Requires datacenter vs residential classification
  - `residential_ip_ratio`: Requires residential ISP identification

### Business Impact

**Without IP Classification** (Current State):
- **Feature discrimination**: 0.145 (barely above random chance)
- **Viable features**: 2 of 18 infrastructure features work (11%)
- **Detection capability**: Cannot distinguish snowshoe spam from organic botnets
- **Campaign clustering**: Cannot attribute attacks to specific infrastructure providers

**With IP Classification** (Target State):
- **Feature discrimination**: 0.8+ (5.5x improvement)
- **Viable features**: 15-18 of 18 infrastructure features work (83-100%)
- **Detection capability**: Clear signal for distributed campaigns across cloud/residential networks
- **Campaign clustering**: "Show me all AWS-based campaigns" or "TOR-only campaigns"

### Technical Challenges

1. **Cost Constraint**: Commercial IP intelligence APIs (IPInfo, IPdata, Maxmind GeoIP2 Insights) cost $100-500/month
2. **API Quota**: 300K+ unique IPs to classify would exhaust free API tiers immediately
3. **Accuracy Requirements**: Need >90% coverage with acceptable false positive rates
4. **Performance Requirements**: Classification must not slow down enrichment pipeline (<20ms per IP)
5. **Temporal Accuracy**: Classification must be "what was it at time of attack" for campaign clustering
6. **Maintenance Burden**: Must keep data sources updated without manual intervention

---

## Decision Drivers

1. **Cost**: $0/month solution required (free data sources only)
2. **Coverage**: 90%+ of honeypot IPs classified with confidence scores
3. **Accuracy**: TOR 95%+, Cloud 99%+, Datacenter/Residential 70-80%
4. **Performance**: <20ms per IP (p99), >95% cache hit rate after warmup
5. **Integration**: Seamless integration into existing ADR-007 three-tier architecture
6. **Temporal Accuracy**: Preserve "at time of attack" classification for campaign analysis
7. **Maintainability**: Automated data source updates with minimal operational overhead
8. **Observability**: Statistics tracking, cache monitoring, data source health checks

---

## Considered Options

### Option 1: Third-Party API Service (IPInfo, IPdata, Maxmind Insights)

**Pros**:
- High accuracy (95%+ for all categories)
- Professional support and SLAs
- Comprehensive coverage (VPN, proxy, hosting, mobile)
- Regular automatic updates

**Cons**:
- **Cost**: $100-500/month for required query volume
- **API dependency**: Rate limits, downtime risk, vendor lock-in
- **Quota exhaustion**: 300K IPs × 5-6 queries/session = API quota burnout
- **Latency**: Network round-trip for each query (50-200ms)

**Verdict**: ❌ Rejected due to cost constraint and API dependency risk

---

### Option 2: Single-Tier In-Memory Cache

**Pros**:
- Simplest implementation (just Redis)
- Fastest lookups (<1ms)
- Minimal code complexity

**Cons**:
- **No persistence**: Redis restart loses all classifications (6-10 hours to rebuild)
- **Memory pressure**: 300K IPs × 500 bytes = 150 MB minimum (grows over time)
- **No fallback**: Cache miss = full classification pipeline (expensive)
- **No TTL flexibility**: Cannot have different TTLs for TOR (1h) vs Cloud (24h)

**Verdict**: ❌ Rejected due to lack of persistence and inflexible TTL strategy

---

### Option 3: Database-Only Caching

**Pros**:
- Persistent storage (survives restarts)
- Simple schema (enrichment_cache table already exists)
- SQL queryable for analytics

**Cons**:
- **Slower**: 5-15ms per query (vs <1ms for Redis)
- **No TTL enforcement**: Requires manual expiration cleanup
- **No hot data optimization**: All IPs treated equally (TOR needs 1h TTL, Cloud needs 24h TTL)
- **Scalability**: Database becomes bottleneck at high query rates

**Verdict**: ❌ Rejected due to performance constraints and lack of TTL flexibility

---

### Option 4: Multi-Tier Cache with Free Data Sources (SELECTED)

**Architecture**:
```
L1 (Redis): <1ms latency, type-specific TTLs (TOR 1h, others 24h)
    ↓ miss
L2 (Database): <10ms latency, 7-day TTL (enrichment_cache table)
    ↓ miss
L3 (Disk): <50ms latency, 30-day TTL, sharded by IP octets (1.2.3.4 → /1/2/3/4.json)
    ↓ miss
Classify: Free data sources (TOR list, cloud ranges, datacenter lists, ASN heuristics)
    ↓ warm cache
Store in L1 + L2 + L3
```

**Data Sources** (All Free):
1. **TOR Exit Nodes**: Tor Project bulk exit list (updated hourly, 95% accuracy)
2. **Cloud Providers**: GitHub rezmoss/cloud-provider-ip-addresses (AWS/Azure/GCP/CloudFlare, daily updates, 99% accuracy)
3. **Datacenters**: GitHub jhassine/server-ip-addresses (hosting providers, weekly updates, 75% accuracy)
4. **Residential ISPs**: ASN name heuristics (regex patterns: telecom, broadband, mobile, 70% accuracy)

**Pros**:
- ✅ **Zero cost**: All data sources are free and open source
- ✅ **High coverage**: 90%+ of IPs classified (TOR 95%, Cloud 99%, Datacenter 75%, Residential 70%)
- ✅ **Performance**: >95% cache hit rate after warmup, <1ms p50, <20ms p99
- ✅ **Persistence**: Three layers of durability (Redis, Database, Disk)
- ✅ **Flexible TTLs**: Type-specific expiration (TOR 1h, Cloud 24h)
- ✅ **Graceful degradation**: Falls through cache tiers on failures
- ✅ **Cache warming**: Upper tiers populated automatically on lower hits
- ✅ **Integration**: Follows ADR-005 hybrid cache pattern already proven in production

**Cons**:
- ⚠️ **Maintenance burden**: Must update data sources (automated via cron)
- ⚠️ **Accuracy trade-off**: Datacenter/Residential 70-80% vs commercial API 95%+
- ⚠️ **Complexity**: Three cache layers to monitor and maintain
- ⚠️ **Data source risk**: Upstream GitHub repos could change format or go offline

**Verdict**: ✅ **SELECTED** - Optimal balance of cost, coverage, performance, and maintainability

---

## Decision

**We will implement a multi-tier cached IP classification service using free data sources**, integrated as **Pass 4** in the existing ADR-007 Tier 2 (IP Inventory) enrichment pipeline.

### Classification Priority Order

```
1. TOR Exit Nodes (Priority 1, 95% confidence)
   ↓ no match
2. Cloud Providers (Priority 2, 99% confidence)
   ↓ no match
3. Datacenters (Priority 3, 75% confidence)
   ↓ no match
4. Residential ISPs (Priority 4, 70% confidence, requires ASN data)
   ↓ no match
5. Unknown (Fallback, 0% confidence)
```

### Data Model

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
    provider: Optional[str]  # e.g., "aws", "azure", "tor", "residential"
    confidence: float        # 0.0 to 1.0
    source: str              # e.g., "cloud_ranges_aws", "tor_bulk_list"
    classified_at: datetime  # Timestamp for staleness tracking
```

### Storage Strategy

**Tier 2 (IP Inventory)** - Mutable current state:
```python
# ip_inventory.enrichment JSONB structure
{
  "ip_classification": {
    "ip_type": "cloud",
    "provider": "aws",
    "confidence": 0.99,
    "source": "cloud_ranges_aws",
    "classified_at": "2025-11-10T12:34:56Z"
  }
}

# Computed column for fast filtering
ip_inventory.ip_type = enrichment['ip_classification']['ip_type']  # "cloud"
```

**Tier 3 (Session Summaries)** - Immutable point-in-time snapshot:
```python
# Populated from ip_inventory.ip_type at session creation time
session_summaries.snapshot_ip_type = ip_inventory.ip_type  # "cloud"
```

**Key Benefit**: Temporal accuracy preserved - `snapshot_ip_type` captures "what was it at time of attack" for campaign clustering, while `ip_inventory.ip_type` reflects current classification.

### Integration with ADR-007 Three-Tier Architecture

**IPClassifier runs INSIDE CascadeEnricher as Pass 4**:
```
Pass 1: MaxMind GeoIP2 (offline, geographic data)
Pass 2: Team Cymru ASN (online, 500 IPs/batch)
Pass 3: GreyNoise (online, malicious activity)
Pass 4: IPClassifier (NEW) ← Infrastructure type classification
  ├─ Check 3-tier cache (Redis → Database → Disk)
  ├─ TOR matcher → Cloud matcher → Datacenter matcher → Residential heuristic
  └─ Store in enrichment['ip_classification']
```

**Automatic Invocation**:
1. **Bulk Load** (`cowrie-loader bulk`) - classifies all IPs during initial import
2. **Delta Load** (`cowrie-loader delta`) - classifies new IPs in incremental loads
3. **Refresh** (`cowrie-enrich refresh --ips N`) - re-classifies stale IPs (>30 days old)

---

## Consequences

### Positive

1. ✅ **Zero Cost**: $0/month using free data sources (TOR, GitHub cloud ranges, datacenter lists)
2. ✅ **High Coverage**: 90%+ of IPs classified (TOR 95%, Cloud 99%, Datacenter 75%, Residential 70%)
3. ✅ **Feature Enablement**: 5-8 blocked snowshoe detection features now functional
4. ✅ **Performance**: <1ms p50, <20ms p99, >95% cache hit rate after warmup
5. ✅ **Campaign Attribution**: "Show all AWS campaigns" or "TOR-only attacks" queries enabled
6. ✅ **Temporal Accuracy**: `snapshot_ip_type` preserves "at time of attack" for clustering
7. ✅ **Integration Simplicity**: Follows existing ADR-005 hybrid cache pattern
8. ✅ **Graceful Degradation**: Three cache tiers provide resilience on failures

### Negative

1. ⚠️ **Maintenance Burden**: Data sources require updates (TOR hourly, cloud daily, datacenter weekly)
   - **Mitigation**: Automated cron jobs with monitoring, downtime alerts

2. ⚠️ **Accuracy Trade-off**: Datacenter/Residential 70-80% vs commercial APIs 95%+
   - **Mitigation**: Focus on high-confidence classifications (TOR 95%, Cloud 99%)
   - **Acceptable**: 70-80% accuracy sufficient for snowshoe spam detection (needs patterns, not perfection)

3. ⚠️ **Complexity**: Three cache layers (Redis, Database, Disk) to monitor
   - **Mitigation**: Unified statistics API, health check endpoint, cache monitoring dashboard

4. ⚠️ **Data Source Risk**: GitHub repos could change format or go offline
   - **Mitigation**: Version pinning, fallback sources, monitoring for upstream changes

5. ⚠️ **Staleness Risk**: Classifications age out (TOR 1h, Cloud 24h, DB 7d, Disk 30d)
   - **Mitigation**: TTL tuning based on IP type, refresh jobs for stale data

6. ⚠️ **Storage Growth**: Cache layers consume disk space (~150 MB for 300K IPs)
   - **Mitigation**: TTL-based expiration, disk is cheap, acceptable cost

### Neutral

1. 📊 **Observability**: Statistics tracking required for cache hit rates, classification distribution
2. 🔄 **Operational Overhead**: Monitoring cron jobs, data source health checks
3. 📚 **Documentation**: User guide for classification interpretation and troubleshooting

---

## Implementation Summary

**Components Implemented**:
1. **`models.py`**: IPType enum, IPClassification dataclass
2. **`matchers.py`**: Base IPMatcher abstract class
3. **`tor_matcher.py`**: TOR exit node O(1) set lookup
4. **`cloud_matcher.py`**: PyTricia trees for AWS/Azure/GCP/CloudFlare
5. **`datacenter_matcher.py`**: PyTricia tree for hosting providers
6. **`residential_heuristic.py`**: Regex patterns on ASN names
7. **`cache.py`**: HybridIPClassificationCache (Redis L1, Database L2, Disk L3)
8. **`classifier.py`**: IPClassifier orchestrator with priority-based matching
9. **`factory.py`**: `create_ip_classifier()` factory function

**Integration Points**:
- **CascadeEnricher.enrich_ip()**: Pass 4 adds `enrichment['ip_classification']`
- **IPInventory.ip_type**: Computed column from `enrichment['ip_classification']['ip_type']`
- **SessionSummary.snapshot_ip_type**: Auto-populated from `ip_inventory.ip_type` at session creation

**Data Source Updates** (Automated via cron):
- **TOR**: Hourly (`15 * * * *`) - critical for accuracy
- **Cloud**: Daily (`0 3 * * *`) - high priority
- **Datacenter**: Weekly (`0 4 * * 0`) - medium priority

**Documentation**:
- **User Guide**: `docs/sphinx/source/guides/ip-classification.rst` (comprehensive 450-line guide)
- **Design Spec**: `docs/design/README_IP_CLASSIFICATION.md` (50+ page technical design)
- **Operations**: `docs/operations/ip_classification_data_updates.md` (data source maintenance)
- **API Reference**: `docs/sphinx/source/api/cowrieprocessor.enrichment.ip_classification.rst`

---

## Alternatives Not Chosen

1. **Third-Party API Service** (IPInfo, IPdata, Maxmind Insights)
   - **Reason**: Cost constraint ($100-500/month) and API dependency risk

2. **Single-Tier In-Memory Cache** (Redis only)
   - **Reason**: No persistence on restart, inflexible TTL strategy

3. **Database-Only Caching**
   - **Reason**: Performance bottleneck (5-15ms vs <1ms), no TTL enforcement

---

## References

- **ADR-007**: Three-Tier Enrichment Architecture for Threat Attribution
- **ADR-005**: Hybrid Database + Redis Enrichment Cache
- **ADR-002**: Multi-Container Service Architecture
- **Design Spec**: `docs/design/README_IP_CLASSIFICATION.md` (50+ pages)
- **User Guide**: `docs/sphinx/source/guides/ip-classification.rst` (450 lines)
- **Operations Guide**: `docs/operations/ip_classification_data_updates.md`
- **Data Sources**:
  - TOR Project: https://check.torproject.org/exit-addresses
  - Cloud Ranges: https://github.com/rezmoss/cloud-provider-ip-addresses
  - Datacenters: https://github.com/jhassine/server-ip-addresses

---

## Approval

**Accepted**: 2025-11-10
**Implementation Complete**: 2025-11-10
**Production Deployment**: Pending backfill of 300K IPs + 1.68M sessions
