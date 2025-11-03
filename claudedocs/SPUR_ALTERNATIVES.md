# SPUR Alternatives - Free/Low-Cost VPN/Proxy Detection

**Status**: 2025-11-03
**Context**: User cannot afford SPUR ($$$), needs alternatives for VPN/proxy/Tor detection

---

## Current SPUR Status

**SPUR Data Structure**: Fixed-length array of 18 positional elements
```python
_SPUR_EMPTY_PAYLOAD = ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]
```

**Why Query 13 Returns Zeros**:
- Query checks for object keys: `enrichment->'spur'->>'is_vpn'`
- SPUR returns array: `enrichment->'spur'` = `["", "", "", ...]`
- No API key configured → all sessions have empty array → zero VPN/proxy detections

**SPUR Pricing**: ~$200-500/month for API access (prohibitively expensive for hobby projects)

---

## Free Alternatives

### 1. **IP2Location LITE** (RECOMMENDED)
- **Cost**: FREE (LITE database)
- **Detection**: VPN, proxy, datacenter, Tor
- **Format**: CSV/BIN database (offline lookup)
- **Updates**: Monthly
- **Limits**: Database download only (not API)
- **URL**: https://lite.ip2location.com/ip2proxy-lite
- **Integration**: Load database into PostgreSQL or use Python library

**Pros**:
- ✅ Completely free
- ✅ No API limits
- ✅ Covers VPN, proxy, datacenter
- ✅ Monthly updates
- ✅ Can load into existing database

**Cons**:
- ❌ Database download/update workflow needed
- ❌ Not real-time API

### 2. **MaxMind GeoLite2** (Partial Alternative)
- **Cost**: FREE (requires account)
- **Detection**: ASN, ISP, connection type (but NOT VPN/proxy directly)
- **Format**: MMDB database (offline lookup)
- **Updates**: Weekly
- **URL**: https://dev.maxmind.com/geoip/geolite2-free-geolocation-data
- **Already Used**: Project already uses MaxMind for geolocation

**Pros**:
- ✅ Free and trusted
- ✅ Weekly updates
- ✅ Excellent ISP/ASN data

**Cons**:
- ❌ Doesn't directly flag VPN/proxy
- ❌ Need heuristics to detect datacenter/hosting IPs

### 3. **ProxyCheck.io** (Free Tier)
- **Cost**: FREE for 1,000 queries/day (~30K/month)
- **Detection**: VPN, proxy, Tor, datacenter
- **Format**: REST API
- **Limits**: 1,000/day free, then $10-50/month
- **URL**: https://proxycheck.io/api/
- **Response**: JSON with `proxy`, `type`, `provider`

**Pros**:
- ✅ Real-time API
- ✅ Generous free tier
- ✅ Good detection accuracy

**Cons**:
- ❌ 1,000/day limit insufficient for 1.68M sessions
- ❌ Batch processing would need ~2 months at free tier

### 4. **IPHub** (Free Tier)
- **Cost**: FREE for 1,000 lookups/day
- **Detection**: Proxy/VPN/Tor detection score (0-2)
- **Format**: REST API
- **URL**: https://iphub.info/
- **Response**: JSON with `block` score

**Pros**:
- ✅ Simple API
- ✅ Free tier available

**Cons**:
- ❌ 1,000/day limit
- ❌ Limited detection granularity

### 5. **IPQualityScore** (Free Tier)
- **Cost**: FREE for 5,000 lookups/month
- **Detection**: VPN, proxy, Tor, bot detection
- **Format**: REST API
- **URL**: https://www.ipqualityscore.com/free-ip-lookup-proxy-vpn-test
- **Response**: JSON with detailed fraud scores

**Pros**:
- ✅ Comprehensive detection
- ✅ Fraud scoring included

**Cons**:
- ❌ 5,000/month limit
- ❌ Requires signup and API key management

---

## Recommended Implementation Strategy

### Option A: IP2Location LITE (Best for Budget)
1. **Download**: Monthly IP2PROXY LITE database
2. **Load**: Import into PostgreSQL table (or use Python library)
3. **Query**: Join session_summaries with IP2Location table on source_ip
4. **Cost**: $0
5. **Timeline**: 1-2 hours setup, monthly updates

**SQL Example**:
```sql
-- After loading IP2Location into table: ip2location_proxy
SELECT
    ss.session_id,
    ip2.proxy_type,
    ip2.country_code,
    CASE
        WHEN ip2.proxy_type IN ('VPN', 'TOR', 'PUB', 'WEB') THEN true
        ELSE false
    END as is_anonymized
FROM session_summaries ss
LEFT JOIN ip2location_proxy ip2 ON ss.source_ip = ip2.ip_from AND ss.source_ip <= ip2.ip_to
```

### Option B: MaxMind + Heuristics (Already Available)
1. **Use**: Existing MaxMind GeoLite2 ASN data
2. **Heuristic**: Classify datacenter/hosting ASNs as potential VPN
3. **Detection**: Not 100% accurate but identifies hosting infrastructure
4. **Cost**: $0 (already using MaxMind)

