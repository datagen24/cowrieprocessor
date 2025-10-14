"""Tests for enrichment telemetry integration."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from cowrieprocessor.enrichment.telemetry import EnrichmentMetrics, EnrichmentTelemetry


class TestEnrichmentTelemetry:
    """Test enrichment telemetry functionality."""

    def test_enrichment_metrics_initialization(self) -> None:
        """Test EnrichmentMetrics initialization."""
        metrics = EnrichmentMetrics()
        assert metrics.cache_hits == 0
        assert metrics.cache_misses == 0
        assert metrics.cache_stores == 0
        assert metrics.api_calls_total == 0
        assert metrics.sessions_enriched == 0
        assert metrics.files_enriched == 0

    def test_enrichment_telemetry_initialization(self) -> None:
        """Test EnrichmentTelemetry initialization."""
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry = EnrichmentTelemetry("test_phase", temp_dir)
            assert telemetry.metrics.cache_hits == 0
            assert telemetry.metrics.api_calls_total == 0

    def test_record_cache_stats(self) -> None:
        """Test recording cache statistics."""
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry = EnrichmentTelemetry("test_phase", temp_dir)
            
            cache_stats = {"hits": 10, "misses": 5, "stores": 8}
            telemetry.record_cache_stats(cache_stats)
            
            assert telemetry.metrics.cache_hits == 10
            assert telemetry.metrics.cache_misses == 5
            assert telemetry.metrics.cache_stores == 8

    def test_record_api_call(self) -> None:
        """Test recording API calls."""
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry = EnrichmentTelemetry("test_phase", temp_dir)
            
            # Record successful API call
            telemetry.record_api_call("dshield", True, 150.0)
            assert telemetry.metrics.api_calls_total == 1
            assert telemetry.metrics.api_calls_successful == 1
            assert telemetry.metrics.api_calls_failed == 0
            assert telemetry.metrics.dshield_calls == 1
            assert telemetry.metrics.enrichment_duration_ms == 150.0
            
            # Record failed API call
            telemetry.record_api_call("virustotal", False, 200.0)
            assert telemetry.metrics.api_calls_total == 2
            assert telemetry.metrics.api_calls_successful == 1
            assert telemetry.metrics.api_calls_failed == 1
            assert telemetry.metrics.virustotal_calls == 1
            assert telemetry.metrics.enrichment_duration_ms == 350.0

    def test_record_rate_limit_hit(self) -> None:
        """Test recording rate limit hits."""
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry = EnrichmentTelemetry("test_phase", temp_dir)
            
            telemetry.record_rate_limit_hit("dshield", 2.5)
            assert telemetry.metrics.rate_limit_hits == 1
            assert telemetry.metrics.rate_limit_delays == 2.5
            
            telemetry.record_rate_limit_hit("urlhaus", 1.0)
            assert telemetry.metrics.rate_limit_hits == 2
            assert telemetry.metrics.rate_limit_delays == 3.5

    def test_record_session_enrichment(self) -> None:
        """Test recording session enrichment."""
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry = EnrichmentTelemetry("test_phase", temp_dir)
            
            # Record successful enrichment
            telemetry.record_session_enrichment(True)
            assert telemetry.metrics.sessions_enriched == 1
            assert telemetry.metrics.enrichment_errors == 0
            assert telemetry.metrics.last_enrichment_time is not None
            
            # Record failed enrichment
            telemetry.record_session_enrichment(False)
            assert telemetry.metrics.sessions_enriched == 1
            assert telemetry.metrics.enrichment_errors == 1

    def test_record_file_enrichment(self) -> None:
        """Test recording file enrichment."""
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry = EnrichmentTelemetry("test_phase", temp_dir)
            
            # Record successful enrichment
            telemetry.record_file_enrichment(True)
            assert telemetry.metrics.files_enriched == 1
            assert telemetry.metrics.enrichment_errors == 0
            
            # Record failed enrichment
            telemetry.record_file_enrichment(False)
            assert telemetry.metrics.files_enriched == 1
            assert telemetry.metrics.enrichment_errors == 1

    def test_record_cache_error(self) -> None:
        """Test recording cache errors."""
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry = EnrichmentTelemetry("test_phase", temp_dir)
            
            telemetry.record_cache_error()
            assert telemetry.metrics.cache_errors == 1
            
            telemetry.record_cache_error()
            assert telemetry.metrics.cache_errors == 2

    def test_set_ingest_id(self) -> None:
        """Test setting ingest ID."""
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry = EnrichmentTelemetry("test_phase", temp_dir)
            
            telemetry.set_ingest_id("test_ingest_123")
            assert telemetry.metrics.ingest_id == "test_ingest_123"

    def test_get_cache_hit_rate(self) -> None:
        """Test cache hit rate calculation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry = EnrichmentTelemetry("test_phase", temp_dir)
            
            # No requests yet
            assert telemetry.get_cache_hit_rate() == 0.0
            
            # Record some cache stats
            telemetry.metrics.cache_hits = 8
            telemetry.metrics.cache_misses = 2
            assert telemetry.get_cache_hit_rate() == 80.0
            
            # All misses
            telemetry.metrics.cache_hits = 0
            telemetry.metrics.cache_misses = 5
            assert telemetry.get_cache_hit_rate() == 0.0

    def test_get_api_success_rate(self) -> None:
        """Test API success rate calculation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry = EnrichmentTelemetry("test_phase", temp_dir)
            
            # No API calls yet
            assert telemetry.get_api_success_rate() == 0.0
            
            # Record some API calls
            telemetry.metrics.api_calls_successful = 9
            telemetry.metrics.api_calls_failed = 1
            telemetry.metrics.api_calls_total = 10
            assert telemetry.get_api_success_rate() == 90.0
            
            # All failures
            telemetry.metrics.api_calls_successful = 0
            telemetry.metrics.api_calls_failed = 3
            telemetry.metrics.api_calls_total = 3
            assert telemetry.get_api_success_rate() == 0.0

    def test_get_enrichment_throughput(self) -> None:
        """Test enrichment throughput calculation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry = EnrichmentTelemetry("test_phase", temp_dir)
            
            # No enrichments yet
            assert telemetry.get_enrichment_throughput() == 0.0
            
            # Record some enrichments
            telemetry.metrics.sessions_enriched = 10
            # Simulate some time passing
            telemetry._start_time -= 10  # 10 seconds ago
            throughput = telemetry.get_enrichment_throughput()
            assert throughput > 0.9  # Should be close to 1.0 sessions/second

    def test_get_summary(self) -> None:
        """Test getting telemetry summary."""
        with tempfile.TemporaryDirectory() as temp_dir:
            telemetry = EnrichmentTelemetry("test_phase", temp_dir)
            
            # Set up some test data
            telemetry.metrics.cache_hits = 10
            telemetry.metrics.cache_misses = 5
            telemetry.metrics.api_calls_total = 8
            telemetry.metrics.api_calls_successful = 7
            telemetry.metrics.sessions_enriched = 3
            telemetry.metrics.dshield_calls = 2
            telemetry.metrics.virustotal_calls = 1
            
            summary = telemetry.get_summary()
            
            assert "cache_stats" in summary
            assert "api_stats" in summary
            assert "service_stats" in summary
            assert "performance" in summary
            assert "rate_limiting" in summary
            assert "errors" in summary
            assert "timestamps" in summary
            
            assert summary["cache_stats"]["hits"] == 10
            assert summary["cache_stats"]["misses"] == 5
            assert summary["api_stats"]["total_calls"] == 8
            assert summary["service_stats"]["dshield_calls"] == 2
            assert summary["performance"]["sessions_enriched"] == 3

    @patch('cowrieprocessor.enrichment.telemetry.StatusEmitter')
    def test_status_emitter_integration(self, mock_status_emitter: Mock) -> None:
        """Test integration with StatusEmitter."""
        mock_instance = Mock()
        mock_status_emitter.return_value = mock_instance
        
        telemetry = EnrichmentTelemetry("test_phase")
        
        # Record some metrics
        telemetry.record_cache_stats({"hits": 5, "misses": 2, "stores": 3})
        telemetry.record_api_call("dshield", True)
        
        # Verify StatusEmitter was called
        assert mock_status_emitter.called
        assert mock_instance.record_metrics.called


