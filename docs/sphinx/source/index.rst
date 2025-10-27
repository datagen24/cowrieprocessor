Cowrie Processor Documentation
===============================

**Cowrie Processor** is a Python-based framework for processing and analyzing Cowrie honeypot logs from multiple sensors.
It provides centralized database storage, threat intelligence enrichment, Elasticsearch reporting, and advanced threat detection capabilities.

.. image:: https://img.shields.io/badge/python-3.9%2B-blue
   :alt: Python 3.9+

.. image:: https://img.shields.io/badge/license-MIT-green
   :alt: License: MIT

Features
--------

* **Multi-sensor honeypot log aggregation** with SQLite and PostgreSQL support
* **Threat intelligence enrichment** via VirusTotal, DShield, URLHaus, SPUR, and HIBP
* **Advanced threat detection** using machine learning and behavioral analysis
* **Dead Letter Queue (DLQ)** processing with circuit breaker pattern
* **Elasticsearch integration** for reporting and visualization
* **SSH key intelligence** for campaign detection and key reuse analysis
* **Password breach detection** using HIBP k-anonymity API

Getting Started
---------------

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   installation
   quickstart
   configuration

User Guides
-----------

.. toctree::
   :maxdepth: 2
   :caption: Guides

   guides/telemetry
   guides/dlq-processing
   guides/dlq-production
   guides/postgresql-migration
   guides/postgresql-stored-procedures

Reference
---------

.. toctree::
   :maxdepth: 2
   :caption: Reference

   reference/data-dictionary
   reference/enrichment-schemas

Architecture Decision Records
-----------------------------

.. toctree::
   :maxdepth: 2
   :caption: Architecture Decisions

   adr/index

API Documentation
-----------------

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   api/modules

Indices and Tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
