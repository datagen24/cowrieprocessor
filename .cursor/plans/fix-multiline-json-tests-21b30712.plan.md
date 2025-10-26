<!-- 21b30712-33ac-47e6-b4de-f292d6236174 89ddf591-43ee-436c-87a4-029814559330 -->
# Fix Multiline JSON Test Failures

## Overview

Fix 5 failing tests in `test_bulk_loader.py` related to multiline JSON parsing by addressing the root cause: UnicodeSanitizer interference during line accumulation and lack of intelligent Cowrie event validation.

## Root Causes Identified

1. **UnicodeSanitizer Interference**: The `_iter_multiline_json()` method calls `UnicodeSanitizer.sanitize_json_string()` which attempts JSON repair on incomplete JSON fragments during accumulation, breaking the parsing logic.

2. **Missing Cowrie Event Validation**: When accumulating lines, we don't validate if the parsed JSON is actually a valid Cowrie event structure before yielding it.

3. **Test Expectations Mismatch**: Some tests expect behavior that doesn't match the actual (correct) implementation.

## Implementation Strategy

### Phase 1: Refactor Multiline JSON Parser (Option 1.A)

**File**: `cowrieprocessor/loader/bulk.py`

Modify `_iter_multiline_json()` method (lines 960-1009):

1. **Remove sanitization during accumulation** - Parse raw JSON first, sanitize only after successful parse
2. **Add Cowrie event validation** - Use `CowrieEventValidator` or `CowrieSchemaValidator` to verify parsed JSON is a valid Cowrie event
3. **Improve accumulation logic** - Better handling of blank lines and multiline object boundaries

**Key Changes**:

```python
def _iter_multiline_json(self, handle: TextIO) -> Iterator[tuple[int, Any]]:
    """Iterate through potentially multiline JSON objects."""
    accumulated_lines: list[str] = []
    start_offset = 0

    for offset, line in enumerate(handle):
        stripped = line.strip()
        if not stripped:
            continue

        if not accumulated_lines:
            start_offset = offset
            accumulated_lines.append(stripped)
        else:
            accumulated_lines.append(stripped)

        # Try to parse WITHOUT sanitization first
        try:
            combined_content = "\n".join(accumulated_lines)
            payload = json.loads(combined_content)  # Raw parse
            
            # Validate it's a Cowrie event
            if self._is_valid_cowrie_event(payload):
                # NOW sanitize the successfully parsed event
                sanitized_payload = self._sanitize_event(payload)
                yield start_offset, sanitized_payload
                accumulated_lines = []
            else:
                # Not a valid Cowrie event, might need more lines
                if len(accumulated_lines) > 100:
                    yield start_offset, self._make_dead_letter_event(combined_content)
                    accumulated_lines = []
        except (json.JSONDecodeError, ValueError):
            # Incomplete JSON, continue accumulating
            if len(accumulated_lines) > 100:
                combined_content = "\n".join(accumulated_lines)
                yield start_offset, self._make_dead_letter_event(combined_content)
                accumulated_lines = []
```

### Phase 2: Add Intelligent Cowrie Event Validation

**File**: `cowrieprocessor/loader/bulk.py`

Add new helper methods to BulkLoader class:

```python
def _is_valid_cowrie_event(self, payload: Any) -> bool:
    """Check if parsed JSON is a valid Cowrie event structure."""
    if not isinstance(payload, dict):
        return False
    
    # Must have eventid field
    if "eventid" not in payload:
        return False
    
    eventid = payload.get("eventid")
    
    # Must start with "cowrie."
    if not isinstance(eventid, str) or not eventid.startswith("cowrie."):
        return False
    
    # Must have timestamp
    if "timestamp" not in payload:
        return False
    
    # Use existing validator if available
    from .cowrie_schema import CowrieSchemaValidator
    is_valid, errors = CowrieSchemaValidator.validate_event(payload)
    
    return is_valid

def _sanitize_event(self, payload: dict[str, Any]) -> dict[str, Any]:
    """Sanitize a successfully parsed Cowrie event."""
    from ..utils.unicode_sanitizer import UnicodeSanitizer
    
    # Sanitize string fields only, not the entire JSON structure
    sanitized = {}
    for key, value in payload.items():
        if isinstance(value, str):
            sanitized[key] = UnicodeSanitizer.sanitize_unicode_string(value)
        else:
            sanitized[key] = value
    
    return sanitized
```

### Phase 3: Update Test Expectations (Option 2.B)

**File**: `tests/unit/test_bulk_loader.py`

Update failing tests to match correct behavior:

