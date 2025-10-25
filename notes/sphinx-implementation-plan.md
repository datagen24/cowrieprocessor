# Sphinx API Documentation Implementation Plan

**Date**: October 25, 2025
**Goal**: Set up Sphinx for automated API documentation from docstrings, hosted on ReadTheDocs
**Estimated Total Effort**: 6-8 hours

---

## Objectives

1. ✅ Initialize Sphinx with proper configuration for Python API docs
2. ✅ Configure autodoc to generate docs from Google-style docstrings
3. ✅ Set up ReadTheDocs hosting configuration
4. ✅ Audit existing markdown docs and migrate appropriate content
5. ✅ Create documentation build automation
6. ✅ Test full documentation build locally
7. ✅ Provide maintenance guide for ongoing doc updates

---

## Project Context

### Current State
- **Docstrings**: Google-style docstrings throughout codebase (mandated by CLAUDE.md)
- **Coverage**: All modules, classes, and functions have docstrings
- **Markdown Docs**: 20+ markdown files in `docs/` (need verification/migration)
- **Sphinx**: Installed (v7.4.7) but not configured

### Target State
- **Sphinx Setup**: Full configuration with autodoc, napoleon, theme
- **API Reference**: Auto-generated from docstrings
- **Guides**: Migrated markdown docs in Sphinx structure
- **Hosting**: ReadTheDocs-ready with `.readthedocs.yaml`
- **CI/CD**: GitHub Actions for doc builds (optional)

---

## Implementation Phases

### Phase 1: Sphinx Initialization (1 hour)

**Tasks**:
1. Create `docs/source/` directory structure
2. Generate initial `conf.py` configuration
3. Install required Sphinx extensions
4. Configure theme (sphinx-rtd-theme)
5. Create index.rst and initial structure

**Files Created**:
- `docs/source/conf.py`
- `docs/source/index.rst`
- `docs/source/api/index.rst`
- `docs/source/guides/index.rst`
- `.readthedocs.yaml`

**Dependencies to Add**:
```toml
[dependency-groups]
docs = [
  "sphinx==7.4.7",
  "sphinx-rtd-theme==2.0.0",
  "sphinx-autodoc-typehints==2.0.0",
  "myst-parser==2.0.0",  # For markdown support
]
```

---

### Phase 2: API Documentation Setup (2 hours)

**Tasks**:
1. Configure autodoc extension
2. Configure napoleon for Google-style docstrings
3. Generate API documentation structure with sphinx-apidoc
4. Create module documentation pages
5. Configure intersphinx for external links (Python, SQLAlchemy, etc.)

**Commands**:
```bash
# Generate API docs from code
uv run sphinx-apidoc -f -o docs/source/api cowrieprocessor

# Build HTML docs
uv run sphinx-build -b html docs/source docs/build/html
```

**API Structure**:
```
docs/source/api/
├── index.rst                    # API overview
├── cowrieprocessor.rst          # Main package
├── cowrieprocessor.cli.rst      # CLI modules
├── cowrieprocessor.db.rst       # Database modules
├── cowrieprocessor.enrichment.rst
├── cowrieprocessor.loader.rst
├── cowrieprocessor.reporting.rst
├── cowrieprocessor.threat_detection.rst
└── modules.rst                   # Auto-generated
```

---

### Phase 3: Markdown Documentation Audit (2 hours)

**Tasks**:
1. Review all 20+ markdown files in `docs/`
2. Categorize by status: current/outdated/obsolete
3. Identify migration candidates
4. Convert relevant markdown to RST or configure myst-parser
5. Create guides section in Sphinx

**Markdown Files to Audit**:

**Database Documentation**:
- `data_dictionary.md` (35KB) - **CRITICAL**: Database schema reference
- `schema-v7-migration.md` - Migration guide
- `postgresql-migration-guide.md` - PostgreSQL setup
- `dlq-processing-solution.md` - DLQ processing

**Development Documentation**:
- `sqlalchemy-2.0-migration.md` - SQLAlchemy upgrade
- `MYPY-REMEDIATION-SUMMARY.md` - Type checking
- `mypy-remediation-progress.md` - Type checking progress

**Feature Documentation**:
- `enrichment-schemas.md` - Enrichment data structures
- `enrichment_test_harness.md` - Testing guide
- `snowshoe-phase0-research.md` - Threat research
- `snowshoe-github-issues.md` - Feature tracking

**Configuration**:
- `postgresql-stored-procedures-dlq.md` - Advanced DB features

**Subdirectories**:
- `docs/ADR/` - Architecture Decision Records
- `docs/db/` - Database-specific docs
- `docs/issues/` - Issue tracking docs
- `docs/json/` - JSON schema examples

**Migration Strategy**:
1. **Keep as markdown** (use myst-parser): Guides, tutorials, ADRs
2. **Convert to RST**: API references, structured documentation
3. **Archive**: Outdated/obsolete documents
4. **Update**: Out-of-date content before migration

