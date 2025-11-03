# Plan: Phase 1 - TTP-Based Actor Profiling & Feature Discovery

## Mission Clarification

**Critical Insight**: This is NOT "snowshoe spam vs legitimate traffic" classification.

**Actual Mission**:
- **Actor Clustering**: Group attack campaigns by unique TTP patterns
- **Behavioral Fingerprinting**: Identify threat actors by their operational patterns
- **Campaign Tracking**: Link IPs/passwords/ASNs/SSH keys to persistent threat actors
- **MITRE ATT&CK Mapping**: Translate command sequences to standardized TTPs

**Context**: All honeypot traffic is suspicious - we're profiling attackers, not detecting attacks.

---

## Hypothesis

**Research Question**: What features best discriminate between different threat actors operating against our honeypots?

**Hypothesis**: A data-driven feature selection process using production database analysis will identify 20-40 optimal features that capture:
1. **TTP Sequences**: Command patterns mapped to MITRE ATT&CK techniques
2. **Operational Fingerprints**: Timing, tooling, targeting patterns
3. **Infrastructure Reuse**: IP/ASN/SSH key clustering
4. **Credential Patterns**: Password lists, username strategies

**Why this approach**:
- Avoids arbitrary feature counts (e.g., "64 features")
- Grounded in actual attacker behavioral variance
- Uses statistical validation (mutual information, chi-square tests)
- Optimizes for recall (minimize false negatives - missing actors)
- Supports analyst-in-the-loop feedback for supervised refinement

---

## Expected Outcomes (Quantitative)

**Phase 1A: Feature Discovery** (15-20 hours)
- **Deliverable**: Data-driven optimal feature set (target: 20-40 features)
- **Method**: Statistical analysis on production database
- **Validation**: Features show high inter-campaign variance, low intra-campaign variance
- **Output**: Feature specification document with justification for each feature

**Phase 1B: TTP Profiling** (15-20 hours)
- **Deliverable**: MITRE ATT&CK mapping for command sequences
- **Method**: Pattern matching + domain expertise
- **Validation**: 80%+ command sequences mapped to MITRE techniques
- **Output**: TTP fingerprint database for known campaigns

**Phase 1C: Random Forest Baseline** (10-15 hours)
- **Deliverable**: Actor clustering model with campaign similarity scoring
- **Target Metrics**:
  - **Recall**: ≥0.85 (minimize missing threat actors)
  - **Precision**: ≥0.70 (acceptable false positive rate for analyst review)
  - **F1 Score**: ≥0.75 (balanced improvement over 0.667 baseline)
- **Validation**: Analyst feedback on top-N most similar campaigns

---

## Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|-----------|
| **Feature explosion** (100+ candidates) | Medium | Use mutual information ranking, iterative pruning |
| **MITRE mapping incompleteness** | Medium | Start with high-confidence mappings, expand iteratively |
| **Insufficient labeled data** (22 incidents) | High | Use semi-supervised learning, analyst labeling during Phase 1 |
| **Actor overlap** (single IP, multiple actors) | High | Use TTP sequences as primary discriminator, not just IPs |
| **Part-time development pace** | Low | Modular milestones, can pause/resume at checkpoints |

---

## Execution Phases

### Phase 1A: Data-Driven Feature Discovery (15-20 hours)

**Objective**: Identify optimal feature set through production database analysis.

#### Sub-Phase 1A.1: Data Distribution Analysis (4-6 hours)
**Research Questions**:
1. What varies between attack campaigns?
2. What's consistent within campaigns?
3. Which features have high discriminative power?

**SQL Queries to Run** (against production PostgreSQL):

