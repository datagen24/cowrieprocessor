<!-- 8042b6e4-71be-4583-a27e-eea20ca448fa 8ae84881-895c-4242-85ee-fdf3fb1e35e5 -->
# Snowshoe Botnet Detector Enhancement Plan (REVISED)

## Overview

Enhance the existing snowshoe detector with longtail analysis patterns, pgvector-based behavioral similarity (graceful degradation), and HIBP password intelligence to identify different botnets and detect credential stuffing vs targeted attacks.

**Critical Updates Based on Critique**:

- Added Phase 0 for baseline establishment and defanging review
- Fixed pgvector fallback to use NearestNeighbors (not DBSCAN)
- Replaced FK with JSONB vector_metadata field
- Added bidirectional migrations with data cleaning
- Made all thresholds configurable in sensors.toml
- Added SQLite compatibility testing throughout
- Implemented vocabulary versioning and persistence
- Added temporal bucketing for historical queries
- Integrated with existing observability infrastructure

## Deployment Context

- **Scale**: ~1 year data from 5 honeypots per researcher instance
- **Distribution**: Individual researcher laptops (PostgreSQL or SQLite)
- **Processing**: Periodic cron jobs generating daily reports (not real-time)
- **History**: Multi-year analysis with fingerprint stability requirements
- **Vocabulary**: Dynamic learning with defanging awareness

## Phase 0: Baseline & Defanging Review (CRITICAL PREREQUISITE)

**Objectives**: Establish baseline metrics and understand defanging dependency

**Tasks**:

1. **Baseline Establishment**:

                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                - Run current detector on labeled test dataset
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                - Record detection counts, scores, FP/TP rates, F1 scores
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                - Document baseline metrics for comparison

2. **Defanging Module Review** (CRITICAL):

   - Document all defanging transformation patterns using template below
   - Identify reversible normalization approach
   - Test vocabulary consistency with defanged vs non-defanged commands
   - Document edge cases (partial defanging, multiple markers, unicode)

   **Defanging Pattern Documentation Template**:
   
   Expected patterns (to be confirmed by reviewing defanging module):
   - Command substitution: `$(cmd)` → `$(__DEFANGED__)`
   - Dangerous operations: `rm -rf` → `rm__DEFANGED__ -rf`
   - URLs: `http://evil.com` → `http://__DEFANGED__/evil.com`
   - File paths: `/etc/passwd` → `/etc/__DEFANGED__/passwd`
   - IP addresses: `192.168.1.1` → `192.168.__DEFANGED__.1`
   
   Document for each pattern:
   - Original form
   - Defanged form
   - Normalization strategy (how to reverse it for vectorization)
   - Edge cases (partial defanging, nested patterns, unicode)
   - Test examples

3. **Test Dataset Creation**:

                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                - Create labeled dataset with known attack types
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                - Include edge cases (no commands, single IP, mixed IPv4/IPv6, empty passwords)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                - Document expected detection outcomes

4. **Configuration Strategy**:

                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                - Design `sensors.toml` snowshoe detector section with all parameters
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                - Define configuration hierarchy (file → env → CLI)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                - Implement configuration validation
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                - Document override behavior

5. **Behavioral Feature Vector Definition** (CRITICAL):

                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                - Define exact 64-dimensional behavioral feature vector
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                - Document extraction methodology for each feature
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                - Specify normalization approach (0-1 range, log scale, etc.)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                - Define handling of missing/null values
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                - Validate feature independence and relevance

**Deliverables**:

- Baseline metrics document
- Defanging patterns documentation  
- Labeled test dataset
- Configuration schema in `sensors.toml`
- **64-dimensional behavioral feature vector specification document**

## Phase 1: Database Schema Enhancements (Migration v11)

**File**: `cowrieprocessor/db/migrations.py`

**Implementation**:

