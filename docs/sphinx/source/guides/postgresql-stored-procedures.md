# PostgreSQL Stored Procedures for DLQ Processing

## Overview

This document outlines the implementation of PostgreSQL stored procedures for high-performance Dead Letter Queue (DLQ) processing. This approach eliminates the need to pull records to the application layer, providing significant performance improvements and reduced network overhead.

## 🎯 **Your Questions - Comprehensive Answers**

### **1. How do we track if we have reprocessed something?**

**✅ CURRENT IMPLEMENTATION:**
- **DLQ Model Fields**: `DeadLetterEvent` has `resolved` (Boolean) and `resolved_at` (DateTime)
- **Processing Logic**: Events are marked as `resolved = True` when successfully processed
- **Query Filter**: Only processes `resolved = False` events

**🚀 STORED PROCEDURE ENHANCEMENT:**
```sql
-- Mark DLQ event as resolved after successful processing
UPDATE dead_letter_events 
SET resolved = TRUE, resolved_at = NOW()
WHERE id = dlq_record.id;
```

### **2. Are we removing it from the DLQ?**

**❌ NO - We're NOT removing DLQ records**
- **Current Behavior**: DLQ events are marked as `resolved = True` but remain in the table
- **Retention Policy**: Resolved events stay for audit/history purposes
- **Cleanup Option**: Optional cleanup procedure removes old resolved events

**🚀 STORED PROCEDURE CLEANUP:**
```sql
-- Optional cleanup of old resolved events
CREATE OR REPLACE FUNCTION cleanup_resolved_dlq_events(
    p_older_than_days INTEGER DEFAULT 30
)
RETURNS INTEGER
```

### **3. Did we add a field to the DLQ record to track it being processed?**

**✅ YES - Already exists in schema:**
- `resolved` (Boolean) - tracks processing status
- `resolved_at` (DateTime) - tracks when it was processed
- These fields were already in the `DeadLetterEvent` model

### **4. Would it be useful to add as a stored procedure in PostgreSQL?**

**🎯 ABSOLUTELY YES!** This provides massive benefits:

## 🚀 **Stored Procedure Benefits**

### **Performance Improvements**
- **No Network Overhead**: Processing happens entirely in the database
- **Batch Processing**: Process thousands of events in a single transaction
- **Reduced Memory Usage**: No need to load records into application memory
- **Faster Execution**: Database-optimized JSON operations

### **Operational Benefits**
- **Atomic Operations**: All-or-nothing processing with rollback on failure
- **Concurrent Processing**: Multiple workers can process different batches safely
- **Audit Trail**: Complete history of processing attempts
- **Resource Efficiency**: Minimal application server resources required

### **Scalability Benefits**
- **Horizontal Scaling**: Can run on multiple database connections
- **Load Distribution**: Database handles the heavy lifting
- **Reduced Bottlenecks**: No application server memory/CPU limits

## 📊 **Implementation Details**

### **Core Stored Procedures**

#### **1. Main Processing Function**
```sql
CREATE OR REPLACE FUNCTION process_dlq_events(
    p_limit INTEGER DEFAULT NULL,
    p_reason_filter TEXT DEFAULT NULL
)
RETURNS TABLE(
    processed_count INTEGER,
    repaired_count INTEGER,
    failed_count INTEGER,
    skipped_count INTEGER
)
```

#### **2. JSON Repair Function**
```sql
CREATE OR REPLACE FUNCTION repair_cowrie_json(malformed_content TEXT)
RETURNS JSONB
```

#### **3. UPSERT Function**
```sql
CREATE OR REPLACE FUNCTION upsert_repaired_event(
    p_source TEXT,
    p_source_offset BIGINT,
    p_source_inode TEXT,
    p_payload JSONB
)
RETURNS BOOLEAN
```

