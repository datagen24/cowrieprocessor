# Milestone 1: Feature Analysis Report (Behavioral Features)

**Date**: 2025-11-02
**Status**: Phase 0 - Behavioral Analysis Complete
**Enrichment Status**: ⚠️ **BLOCKED** - 100% NULL enrichment data (backfill required)

---

## Executive Summary

This report analyzes **behavioral features** extracted from 1.63M honeypot sessions spanning November 2024 - October 2025. Due to enrichment backfill issues (100% NULL enrichment data), **infrastructure-based features are not available**. This analysis focuses exclusively on TTP (Tactics, Techniques, Procedures) profiling using command patterns, temporal behaviors, and credential patterns.

### Key Findings

✅ **Strong Behavioral Data Available**:
- 500 unique commands tracked (1.49M occurrences)
- 20,754 unique password hashes (90.7% breached)
- Rich temporal patterns (hour-of-day, day-of-week)
- SSH key reuse networks identified

❌ **Critical Data Gap - Enrichment Features**:
- 0% geographic attribution (country, ASN)
- 0% infrastructure classification (cloud, VPN, Tor)
- 0% reputation scores (DShield, URLHaus)
- **Impact**: Cannot distinguish nation-state vs cybercrime campaigns

### Recommended Actions

1. **Immediate**: Continue Phase 1A SSH campaign analysis with behavioral features only
2. **Short-term** (1-2 weeks): Run enrichment backfill (`cowrie-enrich refresh`)
3. **Medium-term**: Re-run feature analysis with infrastructure data
4. **Long-term**: Combine behavioral + infrastructure for actor profiling

---

## Part 1: Behavioral Feature Analysis

### 1.1 Command Pattern Features

**Data Source**: `results/03_command_patterns.csv` (500 unique commands)

#### Summary Statistics
- **Total unique commands**: 500
- **Total occurrences**: 1,490,014
- **Average per command**: 2,980 occurrences
- **Concentration**: Top 10 commands = 52% of all activity

#### Command Category Distribution

| Category | Unique Commands | Total Occurrences | % of Total |
|----------|----------------|-------------------|------------|
| `other` | 243 | 696,018 | 46.7% |
| `lateral_movement` | 8 | 499,598 | 33.5% |
| `system_info_discovery` | 31 | 177,342 | 11.9% |
| `persistence` | 5 | 58,244 | 3.9% |
| `resource_development` | 7 | 57,678 | 3.9% |
| `network_scan` | 4 | 711 | 0.05% |
| `account_manipulation` | 202 | 423 | 0.03% |

#### Top Attack Patterns

**Pattern 1: SSH Key Injection Campaign** (161,387 occurrences)
```bash
# Lateral movement sequence
lockr -ia .ssh
cd ~; chattr -ia .ssh; lockr -ia .ssh
cd ~ && rm -rf .ssh && mkdir .ssh && echo "ssh-rsa AAAAB3NzaC1yc2EAAAA..." >> .ssh/authorized_keys
```
- **TTP**: Persistent backdoor via SSH key injection
- **Sophistication**: Automated (identical SSH key across all attempts)
- **Actor type**: Mass compromise campaign (likely botnet)

**Pattern 2: System Reconnaissance** (53,939 occurrences)
```bash
cat /proc/cpuinfo | grep name | wc -l
cat /proc/cpuinfo | grep name | head -n 1 | awk '{print $4,$5,$6,$7,$8,$9;}'
free -m | grep Mem | awk '{print $2 ,$3, $4, $5, $6, $7}'
```
- **TTP**: Resource assessment for cryptocurrency mining
- **Sophistication**: Automated scripted recon
- **Actor type**: Cryptominer deployment (checking CPU/RAM capacity)

**Pattern 3: Persistence Establishment** (53,441 occurrences)
```bash
crontab -l
```
- **TTP**: Checking for existing cron jobs before installing persistence
- **Sophistication**: Cautious (avoiding detection by checking first)
- **Actor type**: Automated malware with anti-detection