````python
def _upgrade_to_v11(conn):
    """Upgrade to v11 with database-agnostic JSON type handling."""
    
    # Determine JSON column type based on database
    if conn.dialect.name == 'postgresql':
        json_type = 'JSONB'
    else:  # SQLite
        json_type = 'JSON'
    
    # Step 1: Clean existing String score data
    conn.execute(text("""
        UPDATE snowshoe_detection 
        SET confidence_score = NULL 
        WHERE confidence_score IS NULL 
           OR confidence_score = '' 
           OR NOT (confidence_score ~ '^[0-9.]+

## Phase 2: Core Detector Enhancements

### 2.1: Memory Management & Batch Processing

**File**: `cowrieprocessor/threat_detection/snowshoe.py`

- Add configurable parameters from `sensors.toml`:
 - `memory_limit_gb`, `memory_warning_threshold`, `batch_size`
- Implement `_check_memory_usage()` method
- Modify `_extract_ip_data()` for batch processing
- Add memory warnings with OpenTelemetry metrics

### 2.1a: Defanging-Aware Command Processing (NEW PRIORITY)

**Critical dependency for command sequence analysis**

- Implement `DefangingAwareVectorizer` subclass of `CommandVectorizer`
- Add `normalize_command()` method that reverses defanging markers
- Implement vocabulary caching with versioning:
  ```python
  vocabulary_metadata = {
      "version": compute_vocabulary_hash(),
      "size": len(vocabulary),
      "normalization": "defang_aware_v1",
      "last_updated": timestamp
  }
  ```

- Test vocabulary consistency across defanged/non-defanged datasets
- Document normalization approach and versioning strategy

### 2.2: Command Sequence Analysis

- Create `DefangingAwareVectorizer` instance with persistence
- Implement vocabulary management:
 - Load from cache if exists
 - Incremental learning with `partial_fit()`
 - Save updated vocabulary after each run
 - Track vocabulary version in fingerprints
- Add `_extract_command_sequences()` method
- Add `_analyze_command_similarity()` using TF-IDF cosine similarity
- Store command patterns in `botnet_fingerprint` JSON

### 2.3: Enhanced Behavioral Similarity with pgvector Support

**Key Fix**: Use NearestNeighbors (not DBSCAN) for sklearn fallback

- Add `vector_analysis_enabled` parameter (default: True)
- Detect pgvector availability via `has_pgvector()`
- Implement `_create_behavioral_vectors()` method:
 - **Define exact 64 features** (temporal, commands, auth, network, files, geo, passwords)
 - Use 64-dimensional vectors matching `behavioral_pattern_vectors` table
- Implement `_analyze_behavioral_similarity_with_vectors()`:
 - **If pgvector available**: Store vectors in DB, use L2/cosine distance
 - **If pgvector unavailable**: Use sklearn NearestNeighbors with same metric
 - Store method in `vector_metadata` JSONB field
- Document that fingerprints are implementation-specific

### 2.4: Integrate HIBP Password Intelligence

**Key Fix**: Read from pre-enriched data, handle missing enrichment gracefully

- Add `enable_password_intelligence` parameter (default: True)
- Implement `_compute_password_intelligence()`:
 - Read from `SessionSummary.enrichment['password_stats']`
 - Calculate breach ratio, credential stuffing score, diversity score
 - Track enrichment coverage
 - Adjust password intelligence weight based on coverage
 - Add confidence indicators based on sample size
- Add configurable thresholds from `sensors.toml`:
 - `credential_stuffing_threshold` (default: 0.70)
 - `targeted_attack_threshold` (default: 0.30)
 - `min_passwords_for_intel` (default: 10)
 - `min_ips_for_diversity` (default: 5)
- Implement attack classification:
 - **Credential Stuffing**: High breach ratio (>70%), high geographic diversity
 - **Targeted Attack**: Low breach ratio (<30%), focused geography
 - **Hybrid/Multi-Botnet**: Mixed breach ratios, multiple patterns
 - **Unknown Botnet**: Novel patterns
- Update `_generate_recommendation()` with password intelligence insights

### 2.5: Botnet Fingerprinting

- Implement `_generate_botnet_fingerprint()`:
 - Command sequence patterns (top N-grams) from normalized commands
 - Behavioral vector centroid
 - Password pattern characteristics with coverage metadata
 - Timing pattern signature
 - Geographic distribution signature (defined explicitly)
 - Vocabulary metadata for stability tracking (version hash, size, top 100 terms)
- Generate hash signatures for fast comparison:
 - `command_pattern_hash`
 - `timing_signature_hash`
 - `geo_signature_hash`
- Store complete fingerprint in `botnet_fingerprint` JSONB field
- Implement `_check_vocabulary_compatibility()`:
 - Return True if same vocabulary version (hash match)
 - Return True if vocabulary overlap > 80% (shared terms)
 - Return True if same normalization version with sufficient overlap
 - Return False if different normalization versions
 - Return False if insufficient data for comparison (conservative)
 - Log compatibility decisions for debugging

## Phase 3: Enhanced Detection Scoring

**File**: `cowrieprocessor/threat_detection/snowshoe.py`

**Update `_calculate_snowshoe_score()` method**:

- Load weights from `sensors.toml` configuration:
 - Volume patterns: 25%
 - Geographic diversity: 20%
 - Timing coordination: 15%
 - Command similarity: 15%
 - Behavioral similarity: 15%
 - Password intelligence: 10%
- Validate weights sum to 1.0
- Adjust password weight based on coverage and sample size
- Return detailed scoring breakdown for analysis

**Attack Pattern Classification**:

- Use configurable thresholds
- Include confidence indicators
- Document classification logic
- Store in `attack_classification` field

## Phase 4: Result Storage & Historical Analysis

**File**: `cowrieprocessor/threat_detection/snowshoe.py`

**Add Methods**:

- `store_detection_result()`: Save to `SnowshoeDetection` with all new fields
- `find_similar_attacks()`: Query with temporal bucketing
 - Fast filter by hash signatures (indexed)
 - Deep JSON comparison on candidates
 - Check vocabulary compatibility
 - Return top matches with similarity scores
- `cluster_botnets()`: Group detections by fingerprints to identify campaigns
- `_compute_fingerprint_similarity()`: Compare fingerprints with vocabulary awareness

**Temporal Bucketing Strategy**:

- Optional time window filtering for performance
- Index strategy optimized for multi-year searches
- Efficient candidate filtering before deep comparison

**Update `detect()` method**:

- Return enhanced result with password intelligence
- Include botnet fingerprint and classification
- Add similar attack references if found in history
- Include vocabulary metadata

## Phase 5: CLI Integration & Report Generation

**File**: `cowrieprocessor/cli/analyze.py`

**Update `snowshoe_analyze()` function**:

- Add CLI flags:
 - `--enable-password-intel` (default: True)
 - `--enable-vector-analysis` (default: True)
 - `--memory-limit` (override config)
 - `--store-results` (save to database)
 - `--time-window-days` (for historical searches)
 - `--format` (text, json, markdown, table)
- Display enhanced output:
 - Password intelligence summary with coverage
 - Botnet fingerprint and classification
 - Similar historical attacks
 - Vocabulary metadata
 - Enrichment coverage metrics
- Generate reports suitable for daily cron output

**Report Generation**:

- Implement `generate_detection_report()` for multiple formats
- Include attack classification summary
- Show historical campaign tracking
- Document enrichment coverage

## Phase 6: Comprehensive Testing

**Files**: `tests/unit/test_snowshoe_enhanced.py`, `tests/integration/test_snowshoe_integration.py`

**Database Compatibility Testing (Every Phase)**:
- All unit tests run against both PostgreSQL and SQLite
- Integration tests run against both databases in CI
- Identify database-specific behavior early
- Document any PostgreSQL-only or SQLite-only limitations

**Unit Tests** (concurrent with each phase):

- Memory management and batch processing
- Defanging-aware command normalization
- Vocabulary persistence and versioning
- Behavioral vector creation (with/without pgvector)
- Password intelligence with coverage adjustment
- Botnet fingerprinting with vocabulary metadata
- Graceful degradation (pgvector → NearestNeighbors)
- Attack pattern classification with thresholds
- Configuration loading and validation
- Edge cases (no commands, empty passwords, single IP, etc.)

**Integration Tests**:

- Full detection pipeline with real session data
- PostgreSQL and SQLite compatibility (tested throughout)
- pgvector integration when available
- Password intelligence with pre-enriched data
- Result storage and retrieval
- Historical similarity detection with temporal bucketing
- Vocabulary evolution across runs
- Bidirectional migration testing

**Performance Tests**:

- Memory usage with large datasets (10k+ sessions)
- Batch processing efficiency
- pgvector vs NearestNeighbors performance comparison
- Historical query performance with multi-year data
- Vocabulary cache performance

**Adversarial Testing**:

- Incremental behavior variation
- Mixed attack patterns
- Slow-distributed attacks
- Mimicking legitimate traffic
- Evasion simulation

## Phase 7: Documentation & Observability

**Files**: `docs/snowshoe_detection.md`, `README.md`

**Documentation**:

- Enhanced detection capabilities overview
- Password intelligence integration and coverage requirements
- Botnet fingerprinting approach with vocabulary versioning
- Attack classification examples with thresholds
- pgvector requirements and fallback behavior
- SQLite vs PostgreSQL differences
- Configuration guide for `sensors.toml`
- Vocabulary management and evolution
- Defanging impact on fingerprinting
- Historical analysis and temporal bucketing
- Report generation for cron jobs

**Observability Integration**:

- Wire into OpenTelemetry:
 - Detection counts by attack classification
 - Pipeline execution duration (p50, p95, p99)
 - Memory usage during processing
 - Batch processing throughput
 - Password enrichment coverage
 - Vector method usage (pgvector vs sklearn)
 - Historical query duration
- Wire into JSON status monitor:
 - Current processing phase
 - Sessions processed/total
 - Memory usage
 - Estimated time remaining
 - Last error message

## Key Design Decisions

### 1. Graceful Degradation (FIXED)

```python
# Use NearestNeighbors (not DBSCAN) for sklearn fallback
if self.pgvector_available:
    similarity = self._compute_similarity_pgvector(vectors)
else:
    # Use same distance metric for consistency
    similarity = self._compute_similarity_sklearn_nn(vectors, metric='cosine')

# Store method in vector_metadata
vector_metadata = {
    "method": "pgvector" if self.pgvector_available else "sklearn_nn",
    "metric": "cosine",
    "dimensions": 64
}
````

### 2. Password Intelligence with Coverage

```python
# Extract from pre-enriched data
password_intel = self._extract_password_intelligence(sessions)

# Adjust weight based on coverage and sample size
coverage = password_intel['enriched_count'] / len(sessions)
sample_size_factor = min(1.0, password_intel['total_passwords'] / self.min_passwords_for_intel)
effective_weight = base_weight * coverage * sample_size_factor

# Include confidence indicator with clearer thresholds
# If min_passwords_for_intel = 10:
# - 10+ passwords: factor = 1.0 → "high" (sufficient sample)
# - 7-9 passwords: factor = 0.7-0.9 → "medium" (borderline sufficient)  
# - < 7 passwords: factor < 0.7 → "low" (insufficient sample)
if sample_size_factor >= 1.0:
    password_intel['confidence'] = 'high'
elif sample_size_factor >= 0.7:
    password_intel['confidence'] = 'medium'
else:
    password_intel['confidence'] = 'low'
```

### 3. Botnet Fingerprinting with Vocabulary Metadata

```python
fingerprint = {
    "command_ngrams": top_command_ngrams,
    "behavioral_centroid": behavioral_vector_mean,
    "password_characteristics": {
        "breach_ratio": breach_ratio,
        "avg_prevalence": avg_prevalence,
        "password_diversity": password_diversity,
        "coverage": enrichment_coverage
    },
    "timing_signature": timing_pattern_hash,
    "geographic_signature": {
        "country_count": len(unique_countries),
        "asn_count": len(unique_asns),
        "country_entropy": country_entropy,
        "top_3_countries": top_countries
    },
    "vectorizer_metadata": {
        "vocabulary_version": vocabulary_hash,
        "vocabulary_size": len(vocabulary),
        "normalization": "defang_aware_v1"
    }
}
```

### 4. Vector Metadata (NO FK)

```python
# Store in JSONB field instead of FK
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

### 5. Temporal Bucketing for Historical Queries

```python
def find_similar_attacks(self, fingerprint, max_results=10, time_window_days=None):
    # Optional time windowing for performance
    if time_window_days:
        cutoff = datetime.now() - timedelta(days=time_window_days)
        query = query.filter(SnowshoeDetection.detection_time >= cutoff)
    
    # Fast filter by indexed hash signatures
    candidates = query.filter(
        or_(
            SnowshoeDetection.command_pattern_hash == fingerprint['command_pattern_hash'],
            SnowshoeDetection.timing_signature_hash == fingerprint['timing_signature_hash'],
            SnowshoeDetection.geo_signature_hash == fingerprint['geo_signature_hash']
        )
    ).limit(max_results * 3).all()
    
    # Deep comparison with vocabulary compatibility check
    similar = []
    incompatible_count = 0
    
    for candidate in candidates:
        if not self._check_vocabulary_compatibility(candidate, fingerprint):
            incompatible_count += 1
            continue  # Skip incompatible vocabularies
        
        similarity = self._compute_fingerprint_similarity(candidate, fingerprint)
        if similarity > self.similarity_threshold:
            similar.append((candidate, similarity))
    
    if incompatible_count > 0:
        logger.info(f"Skipped {incompatible_count} candidates due to vocabulary incompatibility")
    
    return sorted(similar, key=lambda x: x[1], reverse=True)[:max_results]
```

## Configuration in sensors.toml

```toml
[snowshoe_detector]
# Memory management
memory_limit_gb = 4.0
memory_warning_threshold_gb = 3.2
batch_size = 1000  # Auto-calculated if omitted (based on memory_limit_gb)

# Detection thresholds (configurable, not hardcoded)
credential_stuffing_threshold = 0.70
targeted_attack_threshold = 0.30
min_passwords_for_intel = 10
min_ips_for_diversity = 5
similarity_threshold = 0.75

# Scoring weights (must sum to 1.0)
[snowshoe_detector.weights]
volume = 0.25
geographic = 0.20
timing = 0.15
command_similarity = 0.15
behavioral_similarity = 0.15
password_intelligence = 0.10

# Feature flags
[snowshoe_detector.features]
enable_password_intelligence = true
enable_vector_analysis = true
vector_analysis_method = "auto"  # auto, pgvector, sklearn

# Command vectorization
[snowshoe_detector.command_vectorizer]
max_features = 1000
ngram_range = [1, 3]
vocabulary_cache_path = "./cache/snowshoe_vocabulary.pkl"
update_vocabulary_on_new_commands = true
```

## Files to Modify

1. `cowrieprocessor/db/models.py` - Add fields to `SnowshoeDetection`
2. `cowrieprocessor/db/migrations.py` - Create bidirectional v11 migration
3. `cowrieprocessor/threat_detection/snowshoe.py` - Core enhancements (major refactor)
4. `cowrieprocessor/cli/analyze.py` - Update CLI command
5. `sensors.toml` - Add snowshoe detector configuration
6. `tests/unit/test_snowshoe_enhanced.py` - New unit tests
7. `tests/integration/test_snowshoe_integration.py` - New integration tests
8. `docs/snowshoe_detection.md` - New documentation
9. `README.md` - Update with new capabilities

## Success Criteria

- ✅ Baseline metrics established and documented
- ✅ Defanging integration tested and vocabulary consistent
- ✅ Memory usage stays under configurable limits
- ✅ Graceful degradation works (pgvector → sklearn NearestNeighbors)
- ✅ Password intelligence correctly identifies attack types with coverage metrics
- ✅ Botnet fingerprinting enables clustering with vocabulary versioning
- ✅ All tests pass with 80%+ coverage on both PostgreSQL and SQLite
- ✅ Bidirectional migrations work cleanly
- ✅ Detection accuracy improves over baseline (F1 score, FP rate)
- ✅ Historical queries efficient with multi-year data
- ✅ Configuration fully externalized to sensors.toml
- ✅ Observability fully integrated (OpenTelemetry + JSON status)
- ✅ Documentation complete and clear

## Implementation Order (REVISED)

1. **Phase 0: Baseline & Defanging** - Critical prerequisites
2. **Phase 1: Database schema** - Test on both databases immediately
3. **Phase 2.1: Memory management** - Prevent OOM issues
4. **Phase 2.1a: Defanging-aware processing** - Critical for command analysis
5. **Phase 2.4: Password intelligence** - High-value, independent feature
6. **Phase 2.2: Command sequence analysis** - Builds on defanging work
7. **Phase 2.3: Vector-based behavioral similarity** - Most complex
8. **Phase 2.5: Botnet fingerprinting** - Integrates all enhancements
9. **Phase 3: Enhanced scoring** - Ties everything together
10. **Phase 4: Storage & historical analysis** - Enable long-term tracking
11. **Phase 5: CLI & report integration** - User-facing functionality
12. **Phase 6: Comprehensive testing** - Validate all enhancements
13. **Phase 7: Documentation & observability** - Enable adoption)

""")) if conn.dialect.name == 'postgresql' else conn.execute(text("""

UPDATE snowshoe_detection

SET confidence_score = NULL

WHERE confidence_score IS NULL

OR confidence_score = ''

OR CAST(confidence_score AS TEXT) NOT GLOB '*[0-9]*'

"""))

