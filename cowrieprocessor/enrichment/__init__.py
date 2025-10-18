"""Enrichment utilities for compatibility layers and caching."""

from __future__ import annotations

from .cache import EnrichmentCacheManager

__all__ = ["EnrichmentCacheManager", "LegacyEnrichmentAdapter"]


def __getattr__(name: str) -> type:
    if name == "LegacyEnrichmentAdapter":
        from .legacy_adapter import LegacyEnrichmentAdapter as adapter

        return adapter
    raise AttributeError(f"module 'cowrieprocessor.enrichment' has no attribute {name!r}")
