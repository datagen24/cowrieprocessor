"""Integration tests for Phase 1 Unicode sanitization end-to-end flow."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from cowrieprocessor.enrichment.handlers import EnrichmentService
from cowrieprocessor.loader.bulk import BulkLoader, BulkLoaderConfig
from cowrieprocessor.loader.file_processor import extract_file_data


class TestPhase1SanitizationE2E(unittest.TestCase):
    """End-to-end tests for Phase 1 ingestion-time Unicode sanitization.

    These tests validate that sanitization works correctly through the complete pipeline:
    1. API responses are sanitized before storage
    2. File metadata is sanitized during extraction
    3. Source files are sanitized during aggregation
    """

    def setUp(self) -> None:
        """Set up test fixtures."""
        # Create temporary cache directory
        self.temp_dir = tempfile.mkdtemp()

        # Create EnrichmentService
        self.enrichment = EnrichmentService(
            cache_dir=Path(self.temp_dir),
            vt_api=None,
            dshield_email="test@example.com",
            urlhaus_api="test_key",
            spur_api="test_key",
            skip_enrich=False,
            enable_rate_limiting=False,
            enable_telemetry=False,
        )

        # Create BulkLoader (engine not needed for sanitization method testing)
        self.loader = BulkLoader(None, BulkLoaderConfig())  # type: ignore[arg-type]

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_enrichment_pipeline_sanitizes_dshield_response(self) -> None:
        """Test that DShield API response goes through complete sanitization pipeline.

        Pipeline flow:
        1. Mock API returns dirty data with null bytes
        2. _enrich_with_hybrid_cache() calls _sanitize_enrichment()
        3. Sanitized data is returned and stored in cache
        4. Verify no Unicode control chars remain in result
        """

        # Mock API call returning dirty data
        def mock_dshield_api() -> dict[str, Any]:
            return {
                "ip": {
                    "asname": "Evil\x00Corp\x01",
                    "ascountry": "US\x00",
                    "asnum": "12345\x00",
                }
            }

        # Mock cache miss to force API call and sanitization
        with patch.object(self.enrichment.cache_manager, "get_cached", return_value=None):
            with patch.object(self.enrichment.cache_manager, "store_cached") as mock_store:
                result = self.enrichment._enrich_with_hybrid_cache("dshield", "192.168.1.1", mock_dshield_api, {})

        # Verify sanitization happened
        self.assertEqual(result["ip"]["asname"], "EvilCorp")
        self.assertEqual(result["ip"]["ascountry"], "US")
        self.assertEqual(result["ip"]["asnum"], "12345")

        # Verify no null bytes remain anywhere in the structure
        import json

        json_str = json.dumps(result)
        self.assertNotIn("\\u0000", json_str)
        self.assertNotIn("\\x00", json_str)

        # Verify sanitized data was stored in cache (not dirty data)
        mock_store.assert_called_once()
        stored_data = mock_store.call_args[0][2]  # Third argument is the data
        self.assertEqual(stored_data["ip"]["asname"], "EvilCorp")

    def test_enrichment_pipeline_sanitizes_urlhaus_response(self) -> None:
        """Test that URLHaus API response goes through complete sanitization pipeline."""

        # Mock API returning dirty tags
        def mock_urlhaus_api() -> dict[str, Any]:
            return {"tags": "malware\x00,phishing\x01,trojan\x02"}

        # Mock cache miss
        with patch.object(self.enrichment.cache_manager, "get_cached", return_value=None):
            with patch.object(self.enrichment.cache_manager, "store_cached"):
                result = self.enrichment._enrich_with_hybrid_cache(
                    "urlhaus", "http://evil.com", mock_urlhaus_api, {"tags": ""}
                )

        # Verify all control chars removed
        self.assertNotIn("\x00", result["tags"])
        self.assertNotIn("\x01", result["tags"])
        self.assertNotIn("\x02", result["tags"])
        self.assertEqual(result["tags"], "malware,phishing,trojan")

    def test_enrichment_pipeline_sanitizes_spur_response(self) -> None:
        """Test that SPUR API response goes through complete sanitization pipeline."""

        # Mock API returning dirty list data
        def mock_spur_api() -> dict[str, Any]:
            return {
                "spur_data": [
                    "ISP\x00Name",  # organization
                    [],  # behaviors
                    "",  # concentration country
                    "",  # geohash
                    "",  # skew
                    "",  # countries
                    "",  # count
                    [],  # proxies
                    "",  # spread
                    [],  # types
                    "",  # infrastructure
                    "New\x00York",  # city
                    "US\x01",  # country
                ]
            }

        # Mock cache miss
        with patch.object(self.enrichment.cache_manager, "get_cached", return_value=None):
            with patch.object(self.enrichment.cache_manager, "store_cached"):
                result = self.enrichment._enrich_with_hybrid_cache("spur", "10.0.0.1", mock_spur_api, {"spur_data": []})

        # Verify sanitization of list elements
        spur_data = result["spur_data"]
        self.assertEqual(spur_data[0], "ISPName")  # organization
        self.assertEqual(spur_data[11], "NewYork")  # city
        self.assertEqual(spur_data[12], "US")  # country

    def test_cached_enrichment_data_is_sanitized_on_retrieval(self) -> None:
        """Test that pre-existing dirty cached data is sanitized when retrieved.

        This ensures backward compatibility - old cache entries from before Phase 1
        are sanitized when retrieved, preventing Unicode errors.
        """
        # Mock cached data with null bytes (simulating old cache entry)
        dirty_cached_data = {
            "ip": {
                "asname": "Cached\x00ISP",
                "ascountry": "DE\x00",
            }
        }

        # Mock cache hit with dirty data
        with patch.object(self.enrichment.cache_manager, "get_cached", return_value=dirty_cached_data):
            result = self.enrichment._enrich_with_hybrid_cache("dshield", "10.0.0.1", lambda: {}, {})

        # Verify cached data was sanitized before return
        self.assertEqual(result["ip"]["asname"], "CachedISP")
        self.assertEqual(result["ip"]["ascountry"], "DE")

    def test_file_metadata_extraction_sanitizes_filename(self) -> None:
        """Test that file download event extraction sanitizes filename.

        Pipeline flow:
        1. Cowrie captures file download with dirty filename
        2. extract_file_data() calls UnicodeSanitizer
        3. Sanitized filename is returned
        """
        # Create event with malicious filename
        dirty_event = {
            "eventid": "cowrie.session.file_download",
            "shasum": "a" * 64,
            "filename": "\x00\x01malicious\x02.exe\x03",
            "size": 1024,
            "url": "http://clean.com/file.exe",
            "timestamp": "2024-11-03T12:00:00Z",
        }

        # Extract and verify sanitization
        file_data = extract_file_data(dirty_event, "test-session-1")

        self.assertIsNotNone(file_data)
        self.assertEqual(file_data["filename"], "malicious.exe")
        self.assertNotIn("\x00", file_data["filename"])
        self.assertNotIn("\x01", file_data["filename"])

    def test_file_metadata_extraction_sanitizes_url(self) -> None:
        """Test that file download event extraction sanitizes URL."""
        # Create event with malicious URL
        dirty_event = {
            "eventid": "cowrie.session.file_download",
            "shasum": "b" * 64,
            "filename": "clean.exe",
            "size": 2048,
            "url": "http://\x00evil\x01.com/\x02malware.exe",
            "timestamp": "2024-11-03T12:00:00Z",
        }

        # Extract and verify sanitization
        file_data = extract_file_data(dirty_event, "test-session-1")

        self.assertIsNotNone(file_data)
        self.assertEqual(file_data["download_url"], "http://evil.com/malware.exe")
        self.assertNotIn("\x00", file_data["download_url"])
        self.assertNotIn("\x01", file_data["download_url"])

    def test_file_metadata_extraction_sanitizes_both_fields(self) -> None:
        """Test sanitization of both filename and URL with multiple control chars."""
        dirty_event = {
            "eventid": "cowrie.session.file_download",
            "shasum": "c" * 64,
            "filename": "\x00\x01trojan\x02.exe\x03",
            "size": 4096,
            "url": "http://\x00bad\x01site\x02.com/\x03file",
            "timestamp": "2024-11-03T12:00:00Z",
        }

        file_data = extract_file_data(dirty_event, "test-session-1")

        self.assertIsNotNone(file_data)
        # All control chars removed, stripped
        self.assertEqual(file_data["filename"], "trojan.exe")
        self.assertEqual(file_data["download_url"], "http://badsite.com/file")

    def test_source_files_sanitization_removes_null_bytes(self) -> None:
        """Test that session source file paths are sanitized.

        Pipeline flow:
        1. Session aggregator collects source files with dirty paths
        2. _sanitize_source_files() is called
        3. Clean paths are returned for storage
        """
        # Create dirty source files set
        dirty_files = {
            "/path/to/\x00file1.log",
            "/path/\x01to/file2.log",
            "/clean/path/file3.log",
        }

        # Sanitize
        sanitized = self.loader._sanitize_source_files(dirty_files)

        # Verify sanitization
        self.assertIsNotNone(sanitized)
        self.assertEqual(len(sanitized), 3)
        self.assertIn("/path/to/file1.log", sanitized)
        self.assertIn("/path/to/file2.log", sanitized)
        self.assertIn("/clean/path/file3.log", sanitized)

        # Verify sorted
        self.assertEqual(sanitized[0], "/clean/path/file3.log")

    def test_source_files_sanitization_removes_multiple_control_chars(self) -> None:
        """Test removal of multiple different control characters from file paths."""
        dirty_files = {
            "/path\x00/with\x01/many\x02/control\x03/chars.log",
        }

        sanitized = self.loader._sanitize_source_files(dirty_files)

        self.assertIsNotNone(sanitized)
        self.assertEqual(len(sanitized), 1)
        self.assertEqual(sanitized[0], "/path/with/many/control/chars.log")

        # Verify no control chars remain
        for char_code in range(0x00, 0x20):
            if char_code not in (0x09, 0x0A, 0x0D):  # Preserve tabs, newlines
                self.assertNotIn(chr(char_code), sanitized[0])

    def test_full_pipeline_all_sanitization_points(self) -> None:
        """Integration test validating all three sanitization points work together.

        This is the comprehensive test covering:
        1. Enrichment API response sanitization (DShield, URLHaus, SPUR)
        2. File metadata sanitization (filename, URL)
        3. Source files sanitization (log paths)
        """

        # 1. Test enrichment sanitization
        def mock_dshield_api() -> dict[str, Any]:
            return {"ip": {"asname": "Test\x00ISP", "ascountry": "US\x00"}}

        with patch.object(self.enrichment.cache_manager, "get_cached", return_value=None):
            with patch.object(self.enrichment.cache_manager, "store_cached"):
                enrichment_result = self.enrichment._enrich_with_hybrid_cache(
                    "dshield", "192.168.1.1", mock_dshield_api, {}
                )

        # 2. Test file metadata sanitization
        dirty_file_event = {
            "eventid": "cowrie.session.file_download",
            "shasum": "d" * 64,
            "filename": "trojan\x00.exe",
            "size": 8192,
            "url": "http://bad\x00site.com/malware",
            "timestamp": "2024-11-03T12:00:00Z",
        }
        file_result = extract_file_data(dirty_file_event, "test-session")

        # 3. Test source files sanitization
        dirty_source_files = {"/var/log/\x00cowrie.log", "/tmp/\x01session.json"}
        source_files_result = self.loader._sanitize_source_files(dirty_source_files)

        # Verify all sanitization worked
        self.assertEqual(enrichment_result["ip"]["asname"], "TestISP")
        self.assertIsNotNone(file_result)
        self.assertEqual(file_result["filename"], "trojan.exe")
        self.assertIsNotNone(source_files_result)
        self.assertEqual(len(source_files_result), 2)

        # Verify no control chars remain in any output
        import json

        # Check enrichment
        enrichment_json = json.dumps(enrichment_result)
        self.assertNotIn("\\x00", enrichment_json)

        # Check file metadata
        self.assertNotIn("\x00", file_result["filename"])
        self.assertNotIn("\x00", file_result["download_url"])

        # Check source files
        for path in source_files_result:
            self.assertNotIn("\x00", path)
            self.assertNotIn("\x01", path)


if __name__ == "__main__":
    unittest.main()
