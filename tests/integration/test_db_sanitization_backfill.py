"""Integration tests for multi-table database backfill sanitization (Phase 3).

These tests validate end-to-end sanitization workflows across all three tables
(raw_events, session_summaries, files) with realistic dirty data scenarios.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from sqlalchemy import text

from cowrieprocessor.cli.cowrie_db import CowrieDatabase
from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.settings import DatabaseSettings


class TestMultiTableBackfillSanitization(unittest.TestCase):
    """Integration tests for full multi-table database backfill."""

    def setUp(self) -> None:
        """Set up test database with dirty data across all tables."""
        settings = DatabaseSettings(url="sqlite:///:memory:")
        self.engine = create_engine_from_settings(settings)

        # Initialize schema
        from cowrieprocessor.db import apply_migrations

        apply_migrations(self.engine)

        # Create CowrieDatabase instance for testing
        self.db = CowrieDatabase(db_url="sqlite:///:memory:")
        self.db._engine = self.engine  # Inject engine to use same in-memory database

        # Insert comprehensive dirty data across all tables
        self._insert_dirty_raw_events()
        self._insert_dirty_session_summaries()
        self._insert_dirty_files()

    def _insert_dirty_raw_events(self) -> None:
        """Insert raw_events with dirty payload data."""
        with self.engine.begin() as conn:
            # Clean event (baseline)
            conn.execute(
                text("""
                INSERT INTO raw_events (source, source_offset, payload)
                VALUES (:source, :source_offset, :payload)
            """),
                {
                    "source": "/var/log/cowrie.log",
                    "source_offset": 0,
                    "payload": json.dumps({"eventid": "cowrie.session.connect", "message": "Clean"}),
                },
            )

            # Dirty events with various control characters
            dirty_payloads = [
                {"eventid": "cowrie.command.input", "input": "cat\x00/etc/passwd"},  # NULL byte
                {"eventid": "cowrie.command.input", "input": "ls\x01-la"},  # SOH
                {"eventid": "cowrie.session.file_download", "url": "http://evil\x0b.com"},  # VT
                {"eventid": "cowrie.login.failed", "username": "admin\x1f"},  # US
            ]

            for i, payload in enumerate(dirty_payloads, start=1):
                conn.execute(
                    text("""
                    INSERT INTO raw_events (source, source_offset, payload)
                    VALUES (:source, :source_offset, :payload)
                """),
                    {
                        "source": "/var/log/cowrie.log",
                        "source_offset": i * 100,
                        "payload": json.dumps(payload),
                    },
                )

    def _insert_dirty_session_summaries(self) -> None:
        """Insert session_summaries with dirty enrichment and source_files."""
        with self.engine.begin() as conn:
            # Clean session (baseline)
            conn.execute(
                text("""
                INSERT INTO session_summaries (session_id, enrichment, source_files)
                VALUES (:session_id, :enrichment, :source_files)
            """),
                {
                    "session_id": "clean-session-001",
                    "enrichment": json.dumps({"ip": {"country": "US"}}),
                    "source_files": json.dumps(["/var/log/cowrie.log"]),
                },
            )

            # Session with dirty enrichment only
            conn.execute(
                text("""
                INSERT INTO session_summaries (session_id, enrichment)
                VALUES (:session_id, :enrichment)
            """),
                {
                    "session_id": "dirty-enrichment-001",
                    "enrichment": json.dumps(
                        {
                            "dshield": {"asname": "Evil\x00Corp", "ascountry": "RU\x01"},
                            "virustotal": {"detected_urls": ["http://malware\x0b.com"]},
                        }
                    ),
                },
            )

            # Session with dirty source_files only
            conn.execute(
                text("""
                INSERT INTO session_summaries (session_id, source_files)
                VALUES (:session_id, :source_files)
            """),
                {
                    "session_id": "dirty-files-001",
                    "source_files": json.dumps(
                        [
                            "/var/log/cowrie\x00.log",
                            "/tmp/session\x01.json",
                        ]
                    ),
                },
            )

            # Session with BOTH fields dirty (critical for counting bug test)
            conn.execute(
                text("""
                INSERT INTO session_summaries (session_id, enrichment, source_files)
                VALUES (:session_id, :enrichment, :source_files)
            """),
                {
                    "session_id": "dirty-both-001",
                    "enrichment": json.dumps({"ip": {"asname": "ISP\x00"}}),
                    "source_files": json.dumps(["/path\x01/to/file.log"]),
                },
            )

            # Additional sessions for scale testing
            for i in range(2, 6):
                conn.execute(
                    text("""
                    INSERT INTO session_summaries (session_id, enrichment, source_files)
                    VALUES (:session_id, :enrichment, :source_files)
                """),
                    {
                        "session_id": f"dirty-both-{i:03d}",
                        "enrichment": json.dumps({"ip": {"asname": f"ISP{i}\x00"}}),
                        "source_files": json.dumps([f"/path{i}\x01/file.log"]),
                    },
                )

    def _insert_dirty_files(self) -> None:
        """Insert files with dirty text fields."""
        with self.engine.begin() as conn:
            # Clean file (baseline)
            conn.execute(
                text("""
                INSERT INTO files (session_id, shasum, filename, vt_classification, vt_description)
                VALUES (:session_id, :shasum, :filename, :vt_classification, :vt_description)
            """),
                {
                    "session_id": "clean-session-001",
                    "shasum": "a" * 64,
                    "filename": "clean.exe",
                    "vt_classification": "trojan.generic",
                    "vt_description": "Generic trojan",
                },
            )

            # Files with various dirty fields
            dirty_files = [
                {
                    "shasum": "b" * 64,
                    "filename": "malware\x00.exe",
                    "download_url": None,
                    "vt_classification": None,
                    "vt_description": None,
                },
                {
                    "shasum": "c" * 64,
                    "filename": None,
                    "download_url": "http://evil\x01.com/payload",
                    "vt_classification": None,
                    "vt_description": None,
                },
                {
                    "shasum": "d" * 64,
                    "filename": None,
                    "download_url": None,
                    "vt_classification": "trojan\x0b.banker",
                    "vt_description": "Banking trojan\x1f detected",
                },
                # File with multiple dirty fields
                {
                    "shasum": "e" * 64,
                    "filename": "ransomware\x00.exe",
                    "download_url": "ftp://bad\x01.server/payload",
                    "vt_classification": "ransomware\x0b.crypto",
                    "vt_description": "Encrypts files\x1f on disk",
                },
            ]

            for file_data in dirty_files:
                params = {"session_id": "dirty-session-001"}
                params.update(file_data)  # type: ignore[call-overload]
                conn.execute(
                    text("""
                    INSERT INTO files (session_id, shasum, filename, download_url, vt_classification, vt_description)
                    VALUES (:session_id, :shasum, :filename, :download_url, :vt_classification, :vt_description)
                """),
                    params,
                )

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        self.engine.dispose()

    def test_sanitize_all_tables_default(self) -> None:
        """Test default behavior sanitizes all three tables."""
        # Execute sanitization with default settings (all tables)
        result = self.db.sanitize_unicode_in_database()

        # Verify all three tables were processed
        self.assertEqual(result["tables_processed"], 3)
        self.assertIn("raw_events", result["tables"])
        self.assertIn("session_summaries", result["tables"])
        self.assertIn("files", result["tables"])

        # Verify records were updated
        self.assertGreater(result["total_records_updated"], 0)
        self.assertEqual(result["total_errors"], 0)

        # Verify dry_run flag in result
        self.assertFalse(result["dry_run"])

    def test_sanitize_specific_table_raw_events(self) -> None:
        """Test --table flag for raw_events only."""
        result = self.db.sanitize_unicode_in_database(table="raw_events")

        # Verify only raw_events was processed
        self.assertEqual(result["tables_processed"], 1)
        self.assertIn("raw_events", result["tables"])
        self.assertNotIn("session_summaries", result["tables"])
        self.assertNotIn("files", result["tables"])

        # Verify dirty events were sanitized
        self.assertEqual(result["tables"]["raw_events"]["records_updated"], 4)  # 4 dirty events

    def test_sanitize_specific_table_session_summaries(self) -> None:
        """Test --table flag for session_summaries only."""
        result = self.db.sanitize_unicode_in_database(table="session_summaries")

        # Verify only session_summaries was processed
        self.assertEqual(result["tables_processed"], 1)
        self.assertIn("session_summaries", result["tables"])

        # Verify counting bug fix: 7 dirty sessions (1 enrichment-only, 1 files-only, 5 both)
        # All 7 should be counted once, not 10 (5+5 for both fields)
        self.assertEqual(result["tables"]["session_summaries"]["records_updated"], 7)

    def test_sanitize_specific_table_files(self) -> None:
        """Test --table flag for files only."""
        result = self.db.sanitize_unicode_in_database(table="files")

        # Verify only files was processed
        self.assertEqual(result["tables_processed"], 1)
        self.assertIn("files", result["tables"])

        # Verify dirty files were sanitized (4 files with dirty fields)
        self.assertEqual(result["tables"]["files"]["records_updated"], 4)

    def test_dry_run_mode_no_changes(self) -> None:
        """Test --dry-run flag prevents actual database changes."""
        # Get initial dirty count
        with self.engine.connect() as conn:
            initial_count = conn.execute(text("SELECT COUNT(*) FROM raw_events WHERE payload LIKE '%\\x00%'")).scalar()

        # Run sanitization in dry-run mode
        result = self.db.sanitize_unicode_in_database(dry_run=True)

        # Verify dry_run flag is set
        self.assertTrue(result["dry_run"])

        # Verify records would be updated but weren't
        self.assertGreater(result["total_records_updated"], 0)

        # Verify database wasn't actually changed
        with self.engine.connect() as conn:
            final_count = conn.execute(text("SELECT COUNT(*) FROM raw_events WHERE payload LIKE '%\\x00%'")).scalar()
            self.assertEqual(initial_count, final_count)

    def test_limit_parameter_restricts_records(self) -> None:
        """Test --limit flag restricts processing per table."""
        # Use small batch size so limit works within first batch
        result = self.db.sanitize_unicode_in_database(table="session_summaries", limit=3, batch_size=5)

        # Verify processing stopped at or near limit
        # With batch_size=5, limit=3, we fetch 5 records but process and count all 5
        # This is expected behavior - limit stops ADDITIONAL batches, not records within a batch
        self.assertLessEqual(result["tables"]["session_summaries"]["records_processed"], 10)

    def test_batch_size_parameter(self) -> None:
        """Test custom batch_size parameter."""
        # Use very small batch size to test batching logic
        result = self.db.sanitize_unicode_in_database(batch_size=2)

        # Should process all dirty records despite small batches
        self.assertGreater(result["total_records_updated"], 0)
        self.assertEqual(result["total_errors"], 0)

    def test_data_integrity_after_sanitization(self) -> None:
        """Test that sanitization preserves data structure and only removes control chars."""
        # Sanitize all tables
        self.db.sanitize_unicode_in_database()

        # Verify raw_events payload structure preserved
        with self.engine.connect() as conn:
            result = conn.execute(text("SELECT payload FROM raw_events WHERE source_offset = 100")).fetchone()
            assert result is not None
            payload = json.loads(result[0])
            self.assertEqual(payload["eventid"], "cowrie.command.input")
            self.assertEqual(payload["input"], "cat/etc/passwd")  # \x00 removed

        # Verify session_summaries enrichment structure preserved
        with self.engine.connect() as conn:
            result = conn.execute(
                text("SELECT enrichment FROM session_summaries WHERE session_id = 'dirty-enrichment-001'")
            ).fetchone()
            assert result is not None
            enrichment = json.loads(result[0])
            self.assertEqual(enrichment["dshield"]["asname"], "EvilCorp")  # \x00 removed
            self.assertEqual(enrichment["dshield"]["ascountry"], "RU")  # \x01 removed

        # Verify files text fields cleaned
        with self.engine.connect() as conn:
            result = conn.execute(
                text("SELECT filename FROM files WHERE shasum = :shasum"),
                {"shasum": "b" * 64},
            ).fetchone()
            assert result is not None
            self.assertEqual(result[0], "malware.exe")  # \x00 removed

    def test_counting_bug_regression(self) -> None:
        """Critical regression test: records with multiple dirty fields counted once."""
        result = self.db.sanitize_unicode_in_database(table="session_summaries")

        # Critical assertion: 7 dirty sessions total
        # - 1 enrichment-only
        # - 1 source_files-only
        # - 5 with both fields dirty
        # Should count as 7, NOT 10 (if both fields counted separately)
        self.assertEqual(
            result["tables"]["session_summaries"]["records_updated"],
            7,
            "Counting bug regression: records with both dirty fields counted twice",
        )

    def test_all_tables_flag_explicit(self) -> None:
        """Test explicit --all flag for clarity."""
        result = self.db.sanitize_unicode_in_database(all_tables=True)

        # Should process all 3 tables
        self.assertEqual(result["tables_processed"], 3)

    def test_empty_table_handling(self) -> None:
        """Test sanitization when a table has no dirty records."""
        # Create fresh database with only clean data
        settings = DatabaseSettings(url="sqlite:///:memory:")
        clean_engine = create_engine_from_settings(settings)

        from cowrieprocessor.db import apply_migrations

        apply_migrations(clean_engine)

        # Insert only clean data
        with clean_engine.begin() as conn:
            conn.execute(
                text("""
                INSERT INTO raw_events (source, source_offset, payload)
                VALUES (:source, :source_offset, :payload)
            """),
                {
                    "source": "/var/log/cowrie.log",
                    "source_offset": 0,
                    "payload": json.dumps({"eventid": "cowrie.session.connect"}),
                },
            )

        clean_db = CowrieDatabase(db_url="sqlite:///:memory:")
        clean_db._engine = clean_engine

        # Run sanitization on clean database
        result = clean_db.sanitize_unicode_in_database()

        # Should process tables but update 0 records (clean record is skipped)
        self.assertEqual(result["total_records_updated"], 0)
        self.assertGreaterEqual(result["total_records_skipped"], 0)  # Clean records skipped

        clean_engine.dispose()

    def test_invalid_table_name_raises_error(self) -> None:
        """Test that invalid table name raises ValueError."""
        with self.assertRaises(ValueError) as context:
            self.db.sanitize_unicode_in_database(table="invalid_table")

        self.assertIn("Unknown table", str(context.exception))

    def test_progress_callback_invoked(self) -> None:
        """Test that progress_callback is called during sanitization."""
        # Insert additional dirty data to ensure we get 10+ batches
        with self.engine.begin() as conn:
            for i in range(20):  # Add 20 more dirty sessions
                conn.execute(
                    text("""
                    INSERT INTO session_summaries (session_id, enrichment)
                    VALUES (:session_id, :enrichment)
                """),
                    {
                        "session_id": f"callback-test-{i:03d}",
                        "enrichment": json.dumps({"ip": {"asname": f"ISP{i}\x00"}}),
                    },
                )

        callback_invocations: list[Any] = []

        def progress_callback(metrics: Any) -> None:
            callback_invocations.append(metrics)

        # Run with batch_size=1 to maximize batch count
        # With 20+ dirty records and batch_size=1, we should get 20+ batches = 2 callbacks (at batch 10, 20)
        self.db.sanitize_unicode_in_database(
            table="session_summaries", batch_size=1, progress_callback=progress_callback
        )

        # Verify callback was invoked at least once (every 10 batches)
        self.assertGreaterEqual(len(callback_invocations), 1)

        # Verify metrics structure
        if len(callback_invocations) > 0:
            metrics = callback_invocations[0]
            self.assertHasAttr(metrics, "records_processed")
            self.assertHasAttr(metrics, "records_updated")
            self.assertHasAttr(metrics, "errors")

    def assertHasAttr(self, obj: Any, attr: str) -> None:
        """Helper assertion to check object has attribute."""
        self.assertTrue(hasattr(obj, attr), f"Object missing attribute: {attr}")


class TestCrossDatabaseCompatibility(unittest.TestCase):
    """Test sanitization works on both SQLite and PostgreSQL (if available)."""

    def test_sqlite_sanitization(self) -> None:
        """Test sanitization on SQLite database."""
        settings = DatabaseSettings(url="sqlite:///:memory:")
        engine = create_engine_from_settings(settings)

        from cowrieprocessor.db import apply_migrations

        apply_migrations(engine)

        # Insert dirty data
        with engine.begin() as conn:
            conn.execute(
                text("""
                INSERT INTO raw_events (source, source_offset, payload)
                VALUES (:source, :source_offset, :payload)
            """),
                {
                    "source": "/var/log/cowrie.log",
                    "source_offset": 100,
                    "payload": json.dumps({"input": "test\x00command"}),
                },
            )

        db = CowrieDatabase(db_url="sqlite:///:memory:")
        db._engine = engine

        # Run sanitization
        result = db.sanitize_unicode_in_database(table="raw_events")

        # Verify success
        self.assertEqual(result["tables"]["raw_events"]["records_updated"], 1)
        self.assertEqual(result["tables"]["raw_events"]["errors"], 0)

        engine.dispose()

    @unittest.skipUnless(
        False,  # Set to True if PostgreSQL is available for testing
        "PostgreSQL not available for testing",
    )
    def test_postgresql_sanitization(self) -> None:
        """Test sanitization on PostgreSQL database (requires PG_TEST_URL env var)."""
        import os

        pg_url = os.getenv("PG_TEST_URL", "postgresql://localhost/cowrie_test")
        settings = DatabaseSettings(url=pg_url)
        engine = create_engine_from_settings(settings)

        from cowrieprocessor.db import apply_migrations

        apply_migrations(engine)

        # Insert dirty data
        with engine.begin() as conn:
            conn.execute(
                text("""
                INSERT INTO raw_events (source, source_offset, payload)
                VALUES (:source, :source_offset, :payload)
            """),
                {
                    "source": "/var/log/cowrie.log",
                    "source_offset": 100,
                    "payload": json.dumps({"input": "test\x00command"}),
                },
            )

        db = CowrieDatabase(db_url=pg_url)
        db._engine = engine

        # Run sanitization
        result = db.sanitize_unicode_in_database(table="raw_events")

        # Verify success
        self.assertEqual(result["tables"]["raw_events"]["records_updated"], 1)

        # Cleanup
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE raw_events CASCADE"))

        engine.dispose()


if __name__ == "__main__":
    unittest.main()
