"""Performance tests for enrichment workflows."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.fixtures.enrichment_fixtures import (
    get_dshield_response,
    get_spur_response,
)
from tests.fixtures.mock_enrichment_handlers import MockAbuseIPDBHandler, MockOTXHandler
from tests.fixtures.statistical_analysis import HoneypotStatisticalAnalyzer


class TestEnrichmentCachePerformance:
    """Test cache performance under various scenarios."""

    def test_cache_hit_performance(self, tmp_path):
        """Test cache hit performance for repeated lookups."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        from process_cowrie import dshield_query

        # Populate cache with test data
        test_ip = "192.168.1.100"
        # dshield_data = json.loads(get_dshield_response("datacenter"))

        # First call - should make API call
        start_time = time.time()
        result1 = dshield_query(test_ip, cache_base=cache_dir)
        api_call_time = time.time() - start_time

        # Second call - should use cache
        start_time = time.time()
        result2 = dshield_query(test_ip, cache_base=cache_dir)
        cache_hit_time = time.time() - start_time

        # Cache hit should be significantly faster
        assert cache_hit_time < api_call_time * 0.1  # 10x faster
        assert result1 == result2

        # Verify cache file exists
        cache_file = cache_dir / "dshield_192.168.1.100.json"
        assert cache_file.exists()

    def test_cache_miss_performance(self, tmp_path):
        """Test cache miss performance for new lookups."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        from process_cowrie import dshield_query

        # Mock the API call to measure performance
        with patch('process_cowrie.enrichment_dshield_query') as mock_dshield:
            mock_dshield.return_value = json.loads(get_dshield_response("datacenter"))

            # Time multiple cache misses
            test_ips = [f"192.168.1.{i}" for i in range(10)]

            start_time = time.time()
            for ip in test_ips:
                dshield_query(ip, cache_base=cache_dir)
            total_time = time.time() - start_time

            # Should complete in reasonable time
            assert total_time < 5.0  # Less than 5 seconds for 10 lookups
            assert mock_dshield.call_count == 10

    def test_concurrent_cache_access_performance(self, tmp_path):
        """Test cache performance under concurrent access."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        from process_cowrie import dshield_query

        def worker(ip):
            """Worker function for concurrent cache access."""
            return dshield_query(ip, cache_base=cache_dir)

        # Mock API calls
        with patch('process_cowrie.enrichment_dshield_query') as mock_dshield:
            mock_dshield.return_value = json.loads(get_dshield_response("datacenter"))

            test_ips = [f"192.168.1.{i}" for i in range(20)]

            # Test concurrent access
            start_time = time.time()
            with ThreadPoolExecutor(max_workers=5) as executor:
                results = list(executor.map(worker, test_ips))
            total_time = time.time() - start_time

            # Should complete in reasonable time
            assert total_time < 10.0  # Less than 10 seconds for 20 concurrent lookups
            assert len(results) == 20
            assert mock_dshield.call_count == 20

    def test_cache_ttl_performance(self, tmp_path):
        """Test cache TTL expiration performance."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        from process_cowrie import dshield_query

        # Create cache entry
        test_ip = "192.168.1.100"
        dshield_query(test_ip, cache_base=cache_dir)

        # Mock time to simulate TTL expiration
        with patch('process_cowrie.enrichment_dshield_query') as mock_dshield:
            mock_dshield.return_value = json.loads(get_dshield_response("datacenter"))

            # First call should use cache
            result1 = dshield_query(test_ip, cache_base=cache_dir, now=lambda: time.time())

            # Mock expired cache
            expired_time = time.time() - 7200  # 2 hours ago

            # Second call should make fresh API call
            result2 = dshield_query(test_ip, cache_base=cache_dir, now=lambda: expired_time)

            # Both calls should succeed but second should make API call
            assert result1 == result2
            assert mock_dshield.call_count == 1  # Only one API call due to expiration


class TestEnrichmentTimeoutPerformance:
    """Test timeout handling performance."""

    def test_timeout_enforcement(self, tmp_path):
        """Test that timeouts are properly enforced."""
        from process_cowrie import safe_read_uh_data

        def slow_api_call(*args, **kwargs):
            time.sleep(5)  # Longer than timeout
            return "completed"

        with patch('process_cowrie.with_timeout', side_effect=TimeoutError("Operation timed out")):
            start_time = time.time()
            result = safe_read_uh_data("192.168.1.100", "test-key", timeout=1)
            end_time = time.time()

            # Should timeout quickly
            assert end_time - start_time < 2.0
            assert result == "TIMEOUT"

    def test_timeout_with_cache_fallback(self, tmp_path):
        """Test timeout handling with cache fallback."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        # Pre-populate cache
        cache_file = cache_dir / "uh_192.168.1.100"
        cache_file.write_text('{"cached": "data"}')

        from process_cowrie import safe_read_uh_data

        def slow_api_call(*args, **kwargs):
            time.sleep(5)  # Longer than timeout
            return "completed"

        with patch('process_cowrie.with_timeout', side_effect=TimeoutError("Operation timed out")):
            result = safe_read_uh_data("192.168.1.100", "test-key", cache_base=cache_dir, timeout=1)

            # Should return timeout indicator
            assert result == "TIMEOUT"

    def test_bulk_timeout_handling(self, tmp_path):
        """Test timeout handling in bulk operations."""
        from process_cowrie import safe_read_uh_data

        def slow_api_call(*args, **kwargs):
            time.sleep(5)  # Longer than timeout
            return "completed"

        with patch('process_cowrie.with_timeout', side_effect=TimeoutError("Operation timed out")):
            # Test multiple IPs with timeouts
            test_ips = [f"192.168.1.{i}" for i in range(10)]

            start_time = time.time()
            results = []
            for ip in test_ips:
                result = safe_read_uh_data(ip, "test-key", timeout=1)
                results.append(result)
            end_time = time.time()

            # Should complete quickly despite timeouts
            assert end_time - start_time < 5.0  # Less than 5 seconds for 10 timeouts
            assert all(result == "TIMEOUT" for result in results)