# Repeat for geographic_spread

# ... (similar cleaning)

# Step 2: Convert String → Float

if conn.dialect.name == 'postgresql':

conn.execute(text("""

ALTER TABLE snowshoe_detection

ALTER COLUMN confidence_score TYPE FLOAT USING confidence_score::FLOAT,

ALTER COLUMN geographic_spread TYPE FLOAT USING geographic_spread::FLOAT

"""))

else:  # SQLite doesn't support ALTER COLUMN TYPE, need to recreate

# SQLite migration approach documented in migration code

pass

# Step 3: Add new columns

conn.execute(text(f"""

ALTER TABLE snowshoe_detection

ADD COLUMN password_breach_ratio FLOAT,

ADD COLUMN credential_stuffing_score FLOAT,

ADD COLUMN password_diversity_score FLOAT,

ADD COLUMN password_intel {json_type},

ADD COLUMN botnet_fingerprint {json_type},

ADD COLUMN command_pattern_hash VARCHAR(64),

ADD COLUMN timing_signature_hash VARCHAR(64),

ADD COLUMN geo_signature_hash VARCHAR(64),

ADD COLUMN vector_metadata {json_type},

ADD COLUMN attack_classification VARCHAR(50),

ADD COLUMN classification_confidence FLOAT

"""))

