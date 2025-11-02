# Sanitization Performance Fix - 50-100x Speed Improvement

**Date**: 2025-11-02
**Issue**: Sanitization taking 20+ hours to process 12.4M records
**Root Cause**: OFFSET pagination O(n) complexity + processing all records
**Solution**: Cursor-based pagination + pre-filtering + batch UPDATEs
**Expected Speedup**: 50-100x faster (20 hours → 15-30 minutes)

---

## 🚨 Current Performance Crisis

### Stats After 8 Hours
- **Processed**: 1,372,000 records
- **Total DB**: 12,410,467 records
- **Remaining**: 11,038,467 records (89%)
- **Speed**: ~171 records/second
- **Estimated completion**: 20+ hours total

### Root Causes

**1. OFFSET Pagination (CATASTROPHIC)**
```sql
SELECT id, payload::text FROM raw_events
ORDER BY id LIMIT 1000 OFFSET 1372000;
```
- PostgreSQL scans 1.37M rows to skip them, then returns 1,000
- **O(n) complexity** - gets exponentially slower
- At 5M offset: scans 5M rows for each batch!

**2. No Pre-Filtering (MAJOR WASTE)**
```sql
SELECT ... FROM raw_events  -- ALL 12.4M records!
```
- Processes every record in Python
- Only ~1,267 records (0.01%) actually need fixing
- Wastes 99.99% of processing time

**3. Individual UPDATEs (INEFFICIENT)**
- One UPDATE statement per problematic record
- ~1,267 individual transactions instead of batching

---

## ⚡ Immediate SQL-Only Fix

### Option A: Direct PostgreSQL Regex Replace (Fastest!)

**Run this SQL directly to bypass Python entirely:**

```sql
-- BACKUP FIRST!
CREATE TABLE raw_events_backup AS SELECT * FROM raw_events WHERE id IN (
    SELECT id FROM raw_events
    WHERE payload::text ~ '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]'
);

-- Single UPDATE using regex_replace (processes ~1,267 records in seconds)
UPDATE raw_events
SET payload = CAST(
    regexp_replace(
        payload::text,
        '\\u0000', '', 'g'  -- Remove \u0000 null bytes
    ) AS jsonb
)
WHERE payload::text ~ '\\u0000';

-- Repeat for other control characters if needed:
UPDATE raw_events
SET payload = CAST(
    regexp_replace(
        payload::text,
        '\\u0001', '', 'g'  -- Remove \u0001 SOH
    ) AS jsonb
)
WHERE payload::text ~ '\\u0001';

-- Or use a more comprehensive regex (PostgreSQL 9.3+):
UPDATE raw_events
SET payload = CAST(
    regexp_replace(
        payload::text,
        '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]',
        '',
        'g'
    ) AS jsonb
)
WHERE payload::text ~ '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]';

-- Verify fix
SELECT COUNT(*) FROM raw_events
WHERE payload::text ~ '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]';
-- Should return 0
```

**Estimated time**: 5-10 seconds for ~1,267 records

---

### Option B: Stop Current Job, Use Optimized Python

**Kill the current slow sanitization:**
```bash
pkill -f "cowrie-db sanitize"
```

**Use the optimized version (see implementation below)**

---

## 🚀 Optimized Python Implementation

### Key Changes

**1. Cursor-Based Pagination**
```python
# OLD (O(n) - slow):
WHERE id IN (SELECT id FROM raw_events ORDER BY id LIMIT 1000 OFFSET 1372000)

# NEW (O(1) - fast):
WHERE id > :last_processed_id ORDER BY id LIMIT 1000
```

**2. Pre-Filter with WHERE Clause**
```python
# OLD: Fetch ALL, filter in Python
SELECT id, payload::text FROM raw_events ORDER BY id LIMIT 1000

# NEW: Filter in SQL, fetch only problematic
SELECT id, payload::text FROM raw_events
WHERE payload::text ~ '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]'
  AND id > :last_id
ORDER BY id LIMIT 1000
```

