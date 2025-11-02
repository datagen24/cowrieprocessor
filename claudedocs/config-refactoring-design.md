# Configuration System Refactoring Design

**Status**: Design
**Type**: Architecture Enhancement
**Priority**: P3 - Medium (Backlog)
**Created**: 2025-11-02
**Related**: ADR-005 Redis Configuration Integration (commit 778f6f5)

## Executive Summary

Refactor the current `sensors.toml` monolithic configuration file into a modular, domain-separated configuration system with three distinct files: `sensors.toml` (sensor-specific), `global.toml` (infrastructure), and `features.toml` (feature flags and enrichment).

## Problem Statement

### Current State Issues

1. **Configuration Ambiguity**: The `sensors.toml` file name suggests sensor-only configuration, but it actually contains:
   - Sensor-specific settings (log paths, API keys per sensor)
   - Global infrastructure settings (database URL, Redis cache)
   - Feature configuration (enrichment services, snowshoe detection)

2. **Maintenance Challenges**:
   - Difficult to distinguish between infrastructure and sensor settings
   - No clear separation of concerns
   - Harder to deploy infrastructure changes vs sensor changes
   - Risk of infrastructure misconfiguration when editing sensor settings

3. **Scalability Concerns**:
   - Adding new global features clutters sensor configuration
   - Infrastructure settings scattered throughout file
   - No standardized location for feature flags

### Recent Pain Point

During ADR-005 implementation, Redis configuration was initially only available via environment variables because the filename `sensors.toml` created an incorrect assumption that it was sensor-only. This led to the realization that global infrastructure settings should be centralized and clearly separated.

## Design Goals

1. **Clarity**: Clear separation of concerns with self-documenting file names
2. **Maintainability**: Easy to locate and modify specific configuration types
3. **Scalability**: Simple to add new sensors, infrastructure, or features
4. **Backward Compatibility**: Smooth migration path from current configuration
5. **DRY Principle**: Eliminate configuration duplication across sensors
6. **Security**: Better secret management with clear boundaries

## Proposed Architecture

### Three-File Configuration System

```
config/
├── global.toml          # Infrastructure and system-wide settings
├── sensors.toml         # Sensor-specific configurations
└── features.toml        # Feature flags and enrichment settings
```

### File Responsibilities

#### 1. `global.toml` - Infrastructure Configuration

**Purpose**: System-wide infrastructure settings that apply to all sensors

**Contents**:
- Database connection settings
- Redis cache configuration
- Elasticsearch connection
- Logging and telemetry settings
- System-wide directories (cache, logs, reports)
- Performance tuning (memory limits, concurrency)

**Example Structure**:
```toml
# global.toml - Infrastructure Configuration

[database]
url = "postgresql://user:pass@host:port/database"
# Or: url = "sqlite:///path/to/db.sqlite"
pool_size = 10
pool_timeout = 30
max_overflow = 20

[cache]
# Redis L1 Cache (ADR-005)
redis_enabled = true
redis_host = "localhost"
redis_port = 6379
redis_db = 0
redis_ttl_seconds = 3600
redis_password = "env:REDIS_PASSWORD"

# Database L2 Cache (ADR-005)
db_cache_enabled = true
db_cache_ttl_days = 30

# Filesystem L3 Cache
filesystem_cache_enabled = true
filesystem_cache_dir = "/mnt/dshield/data/cache"

[elasticsearch]
enabled = false
host = "localhost"
port = 9200
username = "elastic"
password = "env:ES_PASSWORD"
# Or cloud deployment:
# cloud_id = "deployment:dXMtZWFzdC0xLmF3cy5mb3VuZC5pbyQ..."
# api_key = "env:ES_API_KEY"

[directories]
cache_dir = "/mnt/dshield/data/cache"
log_dir = "/mnt/dshield/data/logs"
report_dir = "/mnt/dshield/reports"
temp_dir = "/mnt/dshield/data/temp"

[performance]
max_workers = 4
memory_warning_threshold = 0.75
batch_size = 1000
enable_parallel_processing = true

[logging]
level = "INFO"
format = "json"  # or "text"
enable_telemetry = true
telemetry_endpoint = "http://localhost:4318"

[security]
enable_secret_references = true
# Supported: env:, file:, op://, aws-sm://, vault://, sops://
secret_scan_on_startup = true
```

