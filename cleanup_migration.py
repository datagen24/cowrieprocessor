#!/usr/bin/env python3
"""Clean up partial migration state and retry migration."""

from __future__ import annotations

import logging
import sys
from cowrieprocessor.db import create_engine_from_settings
from cowrieprocessor.db.migrations import _safe_execute_sql, _table_exists
from cowrieprocessor.settings import DatabaseSettings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def cleanup_partial_migration(db_url: str) -> bool:
    """Clean up any partial migration state."""
    try:
        logger.info(f"Cleaning up partial migration state for: {db_url}")
        
        # Create database settings object
        db_settings = DatabaseSettings(url=db_url)
        
        # Create engine
        engine = create_engine_from_settings(db_settings)
        
        with engine.connect() as connection:
            # Start transaction
            trans = connection.begin()
            
            try:
                # Drop tables if they exist (in reverse dependency order)
                tables_to_drop = [
                    'longtail_detections',
                    'longtail_analysis',
                    'command_sequence_vectors',  # pgvector tables
                    'behavioral_vectors',
                ]
                
                for table in tables_to_drop:
                    if _table_exists(connection, table):
                        logger.info(f"Dropping table: {table}")
                        _safe_execute_sql(
                            connection,
                            f"DROP TABLE IF EXISTS {table} CASCADE",
                            f"Drop {table} table"
                        )
                
                # Reset schema version to 8
                logger.info("Resetting schema version to 8")
                _safe_execute_sql(
                    connection,
                    "UPDATE schema_state SET value = '8' WHERE key = 'schema_version'",
                    "Reset schema version to 8"
                )
                
                # Commit transaction
                trans.commit()
                logger.info("✅ Cleanup completed successfully")
                return True
                
            except Exception as e:
                # Rollback on error
                trans.rollback()
                logger.error(f"❌ Cleanup failed: {e}")
                return False
                
    except Exception as e:
        logger.error(f"❌ Cleanup failed: {e}")
        return False


def main() -> int:
    """Main cleanup function."""
    if len(sys.argv) != 2:
        print("Usage: python cleanup_migration.py <database_url>")
        print("Example: python cleanup_migration.py postgresql://user:pass@localhost/cowrie")
        return 1
    
    db_url = sys.argv[1]
    
    success = cleanup_partial_migration(db_url)
    if success:
        print("\n🎉 Cleanup completed! You can now run the migration again:")
        print(f"uv run cowrie-db migrate")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
