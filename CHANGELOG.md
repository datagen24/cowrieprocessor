# Changelog

All notable changes to the Cowrie Processor script will be documented in this file.

## [Unreleased]

### Fixed
- **Unicode Sanitization Bug** (November 2, 2025):
  - **Critical fix**: `is_safe_for_postgres_json()` now detects JSON Unicode escape sequences (`\u0000`, `\u0001`, etc.)
  - **Root cause**: PostgreSQL `payload::text` casts return escape sequences as literal strings, not actual bytes
  - **Impact**: Previously skipped 1.43M records that contained problematic Unicode in JSONB fields
  - **Detection added**: Dual-pattern checking for both actual control bytes (`\x00`) and JSON escapes (`\u0000`)
  - **Regex pattern**: `\\u00(?:0[0-8bcef]|1[0-9a-fA-F])|\\u007[fF]` (matches control chars except safe whitespace)
  - **Files changed**:
    - `cowrieprocessor/utils/unicode_sanitizer.py:213-278` (added escape sequence detection)
    - `tests/unit/test_unicode_sanitizer.py:171-215` (added 2 new test methods, 22 total tests passing)
    - `scripts/debug/verify_sanitization_fix.py` (verification script)
    - `claudedocs/sanitization_bug_fix.md` (comprehensive documentation)
  - **Verification**: All tests pass, verification script confirms fix works correctly
  - **Action required**: Re-run `cowrie-db sanitize` to properly clean affected records

### Added - Test Coverage Improvements (Week 4, October 2025)
- **Week 4 Days 16-20 COMPLETE** (October 25): CLI, database management, and small-module testing achieving 55% → 58% total coverage (+3%, +310 statements)
  - **Tests created**: 98 new tests (100% passing rate, zero technical debt)
  - **Quality standards**: All tests with Google-style docstrings, Given-When-Then patterns, full type annotations
  - **Strategic validation**: Small-module focus (100-300 statements) delivers 3-4x better ROI than large modules (Day 19 proof)
  - **Key learning**: Large modules (>800 statements) have dramatically lower project coverage impact (Day 18 lesson)
  - **CI status**: 58% achieved, 65% minimum required for CI gate (Week 5-6 sprint planned)
  - **Documentation**: Comprehensive daily summaries, strategic assessments, Week 5-6 execution plan
- **Day 20 Bridge Work** (October 25):
  - **Test fixes**: 2 rate_limiting test failures resolved (91 → 89 total failures)
  - **Planning**: Comprehensive Week 5-6 Sprint Plan created (`notes/WEEK5-6_SPRINT_PLAN.md`, 1,100+ lines)
  - **Week 5 strategy**: Coverage sprint 58% → 65.5% (+7.5%, Days 21-25, small-module focus)
  - **Week 6 strategy**: Fix 89 broken tests + verification (Days 26-28, category-based fixes)
  - **Documentation**: Week 4 final summary (`notes/DAY20_WEEK4_FINAL.md`, comprehensive retrospective)
  - **Commits**: `fix(tests): update rate_limiting tests for HIBP and correct VT rate` (02f4ee4)
- **Multi-Module Testing** (Day 19, October 25):
  - 43 new tests for `health.py` and `cache.py` (small-module strategic focus)
  - Overall project coverage: 57% → 58% (+1 percentage point, +54 statements)
  - **Module 1: health.py** (18 tests, 437 lines):
    - Module coverage: 60% → 93% (+33%, exceeded 85% target)
    - **Test File Rewritten**: `tests/unit/test_health_cli.py` (58 → 437 lines, 9x growth)
    - **Functions tested**: `_check_database` (all DB types), `_load_status` (aggregate/individual), `main` (all CLI paths)
    - Test categories: HealthReport dataclass (1), database checking (7), status loading (5), CLI entry point (5)
  - **Module 2: cache.py** (25 tests, 667 lines):
    - Module coverage: 54% → 84% (+30%, exceeded 80% target)
    - **Test File Created**: `tests/unit/test_cache.py` (667 lines, complements existing test_cache_security.py)
    - **Functions tested**: Path builders (HIBP, DShield, hex-sharded), TTL management, cleanup_expired, legacy migration
    - Test categories: Path builders (11), TTL handling (3), cleanup (4), legacy migration (3), error handling (4)
  - **Strategic Success**: Small-module focus (99, 177 statements) delivers 3-4x better ROI than large modules
  - Test quality: 100% pass rate (43/43), zero flaky tests, real databases/filesystems
  - Testing efficiency: 1.93 statements per test average, +63% combined module coverage