#### 2. `sensors.toml` - Sensor Configuration

**Purpose**: Individual sensor definitions with sensor-specific settings only

**Contents**:
- Sensor name and log path
- Per-sensor API keys (with secret references)
- Per-sensor processing parameters (summarizedays, etc.)
- Per-sensor overrides (optional report directory)

**Example Structure**:
```toml
# sensors.toml - Sensor-Specific Configuration

[[sensor]]
name = "aws-eastus-dshield"
logpath = "/mnt/dshield/aws-eastus-dshield/NSM/cowrie"
summarizedays = 360

# API Keys (secret references recommended)
email = "steve@scpeterson.com"
vtapi = "env:VT_API_KEY_AWS_EAST"
urlhausapi = "env:URLHAUS_API_KEY"
spurapi = "env:SPUR_API_KEY"

# Optional per-sensor overrides
# report_dir = "/mnt/dshield/reports/aws-eastus"

[[sensor]]
name = "inter-nj01-dshield"
logpath = "/mnt/dshield/inter-nj01-dshield/NSM/cowrie"
summarizedays = 190

# API Keys
email = "steve@scpeterson.com"
vtapi = "env:VT_API_KEY_INTER_NJ"
urlhausapi = "env:URLHAUS_API_KEY"
spurapi = "env:SPUR_API_KEY"

[[sensor]]
name = "gcp-uscentral-dshield"
logpath = "/mnt/dshield/gcp-uscentral-dshield/NSM/cowrie"
summarizedays = 30
enabled = false  # Disabled sensor

# Minimal configuration for disabled sensors
email = "steve@scpeterson.com"
```

#### 3. `features.toml` - Feature Flags & Enrichment

**Purpose**: Feature-specific configuration and enrichment service settings

**Contents**:
- Feature flags (enable/disable features)
- Enrichment service defaults
- Threat detection configuration (snowshoe, longtail, botnet)
- Rate limiting settings
- Report generation settings

**Example Structure**:
```toml
# features.toml - Feature Flags and Enrichment Configuration

[enrichment]
enabled = true
mode = "adaptive"  # "adaptive", "always", "never"

# Default enrichment services (can be overridden per sensor)
[enrichment.defaults]
enable_virustotal = true
enable_dshield = true
enable_urlhaus = true
enable_spur = true
enable_hibp_passwords = true
enable_ssh_key_tracking = true

# Service-specific rate limits
[enrichment.rate_limits]
virustotal_rate = 4      # requests per minute
virustotal_burst = 1
dshield_rate = 30
dshield_burst = 5
urlhaus_rate = 30
urlhaus_burst = 5
spur_rate = 60
spur_burst = 10

# Cache TTLs (can override global cache settings)
[enrichment.cache_ttls]
virustotal_days = 30
dshield_days = 7
urlhaus_days = 3
spur_days = 14
hibp_days = 90

[threat_detection]
enabled = true

# Snowshoe Spam Detection (ADR-006)
[threat_detection.snowshoe]
enabled = true
use_dshield = true
use_spur = true
max_enrichment_age_days = 365
treat_stale_as_unknown = false

# Cloud provider keywords for ASN matching
cloud_provider_keywords = [
    "amazon", "aws",
    "google", "gcp",
    "azure", "microsoft",
    "digitalocean",
    "linode",
    "vultr",
    "ovh",
    "hetzner",
    "scaleway"
]

# Longtail Analysis (ML-based anomaly detection)
[threat_detection.longtail]
enabled = true
min_sessions_for_analysis = 100
anomaly_threshold = 0.85
feature_extraction = "full"  # "full", "basic", "minimal"

# Botnet Detection
[threat_detection.botnet]
enabled = true
command_similarity_threshold = 0.9
time_window_hours = 24

[reporting]
enabled = true
formats = ["html", "json", "elasticsearch"]

# Report generation settings
[reporting.schedule]
daily_enabled = true
weekly_enabled = true
monthly_enabled = true

[reporting.elasticsearch]
publish_enabled = false
ilm_policy = "cowrie-reports"
index_prefix = "cowrie"
retention_days = 90

[features]
# Experimental or toggle-able features
enable_dlq_processing = true
enable_parallel_enrichment = true
enable_adaptive_rate_limiting = true  # ADR-005
enable_hybrid_cache = true             # ADR-005
enable_session_clustering = false      # Future feature
enable_real_time_alerting = false      # Future feature
```