# Step 4: Create database-specific indexes

if conn.dialect.name == 'postgresql':

# PostgreSQL: Standard indexes

conn.execute(text("""

CREATE INDEX idx_command_pattern_hash

ON snowshoe_detection (command_pattern_hash)

"""))

conn.execute(text("""

CREATE INDEX idx_timing_signature_hash

ON snowshoe_detection (timing_signature_hash)

"""))

conn.execute(text("""

CREATE INDEX idx_geo_signature_hash

ON snowshoe_detection (geo_signature_hash)

"""))

conn.execute(text("""

CREATE INDEX idx_attack_classification

ON snowshoe_detection (attack_classification)

"""))

# PostgreSQL: GIN indexes on JSONB paths

conn.execute(text("""

CREATE INDEX idx_password_intel_breach_ratio

ON snowshoe_detection ((password_intel->>'breach_ratio'))

"""))

conn.execute(text("""

CREATE INDEX idx_password_intel_attack_type

ON snowshoe_detection ((password_intel->>'attack_type'))

"""))

else:  # SQLite

# SQLite: Standard indexes

conn.execute(text("""

CREATE INDEX idx_command_pattern_hash

ON snowshoe_detection (command_pattern_hash)

"""))

conn.execute(text("""

CREATE INDEX idx_timing_signature_hash

ON snowshoe_detection (timing_signature_hash)

"""))

