<<<<<<< HEAD
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
=======
"""External enrichment handlers for Cowrie log analysis.

This module contains functions for enriching Cowrie log data with external
API data from VirusTotal, DShield, URLHaus, and SPUR.
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
import requests


def with_timeout(timeout_seconds: float, func, *args, **kwargs):
    """Execute a function with a timeout.
    
    Args:
        timeout_seconds: Maximum time to wait for the function
        func: Function to execute
        *args: Arguments to pass to the function
        **kwargs: Keyword arguments to pass to the function
        
    Returns:
        Result of the function call
        
    Raises:
        TimeoutError: If the function doesn't complete within the timeout
    """
    import signal
    
    def timeout_handler(signum, frame):
        raise TimeoutError("Operation timed out")
    
    # Set the signal handler
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(int(timeout_seconds))
    
    try:
        result = func(*args, **kwargs)
        return result
    finally:
        # Restore the old handler
>>>>>>> 4b5ecbc (Add debug modules and identify JSON parsing issue)
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


<<<<<<< HEAD
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
=======
def vt_query(hash: str, cache_dir: Path, vtapi: str, skip_enrich: bool = False) -> None:
    """Query VirusTotal for a file hash and write the JSON response.
    
    Args:
        hash: SHA-256 string of the file to look up
        cache_dir: Directory to write/read cached VT responses
        vtapi: VirusTotal API key
        skip_enrich: If True, skip the API call
    """
    if skip_enrich or not vtapi:
        return
        
    vt_session = requests.session()
    vt_session.headers.update({'X-Apikey': vtapi})
    url = "https://www.virustotal.com/api/v3/files/" + hash
    
    try:
        response = vt_session.get(url, timeout=30)
        response.raise_for_status()
        
        vt_path = cache_dir / hash
        with open(vt_path, 'w', encoding='utf-8') as f:
            f.write(response.text)
    except Exception as e:
        logging.error(f"VT query failed for {hash}: {e}")
    finally:
        vt_session.close()


def dshield_query(ip_address: str, email: str, skip_enrich: bool = False) -> Dict[str, Any]:
    """Query DShield for information about an IP address.
    
    Args:
        ip_address: IP address string
        email: Email address for DShield API
        skip_enrich: If True, return empty data
        
    Returns:
        Parsed JSON response as a dictionary
    """
    if skip_enrich:
        return {"ip": {"asname": "", "ascountry": ""}}
        
    # Check cache
    cache_dir = Path('/mnt/dshield/data/cache')
    cache_file = cache_dir / f"dshield_{ip_address}.json"
    
    if cache_file.exists():
        try:
            with open(cache_file, 'r') as f:
                cached_data = json.load(f)
                if time.time() - cached_data.get('timestamp', 0) < 86400:  # 24 hours
                    return cached_data.get('data', {"ip": {"asname": "", "ascountry": ""}})
        except Exception:
            pass
    
    dshield_session = requests.session()
    url = f"https://dshield.org/api/ip/{ip_address}?email={email}"
    
    try:
        response = dshield_session.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        # Cache the result
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_file, 'w') as f:
                json.dump({'timestamp': time.time(), 'data': data}, f)
        except Exception:
            pass
            
        return data
    except Exception as e:
        logging.error(f"DShield query failed for {ip_address}: {e}")
        return {"ip": {"asname": "", "ascountry": ""}}
    finally:
        dshield_session.close()


def safe_read_uh_data(ip_address: str, urlhausapi: str, skip_enrich: bool = False) -> str:
    """Safely read URLHaus data with timeout handling.
    
    Args:
        ip_address: IP address to query
        urlhausapi: URLHaus API key
        skip_enrich: If True, return empty string
        
    Returns:
        Comma-separated string of unique URLHaus tags, or empty string
    """
    if skip_enrich:
        return ""
        
    try:
        return with_timeout(30, read_uh_data, ip_address, urlhausapi)
    except TimeoutError:
        logging.warning(f"URLHaus query timed out for IP {ip_address}")
        return "TIMEOUT"


def read_uh_data(ip_address: str, uh_api: str) -> str:
    """Read URLHaus data for an IP address.
    
    Args:
        ip_address: IP address string
        uh_api: URLHaus API key
        
    Returns:
        Comma-separated string of unique URLHaus tags, or empty string
    """
    cache_dir = Path('/mnt/dshield/data/cache')
    uh_path = cache_dir / ("uh_" + ip_address)
    
    if not uh_path.exists():
        uh_session = requests.session()
        uh_header = {'Auth-Key': uh_api}
        host = {'host': ip_address}
        
        try:
            response = uh_session.post('https://urlhaus-api.abuse.ch/v1/host/', 
                                     headers=uh_header, data=host, timeout=30)
            response.raise_for_status()
            
            with open(uh_path, 'w', encoding='utf-8') as f:
                f.write(response.text)
        except Exception as e:
            logging.error(f"URLHaus query failed for {ip_address}: {e}")
            return ""
        finally:
            uh_session.close()
    
    try:
        with open(uh_path, 'r', encoding='utf-8') as f:
            uh_data = f.readlines()
    except FileNotFoundError:
        return ""
    
    tags = ""
    file = ""
    for eachline in uh_data:
        file += eachline
    uh_data.close()
    
    try:
        json_data = json.loads(file)
        tags = set()
        for eachurl in json_data['urls']:
            if eachurl['tags']:
                for eachtag in eachurl['tags']:
                    tags.add(eachtag)
        stringtags = ""
        for eachtag in tags:
            stringtags += eachtag + ", "
        return stringtags[:-2]
    except Exception:
        return ""


def read_spur_data(ip_address: str, spurapi: str, skip_enrich: bool = False) -> List[str]:
    """Read cached SPUR.us data and return normalized fields.
    
    Args:
        ip_address: IP address string
        spurapi: SPUR API key
        skip_enrich: If True, return empty data
        
    Returns:
        List of SPUR attributes in the following order:
        [asn, asn_org, organization, infrastructure, client_behaviors,
         client_proxies, client_types, client_count, client_concentration,
         client_countries, client_geo_spread, risks, services, location,
         tunnel_anonymous, tunnel_entries, tunnel_operator, tunnel_type]
    """
    if skip_enrich:
        return ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]
        
    cache_dir = Path('/mnt/dshield/data/cache')
    spur_path = cache_dir / ("spur_" + ip_address.replace(":", "_") + ".json")
    
    if not spur_path.exists():
        spur_session = requests.session()
        spur_session.headers = {'Token': spurapi}
        
        try:
            response = spur_session.get(f"https://spur.us/api/v1/context/{ip_address}", timeout=30)
            response.raise_for_status()
            
            with open(spur_path, 'w', encoding='utf-8') as f:
                f.write(response.text)
        except Exception as e:
            logging.error(f"SPUR query failed for {ip_address}: {e}")
            return ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]
        finally:
            spur_session.close()
    
    try:
        with open(spur_path, 'r', encoding='utf-8') as f:
            spur_data = f.readlines()
    except FileNotFoundError:
        return ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]
    
    file = ""
    for eachline in spur_data:
        file += eachline
    spur_data.close()
    
    try:
        json_data = json.loads(file)
    except Exception:
        return ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]
    
    # Extract SPUR data fields
    spur_list = []
    
    # ASN data
    asn = json_data.get('asn', '')
    spur_list.append(str(asn))
    
    asn_org = json_data.get('asn_organization', '')
    spur_list.append(str(asn_org))
    
    organization = json_data.get('organization', '')
    spur_list.append(str(organization))
    
    infrastructure = json_data.get('infrastructure', '')
    spur_list.append(str(infrastructure))
    
    # Client data
    client_behaviors = json_data.get('client_behaviors', '')
    spur_list.append(str(client_behaviors))
    
    client_proxies = json_data.get('client_proxies', '')
    spur_list.append(str(client_proxies))
    
    client_types = json_data.get('client_types', '')
    spur_list.append(str(client_types))
    
    client_count = json_data.get('client_count', '')
    spur_list.append(str(client_count))
    
    client_concentration = json_data.get('client_concentration', '')
    spur_list.append(str(client_concentration))
    
    client_countries = json_data.get('client_countries', '')
    spur_list.append(str(client_countries))
    
    client_geo_spread = json_data.get('client_geo_spread', '')
    spur_list.append(str(client_geo_spread))
    
    # Risk and service data
    risks = json_data.get('risks', '')
    spur_list.append(str(risks))
    
    services = json_data.get('services', '')
    spur_list.append(str(services))
    
    location = json_data.get('location', '')
    spur_list.append(str(location))
    
    # Tunnel data
    tunnel_anonymous = ""
    tunnel_entries = ""
    tunnel_operator = ""
    tunnel_type = ""
    
    if "tunnels" in json_data:
        for each_tunnel in json_data['tunnels']:
            if "anonymous" in each_tunnel:
                tunnel_anonymous = each_tunnel['anonymous']
            if "entries" in each_tunnel:
                tunnel_entries = each_tunnel['entries']
            if "operator" in each_tunnel:
                tunnel_operator = each_tunnel['operator']
            if "type" in each_tunnel:
                tunnel_type = each_tunnel['type']
    
    spur_list.append(tunnel_anonymous)
    spur_list.append(tunnel_entries)
    spur_list.append(tunnel_operator)
    spur_list.append(tunnel_type)
    
    return spur_list
>>>>>>> 4b5ecbc (Add debug modules and identify JSON parsing issue)
