#!/usr/bin/env python3
"""Schema migration script for v3 to v4 - adds files table."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.db.migrations import apply_migrations, CURRENT_SCHEMA_VERSION
from cowrieprocessor.settings import load_database_settings


def main() -> int:
    """Main migration function."""
    parser = argparse.ArgumentParser(
        description="Migrate Cowrie processor database from v3 to v4 schema"
    )
    parser.add_argument(
        "--db",
        type=str,
        help="Database URL (default: from settings)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force migration even if already at v4",
    )
    
    args = parser.parse_args()
    
    # Get database engine
    if args.db:
        from sqlalchemy import create_engine
        engine = create_engine(args.db)
    else:
        db_settings = load_database_settings()
        engine = create_engine_from_settings(db_settings)
    
    print(f"Connecting to database...")
    
    # Check current schema version
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(text("SELECT value FROM schema_state WHERE key = 'schema_version'"))
        current_version = result.scalar_one_or_none()
        
        if current_version:
            current_version = int(current_version)
            print(f"Current schema version: {current_version}")
        else:
            current_version = 0
            print("No schema version found, assuming v0")
    
    if current_version >= CURRENT_SCHEMA_VERSION and not args.force:
        print(f"Database is already at schema version {current_version} (target: {CURRENT_SCHEMA_VERSION})")
        print("Use --force to migrate anyway")
        return 0
    
    if args.dry_run:
        print("DRY RUN: Would migrate database to v4 schema")
        print("Changes that would be made:")
        print("- Create 'files' table with proper indexes")
        print("- Update schema_version to 4")
        return 0
    
    print("Starting migration to v4 schema...")
    
    try:
        # Apply migrations
        new_version = apply_migrations(engine)
        print(f"Migration completed successfully. New schema version: {new_version}")
        
        # Verify files table was created
        with engine.connect() as conn:
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='files'"))
            if result.fetchone():
                print("✓ Files table created successfully")
                
                # Show table structure
                result = conn.execute(text("PRAGMA table_info(files)"))
                columns = result.fetchall()
                print(f"Files table has {len(columns)} columns:")
                for col in columns:
                    print(f"  - {col[1]} ({col[2]})")
            else:
                print("✗ Files table was not created")
                return 1
        
        return 0
        
    except Exception as e:
        print(f"Migration failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
