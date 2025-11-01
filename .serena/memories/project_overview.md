# Cowrie Processor - Project Overview

## Purpose
Cowrie Processor is a Python-based framework for processing and analyzing Cowrie honeypot logs from multiple sensors. It provides:
- Centralized database storage (SQLite/PostgreSQL)
- Threat intelligence enrichment (VirusTotal, DShield, URLHaus, SPUR, HIBP)
- Elasticsearch reporting with ILM integration
- Advanced threat detection capabilities (ML-based anomaly detection, snowshoe spam, botnet detection)

## Target Use Cases
- Multi-sensor honeypot deployment management
- Centralized threat intelligence gathering
- Security research and analysis
- Malware collection and analysis
- Attack pattern detection and reporting

## Tech Stack
- **Language**: Python 3.9+ (target: 3.13)
- **Package Manager**: `uv` (MANDATORY - do not use pip directly)
- **ORM**: SQLAlchemy 2.0
- **Databases**: SQLite (dev/single-sensor), PostgreSQL (production/multi-sensor)
- **Testing**: pytest with coverage reporting (65% minimum)
- **Linting**: ruff (line-length: 120, target: py313)
- **Type Checking**: mypy with strict configuration
- **CI/CD**: GitHub Actions with mandatory quality gates

## Key Features
1. **Multi-Layer Database Design**:
   - Raw event layer (immutable append-only)
   - Session aggregation layer
   - File tracking with SHA256 indexing
   - Password analytics with HIBP integration
   - SSH key intelligence tracking
   - ML-based threat detection

2. **Enrichment Pipeline**:
   - Unified caching layer with TTLs
   - Rate limiting with token buckets
   - VirusTotal, DShield, URLHaus, SPUR integration
   - OpenTelemetry tracing

3. **Reporting & Analytics**:
   - Daily/weekly/monthly Elasticsearch reports
   - Per-sensor HTML/JSON reports
   - Real-time status monitoring

## Project Status
- **Current Branch**: main
- **Active Development**: Multi-container architecture (K3s deployment)
- **Recent Focus**: Sphinx documentation, ADR integration, Docker/K3s deployment guides
- **Archive Status**: Phase 3 refactoring complete (October 2025) - legacy code moved to archive/
