# Milestone 1: Feature Analysis - Executive Summary

**Date**: 2025-11-02
**Full Report**: `MILESTONE1_FEATURE_ANALYSIS_REPORT.md`

---

## Key Findings (1-Minute Read)

### ✅ Strong Behavioral Data Available

**Dataset**: 1.63M sessions (Nov 2024 - Oct 2025)

**Top Attack Patterns Identified**:
1. **SSH Key Injection Campaign**: 161K attempts (33% of all activity)
   - Automated backdoor installation via SSH authorized_keys
   - Single SSH public key reused across all attempts
   - **Actor Type**: Mass compromise botnet

2. **Cryptominer Reconnaissance**: 54K attempts (11% of activity)
   - System resource checks (CPU count, memory capacity)
   - Automated scripted recon
   - **Actor Type**: Mining malware deployment

3. **Credential Stuffing**: 1.5M login attempts
   - 90.7% use breached passwords (HIBP-confirmed)
   - Top password reused 11,610 times
   - **Actor Type**: Leak compilation abuse

**Behavioral Features Ready for Phase 1A**:
- ✅ Command patterns (500 unique commands, TTP classification)
- ✅ Temporal patterns (hour-of-day, commands/minute velocity)
- ✅ Credential patterns (password reuse, breach correlation)
- ✅ Activity volume (session counts, file downloads)

---

### ❌ Critical Enrichment Data Gap

**Problem**: 100% of enrichment fields are NULL (30K+ sessions)

**Root Cause**: `cowrie-enrich refresh` has never been run

**Missing Features**:
- Geographic attribution (country, ASN, AS name)
- Infrastructure classification (cloud, VPN, Tor)
- Reputation scores (DShield, URLHaus)

**Impact**:
- ❌ Cannot distinguish nation-state vs cybercrime
- ❌ Cannot calculate geographic spread features
- ❌ Cannot detect infrastructure abuse patterns
- ❌ Limited actor profiling (behavioral only)

**Recovery Timeline**: 1-2 weeks (API rate limits)

---

## Recommended Actions

### Immediate (This Week)

1. **Proceed with Phase 1A** using behavioral features only
   - Focus: SSH campaign behavioral clustering
   - Use: Tier 1 features (command patterns, temporal, credentials)
   - Accept: Limited actor attribution without infrastructure data

2. **Start Enrichment Backfill**
   ```bash
   uv run cowrie-enrich refresh \
       --sessions 0 --files 0 \
       --progress
   ```
   - Expected: 1-2 weeks completion
   - Monitor: Query enrichment coverage daily

3. **Investigate Data Quality Issues**
   - Risk scores always 100 (calculation bug?)
   - Commands/session discrepancy (0.97 vs 18.6)
   - VT/DShield flags always false (enrichment never ran)

### Short-Term (Weeks 3-4)

4. **Re-run Feature Analysis** with enrichment data
   - Execute: All Phase 1 SQL queries again
   - Add: Tier 3 infrastructure features
   - Update: Snowshoe detection baseline

5. **Combined Actor Profiling**
   - Behavioral + infrastructure feature engineering
   - Nation-state vs cybercrime classification
   - Malware campaign attribution

---

## Feature Prioritization for Phase 1A

### Tier 1: Use Now (Behavioral Features)

| Feature | Discriminative Power | Use Case |
|---------|---------------------|----------|
| `lateral_movement_cmd_ratio` | CRITICAL | Botnet detection |
| `commands_per_minute` | CRITICAL | Automated vs human |
| `password_reuse_count` | CRITICAL | Credential stuffing |
| `command_diversity_entropy` | HIGH | Campaign sophistication |
| `session_duration` | HIGH | Scanner vs compromiser |

### Tier 3: Deferred (Enrichment Required)

| Feature | Discriminative Power | Availability |
|---------|---------------------|--------------|
| `geographic_spread_km` | CRITICAL | Post-backfill |
| `cloud_provider_ratio` | CRITICAL | Post-backfill |
| `asn_diversity_score` | HIGH | Post-backfill |
| `vpn_tor_ratio` | HIGH | Post-backfill |

