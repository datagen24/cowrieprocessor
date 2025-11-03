# Post-Enrichment Query Re-Run Plan

**Date**: 2025-11-02
**Status**: Enrichment backfill completed - ready to re-run queries
**Purpose**: Capture infrastructure features that were 100% NULL before enrichment

---

## Phase 1: Verify Enrichment Completeness (CRITICAL FIRST STEP)

**Before re-running any feature queries, MUST verify enrichment is actually populated.**

### Step 1A: Run Diagnostic Query 1 (Overall Completeness)

**File**: `scripts/phase1/ENRICHMENT_DIAGNOSTIC_QUERIES_V2.sql` (Query 1)

**Purpose**: Verify nested enrichment fields are populated (not just empty JSON objects)

**Expected Results** (if enrichment succeeded):
```
total_sessions: 500,000+
enrichment_column_exists: 500,000+
has_country: 475,000+ (>95%)
has_asn: 475,000+ (>95%)
has_urlhaus: 400,000+ (>80%)
has_spur: 350,000+ (>70%)

country_pct: >95%
asn_pct: >95%
urlhaus_pct: >80%
spur_pct: >70%
```

**Run Command**:
```bash
psql -h 10.130.30.89 -U username -d dshield -c "
SELECT
    COUNT(*) as total_sessions,
    COUNT(enrichment) as enrichment_column_exists,
    COUNT(CASE WHEN enrichment->'dshield'->>'country' IS NOT NULL THEN 1 END) as has_country,
    COUNT(CASE WHEN enrichment->'dshield'->>'asn' IS NOT NULL THEN 1 END) as has_asn,
    ROUND(100.0 * COUNT(CASE WHEN enrichment->'dshield'->>'country' IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as country_pct,
    ROUND(100.0 * COUNT(CASE WHEN enrichment->'dshield'->>'asn' IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as asn_pct
FROM session_summaries
WHERE first_event_at >= '2024-11-01';
" > results/POST_ENRICHMENT_diagnostic_summary.txt
```

**Success Criteria**:
- ✅ `country_pct >= 80%` (acceptable enrichment)
- ✅ `asn_pct >= 80%` (acceptable enrichment)
- ⚠️ If <80%, investigate enrichment errors before proceeding

### Step 1B: Sample Enrichment JSON Structure (Quality Check)

**File**: `scripts/phase1/ENRICHMENT_DIAGNOSTIC_QUERIES_V2.sql` (Query 2)

**Purpose**: Inspect actual enrichment JSON to verify format and content

**Run Command**:
```bash
psql -h 10.130.30.89 -U username -d dshield -c "
SELECT
    session_id,
    enrichment::text as enrichment_json_raw
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND enrichment IS NOT NULL
LIMIT 5;
" > results/POST_ENRICHMENT_sample_json.txt
```

**Manual Inspection**:
- Verify JSON structure matches expected format
- Check for empty objects `{}` vs populated data
- Confirm service keys exist: `dshield`, `urlhaus`, `spur`

### Step 1C: Enrichment by Service Availability

**File**: `scripts/phase1/ENRICHMENT_DIAGNOSTIC_QUERIES_V2.sql` (Query 4)

**Purpose**: Check which enrichment services have data

**Expected Results**:
```
dshield_data_pct: >95% (free service, should be highest)
urlhaus_data_pct: >80% (API key required)
spur_data_pct: >70% (API key required, may be lower)
```

**Run Command**:
```bash
psql -h 10.130.30.89 -U username -d dshield -f scripts/phase1/ENRICHMENT_DIAGNOSTIC_QUERIES_V2.sql \
    | grep -A 5 "QUERY 4" > results/POST_ENRICHMENT_service_availability.txt
```

**Decision Point**:
- ✅ If all services >70%, proceed with re-run plan
- ⚠️ If DShield <80%, investigate API key or rate limiting issues
- ⚠️ If URLHaus/SPUR <50%, document as known limitation

---

## Phase 2: Re-Run Existing Queries with Enrichment Data