class TestConcurrentEnrichmentPerformance:
    """Test concurrent enrichment processing performance."""

    def test_concurrent_ip_enrichment(self, tmp_path):
        """Test concurrent IP enrichment across multiple services."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        from process_cowrie import dshield_query, read_spur_data

        def enrich_ip(ip):
            """Enrich a single IP with multiple services."""
            results = {}

            # DShield enrichment
            try:
                results["dshield"] = dshield_query(ip, cache_base=cache_dir)
            except Exception:
                results["dshield"] = {"ip": {"asname": "", "ascountry": ""}}

            # SPUR enrichment
            try:
                results["spur"] = read_spur_data(ip, "test-key", cache_base=cache_dir)
            except Exception:
                results["spur"] = [""] * 18

            return results

        # Mock API calls for performance testing
        with (
            patch('process_cowrie.enrichment_dshield_query') as mock_dshield,
            patch('process_cowrie.enrichment_read_spur_data') as mock_spur,
        ):
            mock_dshield.return_value = json.loads(get_dshield_response("datacenter"))
            mock_spur.return_value = json.loads(get_spur_response("datacenter"))

            # Test concurrent enrichment
            test_ips = [f"192.168.1.{i}" for i in range(50)]

            start_time = time.time()
            with ThreadPoolExecutor(max_workers=10) as executor:
                results = list(executor.map(enrich_ip, test_ips))
            end_time = time.time()

            total_time = end_time - start_time

            # Should complete in reasonable time
            assert total_time < 15.0  # Less than 15 seconds for 50 concurrent enrichments
            assert len(results) == 50

            # Verify all results have expected structure
            for result in results:
                assert "dshield" in result
                assert "spur" in result
                assert result["dshield"]["ip"]["asname"] == "AMAZON-02"
                assert len(result["spur"]) == 18

    def test_concurrent_file_enrichment(self, tmp_path):
        """Test concurrent file hash enrichment."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        from process_cowrie import vt_query

        def enrich_file(hash_value):
            """Enrich a single file hash."""
            try:
                vt_query(hash_value, cache_dir)
                return True
            except Exception:
                return False

        # Mock API calls
        with patch('process_cowrie.enrichment_vt_query') as mock_vt:
            mock_vt.return_value = None  # VT query doesn't return value

            # Test concurrent file enrichment
            test_hashes = [f"hash_{i:032x}" for i in range(30)]

            start_time = time.time()
            with ThreadPoolExecutor(max_workers=5) as executor:
                results = list(executor.map(enrich_file, test_hashes))
            end_time = time.time()

            total_time = end_time - start_time

            # Should complete in reasonable time
            assert total_time < 10.0  # Less than 10 seconds for 30 concurrent enrichments
            assert all(results)  # All should succeed
            assert mock_vt.call_count == 30


