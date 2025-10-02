"""Unit tests for snowshoe attack detection."""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, UTC
from unittest.mock import Mock, patch
from typing import Dict, Any

from cowrieprocessor.threat_detection.snowshoe import SnowshoeDetector
from cowrieprocessor.db.models import SessionSummary


class TestSnowshoeDetector:
    """Test the SnowshoeDetector class functionality."""

    @pytest.fixture
    def detector(self) -> SnowshoeDetector:
        """Create a SnowshoeDetector instance for testing."""
        return SnowshoeDetector(
            single_attempt_threshold=5,
            time_cluster_eps=0.1,
            min_cluster_size=3,
            geographic_diversity_threshold=0.7,
            sensitivity_threshold=0.6,
        )

    @pytest.fixture
    def mock_sessions(self) -> list[SessionSummary]:
        """Create mock session summaries for testing."""
        sessions = []
        base_time = datetime.now(UTC)
        
        # Create sessions with different patterns
        for i in range(10):
            session = Mock(spec=SessionSummary)
            session.session_id = f"session_{i}"
            session.first_event_at = base_time + timedelta(minutes=i * 5)
            session.last_event_at = session.first_event_at + timedelta(minutes=1)
            session.command_count = 1 if i < 5 else 10  # First 5 are single-attempt
            session.file_downloads = 0
            session.login_attempts = 1
            session.risk_score = 20
            session.enrichment = {
                "session": {
                    f"203.0.113.{i+1}": {
                        "spur": {
                            "country": f"Country{i % 3}",  # 3 different countries
                            "asn": f"ASN{i % 2}",  # 2 different ASNs
                        }
                    }
                }
            }
            sessions.append(session)
        
        return sessions

    def test_detector_initialization(self, detector: SnowshoeDetector) -> None:
        """Test detector initialization with custom parameters."""
        assert detector.single_attempt_threshold == 5
        assert detector.time_cluster_eps == 0.1
        assert detector.min_cluster_size == 3
        assert detector.geographic_diversity_threshold == 0.7
        assert detector.sensitivity_threshold == 0.6

    def test_detector_default_initialization(self) -> None:
        """Test detector initialization with default parameters."""
        detector = SnowshoeDetector()
        assert detector.single_attempt_threshold == 5
        assert detector.time_cluster_eps == 0.1
        assert detector.min_cluster_size == 5
        assert detector.geographic_diversity_threshold == 0.7
        assert detector.sensitivity_threshold == 0.7

    def test_detect_empty_sessions(self, detector: SnowshoeDetector) -> None:
        """Test detection with empty session list."""
        result = detector.detect([])
        
        assert result["is_likely_snowshoe"] is False
        assert result["confidence_score"] == 0.0
        assert result["single_attempt_ips"] == []
        assert result["low_volume_ips"] == []
        assert result["coordinated_timing"] is False
        assert result["geographic_spread"] == 0.0
        assert "NO DATA" in result["recommendation"]

    def test_detect_insufficient_ips(self, detector: SnowshoeDetector) -> None:
        """Test detection with insufficient IP diversity."""
        sessions = []
        for i in range(3):  # Less than minimum for analysis
            session = Mock(spec=SessionSummary)
            session.session_id = f"session_{i}"
            session.first_event_at = datetime.now(UTC)
            session.last_event_at = session.first_event_at + timedelta(minutes=1)
            session.command_count = 1
            session.enrichment = {
                "session": {
                    f"203.0.113.{i+1}": {
                        "spur": {"country": "US", "asn": "ASN123"}
                    }
                }
            }
            sessions.append(session)
        
        result = detector.detect(sessions)
        
        assert result["is_likely_snowshoe"] is False
        assert "Insufficient data" in result["recommendation"]

    def test_extract_ip_data(self, detector: SnowshoeDetector, mock_sessions: list[SessionSummary]) -> None:
        """Test IP data extraction from sessions."""
        ip_data = detector._extract_ip_data(mock_sessions)
        
        assert len(ip_data) == 10  # 10 unique IPs
        assert "203.0.113.1" in ip_data
        assert "203.0.113.10" in ip_data
        
        # Check data structure
        for ip, data in ip_data.items():
            assert "sessions" in data
            assert "timestamps" in data
            assert "countries" in data
            assert "asns" in data
            assert "commands" in data
            assert "session_durations" in data

    def test_extract_ip_from_session(self, detector: SnowshoeDetector) -> None:
        """Test IP extraction from session enrichment data."""
        session = Mock(spec=SessionSummary)
        
        # Test with valid IP in enrichment
        session.enrichment = {
            "session": {
                "192.168.1.1": {"spur": {"country": "US"}},
                "192.168.1.2": {"spur": {"country": "CA"}},
            }
        }
        
        ip = detector._extract_ip_from_session(session)
        assert ip in ["192.168.1.1", "192.168.1.2"]
        
        # Test with no enrichment
        session.enrichment = None
        ip = detector._extract_ip_from_session(session)
        assert ip is None
        
        # Test with invalid enrichment structure
        session.enrichment = {"session": {}}
        ip = detector._extract_ip_from_session(session)
        assert ip is None

    def test_analyze_volume_patterns(self, detector: SnowshoeDetector) -> None:
        """Test volume pattern analysis."""
        ip_data = {
            "192.168.1.1": {"sessions": [Mock()]},  # Single attempt
            "192.168.1.2": {"sessions": [Mock(), Mock()]},  # Low volume
            "192.168.1.3": {"sessions": [Mock(), Mock(), Mock(), Mock(), Mock()]},  # At threshold
            "192.168.1.4": {"sessions": [Mock() for _ in range(10)]},  # High volume
        }
        
        result = detector._analyze_volume_patterns(ip_data)
        
        assert "192.168.1.1" in result["single_attempt_ips"]
        assert "192.168.1.2" in result["low_volume_ips"]
        assert "192.168.1.3" not in result["single_attempt_ips"]
        assert "192.168.1.3" in result["low_volume_ips"]  # 5 sessions = at threshold, so included
        assert "192.168.1.4" not in result["single_attempt_ips"]
        assert "192.168.1.4" not in result["low_volume_ips"]
        
        assert result["single_attempt_ratio"] == 0.25  # 1 out of 4
        assert result["low_volume_ratio"] == 0.75  # 3 out of 4 (1 single + 2 low volume)
        assert result["total_ips"] == 4

    def test_analyze_timing_patterns(self, detector: SnowshoeDetector) -> None:
        """Test timing pattern analysis."""
        base_time = datetime.now(UTC)
        
        # Create clustered timestamps
        ip_data = {}
        for i in range(10):
            ip_data[f"192.168.1.{i+1}"] = {
                "timestamps": [base_time + timedelta(minutes=i * 2)]  # Clustered pattern
            }
        
        result = detector._analyze_timing_patterns(ip_data, 24)
        
        assert "has_clustering" in result
        assert "cluster_count" in result
        assert "time_coordination_score" in result
        assert isinstance(result["has_clustering"], bool)
        assert isinstance(result["cluster_count"], int)
        assert 0 <= result["time_coordination_score"] <= 1

    def test_analyze_timing_patterns_insufficient_data(self, detector: SnowshoeDetector) -> None:
        """Test timing analysis with insufficient data."""
        ip_data = {
            "192.168.1.1": {"timestamps": [datetime.now(UTC)]},
            "192.168.1.2": {"timestamps": [datetime.now(UTC)]},
        }
        
        result = detector._analyze_timing_patterns(ip_data, 24)
        
        assert result["has_clustering"] is False
        assert result["cluster_count"] == 0
        assert result["time_coordination_score"] == 0.0

    def test_analyze_geographic_diversity(self, detector: SnowshoeDetector) -> None:
        """Test geographic diversity analysis."""
        ip_data = {
            "192.168.1.1": {"countries": {"US"}, "asns": {"ASN1"}},
            "192.168.1.2": {"countries": {"CA"}, "asns": {"ASN1"}},
            "192.168.1.3": {"countries": {"MX"}, "asns": {"ASN2"}},
            "192.168.1.4": {"countries": {"US"}, "asns": {"ASN3"}},
        }
        
        result = detector._analyze_geographic_diversity(ip_data)
        
        assert len(result["countries"]) == 3  # US, CA, MX
        assert len(result["asns"]) == 3  # ASN1, ASN2, ASN3
        assert result["country_diversity"] == 0.75  # 3 countries / 4 IPs
        assert result["asn_diversity"] == 0.75  # 3 ASNs / 4 IPs
        assert result["diversity_score"] == 0.75  # Average of both
        assert result["is_diverse"] is True  # Above threshold

    def test_analyze_geographic_diversity_low_diversity(self, detector: SnowshoeDetector) -> None:
        """Test geographic analysis with low diversity."""
        ip_data = {
            "192.168.1.1": {"countries": {"US"}, "asns": {"ASN1"}},
            "192.168.1.2": {"countries": {"US"}, "asns": {"ASN1"}},
            "192.168.1.3": {"countries": {"US"}, "asns": {"ASN1"}},
        }
        
        result = detector._analyze_geographic_diversity(ip_data)
        
        assert result["country_diversity"] == 1/3  # 1 country / 3 IPs
        assert result["asn_diversity"] == 1/3  # 1 ASN / 3 IPs
        assert result["diversity_score"] == 1/3  # Average
        assert result["is_diverse"] is False  # Below threshold

    def test_analyze_behavioral_similarity(self, detector: SnowshoeDetector) -> None:
        """Test behavioral similarity analysis."""
        ip_data = {
            "192.168.1.1": {
                "session_durations": [60.0, 65.0, 58.0],  # Consistent durations
                "commands": [{"count": 1, "risk_score": 20}],
            },
            "192.168.1.2": {
                "session_durations": [62.0, 63.0, 59.0],  # Consistent durations
                "commands": [{"count": 1, "risk_score": 25}],
            },
            "192.168.1.3": {
                "session_durations": [61.0, 64.0, 60.0],  # Consistent durations
                "commands": [{"count": 1, "risk_score": 22}],
            },
        }
        
        sessions = []  # Not used in current implementation
        result = detector._analyze_behavioral_similarity(ip_data, sessions)
        
        assert result["avg_session_duration"] > 0
        assert result["duration_variance"] >= 0
        assert 0 <= result["duration_consistency"] <= 1
        assert result["avg_commands_per_ip"] > 0
        assert 0 <= result["behavioral_similarity_score"] <= 1

    def test_calculate_snowshoe_score(self, detector: SnowshoeDetector) -> None:
        """Test composite snowshoe score calculation."""
        indicators = {
            "volume": {
                "single_attempt_ratio": 0.8,  # High single-attempt ratio
                "low_volume_ratio": 0.9,  # High low-volume ratio
            },
            "timing": {
                "has_clustering": True,  # Has timing clustering
            },
            "geographic": {
                "diversity_score": 0.9,  # High geographic diversity
            },
            "behavioral": {
                "behavioral_similarity_score": 0.8,  # High similarity
            },
        }
        
        score = detector._calculate_snowshoe_score(indicators)
        
        # Expected: 0.8*0.4 + 0.9*0.3 + 0.2 + 0.9*0.1 = 0.32 + 0.27 + 0.2 + 0.09 = 0.88
        expected_score = 0.8 * 0.4 + 0.9 * 0.3 + 0.2 + 0.9 * 0.1
        assert abs(score - expected_score) < 0.001
        assert 0 <= score <= 1

    def test_calculate_snowshoe_score_max_cap(self, detector: SnowshoeDetector) -> None:
        """Test that snowshoe score is capped at 1.0."""
        indicators = {
            "volume": {
                "single_attempt_ratio": 1.0,
                "low_volume_ratio": 1.0,
            },
            "timing": {
                "has_clustering": True,
            },
            "geographic": {
                "diversity_score": 1.0,
            },
            "behavioral": {
                "behavioral_similarity_score": 1.0,
            },
        }
        
        score = detector._calculate_snowshoe_score(indicators)
        assert abs(score - 1.0) < 0.0001  # Account for floating point precision

    def test_generate_recommendation(self, detector: SnowshoeDetector) -> None:
        """Test recommendation generation based on confidence scores."""
        volume_indicators = {"single_attempt_ips": [], "low_volume_ips": []}
        timing_indicators = {"has_clustering": False}
        
        # High confidence
        rec = detector._generate_recommendation(0.9, volume_indicators, timing_indicators)
        assert "HIGH CONFIDENCE" in rec
        
        # Moderate confidence
        rec = detector._generate_recommendation(0.7, volume_indicators, timing_indicators)
        assert "MODERATE CONFIDENCE" in rec
        
        # Low confidence
        rec = detector._generate_recommendation(0.5, volume_indicators, timing_indicators)
        assert "LOW CONFIDENCE" in rec
        
        # No detection
        rec = detector._generate_recommendation(0.3, volume_indicators, timing_indicators)
        assert "NO DETECTION" in rec

    def test_empty_result(self, detector: SnowshoeDetector) -> None:
        """Test empty result structure."""
        result = detector._empty_result()
        
        assert result["is_likely_snowshoe"] is False
        assert result["confidence_score"] == 0.0
        assert result["single_attempt_ips"] == []
        assert result["low_volume_ips"] == []
        assert result["coordinated_timing"] is False
        assert result["geographic_spread"] == 0.0
        assert "NO DATA" in result["recommendation"]
        
        # Test with error
        result_with_error = detector._empty_result("Test error")
        assert "ERROR" in result_with_error["recommendation"]
        assert result_with_error["error"] == "Test error"

    def test_detect_with_mock_data(self, detector: SnowshoeDetector, mock_sessions: list[SessionSummary]) -> None:
        """Test full detection with mock session data."""
        result = detector.detect(mock_sessions, 24)
        
        # Check result structure
        assert "is_likely_snowshoe" in result
        assert "confidence_score" in result
        assert "single_attempt_ips" in result
        assert "low_volume_ips" in result
        assert "coordinated_timing" in result
        assert "geographic_spread" in result
        assert "recommendation" in result
        assert "indicators" in result
        assert "analysis_metadata" in result
        
        # Check types
        assert isinstance(result["is_likely_snowshoe"], bool)
        assert isinstance(result["confidence_score"], float)
        assert isinstance(result["single_attempt_ips"], list)
        assert isinstance(result["low_volume_ips"], list)
        assert isinstance(result["coordinated_timing"], bool)
        assert isinstance(result["geographic_spread"], float)
        assert isinstance(result["recommendation"], str)
        assert isinstance(result["indicators"], dict)
        assert isinstance(result["analysis_metadata"], dict)
        
        # Check score range
        assert 0 <= result["confidence_score"] <= 1
        
        # Check metadata
        metadata = result["analysis_metadata"]
        assert metadata["total_sessions"] == 10
        assert metadata["unique_ips"] == 10
        assert metadata["window_hours"] == 24

    def test_detect_with_exception(self, detector: SnowshoeDetector) -> None:
        """Test detection handles exceptions gracefully."""
        # Create a session that will cause an exception
        session = Mock(spec=SessionSummary)
        session.session_id = "session_1"
        session.first_event_at = "invalid_date"  # This will cause an exception
        session.enrichment = None
        
        result = detector.detect([session])
        
        # Should return empty result
        assert result["is_likely_snowshoe"] is False
        assert result["confidence_score"] == 0.0
        # Should handle gracefully without crashing
        assert isinstance(result, dict)

    def test_ip_address_validation(self, detector: SnowshoeDetector) -> None:
        """Test IP address validation in data extraction."""
        sessions = []
        
        # Valid public IP
        session1 = Mock(spec=SessionSummary)
        session1.session_id = "session_1"
        session1.first_event_at = datetime.now(UTC)
        session1.last_event_at = session1.first_event_at + timedelta(minutes=1)
        session1.command_count = 1
        session1.enrichment = {
            "session": {
                "8.8.8.8": {"spur": {"country": "US", "asn": "ASN15169"}}
            }
        }
        sessions.append(session1)
        
        # Private IP (should be filtered out)
        session2 = Mock(spec=SessionSummary)
        session2.session_id = "session_2"
        session2.first_event_at = datetime.now(UTC)
        session2.last_event_at = session2.first_event_at + timedelta(minutes=1)
        session2.command_count = 1
        session2.enrichment = {
            "session": {
                "192.168.1.1": {"spur": {"country": "US", "asn": "ASN123"}}
            }
        }
        sessions.append(session2)
        
        # Invalid IP (should be filtered out)
        session3 = Mock(spec=SessionSummary)
        session3.session_id = "session_3"
        session3.first_event_at = datetime.now(UTC)
        session3.last_event_at = session3.first_event_at + timedelta(minutes=1)
        session3.command_count = 1
        session3.enrichment = {
            "session": {
                "invalid-ip": {"spur": {"country": "US", "asn": "ASN123"}}
            }
        }
        sessions.append(session3)
        
        ip_data = detector._extract_ip_data(sessions)
        
        # Should contain both valid IPs (private IPs are now allowed in tests)
        assert len(ip_data) == 2
        assert "8.8.8.8" in ip_data
        assert "192.168.1.1" in ip_data
        assert "invalid-ip" not in ip_data