class TestEnrichmentServiceTelemetryIntegration:
    """Test telemetry integration with EnrichmentService."""

    def test_enrichment_service_with_telemetry(self) -> None:
        """Test EnrichmentService with telemetry enabled."""
        import tempfile

        from cowrieprocessor.enrichment import EnrichmentCacheManager
        from enrichment_handlers import EnrichmentService
        
        cache_dir = Path(tempfile.mkdtemp())
        cache_manager = EnrichmentCacheManager(cache_dir)
        
        # Test with telemetry enabled
        service = EnrichmentService(
            cache_dir=cache_dir,
            vt_api="test-key",
            dshield_email="test@example.com",
            urlhaus_api="test-key",
            spur_api="test-key",
            cache_manager=cache_manager,
            enable_telemetry=True,
            telemetry_phase="test_enrichment",
        )
        
        assert service.enable_telemetry is True
        assert service.telemetry is not None
        assert service.telemetry.metrics.cache_hits == 0

    def test_enrichment_service_without_telemetry(self) -> None:
        """Test EnrichmentService with telemetry disabled."""
        import tempfile

        from cowrieprocessor.enrichment import EnrichmentCacheManager
        from enrichment_handlers import EnrichmentService
        
        cache_dir = Path(tempfile.mkdtemp())
        cache_manager = EnrichmentCacheManager(cache_dir)
        
        # Test with telemetry disabled
        service = EnrichmentService(
            cache_dir=cache_dir,
            vt_api="test-key",
            dshield_email="test@example.com",
            urlhaus_api="test-key",
            spur_api="test-key",
            cache_manager=cache_manager,
            enable_telemetry=False,
        )
        
        assert service.enable_telemetry is False
        assert service.telemetry is None

    def test_cache_snapshot_method(self) -> None:
        """Test that cache_snapshot method works with telemetry."""
        import tempfile

        from cowrieprocessor.enrichment import EnrichmentCacheManager
        from enrichment_handlers import EnrichmentService
        
        cache_dir = Path(tempfile.mkdtemp())
        cache_manager = EnrichmentCacheManager(cache_dir)
        
        service = EnrichmentService(
            cache_dir=cache_dir,
            vt_api="test-key",
            dshield_email="test@example.com",
            urlhaus_api="test-key",
            spur_api="test-key",
            cache_manager=cache_manager,
            enable_telemetry=True,
        )
        
        # Test cache_snapshot method
        snapshot = service.cache_snapshot()
        assert isinstance(snapshot, dict)
        assert "hits" in snapshot
        assert "misses" in snapshot
        assert "stores" in snapshot
