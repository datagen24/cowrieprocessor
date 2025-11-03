"""Unit tests for file metadata sanitization (Phase 1)."""

from __future__ import annotations

import unittest

from cowrieprocessor.loader.file_processor import extract_file_data


class TestFileMetadataSanitization(unittest.TestCase):
    """Test Unicode sanitization in file metadata extraction."""

    def test_filename_sanitization_removes_null_bytes(self) -> None:
        """Test that filenames with null bytes are sanitized."""
        event_payload = {
            "eventid": "cowrie.session.file_download",
            "shasum": "a" * 64,  # Valid SHA-256
            "filename": "malicious\x00file.exe",
            "size": 1024,
            "url": "http://example.com/file.exe",
            "timestamp": "2024-11-03T12:00:00Z",
        }

        result = extract_file_data(event_payload, "session123")

        self.assertIsNotNone(result)
        self.assertEqual(result["filename"], "maliciousfile.exe")
        self.assertNotIn("\x00", result["filename"])

    def test_url_sanitization_removes_control_chars(self) -> None:
        """Test that download URLs with control characters are sanitized."""
        event_payload = {
            "eventid": "cowrie.session.file_download",
            "shasum": "b" * 64,
            "filename": "file.exe",
            "size": 2048,
            "url": "http://evil\x00.com/\x01malware.exe",
            "timestamp": "2024-11-03T12:00:00Z",
        }

        result = extract_file_data(event_payload, "session123")

        self.assertIsNotNone(result)
        self.assertEqual(result["download_url"], "http://evil.com/malware.exe")
        self.assertNotIn("\x00", result["download_url"])
        self.assertNotIn("\x01", result["download_url"])

    def test_filename_and_url_sanitization_together(self) -> None:
        """Test sanitization of both filename and URL with multiple control chars."""
        event_payload = {
            "eventid": "cowrie.session.file_download",
            "shasum": "c" * 64,
            "filename": "\x00\x01trojan\x02.exe\x03",
            "size": 4096,
            "url": "http://\x00bad\x01site\x02.com/\x03file",
            "timestamp": "2024-11-03T12:00:00Z",
        }

        result = extract_file_data(event_payload, "session123")

        self.assertIsNotNone(result)
        # All control chars removed, stripped
        self.assertEqual(result["filename"], "trojan.exe")
        self.assertEqual(result["download_url"], "http://badsite.com/file")

    def test_sanitization_preserves_clean_data(self) -> None:
        """Test that clean filenames and URLs are preserved."""
        event_payload = {
            "eventid": "cowrie.session.file_download",
            "shasum": "d" * 64,
            "filename": "clean_file.exe",
            "size": 8192,
            "url": "http://example.com/downloads/file.exe",
            "timestamp": "2024-11-03T12:00:00Z",
        }

        result = extract_file_data(event_payload, "session123")

        self.assertIsNotNone(result)
        self.assertEqual(result["filename"], "clean_file.exe")
        self.assertEqual(result["download_url"], "http://example.com/downloads/file.exe")

    def test_none_values_handled_correctly(self) -> None:
        """Test that None filename/URL values are handled."""
        event_payload = {
            "eventid": "cowrie.session.file_download",
            "shasum": "e" * 64,
            # No filename or url fields
            "size": 1024,
            "timestamp": "2024-11-03T12:00:00Z",
        }

        result = extract_file_data(event_payload, "session123")

        self.assertIsNotNone(result)
        self.assertIsNone(result["filename"])
        self.assertIsNone(result["download_url"])

    def test_length_limits_still_enforced(self) -> None:
        """Test that length limits are still enforced after sanitization."""
        long_filename = "a" * 600  # Exceeds 512 char limit
        long_url = "http://example.com/" + "b" * 1100  # Exceeds 1024 char limit

        event_payload = {
            "eventid": "cowrie.session.file_download",
            "shasum": "f" * 64,
            "filename": long_filename,
            "url": long_url,
            "size": 1024,
            "timestamp": "2024-11-03T12:00:00Z",
        }

        result = extract_file_data(event_payload, "session123")

        self.assertIsNotNone(result)
        self.assertLessEqual(len(result["filename"]), 512)
        self.assertLessEqual(len(result["download_url"]), 1024)

    def test_sanitization_before_length_truncation(self) -> None:
        """Test that sanitization happens before length truncation."""
        # Filename with null bytes that will be truncated
        filename_with_nulls = "\x00" * 10 + "valid_part" + "a" * 600

        event_payload = {
            "eventid": "cowrie.session.file_download",
            "shasum": "1" * 64,
            "filename": filename_with_nulls,
            "size": 1024,
            "timestamp": "2024-11-03T12:00:00Z",
        }

        result = extract_file_data(event_payload, "session123")

        self.assertIsNotNone(result)
        # Null bytes removed, then truncated to 512
        self.assertNotIn("\x00", result["filename"])
        self.assertLessEqual(len(result["filename"]), 512)
        self.assertTrue(result["filename"].startswith("valid_part"))


if __name__ == "__main__":
    unittest.main()