---

### Phase 4: ReadTheDocs Configuration (1 hour)

**Tasks**:
1. Create `.readthedocs.yaml` configuration
2. Configure build environment (Python 3.9+)
3. Specify dependencies and build commands
4. Set up versioning strategy
5. Configure theme and customization

**`.readthedocs.yaml`**:
```yaml
version: 2

build:
  os: ubuntu-22.04
  tools:
    python: "3.13"

sphinx:
  configuration: docs/source/conf.py
  fail_on_warning: true

python:
  install:
    - method: pip
      path: .
      extra_requirements:
        - docs
```

**ReadTheDocs Setup**:
1. Connect GitHub repository to ReadTheDocs
2. Configure webhook for automatic builds
3. Set up versioning (stable, latest, v3.0.0, etc.)
4. Configure custom domain (optional)

---

### Phase 5: Build Automation (1 hour)

**Tasks**:
1. Create Makefile for documentation builds
2. Add GitHub Actions workflow for doc builds
3. Configure pre-commit hook for doc builds (optional)
4. Add documentation build to CI/CD pipeline

**Makefile**:
```makefile
.PHONY: docs docs-clean docs-serve

docs:
	uv run sphinx-build -b html docs/source docs/build/html

docs-clean:
	rm -rf docs/build

docs-serve:
	cd docs/build/html && python -m http.server 8000

docs-watch:
	uv run sphinx-autobuild docs/source docs/build/html
```

**GitHub Actions** (`.github/workflows/docs.yml`):
```yaml
name: Documentation

on:
  push:
    branches: [main, Test-Suite-refactor]
  pull_request:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - name: Install uv
        run: pip install uv
      - name: Install dependencies
        run: uv sync --all-extras
      - name: Build documentation
        run: make docs
      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: documentation
          path: docs/build/html
```

---

### Phase 6: Testing and Validation (1 hour)

**Tasks**:
1. Build documentation locally
2. Verify all API modules documented
3. Check for warnings/errors
4. Validate links (internal and external)
5. Test search functionality
6. Review generated HTML for completeness

**Validation Checklist**:
- [ ] All modules appear in API reference
- [ ] Docstrings render correctly
- [ ] Type hints display properly
- [ ] Cross-references work
- [ ] Search functionality works
- [ ] Theme renders correctly
- [ ] No Sphinx warnings
- [ ] All guides accessible

---

## Directory Structure (After Setup)

```
cowrieprocessor/
├── .readthedocs.yaml           # ReadTheDocs configuration
├── docs/
│   ├── source/                 # Sphinx source files
│   │   ├── conf.py            # Sphinx configuration
│   │   ├── index.rst          # Documentation home
│   │   ├── api/               # API reference (auto-generated)
│   │   │   ├── index.rst
│   │   │   ├── cowrieprocessor.rst
│   │   │   ├── cowrieprocessor.cli.rst
│   │   │   └── ...
│   │   ├── guides/            # User guides (migrated markdown)
│   │   │   ├── index.rst
│   │   │   ├── installation.md
│   │   │   ├── quickstart.md
│   │   │   ├── database.md
│   │   │   └── ...
│   │   ├── reference/         # Reference documentation
│   │   │   ├── data-dictionary.md
│   │   │   ├── schema-migrations.md
│   │   │   └── ...
│   │   ├── adr/               # Architecture Decision Records
│   │   │   └── ... (migrated from docs/ADR/)
│   │   └── _static/           # Static files (images, CSS)
│   ├── build/                 # Build output (gitignored)
│   │   └── html/
│   ├── Makefile               # Build commands
│   └── [legacy-md-files]      # Existing markdown (to be migrated)
├── Makefile                   # Root Makefile with docs target
└── ...
```

---

## Sphinx Configuration Details

### Extensions to Enable

```python
extensions = [
    'sphinx.ext.autodoc',           # Auto-generate from docstrings
    'sphinx.ext.napoleon',          # Google/NumPy style docstrings
    'sphinx.ext.viewcode',          # Add links to source code
    'sphinx.ext.intersphinx',       # Link to other projects
    'sphinx.ext.autosummary',       # Generate summary tables
    'sphinx.ext.coverage',          # Documentation coverage
    'sphinx_autodoc_typehints',     # Type hints in docs
    'myst_parser',                  # Markdown support
]
```

### Intersphinx Mapping

```python
intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'sqlalchemy': ('https://docs.sqlalchemy.org/en/20/', None),
    'requests': ('https://requests.readthedocs.io/en/latest/', None),
    'pandas': ('https://pandas.pydata.org/docs/', None),
    'numpy': ('https://numpy.org/doc/stable/', None),
}
```

### Theme Configuration

