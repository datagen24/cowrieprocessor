"""Performance tests for files table backfill functionality."""

from __future__ import annotations

import json
import pytest
import time
from datetime import datetime
from pathlib import Path

from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.db.migrations import apply_migrations
from cowrieprocessor.loader.bulk import BulkLoader, BulkLoaderConfig
from cowrieprocessor.settings import load_database_settings


@pytest.fixture
def large_event_dataset(tmp_path):
    """Create a large dataset of file download events for performance testing."""
    events = []
    
    # Generate 1000 file download events
    for i in range(1000):
        event = {
            "eventid": "cowrie.session.file_download",
            "session": f"session{i:06d}",
            "timestamp": f"2025-01-27T{i%24:02d}:{i%60:02d}:00Z",
            "src_ip": f"192.168.1.{(i % 254) + 1}",
            "shasum": f"{i:064x}",  # Generate unique hash
            "filename": f"file_{i}.txt",
            "size": 1024 + (i % 10000),
            "url": f"http://example.com/file_{i}.txt",
        }
        events.append(event)
    
    # Create temporary JSON file
    json_file = tmp_path / "large_events.json"
    with open(json_file, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
    
    return json_file, events


@pytest.fixture
def performance_engine(tmp_path):
    """Create database engine optimized for performance testing."""
    db_path = tmp_path / "perf_test.db"
    engine = create_engine_from_settings(load_database_settings())
    # Override with test database path
    from sqlalchemy import create_engine
    engine = create_engine(f"sqlite:///{db_path}")
    apply_migrations(engine)
    return engine


class TestFilesBackfillPerformance:
    """Test performance characteristics of files table backfill."""

    def test_bulk_loader_performance(self, performance_engine, large_event_dataset):
        """Test bulk loader performance with large dataset."""
        json_file, events = large_event_dataset
        
        # Create bulk loader with optimized config
        config = BulkLoaderConfig(
            batch_size=500,  # Larger batch size for performance
            telemetry_interval=100,
        )
        loader = BulkLoader(performance_engine, config)
        
        # Measure processing time
        start_time = time.perf_counter()
        metrics = loader.load_paths([json_file])
        end_time = time.perf_counter()
        
        processing_time = end_time - start_time
        events_per_second = len(events) / processing_time
        
        # Verify all events were processed
        assert metrics.events_read == len(events)
        assert metrics.events_invalid == 0
        
        # Verify all files were inserted
        with performance_engine.connect() as conn:
            from sqlalchemy import text
            result = conn.execute(text("SELECT COUNT(*) FROM files"))
            file_count = result.scalar_one()
            assert file_count == len(events)
        
        # Performance assertions
        assert processing_time < 30.0, f"Processing took {processing_time:.2f}s, expected < 30s"
        assert events_per_second > 50, f"Processing rate {events_per_second:.1f} events/sec, expected > 50/sec"
        
        print(f"Performance results:")
        print(f"  Events processed: {len(events)}")
        print(f"  Processing time: {processing_time:.2f}s")
        print(f"  Events per second: {events_per_second:.1f}")
        print(f"  Batches committed: {metrics.batches_committed}")

    def test_memory_usage_stability(self, performance_engine, large_event_dataset):
        """Test that memory usage remains stable during large backfill."""
        import psutil
        import os
        
        json_file, events = large_event_dataset
        
        # Get initial memory usage
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Create bulk loader
        config = BulkLoaderConfig(batch_size=100)  # Smaller batches for memory testing
        loader = BulkLoader(performance_engine, config)
        
        # Process events
        loader.load_paths([json_file])
        
        # Get final memory usage
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory
        
        # Memory increase should be reasonable (less than 100MB for 1000 events)
        assert memory_increase < 100, f"Memory increased by {memory_increase:.1f}MB, expected < 100MB"
        
        print(f"Memory usage:")
        print(f"  Initial: {initial_memory:.1f}MB")
        print(f"  Final: {final_memory:.1f}MB")
        print(f"  Increase: {memory_increase:.1f}MB")

    def test_batch_size_optimization(self, performance_engine, large_event_dataset):
        """Test different batch sizes for optimal performance."""
        json_file, events = large_event_dataset
        
        batch_sizes = [50, 100, 500, 1000]
        results = []
        
        for batch_size in batch_sizes:
            # Create fresh engine for each test
            from sqlalchemy import create_engine
            test_engine = create_engine("sqlite:///:memory:")
            apply_migrations(test_engine)
            
            config = BulkLoaderConfig(batch_size=batch_size)
            loader = BulkLoader(test_engine, config)
            
            # Measure processing time
            start_time = time.perf_counter()
            metrics = loader.load_paths([json_file])
            end_time = time.perf_counter()
            
            processing_time = end_time - start_time
            events_per_second = len(events) / processing_time
            
            results.append({
                "batch_size": batch_size,
                "processing_time": processing_time,
                "events_per_second": events_per_second,
                "batches_committed": metrics.batches_committed,
            })
        
        # Find optimal batch size
        best_result = max(results, key=lambda x: x["events_per_second"])
        
        print(f"Batch size optimization results:")
        for result in results:
            print(f"  Batch size {result['batch_size']}: {result['events_per_second']:.1f} events/sec")
        print(f"  Optimal batch size: {best_result['batch_size']}")
        
        # Verify that larger batch sizes generally perform better
        assert best_result["batch_size"] >= 100, "Larger batch sizes should perform better"

    def test_concurrent_access_during_backfill(self, performance_engine, large_event_dataset):
        """Test that database remains accessible during backfill."""
        import threading
        import queue
        
        json_file, events = large_event_dataset
        
        # Results queue for concurrent queries
        results_queue = queue.Queue()
        
        def query_worker():
            """Worker that performs queries during backfill."""
            try:
                with performance_engine.connect() as conn:
                    from sqlalchemy import text
                    # Perform some queries
                    result = conn.execute(text("SELECT COUNT(*) FROM raw_events"))
                    count = result.scalar_one()
                    results_queue.put(("raw_events_count", count))
                    
                    result = conn.execute(text("SELECT COUNT(*) FROM files"))
                    count = result.scalar_one()
                    results_queue.put(("files_count", count))
                    
            except Exception as e:
                results_queue.put(("error", str(e)))
        
        # Start backfill in background
        config = BulkLoaderConfig(batch_size=200)
        loader = BulkLoader(performance_engine, config)
        
        # Start query worker thread
        query_thread = threading.Thread(target=query_worker)
        query_thread.start()
        
        # Start backfill
        start_time = time.perf_counter()
        metrics = loader.load_paths([json_file])
        end_time = time.perf_counter()
        
        # Wait for query worker to complete
        query_thread.join(timeout=5.0)
        
        # Check results
        assert not results_queue.empty(), "Query worker should have produced results"
        
        # Process results
        errors = []
        while not results_queue.empty():
            result_type, value = results_queue.get()
            if result_type == "error":
                errors.append(value)
            else:
                print(f"Concurrent query result: {result_type} = {value}")
        
        # Should not have any errors
        assert len(errors) == 0, f"Concurrent queries failed: {errors}"
        
        print(f"Backfill completed in {end_time - start_time:.2f}s with {metrics.events_read} events")

    def test_large_file_metadata_handling(self, performance_engine, tmp_path):
        """Test handling of files with large metadata."""
        # Create events with large filenames and URLs
        events = []
        
        for i in range(100):
            # Create very long filename and URL
            long_filename = f"{'a' * 500}_{i}.txt"  # 500+ chars
            long_url = f"http://example.com/{'b' * 500}/file_{i}.txt"  # 500+ chars
            
            event = {
                "eventid": "cowrie.session.file_download",
                "session": f"session{i:06d}",
                "timestamp": f"2025-01-27T{i%24:02d}:{i%60:02d}:00Z",
                "src_ip": f"192.168.1.{(i % 254) + 1}",
                "shasum": f"{i:064x}",
                "filename": long_filename,
                "size": 1024 + (i % 10000),
                "url": long_url,
            }
            events.append(event)
        
        # Create temporary JSON file
        json_file = tmp_path / "large_metadata_events.json"
        with open(json_file, "w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")
        
        # Process with bulk loader
        config = BulkLoaderConfig(batch_size=50)
        loader = BulkLoader(performance_engine, config)
        
        start_time = time.perf_counter()
        metrics = loader.load_paths([json_file])
        end_time = time.perf_counter()
        
        # Verify processing completed successfully
        assert metrics.events_read == len(events)
        assert metrics.events_invalid == 0
        
        # Verify metadata was properly truncated
        with performance_engine.connect() as conn:
            from sqlalchemy import text
            result = conn.execute(text("SELECT filename, download_url FROM files LIMIT 1"))
            row = result.fetchone()
            
            # Filenames should be truncated to 512 chars
            assert len(row[0]) <= 512
            # URLs should be truncated to 1024 chars
            assert len(row[1]) <= 1024
        
        processing_time = end_time - start_time
        print(f"Large metadata processing: {len(events)} events in {processing_time:.2f}s")
        assert processing_time < 10.0, "Large metadata processing should complete quickly"