conn.execute(text("""

CREATE INDEX idx_geo_signature_hash

ON snowshoe_detection (geo_signature_hash)

"""))

conn.execute(text("""

CREATE INDEX idx_attack_classification

ON snowshoe_detection (attack_classification)

"""))

# SQLite: json_extract for indexing JSON paths

conn.execute(text("""

CREATE INDEX idx_password_intel_breach_ratio

ON snowshoe_detection (json_extract(password_intel, '$.breach_ratio'))

"""))

conn.execute(text("""

CREATE INDEX idx_password_intel_attack_type

ON snowshoe_detection (json_extract(password_intel, '$.attack_type'))

"""))

def _downgrade_from_v11(conn):

"""Downgrade from v11 to v10 - clean rollback."""

# Drop indexes first (database-agnostic)

conn.execute(text("DROP INDEX IF EXISTS idx_command_pattern_hash"))

conn.execute(text("DROP INDEX IF EXISTS idx_timing_signature_hash"))

conn.execute(text("DROP INDEX IF EXISTS idx_geo_signature_hash"))

conn.execute(text("DROP INDEX IF EXISTS idx_attack_classification"))

conn.execute(text("DROP INDEX IF EXISTS idx_password_intel_breach_ratio"))

conn.execute(text("DROP INDEX IF EXISTS idx_password_intel_attack_type"))

# Remove new columns

conn.execute(text("""

ALTER TABLE snowshoe_detection

DROP COLUMN IF EXISTS password_breach_ratio,

DROP COLUMN IF EXISTS credential_stuffing_score,

DROP COLUMN IF EXISTS password_diversity_score,

DROP COLUMN IF EXISTS password_intel,

DROP COLUMN IF EXISTS botnet_fingerprint,

DROP COLUMN IF EXISTS command_pattern_hash,

DROP COLUMN IF EXISTS timing_signature_hash,

DROP COLUMN IF EXISTS geo_signature_hash,

DROP COLUMN IF EXISTS vector_metadata,

DROP COLUMN IF EXISTS attack_classification,

DROP COLUMN IF EXISTS classification_confidence

"""))

# Revert score type changes (if applicable)

if conn.dialect.name == 'postgresql':

conn.execute(text("""

ALTER TABLE snowshoe_detection

ALTER COLUMN confidence_score TYPE VARCHAR USING confidence_score::VARCHAR,

ALTER COLUMN geographic_spread TYPE VARCHAR USING geographic_spread::VARCHAR

"""))

````

**Migration Testing Checklist**:
- [ ] Test upgrade on PostgreSQL with no existing data
- [ ] Test upgrade on PostgreSQL with existing v10 data (including bad strings)
- [ ] Test upgrade on SQLite with no existing data
- [ ] Test upgrade on SQLite with existing v10 data
- [ ] Test downgrade on PostgreSQL
- [ ] Test downgrade on SQLite
- [ ] Test upgrade → downgrade → upgrade cycle (both databases)
- [ ] Verify all indexes created correctly (PostgreSQL GIN indexes, SQLite json_extract indexes)
- [ ] Verify data integrity after each operation (row counts, non-null constraints)
- [ ] Test with edge case data (NULL values, empty strings, very large JSON objects)
- [ ] Verify String→Float conversion handles all edge cases correctly
- [ ] Verify JSONB (PostgreSQL) vs JSON (SQLite) compatibility

## Phase 2: Core Detector Enhancements

### 2.1: Memory Management & Batch Processing

**File**: `cowrieprocessor/threat_detection/snowshoe.py`

- Add configurable parameters from `sensors.toml`:
 - `memory_limit_gb`, `memory_warning_threshold`, `batch_size`
- Implement `_check_memory_usage()` method
- Modify `_extract_ip_data()` for batch processing
- Add memory warnings with OpenTelemetry metrics

### 2.1a: Defanging-Aware Command Processing (NEW PRIORITY)

**Critical dependency for command sequence analysis**

- Implement `DefangingAwareVectorizer` subclass of `CommandVectorizer`
- Add `normalize_command()` method that reverses defanging markers
- Implement vocabulary caching with versioning:
  ```python
  vocabulary_metadata = {
      "version": compute_vocabulary_hash(),
      "size": len(vocabulary),
      "normalization": "defang_aware_v1",
      "last_updated": timestamp
  }
  ```

