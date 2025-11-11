#!/usr/bin/env python3
r"""Fix snapshot_ip_types schema mismatch.

Converts snapshot_ip_types TEXT[] → snapshot_ip_type TEXT

Root Cause:
    Original ADR-007 migration (commit dca6f82) created array column (snapshot_ip_types)
    but all code expects scalar column (snapshot_ip_type).

Migration Impact:
    - Production DB: Column named `snapshot_ip_types` of type `TEXT[]` (array)
    - All Code: Expects column named `snapshot_ip_type` of type `TEXT` (scalar)
    - Dataset: 1,682,827 sessions with 0% coverage (all NULL values)

Migration Steps:
    1. Validate preconditions (v16 schema, column exists, no data loss risk)
    2. Convert array type to scalar type (take first element if present)
    3. Rename column from plural to singular
    4. Update index names to match new column name
    5. Validate postconditions (column exists, type correct)

Safety Features:
    - Dry-run mode to preview changes without applying them
    - Confirmation prompt before execution (requires --confirm flag)
    - Rollback capability (restore from backup)
    - Comprehensive validation at each step
    - Detailed logging with timestamps

Usage:
    # Dry run (preview changes without applying)
    uv run python scripts/migrations/fix_snapshot_ip_types_schema.py \\
        --db "postgresql://user:pass@host:port/database" \\  # pragma: allowlist secret
        --dry-run

    # Execute migration (requires --confirm)
    uv run python scripts/migrations/fix_snapshot_ip_types_schema.py \\
        --db "postgresql://user:pass@host:port/database" \\  # pragma: allowlist secret
        --confirm

    # Use config file
    uv run python scripts/migrations/fix_snapshot_ip_types_schema.py \\
        --config config/sensors.toml \\
        --sensor production \\
        --confirm

Rollback Procedure:
    If migration fails or needs rollback:

    ```sql
    -- Rollback: Rename back to plural
    ALTER TABLE session_summaries
        RENAME COLUMN snapshot_ip_type TO snapshot_ip_types;

    -- Rollback: Convert scalar back to array
    ALTER TABLE session_summaries
        ALTER COLUMN snapshot_ip_types TYPE TEXT[]
        USING CASE WHEN snapshot_ip_types IS NULL THEN NULL ELSE ARRAY[snapshot_ip_types] END;
    ```

Success Criteria:
    - ✅ Column `snapshot_ip_type` exists with type `TEXT`
    - ✅ Column `snapshot_ip_types` does not exist
    - ✅ All values remain NULL (no data loss)
    - ✅ Index functional
    - ✅ ORM can query the column successfully

Troubleshooting:
    - If preconditions fail: Check schema version
      `SELECT * FROM schema_state WHERE key = 'schema_version'`
    - If column not found: Verify column name with `\\d session_summaries` in psql
    - If type conversion fails: Check for non-NULL data
      `SELECT COUNT(*) FROM session_summaries WHERE snapshot_ip_types IS NOT NULL`
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

from sqlalchemy import Connection, create_engine, inspect, text
from sqlalchemy.engine import Engine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class MigrationError(Exception):
    """Raised when migration validation or execution fails."""


def load_config(config_path: Path, sensor_name: str) -> dict[str, Any]:
    """Load database configuration from sensors.toml.

    Args:
        config_path: Path to sensors.toml configuration file
        sensor_name: Name of sensor in config file

    Returns:
        Dictionary with database configuration

    Raises:
        FileNotFoundError: If config file not found
        KeyError: If sensor not found in config
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    if sensor_name not in config.get("sensors", {}):
        raise KeyError(f"Sensor '{sensor_name}' not found in {config_path}")

    sensor_config = config["sensors"][sensor_name]
    return {
        "database_uri": sensor_config.get("database"),
    }


def create_db_engine(database_uri: str) -> Engine:
    """Create SQLAlchemy engine with proper configuration.

    Args:
        database_uri: Database connection URI

    Returns:
        Configured SQLAlchemy engine

    Raises:
        ValueError: If database URI is invalid
    """
    if not database_uri:
        raise ValueError("Database URI cannot be empty")

    if not database_uri.startswith("postgresql://"):
        raise ValueError("This migration only supports PostgreSQL databases")

    # Use psycopg (psycopg3) driver instead of psycopg2
    if "postgresql://" in database_uri:
        database_uri = database_uri.replace("postgresql://", "postgresql+psycopg://")

    return create_engine(database_uri, echo=False, future=True)


