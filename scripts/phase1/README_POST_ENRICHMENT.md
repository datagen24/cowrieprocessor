# Post-Enrichment Query Execution Guide

**Date**: 2025-11-02
**Purpose**: Re-run feature discovery queries after enrichment backfill

---

## Quick Start

### Option 1: Automated Script (Recommended)

Run all queries with a single command:

```bash
# Set database connection (optional - defaults shown)
export COWRIEPROC_DB_HOST="10.130.30.89"
export COWRIEPROC_DB_USER="your_username"
export COWRIEPROC_DB_NAME="dshield"
export COWRIEPROC_RESULTS_DIR="results"

# Execute all queries
./scripts/phase1/run_post_enrichment_queries.sh
```

**What it does**:
1. ✅ Verifies enrichment coverage (>80% required)
2. ✅ Re-runs Query 6 (enrichment analysis)
3. ✅ Re-runs Query 1 (session activity with flags)
4. ✅ Runs 4 new infrastructure queries (11-14)
5. ✅ Saves all results to `results/` directory

**Expected runtime**: 2-5 minutes (all 6 queries)

---

### Option 2: Manual Execution (Individual Queries)

Run queries individually for more control:

#### 1. Verify Enrichment First (CRITICAL)

```bash
psql -h 10.130.30.89 -U username -d dshield -c "
SELECT
    COUNT(*) as total_sessions,
    COUNT(CASE WHEN enrichment->'dshield'->>'country' IS NOT NULL THEN 1 END) as has_country,
    ROUND(100.0 * COUNT(CASE WHEN enrichment->'dshield'->>'country' IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as country_pct
FROM session_summaries
WHERE first_event_at >= '2024-11-01';
"
```

**Success criteria**: `country_pct >= 80%`

#### 2. Run New Infrastructure Queries

**Query 11: Geographic Distribution**
```bash
psql -h 10.130.30.89 -U username -d dshield \
     -f scripts/phase1/sql_query_11_geographic_distribution.sql \
     --csv > results/11_geographic_distribution.csv
```

**Query 12: ASN Infrastructure**
```bash
psql -h 10.130.30.89 -U username -d dshield \
     -f scripts/phase1/sql_query_12_asn_infrastructure_analysis.sql \
     --csv > results/12_asn_infrastructure_analysis.csv
```

**Query 13: Anonymization Analysis**
```bash
psql -h 10.130.30.89 -U username -d dshield \
     -f scripts/phase1/sql_query_13_anonymization_analysis.sql \
     --csv > results/13_anonymization_analysis.csv
```

**Query 14: Reputation Distribution**
```bash
psql -h 10.130.30.89 -U username -d dshield \
     -f scripts/phase1/sql_query_14_reputation_distribution.sql \
     --csv > results/14_reputation_distribution.csv
```

---

## Query Descriptions

### Query 11: Geographic Distribution
- **Purpose**: Identify top attacking countries and geographic clustering
- **Expected rows**: 50-200 (countries with >100 sessions)
- **Key fields**: `country`, `session_count`, `unique_asns`, `asn_diversity_ratio`
- **Insights**: Nation-state vs global botnet detection

### Query 12: ASN Infrastructure Analysis
- **Purpose**: Detect cloud provider abuse and hosting patterns
- **Expected rows**: 100-500 (top ASNs)
- **Key fields**: `asn`, `as_name`, `infrastructure_type`, `session_count`
- **Insights**: AWS/Azure/GCP abuse, datacenter vs ISP ratio

### Query 13: Anonymization Analysis
- **Purpose**: Measure operational security via VPN/Proxy/Tor usage
- **Expected rows**: 365 (daily statistics)
- **Key fields**: `vpn_ratio`, `tor_ratio`, `anonymization_ratio`, `datacenter_ratio`
- **Insights**: Sophisticated actors use VPN/Tor, botnets use residential IPs

### Query 14: Reputation Distribution
- **Purpose**: Prioritize response based on DShield attack history
- **Expected rows**: 5-10 (reputation buckets)
- **Key fields**: `reputation_bucket`, `session_count`, `avg_attack_count`
- **Insights**: First-time vs repeat attackers, known-bad infrastructure

---

## Expected Output

