"""Unit tests for ORM-level Unicode sanitization listeners (Phase 2)."""

from __future__ import annotations

import unittest

from cowrieprocessor.db import sanitization_listeners
from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.db.models import Files, SessionSummary
from cowrieprocessor.settings import DatabaseSettings


class TestORMSanitizationListeners(unittest.TestCase):
    """Test SQLAlchemy event listeners for automatic Unicode sanitization."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        # Create in-memory SQLite engine with ORM sanitization ENABLED
        settings = DatabaseSettings(url="sqlite:///:memory:", enable_orm_sanitization=True)
        self.engine = create_engine_from_settings(settings)

        # Initialize migrations
        from cowrieprocessor.db import apply_migrations

        apply_migrations(self.engine)

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        self.engine.dispose()

    def test_enrichment_listener_fires_on_assignment(self) -> None:
        """Test that enrichment listener fires when assigning to SessionSummary.enrichment."""
        # Create a SessionSummary instance
        session = SessionSummary(session_id="test-session-1")

        # Assign dirty data with null bytes
        dirty_enrichment = {
            "dshield": {
                "asname": "Test\x00ISP",
                "ascountry": "US\x00",
            }
        }

        session.enrichment = dirty_enrichment

        # Verify listener sanitized the data
        self.assertIsNotNone(session.enrichment)
        self.assertEqual(session.enrichment["dshield"]["asname"], "TestISP")  # type: ignore[index]
        self.assertEqual(session.enrichment["dshield"]["ascountry"], "US")  # type: ignore[index]

        # Verify no null bytes remain
        import json

        enrichment_json = json.dumps(session.enrichment)
        self.assertNotIn("\\x00", enrichment_json)

    def test_source_files_listener_fires_on_assignment(self) -> None:
        """Test that source_files listener fires when assigning to SessionSummary.source_files."""
        session = SessionSummary(session_id="test-session-2")

        # Assign dirty list with null bytes
        dirty_files = ["/path/to/\x00file1.log", "/path/\x01to/file2.log"]

        session.source_files = dirty_files  # type: ignore[assignment]

        # Verify listener sanitized the data
        self.assertIsNotNone(session.source_files)
        self.assertEqual(len(session.source_files), 2)  # type: ignore[arg-type]
        self.assertEqual(session.source_files[0], "/path/to/file1.log")  # type: ignore[index]
        self.assertEqual(session.source_files[1], "/path/to/file2.log")  # type: ignore[index]

    def test_filename_listener_fires_on_assignment(self) -> None:
        """Test that filename listener fires when assigning to Files.filename."""
        file_record = Files(
            session_id="test-session",
            shasum="a" * 64,
        )

        # Assign dirty filename
        file_record.filename = "malware\x00.exe"

        # Verify listener sanitized the data
        self.assertEqual(file_record.filename, "malware.exe")

    def test_download_url_listener_fires_on_assignment(self) -> None:
        """Test that download_url listener fires when assigning to Files.download_url."""
        file_record = Files(
            session_id="test-session",
            shasum="b" * 64,
        )

        # Assign dirty URL
        file_record.download_url = "http://evil\x00.com/malware"

        # Verify listener sanitized the data
        self.assertEqual(file_record.download_url, "http://evil.com/malware")

    def test_vt_classification_listener_fires_on_assignment(self) -> None:
        """Test that vt_classification listener fires when assigning to Files.vt_classification."""
        file_record = Files(
            session_id="test-session",
            shasum="c" * 64,
        )

        # Assign dirty classification
        file_record.vt_classification = "trojan\x00.generic"

        # Verify listener sanitized the data
        self.assertEqual(file_record.vt_classification, "trojan.generic")

    def test_vt_description_listener_fires_on_assignment(self) -> None:
        """Test that vt_description listener fires when assigning to Files.vt_description."""
        file_record = Files(
            session_id="test-session",
            shasum="d" * 64,
        )

        # Assign dirty description
        file_record.vt_description = "Malicious file\x00 detected by VirusTotal"

        # Verify listener sanitized the data
        self.assertEqual(file_record.vt_description, "Malicious file detected by VirusTotal")

    def test_listeners_handle_none_values(self) -> None:
        """Test that listeners correctly handle None values without errors."""
        session = SessionSummary(session_id="test-session-3")

        # Assign None values (should not raise)
        session.enrichment = None
        session.source_files = None

        self.assertIsNone(session.enrichment)
        self.assertIsNone(session.source_files)

        file_record = Files(
            session_id="test-session",
            shasum="e" * 64,
        )

        file_record.filename = None
        file_record.download_url = None
        file_record.vt_classification = None
        file_record.vt_description = None

        self.assertIsNone(file_record.filename)
        self.assertIsNone(file_record.download_url)
        self.assertIsNone(file_record.vt_classification)
        self.assertIsNone(file_record.vt_description)

    def test_listeners_preserve_clean_data(self) -> None:
        """Test that listeners don't corrupt clean data."""
        session = SessionSummary(session_id="test-session-4")

        # Assign clean data
        clean_enrichment = {
            "dshield": {
                "asname": "CleanISP",
                "ascountry": "US",
            }
        }

        session.enrichment = clean_enrichment

        # Verify data is unchanged
        self.assertEqual(session.enrichment, clean_enrichment)

        # Clean source files
        clean_files = ["/var/log/cowrie.log", "/tmp/session.json"]
        session.source_files = clean_files  # type: ignore[assignment]

        self.assertEqual(session.source_files, clean_files)

    def test_nested_structure_sanitization(self) -> None:
        """Test that deeply nested structures are sanitized correctly."""
        session = SessionSummary(session_id="test-session-5")

        # Assign deeply nested dirty data
        dirty_enrichment = {
            "level1": {
                "level2": {
                    "level3": {
                        "value": "deep\x00value",
                        "list": ["item\x00one", "item\x01two"],
                    }
                }
            }
        }

        session.enrichment = dirty_enrichment

        # Verify nested sanitization
        self.assertEqual(
            session.enrichment["level1"]["level2"]["level3"]["value"],  # type: ignore[index]
            "deepvalue",
        )
        self.assertEqual(
            session.enrichment["level1"]["level2"]["level3"]["list"][0],  # type: ignore[index]
            "itemone",
        )
        self.assertEqual(
            session.enrichment["level1"]["level2"]["level3"]["list"][1],  # type: ignore[index]
            "itemtwo",
        )

    def test_feature_flag_disables_listeners(self) -> None:
        """Test that feature flag can disable sanitization listeners."""
        # Create engine with sanitization DISABLED
        settings_disabled = DatabaseSettings(url="sqlite:///:memory:", enable_orm_sanitization=False)
        engine_disabled = create_engine_from_settings(settings_disabled)

        from cowrieprocessor.db import apply_migrations

        apply_migrations(engine_disabled)

        # Manually set listeners to disabled
        sanitization_listeners.set_listeners_enabled(False)

        # Create instance and assign dirty data
        session = SessionSummary(session_id="test-session-disabled")
        dirty_enrichment = {"field": "value\x00"}

        session.enrichment = dirty_enrichment

        # With listeners disabled, data should NOT be sanitized
        self.assertEqual(session.enrichment["field"], "value\x00")  # type: ignore[index]

        # Re-enable for other tests
        sanitization_listeners.set_listeners_enabled(True)
        engine_disabled.dispose()

    def test_multiple_assignments_sanitize_correctly(self) -> None:
        """Test that multiple assignments to the same field are sanitized."""
        session = SessionSummary(session_id="test-session-6")

        # First assignment
        session.enrichment = {"value": "first\x00"}
        self.assertEqual(session.enrichment["value"], "first")  # type: ignore[index]

        # Second assignment
        session.enrichment = {"value": "second\x00"}
        self.assertEqual(session.enrichment["value"], "second")  # type: ignore[index]

        # Third assignment with different control char
        session.enrichment = {"value": "third\x01"}
        self.assertEqual(session.enrichment["value"], "third")  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
