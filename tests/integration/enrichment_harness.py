"""Offline enrichment harness for integration tests and developer drills."""

from __future__ import annotations

import copy
import json
import sqlite3
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from cowrieprocessor.enrichment import EnrichmentCacheManager, LegacyEnrichmentAdapter
from cowrieprocessor.enrichment.handlers import _parse_spur_payload
from tests.fixtures.enrichment_fixtures import (
    DSHIELD_RESPONSES,
    SPUR_RESPONSES,
    URLHAUS_RESPONSES,
    VIRUSTOTAL_RESPONSES,
)

try:
    from unittest.mock import patch
except ImportError:  # pragma: no cover - defensive
    from mock import patch  # type: ignore


@dataclass(frozen=True)
class HarnessSessionResult:
    """Result bundle returned by the offline enrichment harness."""

    session_id: str
    src_ip: str
    enrichment: Dict[str, Any]
    flags: Dict[str, bool]


def _default_stub_payloads() -> Dict[str, Any]:
    """Return default stub payloads for each enrichment provider."""
    return {
        "dshield": {"default": copy.deepcopy(DSHIELD_RESPONSES["datacenter"])},
        "urlhaus": {"default": copy.deepcopy(URLHAUS_RESPONSES["malicious_urls"])},
        "spur": {"default": copy.deepcopy(SPUR_RESPONSES["datacenter"])},
        "virustotal": {"default": copy.deepcopy(VIRUSTOTAL_RESPONSES["malware"])},
    }


