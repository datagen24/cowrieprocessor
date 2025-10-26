# Bulk Loader Multiline JSON Test Failures Investigation

**Date**: 2025-10-25
**Context**: Week 3 Test Failure Resolution (Day 28)
**Status**: Partial fix applied, remaining issues deferred

## Problem Summary

5 tests in `tests/unit/test_bulk_loader.py` are failing due to multiline/prettified JSON handling:

1. `test_bulk_loader_handles_multiline_json` - Expected 2 events, got 1
2. `test_bulk_loader_rejects_multiline_json_by_default` - Expected 6 events read, got 1
3. `test_bulk_loader_mixed_json_formats` - Expected 2 inserted, got 3
4. `test_bulk_loader_handles_malformed_json` - Expected 0 inserted, got 1
5. `test_bulk_loader_multiline_json_malformed_limit` - Expected 2 events read, got 1

## Root Cause Analysis

### 1. File Type Detection Issue (FIXED ✅)

**Problem**: `FileTypeDetector.detect_file_type()` was only trying to parse individual lines as JSON. For prettified JSON (created with `json.dumps(obj, indent=2)`), individual lines like `"  \"session\": \"multiline123\",\n"` are not valid JSON.

**Example**:
```json
{
  "session": "multiline123",
  "eventid": "cowrie.session.connect",
  "timestamp": "2024-01-01T00:00:00Z",
  "src_ip": "1.2.3.4"
}
```

Line 0: `{\n` - Not valid JSON
Line 1: `  "session": "multiline123",\n` - Not valid JSON
...only when accumulated do they form valid JSON.

**Solution Applied**: Enhanced `file_type_detector.py` (lines 75-96):
- Try parsing entire sample as single JSON object first
- Added pattern detection for JSON structure (braces, colons, quotes)
- Falls back to line-by-line parsing if neither works

**Result**: Files are now correctly identified as `json` type instead of `unknown` or `structured_log`.

### 2. Multiline JSON Parser Logic (INVESTIGATION INCOMPLETE)

**Current Behavior**: The `_iter_multiline_json()` method in `bulk.py` (lines 960-1009) accumulates lines until valid JSON is parsed.

**Test Simulation** (manual run):
```
Line 0-5: Accumulate → Parse SUCCESS (event 1)
Line 6-11: Accumulate → Parse SUCCESS (event 2)
```

This logic should work, but tests still fail with:
- `events_inserted=1` (expected 2)
- `events_quarantined=1`

**Observations**:
- Many "Malformed JSON detected" warnings from `UnicodeSanitizer`
- JSON repair strategies may be interfering with multiline parsing
- Second event might be getting sent to DLQ instead of being parsed

### 3. Configuration Priority

**Code**: `bulk.py` lines 801-810
```python
if self.config.hybrid_json:
    # Use improved hybrid processor
    from .improved_hybrid import ImprovedHybridProcessor
    processor = ImprovedHybridProcessor()
    yield from processor.process_lines(handle)
elif self.config.multiline_json:
    yield from self._iter_multiline_json(handle)
else:
    yield from self._iter_line_by_line(handle)
```

**Priority**: `hybrid_json` > `multiline_json` > line-by-line

Tests use `BulkLoaderConfig(multiline_json=True)`, so `_iter_multiline_json()` should be called.

## What Was Tried

### Attempt 1: Fix FileTypeDetector
✅ **Success** - Now detects multiline JSON files correctly
Commit: `39e53e6` - "fix(file-type-detector): improve multiline JSON detection"

### Attempt 2: Investigate _iter_multiline_json Logic
⏸️ **Deferred** - Logic appears sound but interaction with UnicodeSanitizer unclear

### Attempt 3: Test hybrid_json Mode
❌ **Blocked** - Test harness import issues

## Remaining Issues

1. **Unicode Sanitizer Interference**: The sanitizer may be "fixing" multiline JSON in ways that break parsing
2. **Second Event Lost**: Only first event gets inserted, second goes to quarantine
3. **DLQ Behavior**: Why is the second prettified JSON object being flagged as malformed?

## Relevant Code Locations

- **File Type Detector**: `cowrieprocessor/utils/file_type_detector.py:75-96`
- **Multiline Parser**: `cowrieprocessor/loader/bulk.py:960-1009`
- **Unicode Sanitizer**: `cowrieprocessor/utils/unicode_sanitizer.py:94-109`
- **Test Helper**: `tests/unit/test_bulk_loader.py:116-121` (_write_multiline_events)
- **Improved Hybrid**: `cowrieprocessor/loader/improved_hybrid.py` (alternative approach)

## Recommendations

### Short-term
1. **Option A**: Mark these 5 tests as `@pytest.mark.skip(reason="multiline JSON parsing needs investigation")`
2. **Option B**: Change tests to use `hybrid_json=True` mode instead
3. **Option C**: Investigate UnicodeSanitizer's interaction with multiline JSON

### Long-term
1. Add integration test for end-to-end multiline JSON file processing
2. Refactor JSON parsing to have clearer separation:
   - Detection phase (FileTypeDetector)
   - Parsing phase (line-by-line vs multiline vs hybrid)
   - Sanitization phase (Unicode cleanup)
3. Consider deprecating `multiline_json` in favor of `hybrid_json` mode

## Testing Notes

### Manual Test for Multiline Parsing
```python
import json
from pathlib import Path

events = [
    {'session': 'multiline123', 'eventid': 'cowrie.session.connect', ...},
    {'session': 'multiline123', 'eventid': 'cowrie.command.input', ...},
]

with open('test.json', 'w') as f:
    for event in events:
        f.write(json.dumps(event, indent=2))
        f.write('\n')

# File structure:
# Lines 0-5: First JSON object (prettified)
# Line 6: Blank (just \n from previous write)
# Lines 7-12: Second JSON object (prettified)
```

### Expected vs Actual
- **Expected**: Both events parsed and inserted
- **Actual**: First event inserted, second quarantined
- **Metrics**: `events_read=1, events_inserted=1, events_quarantined=1`

## Decision

**Status**: Investigation paused after FileTypeDetector fix
**Reason**: 5 tests complex, 53 other failures likely faster to fix
**Next Steps**: Move to `test_cowrie_db_cli.py` (14 failures) - likely simpler import/mock issues