### Query 6: Enrichment Analysis (HIGHEST PRIORITY)

**File**: `scripts/phase1/sql_analysis_queries_v2.sql` (lines 240-264)

**Status**: ⚠️ **CRITICAL RE-RUN** - Was 100% NULL before

**What This Query Extracts**:
- Geographic: `country`, `asn`, `as_name`
- Infrastructure: `is_vpn`, `is_proxy`, `is_tor`, `organization`
- Reputation: `dshield_attacks`, `dshield_count`, `threat_level`
- Classification: `spur_client_type`

**Re-Run Command**:
```bash
psql -h 10.130.30.89 -U username -d dshield -c "
SELECT
    session_id,
    first_event_at,
    -- Geographic enrichment
    enrichment->'dshield'->>'country' as country,
    enrichment->'dshield'->>'asn' as asn,
    enrichment->'dshield'->>'as_name' as as_name,
    -- Infrastructure detection
    enrichment->>'is_vpn' as is_vpn,
    enrichment->>'is_proxy' as is_proxy,
    enrichment->>'is_tor' as is_tor,
    enrichment->>'organization' as organization,
    enrichment->>'threat_level' as threat_level,
    -- Reputation scores
    enrichment->'dshield'->>'attacks' as dshield_attacks,
    enrichment->'dshield'->>'count' as dshield_count,
    enrichment->'spur'->>'client' as spur_client_type
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND enrichment IS NOT NULL
ORDER BY first_event_at DESC
LIMIT 5000;
" > results/POST_ENRICHMENT_06_enrichment_analysis.csv
```

**Expected Output**:
- **Before**: All columns NULL (30,000 rows)
- **After**: 80-95% of columns populated with actual data

**Validation**:
```bash
# Check that country field is populated
head -100 results/POST_ENRICHMENT_06_enrichment_analysis.csv | grep -c '"US"'
# Should show >80 hits if enrichment worked
```

### Query 1: Session Activity Patterns (Update vt_flagged/dshield_flagged)

**File**: `scripts/phase1/sql_analysis_queries_v2.sql` (lines 26-42)

**Status**: ⚠️ **RE-RUN RECOMMENDED** - vt_flagged and dshield_flagged were always 0

**What Changed with Enrichment**:
- `vt_flagged_sessions`: Now should show >0 (malware-flagged sessions)
- `dshield_flagged_sessions`: Now should show >0 (high-reputation-score sessions)

**Re-Run Command**:
```bash
psql -h 10.130.30.89 -U username -d dshield -c "
SELECT
    DATE(first_event_at) as attack_date,
    COUNT(DISTINCT session_id) as session_count,
    SUM(command_count) as total_commands,
    SUM(CASE WHEN vt_flagged THEN 1 ELSE 0 END) as vt_flagged_sessions,
    SUM(CASE WHEN dshield_flagged THEN 1 ELSE 0 END) as dshield_flagged_sessions,
    AVG(EXTRACT(EPOCH FROM (last_event_at - first_event_at))) as avg_duration_seconds
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
GROUP BY DATE(first_event_at)
ORDER BY attack_date DESC;
" > results/POST_ENRICHMENT_01_session_activity_patterns.csv
```

**Validation**:
- Compare `vt_flagged_sessions` column: Before=0, After=>0
- Compare `dshield_flagged_sessions` column: Before=0, After=>0

### Query 7: High-Activity Sessions (Update flagged status)

**File**: `scripts/phase1/sql_analysis_queries_v2.sql` (lines 274-308)

**Status**: ⚠️ **RE-RUN RECOMMENDED** - vt_flagged and dshield_flagged were always false

**Re-Run Command**:
```bash
psql -h 10.130.30.89 -U username -d dshield -c "
SELECT
    session_id,
    first_event_at,
    command_count,
    file_downloads,
    vt_flagged,
    dshield_flagged,
    risk_score
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND (command_count >= 20 OR file_downloads >= 2 OR ssh_key_injections >= 1 OR risk_score >= 70)
ORDER BY command_count DESC
LIMIT 500;
" > results/POST_ENRICHMENT_07_high_activity_sessions.csv
```

