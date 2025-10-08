"""Tests for VirusTotal handler."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import vt

from cowrieprocessor.enrichment.virustotal_handler import VirusTotalHandler


class TestVirusTotalHandler:
    """Test VirusTotalHandler class."""

    def test_init(self) -> None:
        """Test handler initialization."""
        cache_dir = Path("/tmp/test_cache")
        handler = VirusTotalHandler(
            api_key="test-key",
            cache_dir=cache_dir,
            timeout=60,
            skip_enrich=False,
            enable_quota_management=True,
        )

        assert handler.api_key == "test-key"
        assert handler.cache_dir == cache_dir
        assert handler.timeout == 60
        assert handler.skip_enrich is False
        assert handler.quota_manager is not None
        assert handler.client is not None

    def test_init_skip_enrich(self) -> None:
        """Test handler initialization with enrichment skipped."""
        cache_dir = Path("/tmp/test_cache")
        handler = VirusTotalHandler(
            api_key="test-key",
            cache_dir=cache_dir,
            skip_enrich=True,
        )

        assert handler.client is None
        assert handler.quota_manager is None

    def test_init_no_api_key(self) -> None:
        """Test handler initialization without API key."""
        cache_dir = Path("/tmp/test_cache")
        handler = VirusTotalHandler(
            api_key="",
            cache_dir=cache_dir,
        )

        assert handler.client is None
        assert handler.quota_manager is None

    def test_get_cache_path(self) -> None:
        """Test cache path generation."""
        cache_dir = Path("/tmp/test_cache")
        handler = VirusTotalHandler("test-key", cache_dir)

        cache_path = handler._get_cache_path("abc123")
        expected = cache_dir / "vt_abc123.json"
        assert cache_path == expected

    def test_load_cached_response_exists(self, tmp_path: Path) -> None:
        """Test loading cached response when file exists."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        handler = VirusTotalHandler("test-key", cache_dir)

        # Create cached response
        test_data = {"test": "data"}
        cache_path = handler._get_cache_path("abc123")
        with open(cache_path, 'w') as f:
            json.dump(test_data, f)

        # Load cached response
        result = handler._load_cached_response("abc123")
        assert result == test_data

    def test_load_cached_response_not_exists(self, tmp_path: Path) -> None:
        """Test loading cached response when file doesn't exist."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        handler = VirusTotalHandler("test-key", cache_dir)

        result = handler._load_cached_response("nonexistent")
        assert result is None

    def test_load_cached_response_invalid_json(self, tmp_path: Path) -> None:
        """Test loading cached response with invalid JSON."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        handler = VirusTotalHandler("test-key", cache_dir)

        # Create invalid JSON file
        cache_path = handler._get_cache_path("abc123")
        with open(cache_path, 'w') as f:
            f.write("invalid json")

        result = handler._load_cached_response("abc123")
        assert result is None

    def test_save_cached_response(self, tmp_path: Path) -> None:
        """Test saving cached response."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        handler = VirusTotalHandler("test-key", cache_dir)

        test_data = {"test": "data"}
        handler._save_cached_response("abc123", test_data)

        # Verify file was created
        cache_path = handler._get_cache_path("abc123")
        assert cache_path.exists()

        # Verify content
        with open(cache_path, 'r') as f:
            saved_data = json.load(f)
        assert saved_data == test_data

    @patch('cowrieprocessor.enrichment.virustotal_handler.VirusTotalQuotaManager')
    def test_check_quota_before_request(self, mock_quota_manager_class: Mock) -> None:
        """Test quota check before request."""
        mock_quota_manager = Mock()
        mock_quota_manager.can_make_request.return_value = True
        mock_quota_manager_class.return_value = mock_quota_manager

        handler = VirusTotalHandler("test-key", Path("/tmp"), enable_quota_management=True)
        handler.quota_manager = mock_quota_manager

        result = handler._check_quota_before_request()
        assert result is True
        mock_quota_manager.can_make_request.assert_called_once_with(90.0)

        # Test when quota check fails
        mock_quota_manager.can_make_request.return_value = False
        result = handler._check_quota_before_request()
        assert result is False

    def test_check_quota_before_request_no_manager(self) -> None:
        """Test quota check when no quota manager."""
        handler = VirusTotalHandler("test-key", Path("/tmp"), enable_quota_management=False)

        result = handler._check_quota_before_request()
        assert result is True

    @patch('cowrieprocessor.enrichment.virustotal_handler.time.sleep')
    @patch('cowrieprocessor.enrichment.virustotal_handler.VirusTotalQuotaManager')
    def test_handle_quota_error(self, mock_quota_manager_class: Mock, mock_sleep: Mock) -> None:
        """Test quota error handling."""
        mock_quota_manager = Mock()
        mock_quota_manager.get_backoff_time.return_value = 120.0
        mock_quota_manager_class.return_value = mock_quota_manager

        handler = VirusTotalHandler("test-key", Path("/tmp"), enable_quota_management=True)
        handler.quota_manager = mock_quota_manager

        result = handler._handle_quota_error("test-hash")

        assert result is None
        mock_quota_manager.get_backoff_time.assert_called_once()
        mock_sleep.assert_called_once_with(120.0)

    @patch('cowrieprocessor.enrichment.virustotal_handler.vt.Client')
    def test_fetch_file_info_success(self, mock_client_class: Mock) -> None:
        """Test successful file info fetch."""
        # Mock file object
        mock_file_obj = Mock()
        mock_file_obj.id = "test-file-id"
        mock_file_obj.type = "file"
        mock_file_obj.last_analysis_stats = {"malicious": 5, "harmless": 10}
        mock_file_obj.last_analysis_results = {"test": "results"}
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

        # Mock client
        mock_client = Mock()
        mock_client.get_object.return_value = mock_file_obj
        mock_client_class.return_value = mock_client

        handler = VirusTotalHandler("test-key", Path("/tmp"))
        handler.client = mock_client
        handler.quota_manager = None  # Disable quota management for simplicity

        result = handler._fetch_file_info("test-hash")

        assert result is not None
        assert "data" in result
        assert result["data"]["id"] == "test-file-id"
        assert result["data"]["attributes"]["last_analysis_stats"] == {"malicious": 5, "harmless": 10}

    @patch('cowrieprocessor.enrichment.virustotal_handler.vt.Client')
    def test_fetch_file_info_not_found(self, mock_client_class: Mock) -> None:
        """Test file info fetch when file not found."""
        mock_client = Mock()
        mock_client.get_object.side_effect = vt.APIError("Not found", "NotFoundError")
        mock_client_class.return_value = mock_client

        handler = VirusTotalHandler("test-key", Path("/tmp"))
        handler.client = mock_client
        handler.quota_manager = None

        # The retry decorator will re-raise the exception after max retries
        with pytest.raises(vt.APIError):
            handler._fetch_file_info("test-hash")

    @patch('cowrieprocessor.enrichment.virustotal_handler.vt.Client')
    @patch('cowrieprocessor.enrichment.virustotal_handler.time.sleep')
    def test_fetch_file_info_quota_exceeded(self, mock_sleep: Mock, mock_client_class: Mock) -> None:
        """Test file info fetch when quota exceeded."""
        mock_client = Mock()
        mock_client.get_object.side_effect = vt.APIError("Quota exceeded", "QuotaExceededError")
        mock_client_class.return_value = mock_client

        # Mock quota manager
        mock_quota_manager = Mock()
        mock_quota_manager.get_backoff_time.return_value = 60.0

        handler = VirusTotalHandler("test-key", Path("/tmp"))
        handler.client = mock_client
        handler.quota_manager = mock_quota_manager

        # The retry decorator will re-raise the exception after max retries
        with pytest.raises(vt.APIError):
            handler._fetch_file_info("test-hash")

        # Sleep might be called by the retry decorator, but not necessarily by quota handling
        # since the retry decorator catches the exception first

    @patch('cowrieprocessor.enrichment.virustotal_handler.VirusTotalQuotaManager')
    def test_enrich_file_cached(self, mock_quota_manager_class: Mock, tmp_path: Path) -> None:
        """Test file enrichment with cached response."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        handler = VirusTotalHandler("test-key", cache_dir)

        # Create cached response
        test_data = {"cached": "data"}
        handler._save_cached_response("abc123", test_data)

        result = handler.enrich_file("abc123")
        assert result == test_data

    @patch('cowrieprocessor.enrichment.virustotal_handler.vt.Client')
    def test_enrich_file_fresh(self, mock_client_class: Mock, tmp_path: Path) -> None:
        """Test file enrichment with fresh API call."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        # Mock file object
        mock_file_obj = Mock()
        mock_file_obj.id = "test-file-id"
        mock_file_obj.type = "file"
        mock_file_obj.last_analysis_stats = {"malicious": 5, "harmless": 10}
        mock_file_obj.last_analysis_results = {}
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

        # Mock client
        mock_client = Mock()
        mock_client.get_object.return_value = mock_file_obj
        mock_client_class.return_value = mock_client

        handler = VirusTotalHandler("test-key", cache_dir)
        handler.client = mock_client
        handler.quota_manager = None

        result = handler.enrich_file("abc123")

        assert result is not None
        assert "data" in result
        assert result["data"]["id"] == "test-file-id"

        # Verify cache was created
        cache_path = handler._get_cache_path("abc123")
        assert cache_path.exists()

    def test_enrich_file_skip_enrich(self) -> None:
        """Test file enrichment when enrichment is skipped."""
        handler = VirusTotalHandler("test-key", Path("/tmp"), skip_enrich=True)

        result = handler.enrich_file("abc123")
        assert result is None

    def test_enrich_file_no_api_key(self) -> None:
        """Test file enrichment when no API key."""
        handler = VirusTotalHandler("", Path("/tmp"))

        result = handler.enrich_file("abc123")
        assert result is None

    def test_get_quota_status(self) -> None:
        """Test quota status retrieval."""
        handler = VirusTotalHandler("test-key", Path("/tmp"), enable_quota_management=False)

        result = handler.get_quota_status()
        assert result["status"] == "disabled"
        assert "message" in result

    def test_extract_analysis_stats(self) -> None:
        """Test analysis stats extraction."""
        handler = VirusTotalHandler("test-key", Path("/tmp"))

        vt_response = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {
                        "malicious": 5,
                        "harmless": 10,
                        "suspicious": 2,
                        "undetected": 20,
                        "timeout": 1,
                        "confirmed-timeout": 0,
                        "failure": 0,
                        "type-unsupported": 0,
                    }
                }
            }
        }

        stats = handler.extract_analysis_stats(vt_response)

        assert stats["malicious"] == 5
        assert stats["harmless"] == 10
        assert stats["suspicious"] == 2
        assert stats["undetected"] == 20
        assert stats["total_scans"] == 38

    def test_extract_analysis_stats_invalid(self) -> None:
        """Test analysis stats extraction with invalid response."""
        handler = VirusTotalHandler("test-key", Path("/tmp"))

        # Test with None
        stats = handler.extract_analysis_stats(None)
        assert stats == {}

        # Test with invalid structure
        stats = handler.extract_analysis_stats({"invalid": "data"})
        assert stats == {}

        # Test with partial structure
        stats = handler.extract_analysis_stats({"data": "invalid"})
        assert stats == {}

    def test_extract_analysis_stats_with_non_numeric_values(self) -> None:
        """Test analysis stats extraction with non-numeric values (e.g., nested dicts)."""
        handler = VirusTotalHandler("test-key", Path("/tmp"))

        # Test with stats that contain non-numeric values (like WhistleBlowerDict objects)
        vt_response = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {
                        "malicious": 5,
                        "harmless": 10,
                        "suspicious": 2,
                        "undetected": 20,
                        "timeout": 1,
                        "confirmed-timeout": 0,
                        "failure": 0,
                        "type-unsupported": 0,
                        "nested_dict": {"should": "be_ignored"},  # This should not break the sum
                    }
                }
            }
        }

        stats = handler.extract_analysis_stats(vt_response)

        # All numeric fields should be extracted
        assert stats["malicious"] == 5
        assert stats["harmless"] == 10
        assert stats["suspicious"] == 2
        assert stats["undetected"] == 20

        # total_scans should only sum numeric values (ignoring the nested_dict)
        expected_total = 5 + 10 + 2 + 20 + 1 + 0 + 0 + 0  # 38
        assert stats["total_scans"] == expected_total

    def test_is_malicious(self) -> None:
        """Test malicious detection logic."""
        handler = VirusTotalHandler("test-key", Path("/tmp"))

        # Test malicious file (threshold 2)
        vt_response = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {
                        "malicious": 5,
                        "harmless": 10,
                        "suspicious": 2,
                        "undetected": 20,
                        "timeout": 1,
                        "confirmed-timeout": 0,
                        "failure": 0,
                        "type-unsupported": 0,
                    }
                }
            }
        }

        assert handler.is_malicious(vt_response, threshold=2) is True
        assert handler.is_malicious(vt_response, threshold=10) is False

    def test_is_malicious_invalid_response(self) -> None:
        """Test malicious detection with invalid response."""
        handler = VirusTotalHandler("test-key", Path("/tmp"))

        assert handler.is_malicious(None) is False
        assert handler.is_malicious({"invalid": "data"}) is False

    def test_close(self) -> None:
        """Test handler cleanup."""
        handler = VirusTotalHandler("test-key", Path("/tmp"))
        handler.client = Mock()

        handler.close()
        handler.client.close.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__])
