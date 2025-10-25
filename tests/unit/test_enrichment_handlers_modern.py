"""Tests for modern enrichment handlers (enrichment/handlers.py).

Tests the EnrichmentService class and related helper functions for coordinating
external enrichment lookups with caching, rate limiting, and telemetry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

from cowrieprocessor.enrichment.handlers import (
    EnrichmentService,
    _cache_path,
    _coerce_int,
    _empty_dshield,
    _parse_spur_payload,
    _parse_urlhaus_tags,
    _resolve_cache_base,
    _stringify,
    DEFAULT_CACHE_BASE,
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