### Query 8: Session Feature Vectors (Add enrichment ratios)

**File**: `scripts/phase1/sql_analysis_queries_v2.sql` (lines 319-343)

**Status**: ⚠️ **RE-RUN RECOMMENDED** - vt_flagged_ratio and dshield_flagged_ratio were always 0

**Re-Run Command**:
```bash
psql -h 10.130.30.89 -U username -d dshield -f scripts/phase1/sql_analysis_queries_v2.sql \
    | csplit - '/QUERY 8/' '{*}' && mv xx01 results/POST_ENRICHMENT_08_session_feature_vectors.csv
```

**Note**: This query already includes enrichment ratios, but they were 0% before enrichment.

---

## Phase 3: Create NEW Infrastructure Feature Queries

### NEW Query 11: Geographic Distribution Analysis

**Purpose**: Analyze geographic clustering and country diversity

**Query**:
```sql
-- ============================================================================
-- QUERY 11: Geographic Distribution Analysis
-- ============================================================================
-- PURPOSE: Analyze geographic patterns for nation-state vs cybercrime distinction
-- EXPECTED: ~50-200 rows (top countries)
-- CSV: results/11_geographic_distribution.csv
-- ============================================================================

SELECT
    enrichment->'dshield'->>'country' as country,
    COUNT(DISTINCT session_id) as session_count,
    COUNT(DISTINCT enrichment->'dshield'->>'asn') as unique_asns,
    COUNT(DISTINCT DATE(first_event_at)) as days_active,
    MIN(first_event_at) as first_seen,
    MAX(first_event_at) as last_seen,
    AVG(command_count) as avg_commands_per_session,
    SUM(file_downloads) as total_file_downloads,
    SUM(CASE WHEN vt_flagged THEN 1 ELSE 0 END) as vt_flagged_count,
    SUM(CASE WHEN dshield_flagged THEN 1 ELSE 0 END) as dshield_flagged_count,
    -- Calculate geographic concentration
    ROUND(100.0 * COUNT(DISTINCT session_id) / (SELECT COUNT(*) FROM session_summaries WHERE first_event_at >= '2024-11-01' AND enrichment->'dshield'->>'country' IS NOT NULL), 2) as country_percentage
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND enrichment->'dshield'->>'country' IS NOT NULL
GROUP BY enrichment->'dshield'->>'country'
HAVING COUNT(DISTINCT session_id) >= 100  -- Min 100 sessions per country
ORDER BY session_count DESC
LIMIT 200;
```

**Save As**: `scripts/phase1/sql_query_11_geographic_distribution.sql`

**Run Command**:
```bash
psql -h 10.130.30.89 -U username -d dshield -f scripts/phase1/sql_query_11_geographic_distribution.sql \
    > results/11_geographic_distribution.csv
```

**Expected Insights**:
- Top attacking countries (e.g., CN, US, RU, BR)
- Geographic concentration ratio (single country vs distributed)
- Country-specific attack patterns (commands, malware delivery)

### NEW Query 12: ASN and Hosting Provider Analysis

**Purpose**: Identify infrastructure abuse patterns (cloud providers, hosting, botnets)

