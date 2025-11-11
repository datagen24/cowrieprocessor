IP Classification User Guide
==============================

Overview
--------

The IP Classification service automatically identifies the infrastructure type of IP addresses encountered in Cowrie honeypot logs. This enables advanced threat detection features like snowshoe spam detection, botnet identification, and infrastructure clustering.

**What it classifies:**

- **TOR exit nodes** (95%+ accuracy, official Tor Project data)
- **Cloud providers**: AWS, Azure, GCP, CloudFlare (99%+ accuracy)
- **Datacenters and hosting providers** (70-80% accuracy)
- **Residential ISPs** via ASN heuristics (70-80% accuracy)

**Cost**: $0/month (all free data sources)

**Coverage**: 90%+ of honeypot IPs classified with confidence scores

Quick Start
-----------

Basic Usage
~~~~~~~~~~~

The IP classification service is automatically invoked during enrichment workflows:

.. code-block:: bash

   # Enrich IPs encountered in the last 7 days
   uv run cowrie-enrich refresh --ips 1000 --verbose

   # Or refresh all stale IPs (>30 days old)
   uv run cowrie-enrich refresh --ips 0 --verbose

Python API
~~~~~~~~~~

You can also use the classification service directly in Python:

.. code-block:: python

   from pathlib import Path
   from cowrieprocessor.enrichment.ip_classification import create_ip_classifier
   from cowrieprocessor.db.engine import get_engine

   # Create classifier with default cache directory
   classifier = create_ip_classifier(
       cache_dir=Path("/mnt/dshield/data/cache"),
       db_engine=get_engine("postgresql://...")
   )

   # Classify a single IP
   result = classifier.classify("8.8.8.8")
   print(f"Type: {result.ip_type}")
   print(f"Provider: {result.provider}")
   print(f"Confidence: {result.confidence}")

   # Bulk classify multiple IPs
   ips = ["52.0.0.1", "104.16.0.1", "13.107.0.1"]
   results = classifier.bulk_classify(ips)
   for ip, classification in results.items():
       print(f"{ip}: {classification.ip_type} ({classification.confidence:.0%})")

Architecture
------------

Three-Tier Enrichment
~~~~~~~~~~~~~~~~~~~~~

IP classification integrates with the existing three-tier enrichment architecture (ADR-007):

**Tier 1: ASN Inventory**
   Organization-level metadata (most stable, yearly updates)

**Tier 2: IP Inventory** ← *IPClassifier runs here*
   - Pass 1: MaxMind GeoIP2 (offline, geographic data)
   - Pass 2: Team Cymru ASN lookups (online, 500 IPs/batch)
   - Pass 3: GreyNoise (online, malicious activity)
   - **Pass 4: IPClassifier (NEW)** - Infrastructure type classification

**Tier 3: Session Summaries**
   - Immutable point-in-time snapshots
   - ``snapshot_ip_type`` column auto-populated from IP inventory
   - Preserves "what was it at time of attack" temporal accuracy

Multi-Tier Cache
~~~~~~~~~~~~~~~~

The classifier uses a three-tier cache for performance:

**L1 (Redis)**: In-memory, <1ms latency
   - TOR/Unknown: 1 hour TTL
   - Cloud/DC/Residential: 24 hour TTL

**L2 (Database)**: enrichment_cache table, <10ms latency
   - 7-day TTL for all classifications

**L3 (Disk)**: Filesystem sharded by IP octets, <50ms latency
   - 30-day TTL
   - Path example: ``1.2.3.4`` → ``cache_dir/1/2/3/4.json``

**Cache warming**: Upper tiers populated automatically on lower tier hits

**Hit rate target**: >95% after warmup

Classification Priority
~~~~~~~~~~~~~~~~~~~~~~~

IPs are classified using priority-ordered matchers:

1. **TOR Exit Nodes** (Priority 1)
   - O(1) set lookup
   - Data source: Tor Project bulk exit list
   - Confidence: 95%

2. **Cloud Providers** (Priority 2)
   - PyTricia tree lookups for AWS, Azure, GCP, CloudFlare
   - Data source: GitHub rezmoss/cloud-provider-ip-addresses
   - Confidence: 99%

3. **Datacenters** (Priority 3)
   - PyTricia tree for hosting providers
   - Data source: GitHub jhassine/server-ip-addresses
   - Confidence: 75%

4. **Residential ISPs** (Priority 4)
   - Regex patterns on ASN names (telecom, broadband, mobile)
   - Requires ASN data from Team Cymru
   - Confidence: 70%

5. **Unknown** (Fallback)
   - Applied when no matchers succeed
   - Confidence: 0%

Data Models
-----------

IPType Enum
~~~~~~~~~~~

.. code-block:: python

   from cowrieprocessor.enrichment.ip_classification.models import IPType

   class IPType(str, Enum):
       TOR = "tor"
       CLOUD = "cloud"
       DATACENTER = "datacenter"
       RESIDENTIAL = "residential"
       UNKNOWN = "unknown"

