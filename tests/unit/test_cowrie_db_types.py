"""Unit tests for cowrie_db.py type safety and SQLAlchemy 2.0 compatibility."""

from unittest.mock import Mock, patch

from cowrieprocessor.cli.cowrie_db import CowrieDatabase, SanitizationMetrics


class TestCowrieDatabaseTypes:
    """Test type safety and SQLAlchemy 2.0 compatibility for CowrieDatabase."""

    def test_database_initialization_types(self):
        """Test that database initialization has correct types."""
        db = CowrieDatabase("sqlite:///test.db")

        # Test that attributes have correct types
        assert isinstance(db.db_url, str)
        assert db._engine is None
        assert db._session_maker is None

    def test_get_engine_return_type(self):
        """Test that _get_engine returns proper Engine type."""
        with patch('cowrieprocessor.cli.cowrie_db.create_engine_from_settings') as mock_create:
            mock_engine = Mock()
            mock_create.return_value = mock_engine

            db = CowrieDatabase("sqlite:///test.db")
            engine = db._get_engine()

            assert engine is mock_engine
            mock_create.assert_called_once()

    def test_get_session_return_type(self):
        """Test that _get_session returns proper Session type."""
        with patch('cowrieprocessor.cli.cowrie_db.sessionmaker') as mock_sessionmaker:
            mock_session = Mock()
            mock_sessionmaker_instance = Mock()
            mock_sessionmaker_instance.return_value = mock_session
            mock_sessionmaker.return_value = mock_sessionmaker_instance

            with patch.object(CowrieDatabase, '_get_engine') as mock_get_engine:
                mock_engine = Mock()
                mock_get_engine.return_value = mock_engine

                db = CowrieDatabase("sqlite:///test.db")
                session = db._get_session()

                assert session is mock_session
                mock_sessionmaker.assert_called_once_with(bind=mock_engine, future=True)

    def test_database_type_detection(self):
        """Test database type detection methods."""
        sqlite_db = CowrieDatabase("sqlite:///test.db")
        postgres_db = CowrieDatabase("postgresql://user:pass@host/db")

        assert sqlite_db._is_sqlite() is True
        assert sqlite_db._is_postgresql() is False

        assert postgres_db._is_sqlite() is False
        assert postgres_db._is_postgresql() is True

    def test_table_exists_return_type(self):
        """Test that _table_exists returns proper bool type."""
        with patch.object(CowrieDatabase, '_get_engine') as mock_get_engine:
            mock_engine = Mock()
            mock_connection = Mock()
            mock_engine.connect.return_value.__enter__.return_value = mock_connection
            mock_get_engine.return_value = mock_engine

            with patch.object(CowrieDatabase, '_is_sqlite', return_value=True):
                mock_connection.execute.return_value.fetchone.return_value = ("test_table",)

                db = CowrieDatabase("sqlite:///test.db")
                result = db._table_exists("test_table")

                assert isinstance(result, bool)
                assert result is True

    def test_table_exists_not_found(self):
        """Test _table_exists returns False for non-existent table."""
        with patch.object(CowrieDatabase, '_get_engine') as mock_get_engine:
            mock_engine = Mock()
            mock_connection = Mock()
            mock_engine.connect.return_value.__enter__.return_value = mock_connection
            mock_get_engine.return_value = mock_engine

            with patch.object(CowrieDatabase, '_is_sqlite', return_value=True):
                mock_connection.execute.return_value.fetchone.return_value = None

                db = CowrieDatabase("sqlite:///test.db")
                result = db._table_exists("nonexistent_table")

                assert isinstance(result, bool)
                assert result is False

    def test_sanitization_metrics_types(self):
        """Test SanitizationMetrics dataclass types."""
        metrics = SanitizationMetrics()

        assert isinstance(metrics.records_processed, int)
        assert isinstance(metrics.records_updated, int)
        assert isinstance(metrics.records_skipped, int)
        assert isinstance(metrics.errors, int)
        assert isinstance(metrics.batches_processed, int)
        assert isinstance(metrics.duration_seconds, float)
        assert isinstance(metrics.dry_run, bool)
        assert metrics.ingest_id is None

    def test_sanitization_metrics_with_values(self):
        """Test SanitizationMetrics with specific values."""
        metrics = SanitizationMetrics(
            records_processed=100,
            records_updated=50,
            records_skipped=25,
            errors=2,
            batches_processed=5,
            duration_seconds=10.5,
            dry_run=False,
            ingest_id="test-123",
        )

        assert metrics.records_processed == 100
        assert metrics.records_updated == 50
        assert metrics.records_skipped == 25
        assert metrics.errors == 2
        assert metrics.batches_processed == 5
        assert metrics.duration_seconds == 10.5
        assert metrics.dry_run is False
        assert metrics.ingest_id == "test-123"

    def test_migrate_return_type(self):
        """Test that migrate method returns proper Dict[str, Any] type."""
        with patch.object(CowrieDatabase, '_is_sqlite', return_value=True):
            with patch('cowrieprocessor.cli.cowrie_db.Path.exists', return_value=False):
                with patch.object(CowrieDatabase, 'get_schema_version', return_value=0):
                    with patch('cowrieprocessor.cli.cowrie_db.apply_migrations') as mock_apply:
                        mock_apply.return_value = 9

                        db = CowrieDatabase("sqlite:///test.db")
                        result = db.migrate()

                        assert isinstance(result, dict)
                        assert 'current_version' in result
                        assert 'target_version' in result
                        assert 'migrations_applied' in result
                        assert 'dry_run' in result
                        assert isinstance(result['current_version'], int)
                        assert isinstance(result['target_version'], int)
                        assert isinstance(result['migrations_applied'], list)
                        assert isinstance(result['dry_run'], bool)

    def test_migrate_dry_run_return_type(self):
        """Test that migrate method with dry_run=True returns proper type."""
        with patch.object(CowrieDatabase, '_is_sqlite', return_value=True):
            with patch('cowrieprocessor.cli.cowrie_db.Path.exists', return_value=False):
                with patch.object(CowrieDatabase, 'get_schema_version', return_value=5):
                    db = CowrieDatabase("sqlite:///test.db")
                    result = db.migrate(dry_run=True)

                    assert isinstance(result, dict)
                    assert result['dry_run'] is True
                    assert 'migrations_applied' in result
                    assert isinstance(result['migrations_applied'], list)

    def test_validate_schema_return_type(self):
        """Test that validate_schema method returns proper Dict[str, Any] type."""
        with patch.object(CowrieDatabase, '_get_engine') as mock_get_engine:
            mock_engine = Mock()
            mock_connection = Mock()
            mock_engine.connect.return_value.__enter__.return_value = mock_connection
            mock_get_engine.return_value = mock_engine

            with patch.object(CowrieDatabase, 'get_schema_version', return_value=9):
                with patch.object(CowrieDatabase, '_is_sqlite', return_value=True):
                    with patch('cowrieprocessor.cli.cowrie_db.Path.exists', return_value=True):
                        with patch('cowrieprocessor.cli.cowrie_db.Path.stat') as mock_stat:
                            mock_stat.return_value.st_size = 1024 * 1024  # 1MB

                            mock_connection.execute.return_value.fetchall.return_value = [
                                ("raw_events", 1000),
                                ("session_summaries", 500),
                                ("files", 200),
                            ]

                            db = CowrieDatabase("sqlite:///test.db")
                            result = db.validate_schema()

                            assert isinstance(result, dict)
                            assert 'is_valid' in result
                            assert 'schema_version' in result
                            assert 'database_size_mb' in result
                            assert 'session_count' in result
                            assert isinstance(result['is_valid'], bool)
                            assert isinstance(result['schema_version'], int)
                            assert isinstance(result['database_size_mb'], (int, float))
                            assert isinstance(result['session_count'], int)

    def test_optimize_return_type(self):
        """Test that optimize method returns proper Dict[str, Any] type."""
        with patch.object(CowrieDatabase, '_get_engine') as mock_get_engine:
            mock_engine = Mock()
            mock_connection = Mock()
            mock_engine.connect.return_value.__enter__.return_value = mock_connection
            mock_get_engine.return_value = mock_engine

            with patch.object(CowrieDatabase, '_is_sqlite', return_value=True):
                db = CowrieDatabase("sqlite:///test.db")
                result = db.optimize()

                assert isinstance(result, dict)
                assert 'operations_performed' in result
                assert 'reclaimed_mb' in result
                assert isinstance(result['operations_performed'], list)
                assert isinstance(result['reclaimed_mb'], (int, float))

    def test_create_backup_return_type(self):
        """Test that create_backup method returns proper str type."""
        with patch.object(CowrieDatabase, '_get_engine') as mock_get_engine:
            mock_engine = Mock()
            mock_connection = Mock()
            mock_engine.connect.return_value.__enter__.return_value = mock_connection
            mock_get_engine.return_value = mock_engine

            with patch.object(CowrieDatabase, '_is_sqlite', return_value=True):
                with patch('cowrieprocessor.cli.cowrie_db.Path.exists', return_value=True):
                    with patch('cowrieprocessor.cli.cowrie_db.shutil.copy2') as mock_copy:
                        mock_copy.return_value = "/path/to/backup.db"

                        db = CowrieDatabase("sqlite:///test.db")
                        result = db.create_backup()

                        assert isinstance(result, str)
                        assert result == "/path/to/backup.db"

    def test_check_integrity_return_type(self):
        """Test that check_integrity method returns proper Dict[str, Any] type."""
        with patch.object(CowrieDatabase, '_get_engine') as mock_get_engine:
            mock_engine = Mock()
            mock_connection = Mock()
            mock_engine.connect.return_value.__enter__.return_value = mock_connection
            mock_get_engine.return_value = mock_engine

            with patch.object(CowrieDatabase, '_is_sqlite', return_value=True):
                mock_connection.execute.return_value.fetchone.return_value = ("ok",)

                db = CowrieDatabase("sqlite:///test.db")
                result = db.check_integrity()

                assert isinstance(result, dict)
                assert 'quick_check' in result
                assert 'foreign_keys' in result
                assert 'indexes' in result
                assert 'corruption_found' in result
                assert 'recommendations' in result
                assert isinstance(result['corruption_found'], bool)
                assert isinstance(result['recommendations'], list)

    def test_files_table_stats_return_type(self):
        """Test that get_files_table_stats method returns proper Dict[str, Any] type."""
        with patch.object(CowrieDatabase, '_get_engine') as mock_get_engine:
            mock_engine = Mock()
            mock_connection = Mock()
            mock_engine.connect.return_value.__enter__.return_value = mock_connection
            mock_get_engine.return_value = mock_engine

            with patch.object(CowrieDatabase, '_is_sqlite', return_value=True):
                # Mock the various queries
                mock_connection.execute.return_value.scalar_one.return_value = 1000
                mock_connection.execute.return_value.fetchall.return_value = [
                    ("pending", 500),
                    ("completed", 300),
                    ("failed", 200),
                ]

                db = CowrieDatabase("sqlite:///test.db")
                result = db.get_files_table_stats()

                assert isinstance(result, dict)
                assert 'total_files' in result
                assert 'enrichment_status' in result
                assert 'malicious_files' in result
                assert isinstance(result['total_files'], int)
                assert isinstance(result['enrichment_status'], dict)
                assert isinstance(result['malicious_files'], int)

    def test_backfill_files_table_return_type(self):
        """Test that backfill_files_table method returns proper Dict[str, Any] type."""
        with patch.object(CowrieDatabase, '_get_engine') as mock_get_engine:
            mock_engine = Mock()
            mock_connection = Mock()
            mock_engine.connect.return_value.__enter__.return_value = mock_connection
            mock_get_engine.return_value = mock_engine

            with patch.object(CowrieDatabase, '_table_exists', return_value=True):
                with patch('cowrieprocessor.cli.cowrie_db.get_dialect_name_from_engine', return_value="sqlite"):
                    mock_connection.execute.return_value.fetchall.return_value = []

                    db = CowrieDatabase("sqlite:///test.db")
                    result = db.backfill_files_table(batch_size=100, limit=1000)

                    assert isinstance(result, dict)
                    assert 'events_processed' in result
                    assert 'files_inserted' in result
                    assert 'message' in result
                    assert isinstance(result['events_processed'], int)
                    assert isinstance(result['files_inserted'], int)
                    assert isinstance(result['message'], str)

    def test_analyze_data_quality_return_type(self):
        """Test that analyze_data_quality method returns proper Dict[str, Any] type."""
        with patch.object(CowrieDatabase, '_get_engine') as mock_get_engine:
            mock_engine = Mock()
            mock_connection = Mock()
            mock_engine.connect.return_value.__enter__.return_value = mock_connection
            mock_get_engine.return_value = mock_engine

            with patch('cowrieprocessor.cli.cowrie_db.get_dialect_name_from_engine', return_value="sqlite"):
                mock_connection.execute.return_value.fetchall.return_value = []
                mock_connection.execute.return_value.scalar_one.return_value = 1000

                db = CowrieDatabase("sqlite:///test.db")
                result = db.analyze_data_quality(sample_size=100)

                assert isinstance(result, dict)
                assert 'database_overview' in result
                assert 'json_analysis' in result
                assert 'boolean_fields' in result
                assert 'missing_fields' in result
                assert 'recommendations' in result
                assert isinstance(result['database_overview'], dict)
                assert isinstance(result['json_analysis'], dict)
                assert isinstance(result['boolean_fields'], dict)
                assert isinstance(result['missing_fields'], dict)
                assert isinstance(result['recommendations'], list)

    def test_repair_data_quality_return_type(self):
        """Test that repair_data_quality method returns proper Dict[str, Any] type."""
        with patch.object(CowrieDatabase, '_get_engine') as mock_get_engine:
            mock_engine = Mock()
            mock_connection = Mock()
            mock_engine.connect.return_value.__enter__.return_value = mock_connection
            mock_get_engine.return_value = mock_engine

            with patch.object(CowrieDatabase, '_repair_missing_fields') as mock_repair:
                mock_repair.return_value = {'records_processed': 100, 'fields_backfilled': 50, 'errors': 0}

                db = CowrieDatabase("sqlite:///test.db")
                result = db.repair_data_quality(batch_size=1000, dry_run=True)

                assert isinstance(result, dict)
                assert 'dry_run' in result
                assert 'missing_fields' in result
                assert 'recommendations' in result
                assert isinstance(result['dry_run'], bool)
                assert isinstance(result['missing_fields'], dict)
                assert isinstance(result['recommendations'], list)

    def test_migrate_to_postgresql_return_type(self):
        """Test that migrate_to_postgresql method returns proper Dict[str, Any] type."""
        with patch.object(CowrieDatabase, '_get_engine') as mock_get_engine:
            mock_engine = Mock()
            mock_connection = Mock()
            mock_engine.connect.return_value.__enter__.return_value = mock_connection
            mock_get_engine.return_value = mock_engine

            with patch.object(CowrieDatabase, '_is_sqlite', return_value=True):
                with patch('cowrieprocessor.cli.cowrie_db.create_engine_from_settings') as mock_create:
                    mock_postgres_engine = Mock()
                    mock_create.return_value = mock_postgres_engine

                    with patch.object(CowrieDatabase, '_perform_data_migration') as mock_migrate:
                        mock_migrate.return_value = {
                            'total_records_migrated': 1000,
                            'tables_migrated': ['raw_events', 'session_summaries'],
                            'errors': 0,
                        }

                        with patch.object(CowrieDatabase, '_validate_migration') as mock_validate:
                            mock_validate.return_value = {'is_valid': True, 'mismatches': []}

                            db = CowrieDatabase("sqlite:///test.db")
                            result = db.migrate_to_postgresql(
                                postgres_url="postgresql://user:pass@host/db",
                                batch_size=1000,
                                validate_only=False,
                                skip_schema=False,
                            )

                            assert isinstance(result, dict)
                            assert 'success' in result
                            assert 'total_records_migrated' in result
                            assert 'tables_migrated' in result
                            assert 'errors' in result
                            assert 'validation' in result
                            assert isinstance(result['success'], bool)
                            assert isinstance(result['total_records_migrated'], int)
                            assert isinstance(result['tables_migrated'], list)
                            assert isinstance(result['errors'], int)
                            assert isinstance(result['validation'], dict)

    def test_longtail_migrate_return_type(self):
        """Test that longtail_migrate method returns proper Dict[str, Any] type."""
        with patch.object(CowrieDatabase, '_get_engine') as mock_get_engine:
            mock_engine = Mock()
            mock_connection = Mock()
            mock_engine.connect.return_value.__enter__.return_value = mock_connection
            mock_get_engine.return_value = mock_engine

            with patch.object(CowrieDatabase, 'get_schema_version', return_value=8):
                with patch('cowrieprocessor.cli.cowrie_db._upgrade_to_v9') as mock_upgrade:
                    mock_upgrade.return_value = None

                    db = CowrieDatabase("sqlite:///test.db")
                    result = db.longtail_migrate(dry_run=False)

                    assert isinstance(result, dict)
                    assert 'success' in result
                    assert 'message' in result
                    assert isinstance(result['success'], bool)
                    assert isinstance(result['message'], str)

    def test_longtail_rollback_return_type(self):
        """Test that longtail_rollback method returns proper Dict[str, Any] type."""
        with patch.object(CowrieDatabase, '_get_engine') as mock_get_engine:
            mock_engine = Mock()
            mock_connection = Mock()
            mock_engine.connect.return_value.__enter__.return_value = mock_connection
            mock_get_engine.return_value = mock_engine

            with patch.object(CowrieDatabase, 'get_schema_version', return_value=9):
                with patch('cowrieprocessor.cli.cowrie_db._downgrade_from_v9') as mock_downgrade:
                    mock_downgrade.return_value = None

                    db = CowrieDatabase("sqlite:///test.db")
                    result = db.longtail_rollback()

                    assert isinstance(result, dict)
                    assert 'success' in result
                    assert 'message' in result
                    assert isinstance(result['success'], bool)
                    assert isinstance(result['message'], str)

    def test_validate_longtail_schema_return_type(self):
        """Test that validate_longtail_schema method returns proper Dict[str, Any] type."""
        with patch.object(CowrieDatabase, '_get_engine') as mock_get_engine:
            mock_engine = Mock()
            mock_connection = Mock()
            mock_engine.connect.return_value.__enter__.return_value = mock_connection
            mock_get_engine.return_value = mock_engine

            with patch.object(CowrieDatabase, '_table_exists', return_value=True):
                with patch('cowrieprocessor.cli.cowrie_db.has_pgvector', return_value=True):
                    with patch('cowrieprocessor.cli.cowrie_db.detect_database_features') as mock_features:
                        mock_features.return_value = {'pgvector': True}

                        db = CowrieDatabase("sqlite:///test.db")
                        result = db.validate_longtail_schema()

                        assert isinstance(result, dict)
                        assert 'success' in result
                        assert 'message' in result
                        assert isinstance(result['success'], bool)
                        assert isinstance(result['message'], str)


