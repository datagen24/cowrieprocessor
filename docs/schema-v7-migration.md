# Schema Version 7 - Enhanced DLQ Processing Migration

## Overview

Schema version 7 introduces comprehensive enhancements to the Dead Letter Queue (DLQ) processing system, adding production-ready security, audit, and operational features. This migration is **PostgreSQL-only** and will be skipped for SQLite databases.

## 🚀 **Migration Features**

### **Security & Audit Enhancements**
- **Payload Checksums**: SHA-256 verification for data integrity
- **Retry Count Tracking**: Monitor persistent failure patterns
- **Error History**: Complete forensic audit trail
- **Idempotency Keys**: Safe reprocessing with unique identifiers

### **Operational Features**
- **Processing Locks**: Prevent concurrent processing conflicts
- **Priority Levels**: 1=Critical, 2=High, 3=Medium, 4=Low, 5=Normal
- **Classification**: Mark events as malicious, corrupted, or format errors
- **Resolution Tracking**: Track how events were resolved

### **Performance Optimizations**
- **Enhanced Indexes**: Optimized for common query patterns
- **Monitoring Views**: Real-time health statistics
- **Processing Metrics**: Performance tracking and analysis
- **Circuit Breaker State**: Failure protection and recovery

## 📊 **Schema Changes**

### **Enhanced Dead Letter Events Table**
```sql
-- New columns added to dead_letter_events
ALTER TABLE dead_letter_events ADD COLUMN payload_checksum VARCHAR(64);
ALTER TABLE dead_letter_events ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE dead_letter_events ADD COLUMN error_history JSONB;
ALTER TABLE dead_letter_events ADD COLUMN processing_attempts JSONB;
ALTER TABLE dead_letter_events ADD COLUMN resolution_method VARCHAR(64);
ALTER TABLE dead_letter_events ADD COLUMN idempotency_key VARCHAR(128);
ALTER TABLE dead_letter_events ADD COLUMN processing_lock UUID;
ALTER TABLE dead_letter_events ADD COLUMN lock_expires_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE dead_letter_events ADD COLUMN priority INTEGER NOT NULL DEFAULT 5;
ALTER TABLE dead_letter_events ADD COLUMN classification VARCHAR(32);
ALTER TABLE dead_letter_events ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
ALTER TABLE dead_letter_events ADD COLUMN last_processed_at TIMESTAMP WITH TIME ZONE;
```

### **New Tables**

#### **Processing Metrics Table**
```sql
CREATE TABLE dlq_processing_metrics (
    id SERIAL PRIMARY KEY,
    processing_session_id VARCHAR(64) NOT NULL,
    processing_method VARCHAR(32) NOT NULL,
    batch_size INTEGER NOT NULL,
    processed_count INTEGER NOT NULL,
    repaired_count INTEGER NOT NULL,
    failed_count INTEGER NOT NULL,
    skipped_count INTEGER NOT NULL,
    processing_duration_ms INTEGER NOT NULL,
    avg_processing_time_ms INTEGER,
    peak_memory_mb INTEGER,
    circuit_breaker_triggered BOOLEAN NOT NULL DEFAULT FALSE,
    rate_limit_hits INTEGER NOT NULL DEFAULT 0,
    lock_timeout_count INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE NOT NULL
);
```

#### **Circuit Breaker State Table**
```sql
CREATE TABLE dlq_circuit_breaker_state (
    id SERIAL PRIMARY KEY,
    breaker_name VARCHAR(64) NOT NULL UNIQUE,
    state VARCHAR(16) NOT NULL,
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_failure_time TIMESTAMP WITH TIME ZONE,
    next_attempt_time TIMESTAMP WITH TIME ZONE,
    failure_threshold INTEGER NOT NULL DEFAULT 5,
    timeout_seconds INTEGER NOT NULL DEFAULT 60,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
```

### **New Indexes**
- `ix_dead_letter_events_payload_checksum` - Checksum lookup
- `ix_dead_letter_events_retry_count` - Retry count queries
- `ix_dead_letter_events_idempotency_key` - Idempotency key lookup
- `ix_dead_letter_events_processing_lock` - Lock management
- `ix_dead_letter_events_lock_expires` - Lock expiration queries
- `ix_dead_letter_events_classification` - Classification filtering
- `ix_dead_letter_events_resolved_created` - Resolved event queries
- `ix_dead_letter_events_priority_resolved` - Priority-based processing

### **New Constraints**
- `ck_retry_count_positive` - Ensure retry count >= 0
- `ck_priority_range` - Ensure priority between 1 and 10
- `uq_idempotency_key` - Unique idempotency keys

