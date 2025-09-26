"""Database management CLI for the Cowrie Processor."""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from ..db import CURRENT_SCHEMA_VERSION, apply_migrations
from ..settings import DatabaseSettings
from ..status_emitter import StatusEmitter

logger = logging.getLogger(__name__)


class CowrieDatabase:
    """Database management operations for Cowrie Processor."""

    def __init__(self, db_path: str):
        """Initialize database manager.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._engine = None
        self._session_maker = None

    def _get_engine(self):
        """Get or create SQLAlchemy engine."""
        if self._engine is None:
            settings = DatabaseSettings(url=f"sqlite:///{self.db_path}")
            self._engine = create_engine(settings.url, echo=False, future=True)
        return self._engine

    def _get_session(self):
        """Get or create session maker."""
        if self._session_maker is None:
            self._session_maker = sessionmaker(bind=self._get_engine(), future=True)
        return self._session_maker()

    def get_schema_version(self) -> int:
        """Get current schema version from database."""
        try:
            with self._get_engine().connect() as conn:
                result = conn.execute(
                    text("SELECT value FROM schema_state WHERE key = 'schema_version'")
                ).scalar_one_or_none()
                return int(result) if result else 0
        except Exception as e:
            logger.warning(f"Could not get schema version: {e}")
            return 0

    def migrate(self, target_version: Optional[int] = None, dry_run: bool = False) -> Dict[str, Any]:
        """Run database schema migrations.

        Args:
            target_version: Target schema version (None for latest)
            dry_run: Show what would be done without executing

        Returns:
            Migration result with details
        """
        current_version = self.get_schema_version()
        target = target_version or CURRENT_SCHEMA_VERSION

        result = {
            'current_version': current_version,
            'target_version': target,
            'migrations_applied': [],
            'dry_run': dry_run,
        }

        if current_version >= target:
            result['message'] = f"Database already at version {current_version}"
            return result

        if dry_run:
            result['migrations_applied'] = [f"Migration to version {v}" for v in range(current_version + 1, target + 1)]
            result['message'] = f"Would migrate from v{current_version} to v{target}"
            return result

        try:
            with self._get_engine().begin() as conn:
                # Create advisory lock to prevent concurrent migrations
                conn.execute(text("BEGIN IMMEDIATE"))
                try:
                    # Check for existing migration lock
                    existing_lock = conn.execute(
                        text("SELECT value FROM schema_state WHERE key = 'migration_lock'")
                    ).scalar_one_or_none()

                    if existing_lock:
                        lock_time = float(existing_lock)
                        if time.time() - lock_time < 300:  # 5 minute timeout
                            raise Exception("Migration already in progress by another process")

                    # Set migration lock
                    conn.execute(
                        text("INSERT OR REPLACE INTO schema_state (key, value) VALUES ('migration_lock', :lock_time)"),
                        {'lock_time': str(time.time())},
                    )

                    # Apply migrations
                    final_version = apply_migrations(self._get_engine())
                    result['final_version'] = final_version
                    result['migrations_applied'] = [
                        f"Applied migration to version {v}" for v in range(current_version + 1, final_version + 1)
                    ]
                    result['message'] = f"Successfully migrated to version {final_version}"

                    # Remove migration lock
                    conn.execute(text("DELETE FROM schema_state WHERE key = 'migration_lock'"))

                except Exception as e:
                    conn.execute(text("ROLLBACK"))
                    raise e

        except Exception as e:
            result['error'] = str(e)
            result['message'] = f"Migration failed: {e}"
            raise Exception(f"Migration failed: {e}") from e

        return result

    def validate_schema(self) -> Dict[str, Any]:
        """Validate database schema and health.

        Returns:
            Validation result with health information
        """
        result: Dict[str, Any] = {
            'is_valid': False,
            'schema_version': self.get_schema_version(),
            'expected_version': CURRENT_SCHEMA_VERSION,
            'needs_optimization': False,
            'database_size_mb': 0.0,
            'session_count': 0,
            'command_count': 0,
            'file_count': 0,
        }

        try:
            db_size = os.path.getsize(self.db_path)
            result['database_size_mb'] = round(db_size / (1024 * 1024), 2)
        except OSError:
            result['database_size_mb'] = 0

        try:
            with self._get_session() as session:
                # Check session count
                from ..db.models import SessionSummary

                result['session_count'] = session.query(SessionSummary).count()

                # Check command count
                from ..db.models import CommandStat

                result['command_count'] = session.query(CommandStat).count()

                # Check file count (downloads)
                result['file_count'] = session.query(SessionSummary).filter(SessionSummary.file_downloads > 0).count()

        except Exception as e:
            logger.warning(f"Could not get table counts: {e}")
            result['session_count'] = 0
            result['command_count'] = 0
            result['file_count'] = 0

        # Check schema version
        result['is_valid'] = result['schema_version'] == result['expected_version']

        # Check if optimization might be beneficial
        result['needs_optimization'] = result['database_size_mb'] > 100  # > 100MB

        return result

    def optimize(self, vacuum: bool = True, reindex: bool = True) -> Dict[str, Any]:
        """Run database maintenance operations.

        Args:
            vacuum: Whether to run VACUUM
            reindex: Whether to rebuild indexes

        Returns:
            Optimization result with details
        """
        results = []
        initial_size = 0

        try:
            initial_size = os.path.getsize(self.db_path)
        except OSError:
            pass

        with self._get_engine().connect() as conn:
            if vacuum:
                try:
                    conn.execute(text("VACUUM"))
                    results.append("VACUUM completed successfully")
                except Exception as e:
                    results.append(f"VACUUM failed: {e}")

            if reindex:
                try:
                    # Get all indexes
                    indexes = conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'")
                    ).fetchall()

                    for (index_name,) in indexes:
                        conn.execute(text(f"REINDEX {index_name}"))

                    results.append(f"Reindexed {len(indexes)} indexes")
                except Exception as e:
                    results.append(f"REINDEX failed: {e}")

        final_size = 0
        try:
            final_size = os.path.getsize(self.db_path)
        except OSError:
            pass

        reclaimed = initial_size - final_size

        return {
            'operations': results,
            'initial_size_mb': round(initial_size / (1024 * 1024), 2),
            'final_size_mb': round(final_size / (1024 * 1024), 2),
            'reclaimed_mb': round(reclaimed / (1024 * 1024), 2),
        }

    def create_backup(self, backup_path: Optional[str] = None) -> str:
        """Create a backup of the database.

        Args:
            backup_path: Custom backup location (None for auto-generated)

        Returns:
            Path to created backup file
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if backup_path:
            backup_file = Path(backup_path)
        else:
            backup_dir = Path(self.db_path).parent
            backup_file = backup_dir / f"cowrie_backup_{timestamp}.sqlite"

        # Create backup using SQLite backup API
        with sqlite3.connect(self.db_path) as source:
            with sqlite3.connect(str(backup_file)) as dest:
                source.backup(dest)

        # Verify backup integrity
        if not self._verify_backup_integrity(str(backup_file)):
            backup_file.unlink()
            raise Exception("Backup integrity check failed")

        return str(backup_file)

    def _verify_backup_integrity(self, backup_path: str) -> bool:
        """Verify backup file integrity.

        Args:
            backup_path: Path to backup file

        Returns:
            True if backup is valid
        """
        try:
            with sqlite3.connect(backup_path) as conn:
                # Basic integrity check
                cursor = conn.execute("PRAGMA integrity_check")
                result = cursor.fetchone()
                return result and result[0] == 'ok'
        except Exception:
            return False

    def check_integrity(self, deep: bool = False) -> Dict[str, Any]:
        """Check database integrity and detect corruption.

        Args:
            deep: Perform deep integrity check

        Returns:
            Integrity check result
        """
        results: Dict[str, Dict[str, Any]] = {
            'quick_check': {'is_valid': False, 'error': None},
            'foreign_keys': {'is_valid': False, 'error': None},
            'indexes': {'is_valid': False, 'error': None},
        }

        if deep:
            results.update(
                {
                    'page_integrity': {'is_valid': False, 'error': None},
                    'cell_integrity': {'is_valid': False, 'error': None},
                }
            )

        with self._get_engine().connect() as conn:
            try:
                # Quick integrity check
                cursor = conn.execute(text("PRAGMA quick_check"))
                result = cursor.fetchone()
                results['quick_check'] = {
                    'is_valid': result and result[0] == 'ok',
                    'error': result[0] if result else 'Unknown error',
                }
            except Exception as e:
                results['quick_check']['error'] = str(e)

            try:
                # Foreign key check
                conn.execute(text("PRAGMA foreign_keys = ON"))
                cursor = conn.execute(text("PRAGMA foreign_key_check"))
                rows = cursor.fetchall()
                results['foreign_keys'] = {
                    'is_valid': len(rows) == 0,
                    'error': f"Found {len(rows)} foreign key violations" if rows else None,
                }
            except Exception as e:
                results['foreign_keys']['error'] = str(e)

            try:
                # Index check
                cursor = conn.execute(text("PRAGMA integrity_check"))
                result = cursor.fetchone()
                results['indexes'] = {
                    'is_valid': result and result[0] == 'ok',
                    'error': result[0] if result else 'Unknown error',
                }
            except Exception as e:
                results['indexes']['error'] = str(e)

            if deep:
                try:
                    # Page integrity (SQLite specific)
                    cursor = conn.execute(text("PRAGMA page_count"))
                    page_count = cursor.fetchone()[0]

                    bad_pages = []
                    for page_num in range(1, page_count + 1):
                        try:
                            cursor = conn.execute(text(f"PRAGMA page_info({page_num})"))
                            cursor.fetchone()  # Just check if page is accessible
                        except Exception:
                            bad_pages.append(page_num)

                    results['page_integrity'] = {
                        'is_valid': len(bad_pages) == 0,
                        'error': f"Found {len(bad_pages)} bad pages" if bad_pages else None,
                    }
                except Exception as e:
                    results['page_integrity']['error'] = str(e)

        corruption_found = any(not r['is_valid'] for r in results.values())

        return {
            'corruption_found': corruption_found,
            'checks': results,
            'recommendations': self._get_integrity_recommendations(results) if corruption_found else [],
        }

    def _get_integrity_recommendations(self, results: Dict[str, Any]) -> list[str]:
        """Get recommendations for fixing corruption."""
        recommendations = []

        if not results['quick_check']['is_valid']:
            recommendations.append("Run 'cowrie-db repair --rebuild-indexes' to attempt repair")

        if not results['foreign_keys']['is_valid']:
            recommendations.append("Restore from backup: corruption affects data integrity")

        if not results['indexes']['is_valid']:
            recommendations.append("Rebuild indexes with 'cowrie-db optimize --reindex'")

        if 'page_integrity' in results and not results['page_integrity']['is_valid']:
            recommendations.append("Database corruption is severe - restore from backup")

        return recommendations


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description='Cowrie database management utilities', prog='cowrie-db')
    parser.add_argument('--db-path', default='../cowrieprocessor.sqlite', help='Path to SQLite database file')

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Migrate command
    migrate_parser = subparsers.add_parser('migrate', help='Run database schema migrations')
    migrate_parser.add_argument('--dry-run', action='store_true', help='Show what would be done without executing')
    migrate_parser.add_argument('--target-version', type=int, help='Target schema version')

    # Check command
    check_parser = subparsers.add_parser('check', help='Validate database schema and health')
    check_parser.add_argument('--verbose', action='store_true', help='Show detailed health information')

    # Optimize command
    optimize_parser = subparsers.add_parser('optimize', help='Run database maintenance operations')
    optimize_parser.add_argument('--no-vacuum', action='store_true', help='Skip VACUUM operation')
    optimize_parser.add_argument('--no-reindex', action='store_true', help='Skip index rebuilding')

    # Backup command
    backup_parser = subparsers.add_parser('backup', help='Create a backup of the database')
    backup_parser.add_argument('--output', help='Custom backup location')

    # Integrity command
    integrity_parser = subparsers.add_parser('integrity', help='Check database integrity and detect corruption')
    integrity_parser.add_argument('--deep', action='store_true', help='Perform deep integrity check')

    # Info command
    subparsers.add_parser('info', help='Display database information and statistics')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    db = CowrieDatabase(args.db_path)

    try:
        if args.command == 'migrate':
            result = db.migrate(target_version=args.target_version, dry_run=args.dry_run)

            if args.dry_run:
                print(f"Would migrate from v{result['current_version']} to v{result['target_version']}")
                for migration in result['migrations_applied']:
                    print(f"  - {migration}")
            else:
                print(f"✓ Migrated database to schema version {result.get('final_version', result['target_version'])}")

            if 'error' in result:
                print(f"❌ Migration failed: {result['error']}", file=sys.stderr)
                sys.exit(1)

        elif args.command == 'check':
            result = db.validate_schema()

            if result['is_valid']:
                print(f"✓ Database schema is current (v{result['schema_version']})")
                if args.verbose:
                    print(f"  Database size: {result['database_size_mb']:.1f} MB")
                    print(f"  Total sessions: {result['session_count']:,}")
                    print(f"  Total commands: {result['command_count']:,}")
                    print(f"  Files downloaded: {result['file_count']:,}")

                    if result['needs_optimization']:
                        print("  ⚠️  Database may benefit from optimization")
                sys.exit(0)
            else:
                print(
                    f"❌ Database schema outdated: v{result['schema_version']} "
                    f"(expected v{result['expected_version']})",
                    file=sys.stderr,
                )
                print("Run 'cowrie-db migrate' to update schema", file=sys.stderr)
                sys.exit(1)

        elif args.command == 'optimize':
            vacuum = not args.no_vacuum
            reindex = not args.no_reindex

            print("Optimizing database...")
            result = db.optimize(vacuum=vacuum, reindex=reindex)

            print("✓ Optimization completed:")
            for operation in result['operations']:
                print(f"  - {operation}")

            if result['reclaimed_mb'] > 0:
                print(f"  Reclaimed {result['reclaimed_mb']:.1f} MB of space")

        elif args.command == 'backup':
            backup_file = db.create_backup(args.output)
            print(f"✓ Backup created: {backup_file}")

        elif args.command == 'integrity':
            result = db.check_integrity(deep=args.deep)

            if result['corruption_found']:
                print("❌ Database corruption detected:", file=sys.stderr)
                for check_name, check_result in result['checks'].items():
                    if not check_result['is_valid']:
                        print(f"  - {check_name}: {check_result['error']}", file=sys.stderr)

                print("\nRecovery options:", file=sys.stderr)
                for recommendation in result['recommendations']:
                    print(f"  - {recommendation}", file=sys.stderr)
                sys.exit(1)
            else:
                print("✓ Database integrity verified")

        elif args.command == 'info':
            result = db.validate_schema()

            print("Database Information:")
            print(f"  Schema version: {result['schema_version']}")
            print(f"  Expected version: {result['expected_version']}")
            print(f"  Database size: {result['database_size_mb']:.1f} MB")
            print(f"  Sessions: {result['session_count']:,}")
            print(f"  Commands: {result['command_count']:,}")
            print(f"  Files downloaded: {result['file_count']:,}")

            if result['needs_optimization']:
                print("  Status: May benefit from optimization")
            else:
                print("  Status: Healthy")

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        # Log error using StatusEmitter
        status_emitter = StatusEmitter('database_cli')
        status_emitter.record_metrics({'error': str(e), 'command': args.command, 'phase': 'cli_error'})
        sys.exit(1)


if __name__ == '__main__':
    main()