## Implementation Plan

### Phase 1: Create Configuration Loader (Week 1)

**Goal**: Build unified configuration loader supporting both old and new formats

**Tasks**:
1. Create `cowrieprocessor/utils/config_loader.py`
   - `load_global_config()` → loads global.toml
   - `load_sensors_config()` → loads sensors.toml
   - `load_features_config()` → loads features.toml
   - `load_legacy_config()` → loads old sensors.toml (backward compat)
   - `merge_configs()` → merges all sources with priority

2. Implement configuration priority system:
   - Environment variables (highest priority)
   - New multi-file system (global.toml, sensors.toml, features.toml)
   - Legacy sensors.toml (fallback for migration)
   - Default values (lowest priority)

3. Add configuration validation:
   - Schema validation using pydantic or dataclasses
   - Required field checking
   - Type validation
   - Secret reference validation

4. Unit tests for configuration loading:
   - Test all priority combinations
   - Test backward compatibility
   - Test error handling
   - Test secret resolution

**Files**:
- `cowrieprocessor/utils/config_loader.py` (NEW)
- `cowrieprocessor/utils/config_schema.py` (NEW - validation models)
- `tests/unit/test_config_loader.py` (NEW)

### Phase 2: Create Example Configuration Files (Week 1)

**Goal**: Provide template configurations for users

**Tasks**:
1. Create `config/global.example.toml`
   - Document all global settings
   - Show secret reference examples
   - Include performance tuning guidance

2. Create `config/sensors.example.toml`
   - Show multiple sensor configurations
   - Document sensor-specific overrides
   - Show disabled sensor example

3. Create `config/features.example.toml`
   - Document all feature flags
   - Show enrichment configuration
   - Document threat detection settings

4. Update `config/sensors.toml` → `config/sensors.toml.legacy`
   - Preserve as migration reference
   - Add deprecation notice

**Files**:
- `config/global.example.toml` (NEW)
- `config/sensors.example.toml` (REPLACE)
- `config/features.example.toml` (NEW)
- `config/sensors.toml.legacy` (RENAMED from sensors.toml)

### Phase 3: Migrate CLI Tools (Week 2)

**Goal**: Update all CLI tools to use new configuration system

**Tasks**:
1. Update `cowrieprocessor/cli/db_config.py`
   - Use `load_global_config()` for database settings
   - Maintain backward compatibility with legacy config

2. Update `cowrieprocessor/enrichment/hybrid_cache.py`
   - Use `load_global_config()` for Redis settings
   - Already partially done (commit 778f6f5)

3. Update all CLI entry points:
   - `cowrie-loader` → use new config
   - `cowrie-enrich` → use new config
   - `cowrie-report` → use new config
   - `cowrie-db` → use new config
   - `cowrie-health` → use new config

4. Update `scripts/production/orchestrate_sensors.py`
   - Load from all three config files
   - Validate merged configuration
   - Show deprecation warning if using legacy config

**Files**:
- `cowrieprocessor/cli/*.py` (UPDATE all CLI tools)
- `scripts/production/orchestrate_sensors.py` (UPDATE)

### Phase 4: Documentation & Migration Guide (Week 2)

**Goal**: Help users migrate to new configuration system

