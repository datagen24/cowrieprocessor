# Infrastructure Enrichment - Free/Open-Source Data Sources

**Date**: 2025-11-10
**Purpose**: Identify free data sources to populate `snapshot_ip_type` and enhance infrastructure classification
**Current Gap**: 0% snapshot_ip_type coverage (VPN, Residential, TOR, Cloud, Datacenter)

---

## 🎯 Objective

Enhance snowshoe detection by classifying IPs into infrastructure categories:
1. **TOR Exit Nodes** - Anonymous traffic
2. **VPN/Proxy** - Privacy tools, potentially malicious
3. **Cloud (AWS/Azure/GCP)** - Hyperscale infrastructure
4. **Datacenter/Hosting** - Colocation, VPS providers
5. **Residential/Mobile** - ISP/Telecom networks

---

## 📊 Current State Analysis

### Feature Discovery Gap (Query 15)
```
snapshot_ip_type: 100% NULL (0% coverage)
```

**Impact**:
- Cannot distinguish cloud vs residential attacks
- Cannot identify TOR-based anonymization
- Missing key snowshoe indicator (legitimate users = residential, attackers = datacenter)
- 10-15 expected features → May be limited to 8-12 without IP type classification

### Existing Infrastructure Data
✅ **Available**:
- ASN (85.52% coverage)
- Country (99.99% coverage)
- AS Name (from Team Cymru)
- GeoIP data (MaxMind)

❌ **Missing**:
- IP type classification
- VPN/Proxy detection
- TOR exit node identification
- Cloud provider categorization

---

## 🆓 Free/Open-Source Data Sources

### Category 1: TOR Exit Nodes (HIGH PRIORITY)

#### **Official Tor Project** ✅ RECOMMENDED
**Source**: Tor Project Bulk Exit List
**URL**: https://check.torproject.org/torbulkexitlist
**Update Frequency**: Hourly
**Format**: Plain text (IP addresses, one per line)
**Cost**: FREE
**License**: Public domain

**Implementation**:
```python
# Download hourly, cache for 1 hour
tor_exit_nodes = requests.get("https://check.torproject.org/torbulkexitlist").text.splitlines()
# Store in Redis/SQLite for fast lookup
```

**Alternative**: TorDNSEL DNS Query
**Method**: Query `[reverse-ip].dnsel.torproject.org`
**Returns**: `127.0.0.2` if TOR exit node
**Cost**: FREE

#### **Dan.me.uk TOR Node List** (Backup)
**URL**: https://www.dan.me.uk/tornodes
**Format**: CSV with exit node IPs
**Update**: Last 3 months of data
**Cost**: FREE

---

### Category 2: Cloud Provider IP Ranges (HIGH PRIORITY)

#### **GitHub: rezmoss/cloud-provider-ip-addresses** ✅ RECOMMENDED
**URL**: https://github.com/rezmoss/cloud-provider-ip-addresses
**Providers**: AWS, Azure, GCP, Cloudflare
**Update Frequency**: **Daily** (automated)
**Formats**: TXT, CSV, JSON, SQL
**License**: CC0 1.0 Universal (Public Domain)

**Coverage**:
- AWS (all regions)
- Azure (all regions)
- Google Cloud Platform (all regions)
- Cloudflare (CDN/proxy network)

**Implementation**:
```python
# Daily update via GitHub API or raw file
aws_ranges = requests.get("https://raw.githubusercontent.com/rezmoss/cloud-provider-ip-addresses/main/aws/ipv4.csv").text
azure_ranges = requests.get("https://raw.githubusercontent.com/rezmoss/cloud-provider-ip-addresses/main/azure/ipv4.csv").text
gcp_ranges = requests.get("https://raw.githubusercontent.com/rezmoss/cloud-provider-ip-addresses/main/gcp/ipv4.csv").text
```

#### **GitHub: tobilg/public-cloud-provider-ip-ranges** (Alternative)
**URL**: https://github.com/tobilg/public-cloud-provider-ip-ranges
**Providers**: AWS, Azure, GCP, CloudFlare, DigitalOcean, Fastly, Oracle Cloud
**Formats**: CSV, Parquet, JSON
**Update**: Weekly
**License**: Open source

---

### Category 3: Datacenter/Hosting Detection

#### **GitHub: client9/ipcat** ✅ RECOMMENDED
**URL**: https://github.com/client9/ipcat
**Coverage**: Datacenters, co-location, shared/virtual hosting
**Format**: CSV (IP ranges, provider names, URLs)
**Update**: Community-maintained
**License**: MIT

