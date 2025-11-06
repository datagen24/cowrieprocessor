# ASN Inventory Telemetry Design

**Author**: Claude Code (DevOps Architect)
**Date**: 2025-11-05
**Context**: PR adding ASN inventory auto-population from cascade enrichment
**Status**: Implementation Ready

---

## Executive Summary

The cascade enricher (`cascade_enricher.py`) now auto-populates the `asn_inventory` table during IP enrichment but lacks production observability. This design adds comprehensive OpenTelemetry-based metrics for capacity planning, performance monitoring, and operational visibility.

**Key Metrics**:
- Counter: `asn_inventory.records_created` - Track ASN creation rate
- Counter: `asn_inventory.records_updated` - Track ASN update frequency
- Gauge: `asn_inventory.total_count` - Current inventory size
- Histogram: `asn_inventory.operation_duration_ms` - Performance tracking

---

## Current State Analysis

### ASN Creation Points in cascade_enricher.py

**Location 1: Lines 169-175** (MaxMind enrichment)
```python
if maxmind_result.asn:
    self._ensure_asn_inventory(
        asn=maxmind_result.asn,
        organization_name=maxmind_result.asn_org,
        organization_country=maxmind_result.country_code,
        rir_registry=None,  # MaxMind doesn't provide RIR
    )
```

**Location 2: Lines 185-191** (Cymru fallback)
```python
if cymru_result and cymru_result.asn:
    self._ensure_asn_inventory(
        asn=cymru_result.asn,
        organization_name=cymru_result.asn_org,
        organization_country=cymru_result.country_code,
        rir_registry=cymru_result.registry,
    )
```

**Core Method: Lines 608-680** (`_ensure_asn_inventory`)
- Creates new ASN records (line 664-679)
- Updates existing records (line 646-661)
- Uses SELECT FOR UPDATE for concurrency safety

---

## Existing Telemetry Patterns

### Pattern 1: OpenTelemetry Spans (Recommended)

**File**: `cowrieprocessor/telemetry/otel.py`

```python
from cowrieprocessor.telemetry import start_span

with start_span("operation_name", attributes={"key": "value"}) as span:
    # Perform operation
    if span:
        span.set_attribute("result.count", count)
```

**Characteristics**:
- Graceful fallback when OpenTelemetry unavailable
- Automatic error recording and status tracking
- Distributed tracing support for complex workflows

### Pattern 2: StatusEmitter Metrics (Legacy)

**File**: `cowrieprocessor/enrichment/telemetry.py`

```python
class EnrichmentMetrics:
    cache_hits: int = 0
    cache_misses: int = 0
    # ... dataclass fields

class EnrichmentTelemetry:
    def record_api_call(self, service: str, success: bool, duration_ms: float):
        self.metrics.api_calls_total += 1
        self._emit_metrics()  # Writes to JSON status files
```

**Characteristics**:
- JSON status files in `/mnt/dshield/data/logs/status/`
- Used by monitoring scripts (`monitor_progress.py`)
- Dataclass-based metrics with StatusEmitter writer

---

## Recommended Approach: Hybrid Strategy

**Rationale**:
1. **OpenTelemetry spans** for distributed tracing and modern observability
2. **CascadeStats dataclass** for backward compatibility with existing monitoring
3. **Minimal performance impact** (<1% overhead per operation)

### Why Not Just OpenTelemetry?

The project has existing monitoring infrastructure (`monitor_progress.py`) that reads JSON status files. Adding OpenTelemetry spans **alongside** existing stats ensures:
- New metrics for production APM systems (Prometheus, Jaeger, etc.)
- Backward compatibility with current monitoring scripts
- Gradual migration path (no breaking changes)

---

## Detailed Design

### 1. Extend CascadeStats Dataclass

**Location**: `cascade_enricher.py:52-71`

**Add ASN-specific metrics**:
```python
@dataclass
class CascadeStats:
    """Statistics for cascade enrichment operations."""

    # Existing metrics
    total_ips: int = 0
    cache_hits: int = 0
    maxmind_hits: int = 0
    cymru_hits: int = 0
    greynoise_hits: int = 0
    errors: int = 0

    # NEW: ASN inventory metrics
    asn_records_created: int = 0
    asn_records_updated: int = 0
    asn_operation_duration_ms: float = 0.0
    asn_unique_seen: set[int] = field(default_factory=set)  # For gauge calculation
```

