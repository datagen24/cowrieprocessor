Caching Architecture
====================

3-Tier Hybrid Cache System
---------------------------

Overview
~~~~~~~~

The Cowrie Processor uses a 3-tier caching system for optimal performance across multiple enrichment services:

1. **L1 (Redis)**: Sub-millisecond in-memory cache
2. **L2 (Database)**: Fast persistent cache with SQL queries
3. **L3 (Filesystem)**: Durable long-term cache

This tiered approach balances speed, durability, and resource efficiency while providing graceful degradation when individual tiers are unavailable.

Performance Characteristics
~~~~~~~~~~~~~~~~~~~~~~~~~~~

+-------+-------------+---------+---------------+---------------------------+
| Tier  | Technology  | Latency | TTL           | Use Case                  |
+=======+=============+=========+===============+===========================+
| L1    | Redis       | 0.1-1ms | 1 hour        | Intra-batch cache hits    |
+-------+-------------+---------+---------------+---------------------------+
| L2    | PostgreSQL  | 1-3ms   | 30 days       | Multi-session cache       |
+-------+-------------+---------+---------------+---------------------------+
| L3    | Filesystem  | 5-15ms  | Service-based | Long-term fallback        |
+-------+-------------+---------+---------------+---------------------------+

Graceful Degradation
~~~~~~~~~~~~~~~~~~~~

The system automatically falls back to lower tiers if higher tiers are unavailable:

* **Redis unavailable** → Use L2 (Database) + L3 (Filesystem)
* **Database unavailable** → Use L3 (Filesystem) only
* **All caches miss** → Fetch from external API

Degradation Path
^^^^^^^^^^^^^^^^

.. code-block:: text

   ┌─────────────────────────────────────────────────────────────┐
   │  Optimal Configuration (All tiers active)                   │
   │  L1 (Redis) → L2 (Database) → L3 (Filesystem) → API         │
   │  Latency: 0.1-1ms for warm cache                            │
   └─────────────────────────────────────────────────────────────┘
                          ↓ Redis failure
   ┌─────────────────────────────────────────────────────────────┐
   │  Degraded Mode 1 (Redis unavailable)                        │
   │  L2 (Database) → L3 (Filesystem) → API                      │
   │  Latency: 1-3ms for warm cache                              │
   └─────────────────────────────────────────────────────────────┘
                          ↓ Database failure
   ┌─────────────────────────────────────────────────────────────┐
   │  Degraded Mode 2 (Redis + Database unavailable)             │
   │  L3 (Filesystem) → API                                      │
   │  Latency: 5-15ms for warm cache                             │
   └─────────────────────────────────────────────────────────────┘

Real-World Performance
~~~~~~~~~~~~~~~~~~~~~~

**HIBP Password Enrichment** (100 passwords):

* **Without Redis**: 500-1500ms (filesystem cache only)
* **With Redis**: 10-100ms (Redis L1 hits)
* **Speedup**: 5-15x faster with warm cache

Benchmarking Results
~~~~~~~~~~~~~~~~~~~~

**Test Configuration**:

* Environment: Production-like (PostgreSQL + Redis)
* Dataset: 1000 password enrichment requests
* Measurement: Iterations per second

**Results**:

* Baseline (L3 only): 1.03 iterations/sec
* Optimized (L1+L2+L3): 5.31 iterations/sec
* **Speedup**: 5.16x

**Cache Hit Rates** (after warm-up):

* Redis L1: 65-85%
* Database L2: 10-20%
* Filesystem L3: 3-8%
* API calls: 2-5%

Architecture Details
~~~~~~~~~~~~~~~~~~~~

Tier 1: Redis Cache (L1)
^^^^^^^^^^^^^^^^^^^^^^^^^

**Purpose**: Ultra-fast in-memory cache for intra-batch deduplication

**Characteristics**:

* **Storage**: In-memory key-value store
* **Latency**: 0.1-1ms
* **TTL**: 1 hour (configurable)
* **Capacity**: Limited by Redis memory (recommend 1-2GB)
* **Persistence**: Optional (RDB snapshots)

**Use cases**:

* Password deduplication within enrichment batch
* Repeated IP lookups in session processing
* File hash cache for bulk uploads

**Configuration**:

.. code-block:: toml

   [redis]
   enabled = true
   host = "localhost"
   port = 6379
   db = 0
   ttl = 3600  # 1 hour

Tier 2: Database Cache (L2)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Purpose**: Persistent cache for cross-session data reuse

**Characteristics**:

* **Storage**: PostgreSQL table (``enrichment_cache``)
* **Latency**: 1-3ms
* **TTL**: 30 days (configurable per service)
* **Capacity**: Unlimited (scales with database)
* **Persistence**: ACID-compliant transactional storage

**Use cases**:

