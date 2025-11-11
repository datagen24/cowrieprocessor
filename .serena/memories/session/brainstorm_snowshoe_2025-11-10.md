# Snowshoe Analysis Brainstorming Session - 2025-11-10

## Context
**Milestone 1 Status**: Phase 0 complete (10/10 P0+P1), 3 issues remain open for next phase
**Feature Discovery**: Only 2 high-discrimination features identified from 7 candidates
**Critical Gap**: Need to expand feature set and redo discovery queries for better coverage

## Open Milestone 1 Issues

### #49 - Database-Backed Command Defanger (P1, OPEN)
**Scope**: Major architectural enhancement with 6-phase implementation
**Key Features**:
- Database-backed risk profiles (replace static Python sets)
- Context-aware command analysis (operators, targets, chains)
- Threat intelligence tracking (SSH keys, credentials, actor profiles)
- LLM-safe abstraction layer
**Estimated Effort**: 4-5 weeks
**Dependencies**: Database abstraction layer, existing defanging module

### #60 - Complete Test Dataset (P2, OPEN)
**Scope**: Expand from 22 to 100+ labeled incidents
**Distribution Target**:
- 30+ credential stuffing attacks
- 30+ targeted attacks
- 20+ hybrid attacks
- 20+ legitimate traffic
- 20+ edge cases
**Status**: Deferred to Phase 6 (validation phase)

### #61 - Complete Baseline Metrics (P2, OPEN)
**Scope**: Full dataset baseline execution for Phase 6 validation
**Dependencies**: Issue #60 (Complete Dataset)
**Status**: Deferred to Phase 6

## Feature Discovery Analysis Findings

### Current State (Poor Performance)
- **Total Features Analyzed**: 7
- **High-Discrimination Features**: 2 (28.6% success rate)
- **Average Discrimination Score**: 0.380 (low)
- **Recommended Feature Count**: 2 (insufficient for robust ML)

### Top 2 Features Identified
1. **cmd_div_session_count**: Discrimination Score 1.000
   - Perfect variance, mutual information, chi-square
   - 317 samples, strong signal
2. **cmd_div_avg_duration_seconds**: Discrimination Score 0.859
   - Good variance (0.530), perfect MI and chi-square
   - 317 samples, reliable

### Failed Feature Categories
1. **Infrastructure Fingerprints**: Avg 0.145 (poor)
   - ssh_unique_ips: 0.289 (only 2 unique values)
   - infra_asn: 0.000 (NO DATA - snapshot bug!)
2. **Temporal Behavioral**: Avg 0.107 (very poor)
   - temporal_day_of_week: 0.127 (7 values)
   - temporal_hour_of_day: 0.087 (24 values)

## Root Cause: ADR-007 Snapshot Bug Impact

**Problem**: Session snapshots never populated despite 100% IP inventory enrichment
- **Impact**: Cannot access geo/ASN features without expensive JOINs
- **Affected Queries**: Infrastructure fingerprints (ASN, country)
- **Data Loss**: 1.68M sessions missing snapshot_asn, snapshot_country, snapshot_ip_type
- **Consequence**: Only 2/7 features viable, infrastructure features unusable

## Brainstorming: Snowshoe Analysis Improvements

### Priority 1: Fix Snapshot Population
**Why Critical**: Infrastructure features (ASN, country, IP type) are gold for snowshoe detection
**Action Required**:
1. Fix bulk.py:_upsert_session_summaries() to populate snapshot columns
2. Backfill 1.68M sessions from ip_inventory
3. Re-run infrastructure fingerprint queries
4. Expect 4-5 new high-discrimination features

### Priority 2: Expand Feature Discovery Queries
**Current Coverage**: 10 SQL queries → 7 features (70% extraction rate)
**Improvement Ideas**:

#### Geographic Clustering Features
- Country diversity score (Shannon entropy)
- ASN concentration ratio (top 3 ASNs / total)
- Geographic spread (continent count)
- Provider type clustering (residential/datacenter/mobile ratio)