#### Feature Importance for ML

| Feature | Discriminative Power | Use Case |
|---------|---------------------|----------|
| `lateral_movement_cmd_ratio` | **HIGH** | Distinguish worm/botnet vs manual |
| `system_info_cmd_ratio` | **HIGH** | Detect cryptominer campaigns |
| `persistence_cmd_ratio` | **MEDIUM** | Identify long-term compromise intent |
| `command_diversity_entropy` | **HIGH** | Human vs automated attack |
| `unique_command_count` | **MEDIUM** | Campaign sophistication |

---

### 1.2 Temporal Behavioral Features

**Data Source**: `results/04_temporal_behavioral_patterns.csv` (5,000 sessions)

#### Summary Statistics

**Command Count Distribution**:
- Mean: 18.6 commands/session
- Std: 5.8 commands
- Median: 20 commands
- Max: 22 commands
- **Insight**: Highly clustered around 20 commands → **automated campaign signature**

**Duration Distribution**:
- Mean: 18.7 seconds/session
- Std: 17.6 seconds
- Median: 17.2 seconds
- Max: 198.7 seconds
- **Insight**: Quick sessions (<30s) suggest automated scanning

**Commands Per Minute**:
- Mean: 204.98 commands/min (from sample)
- **Insight**: >100 cmd/min = automated execution (impossible for humans)

#### Hour-of-Day Pattern

Peak activity hours (UTC):
- **20:00-22:00**: 945 sessions (18.9% of total)
- **17:00-19:00**: 762 sessions (15.2%)
- **06:00-08:00**: 663 sessions (13.3%)

**Trough hours**:
- **04:00-05:00**: 121 sessions (2.4%)
- **09:00**: 138 sessions (2.8%)

**Analysis**:
- No clear geographic timezone pattern (activity spread across 24hrs)
- Slight peak in evening hours (17:00-22:00 UTC) = ~30% of activity
- Suggests **global botnet** rather than single-timezone actor

#### Day-of-Week Pattern

**Requires SQL query** - not in current CSV outputs. Recommend:
```sql
SELECT
    EXTRACT(DOW FROM first_event_at) as day_of_week,
    COUNT(*) as session_count
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
GROUP BY day_of_week
ORDER BY day_of_week;
```

#### Feature Importance for ML

| Feature | Discriminative Power | Use Case |
|---------|---------------------|----------|
| `commands_per_minute` | **CRITICAL** | Automated vs human |
| `session_duration` | **HIGH** | Quick scan vs deep compromise |
| `hour_of_day` | **MEDIUM** | Geographic attribution proxy |
| `day_of_week` | **LOW** | Limited value (botnets operate 24/7) |
| `command_count` | **MEDIUM** | Campaign type clustering |

---

### 1.3 Authentication & Credential Features

**Data Sources**:
- `results/05_password_patterns.csv` (20,754 unique passwords)
- `results/01_session_activity_patterns.csv` (login attempt trends)

#### Password Pattern Analysis

**Reuse Statistics** (from 5,000 sample):
- **Total passwords**: 5,000 unique hashes
- **Total attempts**: 159,526 login attempts
- **Mean reuse**: 31.9 attempts per password
- **Median reuse**: 12 attempts
- **Max reuse**: 11,610 attempts (single password)
- **Std**: 276.7 (high variance = few passwords dominate)

**Top Password Concentration**:
- **Top password**: 11,610 attempts (7.3% of all sampled attempts)
- **Top 3 passwords**: 29,081 attempts (18.2%)
- **Top 20 passwords**: 41,146 attempts (25.8%)
- **Insight**: Highly concentrated credential stuffing campaign

**Breach Analysis**:
- **Breached passwords**: 90.7% (4,535/5,000)
- **Interpretation**: Most passwords are from public breach databases
- **TTP**: Attackers using HaveIBeenPwned or similar leak compilations

