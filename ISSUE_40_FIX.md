# Issue #40 Fix: PostgreSQL NUL Byte Error in Password Enrichment

## Problem Summary

The password enrichment process was failing with multiple related errors:

### Error 1: NUL Bytes in Password Text
```
(psycopg.DataError) PostgreSQL text fields cannot contain NUL (0x00) bytes
[SQL: INSERT INTO password_tracking ...]
[parameters: {'password_text': '\x01\x00', ...}]
```

### Error 2: NUL Bytes in Username
```
(psycopg.DataError) PostgreSQL text fields cannot contain NUL (0x00) bytes
[SQL: INSERT INTO password_session_usage ...]
[parameters: {'username': '\x00 \x00 \x00 \x00<\x00a\x00c\x00t\x00i\x00o\x00n\x00>...', ...}]
```

### Error 3: Username Length Exceeds VARCHAR(256) Limit
```
(psycopg.errors.StringDataRightTruncation) value too long for type character varying(256)
[SQL: INSERT INTO password_session_usage ...]
[parameters: {'username': 'b\'\\x10\\x00\\x03\\x00LIORL...' (1038 characters), ...}]
```

### Error 4: Session State Management
```
sqlalchemy.exc.PendingRollbackError: This Session's transaction has been rolled back due to a previous exception during flush.
```

These occurred when attempting to store passwords and usernames containing binary data (including NUL bytes and excessive length) in the database tables.

## Root Cause

1. **PostgreSQL NUL Byte Limitation**: PostgreSQL TEXT and VARCHAR fields cannot store NUL bytes (0x00), but Cowrie honeypot sessions can capture passwords and usernames containing binary data, including NUL bytes.

2. **VARCHAR Length Constraint**: The `password_session_usage.username` field is defined as `VARCHAR(256)`, but some captured usernames (especially from protocol exploits) can exceed this limit.

3. **Session State Management**: When the initial INSERT failed, the exception was caught and logged, but the SQLAlchemy session was not rolled back, leaving it in an invalid state for subsequent operations.

## Solution

### 1. Text Sanitization (`_sanitize_text_for_postgres`)

Added a comprehensive helper function to sanitize text (passwords, usernames) before storing in the database:

```python
def _sanitize_text_for_postgres(text: str, max_length: int | None = None) -> str:
    """Sanitize text for PostgreSQL storage.

    PostgreSQL TEXT and VARCHAR fields cannot contain NUL (0x00) bytes. This function
    removes NUL bytes and optionally truncates to a maximum length.

    Args:
        text: Raw text string that may contain NUL bytes
        max_length: Optional maximum length to truncate to (e.g., 256 for VARCHAR(256))

    Returns:
        Sanitized text string safe for PostgreSQL storage
    """
    # Replace NUL bytes with escape sequence for visibility
    if '\x00' in text:
        text = text.replace('\x00', '\\x00')
    
    # Truncate if needed
    if max_length is not None and len(text) > max_length:
        # Leave room for ellipsis
        text = text[: max_length - 3] + '...'
    
    return text
```

**Design Decisions**: 
- Replaces NUL bytes with the string `'\\x00'` rather than removing them entirely, preserving information about the data structure for security analysis
- Truncates long strings with ellipsis (`...`) to indicate truncation occurred
- Handles both issues (NUL bytes and length) in a single pass

### 2. Session Rollback on Error

Modified the `_enrich_session` function to properly roll back the database session when password tracking fails:

```python
try:
    _track_password(
        db_session=db_session,
        password=password,
        password_sha256=password_sha256,
        hibp_result=hibp_result,
        session_id=session_summary.session_id,
        username=attempt['username'],
        success=attempt['success'],
        timestamp=attempt['timestamp'],
    )
except Exception as e:
    logger.warning(f"Failed to track password: {e}")
    # Rollback the session to recover from any database errors
    db_session.rollback()
```

This ensures that even if password tracking fails, the enrichment process can continue with subsequent passwords and sessions.

### 3. Integration into Password Tracking

Updated `_track_password` to sanitize both passwords and usernames before creating database records:

**Password Text Sanitization:**
```python
# Create new record with sanitized password text
sanitized_password = _sanitize_text_for_postgres(password)
new_password = PasswordTracking(
    password_hash=password_sha256,
    password_text=sanitized_password,  # Use sanitized version
    breached=hibp_result['breached'],
    breach_prevalence=hibp_result.get('prevalence'),
    last_hibp_check=datetime.now(UTC),
    first_seen=timestamp_dt,
    last_seen=timestamp_dt,
    times_seen=1,
    unique_sessions=1,
)
```

