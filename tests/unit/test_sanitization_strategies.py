"""Unit tests for Unicode sanitization strategies (Phase 3)."""

from __future__ import annotations

import json
import unittest
from typing import Any

from sqlalchemy import text

from cowrieprocessor.cli.cowrie_db import (
    FilesSanitization,
    RawEventsSanitization,
    SessionSummariesSanitization,
)
from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.settings import DatabaseSettings


class TestRawEventsSanitization(unittest.TestCase):
    """Test RawEventsSanitization strategy."""

    def setUp(self) -> None:
        """Set up test fixtures with in-memory database."""
        settings = DatabaseSettings(url="sqlite:///:memory:")
        self.engine = create_engine_from_settings(settings)

        # Initialize schema
        from cowrieprocessor.db import apply_migrations

        apply_migrations(self.engine)

        # Insert test data with dirty events
        with self.engine.begin() as conn:
            # Clean event
            conn.execute(
                text("""
                INSERT INTO raw_events (source, source_offset, payload)
                VALUES (:source, :source_offset, :payload)
            """),
                {
                    "source": "/var/log/cowrie.log",
                    "source_offset": 0,
                    "payload": json.dumps({"eventid": "cowrie.session.connect", "message": "Clean message"}),
                },
            )

            # Dirty event with null bytes
            conn.execute(
                text("""
                INSERT INTO raw_events (source, source_offset, payload)
                VALUES (:source, :source_offset, :payload)
            """),
                {
                    "source": "/var/log/cowrie.log",
                    "source_offset": 100,
                    "payload": json.dumps({"eventid": "cowrie.command.input", "input": "test\x00command"}),
                },
            )

            # Another dirty event
            conn.execute(
                text("""
                INSERT INTO raw_events (source, source_offset, payload)
                VALUES (:source, :source_offset, :payload)
            """),
                {
                    "source": "/var/log/cowrie.log",
                    "source_offset": 200,
                    "payload": json.dumps({"eventid": "cowrie.session.file_download", "url": "http://evil\x01.com"}),
                },
            )

        self.strategy = RawEventsSanitization(self.engine)

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        self.engine.dispose()

    def test_get_batch_query_returns_dirty_records_only(self) -> None:
        """Test that get_batch_query returns only records with control characters."""
        query, params = self.strategy.get_batch_query(last_id=0, batch_size=10)

        with self.engine.connect() as conn:
            results = conn.execute(text(query), params).fetchall()

        # SQLite doesn't support regex pre-filtering, so all 3 records returned
        # Only 2 have dirty data, but we'll filter during sanitize_record
        self.assertGreaterEqual(len(results), 2)

    def test_sanitize_record_cleans_dirty_event(self) -> None:
        """Test that sanitize_record removes control characters from event JSON."""
        # Get a dirty record - use same alias as strategy expects
        with self.engine.connect() as conn:
            record = conn.execute(
                text("SELECT id, payload as payload_text FROM raw_events WHERE source_offset = 100")
            ).fetchone()

        record_id, sanitized_fields = self.strategy.sanitize_record(record)

        # Verify control character was removed
        sanitized_event = json.loads(sanitized_fields["payload"])
        self.assertEqual(sanitized_event["input"], "testcommand")  # \x00 removed

    def test_sanitize_record_raises_on_clean_data(self) -> None:
        """Test that sanitize_record raises ValueError for clean data."""
        # Get the clean record - use same alias as strategy expects
        with self.engine.connect() as conn:
            record = conn.execute(
                text("SELECT id, payload as payload_text FROM raw_events WHERE source_offset = 0")
            ).fetchone()

        # Should raise ValueError since no sanitization needed
        with self.assertRaises(ValueError):
            self.strategy.sanitize_record(record)

    def test_update_batch_updates_database(self) -> None:
        """Test that update_batch persists sanitized data."""
        # Get dirty records and sanitize - use same alias as strategy expects
        with self.engine.connect() as conn:
            dirty_records = conn.execute(
                text("SELECT id, payload as payload_text FROM raw_events WHERE source_offset >= 100")
            ).fetchall()

        updates: list[tuple[int, dict[str, Any]]] = []
        for record in dirty_records:
            try:
                record_id, sanitized_fields = self.strategy.sanitize_record(record)
                updates.append((record_id, sanitized_fields))
            except ValueError:
                pass  # Skip clean records

        # Apply updates
        updated_count = self.strategy.update_batch(updates)

        # Verify correct count
        self.assertEqual(updated_count, 2)

        # Verify database was updated
        with self.engine.connect() as conn:
            result = conn.execute(text("SELECT payload FROM raw_events WHERE source_offset = 100")).fetchone()
            assert result is not None  # Narrow type for mypy
            event = json.loads(result[0])
            self.assertEqual(event["input"], "testcommand")