**Success Ratio Analysis**:
- **Mean success ratio**: ~99.7% for top passwords
- **Interpretation**: `times_seen ≈ unique_sessions` → passwords work nearly always
- **Conclusion**: These are **valid credentials**, not random bruteforce

#### Login Attempt Trends

**Aggregate Statistics** (317 days):
- **Total login attempts**: 1,507,439
- **Average per day**: 4,754 attempts
- **Total sessions**: 1,629,746
- **Login-to-session ratio**: 0.92 (most sessions include login attempts)

**Temporal Trends** (requires time-series analysis):
- Recommend query for daily/weekly trends
- Look for campaign start/stop patterns
- Identify credential stuffing burst events

#### SSH Key Injection Patterns

**From Session Activity Data**:
- **Total SSH key injections**: 156,295 (from 317 days)
- **Average per day**: 493 injections
- **Percentage of sessions**: 9.6% (156K / 1.63M)

**Correlation with lateral_movement commands**:
- SSH key injection sessions correlate with `lockr -ia .ssh` pattern
- Suggests single coordinated campaign

#### Feature Importance for ML

| Feature | Discriminative Power | Use Case |
|---------|---------------------|----------|
| `password_entropy` | **HIGH** | Random vs dictionary vs leaked |
| `password_reuse_count` | **CRITICAL** | Credential stuffing detection |
| `breached_password_ratio` | **HIGH** | Campaign sophistication |
| `login_attempt_velocity` | **MEDIUM** | Bruteforce vs stuffing |
| `ssh_key_injection_count` | **HIGH** | Lateral movement intent |

---

### 1.4 Activity Volume Features

**Data Source**: `results/01_session_activity_patterns.csv` (317 days)

#### Aggregate Activity Metrics

| Metric | Total | Daily Average | Interpretation |
|--------|-------|---------------|----------------|
| Sessions | 1,629,746 | 5,141 | Sustained high-volume attacks |
| Commands | 1,584,083 | 4,997 | ~1 command/session (quick scans) |
| File downloads | 193,640 | 611 | 11.9% malware delivery rate |
| Login attempts | 1,507,439 | 4,754 | 92% of sessions attempt login |
| SSH key injections | 156,295 | 493 | 9.6% lateral movement attempts |

#### Session vs Command Ratio

- **Commands per session**: 0.97 (aggregate)
- **From temporal sample**: 18.6 commands/session
- **Discrepancy explanation**: Aggregate includes many zero-command sessions (failed logins)
- **Active sessions** (>0 commands): Likely ~8-10% of total

#### File Download Patterns

- **File download rate**: 11.9% of sessions
- **Interpretation**: ~1 in 8 sessions delivers malware payload
- **TTP**: Initial access → immediate payload delivery
- **Recommendation**: Analyze `files` table for VirusTotal enrichment

#### High-Activity Session Analysis

**Data Source**: `results/07_high_activity_sessions.csv` (50,000 sessions)

*Requires analysis of this CSV to extract:*
- Command count thresholds for "high activity"
- Duration patterns for deep compromise attempts
- Correlation with file downloads
- Clustering by behavioral similarity

#### Feature Importance for ML

| Feature | Discriminative Power | Use Case |
|---------|---------------------|----------|
| `session_count_per_cluster` | **HIGH** | Botnet size estimation |
| `commands_per_session` | **CRITICAL** | Scanner vs compromiser |
| `file_download_ratio` | **HIGH** | Malware campaign detection |
| `login_attempt_density` | **MEDIUM** | Bruteforce intensity |
| `ssh_key_injection_ratio` | **HIGH** | Lateral movement campaigns |

---

## Part 2: Enrichment Gap Impact Assessment

### 2.1 Missing Infrastructure Features

#### Geographic Attribution (0% coverage)

