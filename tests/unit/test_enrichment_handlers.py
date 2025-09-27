"""Unit tests for external enrichment helpers with edge mocking."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest
import requests

import enrichment_handlers


class DummySession:
    """Simple stub for requests.Session objects."""

    def __init__(self, response: SimpleNamespace) -> None:
        """Initialise the dummy session with a predetermined response."""
        self._response = response
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, float]] = []
        self.closed = False

    def get(self, url: str, timeout: float) -> SimpleNamespace:
        """Record a GET call and return the canned response."""
        self.calls.append((url, timeout))
        return self._response

    def post(self, url: str, headers: dict[str, str], data: dict[str, str], timeout: float) -> SimpleNamespace:
        """Record a POST call and return the canned response."""
        self.calls.append((url, timeout))
        return self._response

    def close(self) -> None:
        """Mark the session as closed."""
        self.closed = True


def _dummy_response(text: str, *, json_payload: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        raise_for_status=lambda: None,
        json=(lambda: json_payload) if json_payload is not None else None,
    )


def test_vt_query_writes_cache(tmp_path: Path) -> None:
    """Ensure VirusTotal lookups write responses to the cache directory."""
    response = _dummy_response('{"status": "ok"}')
    session = DummySession(response)

    enrichment_handlers.vt_query(
        "feedface",
        tmp_path,
        "api-key",
        session_factory=lambda: cast(requests.Session, session),
    )

    vt_file = tmp_path / "feedface"
    assert vt_file.read_text(encoding="utf-8") == '{"status": "ok"}'
    assert session.calls == [("https://www.virustotal.com/api/v3/files/feedface", 30)]
    assert session.closed is True


def test_dshield_query_uses_cache(tmp_path: Path) -> None:
    """Verify DShield results are cached and reused within the TTL window."""
    response = _dummy_response("ignored", json_payload={"ip": {"asname": "Example ASN", "ascountry": "US"}})
    session = DummySession(response)

    data = enrichment_handlers.dshield_query(
        "203.0.113.10",
        "analyst@example.com",
        cache_base=tmp_path,
        session_factory=lambda: cast(requests.Session, session),
        now=lambda: 1_000_000.0,
    )

    assert data["ip"]["asname"] == "Example ASN"
    assert session.calls == [("https://dshield.org/api/ip/203.0.113.10?email=analyst@example.com", 30)]

    # Second call should hit the cache and avoid a new HTTP request.
    def fail_factory() -> requests.Session:
        raise AssertionError("unexpected network call")

    cached = enrichment_handlers.dshield_query(
        "203.0.113.10",
        "analyst@example.com",
        cache_base=tmp_path,
        session_factory=fail_factory,
        now=lambda: 1_000_100.0,
    )
    assert cached == data


def test_dshield_query_handles_malformed_cache(tmp_path: Path) -> None:
    """Malformed cache contents should be ignored gracefully."""
    cache_file = tmp_path / "dshield_203.0.113.10.json"
    cache_file.write_text("{not-json}", encoding="utf-8")

    response = _dummy_response("ignored", json_payload={"ip": {"asname": "Fallback", "ascountry": "US"}})
    session = DummySession(response)

    data = enrichment_handlers.dshield_query(
        "203.0.113.10",
        "analyst@example.com",
        cache_base=tmp_path,
        session_factory=lambda: cast(requests.Session, session),
        now=lambda: 2_000_000.0,
    )

    assert data["ip"]["asname"] == "Fallback"


def test_safe_read_uh_data_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeouts in URLHaus fetches should surface as ``TIMEOUT``."""

    def raise_timeout(*_args, **_kwargs):
        raise TimeoutError

    monkeypatch.setattr(enrichment_handlers, "with_timeout", raise_timeout)

    result = enrichment_handlers.safe_read_uh_data(
        "203.0.113.10",
        "token",
        cache_base=tmp_path,
    )
    assert result == "TIMEOUT"


def test_read_uh_data_parses_and_sorts_tags(tmp_path: Path) -> None:
    """The helper should parse tags from the cached JSON payload."""
    payload = {
        "urls": [
            {"tags": ["zzz", "aaa"]},
            {"tags": ["aaa", "bbb"]},
        ]
    }
    cache_path = tmp_path / "uh_203.0.113.10"
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    result = enrichment_handlers.read_uh_data(
        "203.0.113.10",
        "token",
        cache_base=tmp_path,
    )

    assert result == "aaa, bbb, zzz"