IPClassification Dataclass
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from cowrieprocessor.enrichment.ip_classification.models import IPClassification

   @dataclass(slots=True, frozen=True)
   class IPClassification:
       ip_type: IPType
       provider: Optional[str]  # e.g., "aws", "azure", "tor", None
       confidence: float        # 0.0 to 1.0
       source: str              # e.g., "cloud_ranges_aws", "tor_bulk_list"
       classified_at: datetime

Integration Points
------------------

Automatic Integration
~~~~~~~~~~~~~~~~~~~~~

IPClassifier is automatically invoked by:

1. **Bulk Load** (``cowrie-loader bulk``)
   - Classifies all IPs during initial import
   - Populates ``snapshot_ip_type`` in session summaries

2. **Delta Load** (``cowrie-loader delta``)
   - Classifies new IPs encountered in incremental loads

3. **Refresh** (``cowrie-enrich refresh --ips N``)
   - Re-classifies stale IPs (>30 days old)
   - Controlled by ``--ips`` flag for batch size

Database Schema
~~~~~~~~~~~~~~~

**ip_inventory Table** (mutable current state):

- ``ip_type`` (computed column): Current classification from enrichment JSON
- ``is_scanner`` (computed column): Boolean from ip_types array
- ``enrichment`` (JSONB): Full enrichment data including ``ip_classification`` key

**session_summaries Table** (immutable snapshots):

- ``snapshot_ip_type`` (string): Point-in-time classification at session time
- ``snapshot_asn`` (integer): ASN at session time
- ``snapshot_country`` (string): GeoIP country at session time

Data Source Updates
-------------------

Update Frequencies
~~~~~~~~~~~~~~~~~~

The classifier depends on external data sources that must be refreshed:

+-------------------+-------------+------------+
| Data Source       | Frequency   | Critical   |
+===================+=============+============+
| TOR Exit Nodes    | **Hourly**  | High       |
+-------------------+-------------+------------+
| Cloud Providers   | **Daily**   | High       |
+-------------------+-------------+------------+
| Datacenters       | **Weekly**  | Medium     |
+-------------------+-------------+------------+

Manual Updates
~~~~~~~~~~~~~~

Update specific data sources:

.. code-block:: python

   from cowrieprocessor.enrichment.ip_classification import create_ip_classifier
   from pathlib import Path
   from cowrieprocessor.db.engine import get_engine

   classifier = create_ip_classifier(
       cache_dir=Path("/mnt/dshield/data/cache"),
       db_engine=get_engine("postgresql://...")
   )

   # Update TOR exit nodes
   classifier.tor_matcher._download_data()

   # Update cloud provider ranges
   classifier.cloud_matcher._download_data()

   # Update datacenter ranges
   classifier.datacenter_matcher._download_data()

   # Update all sources
   classifier.update_all_sources()

Automated Updates (Cron)
~~~~~~~~~~~~~~~~~~~~~~~~~

Create ``/etc/cron.d/ip-classification-updates``:

.. code-block:: bash

   # TOR exit nodes - Hourly (at minute 15)
   15 * * * * dshield cd /mnt/dshield/cowrieprocessor && uv run python -c "from cowrieprocessor.enrichment.ip_classification import create_ip_classifier; ..."

   # Cloud ranges - Daily (3:00 AM)
   0 3 * * * dshield cd /mnt/dshield/cowrieprocessor && uv run python -c "..."

   # Datacenter ranges - Weekly (Sunday 4:00 AM)
   0 4 * * 0 dshield cd /mnt/dshield/cowrieprocessor && uv run python -c "..."

See ``docs/operations/ip_classification_data_updates.md`` for complete cron configuration.

Performance
-----------

Latency Targets
~~~~~~~~~~~~~~~

+---------------------------+--------------+--------------+
| Operation                 | p50 Target   | p99 Target   |
+===========================+==============+==============+
| Classify (Redis hit)      | <1ms         | <2ms         |
+---------------------------+--------------+--------------+
| Classify (DB hit)         | <5ms         | <15ms        |
+---------------------------+--------------+--------------+
| Classify (uncached)       | <8ms         | <20ms        |
+---------------------------+--------------+--------------+
| Bulk 1K IPs (95% cached)  | <100ms       | <300ms       |
+---------------------------+--------------+--------------+

Throughput
~~~~~~~~~~

With 95% cache hit rate (typical after warmup):

- Single IP classification: ~20/sec
- Bulk classification: ~1,000/sec (batched)

Statistics Tracking
~~~~~~~~~~~~~~~~~~~

The classifier maintains internal statistics:

.. code-block:: python

   stats = classifier.get_stats()
   print(f"Classifications: {stats['classifications_total']}")
   print(f"Cache hit rate: {stats['cache_hit_rate']:.1%}")
   print(f"TOR matches: {stats['matches_by_type']['tor']}")
   print(f"Cloud matches: {stats['matches_by_type']['cloud']}")

