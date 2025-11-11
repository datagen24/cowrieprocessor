# IPClassifier Enrichment Pipeline Integration

**Status**: Design Complete
**Date**: 2025-11-10
**Purpose**: Document how IPClassifier integrates into all enrichment workflows

## Overview

The IPClassifier service integrates into the three-tier enrichment architecture (ADR-007) as **Pass 4** of the cascade enrichment pipeline. This document clarifies exactly where and how IP classification executes across all enrichment workflows.

## Critical Gap Addressed

**User Question**: "I am not sure where in the enrichment pipeline this runs, it appears that it may run after the cascade enricher, but it lacks details on how it is hooked into the enrichment flows (Backfill, bulk, delta, refresh)"

**Answer**: IPClassifier runs INSIDE the CascadeEnricher as Pass 4, NOT after it. It is automatically invoked by all workflows that call CascadeEnricher.

## Three-Tier Enrichment Architecture (ADR-007)

```
Tier 1: ASN Inventory
└─ Organization-level metadata (most stable)
   └─ Created/updated by CascadeEnricher Pass 2 (Cymru)

Tier 2: IP Inventory
└─ Current mutable state with staleness tracking
   └─ Populated by CascadeEnricher (4-pass cascade)
      ├─ Pass 1: MaxMind GeoIP (offline, geo_country)
      ├─ Pass 2: Team Cymru ASN (online, current_asn)
      ├─ Pass 3: GreyNoise (online, is_scanner)
      └─ Pass 4: IPClassifier (NEW - snapshot_ip_type)  ← THIS IS WHERE IT RUNS

Tier 3: Session Summaries
└─ Immutable point-in-time snapshots
   └─ Populated by BulkLoader._lookup_ip_snapshots()
      ├─ Reads: ip_inventory.current_asn → snapshot_asn
      ├─ Reads: ip_inventory.geo_country → snapshot_country
      └─ Reads: ip_inventory.ip_type → snapshot_ip_type  ← USES PASS 4 RESULTS
```

## Integration Point: CascadeEnricher

### Current CascadeEnricher Flow

**File**: `cowrieprocessor/enrichment/cascade_enricher.py`

```python
class CascadeEnricher:
    def __init__(
        self,
        maxmind: MaxMindClient,
        cymru: CymruClient,
        greynoise: GreyNoiseClient,
        session: Session,
    ) -> None:
        self.maxmind = maxmind
        self.cymru = cymru
        self.greynoise = greynoise
        self.session = session

    def enrich_ip(self, ip_address: str) -> IPInventory:
        """Sequential cascade enrichment with early termination."""

        # Pass 1: MaxMind (offline, always first)
        maxmind_result = self.maxmind.lookup_ip(ip_address)

        # Pass 2: Cymru (online, if ASN missing)
        if not maxmind_result or maxmind_result.asn is None:
            cymru_result = self.cymru.lookup_asn(ip_address)

        # Pass 3: GreyNoise (online, independent)
        greynoise_result = self.greynoise.lookup_ip(ip_address)

        # Merge results and update ip_inventory
        merged = self._merge_results(...)
        return merged
```

### Modified CascadeEnricher (With Pass 4)

