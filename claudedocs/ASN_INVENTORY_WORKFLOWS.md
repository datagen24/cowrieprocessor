# ASN Inventory Operational Workflows

**Created**: 2025-11-06
**Purpose**: Comprehensive operational procedures for ASN/Geo enrichment per ADR-007/008
**Audience**: Operators, DevOps, Production Support

## Overview

The ASN Inventory system provides comprehensive IP geolocation and autonomous system number (ASN) enrichment through a multi-source cascade architecture. This guide documents three distinct operational workflows for enriching IP data at different stages of the data lifecycle.

### Purpose of ASN/Geo Inventory (ADR-007)

**Business Value**:
- **Threat Attribution**: Identify attack sources by geographic region and network ownership
- **Pattern Analysis**: Detect coordinated attacks from specific ASNs or cloud providers
- **Intelligence Enrichment**: Augment honeypot data with contextual network information
- **Research Capability**: Enable academic and operational security research

**Technical Implementation**:
- Centralized IP inventory table (`ip_inventory`) with enrichment metadata
- Multi-source cascade enrichment (ADR-008) for high coverage (>95%)
- Cache-first design with source-specific TTLs (MaxMind: infinite, Cymru: 90d, GreyNoise: 7d)
- Feature flag controlled integration (`enable_asn_inventory`)

### Multi-Source Enrichment Cascade (ADR-008)

**Three-Tier Data Sources**:

1. **MaxMind GeoLite2** (Primary - Offline):
   - Coverage: 99% of IPs for geo data, 98% for ASN data
   - Cost: Free (requires license key)
   - Latency: <5ms (local database lookup)
   - Update frequency: Weekly

2. **Team Cymru** (ASN Fallback - DNS/Netcat):
   - Coverage: Fills ~1% ASN gap from MaxMind
   - Cost: Free (community service)
   - Latency: <100ms (DNS) or <200ms (netcat bulk)
   - Update frequency: Real-time BGP data

3. **GreyNoise Community** (Threat Intel - API):
   - Coverage: Scanner/bot classification, RIOT benign services
   - Cost: Free (10K requests/day)
   - Latency: <500ms (API call)
   - Update frequency: Real-time threat intelligence

**Cascade Logic**:
```
IP Address
  → Cache Check (ip_inventory table)
    → If fresh, return cached data
  → MaxMind Lookup (offline, always fast)
    → If ASN found, early termination (99% of cases)
  → Cymru Lookup (online, conditional on ASN gap)
    → Fills remaining 1% ASN coverage
  → GreyNoise Lookup (online, optional threat intel)
    → Adds scanner/bot classification
  → Store merged result in ip_inventory
```

## Three Operational Workflows

### Workflow 1: Net New (During Data Loading)

**When to Use**: Automatic enrichment during cowrie-loader delta/bulk operations

**Activation Method**: Feature flag in configuration or CLI flag

**Use Cases**:
- Production honeypot sensors with real-time data ingestion
- Continuous monitoring deployments requiring immediate context
- Scenarios where enrichment delay is acceptable (80%+ cache hit rate expected)

#### Command Examples

**Configuration-Based Activation** (Recommended for Production):

```toml
# config/sensors.toml
[[sensor]]
name = "production-honeypot"
logpath = "/mnt/dshield/production-honeypot/NSM/cowrie"
enable_asn_inventory = true  # Feature flag enables automatic enrichment
summarizedays = 1

[secrets]
maxmind_license = "env:MAXMIND_LICENSE_KEY"
greynoise_api = "env:GREYNOISE_API_KEY"
```

```bash
# Delta load with automatic ASN enrichment (config-based)
uv run cowrie-loader delta /mnt/dshield/production-honeypot/NSM/cowrie/*.json \
    --db "postgresql://user:pass@host:port/database" \
    --sensor production-honeypot \
    --status-dir /mnt/dshield/data/logs/status

# Feature flag read from sensors.toml, no CLI flag needed
```

**CLI Flag Override** (Testing or One-Off Operations):

