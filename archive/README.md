# Archived Legacy Code

This directory contains deprecated code preserved for reference and rollback purposes.

## Migration Context

As part of the modernization effort in October 2025, the cowrieprocessor project underwent a comprehensive refactoring from a monolithic architecture to a modular ORM-based CLI system. These archived tools represent the original implementation that has been superseded by new CLI commands.

---

## Deprecated Tools

### process_cowrie.py

**Deprecated**: 2025-10-25
**Status**: Fully replaced by `cowrie-loader` CLI
**Last Working Version**: Commit `7343d7f` (Phase 2 completion)
**Lines of Code**: ~2000

**Original Purpose**: Monolithic processor for Cowrie honeypot logs with integrated session parsing, enrichment, and reporting.

**Modern Replacement**:
```bash
# OLD (deprecated)
python process_cowrie.py \
    --logpath /path/to/logs \
    --sensor honeypot-a \
    --db /path/to/db.sqlite \
    --email user@example.com \
    --summarizedays 1

# NEW (current)
uv run cowrie-loader delta /path/to/logs/*.json \
    --db sqlite:////path/to/db.sqlite \
    --sensor honeypot-a \
    --dshield-email user@example.com \
    --last-days 1 \
    --status-dir /mnt/dshield/data/logs/status
```

**Key Differences**:
- New system uses SQLAlchemy 2.0 ORM instead of raw SQL
- Explicit `bulk` vs `delta` modes for initial vs incremental loads
- Database URI format required (`sqlite://` or `postgresql://`)
- Status emitter for real-time progress monitoring
- Modular enrichment pipeline with caching and rate limiting

**Dependencies Migrated**:
- `session_enumerator.py` → `cowrieprocessor/loader/session_parser.py`
- `enrichment_handlers.py` → `cowrieprocessor/enrichment/handlers.py`
- `secrets_resolver.py` → `cowrieprocessor/utils/secrets.py`

---

### es_reports.py

**Deprecated**: 2025-09-15
**Status**: Replaced by `cowrie-report` CLI
**Replacement**: `uv run cowrie-report {daily|weekly|monthly} <date> --publish`

**Original Purpose**: Generate and publish Elasticsearch reports for Cowrie data.

**Modern Replacement**:
```bash
# Daily report
uv run cowrie-report daily 2025-10-25 --db "postgresql://..." --publish

# Weekly rollup
uv run cowrie-report weekly 2025-W43 --db "postgresql://..." --publish

# Monthly aggregation
uv run cowrie-report monthly 2025-10 --db "postgresql://..." --publish
```

**Deprecation Reason**: Original script had explicit deprecation warning. New `cowrie-report` provides better integration with ILM policies and consistent CLI interface.

---

### submit_vtfiles.py

**Deprecated**: 2025-10-25
**Status**: Functionality should be integrated into enrichment pipeline
**Proposed Replacement**: `uv run cowrie-enrich files --submit-new` (not yet implemented)

**Original Purpose**: Manual submission of new malware samples to VirusTotal.

**Migration Path**: Should be integrated into `cowrieprocessor/cli/enrich_passwords.py` as a flag rather than standalone script.

---

### cowrie_malware_enrichment.py

**Deprecated**: 2025-10-25
**Status**: Replaced by integrated enrichment pipeline
**Replacement**: `uv run cowrie-enrich refresh --files 0 --sessions 0`

**Original Purpose**: Standalone malware enrichment using legacy approach.

**Modern Replacement**: The new enrichment system (`cowrieprocessor/enrichment/`) provides:
- Unified caching with TTLs (30-day VirusTotal, 7-day DShield, 3-day URLHaus)
- Rate limiting with token bucket algorithm
- Telemetry integration
- Automatic retry logic
- Disk-based cache with sharding

---

### refresh_cache_and_reports.py

**Deprecated**: 2025-10-25
**Status**: Replaced by modular CLI commands
**Replacement**: Combination of `cowrie-enrich refresh` + `cowrie-report`

**Original Purpose**: Combined cache refresh and report generation.

**Modern Replacement**:
```bash
# Refresh enrichments
uv run cowrie-enrich refresh --sessions 0 --files 0 --verbose

# Generate reports
uv run cowrie-report daily 2025-10-25 --all-sensors --publish
```