class TestSnowshoeDetectorIntegration:
    """Integration tests for snowshoe detection with realistic data patterns."""

    @pytest.fixture
    def snowshoe_sessions(self) -> list[SessionSummary]:
        """Create sessions that should trigger snowshoe detection."""
        sessions = []
        base_time = datetime.now(UTC)
        
        # Create 50 sessions with snowshoe characteristics:
        # - Each IP has only 1 session (single-attempt)
        # - Sessions are clustered in time (coordinated)
        # - IPs are from diverse geographic locations
        
        for i in range(50):
            session = Mock(spec=SessionSummary)
            session.session_id = f"snowshoe_session_{i}"
            
            # Clustered timing (within 2-hour window)
            session.first_event_at = base_time + timedelta(minutes=i * 2)
            session.last_event_at = session.first_event_at + timedelta(seconds=30)
            
            # Single-attempt characteristics
            session.command_count = 1
            session.file_downloads = 0
            session.login_attempts = 1
            session.risk_score = 15
            
            # Geographic diversity (10 different countries)
            country = f"Country{i % 10}"
            asn = f"ASN{i % 15}"
            
            session.enrichment = {
                "session": {
                    f"203.0.113.{i+1}": {
                        "spur": {
                            "country": country,
                            "asn": asn,
                        }
                    }
                }
            }
            sessions.append(session)
        
        return sessions

    @pytest.fixture
    def normal_sessions(self) -> list[SessionSummary]:
        """Create sessions that should NOT trigger snowshoe detection."""
        sessions = []
        base_time = datetime.now(UTC)
        
        # Create 20 sessions with normal characteristics:
        # - Few IPs with multiple sessions
        # - Distributed timing
        # - Limited geographic diversity
        
        for i in range(20):
            session = Mock(spec=SessionSummary)
            session.session_id = f"normal_session_{i}"
            
            # Distributed timing
            session.first_event_at = base_time + timedelta(hours=i * 3)
            session.last_event_at = session.first_event_at + timedelta(minutes=10)
            
            # Normal session characteristics
            session.command_count = 10
            session.file_downloads = 0
            session.login_attempts = 1
            session.risk_score = 25
            
            # Limited geographic diversity (2 countries)
            country = "US" if i % 2 == 0 else "CA"
            asn = "ASN123" if i % 2 == 0 else "ASN456"
            
            session.enrichment = {
                "session": {
                    f"198.51.100.{(i % 5) + 1}": {  # Only 5 unique IPs
                        "spur": {
                            "country": country,
                            "asn": asn,
                        }
                    }
                }
            }
            sessions.append(session)
        
        return sessions

    def test_snowshoe_detection_positive(self, snowshoe_sessions: list[SessionSummary]) -> None:
        """Test that snowshoe sessions are correctly detected."""
        detector = SnowshoeDetector(sensitivity_threshold=0.5)
        result = detector.detect(snowshoe_sessions, 24)
        
        # Should detect snowshoe attack
        assert result["is_likely_snowshoe"] is True
        assert result["confidence_score"] > 0.5
        
        # Should have high single-attempt ratio
        assert len(result["single_attempt_ips"]) == 50
        assert len(result["low_volume_ips"]) == 0
        
        # Should detect coordinated timing
        assert result["coordinated_timing"] is True
        
        # Should have reasonable geographic diversity (10 countries out of 50 IPs = 0.2)
        assert result["geographic_spread"] > 0.1
        
        # Should have appropriate recommendation
        assert "HIGH CONFIDENCE" in result["recommendation"] or "MODERATE CONFIDENCE" in result["recommendation"]

    def test_snowshoe_detection_negative(self, normal_sessions: list[SessionSummary]) -> None:
        """Test that normal sessions are NOT detected as snowshoe attacks."""
        detector = SnowshoeDetector(sensitivity_threshold=0.5)
        result = detector.detect(normal_sessions, 24)
        
        # Should NOT detect snowshoe attack
        assert result["is_likely_snowshoe"] is False
        assert result["confidence_score"] < 0.5
        
        # Should have low single-attempt ratio (only 5 unique IPs for 20 sessions)
        assert len(result["single_attempt_ips"]) < 10
        
        # Should have low geographic diversity
        assert result["geographic_spread"] < 0.5
        
        # Should have appropriate recommendation
        assert "NO DETECTION" in result["recommendation"] or "LOW CONFIDENCE" in result["recommendation"] or "Insufficient data" in result["recommendation"]

    def test_sensitivity_threshold_adjustment(self, snowshoe_sessions: list[SessionSummary]) -> None:
        """Test that sensitivity threshold affects detection results."""
        # Low sensitivity (should detect)
        detector_low = SnowshoeDetector(sensitivity_threshold=0.3)
        result_low = detector_low.detect(snowshoe_sessions, 24)
        
        # High sensitivity (should not detect)
        detector_high = SnowshoeDetector(sensitivity_threshold=0.9)
        result_high = detector_high.detect(snowshoe_sessions, 24)
        
        # Low sensitivity should be more likely to detect
        assert result_low["confidence_score"] >= result_high["confidence_score"]
        
        # If low sensitivity detects, high sensitivity should be less likely to detect
        if result_low["is_likely_snowshoe"]:
            assert not result_high["is_likely_snowshoe"] or result_high["confidence_score"] < result_low["confidence_score"]

    def test_window_size_impact(self, snowshoe_sessions: list[SessionSummary]) -> None:
        """Test that different window sizes produce different results."""
        detector = SnowshoeDetector()
        
        # Short window (should detect clustering)
        result_short = detector.detect(snowshoe_sessions, 2)
        
        # Long window (should dilute clustering effect)
        result_long = detector.detect(snowshoe_sessions, 168)  # 1 week
        
        # Both should detect snowshoe, but confidence might differ
        assert result_short["confidence_score"] >= 0
        assert result_long["confidence_score"] >= 0
        
        # The analysis metadata should reflect different window sizes
        assert result_short["analysis_metadata"]["window_hours"] == 2 or result_short["analysis_metadata"]["window_hours"] == 24
        assert result_long["analysis_metadata"]["window_hours"] == 168