```bash
# Bulk load with explicit ASN enrichment flag
uv run cowrie-loader bulk /mnt/dshield/logs/*.json.bz2 \
    --db "postgresql://user:pass@host:port/database" \
    --sensor test-honeypot \
    --enable-asn-inventory \
    --status-dir /mnt/dshield/data/logs/status

# CLI flag overrides configuration, useful for testing
```

**Disable ASN Enrichment** (Fast Import Mode):

```bash
# Initial bulk import without enrichment (faster ingestion)
uv run cowrie-loader bulk /mnt/dshield/historical/*.json \
    --db "postgresql://..." \
    --sensor historical-import \
    --no-asn-inventory \
    --status-dir /mnt/dshield/data/logs/status

# Run Workflow 3 (Backfill) afterward to enrich historical data
```

#### Behavior and Performance

**Enrichment Trigger**: Every IP address in `raw_events` table
- Source IP (`src_ip`)
- Destination IP (`dst_ip`, if present)
- Download/upload IPs from file operations

**Cache-First Design**:
- 80%+ cache hit rate expected in production (IPs repeat across sessions)
- Fresh cache entries returned immediately (<5ms)
- Only uncached or stale IPs trigger cascade enrichment

**Performance Characteristics**:
- Initial bulk load: +15-20% processing time (cold cache)
- Delta loads: +2-5% processing time (warm cache)
- Background enrichment: Non-blocking, doesn't slow session creation
- Batch commits: Every 1000 IPs to optimize database writes

**Monitoring**:
```bash
# Watch enrichment progress in real-time
tail -f /mnt/dshield/data/logs/status/production-honeypot_loader_status.json

# Key metrics:
# - total_ips_enriched: Number of IPs processed
# - cache_hit_rate: Percentage of cached lookups
# - cascade_latency_p95: 95th percentile enrichment time
# - greynoise_quota_remaining: Daily API quota status
```

### Workflow 2: Refresh (On-Demand Re-Enrichment)

**When to Use**: Re-enrich stale IPs or specific IP ranges with updated data

**Activation Method**: Explicit CLI command

**Use Cases**:
- API key rotation requiring data refresh with new credentials
- Data quality improvements (e.g., MaxMind database update with better coverage)
- Stale data cleanup (Cymru >90 days old, GreyNoise >7 days old)
- Selective re-enrichment of high-value IP ranges
- Quarterly/annual data freshness audits

#### Command Examples

**Refresh Stale Cymru ASN Data** (>90 days old):

```bash
uv run cowrie-enrich refresh --ips 1000 --verbose

# Options:
# --ips N: Number of stale IPs to refresh (batch size)
# --source cymru: Only refresh Cymru ASN data
# --source greynoise: Only refresh GreyNoise scanner data
# --verbose: Show detailed progress and statistics
```

**Refresh Stale GreyNoise Scanner Data** (>7 days old):

```bash
uv run cowrie-enrich refresh --ips 500 --source greynoise --progress

# Output shows:
# - IPs processed
# - Cache updates
# - API quota usage
# - Errors/warnings
```

**Refresh All Stale Data** (Mixed sources):

```bash
# Find all IPs with stale enrichment data and refresh in batches
uv run cowrie-enrich refresh --ips 2000 --all-sources --progress

# Processes:
# 1. Cymru data >90 days old
# 2. GreyNoise data >7 days old
# 3. MaxMind data when database updated
```

**Selective IP Range Refresh**:

```bash
# Refresh specific IP range (requires SQL + tool)
# Step 1: Identify IPs needing refresh
psql -d cowrie -c "
    SELECT ip_address FROM ip_inventory
    WHERE ip_address BETWEEN '1.1.1.0' AND '1.1.1.255'
    AND (enrichment_ts < NOW() - INTERVAL '90 days'
         OR scanner_ts < NOW() - INTERVAL '7 days');
" > ips_to_refresh.txt

# Step 2: Refresh via custom script
python3 << EOF
from cowrieprocessor.enrichment.cascade_factory import create_cascade_enricher
from cowrieprocessor.db.engine import get_engine
from sqlalchemy.orm import Session
from pathlib import Path

engine = get_engine("postgresql://...")
with Session(engine) as session:
    cascade = create_cascade_enricher(
        cache_dir=Path("/mnt/dshield/data/cache"),
        db_session=session,
        config={'greynoise_api': 'env:GREYNOISE_API_KEY'},
        maxmind_license_key='env:MAXMIND_LICENSE_KEY',
    )

    with open('ips_to_refresh.txt') as f:
        for line in f:
            ip = line.strip()
            if ip:
                cascade.enrich_ip(ip)
    session.commit()
EOF
```