**Query**:
```sql
-- ============================================================================
-- QUERY 12: ASN and Hosting Provider Analysis
-- ============================================================================
-- PURPOSE: Identify cloud provider abuse and hosting infrastructure patterns
-- EXPECTED: ~100-500 rows (top ASNs)
-- CSV: results/12_asn_infrastructure_analysis.csv
-- ============================================================================

SELECT
    enrichment->'dshield'->>'asn' as asn,
    enrichment->'dshield'->>'as_name' as as_name,
    enrichment->'dshield'->>'country' as primary_country,
    COUNT(DISTINCT session_id) as session_count,
    COUNT(DISTINCT DATE(first_event_at)) as days_active,
    MIN(first_event_at) as first_seen,
    MAX(first_event_at) as last_seen,
    AVG(command_count) as avg_commands,
    SUM(file_downloads) as total_downloads,
    -- Classify infrastructure type (heuristic based on AS name)
    CASE
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%amazon%' OR enrichment->'dshield'->>'as_name' ILIKE '%aws%' THEN 'AWS'
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%microsoft%' OR enrichment->'dshield'->>'as_name' ILIKE '%azure%' THEN 'Azure'
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%google%' OR enrichment->'dshield'->>'as_name' ILIKE '%gcp%' THEN 'GCP'
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%digitalocean%' THEN 'DigitalOcean'
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%linode%' THEN 'Linode'
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%ovh%' THEN 'OVH'
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%hetzner%' THEN 'Hetzner'
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%alibaba%' THEN 'Alibaba Cloud'
        WHEN enrichment->'dshield'->>'as_name' ILIKE '%telecom%' OR enrichment->'dshield'->>'as_name' ILIKE '%mobile%' THEN 'ISP/Telecom'
        ELSE 'Other/Unknown'
    END as infrastructure_type
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND enrichment->'dshield'->>'asn' IS NOT NULL
GROUP BY
    enrichment->'dshield'->>'asn',
    enrichment->'dshield'->>'as_name',
    enrichment->'dshield'->>'country'
HAVING COUNT(DISTINCT session_id) >= 50  -- Min 50 sessions per ASN
ORDER BY session_count DESC
LIMIT 500;
```

**Save As**: `scripts/phase1/sql_query_12_asn_infrastructure_analysis.sql`

**Expected Insights**:
- Cloud provider abuse (AWS, Azure, GCP prevalence)
- Hosting provider concentration (DigitalOcean, OVH, Hetzner)
- ISP/Telecom vs datacenter infrastructure ratio

### NEW Query 13: VPN/Proxy/Tor Anonymization Analysis

**Purpose**: Measure operational security sophistication via anonymization techniques

**Query**:
```sql
-- ============================================================================
-- QUERY 13: VPN/Proxy/Tor Anonymization Analysis
-- ============================================================================
-- PURPOSE: Measure adversary operational security via anonymization
-- EXPECTED: ~100-500 rows (daily anonymization stats)
-- CSV: results/13_anonymization_analysis.csv
-- ============================================================================

SELECT
    DATE(first_event_at) as attack_date,
    COUNT(DISTINCT session_id) as total_sessions,
    -- VPN detection
    SUM(CASE WHEN enrichment->>'is_vpn' = 'true' THEN 1 ELSE 0 END) as vpn_sessions,
    ROUND(100.0 * SUM(CASE WHEN enrichment->>'is_vpn' = 'true' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) as vpn_ratio,
    -- Proxy detection
    SUM(CASE WHEN enrichment->>'is_proxy' = 'true' THEN 1 ELSE 0 END) as proxy_sessions,
    ROUND(100.0 * SUM(CASE WHEN enrichment->>'is_proxy' = 'true' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) as proxy_ratio,
    -- Tor detection
    SUM(CASE WHEN enrichment->>'is_tor' = 'true' THEN 1 ELSE 0 END) as tor_sessions,
    ROUND(100.0 * SUM(CASE WHEN enrichment->>'is_tor' = 'true' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) as tor_ratio,
    -- Any anonymization
    SUM(CASE WHEN enrichment->>'is_vpn' = 'true' OR enrichment->>'is_proxy' = 'true' OR enrichment->>'is_tor' = 'true' THEN 1 ELSE 0 END) as anonymized_sessions,
    ROUND(100.0 * SUM(CASE WHEN enrichment->>'is_vpn' = 'true' OR enrichment->>'is_proxy' = 'true' OR enrichment->>'is_tor' = 'true' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) as anonymization_ratio,
    -- SPUR client type distribution
    COUNT(CASE WHEN enrichment->'spur'->>'client' = 'RESIDENTIAL' THEN 1 END) as residential_count,
    COUNT(CASE WHEN enrichment->'spur'->>'client' = 'DATACENTER' THEN 1 END) as datacenter_count,
    COUNT(CASE WHEN enrichment->'spur'->>'client' = 'HOSTING' THEN 1 END) as hosting_count
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND enrichment IS NOT NULL
GROUP BY DATE(first_event_at)
ORDER BY attack_date DESC;
```

