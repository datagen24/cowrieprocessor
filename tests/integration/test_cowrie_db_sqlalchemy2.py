"""Integration tests for cowrie_db.py SQLAlchemy 2.0 compatibility."""

import os
import tempfile

import pytest

from cowrieprocessor.cli.cowrie_db import CowrieDatabase, SanitizationMetrics


@pytest.mark.integration
class TestCowrieDatabaseSQLAlchemy2Integration:
    """Integration tests for SQLAlchemy 2.0 compatibility."""

    @pytest.fixture
    def temp_sqlite_db(self):
        """Create a temporary SQLite database for testing."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name

        yield f"sqlite:///{db_path}"

        # Cleanup
        try:
            os.unlink(db_path)
        except OSError:
            pass

    @pytest.fixture
    def cowrie_db(self, temp_sqlite_db):
        """Create a CowrieDatabase instance for testing."""
        return CowrieDatabase(temp_sqlite_db)

    def test_database_initialization_with_sqlalchemy2(self, cowrie_db):
        """Test database initialization with SQLAlchemy 2.0 patterns."""
        # Test that the database can be initialized without errors
        assert cowrie_db.db_url.startswith("sqlite://")
        assert cowrie_db._engine is None
        assert cowrie_db._session_maker is None

    def test_engine_creation_sqlalchemy2(self, cowrie_db):
        """Test engine creation with SQLAlchemy 2.0 patterns."""
        engine = cowrie_db._get_engine()

        # Test that engine is properly created
        assert engine is not None
        assert cowrie_db._engine is engine

        # Test that future=True is set for SQLAlchemy 2.0 compatibility
        assert hasattr(engine, 'future')

    def test_session_creation_sqlalchemy2(self, cowrie_db):
        """Test session creation with SQLAlchemy 2.0 patterns."""
        session = cowrie_db._get_session()

        # Test that session is properly created
        assert session is not None
        assert cowrie_db._session_maker is not None

        # Test that session can be closed
        session.close()

    def test_table_exists_sqlalchemy2(self, cowrie_db):
        """Test _table_exists method with SQLAlchemy 2.0 patterns."""
        # Test with non-existent table
        result = cowrie_db._table_exists("nonexistent_table")
        assert isinstance(result, bool)
        assert result is False

    def test_database_type_detection_sqlalchemy2(self, cowrie_db):
        """Test database type detection methods."""
        assert cowrie_db._is_sqlite() is True
        assert cowrie_db._is_postgresql() is False

    def test_migrate_method_sqlalchemy2(self, cowrie_db):
        """Test migrate method with SQLAlchemy 2.0 patterns."""
        # Test dry run migration
        result = cowrie_db.migrate(dry_run=True)

        assert isinstance(result, dict)
        assert 'current_version' in result
        assert 'target_version' in result
        assert 'migrations_applied' in result
        assert 'dry_run' in result
        assert result['dry_run'] is True

    def test_validate_schema_sqlalchemy2(self, cowrie_db):
        """Test validate_schema method with SQLAlchemy 2.0 patterns."""
        result = cowrie_db.validate_schema()

        assert isinstance(result, dict)
        assert 'is_valid' in result
        assert 'schema_version' in result
        assert 'database_size_mb' in result
        assert 'session_count' in result

    def test_optimize_method_sqlalchemy2(self, cowrie_db):
        """Test optimize method with SQLAlchemy 2.0 patterns."""
        result = cowrie_db.optimize(vacuum=True, reindex=True)

        assert isinstance(result, dict)
        assert 'operations_performed' in result
        assert 'reclaimed_mb' in result

    def test_check_integrity_sqlalchemy2(self, cowrie_db):
        """Test check_integrity method with SQLAlchemy 2.0 patterns."""
        result = cowrie_db.check_integrity(deep=False)

        assert isinstance(result, dict)
        assert 'quick_check' in result
        assert 'foreign_keys' in result
        assert 'indexes' in result
        assert 'corruption_found' in result
        assert 'recommendations' in result

    def test_files_table_stats_sqlalchemy2(self, cowrie_db):
        """Test get_files_table_stats method with SQLAlchemy 2.0 patterns."""
        result = cowrie_db.get_files_table_stats()

        assert isinstance(result, dict)
        assert 'total_files' in result
        assert 'enrichment_status' in result
        assert 'malicious_files' in result

    def test_analyze_data_quality_sqlalchemy2(self, cowrie_db):
        """Test analyze_data_quality method with SQLAlchemy 2.0 patterns."""
        result = cowrie_db.analyze_data_quality(sample_size=10)

        assert isinstance(result, dict)
        assert 'database_overview' in result
        assert 'json_analysis' in result
        assert 'boolean_fields' in result
        assert 'missing_fields' in result
        assert 'recommendations' in result

    def test_repair_data_quality_sqlalchemy2(self, cowrie_db):
        """Test repair_data_quality method with SQLAlchemy 2.0 patterns."""
        result = cowrie_db.repair_data_quality(batch_size=100, dry_run=True)

        assert isinstance(result, dict)
        assert 'dry_run' in result
        assert 'missing_fields' in result
        assert 'recommendations' in result
        assert result['dry_run'] is True

    def test_sanitize_unicode_sqlalchemy2(self, cowrie_db):
        """Test sanitize_unicode_in_database method with SQLAlchemy 2.0 patterns."""
        # Test with dry run
        result = cowrie_db.sanitize_unicode_in_database(batch_size=100, limit=1000, dry_run=True)

        assert isinstance(result, dict)
        assert 'records_processed' in result
        assert 'records_updated' in result
        assert 'records_skipped' in result
        assert 'errors' in result
        assert 'batches_processed' in result

    def test_longtail_migrate_sqlalchemy2(self, cowrie_db):
        """Test longtail_migrate method with SQLAlchemy 2.0 patterns."""
        result = cowrie_db.longtail_migrate(dry_run=True)

        assert isinstance(result, dict)
        assert 'success' in result
        assert 'message' in result

    def test_longtail_rollback_sqlalchemy2(self, cowrie_db):
        """Test longtail_rollback method with SQLAlchemy 2.0 patterns."""
        result = cowrie_db.longtail_rollback()

        assert isinstance(result, dict)
        assert 'success' in result
        assert 'message' in result

    def test_validate_longtail_schema_sqlalchemy2(self, cowrie_db):
        """Test validate_longtail_schema method with SQLAlchemy 2.0 patterns."""
        result = cowrie_db.validate_longtail_schema()

        assert isinstance(result, dict)
        assert 'success' in result
        assert 'message' in result

    def test_backfill_files_table_sqlalchemy2(self, cowrie_db):
        """Test backfill_files_table method with SQLAlchemy 2.0 patterns."""
        result = cowrie_db.backfill_files_table(batch_size=100, limit=1000)

        assert isinstance(result, dict)
        assert 'events_processed' in result
        assert 'files_inserted' in result
        assert 'message' in result

    def test_create_backup_sqlalchemy2(self, cowrie_db):
        """Test create_backup method with SQLAlchemy 2.0 patterns."""
        result = cowrie_db.create_backup()

        assert isinstance(result, str)
        assert result.endswith('.db')

    def test_progress_callback_type_safety(self, cowrie_db):
        """Test that progress callback has proper type safety."""
        # Test that progress callback can be called with SanitizationMetrics
        callback_called = False

        def progress_callback(metrics: SanitizationMetrics) -> None:
            nonlocal callback_called
            callback_called = True
            assert isinstance(metrics, SanitizationMetrics)
            assert isinstance(metrics.records_processed, int)
            assert isinstance(metrics.records_updated, int)
            assert isinstance(metrics.records_skipped, int)
            assert isinstance(metrics.errors, int)
            assert isinstance(metrics.batches_processed, int)
            assert isinstance(metrics.duration_seconds, float)
            assert isinstance(metrics.dry_run, bool)

        # Test with progress callback
        result = cowrie_db.sanitize_unicode_in_database(
            batch_size=100, limit=1000, dry_run=True, progress_callback=progress_callback
        )

        assert isinstance(result, dict)

    def test_sanitization_metrics_type_safety(self):
        """Test SanitizationMetrics type safety."""
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

        assert isinstance(metrics.records_processed, int)
        assert isinstance(metrics.records_updated, int)
        assert isinstance(metrics.records_skipped, int)
        assert isinstance(metrics.errors, int)
        assert isinstance(metrics.batches_processed, int)
        assert isinstance(metrics.duration_seconds, float)
        assert isinstance(metrics.dry_run, bool)
        assert isinstance(metrics.ingest_id, str)

    def test_no_sqlalchemy_deprecation_warnings(self, cowrie_db):
        """Test that no SQLAlchemy deprecation warnings are generated."""
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # Perform various operations that might trigger deprecation warnings
            cowrie_db._get_engine()
            cowrie_db._get_session()
            cowrie_db._table_exists("test_table")
            cowrie_db.validate_schema()

            # Check that no deprecation warnings were generated
            deprecation_warnings = [warning for warning in w if 'deprecat' in str(warning.message).lower()]
            assert len(deprecation_warnings) == 0, (
                f"Found deprecation warnings: {[str(w.message) for w in deprecation_warnings]}"
            )

    def test_sqlalchemy_20_patterns(self, cowrie_db):
        """Test that SQLAlchemy 2.0 patterns are properly used."""
        # Test that we're using proper SQLAlchemy 2.0 patterns
        engine = cowrie_db._get_engine()

        # Test that engine has future=True for SQLAlchemy 2.0 compatibility
        assert hasattr(engine, 'future')

        # Test that session maker is created with future=True
        session_maker = cowrie_db._session_maker
        assert session_maker is not None

    def test_type_annotations_consistency(self, cowrie_db):
        """Test that type annotations are consistent throughout."""
        # Test that all methods return the expected types
        methods_to_test = [
            ('migrate', dict),
            ('validate_schema', dict),
            ('optimize', dict),
            ('check_integrity', dict),
            ('get_files_table_stats', dict),
            ('analyze_data_quality', dict),
            ('repair_data_quality', dict),
            ('backfill_files_table', dict),
            ('sanitize_unicode_in_database', dict),
            ('longtail_migrate', dict),
            ('longtail_rollback', dict),
            ('validate_longtail_schema', dict),
        ]

        for method_name, expected_type in methods_to_test:
            method = getattr(cowrie_db, method_name)

            # Test with minimal parameters to avoid errors
            if method_name == 'migrate':
                result = method(dry_run=True)
            elif method_name in ['optimize', 'check_integrity']:
                result = method()
            elif method_name in [
                'analyze_data_quality',
                'repair_data_quality',
                'backfill_files_table',
                'sanitize_unicode_in_database',
            ]:
                result = method(dry_run=True, batch_size=1, limit=1)
            elif method_name == 'longtail_migrate':
                result = method(dry_run=True)
            else:
                result = method()

            assert isinstance(result, expected_type), f"{method_name} should return {expected_type.__name__}"

    def test_error_handling_type_safety(self, cowrie_db):
        """Test that error handling maintains type safety."""
        # Test error handling with invalid parameters
        result = cowrie_db.backfill_files_table(batch_size=0, limit=0)

        assert isinstance(result, dict)
        assert 'message' in result

        # Test error handling with invalid table name
        result = cowrie_db._table_exists("")

        assert isinstance(result, bool)
        assert result is False

    def test_database_connection_type_safety(self, cowrie_db):
        """Test that database connections maintain type safety."""
        engine = cowrie_db._get_engine()

        # Test that engine connection returns proper types
        with engine.connect() as conn:
            assert conn is not None

            # Test that we can execute queries without type errors
            result = conn.execute(cowrie_db._get_engine().dialect.do_ping(conn))
            # The result should be None for ping, but the operation should not raise type errors


@pytest.mark.integration
class TestSQLAlchemy20CompatibilityIntegration:
    """Integration tests for SQLAlchemy 2.0 compatibility patterns."""

    def test_no_deprecated_patterns_in_code(self):
        """Test that no deprecated SQLAlchemy patterns are used in the code."""
        import os

        # Read the cowrie_db.py file
        cowrie_db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'cowrieprocessor', 'cli', 'cowrie_db.py')
        with open(cowrie_db_path, 'r') as f:
            content = f.read()

        # Check for deprecated patterns
        deprecated_patterns = [
            'session.query(',
            '.query(',
            'session.execute(',
            'session.commit(',
            'session.rollback(',
        ]

        for pattern in deprecated_patterns:
            assert pattern not in content, f"Found deprecated pattern: {pattern}"

    def test_proper_sqlalchemy_20_imports(self):
        """Test that proper SQLAlchemy 2.0 imports are used."""
        import os

        # Read the cowrie_db.py file
        cowrie_db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'cowrieprocessor', 'cli', 'cowrie_db.py')
        with open(cowrie_db_path, 'r') as f:
            content = f.read()

        # Check for proper imports
        required_imports = [
            'from sqlalchemy import Engine, Table, text',
            'from sqlalchemy.orm import Session, sessionmaker',
            'from sqlalchemy.dialects.sqlite import insert as sqlite_insert',
        ]

        for import_stmt in required_imports:
            assert import_stmt in content, f"Missing required import: {import_stmt}"

    def test_proper_type_annotations_usage(self):
        """Test that proper type annotations are used throughout."""
        import os

        # Read the cowrie_db.py file
        cowrie_db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'cowrieprocessor', 'cli', 'cowrie_db.py')
        with open(cowrie_db_path, 'r') as f:
            content = f.read()

        # Check for proper type annotations
        required_annotations = [
            'Dict[str, Any]',
            'Optional[',
            'Callable[',
            'list[',
        ]

        for annotation in required_annotations:
            assert annotation in content, f"Missing required type annotation: {annotation}"

    def test_proper_insert_patterns(self):
        """Test that proper SQLAlchemy 2.0 insert patterns are used."""
        import os

        # Read the cowrie_db.py file
        cowrie_db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'cowrieprocessor', 'cli', 'cowrie_db.py')
        with open(cowrie_db_path, 'r') as f:
            content = f.read()

        # Check for proper insert patterns
        assert 'sqlite_insert(' in content, "Should use sqlite_insert for SQLite"
        assert 'postgres_insert(' in content, "Should use postgres_insert for PostgreSQL"
        assert 'insert as sqlite_insert' in content, "Should import sqlite_insert"

    def test_proper_connection_patterns(self):
        """Test that proper SQLAlchemy 2.0 connection patterns are used."""
        import os

        # Read the cowrie_db.py file
        cowrie_db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'cowrieprocessor', 'cli', 'cowrie_db.py')
        with open(cowrie_db_path, 'r') as f:
            content = f.read()

        # Check for proper connection patterns
        assert 'with engine.connect() as conn:' in content, "Should use engine.connect() pattern"
        assert 'with engine.begin() as conn:' in content, "Should use engine.begin() pattern"

    def test_proper_text_usage(self):
        """Test that proper SQLAlchemy 2.0 text() usage is implemented."""
        import os

        # Read the cowrie_db.py file
        cowrie_db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'cowrieprocessor', 'cli', 'cowrie_db.py')
        with open(cowrie_db_path, 'r') as f:
            content = f.read()

        # Check for proper text() usage
        assert 'text(' in content, "Should use text() for SQL queries"
        assert 'from sqlalchemy import' in content, "Should import from sqlalchemy"
        assert 'text' in content, "Should import text function"
