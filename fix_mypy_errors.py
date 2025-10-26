#!/usr/bin/env python3
"""Bulk fix common mypy errors."""

import re
import sys
from pathlib import Path


def fix_test_functions(content: str) -> str:
    """Add -> None to pytest test functions missing return type."""
    # Match test function definitions without return type annotation
    pattern = r'(\s+def\s+(test_\w+)\s*\([^)]*\)):'

    def replacement(match: re.Match) -> str:
        func_def = match.group(1)
        # Only add -> None if not already present
        if ' -> ' not in func_def:
            return f"{func_def} -> None:"
        return match.group(0)

    return re.sub(pattern, replacement, content)


def fix_pytest_fixtures(content: str) -> str:
    """Add type annotations to pytest fixtures."""
    # Match fixture definitions without return type
    pattern = r'(@pytest\.fixture[^\n]*\n\s+def\s+\w+\s*\([^)]*\)):'

    def replacement(match: re.Match) -> str:
        func_def = match.group(1)
        if ' -> ' not in func_def:
            # Most fixtures return Any
            return f"{func_def} -> Any:"
        return match.group(0)

    return re.sub(pattern, replacement, content)


def add_any_import(content: str) -> str:
    """Add 'Any' to typing imports if needed."""
    if 'from typing import' in content and 'Any' not in content.split('from typing import')[1].split('\n')[0]:
        # Find the typing import line and add Any
        content = re.sub(
            r'(from typing import )([^#\n]+)',
            lambda m: f"{m.group(1)}Any, {m.group(2)}" if 'Any' not in m.group(2) else m.group(0),
            content,
            count=1
        )
    elif 'from typing import' not in content and 'def test_' in content:
        # Add typing import at the top after future imports
        lines = content.split('\n')
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith('from __future__'):
                insert_idx = i + 1
            elif line and not line.startswith('#') and not line.startswith('"""'):
                break

        if '"""' in content:
            # Find end of docstring
            docstring_end = content.find('"""', content.find('"""') + 3)
            if docstring_end > 0:
                lines = content[:docstring_end + 3].split('\n') + ['', 'from typing import Any', ''] + content[docstring_end + 3:].split('\n')
                content = '\n'.join(lines)

    return content


def fix_file(file_path: Path) -> bool:
    """Fix mypy errors in a single file."""
    try:
        content = file_path.read_text(encoding='utf-8')
        original = content

        # Apply fixes
        content = fix_test_functions(content)
        content = fix_pytest_fixtures(content)

        # Add Any import if we made changes that might need it
        if content != original and 'def test_' in content:
            content = add_any_import(content)

        if content != original:
            file_path.write_text(content, encoding='utf-8')
            print(f"✓ Fixed: {file_path}")
            return True

        return False
    except Exception as e:
        print(f"✗ Error fixing {file_path}: {e}", file=sys.stderr)
        return False


def main() -> None:
    """Main entry point."""
    project_root = Path(__file__).parent

    # Fix test files
    test_dirs = [
        project_root / 'tests' / 'unit',
        project_root / 'tests' / 'integration',
        project_root / 'tests' / 'performance',
    ]

    fixed_count = 0
    for test_dir in test_dirs:
        if not test_dir.exists():
            continue

        for test_file in test_dir.glob('test_*.py'):
            if fix_file(test_file):
                fixed_count += 1

    print(f"\n✅ Fixed {fixed_count} files")


if __name__ == '__main__':
    main()