#### Behavior and Performance

**Query Strategy**:
```sql
-- IPs with NULL ASN (MaxMind gap)
SELECT ip_address FROM ip_inventory
WHERE asn_number IS NULL
ORDER BY observation_count DESC  -- High-value IPs first
LIMIT 1000;

-- Stale Cymru data (>90 days)
SELECT ip_address FROM ip_inventory
WHERE asn_source = 'cymru'
AND enrichment_ts < NOW() - INTERVAL '90 days'
LIMIT 1000;

-- Stale GreyNoise data (>7 days)
SELECT ip_address FROM ip_inventory
WHERE scanner_ts < NOW() - INTERVAL '7 days'
LIMIT 500;
```

**Re-Enrichment Process**:
1. Query identifies stale/missing IPs
2. Cascade enricher runs for each IP
3. Existing records updated (UPSERT) with new data
4. Enrichment timestamps updated per source
5. Batch commit every 100 IPs

**Performance**:
- MaxMind-only refresh: ~10K IPs/minute (offline database)
- Cymru fallback: ~1K IPs/minute (DNS rate limit: 100 req/sec)
- GreyNoise inclusion: ~600 IPs/minute (API rate limit: 10 req/sec)

**Monitoring**:
```bash
# Check refresh progress
uv run cowrie-enrich refresh --ips 1000 --progress

# Output example:
# Refreshing stale IP enrichment data...
# Cache hit rate: 12.5% (stale data)
# Cymru refreshed: 875/1000 (87.5%)
# GreyNoise refreshed: 342/500 (68.4%)
# Total time: 3m 24s
# Errors: 0
```

### Workflow 3: Backfill (Historical Data)

**When to Use**: Populate ASN inventory from existing `ip_inventory` table without enrichment

**Activation Method**: Standalone CLI tool

**Use Cases**:
- Initial setup of ASN inventory after system deployment
- Historical data analysis requiring ASN context
- Bulk enrichment of imported data from external sources
- Performance testing with large datasets
- Staging environment data preparation

#### Two-Step Process

**Step 1: Ensure ip_inventory Populated**

The `ip_inventory` table must contain IP addresses before ASN enrichment. This table is typically populated by:
- `cowrie-loader` during normal data ingestion
- Manual SQL imports from external data sources
- Data migration from legacy systems

**Verify ip_inventory Status**:
```sql
-- PostgreSQL
SELECT
    COUNT(*) AS total_ips,
    COUNT(asn_number) AS enriched_ips,
    COUNT(*) - COUNT(asn_number) AS missing_asn,
    ROUND(100.0 * COUNT(asn_number) / COUNT(*), 2) AS enrichment_percent
FROM ip_inventory;

-- Expected output:
--  total_ips | enriched_ips | missing_asn | enrichment_percent
-- -----------+--------------+-------------+--------------------
--     250000 |       125000 |      125000 |              50.00
```

**Populate ip_inventory if Empty** (SQL Script):
```sql
-- Extract unique IPs from raw_events
INSERT INTO ip_inventory (ip_address, first_seen_at, observation_count)
SELECT
    src_ip AS ip_address,
    MIN(event_ts) AS first_seen_at,
    COUNT(*) AS observation_count
FROM raw_events
WHERE src_ip IS NOT NULL
GROUP BY src_ip
ON CONFLICT (ip_address) DO UPDATE SET
    observation_count = ip_inventory.observation_count + EXCLUDED.observation_count;

-- Also insert destination IPs
INSERT INTO ip_inventory (ip_address, first_seen_at, observation_count)
SELECT
    dst_ip AS ip_address,
    MIN(event_ts) AS first_seen_at,
    COUNT(*) AS observation_count
FROM raw_events
WHERE dst_ip IS NOT NULL
GROUP BY dst_ip
ON CONFLICT (ip_address) DO UPDATE SET
    observation_count = ip_inventory.observation_count + EXCLUDED.observation_count;
```

