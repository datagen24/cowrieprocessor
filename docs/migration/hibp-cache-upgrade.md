# HIBP Cache Upgrade Guide

## Overview

This guide covers upgrading from filesystem-only HIBP caching to the 3-tier HybridEnrichmentCache system for 5.16x performance improvement.

## Prerequisites

- **Cowrie Processor**: Version with hybrid cache support (November 2025 or later)
- **PostgreSQL database**: Required for L2 cache tier
- **Redis server**: Optional but recommended for L1 cache tier (can be installed during upgrade)
- **Python**: 3.13+ with `uv` package manager

## Expected Benefits

After upgrading:

- **Performance**: 5.16x faster password enrichment (1.03 → 5.31 iterations/sec)
- **Time savings**: 81% reduction for 1000 passwords (16.2 min → 3.1 min)
- **Cache efficiency**: 65-85% hit rate on Redis L1 tier (after warm-up)
- **Graceful degradation**: Falls back to Database L2 + Filesystem L3 if Redis unavailable

## Migration Steps

### Step 1: Update Codebase

Pull the latest code with hybrid cache support:

```bash
cd /home/speterson/cowrieprocessor
git pull origin main  # Or feature/hibp-hybrid-cache branch

# Rebuild package
uv sync
```

### Step 2: Install Redis (Optional)

Redis provides the fastest L1 cache tier (0.1-1ms latency). If unavailable, the system gracefully degrades to Database L2 + Filesystem L3.

#### Ubuntu/Debian

```bash
# Install Redis
sudo apt-get update
sudo apt-get install redis-server

# Start Redis service
sudo systemctl start redis
sudo systemctl enable redis

# Verify installation
redis-cli ping  # Should return "PONG"
```

#### macOS

```bash
# Install via Homebrew
brew install redis

# Start Redis service
brew services start redis

# Verify installation
redis-cli ping  # Should return "PONG"
```

#### Docker (Alternative)

```bash
# Run Redis in Docker
docker run -d \
    --name cowrie-redis \
    -p 6379:6379 \
    -v /mnt/dshield/data/redis:/data \
    redis:7-alpine

# Verify
docker exec cowrie-redis redis-cli ping
```

### Step 3: Configure Redis

Create or update `config/sensors.toml` (or `sensors.toml` in project root):

```toml
[redis]
enabled = true
host = "localhost"
port = 6379
db = 0
ttl = 3600  # 1 hour (recommended for password enrichment)

# Optional: Redis password protection
# password = "your-secure-password"

# Optional: Connection pool settings
# max_connections = 50
# socket_timeout = 5
# socket_connect_timeout = 5
```

### Step 4: Verify Database Cache

The Database L2 cache uses the existing `enrichment_cache` table. Verify it exists:

```bash
# Check database schema
uv run cowrie-db check --verbose

# Expected output:
#   Database schema version: 16
#   Table: enrichment_cache ... OK
#   Index: idx_enrichment_cache_expires ... OK
```

If the table is missing, run migrations:

```bash
uv run cowrie-db migrate
```

### Step 5: Test Configuration

Test the hybrid cache with a small enrichment batch:

```bash
# Test with last 1 day (dry run)
uv run cowrie-enrich passwords --last-days 1 --verbose

# Expected output:
#   Redis L1 cache initialized successfully
#   Database L2 cache initialized successfully
#   Filesystem L3 cache fallback active
#   Enriched 100 passwords in 18.8 seconds
#   Performance: 5.31 iterations/sec (5.16x speedup)
#   Cache hit rate: 70%
```

### Step 6: Warm Cache (Optional)

Pre-populate cache with historical data for immediate performance benefit:

```bash
# Enrich last 30 days to warm cache
uv run cowrie-enrich passwords --last-days 30 --verbose --progress
```

This creates a warm Redis L1 cache with common passwords, maximizing future cache hit rates.

### Step 7: Production Deployment

Once tested, deploy to production:

```bash
# Full enrichment with hybrid cache
uv run cowrie-enrich passwords --last-days 7 --verbose --progress

# Monitor performance
tail -f /var/log/cowrieprocessor/enrichment.log | grep "iterations/sec"
```

## Configuration Tuning

### High-Volume Deployments (>10K passwords/day)

Optimize for maximum throughput:

```toml
[redis]
enabled = true
host = "localhost"
port = 6379
db = 0
ttl = 7200  # 2 hours for better cross-batch performance
max_connections = 100  # Increase connection pool

[cache]
database_ttl_days = 60  # Longer retention
filesystem_ttl_days = 90
```

### Low-Volume Deployments (<1K passwords/day)

