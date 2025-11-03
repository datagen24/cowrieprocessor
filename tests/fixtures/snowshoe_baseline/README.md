# Snowshoe Baseline Dataset

Labeled attack incidents for snowshoe spam detection algorithm validation and baseline establishment.

## Overview

This dataset contains manually labeled honeypot attack incidents across multiple categories, designed to:
- Establish baseline metrics for snowshoe detection algorithm (#54)
- Provide ground truth for algorithm validation (#55)
- Enable testing of edge cases and false positive scenarios
- Support algorithm tuning and threshold optimization

**Version**: 2.0 (MVP Complete - 22 incidents)
**Created**: 2024-10-15
**Completed**: 2024-11-01
**Target**: 100+ incidents (Issue #60)

## Dataset Structure

```
snowshoe_baseline/
├── credential_stuffing/     # 50-150 IPs, password reuse attacks
│   ├── *_data.json         # Session data + raw events
│   └── *_metadata.json     # Ground truth labels + characteristics
├── targeted_attacks/        # 10-30 IPs, focused account attacks
├── hybrid_attacks/          # Mixed patterns (snowshoe + targeted)
├── legitimate_traffic/      # Should NOT cluster as attacks
├── edge_cases/             # Single IP, null passwords, IPv6, etc.
├── README.md               # This file
├── validate_metadata.py    # Schema validation script
├── extract_incidents.py    # Database extraction tool
└── stats.py               # Dataset statistics generator
```

## Incident Format

Each incident consists of two files:

### 1. Data File (`*_data.json`)
```json
{
  "sessions": [
    {
      "session_id": "abc123",
      "first_event_at": "2024-01-15T10:23:14Z",
      "event_count": 5,
      "login_attempts": 3,
      "enrichment": {
        "src_ip": "1.2.3.4",
        "dshield": {...}
      }
    }
  ],
  "events": [
    {
      "id": 1001,
      "session_id": "abc123",
      "event_type": "cowrie.login.failed",
      "payload": {...}
    }
  ]
}
```

### 2. Metadata File (`*_metadata.json`)
```json
{
  "incident_id": "credential_stuffing_001_20240115",
  "category": "credential_stuffing",
  "date_range": {
    "start": "2024-01-15T10:23:14Z",
    "end": "2024-01-15T10:23:27Z"
  },
  "ip_count": 127,
  "session_count": 453,
  "attack_characteristics": {
    "password_reuse": true,
    "username_reuse": false,
    "geographic_spread": "global",
    "temporal_pattern": "burst",
    "command_similarity": "high"
  },
  "ground_truth_label": "snowshoe_spam",
  "confidence": "high",
  "reviewer": "manual_analysis",
  "review_date": "2024-10-15",
  "notes": "Detailed incident description..."
}
```

## Categories

### Credential Stuffing (Target: 5 incidents)
**Characteristics**:
- IP count: 50-150
- Session count: 100-1000
- Password reuse: High
- Temporal pattern: Burst (minutes to hours)
- Geographic spread: Global
- Commands: Minimal or none

**Ground truth label**: `snowshoe_spam`

**Example attacks**:
- Botnet credential testing
- Compromised proxy rotation
- VPN/exit node rotation

### Targeted Attacks (Target: 5 incidents)
**Characteristics**:
- IP count: 10-30
- Session count: 20-200
- Username reuse: High (specific accounts)
- Temporal pattern: Sustained (hours to days)
- Geographic spread: Regional
- Commands: Moderate to high

**Ground truth label**: `targeted_attack`

**Example attacks**:
- APT reconnaissance
- Manual exploitation
- Semi-automated attack frameworks

### Hybrid Attacks (Target: 5 incidents)
**Characteristics**:
- IP count: 20-100
- Session count: 50-500
- Mixed patterns: Credential stuffing + exploitation
- Temporal pattern: Mixed
- Geographic spread: Global
- Commands: Varies

**Ground truth label**: `hybrid`

**Example attacks**:
- Botnet with exploitation modules
- Coordinated campaigns
- Multi-stage attacks

### Legitimate Traffic (Target: 5 incidents)
**Characteristics**:
- IP count: 1-10
- Session count: 1-20
- Password reuse: Low
- Temporal pattern: Sporadic
- Geographic spread: Local/regional
- Commands: Varies

**Ground truth label**: `legitimate_traffic`

**Examples**:
- Security researchers
- Monitoring services
- Authorized testing
- Misconfigurations

### Edge Cases (Variable count)
**Purpose**: Test algorithm robustness

**Examples**:
- Single IP attack (tests minimum IP threshold)
- No commands recorded (authentication only)
- Empty/null passwords (data quality)
- IPv4/IPv6 mixed traffic
- Multi-day spanning attacks
- Very high IP counts (>500)
- Extremely slow attacks (days/weeks)

## Metadata Schema

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `incident_id` | string | Format: `{category}_{number}_{YYYYMMDD}` |
| `category` | enum | One of 5 categories above |
| `date_range` | object | `{start, end}` ISO 8601 timestamps |
| `ip_count` | integer | Unique source IPs in incident |
| `session_count` | integer | Total sessions in incident |
| `attack_characteristics` | object | See below |
| `ground_truth_label` | enum | `snowshoe_spam`, `targeted_attack`, `hybrid`, `legitimate_traffic`, `unknown` |
| `confidence` | enum | `high`, `medium`, `low` |
| `reviewer` | string | Who labeled this incident |
| `review_date` | string | ISO 8601 date |

### Attack Characteristics

| Field | Type | Values |
|-------|------|--------|
| `password_reuse` | boolean | Same password across multiple IPs |
| `username_reuse` | boolean | Same username across multiple IPs |
| `geographic_spread` | enum | `local`, `regional`, `national`, `global` |
| `temporal_pattern` | enum | `burst`, `sustained`, `sporadic`, `mixed` |
| `command_similarity` | enum | `none`, `low`, `medium`, `high`, `identical` |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `notes` | string | Detailed analysis and observations |
| `enrichment_coverage` | object | Percentage of sessions with enrichment data |

## Usage

### 1. Validate Metadata Schema
```bash
# Validate all metadata files
uv run python validate_metadata.py

# Output:
# ✅ All metadata files are valid!
```

### 2. Extract Incidents from Database
```bash
# Extract credential stuffing attacks
uv run python extract_incidents.py \
    --category credential_stuffing \
    --days 90 \
    --limit 5 \
    --db "postgresql://user:pass@host/db"

# Extract all categories
uv run python extract_incidents.py \
    --all-categories \
    --limit 20 \
    --db "env:DATABASE_URL"
```

### 3. Generate Dataset Statistics
```bash
# Summary statistics
uv run python stats.py

# Output:
# Total incidents: 6
# Categories: credential_stuffing (1), targeted_attacks (1), ...
# IP range: 1-3
# Date range: 2024-01-15 to 2024-06-15
```

### 4. Use in Tests
```python
from pathlib import Path
import json

def load_incident(incident_id: str):
    """Load incident data and metadata."""
    base_dir = Path(__file__).parent / "snowshoe_baseline"

    # Determine category from incident_id
    category = "_".join(incident_id.split("_")[:-2])

    data_file = base_dir / category / f"{incident_id}_data.json"
    metadata_file = base_dir / category / f"{incident_id}_metadata.json"

    with open(data_file) as f:
        data = json.load(f)
    with open(metadata_file) as f:
        metadata = json.load(f)

    return data, metadata

# Example usage
data, metadata = load_incident("credential_stuffing_001_20240115")
assert metadata["ground_truth_label"] == "snowshoe_spam"
assert len(data["sessions"]) == metadata["session_count"]
```

## Labeling Guidelines

### 1. Review Checklist
- [ ] Verify IP count and session count are accurate
- [ ] Confirm ground truth label matches attack pattern
- [ ] Check attack characteristics align with observed behavior
- [ ] Ensure date range covers all session timestamps
- [ ] Add detailed notes explaining classification rationale
- [ ] Set confidence level based on clarity of pattern
- [ ] Update enrichment coverage percentages

### 2. Confidence Levels
- **High**: Clear, unambiguous attack pattern with strong evidence
- **Medium**: Likely attack pattern but some ambiguity
- **Low**: Uncertain classification, requires additional review

### 3. Difficult Cases
- **Slow attacks**: May span days/weeks, check temporal clustering
- **Low IP counts**: Consider if it's targeted vs failed snowshoe
- **Mixed behavior**: Use `hybrid` label for combined patterns
- **Legitimate look-alikes**: Use `legitimate_traffic` + detailed notes

## Current Status (MVP v2.0 - COMPLETE)

### Incidents Created: 22 ✅

| Category | Count | IP Range | Session Range | Ground Truth Labels |
|----------|-------|----------|---------------|---------------------|
| credential_stuffing | 5 | 3-218 | 3-892 | snowshoe_spam |
| targeted_attacks | 5 | 8-23 | 34-156 | targeted_attack |
| hybrid_attacks | 5 | 3-92 | 3-521 | hybrid |
| legitimate_traffic | 5 | 1-4 | 1-7 | legitimate_traffic |
| edge_cases | 2 | 1-2 | 1-2 | snowshoe_spam, targeted_attack |

### Dataset Statistics

- **Total Incidents**: 22
- **Temporal Coverage**: 222 days (2024-01-15 to 2024-08-25)
- **IP Count Range**: 1 to 218 unique sources per incident
- **Session Count Range**: 1 to 892 sessions per incident
- **Enrichment Coverage**: DShield 75.1%, HIBP 70.2%, VirusTotal 22.1%
- **Confidence Levels**: High=17, Medium=5
- **Validation**: 22/22 metadata files valid ✅

### Baseline Metrics (Issue #54 - COMPLETE)

Using simple heuristic-based detector on MVP dataset:

**Performance Metrics**:
- **Precision**: 0.667 (4 TP / 6 detections)
- **Recall**: 0.667 (4 TP / 6 actual snowshoe attacks)
- **F1 Score**: 0.667
- **Accuracy**: 0.818 (18/22 correct classifications)

**Confusion Matrix** (Snowshoe Spam as Positive Class):
- True Positives: 4
- False Positives: 2 (hybrid attacks misclassified as snowshoe)
- False Negatives: 2 (low IP count snowshoe attacks missed)
- True Negatives: 14

**Common Failure Modes**:
1. **Hybrid Attack Confusion** (6 incidents): Difficulty distinguishing hybrid attacks from pure snowshoe or targeted attacks
2. **Low IP Count Snowshoe** (2 incidents): Missed snowshoe attacks with <10 IPs (edge cases)
3. **Edge Case Misclassification** (2 incidents): Single-IP attacks incorrectly classified

**Improvement Targets**:
- Target Precision: ≥0.90
- Target Recall: ≥0.85
- Target F1: ≥0.87

See `scripts/calculate_baseline_metrics.py` for full analysis.

### Phase 0 Completion ✅

- ✅ Issue #53: MVP dataset created (22 incidents)
- ✅ Issue #54: Baseline metrics established
- 🔄 Issue #55: Algorithm validation (in progress)

### Next Steps

1. **Phase 1 Expansion** (Issue #60): Scale to 100+ incidents
   - Better temporal diversity (full year coverage)
   - More edge cases (IPv6, multi-day, extreme IP counts)
   - Extracting real incidents from production database
   - Multiple reviewers for validation

2. **Algorithm Development**:
   - Implement longtail feature extraction
   - Develop hybrid attack detection logic
   - Add temporal and behavioral features
   - Improve edge case handling

3. **Quality Improvements**:
   - Inter-rater reliability testing (multiple reviewers)
   - Blind labeling for validation
   - External security researcher validation

## Related Issues

- **#53**: Create baseline test dataset (this dataset)
- **#54**: Establish baseline metrics using this dataset
- **#55**: Algorithm validation against ground truth labels
- **#60**: Expand to 100+ incidents (future work)

## Contributing

To add new incidents:

1. Extract data using `extract_incidents.py` or create manually
2. Follow naming convention: `{category}_{number}_{YYYYMMDD}`
3. Create both `*_data.json` and `*_metadata.json` files
4. Run `validate_metadata.py` to check schema compliance
5. Add detailed notes explaining classification rationale
6. Update this README with new incident counts

## License

This dataset is part of the CowrieProcessor project and follows the same license.

## Contact

For questions about dataset labeling or usage:
- GitHub Issues: https://github.com/datagen24/cowrieprocessor/issues
- Maintainer: Steve Peterson (steve@scpeterson.com)