- **Database Management Testing** (Day 18, October 25):
  - 22 new functional tests for `cowrieprocessor/cli/cowrie_db.py`
  - Module coverage: 24% → ~30-35% (+6-11 percentage points estimated)
  - Overall project coverage: 57% → 57% (0% change, module is 13% of project)
  - **Test File Created**: `tests/unit/test_cowrie_db.py` (508 lines, 22 tests, 100% pass rate)
  - **Test Categories**:
    - Database basics and type detection (4 tests)
    - Table operations and metadata (4 tests)
    - SanitizationMetrics dataclass (2 tests)
    - Schema management and migrations (6 tests)
    - Database maintenance operations (6 tests)
  - Functions tested: `_is_sqlite`, `_is_postgresql`, `_table_exists`, `_get_all_indexes`, `get_schema_version`, `migrate`, `validate_schema`, `optimize`, `create_backup`, `check_integrity`
  - Test quality: Real SQLite databases with full migrations, no mocking of own code
  - Testing efficiency: 9.4 statements per test average
- **Analyze CLI Testing** (Day 17, October 25):
  - 17 new tests for `cowrieprocessor/cli/analyze.py`
  - Module coverage: 27% → 65% (+38 percentage points, exceeded 55-60% target by +5-10%)
  - Overall project coverage: 56% → 57% (+1 percentage point)
  - **Batch 1 - CLI Entry Points** (11 tests):
    - `longtail_analyze()` - success path, no-sessions error, file output
    - `snowshoe_report()` - report generation, file output, empty results
    - `main()` - CLI router with all 4 command branches (botnet, snowshoe, longtail, snowshoe-report)
  - **Batch 2 - Database Storage & Botnet** (6 tests):
    - `_store_detection_result()` - storage success and exception handling
    - `_store_botnet_detection_result()` - botnet detection storage
    - `_run_botnet_analysis()` - analysis success, no-sessions error, file output
  - Test quality: 100% pass rate, zero technical debt introduced
  - File: `tests/unit/test_analyze.py` (738 → 1,722 lines, +984 lines, +133% growth)
  - Testing efficiency: 2.24% average coverage per test (exceptional ROI)
- **Report CLI Testing** (Day 16, October 25):
  - 16 new tests for `cowrieprocessor/cli/report.py`
  - Module coverage: 63% → 76% (+13 percentage points, exceeded 75% target)
  - Overall project coverage: 55% → 56% (+1 percentage point)
  - **Batch 1 - SSH Key Reports** (7 tests):
    - `_generate_ssh_key_campaigns()` - campaign report generation with multi-key scenarios
    - `_generate_ssh_key_detail()` - detailed timeline and related keys reports
    - `_generate_ssh_key_summary()` - file output testing
    - Error handling: missing fingerprint, key not found, invalid report type
  - **Batch 2 - Date Parsing & Helpers** (9 tests):
    - `_normalize_date_input()` - monthly format parsing and all error paths
    - `_date_range_for_mode()` - December edge case and regular month transitions
    - `_builder_for_mode()` - monthly mode and invalid mode error handling
    - `_target_sensors()` - no sensors error path
  - Test quality: 100% pass rate, zero technical debt introduced
  - File: `tests/unit/test_report_cli.py` (682 → 1,201 lines, +518 lines, +76% growth)
