#!/usr/bin/env python3
"""Proof-of-concept: Optimized sanitization with cursor-based pagination.

Performance improvements:
1. Cursor-based pagination (WHERE id > :last_id) instead of OFFSET
2. Pre-filter with WHERE clause (only fetch problematic records)
3. Batch UPDATEs using PostgreSQL CASE statement

Expected speedup: 50-100x faster for large tables
"""

from sqlalchemy import text


def optimized_sanitization_query() -> None:
    """Show the optimized query approach."""
    print("=" * 80)
    print("OPTIMIZED SANITIZATION APPROACH")
    print("=" * 80)
    print()

    print("❌ CURRENT APPROACH (SLOW):")
    print("-" * 80)
    print("""
-- Processes ALL 12.4M records with OFFSET pagination
SELECT id, payload::text
FROM raw_events
ORDER BY id
LIMIT 1000 OFFSET 1372000;  -- Scans 1.37M rows to skip them!

-- Then checks each one in Python
-- Then individual UPDATEs for problematic records
    """)
    print()

    print("✅ OPTIMIZED APPROACH (FAST):")
    print("-" * 80)
    print("""
-- Step 1: Only fetch problematic records with cursor pagination
SELECT id, payload::text
FROM raw_events
WHERE id > :last_processed_id  -- Cursor-based (O(1) seek)
  AND payload::text ~ '\\\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\\\u007[fF]'  -- Pre-filter
ORDER BY id
LIMIT 1000;

-- Step 2: Batch UPDATE using CASE statement
UPDATE raw_events
SET payload = CASE id
    WHEN 123 THEN CAST(:sanitized_123 AS jsonb)
    WHEN 456 THEN CAST(:sanitized_456 AS jsonb)
    ...
    WHEN 999 THEN CAST(:sanitized_999 AS jsonb)
END
WHERE id IN (123, 456, ..., 999);
    """)
    print()

    print("📊 PERFORMANCE COMPARISON:")
    print("-" * 80)
    print(f"{'Metric':<30} {'Current':<20} {'Optimized':<20}")
    print("-" * 80)
    print(f"{'Records scanned per batch':<30} {'12.4M (full table)':<20} {'~1K (filtered)':<20}")
    print(f"{'Pagination method':<30} {'OFFSET (O(n))':<20} {'Cursor (O(1))':<20}")
    print(f"{'UPDATEs per batch':<30} {'~100 individual':<20} {'1 batch UPDATE':<20}")
    print(f"{'Est. time for 12.4M records':<30} {'20+ hours':<20} {'15-30 minutes':<20}")
    print(f"{'Speedup':<30} {'1x (baseline)':<20} {'50-100x faster':<20}")
    print()

    print("🔑 KEY OPTIMIZATIONS:")
    print("-" * 80)
    print("1. WHERE clause filters to ~1,267 problematic records (0.01% of table)")
    print("2. Cursor (id > :last_id) avoids scanning millions of rows")
    print("3. Batch UPDATE reduces roundtrips from 1,267 to ~2 transactions")
    print("4. Index on 'id' makes cursor seeks instant")
    print()

    print("💡 IMPLEMENTATION:")
    print("-" * 80)
    print("""
last_id = 0
while True:
    # Fetch only problematic records after last_id
    batch = conn.execute(text('''
        SELECT id, payload::text
        FROM raw_events
        WHERE id > :last_id
          AND payload::text ~ '\\\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\\\u007[fF]'
        ORDER BY id
        LIMIT 1000
    '''), {"last_id": last_id}).fetchall()

    if not batch:
        break

    # Process batch (sanitize in Python)
    updates = []
    for record in batch:
        sanitized = UnicodeSanitizer.sanitize_json_string(record.payload_text)
        updates.append((record.id, sanitized))

    # Single batch UPDATE
    if updates:
        when_clauses = ' '.join([f"WHEN {id} THEN CAST(:val_{id} AS jsonb)" for id, _ in updates])
        ids = [id for id, _ in updates]
        params = {f"val_{id}": val for id, val in updates}
        params['ids'] = tuple(ids)

        conn.execute(text(f'''
            UPDATE raw_events
            SET payload = CASE id {when_clauses} END
            WHERE id = ANY(:ids)
        '''), params)

    last_id = batch[-1].id  # Update cursor
    """)


if __name__ == "__main__":
    optimized_sanitization_query()