**Impact**: No breaking changes, purely additive.

### 2. Add OpenTelemetry Instrumentation

**Location**: `_ensure_asn_inventory()` method (lines 608-680)

**Implementation**:
```python
from cowrieprocessor.telemetry import start_span
import time

def _ensure_asn_inventory(
    self,
    asn: int,
    organization_name: str | None,
    organization_country: str | None,
    rir_registry: str | None,
) -> ASNInventory:
    """Create or update ASN inventory record with row-level locking."""

    start_time = time.perf_counter()

    with start_span(
        "cascade_enricher.ensure_asn_inventory",
        attributes={
            "asn.number": asn,
            "asn.organization": organization_name or "unknown",
            "asn.country": organization_country or "unknown",
            "asn.rir": rir_registry or "unknown",
        }
    ) as span:
        now = datetime.now(timezone.utc)

        # Existing SELECT FOR UPDATE logic
        stmt = select(ASNInventory).where(ASNInventory.asn_number == asn).with_for_update()
        existing = self.session.execute(stmt).scalar_one_or_none()

        if existing:
            # Update path
            existing.last_seen = now
            existing.updated_at = now

            if organization_name and not existing.organization_name:
                existing.organization_name = organization_name
            if organization_country and not existing.organization_country:
                existing.organization_country = organization_country
            if rir_registry and not existing.rir_registry:
                existing.rir_registry = rir_registry

            logger.debug(f"Updated ASN {asn} ({existing.organization_name})")
            self.session.flush()

            # NEW: Record metrics
            self._stats.asn_records_updated += 1
            if span:
                span.set_attribute("asn.operation", "update")

            result = existing
        else:
            # Create new ASN record
            new_asn = ASNInventory(
                asn_number=asn,
                organization_name=organization_name,
                organization_country=organization_country,
                rir_registry=rir_registry,
                first_seen=now,
                last_seen=now,
                unique_ip_count=0,
                total_session_count=0,
                enrichment={},
                created_at=now,
                updated_at=now,
            )
            self.session.add(new_asn)
            self.session.flush()
            logger.debug(f"Created ASN {asn} ({organization_name})")

            # NEW: Record metrics
            self._stats.asn_records_created += 1
            if span:
                span.set_attribute("asn.operation", "create")

            result = new_asn

        # Track unique ASNs seen (for gauge metric)
        self._stats.asn_unique_seen.add(asn)

        # Record operation duration
        duration_ms = (time.perf_counter() - start_time) * 1000
        self._stats.asn_operation_duration_ms += duration_ms

        if span:
            span.set_attribute("asn.operation_duration_ms", duration_ms)

        return result
```

**Key Points**:
- **Minimal overhead**: Only 2 lines added (start_time, duration calculation)
- **Graceful degradation**: `if span:` checks handle missing OpenTelemetry
- **Rich attributes**: ASN number, org name, country, RIR for filtering/grouping

### 3. Add Gauge Metric for Current Inventory Size

**Challenge**: Gauges require querying the database, which adds overhead.

**Solution**: Track unique ASNs seen during enrichment session, query on-demand only.

**Location**: `CascadeEnricher.__init__()` and `get_stats()`

```python
def get_stats(self) -> CascadeStats:
    """Get current cascade statistics.

    Returns:
        CascadeStats object with enrichment operation counts
    """
    # Return existing stats (already tracked during enrichment)
    return self._stats

def get_asn_inventory_size(self) -> int:
    """Query current ASN inventory size from database.

    This is an expensive operation (database query) and should be called
    sparingly (e.g., once per enrichment batch, not per IP).

    Returns:
        Total number of ASN records in asn_inventory table
    """
    from sqlalchemy import func
    count = self.session.query(func.count(ASNInventory.asn_number)).scalar()
    return count or 0
```

