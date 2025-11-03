#!/bin/bash
# ============================================================================
# Post-Enrichment Query Execution Script
# ============================================================================
# PURPOSE: Run all enrichment-dependent queries after backfill completes
# DATE: 2025-11-02
# ============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "============================================================================"
echo "Post-Enrichment Query Execution"
echo "============================================================================"
echo ""

# Database connection parameters (override with environment variables)
DB_HOST="${COWRIEPROC_DB_HOST:-10.130.30.89}"
DB_USER="${COWRIEPROC_DB_USER:-your_username}"
DB_NAME="${COWRIEPROC_DB_NAME:-dshield}"
RESULTS_DIR="${COWRIEPROC_RESULTS_DIR:-results}"

echo "Database: ${DB_HOST}/${DB_NAME}"
echo "User: ${DB_USER}"
echo "Results directory: ${RESULTS_DIR}"
echo ""

# Create results directory if it doesn't exist
mkdir -p "${RESULTS_DIR}"

# ============================================================================
# PHASE 1: Verify Enrichment Completeness
# ============================================================================

echo -e "${YELLOW}PHASE 1: Verifying enrichment data...${NC}"
echo ""

ENRICHMENT_CHECK=$(psql -h "${DB_HOST}" -U "${DB_USER}" -d "${DB_NAME}" -t -c "
SELECT
    COUNT(*) as total_sessions,
    COUNT(CASE WHEN enrichment->'dshield'->>'country' IS NOT NULL THEN 1 END) as has_country,
    ROUND(100.0 * COUNT(CASE WHEN enrichment->'dshield'->>'country' IS NOT NULL THEN 1 END) / NULLIF(COUNT(*), 0), 2) as country_pct
FROM session_summaries
WHERE first_event_at >= '2024-11-01';
")

echo "Enrichment check results:"
echo "${ENRICHMENT_CHECK}"
echo ""

# Extract percentage (assuming format: total | has_country | pct)
COUNTRY_PCT=$(echo "${ENRICHMENT_CHECK}" | awk '{print $5}')

if (( $(echo "${COUNTRY_PCT} < 80" | bc -l) )); then
    echo -e "${RED}ERROR: Enrichment coverage too low (${COUNTRY_PCT}% < 80%)${NC}"
    echo "Please run: uv run cowrie-enrich refresh --sessions 0 --files 0"
    exit 1
else
    echo -e "${GREEN}✓ Enrichment coverage: ${COUNTRY_PCT}% (>= 80%)${NC}"
    echo ""
fi

# ============================================================================
# PHASE 2: Re-run Existing Queries with Enrichment Data
# ============================================================================

echo -e "${YELLOW}PHASE 2: Re-running existing queries with enrichment data...${NC}"
echo ""

# Query 6: Enrichment Analysis (CRITICAL)
echo "Running Query 6: Enrichment Analysis..."
psql -h "${DB_HOST}" -U "${DB_USER}" -d "${DB_NAME}" \
     -c "\copy (
         SELECT
             session_id,
             first_event_at,
             enrichment->'dshield'->>'country' as country,
             enrichment->'dshield'->>'asn' as asn,
             enrichment->'dshield'->>'as_name' as as_name,
             enrichment->'spur'->>'is_vpn' as is_vpn,
             enrichment->'spur'->>'is_proxy' as is_proxy,
             enrichment->'spur'->>'is_tor' as is_tor,
             enrichment->>'organization' as organization,
             enrichment->>'threat_level' as threat_level,
             enrichment->'dshield'->>'attacks' as dshield_attacks,
             enrichment->'dshield'->>'count' as dshield_count,
             enrichment->'spur'->>'client' as spur_client_type
         FROM session_summaries
         WHERE first_event_at >= '2024-11-01'
           AND first_event_at < '2025-11-01'
           AND enrichment IS NOT NULL
         ORDER BY first_event_at DESC
         LIMIT 5000
     ) TO STDOUT WITH CSV HEADER" \
     > "${RESULTS_DIR}/POST_ENRICHMENT_06_enrichment_analysis.csv"
echo -e "${GREEN}✓ Query 6 complete${NC}"
echo ""

# Query 1: Session Activity Patterns (vt_flagged/dshield_flagged update)
echo "Running Query 1: Session Activity Patterns..."
psql -h "${DB_HOST}" -U "${DB_USER}" -d "${DB_NAME}" \
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
     > "${RESULTS_DIR}/POST_ENRICHMENT_01_session_activity_patterns.csv"
echo -e "${GREEN}✓ Query 1 complete${NC}"
echo ""

# ============================================================================
# PHASE 3: Run New Infrastructure Queries
# ============================================================================

echo -e "${YELLOW}PHASE 3: Running new infrastructure feature queries...${NC}"
echo ""

# Query 11: Geographic Distribution
echo "Running Query 11: Geographic Distribution..."
psql -h "${DB_HOST}" -U "${DB_USER}" -d "${DB_NAME}" \
     -f scripts/phase1/sql_query_11_geographic_distribution.sql \
     --csv > "${RESULTS_DIR}/11_geographic_distribution.csv"
echo -e "${GREEN}✓ Query 11 complete${NC}"
echo ""

# Query 12: ASN Infrastructure Analysis
echo "Running Query 12: ASN Infrastructure Analysis..."
psql -h "${DB_HOST}" -U "${DB_USER}" -d "${DB_NAME}" \
     -f scripts/phase1/sql_query_12_asn_infrastructure_analysis.sql \
     --csv > "${RESULTS_DIR}/12_asn_infrastructure_analysis.csv"
echo -e "${GREEN}✓ Query 12 complete${NC}"
echo ""

# Query 13: Anonymization Analysis
echo "Running Query 13: Anonymization Analysis..."
psql -h "${DB_HOST}" -U "${DB_USER}" -d "${DB_NAME}" \
     -f scripts/phase1/sql_query_13_anonymization_analysis.sql \
     --csv > "${RESULTS_DIR}/13_anonymization_analysis.csv"
echo -e "${GREEN}✓ Query 13 complete${NC}"
echo ""

# Query 14: Reputation Distribution
echo "Running Query 14: Reputation Distribution..."
psql -h "${DB_HOST}" -U "${DB_USER}" -d "${DB_NAME}" \
     -f scripts/phase1/sql_query_14_reputation_distribution.sql \
     --csv > "${RESULTS_DIR}/14_reputation_distribution.csv"
echo -e "${GREEN}✓ Query 14 complete${NC}"
echo ""

# ============================================================================
# Summary
# ============================================================================

echo "============================================================================"
echo -e "${GREEN}All queries completed successfully!${NC}"
echo "============================================================================"
echo ""
echo "Results saved to:"
echo "  - ${RESULTS_DIR}/POST_ENRICHMENT_06_enrichment_analysis.csv"
echo "  - ${RESULTS_DIR}/POST_ENRICHMENT_01_session_activity_patterns.csv"
echo "  - ${RESULTS_DIR}/11_geographic_distribution.csv"
echo "  - ${RESULTS_DIR}/12_asn_infrastructure_analysis.csv"
echo "  - ${RESULTS_DIR}/13_anonymization_analysis.csv"
echo "  - ${RESULTS_DIR}/14_reputation_distribution.csv"
echo ""
echo "Next steps:"
echo "  1. Review CSV files for data quality"
echo "  2. Run feature analysis: uv run python scripts/analyze_infrastructure_features.py"
echo "  3. Generate updated report: claudedocs/MILESTONE1_INFRASTRUCTURE_FEATURE_ANALYSIS.md"
echo ""