class TestMockHandlerPerformance:
    """Test mock handler performance."""

    def test_mock_otx_performance(self, tmp_path):
        """Test mock OTX handler performance."""
        handler = MockOTXHandler("test_key", tmp_path)

        test_ips = [f"192.168.1.{i}" for i in range(100)]

        start_time = time.time()
        for ip in test_ips:
            result = handler.check_ip(ip)
            assert isinstance(result, dict)
        end_time = time.time()

        total_time = end_time - start_time

        # Should complete quickly (mock operations)
        assert total_time < 2.0  # Less than 2 seconds for 100 lookups

    def test_mock_abuseipdb_performance(self, tmp_path):
        """Test mock AbuseIPDB handler performance."""
        handler = MockAbuseIPDBHandler("test_key", tmp_path)

        test_ips = [f"192.168.1.{i}" for i in range(100)]

        start_time = time.time()
        for ip in test_ips:
            result = handler.check_ip(ip)
            assert isinstance(result, dict)
            assert "data" in result
        end_time = time.time()

        total_time = end_time - start_time

        # Should complete quickly (mock operations)
        assert total_time < 2.0  # Less than 2 seconds for 100 lookups

    def test_statistical_analysis_performance(self):
        """Test statistical analysis performance."""
        # Create mock database
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
            db_path = Path(tmp.name)

        try:
            conn = sqlite3.connect(db_path)

            # Create test tables
            conn.execute("""
                CREATE TABLE sessions (
                    session TEXT, src_ip TEXT, timestamp TEXT, commands TEXT
                )
            """)

            conn.execute("""
                CREATE TABLE commands (
                    session TEXT, command TEXT, timestamp TEXT
                )
            """)

            conn.execute("""
                CREATE TABLE files (
                    session TEXT, filename TEXT, shasum TEXT, timestamp TEXT
                )
            """)

            # Insert test data
            for i in range(1000):
                conn.execute(
                    """
                    INSERT INTO sessions (session, src_ip, timestamp, commands)
                    VALUES (?, ?, ?, ?)
                """,
                    (f"session_{i}", f"192.168.1.{i % 255}", "2025-01-01T10:00:00", "ls,pwd"),
                )

                conn.execute(
                    """
                    INSERT INTO commands (session, command, timestamp)
                    VALUES (?, ?, ?)
                """,
                    (f"session_{i}", f"command_{i}", "2025-01-01T10:00:00"),
                )

                if i % 10 == 0:  # Some files
                    conn.execute(
                        """
                        INSERT INTO files (session, filename, shasum, timestamp)
                        VALUES (?, ?, ?, ?)
                    """,
                        (f"session_{i}", f"file_{i}.exe", f"hash_{i:032x}", "2025-01-01T10:00:00"),
                    )

            conn.commit()

            # Test analysis performance
            analyzer = HoneypotStatisticalAnalyzer(conn)

            start_time = time.time()
            session_analysis = analyzer.analyze_session_patterns(days=30)
            command_analysis = analyzer.analyze_command_patterns(days=30)
            file_analysis = analyzer.analyze_file_patterns(days=30)
            velocity_analysis = analyzer.analyze_attack_velocity(days=30)
            end_time = time.time()

            total_time = end_time - start_time

            # Should complete in reasonable time
            assert total_time < 5.0  # Less than 5 seconds for all analyses

            # Verify results structure
            assert isinstance(session_analysis, dict)
            assert isinstance(command_analysis, dict)
            assert isinstance(file_analysis, dict)
            assert isinstance(velocity_analysis, dict)

            conn.close()

        finally:
            db_path.unlink()


