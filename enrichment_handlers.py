"""External enrichment helpers for Cowrie log analysis.

This module exposes helper functions for enriching Cowrie log data with
VirusTotal, DShield, URLHaus, and SPUR context. Each helper now separates
cache-path resolution, network IO, and payload parsing so that consumers and
unit tests can target the individual pieces.
"""

from __future__ import annotations

import json
import logging
import signal
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import requests

LOGGER = logging.getLogger(__name__)
DEFAULT_CACHE_BASE = Path("/mnt/dshield/data/cache")
DEFAULT_TIMEOUT = 30
_SPUR_EMPTY_PAYLOAD = ["" for _ in range(18)]

SessionFactory = Callable[[], requests.Session]


# ---------------------------------------------------------------------------
# Shared cache helpers
# ---------------------------------------------------------------------------

def _resolve_cache_base(cache_base: Optional[Path]) -> Path:
    return cache_base if cache_base is not None else DEFAULT_CACHE_BASE


def _cache_path(base: Path, name: str) -> Path:
    return base / name


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except Exception:  # pragma: no cover - defensive logging
        LOGGER.debug("Failed reading cache file %s", path, exc_info=True)
        return None


def _write_text(path: Path, payload: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    except Exception:  # pragma: no cover - defensive logging
        LOGGER.debug("Failed writing cache file %s", path, exc_info=True)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict, set, tuple)):
        return str(value)
    return str(value)


# ---------------------------------------------------------------------------
# Timeout helper (retained for backwards compatibility)
# ---------------------------------------------------------------------------

def with_timeout(timeout_seconds: float, func: Callable, *args, **kwargs):
    """Execute ``func`` with a timeout enforced via SIGALRM."""

    def timeout_handler(signum, frame):  # pragma: no cover - signal handler
        raise TimeoutError("Operation timed out")

    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(int(timeout_seconds))

    try:
        return func(*args, **kwargs)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


# ---------------------------------------------------------------------------
# VirusTotal helpers
# ---------------------------------------------------------------------------

def vt_query(
    file_hash: str,
    cache_dir: Path,
    vtapi: str,
    skip_enrich: bool = False,
    *,
    session_factory: SessionFactory = requests.session,
    timeout: int = DEFAULT_TIMEOUT,
) -> None:
    """Query VirusTotal for ``file_hash`` and persist the JSON response."""
    if skip_enrich or not vtapi:
        return

    session = session_factory()
    session.headers.update({"X-Apikey": vtapi})
    try:
        response = session.get(f"https://www.virustotal.com/api/v3/files/{file_hash}", timeout=timeout)
        response.raise_for_status()
        _write_text(cache_dir / file_hash, response.text)
    except Exception:  # pragma: no cover - exercised in integration
        LOGGER.error("VT query failed for %s", file_hash, exc_info=True)
    finally:
        try:
            session.close()
        except Exception:  # pragma: no cover - defensive
            pass


# ---------------------------------------------------------------------------
# DShield helpers
# ---------------------------------------------------------------------------

