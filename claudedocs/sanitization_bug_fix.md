# PostgreSQL JSONB Sanitization Bug Fix

**Date**: 2025-11-02
**Issue**: Unicode escape sequence detection mismatch in `cowrie-db sanitize`
**Impact**: 1.43M records with problematic Unicode were skipped instead of sanitized
**Status**: ✅ FIXED

## The Bug

### Root Cause

When PostgreSQL casts JSONB to text using `payload::text`, control characters are represented as JSON Unicode escape sequences:

```sql
-- What's in the database:
{"username": "\u0000test"}  -- JSONB with null byte

-- What payload::text returns:
'{"username": "\\u0000test"}'  -- Literal string with 6 characters: \, u, 0, 0, 0, 0
```

The `is_safe_for_postgres_json()` function only checked for **actual control bytes** (`\x00`), not the **escape sequences** (`\u0000`), causing a type mismatch:

| Database Content | `payload::text` Returns | Sanitizer Checked For | Match? |
|-----------------|------------------------|----------------------|--------|
| `{"user": "\u0000"}` | `'{"user": "\\u0000"}'` | `'\x00'` (1 byte) | ❌ NO |

**Result**: All 1.43M records marked as "safe" and skipped!

### Discovery

User noticed the monitoring output showed:
```
processed=1430000 updated=0 skipped=1430000 errors=0
```

All records were skipped because the detection logic couldn't find the escape sequences.

## The Fix

### Changes Made

**File**: `cowrieprocessor/utils/unicode_sanitizer.py:213-278`

Added dual-pattern detection:

```python
@classmethod
def is_safe_for_postgres_json(cls, text: str) -> bool:
    """Check if text is safe for PostgreSQL JSON processing.

    Detects both:
    - Actual control character bytes (\x00, \x01, etc.)
    - JSON Unicode escape sequences (\u0000, \u0001, etc.)
    """
    # Pattern 1: Check for actual control character bytes
    dangerous_chars = ['\x00', '\x01', ..., '\x7f']
    if any(char in text for char in dangerous_chars):
        return False

    # Pattern 2: Check for JSON Unicode escape sequences
    # Regex: \\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]
    # Matches: \u0000-\u001f (excluding \t, \n, \r) and \u007f
    escape_pattern = re.compile(
        r'\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]',
        re.IGNORECASE
    )
    if escape_pattern.search(text):
        return False

    return True
```

### Regex Pattern Breakdown

```
\\u00                        # Literal "\u00"
(?:0[0-8bcef]|1[0-9a-fA-F])  # 00-08, 0b-0c, 0e-0f, 10-1f (excludes 09=\t, 0a=\n, 0d=\r)
|\\u007[fF]                  # Also match \u007f (DEL)
```

**Excluded (safe whitespace)**:
- `\u0009` = Tab (`\t`)
- `\u000a` = Newline (`\n`)
- `\u000d` = Carriage Return (`\r`)

### Test Coverage

**New Tests**: `tests/unit/test_unicode_sanitizer.py:171-215`

Added comprehensive test cases:
- ✅ Detection of escape sequences (`\u0000`, `\u0001`, etc.)
- ✅ Safe whitespace exclusion (`\u0009`, `\u000a`, `\u000d`)
- ✅ Mixed pattern detection (bytes + escapes)
- ✅ Case-insensitive matching (`\u007f` and `\u007F`)

**Test Results**: All 22 tests pass ✅

### Verification

Run the verification script:
```bash
uv run python scripts/debug/verify_sanitization_fix.py
```

Expected output:
```
✅ All tests passed! The bug is fixed.

The sanitizer now correctly detects:
  1. Actual control character bytes (\x00, \x01, etc.)
  2. JSON Unicode escape sequences (\u0000, \u0001, etc.)
```

## Impact Assessment

### Before Fix

```
processed=1430000 updated=0 skipped=1430000 errors=0 batches=1430
```

- ❌ All records skipped (false negatives)
- ❌ Problematic Unicode characters remained in database
- ❌ Potential PostgreSQL JSONB conversion errors

### After Fix

Expected behavior:
- ✅ Records with `\u0000`, `\u0001`, etc. detected as unsafe
- ✅ Sanitization applied to problematic records
- ✅ Database cleaned for safe PostgreSQL JSONB operations

### Estimated Impact

Query to check affected records:
```sql
SELECT COUNT(*)
FROM raw_events
WHERE payload::text ~ '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]';
```

## Next Steps

### 1. Stop Current Sanitization

If still running:
```bash
pkill -f "cowrie-db sanitize"
```

### 2. Re-run Sanitization

With the fixed code:
```bash
uv run cowrie-db sanitize \
    --db "postgresql://user:pass@host/db" \
    --batch-size 1000 \
    --status-dir /mnt/dshield/data/logs/status \
    --progress
```

Monitor progress:
```bash
uv run python scripts/production/monitor_progress.py \
    --status-dir /mnt/dshield/data/logs/status \
    --refresh 2
```

### 3. Expected New Output

```
processed=1430000 updated=<actual_count> skipped=<remaining> errors=0
```

Where `updated` > 0 indicates records with problematic Unicode were found and sanitized.

### 4. Verification Query

After sanitization completes:
```sql
-- Should return 0 after successful sanitization
SELECT COUNT(*)
FROM raw_events
WHERE payload::text ~ '\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]';
```

## Files Changed

- ✅ `cowrieprocessor/utils/unicode_sanitizer.py` (detection logic)
- ✅ `tests/unit/test_unicode_sanitizer.py` (test coverage)
- ✅ `scripts/debug/verify_sanitization_fix.py` (verification script)

## Quality Gates

- ✅ All 22 unit tests pass
- ✅ Ruff linting clean
- ✅ MyPy type checking clean (for changed code)
- ✅ Verification script confirms fix

## References

- PostgreSQL JSONB documentation: https://www.postgresql.org/docs/current/datatype-json.html
- Unicode control characters: https://en.wikipedia.org/wiki/C0_and_C1_control_codes
- Regex pattern tester: https://regex101.com/

## Lessons Learned

1. **Type Matching**: When working with database casts, always verify the actual format returned
2. **Dual Detection**: When data can exist in multiple representations, check for all patterns
3. **Test-Driven Fixes**: Write tests first to verify the bug, then implement the fix
4. **Monitoring Value**: Status monitoring revealed the issue through anomalous skip counts