**Missing fields**:
- `enrichment->'dshield'->>'country'`: NULL for 30,000+ sessions
- `enrichment->'dshield'->>'asn'`: NULL for 30,000+ sessions
- `enrichment->'dshield'->>'as_name'`: NULL for 30,000+ sessions

**Impact on analysis**:
❌ **Cannot distinguish**:
- Nation-state actors (geographic clustering patterns)
- Regional cybercrime groups (specific ASN ranges)
- Hosting provider abuse (cloud vs residential infrastructure)

❌ **Cannot calculate**:
- Geographic spread (Haversine distance between IPs)
- Country diversity score (unique countries per cluster)
- ASN concentration ratio (single vs distributed infrastructure)

**Workaround**: Use behavioral patterns only (limited actor attribution)

#### Infrastructure Classification (0% coverage)

**Missing fields from SPUR**:
- `enrichment->'spur'->>'client_type'`: NULL (cloud, hosting, residential)
- `enrichment->'spur'->>'is_vpn'`: NULL
- `enrichment->'spur'->>'is_proxy'`: NULL
- `enrichment->'spur'->>'is_tor'`: NULL

**Impact on analysis**:
❌ **Cannot detect**:
- VPN/Tor usage (operational security sophistication)
- Cloud provider abuse patterns (AWS, Azure, GCP)
- Residential botnet vs datacenter C2 infrastructure

❌ **Cannot calculate**:
- Cloud provider ratio (fraction of sessions from cloud IPs)
- Anonymization ratio (VPN/Proxy/Tor usage percentage)
- Infrastructure diversity score

**Workaround**: Manual IP lookup for sample analysis (not scalable)

### 2.2 Missing Reputation Features

#### DShield Attack Scores (0% coverage)

**Missing fields**:
- `enrichment->'dshield'->>'attacks'`: NULL (attack count history)
- `enrichment->'dshield'->>'mindate'`: NULL (first seen date)
- `enrichment->'dshield'->>'maxdate'`: NULL (last seen date)

**Impact on analysis**:
❌ **Cannot prioritize**:
- Known-bad infrastructure (high DShield attack counts)
- Emerging threats (recent first-seen dates)
- Persistent adversaries (long attack history)

#### URLHaus Malware Campaigns (0% coverage)

**Missing fields**:
- `enrichment->'urlhaus'->>'threat_level'`: NULL (malware risk)
- `enrichment->'urlhaus'->>'campaign'`: NULL (malware family)

**Impact on analysis**:
❌ **Cannot link**:
- File downloads to known malware campaigns
- Sessions to specific malware families (Mirai, Gafgyt, etc.)
- Infrastructure to URLHaus-tracked distribution networks

**Partial data available**:
- VirusTotal enrichment for downloaded files (in `files` table)
- Can analyze `vt_positives`, `vt_total`, `vt_permalink`

### 2.3 Actor Profiling Limitations

#### What We CAN Detect (Behavioral Only)

✅ **Automation vs Human**:
- Commands per minute >100 = automated
- Session duration <30s = scanning
- Identical command sequences = scripted

✅ **Campaign Type**:
- SSH key injection = lateral movement campaign
- System recon commands = cryptominer deployment
- Credential stuffing = leaked password usage

✅ **Sophistication Level**:
- Command diversity = manual vs automated
- Anti-detection techniques (checking crontab first)
- Payload delivery patterns (file downloads)

#### What We CANNOT Detect (Infrastructure Required)

❌ **Nation-State vs Cybercrime**:
- Geographic clustering (state-sponsored APT patterns)
- Infrastructure investment (dedicated vs botnet infrastructure)
- Operational security (VPN/Tor usage patterns)

❌ **Botnet Size & Distribution**:
- IP count per campaign (requires geographic spread)
- ASN diversity (single vs distributed C2)
- Residential vs datacenter botnet composition

❌ **Targeted vs Opportunistic**:
- Geographic focus (specific country targeting)
- Infrastructure selection (specific cloud providers)
- Reputation-aware targeting (avoiding DShield-tracked IPs)