**Save As**: `scripts/phase1/sql_query_13_anonymization_analysis.sql`

**Expected Insights**:
- VPN usage percentage (high = sophisticated actors)
- Tor usage percentage (APT/nation-state indicator)
- Residential vs datacenter infrastructure ratio

### NEW Query 14: Reputation Score Distribution

**Purpose**: Analyze DShield attack scores for known-bad infrastructure prioritization

**Query**:
```sql
-- ============================================================================
-- QUERY 14: DShield Reputation Score Distribution
-- ============================================================================
-- PURPOSE: Prioritize response based on DShield attack history
-- EXPECTED: ~100-500 rows (reputation score buckets)
-- CSV: results/14_reputation_distribution.csv
-- ============================================================================

SELECT
    -- Bucket DShield attack counts
    CASE
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) = 0 THEN '0_first_time'
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) BETWEEN 1 AND 10 THEN '1-10_low'
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) BETWEEN 11 AND 100 THEN '11-100_medium'
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) BETWEEN 101 AND 1000 THEN '101-1000_high'
        WHEN CAST(enrichment->'dshield'->>'attacks' AS INTEGER) > 1000 THEN '1000+_very_high'
        ELSE 'unknown'
    END as reputation_bucket,
    COUNT(DISTINCT session_id) as session_count,
    AVG(command_count) as avg_commands,
    SUM(file_downloads) as total_downloads,
    SUM(CASE WHEN vt_flagged THEN 1 ELSE 0 END) as vt_flagged_count,
    -- Calculate percentage of total
    ROUND(100.0 * COUNT(DISTINCT session_id) / (SELECT COUNT(*) FROM session_summaries WHERE first_event_at >= '2024-11-01' AND enrichment->'dshield'->>'attacks' IS NOT NULL), 2) as percentage
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND enrichment->'dshield'->>'attacks' IS NOT NULL
GROUP BY reputation_bucket
ORDER BY
    CASE reputation_bucket
        WHEN '0_first_time' THEN 1
        WHEN '1-10_low' THEN 2
        WHEN '11-100_medium' THEN 3
        WHEN '101-1000_high' THEN 4
        WHEN '1000+_very_high' THEN 5
        ELSE 6
    END;
```

**Save As**: `scripts/phase1/sql_query_14_reputation_distribution.sql`

**Expected Insights**:
- Percentage of first-time attackers (0 DShield attacks)
- Known-bad infrastructure prevalence (>1000 attacks)
- Correlation between reputation and malware delivery

---

## Phase 4: Execution Plan (Priority Order)

### Step 1: Verify Enrichment (MUST DO FIRST)
```bash
# Diagnostic queries to confirm enrichment is populated
psql -h 10.130.30.89 -U username -d dshield -f scripts/phase1/ENRICHMENT_DIAGNOSTIC_QUERIES_V2.sql
```

**Success Criteria**: >80% country/ASN coverage

### Step 2: Re-Run Existing Queries
```bash
# Query 6: Enrichment analysis (HIGHEST PRIORITY)
psql ... > results/POST_ENRICHMENT_06_enrichment_analysis.csv

# Query 1: Session activity (vt_flagged/dshield_flagged update)
psql ... > results/POST_ENRICHMENT_01_session_activity_patterns.csv

# Query 7: High-activity sessions (flagged status update)
psql ... > results/POST_ENRICHMENT_07_high_activity_sessions.csv

# Query 8: Session feature vectors (enrichment ratios update)
psql ... > results/POST_ENRICHMENT_08_session_feature_vectors.csv
```