- **Documentation**:
  - Detailed summary: `notes/DAY16_REPORT_SUMMARY.md` (comprehensive 350+ line analysis)
  - Week 4 plan: `notes/WEEK4_PLAN.md` (strategic roadmap for Days 16-20)

### Added - Test Coverage Improvements (Week 3, October 2025)
- **Week 3 Days 13-14**: Comprehensive test suite expansion achieving 53% → 55% total coverage (+2%)
- **Database Migrations Testing** (Day 13, October 22):
  - 35 new tests for `cowrieprocessor/db/migrations.py`
  - Coverage: 47% → 58% (+11 percentage points)
  - Tests cover schema v2, v3, v4, v9, v11 migrations
  - Helper function tests: `_table_exists`, `_column_exists`, `_is_generated_column`, `_safe_execute_sql`
  - Migration idempotency verification for all tested migrations
  - SQLite dialect-specific behavior testing
  - Main orchestration function `apply_migrations` fully tested
  - File: `tests/unit/test_migrations.py` (809 lines, all tests passing)
- **SSH Key Analytics Testing** (Day 14, October 23):
  - 17 new tests for `cowrieprocessor/enrichment/ssh_key_analytics.py`
  - Coverage: 32% → 98% (+66 percentage points, exceeded 55% target by 43 points)
  - Campaign detection via graph algorithms (DFS-based connected components)
  - Key timeline and session analysis
  - Key association finding
  - Geographic spread calculation
  - Top keys by usage ranking
  - File: `tests/unit/test_ssh_key_analytics.py` (495 lines, all tests passing)
- **Documentation**:
  - Detailed summary: `notes/DAY13_MIGRATIONS_SUMMARY.md` (333 lines)
  - Detailed summary: `notes/DAY14_SSH_ANALYTICS_SUMMARY.md` (425 lines)

### Fixed - Production Bugs Discovered (Test Coverage Work)
- **SSH Key Analytics** (`ssh_key_analytics.py:409`):
  - Identified bug in `_find_connected_campaigns`: `unique_ips` set initialized but never populated
  - Impact: Reduces campaign detection effectiveness when `min_ips > 0`
  - Workaround: Use `min_ips=0` or lower confidence thresholds
  - Status: Documented in test suite, scheduled for future fix