### 2.4 Recommended Mitigation

**Short-Term** (Current Phase 1A work):
1. Focus on behavioral TTP profiling
2. Use command patterns for campaign clustering
3. Temporal analysis for botnet detection
4. Password pattern analysis for credential stuffing

**Medium-Term** (Post-Backfill):
1. Run `cowrie-enrich refresh --sessions 0 --files 0`
2. Monitor backfill progress (1-2 weeks expected)
3. Re-run all feature discovery queries
4. Combine behavioral + infrastructure analysis

**Long-Term** (Phase 1B+):
1. Actor profiling with full enrichment
2. Geographic threat intelligence
3. Infrastructure abuse pattern detection
4. Malware campaign attribution

---

## Part 3: Feature Prioritization Matrix

### Tier 1: Critical Features (Available Now)

**High discriminative power, available from behavioral data only**

| Feature | Data Source | Discriminative Power | ML Use Case | Phase 1A Priority |
|---------|-------------|---------------------|-------------|-------------------|
| `lateral_movement_cmd_ratio` | Commands | **CRITICAL** | Botnet detection | ✅ HIGH |
| `commands_per_minute` | Temporal | **CRITICAL** | Automated vs human | ✅ HIGH |
| `password_reuse_count` | Passwords | **CRITICAL** | Credential stuffing | ✅ HIGH |
| `command_diversity_entropy` | Commands | **HIGH** | Campaign sophistication | ✅ HIGH |
| `session_duration` | Temporal | **HIGH** | Scanner vs compromiser | ✅ MEDIUM |
| `file_download_ratio` | Activity | **HIGH** | Malware campaigns | ✅ MEDIUM |
| `ssh_key_injection_ratio` | Activity | **HIGH** | Lateral movement | ✅ MEDIUM |

**Recommended Action**: Implement these features immediately for Phase 1A SSH campaign analysis

### Tier 2: Important Features (Available Now)

**Medium discriminative power, useful for clustering and baseline**

| Feature | Data Source | Discriminative Power | ML Use Case | Phase 1A Priority |
|---------|-------------|---------------------|-------------|-------------------|
| `system_info_cmd_ratio` | Commands | **MEDIUM** | Cryptominer detection | ⚠️ MEDIUM |
| `persistence_cmd_ratio` | Commands | **MEDIUM** | Long-term compromise | ⚠️ MEDIUM |
| `login_attempt_velocity` | Passwords | **MEDIUM** | Bruteforce detection | ⚠️ LOW |
| `hour_of_day_entropy` | Temporal | **MEDIUM** | Geographic proxy | ⚠️ LOW |
| `breached_password_ratio` | Passwords | **MEDIUM** | Leak usage detection | ⚠️ LOW |

**Recommended Action**: Include in baseline model, but lower priority than Tier 1

### Tier 3: Blocked Features (Enrichment Required)

**Critical for actor profiling, but currently unavailable**

| Feature | Data Source | Discriminative Power | ML Use Case | Availability |
|---------|-------------|---------------------|-------------|--------------|
| `geographic_spread_km` | DShield | **CRITICAL** | Nation-state detection | ❌ Post-backfill |
| `cloud_provider_ratio` | SPUR | **CRITICAL** | Infrastructure abuse | ❌ Post-backfill |
| `asn_diversity_score` | DShield | **HIGH** | Botnet distribution | ❌ Post-backfill |
| `vpn_tor_ratio` | SPUR | **HIGH** | OpSec sophistication | ❌ Post-backfill |
| `dshield_reputation_score` | DShield | **HIGH** | Known-bad detection | ❌ Post-backfill |
| `urlhaus_campaign_link` | URLHaus | **MEDIUM** | Malware attribution | ❌ Post-backfill |

**Recommended Action**: Document as "deferred" until enrichment backfill completes

### Tier 4: Low-Value Features

**Available but limited discriminative power**