### Step 3: Create and Run New Infrastructure Queries
```bash
# NEW Query 11: Geographic distribution
psql ... > results/11_geographic_distribution.csv

# NEW Query 12: ASN/infrastructure analysis
psql ... > results/12_asn_infrastructure_analysis.csv

# NEW Query 13: Anonymization analysis
psql ... > results/13_anonymization_analysis.csv

# NEW Query 14: Reputation distribution
psql ... > results/14_reputation_distribution.csv
```

### Step 4: Generate Updated Feature Analysis Report

**Run Python analysis** on new CSV results:
```bash
uv run python scripts/analyze_infrastructure_features.py \
    --enrichment-csv results/POST_ENRICHMENT_06_enrichment_analysis.csv \
    --geographic-csv results/11_geographic_distribution.csv \
    --asn-csv results/12_asn_infrastructure_analysis.csv \
    --anonymization-csv results/13_anonymization_analysis.csv \
    --reputation-csv results/14_reputation_distribution.csv \
    --output claudedocs/MILESTONE1_INFRASTRUCTURE_FEATURE_ANALYSIS.md
```

**Note**: This Python script needs to be created to automate analysis of infrastructure features.

---

## Summary: Which Queries to Re-Run

### ✅ MUST Re-Run (Enrichment-Dependent)

| Query # | Name | Reason | Priority |
|---------|------|--------|----------|
| **6** | Enrichment Analysis | 100% NULL before → infrastructure features | **CRITICAL** |
| **1** | Session Activity | vt_flagged/dshield_flagged were 0 | **HIGH** |
| **7** | High-Activity Sessions | vt_flagged/dshield_flagged were false | **MEDIUM** |
| **8** | Session Feature Vectors | Enrichment ratios were 0% | **MEDIUM** |

### ✅ NEW Queries to Create (Infrastructure Features)

| Query # | Name | Purpose | Priority |
|---------|------|---------|----------|
| **11** | Geographic Distribution | Country clustering, nation-state detection | **HIGH** |
| **12** | ASN Infrastructure | Cloud provider abuse, hosting patterns | **HIGH** |
| **13** | Anonymization Analysis | VPN/Proxy/Tor operational security | **MEDIUM** |
| **14** | Reputation Distribution | DShield score prioritization | **MEDIUM** |

### ⚠️ DO NOT Need to Re-Run (Behavioral Only)

| Query # | Name | Reason |
|---------|------|--------|
| 2 | SSH Key Reuse | No enrichment dependency |
| 3 | Command Patterns | Behavioral only (command text) |
| 4 | Temporal Behavioral | Behavioral only (hour-of-day, duration) |
| 5 | Password Patterns | Credential analysis only |
| 9 | SSH Key Associations | SSH key clustering only |
| 10 | Weekly Campaign Patterns | Temporal aggregation only |

---

## Validation Checklist

After re-running queries, verify:

- [ ] **Query 6**: Country field >80% populated (not NULL)
- [ ] **Query 6**: ASN field >80% populated (not NULL)
- [ ] **Query 6**: is_vpn/is_proxy/is_tor fields present (true/false)
- [ ] **Query 1**: vt_flagged_sessions >0 (was 0 before)
- [ ] **Query 1**: dshield_flagged_sessions >0 (was 0 before)
- [ ] **Query 11**: Top 10 countries identified (e.g., CN, US, RU)
- [ ] **Query 12**: Cloud providers identified (AWS, Azure, GCP)
- [ ] **Query 13**: Anonymization ratio >0% (VPN/Tor usage detected)
- [ ] **Query 14**: Reputation buckets populated (not all unknown)

---

## Next Steps After Re-Run

1. **Compare Before/After**: Generate diff report showing enrichment impact
2. **Update Feature Analysis**: Re-run feature importance with infrastructure features
3. **Re-Train Baseline Model**: Include Tier 3 infrastructure features
4. **Update Actor Profiling**: Combine behavioral + infrastructure classification
5. **Update Milestone 1 Report**: Document infrastructure insights

---

**Status**: ⏳ Ready to Execute - Awaiting Database Access
**Expected Runtime**: 30-60 minutes for all queries
**Expected Output**: 8 CSV files (4 re-runs + 4 new queries)