**Usage Pattern** (in CLI tools):
```python
# After batch enrichment completes
cascade = CascadeEnricher(...)
results = cascade.enrich_session_ips(session_id)

stats = cascade.get_stats()
print(f"ASNs created: {stats.asn_records_created}")
print(f"ASNs updated: {stats.asn_records_updated}")
print(f"Unique ASNs in batch: {len(stats.asn_unique_seen)}")

# Query total inventory size (expensive, do once per batch)
total_asns = cascade.get_asn_inventory_size()
print(f"Total ASN inventory size: {total_asns}")
```

---

## Metric Specifications

### Counter: `asn_inventory.records_created`

**Type**: Cumulative counter (monotonically increasing)
**Unit**: Count
**Labels**:
- `source`: `maxmind` | `cymru` (which enrichment source provided ASN)
- `country`: ISO 3166-1 alpha-2 country code (e.g., `US`, `CN`)
- `rir`: Regional Internet Registry (`ARIN`, `RIPE`, `APNIC`, `LACNIC`, `AFRINIC`, `unknown`)

**Purpose**: Track ASN creation rate for capacity planning

**Query Examples** (Prometheus):
```promql
# ASN creation rate (per minute)
rate(asn_inventory_records_created_total[5m]) * 60

# ASNs created by source
sum by (source) (asn_inventory_records_created_total)

# ASNs created by country
topk(10, sum by (country) (asn_inventory_records_created_total))
```

---

### Counter: `asn_inventory.records_updated`

**Type**: Cumulative counter
**Unit**: Count
**Labels**:
- `source`: `maxmind` | `cymru`
- `update_type`: `metadata_enrichment` | `timestamp_refresh`

**Purpose**: Track how often existing ASNs are updated with new data

**Query Examples**:
```promql
# ASN update rate
rate(asn_inventory_records_updated_total[5m]) * 60

# Update ratio (updates vs creates)
rate(asn_inventory_records_updated_total[5m]) / rate(asn_inventory_records_created_total[5m])
```

---

### Gauge: `asn_inventory.total_count`

**Type**: Gauge (can increase or decrease)
**Unit**: Count
**Labels**: None (global inventory size)

**Purpose**: Current ASN inventory size for dashboard visualization

**Implementation Strategy**:
- **Do NOT query on every enrichment** (too expensive)
- **Query once per enrichment batch** (e.g., after processing 1000 IPs)
- **Emit via StatusEmitter** for monitoring scripts

**Query Examples**:
```promql
# Current inventory size
asn_inventory_total_count

# Growth rate (ASNs per day)
deriv(asn_inventory_total_count[1d]) * 86400
```

---

### Histogram: `asn_inventory.operation_duration_ms`

**Type**: Histogram
**Unit**: Milliseconds
**Labels**:
- `operation`: `create` | `update`

**Buckets**: `[1, 5, 10, 25, 50, 100, 250, 500, 1000]` ms

**Purpose**: Track performance of ASN operations for bottleneck detection

**Query Examples**:
```promql
# P95 latency for ASN operations
histogram_quantile(0.95, rate(asn_inventory_operation_duration_ms_bucket[5m]))

# Slow operations (>100ms)
rate(asn_inventory_operation_duration_ms_bucket{le="100"}[5m])
```

---

## Integration with Existing Monitoring

### StatusEmitter Enhancement

**Location**: `cowrieprocessor/enrichment/telemetry.py`

**Add ASN metrics to EnrichmentMetrics**:
```python
@dataclass
class EnrichmentMetrics:
    """Metrics for enrichment operations."""

    # Existing cache statistics
    cache_hits: int = 0
    cache_misses: int = 0
    # ... (existing fields)

    # NEW: ASN inventory metrics
    asn_records_created: int = 0
    asn_records_updated: int = 0
    asn_operation_duration_ms: float = 0.0
    asn_unique_count: int = 0  # Unique ASNs in this batch
    asn_total_inventory_size: int = 0  # Total ASN records (updated periodically)
```

