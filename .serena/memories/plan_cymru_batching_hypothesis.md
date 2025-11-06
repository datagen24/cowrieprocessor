# Plan: Cymru Batching Optimization

## Date: 2025-11-06

## Hypothesis
Implementing synchronous batching for Cymru ASN lookups will eliminate DNS timeout issues and reduce enrichment time by 30% (16 minutes → 11 minutes for 10,000 IPs).

## Current Problem
- Individual DNS lookups per IP causing timeouts
- User observed: "DNS timeout for X.X.X.X, retrying in 1.0s"
- 10,000 IPs taking ~16 minutes with retry delays

## Solution: 3-Pass Enrichment
1. Pass 1: MaxMind (collect IPs needing Cymru)
2. Pass 2: Cymru bulk_lookup() (batches of 500)
3. Pass 3: Merge + GreyNoise

## Expected: 31% faster, zero DNS timeouts

## Delegation:
- backend-architect: Implementation
- quality-engineer: Testing
- technical-writer: Documentation
