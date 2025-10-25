#!/usr/bin/env python3
"""Test the fixed migration against a PostgreSQL database."""

from __future__ import annotations

import logging
import sys

from cowrieprocessor.db import apply_migrations, create_engine_from_settings
from cowrieprocessor.settings import DatabaseSettings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_migration(db_url: str) -> bool:
    """Test the migration with the fixed SQL."""
    try:
        logger.info(f"Testing migration with database: {db_url}")

        # Create database settings object
        db_settings = DatabaseSettings(url=db_url)

        # Create engine
        engine = create_engine_from_settings(db_settings)

        # Apply migrations
        logger.info("Applying migrations...")
        apply_migrations(engine)

        logger.info("✅ Migration completed successfully!")
        return True

    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        return False


def main() -> int:
    """Main test function."""
    if len(sys.argv) != 2:
        print("Usage: python test_migration.py <database_url>")
        print("Example: python test_migration.py postgresql://user:pass@localhost/cowrie")
        return 1

    db_url = sys.argv[1]

    success = test_migration(db_url)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