```python
class CascadeEnricher:
    def __init__(
        self,
        maxmind: MaxMindClient,
        cymru: CymruClient,
        greynoise: GreyNoiseClient,
        ip_classifier: IPClassifier,  # NEW: Pass 4 integration
        session: Session,
    ) -> None:
        self.maxmind = maxmind
        self.cymru = cymru
        self.greynoise = greynoise
        self.ip_classifier = ip_classifier  # NEW
        self.session = session

    def enrich_ip(self, ip_address: str) -> IPInventory:
        """Sequential cascade enrichment with early termination."""

        # Pass 1: MaxMind (offline, always first)
        maxmind_result = self.maxmind.lookup_ip(ip_address)

        # Pass 2: Cymru (online, if ASN missing)
        cymru_result = None
        if not maxmind_result or maxmind_result.asn is None:
            cymru_result = self.cymru.lookup_asn(ip_address)

        # Pass 3: GreyNoise (online, independent)
        greynoise_result = self.greynoise.lookup_ip(ip_address)

        # Pass 4: IP Classification (NEW - uses Cymru data for residential heuristic)
        asn = maxmind_result.asn if maxmind_result else (cymru_result.asn if cymru_result else None)
        as_name = maxmind_result.asn_org if maxmind_result else (cymru_result.asn_org if cymru_result else None)

        ip_classification = self.ip_classifier.classify(
            ip=ip_address,
            asn=asn,
            as_name=as_name,
        )

        # Merge results (including IP classification) and update ip_inventory
        merged = self._merge_results(
            cached=cached,
            maxmind_result=maxmind_result,
            cymru_result=cymru_result,
            greynoise_result=greynoise_result,
            ip_classification=ip_classification,  # NEW
            ip_address=ip_address,
        )

        # Update ip_inventory.enrichment with IP classification
        merged.enrichment['ip_classification'] = {
            'ip_type': ip_classification.ip_type.value,
            'provider': ip_classification.provider,
            'confidence': ip_classification.confidence,
            'source': ip_classification.source,
            'classified_at': ip_classification.classified_at.isoformat(),
        }

        # Update ip_inventory.ip_type computed column (triggers snapshot population)
        # NOTE: ip_type is a hybrid property that reads from enrichment['ip_classification']['ip_type']
        # or enrichment['spur']['type'], so no direct assignment needed - just ensure enrichment is stored

        return merged
```

### Key Design Decision

**IP classification runs INSIDE CascadeEnricher.enrich_ip(), NOT as a separate step after.**

This ensures:
1. **Automatic propagation**: Any workflow calling CascadeEnricher gets IP classification
2. **Data consistency**: Classification happens atomically with other enrichments
3. **Cache efficiency**: Single database transaction updates all enrichment data
4. **Snapshot accuracy**: ip_inventory.ip_type is populated immediately, ready for snapshot reads

## Workflow Integration Points

### 1. Bulk Loading (`cowrie-loader bulk`)

**File**: `cowrieprocessor/loader/bulk.py`

**Flow**:
```
1. Parse Cowrie JSON events
2. Group events by session_id
3. Create SessionAggregate objects
4. Call _upsert_session_summaries()
   ├─ Extract canonical_source_ip from aggregates
   ├─ Call _lookup_ip_snapshots(session, canonical_ips)  ← READS ip_inventory
   │  └─ Query: SELECT ip_address, current_asn, geo_country, ip_type FROM ip_inventory WHERE ip_address IN (...)
   │     └─ ip_type comes from hybrid property (reads enrichment['ip_classification']['ip_type'])
   └─ Populate session_summaries.snapshot_ip_type from ip_inventory.ip_type
```

