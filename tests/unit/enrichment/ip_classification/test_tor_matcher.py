"""Unit tests for TOR exit node matcher."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from cowrieprocessor.enrichment.ip_classification.tor_matcher import TorExitNodeMatcher
from tests.fixtures.ip_classification_fixtures import MOCK_TOR_EXIT_LIST, SAMPLE_TOR_IP, SAMPLE_UNKNOWN_IP


@pytest.fixture
def tor_matcher(tmp_path: Path) -> TorExitNodeMatcher:
    """Create TOR matcher with temp cache directory."""
    return TorExitNodeMatcher(
        data_url="https://check.torproject.org/torbulkexitlist",
        update_interval_seconds=3600,
        cache_dir=tmp_path,
        request_timeout=30,
    )


class TestTorExitNodeMatcher:
    """Test TorExitNodeMatcher class."""

    def test_matcher_initialization(self, tor_matcher: TorExitNodeMatcher) -> None:
        """Test matcher initialization with default parameters."""
        assert tor_matcher.data_url == "https://check.torproject.org/torbulkexitlist"
        assert tor_matcher.update_interval_seconds == 3600
        assert tor_matcher.request_timeout == 30
        assert len(tor_matcher.exit_nodes) == 0
        assert not tor_matcher._data_loaded
        assert tor_matcher.last_update is None

    def test_matcher_initialization_custom_params(self, tmp_path: Path) -> None:
        """Test matcher initialization with custom parameters."""
        matcher = TorExitNodeMatcher(
            data_url="https://example.com/tor-list",
            update_interval_seconds=7200,
            cache_dir=tmp_path / "custom",
            request_timeout=60,
        )

        assert matcher.data_url == "https://example.com/tor-list"
        assert matcher.update_interval_seconds == 7200
        assert matcher.request_timeout == 60
        assert (tmp_path / "custom").exists()

    @patch("cowrieprocessor.enrichment.ip_classification.tor_matcher.requests.get")
    def test_download_data_success(self, mock_get: Mock, tor_matcher: TorExitNodeMatcher) -> None:
        """Test successful data download and parsing."""
        mock_response = Mock()
        mock_response.text = MOCK_TOR_EXIT_LIST
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        tor_matcher._download_data()

        assert tor_matcher._data_loaded
        assert len(tor_matcher.exit_nodes) == 4  # 3 IPv4 + 1 IPv6
        assert "185.220.101.1" in tor_matcher.exit_nodes
        assert "185.220.101.2" in tor_matcher.exit_nodes
        assert "185.220.101.3" in tor_matcher.exit_nodes
        assert "2001:db8::1" in tor_matcher.exit_nodes

    @patch("cowrieprocessor.enrichment.ip_classification.tor_matcher.requests.get")
    def test_download_data_caches_to_disk(self, mock_get: Mock, tor_matcher: TorExitNodeMatcher) -> None:
        """Test that downloaded data is cached to disk."""
        mock_response = Mock()
        mock_response.text = MOCK_TOR_EXIT_LIST
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        tor_matcher._download_data()

        cache_file = tor_matcher.cache_dir / "tor_exit_nodes.txt"
        assert cache_file.exists()
        assert cache_file.read_text() == MOCK_TOR_EXIT_LIST

    @patch("cowrieprocessor.enrichment.ip_classification.tor_matcher.requests.get")
    def test_download_data_empty_response(self, mock_get: Mock, tor_matcher: TorExitNodeMatcher) -> None:
        """Test download with empty response raises ValueError."""
        mock_response = Mock()
        mock_response.text = ""
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(ValueError, match="Empty response from TOR exit node list"):
            tor_matcher._download_data()

    @patch("cowrieprocessor.enrichment.ip_classification.tor_matcher.requests.get")
    def test_download_data_no_valid_ips(self, mock_get: Mock, tor_matcher: TorExitNodeMatcher) -> None:
        """Test download with no valid IPs raises ValueError."""
        mock_response = Mock()
        mock_response.text = "\n\n   \n\n"  # Only whitespace
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(ValueError, match="No valid IPs found in TOR exit node list"):
            tor_matcher._download_data()

    @patch("cowrieprocessor.enrichment.ip_classification.tor_matcher.requests.get")
    def test_download_data_http_error(self, mock_get: Mock, tor_matcher: TorExitNodeMatcher) -> None:
        """Test download with HTTP error raises RequestException."""
        mock_get.side_effect = requests.RequestException("Connection error")

        with pytest.raises(requests.RequestException):
            tor_matcher._download_data()

    @patch("cowrieprocessor.enrichment.ip_classification.tor_matcher.requests.get")
    def test_download_data_timeout(self, mock_get: Mock, tor_matcher: TorExitNodeMatcher) -> None:
        """Test download timeout raises RequestException."""
        mock_get.side_effect = requests.Timeout("Request timeout")

        with pytest.raises(requests.Timeout):
            tor_matcher._download_data()

    @patch("cowrieprocessor.enrichment.ip_classification.tor_matcher.requests.get")
    def test_match_tor_exit_node(self, mock_get: Mock, tor_matcher: TorExitNodeMatcher) -> None:
        """Test matching a TOR exit node IP."""
        mock_response = Mock()
        mock_response.text = MOCK_TOR_EXIT_LIST
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = tor_matcher.match(SAMPLE_TOR_IP)

        assert result is not None
        assert result["provider"] == "tor"

    @patch("cowrieprocessor.enrichment.ip_classification.tor_matcher.requests.get")
    def test_match_non_tor_ip(self, mock_get: Mock, tor_matcher: TorExitNodeMatcher) -> None:
        """Test matching a non-TOR IP returns None."""
        mock_response = Mock()
        mock_response.text = MOCK_TOR_EXIT_LIST
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = tor_matcher.match(SAMPLE_UNKNOWN_IP)

        assert result is None

    @patch("cowrieprocessor.enrichment.ip_classification.tor_matcher.requests.get")
    def test_match_ipv6_tor_exit_node(self, mock_get: Mock, tor_matcher: TorExitNodeMatcher) -> None:
        """Test matching an IPv6 TOR exit node."""
        mock_response = Mock()
        mock_response.text = MOCK_TOR_EXIT_LIST
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = tor_matcher.match("2001:db8::1")

        assert result is not None
        assert result["provider"] == "tor"

    @patch("cowrieprocessor.enrichment.ip_classification.tor_matcher.requests.get")
    def test_match_auto_updates_stale_data(self, mock_get: Mock, tor_matcher: TorExitNodeMatcher) -> None:
        """Test that match() auto-updates stale data."""
        mock_response = Mock()
        mock_response.text = MOCK_TOR_EXIT_LIST
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # First match triggers download
        result1 = tor_matcher.match(SAMPLE_TOR_IP)
        assert result1 is not None
        assert mock_get.call_count == 1

        # Second match uses cached data
        result2 = tor_matcher.match(SAMPLE_TOR_IP)
        assert result2 is not None
        assert mock_get.call_count == 1  # No new download

    @patch("cowrieprocessor.enrichment.ip_classification.tor_matcher.requests.get")
    def test_match_statistics_tracking(self, mock_get: Mock, tor_matcher: TorExitNodeMatcher) -> None:
        """Test that match() updates statistics."""
        mock_response = Mock()
        mock_response.text = MOCK_TOR_EXIT_LIST
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Match TOR IP
        tor_matcher.match(SAMPLE_TOR_IP)
        assert tor_matcher._stats_lookups == 1
        assert tor_matcher._stats_hits == 1
        assert tor_matcher._stats_misses == 0

        # Match non-TOR IP
        tor_matcher.match(SAMPLE_UNKNOWN_IP)
        assert tor_matcher._stats_lookups == 2
        assert tor_matcher._stats_hits == 1
        assert tor_matcher._stats_misses == 1

    @patch("cowrieprocessor.enrichment.ip_classification.tor_matcher.requests.get")
    def test_get_stats(self, mock_get: Mock, tor_matcher: TorExitNodeMatcher) -> None:
        """Test get_stats() returns correct statistics."""
        mock_response = Mock()
        mock_response.text = MOCK_TOR_EXIT_LIST
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Before any matches
        stats = tor_matcher.get_stats()
        assert stats["data_loaded"] is False
        assert stats["last_update"] is None
        assert stats["exit_node_count"] == 0
        assert stats["lookups"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0

        # After downloading and matching
        tor_matcher.match(SAMPLE_TOR_IP)
        tor_matcher.match(SAMPLE_UNKNOWN_IP)

        stats = tor_matcher.get_stats()
        assert stats["data_loaded"] is True
        assert stats["last_update"] is not None
        assert stats["exit_node_count"] == 4
        assert stats["lookups"] == 2
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    @patch("cowrieprocessor.enrichment.ip_classification.tor_matcher.requests.get")
    def test_is_stale_initially(self, mock_get: Mock, tor_matcher: TorExitNodeMatcher) -> None:
        """Test that data is initially stale."""
        assert tor_matcher._is_stale() is True

    @patch("cowrieprocessor.enrichment.ip_classification.tor_matcher.requests.get")
    def test_is_not_stale_after_load(self, mock_get: Mock, tor_matcher: TorExitNodeMatcher) -> None:
        """Test that data is not stale immediately after loading."""
        mock_response = Mock()
        mock_response.text = MOCK_TOR_EXIT_LIST
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        tor_matcher._download_data()
        tor_matcher.last_update = datetime.now(timezone.utc)
        tor_matcher._data_loaded = True

        assert tor_matcher._is_stale() is False

    @patch("cowrieprocessor.enrichment.ip_classification.tor_matcher.requests.get")
    def test_graceful_degradation_on_update_failure(self, mock_get: Mock, tor_matcher: TorExitNodeMatcher) -> None:
        """Test graceful degradation when update fails but cached data exists."""
        # First download succeeds
        mock_response = Mock()
        mock_response.text = MOCK_TOR_EXIT_LIST
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        tor_matcher._download_data()
        tor_matcher.last_update = datetime.now(timezone.utc)
        tor_matcher._data_loaded = True

        # Simulate stale data
        tor_matcher.last_update = datetime(2020, 1, 1, tzinfo=timezone.utc)

        # Second download fails
        mock_get.side_effect = requests.RequestException("Network error")

        # Should still match using stale data (no exception raised)
        result = tor_matcher.match(SAMPLE_TOR_IP)
        assert result is not None
        assert result["provider"] == "tor"

    @patch("cowrieprocessor.enrichment.ip_classification.tor_matcher.requests.get")
    def test_empty_lines_ignored(self, mock_get: Mock, tor_matcher: TorExitNodeMatcher) -> None:
        """Test that empty lines and whitespace are ignored."""
        mock_response = Mock()
        mock_response.text = """185.220.101.1

185.220.101.2

185.220.101.3
"""
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        tor_matcher._download_data()

        assert len(tor_matcher.exit_nodes) == 3
        assert "185.220.101.1" in tor_matcher.exit_nodes
        assert "185.220.101.2" in tor_matcher.exit_nodes
        assert "185.220.101.3" in tor_matcher.exit_nodes