---

## What We Can Detect Now vs Later

### ✅ Available Now (Behavioral Only)

**Automated vs Human Attacks**:
- Commands/minute >100 = automated
- Session duration <30s = scanning
- Identical command sequences = scripted

**Campaign Types**:
- SSH key injection = lateral movement
- System recon = cryptominer deployment
- Credential stuffing = leak usage

**Sophistication**:
- Command diversity = manual vs automated
- Anti-detection techniques (checking crontab first)
- Payload delivery patterns (11.9% file download rate)

### ❌ Blocked Until Enrichment (Infrastructure Required)

**Nation-State vs Cybercrime**:
- Geographic clustering patterns
- Infrastructure investment (dedicated vs botnet)
- Operational security (VPN/Tor usage)

**Botnet Characteristics**:
- IP count per campaign
- ASN diversity (single vs distributed C2)
- Residential vs datacenter composition

**Targeted vs Opportunistic**:
- Geographic focus (specific country targeting)
- Infrastructure selection (specific cloud providers)
- Reputation-aware targeting

---

## Success Metrics

### Phase 1A (Behavioral Features)

**Goal**: SSH campaign behavioral clustering

**Success Criteria**:
- ✅ Cluster sessions by command patterns
- ✅ Identify automated vs manual campaigns
- ✅ Detect credential stuffing patterns
- ⚠️ Limited actor attribution (behavioral only)

**Expected Deliverables**:
- Campaign taxonomy (behavioral TTPs)
- Baseline detection model (behavioral features)
- Known limitations documented (no infrastructure data)

### Post-Enrichment (Weeks 3-6)

**Goal**: Combined behavioral + infrastructure actor profiling

**Success Criteria**:
- ✅ Nation-state vs cybercrime classification
- ✅ Geographic threat intelligence
- ✅ Infrastructure abuse detection
- ✅ Malware campaign attribution

**Expected Deliverables**:
- Enhanced campaign taxonomy (TTPs + infrastructure)
- Improved detection model (full feature set)
- Actor profiling playbook

---

## Timeline

| Week | Phase | Activities | Deliverables |
|------|-------|------------|--------------|
| 1 (Current) | Behavioral Analysis | Feature analysis report, start backfill | This report |
| 2-3 | Enrichment Backfill | Monitor progress, Phase 1A work | SSH campaign clusters |
| 4 | Infrastructure Analysis | Re-run queries, Tier 3 features | Updated feature report |
| 5-6 | Combined Profiling | Behavioral + infrastructure | Actor profiling model |
| 7-8 | Baseline Model | Full feature set training | Detection baseline |

---

## Questions & Answers

**Q: Can we do Phase 1A without enrichment data?**
A: Yes, but with limited actor attribution. Focus on behavioral TTP clustering.

**Q: How long until enrichment backfill completes?**
A: 1-2 weeks (VirusTotal: 4 req/min, DShield: 30 req/min)

**Q: What's the impact of 0% enrichment coverage?**
A: Cannot distinguish nation-state vs cybercrime, cannot calculate geographic features, limited actor profiling.

**Q: Should we delay Phase 1A until enrichment completes?**
A: No. Proceed with behavioral features, re-analyze with infrastructure data when ready.

**Q: What features are highest priority for Phase 1A?**
A: Tier 1 behavioral features: command patterns, temporal velocity, credential reuse.

---

## Related Documents

- **Full Report**: `MILESTONE1_FEATURE_ANALYSIS_REPORT.md` (88 pages, comprehensive)
- **Enrichment Investigation**: `ENRICHMENT_CRITICAL_FINDING.md`
- **Sanitization Complete**: `sanitization_complete_report.md`
- **Feature Validation**: `feature_validation_results.md`
- **SQL Queries**: `scripts/phase1/sql_analysis_queries_v2.sql`

---

**Status**: ✅ Behavioral Analysis Complete | ⏳ Enrichment Backfill Required
**Recommendation**: Proceed with Phase 1A using Tier 1 behavioral features
**Next Milestone**: SSH Campaign Behavioral Clustering (Weeks 1-2)
