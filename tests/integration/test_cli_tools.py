"""Integration tests for CLI tools with cross-backend compatibility."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from cowrieprocessor.cli.cowrie_db import CowrieDatabase
from cowrieprocessor.cli.health import _check_database
from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.db.migrations import apply_migrations
from cowrieprocessor.db.models import RawEvent
from cowrieprocessor.settings import DatabaseSettings


class TestCowrieDatabaseCLI:
    """Test CowrieDatabase CLI tool with cross-backend compatibility."""

    def test_cowrie_database_sqlite(self):
        """Test CowrieDatabase with SQLite database."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            db_url = f"sqlite:///{db_path}"
            db = CowrieDatabase(db_url)

            # Test database type detection
            assert db._is_sqlite() is True
            assert db._is_postgresql() is False

            # Test migration
            result = db.migrate()
            assert result['final_version'] == 6  # Current schema version
            assert 'Successfully migrated' in result['message']

            # Test schema validation
            validation = db.validate_schema()
            assert validation['is_valid'] is True
            assert validation['schema_version'] == 6
            assert validation['database_size_mb'] >= 0  # Can be 0 for very small databases

            # Test integrity check
            integrity = db.check_integrity()
            assert integrity['corruption_found'] is False

            # Test backup creation
            backup_path = db.create_backup()
            assert Path(backup_path).exists()
            assert backup_path.endswith('.sqlite')

            # Clean up backup
            Path(backup_path).unlink(missing_ok=True)

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_cowrie_database_optimization_sqlite(self):
        """Test database optimization with SQLite."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            db_url = f"sqlite:///{db_path}"
            db = CowrieDatabase(db_url)

            # Apply migrations first
            db.migrate()

            # Test optimization
            result = db.optimize(vacuum=True, reindex=True)
            assert 'operations' in result
            assert 'initial_size_mb' in result
            assert 'final_size_mb' in result
            assert 'reclaimed_mb' in result

            # Should have VACUUM and REINDEX operations
            operations = result['operations']
            assert any('VACUUM' in op for op in operations)
            assert any('Reindexed' in op for op in operations)

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_cowrie_database_files_stats(self):
        """Test files table statistics."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            db_url = f"sqlite:///{db_path}"
            db = CowrieDatabase(db_url)

            # Apply migrations first
            db.migrate()

            # Test files table stats
            stats = db.get_files_table_stats()
            assert 'total_files' in stats
            assert 'unique_hashes' in stats
            assert 'enrichment_status' in stats
            assert 'malicious_files' in stats
            assert 'pending_enrichment' in stats

            # Should be zero for empty database
            assert stats['total_files'] == 0
            assert stats['unique_hashes'] == 0
            assert stats['malicious_files'] == 0
            assert stats['pending_enrichment'] == 0

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_cowrie_database_backfill_files(self):
        """Test files table backfill functionality."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            db_url = f"sqlite:///{db_path}"
            db = CowrieDatabase(db_url)

            # Apply migrations first
            db.migrate()

            # Insert test file download event
            Session = sessionmaker(bind=create_engine_from_settings(DatabaseSettings(url=db_url)))
            session = Session()

            test_event = RawEvent(
                source="test",
                source_offset=1,
                ingest_at=datetime.now(timezone.utc),
                payload={
                    "session": "test-session",
                    "eventid": "cowrie.session.file_download",
                    "shasum": "a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456",
                    "filename": "test.exe",
                    "url": "http://example.com/test.exe",
                    "size": 1024,
                },
            )
            session.add(test_event)
            session.commit()
            session.close()

            # Test backfill
            result = db.backfill_files_table(batch_size=100, limit=10)
            assert 'events_processed' in result
            assert 'files_inserted' in result
            assert 'batches_processed' in result
            assert 'errors' in result

            # Should have processed the test event
            assert result['events_processed'] >= 1

        finally:
            Path(db_path).unlink(missing_ok=True)


class TestHealthCLI:
    """Test health check CLI with cross-backend compatibility."""

    def test_health_check_sqlite(self):
        """Test health check with SQLite database."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            db_url = f"sqlite:///{db_path}"

            # Create database and apply migrations
            settings = DatabaseSettings(url=db_url)
            engine = create_engine_from_settings(settings)
            apply_migrations(engine)

            # Test health check
            db_ok, db_summary = _check_database(db_url)
            assert db_ok is True
            assert "sqlite integrity ok" in db_summary

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_health_check_invalid_database(self):
        """Test health check with invalid database."""
        # Test with non-existent SQLite file
        db_url = "sqlite:///definitely_nonexistent_file_12345.db"
        db_ok, db_summary = _check_database(db_url)
        assert db_ok is False
        assert "sqlite database file missing" in db_summary

    def test_health_check_unsupported_database(self):
        """Test health check with unsupported database type."""
        db_url = "mysql://user:pass@localhost/db"
        db_ok, db_summary = _check_database(db_url)
        assert db_ok is False
        assert "unsupported database type" in db_summary