| Feature | Reason | Recommendation |
|---------|--------|----------------|
| `day_of_week` | Botnets operate 24/7 | Exclude from Phase 1A |
| `raw_command_count` | Replaced by `commands_per_minute` | Use rate instead |
| `absolute_timestamps` | Need relative time features | Convert to velocity/gaps |

---

## Part 4: Post-Backfill Analysis Roadmap

### Phase 1: Enrichment Backfill (1-2 Weeks)

**Step 1: Execute Backfill**
```bash
uv run cowrie-enrich refresh \
    --sessions 0 \
    --files 0 \
    --db "postgresql://user:pass@10.130.30.89/dshield" \
    --vt-api-key $VT_API_KEY \
    --dshield-email $DSHIELD_EMAIL \
    --progress
```

**Expected Timeline**:
- 500K+ sessions to enrich
- VirusTotal: 4 req/min → ~2 weeks for 50K files
- DShield: 30 req/min → ~1 week for 500K IPs (with caching)
- URLHaus: 30 req/min → ~1 week
- SPUR: Rate limits unknown

**Monitoring**:
- Track enrichment completeness via `ENRICHMENT_DIAGNOSTIC_QUERIES_V2.sql` (Query 1)
- Target: >80% enrichment coverage before proceeding

### Phase 2: Infrastructure Feature Analysis (Week 3-4)

**Step 2A: Re-run Feature Discovery Queries**

Execute all Phase 1 queries with enrichment data:
```bash
psql -f scripts/phase1/sql_analysis_queries_v2.sql > results/POST_ENRICHMENT_analysis.csv
```

**Step 2B: Geographic Analysis**
- Country distribution (top attacking nations)
- ASN concentration (top hosting providers)
- Geographic spread (Haversine distance calculations)
- Regional clustering patterns

**Step 2C: Infrastructure Classification**
- Cloud provider distribution (AWS, Azure, GCP, etc.)
- VPN/Proxy/Tor detection rates
- Residential vs datacenter infrastructure
- Anonymization sophistication scores

**Step 2D: Reputation Integration**
- DShield attack score distribution
- Known-bad infrastructure prevalence
- URLHaus malware campaign links
- Threat prioritization matrix

### Phase 3: Combined Behavioral + Infrastructure Profiling (Week 5-6)

**Step 3A: Feature Engineering**

Implement Tier 3 features:
```python
# Geographic features
geographic_spread_km = calculate_haversine_distance(ip_locations)
country_diversity = len(unique_countries) / total_ips
asn_concentration = max_asn_count / total_ips

# Infrastructure features
cloud_provider_ratio = cloud_ips / total_ips
vpn_tor_ratio = (vpn_ips + tor_ips) / total_ips
residential_ratio = residential_ips / total_ips

# Reputation features
avg_dshield_score = mean(dshield_attack_counts)
urlhaus_flagged_ratio = urlhaus_flagged / total_sessions
```

**Step 3B: Actor Profiling Matrix**

Combine behavioral + infrastructure for actor type classification:

| Actor Type | Behavioral Signature | Infrastructure Signature |
|------------|---------------------|-------------------------|
| **Nation-State APT** | Low command diversity, persistence-focused | Geographic clustering, high VPN/Tor ratio |
| **Cybercrime Botnet** | High automation, credential stuffing | Distributed ASNs, residential IPs |
| **Cryptominer** | System recon, resource checks | Cloud provider abuse, low reputation |
| **Script Kiddie** | High command diversity, manual execution | Single ASN, no anonymization |
| **Ransomware Gang** | File operations, lateral movement | Cloud infrastructure, high geographic spread |

**Step 3C: Campaign Detection**

Enhanced snowshoe/longtail detection with infrastructure:
- Behavioral clustering (command patterns, temporal)
- Infrastructure clustering (ASN, cloud provider, geography)
- Combined similarity scoring for campaign attribution

### Phase 4: Baseline Model Training (Week 7-8)