**Add recording method**:
```python
class EnrichmentTelemetry:
    def record_asn_operation(
        self,
        operation: str,  # "create" or "update"
        asn: int,
        duration_ms: float
    ) -> None:
        """Record an ASN inventory operation."""
        if operation == "create":
            self.metrics.asn_records_created += 1
        elif operation == "update":
            self.metrics.asn_records_updated += 1

        self.metrics.asn_operation_duration_ms += duration_ms
        self._emit_metrics()

    def update_asn_inventory_size(self, total_count: int) -> None:
        """Update the total ASN inventory size gauge."""
        self.metrics.asn_total_inventory_size = total_count
        self._emit_metrics()
```

**Usage in cascade_enricher.py**:
```python
# Option 1: Use existing telemetry if cascade enricher gets telemetry injected
if hasattr(self, 'telemetry'):
    self.telemetry.record_asn_operation(
        operation="create" if not existing else "update",
        asn=asn,
        duration_ms=duration_ms
    )
```

---

## Performance Impact Analysis

### Overhead Estimation

**Per ASN Operation**:
- `time.perf_counter()` calls: ~100ns × 2 = 200ns
- Stats dataclass updates: ~50ns × 3 = 150ns
- OpenTelemetry span overhead: ~1-5µs (if enabled)
- **Total overhead**: ~6µs per operation

**Context**: ASN operations include database SELECT + INSERT/UPDATE (~5-50ms)

**Impact**: <0.1% overhead (6µs / 5000µs = 0.12%)

**Conclusion**: Negligible performance impact, acceptable for production.

---

## Implementation Plan

### Phase 1: Core Instrumentation (Current PR)

**Files to modify**:
1. `cowrieprocessor/enrichment/cascade_enricher.py`
   - Extend `CascadeStats` dataclass (lines 52-71)
   - Add OpenTelemetry spans to `_ensure_asn_inventory()` (lines 608-680)
   - Track metrics in `_stats` object

2. `cowrieprocessor/enrichment/telemetry.py`
   - Extend `EnrichmentMetrics` dataclass
   - Add `record_asn_operation()` method

**Testing requirements**:
- Unit tests: Verify metrics increment correctly
- Integration tests: Verify OpenTelemetry spans work when available
- Performance tests: Verify <1% overhead

**Documentation**:
- Add metric descriptions to `docs/observability.md` (new file)
- Update `CLAUDE.md` with telemetry patterns

---

### Phase 2: Dashboard Integration (Follow-up)

**Out of scope for current PR**, but documented for operations team:

**Grafana Dashboard Panels**:
1. **ASN Growth Rate** (Time series)
   - Query: `rate(asn_inventory_records_created_total[5m]) * 60`
   - Panel type: Graph
   - Y-axis: ASNs/minute

2. **ASN Distribution by Country** (Pie chart)
   - Query: `sum by (country) (asn_inventory_records_created_total)`
   - Panel type: Pie chart

3. **ASN Operation Latency** (Heatmap)
   - Query: `histogram_quantile(0.95, rate(asn_inventory_operation_duration_ms_bucket[5m]))`
   - Panel type: Heatmap

4. **Total ASN Inventory Size** (Gauge)
   - Query: `asn_inventory_total_count`
   - Panel type: Stat

**Alerting Rules** (Prometheus):
```yaml
groups:
  - name: asn_inventory
    interval: 5m
    rules:
      - alert: ASNCreationRateHigh
        expr: rate(asn_inventory_records_created_total[5m]) * 60 > 100
        for: 10m
        annotations:
          summary: "ASN creation rate unusually high"
          description: "Creating {{ $value }} ASNs/min (threshold: 100/min)"

      - alert: ASNOperationSlow
        expr: histogram_quantile(0.95, rate(asn_inventory_operation_duration_ms_bucket[5m])) > 500
        for: 5m
        annotations:
          summary: "ASN operations running slow"
          description: "P95 latency {{ $value }}ms (threshold: 500ms)"
```

---

## Code Changes Summary

### 1. cascade_enricher.py

**Line 52-71**: Extend `CascadeStats` dataclass
```python
@dataclass
class CascadeStats:
    # ... existing fields
    asn_records_created: int = 0
    asn_records_updated: int = 0
    asn_operation_duration_ms: float = 0.0
    asn_unique_seen: set[int] = field(default_factory=set)
```

