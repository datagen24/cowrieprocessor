"""Unit tests for legacy enrichment adapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from cowrieprocessor.enrichment.legacy_adapter import LegacyEnrichmentAdapter


class TestLegacyEnrichmentAdapter:
    """Test cases for LegacyEnrichmentAdapter."""

    @pytest.fixture
    def mock_cache_manager(self) -> Mock:
        """Mock cache manager for testing."""
        return Mock()

    @pytest.fixture
    def mock_cache_dir(self, tmp_path: Path) -> Path:
        """Mock cache directory for testing."""
        return tmp_path / "cache"

    @pytest.fixture
    def adapter(self, mock_cache_manager: Mock, mock_cache_dir: Path) -> LegacyEnrichmentAdapter:
        """Create LegacyEnrichmentAdapter instance for testing."""
        # Create the adapter normally
        adapter = LegacyEnrichmentAdapter(
            cache_manager=mock_cache_manager,
            cache_dir=mock_cache_dir,
            vt_api="test_vt_key",
            dshield_email="test@example.com",
            urlhaus_api="test_urlhaus_token",
            spur_api="test_spur_key",
            skip_enrich=False,
        )

        # Mock the service
        adapter.service = Mock()
        return adapter

    def test_adapter_initialization(self, mock_cache_manager: Mock, mock_cache_dir: Path) -> None:
        """Test LegacyEnrichmentAdapter initializes correctly."""
        adapter = LegacyEnrichmentAdapter(
            cache_manager=mock_cache_manager,
            cache_dir=mock_cache_dir,
            vt_api="test_vt_key",
            dshield_email="test@example.com",
            urlhaus_api="test_urlhaus_token",
            spur_api="test_spur_key",
            skip_enrich=False,
        )

        assert adapter.cache_manager == mock_cache_manager
        assert adapter.cache_dir == mock_cache_dir
        assert adapter.enabled is True
        assert adapter.service is not None
        assert adapter._session_cache == {}
        assert adapter._file_cache == {}

        # Test that service was initialized with correct parameters
        assert adapter.service.cache_dir == mock_cache_dir
        assert adapter.service.vt_api == "test_vt_key"
        assert adapter.service.dshield_email == "test@example.com"
        assert adapter.service.urlhaus_api == "test_urlhaus_token"
        assert adapter.service.spur_api == "test_spur_key"
        assert adapter.service.cache_manager == mock_cache_manager

    def test_adapter_initialization_with_skip_enrich(self, mock_cache_manager: Mock, mock_cache_dir: Path) -> None:
        """Test LegacyEnrichmentAdapter with skip_enrich=True."""
        adapter = LegacyEnrichmentAdapter(
            cache_manager=mock_cache_manager,
            cache_dir=mock_cache_dir,
            vt_api="test_vt_key",
            dshield_email="test@example.com",
            urlhaus_api="test_urlhaus_token",
            spur_api="test_spur_key",
            skip_enrich=True,
        )

        assert adapter.enabled is False
        assert adapter.service is not None

    def test_dshield_method_with_cached_result(self, adapter: LegacyEnrichmentAdapter) -> None:
        """Test dshield method with cached result."""
        # Setup cached result
        adapter._session_cache["192.168.1.1"] = {"dshield": {"ip": {"asname": "Test ASN", "ascountry": "US"}}}

        result = adapter.dshield("192.168.1.1")

        # Should return from cache without calling service
        assert result == {"ip": {"asname": "Test ASN", "ascountry": "US"}}
        adapter.service.enrich_session.assert_not_called()  # type: ignore[attr-defined]

    def test_dshield_method_with_service_call(self, adapter: LegacyEnrichmentAdapter) -> None:
        """Test dshield method with service call."""
        # Setup service mock
        adapter.service.enrich_session.return_value = {  # type: ignore[attr-defined]
            "enrichment": {"dshield": {"ip": {"asname": "New ASN", "ascountry": "CA"}}}
        }

        result = adapter.dshield("10.0.0.1")

        # Should call service and cache result
        adapter.service.enrich_session.assert_called_once_with("10.0.0.1", "10.0.0.1")  # type: ignore[attr-defined]
        assert result == {"ip": {"asname": "New ASN", "ascountry": "CA"}}
        assert adapter._session_cache["10.0.0.1"]["dshield"] == {"ip": {"asname": "New ASN", "ascountry": "CA"}}

    def test_dshield_method_with_missing_enrichment(self, adapter: LegacyEnrichmentAdapter) -> None:
        """Test dshield method with missing enrichment data."""
        # Setup service mock with no dshield data
        adapter.service.enrich_session.return_value = {"enrichment": {}}  # type: ignore[attr-defined]

        result = adapter.dshield("10.0.0.1")

        # Should return default structure
        assert result == {"ip": {"asname": "", "ascountry": ""}}

    def test_urlhaus_method_with_list_tags(self, adapter: LegacyEnrichmentAdapter) -> None:
        """Test urlhaus method with list of tags."""
        # Setup cached result
        adapter._session_cache["192.168.1.1"] = {"urlhaus": ["malware", "botnet", "phishing"]}

        result = adapter.urlhaus("192.168.1.1")

        # Should return sorted comma-separated string
        assert result == "botnet, malware, phishing"

    def test_urlhaus_method_with_single_tag(self, adapter: LegacyEnrichmentAdapter) -> None:
        """Test urlhaus method with single tag."""
        # Setup service mock
        adapter.service.enrich_session.return_value = {"enrichment": {"urlhaus": "malware"}}  # type: ignore[attr-defined]

        result = adapter.urlhaus("10.0.0.1")

        assert result == "malware"

    def test_urlhaus_method_with_empty_tags(self, adapter: LegacyEnrichmentAdapter) -> None:
        """Test urlhaus method with empty tags."""
        # Setup service mock with empty urlhaus data
        adapter.service.enrich_session.return_value = {"enrichment": {"urlhaus": []}}  # type: ignore[attr-defined]

        result = adapter.urlhaus("10.0.0.1")

        assert result == ""

    def test_spur_method_with_correct_format(self, adapter: LegacyEnrichmentAdapter) -> None:
        """Test spur method with correctly formatted data."""
        # Setup cached result with correct SPUR format (18 elements)
        spur_data = [""] * 18
        spur_data[3] = "DATACENTER"  # Set the 4th element
        adapter._session_cache["192.168.1.1"] = {"spur": spur_data}

        result = adapter.spur("192.168.1.1")

        # Should return the data as-is
        assert len(result) == 18
        assert result[3] == "DATACENTER"

    def test_spur_method_with_incorrect_format(self, adapter: LegacyEnrichmentAdapter) -> None:
        """Test spur method with incorrectly formatted data."""
        # Setup service mock with wrong format (not 18 elements)
        adapter.service.enrich_session.return_value = {"enrichment": {"spur": ["wrong", "format", "data"]}}  # type: ignore[attr-defined]

        result = adapter.spur("10.0.0.1")

        # Should return empty payload format (18 empty strings)
        assert len(result) == 18
        assert all(x == "" for x in result)

    def test_spur_method_with_non_list_data(self, adapter: LegacyEnrichmentAdapter) -> None:
        """Test spur method with non-list data."""
        # Setup service mock with non-list data
        adapter.service.enrich_session.return_value = {"enrichment": {"spur": "not_a_list"}}  # type: ignore[attr-defined]

        result = adapter.spur("10.0.0.1")

        # Should return empty payload format (18 empty strings)
        assert len(result) == 18
        assert all(x == "" for x in result)

    def test_virustotal_method_with_success(self, adapter: LegacyEnrichmentAdapter, mock_cache_dir: Path) -> None:
        """Test virustotal method with successful enrichment."""
        # Setup service mock
        adapter.service.enrich_file.return_value = {  # type: ignore[attr-defined]
            "enrichment": {
                "virustotal": {"data": {"attributes": {"last_analysis_stats": {"malicious": 5, "suspicious": 2}}}}
            }
        }

        result = adapter.virustotal("test_hash", "test_file.exe")

        # Should call service and cache result
        adapter.service.enrich_file.assert_called_once_with("test_hash", "test_file.exe")  # type: ignore[attr-defined]
        assert result is not None
        assert "data" in result  # The virustotal data is returned directly

        # Should write to cache file
        cache_file = mock_cache_dir / "test_hash"
        assert cache_file.exists()
        cache_content = cache_file.read_text()
        assert '"data"' in cache_content  # The virustotal data structure is cached directly

    def test_virustotal_method_with_no_enrichment(self, adapter: LegacyEnrichmentAdapter) -> None:
        """Test virustotal method with no enrichment data."""
        # Setup service mock with no enrichment
        adapter.service.enrich_file.return_value = {"enrichment": {}}  # type: ignore[attr-defined]

        result = adapter.virustotal("test_hash")

        assert result is None

    def test_virustotal_method_with_non_dict_enrichment(self, adapter: LegacyEnrichmentAdapter) -> None:
        """Test virustotal method with non-dict enrichment."""
        # Setup service mock with non-dict enrichment
        adapter.service.enrich_file.return_value = {"enrichment": "not_a_dict"}  # type: ignore[attr-defined]

        result = adapter.virustotal("test_hash")

        assert result is None

    def test_virustotal_method_handles_file_write_errors(self, adapter: LegacyEnrichmentAdapter) -> None:
        """Test virustotal method handles file write errors gracefully."""
        # Setup service mock
        adapter.service.enrich_file.return_value = {"enrichment": {"virustotal": {"test": "data"}}}  # type: ignore[attr-defined]

        # Mock file write to fail
        with patch.object(Path, 'open', side_effect=OSError("Permission denied")):
            result = adapter.virustotal("test_hash")

        # Should still return the result
        assert result is not None
        assert "test" in result  # The test data should be returned

    def test_cache_snapshot_method(self, adapter: LegacyEnrichmentAdapter) -> None:
        """Test cache_snapshot method delegates to service."""
        # Setup service mock
        adapter.service.cache_snapshot.return_value = {"test": 42}  # type: ignore[attr-defined]

        result = adapter.cache_snapshot()

        adapter.service.cache_snapshot.assert_called_once()  # type: ignore[attr-defined]
        assert result == {"test": 42}

    def test_get_session_enrichment_caches_results(self, adapter: LegacyEnrichmentAdapter) -> None:
        """Test _get_session_enrichment caches results correctly."""
        # Setup service mock
        adapter.service.enrich_session.return_value = {  # type: ignore[attr-defined]
            "enrichment": {
                "dshield": {"ip": {"asname": "Test", "ascountry": "US"}},
                "urlhaus": ["malware"],
                "spur": ["", "", "", "DATACENTER"],
            }
        }

        # First call should hit service
        result1 = adapter._get_session_enrichment("192.168.1.1")
        adapter.service.enrich_session.assert_called_once_with("192.168.1.1", "192.168.1.1")  # type: ignore[attr-defined]

        # Second call should use cache
        adapter.service.enrich_session.reset_mock()  # type: ignore[attr-defined]
        result2 = adapter._get_session_enrichment("192.168.1.1")
        adapter.service.enrich_session.assert_not_called()  # type: ignore[attr-defined]

        assert result1 == result2

    def test_get_file_enrichment_caches_results(self, adapter: LegacyEnrichmentAdapter) -> None:
        """Test _get_file_enrichment caches results correctly."""
        # Setup service mock
        adapter.service.enrich_file.return_value = {"enrichment": {"virustotal": {"test": "data"}}}  # type: ignore[attr-defined]

        # First call should hit service
        result1 = adapter._get_file_enrichment("test_hash", "test.exe")
        adapter.service.enrich_file.assert_called_once_with("test_hash", "test.exe")  # type: ignore[attr-defined]

        # Second call should use cache
        adapter.service.enrich_file.reset_mock()  # type: ignore[attr-defined]
        result2 = adapter._get_file_enrichment("test_hash", "test.exe")
        adapter.service.enrich_file.assert_not_called()  # type: ignore[attr-defined]

        assert result1 == result2

    def test_adapter_disabled_with_skip_enrich(self, mock_cache_manager: Mock, mock_cache_dir: Path) -> None:
        """Test adapter is disabled when skip_enrich=True."""
        # Create adapter with mocked service
        adapter = LegacyEnrichmentAdapter(
            cache_manager=mock_cache_manager,
            cache_dir=mock_cache_dir,
            vt_api=None,
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
            skip_enrich=True,
        )
        adapter.service = Mock()  # Mock the service

        assert adapter.enabled is False

        # All methods should return empty/default values when disabled
        assert adapter.dshield("192.168.1.1") == {"ip": {"asname": "", "ascountry": ""}}
        assert adapter.urlhaus("192.168.1.1") == ""
        assert len(adapter.spur("192.168.1.1")) == 18  # Should return 18 empty strings
        assert adapter.virustotal("test_hash") is None

    def test_adapter_service_initialization(self, mock_cache_manager: Mock, mock_cache_dir: Path) -> None:
        """Test adapter properly initializes EnrichmentService."""
        adapter = LegacyEnrichmentAdapter(
            cache_manager=mock_cache_manager,
            cache_dir=mock_cache_dir,
            vt_api="vt_key",
            dshield_email="email@test.com",
            urlhaus_api="urlhaus_token",
            spur_api="spur_key",
            skip_enrich=False,
        )

        # Verify service was initialized with correct parameters
        assert adapter.service.cache_dir == mock_cache_dir
        assert adapter.service.vt_api == "vt_key"
        assert adapter.service.dshield_email == "email@test.com"
        assert adapter.service.urlhaus_api == "urlhaus_token"
        assert adapter.service.spur_api == "spur_key"
        assert adapter.service.cache_manager == mock_cache_manager

    def test_adapter_cache_independence(self, adapter: LegacyEnrichmentAdapter) -> None:
        """Test session and file caches are independent."""
        # Setup different data for session and file caches
        adapter.service.enrich_session.return_value = {"enrichment": {"dshield": {"test": "session"}}}  # type: ignore[attr-defined]
        adapter.service.enrich_file.return_value = {"enrichment": {"virustotal": {"test": "file"}}}  # type: ignore[attr-defined]

        # Cache session data
        adapter._get_session_enrichment("192.168.1.1")
        # Cache file data
        adapter._get_file_enrichment("test_hash", "test.exe")

        # Verify caches are separate
        assert "192.168.1.1" in adapter._session_cache
        assert "test_hash" in adapter._file_cache
        assert adapter._session_cache != adapter._file_cache
