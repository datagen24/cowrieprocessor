"""Unit tests for external enrichment helpers with edge mocking."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

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