**Line 608-680**: Instrument `_ensure_asn_inventory()`
```python
def _ensure_asn_inventory(...) -> ASNInventory:
    start_time = time.perf_counter()

    with start_span("cascade_enricher.ensure_asn_inventory", attributes={...}) as span:
        # ... existing logic

        if existing:
            # ... update logic
            self._stats.asn_records_updated += 1
            if span:
                span.set_attribute("asn.operation", "update")
        else:
            # ... create logic
            self._stats.asn_records_created += 1
            if span:
                span.set_attribute("asn.operation", "create")

        self._stats.asn_unique_seen.add(asn)
        duration_ms = (time.perf_counter() - start_time) * 1000
        self._stats.asn_operation_duration_ms += duration_ms

        if span:
            span.set_attribute("asn.operation_duration_ms", duration_ms)
```

**Add method** (after line 450):
```python
def get_asn_inventory_size(self) -> int:
    """Query current ASN inventory size from database."""
    from sqlalchemy import func
    count = self.session.query(func.count(ASNInventory.asn_number)).scalar()
    return count or 0
```

### 2. enrichment/telemetry.py

**Line 12-63**: Extend `EnrichmentMetrics`
```python
@dataclass
class EnrichmentMetrics:
    # ... existing fields

    # ASN inventory metrics
    asn_records_created: int = 0
    asn_records_updated: int = 0
    asn_operation_duration_ms: float = 0.0
    asn_unique_count: int = 0
    asn_total_inventory_size: int = 0
```

**Add method** (after line 172):
```python
def record_asn_operation(
    self,
    operation: str,
    asn: int,
    duration_ms: float
) -> None:
    """Record an ASN inventory operation."""
    if operation == "create":
        self.metrics.asn_records_created += 1
    elif operation == "update":
        self.metrics.asn_records_updated += 1

    self.metrics.asn_operation_duration_ms += duration_ms
    self._emit_metrics()

def update_asn_inventory_size(self, total_count: int) -> None:
    """Update the total ASN inventory size gauge."""
    self.metrics.asn_total_inventory_size = total_count
    self._emit_metrics()
```

---

## Testing Strategy

### Unit Tests

**File**: `tests/unit/test_cascade_enricher.py`

```python
def test_asn_metrics_on_create(cascade_enricher, session):
    """Verify metrics increment when creating new ASN."""
    initial_stats = cascade_enricher.get_stats()
    assert initial_stats.asn_records_created == 0

    # Trigger ASN creation
    cascade_enricher._ensure_asn_inventory(
        asn=15169,
        organization_name="GOOGLE",
        organization_country="US",
        rir_registry="ARIN"
    )

    stats = cascade_enricher.get_stats()
    assert stats.asn_records_created == 1
    assert stats.asn_records_updated == 0
    assert 15169 in stats.asn_unique_seen
    assert stats.asn_operation_duration_ms > 0

def test_asn_metrics_on_update(cascade_enricher, session):
    """Verify metrics increment when updating existing ASN."""
    # Pre-create ASN
    asn_record = ASNInventory(
        asn_number=15169,
        organization_name="GOOGLE",
        first_seen=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )
    session.add(asn_record)
    session.commit()

    initial_stats = cascade_enricher.get_stats()

    # Trigger update
    cascade_enricher._ensure_asn_inventory(
        asn=15169,
        organization_name="GOOGLE",
        organization_country="US",  # New data
        rir_registry="ARIN"
    )

    stats = cascade_enricher.get_stats()
    assert stats.asn_records_created == 0  # No new creation
    assert stats.asn_records_updated == 1  # Update recorded
    assert 15169 in stats.asn_unique_seen
```

### Integration Tests

**File**: `tests/integration/test_cascade_telemetry.py`