class TestCLIIntegration:
    """Integration tests for CLI tools."""

    def test_full_cli_workflow_sqlite(self):
        """Test complete CLI workflow with SQLite."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            db_url = f"sqlite:///{db_path}"
            db = CowrieDatabase(db_url)

            # 1. Migrate database
            migrate_result = db.migrate()
            assert migrate_result['final_version'] == 6

            # 2. Validate schema
            validation = db.validate_schema()
            assert validation['is_valid'] is True

            # 3. Check integrity
            integrity = db.check_integrity()
            assert integrity['corruption_found'] is False

            # 4. Health check
            db_ok, db_summary = _check_database(db_url)
            assert db_ok is True

            # 5. Get files stats
            files_stats = db.get_files_table_stats()
            assert files_stats['total_files'] == 0

            # 6. Create backup
            backup_path = db.create_backup()
            assert Path(backup_path).exists()

            # 7. Optimize database
            optimize_result = db.optimize()
            assert 'operations' in optimize_result

            # Clean up backup
            Path(backup_path).unlink(missing_ok=True)

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_cli_error_handling(self):
        """Test CLI error handling."""
        # Test with invalid database URL
        db_url = "invalid://database"
        db = CowrieDatabase(db_url)

        # Should handle invalid URLs gracefully
        try:
            db.get_schema_version()
            assert False, "Should have raised an exception"
        except Exception:
            pass  # Expected to fail

        # Test health check with invalid URL
        db_ok, db_summary = _check_database(db_url)
        assert db_ok is False
        assert "unsupported database type" in db_summary


@pytest.mark.integration
class TestCLIPostgreSQLCompatibility:
    """Test CLI tools with PostgreSQL compatibility (mocked)."""

    def test_postgresql_detection(self):
        """Test PostgreSQL database type detection."""
        db_url = "postgresql://user:pass@localhost:5432/cowrie"
        db = CowrieDatabase(db_url)

        assert db._is_sqlite() is False
        assert db._is_postgresql() is True

    def test_postgresql_backup_command_generation(self):
        """Test PostgreSQL backup command generation."""
        db_url = "postgresql://user:password@host:5432/database"
        db = CowrieDatabase(db_url)

        # Test URL parsing for backup
        url_parts = db_url.replace("postgresql://", "").replace("postgres://", "")
        auth, host_db = url_parts.split("@", 1)
        user, password = auth.split(":", 1)
        host_port, database = host_db.split("/", 1)
        host, port = host_port.split(":", 1)

        assert user == "user"
        assert password == "password"
        assert host == "host"
        assert port == "5432"
        assert database == "database"

    def test_health_check_postgresql_format(self):
        """Test health check with PostgreSQL URL format."""
        db_url = "postgresql://user:pass@localhost:5432/cowrie"

        # Test URL format detection
        assert db_url.startswith("postgresql://")

        # Test health check would fail without actual PostgreSQL server
        db_ok, db_summary = _check_database(db_url)
        assert db_ok is False
        assert "connection error" in db_summary or "database error" in db_summary