def test_read_uh_data_returns_empty_on_invalid_payload(tmp_path: Path) -> None:
    """Invalid JSON payloads should return an empty string."""
    cache_path = tmp_path / "uh_203.0.113.10"
    cache_path.write_text("not-json", encoding="utf-8")

    result = enrichment_handlers.read_uh_data(
        "203.0.113.10",
        "token",
        cache_base=tmp_path,
    )

    assert result == ""


def test_read_spur_data_parses_cached_json(tmp_path: Path) -> None:
    """Ensure SPUR cache files are parsed into the expected field order."""
    spur_dir = tmp_path
    spur_path = spur_dir / "spur_203.0.113.10.json"
    spur_payload = {
        "asn": {"number": 64500, "organization": "Example AS"},
        "organization": "Example Org",
        "infrastructure": "Hosting",
        "client": {
            "behaviors": ["botnet"],
            "proxies": "tor",
            "types": ["server"],
            "count": 12,
            "concentration": "medium",
            "countries": ["US", "DE"],
            "spread": "global",
        },
        "risks": ["malware"],
        "services": ["ssh"],
        "location": {"city": "Miami", "country": "US"},
        "tunnels": [
            {
                "anonymous": "yes",
                "entries": 3,
                "operator": "Acme",
                "type": "tor",
            }
        ],
    }
    spur_path.write_text(json.dumps(spur_payload), encoding="utf-8")

    values = enrichment_handlers.read_spur_data(
        "203.0.113.10",
        "spur-token",
        cache_base=tmp_path,
    )

    assert values[0] == "64500"
    assert values[1] == "Example AS"
    assert values[4] == "['botnet']"
    assert values[13] == "Miami, US"
    assert values[-4:] == ["yes", "3", "Acme", "tor"]


def test_read_spur_data_returns_empty_on_invalid_payload(tmp_path: Path) -> None:
    """Malformed SPUR payloads should return an empty list."""
    (tmp_path / "spur_203.0.113.10.json").write_text("not-json", encoding="utf-8")

    values = enrichment_handlers.read_spur_data(
        "203.0.113.10",
        "spur-token",
        cache_base=tmp_path,
    )

    assert values == ["" for _ in range(18)]


# Additional VirusTotal tests
def test_vt_query_handles_404_response(tmp_path: Path) -> None:
    """VirusTotal 404 responses should be handled gracefully."""
    mock_response = SimpleNamespace(
        status_code=404,
        text='{"error": {"code": "NotFoundError", "message": "File not found"}}',
        raise_for_status=lambda: None,
    )

    session = DummySession(mock_response)

    enrichment_handlers.vt_query(
        "nonexistent_hash",
        tmp_path,
        "api-key",
        session_factory=lambda: cast(requests.Session, session),
    )

    # Should cache the 404 response
    vt_file = tmp_path / "nonexistent_hash"
    assert vt_file.exists()
    cached = json.loads(vt_file.read_text(encoding="utf-8"))
    assert "error" in cached


def test_vt_query_handles_rate_limit(tmp_path: Path) -> None:
    """VirusTotal rate limiting should be handled gracefully."""
    mock_response = SimpleNamespace(
        status_code=429,
        text='{"error": {"code": "QuotaExceededError", "message": "Rate limit exceeded"}}',
        raise_for_status=lambda: None,
    )

    session = DummySession(mock_response)

    enrichment_handlers.vt_query(
        "test_hash",
        tmp_path,
        "api-key",
        session_factory=lambda: cast(requests.Session, session),
    )

    # Should not cache rate limit responses
    vt_file = tmp_path / "test_hash"
    assert not vt_file.exists()


def test_vt_query_handles_network_error(tmp_path: Path) -> None:
    """Network errors should be handled gracefully without caching."""

    def failing_session():
        raise requests.exceptions.ConnectionError("Network unreachable")

    enrichment_handlers.vt_query(
        "test_hash",
        tmp_path,
        "api-key",
        session_factory=failing_session,
    )

    # Should not create cache file on error
    vt_file = tmp_path / "test_hash"
    assert not vt_file.exists()


def test_vt_query_skips_enrichment_when_disabled(tmp_path: Path) -> None:
    """VT queries should be skipped when enrichment is disabled."""
    session = DummySession(SimpleNamespace(text="{}", raise_for_status=lambda: None))

    enrichment_handlers.vt_query(
        "test_hash",
        tmp_path,
        "api-key",
        skip_enrich=True,
        session_factory=lambda: cast(requests.Session, session),
    )

    # Should not make any API calls
    assert session.calls == []
    vt_file = tmp_path / "test_hash"
    assert not vt_file.exists()


