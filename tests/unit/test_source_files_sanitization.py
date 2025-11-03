"""Unit tests for source_files sanitization (Phase 1)."""

from __future__ import annotations

import unittest

from cowrieprocessor.loader.bulk import BulkLoader, BulkLoaderConfig


class TestSourceFilesSanitization(unittest.TestCase):
    """Test Unicode sanitization in session source_files."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        from cowrieprocessor.db.engine import create_engine_from_settings
        from cowrieprocessor.settings import DatabaseSettings

        # Create in-memory SQLite engine for testing
        settings = DatabaseSettings(url="sqlite:///:memory:")
        engine = create_engine_from_settings(settings)

        # Initialize migrations
        from cowrieprocessor.db import apply_migrations

        apply_migrations(engine)

        self.loader = BulkLoader(engine, BulkLoaderConfig())

    def test_sanitize_source_files_removes_null_bytes(self) -> None:
        """Test that source file paths with null bytes are sanitized."""
        dirty_files = {
            "/path/to/\x00file1.log",
            "/path/\x01to/file2.log",
            "/clean/path/file3.log",
        }

        result = self.loader._sanitize_source_files(dirty_files)

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 3)
        self.assertIn("/path/to/file1.log", result)
        self.assertIn("/path/to/file2.log", result)
        self.assertIn("/clean/path/file3.log", result)

    def test_sanitize_source_files_returns_sorted_list(self) -> None:
        """Test that result is sorted alphabetically."""
        files = {
            "/zzz/file.log",
            "/aaa/file.log",
            "/mmm/file.log",
        }

        result = self.loader._sanitize_source_files(files)

        self.assertIsNotNone(result)
        self.assertEqual(result[0], "/aaa/file.log")
        self.assertEqual(result[1], "/mmm/file.log")
        self.assertEqual(result[2], "/zzz/file.log")

    def test_sanitize_source_files_handles_empty_set(self) -> None:
        """Test that empty set returns None."""
        empty_files: set[str] = set()

        result = self.loader._sanitize_source_files(empty_files)

        self.assertIsNone(result)

    def test_sanitize_source_files_removes_multiple_control_chars(self) -> None:
        """Test removal of multiple different control characters."""
        files = {
            "/path\x00/with\x01/many\x02/control\x03/chars.log",
        }

        result = self.loader._sanitize_source_files(files)

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "/path/with/many/control/chars.log")
        # Verify no control chars remain
        for char_code in range(0x00, 0x20):
            if char_code not in (0x09, 0x0A, 0x0D):  # Preserve tabs, newlines
                self.assertNotIn(chr(char_code), result[0])

    def test_sanitize_source_files_preserves_clean_paths(self) -> None:
        """Test that clean paths are preserved exactly."""
        clean_files = {
            "/var/log/cowrie/cowrie.log",
            "/home/user/honeypot/logs/session.json",
            "/tmp/test_data/events.json.bz2",
        }

        result = self.loader._sanitize_source_files(clean_files)

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 3)
        # All original paths should be present (sorted)
        for path in clean_files:
            self.assertIn(path, result)


if __name__ == "__main__":
    unittest.main()
