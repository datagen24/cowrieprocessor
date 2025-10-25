Installation
============

Requirements
------------

* Python 3.9 or higher (3.13 recommended)
* UV package manager
* PostgreSQL 12+ (optional, SQLite included)

Quick Install
-------------

Clone the repository and install dependencies:

.. code-block:: bash

   git clone https://github.com/datagen24/cowrieprocessor.git
   cd cowrieprocessor
   uv sync

This will install all dependencies including development tools.

Verify Installation
-------------------

Check that all commands are available:

.. code-block:: bash

   uv run cowrie-loader --help
   uv run cowrie-db --help
   uv run cowrie-enrich --help
   uv run cowrie-report --help

Running Tests
-------------

Run the test suite to verify everything is working:

.. code-block:: bash

   uv run pytest --cov=. --cov-report=term-missing

Minimum 80% code coverage is required.

Next Steps
----------

After installation, proceed to:

* :doc:`quickstart` - Quick start guide
* :doc:`configuration` - Configuration options
* :doc:`guides/dlq-processing` - DLQ processing setup