# Additional DShield tests
def test_dshield_query_handles_expired_cache(tmp_path: Path) -> None:
    """Expired cache entries should trigger fresh API calls."""
    # Create expired cache entry
    expired_data = {
        "timestamp": 0,  # Very old timestamp
        "data": {"ip": {"asname": "Old ASN", "ascountry": "US"}},
    }
    cache_file = tmp_path / "dshield_203.0.113.10.json"
    cache_file.write_text(json.dumps(expired_data), encoding="utf-8")

    response = _dummy_response("ignored", json_payload={"ip": {"asname": "New ASN", "ascountry": "US"}})
    session = DummySession(response)

    data = enrichment_handlers.dshield_query(
        "203.0.113.10",
        "analyst@example.com",
        cache_base=tmp_path,
        session_factory=lambda: cast(requests.Session, session),
        ttl_seconds=3600,  # 1 hour TTL
        now=lambda: 7200,  # 2 hours later (expired)
    )

    # Should fetch fresh data
    assert data["ip"]["asname"] == "New ASN"
    assert session.calls == [("https://dshield.org/api/ip/203.0.113.10?email=analyst@example.com", 30)]


def test_dshield_query_handles_api_error() -> None:
    """DShield API errors should return safe defaults."""

    def failing_session():
        raise requests.exceptions.HTTPError("500 Internal Server Error")

    data = enrichment_handlers.dshield_query(
        "203.0.113.10",
        "analyst@example.com",
        session_factory=failing_session,
    )

    # Should return safe defaults
    assert data == {"ip": {"asname": "", "ascountry": ""}}


def test_dshield_query_handles_timeout(tmp_path: Path) -> None:
    """DShield timeouts should return safe defaults."""

    def timeout_session():
        raise requests.exceptions.Timeout("Request timed out")

    data = enrichment_handlers.dshield_query(
        "203.0.113.10",
        "analyst@example.com",
        cache_base=tmp_path,
        session_factory=timeout_session,
    )

    # Should return safe defaults
    assert data == {"ip": {"asname": "", "ascountry": ""}}


# Additional URLHaus tests
def test_read_uh_data_caches_response(tmp_path: Path) -> None:
    """URLHaus responses should be cached properly."""
    response_text = json.dumps(
        {
            "query_status": "ok",
            "urls": [
                {"tags": ["malware", "trojan"]},
                {"tags": ["botnet", "scanner"]},
            ],
        }
    )

    mock_response = SimpleNamespace(
        text=response_text,
        raise_for_status=lambda: None,
    )

    session = DummySession(mock_response)

    result = enrichment_handlers.read_uh_data(
        "203.0.113.10",
        "api-key",
        cache_base=tmp_path,
        session_factory=lambda: cast(requests.Session, session),
    )

    # Should cache the response
    cache_file = tmp_path / "uh_203.0.113.10"
    assert cache_file.exists()

    # Second call should use cache
    result2 = enrichment_handlers.read_uh_data(
        "203.0.113.10",
        "api-key",
        cache_base=tmp_path,
        session_factory=lambda: cast(requests.Session, DummySession(SimpleNamespace(text="should not be called"))),
    )

    assert result == result2 == "botnet, malware, scanner, trojan"


def test_read_uh_data_handles_no_results(tmp_path: Path) -> None:
    """URLHaus responses with no results should return empty string."""
    response_text = json.dumps({"query_status": "no_results"})

    mock_response = SimpleNamespace(
        text=response_text,
        raise_for_status=lambda: None,
    )

    session = DummySession(mock_response)

    result = enrichment_handlers.read_uh_data(
        "203.0.113.10",
        "api-key",
        cache_base=tmp_path,
        session_factory=lambda: cast(requests.Session, session),
    )

    assert result == ""


def test_read_uh_data_handles_api_failure(tmp_path: Path) -> None:
    """URLHaus API failures should return empty string."""

    def failing_session():
        raise requests.exceptions.RequestException("API unavailable")

    result = enrichment_handlers.read_uh_data(
        "203.0.113.10",
        "api-key",
        cache_base=tmp_path,
        session_factory=failing_session,
    )

    assert result == ""


