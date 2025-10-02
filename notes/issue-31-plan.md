# Issue #31: Implement Snowshoe Attack Detection - Work Plan

**GitHub Issue**: [#31](https://github.com/datagen24/cowrieprocessor/issues/31)  
**Status**: Planning Complete - Ready for Implementation  
**Created**: 2025-01-27  
**Estimated Effort**: 9 days  

## Overview

**Issue #31** requests implementation of detection algorithms for "snowshoe" spam attacks - distributed, low-volume attacks from many IP addresses designed to evade traditional volume-based detection. This is a sophisticated threat detection feature that requires multiple analysis components.

## Background

Snowshoe attacks use hundreds or thousands of IP addresses, each generating minimal traffic to stay under detection thresholds. These are particularly challenging for honeypots to identify without correlation analysis.

## Current Codebase Analysis

### Existing Infrastructure
- **Database Models**: Well-structured ORM with `SessionSummary`, `RawEvent`, and enrichment tables
- **Reporting System**: Robust reporting pipeline with `DailyReportBuilder`, `WeeklyReportBuilder`, etc.
- **CLI Structure**: Established CLI commands in `cowrieprocessor/cli/` with `cowrie-report`, `cowrie-db`
- **Enrichment System**: Geographic and IP intelligence data available via enrichment cache
- **Testing Framework**: Comprehensive test structure with unit, integration, and performance tests
- **Security Standards**: Strict security requirements with input validation, rate limiting, and secure logging

### Integration Points
- **SessionSummary ORM**: Contains IP data, timestamps, and session metrics
- **Enrichment Data**: Geographic information available in JSON format
- **StatusEmitter**: For metrics and telemetry
- **Reporting DAL**: For database access patterns

## Implementation Plan

### Phase 1: Core Detection Algorithm (3 days)

#### 1.1 Create SnowshoeDetector Class
- **Location**: `cowrieprocessor/threat_detection/snowshoe.py` (new module)
- **Features**:
  - Main `SnowshoeDetector` class with configurable parameters
  - Volume analysis for single-attempt IPs (1-5 attempts)
  - Time clustering detection using DBSCAN or similar
  - Geographic diversity calculation
  - Behavioral similarity analysis
  - Composite scoring algorithm (weighted indicators)

#### 1.2 Volume Analysis Implementation
- Identify IPs with minimal activity (1-5 sessions)
- Calculate ratios of single-attempt vs. total IPs
- Track low-volume IP patterns across time windows

#### 1.3 Time Clustering Detection
- Implement temporal clustering using scikit-learn DBSCAN
- Detect coordinated bursts of activity
- Analyze timing patterns for campaign indicators

#### 1.4 Geographic Diversity Analysis
- Leverage existing enrichment data for country/ASN information
- Calculate geographic spread metrics
- Identify unusual geographic distributions

#### 1.5 Behavioral Similarity Analysis
- Compare command patterns across different IPs
- Detect similar attack sequences
- Analyze session duration patterns

### Phase 2: Database Integration (2 days)

#### 2.1 Database Schema
- **New Table**: `snowshoe_detections`
- **Fields**: detection_time, window_start, window_end, confidence_score, unique_ips, single_attempt_ips, geographic_spread, indicators (JSON), created_at
- **Location**: Add to `cowrieprocessor/db/models.py`

#### 2.2 Migration Support
- Create migration script in `cowrieprocessor/db/migrations.py`
- Follow existing migration patterns
- Ensure PostgreSQL and SQLite compatibility

### Phase 3: CLI Integration (1 day)

#### 3.1 New CLI Command
- **Command**: `cowrie-analyze snowshoe`
- **Location**: Extend `cowrieprocessor/cli/` or create new `analyze.py`
- **Parameters**:
  - `--window`: Time window (24h, 48h, 7d)
  - `--sensitivity`: Detection threshold (0.7 default)
  - `--output`: JSON output file
  - `--sensor`: Specific sensor filter

#### 3.2 Reporting Integration
- Add snowshoe section to existing report builders
- Export snowshoe statistics via `cowrie-report snowshoe`
- Integrate with MCP statistics

### Phase 4: Integration & Testing (2 days)

#### 4.1 StatusEmitter Integration
- Add snowshoe detection metrics to telemetry
- Track detection performance and accuracy
- Monitor processing time and resource usage

#### 4.2 Unit Tests ✅ COMPLETED
- **Location**: `tests/unit/test_snowshoe_detection.py`
- Test individual detection algorithms
- Test scoring methodology
- Test edge cases and error handling
- Mock geographic and enrichment data

#### 4.3 Integration Tests ✅ COMPLETED
- **Location**: `tests/integration/test_snowshoe_integration.py`
- Test with real honeypot data patterns
- Validate against known snowshoe campaigns
- Test database integration
- Test CLI commands

#### 4.4 Performance Tests ✅ COMPLETED
- **Location**: `tests/performance/test_snowshoe_performance.py`
- Test with 100k+ sessions
- Validate <30 second processing time requirement
- Memory usage optimization
- Concurrent processing tests

## Phase 5: Botnet Coordination Detection ✅ COMPLETED

### 5.1 Botnet Detector Implementation ✅ COMPLETED
- **Location**: `cowrieprocessor/threat_detection/botnet.py`
- **Class**: `BotnetCoordinatorDetector`
- **Features**:
  - Credential reuse analysis (username/password patterns across IPs)
  - Command sequence similarity using TF-IDF and cosine similarity
  - Temporal coordination detection using DBSCAN clustering
  - Geographic clustering analysis for botnet infrastructure
  - Composite scoring with weighted indicators
  - Support for private IPs (compromised internal networks)

### 5.2 CLI Integration ✅ COMPLETED
- **Location**: `cowrieprocessor/cli/analyze.py`
- **Command**: `cowrie-analyze botnet`
- **Parameters**:
  - `--credential-threshold`: Minimum IPs sharing credentials (default: 3)
  - `--command-similarity`: Command sequence similarity threshold (default: 0.7)
  - `--sensitivity`: Overall detection sensitivity (default: 0.6)
  - `--window`: Analysis time window in hours (default: 24)
  - `--store-results`: Store results in database
  - `--output`: JSON report output file

### 5.3 Real Data Analysis ✅ COMPLETED
- **Tested with**: Actual Cowrie logs from `/mnt/dshield/aws-eastus-dshield/NSM/cowrie`
- **Verified**: Credential reuse patterns (e.g., `ubnt:ubnt` across multiple IPs)
- **Confirmed**: Command similarity detection for coordinated attacks
- **Validated**: Temporal coordination and geographic clustering

### 5.4 Detection Capabilities ✅ COMPLETED
- **Credential Reuse**: Detects shared username/password combinations across IPs
- **Command Similarity**: Identifies similar command sequences using machine learning
- **Temporal Coordination**: Finds coordinated timing patterns using DBSCAN
- **Geographic Clustering**: Identifies botnet infrastructure patterns
- **Composite Scoring**: Weighted algorithm prioritizing credential reuse (40%) and command similarity (30%)

### Phase 5: Security & Validation (1 day)

#### 5.1 Security Compliance
- Input validation for all parameters
- Secure handling of IP addresses and geographic data
- Rate limiting for database queries
- Secure logging (sanitize sensitive data)

#### 5.2 Validation & Tuning
- Test against synthetic snowshoe patterns
- Validate detection accuracy (80%+ requirement)
- Optimize false positive rate (<10% requirement)
- Performance benchmarking

## Technical Specifications

### Detection Algorithm Details

```python
class SnowshoeDetector:
    def detect(self, sessions: List[SessionSummary], window_hours: int = 24) -> dict:
        return {
            "is_likely_snowshoe": score > 0.7,
            "confidence_score": float,
            "single_attempt_ips": List[str],
            "low_volume_ips": List[str],
            "coordinated_timing": bool,
            "geographic_spread": float,
            "recommendation": str
        }
```

### Scoring Methodology
- **Single-attempt ratio**: 40% weight
- **Geographic diversity**: 30% weight  
- **Time coordination**: 20% weight
- **Low volume ratio**: 10% weight

### Database Schema
```sql
CREATE TABLE snowshoe_detections (
    id INTEGER PRIMARY KEY,
    detection_time TIMESTAMP,
    window_start TIMESTAMP,
    window_end TIMESTAMP,
    confidence_score FLOAT,
    unique_ips INTEGER,
    single_attempt_ips INTEGER,
    geographic_spread FLOAT,
    indicators JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### CLI Integration
```bash
# Detect snowshoe campaigns
uv run cowrie-analyze snowshoe --window 24h --sensitivity 0.7

# Export snowshoe statistics
uv run cowrie-report snowshoe --format json --output snowshoe_report.json
```

## Dependencies & Prerequisites

### Required Dependencies
- **scikit-learn**: For DBSCAN clustering
- **pandas**: For data analysis (if not already present)
- **numpy**: For numerical operations

### Existing Dependencies
- **SQLAlchemy**: Database ORM
- **pytest**: Testing framework
- **Click/argparse**: CLI framework

## Success Criteria

1. **Detection Accuracy**: 80%+ of known snowshoe campaigns detected
2. **False Positive Rate**: <10% false positives
3. **Performance**: Process 100k sessions in <30 seconds
4. **Integration**: Seamless integration with MCP statistics
5. **Security**: Full compliance with security requirements
6. **Testing**: 80%+ test coverage

## Implementation Checklist

### Phase 1: Core Detection Algorithm ✅ COMPLETED
- [x] Create `cowrieprocessor/threat_detection/` module
- [x] Implement `SnowshoeDetector` class
- [x] Add volume analysis for single-attempt IPs
- [x] Implement time clustering detection
- [x] Add geographic diversity analysis
- [x] Implement behavioral similarity analysis
- [x] Create composite scoring algorithm

### Phase 2: Database Integration ✅ COMPLETED
- [x] Add `SnowshoeDetection` model to `models.py`
- [x] Create database migration
- [x] Test migration on SQLite and PostgreSQL
- [x] Add proper indexes for performance

### Phase 3: CLI Integration ✅ COMPLETED
- [x] Create new CLI command `cowrie-analyze`
- [x] Add snowshoe subcommand
- [x] Integrate with reporting system
- [x] Add MCP statistics export

### Phase 4: Integration & Testing
- [ ] Add StatusEmitter metrics
- [ ] Create comprehensive unit tests
- [ ] Create integration tests
- [ ] Create performance tests
- [ ] Validate against synthetic data

### Phase 5: Security & Validation
- [ ] Implement input validation
- [ ] Add secure logging
- [ ] Performance benchmarking
- [ ] Final validation testing

## Risk Mitigation

### Performance Risks
- Use efficient database queries with proper indexing
- Implement caching for repeated calculations
- Batch processing for large datasets

### Security Risks
- Validate all inputs and sanitize outputs
- Follow existing security patterns
- Implement proper error handling

### Integration Risks
- Follow existing code patterns and conventions
- Maintain backward compatibility
- Comprehensive testing at each phase

## Timeline Summary

- **Phase 1 (Core Algorithm)**: 3 days
- **Phase 2 (Database)**: 2 days  
- **Phase 3 (CLI)**: 1 day
- **Phase 4 (Integration & Testing)**: 2 days
- **Phase 5 (Security & Validation)**: 1 day

**Total Estimated Effort**: 9 days

## Notes & Considerations

### Security Requirements
- Follow all security-focused development rules
- Never commit credentials or sensitive data
- Validate all external inputs
- Use secure logging patterns
- Implement proper rate limiting

### Code Quality Standards
- Follow Google-style docstrings
- Maintain type hints throughout
- Use snake_case for functions, CamelCase for classes
- Keep line length ≤120 characters
- Achieve 80%+ test coverage

### Integration Patterns
- Follow existing CLI patterns
- Use established database patterns
- Integrate with existing reporting system
- Maintain backward compatibility
- Follow existing error handling patterns

---

**This document serves as the source of truth for implementing Issue #31. All implementation decisions should reference this plan and update it as needed during development.**
