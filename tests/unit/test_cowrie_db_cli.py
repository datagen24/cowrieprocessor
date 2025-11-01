"""Tests for the database management CLI."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from cowrieprocessor.cli.cowrie_db import CowrieDatabase


class TestCowrieDatabase:
    """Test cases for CowrieDatabase class."""

    @pytest.fixture
    def temp_db(self) -> Any:
        """Create temporary database for testing.

        Returns:
            Tuple of (db_url: str, db_path: Path) for testing
        """
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = Path(tmp.name)

        # Initialize database with basic schema
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE schema_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.execute("""
                INSERT INTO schema_state (key, value) VALUES ('schema_version', '14')
            """)
            conn.execute("""
                CREATE TABLE session_summaries (
                    session_id TEXT PRIMARY KEY,
                    first_event_at DATETIME,
                    last_event_at DATETIME,
                    event_count INTEGER NOT NULL DEFAULT 0,
                    command_count INTEGER NOT NULL DEFAULT 0,
                    file_downloads INTEGER NOT NULL DEFAULT 0,
                    login_attempts INTEGER NOT NULL DEFAULT 0,
                    vt_flagged BOOLEAN NOT NULL DEFAULT 0,
                    dshield_flagged BOOLEAN NOT NULL DEFAULT 0,
                    risk_score INTEGER,
                    matcher TEXT,
                    source_files TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                INSERT INTO session_summaries (
                    session_id, event_count, command_count, file_downloads
                ) VALUES ('test_session_1', 10, 5, 2)
            """)

            # Also create command_stats table for proper testing
            conn.execute("""
                CREATE TABLE command_stats (
                    id INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    command_normalized TEXT NOT NULL,
                    occurrences INTEGER NOT NULL DEFAULT 0,
                    first_seen DATETIME,
                    last_seen DATETIME,
                    high_risk BOOLEAN NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                INSERT INTO command_stats (session_id, command_normalized, occurrences)
                VALUES ('test_session_1', 'ls', 3)
            """)

        # Convert to SQLAlchemy URL format
        db_url = f"sqlite:///{db_path}"
        yield db_url

        # Cleanup
        if db_path.exists():
            db_path.unlink()

    def test_get_schema_version(self, temp_db) -> None:
        """Test getting schema version from database."""
        db = CowrieDatabase(temp_db)
        version = db.get_schema_version()
        assert version == 14

    def test_get_schema_version_empty_db(self) -> None:
        """Test getting schema version from non-existent database."""
        db = CowrieDatabase('sqlite:///nonexistent/path.db')
        version = db.get_schema_version()
        assert version == 0

    def test_validate_schema(self, temp_db) -> None:
        """Test schema validation."""
        db = CowrieDatabase(temp_db)
        result = db.validate_schema()

        assert result['is_valid'] is True
        assert result['schema_version'] == 14
        assert result['expected_version'] == 14  # From migrations.py CURRENT_SCHEMA_VERSION
        assert result['session_count'] == 1
        assert result['command_count'] == 1  # One command_stats record in test setup
        assert result['file_count'] == 1  # One session with file_downloads = 2
        assert 'database_size_mb' in result

    def test_migrate_dry_run(self, temp_db) -> None:
        """Test migration dry run."""
        db = CowrieDatabase(temp_db)
        result = db.migrate(dry_run=True)

        assert result['dry_run'] is True
        assert result['current_version'] == 14
        assert result['target_version'] == 14  # Already at latest (CURRENT_SCHEMA_VERSION)
        assert result['message'] == "Database already at version 14"

    def test_create_backup(self, temp_db) -> None:
        """Test database backup creation."""
        db = CowrieDatabase(temp_db)
        backup_path = db.create_backup()

        assert Path(backup_path).exists()
        assert backup_path.endswith('.sqlite')

        # Verify backup integrity
        with sqlite3.connect(backup_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM session_summaries")
            count = cursor.fetchone()[0]
            assert count == 1

    def test_create_backup_custom_path(self, temp_db) -> None:
        """Test backup creation with custom path."""
        db = CowrieDatabase(temp_db)
        # Extract path from sqlite:/// URL
        db_file_path = Path(temp_db.replace("sqlite:///", ""))
        custom_path = str(db_file_path.parent / "custom_backup.db")
        backup_path = db.create_backup(custom_path)

        assert backup_path == custom_path
        assert Path(backup_path).exists()

    def test_verify_backup_integrity_valid(self, temp_db) -> None:
        """Test backup integrity verification with valid backup."""
        db = CowrieDatabase(temp_db)
        backup_path = db.create_backup()

        assert db._verify_backup_integrity(backup_path) is True

    def test_check_integrity(self, temp_db) -> None:
        """Test database integrity check."""
        db = CowrieDatabase(temp_db)
        result = db.check_integrity()

        assert 'corruption_found' in result
        assert 'checks' in result
        assert 'recommendations' in result

        # Check that all expected checks are present
        assert 'quick_check' in result['checks']
        assert 'foreign_keys' in result['checks']
        assert 'indexes' in result['checks']

    def test_check_integrity_deep(self, temp_db) -> None:
        """Test deep integrity check."""
        db = CowrieDatabase(temp_db)
        result = db.check_integrity(deep=True)

        # Should have additional checks when deep=True
        assert 'page_integrity' in result['checks']
        assert 'cell_integrity' in result['checks']

    def test_optimize_vacuum_only(self, temp_db) -> None:
        """Test optimization with vacuum only."""
        db = CowrieDatabase(temp_db)
        result = db.optimize(vacuum=True, reindex=False)

        assert 'operations' in result
        assert 'VACUUM completed successfully' in result['operations']
        assert 'initial_size_mb' in result
        assert 'final_size_mb' in result
        assert 'reclaimed_mb' in result

    def test_optimize_reindex_only(self, temp_db) -> None:
        """Test optimization with reindex only."""
        db = CowrieDatabase(temp_db)
        result = db.optimize(vacuum=False, reindex=True)

        assert 'operations' in result
        assert any('Reindexed' in op for op in result['operations'])


class TestCowrieDatabaseCLI:
    """Test CLI functionality."""

    @pytest.fixture
    def temp_db(self) -> Any:
        """Create temporary database for CLI testing.

        Returns:
            SQLAlchemy URL string for the database
        """
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = Path(tmp.name)

        # Initialize database with basic schema
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE schema_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.execute("""
                INSERT INTO schema_state (key, value) VALUES ('schema_version', '14')
            """)

        db_url = f"sqlite:///{db_path}"
        yield db_url

        # Cleanup
        if db_path.exists():
            db_path.unlink()

    @patch('cowrieprocessor.cli.cowrie_db.CowrieDatabase')
    def test_migrate_command(self, mock_db_class, temp_db, capsys: pytest.CaptureFixture[str]) -> None:
        """Test migrate command."""
        # Mock the database
        mock_db = Mock()
        mock_db.migrate.return_value = {
            'current_version': 14,
            'target_version': 14,
            'final_version': 14,
            'message': 'Database already at version 14',
        }
        mock_db_class.return_value = mock_db

        # Import and run main function with mocked args
        from unittest.mock import patch

        from cowrieprocessor.cli.cowrie_db import main

        with patch('sys.argv', ['cowrie-db', '--db-url', temp_db, 'migrate']):
            main()

        captured = capsys.readouterr()
        assert '✓ Migrated database to schema version 14' in captured.out

    @patch('cowrieprocessor.cli.cowrie_db.CowrieDatabase')
    def test_check_command(self, mock_db_class, temp_db, capsys: pytest.CaptureFixture[str]) -> None:
        """Test check command."""
        # Mock the database
        mock_db = Mock()
        mock_db.validate_schema.return_value = {
            'is_valid': True,
            'schema_version': 14,
            'expected_version': 14,
            'database_size_mb': 10.5,
            'session_count': 100,
            'command_count': 500,
            'file_count': 25,
            'needs_optimization': False,
        }
        mock_db_class.return_value = mock_db

        # Import and run main function with mocked args
        from unittest.mock import patch

        from cowrieprocessor.cli.cowrie_db import main

        with patch('sys.argv', ['cowrie-db', '--db-url', temp_db, 'check', '--verbose']):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert 'Database schema is current (v14)' in captured.out
        assert 'Database size: 10.5 MB' in captured.out
        assert 'Total sessions: 100' in captured.out

    @patch('cowrieprocessor.cli.cowrie_db.CowrieDatabase')
    def test_backup_command(self, mock_db_class, temp_db, capsys: pytest.CaptureFixture[str]) -> None:
        """Test backup command."""
        # Mock the database
        mock_db = Mock()
        mock_db.create_backup.return_value = '/path/to/backup_20250101_120000.sqlite'
        mock_db_class.return_value = mock_db

        # Import and run main function with mocked args
        from unittest.mock import patch

        from cowrieprocessor.cli.cowrie_db import main

        with patch('sys.argv', ['cowrie-db', '--db-url', temp_db, 'backup']):
            main()

        captured = capsys.readouterr()
        assert 'Backup created' in captured.out

    @patch('cowrieprocessor.cli.cowrie_db.CowrieDatabase')
    def test_integrity_command(self, mock_db_class, temp_db, capsys: pytest.CaptureFixture[str]) -> None:
        """Test integrity command."""
        # Mock the database
        mock_db = Mock()
        mock_db.check_integrity.return_value = {
            'corruption_found': False,
            'checks': {
                'quick_check': {'is_valid': True, 'error': None},
                'foreign_keys': {'is_valid': True, 'error': None},
                'indexes': {'is_valid': True, 'error': None},
            },
            'recommendations': [],
        }
        mock_db_class.return_value = mock_db

        # Import and run main function with mocked args
        from unittest.mock import patch

        from cowrieprocessor.cli.cowrie_db import main

        with patch('sys.argv', ['cowrie-db', '--db-url', temp_db, 'integrity']):
            main()

        captured = capsys.readouterr()
        assert 'Database integrity verified' in captured.out