def test_safe_read_uh_data_timeout_protection(tmp_path: Path) -> None:
    """Safe wrapper should handle timeouts gracefully."""

    def slow_function(*args, **kwargs):
        time.sleep(5)  # Longer than timeout
        return "completed"

    with patch.object(enrichment_handlers, 'with_timeout', side_effect=TimeoutError("Operation timed out")):
        result = enrichment_handlers.safe_read_uh_data(
            "203.0.113.10",
            "api-key",
            cache_base=tmp_path,
            timeout=1,  # 1 second timeout
        )

    assert result == "TIMEOUT"


# Additional SPUR tests
def test_read_spur_data_handles_missing_fields(tmp_path: Path) -> None:
    """SPUR responses with missing fields should use defaults."""
    incomplete_payload = {
        "asn": {"number": 12345},
        "organization": "Test Org",
        # Missing infrastructure, client, etc.
    }

    spur_path = tmp_path / "spur_203.0.113.10.json"
    spur_path.write_text(json.dumps(incomplete_payload), encoding="utf-8")

    values = enrichment_handlers.read_spur_data(
        "203.0.113.10",
        "spur-token",
        cache_base=tmp_path,
    )

    # Should have 18 fields with defaults for missing ones
    assert len(values) == 18
    assert values[0] == "12345"  # ASN number
    assert values[1] == ""  # ASN organization (missing)
    assert values[2] == "Test Org"  # Organization


def test_read_spur_data_handles_nested_client_schema(tmp_path: Path) -> None:
    """SPUR responses with nested client schema should be parsed correctly."""
    nested_payload = {
        "asn": {"number": 67890, "organization": "Nested AS"},
        "client_behaviors": ["SCANNER"],
        "client_proxies": "VPN",
        "client_types": ["MOBILE"],
        "client_count": 5,
    }

    spur_path = tmp_path / "spur_203.0.113.10.json"
    spur_path.write_text(json.dumps(nested_payload), encoding="utf-8")

    values = enrichment_handlers.read_spur_data(
        "203.0.113.113",
        "spur-token",
        cache_base=tmp_path,
    )

    assert values[0] == "67890"
    assert values[1] == "Nested AS"
    assert values[4] == "['SCANNER']"  # Legacy nested format
    assert values[5] == "VPN"
    assert values[6] == "['MOBILE']"
    assert values[7] == "5"


def test_read_spur_data_handles_tunnel_parsing(tmp_path: Path) -> None:
    """SPUR tunnel data should be parsed correctly."""
    payload_with_tunnels = {
        "asn": {"number": 11111},
        "tunnels": [
            {"anonymous": "YES", "entries": "15", "operator": "TestVPN", "type": "OPENVPN"},
            {"anonymous": "NO", "entries": "3", "operator": "Corporate", "type": "IPSEC"},
        ],
    }

    spur_path = tmp_path / "spur_192.168.1.1.json"
    spur_path.write_text(json.dumps(payload_with_tunnels), encoding="utf-8")

    values = enrichment_handlers.read_spur_data(
        "192.168.1.1",
        "spur-token",
        cache_base=tmp_path,
    )

    # Should use the first tunnel entry
    assert values[-4:] == ["YES", "15", "TestVPN", "OPENVPN"]


# Cache behavior tests
def test_cache_ttl_expiration(tmp_path: Path) -> None:
    """Cache TTL should be respected across all services."""
    # Test DShield cache expiration
    old_timestamp = time.time() - 7200  # 2 hours ago
    expired_cache = {"timestamp": old_timestamp, "data": {"ip": {"asname": "Old", "ascountry": "US"}}}

    cache_file = tmp_path / "dshield_203.0.113.10.json"
    cache_file.write_text(json.dumps(expired_cache), encoding="utf-8")

    response = _dummy_response("ignored", json_payload={"ip": {"asname": "New", "ascountry": "US"}})
    session = DummySession(response)

    data = enrichment_handlers.dshield_query(
        "203.0.113.10",
        "analyst@example.com",
        cache_base=tmp_path,
        session_factory=lambda: cast(requests.Session, session),
        ttl_seconds=3600,  # 1 hour TTL
        now=lambda: old_timestamp + 7200,  # 2 hours later
    )

    # Should fetch fresh data due to expiration
    assert data["ip"]["asname"] == "New"
    assert len(session.calls) == 1


