"""Compatibility adapter for legacy enrichment functions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from enrichment_handlers import _SPUR_EMPTY_PAYLOAD, EnrichmentService

from .cache import EnrichmentCacheManager


class LegacyEnrichmentAdapter:
    """Bridge old enrichment helpers to the new :class:`EnrichmentService`."""

    def __init__(
        self,
        *,
        cache_manager: EnrichmentCacheManager,
        cache_dir: Path,
        vt_api: str | None,
        dshield_email: str | None,
        urlhaus_api: str | None,
        spur_api: str | None,
        skip_enrich: bool,
    ) -> None:
        """Create the adapter.

        Args:
            cache_manager: Shared cache manager instance.
            cache_dir: Legacy cache directory used by ``process_cowrie``.
            vt_api: VirusTotal API key.
            dshield_email: DShield contact email.
            urlhaus_api: URLHaus API token.
            spur_api: SPUR API token.
            skip_enrich: Whether enrichments are disabled for the run.
        """
        self.cache_manager = cache_manager
        self.cache_dir = cache_dir
        self.enabled = not skip_enrich
        self.service = EnrichmentService(
            cache_dir=cache_dir,
            vt_api=vt_api,
            dshield_email=dshield_email,
            urlhaus_api=urlhaus_api,
            spur_api=spur_api,
            cache_manager=cache_manager,
        )
        self._session_cache: Dict[str, Dict[str, Any]] = {}
        self._file_cache: Dict[str, Dict[str, Any]] = {}

    def dshield(self, ip_address: str) -> Dict[str, Any]:
        """Return DShield metadata for the supplied IP."""
        enrichment = self._get_session_enrichment(ip_address)
        result: Dict[str, Any] = enrichment.get("dshield", {"ip": {"asname": "", "ascountry": ""}})
        return result

    def urlhaus(self, ip_address: str) -> str:
        """Return URLHaus tags for the supplied IP address."""
        enrichment = self._get_session_enrichment(ip_address)
        tags = enrichment.get("urlhaus", "")
        if isinstance(tags, (list, tuple, set)):
            return ", ".join(sorted({str(tag) for tag in tags if tag}))
        return str(tags) if tags else ""

    def spur(self, ip_address: str) -> list[str]:
        """Return SPUR data in the legacy list format."""
        enrichment = self._get_session_enrichment(ip_address)
        spur_data = enrichment.get("spur")
        if isinstance(spur_data, list) and len(spur_data) == len(_SPUR_EMPTY_PAYLOAD):
            return spur_data
        return list(_SPUR_EMPTY_PAYLOAD)

    def virustotal(self, file_hash: str, filename: str | None = None) -> Dict[str, Any] | None:
        """Return VirusTotal enrichment for a file hash and persist legacy cache."""
        enrichment = self._get_file_enrichment(file_hash, filename)
        vt_data = enrichment.get("virustotal") if isinstance(enrichment, dict) else None
        if vt_data is None:
            return None
        try:
            with (self.cache_dir / file_hash).open('w', encoding='utf-8') as handle:
                handle.write(json.dumps(vt_data))
        except OSError:
            pass
        result: Dict[str, Any] = vt_data
        return result

    def cache_snapshot(self) -> Dict[str, int]:
        """Expose underlying cache telemetry."""
        return self.service.cache_snapshot()

    def _get_session_enrichment(self, ip_address: str) -> Dict[str, Any]:
        if ip_address not in self._session_cache:
            result = self.service.enrich_session(ip_address, ip_address)
            enrichment = result.get("enrichment", {}) if isinstance(result, dict) else {}
            self._session_cache[ip_address] = enrichment
        return self._session_cache[ip_address]

    def _get_file_enrichment(self, file_hash: str, filename: str | None) -> Dict[str, Any]:
        if file_hash not in self._file_cache:
            result = self.service.enrich_file(file_hash, filename or file_hash)
            enrichment = result.get("enrichment", {}) if isinstance(result, dict) else {}
            self._file_cache[file_hash] = enrichment
        return self._file_cache[file_hash]


__all__ = ["LegacyEnrichmentAdapter"]
