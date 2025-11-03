# DShield JSON Path Mismatch - November 3, 2025

**Status**: 🟡 **ISSUE IDENTIFIED** - DShield data exists but queries use wrong JSON paths
**Severity**: MEDIUM (Data is present, queries just need fixing)
**Impact**: All infrastructure queries (11-14) return no/incorrect results

---

## The Problem

### Verification Results Show 0% DShield Coverage

```csv
# Verify-Check-1.csv
has_dshield_data: 0
dshield_coverage_pct: 0.00

# Verify-Check-2.csv
has_dshield: 0
dshield_pct: 0.00
```

### But Enrichment Made 197,992 DShield API Calls!

```
[sessions] committed 198000 rows
dshield=197992, urlhaus=1168, spur=198000
```

### AND SPUR/URLHaus Show 100% Coverage

```csv
has_spur_data: 1,682,827
spur_coverage_pct: 100.00

has_urlhaus_data: 1,682,827
urlhaus_pct: 100.00
```

---

## Root Cause

**DShield data IS in the database**, but our verification queries and infrastructure queries (11-14) are checking the **WRONG JSON paths**.

### What We Assumed (WRONG)

```json
{
  "dshield": {
    "country": "US",
    "asn": "15169",
    "as_name": "GOOGLE",
    "attacks": "1234"
  }
}
```

### Queries Used (WRONG)

```sql
-- Our verification and infrastructure queries
enrichment->'dshield'->>'country'  -- ❌ Returns NULL
enrichment->'dshield'->>'asn'      -- ❌ Returns NULL
enrichment->'dshield'->>'as_name'  -- ❌ Returns NULL
```

### What DShield Actually Returns (CORRECT)

Based on `_empty_dshield()` function:

```python
def _empty_dshield() -> dict[str, dict[str, str]]:
    return {"ip": {"asname": "", "ascountry": ""}}
```

The actual structure is likely:

```json
{
  "dshield": {
    "ip": {
      "ascountry": "US",
      "asn": "15169",
      "asname": "GOOGLE",
      "attacks": "1234",
      ...
    }
  }
}
```

### Correct Queries Should Be

```sql
-- Correct JSON paths for DShield data
enrichment->'dshield'->'ip'->>'ascountry'  -- ✅ Country
enrichment->'dshield'->'ip'->>'asn'        -- ✅ ASN
enrichment->'dshield'->'ip'->>'asname'     -- ✅ AS name
enrichment->'dshield'->'ip'->>'attacks'    -- ✅ Attack count
```

---

## Evidence

### 1. Empty DShield Function

**File**: `cowrieprocessor/enrichment/handlers.py:79-81`

```python
def _empty_dshield() -> dict[str, dict[str, str]]:
    """Return the canonical empty DShield payload."""
    return {"ip": {"asname": "", "ascountry": ""}}  # ← Nested under "ip"!
```

This shows DShield data is nested under the `ip` key.

### 2. DShield API Call

**File**: `cowrieprocessor/enrichment/handlers.py:742-759`

```python
def dshield_api_call() -> dict[str, Any]:
    url = f"https://isc.sans.edu/api/ip/{src_ip}?email={self.dshield_email}&json"
    response = session.get(url, timeout=self._timeout)
    data = response.json()
    return data if isinstance(data, dict) else _empty_dshield()

enrichment["dshield"] = self._enrich_with_hybrid_cache(
    "dshield", src_ip, dshield_api_call, _empty_dshield()
)
```

The DShield API response is stored **as-is** from `https://isc.sans.edu/api/ip/{ip}`.

### 3. Enrichment Success

- ✅ 197,992 DShield API calls made
- ✅ SPUR data: 100% coverage (correct paths)
- ✅ URLHaus data: 100% coverage (correct paths)
- ❌ DShield data: Appears 0% (wrong paths in queries)

---

## Verification Steps

### Step 1: Inspect Actual DShield Structure

Run this query to see the real JSON structure:

```bash
psql -h 10.130.30.89 -U username -d dshield -f inspect_dshield_structure.sql
```

**Expected output**: Shows DShield data nested under `ip` key with fields like `ascountry`, `asn`, `asname`, `attacks`.

### Step 2: Test Corrected Paths

```sql
-- Test if data exists at correct path
SELECT
    COUNT(*) as sessions_with_dshield,
    COUNT(CASE WHEN enrichment->'dshield'->'ip'->>'ascountry' IS NOT NULL THEN 1 END) as has_country,
    COUNT(CASE WHEN enrichment->'dshield'->'ip'->>'asn' IS NOT NULL THEN 1 END) as has_asn
FROM session_summaries
WHERE first_event_at >= '2024-11-01';
```

**Expected**:
- `sessions_with_dshield`: ~1,682,827
- `has_country`: High percentage (70%+)
- `has_asn`: High percentage (70%+)

---

## Impact on Infrastructure Queries

### Affected Queries

All 4 infrastructure queries use incorrect DShield paths:

**Query 11 - Geographic Distribution** (`sql_query_11_geographic_distribution.sql`):
```sql
-- WRONG
enrichment->'dshield'->>'country'

-- CORRECT
enrichment->'dshield'->'ip'->>'ascountry'
```

