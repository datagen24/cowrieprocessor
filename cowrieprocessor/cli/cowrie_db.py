"""Database management CLI for the Cowrie Processor."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from ..db import CURRENT_SCHEMA_VERSION, apply_migrations, Files
from ..db.engine import create_engine_from_settings
from ..settings import DatabaseSettings
from ..status_emitter import StatusEmitter

logger = logging.getLogger(__name__)


class CowrieDatabase:
    """Database management operations for Cowrie Processor."""

    def __init__(self, db_url: str):
        """Initialize database manager.

        Args:
            db_url: Database connection URL (SQLite or PostgreSQL)
        """
        self.db_url = db_url
        self._engine = None
        self._session_maker = None

    def _get_engine(self):
        """Get or create SQLAlchemy engine."""
        if self._engine is None:
            settings = DatabaseSettings(url=self.db_url)
            self._engine = create_engine_from_settings(settings)
        return self._engine

    def _get_session(self):
        """Get or create session maker."""
        if self._session_maker is None:
            self._session_maker = sessionmaker(bind=self._get_engine(), future=True)
        return self._session_maker()

    def _is_sqlite(self) -> bool:
        """Check if the database is SQLite."""
        return self.db_url.startswith("sqlite://")

    def _is_postgresql(self) -> bool:
        """Check if the database is PostgreSQL."""
        return self.db_url.startswith("postgresql://") or self.db_url.startswith("postgres://")

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
        # Check if database file exists
        if self._is_sqlite():
            db_path = self.db_url.replace("sqlite:///", "")
            db_exists = Path(db_path).exists()
        else:
            # For PostgreSQL, assume database exists if we can connect
            db_exists = True

        if not db_exists:
            current_version = 0
        else:
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
            # Apply migrations directly - this handles creating tables if they don't exist
            final_version = apply_migrations(self._get_engine())
            result['final_version'] = final_version
            result['migrations_applied'] = [
                f"Applied migration to version {v}" for v in range(current_version + 1, final_version + 1)
            ]
            result['message'] = f"Successfully migrated to version {final_version}"

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
            if self._is_sqlite():
                # SQLite: get file size
                db_path = self.db_url.replace("sqlite:///", "")
                db_size = os.path.getsize(db_path)
                result['database_size_mb'] = round(db_size / (1024 * 1024), 2)
            elif self._is_postgresql():
                # PostgreSQL: get database size from system tables
                with self._get_engine().connect() as conn:
                    size_query = text("""
                        SELECT pg_size_pretty(pg_database_size(current_database())) as size,
                               pg_database_size(current_database()) as bytes
                    """)
                    size_result = conn.execute(size_query).fetchone()
                    if size_result:
                        result['database_size_mb'] = round(size_result.bytes / (1024 * 1024), 2)
                    else:
                        result['database_size_mb'] = 0
            else:
                result['database_size_mb'] = 0
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

                # Check files table count if it exists
                try:
                    result['files_table_count'] = session.query(Files).count()
                except Exception:
                    result['files_table_count'] = 0

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
            vacuum: Whether to run VACUUM (SQLite) or ANALYZE (PostgreSQL)
            reindex: Whether to rebuild indexes

        Returns:
            Optimization result with details
        """
        results = []
        initial_size = 0
        final_size = 0

        # Get initial size
        try:
            if self._is_sqlite():
                db_path = self.db_url.replace("sqlite:///", "")
                initial_size = os.path.getsize(db_path)
            elif self._is_postgresql():
                with self._get_engine().connect() as conn:
                    size_result = conn.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
                    initial_size = size_result
        except OSError:
            pass

        with self._get_engine().connect() as conn:
            if vacuum:
                try:
                    if self._is_sqlite():
                        conn.execute(text("VACUUM"))
                        results.append("VACUUM completed successfully")
                    elif self._is_postgresql():
                        conn.execute(text("ANALYZE"))
                        results.append("ANALYZE completed successfully")
                except Exception as e:
                    results.append(f"Vacuum/Analyze failed: {e}")

            if reindex:
                try:
                    if self._is_sqlite():
                        # Get all indexes
                        indexes = conn.execute(
                            text("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'")
                        ).fetchall()

                        for (index_name,) in indexes:
                            conn.execute(text(f"REINDEX {index_name}"))

                        results.append(f"Reindexed {len(indexes)} indexes")
                    elif self._is_postgresql():
                        # PostgreSQL: REINDEX DATABASE
                        conn.execute(text("REINDEX DATABASE"))
                        results.append("REINDEX DATABASE completed successfully")
                except Exception as e:
                    results.append(f"REINDEX failed: {e}")

        # Get final size
        try:
            if self._is_sqlite():
                db_path = self.db_url.replace("sqlite:///", "")
                final_size = os.path.getsize(db_path)
            elif self._is_postgresql():
                with self._get_engine().connect() as conn:
                    size_result = conn.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
                    final_size = size_result
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
        
        if self._is_sqlite():
            # SQLite backup using file copy
            db_path = self.db_url.replace("sqlite:///", "")
            if backup_path:
                backup_file = Path(backup_path)
            else:
                backup_dir = Path(db_path).parent
                backup_file = backup_dir / f"cowrie_backup_{timestamp}.sqlite"
            
            # Copy SQLite file
            import shutil
            shutil.copy2(db_path, str(backup_file))
            
            # Verify backup integrity
            if not self._verify_backup_integrity(str(backup_file)):
                backup_file.unlink()
                raise Exception("Backup integrity check failed")
            
            return str(backup_file)
            
        elif self._is_postgresql():
            # PostgreSQL backup using pg_dump
            import subprocess
            
            if backup_path:
                backup_file = Path(backup_path)
            else:
                backup_file = Path(f"cowrie_backup_{timestamp}.sql")
            
            # Extract connection details from URL
            # Format: postgresql://user:password@host:port/database
            url_parts = self.db_url.replace("postgresql://", "").replace("postgres://", "")
            if "@" in url_parts:
                auth, host_db = url_parts.split("@", 1)
                if ":" in auth:
                    user, password = auth.split(":", 1)
                else:
                    user = auth
                    password = ""
                
                if "/" in host_db:
                    host_port, database = host_db.split("/", 1)
                    if ":" in host_port:
                        host, port = host_port.split(":", 1)
                    else:
                        host = host_port
                        port = "5432"
                else:
                    host = host_db
                    port = "5432"
                    database = "postgres"
            else:
                # Simple format: postgresql://database
                user = "postgres"
                password = ""
                host = "localhost"
                port = "5432"
                database = url_parts
            
            # Set environment variables for pg_dump
            env = os.environ.copy()
            if password:
                env['PGPASSWORD'] = password
            
            # Run pg_dump
            cmd = [
                'pg_dump',
                '-h', host,
                '-p', port,
                '-U', user,
                '-d', database,
                '-f', str(backup_file),
                '--no-password'
            ]
            
            try:
                subprocess.run(cmd, env=env, check=True, capture_output=True)
                return str(backup_file)
            except subprocess.CalledProcessError as e:
                raise Exception(f"PostgreSQL backup failed: {e.stderr.decode()}")
        else:
            raise Exception(f"Backup not supported for database type: {self.db_url}")

    def _verify_backup_integrity(self, backup_path: str) -> bool:
        """Verify backup file integrity.

        Args:
            backup_path: Path to backup file

        Returns:
            True if backup is valid
        """
        try:
            if self._is_sqlite():
                # SQLite integrity check
                import sqlite3
                with sqlite3.connect(backup_path) as conn:
                    cursor = conn.execute("PRAGMA integrity_check")
                    result = cursor.fetchone()
                    return result and result[0] == 'ok'
            elif self._is_postgresql():
                # PostgreSQL backup verification (check if file exists and is not empty)
                backup_file = Path(backup_path)
                return backup_file.exists() and backup_file.stat().st_size > 0
            else:
                return False
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
            if self._is_sqlite():
                # SQLite-specific integrity checks
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

            elif self._is_postgresql():
                # PostgreSQL-specific integrity checks
                try:
                    # Check for dead tuples and bloat
                    cursor = conn.execute(text("""
                        SELECT schemaname, tablename, n_dead_tup, n_live_tup
                        FROM pg_stat_user_tables
                        WHERE n_dead_tup > 0
                    """))
                    dead_tuples = cursor.fetchall()
                    
                    results['quick_check'] = {
                        'is_valid': len(dead_tuples) == 0,
                        'error': f"Found {len(dead_tuples)} tables with dead tuples" if dead_tuples else None,
                    }
                except Exception as e:
                    results['quick_check']['error'] = str(e)

                try:
                    # Check for foreign key violations
                    cursor = conn.execute(text("""
                        SELECT COUNT(*) FROM (
                            SELECT 1 FROM information_schema.table_constraints
                            WHERE constraint_type = 'FOREIGN KEY'
                        ) fk_check
                    """))
                    fk_count = cursor.fetchone()[0]
                    
                    results['foreign_keys'] = {
                        'is_valid': True,  # PostgreSQL maintains FK integrity automatically
                        'error': None,
                    }
                except Exception as e:
                    results['foreign_keys']['error'] = str(e)

                try:
                    # Check for index corruption
                    cursor = conn.execute(text("""
                        SELECT COUNT(*) FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE c.relkind = 'i' AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                    """))
                    index_count = cursor.fetchone()[0]
                    
                    results['indexes'] = {
                        'is_valid': True,  # PostgreSQL maintains index integrity automatically
                        'error': None,
                    }
                except Exception as e:
                    results['indexes']['error'] = str(e)

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

    def backfill_files_table(self, batch_size: int = 1000, limit: Optional[int] = None) -> Dict[str, Any]:
        """Backfill files table from historical raw_events data.

        Args:
            batch_size: Number of records to process in each batch
            limit: Maximum number of events to process (None for all)

        Returns:
            Backfill result with statistics
        """
        result = {
            'events_processed': 0,
            'files_inserted': 0,
            'errors': 0,
            'batches_processed': 0,
        }

        try:
            # Check if files table exists
            with self._get_engine().connect() as conn:
                tables = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name='files'")
                ).fetchall()

                if not tables:
                    raise Exception("Files table does not exist. Run 'cowrie-db migrate' first.")

            # Import here to avoid circular imports
            from ..loader.file_processor import extract_file_data, create_files_record
            from ..db.json_utils import JSONAccessor, get_dialect_name_from_engine

            with self._get_engine().connect() as conn:
                dialect_name = get_dialect_name_from_engine(self._get_engine())
                
                # Query for file download events using JSON abstraction
                if dialect_name == "postgresql":
                    query = text("""
                        SELECT payload->>'session' as session_id, payload
                        FROM raw_events
                        WHERE payload->>'eventid' = 'cowrie.session.file_download'
                          AND payload->>'shasum' IS NOT NULL
                          AND payload->>'shasum' != ''
                        ORDER BY id ASC
                    """)
                else:
                    query = text("""
                        SELECT json_extract(payload, '$.session') as session_id, payload
                        FROM raw_events
                        WHERE json_extract(payload, '$.eventid') = 'cowrie.session.file_download'
                          AND json_extract(payload, '$.shasum') IS NOT NULL
                          AND json_extract(payload, '$.shasum') != ''
                        ORDER BY id ASC
                    """)

                if limit:
                    query = text(str(query) + f" LIMIT {limit}")

                events = conn.execute(query).fetchall()

                if not events:
                    result['message'] = "No file download events found to backfill"
                    return result

                # Process events in batches
                batch = []
                for event in events:
                    try:
                        # Parse payload
                        import json

                        payload = json.loads(event.payload) if isinstance(event.payload, str) else event.payload

                        # Extract file data
                        file_data = extract_file_data(payload, event.session_id)
                        if file_data:
                            file_record = create_files_record(file_data)
                            batch.append(file_record)
                            result['events_processed'] += 1

                        # Process batch when it reaches batch_size
                        if len(batch) >= batch_size:
                            inserted = self._insert_files_batch(batch)
                            result['files_inserted'] += inserted
                            result['batches_processed'] += 1
                            batch = []

                    except Exception as e:
                        logger.warning(f"Error processing event: {e}")
                        result['errors'] += 1

                # Process remaining batch
                if batch:
                    inserted = self._insert_files_batch(batch)
                    result['files_inserted'] += inserted
                    result['batches_processed'] += 1

                result['message'] = (
                    f"Backfill completed: {result['files_inserted']} files inserted from {result['events_processed']} events"
                )

        except Exception as e:
            result['error'] = str(e)
            result['message'] = f"Backfill failed: {e}"
            raise Exception(f"Backfill failed: {e}") from e

        return result

    def _insert_files_batch(self, files: list[Files]) -> int:
        """Insert a batch of files with conflict resolution."""
        if not files:
            return 0

        try:
            with self._get_engine().begin() as conn:
                from sqlalchemy.dialects.sqlite import insert

                # Convert Files objects to dictionaries
                file_dicts = []
                for file_record in files:
                    file_dict = {
                        "session_id": file_record.session_id,
                        "shasum": file_record.shasum,
                        "filename": file_record.filename,
                        "file_size": file_record.file_size,
                        "download_url": file_record.download_url,
                        "vt_classification": file_record.vt_classification,
                        "vt_description": file_record.vt_description,
                        "vt_malicious": file_record.vt_malicious or False,
                        "vt_first_seen": file_record.vt_first_seen,
                        "vt_last_analysis": file_record.vt_last_analysis,
                        "vt_positives": file_record.vt_positives,
                        "vt_total": file_record.vt_total,
                        "vt_scan_date": file_record.vt_scan_date,
                        "first_seen": file_record.first_seen,
                        "enrichment_status": file_record.enrichment_status or "pending",
                    }
                    file_dicts.append(file_dict)

                # Use INSERT OR IGNORE for conflict resolution
                stmt = insert(Files.__table__).values(file_dicts)
                stmt = stmt.on_conflict_do_nothing(index_elements=["session_id", "shasum"])

                result = conn.execute(stmt)
                return int(result.rowcount or 0)

        except Exception as e:
            logger.error(f"Error inserting files batch: {e}")
            return 0

    def get_files_table_stats(self) -> Dict[str, Any]:
        """Get statistics about the files table.

        Returns:
            Files table statistics
        """
        result = {
            'total_files': 0,
            'unique_hashes': 0,
            'enrichment_status': {},
            'malicious_files': 0,
            'pending_enrichment': 0,
        }

        try:
            with self._get_engine().connect() as conn:
                # Total files
                result['total_files'] = conn.execute(text("SELECT COUNT(*) FROM files")).scalar_one()

                # Unique hashes
                result['unique_hashes'] = conn.execute(text("SELECT COUNT(DISTINCT shasum) FROM files")).scalar_one()

                # Enrichment status breakdown
                status_query = text("""
                    SELECT enrichment_status, COUNT(*) as count
                    FROM files
                    GROUP BY enrichment_status
                """)
                for row in conn.execute(status_query):
                    result['enrichment_status'][row.enrichment_status] = row.count

                # Malicious files
                result['malicious_files'] = conn.execute(
                    text("SELECT COUNT(*) FROM files WHERE vt_malicious = 1")
                ).scalar_one()

                # Pending enrichment
                result['pending_enrichment'] = conn.execute(
                    text("SELECT COUNT(*) FROM files WHERE enrichment_status IN ('pending', 'failed')")
                ).scalar_one()

        except Exception as e:
            logger.warning(f"Could not get files table stats: {e}")

        return result


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description='Cowrie database management utilities', prog='cowrie-db')
    parser.add_argument('--db-url', default='sqlite:///cowrieprocessor.sqlite', 
                       help='Database connection URL (SQLite or PostgreSQL)')

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

    # Backfill command
    backfill_parser = subparsers.add_parser('backfill', help='Backfill files table from historical data')
    backfill_parser.add_argument('--batch-size', type=int, default=1000, help='Batch size for processing')
    backfill_parser.add_argument('--limit', type=int, help='Limit number of events to process')

    # Files command
    files_parser = subparsers.add_parser('files', help='Display files table statistics')

    # Info command
    subparsers.add_parser('info', help='Display database information and statistics')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    db = CowrieDatabase(args.db_url)

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

        elif args.command == 'backfill':
            print("Backfilling files table from historical data...")
            result = db.backfill_files_table(batch_size=args.batch_size, limit=args.limit)

            print(f"✓ {result['message']}")
            if result.get('events_processed', 0) > 0:
                print(f"  Events processed: {result['events_processed']:,}")
                print(f"  Files inserted: {result['files_inserted']:,}")
                print(f"  Batches processed: {result['batches_processed']:,}")
                if result.get('errors', 0) > 0:
                    print(f"  Errors: {result['errors']:,}")

            if 'error' in result:
                print(f"❌ Backfill failed: {result['error']}", file=sys.stderr)
                sys.exit(1)

        elif args.command == 'files':
            result = db.get_files_table_stats()

            print("Files Table Statistics:")
            print(f"  Total files: {result['total_files']:,}")
            print(f"  Unique hashes: {result['unique_hashes']:,}")
            print(f"  Malicious files: {result['malicious_files']:,}")
            print(f"  Pending enrichment: {result['pending_enrichment']:,}")

            if result['enrichment_status']:
                print("  Enrichment status breakdown:")
                for status, count in result['enrichment_status'].items():
                    print(f"    {status}: {count:,}")

        elif args.command == 'info':
            result = db.validate_schema()

            print("Database Information:")
            print(f"  Schema version: {result['schema_version']}")
            print(f"  Expected version: {result['expected_version']}")
            print(f"  Database size: {result['database_size_mb']:.1f} MB")
            print(f"  Sessions: {result['session_count']:,}")
            print(f"  Commands: {result['command_count']:,}")
            print(f"  Files downloaded: {result['file_count']:,}")
            print(f"  Files table entries: {result.get('files_table_count', 0):,}")

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