```python
def test_opentelemetry_spans_emitted(cascade_enricher, session):
    """Verify OpenTelemetry spans are created when available."""
    from unittest.mock import patch, MagicMock

    mock_tracer = MagicMock()
    mock_span = MagicMock()
    mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span

    with patch('cowrieprocessor.telemetry.otel.trace.get_tracer', return_value=mock_tracer):
        cascade_enricher._ensure_asn_inventory(
            asn=15169,
            organization_name="GOOGLE",
            organization_country="US",
            rir_registry="ARIN"
        )

    # Verify span created
    mock_tracer.start_as_current_span.assert_called_once_with("cascade_enricher.ensure_asn_inventory")

    # Verify attributes set
    mock_span.set_attribute.assert_any_call("asn.number", 15169)
    mock_span.set_attribute.assert_any_call("asn.organization", "GOOGLE")
    mock_span.set_attribute.assert_any_call("asn.operation", "create")
```

---

## Operations Documentation

### Metric Reference for Ops Team

**Metric Name**: `asn_inventory.records_created`
**Type**: Counter
**Description**: Number of new ASN records created in the inventory
**Labels**: `source`, `country`, `rir`
**Use Case**: Capacity planning, data source effectiveness analysis
**Alert Threshold**: >100 ASNs/min sustained for >10 minutes (potential data quality issue)

**Metric Name**: `asn_inventory.records_updated`
**Type**: Counter
**Description**: Number of existing ASN records updated with new metadata
**Labels**: `source`, `update_type`
**Use Case**: Data freshness tracking, source priority validation
**Alert Threshold**: None (updates are expected and healthy)

**Metric Name**: `asn_inventory.total_count`
**Type**: Gauge
**Description**: Current total number of ASN records in inventory
**Labels**: None
**Use Case**: Dashboard visualization, growth tracking
**Alert Threshold**: None (informational only)

**Metric Name**: `asn_inventory.operation_duration_ms`
**Type**: Histogram
**Description**: Time taken to create or update ASN records
**Labels**: `operation`
**Use Case**: Performance monitoring, database bottleneck detection
**Alert Threshold**: P95 latency >500ms sustained for >5 minutes

---

## Decision: Current PR vs Follow-up

### Recommendation: Include in Current PR

**Rationale**:
1. **Low risk**: Purely additive, no breaking changes
2. **Small scope**: ~50 lines of code changes
3. **High value**: Immediate visibility into ASN operations
4. **Performance**: <0.1% overhead, negligible impact
5. **Testing**: Can reuse existing test infrastructure

**What to include in this PR**:
- ✅ Extend `CascadeStats` dataclass
- ✅ Add OpenTelemetry spans to `_ensure_asn_inventory()`
- ✅ Add `get_asn_inventory_size()` method
- ✅ Unit tests for metrics
- ✅ Update documentation

**What to defer to follow-up**:
- ❌ Grafana dashboards (requires production APM setup)
- ❌ Prometheus alerting rules (requires metrics infrastructure)
- ❌ EnrichmentTelemetry integration (optional, adds complexity)

---

## Appendix: Alternative Approaches Considered

### Alternative 1: StatusEmitter Only (No OpenTelemetry)

**Pros**:
- Simpler implementation
- Relies on existing infrastructure

**Cons**:
- No distributed tracing support
- JSON files harder to query/aggregate
- No standard metrics format (Prometheus)

**Decision**: Rejected. OpenTelemetry is industry standard and project already has it.

### Alternative 2: Database Triggers for Metrics

**Approach**: Use PostgreSQL triggers to track ASN operations

**Pros**:
- Zero application code changes
- Guaranteed accuracy (can't miss events)

**Cons**:
- PostgreSQL-only (breaks SQLite compatibility)
- No performance metrics (duration tracking)
- Hard to export to APM systems

**Decision**: Rejected. Violates "Database Compatibility" principle from CLAUDE.md.

### Alternative 3: Query-Based Metrics (No State Tracking)

**Approach**: Calculate metrics by querying database on-demand

**Pros**:
- Always accurate (source of truth)
- No state management complexity

**Cons**:
- Expensive (requires COUNT queries)
- Can't track operation durations
- High overhead for high-frequency operations

**Decision**: Partially adopted. Use for gauge metrics only, track counters in memory.

---

## References

- **ADR-008**: Multi-Source ASN/Geo Enrichment (design context)
- **CLAUDE.md**: Project development guidelines
- **OpenTelemetry Python Docs**: https://opentelemetry.io/docs/languages/python/
- **Prometheus Best Practices**: https://prometheus.io/docs/practices/naming/