**Step 4A: Feature Validation**

Re-run validation scripts with full features:
```bash
# Test feature extraction with enrichment data
uv run python scripts/test_feature_extraction.py

# Verify feature independence (including infrastructure features)
uv run python scripts/analyze_feature_independence.py
```

**Step 4B: Baseline Model**

Train snowshoe detection baseline:
- Input: Tier 1 + Tier 2 + Tier 3 features
- Target: Binary classification (snowshoe vs single-source)
- Evaluation: Precision/Recall on known campaigns
- Baseline: RandomForest or XGBoost

**Step 4C: Performance Metrics**

Establish baseline performance:
- Detection rate (% of campaigns identified)
- False positive rate (% of single-source flagged)
- Campaign attribution accuracy
- Infrastructure abuse detection rate

---

## Appendices

### Appendix A: SQL Query Recommendations

**Query 1: Day-of-Week Distribution**
```sql
SELECT
    EXTRACT(DOW FROM first_event_at) as day_of_week,
    CASE EXTRACT(DOW FROM first_event_at)
        WHEN 0 THEN 'Sunday'
        WHEN 1 THEN 'Monday'
        WHEN 2 THEN 'Tuesday'
        WHEN 3 THEN 'Wednesday'
        WHEN 4 THEN 'Thursday'
        WHEN 5 THEN 'Friday'
        WHEN 6 THEN 'Saturday'
    END as day_name,
    COUNT(*) as session_count,
    AVG(duration_seconds) as avg_duration,
    AVG(command_count) as avg_commands
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
GROUP BY day_of_week
ORDER BY day_of_week;
```

**Query 2: High-Activity Session Characteristics**
```sql
-- Analyze sessions with >50 commands or >300s duration
SELECT
    session_id,
    command_count,
    duration_seconds,
    login_attempts,
    file_downloads,
    ssh_key_injections,
    commands_per_minute,
    CASE
        WHEN command_count > 50 THEN 'high_commands'
        WHEN duration_seconds > 300 THEN 'long_duration'
        ELSE 'other'
    END as activity_type
FROM session_summaries
WHERE first_event_at >= '2024-11-01'
  AND (command_count > 50 OR duration_seconds > 300)
LIMIT 1000;
```

**Query 3: Password Success Rate Analysis**
```sql
-- Compare successful vs failed login attempts by password
SELECT
    password_hash,
    times_seen as total_attempts,
    unique_sessions as successful_sessions,
    ROUND(unique_sessions::numeric / NULLIF(times_seen, 0), 4) as success_ratio,
    breached,
    breach_prevalence
FROM passwords
WHERE times_seen >= 100
ORDER BY times_seen DESC
LIMIT 100;
```

### Appendix B: Feature Engineering Code Stubs

**Stub 1: Command Category Ratios**
```python
def calculate_command_ratios(session_commands: list[str]) -> dict:
    """Calculate command category ratios for TTP profiling."""
    categories = {
        'lateral_movement': 0,
        'system_info_discovery': 0,
        'persistence': 0,
        'resource_development': 0,
        'other': 0
    }

    for cmd in session_commands:
        category = classify_command(cmd)  # From command_patterns.csv
        categories[category] += 1

    total = len(session_commands)
    return {
        f'{cat}_ratio': count / total if total > 0 else 0
        for cat, count in categories.items()
    }
```

**Stub 2: Temporal Velocity Features**
```python
def calculate_temporal_features(session: SessionSummary) -> dict:
    """Calculate temporal velocity and pattern features."""
    duration_minutes = session.duration_seconds / 60

    return {
        'commands_per_minute': session.command_count / duration_minutes if duration_minutes > 0 else 0,
        'logins_per_minute': session.login_attempts / duration_minutes if duration_minutes > 0 else 0,
        'hour_of_day': session.first_event_at.hour,
        'day_of_week': session.first_event_at.weekday(),
        'is_weekend': session.first_event_at.weekday() >= 5,
        'is_business_hours': 9 <= session.first_event_at.hour <= 17
    }
```

