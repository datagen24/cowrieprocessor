# ADR-007/008 Compliance Remediation Execution

## Context
Working on systematic remediation of ADR-007/008 compliance violations identified in `/Users/speterson/src/dshield/cowrieprocessor/claudedocs/ADR_007_008_COMPLIANCE_ANALYSIS.md`

## Violations Summary
1. **CRITICAL SECURITY**: Credentials exposed in git (DB password, VT API key, URLHaus API key)
2. **HIGH**: Enrichment cache integration missing (CascadeEnricher not using EnrichmentCacheManager)
3. **HIGH**: Incomplete workflow integration (Net New, Refresh, Backfill)
4. **MEDIUM**: Documentation errors (non-existent package extras, missing procedures)
5. **MEDIUM**: Scale testing gap (staging vs production data volumes)

## Execution Strategy
**Multi-Agent Parallel Execution Pattern**

### Phase 0: BLOCKING Security Tasks
- Task 0.3: security-engineer → Update sensors.example.toml with secrets patterns
- Task 0.4: backend-architect → Create cascade_factory.py with secrets integration
- Task 0.5: devops-architect → Add pre-commit hooks for credential detection

Note: Tasks 0.1 (credential rotation) and 0.2 (git history cleanup) require user coordination as they affect production systems and require force-push.

### Phase 1: Immediate Stabilization
- Task 1.1: backend-architect → Create cascade_factory.py (if not in 0.4)
- Task 1.2: backend-architect → Integrate into cowrie-loader (delta/bulk)
- Task 1.3: backend-architect → Integrate into cowrie-enrich refresh

### Phase 2: Documentation & Workflow
- Task 2.3: technical-writer → Fix documentation errors
- Task 2.3: technical-writer → Create operational procedures guide

## Sub-Agent Delegation Plan
1. **security-engineer**: Secrets management patterns (Task 0.3)
2. **backend-architect**: Factory function + workflow integration (Tasks 0.4, 1.1, 1.2, 1.3)
3. **devops-architect**: Pre-commit hooks (Task 0.5)
4. **technical-writer**: Documentation fixes (Task 2.3)

## Execution Order
1. Parallel: Tasks 0.3, 0.4, 0.5 (security hardening)
2. Sequential: Tasks 1.1→1.2→1.3 (depends on factory)
3. Parallel: Task 2.3 (documentation - independent)

## Success Criteria
- ✅ No plaintext credentials in example config
- ✅ Factory function with secrets resolver integration exists
- ✅ Pre-commit hooks prevent future credential exposure
- ✅ CascadeEnricher integrates with EnrichmentCacheManager
- ✅ All three workflows (Net New, Refresh, Backfill) functional
- ✅ Documentation errors corrected
- ✅ All code passes CI gates (ruff, mypy, pytest ≥65%)

## Started
2025-11-06 via /sc:pm command
