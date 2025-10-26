Configuration
=============

Environment Variables
---------------------

API Keys and Credentials
^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   # VirusTotal
   export VT_API_KEY="your-virustotal-api-key"

   # DShield
   export DSHIELD_EMAIL="your@email.com"

   # URLHaus (optional)
   export URLHAUS_API_KEY="your-urlhaus-api-key"

   # SPUR.us (optional)
   export SPUR_API_KEY="your-spur-api-key"

Database Configuration
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   # SQLite (default)
   export DATABASE_URL="sqlite:///path/to/cowrie.sqlite"

   # PostgreSQL
   export DATABASE_URL="postgresql://user:pass@host:port/database"

Secret Management
-----------------

Secrets can be sourced from multiple backends using URI notation:

Environment Variables
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   export VT_API_KEY="env:VIRUSTOTAL_KEY"

File-based Secrets
^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   export VT_API_KEY="file:/path/to/vt-key.txt"

1Password CLI
^^^^^^^^^^^^^

.. code-block:: bash

   export VT_API_KEY="op://vault/item/field"

AWS Secrets Manager
^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   export VT_API_KEY="aws-sm://us-east-1/virustotal#api_key"

HashiCorp Vault
^^^^^^^^^^^^^^^

.. code-block:: bash

   export VT_API_KEY="vault://secret/data/virustotal#api_key"

SOPS Encrypted Files
^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   export VT_API_KEY="sops://secrets.yaml#virustotal.api_key"

Cache Configuration
-------------------

Enrichment cache settings:

.. code-block:: bash

   # Cache directory (default: ~/.cache/cowrieprocessor)
   export COWRIE_CACHE_DIR="/mnt/dshield/data/cache"

   # Cache TTLs (days)
   export VT_CACHE_TTL=30
   export DSHIELD_CACHE_TTL=7
   export URLHAUS_CACHE_TTL=3

Rate Limiting
-------------

Configure rate limits for API enrichment:

.. code-block:: bash

   # VirusTotal: 4 requests per minute (free tier)
   export VT_RATE_LIMIT=4

   # DShield: 30 requests per minute
   export DSHIELD_RATE_LIMIT=30

   # URLHaus: 30 requests per minute
   export URLHAUS_RATE_LIMIT=30

Database Schema
---------------

The current schema version is **v14**. Migrations are handled automatically by:

.. code-block:: bash

   uv run cowrie-db migrate --db your-database.sqlite

See :doc:`reference/data-dictionary` for complete schema documentation.

Production Configuration
------------------------

For production deployments with PostgreSQL:

.. code-block:: bash

   # PostgreSQL with connection pooling
   export DATABASE_URL="postgresql://user:pass@host:5432/cowrie?pool_size=20"

   # Shared cache for multi-sensor deployments
   export COWRIE_CACHE_DIR="/mnt/dshield/data/cache"

   # Status files for monitoring
   export STATUS_DIR="/mnt/dshield/data/logs/status"

See :doc:`guides/postgresql-migration` for detailed production setup.