**Username Sanitization:**
```python
# Sanitize username for PostgreSQL (max 256 chars, no NUL bytes)
sanitized_username = _sanitize_text_for_postgres(username, max_length=256)
usage_record = PasswordSessionUsage(
    password_id=password_id,
    session_id=session_id,
    username=sanitized_username,  # Use sanitized version
    success=success,
    timestamp=timestamp_dt,
)
```

## Testing

Created comprehensive unit tests in `tests/unit/test_enrich_passwords_cli.py`:

### Test Coverage

1. **Text Sanitization Tests**:
   - Single NUL byte handling
   - Multiple NUL bytes handling
   - Text without NUL bytes (no-op)
   - Empty text
   - Special characters without NUL bytes
   - **Length truncation to max_length**
   - **Combined NUL bytes and length truncation**
   - **Username sanitization for VARCHAR(256)**

2. **Password Tracking Tests**:
   - Tracking passwords with NUL bytes succeeds
   - Multiple passwords with NUL bytes
   - Updating existing password records with NUL bytes

3. **Binary and UTF-8 Tests**:
   - Binary passwords with various control characters
   - UTF-8 passwords (no corruption)
   - Mixed UTF-8 and NUL bytes

### Test Results

All 14 unit tests pass successfully (3 new tests for length truncation):
```
============================== 14 passed in 8.55s ==============================
```

Existing integration tests continue to pass:
```
tests/integration/test_password_enrichment.py::test_end_to_end_password_enrichment PASSED
tests/integration/test_password_enrichment.py::test_daily_aggregation PASSED
tests/integration/test_password_enrichment.py::test_cache_efficiency PASSED
tests/integration/test_password_enrichment.py::test_force_reenrichment PASSED
tests/integration/test_password_enrichment.py::test_novel_password_tracking PASSED
```

## Files Modified

1. **cowrieprocessor/cli/enrich_passwords.py**:
   - Added `_sanitize_password_text()` function
   - Modified `_track_password()` to use sanitization
   - Added session rollback in `_enrich_session()` error handler

2. **tests/unit/test_enrich_passwords_cli.py** (NEW):
   - 11 comprehensive unit tests
   - Full type annotations
   - Tests for sanitization, tracking, and edge cases

## Impact

### Positive Impacts

1. **Robustness**: The password enrichment process now handles binary passwords gracefully without crashing.
2. **Data Preservation**: Password information is preserved (as escaped text) rather than lost or causing failures.
3. **Resilience**: Session rollback ensures that one bad password doesn't corrupt the entire batch processing.
4. **Maintainability**: Well-tested code with clear documentation.

### Potential Considerations

1. **Password Representation**: Passwords with NUL bytes are now stored with `\\x00` escape sequences. This is a visual representation change but doesn't affect the password hash, which remains accurate for HIBP lookups.

2. **Existing Data**: Any passwords that previously failed to insert will now be successfully tracked. There's no migration needed for existing data.

## Security Considerations

- The sanitization function only affects the stored `password_text` field, not the `password_hash`.
- Password hashes remain unchanged and accurate for HIBP breach checking.
- No sensitive information is logged beyond what was already being logged.
- The escaped representation (`\\x00`) makes binary passwords more visible in reports and debugging.

## Verification Steps

To verify the fix works:

1. Run unit tests: `uv run pytest tests/unit/test_enrich_passwords_cli.py -v`
2. Run integration tests: `uv run pytest tests/integration/test_password_enrichment.py -v`
3. Test with real data containing the problematic password:
   ```bash
   # The password hash from the error: 47dc540c94ceb704a23875c11273e16bb0b8a87aed84de911f2133568115f254
   # Should now process successfully
   ```

## Conclusion

This fix resolves issue #40 by:
1. **Preventing PostgreSQL NUL byte errors** through comprehensive text sanitization
2. **Handling VARCHAR length constraints** by truncating overly long usernames
3. **Ensuring graceful error recovery** through session rollback
4. **Maintaining data integrity and analysis capabilities** by preserving information (escaped NUL bytes, truncation indicators)
5. **Adding comprehensive test coverage** for all edge cases (14 unit tests)

The solution is **backward-compatible** and requires **no database migrations or configuration changes**. Both passwords and usernames are now safely sanitized before storage, handling the full range of binary data that can be captured by Cowrie honeypots.

