"""Unit tests for enrichment API sanitization (Phase 1)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from cowrieprocessor.enrichment.handlers import EnrichmentService


class TestEnrichmentSanitization(unittest.TestCase):
    """Test Unicode sanitization in enrichment API responses."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        # Create temporary cache directory
        self.temp_dir = tempfile.mkdtemp()

        # Create EnrichmentService with skip_enrich=False to allow API calls
        self.service = EnrichmentService(
            cache_dir=Path(self.temp_dir),
            vt_api=None,
            dshield_email="test@example.com",
            urlhaus_api="test_key",
            spur_api="test_key",
            skip_enrich=False,
            enable_rate_limiting=False,
            enable_telemetry=False,
        )

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sanitize_enrichment_removes_null_bytes(self) -> None:
        """Test that _sanitize_enrichment removes null bytes from dict values."""
        dirty_data = {
            "country": "US\x00",
            "asn": "AS12345\x00\x01",
            "nested": {"field": "value\x00"},
        }

        clean_data = self.service._sanitize_enrichment(dirty_data)

        self.assertEqual(clean_data["country"], "US")
        self.assertEqual(clean_data["asn"], "AS12345")
        self.assertEqual(clean_data["nested"]["field"], "value")

    def test_sanitize_enrichment_handles_nested_structures(self) -> None:
        """Test sanitization of deeply nested dictionaries and lists."""
        dirty_data = {
            "level1": {"level2": {"level3": "deep\x00value"}},
            "list_field": [
                {"item": "one\x00"},
                {"item": "two\x01"},
            ],
        }

        clean_data = self.service._sanitize_enrichment(dirty_data)

        self.assertEqual(clean_data["level1"]["level2"]["level3"], "deepvalue")
        self.assertEqual(clean_data["list_field"][0]["item"], "one")
        self.assertEqual(clean_data["list_field"][1]["item"], "two")

    def test_sanitize_enrichment_preserves_clean_data(self) -> None:
        """Test that clean data is preserved unchanged."""
        clean_data = {
            "country": "US",
            "asn": "AS12345",
            "nested": {"field": "value"},
        }

        result = self.service._sanitize_enrichment(clean_data)

        self.assertEqual(result, clean_data)

    def test_dshield_api_response_sanitization_via_hybrid_cache(self) -> None:
        """Test that DShield API responses are sanitized through hybrid cache method."""

        def mock_api_call() -> dict[str, Any]:
            return {
                "ip": {
                    "asname": "Evil\x00Corp",
                    "ascountry": "US\x00",
                }
            }

        # Mock cache miss to force API call and sanitization
        with patch.object(self.service.cache_manager, 'get_cached', return_value=None):
            with patch.object(self.service.cache_manager, 'store_cached') as mock_store:
                result = self.service._enrich_with_hybrid_cache("dshield", "192.168.1.1", mock_api_call, {})

        # Verify sanitization happened
        self.assertEqual(result["ip"]["asname"], "EvilCorp")
        self.assertEqual(result["ip"]["ascountry"], "US")
        # Verify sanitized data was stored in cache
        mock_store.assert_called_once()
        stored_data = mock_store.call_args[0][2]  # Third argument is the data
        self.assertEqual(stored_data["ip"]["asname"], "EvilCorp")

    def test_urlhaus_api_response_sanitization_via_hybrid_cache(self) -> None:
        """Test that URLHaus API responses are sanitized through hybrid cache method."""

        def mock_api_call() -> dict[str, Any]:
            return {"tags": "malware\x00,phishing\x01"}

        # Mock cache miss to force API call and sanitization
        with patch.object(self.service.cache_manager, 'get_cached', return_value=None):
            with patch.object(self.service.cache_manager, 'store_cached'):
                result = self.service._enrich_with_hybrid_cache("urlhaus", "192.168.1.1", mock_api_call, {"tags": ""})

        # Verify sanitization happened
        self.assertNotIn("\x00", result["tags"])
        self.assertNotIn("\x01", result["tags"])

    def test_spur_api_response_sanitization_via_hybrid_cache(self) -> None:
        """Test that SPUR API responses are sanitized through hybrid cache method."""

        def mock_api_call() -> dict[str, Any]:
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

        # Mock cache miss to force API call and sanitization
        with patch.object(self.service.cache_manager, 'get_cached', return_value=None):
            with patch.object(self.service.cache_manager, 'store_cached'):
                result = self.service._enrich_with_hybrid_cache("spur", "192.168.1.1", mock_api_call, {"spur_data": []})

        # Verify sanitization happened in SPUR list format
        spur_data = result["spur_data"]
        self.assertEqual(spur_data[0], "ISPName")  # organization
        self.assertEqual(spur_data[11], "NewYork")  # city
        self.assertEqual(spur_data[12], "US")  # country

    def test_cached_data_sanitization(self) -> None:
        """Test that cached data is sanitized when retrieved."""
        # Mock cached data with null bytes
        dirty_cached_data = {
            "ip": {
                "asname": "Cached\x00ISP",
                "ascountry": "US\x00",
            }
        }

        with patch.object(self.service.cache_manager, 'get_cached', return_value=dirty_cached_data):
            result = self.service._enrich_with_hybrid_cache("dshield", "192.168.1.1", lambda: {}, {})

        # Verify cached data was sanitized
        self.assertEqual(result["ip"]["asname"], "CachedISP")
        self.assertEqual(result["ip"]["ascountry"], "US")


if __name__ == "__main__":
    unittest.main()
