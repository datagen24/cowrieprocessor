# Phase 1: TTP Profiling Mission Context

## CRITICAL MISSION REFRAMING (2025-11-01)

### ❌ WRONG: Binary Classification
Original assumption: "Detect snowshoe spam vs legitimate traffic"

### ✅ CORRECT: Actor Profiling & TTP Clustering
**Actual Mission**: "Identify threat actors by unique sequences of TTPs and group campaigns by behavioral fingerprints"

**Key Insight**: ALL honeypot traffic is suspicious. We're profiling attackers, not detecting attacks.

## Mission Objectives

### Primary Goal
Identify and track threat actors across campaigns using behavioral fingerprints:
- SSH key fingerprints (GOLD MINE - strongest signal)
- Command sequence patterns (TTP sequences)
- Infrastructure reuse (ASN, IP rotation patterns)
- Credential strategies (password lists, username enumeration)
- Temporal patterns (attack velocity, timing)

### Secondary Goal
Group campaigns by similarity to cluster threat actors:
- Link IPs/passwords/ASNs/SSH keys to persistent actors
- Map command sequences to MITRE ATT&CK techniques
- Track actors over time using TTP evolution

### Success Metrics (Phase 1)
- **Recall ≥0.85**: Minimize missing threat actors (false negatives BAD)
- **Precision ≥0.70**: Acceptable false positive rate for analyst review
- **F1 Score ≥0.75**: 30% improvement over Phase 0 baseline (0.667)

**Priority**: Recall > Precision (false negatives worse than false positives)

## User Context & Priorities

### User Background
- Works on project weekends/evenings (part-time)
- Has tracked massive SSH persistent campaign with writeups
- Primary interests: Persistence, Credential Injection, Reconnaissance

### Dataset Context
- 1 year of Cowrie SSH/telnet data (2024-11-01 to 2025-11-01)
- Mostly complete with some gaps
- Sporadic data from other sensors
- Web honeypot logs available but unused by tool

### Labeling Strategy
User prefers Option A: Label during Phase 1 as patterns emerge
- Semi-supervised learning approach
- Analyst-in-the-loop feedback model
- Can label as many incidents as needed

### Deployment Context
- Daily batch processing (not real-time)
- Need to update historical data periodically
- Future: Deep Learning with feedback model

## Phase 1 Architecture

### Phase 1A: Feature Discovery (15-20h, 2-3 weekends)
**Status**: SQL queries created, awaiting execution

**Deliverables**:
1. ✅ SQL queries for production database (corrected for schema)
2. ✅ Python analysis script (feature importance ranking)
3. ⏳ Execute queries on production DB
4. ⏳ Generate feature discovery report
5. ⏳ Identify 20-40 optimal features (data-driven, not arbitrary)

**Key Queries**:
- Query 2: SSH Key Reuse (GOLD MINE for actor tracking)
- Query 7-9: MITRE techniques (Persistence, Credential Access, Recon)
- Query 10: Campaign correlation matrix

### Phase 1B: TTP Profiling & MITRE Mapping (15-20h, 2-3 weekends)
**Status**: Pending Phase 1A completion

**Deliverables**:
1. MITRE ATT&CK mapper implementation
2. Command sequence → technique mapping
3. Known actor template from SSH persistent campaign
4. Technique sequence fingerprints
5. Focus: T1098, T1053 (Persistence), T1003, T1078 (Credential), T1046, T1018 (Recon)

### Phase 1C: Random Forest Clustering (10-15h, 1-2 weekends)
**Status**: Pending Phase 1B completion

**Deliverables**:
1. Feature engineering with top 20-40 features
2. Semi-supervised Random Forest training
3. Campaign similarity scoring
4. Analyst review tool for interactive labeling
5. Target: Recall ≥0.85, Precision ≥0.70, F1 ≥0.75

## Feature Categories (Data-Driven)

### 1. TTP Sequences (10-15 features)
- Command N-grams (bigrams, trigrams)
- MITRE technique patterns
- Tool signatures (nmap, masscan, wget patterns)
- Post-exploitation sequences

### 2. Temporal Behavioral (5-8 features)
- Attack velocity (commands per minute)
- Session timing patterns (hour of day, day of week)
- Campaign duration
- Time between attempts

### 3. Infrastructure Fingerprints (5-8 features)
- ASN diversity
- SSH key reuse (CRITICAL)
- IP rotation patterns
- Cloud/VPN/Tor usage
- Geographic spread

