# ADR 001: Use JSONB for Vector Metadata Instead of Foreign Keys

**Status**: Accepted  
**Date**: 2025-10-13  
**Context**: Snowshoe Botnet Detector Enhancement - Phase 1 Database Schema  
**Deciders**: Architecture Review  

## Context and Problem Statement

The snowshoe detector enhancement requires storing references to behavioral pattern vectors when pgvector is available. The initial design proposed using a foreign key (`behavioral_vector_id`) to the `behavioral_pattern_vectors` table. However, this creates significant deployment and compatibility issues.

### Deployment Context
- **Database Diversity**: Researchers use both PostgreSQL (with/without pgvector) and SQLite
- **Optional Feature**: pgvector is an optional PostgreSQL extension, not always available
- **Schema Drift**: Different installations would have incompatible schemas
- **Migration Complexity**: Conditional foreign keys are difficult to manage across database types

## Decision Drivers

1. **Cross-Database Compatibility**: Must work on PostgreSQL and SQLite
2. **Optional pgvector**: Schema must work whether pgvector is available or not
3. **Migration Simplicity**: Avoid conditional schema elements
4. **Future Flexibility**: Support additional vector backends (e.g., future alternatives to pgvector)
5. **Debugging & Transparency**: Store method metadata for reproducibility

## Considered Options

### Option A: Foreign Key to behavioral_pattern_vectors (REJECTED)

```python
# In SnowshoeDetection model
behavioral_vector_id = Column(Integer, ForeignKey('behavioral_pattern_vectors.id'), nullable=True)
```

**Pros**:
- Referential integrity enforced by database
- Standard relational design pattern
- Direct joins for queries

**Cons**:
- ❌ Only works when pgvector available
- ❌ Creates schema drift across installations
- ❌ Migration fails on non-pgvector systems
- ❌ SQLite deployments cannot use this approach
- ❌ Difficult to handle in application code (nullable FK that may not have valid targets)
- ❌ Schema validation tools report inconsistencies

### Option B: JSONB/JSON Field for Vector Metadata (ACCEPTED)

```python
# In SnowshoeDetection model
vector_metadata = Column(JSONB, nullable=True)  # PostgreSQL
vector_metadata = Column(JSON, nullable=True)   # SQLite

# Usage
if self.pgvector_available:
    vector_metadata = {
        "vector_id": vector_id,
        "method": "pgvector",
        "table": "behavioral_pattern_vectors",
        "dimensions": 64,
        "metric": "cosine"
    }
else:
    vector_metadata = {
        "method": "sklearn_nn",
        "algorithm": "NearestNeighbors",
        "metric": "cosine",
        "dimensions": 64
    }
```

**Pros**:
- ✅ Works consistently across PostgreSQL and SQLite
- ✅ No foreign key constraints to manage
- ✅ Stores method metadata for reproducibility
- ✅ Future-proof for additional vector backends
- ✅ Easy to extend with new fields
- ✅ Application handles reference resolution
- ✅ Schema remains consistent across all installations

**Cons**:
- No database-enforced referential integrity
- Requires application-level validation
- Slightly more complex queries (JSON path extraction)

### Option C: Separate Metadata Table (REJECTED)

```python
# Create separate table for vector references
class VectorMetadata(Base):
    __tablename__ = "vector_metadata"
    id = Column(Integer, primary_key=True)
    detection_id = Column(Integer, ForeignKey('snowshoe_detection.id'))
    method = Column(String(50))
    vector_id = Column(Integer, nullable=True)
    ...
```

**Pros**:
- Normalized design
- Could support multiple vectors per detection

**Cons**:
- ❌ Adds complexity with additional table
- ❌ Still has FK issues with pgvector table
- ❌ Overkill for single vector reference
- ❌ More complex queries (additional joins)

## Decision Outcome

**Chosen Option**: Option B - JSONB/JSON Field for Vector Metadata

### Rationale

1. **Deployment Reality**: The project serves individual researchers with diverse database setups. A solution that works everywhere is more valuable than one with perfect referential integrity in limited scenarios.