**SQL Example**:
```sql
-- Using existing DShield ASN data
SELECT
    session_id,
    enrichment->'dshield'->'ip'->>'asname' as asn_name,
    CASE
        WHEN enrichment->'dshield'->'ip'->>'asname' ILIKE '%vpn%' THEN 'vpn'
        WHEN enrichment->'dshield'->'ip'->>'asname' ILIKE '%hosting%' THEN 'hosting'
        WHEN enrichment->'dshield'->'ip'->>'asname' ILIKE '%datacenter%' THEN 'datacenter'
        ELSE 'residential'
    END as inferred_type
FROM session_summaries
```

### Option C: Hybrid Approach (Most Comprehensive)
1. **IP2Location**: Primary VPN/proxy detection (offline)
2. **MaxMind**: ASN classification (already have)
3. **DShield**: Reputation scoring (already have)
4. **Combined Score**: Composite anonymization likelihood

**Benefits**:
- ✅ Free
- ✅ No API limits
- ✅ Multiple data sources improve accuracy

---

## Query 13 Modification Options

### If Using IP2Location Database:
```sql
-- Replace SPUR checks with IP2Location joins
SELECT
    DATE(first_event_at) as attack_date,
    COUNT(DISTINCT session_id) as total_sessions,

    -- VPN detection from IP2Location
    SUM(CASE WHEN ip2.proxy_type = 'VPN' THEN 1 ELSE 0 END) as vpn_sessions,

    -- Proxy detection
    SUM(CASE WHEN ip2.proxy_type IN ('PUB', 'WEB') THEN 1 ELSE 0 END) as proxy_sessions,

    -- Tor detection
    SUM(CASE WHEN ip2.proxy_type = 'TOR' THEN 1 ELSE 0 END) as tor_sessions

FROM session_summaries ss
LEFT JOIN ip2location_proxy ip2
    ON ss.source_ip >= ip2.ip_from AND ss.source_ip <= ip2.ip_to
WHERE first_event_at >= '2024-11-01'
GROUP BY DATE(first_event_at);
```

### If Using MaxMind Heuristics:
```sql
-- Use ASN name patterns for inference
SELECT
    DATE(first_event_at) as attack_date,
    COUNT(DISTINCT session_id) as total_sessions,

    -- Inferred VPN from ASN names
    SUM(CASE WHEN enrichment->'dshield'->'ip'->>'asname' ILIKE '%vpn%' THEN 1 ELSE 0 END) as likely_vpn,

    -- Datacenter/hosting (high anonymization likelihood)
    SUM(CASE WHEN enrichment->'dshield'->'ip'->>'asname' ILIKE '%hosting%'
              OR enrichment->'dshield'->'ip'->>'asname' ILIKE '%datacenter%' THEN 1 ELSE 0 END) as datacenter

FROM session_summaries
WHERE first_event_at >= '2024-11-01'
GROUP BY DATE(first_event_at);
```

---

## Implementation Effort

| Alternative | Setup Time | Recurring Effort | Accuracy | Cost |
|-------------|------------|------------------|----------|------|
| IP2Location LITE | 2 hours | 15 min/month | ⭐⭐⭐⭐ (Very Good) | $0 |
| MaxMind Heuristics | 30 min | 0 | ⭐⭐ (Moderate) | $0 |
| ProxyCheck.io API | 1 hour | 0 | ⭐⭐⭐⭐⭐ (Excellent) | $0 (limited) |
| Hybrid Approach | 3 hours | 15 min/month | ⭐⭐⭐⭐⭐ (Best) | $0 |

---

## Recommendation

**For your use case (1.68M sessions, budget constraints):**

1. **Immediate**: Use **MaxMind heuristics** with existing DShield ASN data (30 minutes)
   - Modify Query 13 to use ASN name pattern matching
   - Run queries to get baseline infrastructure classification

2. **Short-term**: Implement **IP2Location LITE** (1-2 hours)
   - Download PX11LITE database (monthly)
   - Load into PostgreSQL
   - Update Query 13 to use IP2Location joins
   - Set up monthly database refresh script

3. **Long-term**: Consider **hybrid approach** if accuracy requirements increase
   - Combine IP2Location + MaxMind + DShield reputation
   - Build composite anonymization score
   - Machine learning classification of VPN/proxy patterns

**Next Steps**:
1. Decide which alternative to implement
2. Update Query 13 to use chosen data source
3. Re-run infrastructure analysis with working queries
4. Generate comprehensive feature analysis report

---

## Resources

- IP2Location LITE: https://lite.ip2location.com/ip2proxy-lite
- MaxMind GeoLite2: https://dev.maxmind.com/geoip/geolite2-free-geolocation-data
- ProxyCheck.io: https://proxycheck.io/api/
- IPHub: https://iphub.info/
- IPQualityScore: https://www.ipqualityscore.com/documentation/proxy-detection/overview

---

## Conclusion

✅ **Good News**: Multiple free alternatives exist for SPUR
🎯 **Recommended**: IP2Location LITE for best free accuracy
⚡ **Quick Start**: MaxMind heuristics using existing DShield ASN data
💰 **Cost**: $0 for all recommended approaches