```sql
-- 1. Command diversity analysis
SELECT
    DATE(start_time) as attack_date,
    COUNT(DISTINCT src_ip) as unique_ips,
    COUNT(DISTINCT commands) as unique_commands,
    COUNT(DISTINCT password_hash) as unique_passwords,
    COUNT(DISTINCT ssh_key_fingerprint) as unique_ssh_keys,
    AVG(session_duration_seconds) as avg_duration,
    COUNT(*) as session_count
FROM session_summaries
WHERE start_time >= '2024-01-01'
GROUP BY DATE(start_time)
ORDER BY unique_ips DESC
LIMIT 100;

-- 2. TTP sequence patterns (command N-grams)
SELECT
    commands[1:3] as first_three_commands,
    COUNT(DISTINCT src_ip) as campaign_size,
    COUNT(*) as session_count,
    AVG(session_duration_seconds) as avg_duration
FROM session_summaries
WHERE start_time >= '2024-01-01'
  AND array_length(commands, 1) >= 3
GROUP BY commands[1:3]
HAVING COUNT(DISTINCT src_ip) > 10
ORDER BY campaign_size DESC
LIMIT 50;

-- 3. Temporal patterns (attack velocity)
SELECT
    DATE(start_time) as attack_date,
    EXTRACT(HOUR FROM start_time) as hour_of_day,
    COUNT(DISTINCT src_ip) as unique_ips,
    COUNT(*) as session_count
FROM session_summaries
WHERE start_time >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY attack_date, hour_of_day
ORDER BY attack_date DESC, hour_of_day;

-- 4. Infrastructure reuse (ASN clustering)
SELECT
    dshield_data->>'asn' as asn,
    dshield_data->>'as_name' as as_name,
    COUNT(DISTINCT src_ip) as unique_ips,
    COUNT(DISTINCT password_hash) as password_variety,
    COUNT(*) as session_count
FROM session_summaries
WHERE start_time >= '2024-01-01'
  AND dshield_data IS NOT NULL
GROUP BY asn, as_name
HAVING COUNT(DISTINCT src_ip) > 5
ORDER BY unique_ips DESC
LIMIT 50;

-- 5. SSH key reuse patterns
SELECT
    ssh_key_fingerprint,
    COUNT(DISTINCT src_ip) as unique_ips,
    COUNT(DISTINCT DATE(start_time)) as days_active,
    MIN(start_time) as first_seen,
    MAX(start_time) as last_seen
FROM session_summaries
WHERE ssh_key_fingerprint IS NOT NULL
GROUP BY ssh_key_fingerprint
HAVING COUNT(DISTINCT src_ip) > 3
ORDER BY unique_ips DESC
LIMIT 50;

-- 6. Password list analysis (credential stuffing patterns)
SELECT
    password_hash,
    COUNT(DISTINCT src_ip) as used_by_ips,
    COUNT(DISTINCT username) as username_variety,
    COUNT(*) as attempt_count
FROM session_summaries
WHERE password_hash IS NOT NULL
GROUP BY password_hash
HAVING COUNT(DISTINCT src_ip) > 5
ORDER BY used_by_ips DESC
LIMIT 100;
```

**Analysis Workflow**:
1. Run queries on production database
2. Export results to CSV for analysis
3. Calculate statistical measures:
   - **Variance**: High variance between campaigns = good discriminator
   - **Mutual Information**: I(Feature, Campaign) for ranking
   - **Chi-Square**: Test for independence
4. Rank features by discriminative power
5. Document findings in `docs/phase1/feature_discovery_analysis.md`

#### Sub-Phase 1A.2: Feature Engineering (6-8 hours)

**Feature Categories** (prioritized by research findings):

**1. TTP Sequence Features** (10-15 features)
- Command N-grams (bigrams, trigrams)
- Command vocabulary size
- Command sequence entropy
- MITRE technique coverage (% of ATT&CK matrix touched)
- Technique transition patterns (T1078 → T1059 → T1105)

**2. Temporal Behavioral Features** (5-8 features)
- Attack velocity (sessions per hour)
- Session duration distribution (mean, std, percentiles)
- Time-of-day patterns (UTC hour distribution)
- Campaign duration (first_seen to last_seen)
- Inter-session timing (gaps between sessions)

**3. Infrastructure Fingerprint Features** (5-8 features)
- ASN diversity (unique ASNs used)
- Geographic spread (km, already have from Phase 0)
- Cloud/VPN/Tor provider mix (already have from Phase 0)
- IP rotation rate (new IPs per day)
- SSH key reuse patterns

**4. Credential Strategy Features** (5-8 features)
- Password list entropy
- Username enumeration pattern (single user vs spray)
- Credential pair uniqueness
- HIBP breach correlation (novel vs known passwords)
- Password mutation patterns (leet speak, number suffixes)

**5. Tool & Technique Features** (5-8 features)
- Exploitation tool signatures (metasploit, nmap, etc.)
- Post-exploitation commands (download URLs, persistence)
- Lateral movement attempts
- Data exfiltration patterns
- File operation diversity