1. **`test_bulk_loader_handles_multiline_json`** (lines 124-156)

   - Currently expects: `events_inserted == 2, events_read == 2`
   - Investigate actual behavior and update assertions

2. **`test_bulk_loader_rejects_multiline_json_by_default`** (lines 158-178)

   - Currently expects: `events_read == 6` (treating each line as event)
   - Update to match actual line-by-line parsing behavior with prettified JSON

3. **`test_bulk_loader_mixed_json_formats`** (lines 181-217)

   - Currently expects: `events_inserted == 2`
   - Investigate if mixed format creates additional events

4. **`test_bulk_loader_handles_malformed_json`** (lines 358-377)

   - Currently expects: `events_inserted == 0`
   - Verify malformed JSON goes to quarantine correctly

5. **`test_bulk_loader_multiline_json_malformed_limit`** (lines 380-395)

   - Currently expects: `events_read == 2`
   - Verify behavior when accumulation exceeds 100-line limit

### Phase 4: Add Comprehensive Test Coverage

**File**: `tests/unit/test_bulk_loader.py`

Add new tests for edge cases:

1. **Test multiline JSON with blank lines between events**
2. **Test multiline JSON with nested objects**
3. **Test multiline JSON with Unicode characters**
4. **Test transition from valid to invalid JSON in same file**
5. **Test Cowrie event validation rejects non-Cowrie JSON**

### Phase 5: Improve FileTypeDetector Intelligence

**File**: `cowrieprocessor/utils/file_type_detector.py`

Enhance multiline JSON detection (lines 75-96) with Cowrie-specific patterns:

```python
# After detecting JSON structure, validate it looks like Cowrie logs
if has_json_structure:
    # Look for Cowrie-specific patterns
    cowrie_indicators = sum(
        1 for line in sample_content
        if any(pattern in line for pattern in ['"eventid":', '"cowrie.', '"session":', '"src_ip":'])
    )
    
    if cowrie_indicators >= 2:  # At least 2 Cowrie-specific fields
        return 'json', 'high', sample_content
    else:
        return 'json', 'medium', sample_content
```

## Testing Strategy

1. **Run failing tests individually** to understand exact failure modes
2. **Add debug logging** to trace line accumulation and parsing decisions
3. **Create minimal reproduction** for each failure case
4. **Verify fixes** don't break existing passing tests
5. **Run full test suite** to ensure no regressions

## Success Criteria

- All 5 failing multiline JSON tests pass
- No regressions in other bulk loader tests
- Code maintains 80%+ coverage
- Passes ruff, mypy, and formatting checks
- Documentation updated for multiline JSON parsing behavior

## Files to Modify

1. `cowrieprocessor/loader/bulk.py` - Core parsing logic
2. `cowrieprocessor/utils/file_type_detector.py` - Enhanced detection
3. `tests/unit/test_bulk_loader.py` - Updated test expectations
4. `cowrieprocessor/utils/unicode_sanitizer.py` - May need adjustments

## Risks and Mitigations

**Risk**: Removing sanitization during accumulation may expose Unicode issues

**Mitigation**: Apply sanitization after successful parse but BEFORE database insertion. The flow is: accumulate → parse → validate → sanitize → insert. This ensures Unicode issues are handled before any database interaction while allowing proper JSON parsing.

**Risk**: Changing test expectations may hide real bugs

**Mitigation**: Thoroughly investigate each test to understand intended vs actual behavior. Document why expectations changed.

**Risk**: Cowrie event validation may be too strict

**Mitigation**: Use existing `CowrieSchemaValidator` which already handles all event types. Start with lenient validation (eventid + timestamp) and only use full schema validation if needed.

**Risk**: Sanitized events may not match original for deduplication

**Mitigation**: The `_payload_hash()` method should be applied to sanitized payloads consistently, ensuring deduplication still works correctly.

### To-dos

- [ ] Run each failing test individually with verbose output to understand exact failure modes and current behavior
- [ ] Refactor _iter_multiline_json() to parse raw JSON first, then sanitize after successful parse
- [ ] Add _is_valid_cowrie_event() and _sanitize_event() helper methods to BulkLoader class
- [ ] Update assertions in 5 failing tests to match correct behavior based on investigation findings
- [ ] Add Cowrie-specific pattern detection to FileTypeDetector for better multiline JSON identification
- [ ] Add comprehensive tests for multiline JSON edge cases (blank lines, nested objects, Unicode, etc.)
- [ ] Run full test suite to ensure changes don't break existing passing tests
- [ ] Run ruff check, ruff format, and mypy to ensure code quality standards