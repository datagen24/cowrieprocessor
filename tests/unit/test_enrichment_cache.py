"""Unit tests for the enrichment cache manager."""

from __future__ import annotations

import os
import time
from pathlib import Path

from cowrieprocessor.enrichment import EnrichmentCacheManager


def test_cache_manager_records_hits_and_misses(tmp_path: Path) -> None:
    """Cache manager should track hits, misses, and respect TTLs."""
    manager = EnrichmentCacheManager(tmp_path, ttls={'virustotal': 60})

    # Miss prior to storing
    assert manager.load_text('virustotal', 'deadbeef') is None
    assert manager.stats['misses'] == 1

    manager.store_text('virustotal', 'deadbeef', '{"status": "ok"}')
    assert manager.stats['stores'] == 1

    cached = manager.load_text('virustotal', 'deadbeef')
    assert cached == '{"status": "ok"}'
    assert manager.stats['hits'] == 1

    # Expire entry by manipulating mtime
    cache_path = manager.get_path('virustotal', 'deadbeef')
    os.utime(cache_path, (time.time() - 120, time.time() - 120))
    assert manager.load_text('virustotal', 'deadbeef') is None
    assert manager.stats['misses'] == 2


def test_cache_manager_snapshot_is_copy(tmp_path: Path) -> None:
    """Snapshot should return a copy of the internal stats."""
    manager = EnrichmentCacheManager(tmp_path)
    manager.store_text('dshield', '1.2.3.4', '{}')
    snapshot = manager.snapshot()
    snapshot['stores'] = 999
    assert manager.stats['stores'] != 999


def test_cleanup_expired_removes_stale_entries(tmp_path: Path) -> None:
    """Expired cache entries should be removed without touching fresh ones."""
    manager = EnrichmentCacheManager(tmp_path, ttls={'virustotal': 60})

    manager.store_text('virustotal', 'fresh-hash', '{"status": "ok"}')
    manager.store_text('virustotal', 'stale-hash', '{"status": "stale"}')

    fresh_path = manager.get_path('virustotal', 'fresh-hash')
    stale_path = manager.get_path('virustotal', 'stale-hash')

    base_time = time.time()
    os.utime(fresh_path, (base_time, base_time))
    os.utime(stale_path, (base_time - 3600, base_time - 3600))

    stats = manager.cleanup_expired(now=lambda: base_time)

    assert stats['scanned'] == 2
    assert stats['deleted'] == 1
    assert stale_path.exists() is False
    assert fresh_path.exists() is True
