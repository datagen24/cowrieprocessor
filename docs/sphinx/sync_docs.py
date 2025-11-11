#!/usr/bin/env python3
"""Automated documentation sync script for Sphinx.

Syncs markdown documentation from docs/ to docs/sphinx/source/ while
excluding working directories and applying intelligent categorization.

Usage:
    python sync_docs.py [--dry-run] [--verbose]
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path
from typing import NamedTuple


class SyncRule(NamedTuple):
    """Rule for syncing documentation files."""

    source_pattern: str  # Glob pattern in docs/
    dest_dir: str  # Destination directory under docs/sphinx/source/
    transform_name: bool = False  # Whether to transform filename


# Directories to exclude from sync (working docs, temporary, archives)
EXCLUDE_DIRS = {
    "pdca",
    "claudedocs",
    ".serena",
    "archive",
    "brainstorming",
    "issues",
    "json",
    "phase1",
    "db",
    "designs",  # Keep designs separate - they're design docs, not user guides
    "validation",  # Internal validation docs
    "sphinx",  # Don't sync sphinx into itself
}

# Sync rules: pattern -> destination mapping
SYNC_RULES = [
    # ADRs
    SyncRule("ADR/*.md", "adr/"),
    # Guides
    SyncRule("*-guide.md", "guides/"),
    SyncRule("dlq-*.md", "guides/"),
    SyncRule("telemetry-*.md", "guides/"),
    SyncRule("postgresql-*.md", "guides/"),
    SyncRule("SECURITY-*.md", "guides/", transform_name=True),
    # Reference documentation
    SyncRule("data_dictionary.md", "reference/"),
    SyncRule("enrichment-schemas.md", "reference/"),
    # Operations & Runbooks
    SyncRule("runbooks/*.md", "operations/"),
    SyncRule("operations/*.md", "operations/"),
]


def should_exclude_dir(path: Path) -> bool:
    """Check if a directory should be excluded from sync."""
    return any(excluded in path.parts for excluded in EXCLUDE_DIRS)


def transform_filename(filename: str) -> str:
    """Transform filename for Sphinx (lowercase, hyphenated)."""
    # SECURITY-PRECOMMIT-SETUP.md -> security-precommit-setup.md
    return filename.lower()


def find_source_files(docs_root: Path, pattern: str) -> list[Path]:
    """Find all source files matching pattern, excluding working directories."""
    files = []
    for path in docs_root.glob(pattern):
        if path.is_file() and not should_exclude_dir(path):
            files.append(path)
    return files


def sync_file(source: Path, dest: Path, dry_run: bool = False, verbose: bool = False) -> str:
    """Sync a single file. Returns status string."""
    if not dest.parent.exists():
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
        status = f"CREATE DIR {dest.parent.relative_to(dest.parent.parent.parent)}"
        if verbose:
            print(f"  {status}")

    if dest.exists():
        # Check if files are identical
        if filecmp.cmp(source, dest, shallow=False):
            if verbose:
                print(f"  UNCHANGED: {dest.name}")
            return "unchanged"
        else:
            if not dry_run:
                shutil.copy2(source, dest)
            status = f"UPDATED: {source.name} -> {dest.relative_to(dest.parent.parent.parent)}"
            print(f"  {status}")
            return "updated"
    else:
        if not dry_run:
            shutil.copy2(source, dest)
        status = f"ADDED: {source.name} -> {dest.relative_to(dest.parent.parent.parent)}"
        print(f"  {status}")
        return "added"


def sync_docs(docs_root: Path, sphinx_source: Path, dry_run: bool = False, verbose: bool = False) -> dict[str, int]:
    """Sync documentation files according to rules."""
    stats = {"added": 0, "updated": 0, "unchanged": 0, "skipped": 0}

    print(f"Syncing docs from {docs_root} to {sphinx_source}")
    if dry_run:
        print("DRY RUN - no files will be modified\n")

    for rule in SYNC_RULES:
        source_files = find_source_files(docs_root, rule.source_pattern)

        if not source_files:
            if verbose:
                print(f"No files found for pattern: {rule.source_pattern}")
            continue

        print(f"\nPattern: {rule.source_pattern} ({len(source_files)} files)")

        for source_file in source_files:
            dest_name = transform_filename(source_file.name) if rule.transform_name else source_file.name
            dest_file = sphinx_source / rule.dest_dir / dest_name

            result = sync_file(source_file, dest_file, dry_run, verbose)
            stats[result] += 1

    return stats


def verify_sphinx_index(sphinx_source: Path, dry_run: bool = False) -> list[str]:
    """Verify that all synced files are referenced in index files."""
    warnings = []

    # Check ADR index
    adr_index = sphinx_source / "adr" / "index.md"
    if adr_index.exists():
        adr_content = adr_index.read_text()
        adr_files = list((sphinx_source / "adr").glob("*.md"))
        for adr_file in adr_files:
            if adr_file.name == "index.md":
                continue
            # Check if ADR is referenced in toctree
            if adr_file.stem not in adr_content:
                warnings.append(f"ADR {adr_file.name} not in adr/index.md toctree")

    # Check main index
    main_index = sphinx_source / "index.rst"
    if main_index.exists():
        main_content = main_index.read_text()

        # Check guides
        guide_files = list((sphinx_source / "guides").glob("*.md"))
        for guide_file in guide_files:
            if guide_file.stem not in main_content:
                warnings.append(f"Guide {guide_file.name} not in main index.rst")

        # Check operations
        ops_files = list((sphinx_source / "operations").glob("*.md"))
        for ops_file in ops_files:
            if ops_file.stem not in main_content:
                warnings.append(f"Operations doc {ops_file.name} not in main index.rst")

    return warnings


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Sync docs to Sphinx source directory")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without modifying files")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show verbose output including unchanged files")
    parser.add_argument(
        "--verify", action="store_true", help="Verify that all synced files are referenced in index files"
    )
    args = parser.parse_args()

    # Determine paths
    script_dir = Path(__file__).parent
    docs_root = script_dir.parent
    sphinx_source = script_dir / "source"

    if not docs_root.exists():
        print(f"Error: docs directory not found at {docs_root}", file=sys.stderr)
        return 1

    if not sphinx_source.exists():
        print(f"Error: Sphinx source directory not found at {sphinx_source}", file=sys.stderr)
        return 1

    # Sync documentation
    stats = sync_docs(docs_root, sphinx_source, args.dry_run, args.verbose)

    # Print summary
    print("\n" + "=" * 60)
    print("Sync Summary:")
    print(f"  Added:     {stats['added']}")
    print(f"  Updated:   {stats['updated']}")
    print(f"  Unchanged: {stats['unchanged']}")
    print(f"  Skipped:   {stats['skipped']}")
    print("=" * 60)

    # Verify index files if requested
    if args.verify:
        print("\nVerifying index files...")
        warnings = verify_sphinx_index(sphinx_source, args.dry_run)
        if warnings:
            print("\n⚠️  Index Warnings:")
            for warning in warnings:
                print(f"  - {warning}")
            print("\nRun 'uv run python docs/sphinx/sync_docs.py' to see what needs updating")
        else:
            print("✅ All synced files are properly indexed")

    if args.dry_run:
        print("\n✅ Dry run complete - no files were modified")
    else:
        print("\n✅ Sync complete")

    return 0


if __name__ == "__main__":
    sys.exit(main())