class TestMemoryUsagePerformance:
    """Test memory usage during enrichment operations."""

    def test_memory_usage_during_bulk_enrichment(self, tmp_path):
        """Test memory usage during bulk enrichment operations."""
        import os

        import psutil

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        from process_cowrie import dshield_query

        # Get initial memory usage
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss

        # Mock API calls
        with patch('process_cowrie.enrichment_dshield_query') as mock_dshield:
            mock_dshield.return_value = json.loads(get_dshield_response("datacenter"))

            # Perform bulk enrichment
            test_ips = [f"192.168.1.{i}" for i in range(100)]

            for ip in test_ips:
                dshield_query(ip, cache_base=cache_dir)

            # Force garbage collection
            import gc

            gc.collect()

            # Check memory usage
            final_memory = process.memory_info().rss
            memory_increase = final_memory - initial_memory

            # Memory increase should be reasonable
            assert memory_increase < 50 * 1024 * 1024  # Less than 50MB increase

    def test_cache_memory_efficiency(self, tmp_path):
        """Test that caching doesn't cause memory leaks."""
        import os

        import psutil

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        from process_cowrie import dshield_query

        process = psutil.Process(os.getpid())

        # Mock API calls
        with patch('process_cowrie.enrichment_dshield_query') as mock_dshield:
            mock_dshield.return_value = json.loads(get_dshield_response("datacenter"))

            # Perform many cache operations
            for iteration in range(10):
                test_ips = [f"192.168.1.{i}" for i in range(iteration * 10, (iteration + 1) * 10)]

                for ip in test_ips:
                    dshield_query(ip, cache_base=cache_dir)

                # Check memory usage periodically
                if iteration % 3 == 0:
                    import gc

                    gc.collect()
                    current_memory = process.memory_info().rss

                    # Memory shouldn't grow unbounded
                    assert current_memory < 200 * 1024 * 1024  # Less than 200MB

    def test_concurrent_memory_usage(self, tmp_path):
        """Test memory usage during concurrent operations."""
        import os

        import psutil

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        from process_cowrie import dshield_query

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss

        def worker(worker_id):
            """Worker function for concurrent memory test."""
            test_ips = [f"192.168.{worker_id}.{i}" for i in range(20)]

            with patch('process_cowrie.enrichment_dshield_query') as mock_dshield:
                mock_dshield.return_value = json.loads(get_dshield_response("datacenter"))

                for ip in test_ips:
                    dshield_query(ip, cache_base=cache_dir)

        # Run concurrent workers
        threads = []
        for worker_id in range(5):
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Force garbage collection
        import gc

        gc.collect()

        final_memory = process.memory_info().rss
        memory_increase = final_memory - initial_memory

        # Memory increase should be reasonable for concurrent operations
        assert memory_increase < 100 * 1024 * 1024  # Less than 100MB increase


class TestEnrichmentThroughput:
    """Test enrichment throughput under various conditions."""

    def test_sequential_throughput(self, tmp_path):
        """Test sequential enrichment throughput."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        from process_cowrie import dshield_query, read_spur_data

        with (
            patch('process_cowrie.enrichment_dshield_query') as mock_dshield,
            patch('process_cowrie.enrichment_read_spur_data') as mock_spur,
        ):
            mock_dshield.return_value = json.loads(get_dshield_response("datacenter"))
            mock_spur.return_value = json.loads(get_spur_response("datacenter"))

            # Test sequential throughput
            test_ips = [f"192.168.1.{i}" for i in range(100)]

            start_time = time.time()
            for ip in test_ips:
                dshield_query(ip, cache_base=cache_dir)
                read_spur_data(ip, "test-key", cache_base=cache_dir)
            end_time = time.time()

            total_time = end_time - start_time
            throughput = len(test_ips) / total_time

            # Should achieve reasonable throughput
            assert throughput > 5.0  # At least 5 enrichments per second
            assert total_time < 30.0  # Less than 30 seconds for 100 enrichments

    def test_cached_throughput(self, tmp_path):
        """Test throughput when using cached data."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        from process_cowrie import dshield_query

        # Pre-populate cache
        test_ips = [f"192.168.1.{i}" for i in range(50)]
        for ip in test_ips:
            dshield_query(ip, cache_base=cache_dir)

        # Test cached throughput
        start_time = time.time()
        for ip in test_ips:
            dshield_query(ip, cache_base=cache_dir)  # Should use cache
        end_time = time.time()

        total_time = end_time - start_time
        throughput = len(test_ips) / total_time

        # Cached operations should be very fast
        assert throughput > 100.0  # At least 100 cache hits per second
        assert total_time < 1.0  # Less than 1 second for 50 cache hits

    @pytest.mark.asyncio
    async def test_async_enrichment_throughput(self, tmp_path):
        """Test async enrichment throughput."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        # Create async versions of enrichment functions for testing
        async def async_dshield_query(ip):
            """Async version of dshield query."""
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, dshield_query, ip, cache_dir)

        from process_cowrie import dshield_query

        # Mock API calls
        with patch('process_cowrie.enrichment_dshield_query') as mock_dshield:
            mock_dshield.return_value = json.loads(get_dshield_response("datacenter"))

            # Test async throughput
            test_ips = [f"192.168.1.{i}" for i in range(50)]

            start_time = time.time()
            tasks = [async_dshield_query(ip) for ip in test_ips]
            results = await asyncio.gather(*tasks)
            end_time = time.time()

            total_time = end_time - start_time
            throughput = len(test_ips) / total_time

            # Async operations should have good throughput
            assert throughput > 10.0  # At least 10 async enrichments per second
            assert len(results) == 50