```python
html_theme = 'sphinx_rtd_theme'
html_theme_options = {
    'canonical_url': 'https://cowrieprocessor.readthedocs.io/',
    'logo_only': False,
    'display_version': True,
    'prev_next_buttons_location': 'bottom',
    'style_external_links': True,
    'collapse_navigation': False,
    'sticky_navigation': True,
    'navigation_depth': 4,
    'includehidden': True,
    'titles_only': False,
}
```

### Autodoc Configuration

```python
autodoc_default_options = {
    'members': True,
    'member-order': 'bysource',
    'special-members': '__init__',
    'undoc-members': True,
    'exclude-members': '__weakref__',
    'show-inheritance': True,
}

autodoc_typehints = 'description'
autodoc_typehints_description_target = 'documented'
```

---

## Markdown Documentation Audit Plan

### Step 1: Categorize Existing Docs

**Category A: Must Migrate** (current, essential):
- `data_dictionary.md` - Database schema reference
- `postgresql-migration-guide.md` - Production setup guide
- `enrichment-schemas.md` - API schemas

**Category B: Should Migrate** (useful, may need updates):
- `dlq-processing-solution.md`
- `enrichment_test_harness.md`
- `schema-v7-migration.md`

**Category C: Archive** (outdated or superseded):
- `mypy-remediation-progress.md` - Historical progress (completed)
- `MYPY-REMEDIATION-SUMMARY.md` - Historical summary
- `PHASE-9-COMPLETION.md` - Historical milestone

**Category D: Preserve as Reference** (historical value):
- `docs/ADR/` - Architecture Decision Records (migrate)
- `snowshoe-phase0-research.md` - Research notes
- `sqlalchemy-2.0-migration.md` - Migration notes

### Step 2: Content Verification

For each Category A/B document:
1. Review for accuracy (compare with code)
2. Check for outdated information
3. Verify all references are valid
4. Update as needed before migration

### Step 3: Migration Strategy

**Using myst-parser** (recommended):
- Keep markdown format
- Add YAML frontmatter for metadata
- Include in Sphinx toctree
- Minimal conversion needed

**Example**:
```markdown
---
title: Database Schema Reference
description: Comprehensive data dictionary for cowrieprocessor database
---

# Database Schema Reference

Content here...
```

**Convert to RST** (if restructuring needed):
- Use `pandoc` for initial conversion
- Manual cleanup and formatting
- Add Sphinx directives

---

## Implementation Order

### Day 1: Core Setup (3-4 hours)
1. ✅ Create implementation plan (this document)
2. ⏳ Initialize Sphinx configuration
3. ⏳ Install dependencies and extensions
4. ⏳ Generate initial API documentation
5. ⏳ Test basic build

### Day 2: Content Migration (3-4 hours)
6. ⏳ Audit markdown documentation
7. ⏳ Migrate Category A documents
8. ⏳ Set up guides structure
9. ⏳ Configure myst-parser for markdown

### Day 3: Finalization (2 hours)
10. ⏳ Set up ReadTheDocs configuration
11. ⏳ Create build automation (Makefile, CI/CD)
12. ⏳ Full build test and validation
13. ⏳ Create maintenance documentation

---

## Success Criteria

### Minimum Viable Documentation (MVP)
- [ ] Sphinx builds without errors
- [ ] All API modules documented
- [ ] ReadTheDocs configuration working
- [ ] At least 3 key guides migrated (installation, quickstart, database)
- [ ] Documentation accessible locally

### Target State
- [ ] All Category A docs migrated and verified
- [ ] Category B docs migrated or archived
- [ ] GitHub Actions builds docs on every PR
- [ ] ReadTheDocs publishes docs automatically
- [ ] Search functionality works
- [ ] All cross-references valid

### Stretch Goals
- [ ] Custom theme/branding
- [ ] Versioned documentation (v2.0.0, v3.0.0, latest)
- [ ] API usage examples in docstrings
- [ ] Tutorial section with code examples
- [ ] Contributors guide in docs

---

## Maintenance Strategy

### Updating API Documentation
**When**: After any code changes to public APIs
**How**: Automatic (sphinx-apidoc regenerates from docstrings)
**Validation**: CI/CD builds fail if docs have errors

### Updating Guides
**When**: Features change, new guides needed
**How**: Edit markdown files in `docs/source/guides/`
**Validation**: Build docs locally before committing

### ReadTheDocs
**When**: Automatically on every push to main/branches
**How**: Webhook triggers ReadTheDocs build
**Monitoring**: Check ReadTheDocs dashboard for build status

---

## Next Steps

**Immediate Actions**:
1. Get approval for implementation plan
2. Begin Phase 1: Sphinx initialization
3. Install required dependencies
4. Generate initial API docs
5. Test basic build

**Deliverables**:
- Sphinx configuration files
- Generated API documentation
- ReadTheDocs configuration
- Build automation (Makefile)
- Migration audit report
- Maintenance guide

---

*Plan created: October 25, 2025*
*Estimated completion: 3 days (6-8 hours total)*
*Status: Ready to implement*