**Tasks**:
1. Create migration guide: `docs/configuration/MIGRATION.md`
   - Explain new configuration structure
   - Provide migration steps
   - Show before/after examples
   - Document deprecation timeline

2. Update main documentation:
   - `CLAUDE.md` → update configuration section
   - `README.md` → update quick start
   - `docs/configuration/README.md` → comprehensive config docs

3. Add configuration validation tool:
   - `scripts/validate_config.py` → validate new config files
   - Check for missing required fields
   - Warn about deprecated fields

4. Create automated migration script:
   - `scripts/migrate_config.py` → split sensors.toml into three files
   - Parse legacy format
   - Generate new format files
   - Validate output

**Files**:
- `docs/configuration/MIGRATION.md` (NEW)
- `docs/configuration/README.md` (NEW)
- `scripts/validate_config.py` (NEW)
- `scripts/migrate_config.py` (NEW)
- `CLAUDE.md` (UPDATE)
- `README.md` (UPDATE)

### Phase 5: Testing & Validation (Week 3)

**Goal**: Ensure backward compatibility and correct behavior

**Tasks**:
1. Integration tests:
   - Test legacy config loading
   - Test new multi-file config loading
   - Test configuration merging and priority
   - Test environment variable overrides

2. End-to-end workflow tests:
   - Test cowrie-loader with new config
   - Test enrichment with new config
   - Test reporting with new config

3. Performance testing:
   - Benchmark config loading time
   - Ensure no regression vs current system

4. User acceptance testing:
   - Test migration script on real configurations
   - Validate all examples work correctly

**Files**:
- `tests/integration/test_config_integration.py` (NEW)
- `tests/integration/test_config_migration.py` (NEW)

### Phase 6: Deprecation & Rollout (Week 4)

**Goal**: Smooth transition with clear communication

**Tasks**:
1. Add deprecation warnings:
   - Detect legacy config usage
   - Print migration instructions
   - Set deprecation timeline (e.g., "legacy support ends in 6 months")

2. Update release notes:
   - Document new configuration system
   - Highlight benefits
   - Link to migration guide

3. Provide rollback capability:
   - Keep legacy config loader functional
   - Document rollback procedure

**Timeline**:
- Week 1-2: Implementation
- Week 3: Testing
- Week 4: Documentation & rollout preparation
- Ongoing: Support legacy config for 6 months

## Success Criteria

### Functional Requirements

- ✅ Configuration loads from all three files (global, sensors, features)
- ✅ Legacy `sensors.toml` continues to work (backward compatibility)
- ✅ Environment variables override all file-based configuration
- ✅ Secret references work across all config files
- ✅ Configuration validation catches errors before runtime
- ✅ All CLI tools work with new configuration system

### Non-Functional Requirements

- ✅ Configuration loading adds <10ms overhead vs current system
- ✅ Migration script successfully converts existing configs
- ✅ 100% test coverage for configuration loading logic
- ✅ Comprehensive documentation for users
- ✅ Zero breaking changes for existing deployments

## Benefits

### For Developers

1. **Clarity**: Clear separation between infrastructure, sensors, and features
2. **Maintainability**: Easy to locate and modify specific configuration types
3. **Testability**: Easier to test individual configuration domains
4. **Extensibility**: Simple to add new global or feature settings

### For Users

1. **Discoverability**: Self-documenting file names
2. **Safety**: Less risk of misconfiguring infrastructure when editing sensors
3. **Flexibility**: Can override at multiple levels (global → sensor → environment)
4. **Security**: Better secret management with clear boundaries

### For Operations

1. **Deployment**: Separate deployment of infrastructure vs sensor changes
2. **Scalability**: Easy to manage many sensors without file bloat
3. **Monitoring**: Feature flags enable gradual rollouts
4. **Troubleshooting**: Clear configuration boundaries

## Risks & Mitigation

### Risk 1: Migration Complexity

**Description**: Users may struggle to migrate existing configurations

**Mitigation**:
- Provide automated migration script
- Maintain backward compatibility for 6 months
- Comprehensive migration guide with examples
- Detect legacy config and show helpful warnings