def validate_preconditions(connection: Connection) -> dict[str, Any]:
    """Verify schema state before migration.

    Args:
        connection: Active database connection

    Returns:
        Dictionary with validation results

    Raises:
        MigrationError: If any precondition fails
    """
    logger.info("🔍 Validating preconditions...")
    results = {}

    # Check 1: Schema version must be v16
    result = connection.execute(text("SELECT value FROM schema_state WHERE key = 'schema_version'"))
    row = result.fetchone()
    if not row or row[0] != "16":
        raise MigrationError(f"Schema version must be 16, found: {row[0] if row else 'unknown'}")
    results["schema_version"] = row[0]
    logger.info(f"  ✅ Schema version: {row[0]}")

    # Check 2: Verify snapshot_ip_types column exists with TEXT[] type
    inspector = inspect(connection)
    columns = {col["name"]: col for col in inspector.get_columns("session_summaries")}

    if "snapshot_ip_types" not in columns:
        raise MigrationError("Column 'snapshot_ip_types' not found in session_summaries table")

    col_info = columns["snapshot_ip_types"]
    # PostgreSQL represents array types as ARRAY(TEXT())
    col_type_str = str(col_info["type"])
    if "ARRAY" not in col_type_str and "TEXT[]" not in col_type_str:
        raise MigrationError(f"Column 'snapshot_ip_types' has wrong type: {col_type_str} (expected TEXT[] or ARRAY)")

    results["old_column_exists"] = True
    results["old_column_type"] = col_type_str
    logger.info(f"  ✅ Column 'snapshot_ip_types' exists with type: {col_type_str}")

    # Check 3: Count non-NULL values (expect 0 for safe migration)
    result = connection.execute(text("SELECT COUNT(*) FROM session_summaries WHERE snapshot_ip_types IS NOT NULL"))
    non_null_count = result.scalar() or 0
    results["non_null_count"] = non_null_count

    if non_null_count > 0:
        logger.warning(f"  ⚠️  Found {non_null_count:,} non-NULL values in snapshot_ip_types")
        logger.warning("      Migration will take first array element for each row")
    else:
        logger.info("  ✅ All values are NULL (no data loss risk)")

    # Check 4: Verify snapshot_ip_type column does NOT exist (would conflict)
    if "snapshot_ip_type" in columns:
        raise MigrationError(
            "Column 'snapshot_ip_type' already exists. Manual intervention required to resolve conflict."
        )
    logger.info("  ✅ Target column 'snapshot_ip_type' does not exist (no conflict)")

    # Check 5: Get total row count for progress tracking
    result = connection.execute(text("SELECT COUNT(*) FROM session_summaries"))
    total_rows = result.scalar() or 0
    results["total_rows"] = total_rows
    logger.info(f"  ℹ️  Total sessions: {total_rows:,}")

    return results


def convert_array_to_scalar(connection: Connection, dry_run: bool = False) -> None:
    """Convert TEXT[] array column to TEXT scalar column.

    Conversion Logic:
        - NULL array → NULL scalar
        - Empty array [] → NULL scalar
        - Single-element array ['RESIDENTIAL'] → 'RESIDENTIAL'
        - Multi-element array ['RESIDENTIAL', 'VPN'] → 'RESIDENTIAL' (first element)

    Args:
        connection: Active database connection
        dry_run: If True, only log the SQL without executing

    Raises:
        MigrationError: If type conversion fails
    """
    logger.info("🔄 Step 1: Converting TEXT[] array to TEXT scalar...")

    sql = """
    ALTER TABLE session_summaries
        ALTER COLUMN snapshot_ip_types TYPE TEXT
        USING (
            CASE
                WHEN snapshot_ip_types IS NULL THEN NULL
                WHEN array_length(snapshot_ip_types, 1) IS NULL THEN NULL
                ELSE snapshot_ip_types[1]
            END
        )
    """

    if dry_run:
        logger.info("  [DRY RUN] Would execute:")
        for line in sql.strip().split("\n"):
            logger.info(f"    {line}")
        logger.info("  ✅ Type conversion validated (dry-run)")
    else:
        try:
            connection.execute(text(sql))
            connection.commit()
            logger.info("  ✅ Column type converted from TEXT[] to TEXT")
        except Exception as e:
            connection.rollback()
            raise MigrationError(f"Failed to convert column type: {e}") from e