- Test vocabulary consistency across defanged/non-defanged datasets
- Document normalization approach and versioning strategy

### 2.2: Command Sequence Analysis

- Create `DefangingAwareVectorizer` instance with persistence
- Implement vocabulary management:
 - Load from cache if exists
 - Incremental learning with `partial_fit()`
 - Save updated vocabulary after each run
 - Track vocabulary version in fingerprints
- Add `_extract_command_sequences()` method
- Add `_analyze_command_similarity()` using TF-IDF cosine similarity
- Store command patterns in `botnet_fingerprint` JSON

### 2.3: Enhanced Behavioral Similarity with pgvector Support

**Key Fix**: Use NearestNeighbors (not DBSCAN) for sklearn fallback

- Add `vector_analysis_enabled` parameter (default: True)
- Detect pgvector availability via `has_pgvector()`
- Implement `_create_behavioral_vectors()` method:
 - **Define exact 64 features** (temporal, commands, auth, network, files, geo, passwords)
 - Use 64-dimensional vectors matching `behavioral_pattern_vectors` table
- Implement `_analyze_behavioral_similarity_with_vectors()`:
 - **If pgvector available**: Store vectors in DB, use L2/cosine distance
 - **If pgvector unavailable**: Use sklearn NearestNeighbors with same metric
 - Store method in `vector_metadata` JSONB field
- Document that fingerprints are implementation-specific

### 2.4: Integrate HIBP Password Intelligence

**Key Fix**: Read from pre-enriched data, handle missing enrichment gracefully

- Add `enable_password_intelligence` parameter (default: True)
- Implement `_compute_password_intelligence()`:
 - Read from `SessionSummary.enrichment['password_stats']`
 - Calculate breach ratio, credential stuffing score, diversity score
 - Track enrichment coverage
 - Adjust password intelligence weight based on coverage
 - Add confidence indicators based on sample size
- Add configurable thresholds from `sensors.toml`:
 - `credential_stuffing_threshold` (default: 0.70)
 - `targeted_attack_threshold` (default: 0.30)
 - `min_passwords_for_intel` (default: 10)
 - `min_ips_for_diversity` (default: 5)
- Implement attack classification:
 - **Credential Stuffing**: High breach ratio (>70%), high geographic diversity
 - **Targeted Attack**: Low breach ratio (<30%), focused geography
 - **Hybrid/Multi-Botnet**: Mixed breach ratios, multiple patterns
 - **Unknown Botnet**: Novel patterns
- Update `_generate_recommendation()` with password intelligence insights

### 2.5: Botnet Fingerprinting

- Implement `_generate_botnet_fingerprint()`:
 - Command sequence patterns (top N-grams) from normalized commands
 - Behavioral vector centroid
 - Password pattern characteristics with coverage metadata
 - Timing pattern signature
 - Geographic distribution signature (defined explicitly)
 - Vocabulary metadata for stability tracking (version hash, size, top 100 terms)
- Generate hash signatures for fast comparison:
 - `command_pattern_hash`
 - `timing_signature_hash`
 - `geo_signature_hash`
- Store complete fingerprint in `botnet_fingerprint` JSONB field
- Implement `_check_vocabulary_compatibility()`:
 - Return True if same vocabulary version (hash match)
 - Return True if vocabulary overlap > 80% (shared terms)
 - Return True if same normalization version with sufficient overlap
 - Return False if different normalization versions
 - Return False if insufficient data for comparison (conservative)
 - Log compatibility decisions for debugging

## Phase 3: Enhanced Detection Scoring

**File**: `cowrieprocessor/threat_detection/snowshoe.py`

**Update `_calculate_snowshoe_score()` method**:

- Load weights from `sensors.toml` configuration:
 - Volume patterns: 25%
 - Geographic diversity: 20%
 - Timing coordination: 15%
 - Command similarity: 15%
 - Behavioral similarity: 15%
 - Password intelligence: 10%
- Validate weights sum to 1.0
- Adjust password weight based on coverage and sample size
- Return detailed scoring breakdown for analysis

**Attack Pattern Classification**:

- Use configurable thresholds
- Include confidence indicators
- Document classification logic
- Store in `attack_classification` field

## Phase 4: Result Storage & Historical Analysis

**File**: `cowrieprocessor/threat_detection/snowshoe.py`

**Add Methods**:

- `store_detection_result()`: Save to `SnowshoeDetection` with all new fields
- `find_similar_attacks()`: Query with temporal bucketing
 - Fast filter by hash signatures (indexed)
 - Deep JSON comparison on candidates
 - Check vocabulary compatibility
 - Return top matches with similarity scores
- `cluster_botnets()`: Group detections by fingerprints to identify campaigns
- `_compute_fingerprint_similarity()`: Compare fingerprints with vocabulary awareness

**Temporal Bucketing Strategy**:

- Optional time window filtering for performance
- Index strategy optimized for multi-year searches
- Efficient candidate filtering before deep comparison

**Update `detect()` method**:

- Return enhanced result with password intelligence
- Include botnet fingerprint and classification
- Add similar attack references if found in history
- Include vocabulary metadata

## Phase 5: CLI Integration & Report Generation

**File**: `cowrieprocessor/cli/analyze.py`

**Update `snowshoe_analyze()` function**:

- Add CLI flags:
 - `--enable-password-intel` (default: True)
 - `--enable-vector-analysis` (default: True)
 - `--memory-limit` (override config)
 - `--store-results` (save to database)
 - `--time-window-days` (for historical searches)
 - `--format` (text, json, markdown, table)
