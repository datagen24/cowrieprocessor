"""Unit tests for mock enrichment handlers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.fixtures.mock_enrichment_handlers import (
    MockAbuseIPDBHandler,
    MockOTXHandler,
    MockStatisticalAnalyzer,
    setup_mock_enrichment_environment,
)


class TestMockOTXHandler:
    """Test mock OTX handler functionality."""

    @pytest.fixture
    def mock_otx(self, tmp_path) -> Any:
        """Create mock OTX handler with temporary cache directory."""
        return MockOTXHandler("test_key", tmp_path)

    def test_otx_check_ip_caches_results(self, mock_otx) -> None:
        """Mock OTX should cache results properly."""
        ip = "192.168.1.100"

        # First call should make API call and cache
        result1 = mock_otx.check_ip(ip)

        cache_file = mock_otx.cache_dir / f"otx_ip_{ip}.json"
        assert cache_file.exists()

        # Second call should use cache
        result2 = mock_otx.check_ip(ip)

        # Results should be identical
        assert result1 == result2

        # Cache file should contain the result
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        assert cached == result1

    def test_otx_check_ip_handles_private_ips(self, mock_otx) -> None:
        """Mock OTX should return clean results for private IPs."""
        private_ips = ["192.168.1.1", "10.0.0.1", "127.0.0.1"]

        for ip in private_ips:
            result = mock_otx.check_ip(ip)
            assert result["reputation"] == 0
            assert len(result["pulse_info"]["pulses"]) == 0
            assert result["malware_families"] == []

    def test_otx_check_ip_handles_known_good_ips(self, mock_otx) -> None:
        """Mock OTX should return clean results for known good IPs."""
        good_ips = ["8.8.8.8", "1.1.1.1", "9.9.9.9"]

        for ip in good_ips:
            result = mock_otx.check_ip(ip)
            assert result["reputation"] == 0
            assert len(result["pulse_info"]["pulses"]) == 0

    def test_otx_check_ip_handles_suspicious_ips(self, mock_otx) -> None:
        """Mock OTX should return malicious results for suspicious IPs."""
        # Set seed for deterministic results
        import random

        random.seed(42)

        suspicious_ips = ["203.0.113.1", "198.51.100.1", "malicious.example.com"]

        for ip in suspicious_ips:
            result = mock_otx.check_ip(ip)

            # Most IPs should be flagged as suspicious (70% chance)
            # With seed 42, these should be flagged
            assert result["reputation"] > 0 or len(result["pulse_info"]["pulses"]) > 0

    def test_otx_check_file_hash_caches_results(self, mock_otx) -> None:
        """Mock OTX file hash check should cache results."""
        hash_value = "d41d8cd98f00b204e9800998ecf8427e"

        result1 = mock_otx.check_file_hash(hash_value)
        result2 = mock_otx.check_file_hash(hash_value)

        # Results should be identical
        assert result1 == result2

        # Cache file should exist
        cache_file = mock_otx.cache_dir / f"otx_hash_{hash_value}.json"
        assert cache_file.exists()

    def test_otx_check_file_hash_handles_known_bad_hashes(self, mock_otx) -> None:
        """Mock OTX should flag known bad hashes."""
        bad_hashes = ["0000deadbeef", "deadbeef0000", "badhash123456"]

        for hash_value in bad_hashes:
            result = mock_otx.check_file_hash(hash_value)
            assert result["malware"] is True
            assert result["pulses"] > 0
            assert len(result["threat_names"]) > 0

    def test_otx_check_file_hash_handles_known_good_hashes(self, mock_otx) -> None:
        """Mock OTX should return clean results for known good hashes."""
        good_hashes = ["aaaacleanhash", "clean12345678", "goodhash0000"]

        for hash_value in good_hashes:
            result = mock_otx.check_file_hash(hash_value)
            assert result["malware"] is False
            assert result["pulses"] == 0
            assert len(result["threat_names"]) == 0

    def test_otx_rate_limiting(self, mock_otx) -> None:
        """Mock OTX should implement rate limiting."""
        # Make requests up to the limit
        for i in range(4):
            result = mock_otx.check_ip(f"192.168.1.{i}")
            assert "error" not in result

        # Next request should be rate limited
        result = mock_otx.check_ip("192.168.1.999")
        assert result == {"error": "rate_limit"}


class TestMockAbuseIPDBHandler:
    """Test mock AbuseIPDB handler functionality."""

    @pytest.fixture
    def mock_abuseipdb(self, tmp_path) -> Any:
        """Create mock AbuseIPDB handler with temporary cache directory."""
        return MockAbuseIPDBHandler("test_key", tmp_path)

    def test_abuseipdb_check_ip_caches_results(self, mock_abuseipdb) -> None:
        """Mock AbuseIPDB should cache results properly."""
        ip = "192.168.1.100"

        result1 = mock_abuseipdb.check_ip(ip)
        result2 = mock_abuseipdb.check_ip(ip)

        # Results should be identical
        assert result1 == result2

        # Cache file should exist
        cache_file = mock_abuseipdb.cache_dir / f"abuse_{ip}_90.json"
        assert cache_file.exists()

    def test_abuseipdb_check_ip_handles_private_ips(self, mock_abuseipdb) -> None:
        """Mock AbuseIPDB should return low risk for private IPs."""
        private_ips = ["192.168.1.1", "10.0.0.1", "127.0.0.1"]

        for ip in private_ips:
            result = mock_abuseipdb.check_ip(ip)
            assert result["data"]["abuseConfidenceScore"] == 0
            assert result["data"]["totalReports"] == 0
            assert result["data"]["isWhitelisted"] is True

    def test_abuseipdb_check_ip_handles_known_good_ips(self, mock_abuseipdb) -> None:
        """Mock AbuseIPDB should return low risk for known good IPs."""
        good_ips = ["8.8.8.8", "1.1.1.1"]

        for ip in good_ips:
            result = mock_abuseipdb.check_ip(ip)
            assert result["data"]["abuseConfidenceScore"] == 0
            assert result["data"]["isWhitelisted"] is True

    def test_abuseipdb_check_ip_handles_suspicious_ips(self, mock_abuseipdb) -> None:
        """Mock AbuseIPDB should return high risk for suspicious IPs."""
        suspicious_ips = ["203.0.113.1", "198.51.100.1"]

        for ip in suspicious_ips:
            result = mock_abuseipdb.check_ip(ip)
            assert result["data"]["abuseConfidenceScore"] > 50
            assert result["data"]["totalReports"] > 0
            assert len(result["data"]["reports"]) > 0

    def test_abuseipdb_rate_limiting(self, mock_abuseipdb) -> None:
        """Mock AbuseIPDB should implement rate limiting."""
        # Make requests up to the limit
        for i in range(4):
            result = mock_abuseipdb.check_ip(f"192.168.1.{i}")
            assert "error" not in result

        # Next request should be rate limited
        result = mock_abuseipdb.check_ip("192.168.1.999")
        assert result == {"error": "rate_limit"}

    def test_abuseipdb_quota_exceeded(self, mock_abuseipdb) -> None:
        """Mock AbuseIPDB should handle quota exceeded."""
        mock_abuseipdb.set_quota_exceeded(True)

        result = mock_abuseipdb.check_ip("192.168.1.100")
        assert result == {"error": "quota_exceeded"}

        # Reset and test normal operation
        mock_abuseipdb.set_quota_exceeded(False)
        result = mock_abuseipdb.check_ip("192.168.1.100")
        assert "error" not in result

    def test_abuseipdb_custom_max_age(self, mock_abuseipdb) -> None:
        """Mock AbuseIPDB should handle different max age parameters."""
        ip = "192.168.1.100"

        # Different max_age should create different cache files
        result1 = mock_abuseipdb.check_ip(ip, max_age_days=30)
        result2 = mock_abuseipdb.check_ip(ip, max_age_days=90)

        cache_file_30 = mock_abuseipdb.cache_dir / f"abuse_{ip}_30.json"
        cache_file_90 = mock_abuseipdb.cache_dir / f"abuse_{ip}_90.json"

        assert cache_file_30.exists()
        assert cache_file_90.exists()

        # Results should be different due to different parameters
        assert result1 != result2


class TestMockStatisticalAnalyzer:
    """Test mock statistical analyzer functionality."""

    @pytest.fixture
    def mock_analyzer(self) -> Any:
        """Create mock statistical analyzer."""
        # Mock database connection
        from unittest.mock import Mock

        mock_db = Mock()
        return MockStatisticalAnalyzer(mock_db)

    def test_analyze_upload_patterns(self, mock_analyzer) -> None:
        """Mock analyzer should return upload pattern analysis."""
        result = mock_analyzer.analyze_upload_patterns(days=30)

        required_keys = [
            "total_unique_files",
            "avg_sources_per_file",
            "most_distributed",
            "temporal_clustering",
            "file_type_distribution",
        ]

        for key in required_keys:
            assert key in result

        assert isinstance(result["total_unique_files"], int)
        assert isinstance(result["avg_sources_per_file"], float)
        assert isinstance(result["most_distributed"], list)
        assert isinstance(result["file_type_distribution"], dict)

    def test_analyze_attack_velocity(self, mock_analyzer) -> None:
        """Mock analyzer should return attack velocity analysis."""
        result = mock_analyzer.analyze_attack_velocity()

        required_keys = ["behavior_distribution", "avg_attack_duration", "persistence_score", "velocity_percentiles"]

        for key in required_keys:
            assert key in result

        assert isinstance(result["behavior_distribution"], dict)
        assert isinstance(result["avg_attack_duration"], float)
        assert isinstance(result["velocity_percentiles"], dict)

        # Check behavior distribution has expected categories
        expected_behaviors = ["human_like", "semi_automated", "automated", "aggressive_bot"]
        for behavior in expected_behaviors:
            assert behavior in result["behavior_distribution"]

    def test_detect_coordinated_attacks(self, mock_analyzer) -> None:
        """Mock analyzer should detect coordinated attacks."""
        result = mock_analyzer.detect_coordinated_attacks()

        assert isinstance(result, list)

        # Each result should have required fields
        for attack in result:
            required_fields = ["command", "ips", "timespan_minutes", "confidence"]
            for field in required_fields:
                assert field in attack

            assert isinstance(attack["ips"], list)
            assert len(attack["ips"]) >= 3  # Coordinated attacks need multiple IPs
            assert attack["confidence"] > 0.5

    def test_generate_threat_indicators(self, mock_analyzer) -> None:
        """Mock analyzer should generate threat indicators."""
        result = mock_analyzer.generate_threat_indicators()

        required_keys = ["high_risk_ips", "suspicious_files", "emerging_patterns", "zero_day_candidates"]

        for key in required_keys:
            assert key in result
            assert isinstance(result[key], list)

        # Check structure of high risk IPs
        for ip_info in result["high_risk_ips"]:
            required_fields = ["ip", "risk_score", "threat_types", "first_seen"]
            for field in required_fields:
                assert field in ip_info

            assert ip_info["risk_score"] > 0.5
            assert isinstance(ip_info["threat_types"], list)


class TestMockEnvironmentSetup:
    """Test mock environment setup functionality."""

    def test_create_mock_enrichment_handlers(self, tmp_path: Path) -> None:
        """Should create all mock handlers."""
        handlers = setup_mock_enrichment_environment(tmp_path)

        assert "otx" in handlers
        assert "abuseipdb" in handlers
        assert "statistical_analyzer" in handlers

        assert isinstance(handlers["otx"], MockOTXHandler)
        assert isinstance(handlers["abuseipdb"], MockAbuseIPDBHandler)
        assert handlers["statistical_analyzer"] is None  # No DB connection

    def test_setup_with_database(self, tmp_path: Path) -> None:
        """Should setup environment with database connection."""
        from unittest.mock import Mock

        mock_db = Mock()
        handlers = setup_mock_enrichment_environment(tmp_path, mock_db)

        assert handlers["statistical_analyzer"] is not None
        assert isinstance(handlers["statistical_analyzer"], MockStatisticalAnalyzer)

    def test_mock_handlers_integration(self, tmp_path: Path) -> None:
        """Mock handlers should work together in integration scenario."""
        handlers = setup_mock_enrichment_environment(tmp_path)

        # Test IP enrichment across multiple services
        test_ip = "203.0.113.100"

        otx_result = handlers["otx"].check_ip(test_ip)
        abuse_result = handlers["abuseipdb"].check_ip(test_ip)

        # Both should return valid results
        assert isinstance(otx_result, dict)
        assert isinstance(abuse_result, dict)

        # Should have expected structure
        assert "reputation" in otx_result
        assert "data" in abuse_result
        assert "abuseConfidenceScore" in abuse_result["data"]
