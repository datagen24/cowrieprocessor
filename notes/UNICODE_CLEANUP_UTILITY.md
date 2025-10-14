# Unicode Cleanup Utility for Cowrie Database

## Overview

The Unicode Cleanup Utility provides a comprehensive solution for sanitizing Unicode control characters in existing database records. This utility is designed to handle corrupted JSON data that contains problematic Unicode characters that cause PostgreSQL processing errors.

## Features

- **Batch Processing**: Processes records in configurable batches for optimal performance
- **Dry Run Mode**: Preview changes without making modifications to the database
- **Database Agnostic**: Works with both PostgreSQL and SQLite databases
- **Comprehensive Logging**: Detailed progress reporting and error handling
- **Safe Operation**: Validates sanitized data before database updates
- **CLI Integration**: Easy-to-use command-line interface

## Usage

### Command Line Interface

```bash
# Dry run to see what would be changed
cowrie-db sanitize --dry-run --limit 100

# Sanitize all records in the database
cowrie-db sanitize

# Sanitize with custom batch size and limit
cowrie-db sanitize --batch-size 500 --limit 1000

# Sanitize with progress tracking for monitoring
cowrie-db sanitize --status-dir /path/to/status --ingest-id my-cleanup

# Get help
cowrie-db sanitize --help
```

### Programmatic Usage

```python
from cowrieprocessor.cli.cowrie_db import CowrieDatabase

db = CowrieDatabase("postgresql://user:pass@host/db")

# Dry run
result = db.sanitize_unicode_in_database(dry_run=True, limit=100)
print(f"Would update {result['records_updated']} records")

# Actual sanitization
result = db.sanitize_unicode_in_database(
    batch_size=1000,
    limit=5000,
    dry_run=False
)
print(f"Updated {result['records_updated']} records")
```

## Command Options

| Option | Description | Default |
|--------|-------------|---------|
| `--batch-size` | Number of records to process in each batch | 1000 |
| `--limit` | Maximum number of records to process | None (all) |
| `--dry-run` | Preview changes without making modifications | False |
| `--status-dir` | Directory for status JSON files (for monitoring) | None |
| `--ingest-id` | Status identifier for progress tracking | Auto-generated |

## How It Works

### 1. Data Retrieval
- Queries the `raw_events` table using text-based filtering to avoid triggering PostgreSQL JSON processing
- Processes records in configurable batches for optimal performance

### 2. Unicode Sanitization
- Uses the centralized `UnicodeSanitizer` to detect and remove problematic characters
- Applies both string-level and JSON-aware sanitization
- Validates that sanitized data is safe for PostgreSQL processing

### 3. Database Updates
- Updates records with sanitized JSON payloads
- Uses database-specific conflict resolution (PostgreSQL vs SQLite)
- Maintains data integrity throughout the process

### 4. Progress Reporting
- Logs progress every 10 batches processed
- Provides detailed statistics on processed, updated, and skipped records
- Reports any errors encountered during processing

## Safety Features

### Validation
- **Pre-sanitization**: Checks if records actually need sanitization
- **Post-sanitization**: Validates that sanitized JSON is valid and safe
- **Database Safety**: Ensures sanitized data is compatible with PostgreSQL

### Error Handling
- **Individual Record Errors**: Logs and skips problematic records
- **Batch Errors**: Continues processing remaining batches
- **Graceful Degradation**: Provides detailed error reporting

### Rollback Protection
- **Dry Run Mode**: Preview all changes before execution
- **Batch Processing**: Limited scope of changes per batch
- **Validation**: Multiple validation steps prevent data corruption

## Performance Considerations

### Batch Processing
- Configurable batch sizes (default: 1000 records)
- Memory-efficient processing of large datasets
- Progress logging to monitor long-running operations

### Database Optimization
- Uses efficient text-based queries to avoid JSON processing overhead
- Database-specific optimizations for PostgreSQL and SQLite
- Minimal database connection overhead

### Resource Usage
- Processes records in memory-efficient batches
- Configurable limits to control resource usage
- Progress reporting for long-running operations

## Example Output

### Dry Run
```
Sanitizing Unicode control characters in database records...
✓ Dry run completed: 1000 records analyzed, 150 would be updated, 850 would be skipped, 0 errors
  Records processed: 1000
  Records updated: 150
  Records skipped: 850
  Batches processed: 1
```

### Actual Run
```
Sanitizing Unicode control characters in database records...
✓ Sanitization completed: 1000 records processed, 150 updated, 850 skipped, 0 errors
  Records processed: 1000
  Records updated: 150
  Records skipped: 850
  Batches processed: 1
```

## Error Scenarios

