"""Telemetry integration for enrichment services."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from cowrieprocessor.status_emitter import StatusEmitter


@dataclass
class EnrichmentMetrics:
    """Metrics for enrichment operations."""

    # Cache statistics
    cache_hits: int = 0
    cache_misses: int = 0
    cache_stores: int = 0

    # API call statistics
    api_calls_total: int = 0
    api_calls_successful: int = 0
    api_calls_failed: int = 0

    # Rate limiting statistics
    rate_limit_hits: int = 0
    rate_limit_delays: float = 0.0

    # Performance metrics
    enrichment_duration_ms: float = 0.0
    sessions_enriched: int = 0
    files_enriched: int = 0

    # Service-specific metrics
    dshield_calls: int = 0
    virustotal_calls: int = 0
    urlhaus_calls: int = 0
    spur_calls: int = 0

    # Error tracking
    enrichment_errors: int = 0
    cache_errors: int = 0

    # Timestamps
    last_enrichment_time: Optional[str] = None
    ingest_id: Optional[str] = None


class EnrichmentTelemetry:
    """Telemetry integration for enrichment services."""

    def __init__(self, phase: str = "enrichment", status_dir: Optional[str] = None):
        """Initialize enrichment telemetry.

        Args:
            phase: The telemetry phase name
            status_dir: Optional custom status directory
        """
        self.status_emitter = StatusEmitter(phase, status_dir)
        self.metrics = EnrichmentMetrics()
        self._start_time = time.time()

    def record_cache_stats(self, cache_stats: Dict[str, int]) -> None:
        """Record cache statistics."""
        self.metrics.cache_hits = cache_stats.get("hits", 0)
        self.metrics.cache_misses = cache_stats.get("misses", 0)
        self.metrics.cache_stores = cache_stats.get("stores", 0)
        self._emit_metrics()

    def record_api_call(self, service: str, success: bool, duration_ms: float = 0.0) -> None:
        """Record an API call."""
        self.metrics.api_calls_total += 1
        if success:
            self.metrics.api_calls_successful += 1
        else:
            self.metrics.api_calls_failed += 1

        # Service-specific tracking
        if service == "dshield":
            self.metrics.dshield_calls += 1
        elif service == "virustotal":
            self.metrics.virustotal_calls += 1
        elif service == "urlhaus":
            self.metrics.urlhaus_calls += 1
        elif service == "spur":
            self.metrics.spur_calls += 1

        self.metrics.enrichment_duration_ms += duration_ms
        self._emit_metrics()

    def record_rate_limit_hit(self, service: str, delay_seconds: float) -> None:
        """Record a rate limit hit."""
        self.metrics.rate_limit_hits += 1
        self.metrics.rate_limit_delays += delay_seconds
        self._emit_metrics()

    def record_session_enrichment(self, success: bool) -> None:
        """Record a session enrichment."""
        if success:
            self.metrics.sessions_enriched += 1
        else:
            self.metrics.enrichment_errors += 1

        self.metrics.last_enrichment_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._emit_metrics()

    def record_file_enrichment(self, success: bool) -> None:
        """Record a file enrichment."""
        if success:
            self.metrics.files_enriched += 1
        else:
            self.metrics.enrichment_errors += 1

        self.metrics.last_enrichment_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._emit_metrics()

    def record_cache_error(self) -> None:
        """Record a cache error."""
        self.metrics.cache_errors += 1
        self._emit_metrics()

    def set_ingest_id(self, ingest_id: str) -> None:
        """Set the ingest ID for this telemetry session."""
        self.metrics.ingest_id = ingest_id
        self._emit_metrics()

    def _emit_metrics(self) -> None:
        """Emit current metrics to the status emitter."""
        self.status_emitter.record_metrics(self.metrics)

    def get_cache_hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total_requests = self.metrics.cache_hits + self.metrics.cache_misses
        if total_requests == 0:
            return 0.0
        return (self.metrics.cache_hits / total_requests) * 100.0

    def get_api_success_rate(self) -> float:
        """Calculate API success rate."""
        if self.metrics.api_calls_total == 0:
            return 0.0
        return (self.metrics.api_calls_successful / self.metrics.api_calls_total) * 100.0

    def get_enrichment_throughput(self) -> float:
        """Calculate enrichment throughput (sessions per second)."""
        elapsed_time = time.time() - self._start_time
        if elapsed_time == 0:
            return 0.0
        return self.metrics.sessions_enriched / elapsed_time

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of current metrics."""
        return {
            "cache_stats": {
                "hits": self.metrics.cache_hits,
                "misses": self.metrics.cache_misses,
                "stores": self.metrics.cache_stores,
                "hit_rate_percent": self.get_cache_hit_rate(),
            },
            "api_stats": {
                "total_calls": self.metrics.api_calls_total,
                "successful_calls": self.metrics.api_calls_successful,
                "failed_calls": self.metrics.api_calls_failed,
                "success_rate_percent": self.get_api_success_rate(),
            },
            "service_stats": {
                "dshield_calls": self.metrics.dshield_calls,
                "virustotal_calls": self.metrics.virustotal_calls,
                "urlhaus_calls": self.metrics.urlhaus_calls,
                "spur_calls": self.metrics.spur_calls,
            },
            "performance": {
                "sessions_enriched": self.metrics.sessions_enriched,
                "files_enriched": self.metrics.files_enriched,
                "throughput_sessions_per_sec": self.get_enrichment_throughput(),
                "avg_enrichment_duration_ms": (
                    self.metrics.enrichment_duration_ms / max(1, self.metrics.api_calls_total)
                ),
            },
            "rate_limiting": {
                "rate_limit_hits": self.metrics.rate_limit_hits,
                "total_delay_seconds": self.metrics.rate_limit_delays,
            },
            "errors": {
                "enrichment_errors": self.metrics.enrichment_errors,
                "cache_errors": self.metrics.cache_errors,
            },
            "timestamps": {
                "last_enrichment": self.metrics.last_enrichment_time,
                "ingest_id": self.metrics.ingest_id,
            },
        }
