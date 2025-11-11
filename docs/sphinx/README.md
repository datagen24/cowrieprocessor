# Sphinx Documentation Build System

This directory contains the Sphinx documentation build system for Cowrie Processor.

## Quick Start

### Build Documentation

```bash
# From project root
cd docs/sphinx

# Build HTML documentation (auto-syncs docs)
uv run make html

# Or sync manually then build
uv run make sync
uv run make html
```

### Check Documentation Sync

```bash
# See what would be synced (dry-run)
uv run make sync-check

# Verify all synced files are in index
uv run make sync-verify

# Sync documentation manually
uv run make sync
```

## Automated Documentation Sync

The `sync_docs.py` script automatically syncs markdown documentation from `docs/` to `docs/sphinx/source/` when building documentation.

### What Gets Synced

**ADRs** (`docs/ADR/` → `docs/sphinx/source/adr/`)
- All Architecture Decision Records

**Guides** (`docs/*-guide.md`, `docs/dlq-*.md`, etc. → `docs/sphinx/source/guides/`)
- DLQ processing guides
- PostgreSQL migration guides
- Telemetry operations
- Security pre-commit setup

**Operations** (`docs/runbooks/`, `docs/operations/` → `docs/sphinx/source/operations/`)
- Operational runbooks
- Enrichment operations
- Production execution plans

**Reference** (`docs/data_dictionary.md`, `docs/enrichment-schemas.md` → `docs/sphinx/source/reference/`)
- Data dictionary
- Enrichment schemas

### What Gets Excluded

The following directories are **excluded** from sync (working/temporary docs):

- `pdca/` - PDCA documentation (working docs)
- `claudedocs/` - Claude AI working documentation
- `.serena/` - Serena AI memory storage
- `archive/` - Archived documentation
- `brainstorming/` - Brainstorming notes
- `issues/` - Issue tracking docs
- `json/` - JSON schema files
- `phase1/` - Phase-specific working docs
- `db/` - Database working docs
- `designs/` - Design documents (not user-facing)
- `validation/` - Internal validation docs
- `sphinx/` - Avoid recursive sync

### Sync Rules

The sync script uses pattern-based rules to categorize files:

```python
# ADRs
"ADR/*.md" → "adr/"

# Guides
"*-guide.md" → "guides/"
"dlq-*.md" → "guides/"
"telemetry-*.md" → "guides/"
"postgresql-*.md" → "guides/"
"SECURITY-*.md" → "guides/" (lowercase transform)

# Reference
"data_dictionary.md" → "reference/"
"enrichment-schemas.md" → "reference/"

# Operations
"runbooks/*.md" → "operations/"
"operations/*.md" → "operations/"
```

### Manual Sync

If you need to sync without building:

```bash
# From docs/sphinx/
uv run python sync_docs.py

# Dry-run to see what would change
uv run python sync_docs.py --dry-run --verbose

# Verify index files reference all synced docs
uv run python sync_docs.py --verify
```

## Directory Structure

```
docs/sphinx/
├── Makefile              # Build system with auto-sync
├── sync_docs.py          # Documentation sync script
├── README.md             # This file
├── source/               # Sphinx source files
│   ├── conf.py          # Sphinx configuration
│   ├── index.rst        # Main documentation index
│   ├── adr/             # Architecture Decision Records
│   ├── guides/          # User guides
│   ├── operations/      # Operations runbooks
│   ├── reference/       # Reference documentation
│   └── api/             # Auto-generated API docs
└── build/               # Built documentation (gitignored)
    └── html/            # HTML output
```

## Workflow

### Adding New Documentation

1. **Create documentation in `docs/`** (appropriate subdirectory)
2. **Run sync check**: `uv run make sync-check`
3. **Update index files** if needed:
   - `docs/sphinx/source/adr/index.md` for ADRs
   - `docs/sphinx/source/index.rst` for guides/operations
4. **Build and verify**: `uv run make html`
5. **Check output**: Open `build/html/index.html`

### Updating Existing Documentation

1. **Edit files in `docs/`** (NOT in `docs/sphinx/source/`)
2. **Sync automatically runs** when you `make html`
3. **Or sync manually**: `uv run make sync`

### Working Documentation

Create temporary/working docs in excluded directories:

```
docs/
├── pdca/           # PDCA cycles - excluded
├── claudedocs/     # Claude working docs - excluded
├── brainstorming/  # Notes - excluded
├── designs/        # Design docs - excluded
└── validation/     # Internal validation - excluded
```

These won't be synced to Sphinx automatically.

## Configuration

### conf.py

Key settings for markdown support:

```python
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',
    'sphinx_autodoc_typehints',
    'myst_parser',  # Markdown support
]

html_theme = 'sphinx_rtd_theme'  # Read the Docs theme
```

### Sync Script Customization

To modify sync behavior, edit `sync_docs.py`:

- `EXCLUDE_DIRS`: Add/remove excluded directories
- `SYNC_RULES`: Add/remove sync patterns
- `transform_filename()`: Customize filename transformations

## Troubleshooting

### Files Not Syncing

1. Check if file is in excluded directory: `uv run make sync-check`
2. Verify pattern matches: Look at `SYNC_RULES` in `sync_docs.py`
3. Run with verbose output: `uv run python sync_docs.py --dry-run --verbose`

### Files Not Appearing in Documentation

1. Verify sync worked: `uv run make sync-verify`
2. Check index files reference the new files:
   - `source/adr/index.md` for ADRs
   - `source/index.rst` for guides/operations
3. Rebuild: `uv run make html`

### Build Warnings

- **"File not in toctree"**: Add file to appropriate index
- **"Duplicate declaration"**: File synced but already exists with different name
- **"Unknown directive"**: Check markdown syntax compatibility with MyST

## CI/CD Integration

The sync script can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions
- name: Build documentation
  run: |
    cd docs/sphinx
    uv run make html

- name: Check documentation sync
  run: |
    cd docs/sphinx
    uv run make sync-verify
```

## Contributing

When adding new documentation:

1. ✅ Create in appropriate `docs/` subdirectory
2. ✅ Use markdown (.md) format when possible
3. ✅ Run `make sync-check` to verify sync rules
4. ✅ Update index files to reference new docs
5. ✅ Test locally with `make html`
6. ✅ Commit both `docs/` and `docs/sphinx/source/` changes

## Reference

- [Sphinx Documentation](https://www.sphinx-doc.org/)
- [MyST Parser](https://myst-parser.readthedocs.io/) - Markdown support
- [Read the Docs Theme](https://sphinx-rtd-theme.readthedocs.io/)
