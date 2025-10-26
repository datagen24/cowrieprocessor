#!/usr/bin/env python3
"""Production deployment script for longtail analysis.

This script handles the complete deployment process for the longtail analysis
feature, including database migration, testing, and validation.

Usage:
    uv run python scripts/deploy_longtail_analysis.py --db-url postgresql://user:pass@localhost/cowrie
    uv run python scripts/deploy_longtail_analysis.py --db-url sqlite:///cowrie.db --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, Dict

from cowrieprocessor.db import apply_migrations
from cowrieprocessor.db.engine import create_engine_from_settings, detect_database_features
from cowrieprocessor.db.settings import DatabaseSettings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_prerequisites() -> bool:
    """Check that all prerequisites are met for deployment."""
    logger.info("Checking deployment prerequisites...")

    try:
        # Check that longtail analysis components are available
        # Import test - if this fails, components are not available
        try:
            import cowrieprocessor.threat_detection.longtail  # noqa: F401
        except ImportError as e:
            logger.error(f"❌ Longtail analysis components not available: {e}")
            return False

        logger.info("✅ Longtail analysis components available")

        # Check database migration functions
        from cowrieprocessor.db.migrations import CURRENT_SCHEMA_VERSION

        if CURRENT_SCHEMA_VERSION != 9:
            logger.error(f"❌ Expected schema version 9, got {CURRENT_SCHEMA_VERSION}")
            return False

        logger.info("✅ Database migration functions available")

        return True

    except ImportError as e:
        logger.error(f"❌ Missing required components: {e}")
        return False


def validate_database_features(db_url: str) -> dict[str, Any]:
    """Validate database features for longtail analysis."""
    logger.info(f"Validating database features for: {db_url}")

    try:
        engine = create_engine_from_settings(DatabaseSettings(url=db_url))
        features = detect_database_features(engine)

        logger.info(f"Database type: {features['database_type']}")
        logger.info(f"Database version: {features['version']}")
        logger.info(f"pgvector available: {features['pgvector']}")
        logger.info(f"Vector longtail support: {features['vector_longtail']}")

        # Validate requirements
        if features['database_type'] == 'sqlite':
            logger.warning("⚠️  Using SQLite - vector analysis will be disabled")
        elif features['pgvector']:
            logger.info("✅ PostgreSQL with pgvector - full vector analysis available")
        else:
            logger.warning("⚠️  PostgreSQL without pgvector - traditional analysis only")

        return {
            "success": True,
            "features": features,
        }

    except Exception as e:
        logger.error(f"❌ Database feature validation failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }


def run_database_migration(db_url: str, dry_run: bool = False) -> dict[str, Any]:
    """Run database migration for longtail analysis."""
    logger.info(f"Running database migration (dry_run={dry_run})...")

    try:
        engine = create_engine_from_settings(DatabaseSettings(url=db_url))

        if dry_run:
            logger.info("🔍 DRY RUN: Would apply v9 migration")
            return {
                "success": True,
                "dry_run": True,
                "migration": "v9_longtail_analysis",
            }

        # Apply migrations
        apply_migrations(engine)

        logger.info("✅ Database migration completed successfully")
        return {
            "success": True,
            "migration_applied": "v9_longtail_analysis",
        }

    except Exception as e:
        logger.error(f"❌ Database migration failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }


def run_deployment_validation(db_url: str) -> dict[str, Any]:
    """Run comprehensive deployment validation."""
    logger.info("Running deployment validation...")

    results: Dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "deployment_target": db_url,
        "validation_results": {},
    }

    # 1. Prerequisites check
    results["validation_results"]["prerequisites"] = {
        "success": check_prerequisites(),
    }

    if not results["validation_results"]["prerequisites"]["success"]:
        logger.error("❌ Prerequisites check failed")
        return results

    # 2. Database features validation
    results["validation_results"]["database_features"] = validate_database_features(db_url)

    # 3. Migration test (dry run)
    results["validation_results"]["migration_dry_run"] = run_database_migration(db_url, dry_run=True)

    # Summary
    successful_validations = sum(1 for test in results["validation_results"].values() if test.get("success", False))
    total_validations = len(results["validation_results"])

    results["deployment_readiness"] = {
        "ready": successful_validations == total_validations,
        "successful_checks": successful_validations,
        "total_checks": total_validations,
        "success_rate": successful_validations / total_validations if total_validations > 0 else 0,
    }

    logger.info("=" * 60)
    logger.info("DEPLOYMENT VALIDATION COMPLETE")
    logger.info(f"Checks passed: {successful_validations}/{total_validations}")
    logger.info(f"Deployment readiness: {'✅ READY' if results['deployment_readiness']['ready'] else '❌ NOT READY'}")

    return results


def main() -> int:
    """Main deployment function."""
    parser = argparse.ArgumentParser(description="Deploy longtail analysis to production database")
    parser.add_argument("--db-url", required=True, help="Database URL for deployment")
    parser.add_argument("--dry-run", action="store_true", help="Run validation without applying changes")
    parser.add_argument("--output", help="Output file for deployment report (default: stdout)")

    args = parser.parse_args()

    logger.info("🚀 Starting longtail analysis deployment...")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("🔍 Running in DRY RUN mode - no changes will be applied")

    # Run deployment validation
    results = run_deployment_validation(args.db_url)

    # If dry run or validation failed, don't apply migration
    if args.dry_run or not results["deployment_readiness"]["ready"]:
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            logger.info(f"Dry run results written to {args.output}")
        else:
            print(json.dumps(results, indent=2, default=str))

        if not results["deployment_readiness"]["ready"]:
            logger.error("❌ Deployment validation failed - not proceeding with migration")
            return 1

        logger.info("✅ Deployment validation passed - ready for production")
        return 0

    # Apply migration if validation passed
    logger.info("Applying database migration...")
    migration_result = run_database_migration(args.db_url, dry_run=False)

    if migration_result["success"]:
        logger.info("✅ Database migration applied successfully")
        results["migration_applied"] = migration_result

        if args.output:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            logger.info(f"Deployment report written to {args.output}")
        else:
            print(json.dumps(results, indent=2, default=str))

        return 0
    else:
        logger.error(f"❌ Database migration failed: {migration_result['error']}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