**Data Quality**: Moderate (requires manual review)
**Best For**: Identifying known hosting providers

#### **GitHub: jhassine/server-ip-addresses** ✅ RECOMMENDED
**URL**: https://github.com/jhassine/server-ip-addresses
**Coverage**: Data centers, cloud service providers
**Providers**: AWS, Azure, GCP, CloudFlare
**Update Frequency**: **Daily**
**Formats**: CSV (detailed), TXT (CIDR only)
**License**: Open source

**Implementation**:
```python
# Daily update from GitHub
datacenter_ranges = requests.get("https://raw.githubusercontent.com/jhassine/server-ip-addresses/main/data/datacenters.csv").text
# Parse CIDR blocks, store in IPSet for fast lookup
```

#### **GitHub: Pymmdrza/Datacenter_List_DataBase_IP** (Supplemental)
**URL**: https://github.com/Pymmdrza/Datacenter_List_DataBase_IP
**Coverage**: Comprehensive datacenter and hosting IPs
**Format**: IP ranges, CIDR lists
**License**: Open source

---

### Category 4: VPN/Proxy Detection (PARTIAL COVERAGE)

#### **Limited Free Options** ⚠️
Most VPN detection requires paid services (SPUR, IPinfo, IP2Proxy).

**Open-Source Alternatives**:

1. **ASN-Based Heuristics** (DIY Approach)
   - Known VPN provider ASNs (NordVPN, ExpressVPN, etc.)
   - Manually curated list from public sources
   - **Accuracy**: ~60-70% (misses residential VPNs)

2. **Hosting Provider Detection as Proxy** (Workaround)
   - If IP is datacenter/hosting + not cloud + high anonymity score → likely VPN/Proxy
   - **Logic**: `ip_type = "hosting" AND asn NOT IN (aws, azure, gcp) AND tor = false → "potential_vpn"`

3. **Community Lists** (Supplemental)
   - VPN provider domains → ASN resolution
   - Manually updated from public disclosures
   - **Maintenance**: High (VPN providers change IPs frequently)

**RECOMMENDATION**: Defer comprehensive VPN detection to Phase 2, focus on:
- TOR (free, high accuracy)
- Cloud providers (free, high accuracy)
- Datacenter/hosting (free, moderate accuracy)
- Use heuristics for VPN classification based on above

---

### Category 5: Residential/Mobile Classification (HEURISTIC)

#### **No Direct Free Database** ❌

**Workaround Strategy** (Process of Elimination):
```python
if ip in tor_exit_nodes:
    ip_type = "tor"
elif ip in cloud_ranges:
    ip_type = "cloud"
elif ip in datacenter_ranges:
    ip_type = "datacenter"
elif asn_name matches ("telecom", "broadband", "mobile", "wireless"):
    ip_type = "residential"  # Heuristic based on AS name
else:
    ip_type = "unknown"
```

**ASN Name Patterns for Residential** (from Query 12):
- Contains: "telecom", "mobile", "broadband", "wireless", "cable"
- Excludes: "hosting", "datacenter", "server", "cloud", "colocation"

**Accuracy**: ~70-80% (good enough for snowshoe detection)

---

## 🏗️ Proposed Implementation Architecture

### Phase 1: Foundation (Week 1)

#### 1.1 IP Classification Service
**File**: `cowrieprocessor/enrichment/ip_classifier.py`

**Components**:
- `TorExitNodeChecker` (Tor Project bulk list)
- `CloudProviderMatcher` (rezmoss/cloud-provider-ip-addresses)
- `DatacenterMatcher` (jhassine/server-ip-addresses + client9/ipcat)
- `ResidentialHeuristic` (ASN name pattern matching)

**Dependencies**:
- `ipaddress` (stdlib)
- `requests` (download lists)
- `pytricia` or `netaddr` (CIDR matching)
- Redis or SQLite (caching)

#### 1.2 Data Update Pipeline
**File**: `cowrieprocessor/enrichment/ip_classification_updater.py`

**Update Schedule**:
- TOR exit nodes: **Hourly** (via cron)
- Cloud IP ranges: **Daily** (via cron)
- Datacenter lists: **Weekly** (via cron)

**Storage**:
- SQLite table: `ip_classification_cache`
  - Columns: `network_cidr`, `ip_type`, `provider`, `last_updated`