class TestSQLAlchemy20Compatibility:
    """Test SQLAlchemy 2.0 compatibility patterns."""

    def test_no_deprecated_query_patterns(self):
        """Test that no deprecated session.query() patterns are used."""
        # This test ensures we're not using deprecated SQLAlchemy 1.x patterns
        import os

        # Read the cowrie_db.py file
        cowrie_db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'cowrieprocessor', 'cli', 'cowrie_db.py')
        with open(cowrie_db_path, 'r') as f:
            content = f.read()

        # Check for deprecated patterns (exclude test files)
        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            if 'session.query(' in line and 'test_' not in cowrie_db_path:
                assert False, f"Found deprecated session.query() pattern on line {i}: {line.strip()}"
            if '.query(' in line and 'test_' not in cowrie_db_path and 'session.query(' not in line:
                assert False, f"Found deprecated .query() pattern on line {i}: {line.strip()}"

    def test_proper_insert_patterns(self):
        """Test that proper SQLAlchemy 2.0 insert patterns are used."""
        # This test ensures we're using proper SQLAlchemy 2.0 insert patterns
        import os

        # Read the cowrie_db.py file
        cowrie_db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'cowrieprocessor', 'cli', 'cowrie_db.py')
        with open(cowrie_db_path, 'r') as f:
            content = f.read()

        # Check for proper insert patterns
        assert 'sqlite_insert(' in content, "Should use sqlite_insert for SQLite"
        assert 'postgres_insert(' in content, "Should use postgres_insert for PostgreSQL"

    def test_proper_type_annotations(self):
        """Test that proper type annotations are used."""
        # This test ensures we're using proper type annotations
        import os

        # Read the cowrie_db.py file
        cowrie_db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'cowrieprocessor', 'cli', 'cowrie_db.py')
        with open(cowrie_db_path, 'r') as f:
            content = f.read()

        # Check for proper type annotations
        assert 'from typing import' in content, "Should import typing module"
        assert 'Dict[str, Any]' in content, "Should use proper dict type annotations"
        assert 'Optional[' in content, "Should use Optional for nullable types"
        assert 'Callable[' in content, "Should use Callable for function types"

    def test_proper_imports(self):
        """Test that proper SQLAlchemy 2.0 imports are used."""
        # This test ensures we're using proper SQLAlchemy 2.0 imports
        import os

        # Read the cowrie_db.py file
        cowrie_db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'cowrieprocessor', 'cli', 'cowrie_db.py')
        with open(cowrie_db_path, 'r') as f:
            content = f.read()

        # Check for proper imports
        assert 'from sqlalchemy import Engine, Table, text' in content, "Should import Engine and Table"
        assert 'from sqlalchemy.orm import Session, sessionmaker' in content, "Should import Session and sessionmaker"
        assert 'from sqlalchemy.dialects.sqlite import insert as sqlite_insert' in content, (
            "Should import sqlite_insert"
        )
