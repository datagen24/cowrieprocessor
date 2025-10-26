"""File organization utility to move mislocated files to correct directories.

This script helps identify and move files that are in the wrong directory
based on their content type.
"""

import argparse
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List

from ..utils.file_type_detector import FileTypeDetector

logger = logging.getLogger(__name__)


def organize_files(source_directory: Path, dry_run: bool = True, move_files: bool = False) -> Dict[str, List[Path]]:
    """Organize files by moving them to appropriate directories based on content type.

    Args:
        source_directory: Directory to scan for mislocated files
        dry_run: If True, only report what would be moved (default: True)
        move_files: If True, actually move files (default: False)

    Returns:
        Dictionary mapping file types to lists of file paths
    """
    results: Dict[str, List[Any]] = {
        'iptables_files': [],
        'cowrie_files': [],
        'webhoneypot_files': [],
        'unknown_files': [],
        'errors': [],
    }

    # Find all files recursively
    for file_path in source_directory.rglob('*'):
        if not file_path.is_file():
            continue

        # Skip already organized files
        if any(part in ['cowrie', 'iptables', 'webhoneypot', 'dshield'] for part in file_path.parts):
            continue

        try:
            should_process, file_type, reason = FileTypeDetector.should_process_as_json(file_path)

            if file_type == 'iptables':
                results['iptables_files'].append(file_path)

                if move_files and not dry_run:
                    target_dir = _get_target_directory(file_path, 'iptables')
                    if target_dir:
                        target_path = target_dir / file_path.name
                        logger.info(f"Moving {file_path} -> {target_path}")
                        target_dir.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(file_path), str(target_path))

            elif file_type == 'cowrie_json':
                results['cowrie_files'].append(file_path)

                if move_files and not dry_run:
                    target_dir = _get_target_directory(file_path, 'cowrie')
                    if target_dir:
                        target_path = target_dir / file_path.name
                        logger.info(f"Moving {file_path} -> {target_path}")
                        target_dir.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(file_path), str(target_path))

            elif file_type == 'webhoneypot_json':
                results['webhoneypot_files'].append(file_path)

                if move_files and not dry_run:
                    target_dir = _get_target_directory(file_path, 'webhoneypot')
                    if target_dir:
                        target_path = target_dir / file_path.name
                        logger.info(f"Moving {file_path} -> {target_path}")
                        target_dir.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(file_path), str(target_path))

            elif file_type not in ['json', 'cowrie_json', 'webhoneypot_json']:
                results['unknown_files'].append((file_path, file_type, reason))

        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            results['errors'].append((file_path, str(e)))

    return results


def _get_target_directory(file_path: Path, target_type: str) -> Path:
    """Get the target directory for a file based on its type."""
    # Navigate up to find the NSM directory
    current = file_path.parent
    while current != current.parent:  # Not at root
        if current.name == 'NSM':
            return current / target_type
        current = current.parent

    # If no NSM directory found, create one relative to the file
    return file_path.parent / 'NSM' / target_type


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Organize files by content type")
    parser.add_argument('source', help="Source directory to scan")
    parser.add_argument(
        '--dry-run', action='store_true', default=True, help="Only report what would be moved (default)"
    )
    parser.add_argument('--move', action='store_true', help="Actually move files (overrides --dry-run)")
    parser.add_argument('--verbose', '-v', action='store_true', help="Verbose output")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO)
    else:
        logging.basicConfig(level=logging.WARNING)

    source_dir = Path(args.source)
    if not source_dir.exists():
        logger.error(f"Source directory does not exist: {source_dir}")
        return 1

    move_files = args.move or not args.dry_run

    print(f"Scanning directory: {source_dir}")
    print(f"Mode: {'DRY RUN' if not move_files else 'MOVING FILES'}")
    print()

    results = organize_files(source_dir, dry_run=not move_files, move_files=move_files)

    # Report results
    if results['iptables_files']:
        print(f"Found {len(results['iptables_files'])} iptables files:")
        for file_path in results['iptables_files']:
            print(f"  {file_path}")
        print()

    if results['cowrie_files']:
        print(f"Found {len(results['cowrie_files'])} cowrie files:")
        for file_path in results['cowrie_files']:
            print(f"  {file_path}")
        print()

    if results['webhoneypot_files']:
        print(f"Found {len(results['webhoneypot_files'])} webhoneypot files:")
        for file_path in results['webhoneypot_files']:
            print(f"  {file_path}")
        print()

    if results['unknown_files']:
        print(f"Found {len(results['unknown_files'])} unknown files:")
        for file_path, file_type, reason in results['unknown_files']:  # type: ignore
            print(f"  {file_path} (type: {file_type}, reason: {reason})")  # type: ignore[has-type]
        print()

    if results['errors']:
        print(f"Encountered {len(results['errors'])} errors:")
        for file_path, error in results['errors']:  # type: ignore
            print(f"  {file_path}: {error}")  # type: ignore[has-type]
        print()

    total_moved = len(results['iptables_files']) + len(results['cowrie_files']) + len(results['webhoneypot_files'])
    print(f"Total files {'would be moved' if not move_files else 'moved'}: {total_moved}")

    return 0


if __name__ == '__main__':
    exit(main())
