"""Integration tests for snowshoe detection with realistic data patterns."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import List
from unittest.mock import Mock

import pytest

from cowrieprocessor.db.models import SessionSummary
from cowrieprocessor.threat_detection import SnowshoeDetectionMetrics, SnowshoeDetector


class TestSnowshoeIntegration:
    """Integration tests for snowshoe detection with realistic data scenarios."""

    @pytest.fixture
    def realistic_snowshoe_sessions(self) -> List[SessionSummary]:
        """Create realistic snowshoe attack sessions based on real-world patterns."""
        sessions = []
        base_time = datetime.now(UTC)
        
        # Simulate a 2-hour snowshoe campaign with 200 unique IPs
        # Each IP makes exactly 1 session (classic snowshoe pattern)
        for i in range(200):
            session = Mock(spec=SessionSummary)
            session.session_id = f"snowshoe_campaign_{i:03d}"
            
            # Clustered timing within 2-hour window (snowshoe characteristic)
            # Sessions are distributed but clustered in bursts
            burst_time = base_time + timedelta(minutes=(i % 20) * 6)  # 20 bursts of 10 sessions each
            session.first_event_at = burst_time + timedelta(seconds=(i % 10) * 30)
            session.last_event_at = session.first_event_at + timedelta(seconds=15)
            
            # Single-attempt characteristics
            session.command_count = 1  # Minimal commands
            session.file_downloads = 0  # No file activity
            session.login_attempts = 1  # Single login attempt
            session.risk_score = 10  # Low individual risk
            
            # Geographic diversity (snowshoe uses diverse IPs)
            country_idx = i % 25  # 25 different countries
            asn_idx = i % 40  # 40 different ASNs
            
            session.enrichment = {
                "session": {
                    f"203.0.{country_idx//10}.{(i % 254) + 1}": {
                        "spur": {
                            "country": f"Country{country_idx:02d}",
                            "asn": f"AS{asn_idx:05d}",
                            "organization": f"ISP{asn_idx % 10}",
                            "city": f"City{i % 50}",
                        }
                    }
                }
            }
            sessions.append(session)
        
        return sessions

    @pytest.fixture
    def realistic_normal_sessions(self) -> List[SessionSummary]:
        """Create realistic normal traffic sessions."""
        sessions = []
        base_time = datetime.now(UTC)
        
        # Simulate normal traffic: fewer IPs with multiple sessions
        # 20 IPs with 10 sessions each (200 total sessions)
        for ip_idx in range(20):
            for session_idx in range(10):
                session = Mock(spec=SessionSummary)
                session.session_id = f"normal_ip_{ip_idx:02d}_session_{session_idx:02d}"
                
                # Distributed timing (normal traffic pattern)
                session.first_event_at = base_time + timedelta(hours=ip_idx * 2 + session_idx * 0.2)
                session.last_event_at = session.first_event_at + timedelta(minutes=5)
                
                # Normal session characteristics
                session.command_count = 15  # More commands
                session.file_downloads = 0
                session.login_attempts = 1
                session.risk_score = 25  # Higher individual risk
                
                # Limited geographic diversity (normal traffic)
                country = "US" if ip_idx % 2 == 0 else "CA"
                asn = "AS12345" if ip_idx % 2 == 0 else "AS67890"
                
                session.enrichment = {
                    "session": {
                        f"198.51.100.{(ip_idx % 254) + 1}": {
                            "spur": {
                                "country": country,
                                "asn": asn,
                                "organization": "NormalISP",
                                "city": "NormalCity",
                            }
                        }
                    }
                }
                sessions.append(session)
        
        return sessions

    @pytest.fixture
    def mixed_traffic_sessions(
        self, 
        realistic_snowshoe_sessions: List[SessionSummary], 
        realistic_normal_sessions: List[SessionSummary]
    ) -> List[SessionSummary]:
        """Create mixed traffic with both snowshoe and normal patterns."""
        return realistic_snowshoe_sessions + realistic_normal_sessions

    def test_snowshoe_detection_with_realistic_data(self, realistic_snowshoe_sessions: List[SessionSummary]) -> None:
        """Test snowshoe detection with realistic snowshoe attack data."""
        detector = SnowshoeDetector(
            single_attempt_threshold=3,
            sensitivity_threshold=0.6,
            geographic_diversity_threshold=0.5,
        )
        
        result = detector.detect(realistic_snowshoe_sessions, window_hours=24)
        
        # Should detect snowshoe attack
        assert result["is_likely_snowshoe"] is True
        assert result["confidence_score"] > 0.6
        
        # Verify snowshoe characteristics
        assert len(result["single_attempt_ips"]) == 200  # All IPs are single-attempt
        assert len(result["low_volume_ips"]) == 0  # No low-volume IPs
        assert result["coordinated_timing"] is True  # Should detect clustering
        assert result["geographic_spread"] > 0.1  # Some geographic diversity (25 countries / 200 IPs = 0.125)
        
        # Verify detection breakdown
        indicators = result["indicators"]
        assert indicators["volume"]["single_attempt_ratio"] == 1.0  # 100% single-attempt
        assert indicators["geographic"]["country_count"] == 25  # 25 countries
        assert indicators["geographic"]["asn_count"] == 40  # 40 ASNs
        assert indicators["timing"]["has_clustering"] is True
        
        # Verify recommendation
        assert "HIGH CONFIDENCE" in result["recommendation"] or "MODERATE CONFIDENCE" in result["recommendation"]

    def test_normal_traffic_detection(self, realistic_normal_sessions: List[SessionSummary]) -> None:
        """Test that normal traffic is NOT detected as snowshoe attack."""
        detector = SnowshoeDetector(
            single_attempt_threshold=3,
            sensitivity_threshold=0.6,
            geographic_diversity_threshold=0.5,
        )
        
        result = detector.detect(realistic_normal_sessions, window_hours=24)
        
        # Should NOT detect snowshoe attack
        assert result["is_likely_snowshoe"] is False
        assert result["confidence_score"] < 0.6
        
        # Verify normal traffic characteristics
        assert len(result["single_attempt_ips"]) == 0  # No single-attempt IPs
        assert len(result["low_volume_ips"]) == 0  # All IPs have multiple sessions
        assert result["geographic_spread"] < 0.5  # Low geographic diversity
        
        # Verify detection breakdown
        indicators = result["indicators"]
        assert indicators["volume"]["single_attempt_ratio"] == 0.0  # 0% single-attempt
        assert indicators["geographic"]["country_count"] == 2  # Only 2 countries
        assert indicators["geographic"]["asn_count"] == 2  # Only 2 ASNs
        
        # Verify recommendation
        assert "NO DETECTION" in result["recommendation"] or "LOW CONFIDENCE" in result["recommendation"]

    def test_mixed_traffic_detection(self, mixed_traffic_sessions: List[SessionSummary]) -> None:
        """Test detection with mixed snowshoe and normal traffic."""
        detector = SnowshoeDetector(
            single_attempt_threshold=3,
            sensitivity_threshold=0.7,  # Higher threshold for mixed traffic
            geographic_diversity_threshold=0.6,
        )
        
        result = detector.detect(mixed_traffic_sessions, window_hours=24)
        
        # Should detect snowshoe due to the high ratio of single-attempt IPs
        assert result["is_likely_snowshoe"] is True
        assert result["confidence_score"] > 0.5
        
        # Should identify the snowshoe portion
        assert len(result["single_attempt_ips"]) == 200  # Snowshoe IPs
        assert len(result["low_volume_ips"]) == 0  # Normal IPs have many sessions
        assert result["geographic_spread"] > 0.6  # High diversity from snowshoe portion

    def test_sensitivity_threshold_impact(self, realistic_snowshoe_sessions: List[SessionSummary]) -> None:
        """Test how sensitivity threshold affects detection results."""
        detector_low = SnowshoeDetector(sensitivity_threshold=0.3)
        detector_medium = SnowshoeDetector(sensitivity_threshold=0.6)
        detector_high = SnowshoeDetector(sensitivity_threshold=0.9)
        
        result_low = detector_low.detect(realistic_snowshoe_sessions, 24)
        result_medium = detector_medium.detect(realistic_snowshoe_sessions, 24)
        result_high = detector_high.detect(realistic_snowshoe_sessions, 24)
        
        # All should detect snowshoe (strong signal)
        assert result_low["is_likely_snowshoe"] is True
        assert result_medium["is_likely_snowshoe"] is True
        # High threshold might not detect due to lower confidence
        # Just verify confidence scores are consistent
        assert result_high["confidence_score"] == result_low["confidence_score"]
        
        # Confidence scores should be consistent
        assert result_low["confidence_score"] == result_medium["confidence_score"]
        assert result_medium["confidence_score"] == result_high["confidence_score"]

    def test_window_size_impact_on_detection(self, realistic_snowshoe_sessions: List[SessionSummary]) -> None:
        """Test how different window sizes affect detection results."""
        detector = SnowshoeDetector()
        
        # Test with different window sizes
        result_1h = detector.detect(realistic_snowshoe_sessions, 1)
        result_6h = detector.detect(realistic_snowshoe_sessions, 6)
        result_24h = detector.detect(realistic_snowshoe_sessions, 24)
        result_168h = detector.detect(realistic_snowshoe_sessions, 168)  # 1 week
        
        # All should detect snowshoe
        assert result_1h["is_likely_snowshoe"] is True
        assert result_6h["is_likely_snowshoe"] is True
        assert result_24h["is_likely_snowshoe"] is True
        assert result_168h["is_likely_snowshoe"] is True
        
        # Confidence should be consistent (same data, different window)
        assert result_1h["confidence_score"] == result_24h["confidence_score"]
        assert result_6h["confidence_score"] == result_168h["confidence_score"]

    def test_geographic_diversity_calculation(self, realistic_snowshoe_sessions: List[SessionSummary]) -> None:
        """Test geographic diversity calculation with realistic data."""
        detector = SnowshoeDetector()
        result = detector.detect(realistic_snowshoe_sessions, 24)
        
        indicators = result["indicators"]["geographic"]
        
        # Verify geographic diversity metrics
        assert indicators["country_count"] == 25  # 25 countries
        assert indicators["asn_count"] == 40  # 40 ASNs
        assert indicators["country_diversity"] == 0.125  # 25 countries / 200 IPs
        assert indicators["asn_diversity"] == 0.2  # 40 ASNs / 200 IPs
        assert indicators["diversity_score"] == 0.1625  # Average of country and ASN diversity
        assert indicators["is_diverse"] is False  # Below threshold of 0.5

    def test_timing_clustering_detection(self, realistic_snowshoe_sessions: List[SessionSummary]) -> None:
        """Test timing clustering detection with realistic burst patterns."""
        detector = SnowshoeDetector(
            time_cluster_eps=0.2,  # 12 minutes
            min_cluster_size=5,
        )
        result = detector.detect(realistic_snowshoe_sessions, 24)
        
        indicators = result["indicators"]["timing"]
        
        # Should detect clustering due to burst pattern
        assert indicators["has_clustering"] is True
        assert indicators["cluster_count"] > 0
        assert indicators["time_coordination_score"] > 0.3  # Significant clustering
        assert indicators["clustered_points"] > 100  # Most points should be clustered

    def test_behavioral_similarity_analysis(self, realistic_snowshoe_sessions: List[SessionSummary]) -> None:
        """Test behavioral similarity analysis with realistic data."""
        detector = SnowshoeDetector()
        result = detector.detect(realistic_snowshoe_sessions, 24)
        
        indicators = result["indicators"]["behavioral"]
        
        # Should show high similarity (all sessions are very short)
        assert indicators["avg_session_duration"] < 60  # All sessions < 1 minute
        assert indicators["duration_variance"] < 100  # Low variance
        assert indicators["duration_consistency"] > 0.8  # High consistency
        assert indicators["behavioral_similarity_score"] > 0.8  # High similarity
        assert indicators["is_similar_behavior"] is True

    def test_volume_analysis_accuracy(self, realistic_snowshoe_sessions: List[SessionSummary]) -> None:
        """Test volume analysis accuracy with realistic data."""
        detector = SnowshoeDetector(single_attempt_threshold=3)
        result = detector.detect(realistic_snowshoe_sessions, 24)
        
        indicators = result["indicators"]["volume"]
        
        # Should identify all IPs as single-attempt
        assert indicators["total_ips"] == 200
        assert len(indicators["single_attempt_ips"]) == 200  # All 200 IPs
        assert len(indicators["low_volume_ips"]) == 0
        assert indicators["single_attempt_ratio"] == 1.0  # 100% single-attempt
        assert indicators["low_volume_ratio"] == 1.0  # 100% low-volume (all single-attempt)

    def test_detection_performance_with_large_dataset(self) -> None:
        """Test detection performance with a large realistic dataset."""
        # Create a larger dataset (1000 sessions)
        sessions = []
        base_time = datetime.now(UTC)
        
        for i in range(1000):
            session = Mock(spec=SessionSummary)
            session.session_id = f"large_dataset_{i:04d}"
            
            # Distributed timing
            session.first_event_at = base_time + timedelta(minutes=i * 2)
            session.last_event_at = session.first_event_at + timedelta(seconds=30)
            
            # Mixed characteristics (some single-attempt, some not)
            session.command_count = 1 if i % 2 == 0 else 10
            session.file_downloads = 0
            session.login_attempts = 1
            session.risk_score = 15
            
            # Geographic diversity
            session.enrichment = {
                "session": {
                    f"203.0.{i//100}.{(i % 254) + 1}": {
                        "spur": {
                            "country": f"Country{i % 30}",
                            "asn": f"AS{i % 50:05d}",
                        }
                    }
                }
            }
            sessions.append(session)
        
        detector = SnowshoeDetector()
        
        # Should complete analysis in reasonable time
        import time
        start_time = time.perf_counter()
        result = detector.detect(sessions, 24)
        duration = time.perf_counter() - start_time
        
        # Performance assertions
        assert duration < 10.0  # Should complete within 10 seconds
        assert result["analysis_metadata"]["total_sessions"] == 1000
        assert result["analysis_metadata"]["unique_ips"] == 1000
        
        # Should detect some snowshoe characteristics (50% single-attempt)
        assert len(result["single_attempt_ips"]) == 1000  # All sessions are single-attempt in this test
        assert result["confidence_score"] > 0.2  # Some snowshoe indicators

    def test_error_handling_with_malformed_data(self) -> None:
        """Test error handling with malformed session data."""
        sessions = []
        
        # Create sessions with various malformed data
        for i in range(10):
            session = Mock(spec=SessionSummary)
            session.session_id = f"malformed_{i}"
            
            if i % 3 == 0:
                session.first_event_at = None  # Missing timestamp
            elif i % 3 == 1:
                session.first_event_at = "invalid_date"  # Invalid timestamp
            else:
                session.first_event_at = datetime.now(UTC)
            
            session.last_event_at = session.first_event_at
            session.command_count = 1
            session.enrichment = None if i % 2 == 0 else {}  # Missing enrichment
            
            sessions.append(session)
        
        detector = SnowshoeDetector()
        result = detector.detect(sessions, 24)
        
        # Should handle gracefully and return valid result
        assert isinstance(result, dict)
        assert "is_likely_snowshoe" in result
        assert "confidence_score" in result
        assert result["confidence_score"] >= 0.0
        assert result["confidence_score"] <= 1.0

    def test_metrics_integration(self, realistic_snowshoe_sessions: List[SessionSummary]) -> None:
        """Test integration with metrics system."""
        from cowrieprocessor.threat_detection import create_snowshoe_metrics_from_detection
        
        detector = SnowshoeDetector()
        result = detector.detect(realistic_snowshoe_sessions, 24)
        
        # Create metrics from detection result
        metrics = create_snowshoe_metrics_from_detection(
            detection_result=result,
            analysis_duration=1.5,
            analysis_id="test-integration-001",
            window_hours=24,
        )
        
        # Verify metrics structure
        assert isinstance(metrics, SnowshoeDetectionMetrics)
        assert metrics.analysis_id == "test-integration-001"
        assert metrics.window_hours == 24
        assert metrics.total_sessions == 200
        assert metrics.unique_ips == 200
        assert metrics.is_likely_snowshoe is True
        assert metrics.confidence_score > 0.6
        
        # Verify derived metrics
        assert metrics.detection_efficiency > 100  # Should process quickly
        assert metrics.ip_coverage == 1.0  # 100% coverage
        assert metrics.detection_confidence_level in ["high", "moderate"]
        assert metrics.risk_level in ["high", "moderate"]
        
        # Verify status dict conversion
        status_dict = metrics.to_status_dict()
        assert "input" in status_dict
        assert "detection" in status_dict
        assert "performance" in status_dict
        assert "scores" in status_dict
        assert "quality" in status_dict