class OfflineEnrichmentHarness:
    """Context manager that patches enrichment lookups with stub responses."""

    def __init__(
        self,
        db_path: Path,
        cache_dir: Path,
        *,
        stubbed_responses: Optional[Dict[str, Any]] = None,
        skip_enrich: bool = False,
        readonly: bool = True,
    ) -> None:
        """Prepare harness configuration before patches are activated."""
        self.db_path = Path(db_path)
        self.cache_dir = Path(cache_dir)
        self.stubbed_responses = stubbed_responses or _default_stub_payloads()
        self.skip_enrich = skip_enrich
        self.readonly = readonly
        self._stack = ExitStack()
        self._adapter: LegacyEnrichmentAdapter | None = None
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> "OfflineEnrichmentHarness":
        """Initialise mocks, cache manager, and open a database connection."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._stack.enter_context(patch("enrichment_handlers.dshield_query", self._fake_dshield))
        self._stack.enter_context(patch("enrichment_handlers.safe_read_uh_data", self._fake_urlhaus))
        self._stack.enter_context(patch("enrichment_handlers.read_spur_data", self._fake_spur))
        self._stack.enter_context(patch("enrichment_handlers.vt_query", self._fake_vt))

        cache_manager = EnrichmentCacheManager(self.cache_dir)
        self._adapter = LegacyEnrichmentAdapter(
            cache_manager=cache_manager,
            cache_dir=self.cache_dir,
            vt_api="offline-vt",
            dshield_email="offline@example.com",
            urlhaus_api="offline-urlhaus",
            spur_api="offline-spur",
            skip_enrich=self.skip_enrich,
        )

        if self.readonly:
            uri = f"file:{self.db_path}?mode=ro&immutable=1"
            self._connection = sqlite3.connect(uri, uri=True)
            self._connection.execute("PRAGMA query_only=1")
        else:
            self._connection = sqlite3.connect(self.db_path)

        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Tear down temporary resources and close the SQLite connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._stack.close()

    @property
    def adapter(self) -> LegacyEnrichmentAdapter:
        """Return the lazily constructed legacy adapter used in tests."""
        if self._adapter is None:
            raise RuntimeError("Harness must be entered before use")
        return self._adapter

    @property
    def connection(self) -> sqlite3.Connection:
        """Expose the current SQLite connection for fixture consumers."""
        if self._connection is None:
            raise RuntimeError("Harness must be entered before use")
        return self._connection

    def cache_snapshot(self) -> Dict[str, int]:
        """Return cache telemetry counters collected during the harness run."""
        return self.adapter.cache_snapshot()

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    def sample_sessions(self, limit: int = 10) -> List[Tuple[str, str]]:
        """Return session IDs and source IPs from the backing database."""
        sessions: List[Tuple[str, str]] = []
        cursor = self.connection.execute(
            "SELECT session_id FROM session_summaries LIMIT ?",
            (limit,),
        )
        for (session_id,) in cursor:
            src_ip = self._lookup_src_ip(session_id)
            if src_ip:
                sessions.append((session_id, src_ip))
        return sessions

    def _lookup_src_ip(self, session_id: str) -> Optional[str]:
        cursor = self.connection.execute(
            """
            SELECT json_extract(payload, '$.src_ip')
            FROM raw_events
            WHERE session_id = ? AND json_extract(payload, '$.src_ip') IS NOT NULL
            LIMIT 1
            """,
            (session_id,),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------
    # Enrichment helpers
    # ------------------------------------------------------------------

    def evaluate_session(
        self,
        session_id: str,
        src_ip: str,
        *,
        file_hashes: Iterable[str] | None = None,
    ) -> HarnessSessionResult:
        """Run offline enrichments for the provided session/IP pair."""
        session_result = self.adapter.service.enrich_session(session_id, src_ip)
        enrichment_payload: Dict[str, Any] = dict(session_result.get("enrichment", {}))

        if file_hashes:
            for file_hash in file_hashes:
                file_result = self.adapter.service.enrich_file(file_hash, file_hash)
                enrichment_payload.update(file_result.get("enrichment", {}))

        combined = {
            "session_id": session_id,
            "src_ip": src_ip,
            "enrichment": enrichment_payload,
        }
        flags = self.adapter.service.get_session_flags(combined)
        return HarnessSessionResult(session_id, src_ip, enrichment_payload, flags)

    # ------------------------------------------------------------------
    # Stub helpers
    # ------------------------------------------------------------------

    def _resolve_stub(self, service: str, lookup_key: str) -> Any:
        data = self.stubbed_responses.get(service)
        if isinstance(data, dict) and "by_key" in data:
            mapping = data.get("by_key", {})
            if lookup_key in mapping:
                data = mapping[lookup_key]
            else:
                data = data.get("default", data)
        elif isinstance(data, dict) and "default" in data:
            data = data["default"]

        if callable(data):
            data = data(lookup_key)

        if isinstance(data, Exception):
            raise data

        if isinstance(data, (dict, list)):
            return copy.deepcopy(data)
        return data

    def _fake_dshield(self, ip_address: str, *_args, **_kwargs) -> Dict[str, Any]:
        payload = self._resolve_stub("dshield", ip_address)
        if isinstance(payload, str):
            return json.loads(payload)
        return payload

    def _fake_urlhaus(self, ip_address: str, *_args, **_kwargs) -> str:
        payload = self._resolve_stub("urlhaus", ip_address)
        if isinstance(payload, str):
            return payload
        urls = payload.get("urls", []) if isinstance(payload, dict) else []
        tags = {tag for entry in urls for tag in entry.get("tags", []) if tag}
        return ", ".join(sorted(tags))

    def _fake_spur(self, ip_address: str, *_args, **_kwargs) -> List[str]:
        payload = self._resolve_stub("spur", ip_address)
        if isinstance(payload, list):
            return payload
        if isinstance(payload, str):
            return _parse_spur_payload(payload)
        return _parse_spur_payload(json.dumps(payload))

    def _fake_vt(self, file_hash: str, *_args, **_kwargs) -> Optional[Dict[str, Any]]:
        payload = self._resolve_stub("virustotal", file_hash)
        if payload in (None, ""):
            return None
        if isinstance(payload, str):
            return json.loads(payload)
        return payload


__all__ = ["OfflineEnrichmentHarness", "HarnessSessionResult"]