Optimize for resource efficiency:

```toml
[redis]
enabled = false  # Skip Redis overhead

[cache]
database_ttl_days = 30  # Standard retention
filesystem_ttl_days = 60
```

### Memory-Constrained Systems

Optimize for minimal memory footprint:

```toml
[redis]
enabled = false  # Disable Redis

[cache]
database_ttl_days = 7  # Aggressive expiration
filesystem_ttl_days = 14
```

Configure Redis memory limit (if enabled):

```bash
# /etc/redis/redis.conf
maxmemory 512mb
maxmemory-policy allkeys-lru
```

## Performance Validation

### Benchmark Performance

Run before/after benchmarks to validate improvement:

**Before upgrade** (Filesystem-only):

```bash
# Record baseline performance
time uv run cowrie-enrich passwords --last-days 1 --verbose | tee baseline.log

# Expected: ~1.03 iterations/sec
```

**After upgrade** (Hybrid cache):

```bash
# Record optimized performance
time uv run cowrie-enrich passwords --last-days 1 --verbose | tee optimized.log

# Expected: ~5.31 iterations/sec (5.16x speedup)
```

### Monitor Cache Hit Rates

Track cache performance over time:

```bash
# Enable verbose logging
uv run cowrie-enrich passwords --last-days 7 --verbose | grep "Cache hit rate"

# Expected output:
#   Cache hit rate: 70% (Redis L1: 65%, Database L2: 5%)
#   API calls: 300 (30%)
```

Target metrics:

- **Cache hit rate**: >60% (after warm-up)
- **Redis L1 hits**: 50-80%
- **Database L2 hits**: 10-20%
- **API calls**: <30%

## Rollback Procedure

If issues occur, the system gracefully degrades without data loss:

### Option 1: Disable Redis (Keep Database L2)

```toml
[redis]
enabled = false  # Falls back to Database L2 + Filesystem L3
```

Performance: ~2-3 iterations/sec (still 2-3x speedup vs baseline)

### Option 2: Disable All Hybrid Cache

```bash
# Set environment variable to force filesystem-only cache
export USE_LEGACY_CACHE=true

uv run cowrie-enrich passwords --last-days 7
```

Performance: ~1.03 iterations/sec (baseline, no regression)

### Option 3: Complete Rollback

Revert to previous codebase version:

```bash
# Checkout previous version
git checkout <previous-commit-hash>

# Rebuild package
uv sync

# Run with old cache system
uv run cowrie-enrich passwords --last-days 7
```

**Important**: No data loss occurs during rollback. All enrichment data is preserved in the database.

## Troubleshooting

### Redis Connection Failures

**Symptom**: Warning "Failed to connect to Redis"

**Diagnosis**:

```bash
# Check Redis status
sudo systemctl status redis

# Test connection
redis-cli ping  # Should return "PONG"

# Check Redis logs
sudo tail -f /var/log/redis/redis-server.log
```

**Solution**:

1. Start Redis: `sudo systemctl start redis`
2. Check firewall: `sudo ufw allow 6379`
3. Verify bind address: `redis-cli CONFIG GET bind`
4. Check password (if configured): `redis-cli AUTH <password>`

If Redis cannot be fixed, system automatically falls back to Database L2 + Filesystem L3 (no data loss).

### Database Cache Failures

**Symptom**: Warning "Failed to initialize database cache"

**Diagnosis**:

```bash
# Check database connection
uv run cowrie-db check --verbose

# Verify enrichment_cache table
psql -d cowrie -c "\d enrichment_cache"

# Check table permissions
psql -d cowrie -c "SELECT grantee, privilege_type FROM information_schema.role_table_grants WHERE table_name = 'enrichment_cache';"
```

**Solution**:

1. Run migrations: `uv run cowrie-db migrate`
2. Grant permissions: `GRANT ALL ON enrichment_cache TO cowrie_user;`
3. Rebuild indexes: `REINDEX TABLE enrichment_cache;`

If database cache cannot be fixed, system automatically falls back to Filesystem L3 (no data loss).

### Low Cache Hit Rate

**Symptom**: Cache hit rate <30% after 100+ passwords

**Possible causes**:

1. **Cold cache**: First 100-200 passwords have no cache benefit (expected)
2. **Short TTL**: Redis TTL too short for cross-batch reuse
3. **Unique passwords**: Most passwords are novel (expected for targeted attacks)
4. **Redis memory limit**: Cache eviction due to memory pressure

**Diagnosis**:

```bash
# Check Redis memory usage
redis-cli INFO memory | grep used_memory_human

# Check Redis eviction rate
redis-cli INFO stats | grep evicted_keys

# Check cache statistics
uv run cowrie-enrich passwords --last-days 1 --verbose | tail -20
```

