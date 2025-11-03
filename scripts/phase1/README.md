# Phase 1A Feature Discovery Scripts

Data-driven feature selection for threat actor clustering using statistical analysis on production database.

## Scripts

### 1. `sql_analysis_queries.sql` (800+ lines)
10 PostgreSQL queries for production database analysis:

- **Query 1-4**: Campaign fingerprinting (command diversity, TTP sequences, temporal patterns, ASN clustering)
- **Query 5**: SSH Key Reuse (**GOLD MINE** for persistent actor tracking)
- **Query 6**: Password List Analysis (credential stuffing patterns)
- **Query 7-9**: MITRE Techniques (Persistence, Credential Access, Recon)
- **Query 10**: Campaign Correlation Matrix (actor clustering seeds)

**Usage**: Execute in PGAdmin, export to CSV files in `results/` directory

### 2. `analyze_feature_importance.py` (700+ lines)
Python script for statistical feature analysis:

**Input**: CSV files from SQL queries
**Output**: Feature discovery analysis report (Markdown)

**Statistical Measures**:
- Variance (30%): Inter-campaign variability
- Mutual Information (40%): Information gain
- Chi-Square (30%): Statistical independence

**Usage**:
```bash
# Quick start (after SQL queries executed)
uv run python scripts/phase1/analyze_feature_importance.py --verbose

# Custom paths
uv run python scripts/phase1/analyze_feature_importance.py \
    --results-dir /custom/results/ \
    --output /custom/analysis.md \
    --top-n 50

# Help
uv run python scripts/phase1/analyze_feature_importance.py --help
```

## Quick Start

See `docs/phase1/PHASE1A_QUICKSTART.md` for step-by-step instructions.

**Timeline**: 50 minutes total
1. Execute SQL queries (30 min)
2. Run Python analysis (5 min)
3. Review report (15 min)

## Expected Output

**Feature Discovery Report**: `docs/phase1/feature_discovery_analysis.md`

Contains:
- Total features analyzed (60-100 estimated)
- Top features ranked by discrimination score
- Category breakdown (TTP, Temporal, Infrastructure, Credential, MITRE)
- Recommendations for Phase 1B implementation
- Data-driven optimal feature count (target: 20-40)

## Dependencies

Python dependencies installed via `uv sync`:
- pandas (CSV processing)
- numpy (numerical calculations)
- scipy (statistical tests: chi-square, entropy)

## Phase Context

**Phase 1A.1**: Feature Discovery (SQL + Python Analysis)
**Phase 1A.2**: Analyze SSH Persistent Campaign (create known actor template)
**Phase 1B**: MITRE Mapper Implementation
**Phase 1C**: Random Forest Training

See `docs/pdca/phase1-ttp-profiling/plan.md` for comprehensive Phase 1 plan.

## Status

✅ Scripts complete and ready
⏳ Awaiting execution on production database
📊 Estimated 60-100 features to analyze
🎯 Target: 20-40 optimal features for Phase 1B

---

**Created**: 2025-11-01
**Owner**: Phase 1 TTP Profiling
**Purpose**: Data-driven feature selection for threat actor clustering
