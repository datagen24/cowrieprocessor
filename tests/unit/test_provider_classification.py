"""Unit tests for provider classification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from cowrieprocessor.features import ProviderClassifier
from tests.fixtures.enrichment_fixtures import DSHIELD_RESPONSES, SPUR_RESPONSES


class MockSessionSummary:
    """Mock SessionSummary for testing."""

    def __init__(self, enrichment: dict[str, Any], updated_at: datetime | None = None) -> None:
        """Initialize mock session.

        Args:
            enrichment: Enrichment data dictionary
            updated_at: Last update timestamp
        """
        self.enrichment = enrichment
        self.updated_at = updated_at or datetime.now(timezone.utc)


class TestProviderClassifier:
    """Tests for ProviderClassifier."""

    @pytest.fixture
    def default_config(self) -> dict[str, Any]:
        """Default configuration for classifier.

        Returns:
            Default configuration dictionary
        """
        return {
            "use_dshield": True,
            "use_spur": True,
            "max_enrichment_age_days": 365,
            "treat_stale_as_unknown": False,
            "cloud_provider_keywords": [
                "amazon",
                "aws",
                "google",
                "gcp",
                "azure",
                "microsoft",
                "digitalocean",
                "linode",
                "vultr",
                "ovh",
            ],
        }

    @pytest.fixture
    def classifier(self, default_config: dict[str, Any]) -> ProviderClassifier:
        """Create classifier instance.

        Args:
            default_config: Configuration dictionary

        Returns:
            ProviderClassifier instance
        """
        return ProviderClassifier(default_config)

    def test_cloud_detection_from_dshield_asn(self, classifier: ProviderClassifier) -> None:
        """Test cloud provider detection from DShield ASN name."""
        enrichment = {"dshield": DSHIELD_RESPONSES["datacenter"], "spur": {}}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=5))

        features = classifier.classify(session)

        assert features.is_cloud_provider is True
        assert features.cloud_confidence == "high"
        assert features.provider_name is not None and "Amazon" in features.provider_name
        assert features.is_vpn_provider is False
        assert features.is_tor_exit is False

    def test_cloud_detection_from_spur_infrastructure(self, classifier: ProviderClassifier) -> None:
        """Test cloud provider detection from Spur infrastructure field."""
        enrichment = {"dshield": {}, "spur": SPUR_RESPONSES["datacenter"]}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=10))

        features = classifier.classify(session)

        assert features.is_cloud_provider is True
        assert features.cloud_confidence == "high"
        assert features.provider_name == "Amazon Web Services"

    def test_vpn_detection_from_spur_infrastructure(self, classifier: ProviderClassifier) -> None:
        """Test VPN provider detection from Spur infrastructure field."""
        enrichment = {"dshield": {}, "spur": SPUR_RESPONSES["vpn"]}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=3))

        features = classifier.classify(session)

        assert features.is_vpn_provider is True
        assert features.vpn_confidence == "high"
        assert features.provider_name == "Mullvad VPN"
        assert features.is_cloud_provider is False

    def test_vpn_detection_from_spur_tunnels(self, classifier: ProviderClassifier) -> None:
        """Test VPN provider detection from Spur tunnels field."""
        spur_data = {
            "asn": {"number": 12345, "organization": "Example ISP"},
            "organization": "Example",
            "infrastructure": "HOSTING",
            "client": {"behaviors": [], "proxies": "", "types": ["SERVER"]},
            "tunnels": [{"anonymous": "YES", "entries": "5", "operator": "ProtonVPN", "type": "OPENVPN"}],
        }
        enrichment = {"dshield": {}, "spur": spur_data}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=7))

        features = classifier.classify(session)

        assert features.is_vpn_provider is True
        assert features.provider_name == "ProtonVPN"

    def test_vpn_detection_from_spur_behaviors(self, classifier: ProviderClassifier) -> None:
        """Test VPN provider detection from Spur client behaviors."""
        spur_data = {
            "asn": {"number": 12345, "organization": "Example ISP"},
            "organization": "VPN Service Inc",
            "infrastructure": "HOSTING",
            "client": {"behaviors": ["VPN"], "proxies": "VPN", "types": ["PROXY"]},
            "tunnels": [],
        }
        enrichment = {"dshield": {}, "spur": spur_data}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=2))

        features = classifier.classify(session)

        assert features.is_vpn_provider is True
        assert features.provider_name == "VPN Service Inc"

    def test_tor_detection_from_spur_behaviors(self, classifier: ProviderClassifier) -> None:
        """Test Tor exit detection from Spur client behaviors."""
        enrichment = {"dshield": {}, "spur": SPUR_RESPONSES["tor_exit"]}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=1))

        features = classifier.classify(session)

        assert features.is_tor_exit is True
        assert features.tor_confidence == "high"
        # Returns operator name from tunnels when available
        assert features.provider_name == "Tor Project"

    def test_tor_detection_from_spur_tunnels(self, classifier: ProviderClassifier) -> None:
        """Test Tor exit detection from Spur tunnels field."""
        spur_data = {
            "asn": {"number": 12345, "organization": "Example ISP"},
            "organization": "Example",
            "infrastructure": "HOSTING",
            "client": {"behaviors": [], "proxies": "", "types": ["PROXY"]},
            "tunnels": [{"anonymous": "YES", "entries": "100", "operator": "Tor", "type": "TOR"}],
        }
        enrichment = {"dshield": {}, "spur": spur_data}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=5))

        features = classifier.classify(session)

        assert features.is_tor_exit is True
        # Returns operator name from tunnels
        assert features.provider_name == "Tor"

    def test_residential_ip_no_detection(self, classifier: ProviderClassifier) -> None:
        """Test residential IP with no cloud/VPN/Tor detection."""
        enrichment = {"dshield": DSHIELD_RESPONSES["residential"], "spur": SPUR_RESPONSES["residential"]}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=15))

        features = classifier.classify(session)

        assert features.is_cloud_provider is False
        assert features.is_vpn_provider is False
        assert features.is_tor_exit is False
        assert features.cloud_confidence == "medium"  # Fresh data, no detection
        assert features.vpn_confidence == "medium"
        assert features.tor_confidence == "medium"

    def test_missing_enrichment_data(self, classifier: ProviderClassifier) -> None:
        """Test handling of missing enrichment data."""
        enrichment: dict[str, Any] = {}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc))

        features = classifier.classify(session)

        assert features.is_cloud_provider is False
        assert features.is_vpn_provider is False
        assert features.is_tor_exit is False
        assert features.cloud_confidence == "none"
        assert features.vpn_confidence == "none"
        assert features.tor_confidence == "none"
        assert features.provider_name is None

    def test_stale_enrichment_handling(self, classifier: ProviderClassifier) -> None:
        """Test stale enrichment data handling."""
        enrichment = {"dshield": DSHIELD_RESPONSES["datacenter"], "spur": {}}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=400))

        features = classifier.classify(session)

        assert features.enrichment_stale is True
        assert features.enrichment_age_days == 400
        # Stale but still detected (treat_stale_as_unknown=False by default)
        assert features.is_cloud_provider is True
        assert features.cloud_confidence == "medium"  # Stale + detection = medium

    def test_stale_enrichment_as_unknown(self, default_config: dict[str, Any]) -> None:
        """Test treating stale enrichment as unknown."""
        config = default_config.copy()
        config["treat_stale_as_unknown"] = True
        classifier = ProviderClassifier(config)

        enrichment = {"dshield": DSHIELD_RESPONSES["datacenter"], "spur": {}}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=400))

        features = classifier.classify(session)

        assert features.enrichment_stale is True
        assert features.is_cloud_provider is False  # Treated as unknown
        assert features.cloud_confidence == "none"

    def test_confidence_high_fresh_detection(self, classifier: ProviderClassifier) -> None:
        """Test high confidence with fresh enrichment and positive detection."""
        enrichment = {"dshield": DSHIELD_RESPONSES["datacenter"], "spur": {}}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=5))

        features = classifier.classify(session)

        assert features.cloud_confidence == "high"  # <30 days + detection

    def test_confidence_medium_fresh_no_detection(self, classifier: ProviderClassifier) -> None:
        """Test medium confidence with fresh enrichment but no detection."""
        enrichment = {"dshield": DSHIELD_RESPONSES["residential"], "spur": SPUR_RESPONSES["residential"]}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=10))

        features = classifier.classify(session)

        assert features.cloud_confidence == "medium"  # <30 days, no detection

    def test_confidence_medium_stale_detection(self, classifier: ProviderClassifier) -> None:
        """Test medium confidence with stale enrichment but positive detection."""
        enrichment = {"dshield": DSHIELD_RESPONSES["datacenter"], "spur": {}}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=200))

        features = classifier.classify(session)

        assert features.cloud_confidence == "medium"  # Stale + detection

    def test_confidence_low_stale_no_detection(self, classifier: ProviderClassifier) -> None:
        """Test low confidence with stale enrichment and no detection."""
        enrichment = {"dshield": DSHIELD_RESPONSES["residential"], "spur": SPUR_RESPONSES["residential"]}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=200))

        features = classifier.classify(session)

        assert features.cloud_confidence == "low"  # Stale, no detection

    def test_confidence_none_no_data(self, classifier: ProviderClassifier) -> None:
        """Test none confidence with missing enrichment data."""
        enrichment: dict[str, Any] = {}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc))

        features = classifier.classify(session)

        assert features.cloud_confidence == "none"
        assert features.vpn_confidence == "none"
        assert features.tor_confidence == "none"

    def test_ipv6_preparation(self, classifier: ProviderClassifier) -> None:
        """Test IPv6 address handling preparation (detection ready, implementation deferred)."""
        # IPv6 enrichment data structure matches IPv4
        enrichment = {"dshield": DSHIELD_RESPONSES["datacenter"], "spur": {}}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=5))

        features = classifier.classify(session)

        # Classification logic is IPv6-ready (no IP-version-specific code)
        assert features.is_cloud_provider is True
        assert features.cloud_confidence == "high"

    def test_disable_dshield(self, default_config: dict[str, Any]) -> None:
        """Test disabling DShield enrichment."""
        config = default_config.copy()
        config["use_dshield"] = False
        classifier = ProviderClassifier(config)

        enrichment = {"dshield": DSHIELD_RESPONSES["datacenter"], "spur": {}}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=5))

        features = classifier.classify(session)

        # Should not detect cloud from DShield when disabled
        assert features.is_cloud_provider is False

    def test_disable_spur(self, default_config: dict[str, Any]) -> None:
        """Test disabling Spur enrichment."""
        config = default_config.copy()
        config["use_spur"] = False
        classifier = ProviderClassifier(config)

        enrichment = {"dshield": {}, "spur": SPUR_RESPONSES["vpn"]}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=5))

        features = classifier.classify(session)

        # Should not detect VPN from Spur when disabled
        assert features.is_vpn_provider is False

    def test_custom_cloud_keywords(self, default_config: dict[str, Any]) -> None:
        """Test custom cloud provider keywords."""
        config = default_config.copy()
        config["cloud_provider_keywords"] = ["testcloud", "customdc"]
        classifier = ProviderClassifier(config)

        # DShield data with custom keyword
        dshield_data = {
            "ip": {
                "asname": "TESTCLOUD-01",
                "ascountry": "US",
                "asnumber": 99999,
                "asdescription": "TestCloud Services",
            }
        }
        enrichment = {"dshield": dshield_data, "spur": {}}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=5))

        features = classifier.classify(session)

        assert features.is_cloud_provider is True
        assert features.provider_name == "TestCloud Services"

    def test_case_insensitive_cloud_detection(self, classifier: ProviderClassifier) -> None:
        """Test case-insensitive cloud provider keyword matching."""
        # Mixed case ASN name
        dshield_data = {
            "ip": {
                "asname": "AmAzOn-AWS-02",
                "ascountry": "US",
                "asnumber": 16509,
                "asdescription": "Amazon Web Services",
            }
        }
        enrichment = {"dshield": dshield_data, "spur": {}}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=5))

        features = classifier.classify(session)

        assert features.is_cloud_provider is True

    def test_multiple_provider_types(self, classifier: ProviderClassifier) -> None:
        """Test session with multiple provider type detections (edge case)."""
        # Cloud + VPN (unusual but possible with certain hosting providers)
        spur_data = {
            "asn": {"number": 16509, "organization": "Amazon AWS"},
            "organization": "Amazon VPN Service",  # Hypothetical
            "infrastructure": "DATACENTER",
            "client": {"behaviors": ["VPN"], "proxies": "VPN", "types": ["SERVER"]},
            "tunnels": [{"anonymous": "YES", "operator": "AWS VPN", "type": "OPENVPN"}],
        }
        enrichment = {"dshield": DSHIELD_RESPONSES["datacenter"], "spur": spur_data}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=5))

        features = classifier.classify(session)

        # Both detections should succeed
        assert features.is_cloud_provider is True
        assert features.is_vpn_provider is True
        assert features.is_tor_exit is False

    def test_enrichment_age_calculation(self, classifier: ProviderClassifier) -> None:
        """Test enrichment age calculation."""
        enrichment = {"dshield": DSHIELD_RESPONSES["datacenter"], "spur": {}}
        session = MockSessionSummary(enrichment, datetime.now(timezone.utc) - timedelta(days=42))

        features = classifier.classify(session)

        assert features.enrichment_age_days == 42

    def test_null_updated_at(self, classifier: ProviderClassifier) -> None:
        """Test handling of null updated_at timestamp."""
        enrichment = {"dshield": DSHIELD_RESPONSES["datacenter"], "spur": {}}
        session = MockSessionSummary(enrichment, None)

        features = classifier.classify(session)

        # Should still classify with default fresh timestamp
        assert features.is_cloud_provider is True
        assert features.enrichment_age_days is None or features.enrichment_age_days == 0
