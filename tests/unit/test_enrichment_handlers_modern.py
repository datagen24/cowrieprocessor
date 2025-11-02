"""Tests for modern enrichment handlers (enrichment/handlers.py).

Tests the EnrichmentService class and related helper functions for coordinating
external enrichment lookups with caching, rate limiting, and telemetry.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from cowrieprocessor.enrichment.handlers import (
    DEFAULT_CACHE_BASE,
    EnrichmentService,
    _cache_path,
    _coerce_int,
    _empty_dshield,
    _parse_spur_payload,
    _parse_urlhaus_tags,
    _resolve_cache_base,
    _stringify,
)


class TestHelperFunctions:
    """Test module-level helper functions."""

    def test_resolve_cache_base_with_path(self, tmp_path: Path) -> None:
        """Test cache base resolution with provided path."""
        result = _resolve_cache_base(tmp_path)
        assert result == tmp_path

    def test_resolve_cache_base_with_none(self) -> None:
        """Test cache base resolution with None (uses default)."""
        result = _resolve_cache_base(None)
        assert result == DEFAULT_CACHE_BASE

    def test_cache_path(self, tmp_path: Path) -> None:
        """Test cache path construction."""
        base = tmp_path
        name = "test_cache.json"
        result = _cache_path(base, name)
        assert result == base / name
        assert result.parent == base

    def test_stringify_none(self) -> None:
        """Test stringify with None value."""
        assert _stringify(None) == ""

    def test_stringify_string(self) -> None:
        """Test stringify with string value."""
        assert _stringify("test") == "test"

    def test_stringify_int(self) -> None:
        """Test stringify with integer value."""
        assert _stringify(42) == "42"

    def test_stringify_list(self) -> None:
        """Test stringify with list value."""
        result = _stringify([1, 2, 3])
        assert result == "[1, 2, 3]"

    def test_stringify_dict(self) -> None:
        """Test stringify with dict value."""
        result = _stringify({"key": "value"})
        assert "key" in result
        assert "value" in result

    def test_empty_dshield(self) -> None:
        """Test empty DShield payload generation."""
        result = _empty_dshield()
        assert result == {"ip": {"asname": "", "ascountry": ""}}
        assert "ip" in result
        assert result["ip"]["asname"] == ""
        assert result["ip"]["ascountry"] == ""

    def test_coerce_int_with_int(self) -> None:
        """Test coerce_int with integer value."""
        assert _coerce_int(42) == 42

    def test_coerce_int_with_string(self) -> None:
        """Test coerce_int with string value."""
        assert _coerce_int("42") == 42

    def test_coerce_int_with_invalid(self) -> None:
        """Test coerce_int with invalid value."""
        assert _coerce_int("not_a_number") == 0
        assert _coerce_int(None) == 0

    def test_parse_urlhaus_tags_with_tags(self) -> None:
        """Test URLHaus tag parsing with valid tags."""
        payload = '{"urls": [{"tags": ["malware", "trojan"]}, {"tags": ["botnet"]}]}'
        result = _parse_urlhaus_tags(payload)
        assert result == "botnet, malware, trojan"  # Sorted and comma-space separated

    def test_parse_urlhaus_tags_empty(self) -> None:
        """Test URLHaus tag parsing with empty tags."""
        payload = '{"tags": []}'
        result = _parse_urlhaus_tags(payload)
        assert result == ""

    def test_parse_urlhaus_tags_invalid_json(self) -> None:
        """Test URLHaus tag parsing with invalid JSON."""
        payload = "not json"
        result = _parse_urlhaus_tags(payload)
        assert result == ""

    def test_parse_spur_payload_valid(self) -> None:
        """Test SPUR payload parsing with valid data."""
        payload = '{"asn": {"number": "12345", "organization": "Test Org"}, "client": {"proxies": ["proxy1"]}}'
        result = _parse_spur_payload(payload)
        assert len(result) == 18
        assert result[0] == "12345"  # ASN number
        assert result[1] == "Test Org"  # ASN organization
        assert "proxy1" in result[5]  # Client proxies field (index 5)

    def test_parse_spur_payload_invalid(self) -> None:
        """Test SPUR payload parsing with invalid JSON."""
        payload = "not json"
        result = _parse_spur_payload(payload)
        assert len(result) == 18
        assert all(field == "" for field in result)


class TestEnrichmentServiceInit:
    """Test EnrichmentService initialization."""

    def test_init_minimal(self, tmp_path: Path) -> None:
        """Test initialization with minimal parameters."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api=None,
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
        )

        assert service.cache_dir == tmp_path
        assert tmp_path.exists()  # Cache dir created
        assert service.vt_api == ""
        assert service.dshield_email == ""
        assert service.urlhaus_api == ""
        assert service.spur_api == ""
        assert service.skip_enrich is False
        assert service.enable_rate_limiting is True
        assert service.enable_telemetry is True

    def test_init_with_api_keys(self, tmp_path: Path) -> None:
        """Test initialization with API keys."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api="vt-key-123",
            dshield_email="test@example.com",
            urlhaus_api="uh-key-456",
            spur_api="spur-key-789",
        )

        assert service.vt_api == "vt-key-123"
        assert service.dshield_email == "test@example.com"
        assert service.urlhaus_api == "uh-key-456"
        assert service.spur_api == "spur-key-789"

    def test_init_skip_enrich(self, tmp_path: Path) -> None:
        """Test initialization with skip_enrich enabled."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api=None,
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
            skip_enrich=True,
        )

        assert service.skip_enrich is True
        assert service.vt_handler.skip_enrich is True

    def test_init_disable_rate_limiting(self, tmp_path: Path) -> None:
        """Test initialization with rate limiting disabled."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api=None,
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
            enable_rate_limiting=False,
        )

        assert service.enable_rate_limiting is False

    def test_init_disable_telemetry(self, tmp_path: Path) -> None:
        """Test initialization with telemetry disabled."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api=None,
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
            enable_telemetry=False,
        )

        assert service.telemetry is None

    def test_init_with_custom_cache_manager(self, tmp_path: Path) -> None:
        """Test initialization with custom cache manager."""
        from cowrieprocessor.enrichment import EnrichmentCacheManager

        custom_manager = EnrichmentCacheManager(tmp_path)
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api=None,
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
            cache_manager=custom_manager,
        )

        assert service.cache_manager is custom_manager


