# Plan: Milestone 1 - Snowshoe Enhancement Phase 0

## Hypothesis

**Goal**: Establish baseline infrastructure for snowshoe spam detection enhancement by completing critical blockers in defanging normalization, test dataset creation, and feature extraction validation.

**Why this approach**:
- Phase 0 establishes measurement infrastructure (baseline metrics + test datasets)
- Defanging normalization is critical for command sequence analysis (Phase 2.2)
- Provider classification enables behavioral profiling (cloud/VPN/Tor patterns)
- Feature validation ensures ML model training will use robust, independent features

**Expected Outcomes** (Quantitative):
- **Test Coverage**: Current unknown → Target 70%+ for new modules
- **Implementation Time**: ~81 hours (P0+P1 only, P2 deferred)
- **Dataset Quality**: 20 labeled incidents (MVP) with 100% metadata validation
- **Baseline Metrics**: Precision/Recall/F1 documented for current detector
- **Feature Independence**: Correlation analysis showing |r| < 0.95 for all pairs

## Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|-----------|
| MVP dataset too small for meaningful baseline | Medium | Focus on edge case coverage over size; defer full dataset (#60) to later |
| Defanging patterns incomplete | High | Comprehensive edge case documentation (#51) before implementation |
| Provider classification unreliable with stale data | Medium | Implement staleness tracking + confidence metadata |
| Feature correlation analysis reveals redundancies | Low | Designed outcome - will remove highly correlated features (r>0.95) |
| Time estimate too optimistic | Medium | Parallel tracks + agent delegation for efficiency |

## Execution Phases

### Phase 1: Critical Blockers (Parallel Tracks) - P0
**Duration**: ~63 hours (parallelized to ~18 hours wall time)

**Track A: Defanging Normalization** (18h)
- Agent: `python-expert` + `technical-writer` + `quality-engineer`
- Issues: #50 → #51 → #52
- Deliverables:
  - `cowrieprocessor/vectorization/defanging_normalizer.py`
  - Edge case documentation
  - Vocabulary consistency tests passing

**Track B: Dataset & Baseline** (24h)
- Agent: `quality-engineer` + `deep-research-agent`
- Issues: #53 → #54
- Deliverables:
  - `tests/fixtures/snowshoe_baseline/` with 20 labeled incidents
  - Baseline metrics report (Precision/Recall/F1)
  - Failure mode analysis

**Track C: Provider Classification** (18h)
- Agent: `backend-architect` + `python-expert`
- Issues: #55 → #56
- Deliverables:
  - `cowrieprocessor/features/provider_classification.py`
  - `cowrieprocessor/features/aggregation.py`
  - Enrichment-based provider detection (cloud/VPN/Tor)

**Track D: Batch Size Optimization** (3h)
- Agent: `backend-architect`
- Issues: #59
- Deliverables:
  - `cowrieprocessor/utils/memory.py`
  - Auto-calculation based on memory limits
  - Configuration updates

### Phase 2: Validation - P1
**Duration**: ~15 hours (sequential after Phase 1)

**Feature Testing & Analysis** (12h)
- Agent: `quality-engineer` + `performance-engineer`
- Issues: #57 → #58
- Deliverables:
  - Feature extraction robustness test (50+ sessions)
  - Correlation analysis + matrix visualization
  - Feature independence validation

### Phase 3: Complete Dataset - P2 (DEFERRED)
**Duration**: ~48 hours (defer to post-milestone)

- Issues: #60, #61
- Reason: MVP dataset (#53) sufficient for Phase 0 objectives
- Timeline: Complete during Phase 6 (full validation)

## Success Criteria

**Code Quality**:
- [ ] All new modules pass ruff format/lint
- [ ] MyPy type checking passes (0 errors)
- [ ] Test coverage ≥65% overall, ≥70% for new modules
- [ ] All tests pass in CI pipeline

**Functionality**:
- [ ] DefangingAwareNormalizer handles all 6 pattern types + edge cases
- [ ] Vocabulary consistency tests: 100% pass rate (9/9 cases)
- [ ] MVP dataset: 20 incidents with complete metadata
- [ ] Baseline metrics: P/R/F1 calculated and documented
- [ ] Provider classification: Works with DShield + Spur enrichment
- [ ] Feature aggregation: Geographic spread + entropy functions complete
- [ ] Feature testing: 100% extraction success on 50+ sessions
- [ ] Feature independence: All pairs |r| < 0.95

**Documentation**:
- [ ] Phase 0 research document updated with all results
- [ ] Defanging edge cases documented
- [ ] Baseline report created
- [ ] Failure mode analysis documented
- [ ] All GitHub issues closed with completion comments

## Agent Coordination

### Parallel Execution Strategy
```yaml
Agents Active Simultaneously (Phase 1):
  - python-expert: #50 DefangingAwareNormalizer + #56 Aggregation
  - backend-architect: #55 Provider classification + #59 Batch size
  - quality-engineer: #53 MVP dataset + #54 Baseline + #52 Tests
  - technical-writer: #51 Edge case documentation

Sequential Handoffs (Phase 2):
  - quality-engineer: #57 Feature testing (requires #55, #56)
  - performance-engineer: #58 Independence analysis (requires #57)
```

### MCP Tool Loading Strategy
```yaml
Phase 1 Tools:
  - context7: Python patterns, pytest best practices
  - sequential: Complex analysis for provider classification logic
  - serena: Code navigation and symbol operations

Phase 2 Tools:
  - sequential: Statistical analysis for correlation
  - context7: NumPy/pandas patterns for feature analysis
```

## Next Actions

1. **Immediate**: Start Track A (python-expert → #50 DefangingAwareNormalizer)
2. **Parallel**: Start Track C (backend-architect → #55 Provider Classification)
3. **Parallel**: Start Track D (backend-architect → #59 Batch Size)
4. **Parallel**: Start Track B (quality-engineer → #53 MVP Dataset)
5. **Sequential**: Quality gates before Phase 2 (#57, #58)

## Quality Gates

**Gate 1**: Before moving to Phase 2
- All Phase 1 tracks complete
- All P0 tests passing
- Code coverage ≥65%
- MyPy + Ruff passing

**Gate 2**: Before milestone closure
- All P1 issues complete
- Baseline metrics documented
- Feature validation complete
- All acceptance criteria met
