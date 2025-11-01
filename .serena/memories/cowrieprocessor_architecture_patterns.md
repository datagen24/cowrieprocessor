# CowrieProcessor Architecture & Code Patterns

## Project Structure

```
cowrieprocessor/
├── cli/              # Command-line interfaces (cowrie-loader, cowrie-report, etc.)
├── db/               # Database layer (models, engine, migrations)
├── loader/           # Data ingestion pipelines (bulk, delta)
├── enrichment/       # API enrichment services (VT, DShield, SPUR, HIBP)
├── reporting/        # Report generation (DAL, builders, ES publisher)
├── threat_detection/ # ML-based detection (longtail, snowshoe, botnet)
├── features/         # Feature extraction (aggregation, provider classification)
├── vectorization/    # Text normalization (defanging)
├── utils/            # Shared utilities
└── telemetry/        # OpenTelemetry tracing
```

## SQLAlchemy Patterns

### Import Pattern
```python
from cowrieprocessor.db import (
    SessionSummary,
    RawEvent,
    SSHKeyIntelligence,
    PasswordTracking,
    CommandStats
)
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import Session, sessionmaker
```

### Query Pattern (SQLAlchemy 2.0 style)
```python
# ✅ CORRECT: Use select() not session.query()
stmt = select(SessionSummary).where(
    SessionSummary.first_event_at >= start_date,
    SessionSummary.first_event_at < end_date
)
results = session.execute(stmt).scalars().all()

# ❌ WRONG: Old SQLAlchemy 1.x style
results = session.query(SessionSummary).filter(...)  # Deprecated
```

### JSON Field Access (SQLAlchemy)
```python
# PostgreSQL JSON operators
from sqlalchemy.dialects.postgresql import JSONB

# Text extraction
stmt = select(
    SessionSummary.session_id,
    SessionSummary.enrichment['country'].astext.label('country'),
    SessionSummary.enrichment['dshield']['attacks'].astext.label('attacks')
)

# Or raw SQL for complex JSON
from sqlalchemy import text
stmt = text("""
    SELECT enrichment->>'country' as country
    FROM session_summaries
""")
```

## Configuration File Location

**Current Standard** (as of Oct 2025 refactoring):
- Configuration directory: `config/` at project root
- Main config file: `config/sensors.toml`
- Fallback: `sensors.toml` at project root (legacy)

**All CLI tools** auto-detect config location:
```python
config_path = Path("config/sensors.toml")
if not config_path.exists():
    config_path = Path("sensors.toml")  # Fallback
```

## Date/Time Handling

### Timezone-Aware Datetimes
```python
from datetime import datetime, timezone

# ✅ CORRECT: Always use timezone-aware datetimes
start_date = datetime(2024, 11, 1, tzinfo=timezone.utc)

# SQLAlchemy model fields are DATETIME with timezone=True
first_event_at = Column(DateTime(timezone=True))
```

### Normalize for SQLite Compatibility
```python
def _normalize_datetime(dt: datetime) -> datetime:
    """Return timezone-naive UTC for SQLite comparisons."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
```

## Feature Engineering Patterns

### Pattern 1: Aggregation Functions
Located in `cowrieprocessor/features/aggregation.py`:

```python
def aggregate_features(sessions: List[SessionSummary], classifier) -> Dict[str, Any]:
    """13-dimensional feature vector extraction."""
    return {
        "ip_count": len(set(s.src_ip for s in sessions)),
        "geographic_spread_km": calculate_geographic_spread(sessions),
        "password_entropy": calculate_entropy([s.password_hash for s in sessions]),
        "cloud_provider_ratio": calculate_provider_ratio(sessions, classifier),
        # ... 13 total features
    }
```

### Pattern 2: Provider Classification
Located in `cowrieprocessor/features/provider_classification.py`:

```python
from dataclasses import dataclass

@dataclass
class ProviderFeatures:
    is_cloud_provider: bool
    is_vpn_provider: bool
    is_tor_exit: bool
    cloud_confidence: str  # "high", "medium", "low", "none"
    vpn_confidence: str
    tor_confidence: str

def classify_provider(enrichment: Dict) -> ProviderFeatures:
    # Extract from DShield/SPUR enrichment data
    # Return confidence levels based on data freshness
```

## CLI Tool Architecture

### Entry Point Pattern
All CLI tools use Click framework:

```python
import click
from pathlib import Path

@click.command()
@click.option('--db', required=True, help='Database connection string')
@click.option('--sensor', required=True, help='Sensor identifier')
@click.option('--last-days', default=1, help='Days to process')
def main(db: str, sensor: str, last_days: int) -> None:
    """CLI tool docstring."""
    # Implementation
    pass

if __name__ == '__main__':
    main()
```

### Standard Options
Common across all CLI tools:
- `--db`: Database connection string (SQLite or PostgreSQL)
- `--config`: Path to sensors.toml (default: config/sensors.toml)
- `--verbose`: Enable verbose output
- `--progress`: Show progress bars

## Data Ingestion Patterns

### Bulk Load (Initial Import)
```python
# cowrieprocessor/loader/bulk.py
def bulk_load(
    log_paths: List[Path],
    db_url: str,
    status_dir: Path,
    enrichment_config: EnrichmentConfig
) -> LoaderStats:
    # Process all files from scratch
    # Emit status JSON for monitoring
    # Return stats (sessions processed, errors, etc.)
```

### Delta Load (Incremental)
```python
# cowrieprocessor/loader/delta.py
def delta_load(
    log_paths: List[Path],
    db_url: str,
    status_dir: Path,
    cursor_file: Path
) -> LoaderStats:
    # Resume from last processed offset
    # Only process new events since last run
```

