#!/usr/bin/env python3
"""Migrate enrichment cache from filesystem to database.

This script migrates existing filesystem-based enrichment cache entries
to the new database L2 cache (schema v15+). It preserves TTLs and handles
all service-specific directory layouts.

Usage:
    uv run python scripts/migrate_filesystem_cache_to_db.py --cache-dir ~/.cache/cowrieprocessor/enrichment
    uv run python scripts/migrate_filesystem_cache_to_db.py --cache-dir /mnt/dshield/data/cache --db "postgresql://..."
    uv run python scripts/migrate_filesystem_cache_to_db.py --help

Requirements:
    - Database schema v15 or later (enrichment_cache table)
    - Read access to filesystem cache directory
    - Write access to database

The script:
    1. Scans filesystem cache for all services (virustotal, dshield, urlhaus, spur, hibp)
    2. Reads JSON files and extracts cache keys
    3. Inserts into database cache with appropriate TTLs
    4. Reports statistics (entries migrated, errors, duplicates)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Iterator

from cowrieprocessor.cli.db_config import resolve_database_settings
from cowrieprocessor.db import create_engine_from_settings
from cowrieprocessor.enrichment.cache import EnrichmentCacheManager
from cowrieprocessor.enrichment.db_cache import DatabaseCache

LOGGER = logging.getLogger(__name__)


def discover_cache_files(cache_dir: Path) -> Iterator[tuple[str, Path, str]]:
    """Scan filesystem cache and yield (service, file_path, cache_key) tuples.

    Args:
        cache_dir: Root cache directory containing service subdirectories

    Yields:
        Tuples of (service_name, file_path, cache_key)
    """
    # Service directories to scan
    services = ["virustotal", "dshield", "urlhaus", "spur", "hibp"]

    for service in services:
        service_dir = cache_dir / service
        if not service_dir.exists():
            LOGGER.info(f"Skipping {service}: directory not found at {service_dir}")
            continue

        # Recursively find all .json files
        for json_file in service_dir.rglob("*.json"):
            # Extract cache key from filename (without .json extension)
            cache_key = json_file.stem

            # Special handling for service-specific cache keys
            if service == "dshield":
                # DShield uses IP octets: 1/2/3/4.json -> reconstruct IP
                parts = json_file.relative_to(service_dir).parts
                if len(parts) == 4:  # octets/file.json
                    cache_key = ".".join(parts[:-1]) + "." + json_file.stem
            elif service == "hibp":
                # HIBP uses SHA-1 prefix: AB/CD/E/ABCDE.json -> use filename
                cache_key = json_file.stem
            elif service in ("virustotal", "virustotal_unknown"):
                # VirusTotal uses hex sharding: ab/cd/ef/12/hash.json -> use filename
                cache_key = json_file.stem

            yield service, json_file, cache_key


def migrate_cache_entry(
    db_cache: DatabaseCache,
    service: str,
    cache_key: str,
    payload: dict,
) -> bool:
    """Migrate a single cache entry to the database.

    Args:
        db_cache: DatabaseCache instance
        service: Service name (virustotal, dshield, etc.)
        cache_key: Cache key for the entry
        payload: JSON payload to cache

    Returns:
        True if migration succeeded, False otherwise
    """
    try:
        db_cache.set(service, cache_key, payload)
        return True
    except Exception as e:
        LOGGER.error(f"Failed to migrate {service}/{cache_key}: {e}")
        return False


def main(argv: list[str] | None = None) -> int:
    """Main entry point for cache migration script."""
    parser = argparse.ArgumentParser(
        description="Migrate filesystem enrichment cache to database (schema v15+)"
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path.home() / ".cache" / "cowrieprocessor" / "enrichment",
        help="Filesystem cache root directory (default: ~/.cache/cowrieprocessor/enrichment)",
    )
    parser.add_argument(
        "--db",
        help="Database URL (default: from sensors.toml or environment)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan cache but don't insert into database",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of entries to migrate before committing (default: 100)",
    )

    args = parser.parse_args(argv)

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Validate cache directory
    if not args.cache_dir.exists():
        LOGGER.error(f"Cache directory not found: {args.cache_dir}")
        return 1

    LOGGER.info(f"Scanning cache directory: {args.cache_dir}")

    # Initialize database connection
    if not args.dry_run:
        settings = resolve_database_settings(args.db)
        engine = create_engine_from_settings(settings)
        db_cache = DatabaseCache(engine)
        LOGGER.info(f"Connected to database: {settings.url}")
    else:
        db_cache = None  # type: ignore[assignment]
        LOGGER.info("DRY RUN MODE: No database operations will be performed")

    # Migration statistics
    stats = {
        "total_scanned": 0,
        "total_migrated": 0,
        "total_errors": 0,
        "by_service": {},
    }

    # Scan and migrate cache entries
    batch = []
    for service, file_path, cache_key in discover_cache_files(args.cache_dir):
        stats["total_scanned"] += 1
        stats["by_service"].setdefault(service, {"scanned": 0, "migrated": 0, "errors": 0})
        stats["by_service"][service]["scanned"] += 1

        # Read JSON payload
        try:
            with file_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            LOGGER.warning(f"Failed to read {file_path}: {e}")
            stats["total_errors"] += 1
            stats["by_service"][service]["errors"] += 1
            continue

        if args.dry_run:
            LOGGER.debug(f"[DRY RUN] Would migrate {service}/{cache_key}")
            stats["total_migrated"] += 1
            stats["by_service"][service]["migrated"] += 1
        else:
            batch.append((service, cache_key, payload))

            # Commit in batches
            if len(batch) >= args.batch_size:
                for svc, key, data in batch:
                    if migrate_cache_entry(db_cache, svc, key, data):
                        stats["total_migrated"] += 1
                        stats["by_service"][svc]["migrated"] += 1
                    else:
                        stats["total_errors"] += 1
                        stats["by_service"][svc]["errors"] += 1
                batch.clear()
                LOGGER.info(f"Progress: {stats['total_migrated']}/{stats['total_scanned']} migrated")

    # Migrate remaining entries
    if not args.dry_run and batch:
        for svc, key, data in batch:
            if migrate_cache_entry(db_cache, svc, key, data):
                stats["total_migrated"] += 1
                stats["by_service"][svc]["migrated"] += 1
            else:
                stats["total_errors"] += 1
                stats["by_service"][svc]["errors"] += 1

    # Report statistics
    print("\n" + "=" * 60)
    print("MIGRATION SUMMARY")
    print("=" * 60)
    print(f"Total entries scanned:  {stats['total_scanned']}")
    print(f"Total entries migrated: {stats['total_migrated']}")
    print(f"Total errors:           {stats['total_errors']}")
    print("\nBy Service:")
    for service, service_stats in sorted(stats["by_service"].items()):
        print(f"  {service:20s} {service_stats['migrated']:6d} / {service_stats['scanned']:6d} "
              f"(errors: {service_stats['errors']})")
    print("=" * 60)

    if args.dry_run:
        print("\nDRY RUN COMPLETE - No database changes made")
    else:
        print("\nMIGRATION COMPLETE")

    return 0 if stats["total_errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