- Redis (production): Fast in-memory lookup

#### 1.3 Integration with Cascade Enricher
**File**: `cowrieprocessor/enrichment/cascade_enricher.py`

**New Method**: `_classify_ip_type(ip_address: str) -> str`
**Placement**: After Cymru ASN enrichment (Pass 2)
**Output**: `snapshot_ip_type` field populated

---

### Phase 2: Enrichment (Week 2)

#### 2.1 Backfill Existing Sessions
**Script**: `scripts/backfill_ip_classification.py`

**Process**:
1. Query `ip_inventory` for all IPs (38,864 IPs)
2. Classify each IP using new service
3. Update `snapshot_ip_type` for 1.68M sessions (via JOIN on source_ip)
4. Commit in batches of 10,000

**Estimated Time**: 2-4 hours (38K IPs × 10ms lookup = 6 minutes + DB updates)

#### 2.2 Real-Time Classification
**Location**: `bulk.py:_upsert_session_summaries()`

**Logic**:
```python
# After populating snapshot_asn and snapshot_country
ip_type = ip_classifier.classify(session.source_ip)
snapshot_values["snapshot_ip_type"] = ip_type
```

---

### Phase 3: Feature Extraction (Week 3)

#### New Infrastructure Features

**From Query 15 Enhanced**:
1. **IP Type Distribution**
   - `pct_tor` = sessions from TOR / total sessions
   - `pct_cloud` = sessions from AWS/Azure/GCP / total
   - `pct_datacenter` = sessions from hosting / total
   - `pct_residential` = sessions from ISPs / total

2. **Infrastructure Diversity**
   - Shannon entropy of IP types
   - `H = -Σ(p_i * log2(p_i))` where p_i = proportion of each type
   - High entropy = diverse infrastructure (snowshoe indicator)

3. **Anonymization Score**
   - `anonymization_score = (tor_sessions + vpn_sessions) / total_sessions`
   - Range: 0.0 (none) to 1.0 (all anonymous)
   - >0.5 = High anonymization (sophisticated actor)

4. **Cloud Provider Clustering**
   - `cloud_concentration = max(aws, azure, gcp) / total_cloud_sessions`
   - Low concentration = multi-cloud snowshoe
   - High concentration = single-provider (easier attribution)

5. **Residential/Datacenter Ratio**
   - `resi_dc_ratio = residential_sessions / datacenter_sessions`
   - <0.1 = Datacenter-heavy (likely attack infrastructure)
   - >10.0 = Residential-heavy (legitimate users or botnet)

**Expected Discrimination Scores**: 0.7+ for all 5 features

---

## 📈 Expected Impact on Feature Discovery

### Before IP Classification
- **Viable Features**: 10-12 (infrastructure features limited)
- **Missing**: TOR detection, cloud classification, residential filtering
- **Snowshoe Detection**: Moderate (geographic/ASN only)

### After IP Classification
- **Viable Features**: **15-18** (5-8 new infrastructure features)
- **New Capabilities**:
  - Distinguish cloud vs residential attacks
  - Identify TOR-based anonymization campaigns
  - Detect multi-cloud snowshoe patterns
  - Filter residential botnets vs datacenter attacks
- **Snowshoe Detection**: **High** (comprehensive infrastructure profiling)

### Feature Discrimination Improvement
- Infrastructure features: 0.145 → **0.8+** (5.5x improvement)
- Overall avg discrimination: 0.380 → **0.65+** (70% improvement)
- Phase 1B ML model: 10-12 features → **15-18 features** (50% increase)

---

## 💰 Cost Analysis

### Data Sources (All FREE)
| Source | Cost | Update | Maintenance |
|--------|------|--------|-------------|
| Tor Project | $0 | Hourly | Automated |
| rezmoss/cloud-provider-ip-addresses | $0 | Daily | Automated |
| jhassine/server-ip-addresses | $0 | Daily | Automated |
| client9/ipcat | $0 | Weekly | Manual review |
| ASN heuristics | $0 | N/A | Pattern updates |

**Total Cost**: **$0/month** ✅

### Infrastructure Costs
- **Storage**: +50MB (IP classification cache) - negligible
- **Compute**: +10ms per IP lookup (cached) - negligible
- **Bandwidth**: ~5MB/day (list downloads) - negligible

**Total Infrastructure**: **<$1/month** ✅

---

## ⚠️ Limitations & Caveats

### Accuracy Expectations

