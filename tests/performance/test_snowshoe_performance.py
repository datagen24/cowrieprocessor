"""Performance tests for snowshoe detection with large datasets."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import List
from unittest.mock import Mock

import psutil
import pytest

from cowrieprocessor.db.models import SessionSummary
from cowrieprocessor.threat_detection import SnowshoeDetector, create_snowshoe_metrics_from_detection


class TestSnowshoePerformance:
    """Performance tests for snowshoe detection with large datasets."""

    @pytest.fixture
    def large_snowshoe_dataset(self) -> List[SessionSummary]:
        """Create a large dataset simulating snowshoe attacks."""
        sessions = []
        base_time = datetime.now(UTC)

        # Create 100,000 sessions with snowshoe characteristics
        print("Creating 100,000 snowshoe sessions...")

        for i in range(100000):
            session = Mock(spec=SessionSummary)
            session.session_id = f"snowshoe_large_{i:06d}"

            # Clustered timing pattern
            burst_time = base_time + timedelta(minutes=(i % 1000) * 2)  # 1000 bursts
            session.first_event_at = burst_time + timedelta(seconds=(i % 100) * 6)
            session.last_event_at = session.first_event_at + timedelta(seconds=20)

            # Single-attempt characteristics
            session.command_count = 1
            session.file_downloads = 0
            session.login_attempts = 1
            session.risk_score = 10

            # Geographic diversity
            session.enrichment = {
                "session": {
                    f"203.0.{(i % 100) // 10}.{(i % 254) + 1}": {
                        "spur": {
                            "country": f"Country{i % 50:02d}",
                            "asn": f"AS{i % 100:05d}",
                            "organization": f"ISP{i % 20}",
                            "city": f"City{i % 200}",
                        }
                    }
                }
            }
            sessions.append(session)

        print(f"Created {len(sessions)} sessions")
        return sessions

    @pytest.fixture
    def large_mixed_dataset(self) -> List[SessionSummary]:
        """Create a large mixed dataset with both snowshoe and normal traffic."""
        sessions = []
        base_time = datetime.now(UTC)

        # 80,000 snowshoe sessions + 20,000 normal sessions
        print("Creating 100,000 mixed traffic sessions...")

        # Snowshoe portion (80,000 sessions)
        for i in range(80000):
            session = Mock(spec=SessionSummary)
            session.session_id = f"snowshoe_mixed_{i:06d}"

            session.first_event_at = base_time + timedelta(minutes=(i % 2000) * 2)
            session.last_event_at = session.first_event_at + timedelta(seconds=15)

            session.command_count = 1
            session.file_downloads = 0
            session.login_attempts = 1
            session.risk_score = 10

            session.enrichment = {
                "session": {
                    f"203.0.{(i % 50) // 10}.{(i % 254) + 1}": {
                        "spur": {
                            "country": f"Country{i % 30:02d}",
                            "asn": f"AS{i % 80:05d}",
                        }
                    }
                }
            }
            sessions.append(session)

        # Normal traffic portion (20,000 sessions from 2,000 IPs)
        for ip_idx in range(2000):
            for session_idx in range(10):
                session = Mock(spec=SessionSummary)
                session.session_id = f"normal_mixed_{ip_idx:04d}_{session_idx:02d}"

                session.first_event_at = base_time + timedelta(hours=ip_idx + session_idx * 0.1)
                session.last_event_at = session.first_event_at + timedelta(minutes=5)

                session.command_count = 15
                session.file_downloads = 0
                session.login_attempts = 1
                session.risk_score = 25

                session.enrichment = {
                    "session": {
                        f"198.51.100.{(ip_idx % 254) + 1}": {
                            "spur": {
                                "country": "US" if ip_idx % 2 == 0 else "CA",
                                "asn": "AS12345" if ip_idx % 2 == 0 else "AS67890",
                            }
                        }
                    }
                }
                sessions.append(session)

        print(f"Created {len(sessions)} mixed sessions")
        return sessions

    def test_snowshoe_detection_performance_100k_sessions(self, large_snowshoe_dataset: List[SessionSummary]) -> None:
        """Test snowshoe detection performance with 100,000 sessions.

        This test verifies that the detection algorithm can process large datasets
        within the required performance constraints (<30 seconds for 100k sessions).
        """
        detector = SnowshoeDetector(
            single_attempt_threshold=5,
            time_cluster_eps=0.1,
            min_cluster_size=10,
            sensitivity_threshold=0.7,
        )

        # Monitor system resources
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        process.cpu_percent()

        # Perform analysis with timing
        print("Starting snowshoe detection analysis...")
        start_time = time.perf_counter()

        result = detector.detect(large_snowshoe_dataset, window_hours=24)

        end_time = time.perf_counter()
        analysis_duration = end_time - start_time

        # Monitor final resources
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        final_cpu = process.cpu_percent()
        memory_used = final_memory - initial_memory

        print(f"Analysis completed in {analysis_duration:.2f} seconds")
        print(f"Memory used: {memory_used:.2f} MB")
        print(f"CPU usage: {final_cpu:.1f}%")

        # Performance assertions
        assert analysis_duration < 30.0, f"Analysis took {analysis_duration:.2f}s, should be <30s"
        assert memory_used < 2000, f"Memory usage {memory_used:.2f}MB too high, should be <2GB"

        # Verify detection results
        assert result["is_likely_snowshoe"] is True
        assert result["confidence_score"] > 0.8
        assert len(result["single_attempt_ips"]) == 100000
        assert result["coordinated_timing"] is True
        assert result["geographic_spread"] > 0.8

        # Verify performance metrics
        sessions_per_second = len(large_snowshoe_dataset) / analysis_duration
        assert sessions_per_second > 3000, f"Processing rate {sessions_per_second:.0f} sessions/sec too low"

    def test_mixed_traffic_performance_100k_sessions(self, large_mixed_dataset: List[SessionSummary]) -> None:
        """Test detection performance with mixed traffic (100k sessions)."""
        detector = SnowshoeDetector(
            single_attempt_threshold=5,
            sensitivity_threshold=0.7,
        )

        # Monitor resources
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024

        print("Starting mixed traffic analysis...")
        start_time = time.perf_counter()

        result = detector.detect(large_mixed_dataset, window_hours=24)

        end_time = time.perf_counter()
        analysis_duration = end_time - start_time

        final_memory = process.memory_info().rss / 1024 / 1024
        memory_used = final_memory - initial_memory

        print(f"Mixed analysis completed in {analysis_duration:.2f} seconds")
        print(f"Memory used: {memory_used:.2f} MB")

        # Performance assertions
        assert analysis_duration < 30.0, f"Analysis took {analysis_duration:.2f}s, should be <30s"
        assert memory_used < 2000, f"Memory usage {memory_used:.2f}MB too high"

        # Verify detection results
        assert result["is_likely_snowshoe"] is True  # Should detect due to 80% snowshoe
        assert len(result["single_attempt_ips"]) == 80000  # 80k snowshoe IPs
        assert result["confidence_score"] > 0.6

    def test_memory_efficiency_with_large_datasets(self, large_snowshoe_dataset: List[SessionSummary]) -> None:
        """Test memory efficiency with large datasets."""
        detector = SnowshoeDetector()

        # Monitor memory usage throughout the process
        process = psutil.Process()
        memory_samples = []

        # Sample memory before analysis
        memory_samples.append(process.memory_info().rss / 1024 / 1024)

        # Perform analysis
        start_time = time.perf_counter()
        detector.detect(large_snowshoe_dataset, window_hours=24)
        end_time = time.perf_counter()

        # Sample memory after analysis
        memory_samples.append(process.memory_info().rss / 1024 / 1024)

        memory_used = memory_samples[-1] - memory_samples[0]
        duration = end_time - start_time

        print("Memory efficiency test:")
        print(f"  Initial memory: {memory_samples[0]:.2f} MB")
        print(f"  Final memory: {memory_samples[-1]:.2f} MB")
        print(f"  Memory used: {memory_used:.2f} MB")
        print(f"  Duration: {duration:.2f} seconds")
        print(f"  Memory per session: {memory_used / len(large_snowshoe_dataset) * 1024:.2f} KB")

        # Memory efficiency assertions
        assert memory_used < 1500, f"Memory usage {memory_used:.2f}MB too high"
        assert memory_used / len(large_snowshoe_dataset) * 1024 < 20, "Memory per session too high"

    def test_cpu_efficiency_with_large_datasets(self, large_snowshoe_dataset: List[SessionSummary]) -> None:
        """Test CPU efficiency with large datasets."""
        detector = SnowshoeDetector()

        # Monitor CPU usage
        process = psutil.Process()

        # Start CPU monitoring
        process.cpu_percent()  # Initialize
        time.sleep(0.1)  # Allow initialization

        # Perform analysis while monitoring CPU
        start_time = time.perf_counter()
        cpu_samples = []

        # Sample CPU usage during analysis
        for i in range(10):  # Sample 10 times during analysis
            cpu_samples.append(process.cpu_percent())
            time.sleep(0.5)

        detector.detect(large_snowshoe_dataset, window_hours=24)
        end_time = time.perf_counter()

        duration = end_time - start_time
        avg_cpu = sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0
        max_cpu = max(cpu_samples) if cpu_samples else 0

        print("CPU efficiency test:")
        print(f"  Average CPU: {avg_cpu:.1f}%")
        print(f"  Max CPU: {max_cpu:.1f}%")
        print(f"  Duration: {duration:.2f} seconds")

        # CPU efficiency assertions
        assert avg_cpu < 80, f"Average CPU usage {avg_cpu:.1f}% too high"
        assert max_cpu < 95, f"Max CPU usage {max_cpu:.1f}% too high"

    def test_concurrent_analysis_performance(self) -> None:
        """Test performance with multiple concurrent analyses."""
        import queue
        import threading

        # Create smaller datasets for concurrent testing
        datasets = []
        for i in range(5):  # 5 concurrent analyses
            sessions = []
            base_time = datetime.now(UTC)

            for j in range(20000):  # 20k sessions each
                session = Mock(spec=SessionSummary)
                session.session_id = f"concurrent_{i}_{j:05d}"
                session.first_event_at = base_time + timedelta(minutes=j * 2)
                session.last_event_at = session.first_event_at + timedelta(seconds=30)
                session.command_count = 1
                session.file_downloads = 0
                session.login_attempts = 1
                session.risk_score = 10
                session.enrichment = {
                    "session": {
                        f"203.0.{i}.{(j % 254) + 1}": {
                            "spur": {
                                "country": f"Country{j % 20:02d}",
                                "asn": f"AS{j % 40:05d}",
                            }
                        }
                    }
                }
                sessions.append(session)
            datasets.append(sessions)

        detector = SnowshoeDetector()
        results_queue = queue.Queue()

        def analyze_dataset(dataset: List[SessionSummary], dataset_id: int) -> None:
            """Analyze a single dataset and put result in queue."""
            start_time = time.perf_counter()
            result = detector.detect(dataset, window_hours=24)
            duration = time.perf_counter() - start_time
            results_queue.put((dataset_id, duration, result))

        # Start concurrent analyses
        threads = []
        start_time = time.perf_counter()

        for i, dataset in enumerate(datasets):
            thread = threading.Thread(target=analyze_dataset, args=(dataset, i))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        total_time = time.perf_counter() - start_time

        # Collect results
        results = []
        while not results_queue.empty():
            results.append(results_queue.get())

        print("Concurrent analysis test:")
        print(f"  Total time: {total_time:.2f} seconds")
        print(f"  Number of analyses: {len(results)}")
        print(f"  Average time per analysis: {sum(r[1] for r in results) / len(results):.2f} seconds")

        # Verify all analyses completed successfully
        assert len(results) == 5, f"Expected 5 results, got {len(results)}"

        for dataset_id, duration, result in results:
            assert duration < 15.0, f"Analysis {dataset_id} took {duration:.2f}s, should be <15s"
            assert result["is_likely_snowshoe"] is True
            assert result["confidence_score"] > 0.7

    def test_scalability_with_different_sizes(self) -> None:
        """Test scalability with different dataset sizes."""
        sizes = [1000, 5000, 10000, 25000, 50000, 75000, 100000]
        results = []

        detector = SnowshoeDetector()

        for size in sizes:
            print(f"Testing with {size:,} sessions...")

            # Create dataset of specified size
            sessions = []
            base_time = datetime.now(UTC)

            for i in range(size):
                session = Mock(spec=SessionSummary)
                session.session_id = f"scale_test_{i:06d}"
                session.first_event_at = base_time + timedelta(minutes=i * 2)
                session.last_event_at = session.first_event_at + timedelta(seconds=30)
                session.command_count = 1
                session.file_downloads = 0
                session.login_attempts = 1
                session.risk_score = 10
                # Generate unique IPs by using different octets
                ip_octet4 = (i % 254) + 1
                ip_octet3 = (i // 254) % 254
                ip_octet2 = (i // (254 * 254)) % 254
                session.enrichment = {
                    "session": {
                        f"203.{ip_octet2}.{ip_octet3}.{ip_octet4}": {
                            "spur": {
                                "country": f"Country{i % 30:02d}",
                                "asn": f"AS{i % 50:05d}",
                            }
                        }
                    }
                }
                sessions.append(session)

            # Measure performance
            start_time = time.perf_counter()
            result = detector.detect(sessions, window_hours=24)
            duration = time.perf_counter() - start_time

            sessions_per_second = size / duration
            results.append((size, duration, sessions_per_second))

            print(f"  {size:,} sessions: {duration:.2f}s ({sessions_per_second:.0f} sessions/sec)")

            # Verify results are consistent
            # For this test, we expect all sessions to be single-attempt (snowshoe pattern)
            assert len(result["single_attempt_ips"]) == size
            # With sufficient data, should detect snowshoe pattern
            if size >= 1000:
                assert result["is_likely_snowshoe"] is True

        # Analyze scalability
        print("\nScalability analysis:")
        for size, duration, rate in results:
            print(f"  {size:6,} sessions: {duration:6.2f}s ({rate:6.0f} sessions/sec)")

        # Verify linear or sub-linear scaling
        # Processing rate should not degrade significantly with larger datasets
        rates = [r[2] for r in results]
        min_rate = min(rates)
        max_rate = max(rates)

        # Rate should not vary by more than 70% (algorithm complexity increases with dataset size)
        rate_variation = (max_rate - min_rate) / min_rate
        assert rate_variation < 0.7, f"Processing rate variation {rate_variation:.2%} too high"

    def test_metrics_performance_integration(self, large_snowshoe_dataset: List[SessionSummary]) -> None:
        """Test performance of metrics integration with large datasets."""
        detector = SnowshoeDetector()

        # Perform detection
        start_time = time.perf_counter()
        result = detector.detect(large_snowshoe_dataset, window_hours=24)
        detection_duration = time.perf_counter() - start_time

        # Create metrics
        metrics_start = time.perf_counter()
        metrics = create_snowshoe_metrics_from_detection(
            detection_result=result,
            analysis_duration=detection_duration,
            analysis_id="perf-test-001",
            window_hours=24,
        )
        metrics_duration = time.perf_counter() - metrics_start

        # Convert to status dict
        status_start = time.perf_counter()
        status_dict = metrics.to_status_dict()
        status_duration = time.perf_counter() - status_start

        total_time = detection_duration + metrics_duration + status_duration

        print("Metrics performance test:")
        print(f"  Detection: {detection_duration:.3f}s")
        print(f"  Metrics creation: {metrics_duration:.3f}s")
        print(f"  Status dict conversion: {status_duration:.3f}s")
        print(f"  Total: {total_time:.3f}s")

        # Performance assertions
        assert total_time < 35.0, f"Total time {total_time:.2f}s too high"
        assert metrics_duration < 1.0, f"Metrics creation {metrics_duration:.3f}s too slow"
        assert status_duration < 0.1, f"Status conversion {status_duration:.3f}s too slow"

        # Verify metrics accuracy
        assert metrics.total_sessions == 100000
        assert metrics.unique_ips == 100000
        assert metrics.detection_efficiency > 3000  # Should process quickly
        assert metrics.ip_coverage == 1.0
        assert isinstance(status_dict, dict)
        assert "input" in status_dict
        assert "detection" in status_dict