Troubleshooting
---------------

Low Coverage (<90%)
~~~~~~~~~~~~~~~~~~~

**Symptom**: ``snapshot_ip_type`` is "unknown" for most sessions

**Solutions**:

1. Verify data sources are up-to-date:

   .. code-block:: bash

      uv run python -c "from cowrieprocessor.enrichment.ip_classification import create_ip_classifier; from pathlib import Path; classifier = create_ip_classifier(cache_dir=Path('/mnt/dshield/data/cache')); print(classifier.tor_matcher.get_stats()); print(classifier.cloud_matcher.get_stats())"

2. Check for missing ASN data (required for residential classification):

   .. code-block:: sql

      SELECT COUNT(*) FROM ip_inventory WHERE enrichment->>'asn' IS NULL;

3. Re-run enrichment for IPs with missing ASN data:

   .. code-block:: bash

      uv run cowrie-enrich refresh --ips 0

High Latency
~~~~~~~~~~~~

**Symptom**: IP classification taking >50ms per IP

**Solutions**:

1. Check Redis connection:

   .. code-block:: bash

      redis-cli -h localhost -p 6379 PING

2. Verify cache hit rate (should be >95%):

   .. code-block:: python

      stats = classifier.get_stats()
      print(f"Cache hit rate: {stats['cache_hit_rate']:.1%}")

3. Warm up cache for frequently seen IPs:

   .. code-block:: python

      # Get top 1000 IPs from last 30 days
      top_ips = session.query(SessionSummary.source_ip).group_by(SessionSummary.source_ip).order_by(func.count().desc()).limit(1000).all()
      classifier.bulk_classify([ip[0] for ip in top_ips])

Incorrect Classifications
~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptom**: Known cloud/datacenter IPs classified as "unknown"

**Solutions**:

1. Check if IP is in data source:

   .. code-block:: python

      ip = "52.0.0.1"
      print(f"TOR: {classifier.tor_matcher.match(ip)}")
      print(f"Cloud: {classifier.cloud_matcher.match(ip)}")
      print(f"DC: {classifier.datacenter_matcher.match(ip)}")

2. Force data source update:

   .. code-block:: python

      classifier.cloud_matcher._download_data(force=True)

3. Report missing ranges to upstream:

   - AWS/Azure/GCP: https://github.com/rezmoss/cloud-provider-ip-addresses
   - Datacenters: https://github.com/jhassine/server-ip-addresses

Advanced Topics
---------------

Custom Matchers
~~~~~~~~~~~~~~~

You can extend the classifier with custom matchers:

.. code-block:: python

   from cowrieprocessor.enrichment.ip_classification.matchers import IPMatcher
   from cowrieprocessor.enrichment.ip_classification.models import IPClassification, IPType

   class VPNMatcher(IPMatcher):
       def __init__(self, cache_dir: Path):
           super().__init__(cache_dir)
           self.vpn_ranges = self._load_vpn_ranges()

       def match(self, ip: str) -> Optional[IPClassification]:
           # Custom VPN matching logic
           if ip in self.vpn_ranges:
               return IPClassification(
                   ip_type=IPType.CLOUD,  # or create new IPType.VPN
                   provider="vpn",
                   confidence=0.85,
                   source="custom_vpn_ranges",
                   classified_at=datetime.now(UTC)
               )
           return None

   # Register custom matcher
   classifier = create_ip_classifier(...)
   classifier.add_matcher(VPNMatcher(...), priority=2)  # After TOR, before Cloud

Direct Cache Access
~~~~~~~~~~~~~~~~~~~~

For advanced use cases, you can access the cache directly:

.. code-block:: python

   from cowrieprocessor.enrichment.ip_classification.cache import IPClassificationCache

   cache = IPClassificationCache(
       cache_dir=Path("/mnt/dshield/data/cache"),
       redis_enabled=True,
       db_cache_enabled=True
   )

   # Check cache without classification
   cached = cache.get("8.8.8.8")
   if cached:
       print(f"Cached: {cached.ip_type} ({cached.confidence:.0%})")

   # Manually store result
   cache.store("1.2.3.4", IPClassification(...))

   # Get cache statistics
   stats = cache.get_stats()
   print(f"L1 hits: {stats['redis_hits']}")
   print(f"L2 hits: {stats['db_hits']}")
   print(f"L3 hits: {stats['disk_hits']}")

Related Documentation
---------------------

- **API Reference**: :doc:`../api/cowrieprocessor.enrichment.ip_classification`
- **Design Specification**: ``docs/design/README_IP_CLASSIFICATION.md`` (50+ pages)
- **Data Source Updates**: ``docs/operations/ip_classification_data_updates.md``
- **ADR-007**: Three-tier enrichment architecture
- **Enrichment Integration**: ``docs/design/ip_classifier_enrichment_integration.md``