def dshield_query(
    ip_address: str,
    email: str,
    skip_enrich: bool = False,
    *,
    cache_base: Optional[Path] = None,
    session_factory: SessionFactory = requests.session,
    ttl_seconds: int = 86400,
    now: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Return DShield metadata for ``ip_address`` with simple caching."""
    if skip_enrich:
        return {"ip": {"asname": "", "ascountry": ""}}

    base = _resolve_cache_base(cache_base)
    cache_path = _cache_path(base, f"dshield_{ip_address}.json")

    payload = _read_text(cache_path)
    if payload:
        try:
            cached = json.loads(payload)
            timestamp = cached.get("timestamp", 0)
            if now() - timestamp < ttl_seconds:
                return cached.get("data", {"ip": {"asname": "", "ascountry": ""}})
        except json.JSONDecodeError:
            LOGGER.debug("Ignoring malformed DShield cache for %s", ip_address)

    session = session_factory()
    try:
        response = session.get(f"https://dshield.org/api/ip/{ip_address}?email={email}", timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        _write_text(cache_path, json.dumps({"timestamp": now(), "data": data}))
        return data
    except Exception:
        LOGGER.error("DShield query failed for %s", ip_address, exc_info=True)
        return {"ip": {"asname": "", "ascountry": ""}}
    finally:
        try:
            session.close()
        except Exception:  # pragma: no cover - defensive
            pass


# ---------------------------------------------------------------------------
# URLHaus helpers
# ---------------------------------------------------------------------------

def safe_read_uh_data(
    ip_address: str,
    urlhausapi: str,
    skip_enrich: bool = False,
    *,
    cache_base: Optional[Path] = None,
    session_factory: SessionFactory = requests.session,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Wrap ``read_uh_data`` with a timeout guard."""
    if skip_enrich or not urlhausapi:
        return ""

    try:
        return with_timeout(
            timeout,
            read_uh_data,
            ip_address,
            urlhausapi,
            cache_base=cache_base,
            session_factory=session_factory,
            timeout=timeout,
        )
    except TimeoutError:
        LOGGER.warning("URLHaus query timed out for %s", ip_address)
        return "TIMEOUT"


def read_uh_data(
    ip_address: str,
    uh_api: str,
    *,
    cache_base: Optional[Path] = None,
    session_factory: SessionFactory = requests.session,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Return a comma-separated list of unique URLHaus tags for ``ip_address``."""
    base = _resolve_cache_base(cache_base)
    cache_path = _cache_path(base, f"uh_{ip_address}")

    payload = _read_text(cache_path)
    if payload is None:
        payload = _fetch_urlhaus_payload(ip_address, uh_api, session_factory, timeout)
        if payload is None:
            return ""
        _write_text(cache_path, payload)

    return _parse_urlhaus_tags(payload)


def _fetch_urlhaus_payload(
    ip_address: str,
    uh_api: str,
    session_factory: SessionFactory,
    timeout: int,
) -> Optional[str]:
    session = session_factory()
    session.headers.update({"Auth-Key": uh_api})
    try:
        response = session.post(
            "https://urlhaus-api.abuse.ch/v1/host/",
            headers={"Auth-Key": uh_api},
            data={"host": ip_address},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.text
    except Exception:
        LOGGER.error("URLHaus query failed for %s", ip_address, exc_info=True)
        return None
    finally:
        try:
            session.close()
        except Exception:  # pragma: no cover - defensive
            pass


def _parse_urlhaus_tags(payload: str) -> str:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        LOGGER.debug("Malformed URLHaus payload: %s", payload[:128])
        return ""

    urls: Iterable[dict[str, Any]] = data.get("urls", []) or []
    tags: set[str] = set()
    for entry in urls:
        entry_tags = entry.get("tags") or []
        for tag in entry_tags:
            if tag:
                tags.add(str(tag))

    if not tags:
        return ""
    return ", ".join(sorted(tags))


# ---------------------------------------------------------------------------
# SPUR helpers
# ---------------------------------------------------------------------------

def read_spur_data(
    ip_address: str,
    spurapi: str,
    skip_enrich: bool = False,
    *,
    cache_base: Optional[Path] = None,
    session_factory: SessionFactory = requests.session,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[str]:
    """Return SPUR attributes for ``ip_address`` in a deterministic order."""
    if skip_enrich or not spurapi:
        return list(_SPUR_EMPTY_PAYLOAD)

    base = _resolve_cache_base(cache_base)
    cache_path = _cache_path(base, f"spur_{ip_address.replace(':', '_')}.json")

    payload = _read_text(cache_path)
    if payload is None:
        payload = _fetch_spur_payload(ip_address, spurapi, session_factory, timeout)
        if payload is None:
            return list(_SPUR_EMPTY_PAYLOAD)
        _write_text(cache_path, payload)

    return _parse_spur_payload(payload)


def _fetch_spur_payload(
    ip_address: str,
    spurapi: str,
    session_factory: SessionFactory,
    timeout: int,
) -> Optional[str]:
    session = session_factory()
    session.headers.update({"Token": spurapi})
    try:
        response = session.get(f"https://spur.us/api/v1/context/{ip_address}", timeout=timeout)
        response.raise_for_status()
        return response.text
    except Exception:
        LOGGER.error("SPUR query failed for %s", ip_address, exc_info=True)
        return None
    finally:
        try:
            session.close()
        except Exception:  # pragma: no cover - defensive
            pass


def _parse_spur_payload(payload: str) -> list[str]:
    try:
        data = json.loads(payload) if payload else {}
    except json.JSONDecodeError:
        LOGGER.debug("Malformed SPUR payload: %s", payload[:128])
        return list(_SPUR_EMPTY_PAYLOAD)

    result = list(_SPUR_EMPTY_PAYLOAD)

    # ASN fields
    asn_value = data.get("asn")
    asn_number = ""
    asn_org = ""
    if isinstance(asn_value, dict):
        asn_number = _stringify(asn_value.get("number"))
        asn_org = _stringify(asn_value.get("organization"))
    else:
        asn_number = _stringify(asn_value)
        asn_org = _stringify(data.get("asn_organization"))

    result[0] = asn_number
    result[1] = asn_org

    # Organization & infrastructure
    result[2] = _stringify(data.get("organization"))
    result[3] = _stringify(data.get("infrastructure"))

    # Client details (support both legacy nested and flattened schemas)
    client = data.get("client", {}) if isinstance(data.get("client"), dict) else {}
    result[4] = _stringify(client.get("behaviors", data.get("client_behaviors")))
    result[5] = _stringify(client.get("proxies", data.get("client_proxies")))
    result[6] = _stringify(client.get("types", data.get("client_types")))
    result[7] = _stringify(client.get("count", data.get("client_count")))
    result[8] = _stringify(client.get("concentration", data.get("client_concentration")))
    result[9] = _stringify(client.get("countries", data.get("client_countries")))
    result[10] = _stringify(client.get("spread", data.get("client_geo_spread")))

    result[11] = _stringify(data.get("risks"))
    result[12] = _stringify(data.get("services"))

    location = data.get("location", {})
    if isinstance(location, dict):
        parts = [
            location.get("city"),
            location.get("state"),
            location.get("country"),
        ]
        result[13] = ", ".join(filter(None, (_stringify(part) for part in parts))).strip(", ")
    else:
        result[13] = _stringify(location)

    tunnels = data.get("tunnels")
    tunnel_info = ("", "", "", "")
    if isinstance(tunnels, Iterable):
        for entry in tunnels:
            if isinstance(entry, dict):
                tunnel_info = (
                    _stringify(entry.get("anonymous")),
                    _stringify(entry.get("entries")),
                    _stringify(entry.get("operator")),
                    _stringify(entry.get("type")),
                )
                break
    result[14:18] = tunnel_info

    return result
