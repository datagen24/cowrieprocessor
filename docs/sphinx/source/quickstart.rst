Quick Start Guide
=================

This guide will help you get started with Cowrie Processor in 5 minutes.

1. Initialize Database
----------------------

Create and initialize the database with migrations:

.. code-block:: bash

   uv run cowrie-db migrate --db cowrie.sqlite

This creates a SQLite database with schema v14.

2. Load Cowrie Logs
--------------------

Load your first batch of Cowrie honeypot logs:

.. code-block:: bash

   uv run cowrie-loader bulk /path/to/cowrie/logs/*.json \
       --db cowrie.sqlite \
       --status-dir ./status

For multiline JSON logs (pretty-printed):

.. code-block:: bash

   uv run cowrie-loader bulk /path/to/logs/*.json.bz2 \
       --db cowrie.sqlite \
       --multiline-json

3. Enrich with Threat Intelligence
-----------------------------------

Enrich sessions with VirusTotal and DShield data:

.. code-block:: bash

   export VT_API_KEY="your-virustotal-api-key"
   export DSHIELD_EMAIL="your@email.com"

   uv run cowrie-enrich refresh \
       --db cowrie.sqlite \
       --last-days 7 \
       --progress

4. Check Password Breaches
---------------------------

Use HIBP to check for breached passwords:

.. code-block:: bash

   uv run cowrie-enrich passwords \
       --db cowrie.sqlite \
       --last-days 30 \
       --progress

5. Generate Reports
--------------------

Create a daily report:

.. code-block:: bash

   uv run cowrie-report daily 2025-10-25 \
       --db cowrie.sqlite \
       --output reports/ \
       --sensor my-honeypot

What's Next?
------------

* Learn about :doc:`guides/dlq-processing` for handling malformed logs
* Set up :doc:`guides/postgresql-migration` for production deployments
* Explore :doc:`reference/enrichment-schemas` for available enrichment data
* Review :doc:`api/modules` for programmatic access