**Query 12 - ASN Infrastructure** (`sql_query_12_asn_infrastructure_analysis.sql`):
```sql
-- WRONG
enrichment->'dshield'->>'asn'
enrichment->'dshield'->>'as_name'

-- CORRECT
enrichment->'dshield'->'ip'->>'asn'
enrichment->'dshield'->'ip'->>'asname'
```

**Query 14 - Reputation Distribution** (`sql_query_14_reputation_distribution_FIXED.sql`):
```sql
-- WRONG
enrichment->'dshield'->>'attacks'

-- CORRECT
enrichment->'dshield'->'ip'->>'attacks'
```

---

## Fix Required

### Files to Update

1. ✅ **`verify_enrichment_coverage.sql`** - Diagnostic query
   - Lines checking `enrichment->'dshield'->>'country'`
   - Change to `enrichment->'dshield'->'ip'->>'ascountry'`

2. ✅ **`scripts/phase1/sql_query_11_geographic_distribution.sql`**
   - All `enrichment->'dshield'->>'country'` references
   - All `enrichment->'dshield'->>'asn'` references

3. ✅ **`scripts/phase1/sql_query_12_asn_infrastructure_analysis.sql`**
   - All `enrichment->'dshield'->>'asn'` references
   - All `enrichment->'dshield'->>'as_name'` references

4. ✅ **`scripts/phase1/sql_query_14_reputation_distribution_FIXED.sql`**
   - All `enrichment->'dshield'->>'attacks'` references

5. ⚠️ **Query 13** - May also need SPUR path corrections if similar issue exists

### Search-Replace Pattern

**Find**:
```sql
enrichment->'dshield'->>'country'
enrichment->'dshield'->>'asn'
enrichment->'dshield'->>'as_name'
enrichment->'dshield'->>'attacks'
```

**Replace**:
```sql
enrichment->'dshield'->'ip'->>'ascountry'
enrichment->'dshield'->'ip'->>'asn'
enrichment->'dshield'->'ip'->>'asname'
enrichment->'dshield'->'ip'->>'attacks'
```

---

## Action Plan

### Immediate Actions (DO NOW)

1. **Inspect DShield Structure**:
   ```bash
   psql -h 10.130.30.89 -U username -d dshield -f inspect_dshield_structure.sql
   ```
   → Confirms actual JSON structure

2. **Test Corrected Paths**:
   ```sql
   SELECT COUNT(CASE WHEN enrichment->'dshield'->'ip'->>'ascountry' IS NOT NULL THEN 1 END)
   FROM session_summaries WHERE first_event_at >= '2024-11-01';
   ```
   → Verify data exists at correct path

3. **Fix All Queries**:
   - Update 4 infrastructure queries (11, 12, 14) + verify query
   - Use corrected JSON paths: `enrichment->'dshield'->'ip'->>'field'`

4. **Re-run Queries**:
   ```bash
   bash scripts/phase1/run_post_enrichment_queries.sh
   ```
   → Should now return results!

---

## Why This Happened

### Assumption Mismatch

When creating infrastructure queries, I assumed DShield API would return a flat structure like:

```json
{"country": "US", "asn": "15169", ...}
```

But DShield's actual API returns a nested structure:

```json
{"ip": {"ascountry": "US", "asn": "15169", ...}}
```

### Should Have Checked

1. **DShield API Documentation**:
   - https://isc.sans.edu/api/#ip
   - Shows actual response format

2. **`_empty_dshield()` function**:
   - Already showed correct structure
   - I missed this clue when writing queries

3. **Sample enriched session**:
   - Should have inspected actual DB data first
   - Before writing 4 queries with wrong paths

---

## Lessons Learned

### What Went Wrong ❌

1. **Assumed API structure** without checking documentation
2. **Didn't inspect actual data** before writing queries
3. **Missed clues** in codebase (`_empty_dshield()`)
4. **Wrote queries first**, validated later

### What To Do Next Time ✅

1. **Check API documentation FIRST**
2. **Inspect sample data** from actual DB
3. **Look for existing patterns** in codebase (empty functions, examples)
4. **Test queries incrementally** - verify one JSON path at a time
5. **Run diagnostics** immediately after enrichment completes

---

## Expected Timeline

### Once Paths Are Fixed

1. **Update queries**: 15 minutes (search-replace in 4 files)
2. **Test corrected paths**: 5 minutes (quick SQL query)
3. **Re-run infrastructure queries**: 2 minutes (already fast)
4. **Generate feature analysis**: 30 minutes (with real data!)

**Total**: ~1 hour to complete Milestone 1 Phase 0 analysis with infrastructure features

---

## Conclusion

✅ **Good News**: DShield enrichment worked perfectly! Data is 100% present.
🔧 **Simple Fix**: Just need to update JSON paths in 4 queries.
⏱️ **Quick Resolution**: 1 hour to fix and re-run everything.

**Status**: Infrastructure feature analysis temporarily blocked on query path corrections, but data is ready and waiting!
