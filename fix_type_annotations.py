#!/usr/bin/env python3
"""Automatically fix common MyPy type annotation issues in test files."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def fix_pytest_fixtures(content: str) -> tuple[str, int]:
    """Add type annotations for common pytest fixtures.

    Args:
        content: File content to fix

    Returns:
        Tuple of (fixed_content, num_fixes)
    """
    fixes = 0

    # Common pytest fixture type annotations
    fixtures = {
        'monkeypatch': 'pytest.MonkeyPatch',
        'tmp_path': 'Path',
        'tmpdir': 'Any',  # Legacy tmpdir
        'capfd': 'pytest.CaptureFixture[str]',
        'capsys': 'pytest.CaptureFixture[str]',
        'caplog': 'pytest.LogCaptureFixture',
    }

    for fixture, type_ann in fixtures.items():
        # Pattern: def test_something(fixture) ->
        pattern = rf'(def test_\w+\([^)]*)\b{fixture}\b([^):]*\))(\s*->)'
        replacement = rf'\1{fixture}: {type_ann}\2\3'

        new_content = re.sub(pattern, replacement, content)
        if new_content != content:
            fixes += 1
            content = new_content

    return content, fixes


def add_pytest_import(content: str) -> str:
    """Add pytest import if fixtures are used but import is missing.

    Args:
        content: File content

    Returns:
        Content with pytest import added if needed
    """
    # Check if we use pytest fixtures
    uses_pytest = bool(re.search(r': pytest\.[A-Z]', content))
    has_import = 'import pytest' in content

    if uses_pytest and not has_import:
        # Find where to insert import (after from __future__)
        lines = content.split('\n')
        insert_pos = 0

        for i, line in enumerate(lines):
            if line.startswith('from __future__'):
                insert_pos = i + 1
                break
            elif line.startswith('import ') or line.startswith('from '):
                insert_pos = i
                break

        lines.insert(insert_pos, 'import pytest')
        content = '\n'.join(lines)

    return content


def add_pathlib_import(content: str) -> str:
    """Add pathlib.Path import if Path type is used.

    Args:
        content: File content

    Returns:
        Content with Path import added if needed
    """
    uses_path = bool(re.search(r': Path\b', content))
    has_import = 'from pathlib import Path' in content or 'import pathlib' in content

    if uses_path and not has_import:
        lines = content.split('\n')
        insert_pos = 0

        for i, line in enumerate(lines):
            if line.startswith('from __future__'):
                insert_pos = i + 1
                break
            elif line.startswith('import ') or line.startswith('from '):
                insert_pos = i
                break

        lines.insert(insert_pos, 'from pathlib import Path')
        content = '\n'.join(lines)

    return content


def process_file(file_path: Path) -> tuple[bool, int]:
    """Process a single file to fix type annotations.

    Args:
        file_path: Path to file to fix

    Returns:
        Tuple of (was_modified, num_fixes)
    """
    try:
        content = file_path.read_text()
        original = content

        # Apply fixes
        content, fixture_fixes = fix_pytest_fixtures(content)

        # Add imports if needed
        if fixture_fixes > 0:
            content = add_pytest_import(content)
            content = add_pathlib_import(content)

        # Write back if changed
        if content != original:
            file_path.write_text(content)
            return True, fixture_fixes

        return False, 0

    except Exception as e:
        print(f"Error processing {file_path}: {e}", file=sys.stderr)
        return False, 0


def main() -> int:
    """Main entry point."""
    # Find all test files
    test_files = list(Path('tests').rglob('test_*.py'))

    total_files = 0
    total_fixes = 0

    for file_path in sorted(test_files):
        modified, num_fixes = process_file(file_path)
        if modified:
            total_files += 1
            total_fixes += num_fixes
            print(f"✓ Fixed {file_path} ({num_fixes} fixtures)")

    print(f"\nTotal: {total_files} files modified, {total_fixes} fixtures annotated")
    return 0


if __name__ == '__main__':
    sys.exit(main())
