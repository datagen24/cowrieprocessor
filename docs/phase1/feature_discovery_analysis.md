# Phase 1A Feature Discovery Analysis Report

**Generated**: 2025-11-01 16:01:12
**Total Features Analyzed**: 7
**Average Discrimination Score**: 0.380
**Features Above Threshold (≥0.6)**: 2

---

## Executive Summary

Analyzed 7 potential features from 10 SQL queries. Identified **2 high-discrimination features** suitable for threat actor clustering.

### Recommended Feature Count: **2**

Based on statistical analysis (variance, mutual information, chi-square tests), we recommend using the top **2 features** for Phase 1B Random Forest training.

---

## Top Features by Discrimination Score

| Rank | Feature | Disc. Score | Variance | MI | Chi² | Samples |
|------|---------|-------------|----------|-----|------|---------|
| 1 | `cmd_div_session_count` | 1.000 | 1.000 | 1.000 | 951.0 | 317 |
| 2 | `cmd_div_avg_duration_seconds` | 0.859 | 0.530 | 1.000 | 951.0 | 317 |
| 3 | `cmd_div_session_count` | 0.300 | 1.000 | 0.000 | 0.0 | 50 |
| 4 | `ssh_unique_ips` | 0.289 | 0.964 | 0.000 | 0.0 | 2 |
| 5 | `temporal_day_of_week` | 0.127 | 0.423 | 0.000 | 0.0 | 5000 |
| 6 | `temporal_hour_of_day` | 0.087 | 0.291 | 0.000 | 0.0 | 5000 |
| 7 | `infra_asn` | 0.000 | 0.000 | 0.000 | 0.0 | 0 |

---

## Feature Categories Analysis

### Infrastructure Fingerprints

- **Features Analyzed**: 2
- **Average Discrimination**: 0.145
- **Recommended Count**: 0

**Top Features in Category**:

- `ssh_unique_ips`: 0.289 (2 unique values)
- `infra_asn`: 0.000 (0 unique values)


### Temporal Behavioral

- **Features Analyzed**: 2
- **Average Discrimination**: 0.107
- **Recommended Count**: 0

**Top Features in Category**:

- `temporal_day_of_week`: 0.127 (7 unique values)
- `temporal_hour_of_day`: 0.087 (24 unique values)


---

## Statistical Methodology

### Discrimination Score Calculation

Combined score (0-1) using weighted average:
- **Variance** (30%): Measures inter-campaign variability
- **Mutual Information** (40%): Measures information gain about campaign identity
- **Chi-Square** (30%): Tests independence from campaign identity

### Thresholds

- **High Discrimination**: ≥0.7 (excellent actor discrimination)
- **Moderate Discrimination**: 0.6-0.7 (good discrimination)
- **Low Discrimination**: <0.6 (consider excluding)

---

## Recommendations for Phase 1B

1. **Feature Set**: Use top 2 features for Random Forest training
2. **Implementation**: Create `cowrieprocessor/features/ttp_features.py`
3. **Validation**: Test on 22-incident Phase 0 baseline dataset
4. **Target Metrics**:
   - Recall: ≥0.85 (minimize missed threat actors)
   - Precision: ≥0.70 (acceptable false positive rate)
   - F1 Score: ≥0.75 (30% improvement over 0.667 baseline)

---

## Next Steps

1. **Review SSH Key Features**: Query 5 (SSH key reuse) is **gold mine** - validate these features on production data
2. **MITRE Mapping**: Implement MITRE ATT&CK mapper for technique-based features
3. **Feature Engineering**: Implement top features in production code
4. **Phase 1B Kickoff**: Begin Random Forest training with selected features

---

**Report End**