### Common Issues
1. **Invalid JSON**: Records with malformed JSON are skipped
2. **Unicode Issues**: Control characters are removed and validated
3. **Database Errors**: Individual record errors are logged and processing continues

### Error Handling
- All errors are logged with detailed information
- Processing continues despite individual record failures
- Comprehensive error reporting in the final results

## Progress Monitoring Integration

The sanitize command integrates with the Cowrie Processor's monitoring system for real-time progress tracking.

### StatusEmitter Integration

The command uses `StatusEmitter` to write progress information to JSON status files that can be monitored by external tools:

```bash
# Run with progress tracking
cowrie-db sanitize --status-dir /path/to/status --ingest-id cleanup-001

# Monitor progress using the built-in monitor
python monitor_progress.py
```

### Status File Format

The status files contain detailed metrics:

```json
{
  "phase": "sanitization",
  "ingest_id": "cleanup-001",
  "last_updated": "2025-10-06T13:53:42.663001+00:00",
  "metrics": {
    "records_processed": 1000,
    "records_updated": 150,
    "records_skipped": 850,
    "errors": 0,
    "batches_processed": 10,
    "duration_seconds": 45.2,
    "dry_run": false,
    "ingest_id": "cleanup-001"
  },
  "checkpoint": {},
  "dead_letter": {"total": 0}
}
```

### Monitoring with monitor_progress.py

The `monitor_progress.py` script automatically detects and displays sanitization progress:

```
[sanitization] aggregate last_updated=2025-10-06T13:53:42.663790+00:00
  - sanitization ingest=cleanup-001 processed=1000 updated=150 skipped=850
```

## Integration with Existing Workflow

### Backfill Operations
The cleanup utility can be used before or after backfill operations:

```bash
# Clean existing data before backfill
cowrie-db sanitize
cowrie-db backfill

# Or clean after backfill to handle any remaining issues
cowrie-db backfill
cowrie-db sanitize
```

### Maintenance Workflow with Monitoring
```bash
# Regular maintenance with progress tracking
cowrie-db sanitize --dry-run --limit 1000 --status-dir /var/log/status  # Check for issues
cowrie-db sanitize --limit 10000 --status-dir /var/log/status           # Clean recent data
cowrie-db optimize                                                       # Optimize database
```

### Long-Running Operations
For large databases, use monitoring to track progress:

```bash
# Terminal 1: Run sanitization
cowrie-db sanitize --status-dir /var/log/status --ingest-id full-cleanup

# Terminal 2: Monitor progress
python monitor_progress.py
```

## Testing

The utility includes comprehensive test coverage:

- **Unit Tests**: 11 test cases covering all functionality
- **Integration Tests**: End-to-end workflow testing
- **Error Handling**: Various error scenarios and recovery
- **Performance Tests**: Batch processing and resource usage

Run tests with:
```bash
uv run pytest tests/unit/test_unicode_cleanup_utility.py -v
```

## Monitoring and Logging

### Progress Logging
- Logs progress every 10 batches processed
- Detailed statistics on processed, updated, and skipped records
- Error counts and types for monitoring

### Log Levels
- **INFO**: Progress updates and completion messages
- **WARNING**: Skipped records and minor issues
- **ERROR**: Processing errors and failures
- **DEBUG**: Detailed processing information

## Best Practices

### Before Running
1. **Backup**: Always backup your database before running sanitization
2. **Dry Run**: Use `--dry-run` first to preview changes
3. **Test**: Run on a small subset with `--limit` to verify behavior

### During Processing
1. **Monitor**: Watch logs for any errors or issues
2. **Resource Usage**: Monitor database and system resources
3. **Progress**: Use progress logging to track long-running operations

### After Completion
1. **Verify**: Check that the operation completed successfully
2. **Validate**: Verify that database operations work correctly
3. **Optimize**: Consider running database optimization after cleanup

## Troubleshooting

### Common Issues

**Q: The utility hangs during processing**
A: Check for database locks or connection issues. Try reducing batch size.

**Q: Many records are being skipped**
A: This is normal if your data is already clean. Use `--dry-run` to verify.

**Q: Database errors during processing**
A: Check database connectivity and permissions. Ensure the `raw_events` table exists.

**Q: Memory usage is high**
A: Reduce batch size to lower memory usage. The default batch size is optimized for most cases.

### Getting Help

- Check the logs for detailed error messages
- Use `--dry-run` to preview operations
- Start with small limits to test behavior
- Review the test cases for expected behavior patterns

## Conclusion

The Unicode Cleanup Utility provides a robust, safe, and efficient way to handle Unicode control character issues in existing Cowrie database records. With comprehensive error handling, progress reporting, and safety features, it ensures that database cleanup operations are reliable and maintainable.