**Stub 3: Credential Pattern Features**
```python
def calculate_credential_features(session: SessionSummary, password_stats: dict) -> dict:
    """Calculate credential attack pattern features."""
    unique_passwords = len(set(session.passwords))

    # Look up breach status for passwords
    breached_count = sum(1 for pwd in session.passwords if password_stats.get(pwd, {}).get('breached'))

    return {
        'unique_password_count': unique_passwords,
        'password_diversity': unique_passwords / len(session.passwords) if session.passwords else 0,
        'breached_password_ratio': breached_count / len(session.passwords) if session.passwords else 0,
        'avg_password_reuse': sum(password_stats.get(pwd, {}).get('times_seen', 1) for pwd in session.passwords) / len(session.passwords) if session.passwords else 0
    }
```

### Appendix C: Data Quality Observations

**Issue 1: Risk Score Uniformity**
- All sampled sessions show `risk_score=100`
- Expected: Variable risk scores based on behavior
- Investigation needed: Risk calculation logic may be broken

**Issue 2: VT/DShield Flagged Always Zero**
- `vt_flagged=0` for all 317 days
- `dshield_flagged=0` for all 317 days
- Confirms enrichment was never populated (not just NULL, but FALSE)

**Issue 3: Commands Per Session Discrepancy**
- Aggregate: 0.97 commands/session (1.58M commands / 1.63M sessions)
- Sample: 18.6 commands/session (from 5K session sample)
- Explanation: Most sessions have 0 commands (failed login attempts)
- Recommendation: Filter for `command_count > 0` in analyses

**Issue 4: SSH Key Injection Count**
- Total SSH key injections: 156,295
- Expected correlation with `lateral_movement` commands: 499,598
- Ratio: 31% of lateral_movement sessions include SSH key injection
- Investigate: What are the other 69% of lateral_movement commands?

---

## Conclusion

### Summary

This report provides a comprehensive analysis of **behavioral features** extracted from 1.63M honeypot sessions. Despite the complete lack of enrichment data (0% coverage), we have identified strong behavioral signals for:

✅ **Automated vs Human Detection**: Commands per minute, session duration
✅ **Campaign Type Classification**: Command patterns, TTP analysis
✅ **Credential Stuffing Detection**: Password reuse, breach correlation
✅ **Lateral Movement Campaigns**: SSH key injection patterns

However, **infrastructure-based actor profiling is blocked** until enrichment backfill completes.

### Recommendations

**Immediate** (This Week):
1. ✅ Use Tier 1 behavioral features for Phase 1A SSH campaign analysis
2. ✅ Begin enrichment backfill process (1-2 weeks expected)
3. ⚠️ Investigate risk_score calculation bug (always 100)

**Short-Term** (Weeks 3-4):
1. Re-run feature discovery queries with enrichment data
2. Implement Tier 3 infrastructure features
3. Update snowshoe detection with geographic features

**Medium-Term** (Weeks 5-8):
1. Combined behavioral + infrastructure actor profiling
2. Baseline model training with full feature set
3. Campaign detection and attribution testing

### Phase 1A Impact

**What We CAN Do Now**:
- SSH campaign behavioral clustering
- Automated vs manual attack detection
- Credential stuffing campaign identification
- TTP-based actor profiling (limited)

**What We CANNOT Do** (Post-Backfill):
- Nation-state vs cybercrime attribution
- Geographic threat intelligence
- Infrastructure abuse detection
- Malware campaign attribution

**Recommended Path Forward**: Proceed with Phase 1A using behavioral features, re-analyze with infrastructure data when available.

---

**Status**: ✅ Behavioral Analysis Complete | ⏳ Awaiting Enrichment Backfill
**Next Milestone**: Phase 1A SSH Campaign Analysis (Behavioral Features Only)