**Feature Selection Process**:
```python
# Iterative feature selection
baseline_features = 13  # From Phase 0
candidate_features = 40-60  # From research

for feature in ranked_candidates:
    current_features.add(feature)

    # Train model on current_features
    model = RandomForest(current_features)
    recall, precision = cross_validate(model, labeled_data)

    # Keep if improvement > 2% recall
    if recall > previous_recall + 0.02:
        selected_features.add(feature)
        previous_recall = recall
    else:
        current_features.remove(feature)  # Prune

# Result: Data-driven optimal feature set
```

**Deliverable**: `cowrieprocessor/features/ttp_features.py`

#### Sub-Phase 1A.3: Feature Validation (4-6 hours)

**Validation Methods**:
1. **Inter-campaign variance**: High variance = good discriminator
2. **Intra-campaign consistency**: Low variance = stable fingerprint
3. **Correlation analysis**: Avoid redundancy (|r| < 0.95)
4. **Missing data handling**: Graceful degradation for incomplete enrichment

**Script**: `scripts/validate_feature_discriminability.py`

---

### Phase 1B: TTP Profiling & MITRE Mapping (15-20 hours)

**Objective**: Map command sequences to MITRE ATT&CK framework for behavioral fingerprinting.

#### Sub-Phase 1B.1: MITRE ATT&CK Integration (8-10 hours)

**Command → Technique Mapping**:

| Command Pattern | MITRE Technique | Confidence |
|----------------|-----------------|------------|
| `curl http://... \| bash` | T1105 (Ingress Tool Transfer) | High |
| `wget ... && chmod +x` | T1105 + T1059 (Command Execution) | High |
| `/etc/passwd`, `/etc/shadow` | T1003 (Credential Dumping) | Medium |
| `nmap`, `masscan` | T1046 (Network Service Discovery) | High |
| `crontab -e`, `systemd` | T1053 (Scheduled Task) | High |
| `ssh-keygen`, `.ssh/authorized_keys` | T1098 (Account Manipulation) | High |

**Implementation**:
```python
# cowrieprocessor/ttp/mitre_mapper.py

class MITREMapper:
    def __init__(self):
        self.technique_patterns = self.load_technique_database()

    def map_command_sequence(self, commands: List[str]) -> List[str]:
        """Map command sequence to MITRE technique IDs."""
        techniques = []
        for cmd in commands:
            normalized = defanging_normalizer.normalize(cmd)
            matched = self.pattern_match(normalized)
            techniques.extend(matched)
        return techniques

    def build_ttp_fingerprint(self, session: SessionSummary) -> Dict:
        """Create TTP fingerprint for session."""
        techniques = self.map_command_sequence(session.commands)
        return {
            "technique_ids": techniques,
            "technique_count": len(set(techniques)),
            "tactics": self.techniques_to_tactics(techniques),
            "kill_chain_stage": self.infer_kill_chain_stage(techniques),
            "sophistication_score": self.calculate_sophistication(techniques),
        }
```

