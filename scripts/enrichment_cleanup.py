#!/usr/bin/env python3
"""Daily cleanup job for expired enrichment cache entries.

This script removes expired cache entries from the enrichment cache directory
and provides statistics about the cleanup operation. It's designed to be run
as a daily cron job.

Usage:
    python scripts/enrichment_cleanup.py [--cache-dir PATH] [--dry-run] [--verbose]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from cowrieprocessor.enrichment import EnrichmentCacheManager


def setup_logging(verbose: bool = False) -> None:
    """Set up logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def main() -> int:
    """Main entry point for the cleanup script."""
    parser = argparse.ArgumentParser(
        description="Clean up expired enrichment cache entries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Clean up default cache directory
    python scripts/enrichment_cleanup.py
    
    # Clean up specific cache directory with verbose output
    python scripts/enrichment_cleanup.py --cache-dir /var/cache/enrichment --verbose
    
    # Dry run to see what would be cleaned up
    python scripts/enrichment_cleanup.py --dry-run --verbose
        """
    )
    
    parser.add_argument(
        '--cache-dir',
        type=Path,
        default=Path('/mnt/dshield/data/cache'),
        help='Cache directory to clean up (default: /mnt/dshield/data/cache)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be cleaned up without actually deleting files'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)
    
    # Validate cache directory
    if not args.cache_dir.exists():
        logger.error("Cache directory does not exist: %s", args.cache_dir)
        return 1
    
    if not args.cache_dir.is_dir():
        logger.error("Cache path is not a directory: %s", args.cache_dir)
        return 1
    
    logger.info("Starting enrichment cache cleanup")
    logger.info("Cache directory: %s", args.cache_dir)
    logger.info("Dry run mode: %s", args.dry_run)
    
    try:
        # Create cache manager
        cache_manager = EnrichmentCacheManager(base_dir=args.cache_dir)
        
        # Get initial cache statistics
        initial_stats = cache_manager.snapshot()
        logger.info("Initial cache statistics: %s", initial_stats)
        
        if args.dry_run:
            # For dry run, we'll simulate the cleanup by checking what would be deleted
            logger.info("DRY RUN: Analyzing cache directory...")
            
            # Count files that would be cleaned up
            total_files = 0
            expired_files = 0
            
            for service_dir in args.cache_dir.iterdir():
                if not service_dir.is_dir():
                    continue
                
                service_name = service_dir.name
                logger.debug("Checking service directory: %s", service_name)
                
                for shard_dir in service_dir.iterdir():
                    if not shard_dir.is_dir():
                        continue
                    
                    for cache_file in shard_dir.glob("*.json"):
                        total_files += 1
                        
                        # Check if file would be expired
                        if not cache_manager._is_valid(cache_file, service_name):
                            expired_files += 1
                            logger.debug("Would delete expired file: %s", cache_file)
            
            logger.info("DRY RUN RESULTS:")
            logger.info("  Total cache files: %d", total_files)
            logger.info("  Expired files (would be deleted): %d", expired_files)
            logger.info("  Files to keep: %d", total_files - expired_files)
            
            if expired_files > 0:
                logger.info("DRY RUN: %d files would be deleted", expired_files)
            else:
                logger.info("DRY RUN: No expired files found")
            
            return 0
        
        # Perform actual cleanup
        logger.info("Performing cache cleanup...")
        cleanup_stats = cache_manager.cleanup_expired()
        
        # Log cleanup results
        logger.info("Cleanup completed:")
        logger.info("  Files scanned: %d", cleanup_stats.get("scanned", 0))
        logger.info("  Files deleted: %d", cleanup_stats.get("deleted", 0))
        logger.info("  Errors encountered: %d", cleanup_stats.get("errors", 0))
        
        # Get final cache statistics
        final_stats = cache_manager.snapshot()
        logger.info("Final cache statistics: %s", final_stats)
        
        # Calculate cleanup efficiency
        scanned = cleanup_stats.get("scanned", 0)
        deleted = cleanup_stats.get("deleted", 0)
        if scanned > 0:
            cleanup_percentage = (deleted / scanned) * 100
            logger.info("Cleanup efficiency: %.1f%% of scanned files were expired", cleanup_percentage)
        
        # Log any errors
        if cleanup_stats.get("errors", 0) > 0:
            logger.warning("Some files could not be deleted - check permissions")
            return 1
        
        logger.info("Cache cleanup completed successfully")
        return 0
        
    except Exception as e:
        logger.error("Cache cleanup failed: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