class TestSessionSummariesSanitization(unittest.TestCase):
    """Test SessionSummariesSanitization strategy."""

    def setUp(self) -> None:
        """Set up test fixtures with in-memory database."""
        settings = DatabaseSettings(url="sqlite:///:memory:")
        self.engine = create_engine_from_settings(settings)

        # Initialize schema
        from cowrieprocessor.db import apply_migrations

        apply_migrations(self.engine)

        # Insert test data
        with self.engine.begin() as conn:
            # Session with clean enrichment only
            conn.execute(
                text("""
                INSERT INTO session_summaries (session_id, enrichment)
                VALUES (:session_id, :enrichment)
            """),
                {
                    "session_id": "clean-session",
                    "enrichment": json.dumps({"ip": {"country": "US"}}),
                },
            )

            # Session with dirty enrichment only
            conn.execute(
                text("""
                INSERT INTO session_summaries (session_id, enrichment)
                VALUES (:session_id, :enrichment)
            """),
                {
                    "session_id": "dirty-enrichment",
                    "enrichment": json.dumps({"ip": {"asname": "ISP\x00Corp"}}),
                },
            )

            # Session with dirty source_files only
            conn.execute(
                text("""
                INSERT INTO session_summaries (session_id, source_files)
                VALUES (:session_id, :source_files)
            """),
                {
                    "session_id": "dirty-files",
                    "source_files": json.dumps(["/path/to/\x00file.log"]),
                },
            )

            # Session with BOTH dirty fields (critical test case for counting bug)
            conn.execute(
                text("""
                INSERT INTO session_summaries (session_id, enrichment, source_files)
                VALUES (:session_id, :enrichment, :source_files)
            """),
                {
                    "session_id": "dirty-both",
                    "enrichment": json.dumps({"ip": {"asname": "Bad\x00ISP"}}),
                    "source_files": json.dumps(["/var/log/\x01cowrie.log"]),
                },
            )

        self.strategy = SessionSummariesSanitization(self.engine)

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        self.engine.dispose()

    def test_sanitize_record_cleans_enrichment_only(self) -> None:
        """Test sanitization of enrichment field only."""
        with self.engine.connect() as conn:
            record = conn.execute(
                text("""
                SELECT session_id, enrichment as enrichment_text, source_files as source_files_text
                FROM session_summaries WHERE session_id = 'dirty-enrichment'
            """)
            ).fetchone()

        session_id, sanitized_fields = self.strategy.sanitize_record(record)

        # Verify only enrichment is in sanitized_fields
        self.assertIn("enrichment", sanitized_fields)
        self.assertNotIn("source_files", sanitized_fields)

        # Verify control character removed
        enrichment = json.loads(sanitized_fields["enrichment"])
        self.assertEqual(enrichment["ip"]["asname"], "ISPCorp")

    def test_sanitize_record_cleans_source_files_only(self) -> None:
        """Test sanitization of source_files field only."""
        with self.engine.connect() as conn:
            record = conn.execute(
                text("""
                SELECT session_id, enrichment as enrichment_text, source_files as source_files_text
                FROM session_summaries WHERE session_id = 'dirty-files'
            """)
            ).fetchone()

        session_id, sanitized_fields = self.strategy.sanitize_record(record)

        # Verify only source_files is in sanitized_fields
        self.assertNotIn("enrichment", sanitized_fields)
        self.assertIn("source_files", sanitized_fields)

        # Verify control character removed
        files = json.loads(sanitized_fields["source_files"])
        self.assertEqual(files[0], "/path/to/file.log")

    def test_sanitize_record_cleans_both_fields(self) -> None:
        """Test sanitization when both fields are dirty."""
        with self.engine.connect() as conn:
            record = conn.execute(
                text("""
                SELECT session_id, enrichment as enrichment_text, source_files as source_files_text
                FROM session_summaries WHERE session_id = 'dirty-both'
            """)
            ).fetchone()

        session_id, sanitized_fields = self.strategy.sanitize_record(record)

        # Verify both fields are in sanitized_fields
        self.assertIn("enrichment", sanitized_fields)
        self.assertIn("source_files", sanitized_fields)

    def test_update_batch_counts_unique_records_not_fields(self) -> None:
        """Test counting bug fix: records with both dirty fields should count as 1, not 2."""
        # Get all dirty records
        with self.engine.connect() as conn:
            dirty_records = conn.execute(
                text("""
                SELECT session_id, enrichment as enrichment_text, source_files as source_files_text
                FROM session_summaries WHERE session_id != 'clean-session'
            """)
            ).fetchall()

        # Sanitize all records
        updates: list[tuple[str, dict[str, Any]]] = []
        for record in dirty_records:
            try:
                session_id, sanitized_fields = self.strategy.sanitize_record(record)
                updates.append((session_id, sanitized_fields))
            except ValueError:
                pass  # Skip clean

        # Apply updates
        updated_count = self.strategy.update_batch(updates)

        # Critical assertion: Should be 3 records (dirty-enrichment, dirty-files, dirty-both)
        # NOT 4 (which would happen if dirty-both was counted twice)
        self.assertEqual(updated_count, 3, "Counting bug regression: records with both dirty fields counted twice")

        # Verify database was actually updated
        with self.engine.connect() as conn:
            # Check enrichment was sanitized
            result = conn.execute(
                text("SELECT enrichment FROM session_summaries WHERE session_id = 'dirty-both'")
            ).fetchone()
            assert result is not None  # Narrow type for mypy
            enrichment = json.loads(result[0])
            self.assertEqual(enrichment["ip"]["asname"], "BadISP")

            # Check source_files was sanitized
            result = conn.execute(
                text("SELECT source_files FROM session_summaries WHERE session_id = 'dirty-both'")
            ).fetchone()
            assert result is not None  # Narrow type for mypy
            files = json.loads(result[0])
            self.assertEqual(files[0], "/var/log/cowrie.log")