#### Command Pattern Features
- Command vocabulary size (unique commands per IP)
- Command sequence similarity (edit distance clustering)
- Defanged command risk score distribution
- SSH key injection attempts per IP

#### Temporal Features
- Time zone consistency (sessions clustered in single TZ vs distributed)
- Attack wave detection (burst periods vs sustained)
- Inter-session timing (gaps between connections from same IP)
- Session duration coefficient of variation

#### Behavioral Fingerprints
- Login attempt ratio (attempts per session)
- Command execution ratio (commands per successful login)
- File download patterns (wget/curl usage)
- Credential reuse patterns (same username/password across IPs)

### Priority 3: Machine Learning Approach Enhancement

**Current Baseline**: 66.7% F1 Score (Phase 0)
**Target**: 75%+ F1 Score (30% improvement)

**Proposed Approach**:
1. **Feature Engineering**: Extract 15-20 high-discrimination features
2. **Dimensionality Reduction**: PCA/t-SNE for visualization, feature selection
3. **Ensemble Methods**: Random Forest + Gradient Boosting
4. **Class Balancing**: SMOTE for rare attack types
5. **Hyperparameter Tuning**: GridSearchCV for optimal model

### Priority 4: Threat Intelligence Integration

**Leverage Issue #49 Work**:
- Track SSH key reuse across campaigns (observed_ssh_keys)
- Track credential patterns (observed_credentials)
- Build threat actor profiles (behavioral fingerprints)
- Correlate IP infrastructure with known campaigns

**Benefit**: Historical context for snowshoe detection (returning actors)

## Next Actions Plan

### Short-term (Week 1)
1. ✅ Analyze Milestone 1 issues (DONE)
2. ✅ Review feature discovery gaps (DONE)
3. ⏳ Design expanded SQL query suite (20-25 queries targeting 15-20 features)
4. ⏳ Prioritize snapshot bug fix (blocking infrastructure features)

### Medium-term (Week 2-3)
1. Fix ADR-007 snapshot population
2. Backfill production data (1.68M sessions)
3. Execute expanded feature discovery queries
4. Analyze new feature discrimination scores
5. Create Phase 1B ML training plan

### Long-term (Month 2)
1. Implement Phase 1B Random Forest detector
2. Validate on 100+ incident dataset (#60)
3. Measure baseline improvement (#61)
4. Integrate threat intelligence (#49 Phase 3)

## Open Questions for Discussion

1. **Feature Discovery Scope**: Target 15 features? 20? 25? (Trade-off: coverage vs overfitting)
2. **Query Execution**: Re-run on production server or wait for snapshot fix? (Risk: wasted effort if queries need JOINs)
3. **ML Approach**: Random Forest only or ensemble (RF + XGBoost)? (Complexity vs performance)
4. **Dataset Expansion**: Start #60 now or wait for Phase 1B validation? (Parallel work vs sequential)
5. **Issue #49 Timing**: Integrate defanger refactor into Phase 1 or defer to Phase 2? (Scope creep risk)

## Recommended Decision

**Proposal**: Sequential approach with clear gates
1. **Gate 1**: Fix snapshot bug → Validate infrastructure features work
2. **Gate 2**: Expand queries (15 features) → Re-run feature discovery
3. **Gate 3**: Select top 10-12 features → Implement Phase 1B ML detector
4. **Gate 4**: Validate on MVP dataset (22 incidents) → If >75% F1, proceed
5. **Gate 5**: Expand to 100+ dataset (#60) → Final validation (#61)

**Rationale**:
- Minimize rework (snapshot fix first)
- Validate incrementally (gates prevent over-investment)
- Defer Issue #49 to Phase 2 (avoid scope creep)
- Focus Phase 1B on core ML detector (proven approach)

## Session End State
- Milestone 1 issues analyzed: 3 open (1 P1, 2 P2)
- Feature discovery gaps identified: Infrastructure features blocked by snapshot bug
- Brainstorming complete: 4 priority improvements, 5 open questions
- Next action: Design expanded SQL query suite (15-20 features)
