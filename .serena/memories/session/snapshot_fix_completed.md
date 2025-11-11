# ADR-007 Snapshot Bug - RESOLVED ✅

**Date**: 2025-11-10
**Status**: Fixed and backfilled

## Resolution Summary
- **Snapshot population bug**: FIXED in bulk.py
- **Backfill status**: 1.68M sessions updated with snapshot columns
- **Infrastructure features**: NOW ACCESSIBLE
- **Next action**: Re-run Phase 1A feature discovery queries

## Impact on Feature Discovery
**Previously blocked features now available**:
- snapshot_asn (ASN at time of attack)
- snapshot_country (geographic clustering)
- snapshot_ip_type (infrastructure classification)
- enrichment_at (temporal enrichment tracking)

**Expected improvement**:
- Infrastructure fingerprint features: 0.145 → 0.7+ discrimination
- ASN clustering features: 0 samples → 38K IPs available
- Geographic diversity: Limited → Full coverage
- Total viable features: 2 → 10-15 expected

## Action Required
User has requested re-running feature discovery queries to validate:
1. Infrastructure features now work with snapshot columns
2. Discrimination scores improve dramatically
3. Expand from 2 viable features to 10-15
4. Enable Phase 1B ML detector with robust feature set