**Step 2: Run Backfill Enrichment**

```bash
# Backfill ASN/Geo data for all unenriched IPs
uv run cowrie-enrich-asn \
    --db "postgresql://user:pass@host:port/database" \
    --batch-size 1000 \
    --commit-interval 5000 \
    --progress

# Options:
# --batch-size: Number of IPs to process per batch (default: 1000)
# --commit-interval: Commit every N IPs (default: 5000)
# --progress: Show progress bar and statistics
# --max-ips: Limit total IPs to process (useful for testing)
# --workers: Number of parallel workers (default: 4)
```

**Large-Scale Backfill** (Production):
```bash
# Process 1 million IPs in parallel with progress monitoring
uv run cowrie-enrich-asn \
    --db "postgresql://..." \
    --batch-size 2000 \
    --commit-interval 10000 \
    --workers 8 \
    --progress \
    --max-ips 1000000

# Expected output:
# ASN Backfill Progress
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 1000000/1000000 [45:23<00:00, 367.2 IPs/s]
#
# Summary:
# - Total IPs processed: 1,000,000
# - Enriched successfully: 987,432 (98.7%)
# - Cache hits: 812,543 (81.2%)
# - MaxMind ASN: 976,234 (97.6%)
# - Cymru fallback: 11,198 (1.1%)
# - GreyNoise scanner: 234,567 (23.5%)
# - Errors: 12,568 (1.3%)
# - Total time: 45m 23s
# - Avg throughput: 367 IPs/sec
```

#### Behavior and Performance

**Batch Processing Strategy**:
```python
# Pseudo-code for backfill logic
while True:
    # Query batch of unenriched IPs
    unenriched_ips = query_unenriched_ips(batch_size=1000)
    if not unenriched_ips:
        break

    # Enrich batch using cascade
    for ip in unenriched_ips:
        enriched_data = cascade.enrich_ip(ip)
        # Update ip_inventory with enriched data

    # Commit every commit_interval IPs
    if total_processed % commit_interval == 0:
        session.commit()

    # Show progress
    progress_bar.update(len(unenriched_ips))
```

**Performance Characteristics**:
- **Cold Start**: ~200-300 IPs/sec (no cache, all API calls)
- **Warm Cache**: ~500-1000 IPs/sec (80%+ cache hit rate)
- **MaxMind Only**: ~10K IPs/sec (offline database, no API calls)
- **Parallel Workers**: Linear scaling up to 8 workers (CPU/IO bound)

**Database Impact**:
- Bulk commits reduce transaction overhead
- Indexes on `ip_address` critical for performance
- Temporary index on `asn_number IS NULL` speeds up unenriched queries
- VACUUM ANALYZE recommended after large backfills

**Resource Usage**:
- Memory: ~500MB per worker (MaxMind databases + cache)
- CPU: Moderate (network I/O bound for Cymru/GreyNoise)
- Network: Burst traffic during cold start, minimal after cache warm
- Disk: Cache directory grows (~10KB per unique IP enriched)

**Error Handling**:
- API failures: Retry with exponential backoff (1s, 2s, 4s, 8s)
- Rate limit exhaustion: Graceful degradation (GreyNoise quota = 0)
- Database errors: Rollback batch, log error, continue
- Transient failures: Skip IP, mark for retry in next run

#### Production Deployment Strategy

**Staging Test** (Small Dataset):
```bash
# Test on 10K IPs to validate configuration
uv run cowrie-enrich-asn \
    --db "postgresql://staging-db/..." \
    --max-ips 10000 \
    --batch-size 100 \
    --progress

# Expected completion: ~30 seconds (warm cache) to 5 minutes (cold)
```