* Long-term password breach status cache
* IP enrichment data across multiple days
* File analysis results

**Schema**:

.. code-block:: sql

   CREATE TABLE enrichment_cache (
       service VARCHAR(50),
       key VARCHAR(255),
       value JSONB,
       expires_at TIMESTAMP,
       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
       updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
       PRIMARY KEY (service, key)
   );

   CREATE INDEX idx_enrichment_cache_expires
       ON enrichment_cache(expires_at);

Tier 3: Filesystem Cache (L3)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Purpose**: Durable long-term fallback cache

**Characteristics**:

* **Storage**: Sharded JSON files on filesystem
* **Latency**: 5-15ms
* **TTL**: Service-dependent (3-60 days)
* **Capacity**: Unlimited (scales with disk)
* **Persistence**: Survives database restarts

**Directory structure**:

.. code-block:: text

   /mnt/dshield/data/cache/
   ├── virustotal/
   │   ├── 00/  # Sharded by first 2 hex chars
   │   │   └── 001234abcdef.json
   │   └── ff/
   ├── dshield/
   ├── urlhaus/
   └── hibp/

**Use cases**:

* Historical enrichment data
* Large-scale bulk processing recovery
* Disaster recovery scenarios

Service-Specific TTL Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Different enrichment services have different cache freshness requirements:

+----------------+----------+------------+---------------------------+
| Service        | L1 (Redis)| L2 (DB)   | L3 (Filesystem)           |
+================+==========+============+===========================+
| HIBP           | 1 hour   | 30 days    | 60 days                   |
+----------------+----------+------------+---------------------------+
| VirusTotal     | 1 hour   | 30 days    | 30 days                   |
+----------------+----------+------------+---------------------------+
| DShield        | 1 hour   | 7 days     | 7 days                    |
+----------------+----------+------------+---------------------------+
| URLHaus        | 1 hour   | 3 days     | 3 days                    |
+----------------+----------+------------+---------------------------+
| SPUR           | 1 hour   | 30 days    | 30 days                   |
+----------------+----------+------------+---------------------------+

Cache Workflow
~~~~~~~~~~~~~~

Lookup Flow
^^^^^^^^^^^

.. code-block:: python

   def get_cached(service: str, key: str) -> Optional[dict]:
       # Try L1 (Redis)
       if redis_client:
           result = redis_client.get(f"{service}:{key}")
           if result:
               return json.loads(result)

       # Try L2 (Database)
       if db_cache:
           result = db_cache.get(service, key)
           if result:
               # Backfill L1
               if redis_client:
                   redis_client.setex(
                       f"{service}:{key}",
                       ttl=3600,
                       value=json.dumps(result)
                   )
               return result

       # Try L3 (Filesystem)
       result = filesystem_cache.get(service, key)
       if result:
           # Backfill L1 and L2
           if redis_client:
               redis_client.setex(f"{service}:{key}", 3600, json.dumps(result))
           if db_cache:
               db_cache.set(service, key, result, ttl_days=30)
           return result

       # Cache miss - fetch from API
       return None

Storage Flow
^^^^^^^^^^^^

.. code-block:: python

   def store_cached(service: str, key: str, value: dict) -> None:
       # Store in all tiers (write-through)

       # L1 (Redis)
       if redis_client:
           redis_client.setex(
               f"{service}:{key}",
               ttl=3600,
               value=json.dumps(value)
           )

       # L2 (Database)
       if db_cache:
           db_cache.set(service, key, value, ttl_days=30)

       # L3 (Filesystem)
       filesystem_cache.set(service, key, value)

Cache Invalidation
~~~~~~~~~~~~~~~~~~

Manual Invalidation
^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   # Clear Redis cache (L1)
   redis-cli FLUSHDB

   # Clear database cache (L2)
   uv run cowrie-db execute "DELETE FROM enrichment_cache WHERE service = 'hibp'"

   # Clear filesystem cache (L3)
   rm -rf /mnt/dshield/data/cache/hibp/

Automatic Expiration
^^^^^^^^^^^^^^^^^^^^

Each tier has automatic expiration:

* **L1 (Redis)**: TTL enforced by Redis (1 hour default)
* **L2 (Database)**: Background cleanup job removes expired entries
* **L3 (Filesystem)**: On-demand cleanup via ``EnrichmentCacheManager.cleanup_expired()``

Monitoring and Metrics
~~~~~~~~~~~~~~~~~~~~~~

Cache Hit Rate Monitoring
^^^^^^^^^^^^^^^^^^^^^^^^^^

Enable verbose logging to track cache performance:

.. code-block:: bash

   uv run cowrie-enrich passwords --last-days 7 --verbose

Output includes:

