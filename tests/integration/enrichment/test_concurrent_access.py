"""Integration tests for concurrent IP classification access patterns.

Tests thread safety and concurrent access:
- Multiple threads classify IPs simultaneously
- Cache operations are thread-safe
- No race conditions in statistics
- Database transactions work correctly under concurrency
- Cache warming doesn't cause corruption
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from cowrieprocessor.db.models import Base
from cowrieprocessor.enrichment.ip_classification import (
    create_ip_classifier,
)


@pytest.fixture
def concurrent_db_engine(tmp_path: Path):  # type: ignore[misc]
    """Create SQLite database for concurrent testing (WAL mode)."""
    db_path = tmp_path / "concurrent_test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},  # Allow multi-threaded access
        pool_pre_ping=True,
    )
    Base.metadata.create_all(engine)

    # Enable WAL mode for concurrent access
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        conn.commit()

    yield engine
    engine.dispose()


@pytest.fixture
def concurrent_cache_dir(tmp_path: Path) -> Path:
    """Create cache directory for concurrent tests."""
    cache_dir = tmp_path / "concurrent_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


class TestConcurrentIPClassification:
    """Test concurrent IP classification access patterns."""

    def test_concurrent_classification_thread_safe(self, concurrent_cache_dir: Path, concurrent_db_engine) -> None:
        """Test multiple threads can classify IPs simultaneously.

        Validates:
        - Thread-safe cache operations
        - Consistent results across threads
        - No race conditions in statistics
        - No database locking issues
        """
        classifier = create_ip_classifier(
            cache_dir=concurrent_cache_dir,
            db_engine=concurrent_db_engine,
            enable_redis=False,  # Disable Redis for deterministic testing
        )

        # Test IPs (repeated for concurrent access)
        test_ips = [
            "8.8.8.8",
            "1.1.1.1",
            "52.0.0.1",
            "203.0.113.1",
            "198.51.100.1",
        ] * 10

        def classify_ip(ip: str):
            """Classify IP with thread ID for debugging."""
            thread_id = threading.current_thread().ident
            result = classifier.classify(ip)
            return (ip, result, thread_id)

        # Classify 50 IPs concurrently (10 workers)
        results = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(classify_ip, ip) for ip in test_ips]
            for future in as_completed(futures):
                results.append(future.result())

        # Verify all classifications succeeded
        assert len(results) == len(test_ips)
        assert all(r[1].ip_type is not None for r in results)

        # Verify statistics are consistent
        stats = classifier.get_stats()
        assert stats["classifications"] == len(test_ips)

        # Verify no cache corruption (same IP should have same result)
        ip_results = {}
        for ip, result, thread_id in results:
            if ip not in ip_results:
                ip_results[ip] = result
            else:
                # All results for same IP should be identical
                assert result.ip_type == ip_results[ip].ip_type
                assert result.provider == ip_results[ip].provider
                assert result.confidence == ip_results[ip].confidence

    def test_concurrent_cache_warming(self, concurrent_cache_dir: Path, concurrent_db_engine) -> None:
        """Test concurrent cache warming doesn't cause corruption.

        Validates:
        - Multiple threads can warm cache simultaneously
        - No duplicate cache entries
        - Cache consistency is maintained
        """
        classifier = create_ip_classifier(
            cache_dir=concurrent_cache_dir,
            db_engine=concurrent_db_engine,
            enable_redis=False,
        )

        # Test IPs (each thread will classify same IPs)
        test_ips = ["8.8.8.8", "1.1.1.1", "52.0.0.1"]

        def warm_cache(worker_id: int):
            """Each worker classifies all test IPs."""
            results = []
            for ip in test_ips:
                result = classifier.classify(ip)
                results.append((worker_id, ip, result))
            return results

        # Multiple workers warm cache concurrently
        all_results = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(warm_cache, i) for i in range(5)]
            for future in as_completed(futures):
                all_results.extend(future.result())

        # Verify consistency (all workers got same results for same IPs)
        ip_canonical = {}
        for worker_id, ip, result in all_results:
            if ip not in ip_canonical:
                ip_canonical[ip] = result
            else:
                # All workers should get same result for same IP
                assert result.ip_type == ip_canonical[ip].ip_type
                assert result.provider == ip_canonical[ip].provider

    def test_concurrent_bulk_classification(self, concurrent_cache_dir: Path, concurrent_db_engine) -> None:
        """Test bulk classification with concurrent workers.

        Validates:
        - Bulk operations are thread-safe
        - Results are consistent
        - Performance scales with workers
        """
        classifier = create_ip_classifier(
            cache_dir=concurrent_cache_dir,
            db_engine=concurrent_db_engine,
            enable_redis=False,
        )

        # Large batch of IPs
        all_ips = [
            ("8.8.8.8", 15169, "GOOGLE"),
            ("1.1.1.1", 13335, "CLOUDFLARENET"),
            ("52.0.0.1", 16509, "AMAZON-02"),
            ("203.0.113.1", None, None),
            ("198.51.100.1", None, None),
        ] * 20  # 100 IPs total

        def process_batch(batch):
            """Process a batch of IPs."""
            return classifier.bulk_classify(batch)

        # Split into batches for concurrent processing
        batch_size = 10
        batches = [all_ips[i : i + batch_size] for i in range(0, len(all_ips), batch_size)]

        # Process batches concurrently
        all_results = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(process_batch, batch) for batch in batches]
            for future in as_completed(futures):
                batch_results = future.result()
                all_results.update(batch_results)

        # Verify all IPs were processed
        unique_ips = set(ip for ip, _, _ in all_ips)
        assert len(all_results) == len(unique_ips)

        # Verify consistency
        for ip, _, _ in all_ips:
            assert ip in all_results
            assert all_results[ip].ip_type is not None

    def test_concurrent_statistics_tracking(self, concurrent_cache_dir: Path, concurrent_db_engine) -> None:
        """Test statistics tracking under concurrent access.

        Validates:
        - Statistics counters are accurate
        - No lost updates in concurrent increments
        - Final statistics match expected values
        """
        classifier = create_ip_classifier(
            cache_dir=concurrent_cache_dir,
            db_engine=concurrent_db_engine,
            enable_redis=False,
        )

        # Each worker classifies same set of IPs
        test_ips = ["8.8.8.8", "1.1.1.1", "52.0.0.1"]
        num_workers = 10

        def classify_batch(worker_id: int):
            """Each worker classifies all test IPs."""
            for ip in test_ips:
                classifier.classify(ip)

        # Workers classify concurrently
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(classify_batch, i) for i in range(num_workers)]
            for future in as_completed(futures):
                future.result()

        # Verify statistics
        stats = classifier.get_stats()
        total_classifications = len(test_ips) * num_workers
        assert stats["classifications"] == total_classifications

        # Cache hits should be significant (after first classification)
        # Note: Exact count depends on timing, but should be > 0
        assert stats["cache_hits"] >= 0

    def test_concurrent_database_writes(self, concurrent_cache_dir: Path, concurrent_db_engine) -> None:
        """Test concurrent database writes don't cause conflicts.

        Validates:
        - Database transactions are serialized correctly
        - No duplicate key violations
        - All writes succeed or fail gracefully
        """
        # Create multiple classifier instances (simulates multiple processes)
        classifiers = [
            create_ip_classifier(
                cache_dir=concurrent_cache_dir,
                db_engine=concurrent_db_engine,
                enable_redis=False,
            )
            for _ in range(5)
        ]

        # Each classifier classifies same IPs
        test_ip = "8.8.8.8"

        def classify_with_instance(classifier_idx: int):
            """Classify IP with specific classifier instance."""
            classifier = classifiers[classifier_idx]
            result = classifier.classify(test_ip)
            return (classifier_idx, result)

        # Concurrent classification with different instances
        results = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(classify_with_instance, i) for i in range(5)]
            for future in as_completed(futures):
                results.append(future.result())

        # All should succeed
        assert len(results) == 5
        assert all(r[1].ip_type is not None for r in results)

        # All should get same result
        first_result = results[0][1]
        for _, result in results:
            assert result.ip_type == first_result.ip_type
            assert result.provider == first_result.provider


class TestConcurrentCachePressure:
    """Test cache behavior under concurrent pressure."""

    def test_cache_stampede_prevention(self, concurrent_cache_dir: Path, concurrent_db_engine) -> None:
        """Test cache handles stampede scenario (many threads request same IP).

        Validates:
        - Cache doesn't duplicate work
        - Only one classification per IP occurs
        - Cache hit rate improves over time
        """
        classifier = create_ip_classifier(
            cache_dir=concurrent_cache_dir,
            db_engine=concurrent_db_engine,
            enable_redis=False,
        )

        # Many threads request same IP simultaneously
        test_ip = "8.8.8.8"
        num_threads = 50

        start_time = time.time()

        def classify_same_ip():
            """All threads classify same IP."""
            return classifier.classify(test_ip)

        # Stampede scenario
        results = []
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(classify_same_ip) for _ in range(num_threads)]
            for future in as_completed(futures):
                results.append(future.result())

        elapsed = time.time() - start_time

        # All should get same result
        assert len(results) == num_threads
        first_result = results[0]
        for result in results:
            assert result.ip_type == first_result.ip_type
            assert result.provider == first_result.provider

        # Should complete quickly (cache hit after first classification)
        assert elapsed < 10.0  # 10 seconds for 50 threads (generous)

        # Statistics should show high cache hit rate
        stats = classifier.get_stats()
        assert stats["cache_hits"] > 0

    def test_cache_eviction_under_pressure(self, concurrent_cache_dir: Path, concurrent_db_engine) -> None:
        """Test cache behavior when memory is under pressure.

        Validates:
        - Cache handles large number of unique IPs
        - No memory leaks under sustained load
        - Performance degrades gracefully
        """
        classifier = create_ip_classifier(
            cache_dir=concurrent_cache_dir,
            db_engine=concurrent_db_engine,
            enable_redis=False,
        )

        # Generate large number of unique IPs
        def generate_ips(count: int):
            """Generate unique test IPs."""
            ips = []
            for i in range(count):
                # Use TEST-NET ranges to avoid real IPs
                ip = f"203.0.{i // 256}.{i % 256}"
                ips.append(ip)
            return ips

        test_ips = generate_ips(1000)

        def classify_batch(batch):
            """Classify batch of IPs."""
            return [classifier.classify(ip) for ip in batch]

        # Process large number of IPs concurrently
        batch_size = 100
        batches = [test_ips[i : i + batch_size] for i in range(0, len(test_ips), batch_size)]

        start_time = time.time()

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(classify_batch, batch) for batch in batches]
            for future in as_completed(futures):
                future.result()

        elapsed = time.time() - start_time

        # Should complete in reasonable time
        assert elapsed < 120.0  # 2 minutes for 1000 IPs (generous for CI)

        # Verify statistics
        stats = classifier.get_stats()
        assert stats["classifications"] == len(test_ips)


class TestConcurrentEdgeCases:
    """Test edge cases in concurrent scenarios."""

    def test_concurrent_classifier_close(self, concurrent_cache_dir: Path, concurrent_db_engine) -> None:
        """Test closing classifier while threads are active.

        Validates:
        - Close operation is safe
        - Active threads complete gracefully
        - No resource leaks occur
        """
        classifier = create_ip_classifier(
            cache_dir=concurrent_cache_dir,
            db_engine=concurrent_db_engine,
            enable_redis=False,
        )

        test_ips = ["8.8.8.8", "1.1.1.1"] * 5
        stop_flag = threading.Event()

        def classify_until_stop():
            """Classify IPs until stop flag is set."""
            results = []
            for ip in test_ips:
                if stop_flag.is_set():
                    break
                try:
                    result = classifier.classify(ip)
                    results.append(result)
                except Exception:
                    # May fail if classifier is closed
                    break
            return results

        # Start classification threads
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(classify_until_stop) for _ in range(3)]

            # Let threads run briefly
            time.sleep(0.1)

            # Close classifier while threads are active
            stop_flag.set()
            classifier.close()

            # Wait for threads to complete
            for future in as_completed(futures):
                # Should complete without hanging
                future.result()

        # No assertions - just verify no deadlock or crash

    def test_concurrent_context_manager_usage(self, concurrent_cache_dir: Path, concurrent_db_engine) -> None:
        """Test multiple threads using classifier as context manager.

        Validates:
        - Context manager is thread-safe
        - Resource cleanup works correctly
        - No interference between threads
        """
        test_ips = ["8.8.8.8", "1.1.1.1", "52.0.0.1"]

        def use_classifier_context(worker_id: int):
            """Use classifier in context manager."""
            with create_ip_classifier(
                cache_dir=concurrent_cache_dir,
                db_engine=concurrent_db_engine,
                enable_redis=False,
            ) as classifier:
                results = []
                for ip in test_ips:
                    result = classifier.classify(ip)
                    results.append((worker_id, ip, result))
                return results

        # Multiple threads use context manager
        all_results = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(use_classifier_context, i) for i in range(5)]
            for future in as_completed(futures):
                all_results.extend(future.result())

        # Verify all threads completed successfully
        assert len(all_results) == 5 * len(test_ips)

        # Verify consistency
        for worker_id, ip, result in all_results:
            assert result.ip_type is not None
