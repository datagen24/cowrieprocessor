"""Security tests for EnrichmentCacheManager to verify mutation prevention."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cowrieprocessor.enrichment.cache import EnrichmentCacheManager


class TestCacheMutationPrevention:
    """Test that cache operations prevent data mutation."""

    @pytest.fixture
    def cache_manager(self) -> EnrichmentCacheManager:
        """Create a cache manager for testing."""
        cache_dir = Path(tempfile.mkdtemp())
        return EnrichmentCacheManager(base_dir=cache_dir)

    def test_get_cached_returns_deep_copy(self, cache_manager: EnrichmentCacheManager) -> None:
        """Test that get_cached returns deep copies to prevent mutation."""
        # Test data with nested structures
        original_data = {
            "ip": "192.168.1.100",
            "metadata": {"asname": "Test ISP", "ascountry": "US", "tags": ["malicious", "botnet"]},
            "scores": [1, 2, 3, 4, 5],
            "nested": {"deep": {"value": "test"}},
        }

        service = "dshield"
        key = "test_ip_192.168.1.100"

        # Store the data
        cache_manager.store_cached(service, key, original_data)

        # Retrieve data multiple times
        cached_data_1 = cache_manager.get_cached(service, key)
        cached_data_2 = cache_manager.get_cached(service, key)

        # Verify we got data back
        assert cached_data_1 is not None
        assert cached_data_2 is not None

        # Verify they are deep copies (different objects)
        assert cached_data_1 is not cached_data_2
        assert cached_data_1["metadata"] is not cached_data_2["metadata"]
        assert cached_data_1["metadata"]["tags"] is not cached_data_2["metadata"]["tags"]
        assert cached_data_1["nested"]["deep"] is not cached_data_2["nested"]["deep"]

        # Mutate the first copy
        cached_data_1["ip"] = "10.0.0.1"
        cached_data_1["metadata"]["asname"] = "Modified ISP"
        cached_data_1["metadata"]["tags"].append("modified")
        cached_data_1["scores"].append(6)
        cached_data_1["nested"]["deep"]["value"] = "modified"

        # Verify the second copy is unchanged
        assert cached_data_2["ip"] == "192.168.1.100"
        assert cached_data_2["metadata"]["asname"] == "Test ISP"
        assert cached_data_2["metadata"]["tags"] == ["malicious", "botnet"]
        assert cached_data_2["scores"] == [1, 2, 3, 4, 5]
        assert cached_data_2["nested"]["deep"]["value"] == "test"

        # Verify original data is unchanged (if we had access to it)
        # This tests that the cache doesn't store references to mutable objects

    def test_get_cached_with_complex_nested_structures(self, cache_manager: EnrichmentCacheManager) -> None:
        """Test deep copy behavior with complex nested data structures."""
        complex_data = {
            "session": "abc123",
            "enrichments": {
                "dshield": {"ip": "1.2.3.4", "metadata": {"asname": "Test ASN", "ascountry": "US"}},
                "virustotal": {
                    "file_hash": "abcd1234",
                    "scans": {
                        "engine1": {"detected": True, "version": "1.0"},
                        "engine2": {"detected": False, "version": "2.0"},
                    },
                    "scan_results": [
                        {"engine": "engine1", "result": "malicious"},
                        {"engine": "engine2", "result": "clean"},
                    ],
                },
                "spur": [{"type": "malware", "confidence": 0.8}, {"type": "botnet", "confidence": 0.9}],
            },
            "timestamps": {"start": "2025-01-01T10:00:00Z", "end": "2025-01-01T11:00:00Z"},
        }

        service = "composite"
        key = "complex_test_data"

        # Store and retrieve
        cache_manager.store_cached(service, key, complex_data)
        cached_data = cache_manager.get_cached(service, key)

        assert cached_data is not None

        # Test mutation at various nesting levels
        cached_data["enrichments"]["dshield"]["ip"] = "5.6.7.8"
        cached_data["enrichments"]["virustotal"]["scans"]["engine1"]["detected"] = False
        cached_data["enrichments"]["virustotal"]["scan_results"].append({"engine": "engine3", "result": "suspicious"})
        cached_data["enrichments"]["spur"].append({"type": "phishing", "confidence": 0.7})

        # Retrieve again and verify it's unchanged
        fresh_data = cache_manager.get_cached(service, key)
        assert fresh_data is not None
        assert fresh_data["enrichments"]["dshield"]["ip"] == "1.2.3.4"
        assert fresh_data["enrichments"]["virustotal"]["scans"]["engine1"]["detected"] is True
        assert len(fresh_data["enrichments"]["virustotal"]["scan_results"]) == 2
        assert len(fresh_data["enrichments"]["spur"]) == 2

    def test_get_cached_with_empty_and_none_values(self, cache_manager: EnrichmentCacheManager) -> None:
        """Test deep copy behavior with empty containers and None values."""
        test_data = {
            "empty_dict": {},
            "empty_list": [],
            "none_value": None,
            "empty_string": "",
            "zero_value": 0,
            "false_value": False,
        }

        service = "edge_cases"
        key = "empty_test"

        cache_manager.store_cached(service, key, test_data)
        cached_data = cache_manager.get_cached(service, key)

        assert cached_data is not None
        assert cached_data["empty_dict"] == {}
        assert cached_data["empty_list"] == []
        assert cached_data["none_value"] is None
        assert cached_data["empty_string"] == ""
        assert cached_data["zero_value"] == 0
        assert cached_data["false_value"] is False

        # Test that we can modify empty containers
        cached_data["empty_dict"]["new_key"] = "new_value"
        cached_data["empty_list"].append("new_item")

        # Verify fresh retrieval is unchanged
        fresh_data = cache_manager.get_cached(service, key)
        assert fresh_data["empty_dict"] == {}
        assert fresh_data["empty_list"] == []

    def test_get_cached_missing_key_returns_none(self, cache_manager: EnrichmentCacheManager) -> None:
        """Test that missing cache keys return None."""
        result = cache_manager.get_cached("nonexistent", "missing_key")
        assert result is None

        # Verify stats are updated correctly
        stats = cache_manager.snapshot()
        assert stats["misses"] == 1
        assert stats["hits"] == 0

    def test_get_cached_invalid_json_returns_none(self, cache_manager: EnrichmentCacheManager) -> None:
        """Test that invalid JSON in cache files returns None."""
        service = "test"
        key = "invalid_json"

        # Manually create a cache file with invalid JSON
        cache_path = cache_manager.get_path(service, key)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text("invalid json content", encoding="utf-8")

        # Should return None and increment miss counter
        result = cache_manager.get_cached(service, key)
        assert result is None

        stats = cache_manager.snapshot()
        assert stats["misses"] == 1

    def test_store_cached_with_non_serializable_data(self, cache_manager: EnrichmentCacheManager) -> None:
        """Test that non-JSON-serializable data is handled gracefully."""
        # Create data with non-serializable objects
        non_serializable_data = {
            "valid_data": "test",
            "function": lambda x: x,  # Functions are not JSON serializable
            "set_data": {1, 2, 3},  # Sets are not JSON serializable
        }

        service = "test"
        key = "non_serializable"

        # Should not raise an exception
        cache_manager.store_cached(service, key, non_serializable_data)

        # Should return None since it wasn't stored
        result = cache_manager.get_cached(service, key)
        assert result is None

    def test_cache_stats_accuracy(self, cache_manager: EnrichmentCacheManager) -> None:
        """Test that cache statistics accurately reflect operations."""
        initial_stats = cache_manager.snapshot()
        assert initial_stats["hits"] == 0
        assert initial_stats["misses"] == 0
        assert initial_stats["stores"] == 0

        # Test data
        test_data = {"test": "data"}
        service = "stats_test"
        key = "test_key"

        # Store data
        cache_manager.store_cached(service, key, test_data)
        stats_after_store = cache_manager.snapshot()
        assert stats_after_store["stores"] == 1

        # Retrieve data (hit)
        result = cache_manager.get_cached(service, key)
        assert result is not None
        stats_after_hit = cache_manager.snapshot()
        assert stats_after_hit["hits"] == 1
        assert stats_after_hit["misses"] == 0

        # Retrieve non-existent data (miss)
        cache_manager.get_cached("nonexistent", "missing")
        stats_after_miss = cache_manager.snapshot()
        assert stats_after_miss["hits"] == 1
        assert stats_after_miss["misses"] == 1
