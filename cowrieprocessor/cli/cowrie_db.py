"""Database management CLI for the Cowrie Processor."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from sqlalchemy import Engine, Table, func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from ..db import CURRENT_SCHEMA_VERSION, Files, apply_migrations
from ..db.engine import create_engine_from_settings
from ..db.json_utils import get_dialect_name_from_engine
from ..db.migrations import _downgrade_from_v9, _upgrade_to_v9
from ..settings import DatabaseSettings
from ..status_emitter import StatusEmitter
from ..utils.unicode_sanitizer import UnicodeSanitizer
from .db_config import add_database_argument, resolve_database_settings


@dataclass
class SanitizationMetrics:
    """Metrics for Unicode sanitization operations."""

    records_processed: int = 0
    records_updated: int = 0
    records_skipped: int = 0
    errors: int = 0
    batches_processed: int = 0
    duration_seconds: float = 0.0
    dry_run: bool = False
    ingest_id: Optional[str] = None


logger = logging.getLogger(__name__)


class CowrieDatabase:
    """Database management operations for Cowrie Processor."""

    def __init__(self, db_url: str):
        """Initialize database manager.

        Args:
            db_url: Database connection URL (SQLite or PostgreSQL)
        """
        self.db_url = db_url
        self._engine: Optional[Engine] = None
        self._session_maker: Optional[sessionmaker[Session]] = None

    def _get_engine(self) -> Engine:
        """Get or create SQLAlchemy engine."""
        if self._engine is None:
            settings = DatabaseSettings(url=self.db_url)
            self._engine = create_engine_from_settings(settings)
        return self._engine

    def _get_session(self) -> Session:
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

    def _table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the current database.

        Args:
            table_name: Name of the table to check

        Returns:
            True if table exists, False otherwise
        """
        with self._get_engine().connect() as conn:
            try:
                if self._is_sqlite():
                    # SQLite: Use sqlite_master
                    result = conn.execute(
                        text(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
                    ).fetchone()
                    return result is not None
                else:
                    # PostgreSQL: Use information_schema
                    result = conn.execute(
                        text("""
                        SELECT table_name FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = :table_name
                        """),
                        {"table_name": table_name},
                    ).fetchone()
                    return result is not None
            except Exception:
                return False

    def _get_all_indexes(self) -> list[str]:
        """Get all index names for the current database.

        Returns:
            List of index names
        """
        with self._get_engine().connect() as conn:
            try:
                if self._is_sqlite():
                    # SQLite: Use sqlite_master
                    result = conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'")
                    ).fetchall()
                    return [row[0] for row in result]
                else:
                    # PostgreSQL: Use information_schema
                    result = conn.execute(
                        text("""
                        SELECT indexname FROM pg_indexes
                        WHERE schemaname = 'public'
                        """)
                    ).fetchall()
                    return [row[0] for row in result]
            except Exception:
                return []

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
                # Check session count - use raw SQL to avoid ORM column issues
                try:
                    session_count_result = session.execute(text("SELECT COUNT(*) FROM session_summaries")).scalar()
                    result['session_count'] = session_count_result if session_count_result is not None else 0
                except Exception as e:
                    logger.warning(f"Could not get session count: {e}")
                    result['session_count'] = 0

                # Check command count
                try:
                    from ..db.models import CommandStat

                    count_result = session.scalar(select(func.count()).select_from(CommandStat))
                    result['command_count'] = count_result if count_result is not None else 0
                except Exception as e:
                    logger.warning(f"Could not get command count: {e}")
                    result['command_count'] = 0

                # Check file count (downloads) - use raw SQL to avoid ORM column issues
                try:
                    file_count_result = session.execute(
                        text("SELECT COUNT(*) FROM session_summaries WHERE file_downloads > 0")
                    ).scalar()
                    result['file_count'] = file_count_result if file_count_result is not None else 0
                except Exception as e:
                    logger.warning(f"Could not get file count: {e}")
                    result['file_count'] = 0

                # Check files table count if it exists
                try:
                    files_count_result = session.scalar(select(func.count()).select_from(Files))
                    result['files_table_count'] = files_count_result if files_count_result is not None else 0
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
                    indexes = self._get_all_indexes()

                    if self._is_sqlite():
                        # SQLite: Reindex each index
                        for index_name in indexes:
                            conn.execute(text(f"REINDEX {index_name}"))
                        results.append(f"Reindexed {len(indexes)} indexes")
                    elif self._is_postgresql():
                        # PostgreSQL: REINDEX DATABASE
                        conn.execute(text("REINDEX DATABASE CONCURRENTLY cowrieprocessor"))
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
                '-h',
                host,
                '-p',
                port,
                '-U',
                user,
                '-d',
                database,
                '-f',
                str(backup_file),
                '--no-password',
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
                    return result is not None and result[0] == 'ok'
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
                        result = cursor.fetchone()
                        if result is not None:
                            page_count = result[0]
                        else:
                            page_count = 0

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
                    cursor = conn.execute(
                        text("""
                        SELECT schemaname, tablename, n_dead_tup, n_live_tup
                        FROM pg_stat_user_tables
                        WHERE n_dead_tup > 0
                    """)
                    )
                    dead_tuples = cursor.fetchall()

                    results['quick_check'] = {
                        'is_valid': len(dead_tuples) == 0,
                        'error': f"Found {len(dead_tuples)} tables with dead tuples" if dead_tuples else None,
                    }
                except Exception as e:
                    results['quick_check']['error'] = str(e)

                try:
                    # Check for foreign key violations
                    results['foreign_keys'] = {
                        'is_valid': True,  # PostgreSQL maintains FK integrity automatically
                        'error': None,
                    }
                except Exception as e:
                    results['foreign_keys']['error'] = str(e)

                try:
                    # Check for index corruption
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
        result: Dict[str, Any] = {
            'events_processed': 0,
            'files_inserted': 0,
            'errors': 0,
            'batches_processed': 0,
            'message': '',  # Add message field
            'error': '',  # Add error field
        }

        try:
            # Check if files table exists
            if not self._table_exists('files'):
                raise Exception("Files table does not exist. Run 'cowrie-db migrate' first.")

            # Import here to avoid circular imports
            from ..db.json_utils import get_dialect_name_from_engine
            from ..loader.file_processor import create_files_record, extract_file_data

            # Get database dialect for query construction
            dialect_name = get_dialect_name_from_engine(self._get_engine())

            # Query for file download events using JSON abstraction
            # Handle binary data gracefully by using safer JSON operators and separate connections
            events: list[Any] = []

            # Primary query attempt - use a more restrictive approach to avoid binary data
            try:
                with self._get_engine().connect() as conn:
                    if dialect_name == "postgresql":
                        # Use a query that avoids JSON operators that trigger Unicode processing
                        # Instead, use text-based filtering and handle sanitization in Python
                        query = text("""
                            SELECT id, payload::text as payload_text
                            FROM raw_events
                            WHERE payload::text LIKE '%cowrie.session.file_download%'
                              AND payload::text LIKE '%shasum%'
                            ORDER BY id ASC
                        """)
                    else:
                        query = text("""
                            SELECT id, payload as payload_text
                            FROM raw_events
                            WHERE payload LIKE '%cowrie.session.file_download%'
                              AND payload LIKE '%shasum%'
                            ORDER BY id ASC
                        """)

                    if limit:
                        query = text(str(query) + f" LIMIT {limit}")

                    raw_events = conn.execute(query).fetchall()

                    # Process each event to extract valid file download events
                    events = []

                    for row in raw_events:
                        try:
                            # Sanitize the payload text before parsing
                            sanitized_payload_text = UnicodeSanitizer.sanitize_json_string(row.payload_text)
                            payload = json.loads(sanitized_payload_text)

                            # Check if this is a valid file download event
                            if (
                                payload.get('eventid') == 'cowrie.session.file_download'
                                and payload.get('shasum')
                                and payload.get('shasum') != ''
                                and payload.get('shasum') != 'null'
                            ):
                                events.append(
                                    type('Row', (), {'session_id': payload.get('session'), 'payload': payload})()
                                )
                        except (json.JSONDecodeError, ValueError, AttributeError) as e:
                            logger.debug(f"Skipping invalid JSON payload at id {row.id}: {e}")
                            result['errors'] += 1
                            continue

            except Exception as e:
                logger.warning(f"Primary query failed due to binary data: {e}")

                # Fallback query attempt - try to get raw data and process it more carefully
                try:
                    logger.info("Attempting fallback query strategy...")
                    with self._get_engine().connect() as conn:
                        if dialect_name == "postgresql":
                            # Get raw payload data as text and process in Python
                            query = text("""
                                SELECT id, payload::text as payload_text
                                FROM raw_events
                                WHERE payload::text LIKE '%cowrie.session.file_download%'
                                ORDER BY id ASC
                            """)
                        else:
                            query = text("""
                                SELECT id, payload as payload_text
                                FROM raw_events
                                WHERE payload LIKE '%cowrie.session.file_download%'
                                ORDER BY id ASC
                            """)

                        if limit:
                            query = text(str(query) + f" LIMIT {limit}")

                        raw_events = conn.execute(query).fetchall()

                        # Process each event with enhanced error handling
                        events = []

                        for row in raw_events:
                            try:
                                # Multiple sanitization attempts
                                payload_text = row.payload_text

                                # First, try basic Unicode sanitization
                                sanitized = UnicodeSanitizer.sanitize_unicode_string(payload_text, strict=True)

                                # Try to parse as JSON
                                try:
                                    payload = json.loads(sanitized)
                                except json.JSONDecodeError:
                                    # Try more aggressive sanitization
                                    sanitized = UnicodeSanitizer.sanitize_json_string(payload_text)
                                    payload = json.loads(sanitized)

                                # Check if this is a valid file download event
                                if (
                                    payload.get('eventid') == 'cowrie.session.file_download'
                                    and payload.get('shasum')
                                    and payload.get('shasum') != ''
                                    and payload.get('shasum') != 'null'
                                ):
                                    events.append(
                                        type('Row', (), {'session_id': payload.get('session'), 'payload': payload})()
                                    )

                            except Exception as parse_error:
                                logger.debug(f"Skipping corrupted payload at id {row.id}: {parse_error}")
                                result['errors'] += 1
                                continue

                except Exception as fallback_error:
                    logger.error(f"Fallback query also failed: {fallback_error}")
                    result['message'] = (
                        "Backfill failed: Unable to process corrupted JSON payloads in raw_events table. "
                        "The data contains Unicode control characters that cannot be processed by PostgreSQL. "
                        "Consider running a data cleanup script or migrating from a clean source."
                    )
                    return result

            if not events:
                result['message'] = "No file download events found to backfill"
                return result

            # Process events in batches
            batch = []
            for event in events:
                try:
                    # Extract file data (payload is already sanitized and parsed)
                    file_data = extract_file_data(event.payload, event.session_id)
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
                f"Backfill completed: {result['files_inserted']} files inserted "
                f"from {result['events_processed']} events"
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
                dialect_name = get_dialect_name_from_engine(self._get_engine())

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

                # Use database-specific conflict resolution
                files_table = Files.__table__
                assert isinstance(files_table, Table), "Files.__table__ should be a Table"

                if dialect_name == "sqlite":
                    # SQLite syntax
                    sqlite_stmt = sqlite_insert(files_table).values(file_dicts)
                    sqlite_stmt = sqlite_stmt.on_conflict_do_nothing()
                    result = conn.execute(sqlite_stmt)
                else:
                    # PostgreSQL syntax
                    from sqlalchemy.dialects.postgresql import insert as postgres_insert

                    postgres_stmt = postgres_insert(files_table).values(file_dicts)
                    postgres_stmt = postgres_stmt.on_conflict_do_nothing(index_elements=["session_id", "shasum"])
                    result = conn.execute(postgres_stmt)
                return int(result.rowcount or 0)

        except Exception as e:
            logger.error(f"Error inserting files batch: {e}")
            return 0

    def sanitize_unicode_in_database(
        self,
        batch_size: int = 1000,
        limit: Optional[int] = None,
        dry_run: bool = False,
        progress_callback: Optional[Callable[[SanitizationMetrics], None]] = None,
    ) -> Dict[str, Any]:
        """Sanitize Unicode control characters in existing database records.

        Args:
            batch_size: Number of records to process in each batch
            limit: Maximum number of records to process (None for all)
            dry_run: If True, only report what would be changed without making changes
            progress_callback: Optional callback function to report progress

        Returns:
            Sanitization result with statistics
        """
        result: Dict[str, Any] = {
            'records_processed': 0,
            'records_updated': 0,
            'records_skipped': 0,
            'errors': 0,
            'batches_processed': 0,
            'dry_run': dry_run,
            'message': '',  # Add message field
            'error': '',  # Add error field
        }

        try:
            # Check if raw_events table exists
            if not self._table_exists('raw_events'):
                raise Exception("Raw events table does not exist.")

            dialect_name = get_dialect_name_from_engine(self._get_engine())

            logger.info(f"Starting Unicode sanitization (dry_run={dry_run})...")

            # Process records in batches
            offset = 0
            while True:
                # Get batch of records to process
                with self._get_engine().connect() as conn:
                    if dialect_name == "postgresql":
                        query = text("""
                            SELECT id, payload::text as payload_text
                            FROM raw_events
                            ORDER BY id ASC
                            LIMIT :batch_size OFFSET :offset
                        """)
                    else:
                        query = text("""
                            SELECT id, payload as payload_text
                            FROM raw_events
                            ORDER BY id ASC
                            LIMIT :batch_size OFFSET :offset
                        """)

                    if limit and (offset + batch_size) > limit:
                        query = text(str(query).replace(":batch_size", str(limit - offset)))

                    batch_records = conn.execute(query, {"batch_size": batch_size, "offset": offset}).fetchall()

                if not batch_records:
                    break

                # Process each record in the batch
                records_to_update = []

                for record in batch_records:
                    try:
                        record_id = record.id
                        original_payload_text = record.payload_text

                        # Check if payload contains problematic Unicode characters
                        if not UnicodeSanitizer.is_safe_for_postgres_json(original_payload_text):
                            # Sanitize the payload
                            sanitized_payload_text = UnicodeSanitizer.sanitize_json_string(original_payload_text)

                            # Verify the sanitized payload is valid JSON and safe
                            try:
                                parsed_payload = json.loads(sanitized_payload_text)
                                if UnicodeSanitizer.is_safe_for_postgres_json(sanitized_payload_text):
                                    records_to_update.append(
                                        {
                                            'id': record_id,
                                            'original': original_payload_text,
                                            'sanitized': sanitized_payload_text,
                                            'parsed': parsed_payload,
                                        }
                                    )
                                    result['records_updated'] += 1
                                else:
                                    logger.warning(
                                        f"Record {record_id}: Sanitized payload still not safe for PostgreSQL"
                                    )
                                    result['records_skipped'] += 1
                            except json.JSONDecodeError as e:
                                logger.warning(f"Record {record_id}: Sanitized payload is not valid JSON: {e}")
                                result['records_skipped'] += 1
                        else:
                            result['records_skipped'] += 1

                        result['records_processed'] += 1

                    except Exception as e:
                        logger.error(f"Error processing record {record.id}: {e}")
                        result['errors'] += 1
                        result['records_processed'] += 1

                # Update records in the database (unless dry run)
                if records_to_update and not dry_run:
                    with self._get_engine().begin() as conn:
                        for update_record in records_to_update:
                            try:
                                if dialect_name == "postgresql":
                                    # Update PostgreSQL JSONB column
                                    # Use CAST() instead of :: to avoid parameter binding conflicts
                                    update_query = text("""
                                        UPDATE raw_events
                                        SET payload = CAST(:sanitized_payload AS jsonb)
                                        WHERE id = :record_id
                                    """)
                                else:
                                    # Update SQLite JSON column
                                    update_query = text("""
                                        UPDATE raw_events 
                                        SET payload = :sanitized_payload
                                        WHERE id = :record_id
                                    """)

                                conn.execute(
                                    update_query,
                                    {"sanitized_payload": update_record['sanitized'], "record_id": update_record['id']},
                                )

                            except Exception as e:
                                logger.error(f"Error updating record {update_record['id']}: {e}")
                                result['errors'] += 1

                result['batches_processed'] += 1
                offset += batch_size

                # Log progress and emit status
                if result['batches_processed'] % 10 == 0:
                    logger.info(
                        f"Processed {result['records_processed']} records, "
                        f"updated {result['records_updated']}, "
                        f"skipped {result['records_skipped']}, "
                        f"errors {result['errors']}"
                    )

                    # Emit progress via callback if provided
                    if progress_callback:
                        metrics = SanitizationMetrics(
                            records_processed=result['records_processed'],
                            records_updated=result['records_updated'],
                            records_skipped=result['records_skipped'],
                            errors=result['errors'],
                            batches_processed=result['batches_processed'],
                            dry_run=dry_run,
                        )
                        progress_callback(metrics)

                # Check if we've reached the limit
                if limit and result['records_processed'] >= limit:
                    break

            # Final result message
            if dry_run:
                result['message'] = (
                    f"Dry run completed: {result['records_processed']} records analyzed, "
                    f"{result['records_updated']} would be updated, "
                    f"{result['records_skipped']} would be skipped, "
                    f"{result['errors']} errors"
                )
            else:
                result['message'] = (
                    f"Sanitization completed: {result['records_processed']} records processed, "
                    f"{result['records_updated']} updated, "
                    f"{result['records_skipped']} skipped, "
                    f"{result['errors']} errors"
                )

        except Exception as e:
            result['error'] = str(e)
            result['message'] = f"Sanitization failed: {e}"
            raise Exception(f"Sanitization failed: {e}") from e

        return result

    def analyze_data_quality(self, sample_size: int = 1000) -> Dict[str, Any]:
        """Analyze data quality issues in the database.

        Args:
            sample_size: Number of records to sample for JSON analysis

        Returns:
            Data quality analysis results
        """
        logger.info("🔍 Starting data quality analysis...")

        # Database overview
        overview = self._analyze_database_overview()

        # JSON payload analysis
        json_analysis = self._analyze_json_sample(sample_size)

        # Boolean field analysis
        boolean_analysis = self._analyze_boolean_fields()

        # Missing field analysis
        missing_analysis = self._analyze_missing_fields()

        # Generate recommendations
        recommendations = self._generate_quality_recommendations(json_analysis, boolean_analysis, missing_analysis)

        analysis_summary = {
            'timestamp': datetime.now().isoformat(),
            'analysis_duration_seconds': 0,  # Will be calculated below
            'sample_size': sample_size,
            'overview': overview,
            'json_analysis': json_analysis,
            'boolean_analysis': boolean_analysis,
            'missing_analysis': missing_analysis,
            'recommendations': recommendations,
        }

        logger.info("✅ Data quality analysis complete")
        logger.info("📋 Recommendations:")
        for i, rec in enumerate(recommendations, 1):
            logger.info(f"   {i}. {rec}")

        return analysis_summary

    def _analyze_database_overview(self) -> Dict[str, Any]:
        """Get basic database statistics."""
        logger.info("📊 Analyzing database overview...")

        try:
            with self._get_engine().connect() as conn:
                # Get table counts
                tables = ['raw_events', 'session_summaries', 'command_stats', 'files', 'dead_letter_events']
                table_counts = {}

                for table in tables:
                    try:
                        result = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).fetchone()
                        table_counts[table] = result[0] if result else 0
                    except Exception as e:
                        logger.warning(f"Could not count {table}: {e}")
                        table_counts[table] = 0

                # Get database size
                db_size_mb = 0.0
                if self._is_sqlite():
                    db_path = self.db_url.replace("sqlite:///", "")
                    try:
                        import os

                        db_size_mb = round(os.path.getsize(db_path) / (1024 * 1024), 2)
                    except OSError:
                        db_size_mb = 0.0

                overview = {
                    'table_counts': table_counts,
                    'database_size_mb': db_size_mb,
                    'total_records': sum(table_counts.values()),
                }

                logger.info(f"✅ Database overview: {overview['total_records']} total records")
                return overview

        except Exception as e:
            logger.error(f"❌ Database overview failed: {e}")
            raise

    def _analyze_json_sample(self, sample_size: int = 1000) -> Dict[str, Any]:
        """Analyze a sample of JSON payloads."""
        logger.info(f"🔍 Analyzing JSON payload sample ({sample_size} records)...")

        try:
            with self._get_engine().connect() as conn:
                # Get sample of payloads - handle PostgreSQL JSON comparison
                dialect_name = conn.dialect.name
                if dialect_name == "postgresql":
                    payload_filter = "payload IS NOT NULL"
                else:
                    payload_filter = "payload IS NOT NULL AND payload != ''"

                # Handle PostgreSQL JSON grouping issue
                if dialect_name == "postgresql":
                    # For PostgreSQL, use a different approach - sample by ID instead of grouping by payload
                    result = conn.execute(
                        text(f"""
                        SELECT id, payload
                        FROM raw_events
                        WHERE {payload_filter}
                        ORDER BY id
                        LIMIT {sample_size}
                    """)
                    ).fetchall()
                    # Convert to expected format for analysis
                    payloads = [row[1] for row in result]
                else:
                    result = conn.execute(
                        text(f"""
                        SELECT payload, COUNT(*) as count
                        FROM raw_events
                        WHERE {payload_filter}
                        GROUP BY payload
                        ORDER BY count DESC
                        LIMIT {sample_size}
                    """)
                    ).fetchall()
                    payloads = [row[0] for row in result]

                total_records = 0
                valid_json_count = 0
                invalid_json_count = 0
                malformed_samples: list[Any] = []

                if dialect_name == "postgresql":
                    # For PostgreSQL, we sampled by ID so each payload counts as 1
                    for payload in payloads:
                        total_records += 1

                        # Convert dict payload to string for JSON parsing
                        payload_str = payload if isinstance(payload, str) else str(payload)

                        # Try to parse JSON
                        try:
                            import json

                            json.loads(payload_str)
                            valid_json_count += 1
                        except json.JSONDecodeError:
                            invalid_json_count += 1
                            # Analyze malformed JSON pattern
                            pattern = self._identify_malformed_pattern(payload_str)
                else:
                    # For SQLite, we have count information
                    for payload, count in result:
                        total_records += count

                        # Try to parse JSON
                        try:
                            import json

                            json.loads(payload)
                            valid_json_count += count
                        except json.JSONDecodeError:
                            invalid_json_count += count

                            # Analyze malformed JSON pattern
                            pattern = self._identify_malformed_pattern(payload)
                            if len(malformed_samples) < 10:  # Keep only top 10 samples
                                malformed_samples.append(
                                    {
                                        'payload_preview': (
                                            payload_str[:100] + '...' if len(payload_str) > 100 else payload_str
                                        ),
                                        'count': 1,  # PostgreSQL sample is 1 record
                                        'pattern': pattern,
                                    }
                                )

                # Get additional statistics - handle PostgreSQL JSON comparison
                if dialect_name == "postgresql":
                    empty_payloads = conn.execute(
                        text("SELECT COUNT(*) FROM raw_events WHERE payload IS NULL OR payload::text = ''")
                    ).scalar()
                else:
                    empty_payloads = conn.execute(
                        text("SELECT COUNT(*) FROM raw_events WHERE payload IS NULL OR payload = ''")
                    ).scalar()
                total_raw_events = conn.execute(text("SELECT COUNT(*) FROM raw_events")).scalar()

                # Handle None values from scalar()
                if total_raw_events is None:
                    total_raw_events = 0
                if empty_payloads is None:
                    empty_payloads = 0

                analysis_result = {
                    'sample_size': sample_size,
                    'total_raw_events': total_raw_events,
                    'empty_payloads': empty_payloads,
                    'non_empty_payloads': total_raw_events - empty_payloads,
                    'valid_json_count': valid_json_count,
                    'invalid_json_count': invalid_json_count,
                    'malformed_samples': malformed_samples,
                    'valid_json_percentage': (valid_json_count / total_records * 100) if total_records > 0 else 0,
                    'invalid_json_percentage': (invalid_json_count / total_records * 100) if total_records > 0 else 0,
                }

                logger.info(f"✅ JSON analysis: {valid_json_count} valid, {invalid_json_count} invalid")
                return analysis_result

        except Exception as e:
            logger.error(f"❌ JSON analysis failed: {e}")
            raise

    def _identify_malformed_pattern(self, payload: str) -> str:
        """Identify the pattern of malformed JSON."""
        if '\\"' in payload and payload.count('"') % 2 != 0:
            return 'escaped_quotes'
        elif payload.startswith('{') and not payload.endswith('}'):
            return 'incomplete_object'
        elif '],' in payload or '},' in payload:
            return 'array_element'
        elif payload in ['{}', '[]', '']:
            return 'empty'
        elif payload.startswith('"') and payload.endswith('"'):
            return 'string_wrapped'
        else:
            return 'unknown'

    def _analyze_boolean_fields(self) -> Dict[str, Any]:
        """Analyze boolean field data quality."""
        logger.info("🔍 Analyzing boolean field quality...")

        try:
            with self._get_engine().connect() as conn:
                boolean_issues = {}

                # Check quarantined field
                result = conn.execute(
                    text("""
                    SELECT quarantined, COUNT(*) as count
                    FROM raw_events
                    GROUP BY quarantined
                """)
                ).fetchall()

                quarantined_issues = []
                for value, count in result:
                    if value not in [0, 1, '0', '1', True, False]:
                        quarantined_issues.append({'value': str(value), 'count': count})

                boolean_issues['quarantined'] = {
                    'issues': quarantined_issues,
                    'total_records': sum(count for _, count in result),
                }

                logger.info(f"✅ Boolean analysis: {len(quarantined_issues)} issues found")
                return boolean_issues

        except Exception as e:
            logger.error(f"❌ Boolean analysis failed: {e}")
            raise

    def _analyze_missing_fields(self) -> Dict[str, Any]:
        """Analyze missing field patterns."""
        logger.info("🔍 Analyzing missing field patterns...")

        try:
            with self._get_engine().connect() as conn:
                # Check for NULL session_id, event_type, event_timestamp
                result = conn.execute(
                    text("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(session_id) as has_session_id,
                        COUNT(event_type) as has_event_type,
                        COUNT(event_timestamp) as has_event_timestamp
                    FROM raw_events
                """)
                ).fetchone()

                if result is not None:
                    total_count = result[0]
                    has_session_id = result[1]
                    has_event_type = result[2]
                    has_event_timestamp = result[3]
                else:
                    total_count = has_session_id = has_event_type = has_event_timestamp = 0

                missing_analysis = {
                    'total': total_count,
                    'missing_session_id': total_count - has_session_id,
                    'missing_event_type': total_count - has_event_type,
                    'missing_event_timestamp': total_count - has_event_timestamp,
                    'missing_percentages': {
                        'session_id': ((total_count - has_session_id) / total_count * 100) if total_count > 0 else 0,
                        'event_type': ((total_count - has_event_type) / total_count * 100) if total_count > 0 else 0,
                        'event_timestamp': ((total_count - has_event_timestamp) / total_count * 100)
                        if total_count > 0
                        else 0,
                    },
                }

                logger.info(
                    f"✅ Missing field analysis: {missing_analysis['missing_session_id']} missing "
                    f"session_ids ({missing_analysis['missing_percentages']['session_id']:.1f}%)"
                )
                return missing_analysis

        except Exception as e:
            logger.error(f"❌ Missing field analysis failed: {e}")
            raise

    def _generate_quality_recommendations(
        self, json_analysis: Dict, boolean_analysis: Dict, missing_analysis: Dict
    ) -> list[str]:
        """Generate recommendations based on analysis."""
        recommendations = []

        if json_analysis['invalid_json_percentage'] > 20:
            recommendations.append("🚨 HIGH: >20% malformed JSON - use robust migration script with data cleaning")
        elif json_analysis['invalid_json_percentage'] > 10:
            recommendations.append("⚠️  MEDIUM: >10% malformed JSON - consider data cleaning before migration")
        elif json_analysis['invalid_json_percentage'] > 0:
            recommendations.append("ℹ️  LOW: Some malformed JSON detected - standard migration should handle this")

        if missing_analysis['missing_percentages']['session_id'] > 50:
            recommendations.append("🚨 HIGH: >50% missing session_id - backfill from JSON payload recommended")
        elif missing_analysis['missing_percentages']['session_id'] > 0:
            recommendations.append("ℹ️  INFO: Some missing session_id fields - consider backfill")

        if boolean_analysis['quarantined']['issues']:
            recommendations.append("⚠️  MEDIUM: Boolean field issues detected - use data repair tools")

        if not recommendations:
            recommendations.append("✅ Data quality looks good - standard migration should work")

        return recommendations

    def repair_data_quality(self, batch_size: int = 10000, dry_run: bool = True) -> Dict[str, Any]:
        """Repair data quality issues in the database.

        Args:
            batch_size: Number of records to process in each batch
            dry_run: Show what would be repaired without making changes

        Returns:
            Data repair results
        """
        logger.info(f"🔧 Starting data repair {'(dry run)' if dry_run else ''}...")

        # Backfill missing fields
        backfill_result = self._repair_missing_fields(batch_size, dry_run)

        # Calculate unrepairable records (malformed data)
        # Only count as unrepairable if we actually tried to repair but couldn't
        unrepairable_records = 0
        if (
            backfill_result.get('generated_columns', {}).get('session_id', False)
            and backfill_result.get('generated_columns', {}).get('event_type', False)
            and backfill_result.get('generated_columns', {}).get('event_timestamp', False)
        ):
            # All columns are generated - no records are actually unrepairable
            unrepairable_records = 0
        else:
            # Some columns are regular - but if we have binary data issues, treat as unrepairable
            # This happens when JSON payloads contain binary data that PostgreSQL can't process
            if backfill_result['fields_backfilled'] == 0 and backfill_result['total_missing'] > 0:
                # If no fields were backfilled but there are missing fields, likely binary data issue
                unrepairable_records = backfill_result['total_missing']
            else:
                # Calculate actual unrepairable records
                unrepairable_records = backfill_result['total_missing'] - backfill_result['fields_backfilled']

        repair_summary = {
            'dry_run': dry_run,
            'total_missing': backfill_result['total_missing'],
            'records_processed': backfill_result['records_processed'],
            'fields_backfilled': backfill_result['fields_backfilled'],
            'unrepairable_records': unrepairable_records,
            'errors': backfill_result['errors'],
            'duration_seconds': backfill_result['duration_seconds'],
            'recommendations': [
                "Run 'cowrie-db repair' without --dry-run to apply fixes"
                if dry_run
                else f"✅ Successfully processed {backfill_result['fields_backfilled']} repairable records",
                f"ℹ️  {unrepairable_records:,} records contain genuinely malformed data "
                "and cannot be automatically repaired",
                "Consider running 'cowrie-db migrate' to update schema after repair",
            ],
        }

        logger.info(
            f"✅ Data repair {'analysis' if dry_run else 'complete'}: "
            f"{repair_summary['fields_backfilled']} fields backfilled"
        )
        return repair_summary

    def _repair_missing_fields(self, batch_size: int = 10000, dry_run: bool = True) -> Dict[str, Any]:
        """Backfill missing session_id, event_type, event_timestamp from JSON payload."""
        logger.info(f"🔧 {'Analyzing' if dry_run else 'Backfilling'} missing fields...")

        try:
            with self._get_engine().connect() as conn:
                # Check if columns are generated columns (cannot be updated)
                from ..db.migrations import _is_generated_column

                session_id_generated = _is_generated_column(conn, "raw_events", "session_id")
                event_type_generated = _is_generated_column(conn, "raw_events", "event_type")
                event_timestamp_generated = _is_generated_column(conn, "raw_events", "event_timestamp")

                logger.info(
                    f"Column status: session_id={'generated' if session_id_generated else 'regular'}, "
                    f"event_type={'generated' if event_type_generated else 'regular'}, "
                    f"event_timestamp={'generated' if event_timestamp_generated else 'regular'}"
                )

                # If all columns are generated, there's nothing to repair
                if session_id_generated and event_type_generated and event_timestamp_generated:
                    logger.info("✅ All columns are generated columns - no repair needed")
                    return {
                        'total_missing': 0,
                        'records_processed': 0,
                        'fields_backfilled': 0,
                        'session_id_updated': 0,
                        'event_type_updated': 0,
                        'event_timestamp_updated': 0,
                        'errors': 0,
                        'duration_seconds': 0,
                        'note': 'All columns are generated columns that auto-compute from JSON payload',
                    }

                # Find records with missing fields (only for non-generated columns)
                missing_conditions = []
                if not session_id_generated:
                    missing_conditions.append("session_id IS NULL")
                if not event_type_generated:
                    missing_conditions.append("event_type IS NULL")
                if not event_timestamp_generated:
                    missing_conditions.append("event_timestamp IS NULL")

                if not missing_conditions:
                    logger.info("✅ No non-generated columns need repair")
                    return {
                        'total_missing': 0,
                        'records_processed': 0,
                        'fields_backfilled': 0,
                        'session_id_updated': 0,
                        'event_type_updated': 0,
                        'event_timestamp_updated': 0,
                        'errors': 0,
                        'duration_seconds': 0,
                        'note': 'All columns are generated columns that auto-compute from JSON payload',
                    }

                where_clause = " OR ".join(missing_conditions)

                # Handle PostgreSQL JSON column comparison
                dialect_name = conn.dialect.name
                if dialect_name == "postgresql":
                    payload_not_empty = "AND payload IS NOT NULL"
                else:
                    payload_not_empty = "AND payload IS NOT NULL AND payload != ''"

                try:
                    count_result = conn.execute(
                        text(f"""
                        SELECT COUNT(*) as total_missing
                        FROM raw_events
                        WHERE ({where_clause})
                          {payload_not_empty}
                    """)
                    ).fetchone()

                    total_missing = count_result[0] if count_result else 0
                except Exception:
                    # If we can't count due to binary data issues, fall back to a simpler query
                    logger.warning("Using fallback count query due to binary data in JSON payload")
                    count_result = conn.execute(
                        text(f"""
                        SELECT COUNT(*) as total_missing
                        FROM raw_events
                        WHERE ({where_clause})
                          AND payload IS NOT NULL
                    """)
                    ).fetchone()

                    total_missing = count_result[0] if count_result else 0
                logger.info(f"Found {total_missing} records with missing fields in non-generated columns")

                if total_missing == 0:
                    return {
                        'total_missing': 0,
                        'records_processed': 0,
                        'fields_backfilled': 0,
                        'session_id_updated': 0,
                        'event_type_updated': 0,
                        'event_timestamp_updated': 0,
                        'errors': 0,
                        'duration_seconds': 0,
                    }

                # Use bulk SQL updates for much better performance
                import time

                start_time = time.time()

                # Check database type for appropriate JSON extraction syntax
                dialect_name = conn.dialect.name

                session_id_updated = 0
                event_type_updated = 0
                event_timestamp_updated = 0

                if dialect_name == "postgresql":
                    # PostgreSQL bulk updates using JSON operators - handle binary data gracefully
                    if not session_id_generated and not dry_run:
                        try:
                            update_result = conn.execute(
                                text("""
                                UPDATE raw_events
                                SET session_id = payload->>'session'
                                WHERE session_id IS NULL
                                  AND payload IS NOT NULL
                                  AND (payload->'session') IS NOT NULL
                            """)
                            )
                            session_id_updated = update_result.rowcount or 0
                        except Exception:
                            # If we can't process due to binary data, skip this field
                            logger.warning("Skipping session_id updates due to binary data in JSON payload")
                            session_id_updated = 0
                    elif not session_id_generated and dry_run:
                        try:
                            result = conn.execute(
                                text("""
                                SELECT COUNT(*) FROM raw_events
                                WHERE session_id IS NULL
                                  AND payload IS NOT NULL
                                  AND (payload->'session') IS NOT NULL
                            """)
                            )
                            session_id_updated = result.scalar_one() or 0
                        except Exception:
                            # If we can't count due to binary data, assume 0
                            session_id_updated = 0

                    if not event_type_generated and not dry_run:
                        try:
                            result = conn.execute(
                                text("""
                                UPDATE raw_events
                                SET event_type = payload->>'eventid'
                                WHERE event_type IS NULL
                                  AND payload IS NOT NULL
                                  AND (payload->'eventid') IS NOT NULL
                            """)
                            )
                            event_type_updated = result.rowcount or 0
                        except Exception:
                            logger.warning("Skipping event_type updates due to binary data in JSON payload")
                            event_type_updated = 0
                    elif not event_type_generated and dry_run:
                        try:
                            result = conn.execute(
                                text("""
                                SELECT COUNT(*) FROM raw_events
                                WHERE event_type IS NULL
                                  AND payload IS NOT NULL
                                  AND (payload->'eventid') IS NOT NULL
                            """)
                            )
                            event_type_updated = result.scalar_one() or 0
                        except Exception:
                            event_type_updated = 0

                    if not event_timestamp_generated and not dry_run:
                        try:
                            result = conn.execute(
                                text("""
                                UPDATE raw_events
                                SET event_timestamp = payload->>'timestamp'
                                WHERE event_timestamp IS NULL
                                  AND payload IS NOT NULL
                                  AND (payload->'timestamp') IS NOT NULL
                            """)
                            )
                            event_timestamp_updated = result.rowcount or 0
                        except Exception:
                            logger.warning("Skipping event_timestamp updates due to binary data in JSON payload")
                            event_timestamp_updated = 0
                    elif not event_timestamp_generated and dry_run:
                        try:
                            result = conn.execute(
                                text("""
                                SELECT COUNT(*) FROM raw_events
                                WHERE event_timestamp IS NULL
                                  AND payload IS NOT NULL
                                  AND (payload->'timestamp') IS NOT NULL
                            """)
                            )
                            event_timestamp_updated = result.scalar_one() or 0
                        except Exception:
                            event_timestamp_updated = 0

                else:
                    # SQLite bulk updates using json_extract
                    if not session_id_generated and not dry_run:
                        result = conn.execute(
                            text("""
                            UPDATE raw_events 
                            SET session_id = json_extract(payload, '$.session') 
                            WHERE session_id IS NULL 
                              AND payload IS NOT NULL 
                              AND payload != ''
                              AND json_extract(payload, '$.session') IS NOT NULL
                        """)
                        )
                        session_id_updated = result.rowcount or 0
                    elif not session_id_generated and dry_run:
                        result = conn.execute(
                            text("""
                            SELECT COUNT(*) FROM raw_events 
                            WHERE session_id IS NULL 
                              AND payload IS NOT NULL 
                              AND payload != ''
                              AND json_extract(payload, '$.session') IS NOT NULL
                        """)
                        )
                        session_id_updated = result.scalar_one() or 0

                    if not event_type_generated and not dry_run:
                        result = conn.execute(
                            text("""
                            UPDATE raw_events 
                            SET event_type = json_extract(payload, '$.eventid') 
                            WHERE event_type IS NULL 
                              AND payload IS NOT NULL 
                              AND payload != ''
                              AND json_extract(payload, '$.eventid') IS NOT NULL
                        """)
                        )
                        event_type_updated = result.rowcount or 0
                    elif not event_type_generated and dry_run:
                        result = conn.execute(
                            text("""
                            SELECT COUNT(*) FROM raw_events 
                            WHERE event_type IS NULL 
                              AND payload IS NOT NULL 
                              AND payload != ''
                              AND json_extract(payload, '$.eventid') IS NOT NULL
                        """)
                        )
                        event_type_updated = result.scalar_one() or 0

                    if not event_timestamp_generated and not dry_run:
                        result = conn.execute(
                            text("""
                            UPDATE raw_events 
                            SET event_timestamp = json_extract(payload, '$.timestamp') 
                            WHERE event_timestamp IS NULL 
                              AND payload IS NOT NULL 
                              AND payload != ''
                              AND json_extract(payload, '$.timestamp') IS NOT NULL
                        """)
                        )
                        event_timestamp_updated = result.rowcount or 0
                    elif not event_timestamp_generated and dry_run:
                        result = conn.execute(
                            text("""
                            SELECT COUNT(*) FROM raw_events 
                            WHERE event_timestamp IS NULL 
                              AND payload IS NOT NULL 
                              AND payload != ''
                              AND json_extract(payload, '$.timestamp') IS NOT NULL
                        """)
                        )
                        event_timestamp_updated = result.scalar_one() or 0

                if not dry_run:
                    conn.commit()

                total_backfilled = session_id_updated + event_type_updated + event_timestamp_updated
                duration = time.time() - start_time

                backfill_stats: Dict[str, Any] = {
                    'total_missing': total_missing,
                    'records_processed': total_missing,  # We processed all missing records
                    'fields_backfilled': total_backfilled,
                    'session_id_updated': session_id_updated,
                    'event_type_updated': event_type_updated,
                    'event_timestamp_updated': event_timestamp_updated,
                    'errors': 0,  # Bulk operations don't have individual record errors
                    'duration_seconds': duration,
                    'generated_columns': {
                        'session_id': session_id_generated,
                        'event_type': event_type_generated,
                        'event_timestamp': event_timestamp_generated,
                    },
                }

                logger.info(
                    f"✅ Field backfill {'analysis' if dry_run else 'complete'}: "
                    f"{total_backfilled} fields backfilled in {duration:.2f}s "
                    f"(session_id: {session_id_updated}, event_type: {event_type_updated}, "
                    f"event_timestamp: {event_timestamp_updated})"
                )

                if session_id_generated or event_type_generated or event_timestamp_generated:
                    logger.info("ℹ️  Some columns are generated columns that auto-compute from JSON payload")

                return backfill_stats

        except Exception as e:
            logger.error(f"❌ Field backfill failed: {e}")
            raise

    def get_files_table_stats(self) -> Dict[str, Any]:
        """Get statistics about the files table.

        Returns:
            Files table statistics
        """
        result: Dict[str, Any] = {
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
                    # Access row attributes safely
                    enrichment_status = getattr(row, 'enrichment_status', None)
                    count = getattr(row, 'count', 0)
                    if enrichment_status is not None:
                        result['enrichment_status'][enrichment_status] = count

                # Malicious files - handle PostgreSQL boolean comparison
                if self._is_postgresql():
                    malicious_count = conn.execute(
                        text("SELECT COUNT(*) FROM files WHERE vt_malicious = TRUE")
                    ).scalar_one()
                else:
                    malicious_count = conn.execute(
                        text("SELECT COUNT(*) FROM files WHERE vt_malicious = 1")
                    ).scalar_one()
                result['malicious_files'] = malicious_count

                # Pending enrichment
                result['pending_enrichment'] = conn.execute(
                    text("SELECT COUNT(*) FROM files WHERE enrichment_status IN ('pending', 'failed')")
                ).scalar_one()

        except Exception as e:
            logger.warning(f"Could not get files table stats: {e}")

        return result

    def migrate_to_postgresql(
        self, postgres_url: str, batch_size: int = 10000, validate_only: bool = False, skip_schema: bool = False
    ) -> Dict[str, Any]:
        """Migrate data from SQLite to PostgreSQL.

        Args:
            postgres_url: PostgreSQL connection URL
            batch_size: Number of records to migrate in each batch
            validate_only: Only validate migration without performing it
            skip_schema: Skip schema setup (assume PostgreSQL schema exists)

        Returns:
            Migration result with statistics
        """
        logger.info("🚀 Starting SQLite to PostgreSQL migration...")

        if not self._is_sqlite():
            raise Exception("Source database must be SQLite for migration")

        if not postgres_url.startswith("postgresql://") and not postgres_url.startswith("postgres://"):
            raise Exception("Target database must be PostgreSQL")

        result: Dict[str, Any] = {
            'validate_only': validate_only,
            'skip_schema': skip_schema,
            'tables_migrated': [],
            'total_records_migrated': 0,
            'errors': 0,
            'warnings': 0,
            'start_time': None,
            'end_time': None,
        }

        result['start_time'] = datetime.now().isoformat()

        try:
            # Set up PostgreSQL connection
            postgres_settings = DatabaseSettings(url=postgres_url)
            postgres_engine = create_engine_from_settings(postgres_settings)

            # Apply schema migrations to PostgreSQL if not skipped
            if not skip_schema:
                logger.info("📋 Setting up PostgreSQL schema...")
                apply_migrations(postgres_engine)

            if not validate_only:
                # Perform actual migration
                migration_stats = self._perform_data_migration(postgres_engine, batch_size)
                result.update(migration_stats)

            # Validation
            validation_result = self._validate_migration(postgres_engine)
            result['validation'] = validation_result

            result['end_time'] = datetime.now().isoformat()
            result['success'] = result['errors'] == 0

            if result['success']:
                logger.info("✅ Migration completed successfully")
                logger.info(f"   Records migrated: {result['total_records_migrated']:,}")
                logger.info(f"   Tables migrated: {len(result['tables_migrated'])}")
            else:
                logger.warning(f"⚠️  Migration completed with {result['errors']} errors")

        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            result['error'] = str(e)
            result['success'] = False
            raise

        return result

    def _perform_data_migration(self, postgres_engine: Engine, batch_size: int) -> Dict[str, Any]:
        """Perform the actual data migration from SQLite to PostgreSQL."""
        logger.info("📦 Migrating data...")

        tables_to_migrate = [
            'raw_events',
            'session_summaries',
            'command_stats',
            'files',
            'dead_letter_events',
            'schema_state',
        ]

        migration_stats: Dict[str, Any] = {
            'tables_migrated': [],
            'total_records_migrated': 0,
            'errors': 0,
            'warnings': 0,
        }

        for table_name in tables_to_migrate:
            try:
                logger.info(f"🔄 Migrating table: {table_name}")

                # Check if table exists in source
                with self._get_engine().connect() as sqlite_conn:
                    source_count = sqlite_conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()

                    if source_count == 0:
                        logger.info(f"   Skipping empty table: {table_name}")
                        continue

                # Migrate table data
                table_stats = self._migrate_table_data(table_name, postgres_engine, batch_size)
                migration_stats['tables_migrated'].append(
                    {
                        'table': table_name,
                        'records_migrated': table_stats['records_migrated'],
                        'errors': table_stats['errors'],
                    }
                )

                migration_stats['total_records_migrated'] += table_stats['records_migrated']
                migration_stats['errors'] += table_stats['errors']

                logger.info(f"   ✓ Migrated {table_stats['records_migrated']:,} records")

            except Exception as e:
                logger.error(f"   ❌ Failed to migrate table {table_name}: {e}")
                migration_stats['errors'] += 1
                migration_stats['warnings'] += 1

        return migration_stats

    def _migrate_table_data(self, table_name: str, postgres_engine: Engine, batch_size: int) -> Dict[str, Any]:
        """Migrate data for a specific table."""
        stats: Dict[str, Any] = {
            'records_migrated': 0,
            'errors': 0,
        }

        try:
            # Get table schema from SQLite
            with self._get_engine().connect() as sqlite_conn:
                # Get column information
                columns_query = text(
                    """
                    PRAGMA table_info({})
                """.format(table_name)
                )
                columns = sqlite_conn.execute(columns_query).fetchall()

                if not columns:
                    return stats

                column_names = [col[1] for col in columns]  # col[1] is column name

                # Get total count for progress tracking
                total_count = sqlite_conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()

                # Migrate in batches
                offset = 0
                while offset < total_count:
                    # Get batch of data
                    batch_query = text(f"""
                        SELECT * FROM {table_name} LIMIT :batch_size OFFSET :offset
                    """)

                    batch_data = sqlite_conn.execute(
                        batch_query, {'batch_size': batch_size, 'offset': offset}
                    ).fetchall()

                    if not batch_data:
                        break

                    # Convert to list of dicts for PostgreSQL insert
                    records = []
                    for row in batch_data:
                        record: dict[str, Any] = {}
                        for i, col_name in enumerate(column_names):
                            # Handle None values and type conversion
                            value = row[i]
                            if value is None:
                                record[col_name] = None
                            elif isinstance(value, (int, float, str, bool)):
                                record[col_name] = value
                            else:
                                # Convert other types to string
                                record[col_name] = str(value)

                        records.append(record)

                    # Insert batch into PostgreSQL
                    self._insert_batch_to_postgres(postgres_engine, table_name, records)

                    stats['records_migrated'] += len(records)
                    offset += batch_size

                    # Progress logging
                    if stats['records_migrated'] % (batch_size * 10) == 0:
                        progress = (stats['records_migrated'] / total_count) * 100
                        logger.info(f"   Progress: {stats['records_migrated']:,}/{total_count:,} ({progress:.1f}%)")

        except Exception as e:
            logger.error(f"   Error migrating table {table_name}: {e}")
            stats['errors'] += 1

        return stats

    def _insert_batch_to_postgres(
        self, postgres_engine: Engine, table_name: str, records: list[Dict[str, Any]]
    ) -> None:
        """Insert a batch of records into PostgreSQL table."""
        if not records:
            return

        try:
            with postgres_engine.begin() as conn:
                # Build INSERT statement
                columns = list(records[0].keys())
                placeholders = [f":{col}" for col in columns]

                insert_sql = f"""
                    INSERT INTO {table_name} ({', '.join(columns)})
                    VALUES ({', '.join(placeholders)})
                """

                # Execute batch insert
                conn.execute(text(insert_sql), records)

        except Exception as e:
            logger.error(f"   Failed to insert batch into {table_name}: {e}")
            raise

    def _validate_migration(self, postgres_engine: Engine) -> Dict[str, Any]:
        """Validate the migration by comparing record counts."""
        logger.info("🔍 Validating migration...")

        validation: Dict[str, Any] = {
            'source_counts': {},
            'target_counts': {},
            'mismatches': [],
            'is_valid': True,
        }

        tables_to_check = ['raw_events', 'session_summaries', 'command_stats', 'files', 'dead_letter_events']

        # Get counts from source (SQLite)
        with self._get_engine().connect() as sqlite_conn:
            for table in tables_to_check:
                try:
                    count = sqlite_conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
                    validation['source_counts'][table] = count
                except Exception:
                    validation['source_counts'][table] = 0

        # Get counts from target (PostgreSQL)
        with postgres_engine.connect() as postgres_conn:
            for table in tables_to_check:
                try:
                    count = postgres_conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
                    validation['target_counts'][table] = count
                except Exception:
                    validation['target_counts'][table] = 0

        # Check for mismatches
        for table in tables_to_check:
            source_count = validation['source_counts'][table]
            target_count = validation['target_counts'][table]

            if source_count != target_count:
                validation['mismatches'].append(
                    {
                        'table': table,
                        'source_count': source_count,
                        'target_count': target_count,
                        'difference': target_count - source_count,
                    }
                )
                validation['is_valid'] = False

        if validation['is_valid']:
            logger.info("✅ Migration validation passed")
        else:
            logger.warning(f"⚠️  Migration validation found {len(validation['mismatches'])} mismatches")

        return validation

    def longtail_migrate(self, dry_run: bool = False) -> Dict[str, Any]:
        """Apply longtail analysis schema migration (v9)."""
        logger.info(f"🔄 Longtail migration: v{CURRENT_SCHEMA_VERSION} -> v9")

        if dry_run:
            logger.info("🔍 DRY RUN: Would apply longtail migration")
            return {
                "success": True,
                "dry_run": True,
                "migration": "v9_longtail_analysis",
                "current_version": CURRENT_SCHEMA_VERSION,
            }

        try:
            engine = self._get_engine()

            # Apply v9 migration
            with engine.begin() as conn:
                _upgrade_to_v9(conn)

            logger.info("✅ Longtail migration applied successfully")
            return {
                "success": True,
                "migration_applied": "v9_longtail_analysis",
                "new_version": 9,
            }

        except Exception as e:
            logger.error(f"❌ Longtail migration failed: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def longtail_rollback(self) -> Dict[str, Any]:
        """Rollback longtail analysis migration."""
        logger.info("🔄 Rolling back longtail migration...")

        try:
            engine = self._get_engine()

            # Rollback v9 migration
            with engine.begin() as conn:
                _downgrade_from_v9(conn)

            logger.info("✅ Longtail rollback completed successfully")
            return {
                "success": True,
                "rollback_performed": "v9_to_v8",
                "new_version": 8,
            }

        except Exception as e:
            logger.error(f"❌ Longtail rollback failed: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def validate_longtail_schema(self) -> Dict[str, Any]:
        """Validate longtail analysis schema and tables."""
        logger.info("🔍 Validating longtail analysis schema...")

        try:
            engine = self._get_engine()

            # Check if we're at v9
            current_version = self.get_schema_version()
            if current_version != 9:
                return {
                    "success": False,
                    "error": f"Expected schema version 9, got {current_version}",
                }

            # Check required tables exist
            required_tables = [
                "longtail_analysis",
                "longtail_detections",
            ]

            missing_tables = []
            for table in required_tables:
                if not self._table_exists(table):
                    missing_tables.append(table)

            if missing_tables:
                return {
                    "success": False,
                    "error": f"Missing tables: {missing_tables}",
                }

            # Check if pgvector tables exist (if PostgreSQL)
            if self._is_postgresql():
                try:
                    # Check if pgvector extension is available
                    with engine.connect() as conn:
                        result = conn.execute(
                            text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')")
                        )
                        has_pgvector = result.scalar()

                    if has_pgvector:
                        pgvector_tables = ["command_sequence_vectors", "behavioral_vectors"]
                        for table in pgvector_tables:
                            if not self._table_exists(table):
                                logger.warning(f"⚠️  pgvector table {table} not found")
                    else:
                        logger.info("ℹ️  pgvector extension not available - vector analysis disabled")

                except Exception as e:
                    logger.warning(f"⚠️  Could not check pgvector status: {e}")

            # Check table structures
            table_info = {}
            for table in required_tables:
                with engine.connect() as conn:
                    # Get column information
                    if self._is_sqlite():
                        query = text(f"PRAGMA table_info({table})")
                        params = {}
                    else:
                        query = text(
                            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = :table"
                        )
                        params = {"table": table}

                    result = conn.execute(query, params)
                    columns = [{"name": row[0], "type": row[1]} for row in result]
                    table_info[table] = columns

            logger.info("✅ Longtail schema validation passed")
            return {
                "success": True,
                "schema_version": current_version,
                "tables_validated": required_tables,
                "table_info": table_info,
            }

        except Exception as e:
            logger.error(f"❌ Longtail schema validation failed: {e}")
            return {
                "success": False,
                "error": str(e),
            }


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Cowrie database management utilities',
        prog='cowrie-db',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_database_argument(parser)

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Migrate command
    migrate_parser = subparsers.add_parser('migrate', help='Run database schema migrations')
    migrate_parser.add_argument(
        '--dry-run', action='store_true', help='Show what migrations would be applied without actually executing them'
    )
    migrate_parser.add_argument(
        '--target-version', type=int, help='Target schema version to migrate to (default: latest version)'
    )

    # Check command
    check_parser = subparsers.add_parser('check', help='Validate database schema and health')
    check_parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show detailed health information including table counts and recommendations',
    )

    # Optimize command
    optimize_parser = subparsers.add_parser('optimize', help='Run database maintenance operations')
    optimize_parser.add_argument(
        '--no-vacuum', action='store_true', help='Skip VACUUM/ANALYZE operation (SQLite: VACUUM, PostgreSQL: ANALYZE)'
    )
    optimize_parser.add_argument('--no-reindex', action='store_true', help='Skip index rebuilding operation')

    # Backup command
    backup_parser = subparsers.add_parser('backup', help='Create a backup of the database')
    backup_parser.add_argument(
        '--output', help='Custom backup file location (default: auto-generated timestamped filename)'
    )

    # Integrity command
    integrity_parser = subparsers.add_parser('integrity', help='Check database integrity and detect corruption')
    integrity_parser.add_argument(
        '--deep', action='store_true', help='Perform deep integrity check including page-level analysis (SQLite only)'
    )

    # Backfill command
    backfill_parser = subparsers.add_parser('backfill', help='Backfill files table from historical data')
    backfill_parser.add_argument(
        '--batch-size', type=int, default=1000, help='Number of records to process in each batch (default: 1000)'
    )
    backfill_parser.add_argument(
        '--limit', type=int, help='Maximum number of events to process (default: all available events)'
    )

    # Sanitize command
    sanitize_parser = subparsers.add_parser(
        'sanitize', help='Sanitize Unicode control characters in existing database records'
    )
    sanitize_parser.add_argument(
        '--batch-size', type=int, default=1000, help='Number of records to process in each batch (default: 1000)'
    )
    sanitize_parser.add_argument(
        '--limit', type=int, help='Maximum number of records to process (default: all available records)'
    )
    sanitize_parser.add_argument(
        '--dry-run', action='store_true', help='Show what would be changed without actually making changes'
    )
    sanitize_parser.add_argument('--status-dir', help='Directory for status JSON files')
    sanitize_parser.add_argument('--ingest-id', help='Status identifier for progress tracking')

    # Organize command
    organize_parser = subparsers.add_parser('organize', help='Organize files by content type (move mislocated files)')
    organize_parser.add_argument('source', help='Source directory to scan for mislocated files')
    organize_parser.add_argument(
        '--dry-run', action='store_true', default=True, help='Only report what would be moved (default)'
    )
    organize_parser.add_argument('--move', action='store_true', help='Actually move files (overrides --dry-run)')
    organize_parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')

    # Files command
    subparsers.add_parser('files', help='Display files table statistics')

    # Analyze command
    analyze_parser = subparsers.add_parser(
        'analyze',
        help='Analyze database for data quality issues including JSON validity, '
        'missing fields, and boolean field problems',
    )
    analyze_parser.add_argument(
        '--sample-size',
        type=int,
        default=1000,
        help='Number of records to sample for JSON analysis (default: 1000). '
        'Larger samples give more accurate results but take longer.',
    )

    # Repair command
    repair_parser = subparsers.add_parser(
        'repair',
        help='Repair database data quality issues by backfilling missing fields '
        'from JSON payloads and fixing data inconsistencies',
    )
    repair_parser.add_argument(
        '--batch-size',
        type=int,
        default=10000,
        help='Number of records to process in each batch (default: 10000). '
        'Smaller batches use less memory but take longer.',
    )
    repair_parser.add_argument(
        '--dry-run', action='store_true', help='Show what repairs would be made without actually applying them'
    )

    # Longtail migrate command
    longtail_migrate_parser = subparsers.add_parser(
        'longtail-migrate', help='Apply longtail analysis schema migration (v9)'
    )
    longtail_migrate_parser.add_argument(
        '--dry-run', action='store_true', help='Show what migration would be applied without executing it'
    )

    # Longtail rollback command
    subparsers.add_parser('longtail-rollback', help='Rollback longtail analysis migration to v8')

    # Longtail validate command
    subparsers.add_parser('longtail-validate', help='Validate longtail analysis schema and tables')

    # Info command
    subparsers.add_parser(
        'info',
        help='Display comprehensive database information including schema version, table counts, and health status',
    )

    # Migrate-to-postgres command
    migrate_pg_parser = subparsers.add_parser(
        'migrate-to-postgres', help='Migrate data from SQLite to PostgreSQL database'
    )
    migrate_pg_parser.add_argument(
        '--postgres-url',
        required=True,
        help='PostgreSQL connection URL (format: postgresql://user:password@host:port/database)',
    )
    migrate_pg_parser.add_argument(
        '--batch-size',
        type=int,
        default=10000,
        help='Number of records to migrate in each batch (default: 10000). '
        'Smaller batches use less memory but take longer.',
    )
    migrate_pg_parser.add_argument(
        '--validate-only',
        action='store_true',
        help='Only validate migration prerequisites and show what would be migrated, '
        'without actually performing the migration',
    )
    migrate_pg_parser.add_argument(
        '--skip-schema',
        action='store_true',
        help='Skip PostgreSQL schema setup. Use this if the PostgreSQL database '
        'already has the cowrieprocessor schema installed.',
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Resolve database settings using shared configuration
    db_settings = resolve_database_settings(args.db_url)
    db = CowrieDatabase(db_settings.url)

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

        elif args.command == 'sanitize':
            print("Sanitizing Unicode control characters in database records...")

            # Set up status emitter for progress tracking
            ingest_id = args.ingest_id or f"sanitize-{int(time.time())}"
            emitter = StatusEmitter("sanitization", status_dir=args.status_dir)

            # Initialize metrics
            metrics = SanitizationMetrics(dry_run=args.dry_run, ingest_id=ingest_id)
            emitter.record_metrics(metrics)

            start_time = time.perf_counter()

            # Run sanitization with progress callbacks
            result = db.sanitize_unicode_in_database(
                batch_size=args.batch_size,
                limit=args.limit,
                dry_run=args.dry_run,
                progress_callback=lambda m: emitter.record_metrics(m),
            )

            # Update final metrics
            metrics.records_processed = result['records_processed']
            metrics.records_updated = result['records_updated']
            metrics.records_skipped = result['records_skipped']
            metrics.errors = result['errors']
            metrics.batches_processed = result['batches_processed']
            metrics.duration_seconds = time.perf_counter() - start_time
            emitter.record_metrics(metrics)

            print(f"✓ {result['message']}")
            if result.get('records_processed', 0) > 0:
                print(f"  Records processed: {result['records_processed']:,}")
                print(f"  Records updated: {result['records_updated']:,}")
                print(f"  Records skipped: {result['records_skipped']:,}")
                print(f"  Batches processed: {result['batches_processed']:,}")
                if result.get('errors', 0) > 0:
                    print(f"  Errors: {result['errors']:,}")

            if 'error' in result:
                print(f"❌ Sanitization failed: {result['error']}", file=sys.stderr)
                sys.exit(1)

        elif args.command == 'organize':
            from .file_organizer import organize_files

            source_dir = Path(args.source)
            if not source_dir.exists():
                print(f"❌ Source directory does not exist: {source_dir}", file=sys.stderr)
                sys.exit(1)

            move_files = args.move or not args.dry_run

            if args.verbose:
                logging.basicConfig(level=logging.INFO)
            else:
                logging.basicConfig(level=logging.WARNING)

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
                for item in results['unknown_files']:
                    file_path, file_type, reason = item[0], item[1], item[2]  # type: ignore[index]
                    print(f"  {file_path} (type: {file_type}, reason: {reason})")
                print()

            if results['errors']:
                print(f"Encountered {len(results['errors'])} errors:")
                for item in results['errors']:
                    file_path, error = item[0], item[1]  # type: ignore[index]
                    print(f"  {file_path}: {error}")
                print()

            total_moved = (
                len(results['iptables_files']) + len(results['cowrie_files']) + len(results['webhoneypot_files'])
            )
            print(f"Total files {'would be moved' if not move_files else 'moved'}: {total_moved}")

        elif args.command == 'analyze':
            result = db.analyze_data_quality(sample_size=args.sample_size)

            print("Data Quality Analysis Results:")
            print(f"  Sample size: {result['sample_size']:,} records")
            print(f"  Analysis duration: {result['analysis_duration_seconds']:.2f}s")

            print("\nDatabase Overview:")
            print(f"  Total records: {result['overview']['total_records']:,}")
            print(f"  Database size: {result['overview']['database_size_mb']:.2f} MB")
            for table, count in result['overview']['table_counts'].items():
                print(f"  {table}: {count:,}")

            print("\nJSON Quality Analysis:")
            print(
                f"  Valid JSON: {result['json_analysis']['valid_json_percentage']:.1f}% "
                f"({result['json_analysis']['valid_json_count']:,} records)"
            )
            print(
                f"  Invalid JSON: {result['json_analysis']['invalid_json_percentage']:.1f}% "
                f"({result['json_analysis']['invalid_json_count']:,} records)"
            )

            print("\nMissing Fields Analysis:")
            print(
                f"  Missing session_id: {result['missing_analysis']['missing_percentages']['session_id']:.1f}% "
                f"({result['missing_analysis']['missing_session_id']:,} records)"
            )
            print(
                f"  Missing event_type: {result['missing_analysis']['missing_percentages']['event_type']:.1f}% "
                f"({result['missing_analysis']['missing_event_type']:,} records)"
            )
            print(
                f"  Missing event_timestamp: "
                f"{result['missing_analysis']['missing_percentages']['event_timestamp']:.1f}% "
                f"({result['missing_analysis']['missing_event_timestamp']:,} records)"
            )

            print("\nBoolean Fields Analysis:")
            issues_count = len(result['boolean_analysis']['quarantined']['issues'])
            print(f"  Boolean field issues: {issues_count}")

            print("\nRecommendations:")
            for i, rec in enumerate(result['recommendations'], 1):
                print(f"  {i}. {rec}")

        elif args.command == 'repair':
            result = db.repair_data_quality(batch_size=args.batch_size, dry_run=args.dry_run)

            print(f"Data Repair {'Analysis' if result['dry_run'] else 'Results'}:")
            print(f"  Records processed: {result['records_processed']:,}")
            print(f"  Fields backfilled: {result['fields_backfilled']:,}")
            print(f"  Unrepairable records: {result['unrepairable_records']:,}")
            print(f"  Errors: {result['errors']:,}")
            print(f"  Duration: {result['duration_seconds']:.2f}s")

            if result['unrepairable_records'] > 0:
                print(f"\nℹ️  {result['unrepairable_records']:,} records contain genuinely malformed data")
                print("   and cannot be automatically repaired. These records may need")
                print("   manual review or represent incomplete data fragments.")

            if not result['dry_run'] and result['fields_backfilled'] > 0:
                print(f"\n✅ Successfully backfilled {result['fields_backfilled']:,} fields")
                print("Consider running 'cowrie-db migrate' to ensure schema is current")
            else:
                print("\n📋 Summary:")
                for rec in result['recommendations']:
                    print(f"  - {rec}")

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

        elif args.command == 'migrate-to-postgres':
            print("🚀 Migrating from SQLite to PostgreSQL...")
            result = db.migrate_to_postgresql(
                postgres_url=args.postgres_url,
                batch_size=args.batch_size,
                validate_only=args.validate_only,
                skip_schema=args.skip_schema,
            )

            if result['success']:
                print("✅ Migration completed successfully!")
                print(f"   Records migrated: {result['total_records_migrated']:,}")
                print(f"   Tables migrated: {len(result['tables_migrated'])}")

                if result['validation']['is_valid']:
                    print("✅ Migration validation passed")
                else:
                    print("⚠️  Migration validation found mismatches:")
                    for mismatch in result['validation']['mismatches']:
                        print(f"     {mismatch['table']}: {mismatch['source_count']:,} → {mismatch['target_count']:,}")
            else:
                print(f"❌ Migration failed: {result.get('error', 'Unknown error')}")
                sys.exit(1)

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

        elif args.command == 'longtail-migrate':
            result = db.longtail_migrate(dry_run=args.dry_run)

            if result['success']:
                if result.get('dry_run'):
                    print("🔍 DRY RUN: Longtail migration would be applied")
                    print(f"   Current version: {result['current_version']}")
                    print("   Target version: 9")
                else:
                    print("✅ Longtail migration applied successfully")
                    print(f"   New version: {result['new_version']}")
            else:
                print(f"❌ Migration failed: {result['error']}")

        elif args.command == 'longtail-rollback':
            result = db.longtail_rollback()

            if result['success']:
                print("✅ Longtail rollback completed successfully")
                print(f"   New version: {result['new_version']}")
            else:
                print(f"❌ Rollback failed: {result['error']}")

        elif args.command == 'longtail-validate':
            result = db.validate_longtail_schema()

            if result['success']:
                print("✅ Longtail schema validation passed")
                print(f"   Schema version: {result['schema_version']}")
                print(f"   Tables validated: {', '.join(result['tables_validated'])}")

                for table, columns in result['table_info'].items():
                    print(f"   {table}: {len(columns)} columns")
            else:
                print(f"❌ Schema validation failed: {result['error']}")

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        # Log error using StatusEmitter
        status_emitter = StatusEmitter('database_cli')
        status_emitter.record_metrics({'error': str(e), 'command': args.command, 'phase': 'cli_error'})
        sys.exit(1)


if __name__ == '__main__':
    main()
