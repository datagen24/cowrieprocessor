# Minimal makefile for Sphinx documentation
#

# You can set these variables from the command line, and also
# from the environment for the first two.
SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = source
BUILDDIR      = build
PYTHON        ?= python3
SYNC_SCRIPT   = sync_docs.py

# Put it first so that "make" without argument is like "make help".
help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
	@echo ""
	@echo "Custom targets:"
	@echo "  sync          Sync documentation from docs/ to source/"
	@echo "  sync-check    Dry-run sync to see what would change"
	@echo "  sync-verify   Verify all synced files are in index"
	@echo "  html-sync     Sync docs then build HTML"

.PHONY: help Makefile sync sync-check sync-verify html-sync

# Sync documentation from docs/ to source/
sync:
	@echo "Syncing documentation..."
	@$(PYTHON) $(SYNC_SCRIPT)

# Dry-run sync to see what would change
sync-check:
	@echo "Checking documentation sync (dry-run)..."
	@$(PYTHON) $(SYNC_SCRIPT) --dry-run --verbose

# Verify all synced files are referenced in index files
sync-verify:
	@echo "Verifying documentation index..."
	@$(PYTHON) $(SYNC_SCRIPT) --verify

# Build HTML with auto-sync
html-sync: sync
	@$(SPHINXBUILD) -M html "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
	@echo ""
	@echo "Build complete. HTML pages are in $(BUILDDIR)/html/"

# Override html target to include sync
html: sync
	@$(SPHINXBUILD) -M html "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

# Catch-all target: route all unknown targets to Sphinx using the new
# "make mode" option.  $(O) is meant as a shortcut for $(SPHINXOPTS).
%: Makefile
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