class TestEnrichmentServiceBasicMethods:
    """Test basic EnrichmentService methods."""

    def test_cache_snapshot(self, tmp_path: Path) -> None:
        """Test cache statistics snapshot retrieval."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api=None,
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
        )

        snapshot = service.cache_snapshot()
        assert isinstance(snapshot, dict)
        # Snapshot should contain cache statistics

    def test_get_vt_quota_status_no_manager(self, tmp_path: Path) -> None:
        """Test VT quota status when quota management disabled."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api="test-key",
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
            enable_vt_quota_management=False,
        )

        status = service.get_vt_quota_status()
        assert status["status"] == "disabled"

    def test_close_cleanup(self, tmp_path: Path) -> None:
        """Test service cleanup on close."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api="test-key",
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
        )

        # Should not raise
        service.close()

    def test_context_manager(self, tmp_path: Path) -> None:
        """Test EnrichmentService as context manager."""
        with EnrichmentService(
            cache_dir=tmp_path,
            vt_api=None,
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
        ) as service:
            assert isinstance(service, EnrichmentService)
            assert service.cache_dir == tmp_path


class TestEnrichmentServiceFlags:
    """Test EnrichmentService flag detection methods."""

    def test_dshield_flag_with_counts(self) -> None:
        """Test DShield flag detection with attack counts."""
        payload = {"ip": {"count": "5", "attacks": "10"}}
        assert EnrichmentService._dshield_flag(payload) is True

    def test_dshield_flag_without_counts(self) -> None:
        """Test DShield flag detection without counts."""
        payload = {"ip": {"count": "0", "attacks": "0"}}
        assert EnrichmentService._dshield_flag(payload) is False

    def test_dshield_flag_invalid_payload(self) -> None:
        """Test DShield flag with invalid payload."""
        payload = {"invalid": "data"}
        assert EnrichmentService._dshield_flag(payload) is False

    def test_urlhaus_flag_with_tags(self) -> None:
        """Test URLHaus flag detection with tags."""
        payload = "malware,trojan"
        assert EnrichmentService._urlhaus_flag(payload) is True

    def test_urlhaus_flag_empty(self) -> None:
        """Test URLHaus flag detection with empty tags."""
        payload = ""
        assert EnrichmentService._urlhaus_flag(payload) is False

    def test_spur_flag_with_vpn(self) -> None:
        """Test SPUR flag detection with VPN infrastructure."""
        payload = ["" for _ in range(18)]
        payload[3] = "VPN"  # Infrastructure field (index 3)
        assert EnrichmentService._spur_flag(payload) is True

    def test_spur_flag_without_vpn(self) -> None:
        """Test SPUR flag detection without VPN."""
        payload = ["" for _ in range(18)]
        assert EnrichmentService._spur_flag(payload) is False

    def test_vt_flag_with_malicious(self, tmp_path: Path) -> None:
        """Test VT flag detection with malicious file."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api="test-key",
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
        )

        payload = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {
                        "malicious": 5,
                        "harmless": 10,
                    }
                }
            }
        }

        assert service._vt_flag(payload) is True

    def test_vt_flag_without_malicious(self, tmp_path: Path) -> None:
        """Test VT flag detection without malicious indicators."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api="test-key",
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
        )

        payload = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {
                        "malicious": 0,
                        "harmless": 60,
                    }
                }
            }
        }

        assert service._vt_flag(payload) is False

    def test_get_session_flags_with_enrichments(self, tmp_path: Path) -> None:
        """Test session flag extraction with all enrichments."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api="test-key",
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
        )

        spur_payload = ["" for i in range(18)]
        spur_payload[3] = "VPN"  # Infrastructure field

        session_result = {
            "enrichment": {
                "dshield": {"ip": {"count": "5", "attacks": "10"}},
                "urlhaus": "malware",
                "spur": spur_payload,
            }
        }

        flags = service.get_session_flags(session_result)

        assert flags["dshield_flagged"] is True
        assert flags["urlhaus_flagged"] is True
        assert flags["spur_flagged"] is True

    def test_get_session_flags_empty(self, tmp_path: Path) -> None:
        """Test session flag extraction with empty enrichments."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api=None,
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
        )

        session_result = {}
        flags = service.get_session_flags(session_result)

        assert flags["dshield_flagged"] is False
        assert flags["urlhaus_flagged"] is False
        assert flags["spur_flagged"] is False


class TestEnrichmentServiceEnrich:
    """Test EnrichmentService enrichment methods."""

    @patch('cowrieprocessor.enrichment.handlers.dshield_query')
    def test_enrich_session_skip_enrich(self, mock_dshield: Mock, tmp_path: Path) -> None:
        """Test session enrichment with skip_enrich enabled."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api=None,
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
            skip_enrich=True,
        )

        result = service.enrich_session("session-123", "192.168.1.1")

        # Should return structured response with empty enrichments
        assert result["session_id"] == "session-123"
        assert result["src_ip"] == "192.168.1.1"
        assert result["enrichment"]["dshield"] == {"ip": {"asname": "", "ascountry": ""}}
        assert result["enrichment"]["urlhaus"] == ""
        assert len(result["enrichment"]["spur"]) == 18
        mock_dshield.assert_not_called()

    def test_enrich_file_skip_enrich(self, tmp_path: Path) -> None:
        """Test file enrichment with skip_enrich enabled."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api=None,
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
            skip_enrich=True,
        )

        result = service.enrich_file("abc123", "malware.exe")

        # Should return structured response with None virustotal
        assert result["file_hash"] == "abc123"
        assert result["filename"] == "malware.exe"
        assert result["enrichment"]["virustotal"] is None


class TestCacheIO:
    """Test cache I/O helper functions."""

    def test_read_text_success(self, tmp_path: Path) -> None:
        """Test reading text from existing file."""
        from cowrieprocessor.enrichment.handlers import _read_text

        test_file = tmp_path / "test.txt"
        test_file.write_text("test content", encoding="utf-8")

        result = _read_text(test_file)
        assert result == "test content"

    def test_read_text_not_found(self, tmp_path: Path) -> None:
        """Test reading from non-existent file returns None."""
        from cowrieprocessor.enrichment.handlers import _read_text

        result = _read_text(tmp_path / "nonexistent.txt")
        assert result is None

    def test_write_text_success(self, tmp_path: Path) -> None:
        """Test writing text to file."""
        from cowrieprocessor.enrichment.handlers import _write_text

        test_file = tmp_path / "nested" / "dir" / "test.txt"
        _write_text(test_file, "test content")

        assert test_file.exists()
        assert test_file.read_text(encoding="utf-8") == "test content"
        assert test_file.parent.exists()  # Parent dirs created


class TestRateLimitedSessionFactory:
    """Test rate-limited session factory."""

    def test_create_rate_limited_session_factory(self, tmp_path: Path) -> None:
        """Test creating rate-limited session for a service."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api=None,
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
            enable_rate_limiting=True,
        )

        session = service._create_rate_limited_session_factory("dshield")

        from cowrieprocessor.enrichment.rate_limiting import RateLimitedSession

        assert isinstance(session, RateLimitedSession)
        assert session in service._active_sessions