## Enrichment Service Patterns

### Cache Layer
All enrichment services use disk-based caching:

```python
# cowrieprocessor/enrichment/cache.py
class EnrichmentCache:
    def __init__(self, cache_dir: Path, ttl_days: int):
        self.cache_dir = cache_dir  # Sharded by service
        self.ttl_days = ttl_days
    
    def get(self, key: str) -> Optional[Dict]:
        # Check cache file
        # Validate TTL
        # Return cached result or None
    
    def set(self, key: str, value: Dict) -> None:
        # Write to cache with timestamp
```

### Rate Limiting
Token bucket algorithm:

```python
# cowrieprocessor/enrichment/rate_limiting.py
class TokenBucketRateLimiter:
    def __init__(self, rate: float, burst: int):
        self.rate = rate      # Tokens per second
        self.burst = burst    # Max tokens
    
    def acquire(self, tokens: int = 1) -> bool:
        # Wait if necessary
        # Return True when tokens available
```

## Testing Patterns

### Unit Tests
```python
# tests/unit/test_feature_aggregation.py
import pytest
from cowrieprocessor.features.aggregation import aggregate_features

def test_aggregate_features_basic():
    sessions = create_mock_sessions()
    features = aggregate_features(sessions, mock_classifier)
    
    assert features['ip_count'] == 5
    assert features['password_entropy'] > 0
```

### Integration Tests with Mock APIs
```python
# tests/integration/test_enrichment_flow.py
from unittest.mock import patch

@patch('cowrieprocessor.enrichment.virustotal_handler.VTClient')
def test_enrichment_without_network(mock_vt):
    mock_vt.return_value.get_file_report.return_value = {
        'positives': 5,
        'total': 60
    }
    
    # Test enrichment flow with mocked API
```

## Error Handling Patterns

### Dead Letter Queue
Failed events go to DLQ for later reprocessing:

```python
# cowrieprocessor/db/models.py
class DeadLetterEvent(Base):
    __tablename__ = "dead_letter_events"
    
    id = Column(Integer, primary_key=True)
    original_event_id = Column(Integer)
    reason = Column(String(512))  # Error message
    payload = Column(JSON)        # Original event
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime)
```

### Graceful Degradation
Enrichment failures don't block ingestion:

```python
try:
    enrichment_data = enrich_session(session)
except EnrichmentError as e:
    logger.warning(f"Enrichment failed: {e}")
    enrichment_data = {}  # Continue with empty enrichment

session_summary.enrichment = enrichment_data
```

## Status Emitter Pattern

Long-running operations emit JSON status files:

```python
# cowrieprocessor/utils/status.py
class StatusEmitter:
    def __init__(self, status_dir: Path, process_name: str):
        self.status_file = status_dir / f"{process_name}.json"
    
    def emit(self, stats: Dict) -> None:
        with open(self.status_file, 'w') as f:
            json.dump({
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'status': 'running',
                'progress': stats
            }, f)
```

Monitor with:
```bash
python scripts/production/monitor_progress.py --status-dir /path/to/status --refresh 2
```

## Telemetry Patterns

### OpenTelemetry Integration
```python
from cowrieprocessor.telemetry import start_span

def process_batch(sessions):
    with start_span("cowrie.loader.batch", {"batch_size": len(sessions)}):
        # Processing logic
        for session in sessions:
            with start_span("cowrie.loader.session", {"session_id": session.id}):
                process_session(session)
```

## Key Architectural Decisions

### 1. ORM-First Approach
- All database operations use SQLAlchemy 2.0 ORM
- No raw SQL except for stored procedures
- Benefits: Type safety, database portability, migrations

### 2. Multi-Layer Database Design
- RawEvent: Immutable event storage
- SessionSummary: Aggregated metrics
- Specialized tables: SSH keys, passwords, commands
- Benefits: Normalized, efficient queries, actor tracking

### 3. Feature Flags
- `USE_NEW_ENRICHMENT`: Route enrichment pipeline
- `USE_LEGACY_PROCESSOR`: Fallback to archive/process_cowrie.py
- Benefits: Gradual migration, rollback capability

### 4. Dependency Injection
- Services use constructor injection
- Benefits: Testability, flexibility

### 5. Immutable Event Store
- RawEvent is append-only
- Benefits: Audit trail, reprocessing capability

## Common Pitfalls to Avoid

### ❌ Don't assume schema structure
Always check ORM models before writing queries

### ❌ Don't use session.query()
Use select() with SQLAlchemy 2.0 style

### ❌ Don't ignore timezone
Always use timezone-aware datetimes

### ❌ Don't bypass enrichment cache
Cache prevents API rate limit issues

### ❌ Don't assume src_ip in SessionSummary
It's in RawEvent.payload JSON

## Phase 1 Specific Patterns

### Feature Discovery Queries
- Always start with SessionSummary for aggregates
- Join with specialized tables for details
- Use 2024-11-01 to 2025-11-01 date range
- Export to CSV for Python analysis

### MITRE ATT&CK Mapping (Phase 1B)
Will follow pattern:
```python
# cowrieprocessor/ttp/mitre_mapper.py
class MITREMapper:
    def __init__(self, technique_db: Dict):
        self.techniques = technique_db
    
    def map_command(self, command: str) -> List[MITRETechnique]:
        # Pattern matching to MITRE techniques
        # Return T1098, T1053, etc.
```

---

**Memory Created**: 2025-11-01
**Purpose**: Reference for architectural patterns and common code patterns
**Critical for**: Phase 1B MITRE mapper, feature engineering, query optimization