#### **4. Statistics Function**
```sql
CREATE OR REPLACE FUNCTION get_dlq_statistics()
RETURNS TABLE(
    total_events BIGINT,
    unresolved_events BIGINT,
    resolved_events BIGINT,
    top_reasons JSONB,
    oldest_unresolved TIMESTAMP WITH TIME ZONE,
    newest_unresolved TIMESTAMP WITH TIME ZONE
)
```

### **Usage Examples**

#### **Create Stored Procedures**
```bash
uv run python -m cowrieprocessor.loader.dlq_stored_proc_cli create
```

#### **Process DLQ Events**
```bash
# Process all unresolved events
uv run python -m cowrieprocessor.loader.dlq_stored_proc_cli process

# Process with limit and filter
uv run python -m cowrieprocessor.loader.dlq_stored_proc_cli process --limit 1000 --reason json_parsing_failed
```

#### **Get Statistics**
```bash
uv run python -m cowrieprocessor.loader.dlq_stored_proc_cli stats
```

#### **Cleanup Old Events**
```bash
uv run python -m cowrieprocessor.loader.dlq_stored_proc_cli cleanup --older-than-days 30
```

## 🔄 **Processing Flow**

### **Stored Procedure Workflow**
1. **Query Unresolved Events**: Select `resolved = FALSE` events
2. **Extract Malformed Content**: Get `malformed_content` from payload
3. **Repair JSON**: Use `repair_cowrie_json()` function
4. **UPSERT Raw Event**: Insert/update in `raw_events` table
5. **Mark as Resolved**: Set `resolved = TRUE` and `resolved_at = NOW()`
6. **Return Statistics**: Provide processing counts

### **Error Handling**
- **Transaction Safety**: All operations in single transaction
- **Rollback on Failure**: Failed batches are rolled back completely
- **Detailed Logging**: PostgreSQL logs all operations
- **Graceful Degradation**: Invalid JSON becomes minimal events

## 📈 **Performance Comparison**

### **Application Layer Processing**
- **Memory Usage**: High (loads all records into memory)
- **Network Overhead**: High (transfers all data)
- **Processing Speed**: Slower (application layer JSON parsing)
- **Concurrency**: Limited by application server resources

### **Stored Procedure Processing**
- **Memory Usage**: Low (database handles everything)
- **Network Overhead**: Minimal (only statistics returned)
- **Processing Speed**: Faster (database-optimized operations)
- **Concurrency**: High (database connection pooling)

## 🛠 **Implementation Recommendations**

### **1. Hybrid Approach**
- **Use Stored Procedures**: For bulk processing and high-volume scenarios
- **Keep Application Layer**: For complex repair logic and testing
- **Fallback Support**: Application layer as backup for non-PostgreSQL databases

### **2. Monitoring & Alerting**
- **Processing Metrics**: Track success rates and processing times
- **DLQ Growth**: Monitor unresolved event counts
- **Performance Metrics**: Database performance during processing

### **3. Operational Procedures**
- **Regular Cleanup**: Schedule cleanup of old resolved events
- **Batch Processing**: Process in manageable chunks (1000-10000 events)
- **Concurrent Processing**: Use multiple database connections for large volumes

## 🎯 **Next Steps**

1. **Create Stored Procedures**: Deploy the stored procedure definitions
2. **Test Performance**: Compare with application layer processing
3. **Implement Monitoring**: Add metrics and alerting
4. **Production Deployment**: Roll out for high-volume processing
5. **Documentation**: Update operational procedures

## 📋 **Summary**

The stored procedure approach provides:
- ✅ **Efficient Tracking**: Uses existing `resolved` and `resolved_at` fields
- ✅ **No Data Loss**: Events are marked as resolved, not deleted
- ✅ **High Performance**: Database-native processing
- ✅ **Scalability**: Handles large volumes efficiently
- ✅ **Audit Trail**: Complete processing history
- ✅ **Operational Benefits**: Reduced resource usage and network overhead

This implementation addresses all your concerns while providing significant performance and operational improvements for DLQ processing.
