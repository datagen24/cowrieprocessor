# Phase 1A Feature Discovery - Quick Start Guide

## Overview

Phase 1A identifies optimal features for threat actor clustering using data-driven statistical analysis. This guide walks through executing SQL queries on the production database and analyzing results to determine the best feature set.

## Prerequisites

- Access to production PostgreSQL database (10.130.30.89)
- PGAdmin or psql command-line tool
- Python environment with scipy and pandas (`uv sync`)

## Workflow

### Step 1: Execute SQL Queries (30 minutes)

**Location**: `scripts/phase1/sql_analysis_queries.sql`

Run all 10 queries in PGAdmin and export results to CSV:

```bash
# Create results directory
mkdir -p results/

# For each query in sql_analysis_queries.sql:
# 1. Copy query from file
# 2. Execute in PGAdmin
# 3. Export to CSV: results/01_command_diversity.csv, etc.
```

**Expected Output Files**:
- `results/01_command_diversity.csv` (~100-500 rows)
- `results/02_ttp_sequences.csv` (~200-1000 rows)
- `results/03_temporal_patterns.csv` (~168 rows, 24h × 7d)
- `results/04_asn_clustering.csv` (~50-200 rows)
- `results/05_ssh_key_reuse.csv` (~50-200 rows) **← GOLD MINE**
- `results/06_password_analysis.csv` (~100-500 rows)
- `results/07_persistence_techniques.csv` (~365 rows)
- `results/08_credential_access.csv` (~365 rows)
- `results/09_reconnaissance.csv` (~365 rows)
- `results/10_campaign_correlation.csv` (~500 rows)

**Notes**:
- Query 5 (SSH key reuse) is critical for actor tracking
- Queries 7-9 focus on MITRE techniques (Persistence, Credential Access, Recon)
- Query 10 finds similar campaigns for clustering seeds

### Step 2: Analyze Feature Importance (5 minutes)

**Location**: `scripts/phase1/analyze_feature_importance.py`

Run the Python analysis script to calculate discrimination scores:

```bash
# Analyze all query results
uv run python scripts/phase1/analyze_feature_importance.py \
    --results-dir results/ \
    --output docs/phase1/feature_discovery_analysis.md \
    --top-n 40 \
    --verbose
```

**What It Does**:
1. Loads all CSV files from `results/` directory
2. Calculates statistical measures for each feature:
   - **Variance**: Inter-campaign variability
   - **Mutual Information**: Information gain about campaign identity
   - **Chi-Square**: Independence from campaign identity
3. Computes combined discrimination score (0-1)
4. Ranks features by discriminative power
5. Generates comprehensive Markdown report

**Output**: `docs/phase1/feature_discovery_analysis.md`

### Step 3: Review Analysis Report (15 minutes)

Open `docs/phase1/feature_discovery_analysis.md` and review:

1. **Executive Summary**: Total features analyzed, recommended count
2. **Top Features Table**: Ranked by discrimination score
3. **Category Analysis**: Features grouped by type (TTP, Temporal, Infrastructure, etc.)
4. **Recommendations**: Which features to implement for Phase 1B

**Key Metrics**:
- **Discrimination Score ≥0.7**: Excellent actor discrimination
- **Discrimination Score 0.6-0.7**: Good discrimination
- **Discrimination Score <0.6**: Consider excluding

### Step 4: Validate Feature Count (Discussion)

Compare recommended feature count against Phase 1 targets:

- **Target**: 20-40 optimal features (data-driven)
- **Actual**: See report "Recommended Feature Count" section
- **Decision**: Finalize feature set for Phase 1B implementation

## Expected Timeline

| Phase | Duration | Task |
|-------|----------|------|
| 1A.1 (SQL) | 30 min | Execute 10 SQL queries in PGAdmin |
| 1A.1 (Python) | 5 min | Run feature importance analysis |
| 1A.1 (Review) | 15 min | Review analysis report |
| **Total** | **50 min** | **Complete Phase 1A.1** |

## Troubleshooting

### Issue: Missing CSV files

**Error**: `FileNotFoundError: results/01_command_diversity.csv`

**Solution**: Ensure all queries have been executed and exported. The script will skip missing files but needs at least 1 CSV to run.

### Issue: Database connection timeout

**Error**: `psycopg2.OperationalError: could not connect to server`

**Solution**: Verify VPN connection to production network and database credentials in `config/sensors.toml`.

### Issue: Pandas/Scipy import errors

**Error**: `ModuleNotFoundError: No module named 'scipy'`

**Solution**: Install analysis dependencies:
```bash
uv sync  # Installs all dev dependencies including scipy, pandas
```

### Issue: Chi-square calculation warnings

**Warning**: `Chi-square calculation error: Expected frequency in cell < 5`

**Solution**: This is normal for sparse features. The script handles gracefully and reports 0.0 score.

## Next Steps After Phase 1A.1

Once you have the feature discovery analysis report:

1. **Review Top Features**: Validate that recommended features make sense for TTP profiling
2. **Phase 1A.2**: Analyze known SSH persistent campaign for actor template
3. **Phase 1B**: Implement MITRE ATT&CK mapper
4. **Phase 1C**: Begin Random Forest training with selected features

## File Locations

```
cowrieprocessor/
├── scripts/phase1/
│   ├── sql_analysis_queries.sql           # Step 1: SQL queries
│   └── analyze_feature_importance.py      # Step 2: Python analysis
├── results/                                 # Step 1 output: CSV files
│   ├── 01_command_diversity.csv
│   ├── 02_ttp_sequences.csv
│   └── ... (10 total)
└── docs/phase1/
    ├── PHASE1A_QUICKSTART.md              # This guide
    └── feature_discovery_analysis.md      # Step 2 output: Analysis report
```

## Command Reference

```bash
# Quick execution (after SQL queries complete)
cd /path/to/cowrieprocessor
uv run python scripts/phase1/analyze_feature_importance.py --verbose

# Custom output location
uv run python scripts/phase1/analyze_feature_importance.py \
    --results-dir /custom/results/ \
    --output /custom/analysis.md \
    --top-n 50

# Help
uv run python scripts/phase1/analyze_feature_importance.py --help
```

## Success Criteria

Phase 1A.1 is complete when:

✅ All 10 SQL queries executed successfully
✅ CSV files exported to `results/` directory
✅ Python analysis script runs without errors
✅ Analysis report generated with feature recommendations
✅ Feature count validated (20-40 range)
✅ Ready to proceed to Phase 1A.2

---

**Phase 1A.1 Status**: SQL queries ready, Python analysis ready, awaiting execution
**Next**: Execute SQL queries on production database
**Owner**: User (database access required)
