# VirusTotal JSON Serialization Fix

## Issue
The VirusTotal enrichment was failing with the following error:
```
VirusTotal request failed for a8460f446be540410004b1a8db4083773fa46f7fe76fa84219c93daa1669f8f2: Object of type WhistleBlowerDict is not JSON serializable
VirusTotal enrichment failed for a8460f446be540410004b1a8db4083773fa46f7fe76fa84219c93daa1669f8f2: Object of type WhistleBlowerDict is not JSON serializable
```

## Root Cause
The vt-py SDK returns some objects (like `WhistleBlowerDict`) that are not JSON serializable. When the VirusTotal handler tried to cache the response using `json.dump()`, it failed because these objects couldn't be converted to JSON.

## Solution
Implemented a comprehensive serialization strategy in `cowrieprocessor/enrichment/virustotal_handler.py`:

### 1. Custom Serialization Function
Added a `serialize_value()` function that handles various object types:

```python
def serialize_value(value):
    """Convert vt-py objects to JSON-serializable format."""
    if hasattr(value, 'to_dict'):
        # If the object has a to_dict method, use it
        return value.to_dict()
    elif isinstance(value, dict):
        # Recursively serialize dictionaries
        return {k: serialize_value(v) for k, v in value.items()}
    elif isinstance(value, list):
        # Recursively serialize lists
        return [serialize_value(item) for item in value]
    elif hasattr(value, '__dict__'):
        # Try to convert object attributes to dict
        try:
            return {k: serialize_value(v) for k, v in value.__dict__.items()}
        except (TypeError, AttributeError):
            # If that fails, convert to string
            return str(value)
    else:
        # For basic types, return as-is
        return value
```

### 2. Enhanced JSON Dumping
Updated `_save_cached_response()` to use `default=str` as a fallback:

```python
def _save_cached_response(self, file_hash: str, response: Dict[str, Any]) -> None:
    """Save response to cache."""
    cache_path = self._get_cache_path(file_hash)
    
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(response, f, indent=2, default=str)
    except (OSError, TypeError, ValueError) as e:
        LOGGER.debug("Failed to save cached VT response for %s: %s", file_hash, e)
        raise
```

### 3. Graceful Cache Failure Handling
Added error handling around caching operations:

```python
# Cache the response (but don't fail if caching fails)
try:
    self._save_cached_response(file_hash, response_data)
except Exception as cache_error:
    LOGGER.debug("Failed to cache VirusTotal response for %s: %s", file_hash, cache_error)
    # Continue execution even if caching fails
```

## Benefits

1. **Robust Serialization**: Handles all types of vt-py objects, including `WhistleBlowerDict`
2. **Fallback Strategy**: Multiple levels of fallback ensure serialization always works
3. **Graceful Degradation**: If caching fails, enrichment continues without interruption
4. **Backward Compatibility**: Existing cached files remain compatible
5. **Comprehensive Coverage**: Handles nested structures and lists

## Testing

Created comprehensive tests in `tests/unit/test_virustotal_serialization.py`:

- `test_serialize_whistleblower_dict()`: Tests handling of WhistleBlowerDict objects
- `test_json_serialization_with_default_str()`: Tests JSON serialization with fallback
- `test_serialize_value_recursive()`: Tests nested structure handling

All tests pass, confirming the fix works correctly.

## Usage

No changes required in existing code. The fix is transparent and automatic:

```python
from enrichment_handlers import EnrichmentService

service = EnrichmentService(
    cache_dir="/path/to/cache",
    vt_api="your-api-key",
    enable_vt_quota_management=True,
)

# This will now work without serialization errors
result = service.enrich_file(file_hash, filename)
```

## Technical Details

### Object Types Handled
- `WhistleBlowerDict` and similar custom dict types
- Objects with `to_dict()` methods
- Objects with `__dict__` attributes
- Nested dictionaries and lists
- Basic Python types (str, int, float, bool, None)

### Serialization Strategy
1. **Primary**: Use `to_dict()` if available
2. **Secondary**: Recursively serialize dicts and lists
3. **Tertiary**: Convert object attributes to dict
4. **Fallback**: Convert to string representation
5. **Final**: Use `default=str` in `json.dump()`

### Cache Format
- Files are saved as `vt_{hash}.json`
- Pretty-printed with 2-space indentation
- UTF-8 encoding
- All vt-py objects converted to standard Python types

## Monitoring

The fix includes debug logging for cache failures:
```
DEBUG: Failed to cache VirusTotal response for {hash}: {error}
```

This allows monitoring of any serialization issues without breaking the enrichment process.

## Future Considerations

1. **Performance**: The recursive serialization adds some overhead but ensures compatibility
2. **Memory**: Converting large objects to dicts may use more memory temporarily
3. **Cache Size**: Serialized objects may be larger than original objects
4. **Compatibility**: Future vt-py updates may introduce new object types

## Conclusion

This fix resolves the JSON serialization error while maintaining full functionality. The VirusTotal enrichment will now work reliably with all types of objects returned by the vt-py SDK, including `WhistleBlowerDict` and any future object types.