**3. Batch UPDATEs**
```python
# OLD: Individual UPDATEs
for record in batch:
    UPDATE raw_events SET payload = :val WHERE id = :id

# NEW: Single batch UPDATE
UPDATE raw_events
SET payload = CASE id
    WHEN 123 THEN CAST(:val_123 AS jsonb)
    WHEN 456 THEN CAST(:val_456 AS jsonb)
    ...
END
WHERE id IN (123, 456, ...)
```

### Implementation

**File**: `cowrieprocessor/cli/cowrie_db.py:903-1091`

Replace `sanitize_unicode_in_database()` with:

```python
def sanitize_unicode_in_database(
    self,
    batch_size: int = 1000,
    limit: Optional[int] = None,
    dry_run: bool = False,
    progress_callback: Optional[Callable[[SanitizationMetrics], None]] = None,
    use_optimized: bool = True,  # NEW FLAG
) -> Dict[str, Any]:
    """Sanitize Unicode control characters in existing database records.

    Args:
        batch_size: Number of records to process in each batch
        limit: Maximum number of records to process (None for all)
        dry_run: If True, only report what would be changed
        progress_callback: Optional callback for progress updates
        use_optimized: If True, use cursor-based pagination with pre-filtering (50-100x faster)

    Returns:
        Sanitization result with statistics
    """
    result: Dict[str, Any] = {
        'records_processed': 0,
        'records_updated': 0,
        'records_skipped': 0,
        'errors': 0,
        'batches_processed': 0,
        'dry_run': dry_run,
        'message': '',
        'error': '',
    }

    try:
        if not self._table_exists('raw_events'):
            raise Exception("Raw events table does not exist.")

        dialect_name = get_dialect_name_from_engine(self._get_engine())
        logger.info(f"Starting Unicode sanitization (dry_run={dry_run}, optimized={use_optimized})...")

        if use_optimized and dialect_name == "postgresql":
            # OPTIMIZED PATH: Cursor-based with pre-filtering
            last_id = 0

            while True:
                # Fetch only problematic records after last_id
                with self._get_engine().connect() as conn:
                    query = text("""
                        SELECT id, payload::text as payload_text
                        FROM raw_events
                        WHERE id > :last_id
                          AND payload::text ~ '\\\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\\\u007[fF]'
                        ORDER BY id
                        LIMIT :batch_size
                    """)

                    batch_records = conn.execute(
                        query,
                        {"last_id": last_id, "batch_size": batch_size}
                    ).fetchall()

                if not batch_records:
                    break

                # Process batch (sanitize in Python)
                records_to_update = []

                for record in batch_records:
                    try:
                        record_id = record.id
                        original_payload_text = record.payload_text

                        # Sanitize the payload
                        sanitized_payload_text = UnicodeSanitizer.sanitize_json_string(original_payload_text)

                        # Verify the sanitized payload is valid JSON and safe
                        try:
                            parsed_payload = json.loads(sanitized_payload_text)
                            if UnicodeSanitizer.is_safe_for_postgres_json(sanitized_payload_text):
                                records_to_update.append({
                                    'id': record_id,
                                    'sanitized': sanitized_payload_text,
                                })
                                result['records_updated'] += 1
                            else:
                                logger.warning(f"Record {record_id}: Sanitized payload still unsafe")
                                result['records_skipped'] += 1
                        except json.JSONDecodeError as e:
                            logger.warning(f"Record {record_id}: Invalid JSON after sanitization: {e}")
                            result['records_skipped'] += 1

                        result['records_processed'] += 1

                    except Exception as e:
                        logger.error(f"Error processing record {record.id}: {e}")
                        result['errors'] += 1
                        result['records_processed'] += 1

                # Batch UPDATE using CASE statement
                if records_to_update and not dry_run:
                    with self._get_engine().begin() as conn:
                        # Build CASE statement for batch update
                        ids = [r['id'] for r in records_to_update]
                        when_clauses = []
                        params = {}

                        for i, record in enumerate(records_to_update):
                            param_name = f"val_{i}"
                            when_clauses.append(f"WHEN {record['id']} THEN CAST(:{param_name} AS jsonb)")
                            params[param_name] = record['sanitized']

                        update_query = text(f"""
                            UPDATE raw_events
                            SET payload = CASE id
                                {' '.join(when_clauses)}
                            END
                            WHERE id = ANY(:ids)
                        """)
                        params['ids'] = ids

                        try:
                            conn.execute(update_query, params)
                        except Exception as e:
                            logger.error(f"Error in batch UPDATE: {e}")
                            result['errors'] += len(records_to_update)

                result['batches_processed'] += 1
                last_id = batch_records[-1].id  # Update cursor

                # Log progress
                if result['batches_processed'] % 10 == 0:
                    logger.info(
                        f"Processed {result['records_processed']} records, "
                        f"updated {result['records_updated']}, "
                        f"errors {result['errors']}"
                    )

                    if progress_callback:
                        metrics = SanitizationMetrics(
                            records_processed=result['records_processed'],
                            records_updated=result['records_updated'],
                            records_skipped=result['records_skipped'],
                            errors=result['errors'],
                            batches_processed=result['batches_processed'],
                            dry_run=dry_run,
                        )
                        progress_callback(metrics)

                # Check limit
                if limit and result['records_processed'] >= limit:
                    break

        else:
            # FALLBACK: Original OFFSET-based approach for SQLite or if optimized disabled
            # ... (keep existing code as fallback) ...
            pass

        # Final message
        if dry_run:
            result['message'] = (
                f"Dry run completed: {result['records_processed']} records analyzed, "
                f"{result['records_updated']} would be updated, "
                f"{result['errors']} errors"
            )
        else:
            result['message'] = (
                f"Sanitization completed: {result['records_processed']} records processed, "
                f"{result['records_updated']} updated, "
                f"{result['errors']} errors"
            )

    except Exception as e:
        result['error'] = str(e)
        result['message'] = f"Sanitization failed: {e}"
        raise

    return result
```