2. **Optional Feature Pattern**: pgvector is an optional enhancement, not a core requirement. The schema should not depend on optional features being available.

3. **Method Transparency**: Storing the method used (pgvector vs sklearn) enables:
   - Debugging and troubleshooting
   - Understanding historical detections
   - Comparing results across different implementations
   - Future migration paths

4. **Graceful Degradation**: Aligns with the project's graceful degradation strategy where pgvector is used when available but sklearn provides full functionality as fallback.

5. **SQLite Support**: SQLite is a first-class citizen for single-honeypot researchers. The solution must work perfectly on SQLite.

### Implementation Details

#### Database-Agnostic Column Type
```python
def _upgrade_to_v11(conn):
    # Determine JSON column type based on database
    if conn.dialect.name == 'postgresql':
        json_type = 'JSONB'
    else:  # SQLite
        json_type = 'JSON'
    
    conn.execute(text(f"""
        ALTER TABLE snowshoe_detection 
        ADD COLUMN vector_metadata {json_type}
    """))
```

#### Application-Level Reference Resolution
```python
def get_behavioral_vector(self, detection):
    """Retrieve behavioral vector if available."""
    if not detection.vector_metadata:
        return None
    
    method = detection.vector_metadata.get('method')
    
    if method == 'pgvector':
        # Query pgvector table
        vector_id = detection.vector_metadata['vector_id']
        return session.query(BehavioralPatternVector).get(vector_id)
    elif method == 'sklearn_nn':
        # Vector not stored in database, was computed in-memory
        return None
    else:
        logger.warning(f"Unknown vector method: {method}")
        return None
```

#### Validation
```python
def validate_vector_metadata(metadata):
    """Validate vector metadata structure."""
    if not isinstance(metadata, dict):
        raise ValueError("vector_metadata must be a dictionary")
    
    required_fields = ['method', 'metric', 'dimensions']
    for field in required_fields:
        if field not in metadata:
            raise ValueError(f"vector_metadata missing required field: {field}")
    
    valid_methods = ['pgvector', 'sklearn_nn']
    if metadata['method'] not in valid_methods:
        raise ValueError(f"Invalid method: {metadata['method']}")
    
    return True
```

## Consequences

### Positive

- ✅ **Universal Compatibility**: Works on all database types and configurations
- ✅ **No Migration Failures**: Migrations succeed regardless of pgvector availability
- ✅ **Method Transparency**: Clear record of how vectors were computed
- ✅ **Future Flexibility**: Easy to add support for new vector backends
- ✅ **Debugging**: Full context available for troubleshooting
- ✅ **Consistent Schema**: All installations have identical schema

### Negative

- ⚠️ **No Referential Integrity**: Application must handle invalid references
- ⚠️ **Manual Validation**: Must validate JSON structure in application code
- ⚠️ **Query Complexity**: JSON path extraction slightly more complex than direct FK joins

### Mitigation Strategies

1. **Validation Layer**: Implement strict validation in application code before storing
2. **Testing**: Comprehensive tests for both pgvector and sklearn paths
3. **Documentation**: Clear documentation of vector_metadata structure
4. **Monitoring**: Log warnings when vector references cannot be resolved
5. **Cleanup**: Periodic cleanup of orphaned vector references

## Related Decisions

- **ADR 002** (future): Graceful Degradation Strategy for pgvector vs sklearn
- **ADR 003** (future): Vocabulary Versioning and Compatibility Checking

## References

- [Issue #31 Critique](../notes/snowshoe-detector-critique.md) - Section 3: Conditional Foreign Key Problem
- [PostgreSQL JSONB Documentation](https://www.postgresql.org/docs/current/datatype-json.html)
- [SQLite JSON Functions](https://www.sqlite.org/json1.html)
- Project Pattern: Graceful degradation (PostgreSQL+pgvector → PostgreSQL → SQLite)

## Notes

This decision was made after identifying that conditional foreign keys create deployment complexity and schema drift across the diverse installation base. The JSONB approach provides a pragmatic solution that prioritizes compatibility and flexibility over strict relational design.

The decision aligns with the project's existing patterns where optional features (like pgvector) enhance but don't block functionality.

