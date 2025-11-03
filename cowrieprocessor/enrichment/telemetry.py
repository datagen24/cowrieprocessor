"""Telemetry integration for enrichment services."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from cowrieprocessor.status_emitter import StatusEmitter


@dataclass
class EnrichmentMetrics:
    """Metrics for enrichment operations."""

    # Cache statistics (overall)
    cache_hits: int = 0
    cache_misses: int = 0
    cache_stores: int = 0

    # Cache tier statistics (L1 Redis, L2 Filesystem, L3 API)
    l1_redis_hits: int = 0
    l1_redis_misses: int = 0
    l1_redis_stores: int = 0
    l1_redis_errors: int = 0
    l1_redis_latency_ms: float = 0.0

    l2_filesystem_hits: int = 0
    l2_filesystem_misses: int = 0
    l2_filesystem_stores: int = 0
    l2_filesystem_errors: int = 0
    l2_filesystem_latency_ms: float = 0.0

    l3_api_calls: int = 0

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

    def record_cache_stats(self, cache_stats: Dict[str, Any]) -> None:
        """Record cache statistics.

        Supports both legacy format (hits/misses/stores) and new hybrid cache format
        with tier-specific statistics (L1 Redis, L2 Filesystem, L3 API).
        """
        # Check if this is hybrid cache stats (with tier breakdown)
        if "l1_redis" in cache_stats and "l2_filesystem" in cache_stats:
            # New hybrid cache format
            l1_stats = cache_stats.get("l1_redis", {})
            l2_stats = cache_stats.get("l2_filesystem", {})

            self.metrics.l1_redis_hits = l1_stats.get("hits", 0)
            self.metrics.l1_redis_misses = l1_stats.get("misses", 0)
            self.metrics.l1_redis_stores = l1_stats.get("stores", 0)
            self.metrics.l1_redis_errors = l1_stats.get("errors", 0)
            self.metrics.l1_redis_latency_ms = l1_stats.get("avg_latency_ms", 0.0)

            self.metrics.l2_filesystem_hits = l2_stats.get("hits", 0)
            self.metrics.l2_filesystem_misses = l2_stats.get("misses", 0)
            self.metrics.l2_filesystem_stores = l2_stats.get("stores", 0)
            self.metrics.l2_filesystem_errors = l2_stats.get("errors", 0)
            self.metrics.l2_filesystem_latency_ms = l2_stats.get("avg_latency_ms", 0.0)

            self.metrics.l3_api_calls = cache_stats.get("l3_api_calls", 0)

            # Update overall cache stats for backward compatibility
            self.metrics.cache_hits = cache_stats.get("total_cache_hits", 0)
            self.metrics.cache_misses = cache_stats.get("total_cache_misses", 0)
            self.metrics.cache_stores = self.metrics.l1_redis_stores + self.metrics.l2_filesystem_stores
        else:
            # Legacy filesystem-only cache format
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
        summary: Dict[str, Any] = {
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

        # Add cache tier breakdown if hybrid cache is being used
        if self.metrics.l1_redis_hits > 0 or self.metrics.l1_redis_misses > 0:
            l1_total = self.metrics.l1_redis_hits + self.metrics.l1_redis_misses
            l1_hit_rate = (self.metrics.l1_redis_hits / l1_total * 100.0) if l1_total > 0 else 0.0

            l2_total = self.metrics.l2_filesystem_hits + self.metrics.l2_filesystem_misses
            l2_hit_rate = (self.metrics.l2_filesystem_hits / l2_total * 100.0) if l2_total > 0 else 0.0

            summary["cache_tier_stats"] = {
                "l1_redis": {
                    "hits": self.metrics.l1_redis_hits,
                    "misses": self.metrics.l1_redis_misses,
                    "stores": self.metrics.l1_redis_stores,
                    "errors": self.metrics.l1_redis_errors,
                    "hit_rate_percent": l1_hit_rate,
                    "avg_latency_ms": self.metrics.l1_redis_latency_ms,
                },
                "l2_filesystem": {
                    "hits": self.metrics.l2_filesystem_hits,
                    "misses": self.metrics.l2_filesystem_misses,
                    "stores": self.metrics.l2_filesystem_stores,
                    "errors": self.metrics.l2_filesystem_errors,
                    "hit_rate_percent": l2_hit_rate,
                    "avg_latency_ms": self.metrics.l2_filesystem_latency_ms,
                },
                "l3_api_calls": self.metrics.l3_api_calls,
            }

        return summary