### Before Enrichment
```
Query 6: 100% NULL enrichment fields (country, ASN, etc.)
Query 1: vt_flagged_sessions = 0, dshield_flagged_sessions = 0
No infrastructure data available
```

### After Enrichment (Success)
```
Query 6: >80% populated enrichment fields
Query 1: vt_flagged_sessions >0, dshield_flagged_sessions >0
Query 11: Top 10-20 countries identified (e.g., CN, US, RU, BR)
Query 12: Cloud providers visible (AWS, Azure, GCP prevalence)
Query 13: Anonymization ratios calculated (VPN/Tor usage >0%)
Query 14: Reputation buckets populated (not all unknown)
```

---

## Validation Checklist

After running queries, verify:

- [ ] **Enrichment coverage**: country_pct >= 80%
- [ ] **Query 6**: Country/ASN fields populated (not NULL)
- [ ] **Query 1**: vt_flagged_sessions and dshield_flagged_sessions >0
- [ ] **Query 11**: Top countries include CN, US, RU (expected top attackers)
- [ ] **Query 12**: Infrastructure types classified (AWS, Azure, GCP, etc.)
- [ ] **Query 13**: Anonymization ratio >0% (some VPN/Tor detected)
- [ ] **Query 14**: Reputation buckets distributed (not all first-time)

---

## Troubleshooting

### Error: Enrichment coverage <80%

**Symptom**: `country_pct < 80%` in verification query

**Cause**: Enrichment backfill incomplete or failed

**Solution**:
```bash
# Run enrichment backfill
uv run cowrie-enrich refresh --sessions 0 --files 0 --progress

# Monitor progress
watch -n 60 'psql -h 10.130.30.89 -U username -d dshield -c "
SELECT
    ROUND(100.0 * COUNT(CASE WHEN enrichment->'dshield'->>'country' IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as country_pct
FROM session_summaries
WHERE first_event_at >= '\''2024-11-01'\'';
"'
```

### Error: No results in Query 11-14

**Symptom**: CSV files are empty or have only headers

**Cause**: Date range mismatch or no enriched data

**Solution**:
1. Verify enrichment exists: Run verification query
2. Check date range: Ensure sessions exist in `2024-11-01` to `2025-11-01`
3. Inspect sample: `SELECT * FROM session_summaries WHERE enrichment IS NOT NULL LIMIT 5;`

### Error: Permission denied

**Symptom**: `psql: FATAL: permission denied for database "dshield"`

**Solution**:
```bash
# Ensure correct credentials
export PGPASSWORD='your_password'
psql -h 10.130.30.89 -U username -d dshield -c "SELECT 1;"
```

---

## Next Steps

After successful query execution:

1. **Review CSV files**: Open in spreadsheet or pandas
2. **Validate data quality**: Check for NULL values, outliers
3. **Generate analysis report**: Run Python analysis script
4. **Update feature importance**: Re-rank with infrastructure features
5. **Train baseline model**: Include Tier 3 features

---

## File Locations

**Query files**:
- `scripts/phase1/sql_query_11_geographic_distribution.sql`
- `scripts/phase1/sql_query_12_asn_infrastructure_analysis.sql`
- `scripts/phase1/sql_query_13_anonymization_analysis.sql`
- `scripts/phase1/sql_query_14_reputation_distribution.sql`

**Execution script**:
- `scripts/phase1/run_post_enrichment_queries.sh`

**Results**:
- `results/11_geographic_distribution.csv`
- `results/12_asn_infrastructure_analysis.csv`
- `results/13_anonymization_analysis.csv`
- `results/14_reputation_distribution.csv`
- `results/POST_ENRICHMENT_06_enrichment_analysis.csv`
- `results/POST_ENRICHMENT_01_session_activity_patterns.csv`

**Documentation**:
- `claudedocs/POST_ENRICHMENT_QUERY_RERUN_PLAN.md` (comprehensive plan)
- `claudedocs/MILESTONE1_FEATURE_ANALYSIS_REPORT.md` (original behavioral analysis)

---

## Questions?

See comprehensive documentation:
- **Full plan**: `claudedocs/POST_ENRICHMENT_QUERY_RERUN_PLAN.md`
- **Original analysis**: `claudedocs/MILESTONE1_FEATURE_ANALYSIS_REPORT.md`
- **Enrichment investigation**: `claudedocs/ENRICHMENT_CRITICAL_FINDING.md`