- Display enhanced output:
 - Password intelligence summary with coverage
 - Botnet fingerprint and classification
 - Similar historical attacks
 - Vocabulary metadata
 - Enrichment coverage metrics
- Generate reports suitable for daily cron output

**Report Generation**:

- Implement `generate_detection_report()` for multiple formats
- Include attack classification summary
- Show historical campaign tracking
- Document enrichment coverage

## Phase 6: Comprehensive Testing

**Files**: `tests/unit/test_snowshoe_enhanced.py`, `tests/integration/test_snowshoe_integration.py`

**Unit Tests** (concurrent with each phase):

- Memory management and batch processing
- Defanging-aware command normalization
- Vocabulary persistence and versioning
- Behavioral vector creation (with/without pgvector)
- Password intelligence with coverage adjustment
- Botnet fingerprinting with vocabulary metadata
- Graceful degradation (pgvector → NearestNeighbors)
- Attack pattern classification with thresholds
- Configuration loading and validation
- Edge cases (no commands, empty passwords, single IP, etc.)

**Integration Tests**:

- Full detection pipeline with real session data
- PostgreSQL and SQLite compatibility (tested throughout)
- pgvector integration when available
- Password intelligence with pre-enriched data
- Result storage and retrieval
- Historical similarity detection with temporal bucketing
- Vocabulary evolution across runs
- Bidirectional migration testing

**Performance Tests**:

- Memory usage with large datasets (10k+ sessions)
- Batch processing efficiency
- pgvector vs NearestNeighbors performance comparison
- Historical query performance with multi-year data
- Vocabulary cache performance

**Adversarial Testing**:

- Incremental behavior variation
- Mixed attack patterns
- Slow-distributed attacks
- Mimicking legitimate traffic
- Evasion simulation

## Phase 7: Documentation & Observability

**Files**: `docs/snowshoe_detection.md`, `README.md`

**Documentation**:

- Enhanced detection capabilities overview
- Password intelligence integration and coverage requirements
- Botnet fingerprinting approach with vocabulary versioning
- Attack classification examples with thresholds
- pgvector requirements and fallback behavior
- SQLite vs PostgreSQL differences
- Configuration guide for `sensors.toml`
- Vocabulary management and evolution
- Defanging impact on fingerprinting
- Historical analysis and temporal bucketing
- Report generation for cron jobs

**Observability Integration**:

- Wire into OpenTelemetry:
 - Detection counts by attack classification
 - Pipeline execution duration (p50, p95, p99)
 - Memory usage during processing
 - Batch processing throughput
 - Password enrichment coverage
 - Vector method usage (pgvector vs sklearn)
 - Historical query duration
- Wire into JSON status monitor:
 - Current processing phase
 - Sessions processed/total
 - Memory usage
 - Estimated time remaining
 - Last error message

## Key Design Decisions

### 1. Graceful Degradation (FIXED)

```python
# Use NearestNeighbors (not DBSCAN) for sklearn fallback
if self.pgvector_available:
    similarity = self._compute_similarity_pgvector(vectors)
else:
    # Use same distance metric for consistency
    similarity = self._compute_similarity_sklearn_nn(vectors, metric='cosine')

# Store method in vector_metadata
vector_metadata = {
    "method": "pgvector" if self.pgvector_available else "sklearn_nn",
    "metric": "cosine",
    "dimensions": 64
}
````

### 2. Password Intelligence with Coverage

```python
# Extract from pre-enriched data
password_intel = self._extract_password_intelligence(sessions)

# Adjust weight based on coverage and sample size
coverage = password_intel['enriched_count'] / len(sessions)
sample_size_factor = min(1.0, password_intel['total_passwords'] / self.min_passwords_for_intel)
effective_weight = base_weight * coverage * sample_size_factor

# Include confidence indicator with clearer thresholds
# If min_passwords_for_intel = 10:
# - 10+ passwords: factor = 1.0 → "high" (sufficient sample)
# - 7-9 passwords: factor = 0.7-0.9 → "medium" (borderline sufficient)  
# - < 7 passwords: factor < 0.7 → "low" (insufficient sample)
if sample_size_factor >= 1.0:
    password_intel['confidence'] = 'high'
elif sample_size_factor >= 0.7:
    password_intel['confidence'] = 'medium'
else:
    password_intel['confidence'] = 'low'
```

### 3. Botnet Fingerprinting with Vocabulary Metadata

```python
fingerprint = {
    "command_ngrams": top_command_ngrams,
    "behavioral_centroid": behavioral_vector_mean,
    "password_characteristics": {
        "breach_ratio": breach_ratio,
        "avg_prevalence": avg_prevalence,
        "password_diversity": password_diversity,
        "coverage": enrichment_coverage
    },
    "timing_signature": timing_pattern_hash,
    "geographic_signature": {
        "country_count": len(unique_countries),
        "asn_count": len(unique_asns),
        "country_entropy": country_entropy,
        "top_3_countries": top_countries
    },
    "vectorizer_metadata": {
        "vocabulary_version": vocabulary_hash,
        "vocabulary_size": len(vocabulary),
        "normalization": "defang_aware_v1"
    }
}
```

### 4. Vector Metadata (NO FK)

```python
# Store in JSONB field instead of FK
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

### 5. Temporal Bucketing for Historical Queries