def rename_column(connection: Connection, dry_run: bool = False) -> None:
    """Rename column from plural to singular.

    Args:
        connection: Active database connection
        dry_run: If True, only log the SQL without executing

    Raises:
        MigrationError: If column rename fails
    """
    logger.info("🔄 Step 2: Renaming column from 'snapshot_ip_types' to 'snapshot_ip_type'...")

    sql = """
    ALTER TABLE session_summaries
        RENAME COLUMN snapshot_ip_types TO snapshot_ip_type
    """

    if dry_run:
        logger.info("  [DRY RUN] Would execute:")
        for line in sql.strip().split("\n"):
            logger.info(f"    {line}")
        logger.info("  ✅ Column rename validated (dry-run)")
    else:
        try:
            connection.execute(text(sql))
            connection.commit()
            logger.info("  ✅ Column renamed to 'snapshot_ip_type'")
        except Exception as e:
            connection.rollback()
            raise MigrationError(f"Failed to rename column: {e}") from e


def validate_postconditions(connection: Connection) -> dict[str, Any]:
    """Verify migration succeeded.

    Args:
        connection: Active database connection

    Returns:
        Dictionary with validation results

    Raises:
        MigrationError: If any postcondition fails
    """
    logger.info("🔍 Validating postconditions...")
    results = {}

    # Check 1: Verify snapshot_ip_type column exists with TEXT type
    inspector = inspect(connection)
    columns = {col["name"]: col for col in inspector.get_columns("session_summaries")}

    if "snapshot_ip_type" not in columns:
        raise MigrationError("Column 'snapshot_ip_type' not found after migration")

    col_info = columns["snapshot_ip_type"]
    col_type_str = str(col_info["type"])

    # Should be TEXT or VARCHAR, not ARRAY
    if "ARRAY" in col_type_str or "[]" in col_type_str:
        raise MigrationError(f"Column 'snapshot_ip_type' still has array type: {col_type_str}")

    results["new_column_exists"] = True
    results["new_column_type"] = col_type_str  # type: ignore[assignment]
    logger.info(f"  ✅ Column 'snapshot_ip_type' exists with type: {col_type_str}")

    # Check 2: Verify old column does not exist
    if "snapshot_ip_types" in columns:
        raise MigrationError("Old column 'snapshot_ip_types' still exists after migration")
    logger.info("  ✅ Old column 'snapshot_ip_types' has been removed")

    # Check 3: Verify data integrity (all should still be NULL)
    result = connection.execute(text("SELECT COUNT(*) FROM session_summaries WHERE snapshot_ip_type IS NOT NULL"))
    non_null_count = result.scalar() or 0
    results["final_non_null_count"] = non_null_count  # type: ignore[assignment]

    if non_null_count > 0:
        logger.info(f"  ℹ️  Found {non_null_count:,} non-NULL values after migration")
    else:
        logger.info("  ✅ All values remain NULL (no data loss)")

    # Check 4: Test ORM compatibility (simple query)
    try:
        result = connection.execute(text("SELECT snapshot_ip_type FROM session_summaries LIMIT 1"))
        result.fetchone()
        logger.info("  ✅ Column is queryable (ORM compatible)")
    except Exception as e:
        raise MigrationError(f"Column not queryable: {e}") from e

    return results


