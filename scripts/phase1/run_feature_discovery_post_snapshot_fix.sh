#!/bin/bash
# ============================================================================
# Feature Discovery Query Execution - Post-Snapshot Fix
# ============================================================================
# PURPOSE: Re-run all feature discovery queries after ADR-007 snapshot backfill
# DATE: 2025-11-10
# CONTEXT: Snapshot columns (snapshot_asn, snapshot_country, snapshot_ip_type)
#          are now populated for 1.68M sessions. Infrastructure features should
#          now have high discrimination scores.
# ============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "============================================================================"
echo "Feature Discovery Query Execution - Post-Snapshot Fix"
echo "============================================================================"
echo ""

# Database connection from config/sensors.toml
DB_URL="postgresql://cowrieprocessor:<DB_PASSWORD>@10.130.30.89:5432/cowrieprocessor"
DB_HOST="10.130.30.89"
DB_USER="cowrieprocessor"
DB_NAME="cowrieprocessor"
RESULTS_DIR="results/feature_discovery_2025-11-10"

echo "Database: ${DB_HOST}/${DB_NAME}"
echo "Results directory: ${RESULTS_DIR}"
echo ""

# Create results directory
mkdir -p "${RESULTS_DIR}"

# ============================================================================
# PHASE 1: Verify Snapshot Backfill Completeness
# ============================================================================

echo -e "${YELLOW}PHASE 1: Verifying snapshot backfill status...${NC}"
echo ""