**Solution**:

1. **Increase Redis TTL**:
   ```toml
   [redis]
   ttl = 7200  # 2 hours instead of 1
   ```

2. **Increase Redis memory**:
   ```bash
   # /etc/redis/redis.conf
   maxmemory 2gb  # Increase from 512mb
   ```

3. **Pre-warm cache**:
   ```bash
   uv run cowrie-enrich passwords --last-days 30
   ```

### Performance Degradation

**Symptom**: Enrichment slower than baseline (< 1.0 iterations/sec)

**Diagnosis**:

```bash
# Check Redis latency
redis-cli --latency

# Check database query performance
psql -d cowrie -c "EXPLAIN ANALYZE SELECT * FROM enrichment_cache WHERE service = 'hibp' LIMIT 100;"

# Check filesystem I/O
iostat -x 1 10
```

**Solution**:

1. **Redis slow**: Restart Redis, check CPU/memory usage
2. **Database slow**: Run VACUUM ANALYZE, add indexes
3. **Filesystem slow**: Move cache to SSD, check disk I/O

If degradation persists, disable hybrid cache and revert to filesystem-only (baseline performance).

## Monitoring

### Operational Metrics

Track key metrics in production:

```bash
# Performance metrics
uv run cowrie-enrich passwords --last-days 1 --verbose | grep "iterations/sec"

# Cache hit rates
redis-cli INFO stats | grep keyspace_hits

# Database cache size
psql -d cowrie -c "SELECT COUNT(*), pg_size_pretty(SUM(pg_column_size(value))) FROM enrichment_cache WHERE service = 'hibp';"

# Filesystem cache size
du -sh /mnt/dshield/data/cache/hibp/
```

### Alerting Thresholds

Set alerts for:

- **Performance**: Iterations/sec < 3.0 (below target)
- **Cache hit rate**: < 50% (after warm-up)
- **Redis memory**: > 80% of max_memory
- **Database cache size**: > 10GB
- **Error rate**: > 1%

## FAQ

### Q: Is Redis required for the hybrid cache?

**A**: No, Redis is optional. If unavailable, the system gracefully degrades to Database L2 + Filesystem L3, providing 2-3x speedup vs baseline.

### Q: Will upgrading affect existing enrichment data?

**A**: No, all existing data is preserved. The hybrid cache only changes how data is cached, not how it's stored.

### Q: Can I run Redis on a separate server?

**A**: Yes, configure Redis host in `config/sensors.toml`:

```toml
[redis]
enabled = true
host = "redis.example.com"
port = 6379
```

### Q: How much Redis memory do I need?

**A**: Depends on volume:

- Low (<1K passwords/day): 512MB
- Medium (1-10K passwords/day): 1-2GB
- High (>10K passwords/day): 4-8GB

### Q: Can I use Redis Cluster or Sentinel?

**A**: Currently, only standalone Redis is supported. Cluster/Sentinel support is planned for future releases.

### Q: What happens if Redis runs out of memory?

**A**: Redis evicts least-recently-used (LRU) entries. System continues to work, but cache hit rate decreases. Increase `maxmemory` or enable LRU eviction.

### Q: How do I clear the cache?

**A**: Clear caches by tier:

```bash
# Clear Redis (L1)
redis-cli FLUSHDB

# Clear Database (L2)
psql -d cowrie -c "DELETE FROM enrichment_cache WHERE service = 'hibp';"

# Clear Filesystem (L3)
rm -rf /mnt/dshield/data/cache/hibp/
```

### Q: Can I test the upgrade without affecting production?

**A**: Yes, test in a separate environment first:

1. Clone production database to test environment
2. Install Redis on test server
3. Run enrichment with hybrid cache
4. Validate performance improvements
5. Deploy to production once tested

## Support

For issues or questions:

1. **Check logs**: `/var/log/cowrieprocessor/enrichment.log`
2. **Run diagnostics**: `uv run cowrie-db check --verbose`
3. **Open issue**: [GitHub Issues](https://github.com/datagen24/cowrieprocessor/issues)
4. **Documentation**: See Sphinx docs for detailed API reference

## See Also

- [Password Enrichment Guide](../sphinx/source/enrichment/password-enrichment.rst) - HIBP integration details
- [Caching Architecture](../sphinx/source/performance/caching.rst) - 3-tier cache design
- [Performance Benchmarks](../sphinx/source/performance/benchmarks.rst) - Detailed performance analysis
- [Validation Summary](../fixes/validation-summary.md) - Code change validation report