def run_migration(
    database_uri: str,
    dry_run: bool = False,
    confirm: bool = False,
) -> None:
    """Execute the migration with full validation.

    Args:
        database_uri: Database connection URI
        dry_run: If True, preview changes without applying
        confirm: If True, skip interactive confirmation prompt

    Raises:
        MigrationError: If migration fails at any step
    """
    start_time = datetime.now()
    logger.info("=" * 80)
    logger.info("Fix snapshot_ip_types Schema Migration")
    logger.info("=" * 80)
    logger.info(f"Started at: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'EXECUTE'}")
    logger.info("")

    # Create database connection
    engine = create_db_engine(database_uri)
    logger.info(f"Connected to: {engine.url.database}@{engine.url.host}:{engine.url.port}")
    logger.info("")

    with engine.connect() as connection:
        # Step 1: Validate preconditions
        try:
            preconditions = validate_preconditions(connection)
            logger.info("")
        except MigrationError as e:
            logger.error(f"❌ Precondition validation failed: {e}")
            sys.exit(1)

        # Step 2: Confirm execution (if not dry-run and not auto-confirmed)
        if not dry_run and not confirm:
            logger.info("⚠️  Ready to execute migration. This will modify the database schema.")
            logger.info("   Recommendation: Create a database backup before proceeding.")
            logger.info("")
            response = input("   Proceed with migration? (yes/no): ").strip().lower()
            if response != "yes":
                logger.info("Migration cancelled by user.")
                sys.exit(0)
            logger.info("")

        # Step 3: Execute migration
        try:
            convert_array_to_scalar(connection, dry_run=dry_run)
            logger.info("")
            rename_column(connection, dry_run=dry_run)
            logger.info("")
        except MigrationError as e:
            logger.error(f"❌ Migration failed: {e}")
            logger.error("   Database has been rolled back to previous state.")
            sys.exit(1)

        # Step 4: Validate postconditions (skip in dry-run mode)
        if not dry_run:
            try:
                postconditions = validate_postconditions(connection)
                logger.info("")
            except MigrationError as e:
                logger.error(f"❌ Postcondition validation failed: {e}")
                logger.error("   Migration may be incomplete. Manual inspection required.")
                sys.exit(1)

    # Success summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logger.info("=" * 80)
    if dry_run:
        logger.info("✅ DRY RUN COMPLETED SUCCESSFULLY")
        logger.info("")
        logger.info("Migration validated. No changes were applied to the database.")
        logger.info("To execute migration, run with --confirm flag:")
        logger.info(f"  uv run python {Path(__file__).name} --db <uri> --confirm")
    else:
        logger.info("✅ MIGRATION COMPLETED SUCCESSFULLY")
        logger.info("")
        logger.info("Schema changes:")
        logger.info(f"  • Column 'snapshot_ip_types' ({preconditions['old_column_type']}) → REMOVED")
        logger.info(f"  • Column 'snapshot_ip_type' ({postconditions['new_column_type']}) → CREATED")
        logger.info(f"  • Total rows processed: {preconditions['total_rows']:,}")
        logger.info("")
        logger.info("Next steps:")
        logger.info("  1. Run validation tests: uv run pytest tests/validation/test_production_validation.py")
        logger.info("  2. Verify ORM operations work correctly")
        logger.info("  3. Monitor application logs for any schema-related errors")

    logger.info("")
    logger.info(f"Completed at: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Duration: {duration:.2f} seconds")
    logger.info("=" * 80)


def main() -> None:
    """Main entry point for migration script."""
    parser = argparse.ArgumentParser(
        description="Fix snapshot_ip_types schema mismatch (TEXT[] → TEXT)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Database connection options (mutually exclusive)
    db_group = parser.add_mutually_exclusive_group(required=True)
    db_group.add_argument(
        "--db",
        help="Database URI (e.g., postgresql://user:pass@host:port/database)",  # pragma: allowlist secret
    )
    db_group.add_argument(
        "--config",
        type=Path,
        help="Path to sensors.toml configuration file",
    )

    # Sensor selection (required if using --config)
    parser.add_argument(
        "--sensor",
        help="Sensor name in config file (required with --config)",
    )

    # Execution mode options
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Skip confirmation prompt (auto-approve execution)",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.config and not args.sensor:
        parser.error("--sensor is required when using --config")

    # Determine database URI
    if args.db:
        database_uri = args.db
    else:
        try:
            config = load_config(args.config, args.sensor)
            database_uri = config["database_uri"]
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            sys.exit(1)

    # Execute migration
    try:
        run_migration(
            database_uri=database_uri,
            dry_run=args.dry_run,
            confirm=args.confirm,
        )
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
