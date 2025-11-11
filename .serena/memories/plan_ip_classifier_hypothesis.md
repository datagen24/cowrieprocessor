# IPClassifier Implementation Hypothesis

**Date**: 2025-11-10
**Feature**: IP Infrastructure Classification Service
**Timeline**: 3-4 weeks, 18 tasks, $0/month cost

## Hypothesis

Implementing free IP classification as Pass 4 in CascadeEnricher will populate snapshot_ip_type (0% → 90%+), enabling 5-8 new infrastructure features with 5.5x discrimination improvement.

## Design Documents

- README_IP_CLASSIFICATION.md (executive summary)
- ip_classifier_service_specification.md (50+ pages)
- ip_classifier_implementation_guide.md (step-by-step)
- ip_classifier_enrichment_integration.md (pipeline hooks)

## Expected Outcomes

- snapshot_ip_type: 0% → 90%+ (1.68M sessions)
- Viable features: 10-12 → 15-18 (+50%)
- Infrastructure discrimination: 0.145 → 0.8+ (5.5x)
- Accuracy: TOR 95%+, Cloud 99%+, DC/Resi 70%+
- Performance: >95% cache hit, <20ms p99 latency
- Cost: $0/month (free data sources)

## Implementation Phases

Week 1: Core (models, matchers, tests)
Week 2: Cache + Service (multi-tier, IPClassifier)
Week 3: Integration (CascadeEnricher Pass 4, refresh --ips)
Week 4: Validation (backfill 38K IPs + 1.68M sessions)

## PDCA Documentation

- Plan: docs/pdca/ip_classifier/plan.md ✅
- Do: docs/pdca/ip_classifier/do.md (in progress)
- Check: docs/pdca/ip_classifier/check.md (pending)
- Act: docs/pdca/ip_classifier/act.md (pending)

## Status

✅ Plan complete
🔄 Ready to begin implementation