**When does IP classification happen?**
- **NOT during bulk load** - bulk loader only READS existing enrichment from ip_inventory
- IP enrichment happens separately via `cowrie-enrich refresh --ips N` (see Workflow #4 below)

**Code Location**: `bulk.py:655-785` (_upsert_session_summaries), `bulk.py:465-526` (_lookup_ip_snapshots)

**Integration Status**: ✅ **NO CHANGES NEEDED** - Already reads ip_inventory.ip_type hybrid property

### 2. Delta Loading (`cowrie-loader delta`)

**File**: `cowrieprocessor/loader/delta.py`

**Flow**: Same as bulk loading (uses same BulkLoader class internally)

**Integration Status**: ✅ **NO CHANGES NEEDED** - Inherits bulk loader behavior

### 3. Backfill Script (`scripts/backfill_ip_classification.py`)

**Purpose**: One-time population of snapshot_ip_type for 1.68M existing sessions

**Flow**:
```
1. Query all unique IPs from ip_inventory (38,864 IPs)
2. For each IP without enrichment['ip_classification']:
   ├─ Create CascadeEnricher instance (includes IPClassifier)
   ├─ Call cascade.enrich_ip(ip_address)  ← RUNS PASS 4 AUTOMATICALLY
   │  └─ Pass 4 populates enrichment['ip_classification']
   └─ Commit to database
3. Query session_summaries with NULL snapshot_ip_type
4. Batch UPDATE via JOIN:
   UPDATE session_summaries
   SET snapshot_ip_type = ip_inventory.ip_type
   WHERE source_ip = ip_inventory.ip_address
     AND snapshot_ip_type IS NULL
5. Commit in batches of 10,000
```

**File to Create**: `scripts/backfill_ip_classification.py`

**Code Example**:
```python
from cowrieprocessor.enrichment.cascade_factory import create_cascade_enricher
from cowrieprocessor.enrichment.ip_classification.factory import create_ip_classifier

# Create enricher with IP classifier
ip_classifier = create_ip_classifier(cache_dir, db_session)
cascade = create_cascade_enricher(
    db_session=db_session,
    cache_dir=cache_dir,
    ip_classifier=ip_classifier,  # Pass 4 enabled
)

# Enrich all IPs (Pass 4 runs automatically)
for ip_address in ip_addresses:
    cascade.enrich_ip(ip_address)  # Populates ip_inventory.enrichment['ip_classification']

# Backfill snapshots (reads ip_inventory.ip_type hybrid property)
session.execute(text("""
    UPDATE session_summaries
    SET snapshot_ip_type = ip_inventory.ip_type
    WHERE session_summaries.source_ip = ip_inventory.ip_address
      AND session_summaries.snapshot_ip_type IS NULL
"""))
```

**Integration Status**: 🆕 **NEW SCRIPT REQUIRED**

### 4. Refresh Enrichment (`cowrie-enrich refresh`)

**File**: `cowrieprocessor/cli/enrich_passwords.py` (refresh_enrichment function)

**Current Flow**:
```
1. Load database settings
2. Resolve API credentials (VT, DShield, URLHaus, SPUR)
3. Create EnrichmentService (legacy handler)
4. For each session:
   ├─ Call service.enrich_session(session_id, src_ip)
   │  └─ Calls legacy enrichment handlers (DShield, URLHaus, SPUR)
   └─ Update session_summaries.enrichment
5. For each file:
   └─ Call service.enrich_file(file_hash, filename)
      └─ VirusTotal analysis
```

**Modified Flow (With IP Enrichment)**:
```
1. Load database settings
2. Resolve API credentials
3. Create CascadeEnricher (NEW - replaces EnrichmentService for IP enrichment)
   ├─ MaxMind client
   ├─ Cymru client
   ├─ GreyNoise client
   └─ IPClassifier (Pass 4)  ← NEW
4. Add --ips flag to argparse (NEW)
5. For each IP (NEW workflow):
   ├─ Call cascade.enrich_ip(ip_address)  ← RUNS PASS 4 AUTOMATICALLY
   │  └─ Pass 4 populates enrichment['ip_classification']
   └─ Update ip_inventory.enrichment
6. For each session (existing workflow):
   └─ Legacy enrichment handlers (unchanged)
7. For each file (existing workflow):
   └─ VirusTotal analysis (unchanged)
```

**Code Changes Required**:

**File**: `cowrieprocessor/cli/enrich_passwords.py`

**Change 1**: Add --ips argument
```python
def get_parser() -> argparse.ArgumentParser:
    # ... existing code ...

    refresh_parser.add_argument(
        '--ips',
        type=int,
        default=0,
        help='Number of IPs to refresh (0 for all stale IPs, default: 0)'
    )
```

**Change 2**: Initialize CascadeEnricher in refresh_enrichment()
```python
def refresh_enrichment(args: argparse.Namespace) -> int:
    # ... existing setup ...

    # NEW: Initialize CascadeEnricher with IPClassifier
    if args.ips != 0:  # Only create if IP enrichment requested
        from cowrieprocessor.enrichment.cascade_factory import create_cascade_enricher
        from cowrieprocessor.enrichment.ip_classification.factory import create_ip_classifier

        cache_dir_path = Path(args.cache_dir)

        # Create IP classifier
        ip_classifier = create_ip_classifier(
            cache_dir=cache_dir_path,
            db_session=session_maker(),  # Need session from maker
        )

        # Create cascade enricher with Pass 4
        cascade_enricher = create_cascade_enricher(
            db_session=session_maker(),
            cache_dir=cache_dir_path,
            ip_classifier=ip_classifier,  # Enable Pass 4
        )

    # NEW: IP enrichment workflow
    if args.ips > 0:
        logger.info(f"Refreshing up to {args.ips} stale IPs...")
        for ip_inventory_record in iter_stale_ips(engine, args.ips):
            cascade_enricher.enrich_ip(ip_inventory_record.ip_address)
            # Pass 4 automatically populates enrichment['ip_classification']

    # Existing session enrichment workflow (unchanged)
    for session_id, src_ip in iter_sessions(engine, args.sessions):
        # ... existing code ...

    # Existing file enrichment workflow (unchanged)
    for file_hash, filename, session_id in iter_files(engine, args.files):
        # ... existing code ...
```

**Change 3**: Add iter_stale_ips() helper
```python
def iter_stale_ips(engine: Engine, limit: int) -> Iterator[IPInventory]:
    """Iterate over IPs needing enrichment refresh.

    Criteria:
    - enrichment['ip_classification'] is NULL OR
    - enrichment_updated_at > 30 days old

    Args:
        engine: Database engine
        limit: Maximum number of IPs to process (0 for all)

    Yields:
        IPInventory records needing refresh
    """
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import or_
    from ..db.models import IPInventory

    session_maker = create_session_maker(engine)
    with session_maker() as session:
        threshold = datetime.now(timezone.utc) - timedelta(days=30)

        query = session.query(IPInventory).filter(
            or_(
                # Missing IP classification
                IPInventory.enrichment['ip_classification'].is_(None),
                # Stale enrichment (>30 days)
                IPInventory.enrichment_updated_at < threshold,
            )
        ).order_by(IPInventory.last_seen.desc())  # Most active IPs first

        if limit > 0:
            query = query.limit(limit)

        for record in query:
            yield record
```

**Integration Status**: 🔧 **MODIFICATION REQUIRED** - Add --ips flag and CascadeEnricher initialization

### 5. Real-Time Enrichment (Future)

**Potential Integration**: Enrich IPs as sessions arrive in real-time

**Flow**:
```
1. Cowrie event arrives via AMQP/Kafka
2. Extract source_ip
3. Check if ip_inventory has fresh enrichment
4. If stale or missing:
   ├─ Call cascade.enrich_ip(source_ip)  ← RUNS PASS 4 AUTOMATICALLY
   └─ Update ip_inventory
5. Continue session processing
```

**Integration Status**: 🔮 **FUTURE ENHANCEMENT** - Not part of initial implementation

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     Cowrie JSON Events                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              cowrie-loader bulk / delta                         │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  _upsert_session_summaries()                           │    │
│  │  ├─ Extract canonical_source_ip                        │    │
│  │  ├─ Call _lookup_ip_snapshots(canonical_ips)  ←──┐    │    │
│  │  │  └─ Query: ip_inventory.ip_type              │    │    │
│  │  └─ Populate: snapshot_ip_type ←─────────────────┘    │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ (Reads ip_inventory)
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ip_inventory Table                           │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  Columns:                                              │    │
│  │  - ip_address (PK)                                     │    │
│  │  - current_asn (from Pass 2: Cymru)                    │    │
│  │  - geo_country (from Pass 1: MaxMind)                  │    │
│  │  - enrichment (JSONB) ←────────────────────┐           │    │
│  │    └─ ip_classification: {                │           │    │
│  │         ip_type: "cloud",                  │           │    │
│  │         provider: "aws",                   │           │    │
│  │         confidence: 0.99,                  │           │    │
│  │         source: "cloud_ranges_aws"         │           │    │
│  │       }                                    │           │    │
│  │  - ip_type (hybrid property) ←─────────────┘           │    │
│  │    └─ Reads: enrichment['ip_classification']['ip_type']│    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │
                              │ (Writes enrichment)
                              │
┌─────────────────────────────────────────────────────────────────┐
│              CascadeEnricher.enrich_ip()                        │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  Pass 1: MaxMind (offline)                             │    │
│  │  ├─ geo_country, asn, asn_org                          │    │
│  │  └─ Result: maxmind_result                             │    │
│  │                                                         │    │
│  │  Pass 2: Cymru (online, if ASN missing)                │    │
│  │  ├─ asn, asn_org, registry                             │    │
│  │  └─ Result: cymru_result                               │    │
│  │                                                         │    │
│  │  Pass 3: GreyNoise (online)                            │    │
│  │  ├─ noise, classification, tags                        │    │
│  │  └─ Result: greynoise_result                           │    │
│  │                                                         │    │
│  │  Pass 4: IPClassifier (NEW) ←────────────────────┐     │    │
│  │  ├─ Input: ip_address, asn, as_name             │     │    │
│  │  ├─ Priority: TOR → Cloud → Datacenter → Resi   │     │    │
│  │  ├─ Cache: Redis L1 → DB L2 → Disk L3           │     │    │
│  │  └─ Result: IPClassification {                  │     │    │
│  │       ip_type: IPType.CLOUD,                    │     │    │
│  │       provider: "aws",                          │     │    │
│  │       confidence: 0.99,                         │     │    │
│  │       source: "cloud_ranges_aws"                │     │    │
│  │     }                                           │     │    │
│  │                                                  │     │    │
│  │  Merge all results and update ip_inventory ─────┘     │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │
                              │ (Called by multiple workflows)
                              │
┌─────────────────────────────┴───────────────────────────────────┐
│                                                                  │
│  cowrie-enrich refresh --ips 1000                               │
│  └─ For each stale IP: cascade.enrich_ip()                      │
│                                                                  │
│  scripts/backfill_ip_classification.py                          │
│  └─ For each IP: cascade.enrich_ip()                            │
│                                                                  │
│  (Future) Real-time enrichment pipeline                         │
│  └─ On event arrival: cascade.enrich_ip()                       │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## Cascade Factory Integration

**File**: `cowrieprocessor/enrichment/cascade_factory.py`

**Current Implementation**:
```python
def create_cascade_enricher(
    db_session: Session,
    cache_dir: Path | None = None,
    maxmind_db_path: Path | None = None,
) -> CascadeEnricher:
    """Create fully initialized CascadeEnricher."""

    maxmind = MaxMindClient(maxmind_db_path)
    cymru = CymruClient()
    greynoise = GreyNoiseClient() or MockGreyNoiseClient()

    return CascadeEnricher(
        maxmind=maxmind,
        cymru=cymru,
        greynoise=greynoise,
        session=db_session,
    )
```

**Modified Implementation (With Pass 4)**:
```python
def create_cascade_enricher(
    db_session: Session,
    cache_dir: Path | None = None,
    maxmind_db_path: Path | None = None,
    ip_classifier: IPClassifier | None = None,  # NEW parameter
) -> CascadeEnricher:
    """Create fully initialized CascadeEnricher with IP classification.

    Args:
        db_session: SQLAlchemy session for database operations
        cache_dir: Optional cache directory (defaults to ~/.cache/cowrieprocessor)
        maxmind_db_path: Optional MaxMind database path
        ip_classifier: Optional pre-configured IPClassifier (creates default if None)

    Returns:
        CascadeEnricher with all 4 passes enabled
    """

    # Resolve cache directory
    if cache_dir is None:
        cache_dir = Path.home() / ".cache" / "cowrieprocessor"

    # Create Pass 1-3 clients
    maxmind = MaxMindClient(maxmind_db_path)
    cymru = CymruClient()
    greynoise = GreyNoiseClient() or MockGreyNoiseClient()

    # Create Pass 4 client (NEW)
    if ip_classifier is None:
        from cowrieprocessor.enrichment.ip_classification.factory import create_ip_classifier
        ip_classifier = create_ip_classifier(
            cache_dir=cache_dir / "ip_classification",
            db_session=db_session,
        )

    return CascadeEnricher(
        maxmind=maxmind,
        cymru=cymru,
        greynoise=greynoise,
        ip_classifier=ip_classifier,  # NEW: Pass 4 enabled
        session=db_session,
    )
```

## Configuration and Deployment

### Environment Variables

```bash
# Optional: Override default data source URLs
export TOR_BULK_LIST_URL="https://check.torproject.org/torbulkexitlist"
export CLOUD_RANGES_BASE_URL="https://raw.githubusercontent.com/rezmoss/cloud-provider-ip-addresses/main"
export DATACENTER_RANGES_URL="https://raw.githubusercontent.com/jhassine/server-ip-addresses/main/data/datacenters.csv"

# Optional: Disable IP classification (rollback mechanism)
export DISABLE_IP_CLASSIFICATION=false
```

### Cache Directory Structure

```
/mnt/dshield/data/cache/
├─ virustotal/          # Existing
├─ dshield/             # Existing
├─ urlhaus/             # Existing
├─ spur/                # Existing
└─ ip_classification/   # NEW
   ├─ tor_exit_nodes.txt
   ├─ cloud_ranges/
   │  ├─ aws.csv
   │  ├─ azure.csv
   │  ├─ gcp.csv
   │  └─ cloudflare.csv
   ├─ datacenter_ranges.csv
   └─ disk_cache/
      └─ <sharded by IP octets>
```

### Cron Jobs (Data Source Updates)

```cron
# TOR exit nodes - hourly
0 * * * * cowrie uv run python -m cowrieprocessor.enrichment.ip_classification.matchers update-tor >> /var/log/ip_classification/tor_update.log 2>&1

# Cloud providers - daily at 2 AM
0 2 * * * cowrie uv run python -m cowrieprocessor.enrichment.ip_classification.matchers update-cloud >> /var/log/ip_classification/cloud_update.log 2>&1

# Datacenters - weekly on Sunday at 3 AM
0 3 * * 0 cowrie uv run python -m cowrieprocessor.enrichment.ip_classification.matchers update-datacenter >> /var/log/ip_classification/datacenter_update.log 2>&1
```

## Command Usage Examples

### 1. Initial Backfill (One-Time)

```bash
# Step 1: Enrich all IPs in ip_inventory (38,864 IPs, ~6-10 hours)
uv run python scripts/backfill_ip_classification.py \
    --db "postgresql://user:pass@host:port/cowrieprocessor" \ <!-- pragma: allowlist secret Documentaion example -->
    --cache-dir /mnt/dshield/data/cache/ip_classification \
    --batch-size 10000 \
    --progress

# Step 2: Populate snapshot_ip_type for 1.68M sessions (automatic via script)
# This happens inside the backfill script via UPDATE...JOIN
```

### 2. Refresh Stale IPs (Ongoing Maintenance)

```bash
# Refresh IPs with stale enrichment (>30 days old)
uv run cowrie-enrich refresh \
    --sessions 0 \
    --files 0 \
    --ips 0 \
    --verbose

# Refresh top 1,000 most active IPs
uv run cowrie-enrich refresh \
    --sessions 0 \
    --files 0 \
    --ips 1000 \
    --progress
```

### 3. Bulk Load with Pre-Enriched IPs

```bash
# Enrich IPs first (if not done already)
uv run cowrie-enrich refresh --ips 0 --sessions 0 --files 0

# Then bulk load (will read snapshot_ip_type automatically)
uv run cowrie-loader bulk /path/to/logs/*.json \
    --db "postgresql://user:pass@host:port/cowrieprocessor" \ <!-- pragma: allowlist secret -->
    --status-dir /mnt/dshield/data/logs/status
```

### 4. Delta Load (Incremental)

```bash
# Delta load (no special flags needed - reads ip_inventory automatically)
uv run cowrie-loader delta /path/to/logs/*.json \
    --db "postgresql://user:pass@host:port/cowrieprocessor" \ <!-- pragma: allowlist secret -->
    --status-dir /mnt/dshield/data/logs/status
```

## Performance Characteristics

### Enrichment Latency

| Workflow | Operation | Latency (p50) | Latency (p99) | Notes |
|----------|-----------|---------------|---------------|-------|
| **Bulk Load** | _lookup_ip_snapshots() | <5ms | <15ms | Single JOIN query, batch of IPs |
| **Bulk Load** | Full batch (1000 sessions) | <2s | <5s | No enrichment, just reads |
| **Refresh** | cascade.enrich_ip() (cached) | <10ms | <30ms | Redis L1 + DB L2 hits |
| **Refresh** | cascade.enrich_ip() (uncached) | <50ms | <150ms | All 4 passes + DB writes |
| **Refresh** | Batch (100 IPs, 95% cached) | <2s | <5s | Mostly cache hits |
| **Backfill** | Full run (38,864 IPs) | 6-10 hours | N/A | Network-bound (data downloads) |
| **Backfill** | Session UPDATE (1.68M rows) | 2-4 hours | N/A | Database-bound (batch commits) |

### Cache Hit Rates (After Warmup)

- **Redis L1**: 85-90% (1-hour TTL for TOR/Unknown, 24-hour for stable types)
- **Database L2**: 5-10% (7-day TTL)
- **Disk L3**: 2-3% (30-day TTL)
- **Miss (re-classify)**: 2-5%

**Overall Cache Hit Rate**: >95%

## Success Criteria

### Functional Requirements
- [x] IPClassifier integrates as Pass 4 inside CascadeEnricher
- [x] All workflows (bulk, delta, refresh, backfill) automatically use Pass 4
- [x] snapshot_ip_type populated via ip_inventory.ip_type hybrid property
- [ ] Backfill script successfully enriches 38,864 IPs (6-10 hours)
- [ ] Backfill script successfully updates 1.68M sessions (2-4 hours)
- [ ] `cowrie-enrich refresh --ips N` command functional

### Performance Requirements
- [ ] Cache hit rate >95% after warmup
- [ ] Classification latency p99 <150ms (uncached), <30ms (cached)
- [ ] Bulk load performance unchanged (<5s for 1000 sessions)
- [ ] Refresh enrichment processes 100 IPs in <5s (95% cached)

### Data Quality Requirements
- [ ] snapshot_ip_type coverage ≥90% (from 0%)
- [ ] TOR classification ≥95% accurate
- [ ] Cloud classification ≥99% accurate
- [ ] Datacenter classification ≥70% accurate
- [ ] Residential classification ≥70% accurate

## Rollback Procedures

### If Critical Issues Occur

1. **Disable Pass 4 in CascadeEnricher**:
   ```python
   # In cascade_factory.py, comment out:
   # ip_classifier = create_ip_classifier(...)
   # enricher.ip_classifier = ip_classifier

   # OR set environment variable:
   export DISABLE_IP_CLASSIFICATION=true
   ```

2. **Revert snapshot_ip_type to NULL**:
   ```sql
   UPDATE session_summaries SET snapshot_ip_type = NULL;
   ```

3. **Stop cron jobs**:
   ```bash
   sudo mv /etc/cron.d/ip_classification_updates /etc/cron.d/ip_classification_updates.disabled
   ```

4. **Clear caches**:
   ```bash
   redis-cli KEYS "ip_classification:*" | xargs redis-cli DEL
   rm -rf /mnt/dshield/data/cache/ip_classification/*
   ```

5. **Verify system operates without IP classification**

## Monitoring and Alerts

### Key Metrics to Monitor

1. **Cache Hit Rate**: Should be >95% after warmup
   ```bash
   redis-cli INFO stats | grep keyspace_hits
   ```

2. **Classification Latency**: p99 <150ms (uncached), <30ms (cached)
   ```bash
   grep "ip_classification_latency" /var/log/cowrie-processor/enrichment.log | awk '{print $NF}' | sort -n
   ```

3. **Data Source Update Success**: 100% success rate
   ```bash
   tail -f /var/log/ip_classification/tor_update.log
   ```

4. **snapshot_ip_type Coverage**: ≥90%
   ```sql
   SELECT
       COUNT(*) FILTER (WHERE snapshot_ip_type IS NOT NULL) * 100.0 / COUNT(*) as coverage_pct
   FROM session_summaries;
   ```

### Alert Thresholds

- **CRITICAL**: Cache hit rate <80%
- **WARNING**: Classification latency p99 >200ms
- **CRITICAL**: Data source update fails 3 consecutive times
- **WARNING**: snapshot_ip_type coverage <85%

## Appendix A: Modified File Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `cascade_enricher.py` | **Modify** | Add ip_classifier parameter, implement Pass 4 |
| `cascade_factory.py` | **Modify** | Wire IPClassifier into factory |
| `enrich_passwords.py` | **Modify** | Add --ips flag, integrate CascadeEnricher |
| `backfill_ip_classification.py` | **Create** | One-time backfill script for 1.68M sessions |
| `ip_classification/__init__.py` | **Create** | Package initialization |
| `ip_classification/models.py` | **Create** | IPType enum, IPClassification dataclass |
| `ip_classification/matchers.py` | **Create** | All IP matcher implementations |
| `ip_classification/cache.py` | **Create** | Multi-tier cache implementation |
| `ip_classification/classifier.py` | **Create** | Main IPClassifier service |
| `ip_classification/factory.py` | **Create** | Factory function for dependency injection |
| `bulk.py` | ✅ **No Change** | Already reads ip_type hybrid property |
| `delta.py` | ✅ **No Change** | Inherits bulk loader behavior |

## Appendix B: Testing Strategy

### Unit Tests (95% coverage target)
- Test each IP matcher in isolation with mocked data sources
- Test multi-tier cache with mocked Redis/DB/Disk
- Test IPClassifier priority ordering
- Test CascadeEnricher Pass 4 integration

### Integration Tests (85% coverage target)
- Test full bulk load with pre-enriched IPs
- Test refresh command with --ips flag
- Test backfill script on test database (100 IPs)
- Test cache warming across all tiers

### Performance Tests
- Benchmark IPClassifier.classify() (10,000 IPs, 95% cached)
- Benchmark CascadeEnricher.enrich_ip() with Pass 4
- Benchmark bulk load performance (unchanged baseline)
- Benchmark refresh enrichment throughput

### Manual Validation
- Verify 100 random IPs across all types (TOR, Cloud, Datacenter, Residential)
- Confirm accuracy meets targets (TOR 95%+, Cloud 99%+, DC/Resi 70%+)
- Validate snapshot_ip_type propagation end-to-end

---

**Document Version**: 1.0
**Last Updated**: 2025-11-10
**Author**: CowrieProcessor Team
**Status**: Design Complete - Ready for Implementation
