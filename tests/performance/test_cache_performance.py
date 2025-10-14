"""Performance tests for EnrichmentCacheManager with large datasets."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Dict, List, Set

import pytest

from cowrieprocessor.enrichment.cache import EnrichmentCacheManager


class TestCachePerformance:
    """Test cache performance with large datasets and verify sharding."""

    @pytest.fixture
    def cache_manager(self) -> EnrichmentCacheManager:
        """Create a cache manager for performance testing."""
        cache_dir = Path(tempfile.mkdtemp())
        return EnrichmentCacheManager(base_dir=cache_dir)

    def generate_test_data(self, count: int) -> List[Dict[str, any]]:
        """Generate test data for performance testing."""
        test_data = []
        for i in range(count):
            data = {
                "ip": f"192.168.{i // 256}.{i % 256}",
                "session": f"session_{i:06d}",
                "metadata": {
                    "asname": f"ISP_{i % 100}",
                    "ascountry": ["US", "CA", "GB", "DE", "FR"][i % 5],
                    "tags": [f"tag_{j}" for j in range(i % 5)],
                    "scores": list(range(i % 10)),
                },
                "enrichments": {
                    "dshield": {"ip": f"192.168.{i // 256}.{i % 256}", "reputation": i % 100},
                    "virustotal": {"file_hash": f"hash_{i:08x}", "detections": i % 50},
                    "spur": [{"type": f"threat_{j}", "confidence": (i + j) % 100 / 100} for j in range(i % 3)],
                },
                "timestamp": f"2025-01-01T{(i % 24):02d}:00:00Z",
            }
            test_data.append(data)
        return test_data

    def test_performance_10k_entries(self, cache_manager: EnrichmentCacheManager) -> None:
        """Test cache performance with 10,000+ entries."""
        # Generate 10,000 test entries
        test_data = self.generate_test_data(10000)

        # Measure store performance
        start_time = time.time()
        for i, data in enumerate(test_data):
            cache_manager.store_cached("performance_test", f"entry_{i:06d}", data)
        store_time = time.time() - start_time

        # Verify all entries were stored
        stats = cache_manager.snapshot()
        assert stats["stores"] == 10000

        # Measure retrieval performance (random access)
        import random

        random.seed(42)  # For reproducible results
        test_indices = [random.randint(0, 9999) for _ in range(1000)]

        start_time = time.time()
        retrieved_count = 0
        for idx in test_indices:
            result = cache_manager.get_cached("performance_test", f"entry_{idx:06d}")
            if result is not None:
                retrieved_count += 1
        retrieval_time = time.time() - start_time

        # Verify retrieval performance
        assert retrieved_count == 1000  # All should be found
        assert retrieval_time < 5.0  # Should retrieve 1000 entries in under 5 seconds

        # Verify final stats
        final_stats = cache_manager.snapshot()
        assert final_stats["hits"] == 1000
        assert final_stats["stores"] == 10000

        # Performance assertions
        assert store_time < 30.0  # Should store 10k entries in under 30 seconds
        print(f"Store time: {store_time:.2f}s for 10,000 entries")
        print(f"Retrieval time: {retrieval_time:.2f}s for 1,000 random entries")

    def test_sharding_distribution(self, cache_manager: EnrichmentCacheManager) -> None:
        """Test that cache entries are properly distributed across shards."""
        # Generate test data with known patterns
        test_data = self.generate_test_data(1000)

        # Store entries
        for i, data in enumerate(test_data):
            cache_manager.store_cached("sharding_test", f"entry_{i:06d}", data)

        # Collect shard distribution
        shard_counts: Dict[str, int] = {}
        shard_paths: Set[Path] = set()

        # Check all possible shards (00-ff)
        for shard in range(256):
            shard_hex = f"{shard:02x}"
            shard_dir = cache_manager.base_dir / "sharding_test" / shard_hex
            if shard_dir.exists():
                files = list(shard_dir.glob("*.json"))
                shard_counts[shard_hex] = len(files)
                shard_paths.add(shard_dir)

        # Verify we have multiple shards
        assert len(shard_paths) > 1, "Entries should be distributed across multiple shards"

        # Verify no single shard has all entries
        total_entries = sum(shard_counts.values())
        assert total_entries == 1000, f"Expected 1000 entries, found {total_entries}"

        max_shard_count = max(shard_counts.values()) if shard_counts else 0
        assert max_shard_count < 1000, "No single shard should contain all entries"

        # Verify reasonable distribution (no shard should be empty if others are full)
        non_empty_shards = [count for count in shard_counts.values() if count > 0]
        if len(non_empty_shards) > 1:
            min_count = min(non_empty_shards)
            max_count = max(non_empty_shards)
            # SHA256 with sequential keys can be quite uneven - allow up to 10x variance
            assert max_count <= min_count * 10, f"Shard distribution too uneven: {min_count} vs {max_count}"

        # More important: verify we have reasonable number of shards used
        assert len(shard_paths) >= 10, f"Too few shards used: {len(shard_paths)}"

        print(f"Shard distribution: {len(shard_paths)} shards used")
        print(f"Shard counts: {dict(sorted(shard_counts.items()))}")

    def test_cache_cleanup_performance(self, cache_manager: EnrichmentCacheManager) -> None:
        """Test cache cleanup performance with many expired entries."""
        # Generate test data
        test_data = self.generate_test_data(5000)

        # Store entries using a service with known TTL
        service = "dshield"  # Has 7 day TTL
        for i, data in enumerate(test_data):
            cache_manager.store_cached(service, f"entry_{i:06d}", data)

        # Verify all entries were stored
        stats = cache_manager.snapshot()
        assert stats["stores"] == 5000

        # Simulate expired entries by manually modifying file timestamps
        # This is a bit of a hack, but necessary for testing cleanup
        import os

        old_time = time.time() - (8 * 24 * 3600)  # 8 days ago (older than 7 day TTL)

        cleanup_test_dir = cache_manager.base_dir / service
        for shard_dir in cleanup_test_dir.iterdir():
            if shard_dir.is_dir():
                for cache_file in shard_dir.glob("*.json"):
                    os.utime(cache_file, (old_time, old_time))

        # Run cleanup
        start_time = time.time()
        cleanup_stats = cache_manager.cleanup_expired()
        cleanup_time = time.time() - start_time

        # Verify cleanup performance and results
        assert cleanup_time < 10.0, "Cleanup should complete in under 10 seconds"
        assert cleanup_stats["scanned"] == 5000, "Should scan all entries"
        assert cleanup_stats["deleted"] > 0, "Should delete expired entries"

        print(f"Cleanup time: {cleanup_time:.2f}s for 5,000 entries")
        print(f"Cleanup stats: {cleanup_stats}")

    def test_concurrent_access_simulation(self, cache_manager: EnrichmentCacheManager) -> None:
        """Simulate concurrent access patterns."""
        # Generate test data
        test_data = self.generate_test_data(1000)

        # Store entries
        for i, data in enumerate(test_data):
            cache_manager.store_cached("concurrent_test", f"entry_{i:06d}", data)

        # Simulate concurrent reads (sequential for testing)
        import random

        random.seed(42)

        # Simulate 100 concurrent "threads" each doing 10 reads
        total_reads = 0
        start_time = time.time()

        for thread_id in range(100):
            for read_id in range(10):
                # Random key selection
                key_id = random.randint(0, 999)
                key = f"entry_{key_id:06d}"

                result = cache_manager.get_cached("concurrent_test", key)
                if result is not None:
                    total_reads += 1

        concurrent_time = time.time() - start_time

        # Verify performance
        assert concurrent_time < 5.0, "Concurrent access simulation should complete quickly"
        assert total_reads == 1000, "Should successfully read all entries"

        print(f"Concurrent access time: {concurrent_time:.2f}s for 1,000 reads")

    def test_memory_efficiency(self, cache_manager: EnrichmentCacheManager) -> None:
        """Test that cache operations don't consume excessive memory."""
        import os

        import psutil

        # Get initial memory usage
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss

        # Generate and store large dataset
        test_data = self.generate_test_data(5000)

        for i, data in enumerate(test_data):
            cache_manager.store_cached("memory_test", f"entry_{i:06d}", data)

        # Check memory usage after storing
        after_store_memory = process.memory_info().rss
        memory_increase = after_store_memory - initial_memory

        # Memory increase should be reasonable (less than 100MB for 5k entries)
        assert memory_increase < 100 * 1024 * 1024, f"Memory usage increased by {memory_increase / 1024 / 1024:.1f}MB"

        # Perform many reads
        for i in range(1000):
            cache_manager.get_cached("memory_test", f"entry_{i % 5000:06d}")

        # Check memory usage after reads
        after_reads_memory = process.memory_info().rss
        reads_memory_increase = after_reads_memory - after_store_memory

        # Memory shouldn't grow significantly during reads
        assert reads_memory_increase < 10 * 1024 * 1024, (
            f"Memory usage increased by {reads_memory_increase / 1024 / 1024:.1f}MB during reads"
        )

        print(f"Memory increase after store: {memory_increase / 1024 / 1024:.1f}MB")
        print(f"Memory increase after reads: {reads_memory_increase / 1024 / 1024:.1f}MB")
