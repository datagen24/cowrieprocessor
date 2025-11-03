"""External enrichment helpers and orchestration utilities for Cowrie logs."""

from __future__ import annotations

import json
import logging
import signal
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, Mapping, Optional

import requests
from sqlalchemy.engine import Engine

from cowrieprocessor.enrichment import EnrichmentCacheManager
from cowrieprocessor.enrichment.hybrid_cache import HybridEnrichmentCache, create_redis_client
from cowrieprocessor.enrichment.rate_limiting import (
    RateLimitedSession,
    create_rate_limited_session_factory,
    get_service_rate_limit,
    with_retries,
)
from cowrieprocessor.enrichment.telemetry import EnrichmentTelemetry
from cowrieprocessor.enrichment.virustotal_handler import VirusTotalHandler
from cowrieprocessor.utils.config import load_redis_config

LOGGER = logging.getLogger(__name__)
DEFAULT_CACHE_BASE = Path("/mnt/dshield/data/cache")
DEFAULT_TIMEOUT = 30
_SPUR_EMPTY_PAYLOAD = ["" for _ in range(18)]

SessionFactory = Callable[[], requests.Session]


# ---------------------------------------------------------------------------
# Shared cache helpers
# ---------------------------------------------------------------------------


def _resolve_cache_base(cache_base: Optional[Path]) -> Path:
    """Return the cache directory, defaulting to ``DEFAULT_CACHE_BASE``."""
    return cache_base if cache_base is not None else DEFAULT_CACHE_BASE


def _cache_path(base: Path, name: str) -> Path:
    """Return the full cache path for ``name`` within ``base``."""
    return base / name


def _read_text(path: Path) -> Optional[str]:
    """Read UTF-8 text from ``path`` returning ``None`` on failure."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except Exception:  # pragma: no cover - defensive logging
        LOGGER.debug("Failed reading cache file %s", path, exc_info=True)
        return None


def _write_text(path: Path, payload: str) -> None:
    """Persist UTF-8 text to ``path`` creating parents when required."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    except Exception:  # pragma: no cover - defensive logging
        LOGGER.debug("Failed writing cache file %s", path, exc_info=True)


def _stringify(value: Any) -> str:
    """Coerce arbitrary values into a printable string."""
    if value is None:
        return ""
    if isinstance(value, (list, dict, set, tuple)):
        return str(value)
    return str(value)


def _empty_dshield() -> dict[str, dict[str, str]]:
    """Return the canonical empty DShield payload."""
    return {"ip": {"asname": "", "ascountry": ""}}


# ---------------------------------------------------------------------------
# Timeout helper (retained for backwards compatibility)
# ---------------------------------------------------------------------------


