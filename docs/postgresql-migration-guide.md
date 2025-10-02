# PostgreSQL Migration Guide

This guide provides comprehensive instructions for migrating Cowrie Processor from SQLite to PostgreSQL, including handling data quality issues and production considerations.

## Overview

The PostgreSQL migration implementation provides:
- **Optional PostgreSQL Support**: PostgreSQL drivers are optional extras, maintaining SQLite compatibility
- **Cross-Backend Compatibility**: All components work with both SQLite and PostgreSQL
- **Data Quality Handling**: Robust migration tools handle malformed JSON and other data issues
- **Production-Ready**: Comprehensive testing and validation tools

## Installation

### Default Installation (SQLite)
```bash
# Using pip
pip install cowrieprocessor

# Using uv
uv add cowrieprocessor
```

### PostgreSQL Installation
```bash
# Using pip
pip install cowrieprocessor[postgres]

# Using uv
uv add cowrieprocessor[postgres]
```

## Configuration

### Database URLs

#### SQLite
```toml
# sensors.toml
[global]
db = "sqlite:///path/to/cowrie.db"
```

#### PostgreSQL
```toml
# sensors.toml
[global]
db = "postgresql://user:password@host:port/database"
```

### Environment Variables
```bash
# PostgreSQL connection
export POSTGRES_URL="postgresql://user:password@host:port/database"

# Or use individual components
export POSTGRES_HOST="localhost"
export POSTGRES_PORT="5432"
export POSTGRES_DB="cowrie"
export POSTGRES_USER="cowrie_user"
export POSTGRES_PASSWORD="secure_password"
```

## Migration Process

### 1. Pre-Migration Analysis

Before migrating, analyze your SQLite database for data quality issues:

```bash
# Analyze data quality
uv run python robust_migration.py --sqlite-url "sqlite:///path/to/cowrie.db" --postgres-url "postgresql://user:pass@host/db" --batch-size 1000 --output analysis_results.json
```

This will identify:
- Malformed JSON payloads
- Data integrity issues
- Migration complexity estimates

### 2. Schema Migration

The migration system automatically handles schema differences:

```python
from cowrieprocessor.db.engine import create_engine_from_settings, DatabaseSettings
from cowrieprocessor.db.migrations import apply_migrations

# Apply migrations to PostgreSQL
settings = DatabaseSettings(url="postgresql://user:pass@host/db")
engine = create_engine_from_settings(settings)
apply_migrations(engine)
```

### 3. Data Migration

#### Production Migration Script

For production migrations with large datasets:

```bash
# Production migration with error handling
uv run python production_migration.py \
  --sqlite-url "sqlite:///path/to/cowrie.db" \
  --postgres-url "postgresql://user:pass@host/db" \
  --batch-size 1000 \
  --output migration_results.json
```

#### Memory-Efficient Migration

For very large databases:

```bash
# Memory-efficient migration
uv run python test_memory_efficient_migration.py \
  --sqlite-url "sqlite:///path/to/cowrie.db" \
  --postgres-url "postgresql://user:pass@host/db" \
  --batch-size 500 \
  --output migration_results.json
```

### 4. Data Quality Issues

#### Common Issues and Solutions

**Malformed JSON Payloads**
- **Issue**: SQLite accepts malformed JSON that PostgreSQL rejects
- **Solution**: Migration scripts automatically clean and validate JSON
- **Example**: `{"malformed": "\\"key\\": \\"value\\","}` → `{"key": "value", "_migration_note": "cleaned_from_malformed_json"}`

**Transaction Failures**
- **Issue**: PostgreSQL aborts entire transactions on JSON errors
- **Solution**: Use smaller batch sizes and robust error handling
- **Recommendation**: Start with batch size 500-1000

**Memory Issues**
- **Issue**: Large datasets can cause memory exhaustion
- **Solution**: Use memory-efficient migration with streaming
- **Recommendation**: Process in batches of 500-1000 records

#### Data Cleaning Examples

```python
# Before migration - malformed JSON
payload = '{"malformed": "\\"src_ip\\": \\"192.168.1.1\\","}'

# After migration - cleaned JSON
payload = '{"src_ip": "192.168.1.1", "_migration_note": "cleaned_from_malformed_json"}'
```

### 5. Validation

After migration, validate data integrity:

```bash
# Validate migration results
uv run python test_sqlite_to_postgres_migration.py \
  --sqlite-url "sqlite:///path/to/cowrie.db" \
  --postgres-url "postgresql://user:pass@host/db" \
  --output validation_results.json
```

## Production Considerations

### Performance

#### PostgreSQL Optimization
```sql
-- Create indexes for better performance
CREATE INDEX CONCURRENTLY idx_raw_events_session_id ON raw_events(session_id);
CREATE INDEX CONCURRENTLY idx_raw_events_ingest_at ON raw_events(ingest_at);
CREATE INDEX CONCURRENTLY idx_session_summaries_matcher ON session_summaries(matcher);

-- Analyze tables for query optimization
ANALYZE raw_events;
ANALYZE session_summaries;
```