### Risk 2: Configuration Confusion

**Description**: Users unsure which file to edit for specific settings

**Mitigation**:
- Clear documentation with decision tree
- Validation errors show which file to edit
- Example files demonstrate correct placement
- File-level comments explain responsibilities

### Risk 3: Breaking Changes

**Description**: Existing deployments could break

**Mitigation**:
- Legacy config loader remains functional
- All CLI tools detect and support legacy format
- Deprecation warnings, not errors
- Extensive testing before rollout

### Risk 4: Performance Regression

**Description**: Loading three files instead of one could slow startup

**Mitigation**:
- Benchmark configuration loading
- Implement caching if needed
- Load files in parallel
- Target <10ms overhead

## Future Enhancements

1. **Configuration Hot-Reload**: Detect config changes without restart
2. **Configuration API**: REST API for runtime configuration updates
3. **Configuration Versioning**: Track configuration changes over time
4. **Configuration Templates**: Pre-built configs for common scenarios
5. **Configuration Validation Service**: Standalone config validator
6. **Configuration Encryption**: Encrypt entire config files, not just secrets

## Alternatives Considered

### Alternative 1: Single File with Namespaces

**Approach**: Keep `sensors.toml` but organize with clear TOML namespaces

**Pros**:
- No file splitting required
- Simpler migration (just reorganize sections)
- Single source of truth

**Cons**:
- File becomes very large with many sensors
- Still ambiguous what "sensors.toml" contains
- Harder to deploy infrastructure changes separately
- **Rejected**: Doesn't solve clarity or scalability issues

### Alternative 2: Directory-Based Configuration

**Approach**: `config/global/`, `config/sensors/`, `config/features/` directories

**Pros**:
- Very clear separation
- Can have multiple files per domain
- Extremely scalable

**Cons**:
- Overly complex for current needs
- Harder to understand for simple deployments
- More code to maintain
- **Rejected**: Over-engineered for current requirements

### Alternative 3: Keep Current System

**Approach**: Do nothing, accept current limitations

**Pros**:
- No migration required
- No development effort
- No risk of breaking changes

**Cons**:
- Configuration ambiguity remains
- Scalability issues worsen over time
- Infrastructure settings continue to be scattered
- **Rejected**: Technical debt will compound

## References

- **ADR-005**: Hybrid Cache & Adaptive Rate Limiting (commit fd6d3ee)
- **Commit 778f6f5**: Redis configuration in sensors.toml (motivation for this design)
- **sensors.example.toml**: Current configuration format
- **CLAUDE.md**: Configuration documentation section
- **TOML Specification**: https://toml.io/en/

## Appendix: Configuration Schema

### Global Configuration Schema

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class DatabaseConfig:
    url: str
    pool_size: int = 10
    pool_timeout: int = 30
    max_overflow: int = 20

@dataclass
class CacheConfig:
    redis_enabled: bool = True
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_ttl_seconds: int = 3600
    redis_password: Optional[str] = None
    db_cache_enabled: bool = True
    db_cache_ttl_days: int = 30
    filesystem_cache_enabled: bool = True
    filesystem_cache_dir: str = "/mnt/dshield/data/cache"

@dataclass
class GlobalConfig:
    database: DatabaseConfig
    cache: CacheConfig
    # ... other global settings
```

### Sensor Configuration Schema

```python
@dataclass
class SensorConfig:
    name: str
    logpath: str
    summarizedays: int = 1
    email: Optional[str] = None
    vtapi: Optional[str] = None
    urlhausapi: Optional[str] = None
    spurapi: Optional[str] = None
    enabled: bool = True
    report_dir: Optional[str] = None  # Override global
```

### Features Configuration Schema

```python
@dataclass
class EnrichmentConfig:
    enabled: bool = True
    mode: str = "adaptive"  # "adaptive", "always", "never"
    # ... enrichment settings

@dataclass
class FeaturesConfig:
    enrichment: EnrichmentConfig
    # ... other feature configs
```

---

**End of Design Document**
