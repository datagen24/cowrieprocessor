Password Enrichment
===================

HIBP Integration
----------------

The HIBP (Have I Been Pwned) password enrichment system checks passwords against known data breaches using k-anonymity for privacy.

Overview
~~~~~~~~

The password enrichment system:

* Extracts passwords from Cowrie honeypot login attempts
* Checks passwords against HIBP breach database using k-anonymity
* Tracks password usage patterns across sessions
* Aggregates daily password statistics
* Maintains password breach prevalence data

Performance Optimization
~~~~~~~~~~~~~~~~~~~~~~~~

**Version 1.x** (Before November 2025):

* Filesystem cache only (L3 tier)
* Cache lookup: 5-15ms per password
* No warm cache benefit
* Performance: 1.03 iterations/sec

**Version 2.x** (Current):

* 3-tier HybridEnrichmentCache

  * Redis L1: 0.1-1ms (1-hour TTL)
  * Database L2: 1-3ms (30-day TTL)
  * Filesystem L3: 5-15ms (60-day TTL)

* **5.16x real-world speedup** (1.03 → 5.31 iterations/sec)
* 50-90% warm cache hit rate on Redis L1
* **Time savings**: 81% reduction (16.2 min → 3.1 min for 1000 passwords)

Configuration
~~~~~~~~~~~~~

Enable Redis cache (optional, degrades gracefully):

.. code-block:: bash

   # Install Redis (Ubuntu/Debian)
   sudo apt-get install redis-server

   # Configure in config/sensors.toml
   [redis]
   enabled = true
   host = "localhost"
   port = 6379
   db = 0
   ttl = 3600  # 1 hour

   # Run enrichment
   uv run cowrie-enrich passwords --last-days 7 --verbose

Architecture
~~~~~~~~~~~~

Cache Tier Workflow
^^^^^^^^^^^^^^^^^^^

.. code-block:: text

   Request → Redis L1 (check) → Database L2 (check) → Filesystem L3 (check) → HIBP API
                ↓                    ↓                       ↓
             Hit (0.1-1ms)      Hit (1-3ms)           Hit (5-15ms)
                ↓                    ↓                       ↓
             Return            Backfill L1           Backfill L1+L2
                                Return                   Return

K-Anonymity Process
^^^^^^^^^^^^^^^^^^^

1. Hash password with SHA-1
2. Send only first 5 characters to HIBP API
3. Receive list of matching hash suffixes with breach counts
4. Search locally for full hash
5. Return breach status and prevalence

Privacy Protection
^^^^^^^^^^^^^^^^^^

The k-anonymity approach ensures:

* Full password hash never sent to HIBP
* HIBP cannot determine which specific password was checked
* Only 5-character prefix revealed (matches ~800 hashes on average)

Usage Examples
~~~~~~~~~~~~~~

Basic Enrichment
^^^^^^^^^^^^^^^^

.. code-block:: bash

   # Enrich passwords from last 30 days
   uv run cowrie-enrich passwords --last-days 30

   # Enrich specific date range
   uv run cowrie-enrich passwords --start-date 2025-09-01 --end-date 2025-09-30

   # Enrich specific sensor
   uv run cowrie-enrich passwords --sensor prod-sensor-01 --last-days 7

   # Force re-enrichment
   uv run cowrie-enrich passwords --last-days 30 --force

Query Top Passwords
^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   # View top 20 most-used passwords
   uv run cowrie-enrich top-passwords --last-days 30 --limit 20

   # View newly emerged passwords
   uv run cowrie-enrich new-passwords --last-days 7 --limit 50

Prune Old Data
^^^^^^^^^^^^^^

.. code-block:: bash

   # Delete passwords not seen in 180 days
   uv run cowrie-enrich prune --retention-days 180

Performance Tuning
~~~~~~~~~~~~~~~~~~

Cache Hit Rate Optimization
^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Factors affecting cache hit rate**:

* **Batch size**: Larger batches increase intra-batch password reuse
* **Redis TTL**: Longer TTL increases cross-batch hit rate (default: 1 hour)
* **Database TTL**: Longer TTL increases cross-session hit rate (default: 30 days)
* **Filesystem TTL**: Longer TTL increases long-term hit rate (default: 60 days)

**Recommended settings for high-volume deployments**:

.. code-block:: toml

   [redis]
   enabled = true
   host = "localhost"
   port = 6379
   db = 0
   ttl = 7200  # 2 hours for better cross-batch performance

Monitoring
^^^^^^^^^^

Monitor enrichment performance with verbose logging:

.. code-block:: bash

   uv run cowrie-enrich passwords --last-days 7 --verbose --progress

Output includes:

* Cache hit rate (percentage)
* API call count (should be minimal with warm cache)
* Breached password count
* Enrichment speed (iterations/sec)

API Reference
~~~~~~~~~~~~~

.. autoclass:: cowrieprocessor.enrichment.hibp_client.HIBPPasswordEnricher
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: cowrieprocessor.enrichment.hybrid_cache.HybridEnrichmentCache
   :members:
   :undoc-members:
   :show-inheritance:

Database Schema
~~~~~~~~~~~~~~~

Password Tracking Tables
^^^^^^^^^^^^^^^^^^^^^^^^

**password_tracking**
  Stores unique passwords with breach status and usage statistics:

  * ``password_hash`` (VARCHAR): SHA-256 hash of password (primary key)
  * ``password_text`` (TEXT): Sanitized password text (NUL bytes removed)
  * ``breached`` (BOOLEAN): Whether password appears in HIBP breaches
  * ``breach_prevalence`` (INTEGER): Number of times seen in breaches
  * ``last_hibp_check`` (TIMESTAMP): Last HIBP API check timestamp
  * ``first_seen`` (TIMESTAMP): First observation in honeypot
  * ``last_seen`` (TIMESTAMP): Most recent observation
  * ``times_seen`` (INTEGER): Total observation count
  * ``unique_sessions`` (INTEGER): Number of distinct sessions

**password_session_usage**
  Junction table linking passwords to sessions:

  * ``password_id`` (INTEGER): Foreign key to password_tracking
  * ``session_id`` (VARCHAR): Session identifier
  * ``username`` (VARCHAR): Username from login attempt
  * ``success`` (BOOLEAN): Whether login succeeded
  * ``timestamp`` (TIMESTAMP): Login attempt time

**password_statistics**
  Daily aggregated password statistics:

  * ``date`` (DATE): Aggregation date (primary key)
  * ``total_attempts`` (INTEGER): Total password attempts
  * ``unique_passwords`` (INTEGER): Distinct passwords observed
  * ``breached_count`` (INTEGER): Count of breached passwords
  * ``novel_count`` (INTEGER): Count of novel (non-breached) passwords
  * ``max_prevalence`` (INTEGER): Highest breach prevalence observed

Session Enrichment
^^^^^^^^^^^^^^^^^^

**session_summaries.enrichment.password_stats**
  Per-session password statistics stored in JSONB:

.. code-block:: json

   {
     "password_stats": {
       "total_attempts": 5,
       "unique_passwords": 3,
       "breached_passwords": 2,
       "breach_prevalence_max": 1234567,
       "novel_password_hashes": ["sha256_hash1", "sha256_hash2"],
       "password_details": [
         {
           "username": "root",
           "password_sha256": "abc123...",
           "breached": true,
           "prevalence": 1234567,
           "success": false,
           "timestamp": "2025-11-26T10:30:00Z"
         }
       ]
     }
   }

Troubleshooting
~~~~~~~~~~~~~~~

Redis Connection Failures
^^^^^^^^^^^^^^^^^^^^^^^^^^

**Symptom**: Warning log message "Failed to initialize Redis client"

**Cause**: Redis server not running or unreachable

**Solution**:

1. Check Redis status: ``sudo systemctl status redis``
2. Start Redis: ``sudo systemctl start redis``
3. Test connection: ``redis-cli ping`` (should return "PONG")

If Redis is unavailable, system gracefully degrades to Database L2 + Filesystem L3.

Database Cache Failures
^^^^^^^^^^^^^^^^^^^^^^^

**Symptom**: Warning log message "Failed to initialize database cache"

**Cause**: Database connection issues or missing ``enrichment_cache`` table

**Solution**:

1. Run migrations: ``uv run cowrie-db migrate``
2. Verify table: ``uv run cowrie-db check --verbose``
3. Check database connection in ``config/sensors.toml``

PostgreSQL NUL Byte Errors
^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Symptom**: Error "invalid byte sequence for encoding UTF8: 0x00"

**Cause**: Password contains NUL bytes (``\x00``) which PostgreSQL TEXT fields cannot store

**Solution**:

This is automatically handled by ``_sanitize_text_for_postgres()`` which replaces NUL bytes with ``\x00`` escape sequence. If errors persist:

1. Check PostgreSQL logs for affected passwords
2. Re-run enrichment with ``--force`` flag
3. Report issue if sanitization is not working

Low Cache Hit Rate
^^^^^^^^^^^^^^^^^^

**Symptom**: Cache hit rate below 30% after warm-up period

**Possible causes**:

1. **Short Redis TTL**: Increase ``ttl`` in ``config/sensors.toml`` (default: 3600s)
2. **Cold cache**: First 100-200 passwords have no cache benefit
3. **Unique passwords**: If most passwords are novel, hit rate will be low
4. **Small batches**: Intra-batch reuse requires batch size >50

**Verification**:

.. code-block:: bash

   # Check cache statistics in verbose output
   uv run cowrie-enrich passwords --last-days 1 --verbose

   # Expected output:
   #   Cache hits: 700 (70%)
   #   Cache misses: 300 (30%)
   #   API calls: 300

See Also
~~~~~~~~

* :doc:`../performance/caching` - 3-Tier cache architecture
* :doc:`../performance/benchmarks` - Performance benchmarking results
* :doc:`../guides/hibp-cache-upgrade` - Migration guide for hybrid cache