def with_timeout(timeout_seconds: float, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Execute ``func`` enforcing a wall-clock timeout via ``SIGALRM``."""

    def timeout_handler(signum: int, frame: Any) -> None:  # pragma: no cover - signal handler
        raise TimeoutError("Operation timed out")

    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(int(timeout_seconds))

    try:
        return func(*args, **kwargs)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


# ---------------------------------------------------------------------------
# VirusTotal helpers (Legacy - use VirusTotalHandler for new code)
# ---------------------------------------------------------------------------


@with_retries(max_retries=3, backoff_base=1.0, backoff_factor=2.0)
def vt_query(
    file_hash: str,
    cache_dir: Path,
    vtapi: str,
    skip_enrich: bool = False,
    *,
    session_factory: SessionFactory | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Any:
    """Query VirusTotal for ``file_hash`` and persist the JSON response."""
    if skip_enrich or not vtapi:
        return None

    # Use rate-limited session factory if none provided
    if session_factory is None:
        rate_limit, burst = get_service_rate_limit("virustotal")
        session_factory = create_rate_limited_session_factory(rate_limit, burst)  # type: ignore[assignment]

    # Custom retry logic for 401 errors with longer backoff
    max_retries = 3
    for attempt in range(max_retries + 1):
        try:
            if session_factory is None:
                raise ValueError("Session factory is required")
            return _vt_query_single_attempt(file_hash, cache_dir, vtapi, session_factory, timeout)
        except requests.HTTPError as e:
            if hasattr(e, 'response') and e.response.status_code == 401:
                if attempt < max_retries:
                    # Longer backoff for 401 errors (rate limiting)
                    backoff_time = 60.0 * (2**attempt)  # 60s, 120s, 240s
                    LOGGER.warning(
                        "VT 401 error for %s, retrying in %.1f seconds (attempt %d/%d)",
                        file_hash,
                        backoff_time,
                        attempt + 1,
                        max_retries + 1,
                    )
                    time.sleep(backoff_time)
                    continue
                else:
                    LOGGER.error("VT 401 error for %s after %d attempts, giving up", file_hash, max_retries + 1)
                    return None
            else:
                # Re-raise other HTTP errors to let the decorator handle them
                raise
        except Exception:
            # Re-raise other exceptions to let the decorator handle them
            raise

    return None


def _vt_query_single_attempt(
    file_hash: str,
    cache_dir: Path,
    vtapi: str,
    session_factory: SessionFactory,
    timeout: int,
) -> Any:
    """Single attempt at VirusTotal query without retry logic."""
    try:
        session = session_factory()
    except Exception:  # pragma: no cover - defensive logging
        LOGGER.error("VT session factory failed for %s", file_hash, exc_info=True)
        return None

    headers = getattr(session, "headers", None)
    if isinstance(headers, Mapping):
        headers.update({"X-Apikey": vtapi})  # type: ignore
    else:  # pragma: no cover - simple attribute assignment
        session.headers = {"X-Apikey": vtapi}

    try:
        response = session.get(
            f"https://www.virustotal.com/api/v3/files/{file_hash}",
            timeout=timeout,
        )

        # Handle specific HTTP status codes
        status_code = getattr(response, "status_code", 0)
        if status_code == 429:
            LOGGER.warning("VT query rate limited for %s", file_hash)
            return None
        elif status_code == 401:
            LOGGER.warning("VT query unauthorized for %s (API key issue or rate limit)", file_hash)
            # Raise the exception to trigger retry logic
            response.raise_for_status()
        elif status_code == 404:
            LOGGER.debug("VT query file not found for %s", file_hash)
            return None
        elif status_code >= 400:
            LOGGER.warning("VT query HTTP error %d for %s", status_code, file_hash)
            response.raise_for_status()

        # Success case
        _write_text(cache_dir / file_hash, getattr(response, "text", ""))
        json_loader = getattr(response, "json", None)
        if callable(json_loader):
            try:
                payload = json_loader()
                return payload if isinstance(payload, dict) else None
            except Exception:  # pragma: no cover - defensive logging
                LOGGER.debug("Unable to parse VT JSON for %s", file_hash, exc_info=True)
                return None
        return None

    except requests.HTTPError as e:
        # Re-raise HTTP errors to let the retry logic handle them
        LOGGER.warning("VT HTTP error for %s: %s", file_hash, e)
        raise
    except (requests.RequestException, ConnectionError, TimeoutError) as e:
        # Re-raise network errors to let the retry logic handle them
        LOGGER.warning("VT network error for %s: %s", file_hash, e)
        raise
    except Exception as e:  # pragma: no cover - defensive logging
        # Only catch truly unexpected errors
        LOGGER.error("VT unexpected error for %s: %s", file_hash, e, exc_info=True)
        return None
    finally:
        try:
            session.close()
        except Exception:  # pragma: no cover - defensive
            pass


# ---------------------------------------------------------------------------
# DShield helpers
# ---------------------------------------------------------------------------


@with_retries(max_retries=3, backoff_base=1.0, backoff_factor=2.0, respect_retry_after=True)
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
    """Return DShield metadata for ``ip_address`` with simple caching.

    Note: respect_retry_after=True is critical for DShield API compliance.
    The DShield API returns Retry-After headers during rate limiting events,
    and we must honor these to avoid API bans and ensure reliable enrichment.
    """
    if skip_enrich:
        return _empty_dshield()

    base = _resolve_cache_base(cache_base)
    cache_path = _cache_path(base, f"dshield_{ip_address}.json")

    payload = _read_text(cache_path)
    if payload:
        try:
            cached = json.loads(payload)
            timestamp = cached.get("timestamp", 0)
            if now() - timestamp < ttl_seconds:
                data = cached.get("data", _empty_dshield())
                return data if isinstance(data, dict) else _empty_dshield()
        except json.JSONDecodeError:
            LOGGER.debug("Ignoring malformed DShield cache for %s", ip_address)

    try:
        session = session_factory()
    except Exception:
        LOGGER.error("DShield session factory failed for %s", ip_address, exc_info=True)
        return _empty_dshield()

    try:
        url = f"https://isc.sans.edu/api/ip/{ip_address}?email={email}&json"
        response = session.get(url, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        json_loader = getattr(response, "json", None)
        if callable(json_loader):
            data = json_loader()
        else:
            try:
                data = json.loads(getattr(response, "text", ""))
            except json.JSONDecodeError:
                data = _empty_dshield()
        _write_text(cache_path, json.dumps({"timestamp": now(), "data": data}))
        return data if isinstance(data, dict) else _empty_dshield()
    except Exception:
        LOGGER.error("DShield query failed for %s", ip_address, exc_info=True)
        return _empty_dshield()
    finally:
        try:
            session.close()
        except Exception:  # pragma: no cover - defensive
            pass


# ---------------------------------------------------------------------------
# URLHaus helpers
# ---------------------------------------------------------------------------


@with_retries(max_retries=3, backoff_base=1.0, backoff_factor=2.0)
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
        result = with_timeout(
            timeout,
            read_uh_data,
            ip_address,
            urlhausapi,
            cache_base=cache_base,
            session_factory=session_factory,
            timeout=timeout,
        )
        return str(result)
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
    try:
        session = session_factory()
    except Exception:
        LOGGER.error("URLHaus session factory failed for %s", ip_address, exc_info=True)
        return None

    if not hasattr(session, "headers"):
        session.headers = {}
    session.headers.update({"Auth-Key": uh_api})
    try:
        response = session.post(
            "https://urlhaus-api.abuse.ch/v1/host/",
            headers={"Auth-Key": uh_api},
            data={"host": ip_address},
            timeout=timeout,
        )
        response.raise_for_status()
        return getattr(response, "text", "")
    except Exception:
        LOGGER.error("URLHaus query failed for %s", ip_address, exc_info=True)
        return None
    finally:
        try:
            session.close()
        except Exception:  # pragma: no cover - defensive
            pass


def _parse_urlhaus_tags(payload: str) -> str:
    """Parse unique URLHaus tags from ``payload`` JSON."""
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


@with_retries(max_retries=3, backoff_base=1.0, backoff_factor=2.0)
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
            payload = _load_spur_fallback(base, ip_address)
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
    try:
        session = session_factory()
    except Exception:
        LOGGER.error("SPUR session factory failed for %s", ip_address, exc_info=True)
        return None

    if not hasattr(session, "headers"):
        session.headers = {}
    session.headers.update({"Token": spurapi})
    try:
        response = session.get(f"https://spur.us/api/v1/context/{ip_address}", timeout=timeout)
        response.raise_for_status()
        return getattr(response, "text", "")
    except Exception:
        LOGGER.error("SPUR query failed for %s", ip_address, exc_info=True)
        return None
    finally:
        try:
            session.close()
        except Exception:  # pragma: no cover - defensive
            pass


def _parse_spur_payload(payload: str) -> list[str]:
    """Parse SPUR JSON payload into the legacy list representation."""
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


def _load_spur_fallback(base: Path, ip_address: str) -> Optional[str]:
    """Return cached SPUR payload that matches the IP prefix when exact file is missing."""
    sanitized = ip_address.replace(":", "_")
    prefix = sanitized
    if "." in sanitized:
        prefix = sanitized.rsplit(".", 1)[0]

    for candidate in base.glob(f"spur_{prefix}*.json"):
        payload = _read_text(candidate)
        if payload:
            return payload
    return None


# ---------------------------------------------------------------------------
# Enrichment service façade
# ---------------------------------------------------------------------------


class EnrichmentService:
    """Coordinate external enrichment lookups with shared caching."""

    def __init__(
        self,
        cache_dir: Path | str,
        *,
        vt_api: str | None,
        dshield_email: str | None,
        urlhaus_api: str | None,
        spur_api: str | None,
        cache_manager: EnrichmentCacheManager | None = None,
        engine: Engine | None = None,
        session_factory: SessionFactory = requests.session,
        timeout: int = DEFAULT_TIMEOUT,
        skip_enrich: bool = False,
        enable_rate_limiting: bool = True,
        enable_telemetry: bool = True,
        telemetry_phase: str = "enrichment",
        enable_vt_quota_management: bool = True,
        enable_redis_cache: bool = True,
    ) -> None:
        """Initialise the enrichment service."""
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.vt_api = vt_api or ""
        self.dshield_email = dshield_email or ""
        self.urlhaus_api = urlhaus_api or ""
        self.spur_api = spur_api or ""
        self.skip_enrich = skip_enrich
        self.enable_rate_limiting = enable_rate_limiting
        self.enable_telemetry = enable_telemetry

        # Initialize filesystem cache (L3 in hybrid mode, L2 otherwise)
        filesystem_cache = cache_manager or EnrichmentCacheManager(self.cache_dir)

        # Load cache configuration from sensors.toml or environment variables
        cache_config = load_redis_config()

        # Create database cache if enabled and engine available (schema v15+)
        database_cache = None
        if cache_config.get("db_cache_enabled") and engine is not None:
            from cowrieprocessor.enrichment.db_cache import DatabaseCache

            database_cache = DatabaseCache(engine)
            LOGGER.info("Database L2 cache enabled")

        # Initialize hybrid cache (Redis L1 + Database L2 + Filesystem L3)
        if enable_redis_cache:
            redis_client = create_redis_client()
            self.cache_manager = HybridEnrichmentCache(
                filesystem_cache=filesystem_cache,
                redis_client=redis_client,
                database_cache=database_cache,
            )
        else:
            # Use filesystem-only mode if Redis disabled
            self.cache_manager = filesystem_cache  # type: ignore[assignment]

        # Initialize VirusTotal handler with quota management
        self.vt_handler = VirusTotalHandler(
            api_key=self.vt_api,
            cache_dir=self.cache_dir,
            timeout=timeout,
            skip_enrich=skip_enrich,
            enable_quota_management=enable_vt_quota_management,
        )

        # Initialize telemetry if enabled
        if enable_telemetry:
            self.telemetry = EnrichmentTelemetry(telemetry_phase)
        else:
            self.telemetry = None  # type: ignore[assignment]

        # Use rate-limited sessions if enabled
        if enable_rate_limiting:
            self._session_factory = self._create_rate_limited_session_factory
        else:
            self._session_factory = session_factory  # type: ignore[assignment]
        self._timeout = timeout

        # Track active sessions for cleanup
        self._active_sessions: list[RateLimitedSession | requests.Session] = []

    def _create_rate_limited_session_factory(self, service: str = "default") -> RateLimitedSession:
        """Create a rate-limited session for the specified service."""
        rate, burst = get_service_rate_limit(service)
        session = RateLimitedSession(rate, burst)
        self._active_sessions.append(session)
        return session

    def _sanitize_enrichment(self, data: dict[str, Any]) -> dict[str, Any]:
        """Sanitize enrichment API response data to remove Unicode control characters.

        This method recursively sanitizes all string values in enrichment data to remove
        Unicode control characters (especially null bytes) that cause PostgreSQL JSON errors.

        Args:
            data: Enrichment data dictionary from API response

        Returns:
            Sanitized enrichment data dictionary

        Note:
            This is a critical security and data quality layer - all external API responses
            must be sanitized before storage to prevent PostgreSQL Unicode errors when
            querying session_summaries.enrichment fields.
        """
        from cowrieprocessor.utils.unicode_sanitizer import UnicodeSanitizer

        return UnicodeSanitizer._sanitize_json_object(data)  # type: ignore[no-any-return]

    def cache_snapshot(self) -> Dict[str, int]:
        """Return current cache statistics for telemetry."""
        if isinstance(self.cache_manager, HybridEnrichmentCache):
            # Return hybrid cache stats in legacy format for backward compatibility
            hybrid_stats = self.cache_manager.get_stats()
            return {
                "hits": hybrid_stats["total_cache_hits"],
                "misses": hybrid_stats["total_cache_misses"],
                "stores": hybrid_stats["l1_redis"]["stores"] + hybrid_stats["l2_filesystem"]["stores"],
            }
        else:
            # Filesystem-only mode
            return self.cache_manager.snapshot()  # type: ignore[unreachable]

    def _enrich_with_hybrid_cache(
        self, service: str, cache_key: str, api_call: Callable[[], dict[str, Any]], empty_value: Any
    ) -> Any:
        """Enrich data using hybrid cache (Redis L1 → Database L2 → Filesystem L3 → API).

        Args:
            service: Service name (e.g., 'dshield', 'urlhaus', 'spur')
            cache_key: Cache key (e.g., IP address)
            api_call: Callable that makes the API request
            empty_value: Default value to return on error

        Returns:
            Enrichment data from cache or API (sanitized)
        """
        # Try hybrid cache first (L1 Redis → L2 Database → L3 Filesystem)
        cached = self.cache_manager.get_cached(service, cache_key)
        if cached is not None:
            LOGGER.debug("Cache hit for %s/%s (hybrid cache)", service, cache_key)
            # Sanitize cached data (may contain Unicode control chars from old cache entries)
            return self._sanitize_enrichment(cached)

        # Cache miss - make API call
        try:
            result = api_call()
            # Sanitize API response before caching (prevents storing bad data)
            sanitized_result = self._sanitize_enrichment(result)
            # Store sanitized data in all cache tiers (L1/L2/L3)
            self.cache_manager.store_cached(service, cache_key, sanitized_result)
            LOGGER.debug("API call, sanitization, and cache store for %s/%s", service, cache_key)
            return sanitized_result
        except Exception as e:
            LOGGER.warning("%s enrichment API call failed for %s: %s", service.upper(), cache_key, e)
            return empty_value

    def enrich_session(self, session_id: str, src_ip: str) -> dict[str, Any]:
        """Return enrichment payload for a session/IP pair."""
        start_time = time.time()

        enrichment: dict[str, Any] = {}
        if self.skip_enrich:
            enrichment["dshield"] = _empty_dshield()
            enrichment["urlhaus"] = ""
            enrichment["spur"] = list(_SPUR_EMPTY_PAYLOAD)
        else:
            # DShield enrichment using hybrid cache
            if self.dshield_email:

                def dshield_api_call() -> dict[str, Any]:
                    """Make DShield API request."""
                    session = self._session_factory("dshield")
                    try:
                        url = f"https://isc.sans.edu/api/ip/{src_ip}?email={self.dshield_email}&json"
                        response = session.get(url, timeout=self._timeout)
                        response.raise_for_status()
                        data = (
                            response.json()
                            if hasattr(response, 'json') and callable(response.json)
                            else json.loads(response.text)
                        )
                        return data if isinstance(data, dict) else _empty_dshield()
                    finally:
                        session.close()

                enrichment["dshield"] = self._enrich_with_hybrid_cache(
                    "dshield", src_ip, dshield_api_call, _empty_dshield()
                )
                if self.telemetry:
                    self.telemetry.record_api_call("dshield", enrichment["dshield"] != _empty_dshield())
            else:
                enrichment["dshield"] = _empty_dshield()

            # URLHaus enrichment using hybrid cache
            if self.urlhaus_api:

                def urlhaus_api_call() -> dict[str, Any]:
                    """Make URLHaus API request and wrap result in dict."""
                    session = self._session_factory("urlhaus")
                    try:
                        response = session.post(
                            "https://urlhaus-api.abuse.ch/v1/host/",
                            headers={"Auth-Key": self.urlhaus_api},
                            data={"host": src_ip},
                            timeout=self._timeout,
                        )
                        response.raise_for_status()
                        data = (
                            response.json()
                            if hasattr(response, 'json') and callable(response.json)
                            else json.loads(response.text)
                        )
                        # Extract tags from response
                        tags = set()
                        if isinstance(data, dict) and data.get("query_status") == "ok":
                            for url in data.get("urls", []):
                                tags.update(url.get("tags") or [])
                        tags_str = ",".join(sorted(tags)) if tags else ""
                        return {"tags": tags_str}  # Wrap in dict for cache
                    finally:
                        session.close()

                result = self._enrich_with_hybrid_cache("urlhaus", src_ip, urlhaus_api_call, {"tags": ""})
                enrichment["urlhaus"] = result.get("tags", "")  # Extract string from dict
                if self.telemetry:
                    self.telemetry.record_api_call("urlhaus", bool(enrichment["urlhaus"]))
            else:
                enrichment["urlhaus"] = ""

            # SPUR enrichment using hybrid cache
            if self.spur_api:

                def spur_api_call() -> dict[str, Any]:
                    """Make SPUR API request and wrap result in dict."""
                    session = self._session_factory("spur")
                    if not hasattr(session, "headers"):
                        session.headers = {}
                    session.headers.update({"Token": self.spur_api})
                    try:
                        response = session.get(f"https://spur.us/api/v1/context/{src_ip}", timeout=self._timeout)
                        response.raise_for_status()
                        data = (
                            response.json()
                            if hasattr(response, 'json') and callable(response.json)
                            else json.loads(response.text)
                        )
                        # Extract fields into list format (legacy format)
                        spur_list = [
                            data.get("as", {}).get("organization", ""),
                            data.get("client", {}).get("behaviors", []),
                            data.get("client", {}).get("concentration", {}).get("country", ""),
                            data.get("client", {}).get("concentration", {}).get("geohash", ""),
                            data.get("client", {}).get("concentration", {}).get("skew", ""),
                            data.get("client", {}).get("countries", ""),
                            data.get("client", {}).get("count", ""),
                            data.get("client", {}).get("proxies", []),
                            data.get("client", {}).get("spread", ""),
                            data.get("client", {}).get("types", []),
                            data.get("infrastructure", ""),
                            data.get("location", {}).get("city", ""),
                            data.get("location", {}).get("country", ""),
                            data.get("location", {}).get("state", ""),
                            data.get("organization", ""),
                            data.get("risks", []),
                            data.get("services", []),
                            data.get("tunnels", []),
                        ]
                        return {"spur_data": spur_list}  # Wrap in dict for cache
                    finally:
                        session.close()

                result = self._enrich_with_hybrid_cache(
                    "spur", src_ip, spur_api_call, {"spur_data": list(_SPUR_EMPTY_PAYLOAD)}
                )
                enrichment["spur"] = result.get("spur_data", list(_SPUR_EMPTY_PAYLOAD))  # Extract list from dict
                if self.telemetry:
                    self.telemetry.record_api_call("spur", enrichment["spur"] != list(_SPUR_EMPTY_PAYLOAD))
            else:
                enrichment["spur"] = list(_SPUR_EMPTY_PAYLOAD)

        # Record telemetry
        if self.telemetry:
            (time.time() - start_time) * 1000  # duration_ms
            self.telemetry.record_session_enrichment(True)
            self.telemetry.record_cache_stats(self.cache_manager.snapshot())

        return {
            "session_id": session_id,
            "src_ip": src_ip,
            "enrichment": enrichment,
        }

    def enrich_file(self, file_hash: str, filename: str) -> dict[str, Any]:
        """Return VirusTotal enrichment payload for a file hash."""
        start_time = time.time()

        enrichment: dict[str, Any] = {"virustotal": None}
        if self.skip_enrich or not self.vt_api:
            if self.telemetry:
                self.telemetry.record_file_enrichment(False)
            return {
                "file_hash": file_hash,
                "filename": filename,
                "enrichment": enrichment,
            }

        payload = self._load_vt_payload(file_hash)
        if payload is None:
            try:
                # Use new VirusTotal handler with quota management
                payload = self.vt_handler.enrich_file(file_hash)
                if self.telemetry:
                    self.telemetry.record_api_call("virustotal", True)
            except Exception as e:
                LOGGER.warning("VirusTotal enrichment failed for %s: %s", file_hash, e)
                if self.telemetry:
                    self.telemetry.record_api_call("virustotal", False)

        enrichment["virustotal"] = payload

        # Record telemetry
        if self.telemetry:
            (time.time() - start_time) * 1000  # duration_ms
            self.telemetry.record_file_enrichment(payload is not None)
            self.telemetry.record_cache_stats(self.cache_manager.snapshot())

        return {
            "file_hash": file_hash,
            "filename": filename,
            "enrichment": enrichment,
        }

    def get_session_flags(self, session_result: Mapping[str, Any]) -> dict[str, bool]:
        """Derive boolean enrichment flags from ``session_result``."""
        enrichment_obj = session_result.get("enrichment") if isinstance(session_result, Mapping) else {}
        enrichment = enrichment_obj if isinstance(enrichment_obj, Mapping) else {}

        dshield_flagged = False
        urlhaus_flagged = False
        spur_flagged = False
        for payload in self._iter_session_enrichments(enrichment):
            dshield_flagged = dshield_flagged or self._dshield_flag(payload.get("dshield"))
            urlhaus_flagged = urlhaus_flagged or self._urlhaus_flag(payload.get("urlhaus"))
            spur_flagged = spur_flagged or self._spur_flag(payload.get("spur"))

        vt_flagged = self._vt_flag(enrichment.get("virustotal"))

        return {
            "dshield_flagged": dshield_flagged,
            "urlhaus_flagged": urlhaus_flagged,
            "spur_flagged": spur_flagged,
            "vt_flagged": vt_flagged,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_vt_payload(self, file_hash: str) -> Optional[dict[str, Any]]:
        """Load a cached VirusTotal payload from disk."""
        try:
            cache_path = self.cache_dir / file_hash
            payload = _read_text(cache_path)
        except (TypeError, AttributeError):
            # Handle Mock objects or other non-Path types
            return None

        if payload is None:
            return None
        try:
            data = json.loads(payload)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            LOGGER.debug("Malformed VT cache for %s", file_hash)
            return None

    def _fetch_vt_payload(self, file_hash: str) -> Optional[dict[str, Any]]:
        """Fetch a fresh VirusTotal payload and persist it to disk."""
        response = vt_query(
            file_hash,
            self.cache_dir,
            self.vt_api,
            session_factory=lambda: self._session_factory("virustotal"),
            timeout=self._timeout,
        )
        if isinstance(response, dict):
            try:
                _write_text(self.cache_dir / file_hash, json.dumps(response))
            except Exception:  # pragma: no cover - defensive logging
                LOGGER.debug("Failed to persist VT payload for %s", file_hash, exc_info=True)
            return response
        return self._load_vt_payload(file_hash)

    def _iter_session_enrichments(self, enrichment: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
        """Yield per-IP enrichment payloads from ``enrichment`` mapping."""
        session_section = enrichment.get("session") if isinstance(enrichment, Mapping) else None
        if isinstance(session_section, Mapping):
            for payload in session_section.values():
                if isinstance(payload, Mapping):
                    yield payload
        else:
            yield enrichment

    @staticmethod
    def _dshield_flag(payload: Any) -> bool:
        """Return True when DShield metadata indicates prior activity."""
        if not isinstance(payload, Mapping):
            return False
        ip_obj = payload.get("ip")
        if not isinstance(ip_obj, Mapping):
            return False
        count = _coerce_int(ip_obj.get("count"))
        attacks = _coerce_int(ip_obj.get("attacks"))
        return count > 0 or attacks > 0

    @staticmethod
    def _urlhaus_flag(payload: Any) -> bool:
        """Return True when URLHaus tags are present."""
        return isinstance(payload, str) and bool(payload.strip())

    @staticmethod
    def _spur_flag(payload: Any) -> bool:
        """Return True when SPUR identifies risky infrastructure."""
        if not isinstance(payload, list) or len(payload) < 4:
            return False
        infrastructure = payload[3]
        if not isinstance(infrastructure, str):
            return False
        return infrastructure.upper() in {"DATACENTER", "VPN"}

    def _vt_flag(self, payload: Any) -> bool:
        """Return True when VirusTotal verdicts indicate malicious files."""
        for vt_payload in self._iter_vt_payloads(payload):
            stats = self._extract_vt_stats(vt_payload)
            if _coerce_int(stats.get("malicious")) > 0:
                return True
        return False

    def _iter_vt_payloads(self, payload: Any) -> Iterator[Mapping[str, Any]]:
        """Yield individual VirusTotal payloads from arbitrary structures."""
        if isinstance(payload, Mapping):
            data = payload.get("data")
            if isinstance(data, Mapping):
                yield payload
            else:
                for value in payload.values():
                    yield from self._iter_vt_payloads(value)
        elif isinstance(payload, Iterable) and not isinstance(payload, (str, bytes)):
            for item in payload:
                yield from self._iter_vt_payloads(item)

    def get_vt_quota_status(self) -> Dict[str, Any]:
        """Get VirusTotal quota status.

        Returns:
            Dictionary with quota status information
        """
        if hasattr(self, 'vt_handler'):
            return self.vt_handler.get_quota_status()
        return {"status": "disabled", "message": "VirusTotal handler not initialized"}

    @staticmethod
    def _extract_vt_stats(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Extract the ``last_analysis_stats`` block from a VT payload."""
        data = payload.get("data") if isinstance(payload, Mapping) else None
        attributes = data.get("attributes") if isinstance(data, Mapping) else None
        stats = attributes.get("last_analysis_stats") if isinstance(attributes, Mapping) else None
        return stats if isinstance(stats, Mapping) else {}

    def close(self) -> None:
        """Close enrichment service and cleanup resources."""
        # Close VirusTotal handler
        if hasattr(self, 'vt_handler'):
            self.vt_handler.close()

        # Close hybrid cache (Redis connection)
        if isinstance(self.cache_manager, HybridEnrichmentCache):
            self.cache_manager.close()

        # Close all active sessions
        for session in self._active_sessions:
            try:
                if hasattr(session, 'close'):
                    session.close()
            except Exception:
                # Ignore errors during cleanup
                pass
        self._active_sessions.clear()

    def __enter__(self) -> 'EnrichmentService':
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit with cleanup."""
        self.close()


def _coerce_int(value: Any) -> int:
    """Best-effort coercion of mixed numeric types into integers."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "EnrichmentService",
    "vt_query",
    "dshield_query",
    "safe_read_uh_data",
    "read_uh_data",
    "read_spur_data",
    "with_timeout",
    "_SPUR_EMPTY_PAYLOAD",
]