```python
def find_similar_attacks(self, fingerprint, max_results=10, time_window_days=None):
    # Optional time windowing for performance
    if time_window_days:
        cutoff = datetime.now() - timedelta(days=time_window_days)
        query = query.filter(SnowshoeDetection.detection_time >= cutoff)
    
    # Fast filter by indexed hash signatures
    candidates = query.filter(
        or_(
            SnowshoeDetection.command_pattern_hash == fingerprint['command_pattern_hash'],
            SnowshoeDetection.timing_signature_hash == fingerprint['timing_signature_hash'],
            SnowshoeDetection.geo_signature_hash == fingerprint['geo_signature_hash']
        )
    ).limit(max_results * 3).all()
    
    # Deep comparison with vocabulary compatibility check
    similar = []
    for candidate in candidates:
        if self._check_vocabulary_compatibility(candidate, fingerprint):
            similarity = self._compute_fingerprint_similarity(candidate, fingerprint)
            if similarity > self.similarity_threshold:
                similar.append((candidate, similarity))
    
    return sorted(similar, key=lambda x: x[1], reverse=True)[:max_results]
```

## Configuration in sensors.toml

```toml
[snowshoe_detector]
# Memory management
memory_limit_gb = 4.0
memory_warning_threshold_gb = 3.2
batch_size = 1000

# Detection thresholds (configurable, not hardcoded)
credential_stuffing_threshold = 0.70
targeted_attack_threshold = 0.30
min_passwords_for_intel = 10
min_ips_for_diversity = 5
similarity_threshold = 0.75

# Scoring weights (must sum to 1.0)
[snowshoe_detector.weights]
volume = 0.25
geographic = 0.20
timing = 0.15
command_similarity = 0.15
behavioral_similarity = 0.15
password_intelligence = 0.10

# Feature flags
[snowshoe_detector.features]
enable_password_intelligence = true
enable_vector_analysis = true
vector_analysis_method = "auto"  # auto, pgvector, sklearn

# Command vectorization
[snowshoe_detector.command_vectorizer]
max_features = 1000
ngram_range = [1, 3]
vocabulary_cache_path = "./cache/snowshoe_vocabulary.pkl"
update_vocabulary_on_new_commands = true
```

## Files to Modify

1. `cowrieprocessor/db/models.py` - Add fields to `SnowshoeDetection`
2. `cowrieprocessor/db/migrations.py` - Create bidirectional v11 migration
3. `cowrieprocessor/threat_detection/snowshoe.py` - Core enhancements (major refactor)
4. `cowrieprocessor/cli/analyze.py` - Update CLI command
5. `sensors.toml` - Add snowshoe detector configuration
6. `tests/unit/test_snowshoe_enhanced.py` - New unit tests
7. `tests/integration/test_snowshoe_integration.py` - New integration tests
8. `docs/snowshoe_detection.md` - New documentation
9. `README.md` - Update with new capabilities

## Success Criteria

- ✅ Baseline metrics established and documented
- ✅ Defanging integration tested and vocabulary consistent
- ✅ Memory usage stays under configurable limits
- ✅ Graceful degradation works (pgvector → sklearn NearestNeighbors)
- ✅ Password intelligence correctly identifies attack types with coverage metrics
- ✅ Botnet fingerprinting enables clustering with vocabulary versioning
- ✅ All tests pass with 80%+ coverage on both PostgreSQL and SQLite
- ✅ Bidirectional migrations work cleanly
- ✅ Detection accuracy improves over baseline (F1 score, FP rate)
- ✅ Historical queries efficient with multi-year data
- ✅ Configuration fully externalized to sensors.toml
- ✅ Observability fully integrated (OpenTelemetry + JSON status)
- ✅ Documentation complete and clear

## Implementation Order (REVISED)

1. **Phase 0: Baseline & Defanging** - Critical prerequisites
2. **Phase 1: Database schema** - Test on both databases immediately
3. **Phase 2.1: Memory management** - Prevent OOM issues
4. **Phase 2.1a: Defanging-aware processing** - Critical for command analysis
5. **Phase 2.4: Password intelligence** - High-value, independent feature
6. **Phase 2.2: Command sequence analysis** - Builds on defanging work
7. **Phase 2.3: Vector-based behavioral similarity** - Most complex
8. **Phase 2.5: Botnet fingerprinting** - Integrates all enhancements
9. **Phase 3: Enhanced scoring** - Ties everything together
10. **Phase 4: Storage & historical analysis** - Enable long-term tracking
11. **Phase 5: CLI & report integration** - User-facing functionality
12. **Phase 6: Comprehensive testing** - Validate all enhancements
13. **Phase 7: Documentation & observability** - Enable adoption

### To-dos

- [ ] Phase 0: Establish baseline metrics, review defanging module, create labeled test dataset, design sensors.toml configuration
- [ ] Phase 1: Create bidirectional migration v11 with data cleaning, test on PostgreSQL and SQLite, use JSONB/JSON appropriately
- [ ] Phase 2.1: Add memory management and batch processing with configurable limits from sensors.toml
- [ ] Phase 2.1a: Implement DefangingAwareVectorizer with normalization, vocabulary caching, and versioning
- [ ] Phase 2.4: Integrate HIBP password intelligence with coverage-aware scoring and configurable thresholds
- [ ] Phase 2.2: Add command sequence analysis with vocabulary persistence and incremental learning
- [ ] Phase 2.3: Implement vector-based behavioral similarity using NearestNeighbors fallback (not DBSCAN), store method in vector_metadata JSONB
- [ ] Phase 2.5: Implement botnet fingerprinting with vocabulary metadata, hash signatures, and geographic signature definition
- [ ] Phase 3: Update scoring with configurable weights from sensors.toml, coverage adjustment, and attack classification
- [ ] Phase 4: Add result storage, temporal bucketing for historical queries, vocabulary compatibility checking
- [ ] Phase 5: Update CLI with new flags, multiple output formats, report generation for cron jobs
- [ ] Phase 6: Create unit tests (with edge cases), integration tests (both databases), performance tests, adversarial testing
- [ ] Phase 7: Write documentation, integrate OpenTelemetry metrics, JSON status monitor, configuration guide