---

## 📊 Performance Comparison

| Metric | Current | Optimized | Improvement |
|--------|---------|-----------|-------------|
| Records scanned/batch | 12.4M (full table) | ~1K (filtered) | 12,400x less |
| Pagination method | OFFSET (O(n)) | Cursor (O(1)) | O(n) → O(1) |
| UPDATEs/batch | ~100 individual | 1 batch | 100x less |
| Est. total time | 20+ hours | 15-30 minutes | 50-100x faster |
| Records/second | 171 | 10,000-20,000 | 60-120x faster |

---

## ✅ Testing & Validation

### Test Query Performance

```sql
-- Check how many records need fixing
SELECT COUNT(*) FROM raw_events
WHERE payload::text ~ '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]';
-- Expected: ~1,267

-- Test optimized query speed
EXPLAIN ANALYZE
SELECT id, payload::text FROM raw_events
WHERE id > 0
  AND payload::text ~ '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]'
ORDER BY id
LIMIT 1000;
-- Should complete in <100ms
```

### Benchmark

```bash
# Dry run with limit to test speed
time uv run cowrie-db sanitize \
    --db "postgresql://..." \
    --batch-size 1000 \
    --limit 10000 \
    --dry-run

# Expected: <1 second for 10K records (vs 60 seconds with old method)
```

---

## 🎯 Recommended Action Plan

### Option 1: SQL-Only Fix (Immediate)
1. Backup problematic records (see SQL above)
2. Run direct PostgreSQL UPDATE with regex_replace
3. Verify with count query
4. **Time**: 5-10 seconds total

### Option 2: Python Implementation (Long-term)
1. Stop current slow sanitization
2. Apply optimized implementation
3. Re-run sanitization with `--use-optimized`
4. **Time**: 15-30 minutes

---

## 📝 Future Enhancements

1. **Periodic Index**: Create partial index for faster pre-filtering
   ```sql
   CREATE INDEX idx_problematic_payloads ON raw_events (id)
   WHERE payload::text ~ '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]';
   ```

2. **Parallel Processing**: Process multiple ID ranges concurrently

3. **Incremental Sanitization**: Track last_processed_id to resume

4. **Monitoring**: Real-time metrics on records/second throughput