### **Monitoring View**
```sql
CREATE VIEW dlq_health AS
SELECT 
    COUNT(*) FILTER (WHERE NOT resolved) as pending_events,
    COUNT(*) FILTER (WHERE resolved) as processed_events,
    AVG(EXTRACT(EPOCH FROM (resolved_at - created_at))) as avg_resolution_time_seconds,
    MAX(created_at) FILTER (WHERE NOT resolved) as oldest_unresolved_event,
    COUNT(*) FILTER (WHERE retry_count > 5) as high_retry_events,
    COUNT(*) FILTER (WHERE processing_lock IS NOT NULL AND lock_expires_at > NOW()) as locked_events,
    COUNT(*) FILTER (WHERE classification = 'malicious') as malicious_events,
    COUNT(*) FILTER (WHERE priority <= 3) as high_priority_events
FROM dead_letter_events;
```

## 🔧 **Migration Process**

### **Automatic Migration**
The migration runs automatically when using the `cowrie-db` tool:

```bash
# Check current schema version
cowrie-db check

# Run migration to latest version
cowrie-db migrate

# Dry run to see what would be done
cowrie-db migrate --dry-run
```

### **Migration Steps**
1. **Add Enhanced Columns**: Add all new columns to `dead_letter_events`
2. **Create Indexes**: Add performance-optimized indexes
3. **Add Constraints**: Enforce data integrity rules
4. **Create Tables**: Add metrics and circuit breaker tables
5. **Create Views**: Add health monitoring view
6. **Create Functions**: Add timestamp update function
7. **Create Triggers**: Add automatic timestamp updates
8. **Populate Data**: Generate checksums and idempotency keys
9. **Update Schema Version**: Set version to 7

### **Data Population**
- **Payload Checksums**: SHA-256 hash of existing payloads
- **Idempotency Keys**: Deterministic keys based on source + offset + checksum
- **Default Values**: Priority=5, retry_count=0 for existing records

## 🎯 **Usage After Migration**

### **Enhanced DLQ Processing**
```bash
# Create enhanced stored procedures
uv run python -m cowrieprocessor.loader.dlq_enhanced_cli create

# Process with priority filtering
uv run python -m cowrieprocessor.loader.dlq_enhanced_cli process --priority 3

# Monitor processing health
uv run python -m cowrieprocessor.loader.dlq_enhanced_cli health

# Analyze failure patterns
uv run python -m cowrieprocessor.loader.dlq_enhanced_cli analyze
```

### **Health Monitoring**
```sql
-- Check DLQ health
SELECT * FROM dlq_health;

-- Get processing metrics
SELECT * FROM dlq_processing_metrics 
ORDER BY started_at DESC 
LIMIT 10;

-- Check circuit breaker state
SELECT * FROM dlq_circuit_breaker_state;
```

## ⚠️ **Important Notes**

### **PostgreSQL Only**
- This migration is **PostgreSQL-only**
- SQLite databases will skip this migration
- Enhanced features require PostgreSQL

### **Backward Compatibility**
- Existing DLQ processing continues to work
- New features are additive, not breaking
- Old CLI tools remain functional

### **Performance Impact**
- Migration adds indexes (improves query performance)
- New columns have minimal storage overhead
- Triggers add minimal processing overhead

## 🔍 **Verification**

### **Check Migration Success**
```bash
# Verify schema version
cowrie-db check

# Should show: ✓ Database schema is current (v7)
```

### **Verify New Features**
```sql
-- Check new columns exist
SELECT column_name FROM information_schema.columns 
WHERE table_name = 'dead_letter_events' 
AND column_name IN ('payload_checksum', 'retry_count', 'priority');

-- Check new tables exist
SELECT table_name FROM information_schema.tables 
WHERE table_name IN ('dlq_processing_metrics', 'dlq_circuit_breaker_state');

-- Check health view works
SELECT * FROM dlq_health;
```

## 🚀 **Next Steps**

After successful migration to v7:

1. **Deploy Enhanced CLI**: Use `dlq_enhanced_cli` for production processing
2. **Create Stored Procedures**: Run `dlq_enhanced_cli create`
3. **Configure Monitoring**: Set up alerts on `dlq_health` view
4. **Test Processing**: Run test batches with enhanced features
5. **Production Deployment**: Deploy enhanced processing to production

## 📋 **Migration Checklist**

- [ ] Backup database before migration
- [ ] Run migration: `cowrie-db migrate`
- [ ] Verify schema version: `cowrie-db check`
- [ ] Test enhanced CLI tools
- [ ] Create stored procedures
- [ ] Verify health monitoring
- [ ] Test processing workflows
- [ ] Deploy to production

The enhanced DLQ processing system is now ready for production deployment with comprehensive security, audit, and operational features! 🎉