class TestIteratorMethods:
    """Test iterator and extraction methods."""

    def test_iter_session_enrichments(self, tmp_path: Path) -> None:
        """Test iterating over session enrichments."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api="test-key",
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
        )

        # _iter_session_enrichments expects a "session" key with per-IP mappings
        enrichment = {
            "session": {
                "192.168.1.1": {"dshield": {"ip": {"count": 10}}},
                "192.168.1.2": {"urlhaus": "malware"},
                "192.168.1.3": {"spur": ["AS12345", "Test Org"]},
            }
        }

        results = list(service._iter_session_enrichments(enrichment))
        assert len(results) == 3
        assert results[0]["dshield"]["ip"]["count"] == 10
        assert results[1]["urlhaus"] == "malware"
        assert results[2]["spur"][0] == "AS12345"

    def test_iter_vt_payloads_mapping(self, tmp_path: Path) -> None:
        """Test iterating VT payloads from mapping structure."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api="test-key",
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
        )

        payload = {"data": {"attributes": {"last_analysis_stats": {"malicious": 5}}}}

        results = list(service._iter_vt_payloads(payload))
        assert len(results) == 1
        assert results[0] == payload

    def test_iter_vt_payloads_nested(self, tmp_path: Path) -> None:
        """Test iterating VT payloads from nested structure."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api="test-key",
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
        )

        payload = {"file1": {"data": {"attributes": {}}}, "file2": {"data": {"attributes": {}}}}

        results = list(service._iter_vt_payloads(payload))
        assert len(results) == 2

    def test_iter_vt_payloads_list(self, tmp_path: Path) -> None:
        """Test iterating VT payloads from list structure."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api="test-key",
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
        )

        payload = [{"data": {"attributes": {}}}, {"data": {"attributes": {}}}]

        results = list(service._iter_vt_payloads(payload))
        assert len(results) == 2

    def test_extract_vt_stats(self) -> None:
        """Test extracting VT stats from payload."""
        payload = {"data": {"attributes": {"last_analysis_stats": {"malicious": 5, "harmless": 60, "suspicious": 1}}}}

        stats = EnrichmentService._extract_vt_stats(payload)
        assert stats["malicious"] == 5
        assert stats["harmless"] == 60
        assert stats["suspicious"] == 1


