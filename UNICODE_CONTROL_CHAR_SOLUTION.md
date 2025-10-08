# Unicode Control Character Handling Solution

## Problem Description

The Cowrie Processor was encountering PostgreSQL JSON processing errors due to Unicode control characters in JSON payloads. The specific error was:

```
(psycopg.errors.UntranslatableCharacter) unsupported Unicode escape sequence
DETAIL:  \u0000 cannot be converted to text.
CONTEXT:  JSON data, line 1: ...e": "Remote SSH version: \u0016\u0003\u0001\u0000...
```

This occurred because PostgreSQL's JSON processing cannot handle certain Unicode control characters (specifically \u0000-\u001F and \u007F-\u009F) in JSON strings.

## Solution Overview

A comprehensive Unicode sanitization solution has been implemented that:

1. **Centralizes Unicode sanitization** in a dedicated utility module
2. **Prevents problematic characters** from entering the database during ingestion
3. **Gracefully handles existing corrupted data** in backfill operations
4. **Maintains data integrity** while ensuring PostgreSQL compatibility

## Implementation Details

### 1. Centralized Unicode Sanitizer (`cowrieprocessor/utils/unicode_sanitizer.py`)

The `UnicodeSanitizer` class provides:

- **Control character removal**: Removes \u0000-\u001F and \u007F-\u009F characters
- **JSON-specific sanitization**: Handles both valid and malformed JSON
- **Field-specific sanitization**: Tailored methods for filenames, URLs, and commands
- **PostgreSQL compatibility checking**: Validates data safety before database operations

Key methods:
- `sanitize_unicode_string()`: Basic control character removal
- `sanitize_json_string()`: JSON-aware sanitization with parsing validation
- `sanitize_filename()`: Filename-specific sanitization with path traversal protection
- `sanitize_url()`: URL-specific sanitization
- `validate_and_sanitize_payload()`: Comprehensive payload validation

### 2. Integration Points Updated

#### Bulk Loader (`cowrieprocessor/loader/bulk.py`)
- **Line-by-line processing**: Sanitizes JSON before parsing
- **Multiline JSON processing**: Handles fragmented JSON with control characters
- **Error handling**: Graceful fallback to DLQ for unparseable data

#### File Processing (`cowrieprocessor/loader/file_processor.py`)
- **Filename sanitization**: Uses centralized sanitizer for consistent handling
- **URL sanitization**: Ensures URLs are safe for database storage

#### DLQ Processing (`cowrieprocessor/loader/dlq_processor.py`)
- **JSON repair strategies**: Enhanced to include Unicode sanitization
- **Event stitching**: Sanitizes control characters during repair attempts

#### Backfill Operations (`cowrieprocessor/cli/cowrie_db.py`)
- **Payload sanitization**: Cleans existing data during backfill operations
- **Error recovery**: Graceful handling of corrupted JSON payloads

#### Main Processing Script (`process_cowrie.py`)
- **JSON line processing**: Sanitizes control characters before parsing

### 3. Security Considerations

The sanitization process:

- **Preserves safe whitespace**: Maintains tabs, newlines, and carriage returns for command data
- **Removes dangerous characters**: Eliminates null bytes, control characters, and other problematic sequences
- **Prevents path traversal**: Removes `../` and `..\\` patterns from filenames
- **Limits data length**: Enforces reasonable limits to prevent DoS attacks

### 4. Performance Impact

- **Minimal overhead**: Regex-based sanitization is efficient
- **Early filtering**: Control characters are removed before expensive operations
- **Caching-friendly**: Sanitization results can be cached for repeated operations

## Usage Examples

### Basic String Sanitization
```python
from cowrieprocessor.utils.unicode_sanitizer import UnicodeSanitizer

# Remove control characters
clean_text = UnicodeSanitizer.sanitize_unicode_string("hello\x00world")
# Result: "helloworld"

# Preserve safe whitespace
clean_command = UnicodeSanitizer.sanitize_command("echo 'hello\x00world'\n")
# Result: "echo 'helloworld'\n" (newline preserved)
```

### JSON Payload Sanitization
```python
# Sanitize JSON string
json_str = '{"message": "hello\\u0000world"}'
clean_json = UnicodeSanitizer.sanitize_json_string(json_str)
parsed = json.loads(clean_json)
# Result: {"message": "helloworld"}

# Validate payload for database
payload = {"data": "test\x01value"}
safe_payload = UnicodeSanitizer.validate_and_sanitize_payload(payload)
# Result: {"data": "testvalue"}
```

### File and URL Sanitization
```python
# Sanitize filename
dirty_filename = "file\x00name.txt"
clean_filename = UnicodeSanitizer.sanitize_filename(dirty_filename)
# Result: "filename.txt"

# Sanitize URL
dirty_url = "https://example.com/path\x16"
clean_url = UnicodeSanitizer.sanitize_url(dirty_url)
# Result: "https://example.com/path"
```

## Testing

Comprehensive test coverage includes:

### Unit Tests (`tests/unit/test_unicode_sanitizer.py`)
- Basic sanitization functionality
- JSON parsing and validation
- Field-specific sanitization (filenames, URLs, commands)
- Edge cases and boundary conditions
- Real-world Cowrie log examples

### Integration Tests (`tests/integration/test_unicode_handling_integration.py`)
- End-to-end data processing workflows
- Bulk loader integration
- DLQ processing integration
- PostgreSQL compatibility validation
- Performance testing with large datasets

## Migration Strategy

### For New Data
- **Automatic sanitization**: All new data is automatically sanitized during ingestion
- **No configuration required**: Sanitization is enabled by default
- **Backward compatible**: Existing code continues to work without changes

### For Existing Data
- **Backfill operations**: Existing corrupted data is sanitized during backfill
- **Gradual migration**: Data is cleaned as it's reprocessed
- **Manual cleanup**: Specific scripts can be run to clean existing data

## Error Handling

The solution provides multiple layers of error handling:

1. **Prevention**: Control characters are removed before database operations
2. **Detection**: Unsafe data is identified and logged
3. **Recovery**: Malformed data is sent to DLQ for repair attempts
4. **Fallback**: Critical operations continue even if some data is lost

## Configuration

No configuration is required - sanitization is enabled by default. However, the sanitization behavior can be customized:

- **Strict mode**: More aggressive control character filtering
- **Custom replacements**: Replace control characters with custom strings
- **Whitespace preservation**: Control which whitespace characters are preserved

## Monitoring and Alerting

The solution includes logging for:

- **Sanitization events**: When control characters are removed
- **Data loss**: When data cannot be sanitized and is discarded
- **Performance metrics**: Processing time and throughput impact

## Future Enhancements

Potential improvements include:

1. **Configurable sanitization rules**: Allow customization of which characters to remove
2. **Data recovery**: Attempt to recover data from sanitized versions
3. **Analytics**: Track patterns in control character usage
4. **Integration with enrichment**: Sanitize data during enrichment processes

## Conclusion

This solution comprehensively addresses the Unicode control character issue by:

- **Preventing the problem**: Sanitizing data before database operations
- **Handling existing issues**: Cleaning corrupted data during backfill
- **Maintaining compatibility**: Ensuring PostgreSQL JSON processing works reliably
- **Preserving functionality**: Keeping all existing features intact

The implementation is robust, well-tested, and ready for production use.