#### Connection Pooling
```python
# Configure connection pooling
settings = DatabaseSettings(
    url="postgresql://user:pass@host/db",
    pool_size=20,
    pool_timeout=30
)
```

### Monitoring

#### Health Checks
```bash
# Check database health
uv run python -m cowrieprocessor.cli.health --db-url "postgresql://user:pass@host/db"
```

#### Performance Monitoring
```bash
# Monitor database performance
uv run python -m cowrieprocessor.cli.cowrie_db validate-schema --db-url "postgresql://user:pass@host/db"
```

### Backup and Recovery

#### PostgreSQL Backup
```bash
# Create backup
pg_dump -h host -U user -d database > backup.sql

# Restore backup
psql -h host -U user -d database < backup.sql
```

#### Automated Backups
```bash
# Using cowrie_db CLI
uv run python -m cowrieprocessor.cli.cowrie_db create-backup --db-url "postgresql://user:pass@host/db" --backup-path "backup_$(date +%Y%m%d).sql"
```

## Troubleshooting

### Common Issues

#### Driver Not Found
```
Error: PostgreSQL driver not found. Install with: pip install cowrieprocessor[postgres]
```
**Solution**: Install PostgreSQL extras: `pip install cowrieprocessor[postgres]`

#### Connection Errors
```
Error: connection to server at "host" (port), user "user", database "db" failed
```
**Solution**: Check connection parameters and network connectivity

#### JSON Validation Errors
```
Error: invalid input syntax for type json
```
**Solution**: Use robust migration script that handles malformed JSON

#### Memory Issues
```
Error: MemoryError during migration
```
**Solution**: Reduce batch size or use memory-efficient migration

### Debugging

#### Enable Debug Logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

#### Check Migration Status
```bash
# Check schema version
uv run python -c "
from cowrieprocessor.db.engine import create_engine_from_settings, DatabaseSettings
from sqlalchemy import text
settings = DatabaseSettings(url='postgresql://user:pass@host/db')
engine = create_engine_from_settings(settings)
with engine.connect() as conn:
    result = conn.execute(text('SELECT value FROM schema_state WHERE key = \\'schema_version\\''))
    print(f'Schema version: {result.fetchone()[0]}')
"
```

## Testing

### Compatibility Testing
```bash
# Run full compatibility test suite
uv run python test_postgresql_compatibility.py \
  --postgres-url "postgresql://user:pass@host/db" \
  --sqlite-url "sqlite:///path/to/cowrie.db" \
  --output compatibility_results.json
```

### Migration Testing
```bash
# Test migration with sample data
uv run python test_sqlite_to_postgres_migration.py \
  --sqlite-url "sqlite:///path/to/cowrie.db" \
  --postgres-url "postgresql://user:pass@host/db" \
  --output migration_test_results.json
```

## Best Practices

### Migration Planning
1. **Analyze First**: Always run pre-migration analysis
2. **Test Environment**: Test migration in non-production environment
3. **Backup**: Create full backup before migration
4. **Monitor**: Monitor migration progress and performance
5. **Validate**: Validate data integrity after migration

### Performance Optimization
1. **Indexes**: Create appropriate indexes for your query patterns
2. **Batch Size**: Use optimal batch sizes (500-1000 for most cases)
3. **Connection Pooling**: Configure appropriate connection pool sizes
4. **Monitoring**: Set up performance monitoring

### Data Quality
1. **Clean Data**: Address data quality issues before migration
2. **Validate**: Validate JSON payloads and data integrity
3. **Document**: Document any data cleaning or transformation steps
4. **Monitor**: Monitor for data quality issues post-migration

## Migration Scripts Reference

### Available Scripts

1. **`robust_migration.py`**: Comprehensive migration with data quality handling
2. **`production_migration.py`**: Production-ready migration with error handling
3. **`test_memory_efficient_migration.py`**: Memory-efficient migration for large datasets
4. **`test_postgresql_compatibility.py`**: Compatibility testing suite
5. **`test_sqlite_to_postgres_migration.py`**: Migration testing and validation

### Script Parameters

Common parameters for all migration scripts:
- `--sqlite-url`: SQLite database URL
- `--postgres-url`: PostgreSQL database URL
- `--batch-size`: Batch size for data processing (default: 1000)
- `--output`: Output file for results (JSON format)
- `--sensors-file`: Path to sensors.toml configuration file

## Support

For issues or questions:
1. Check this documentation
2. Review migration script output logs
3. Test with smaller datasets first
4. Contact the development team with specific error messages and logs

## Conclusion

The PostgreSQL migration provides a robust, production-ready solution for scaling Cowrie Processor. The migration tools handle data quality issues automatically, and the comprehensive testing suite ensures compatibility and reliability.

Key benefits:
- **Scalability**: PostgreSQL handles larger datasets and concurrent users
- **Reliability**: ACID compliance and better data integrity
- **Performance**: Better query optimization and indexing
- **Compatibility**: Seamless migration from SQLite with data quality handling