**Production Backfill** (Large Dataset):
```bash
# Step 1: Database preparation
psql -d cowrie << EOF
-- Create index for faster unenriched queries
CREATE INDEX CONCURRENTLY idx_ip_inventory_unenriched
ON ip_inventory (ip_address) WHERE asn_number IS NULL;

-- Analyze for query optimization
ANALYZE ip_inventory;
EOF

# Step 2: Run backfill with monitoring
nohup uv run cowrie-enrich-asn \
    --db "postgresql://prod-db/..." \
    --batch-size 2000 \
    --commit-interval 10000 \
    --workers 8 \
    --progress \
    > backfill_$(date +%Y%m%d_%H%M%S).log 2>&1 &

# Step 3: Monitor progress
tail -f backfill_*.log

# Step 4: Post-backfill cleanup
psql -d cowrie << EOF
-- Drop temporary index
DROP INDEX CONCURRENTLY idx_ip_inventory_unenriched;

-- Vacuum and analyze
VACUUM ANALYZE ip_inventory;

-- Verify enrichment coverage
SELECT
    COUNT(*) AS total_ips,
    COUNT(asn_number) AS enriched,
    ROUND(100.0 * COUNT(asn_number) / COUNT(*), 2) AS coverage_pct
FROM ip_inventory;
EOF
```

## Configuration Guide

### Feature Flags

**Config-Based (Recommended)**:
```toml
# config/sensors.toml
[[sensor]]
name = "production-sensor"
enable_asn_inventory = true  # Default: true for production sensors

# API Keys (use secrets resolver)
[secrets]
maxmind_license = "env:MAXMIND_LICENSE_KEY"
greynoise_api = "env:GREYNOISE_API_KEY"
```

**Environment Variables**:
```bash
export MAXMIND_LICENSE_KEY="your_maxmind_key_here"
export GREYNOISE_API_KEY="your_greynoise_key_here"
export ENABLE_ASN_INVENTORY=true
```

**CLI Overrides**:
```bash
# Enable ASN inventory (override config)
cowrie-loader delta ... --enable-asn-inventory

# Disable ASN inventory (override config)
cowrie-loader delta ... --no-asn-inventory
```

### Secrets Management

**Supported Schemes** (via secrets resolver):
- `env:VARIABLE_NAME` - Environment variable (recommended for Docker/K8s)
- `file:/path/to/secret` - File contents (recommended for VMs)
- `op://vault/item/field` - 1Password CLI
- `aws-sm://region/secret_id#json_key` - AWS Secrets Manager
- `vault://path#field` - HashiCorp Vault (KV v2)
- `sops://path#json.key` - SOPS-encrypted files

**Example Configuration**:
```toml
[secrets]
# Environment variable (Docker/K8s)
maxmind_license = "env:MAXMIND_LICENSE_KEY"
greynoise_api = "env:GREYNOISE_API_KEY"

# File-based (VM deployments)
# maxmind_license = "file:/etc/secrets/maxmind_license"
# greynoise_api = "file:/etc/secrets/greynoise_api"

# 1Password CLI (developer workstations)
# greynoise_api = "op://vault/greynoise/api_key"

# AWS Secrets Manager (AWS deployments)
# maxmind_license = "aws-sm://us-east-1/cowrie/maxmind#license_key"
# greynoise_api = "aws-sm://us-east-1/cowrie/greynoise#api_key"
```

### Cache Directory Configuration

**Default Location**: `/mnt/dshield/data/cache`

**Directory Structure**:
```
/mnt/dshield/data/cache/
├── maxmind/
│   ├── GeoLite2-City.mmdb         # Geo database (updated weekly)
│   └── GeoLite2-ASN.mmdb          # ASN database (updated weekly)
├── cymru/
│   └── asn_cache_*.json           # 90-day TTL cache files
└── greynoise/
    └── scanner_cache_*.json       # 7-day TTL cache files
```

**Custom Cache Directory**:
```toml
# config/sensors.toml
[enrichment]
cache_dir = "/custom/path/to/cache"  # Override default
```

```bash
# CLI override
cowrie-loader delta ... --cache-dir /custom/path/to/cache
```

**Permissions**:
```bash
# Ensure cache directory is writable
sudo mkdir -p /mnt/dshield/data/cache/{maxmind,cymru,greynoise}
sudo chown -R cowrie:cowrie /mnt/dshield/data/cache
sudo chmod -R 755 /mnt/dshield/data/cache
```

### CLI Overrides vs Config-Based Defaults

**Priority Hierarchy** (highest to lowest):
1. **CLI Flags**: Explicit command-line arguments
2. **Environment Variables**: Shell environment settings
3. **Config Files**: `sensors.toml` configuration
4. **Defaults**: Hardcoded application defaults

