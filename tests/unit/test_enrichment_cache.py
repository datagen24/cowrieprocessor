"""Unit tests for the enrichment cache manager."""

from __future__ import annotations

import hashlib
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


def test_hibp_cache_path_structure(tmp_path: Path) -> None:
    """HIBP cache entries should be organized by SHA-1 prefix buckets."""
    manager = EnrichmentCacheManager(tmp_path)
    path = manager.get_path('hibp', 'ABCDE')

    rel_path = path.relative_to(tmp_path)
    assert rel_path.parts[0] == 'hibp'
    assert rel_path.parts[1:4] == ('AB', 'CD', 'E')
    assert path.name == 'ABCDE.json'


def test_dshield_cache_path_structure(tmp_path: Path) -> None:
    """DShield cache entries should shard IPv4 addresses by octet."""
    manager = EnrichmentCacheManager(tmp_path)
    path = manager.get_path('dshield', '203.0.113.5')

    rel_path = path.relative_to(tmp_path)
    assert rel_path.parts[0] == 'dshield'
    assert rel_path.parts[1:4] == ('203', '0', '113')
    assert path.name == '5.json'


def test_legacy_cache_migrates_to_new_layout(tmp_path: Path) -> None:
    """Existing legacy cache files should migrate to the new layout on access."""
    manager = EnrichmentCacheManager(tmp_path)
    cache_key = 'ABCDE'
    digest = hashlib.sha256(cache_key.encode('utf-8')).hexdigest()

    legacy_path = tmp_path / 'hibp' / digest[:2] / f'{digest}.json'
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text('{"value": 1}', encoding='utf-8')

    cached = manager.get_cached('hibp', cache_key)
    assert cached == {'value': 1}

    new_path = manager.get_path('hibp', cache_key)
    assert new_path.exists()
    assert not legacy_path.exists()