def test_concurrent_cache_access(tmp_path: Path) -> None:
    """Concurrent access to cache files should be handled safely."""
    import threading

    results = []
    errors = []

    def worker():
        try:
            # Multiple threads accessing same cache file
            data = enrichment_handlers.dshield_query(
                "203.0.113.10",
                "analyst@example.com",
                cache_base=tmp_path,
                skip_enrich=True,  # Skip actual API calls
            )
            results.append(data)
        except Exception as e:
            errors.append(e)

    # Run multiple threads concurrently
    threads = [threading.Thread(target=worker) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Should complete without errors
    assert len(errors) == 0
    assert len(results) == 5
    # All results should be identical (safe defaults)
    assert all(r == results[0] for r in results)


# Error handling and edge cases
def test_all_services_handle_empty_api_keys(tmp_path: Path) -> None:
    """All services should handle empty/missing API keys gracefully."""
    services = [
        ("vt", lambda: enrichment_handlers.vt_query("test", tmp_path, "")),
        ("dshield", lambda: enrichment_handlers.dshield_query("1.2.3.4", "")),
        ("urlhaus", lambda: enrichment_handlers.safe_read_uh_data("1.2.3.4", "")),
        ("spur", lambda: enrichment_handlers.read_spur_data("1.2.3.4", "")),
    ]

    for service_name, service_func in services:
        result = service_func()

        if service_name == "vt":
            # VT query should return None (no exception)
            assert result is None
        elif service_name == "dshield":
            # DShield should return safe defaults
            assert result == {"ip": {"asname": "", "ascountry": ""}}
        elif service_name == "urlhaus":
            # URLHaus should return empty string
            assert result == ""
        elif service_name == "spur":
            # SPUR should return empty payload
            assert result == [""] * 18


def test_all_services_handle_skip_enrich_flag(tmp_path: Path) -> None:
    """All services should respect the skip_enrich flag."""
    services = [
        ("vt", lambda: enrichment_handlers.vt_query("test", tmp_path, "key", skip_enrich=True)),
        ("dshield", lambda: enrichment_handlers.dshield_query("1.2.3.4", "email", skip_enrich=True)),
        ("urlhaus", lambda: enrichment_handlers.safe_read_uh_data("1.2.3.4", "key", skip_enrich=True)),
        ("spur", lambda: enrichment_handlers.read_spur_data("1.2.3.4", "key", skip_enrich=True)),
    ]

    for service_name, service_func in services:
        result = service_func()

        if service_name == "vt":
            assert result is None
        elif service_name == "dshield":
            assert result == {"ip": {"asname": "", "ascountry": ""}}
        elif service_name == "urlhaus":
            assert result == ""
        elif service_name == "spur":
            assert result == [""] * 18


def test_malformed_responses_handled_gracefully(tmp_path: Path) -> None:
    """All services should handle malformed API responses gracefully."""
    malformed_responses = {
        "vt": "{invalid json",
        "dshield": "{invalid json",
        "urlhaus": "{invalid json",
        "spur": "{invalid json",
    }

    # Create mock sessions that return malformed JSON
    class MalformedSession:
        def __init__(self, response_text):
            self.response_text = response_text
            self.calls = []
            self.closed = False

        def get(self, url, timeout=30):
            self.calls.append(("GET", url, timeout))
            return SimpleNamespace(
                text=self.response_text,
                raise_for_status=lambda: None,
            )

        def post(self, url, headers, data, timeout=30):
            self.calls.append(("POST", url, headers, data, timeout))
            return SimpleNamespace(
                text=self.response_text,
                raise_for_status=lambda: None,
            )

        def close(self):
            self.closed = True

    # Test each service
    services = [
        ("dshield", enrichment_handlers.dshield_query, "1.2.3.4", "email"),
        ("urlhaus", enrichment_handlers.read_uh_data, "1.2.3.4", "key"),
        ("spur", enrichment_handlers.read_spur_data, "1.2.3.4", "key"),
    ]

    for service_name, service_func, *args in services:
        session = MalformedSession(malformed_responses[service_name])

        if service_name == "dshield":
            result = service_func(*args, session_factory=lambda: cast(requests.Session, session))  # type: ignore
            assert result == {"ip": {"asname": "", "ascountry": ""}}
        elif service_name == "urlhaus":
            result = service_func(*args, cache_base=tmp_path, session_factory=lambda: cast(requests.Session, session))  # type: ignore
            assert result == ""
        elif service_name == "spur":
            result = service_func(*args, cache_base=tmp_path, session_factory=lambda: cast(requests.Session, session))  # type: ignore
            assert result == [""] * 18

        assert session.calls  # Should have made API calls
        assert session.closed  # Should have closed session