### 4. Credential Strategies (5-8 features)
- Password entropy
- Username enumeration patterns
- HIBP breach correlation
- Password list signatures

### 5. MITRE Techniques (5-8 features)
- Persistence indicators (cron, systemd, authorized_keys)
- Credential access (passwd files, /etc/shadow)
- Reconnaissance (system enumeration, network scanning)

**Target**: 20-40 total features (determined by statistical analysis)

## Known Attack Campaigns

### SSH Persistent Campaign
User has comprehensive writeups on massive campaign:
- Will be analyzed in Phase 1A.2
- Extract TTP patterns as known actor template
- Seed database with known threat actor
- Use as training data for Random Forest

## MITRE ATT&CK Focus Areas

### Persistence (T1xxx)
- T1098: Account Manipulation (authorized_keys)
- T1053: Scheduled Task/Job (cron, systemd)
- T1136: Create Account (useradd, adduser)
- T1546: Event Triggered Execution (.bashrc, .profile)

### Credential Access (T1xxx)
- T1003: OS Credential Dumping (/etc/passwd, /etc/shadow)
- T1078: Valid Accounts (successful logins)
- T1110: Brute Force (password attempts)
- T1552: Unsecured Credentials (config files)

### Reconnaissance (T1xxx)
- T1046: Network Service Scanning (nmap, masscan)
- T1018: Remote System Discovery (ping sweeps)
- T1082: System Information Discovery (uname, cat /proc/*)
- T1083: File and Directory Discovery (ls, find)

## Baseline Performance (Phase 0)

**Current Detector** (heuristic-based):
- Precision: 0.667
- Recall: 0.667
- F1 Score: 0.667
- Accuracy: 81.8% (18/22 correct)

**Failure Modes**:
1. Hybrid attack confusion (27% of errors)
2. Low IP count snowshoe missed (9% of errors)
3. Edge case misclassification (9% of errors)

**Improvement Targets**:
- Precision: ≥0.90 (35% improvement)
- Recall: ≥0.85 (27% improvement)
- F1 Score: ≥0.87 (30% improvement)

## Phase 1 Timeline

| Phase | Duration | Weekends | Status |
|-------|----------|----------|--------|
| 1A.1 | 3h | 0.5 | ⏳ Queries ready, awaiting execution |
| 1A.2 | 12-17h | 1.5-2 | ⏸️ Pending: Analyze SSH campaign |
| 1B | 15-20h | 2-3 | ⏸️ Pending: MITRE mapper |
| 1C | 10-15h | 1-2 | ⏸️ Pending: Random Forest training |
| **Total** | **40-55h** | **5-8 weekends** | **In Progress** |

## Critical Success Factors

### 1. SSH Key Fingerprints (GOLD MINE)
SSH keys are expensive to generate and difficult to change. Attackers reuse them across campaigns.
**Query 2** in Phase 1A extracts this critical actor identifier.

### 2. Data-Driven Feature Selection
No more "thumb in the wind" feature counts. Statistical analysis (variance, MI, chi-square) identifies optimal features objectively.

### 3. Analyst-in-the-Loop
Semi-supervised learning with feedback allows incremental labeling as patterns emerge. User doesn't need to label everything upfront.

### 4. MITRE Standardization
Using MITRE ATT&CK framework provides:
- Standardized TTP vocabulary
- Cross-campaign comparability
- Industry-standard threat intelligence

### 5. Recall Optimization
False negatives (missing threat actors) are worse than false positives (over-detecting). Optimize for recall in model training.

## Current Work Context (2025-11-01)

### Just Completed
- ✅ Milestone 1 (Phase 0): 100% complete (10/10 P0+P1 issues closed)
- ✅ Phase 1A.1 SQL queries (corrected for actual schema)
- ✅ Python feature importance analyzer
- ✅ Database schema memories created

### Next Actions
1. **User**: Execute SQL queries on production database (30 min)
2. **User**: Run Python analysis script (5 min)
3. **User**: Review feature discovery report (15 min)
4. **Assistant**: Analyze SSH persistent campaign writeups (Phase 1A.2)
5. **Assistant**: Design MITRE ATT&CK mapper (Phase 1B)

### Blockers
- None (user has database access, scripts are ready)

---

**Memory Created**: 2025-11-01
**Purpose**: Preserve mission context and prevent misunderstanding in future sessions
**Critical for**: Phase 1B design, feature engineering, model training
**Key Insight**: This is actor profiling, not binary classification!