**Deprecation Reason**: Monolithic approach. New system separates concerns for better composability.

---

### status_dashboard.py

**Deprecated**: 2025-10-25
**Status**: Redundant with `monitor_progress.py`
**Replacement**: `python scripts/production/monitor_progress.py`

**Original Purpose**: Simple status file viewer for bulk loading progress.

**Modern Replacement**: `monitor_progress.py` provides richer features:
- Real-time refresh with configurable intervals
- Session-level progress tracking
- Enrichment queue monitoring
- Better formatting and error handling

---

## Rollback Procedure

If critical issues arise with the new CLI system:

1. **Immediate Rollback** (< 1 hour):
   ```bash
   cd /home/speterson/cowrieprocessor
   git revert <phase3-commit-hash>
   git push

   # Temporarily restore process_cowrie.py to root
   cp archive/process_cowrie.py .

   # Use legacy orchestration
   export USE_LEGACY_PROCESSOR=true
   uv run python orchestrate_sensors.py --config sensors.toml
   ```

2. **Database Compatibility**:
   - Schema migrations are backward compatible within the same major version
   - Legacy `process_cowrie.py` can read the current schema (as of v0.9.0)
   - No database rollback required for code-only issues

3. **Data Preservation**:
   - All enrichment caches remain intact
   - Status files are forward-compatible
   - No data loss expected from rollback

---

## Historical Context

### Phase 1: Break Dependency Cycles (2025-10-25)
- Migrated 3 core utilities (1,459 lines) from root to package structure
- Eliminated circular dependencies between new CLI and legacy code
- Commit: `da40dc7`

### Phase 2: Modernize Production Tools (2025-10-25)
- Updated `orchestrate_sensors.py` to use `cowrie-loader` by default
- Added backward compatibility mode (`USE_LEGACY_PROCESSOR=true`)
- Updated documentation with migration guides
- Commit: `7343d7f`

### Phase 3: Archive Legacy Code (2025-10-25)
- Moved deprecated tools to `/archive/`
- Moved migration scripts to `/scripts/migrations/archive/`
- Moved debug tools to `/scripts/debug/`
- Moved production tools to `/scripts/production/`
- Created this documentation

---

## File Manifest

| File | Size (approx) | Dependencies | Notes |
|------|---------------|--------------|-------|
| process_cowrie.py | 2000+ lines | SQLite/PostgreSQL, external APIs | Main legacy processor |
| es_reports.py | 500+ lines | Elasticsearch client | Has deprecation warning |
| submit_vtfiles.py | 200+ lines | VirusTotal API | Manual file submission |
| cowrie_malware_enrichment.py | 300+ lines | VirusTotal, URLHaus | Legacy enrichment |
| refresh_cache_and_reports.py | 200+ lines | Multiple services | Cache refresh utility |
| status_dashboard.py | 150+ lines | JSON parsing | Simple status viewer |

---

## Support Policy

**Deprecation Timeline**:
- **Phase 1** (Current): Archived but preserved for rollback
- **Phase 2** (1-3 months): Available with warnings, not actively maintained
- **Phase 3** (3-6 months): Removal candidate if no issues reported with new system
- **Phase 4** (6-12 months): Full removal from repository (preserved in git history)

**Support Level**: **Best Effort Only**
- No new features
- No bug fixes unless critical
- Security patches if absolutely necessary
- Documentation maintained for historical reference

---

## Questions or Issues

If you need to use these archived tools:

1. **Check git history** for context: `git log --follow archive/<filename>`
2. **Review Phase 1 & 2 summaries** in `/tmp/phase1_and_phase2_summary.md`
3. **Consult REFACTORING_RECOMMENDATIONS.md** for migration guidance
4. **Test in isolated environment** before production use

For issues with the new CLI system:
- See `CLAUDE.md` for current architecture
- Run `uv run cowrie-loader --help` for usage
- Check `config/sensors.example.toml` for configuration examples

---

**Archive Created**: 2025-10-25
**Archived By**: Phase 3 Refactoring
**Git Commit**: [To be filled after commit]

🤖 Generated with [Claude Code](https://claude.com/claude-code)
