"""Integration tests for file enrichment flow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.db.migrations import apply_migrations
from cowrieprocessor.loader.bulk import BulkLoader
from cowrieprocessor.settings import load_database_settings


@pytest.fixture
def test_db_path(tmp_path: Path) -> None:
    """Create temporary database for testing."""
    db_path = tmp_path / "test.db"
    return f"sqlite:///{db_path}"


@pytest.fixture
def engine(test_db_path):
    """Create database engine for testing."""
    engine = create_engine_from_settings(load_database_settings())
    # Override with test database path
    from sqlalchemy import create_engine

    engine = create_engine(test_db_path)
    apply_migrations(engine)
    return engine


@pytest.fixture
def sample_file_download_events():
    """Sample file download events for testing."""
    return [
        {
            "eventid": "cowrie.session.file_download",
            "session": "session001",
            "timestamp": "2025-01-27T10:00:00Z",
            "src_ip": "192.168.1.100",
            "shasum": "a" * 64,
            "filename": "test1.txt",
            "size": 1024,
            "url": "http://example.com/test1.txt",
        },
        {
            "eventid": "cowrie.session.file_download",
            "session": "session002",
            "timestamp": "2025-01-27T10:05:00Z",
            "src_ip": "192.168.1.101",
            "shasum": "b" * 64,
            "filename": "malware.exe",
            "size": 2048,
            "url": "http://malicious.com/malware.exe",
        },
        {
            "eventid": "cowrie.session.file_download",
            "session": "session001",  # Same session as first file
            "timestamp": "2025-01-27T10:10:00Z",
            "src_ip": "192.168.1.100",
            "shasum": "c" * 64,
            "filename": "test2.txt",
            "size": 512,
            "url": "http://example.com/test2.txt",
        },
        {
            "eventid": "cowrie.command.input",  # Not a file download
            "session": "session003",
            "timestamp": "2025-01-27T10:15:00Z",
            "src_ip": "192.168.1.102",
            "input": "ls -la",
        },
    ]


class TestFileEnrichmentFlow:
    """Test end-to-end file enrichment flow."""

    def test_bulk_loader_processes_file_events(self, engine, sample_file_download_events, tmp_path: Path) -> None:
        """Test that bulk loader processes file download events."""
        # Create temporary JSON file with events
        json_file = tmp_path / "events.json"
        with open(json_file, "w") as f:
            for event in sample_file_download_events:
                f.write(json.dumps(event) + "\n")

        # Create bulk loader
        loader = BulkLoader(engine)

        # Process the file
        metrics = loader.load_paths([json_file])

        # Verify metrics
        assert metrics.events_read == len(sample_file_download_events)
        assert metrics.events_invalid == 0
        assert metrics.batches_committed > 0

        # Verify files were inserted
        with engine.connect() as conn:
            from sqlalchemy import text

            result = conn.execute(text("SELECT COUNT(*) FROM files"))
            file_count = result.scalar_one()
            assert file_count == 3  # 3 file download events

            # Verify specific files
            result = conn.execute(text("SELECT shasum, filename, session_id FROM files ORDER BY first_seen"))
            files = result.fetchall()

            assert len(files) == 3
            assert files[0][0] == "a" * 64  # First file hash
            assert files[0][1] == "test1.txt"
            assert files[0][2] == "session001"

            assert files[1][0] == "b" * 64  # Second file hash
            assert files[1][1] == "malware.exe"
            assert files[1][2] == "session002"

            assert files[2][0] == "c" * 64  # Third file hash
            assert files[2][1] == "test2.txt"
            assert files[2][2] == "session001"

    def test_files_table_enrichment_status(self, engine, sample_file_download_events, tmp_path: Path) -> None:
        """Test that files are created with correct enrichment status."""
        # Create temporary JSON file with events
        json_file = tmp_path / "events.json"
        with open(json_file, "w") as f:
            for event in sample_file_download_events:
                f.write(json.dumps(event) + "\n")

        # Create bulk loader
        loader = BulkLoader(engine)

        # Process the file
        loader.load_paths([json_file])

        # Verify enrichment status
        with engine.connect() as conn:
            from sqlalchemy import text

            result = conn.execute(text("SELECT enrichment_status FROM files"))
            statuses = [row[0] for row in result.fetchall()]

            # All files should have 'pending' status initially
            assert all(status == "pending" for status in statuses)

    def test_duplicate_file_handling(self, engine, tmp_path: Path) -> None:
        """Test handling of duplicate files (same session_id + shasum)."""
        # Create events with duplicate files
        events = [
            {
                "eventid": "cowrie.session.file_download",
                "session": "session001",
                "timestamp": "2025-01-27T10:00:00Z",
                "src_ip": "192.168.1.100",
                "shasum": "a" * 64,
                "filename": "test.txt",
                "size": 1024,
                "url": "http://example.com/test.txt",
            },
            {
                "eventid": "cowrie.session.file_download",
                "session": "session001",  # Same session
                "timestamp": "2025-01-27T10:05:00Z",
                "src_ip": "192.168.1.100",
                "shasum": "a" * 64,  # Same hash
                "filename": "test.txt",  # Same filename
                "size": 1024,
                "url": "http://example.com/test.txt",
            },
        ]

        # Create temporary JSON file with events
        json_file = tmp_path / "events.json"
        with open(json_file, "w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

        # Create bulk loader
        loader = BulkLoader(engine)

        # Process the file
        loader.load_paths([json_file])

        # Verify only one file record was created
        with engine.connect() as conn:
            from sqlalchemy import text

            result = conn.execute(text("SELECT COUNT(*) FROM files"))
            file_count = result.scalar_one()
            assert file_count == 1

    def test_file_metadata_preservation(self, engine, tmp_path: Path) -> None:
        """Test that file metadata is correctly preserved."""
        # Create event with all metadata fields
        event = {
            "eventid": "cowrie.session.file_download",
            "session": "session001",
            "timestamp": "2025-01-27T10:00:00Z",
            "src_ip": "192.168.1.100",
            "shasum": "a" * 64,
            "filename": "test_file.txt",
            "size": 2048,
            "url": "http://example.com/path/test_file.txt",
        }

        # Create temporary JSON file with event
        json_file = tmp_path / "events.json"
        with open(json_file, "w") as f:
            f.write(json.dumps(event) + "\n")

        # Create bulk loader
        loader = BulkLoader(engine)

        # Process the file
        loader.load_paths([json_file])

        # Verify metadata preservation
        with engine.connect() as conn:
            from sqlalchemy import text

            result = conn.execute(text("SELECT shasum, filename, file_size, download_url FROM files"))
            row = result.fetchone()

            assert row[0] == "a" * 64
            assert row[1] == "test_file.txt"
            assert row[2] == 2048
            assert row[3] == "http://example.com/path/test_file.txt"

    def test_invalid_file_events_handling(self, engine, tmp_path: Path) -> None:
        """Test handling of invalid file events."""
        # Create events with invalid data
        events = [
            {
                "eventid": "cowrie.session.file_download",
                "session": "session001",
                "timestamp": "2025-01-27T10:00:00Z",
                "src_ip": "192.168.1.100",
                "shasum": "invalid_hash",  # Invalid hash length
                "filename": "test.txt",
            },
            {
                "eventid": "cowrie.session.file_download",
                "session": "session002",
                "timestamp": "2025-01-27T10:05:00Z",
                "src_ip": "192.168.1.101",
                # Missing shasum
                "filename": "test2.txt",
            },
            {
                "eventid": "cowrie.session.file_download",
                "session": "session003",
                "timestamp": "2025-01-27T10:10:00Z",
                "src_ip": "192.168.1.102",
                "shasum": "c" * 64,  # Valid hash
                "filename": "valid.txt",
            },
        ]

        # Create temporary JSON file with events
        json_file = tmp_path / "events.json"
        with open(json_file, "w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

        # Create bulk loader
        loader = BulkLoader(engine)

        # Process the file
        loader.load_paths([json_file])

        # Verify only valid file was inserted
        with engine.connect() as conn:
            from sqlalchemy import text

            result = conn.execute(text("SELECT COUNT(*) FROM files"))
            file_count = result.scalar_one()
            assert file_count == 1

            # Verify it's the valid file
            result = conn.execute(text("SELECT filename FROM files"))
            filename = result.scalar_one()
            assert filename == "valid.txt"

    def test_session_summary_file_count_integration(self, engine, sample_file_download_events, tmp_path: Path) -> None:
        """Test that session summaries correctly count file downloads."""
        # Create temporary JSON file with events
        json_file = tmp_path / "events.json"
        with open(json_file, "w") as f:
            for event in sample_file_download_events:
                f.write(json.dumps(event) + "\n")

        # Create bulk loader
        loader = BulkLoader(engine)

        # Process the file
        loader.load_paths([json_file])

        # Verify session summaries
        with engine.connect() as conn:
            from sqlalchemy import text

            # Check session001 (should have 2 files)
            result = conn.execute(text("SELECT file_downloads FROM session_summaries WHERE session_id = 'session001'"))
            file_count = result.scalar_one()
            assert file_count == 2

            # Check session002 (should have 1 file)
            result = conn.execute(text("SELECT file_downloads FROM session_summaries WHERE session_id = 'session002'"))
            file_count = result.scalar_one()
            assert file_count == 1

    def test_files_table_indexes(self, engine) -> None:
        """Test that Files table has proper indexes for performance."""
        with engine.connect() as conn:
            from sqlalchemy import text

            # Check indexes exist
            result = conn.execute(text("PRAGMA index_list('files')"))
            indexes = [row[1] for row in result.fetchall()]

            # Should have indexes for common queries
            expected_indexes = [
                "ix_files_shasum",
                "ix_files_vt_malicious",
                "ix_files_enrichment_status",
                "ix_files_first_seen",
                "ix_files_session_id",
            ]

            for expected_idx in expected_indexes:
                assert expected_idx in indexes