**Example Scenarios**:

**Config says enabled, CLI disables**:
```bash
# Config: enable_asn_inventory = true
# CLI: --no-asn-inventory
# Result: DISABLED (CLI wins)
```

**Config says disabled, environment enables**:
```bash
# Config: enable_asn_inventory = false
# Environment: ENABLE_ASN_INVENTORY=true
# Result: ENABLED (environment wins)
```

**No config, no CLI, use default**:
```bash
# Config: (not set)
# CLI: (not set)
# Result: ENABLED (default is true for production)
```

## Troubleshooting

### Common Issues

#### Issue 1: Missing MaxMind License Key

**Symptom**: `FileNotFoundError: GeoLite2-City.mmdb not found`

**Cause**: MaxMind databases not downloaded or license key missing

**Solution**:
```bash
# Step 1: Register for free MaxMind license key
# Visit: https://www.maxmind.com/en/geolite2/signup

# Step 2: Export license key
export MAXMIND_LICENSE_KEY="your_key_here"

# Step 3: Download databases
mkdir -p /mnt/dshield/data/cache/maxmind
cd /mnt/dshield/data/cache/maxmind

wget "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&license_key=${MAXMIND_LICENSE_KEY}&suffix=tar.gz" -O GeoLite2-City.tar.gz
wget "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-ASN&license_key=${MAXMIND_LICENSE_KEY}&suffix=tar.gz" -O GeoLite2-ASN.tar.gz

tar -xzf GeoLite2-City.tar.gz --strip-components=1 "*/GeoLite2-City.mmdb"
tar -xzf GeoLite2-ASN.tar.gz --strip-components=1 "*/GeoLite2-ASN.mmdb"

# Verify files exist
ls -lh GeoLite2-*.mmdb
```

#### Issue 2: GreyNoise Quota Exhausted

**Symptom**: `GreyNoiseClient: Quota exhausted (0/10000 remaining)`

**Cause**: Daily API quota (10K requests) exceeded

**Solution**:
```python
# Check when quota resets (midnight UTC)
import datetime
now = datetime.datetime.now(datetime.timezone.utc)
midnight_utc = now.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
reset_in = midnight_utc - now
print(f"Quota resets in {reset_in.seconds // 3600} hours {(reset_in.seconds % 3600) // 60} minutes")

# Temporary workaround: Disable GreyNoise until reset
uv run cowrie-loader delta ... --no-greynoise

# Long-term: Upgrade to GreyNoise paid plan for higher quota
# Or: Reduce enrichment frequency to stay within quota
```

#### Issue 3: Cache Permission Errors

**Symptom**: `PermissionError: [Errno 13] Permission denied: '/mnt/dshield/data/cache/cymru/...'`

**Cause**: Cache directory not writable by process user

**Solution**:
```bash
# Fix ownership
sudo chown -R $(whoami):$(whoami) /mnt/dshield/data/cache

# Or: Fix permissions
sudo chmod -R 755 /mnt/dshield/data/cache

# Verify
ls -ld /mnt/dshield/data/cache
# Should show: drwxr-xr-x user user ...
```

#### Issue 4: Team Cymru Timeout

**Symptom**: `socket.timeout: timed out` from CymruClient

**Cause**: Network issues or Cymru service degradation

**Solution**:
```bash
# Test Cymru connectivity
nc -v whois.cymru.com 43
# If connection fails, check network/firewall

# Increase timeout in config
# In Python code or CLI tool:
# cymru_client._timeout = 60  # seconds (default: 30)

# Fallback: Skip Cymru, use MaxMind only
# (Cymru only fills ~1% ASN gap, not critical)
```

#### Issue 5: Stale MaxMind Database

**Symptom**: `WARNING: MaxMind database is 21 days old (last updated: 2025-10-15)`

**Cause**: Automatic update failed or manual update needed

