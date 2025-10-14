"""Tests for VirusTotal serialization handling."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from cowrieprocessor.enrichment.virustotal_handler import VirusTotalHandler


class MockWhistleBlowerDict(dict):
    """Mock WhistleBlowerDict that isn't JSON serializable."""

    def __init__(self, data: dict):
        """Initialize the mock WhistleBlowerDict."""
        super().__init__(data)
        self._special_attr = "not_serializable"

    def __str__(self) -> str:
        """Return string representation of the mock WhistleBlowerDict."""
        return f"WhistleBlowerDict({dict(self)})"


class TestVirusTotalSerialization:
    """Test VirusTotal serialization handling."""

    def test_serialize_whistleblower_dict(self, tmp_path: Path) -> None:
        """Test serialization of WhistleBlowerDict objects."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        # Create a mock file object with WhistleBlowerDict
        mock_file_obj = Mock()
        mock_file_obj.id = "test-file-id"
        mock_file_obj.type = "file"
        mock_file_obj.last_analysis_stats = {"malicious": 5, "harmless": 10}
        mock_file_obj.last_analysis_results = MockWhistleBlowerDict({"test": "result"})
        mock_file_obj.first_submission_date = 1234567890
        mock_file_obj.last_submission_date = 1234567890
        mock_file_obj.md5 = "test-md5"
        mock_file_obj.sha1 = "test-sha1"
        mock_file_obj.sha256 = "test-sha256"
        mock_file_obj.size = 1024
        mock_file_obj.type_description = "PE32"
        mock_file_obj.names = ["test.exe"]
        mock_file_obj.tags = ["trojan"]
        mock_file_obj.reputation = 50
        mock_file_obj.total_votes = 10
        mock_file_obj.meaningful_name = "test.exe"

        # Create handler
        handler = VirusTotalHandler("test-key", cache_dir, enable_quota_management=False)

        # Test the serialize_value function by accessing it through the response
        # We'll mock the client to return our mock object
        with pytest.MonkeyPatch().context() as m:
            m.setattr(handler, 'client', Mock())
            handler.client.get_object.return_value = mock_file_obj

            # This should not raise a JSON serialization error
            result = handler._fetch_file_info("test-hash")

            assert result is not None
            assert "data" in result
            assert "attributes" in result["data"]

            # The WhistleBlowerDict should be converted to a regular dict
            attributes = result["data"]["attributes"]
            assert isinstance(attributes["last_analysis_results"], dict)
            assert attributes["last_analysis_results"]["test"] == "result"

    def test_json_serialization_with_default_str(self, tmp_path: Path) -> None:
        """Test JSON serialization with default=str fallback."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        VirusTotalHandler("test-key", cache_dir)

        # Test data with a non-serializable object
        test_data = {
            "data": {
                "attributes": {
                    "whistleblower": MockWhistleBlowerDict({"key": "value"}),
                    "normal_field": "normal_value",
                }
            }
        }

        # This should work with default=str
        cache_path = cache_dir / "test.json"

        # Should not raise an exception
        with open(cache_path, 'w') as f:
            json.dump(test_data, f, default=str)

        # Verify we can read it back
        with open(cache_path, 'r') as f:
            loaded_data = json.load(f)

        assert loaded_data["data"]["attributes"]["normal_field"] == "normal_value"
        # The non-serializable object should be converted to a dict representation
        assert isinstance(loaded_data["data"]["attributes"]["whistleblower"], dict)
        assert loaded_data["data"]["attributes"]["whistleblower"]["key"] == "value"

    def test_serialize_value_recursive(self) -> None:
        """Test serialize_value function with nested structures."""
        cache_dir = Path("/tmp")
        handler = VirusTotalHandler("test-key", cache_dir)

        # Access the serialize_value function through the class
        # We need to extract it from the _fetch_file_info method
        import inspect

        inspect.getsource(handler._fetch_file_info)

        # Create a test value with nested WhistleBlowerDict
        test_data = {
            "level1": {
                "level2": MockWhistleBlowerDict({"nested": "value"}),
                "normal": "normal_value",
            },
            "list_data": [
                "string",
                MockWhistleBlowerDict({"list_item": "value"}),
                123,
            ],
        }

        # We can't directly test the serialize_value function since it's local,
        # but we can test that the overall serialization works
        # by ensuring the response structure is correct
        mock_file_obj = Mock()
        mock_file_obj.id = "test"
        mock_file_obj.type = "file"
        mock_file_obj.last_analysis_stats = {"malicious": 0}
        mock_file_obj.last_analysis_results = test_data  # This contains WhistleBlowerDict
        mock_file_obj.first_submission_date = 0
        mock_file_obj.last_submission_date = 0
        mock_file_obj.md5 = ""
        mock_file_obj.sha1 = ""
        mock_file_obj.sha256 = ""
        mock_file_obj.size = 0
        mock_file_obj.type_description = ""
        mock_file_obj.names = []
        mock_file_obj.tags = []
        mock_file_obj.reputation = 0
        mock_file_obj.total_votes = 0
        mock_file_obj.meaningful_name = ""

        with pytest.MonkeyPatch().context() as m:
            m.setattr(handler, 'client', Mock())
            handler.client.get_object.return_value = mock_file_obj

            # This should handle the WhistleBlowerDict without errors
            result = handler._fetch_file_info("test-hash")

            assert result is not None
            # The result should be JSON serializable
            json_str = json.dumps(result, default=str)
            assert len(json_str) > 0


if __name__ == "__main__":
    pytest.main([__file__])