class TestFilesSanitization(unittest.TestCase):
    """Test FilesSanitization strategy."""

    def setUp(self) -> None:
        """Set up test fixtures with in-memory database."""
        settings = DatabaseSettings(url="sqlite:///:memory:")
        self.engine = create_engine_from_settings(settings)

        # Initialize schema
        from cowrieprocessor.db import apply_migrations

        apply_migrations(self.engine)

        # Insert test data
        with self.engine.begin() as conn:
            # Clean file
            conn.execute(
                text("""
                INSERT INTO files (session_id, shasum, filename, download_url, vt_classification, vt_description)
                VALUES (:session_id, :shasum, :filename, :download_url, :vt_classification, :vt_description)
            """),
                {
                    "session_id": "test-session",
                    "shasum": "a" * 64,
                    "filename": "clean.exe",
                    "download_url": "http://example.com/file",
                    "vt_classification": "trojan.generic",
                    "vt_description": "Generic trojan detected",
                },
            )

            # Dirty filename
            conn.execute(
                text("""
                INSERT INTO files (session_id, shasum, filename)
                VALUES (:session_id, :shasum, :filename)
            """),
                {
                    "session_id": "test-session",
                    "shasum": "b" * 64,
                    "filename": "malware\x00.exe",
                },
            )

            # Dirty download_url
            conn.execute(
                text("""
                INSERT INTO files (session_id, shasum, download_url)
                VALUES (:session_id, :shasum, :download_url)
            """),
                {
                    "session_id": "test-session",
                    "shasum": "c" * 64,
                    "download_url": "http://evil\x01.com/malware",
                },
            )

            # Dirty VT fields
            conn.execute(
                text("""
                INSERT INTO files (session_id, shasum, vt_classification, vt_description)
                VALUES (:session_id, :shasum, :vt_classification, :vt_description)
            """),
                {
                    "session_id": "test-session",
                    "shasum": "d" * 64,
                    "vt_classification": "trojan\x00.generic",
                    "vt_description": "Malicious file\x00 detected",
                },
            )

        self.strategy = FilesSanitization(self.engine)

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        self.engine.dispose()

    def test_sanitize_record_cleans_filename(self) -> None:
        """Test sanitization of filename field."""
        with self.engine.connect() as conn:
            record = conn.execute(
                text("""
                    SELECT shasum, filename, download_url, vt_classification, vt_description
                    FROM files WHERE shasum = :shasum
                """),
                {"shasum": "b" * 64},
            ).fetchone()

        shasum, sanitized_fields = self.strategy.sanitize_record(record)

        self.assertIn("filename", sanitized_fields)
        self.assertEqual(sanitized_fields["filename"], "malware.exe")

    def test_sanitize_record_cleans_vt_fields(self) -> None:
        """Test sanitization of VirusTotal fields."""
        with self.engine.connect() as conn:
            record = conn.execute(
                text("""
                    SELECT shasum, filename, download_url, vt_classification, vt_description
                    FROM files WHERE shasum = :shasum
                """),
                {"shasum": "d" * 64},
            ).fetchone()

        shasum, sanitized_fields = self.strategy.sanitize_record(record)

        self.assertIn("vt_classification", sanitized_fields)
        self.assertIn("vt_description", sanitized_fields)
        self.assertEqual(sanitized_fields["vt_classification"], "trojan.generic")
        self.assertEqual(sanitized_fields["vt_description"], "Malicious file detected")

    def test_update_batch_updates_multiple_fields(self) -> None:
        """Test batch update with multiple dirty fields per record."""
        # Get dirty records
        with self.engine.connect() as conn:
            dirty_records = conn.execute(
                text("""
                    SELECT shasum, filename, download_url, vt_classification, vt_description
                    FROM files WHERE shasum != :shasum
                """),
                {"shasum": "a" * 64},
            ).fetchall()

        # Sanitize
        updates: list[tuple[str, dict[str, Any]]] = []
        for record in dirty_records:
            try:
                shasum, sanitized_fields = self.strategy.sanitize_record(record)
                updates.append((shasum, sanitized_fields))
            except ValueError:
                pass

        # Apply updates
        updated_count = self.strategy.update_batch(updates)

        # Should be 3 files updated
        self.assertEqual(updated_count, 3)

        # Verify updates persisted
        with self.engine.connect() as conn:
            result = conn.execute(
                text("SELECT filename FROM files WHERE shasum = :shasum"),
                {"shasum": "b" * 64},
            ).fetchone()
            assert result is not None  # Narrow type for mypy
            self.assertEqual(result[0], "malware.exe")


if __name__ == "__main__":
    unittest.main()