**Solution**:
```bash
# Manual update (requires license key)
cd /mnt/dshield/data/cache/maxmind
export MAXMIND_LICENSE_KEY="your_key_here"

# Download latest databases
wget "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&license_key=${MAXMIND_LICENSE_KEY}&suffix=tar.gz" -O GeoLite2-City.tar.gz
wget "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-ASN&license_key=${MAXMIND_LICENSE_KEY}&suffix=tar.gz" -O GeoLite2-ASN.tar.gz

# Backup old databases
mv GeoLite2-City.mmdb GeoLite2-City.mmdb.backup
mv GeoLite2-ASN.mmdb GeoLite2-ASN.mmdb.backup

# Extract new databases
tar -xzf GeoLite2-City.tar.gz --strip-components=1 "*/GeoLite2-City.mmdb"
tar -xzf GeoLite2-ASN.tar.gz --strip-components=1 "*/GeoLite2-ASN.mmdb"

# Verify update
ls -lh GeoLite2-*.mmdb
# Dates should be recent
```

### Error Messages and Solutions

| Error Message | Cause | Solution |
|---------------|-------|----------|
| `ConnectionError: Redis connection failed` | Redis not running or misconfigured | Start Redis or disable Redis L1 cache |
| `API rate limit exceeded (Cymru)` | Too many requests to Team Cymru | Reduce batch size or add delay between batches |
| `Invalid IP address: '...'` | Malformed IP in data | Validate IPs before enrichment, check data quality |
| `Database connection pool exhausted` | Too many concurrent workers | Reduce `--workers` count or increase pool size |
| `Disk space low: cache directory 95% full` | Cache directory nearing capacity | Clean old cache files or expand disk |

### Performance Tuning

**Batch Size Optimization**:
```bash
# Small dataset (<10K IPs): Small batches for fast feedback
--batch-size 100 --commit-interval 500

# Medium dataset (10K-100K IPs): Balanced batches
--batch-size 1000 --commit-interval 5000

# Large dataset (>100K IPs): Large batches for throughput
--batch-size 2000 --commit-interval 10000
```

**Worker Count Tuning**:
```bash
# CPU-bound (MaxMind only): High worker count
--workers 16  # Up to CPU core count

# Network-bound (Cymru/GreyNoise): Moderate workers
--workers 8   # Balance parallelism with rate limits

# Memory-constrained: Low worker count
--workers 2   # Each worker uses ~500MB RAM
```

**Cache Warming Strategy**:
```bash
# Pre-warm cache with top IPs before bulk operations
psql -d cowrie -c "
    SELECT ip_address FROM ip_inventory
    ORDER BY observation_count DESC
    LIMIT 10000;
" | tail -n +3 > top_ips.txt

# Enrich top IPs first (builds cache for common IPs)
uv run cowrie-enrich-asn --ip-file top_ips.txt --batch-size 100
```

### Scale Considerations

**Staging vs Production**:

| Environment | IPs | Workers | Batch Size | Commit Interval | Expected Time |
|-------------|-----|---------|------------|-----------------|---------------|
| Staging | 10K | 2 | 100 | 500 | 5-10 min |
| Small Prod | 100K | 4 | 1000 | 5000 | 30-60 min |
| Medium Prod | 500K | 8 | 2000 | 10000 | 2-4 hours |
| Large Prod | 1M+ | 16 | 2000 | 10000 | 4-8 hours |

**Resource Requirements**:

| IPs | Workers | RAM | Disk (Cache) | Network |
|-----|---------|-----|--------------|---------|
| 10K | 2 | 1GB | 100MB | Low |
| 100K | 4 | 2GB | 1GB | Moderate |
| 500K | 8 | 4GB | 5GB | High |
| 1M+ | 16 | 8GB | 10GB | Very High |

## References

- **ADR-007**: IP Inventory Enrichment Normalization
- **ADR-008**: Multi-Source Enrichment Fallback
- **Multi-Source Cascade Guide**: `docs/enrichment/multi-source-cascade-guide.md`
- **Cascade Factory Implementation**: `claudedocs/CASCADE_FACTORY_IMPLEMENTATION_SUMMARY.md`
- **MaxMind Documentation**: https://dev.maxmind.com/geoip/geolite2-free-geolocation-data
- **Team Cymru Documentation**: https://www.team-cymru.com/ip-asn-mapping
- **GreyNoise Documentation**: https://docs.greynoise.io/docs/community-api