| Category | Accuracy | Rationale |
|----------|----------|-----------|
| TOR | **95%+** | Official Tor Project data |
| Cloud (Big 3) | **99%+** | Official provider IP ranges |
| Datacenter | **70-80%** | Community-maintained, lags on new providers |
| VPN/Proxy | **40-60%** | Heuristic-based, no comprehensive free database |
| Residential | **70-80%** | Process of elimination + ASN heuristics |

### Known Gaps
1. **VPN Detection**: Limited to known hosting providers + heuristics
2. **New Datacenter Providers**: Lag time until community lists updated
3. **Residential Proxy Networks**: Cannot distinguish from legitimate residential
4. **Dynamic IP Ranges**: Cloud providers change IPs, requires daily updates
5. **Hybrid Networks**: Some ASNs mix residential + datacenter (e.g., AT&T Business)

### Mitigation Strategies
1. **Daily Updates**: Automate downloads to minimize lag
2. **Multi-Source Validation**: Cross-reference multiple lists
3. **Confidence Scoring**: `ip_type_confidence` field (low/medium/high)
4. **Manual Review**: Periodic audit of "unknown" classifications
5. **Phase 2 Enhancement**: Consider paid SPUR/IPinfo for VPN detection

---

## 🚀 Rollout Plan

### Week 1: Foundation
- [x] Research completed (this document)
- [ ] Design `IPClassifier` service architecture
- [ ] Implement TOR exit node checker
- [ ] Implement cloud provider matcher
- [ ] Implement datacenter matcher
- [ ] Implement residential heuristic
- [ ] Unit tests (95% coverage target)

### Week 2: Integration
- [ ] Integrate with `cascade_enricher.py`
- [ ] Update `bulk.py` for real-time classification
- [ ] Create `backfill_ip_classification.py` script
- [ ] Execute backfill on 1.68M sessions
- [ ] Validate `snapshot_ip_type` coverage (target: 90%+)

### Week 3: Feature Engineering
- [ ] Re-run Query 15 with IP type populated
- [ ] Extract 5 new infrastructure features
- [ ] Run feature importance analysis
- [ ] Update `feature_discovery_analysis.md`
- [ ] Validate discrimination scores (target: 0.7+)

### Week 4: Validation & Documentation
- [ ] Test on 22-incident MVP dataset
- [ ] Compare before/after snowshoe detection accuracy
- [ ] Document API usage in `docs/api/ip_classification.md`
- [ ] Create ADR for infrastructure enrichment
- [ ] Close GitHub issues #60, #61 with enhanced baseline

---

## 📚 References

### Official Documentation
- Tor Project Bulk Exit List: https://check.torproject.org/torbulkexitlist
- AWS IP Ranges: https://ip-ranges.amazonaws.com/ip-ranges.json
- Azure IP Ranges: https://www.microsoft.com/en-us/download/details.aspx?id=56519
- GCP IP Ranges: https://www.gstatic.com/ipranges/cloud.json

### Community Resources
- rezmoss/cloud-provider-ip-addresses: https://github.com/rezmoss/cloud-provider-ip-addresses
- jhassine/server-ip-addresses: https://github.com/jhassine/server-ip-addresses
- client9/ipcat: https://github.com/client9/ipcat
- tobilg/public-cloud-provider-ip-ranges: https://github.com/tobilg/public-cloud-provider-ip-ranges

### Related Documentation
- ADR-007: Three-Tier Enrichment Architecture
- Phase 1A Feature Discovery: `docs/phase1/feature_discovery_analysis.md`
- Cascade Enricher: `cowrieprocessor/enrichment/cascade_enricher.py`
- Query 15 Results: `results/feature_discovery_2025-11-10/15_snapshot_session_clustering.csv`

---

## ✅ Success Criteria

1. **snapshot_ip_type Coverage**: 90%+ (from 0%)
2. **Classification Accuracy**: 80%+ (validated on known samples)
3. **Feature Discovery**: 15-18 viable features (from 10-12)
4. **Discrimination Scores**: 5 new features with >0.7 scores
5. **Cost**: Remain at $0/month for data sources
6. **Performance**: <10ms IP classification lookup (cached)
7. **Maintenance**: Fully automated daily updates

---

**Status**: READY FOR IMPLEMENTATION
**Next Action**: Design `IPClassifier` service architecture
**Owner**: TBD
**Timeline**: 3-4 weeks (Phases 1-3)