- **Longtail Analysis Storage** (PR #65, October 21):
  - Fixed longtail analysis vector storage and memory detection
  - Resolved numerous mypy typing errors across codebase
- **SSH Key Timestamp Processing** (PR #64, October 21):
  - Fixed record timestamp processing for first_seen and last_seen dates in key records
  - Improved temporal accuracy of SSH key intelligence

### Testing - Quality Metrics
- **Test Suite Status**:
  - New tests created: 52 (35 migrations + 17 ssh_analytics)
  - Test success rate: 100% (all new tests passing)
  - Testing methodology: Real database fixtures, no mocking of own code
  - Test patterns: Given-When-Then docstrings, full type hints, comprehensive assertions
  - Test isolation: Each test creates isolated temporary database
- **Coverage Progress**:
  - Week 2 End: 53%
  - After Day 13: 54%
  - After Day 14: 55%
  - Week 3 Target: 55-56% (on track)
- **Module-Specific Achievements**:
  - `migrations.py`: 47% → 58% (Priority 1 and 2 migrations fully tested)
  - `ssh_key_analytics.py`: 32% → 98% (all 10 methods tested, only 3 trivial edge cases uncovered)

### Technical - Test Implementation Highlights
- **Database Migration Testing**:
  - Version-specific fixture functions for testing incremental migrations
  - Schema validation using SQLAlchemy inspector
  - Index creation verification
  - Idempotency testing (safe re-run verification)
  - Dialect-specific behavior testing (SQLite vs PostgreSQL)
- **Graph Algorithm Testing**:
  - DFS-based connected component detection (campaign identification)
  - Association graph building from key relationships
  - Multi-factor confidence scoring (key diversity, usage volume, IP spread)
  - Complex test data: SSH key campaigns with associations, sessions, and co-occurrences
- **Testing Best Practices**:
  - Real database fixtures with `tmp_path` (no mocking internal code)
  - Google-style docstrings with Given-When-Then pattern
  - Full type annotations (Python 3.9+ syntax)
  - Clear test names describing exact behavior
  - Comprehensive assertions with multiple checks per test

## [3.0.0] - 2025-10-16 - Major Framework Rebuild

Major release with comprehensive threat detection, SSH key intelligence, password enrichment, and architectural improvements.

### Added
- **SSH Key Intelligence Tracking** (PR #63):
  - Database schema v11 with new tables: `ssh_key_intelligence`, `session_ssh_keys`, `ssh_key_associations`
  - Automatic SSH key extraction from Cowrie events
  - Campaign detection via graph algorithms (connected components)
  - Key association tracking and co-occurrence analysis
  - Geographic spread calculation
  - CLI tools: `cowrie-ssh-keys analyze`, `cowrie-ssh-keys backfill`
  - Integration tests for SSH key intelligence pipeline
  - File: `cowrieprocessor/enrichment/ssh_key_analytics.py` and related modules

- **HIBP Password Enrichment** (PR #62):
  - HIBP (Have I Been Pwned) password breach enrichment with k-anonymity
  - Database schema v10 with new tables: `password_statistics`, `password_tracking`, `password_session_usage`
  - New CLI entry point `cowrie-enrich` with subcommands:
    - `passwords` to enrich sessions with password breach data
    - `prune` to remove old passwords (default retention 180 days)
    - `top-passwords` and `new-passwords` reporting utilities
    - `refresh` to refresh enrichments with sensors.toml-aware credential resolution
  - Comprehensive documentation in `HIBP_PASSWORD_ENRICHMENT_IMPLEMENTATION.md`
  - Unit and integration tests for HIBP client and password extractor

- **Longtail Threat Analysis** (PRs #47, #48):
  - Complete implementation with database schema v9
  - Tables: `longtail_analysis`, `longtail_detections`
  - PostgreSQL pgvector support for behavioral analysis (optional)
  - Command sequence anomaly detection
  - Behavioral pattern analysis
  - Integration with `process_cowrie.py`
  - Unicode handling improvements and enrichment enhancements
  - CLI: `cowrie-analyze longtail`

- **Snowshoe Detection** (PR #46):
  - IP rotation pattern detection
  - Attack distribution analysis across networks
  - Integration with threat detection framework

- **Database Management CLI** (PR #24):
  - New `cowrie-db` command for database operations
  - Subcommands: `migrate`, `info`, `health`, `backup`, `restore`
  - Schema version management and validation
  - Migration idempotency and rollback support

- **Telemetry and Validation** (PR #22):
  - Telemetry helpers for monitoring processor health
  - Phase 6 validation tooling for data quality
  - Status reporting infrastructure

- **PostgreSQL Support** (PR #44):
  - Full PostgreSQL database backend support
  - Schema migrations compatible with both SQLite and PostgreSQL
  - Connection pooling and performance optimizations
  - Dialect-specific SQL handling

- **Files Table Schema** (PR #43):
  - Schema v4 with enhanced file tracking
  - Improved file metadata storage
  - Better hash collision handling

- **Bulk Load Support** (PR #23):
  - Handle pretty-printed Cowrie JSON in loaders
  - Multi-line JSON parsing support
  - Configurable `--bulk-load` mode with deferred commits
  - Buffer size configuration via `--buffer-bytes`

- **Stream Reporting** (PR #18):
  - Real-time session metrics reporting
  - Streaming data to Elasticsearch
  - Performance-optimized aggregation

- **Status Tracking** (PRs #7, #8, #9, #10, #15):
  - Live status reporting with JSON status files
  - Phase transition tracking
  - Progress monitoring for long-running operations
  - Timeout handling for report generation
  - Fix for processing hang issues

- **Elasticsearch Integration** (PR #1):
  - ILM write aliases (daily/weekly/monthly `*-write`)
  - Per-sensor and aggregate reporting
  - Automatic index lifecycle management

- **Multi-Sensor Support** (PR #1):
  - Central SQLite database with per-sensor tagging via `--sensor`
  - Per-sensor configuration via `sensors.toml`
  - Orchestration script `orchestrate_sensors.py`

- **Secrets Management** (PR #2):
  - Multi-platform secrets handling
  - Secure credential storage for API keys
  - Integration with enrichment services

### Changed
- **Schema Migrations**:
  - Current schema version: v14 (from v1)
  - Migration v12: Convert event_timestamp to proper datetime type
  - Migration v11: SSH key intelligence tables and indexes
  - Migration v10: HIBP password enrichment tables
  - Migration v9: Longtail analysis tables (with optional pgvector)
  - Earlier migrations: Files table (v4), enrichment caching, indexes

- **Enrichment Framework**:
  - Enrichment cache with TTLs for hashes/IPs to reduce API load
  - Rate limiting with backoff for all external APIs
  - Skip enrichment mode for bulk loading (`--skip-enrich`)
  - Refresh utility `refresh_cache_and_reports.py`

- **CLI Improvements**:
  - Better argument handling and validation
  - Consistent error messages across commands
  - Optional sensor argument in CLI tools

- **Code Quality** (PR #42):
  - Resolved all mypy type errors across codebase
  - Fixed linting issues with ruff
  - Improved type safety and maintainability
  - Applied consistent formatting

- **Documentation**:
  - Updated README with new features and CLI usage
  - Comprehensive data dictionary in `docs/data_dictionary.md`
  - Work plans and implementation docs for major features

### Fixed
- **Type Safety** (PR #42):
  - Resolved mypy type errors throughout codebase
  - Fixed import order and formatting issues
  - Eliminated bare except clauses

- **Enrichment Cache** (PR #45):
  - Fixed cache initialization errors
  - Improved cache hit rates
  - Better error handling for missing cache

- **File Handling**:
  - Fixed bzip2 and gzip log processing
  - Skip malformed JSON lines without crashing
  - Better Unicode handling in file operations

- **Session Duration** (PR #6):
  - Fixed TypeError in `get_session_duration` due to non-dict objects in data list
  - Improved data validation and error handling

- **Status Display** (PR #8):
  - Fixed misleading file count in status when using `--days` parameter
  - Accurate progress reporting

- **Report Generation** (PRs #9, #10, #15):
  - Added progress tracking and timeout handling
  - Fixed report processing hang issues
  - Improved reliability of long-running reports

- **PostgreSQL Compatibility** (PR #48):
  - Fixed type casting errors in PostgreSQL queries
  - Improved dialect-specific SQL generation

### Security
- **API Key Protection**:
  - HIBP uses k-anonymity (only 5-char SHA-1 prefix sent)
  - Secure secrets management across platforms
  - No plaintext API keys in logs or status files

### Performance
- **Bulk Loading**:
  - Deferred commit mode for large imports
  - Configurable buffer sizes
  - Reduced memory footprint for large files

- **Database Optimizations**:
  - Automatic indexes on frequently queried columns
  - Connection pooling for PostgreSQL
  - WAL mode for SQLite with busy timeout tuning

- **Enrichment Efficiency**:
  - Indicator caching reduces API calls by 70-90%
  - Rate limiting prevents API throttling
  - Parallel processing for independent enrichments

### Migration Notes
- **Breaking Changes**:
  - Minimum schema version is now v14
  - PostgreSQL users must have pgvector extension for longtail analysis (optional feature)
  - Old cache formats not compatible (will be rebuilt)

- **Upgrade Path**:
  1. Backup database: `cowrie-db backup`
  2. Run migrations: `cowrie-db migrate`
  3. Verify schema: `cowrie-db info`
  4. Rebuild caches if needed: `cowrie-enrich refresh`

- **Production Deployment**:
  - Test migrations on copy of production database first
  - Use `--bulk-load` for initial large imports
  - Configure rate limits for API services
  - Monitor disk space for cache and temp directories

### Contributors
- @datagen24 - All features and improvements in this release

**Full Changelog**: https://github.com/datagen24/cowrieprocessor/compare/v2.0.0...v3.0.0

## [2.0.0] - 2024-09-14 - Upstream Backports, Docs, and Tooling

### Added
- Google-style docstrings across all modules (`process_cowrie.py`, `cowrie_malware_enrichment.py`, `submit_vtfiles.py`).
- `pyproject.toml` with explicit `py-modules`, runtime dependencies, and build metadata for uv-managed environments.
- Ruff and MyPy configuration under `pyproject.toml` with dev dependencies (`ruff`, `mypy`, `types-requests`).
- New CLI argument `--urlhausapi` for authenticated URLhaus lookups. When omitted, URLhaus lookups are skipped.

### Changed
- Import order and formatting standardized; long lines and bare `except` replaced to satisfy Ruff.
- Minor refactors to avoid variable shadowing and improve type clarity (Path vs str) for MyPy.
- License field in `pyproject.toml` updated to SPDX string (`BSD-4-Clause`).
- README updated to document `--urlhausapi` usage and examples.

### Fixed
- Backported upstream fixes around URLhaus handling:
  - Add Auth-Key header support for URLhaus API.
  - Guard URLhaus calls and output when no API key is provided.
  - Improve robustness around JSON parsing in external API responses.
- Resolved MyPy issues in file iteration and command count aggregation.

### Tooling
- Target Python 3.13 for tooling (Ruff `py313`, MyPy `python_version = "3.13"`), while keeping runtime requirement at Python 3.8+.
- All files pass `ruff check .` and `mypy .` in CI-like runs with uv.

## [2024-06-15] - Major Updates

### Added
- New command line argument `--localpath` for specifying local report output directory (default: `/mnt/dshield/reports`)
- New command line argument `--datapath` for specifying database and working files directory (default: `/mnt/dshield/data`)
- Structured directory layout:
  - `/mnt/dshield/data/db/` - For SQLite database storage
  - `/mnt/dshield/data/temp/` - For temporary processing files
  - `/mnt/dshield/reports/` - For final report storage
- Automatic directory creation for all required paths
- Proper file path handling using `os.path.join()`
- Comprehensive error handling with logging for file operations
- Automatic cleanup of temporary files after processing
- Added virtual environment support for dependency management
- Added .gitignore file for repository management
- Added CHANGELOG.md for tracking changes

### Changed
- Removed deprecated `distutils` import
- Updated file handling to use absolute paths
- Improved file organization with dedicated directories
- Enhanced error handling and logging throughout the script
- Modified report generation to ensure files are created in correct locations
- Updated database storage location to dedicated directory
- Moved to virtual environment for dependency management
- Prepared repository for GitHub hosting

### Fixed
- Fixed bzip2 file handling for compressed log files
- Fixed file path construction for reports and database
- Fixed abnormal report generation and copying
- Fixed temporary directory cleanup
- Fixed file permission issues with proper directory creation

### Dependencies
- Updated requirements.txt with necessary packages:
  - requests>=2.31.0
  - dropbox>=11.36.2
  - ipaddress>=1.0.23
  - pathlib>=1.0.1
  - python-dateutil>=2.8.2

## [Previous Versions]

### Original Features
- Cowrie log processing
- VirusTotal integration
- DShield IP lookup
- URLhaus integration
- SPUR.us data enrichment
- Dropbox upload capability
- SQLite database storage
- Session analysis
- Command tracking
- File download/upload tracking
- Abnormal attack detection
- Report generation