**Technique Database Sources**:
1. MITRE ATT&CK Matrix (crawl https://attack.mitre.org)
2. Community mappings (CTID, Sigma rules)
3. Manual domain expertise
4. Analyst feedback loop

**Deliverable**: `cowrieprocessor/ttp/mitre_mapper.py` + technique database

#### Sub-Phase 1B.2: Campaign Fingerprinting (6-8 hours)

**TTP Fingerprint Schema**:
```json
{
    "campaign_id": "campaign_001_20240115",
    "ttp_fingerprint": {
        "mitre_techniques": ["T1105", "T1059", "T1053"],
        "technique_sequence": "T1078 → T1059 → T1105 → T1053",
        "tactics": ["initial-access", "execution", "persistence"],
        "kill_chain": "weaponization → delivery → exploitation",
        "tool_signatures": ["metasploit", "mimikatz"],
        "sophistication": 0.72
    },
    "behavioral_signature": {
        "command_ngrams": ["curl|bash", "wget&&chmod"],
        "temporal_pattern": "burst",
        "credential_strategy": "password_spray",
        "infrastructure": "cloud_vpn_mix"
    },
    "similarity_to_known": {
        "apt28": 0.34,
        "sandworm": 0.67,
        "lazarus": 0.12
    }
}
```

**Campaign Similarity Metric**:
```python
def calculate_campaign_similarity(campaign_a, campaign_b):
    """Calculate TTP-based similarity between campaigns."""

    # Jaccard similarity on MITRE techniques
    technique_similarity = jaccard(
        set(campaign_a.techniques),
        set(campaign_b.techniques)
    )

    # Sequence similarity (edit distance)
    sequence_similarity = 1 - (levenshtein_distance(
        campaign_a.technique_sequence,
        campaign_b.technique_sequence
    ) / max(len(campaign_a.technique_sequence), len(campaign_b.technique_sequence)))

    # Infrastructure overlap
    infra_similarity = cosine_similarity(
        campaign_a.infrastructure_vector,
        campaign_b.infrastructure_vector
    )

    # Weighted average (prioritize TTPs > infrastructure)
    return 0.5 * technique_similarity + 0.3 * sequence_similarity + 0.2 * infra_similarity
```

**Deliverable**: Campaign fingerprint database + similarity calculator

#### Sub-Phase 1B.3: Known Actor Database (2-4 hours)

**Seed Database**: Known APT groups with documented TTPs
- APT28 (Fancy Bear): Command patterns, infrastructure
- Sandworm: Destructive payloads, OT targeting
- Lazarus: Cryptocurrency targeting, specific tools
- Volt Typhoon: Living-off-the-land, minimal malware

**Sources**:
- MITRE ATT&CK Groups (https://attack.mitre.org/groups/)
- Threat intelligence reports (open-source)
- Historical honeypot campaigns (from your data)

**Deliverable**: `data/known_actors/` directory with fingerprints

---

### Phase 1C: Random Forest Clustering Model (10-15 hours)

**Objective**: Train actor clustering model with analyst-in-the-loop feedback.

#### Sub-Phase 1C.1: Model Training (6-8 hours)

**Approach**: Semi-supervised Random Forest for campaign clustering

**Training Data**:
- **Labeled**: 22 incidents from Phase 0 (ground truth)
- **Unlabeled**: Historical campaigns from production database
- **Expansion**: Analyst labels 20-30 more campaigns during Phase 1

**Model Architecture**:
```python
from sklearn.ensemble import RandomForestClassifier
from sklearn.cluster import AgglomerativeClustering

# Phase 1: Unsupervised clustering to find natural groupings
clustering = AgglomerativeClustering(
    n_clusters=None,
    distance_threshold=0.3,  # Similarity threshold
    metric='cosine',
    linkage='average'
)
cluster_labels = clustering.fit_predict(feature_vectors)

# Phase 2: Supervised Random Forest on labeled + cluster-labeled data
rf = RandomForestClassifier(
    n_estimators=100,
    max_depth=None,
    min_samples_split=5,
    class_weight='balanced',  # Handle imbalanced classes
    random_state=42
)
rf.fit(X_train, y_train)

# Phase 3: Campaign similarity scoring
def predict_campaign_similarity(new_session):
    features = extract_features(new_session)
    cluster_probs = rf.predict_proba(features)
    similar_campaigns = find_top_k_similar(cluster_probs, k=5)
    return similar_campaigns
```

**Hyperparameter Tuning**:
- Grid search with 5-fold cross-validation
- Optimize for recall (minimize false negatives)
- Precision threshold for analyst review

**Deliverable**: `cowrieprocessor/ml/actor_clustering.py`

#### Sub-Phase 1C.2: Analyst Feedback Loop (2-3 hours)

**Interactive Labeling Interface**:
```python
# scripts/analyst_review_tool.py

def review_campaign(campaign_id):
    """Present campaign for analyst review."""

    # Show TTP fingerprint
    print(f"Campaign: {campaign_id}")
    print(f"MITRE Techniques: {campaign.techniques}")
    print(f"Top 10 Commands: {campaign.top_commands}")
    print(f"Similar to: {campaign.similar_campaigns}")

    # Analyst feedback
    label = input("Label (apt28, sandworm, unknown, legitimate): ")
    confidence = input("Confidence (high, medium, low): ")
    notes = input("Notes: ")

    # Save feedback
    save_analyst_label(campaign_id, label, confidence, notes)

    # Retrain model with new label
    if len(new_labels) >= 10:
        retrain_model()
```

**Feedback Metrics**:
- Inter-analyst agreement (if multiple analysts)
- Labeling confidence distribution
- Time per campaign review (optimize UX)

**Deliverable**: Analyst review tool + feedback database

#### Sub-Phase 1C.3: Model Validation (2-4 hours)

**Validation Approach**:
- **Hold-out test set**: 20% of labeled data
- **Temporal validation**: Train on 2024-01 to 2024-06, test on 2024-07+
- **Analyst validation**: Top-N predictions reviewed by analyst

**Target Metrics** (adjusted for actor clustering):
- **Recall**: ≥0.85 (don't miss threat actors)
- **Precision**: ≥0.70 (acceptable false positive rate for review)
- **F1 Score**: ≥0.75 (30% improvement over 0.667 baseline)
- **Top-5 Accuracy**: ≥0.90 (correct actor in top 5 similar campaigns)

**Failure Mode Analysis**:
- Campaigns where model fails (low confidence predictions)
- Feature importance analysis (which features matter most)
- Confusion matrix by actor type

**Deliverable**: Model validation report + feature importance rankings

---

## Quality Gates

**Gate 1: Feature Discovery Complete**
- [ ] Statistical analysis run on production database
- [ ] 20-40 features identified with high discriminative power
- [ ] Features show inter-campaign variance > intra-campaign variance
- [ ] Correlation analysis confirms no redundancy (|r| < 0.95)
- [ ] Feature extraction code implemented with tests

**Gate 2: TTP Profiling Complete**
- [ ] MITRE ATT&CK mapper implemented
- [ ] 80%+ command sequences mapped to techniques
- [ ] Campaign fingerprint schema validated
- [ ] Known actor database seeded with 5+ APT groups
- [ ] Similarity metric validated on known similar campaigns

**Gate 3: Model Training Complete**
- [ ] Random Forest model trained on optimal features
- [ ] Recall ≥0.85 on hold-out test set
- [ ] Feature importance documented
- [ ] Analyst review tool functional
- [ ] 20-30 additional campaigns labeled

---

## Agent Coordination

### Sequential Execution (Part-Time Friendly)

**Phase 1A (Weekends 1-2)**:
- **deep-research-agent**: SQL query design + statistical analysis
- **backend-architect**: Feature extraction implementation
- **quality-engineer**: Feature validation + correlation analysis

**Phase 1B (Weekends 3-4)**:
- **backend-architect**: MITRE mapper implementation
- **deep-research-agent**: Known actor research + fingerprinting
- **python-expert**: Campaign similarity algorithms

**Phase 1C (Weekends 5-6)**:
- **python-expert**: Random Forest implementation
- **quality-engineer**: Model validation + metrics
- **technical-writer**: Analyst review tool UX

---

## Success Criteria

**Technical Success**:
- [ ] 20-40 optimal features identified through data analysis
- [ ] MITRE ATT&CK mapping for 80%+ command sequences
- [ ] Random Forest model with Recall ≥0.85, Precision ≥0.70
- [ ] Analyst review tool functional with feedback loop
- [ ] Campaign similarity scoring operational

**Research Success**:
- [ ] Data-driven feature selection process documented
- [ ] Feature discriminability validated statistically
- [ ] TTP fingerprinting methodology established
- [ ] Actor clustering approach validated with analyst feedback

**Operational Success**:
- [ ] Model runs on daily batch processing
- [ ] Historical data reprocessing supported
- [ ] Analyst workflow integrated with feedback loop
- [ ] Clear path to Deep Learning in Phase 2

---

## Next Actions

### Immediate (This Weekend)
1. **Database Access**: Connect to production PostgreSQL
2. **Run SQL Queries**: Execute data distribution analysis queries
3. **Export Results**: Save to CSV for analysis
4. **Initial Feature Ranking**: Calculate mutual information scores

### Weekend 2-3
1. **Feature Engineering**: Implement top 20-30 features
2. **Feature Validation**: Test on Phase 0 dataset
3. **MITRE Mapper**: Begin command → technique mapping

### Weekend 4-6
1. **Model Training**: Random Forest on optimal features
2. **Analyst Tool**: Build review interface
3. **Validation**: Test on hold-out data + analyst feedback

---

## Timeline Estimate

**Total**: 40-55 hours (6-8 weekends at 8 hours/weekend)

| Phase | Hours | Weekends |
|-------|-------|----------|
| 1A: Feature Discovery | 15-20 | 2-3 |
| 1B: TTP Profiling | 15-20 | 2-3 |
| 1C: Model Training | 10-15 | 1-2 |

**Flexible Checkpoints**: Can pause/resume at any phase boundary.

---

## Phase 2 Preview (Deep Learning)

Once Phase 1 establishes baseline:
- LSTM for command sequence modeling
- Transformer-based actor profiling
- Graph Neural Networks for infrastructure clustering
- Continuous learning with analyst feedback
- Active learning for efficient labeling

**But first**: Let's validate the research-driven approach with Random Forest!