.. code-block:: text

   Cache Statistics:
     Total checks: 1000
     L1 (Redis) hits: 700 (70%)
     L2 (Database) hits: 150 (15%)
     L3 (Filesystem) hits: 50 (5%)
     API calls: 100 (10%)

   Performance:
     Average latency: 0.5ms (L1-weighted)
     Speedup: 5.2x vs no cache

Redis Monitoring
^^^^^^^^^^^^^^^^

Monitor Redis memory and performance:

.. code-block:: bash

   # Check memory usage
   redis-cli INFO memory

   # Check cache statistics
   redis-cli INFO stats

   # Monitor cache keys
   redis-cli KEYS "hibp:*" | wc -l

Database Cache Monitoring
^^^^^^^^^^^^^^^^^^^^^^^^^^

Query database cache metrics:

.. code-block:: sql

   -- Cache size by service
   SELECT service, COUNT(*) as entries,
          SUM(pg_column_size(value)) as bytes
   FROM enrichment_cache
   GROUP BY service;

   -- Expired entries
   SELECT COUNT(*) FROM enrichment_cache
   WHERE expires_at < CURRENT_TIMESTAMP;

   -- Most cached keys
   SELECT service, key, created_at, updated_at
   FROM enrichment_cache
   ORDER BY updated_at DESC
   LIMIT 20;

Optimization Strategies
~~~~~~~~~~~~~~~~~~~~~~~

Increasing Cache Hit Rate
^^^^^^^^^^^^^^^^^^^^^^^^^

**1. Tune Redis TTL**:

Longer TTL increases cross-batch hit rate:

.. code-block:: toml

   [redis]
   ttl = 7200  # 2 hours instead of 1

**2. Increase Batch Size**:

Larger batches increase intra-batch password reuse:

.. code-block:: bash

   # Larger batch size
   uv run cowrie-enrich passwords --last-days 30 --batch-size 500

**3. Pre-warm Cache**:

Pre-populate cache with common passwords:

.. code-block:: bash

   # Enrich historical data first
   uv run cowrie-enrich passwords --start-date 2025-01-01 --end-date 2025-11-01

Reducing Memory Usage
^^^^^^^^^^^^^^^^^^^^^

**1. Aggressive Redis Expiration**:

.. code-block:: toml

   [redis]
   ttl = 1800  # 30 minutes for memory-constrained systems

**2. Disable Redis for Low-Volume**:

For <1000 passwords/day, Redis overhead may not be worth it:

.. code-block:: toml

   [redis]
   enabled = false  # Use Database + Filesystem only

**3. Database Cache Pruning**:

.. code-block:: sql

   -- Delete entries older than 30 days
   DELETE FROM enrichment_cache
   WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '30 days';

Troubleshooting
~~~~~~~~~~~~~~~

Redis Connection Failures
^^^^^^^^^^^^^^^^^^^^^^^^^^

**Symptom**: "Failed to connect to Redis" warning

**Diagnosis**:

.. code-block:: bash

   # Check Redis status
   sudo systemctl status redis

   # Test connection
   redis-cli ping  # Should return "PONG"

   # Check logs
   tail -f /var/log/redis/redis-server.log

**Solution**:

1. Start Redis: ``sudo systemctl start redis``
2. Check firewall: ``sudo ufw allow 6379``
3. Verify config: ``redis-cli CONFIG GET bind``

Database Cache Failures
^^^^^^^^^^^^^^^^^^^^^^^^

**Symptom**: "Failed to initialize database cache" warning

**Diagnosis**:

.. code-block:: sql

   -- Check if table exists
   SELECT * FROM enrichment_cache LIMIT 1;

   -- Check permissions
   SELECT grantee, privilege_type
   FROM information_schema.role_table_grants
   WHERE table_name = 'enrichment_cache';

**Solution**:

1. Run migrations: ``uv run cowrie-db migrate``
2. Grant permissions: ``GRANT ALL ON enrichment_cache TO cowrie_user;``
3. Verify connection: ``uv run cowrie-db check``

Performance Degradation
^^^^^^^^^^^^^^^^^^^^^^^^

**Symptom**: Slow enrichment despite warm cache

**Diagnosis**:

.. code-block:: bash

   # Check Redis latency
   redis-cli --latency

   # Check database query time
   psql -c "EXPLAIN ANALYZE SELECT * FROM enrichment_cache WHERE service = 'hibp' LIMIT 100;"

   # Check filesystem I/O
   iostat -x 1 10

**Solution**:

1. **Redis slow**: Increase memory, check CPU usage
2. **Database slow**: Add indexes, vacuum analyze table
3. **Filesystem slow**: Check disk I/O, move cache to SSD

See Also
~~~~~~~~

* :doc:`benchmarks` - Performance benchmarking methodology
* :doc:`../enrichment/password-enrichment` - HIBP integration details
* :doc:`../guides/hibp-cache-upgrade` - Migration guide