class TestSessionCleanup:
    """Test session cleanup and resource management."""

    def test_close_with_active_sessions(self, tmp_path: Path) -> None:
        """Test cleanup of active sessions on close."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api=None,
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
            enable_rate_limiting=True,
        )

        # Create some sessions
        service._create_rate_limited_session_factory("dshield")
        service._create_rate_limited_session_factory("urlhaus")

        assert len(service._active_sessions) == 2

        # Close should cleanup sessions
        service.close()

        # VT handler should be closed
        assert service.vt_handler is not None


class TestVTPayloadMethods:
    """Test VirusTotal payload loading and fetching."""

    def test_load_vt_payload_from_cache(self, tmp_path: Path) -> None:
        """Test loading VT payload from cache."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api="test-key",
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
        )

        # Create cached VT response (cache_dir/file_hash, no prefix or extension)
        vt_cache_file = tmp_path / "abc123"
        cached_data = {"data": {"attributes": {"last_analysis_stats": {"malicious": 5}}}}
        vt_cache_file.write_text(json.dumps(cached_data), encoding="utf-8")

        result = service._load_vt_payload("abc123")
        assert result == cached_data

    def test_load_vt_payload_cache_miss(self, tmp_path: Path) -> None:
        """Test loading VT payload when cache miss."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api="test-key",
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
        )

        result = service._load_vt_payload("nonexistent")
        assert result is None


class TestEnrichmentIntegration:
    """Test full enrichment workflows with mocked external APIs."""

    @patch("cowrieprocessor.enrichment.handlers.dshield_query")
    @patch("cowrieprocessor.enrichment.handlers.safe_read_uh_data")
    @patch("cowrieprocessor.enrichment.handlers.read_spur_data")
    def test_enrich_session_with_all_apis(
        self, mock_spur: Mock, mock_urlhaus: Mock, mock_dshield: Mock, tmp_path: Path
    ) -> None:
        """Test enriching a session with all API services enabled.

        Given: EnrichmentService with all API keys configured
        When: Calling enrich_session
        Then: Should call all enrichment APIs and return combined results
        """
        # Setup mock responses
        mock_dshield.return_value = {"ip": {"count": 10, "attacks": 5}}
        mock_urlhaus.return_value = '{"urls": [{"tags": ["malware"]}]}'
        mock_spur.return_value = '{"asn": {"number": "12345", "organization": "Test"}}'

        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api="vt-key",
            dshield_email="test@example.com",
            urlhaus_api="uh-key",
            spur_api="spur-key",
        )

        result = service.enrich_session("session-123", "192.168.1.1")

        # Verify structure
        assert result["session_id"] == "session-123"
        assert result["src_ip"] == "192.168.1.1"
        assert "enrichment" in result

        # Verify all APIs were called
        mock_dshield.assert_called_once()
        mock_urlhaus.assert_called_once()
        mock_spur.assert_called_once()

        # Verify enrichment data
        assert result["enrichment"]["dshield"]["ip"]["count"] == 10
        assert "malware" in result["enrichment"]["urlhaus"]
        assert "12345" in result["enrichment"]["spur"]

    @patch("cowrieprocessor.enrichment.handlers.dshield_query")
    def test_enrich_session_dshield_only(self, mock_dshield: Mock, tmp_path: Path) -> None:
        """Test session enrichment with only DShield configured."""
        mock_dshield.return_value = {"ip": {"count": 5}}

        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api=None,
            dshield_email="test@example.com",
            urlhaus_api=None,
            spur_api=None,
        )

        result = service.enrich_session("session-456", "10.0.0.1")

        assert result["enrichment"]["dshield"]["ip"]["count"] == 5
        assert result["enrichment"]["urlhaus"] == ""
        assert isinstance(result["enrichment"]["spur"], list)

    @patch("cowrieprocessor.enrichment.handlers.dshield_query")
    def test_enrich_session_dshield_error(self, mock_dshield: Mock, tmp_path: Path) -> None:
        """Test session enrichment when DShield API fails.

        Given: DShield API raises an exception
        When: Calling enrich_session
        Then: Should handle error gracefully and return empty DShield payload
        """
        mock_dshield.side_effect = Exception("API error")

        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api=None,
            dshield_email="test@example.com",
            urlhaus_api=None,
            spur_api=None,
        )

        result = service.enrich_session("session-789", "10.0.0.2")

        # Should return empty DShield structure on error (from _empty_dshield())
        assert "enrichment" in result
        assert "dshield" in result["enrichment"]
        # _empty_dshield returns {"ip": {"asname": "", "ascountry": ""}}
        assert "ip" in result["enrichment"]["dshield"]
        assert result["enrichment"]["dshield"]["ip"]["asname"] == ""
        assert result["enrichment"]["dshield"]["ip"]["ascountry"] == ""

    @patch("cowrieprocessor.enrichment.handlers.safe_read_uh_data")
    def test_enrich_session_urlhaus_error(self, mock_urlhaus: Mock, tmp_path: Path) -> None:
        """Test session enrichment when URLHaus API fails."""
        mock_urlhaus.side_effect = Exception("URLHaus API error")

        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api=None,
            dshield_email=None,
            urlhaus_api="uh-key",
            spur_api=None,
        )

        result = service.enrich_session("session-error", "10.0.0.3")

        # Should return empty string on URLHaus error
        assert result["enrichment"]["urlhaus"] == ""

    @patch("cowrieprocessor.enrichment.handlers.read_spur_data")
    def test_enrich_session_spur_error(self, mock_spur: Mock, tmp_path: Path) -> None:
        """Test session enrichment when SPUR API fails."""
        mock_spur.side_effect = Exception("SPUR API error")

        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api=None,
            dshield_email=None,
            urlhaus_api=None,
            spur_api="spur-key",
        )

        result = service.enrich_session("session-spur-err", "10.0.0.4")

        # Should return empty SPUR payload on error
        assert isinstance(result["enrichment"]["spur"], list)
        assert len(result["enrichment"]["spur"]) == 18

    def test_enrich_file_with_vt(self, tmp_path: Path) -> None:
        """Test file enrichment with VirusTotal.

        Given: VirusTotal API configured
        When: Calling enrich_file
        Then: Should fetch VT data and return enrichment result
        """
        vt_payload = {"data": {"attributes": {"last_analysis_stats": {"malicious": 10, "suspicious": 2}}}}

        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api="vt-key-123",
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
        )

        # Mock the VT handler's enrich_file method
        service.vt_handler.enrich_file = Mock(return_value=vt_payload)

        result = service.enrich_file("abc123def", "malware.exe")

        assert result["file_hash"] == "abc123def"
        assert result["filename"] == "malware.exe"
        assert result["enrichment"]["virustotal"]["data"]["attributes"]["last_analysis_stats"]["malicious"] == 10

    def test_enrich_file_vt_error(self, tmp_path: Path) -> None:
        """Test file enrichment when VirusTotal API fails."""
        service = EnrichmentService(
            cache_dir=tmp_path,
            vt_api="vt-key-456",
            dshield_email=None,
            urlhaus_api=None,
            spur_api=None,
        )

        # Mock VT handler to raise exception
        service.vt_handler.enrich_file = Mock(side_effect=Exception("VT API error"))

        result = service.enrich_file("def456ghi", "test.bin")

        assert result["file_hash"] == "def456ghi"
        assert result["enrichment"]["virustotal"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