SNAPSHOT_CHECK=$(PGPASSWORD=<DB_PASSWORD> psql -h "${DB_HOST}" -U "${DB_USER}" -d "${DB_NAME}" -t -c "
SELECT
    COUNT(*) as total_sessions,
    COUNT(CASE WHEN snapshot_asn IS NOT NULL THEN 1 END) as has_snapshot_asn,
    COUNT(CASE WHEN snapshot_country IS NOT NULL THEN 1 END) as has_snapshot_country,
    COUNT(CASE WHEN snapshot_ip_type IS NOT NULL THEN 1 END) as has_snapshot_ip_type,
    ROUND(100.0 * COUNT(CASE WHEN snapshot_asn IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as asn_pct,
    ROUND(100.0 * COUNT(CASE WHEN snapshot_country IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as country_pct,
    ROUND(100.0 * COUNT(CASE WHEN snapshot_ip_type IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as ip_type_pct
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND first_event_at < '2025-11-01';
")

echo "Snapshot backfill verification:"
echo "${SNAPSHOT_CHECK}"
echo ""

# Extract percentages
ASN_PCT=$(echo "${SNAPSHOT_CHECK}" | awk '{print $11}')
COUNTRY_PCT=$(echo "${SNAPSHOT_CHECK}" | awk '{print $13}')

if (( $(echo "${ASN_PCT} < 80" | bc -l) )); then
    echo -e "${RED}ERROR: Snapshot ASN coverage too low (${ASN_PCT}% < 80%)${NC}"
    echo "Snapshot backfill may not be complete."
    exit 1
else
    echo -e "${GREEN}✓ Snapshot coverage validated:${NC}"
    echo -e "  - ASN: ${ASN_PCT}%"
    echo -e "  - Country: ${COUNTRY_PCT}%"
    echo ""
fi

# ============================================================================
# PHASE 2: Core Feature Discovery Queries (Original 10 queries)
# ============================================================================

echo -e "${YELLOW}PHASE 2: Running core feature discovery queries...${NC}"
echo ""

# Query 1: Session Activity Patterns
echo -e "${BLUE}Query 1: Session Activity Patterns${NC}"
PGPASSWORD=<DB_PASSWORD> psql -h "${DB_HOST}" -U "${DB_USER}" -d "${DB_NAME}" \
     -c "\copy (
         SELECT
             DATE(first_event_at) as attack_date,
             COUNT(DISTINCT session_id) as session_count,
             SUM(command_count) as total_commands,
             AVG(command_count) as avg_commands_per_session,
             SUM(file_downloads) as total_file_downloads,
             SUM(login_attempts) as total_login_attempts,
             SUM(ssh_key_injections) as total_ssh_key_injections,
             SUM(CASE WHEN vt_flagged THEN 1 ELSE 0 END) as vt_flagged_sessions,
             SUM(CASE WHEN dshield_flagged THEN 1 ELSE 0 END) as dshield_flagged_sessions,
             AVG(EXTRACT(EPOCH FROM (last_event_at - first_event_at))) as avg_duration_seconds,
             STDDEV(command_count) as command_count_stddev
         FROM session_summaries
         WHERE first_event_at >= '2024-11-01'
           AND first_event_at < '2025-11-01'
         GROUP BY DATE(first_event_at)
         ORDER BY attack_date DESC
     ) TO STDOUT WITH CSV HEADER" \
     > "${RESULTS_DIR}/01_session_activity_patterns.csv"
echo -e "${GREEN}✓ Query 1 complete ($(wc -l < ${RESULTS_DIR}/01_session_activity_patterns.csv) rows)${NC}"
echo ""

# Query 2: SSH Key Reuse (GOLD MINE)
echo -e "${BLUE}Query 2: SSH Key Reuse Analysis${NC}"
PGPASSWORD=<DB_PASSWORD> psql -h "${DB_HOST}" -U "${DB_USER}" -d "${DB_NAME}" \
     -c "\copy (
         SELECT
             key_fingerprint,
             key_type,
             key_bits,
             pattern_type,
             first_seen,
             last_seen,
             (last_seen - first_seen) as campaign_duration,
             total_attempts,
             unique_sources as unique_ips,
             unique_sessions,
             CAST(unique_sessions AS FLOAT) / NULLIF(total_attempts, 0) as session_efficiency_ratio,
             EXTRACT(EPOCH FROM (last_seen - first_seen)) / NULLIF(total_attempts, 0) as avg_time_between_attempts
         FROM ssh_key_intelligence
         WHERE first_seen >= '2024-11-01'
           AND unique_sources >= 3
         ORDER BY unique_sources DESC, total_attempts DESC
         LIMIT 200
     ) TO STDOUT WITH CSV HEADER" \
     > "${RESULTS_DIR}/02_ssh_key_reuse.csv"
echo -e "${GREEN}✓ Query 2 complete ($(wc -l < ${RESULTS_DIR}/02_ssh_key_reuse.csv) rows)${NC}"
echo ""

# ============================================================================
# PHASE 3: NEW Infrastructure Feature Queries (Leverage Snapshot Columns)
# ============================================================================

echo -e "${YELLOW}PHASE 3: Running NEW infrastructure feature queries...${NC}"
echo ""

# Query 11: Geographic Distribution
echo -e "${BLUE}Query 11: Geographic Distribution${NC}"
PGPASSWORD=<DB_PASSWORD> psql -h "${DB_HOST}" -U "${DB_USER}" -d "${DB_NAME}" \
     -f scripts/phase1/sql_query_11_geographic_distribution.sql \
     --csv > "${RESULTS_DIR}/11_geographic_distribution.csv"
echo -e "${GREEN}✓ Query 11 complete ($(wc -l < ${RESULTS_DIR}/11_geographic_distribution.csv) rows)${NC}"
echo ""

# Query 12: ASN Infrastructure Analysis
echo -e "${BLUE}Query 12: ASN Infrastructure Analysis${NC}"
PGPASSWORD=<DB_PASSWORD> psql -h "${DB_HOST}" -U "${DB_USER}" -d "${DB_NAME}" \
     -f scripts/phase1/sql_query_12_asn_infrastructure_analysis.sql \
     --csv > "${RESULTS_DIR}/12_asn_infrastructure_analysis.csv"
echo -e "${GREEN}✓ Query 12 complete ($(wc -l < ${RESULTS_DIR}/12_asn_infrastructure_analysis.csv) rows)${NC}"
echo ""

# Query 13: Anonymization Analysis (VPN/Proxy/Tor detection)
echo -e "${BLUE}Query 13: Anonymization Analysis${NC}"
PGPASSWORD=<DB_PASSWORD> psql -h "${DB_HOST}" -U "${DB_USER}" -d "${DB_NAME}" \
     -f scripts/phase1/sql_query_13_anonymization_analysis.sql \
     --csv > "${RESULTS_DIR}/13_anonymization_analysis.csv"
echo -e "${GREEN}✓ Query 13 complete ($(wc -l < ${RESULTS_DIR}/13_anonymization_analysis.csv) rows)${NC}"
echo ""

# Query 14: Reputation Distribution
echo -e "${BLUE}Query 14: Reputation Distribution${NC}"
PGPASSWORD=<DB_PASSWORD> psql -h "${DB_HOST}" -U "${DB_USER}" -d "${DB_NAME}" \
     -f scripts/phase1/sql_query_14_reputation_distribution_FIXED.sql \
     --csv > "${RESULTS_DIR}/14_reputation_distribution.csv"
echo -e "${GREEN}✓ Query 14 complete ($(wc -l < ${RESULTS_DIR}/14_reputation_distribution.csv) rows)${NC}"
echo ""

# Query 15: Snapshot-Based Session Clustering (NEW - leverages snapshot columns directly)
echo -e "${BLUE}Query 15: Snapshot-Based Session Clustering${NC}"
PGPASSWORD=<DB_PASSWORD> psql -h "${DB_HOST}" -U "${DB_USER}" -d "${DB_NAME}" \
     -c "\copy (
         SELECT
             snapshot_asn,
             snapshot_country,
             snapshot_ip_type,
             COUNT(DISTINCT session_id) as session_count,
             COUNT(DISTINCT DATE(first_event_at)) as days_active,
             AVG(command_count) as avg_commands,
             AVG(EXTRACT(EPOCH FROM (last_event_at - first_event_at))) as avg_duration_sec,
             SUM(file_downloads) as total_downloads,
             SUM(ssh_key_injections) as total_ssh_injections,
             -- Calculate ASN concentration
             COUNT(DISTINCT session_id)::numeric /
             (SELECT COUNT(DISTINCT session_id)
              FROM session_summaries
              WHERE first_event_at >= '2024-11-01'
                AND first_event_at < '2025-11-01'
                AND snapshot_asn IS NOT NULL) as asn_concentration,
             -- Geographic diversity within ASN
             COUNT(DISTINCT snapshot_country) as countries_per_asn
         FROM session_summaries
         WHERE first_event_at >= '2024-11-01'
           AND first_event_at < '2025-11-01'
           AND snapshot_asn IS NOT NULL
         GROUP BY snapshot_asn, snapshot_country, snapshot_ip_type
         HAVING COUNT(DISTINCT session_id) >= 10
         ORDER BY session_count DESC
         LIMIT 1000
     ) TO STDOUT WITH CSV HEADER" \
     > "${RESULTS_DIR}/15_snapshot_session_clustering.csv"
echo -e "${GREEN}✓ Query 15 complete ($(wc -l < ${RESULTS_DIR}/15_snapshot_session_clustering.csv) rows)${NC}"
echo ""

# ============================================================================
# PHASE 4: Feature Importance Analysis
# ============================================================================

echo -e "${YELLOW}PHASE 4: Running feature importance analysis...${NC}"
echo ""

uv run python scripts/phase1/analyze_feature_importance.py \
    --results-dir "${RESULTS_DIR}" \
    --output "docs/phase1/feature_discovery_analysis_post_snapshot_fix.md" \
    --top-n 40 \
    --verbose

echo -e "${GREEN}✓ Feature analysis complete${NC}"
echo ""

# ============================================================================
# Summary
# ============================================================================

echo "============================================================================"
echo -e "${GREEN}Feature Discovery Re-execution COMPLETE!${NC}"
echo "============================================================================"
echo ""
echo "Results saved to: ${RESULTS_DIR}/"
echo ""
echo "CSV Files Generated:"
ls -lh "${RESULTS_DIR}"/*.csv
echo ""
echo "Feature Analysis Report:"
echo "  docs/phase1/feature_discovery_analysis_post_snapshot_fix.md"
echo ""
echo "Expected Improvements:"
echo "  - Infrastructure features: 0.145 → 0.7+ discrimination (MAJOR improvement)"
echo "  - Total viable features: 2 → 10-15 expected"
echo "  - ASN clustering: NOW AVAILABLE with snapshot_asn"
echo "  - Geographic diversity: NOW AVAILABLE with snapshot_country"
echo ""
echo "Next Steps:"
echo "  1. Review feature_discovery_analysis_post_snapshot_fix.md"
echo "  2. Compare with original analysis (0.380 avg discrimination)"
echo "  3. Select top 10-12 features for Phase 1B ML detector"
echo "  4. Begin Phase 1B implementation with robust feature set"
echo ""
