"""Comprehensive functional tests for cowrie_db.py database management."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from cowrieprocessor.cli.cowrie_db import CowrieDatabase, SanitizationMetrics
from cowrieprocessor.db import CURRENT_SCHEMA_VERSION, Base


class TestCowrieDatabaseBasics:
    """Test basic CowrieDatabase functionality."""

    def test_database_initialization(self, tmp_path: Path) -> None:
        """Test CowrieDatabase initialization.

        Given: A database URL
        When: CowrieDatabase is initialized
        Then: Instance is created with correct attributes
        """
        # Given: Database URL
        db_path = tmp_path / "test.sqlite"
        db_url = f"sqlite:///{db_path}"

        # When: Initialize CowrieDatabase
        db = CowrieDatabase(db_url)

        # Then: Attributes are set correctly
        assert db.db_url == db_url
        assert db._engine is None
        assert db._session_maker is None

    def test_is_sqlite_detection(self, tmp_path: Path) -> None:
        """Test SQLite database detection.

        Given: A SQLite database URL
        When: _is_sqlite is called
        Then: Returns True
        """
        # Given: SQLite URL
        db_path = tmp_path / "test.sqlite"
        db_url = f"sqlite:///{db_path}"
        db = CowrieDatabase(db_url)

        # When/Then: Detect SQLite
        assert db._is_sqlite() is True
        assert db._is_postgresql() is False

    def test_is_postgresql_detection(self) -> None:
        """Test PostgreSQL database detection.

        Given: A PostgreSQL database URL
        When: _is_postgresql is called
        Then: Returns True
        """
        # Given: PostgreSQL URL
        db_url = "postgresql://user:pass@localhost:5432/dbname"
        db = CowrieDatabase(db_url)

        # When/Then: Detect PostgreSQL
        assert db._is_postgresql() is True
        assert db._is_sqlite() is False

    def test_postgres_alternate_protocol(self) -> None:
        """Test PostgreSQL detection with postgres:// protocol.

        Given: A postgres:// database URL
        When: _is_postgresql is called
        Then: Returns True
        """
        # Given: postgres:// URL
        db_url = "postgres://user:pass@localhost:5432/dbname"
        db = CowrieDatabase(db_url)

        # When/Then: Detect PostgreSQL
        assert db._is_postgresql() is True
        assert db._is_sqlite() is False


class TestCowrieDatabaseTableOperations:
    """Test table existence and metadata operations."""

    def test_table_exists_true(self, tmp_path: Path) -> None:
        """Test _table_exists returns True for existing table.

        Given: Database with schema_state table
        When: _table_exists is called
        Then: Returns True
        """
        # Given: Database with schema_state table
        db_path = tmp_path / "test.sqlite"
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)

        db = CowrieDatabase(f"sqlite:///{db_path}")

        # When/Then: Check existing table
        assert db._table_exists("schema_state") is True

    def test_table_exists_false(self, tmp_path: Path) -> None:
        """Test _table_exists returns False for non-existent table.

        Given: Database without specific table
        When: _table_exists is called for non-existent table
        Then: Returns False
        """
        # Given: Empty database
        db_path = tmp_path / "test.sqlite"
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)

        db = CowrieDatabase(f"sqlite:///{db_path}")

        # When/Then: Check non-existent table
        assert db._table_exists("nonexistent_table") is False

    def test_get_all_indexes_empty_database(self, tmp_path: Path) -> None:
        """Test _get_all_indexes on empty database.

        Given: Fresh database with no custom indexes
        When: _get_all_indexes is called
        Then: Returns empty list or ORM-created indexes only
        """
        # Given: Fresh database
        db_path = tmp_path / "test.sqlite"
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)

        db = CowrieDatabase(f"sqlite:///{db_path}")

        # When: Get all indexes
        indexes = db._get_all_indexes()

        # Then: Result is a list (may include ORM indexes)
        assert isinstance(indexes, list)

    def test_get_all_indexes_with_custom_index(self, tmp_path: Path) -> None:
        """Test _get_all_indexes with custom index.

        Given: Database with custom index
        When: _get_all_indexes is called
        Then: Returns list containing custom index
        """
        # Given: Database with custom index
        db_path = tmp_path / "test.sqlite"
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)

        # Create custom index
        with engine.connect() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS test_idx ON schema_state (key)"))
            conn.commit()

        db = CowrieDatabase(f"sqlite:///{db_path}")

        # When: Get all indexes
        indexes = db._get_all_indexes()

        # Then: Custom index is in the list
        assert isinstance(indexes, list)
        assert "test_idx" in indexes


class TestSanitizationMetrics:
    """Test SanitizationMetrics dataclass."""

    def test_sanitization_metrics_default_values(self) -> None:
        """Test SanitizationMetrics default initialization.

        Given: No arguments provided
        When: SanitizationMetrics is created
        Then: All fields have default values
        """
        # When: Create with defaults
        metrics = SanitizationMetrics()

        # Then: Default values are correct
        assert metrics.records_processed == 0
        assert metrics.records_updated == 0
        assert metrics.records_skipped == 0
        assert metrics.errors == 0
        assert metrics.batches_processed == 0
        assert metrics.duration_seconds == 0.0
        assert metrics.dry_run is False
        assert metrics.ingest_id is None

    def test_sanitization_metrics_custom_values(self) -> None:
        """Test SanitizationMetrics with custom values.

        Given: Custom metric values
        When: SanitizationMetrics is created
        Then: All fields have specified values
        """
        # Given/When: Create with custom values
        metrics = SanitizationMetrics(
            records_processed=1000,
            records_updated=750,
            records_skipped=200,
            errors=50,
            batches_processed=10,
            duration_seconds=45.5,
            dry_run=True,
            ingest_id="test-run-123",
        )

        # Then: Custom values are set
        assert metrics.records_processed == 1000
        assert metrics.records_updated == 750
        assert metrics.records_skipped == 200
        assert metrics.errors == 50
        assert metrics.batches_processed == 10
        assert metrics.duration_seconds == 45.5
        assert metrics.dry_run is True
        assert metrics.ingest_id == "test-run-123"


class TestCowrieDatabaseSchemaManagement:
    """Test schema version and migration operations."""

    def test_get_schema_version_new_database(self, tmp_path: Path) -> None:
        """Test get_schema_version on fresh database.

        Given: Fresh database without schema_state table
        When: get_schema_version is called
        Then: Returns 0
        """
        # Given: Fresh database (no tables)
        db_path = tmp_path / "test.sqlite"
        db_url = f"sqlite:///{db_path}"
        db = CowrieDatabase(db_url)

        # When: Get schema version
        version = db.get_schema_version()

        # Then: Returns 0 for new database
        assert version == 0

    def test_get_schema_version_with_migrations(self, tmp_path: Path) -> None:
        """Test get_schema_version after migrations.

        Given: Database with applied migrations
        When: get_schema_version is called
        Then: Returns correct version number
        """
        # Given: Database with migrations applied
        db_path = tmp_path / "test.sqlite"
        db_url = f"sqlite:///{db_path}"
        db = CowrieDatabase(db_url)

        # Apply migrations
        db.migrate()

        # When: Get schema version
        version = db.get_schema_version()

        # Then: Returns current schema version
        assert version == CURRENT_SCHEMA_VERSION
        assert version > 0

    def test_migrate_new_database(self, tmp_path: Path) -> None:
        """Test migrate on fresh database.

        Given: Fresh database
        When: migrate is called
        Then: Migrations are applied successfully
        """
        # Given: Fresh database
        db_path = tmp_path / "test.sqlite"
        db_url = f"sqlite:///{db_path}"
        db = CowrieDatabase(db_url)

        # When: Run migrations
        result = db.migrate()

        # Then: Migration successful
        assert isinstance(result, dict)
        assert result['current_version'] == 0
        assert result['target_version'] == CURRENT_SCHEMA_VERSION
        assert 'migrations_applied' in result
        assert isinstance(result['migrations_applied'], list)
        assert len(result['migrations_applied']) > 0
        assert result['dry_run'] is False

    def test_migrate_dry_run(self, tmp_path: Path) -> None:
        """Test migrate with dry_run=True.

        Given: Fresh database
        When: migrate is called with dry_run=True
        Then: Returns migration plan without executing
        """
        # Given: Fresh database
        db_path = tmp_path / "test.sqlite"
        db_url = f"sqlite:///{db_path}"
        db = CowrieDatabase(db_url)

        # When: Run dry-run migration
        result = db.migrate(dry_run=True)

        # Then: Returns plan without applying
        assert isinstance(result, dict)
        assert result['dry_run'] is True
        assert 'migrations_applied' in result
        assert len(result['migrations_applied']) > 0
        assert 'Would migrate' in result['message']

        # Verify database wasn't actually migrated
        version = db.get_schema_version()
        assert version == 0

    def test_migrate_already_current(self, tmp_path: Path) -> None:
        """Test migrate on already-migrated database.

        Given: Database already at current schema version
        When: migrate is called
        Then: Returns message indicating no migration needed
        """
        # Given: Database with current schema
        db_path = tmp_path / "test.sqlite"
        db_url = f"sqlite:///{db_path}"
        db = CowrieDatabase(db_url)

        # Apply migrations first
        db.migrate()

        # When: Try to migrate again
        result = db.migrate()

        # Then: No migration needed
        assert isinstance(result, dict)
        assert result['current_version'] == CURRENT_SCHEMA_VERSION
        assert 'already at version' in result['message'].lower()

    def test_validate_schema_success(self, tmp_path: Path) -> None:
        """Test validate_schema on valid database.

        Given: Database with current schema
        When: validate_schema is called
        Then: Returns validation success
        """
        # Given: Database with migrations
        db_path = tmp_path / "test.sqlite"
        db_url = f"sqlite:///{db_path}"
        db = CowrieDatabase(db_url)
        db.migrate()

        # When: Validate schema
        result = db.validate_schema()

        # Then: Validation successful
        assert isinstance(result, dict)
        assert result['is_valid'] is True
        assert result['schema_version'] == CURRENT_SCHEMA_VERSION
        assert result['expected_version'] == CURRENT_SCHEMA_VERSION
        assert isinstance(result['database_size_mb'], (int, float))
        assert result['database_size_mb'] >= 0  # Can be 0 for empty databases
        assert 'session_count' in result
        assert 'command_count' in result
        assert 'file_count' in result


class TestCowrieDatabaseMaintenance:
    """Test database optimization and maintenance operations."""

    def test_optimize_vacuum_and_reindex(self, tmp_path: Path) -> None:
        """Test optimize with VACUUM and REINDEX.

        Given: Database with data
        When: optimize is called
        Then: VACUUM and REINDEX complete successfully
        """
        # Given: Database with schema
        db_path = tmp_path / "test.sqlite"
        db_url = f"sqlite:///{db_path}"
        db = CowrieDatabase(db_url)
        db.migrate()

        # When: Run optimization
        result = db.optimize(vacuum=True, reindex=True)

        # Then: Optimization successful
        assert isinstance(result, dict)
        assert 'operations' in result
        assert 'initial_size_mb' in result
        assert 'final_size_mb' in result
        assert 'reclaimed_mb' in result
        assert isinstance(result['operations'], list)
        assert len(result['operations']) > 0
        assert any('VACUUM' in op for op in result['operations'])

    def test_optimize_vacuum_only(self, tmp_path: Path) -> None:
        """Test optimize with vacuum_only.

        Given: Database with data
        When: optimize is called with reindex=False
        Then: Only VACUUM is performed
        """
        # Given: Database with schema
        db_path = tmp_path / "test.sqlite"
        db_url = f"sqlite:///{db_path}"
        db = CowrieDatabase(db_url)
        db.migrate()

        # When: Run VACUUM only
        result = db.optimize(vacuum=True, reindex=False)

        # Then: Only VACUUM in operations
        assert isinstance(result, dict)
        assert 'operations' in result
        assert any('VACUUM' in op for op in result['operations'])
        # Should not have reindex operation
        reindex_ops = [op for op in result['operations'] if 'Reindex' in op]
        assert len(reindex_ops) == 0

    def test_create_backup_success(self, tmp_path: Path) -> None:
        """Test create_backup creates valid backup file.

        Given: Database with data
        When: create_backup is called
        Then: Backup file is created and verified
        """
        # Given: Database with schema
        db_path = tmp_path / "test.sqlite"
        db_url = f"sqlite:///{db_path}"
        db = CowrieDatabase(db_url)
        db.migrate()

        # When: Create backup
        backup_path = db.create_backup()

        # Then: Backup file exists and is valid
        assert isinstance(backup_path, str)
        assert Path(backup_path).exists()
        assert Path(backup_path).stat().st_size > 0
        assert backup_path.endswith(".sqlite")

    def test_create_backup_custom_path(self, tmp_path: Path) -> None:
        """Test create_backup with custom path.

        Given: Database with data
        When: create_backup is called with custom path
        Then: Backup is created at specified location
        """
        # Given: Database with schema
        db_path = tmp_path / "test.sqlite"
        db_url = f"sqlite:///{db_path}"
        db = CowrieDatabase(db_url)
        db.migrate()

        # When: Create backup with custom path
        custom_backup = str(tmp_path / "custom_backup.sqlite")
        backup_path = db.create_backup(backup_path=custom_backup)

        # Then: Backup at custom location
        assert backup_path == custom_backup
        assert Path(custom_backup).exists()
        assert Path(custom_backup).stat().st_size > 0

    def test_verify_backup_integrity_valid(self, tmp_path: Path) -> None:
        """Test _verify_backup_integrity on valid backup.

        Given: Valid SQLite backup file
        When: _verify_backup_integrity is called
        Then: Returns True
        """
        # Given: Database and backup
        db_path = tmp_path / "test.sqlite"
        db_url = f"sqlite:///{db_path}"
        db = CowrieDatabase(db_url)
        db.migrate()

        backup_path = db.create_backup()

        # When: Verify backup integrity
        is_valid = db._verify_backup_integrity(backup_path)

        # Then: Backup is valid
        assert is_valid is True

    def test_check_integrity_success(self, tmp_path: Path) -> None:
        """Test check_integrity on healthy database.

        Given: Healthy database
        When: check_integrity is called
        Then: Returns success result
        """
        # Given: Database with schema
        db_path = tmp_path / "test.sqlite"
        db_url = f"sqlite:///{db_path}"
        db = CowrieDatabase(db_url)
        db.migrate()

        # When: Check integrity
        result = db.check_integrity()

        # Then: Integrity check successful
        assert isinstance(result, dict)
        assert 'corruption_found' in result
        assert 'recommendations' in result
        assert 'checks' in result  # Results are nested under 'checks'
        assert 'quick_check' in result['checks']
        assert 'foreign_keys' in result['checks']
        assert 'indexes' in result['checks']
        assert result['corruption_found'] is False
        assert isinstance(result['recommendations'], list)
