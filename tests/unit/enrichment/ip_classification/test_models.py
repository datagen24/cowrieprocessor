"""Unit tests for IP classification models (IPType enum, IPClassification dataclass)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cowrieprocessor.enrichment.ip_classification.models import IPClassification, IPType


class TestIPType:
    """Test IPType enum."""

    def test_enum_values(self) -> None:
        """Test that all enum values are correct."""
        assert IPType.TOR.value == "tor"
        assert IPType.CLOUD.value == "cloud"
        assert IPType.DATACENTER.value == "datacenter"
        assert IPType.RESIDENTIAL.value == "residential"
        assert IPType.UNKNOWN.value == "unknown"

    def test_enum_members(self) -> None:
        """Test that all expected enum members exist."""
        assert len(IPType) == 5
        assert IPType.TOR in IPType
        assert IPType.CLOUD in IPType
        assert IPType.DATACENTER in IPType
        assert IPType.RESIDENTIAL in IPType
        assert IPType.UNKNOWN in IPType

    def test_enum_comparison(self) -> None:
        """Test enum member comparison."""
        assert IPType.TOR == IPType.TOR
        assert IPType.TOR != IPType.CLOUD
        assert IPType.CLOUD != IPType.RESIDENTIAL

    def test_enum_from_string(self) -> None:
        """Test creating enum from string value."""
        assert IPType("tor") == IPType.TOR
        assert IPType("cloud") == IPType.CLOUD
        assert IPType("datacenter") == IPType.DATACENTER
        assert IPType("residential") == IPType.RESIDENTIAL
        assert IPType("unknown") == IPType.UNKNOWN

    def test_enum_invalid_value(self) -> None:
        """Test that invalid values raise ValueError."""
        with pytest.raises(ValueError, match="'invalid' is not a valid IPType"):
            IPType("invalid")


class TestIPClassification:
    """Test IPClassification dataclass."""

    def test_classification_creation_full_data(self) -> None:
        """Test creating classification with all fields."""
        now = datetime.now(timezone.utc)
        classification = IPClassification(
            ip_type=IPType.CLOUD,
            provider="aws",
            confidence=0.99,
            source="cloud_ranges_aws",
            classified_at=now,
        )

        assert classification.ip_type == IPType.CLOUD
        assert classification.provider == "aws"
        assert classification.confidence == 0.99
        assert classification.source == "cloud_ranges_aws"
        assert classification.classified_at == now

    def test_classification_creation_minimal_data(self) -> None:
        """Test creating classification with minimal required fields."""
        classification = IPClassification(
            ip_type=IPType.UNKNOWN, provider=None, confidence=0.0, source="none", classified_at=None
        )

        assert classification.ip_type == IPType.UNKNOWN
        assert classification.provider is None
        assert classification.confidence == 0.0
        assert classification.source == "none"
        assert classification.classified_at is not None  # Auto-populated

    def test_classification_auto_timestamp(self) -> None:
        """Test that classified_at is auto-populated if not provided."""
        before = datetime.now(timezone.utc)
        classification = IPClassification(
            ip_type=IPType.TOR,
            provider="tor",
            confidence=0.95,
            source="tor_bulk_list",
        )
        after = datetime.now(timezone.utc)

        assert classification.classified_at is not None
        assert before <= classification.classified_at <= after

    def test_classification_confidence_valid_range(self) -> None:
        """Test confidence validation accepts valid values."""
        # Test boundary values
        c1 = IPClassification(ip_type=IPType.UNKNOWN, provider=None, confidence=0.0, source="test")
        assert c1.confidence == 0.0

        c2 = IPClassification(ip_type=IPType.CLOUD, provider="test", confidence=0.5, source="test")
        assert c2.confidence == 0.5

        c3 = IPClassification(ip_type=IPType.CLOUD, provider="test", confidence=1.0, source="test")
        assert c3.confidence == 1.0

    def test_classification_confidence_below_zero(self) -> None:
        """Test that confidence < 0.0 raises ValueError."""
        with pytest.raises(ValueError, match="confidence must be between 0.0 and 1.0, got -0.1"):
            IPClassification(
                ip_type=IPType.UNKNOWN,
                provider=None,
                confidence=-0.1,
                source="test",
            )

    def test_classification_confidence_above_one(self) -> None:
        """Test that confidence > 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="confidence must be between 0.0 and 1.0, got 1.5"):
            IPClassification(
                ip_type=IPType.CLOUD,
                provider="test",
                confidence=1.5,
                source="test",
            )

    def test_classification_immutable(self) -> None:
        """Test that classification is frozen (immutable)."""
        classification = IPClassification(
            ip_type=IPType.CLOUD,
            provider="aws",
            confidence=0.99,
            source="cloud_ranges_aws",
        )

        with pytest.raises(Exception):  # FrozenInstanceError on Python 3.10+
            classification.ip_type = IPType.TOR  # type: ignore

        with pytest.raises(Exception):
            classification.confidence = 0.5  # type: ignore

    def test_classification_equality(self) -> None:
        """Test classification equality comparison."""
        now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        c1 = IPClassification(
            ip_type=IPType.CLOUD,
            provider="aws",
            confidence=0.99,
            source="cloud_ranges_aws",
            classified_at=now,
        )

        c2 = IPClassification(
            ip_type=IPType.CLOUD,
            provider="aws",
            confidence=0.99,
            source="cloud_ranges_aws",
            classified_at=now,
        )

        c3 = IPClassification(
            ip_type=IPType.CLOUD,
            provider="azure",
            confidence=0.99,
            source="cloud_ranges_azure",
            classified_at=now,
        )

        assert c1 == c2
        assert c1 != c3

    def test_classification_tor_example(self) -> None:
        """Test TOR exit node classification example."""
        classification = IPClassification(
            ip_type=IPType.TOR,
            provider="tor",
            confidence=0.95,
            source="tor_bulk_list",
        )

        assert classification.ip_type == IPType.TOR
        assert classification.provider == "tor"
        assert classification.confidence == 0.95
        assert classification.source == "tor_bulk_list"

    def test_classification_cloud_aws(self) -> None:
        """Test AWS cloud classification."""
        classification = IPClassification(
            ip_type=IPType.CLOUD,
            provider="aws",
            confidence=0.99,
            source="cloud_ranges_aws",
        )

        assert classification.ip_type == IPType.CLOUD
        assert classification.provider == "aws"
        assert classification.confidence == 0.99

    def test_classification_cloud_azure(self) -> None:
        """Test Azure cloud classification."""
        classification = IPClassification(
            ip_type=IPType.CLOUD,
            provider="azure",
            confidence=0.99,
            source="cloud_ranges_azure",
        )

        assert classification.ip_type == IPType.CLOUD
        assert classification.provider == "azure"

    def test_classification_cloud_gcp(self) -> None:
        """Test GCP cloud classification."""
        classification = IPClassification(
            ip_type=IPType.CLOUD,
            provider="gcp",
            confidence=0.99,
            source="cloud_ranges_gcp",
        )

        assert classification.ip_type == IPType.CLOUD
        assert classification.provider == "gcp"

    def test_classification_cloud_cloudflare(self) -> None:
        """Test CloudFlare classification."""
        classification = IPClassification(
            ip_type=IPType.CLOUD,
            provider="cloudflare",
            confidence=0.99,
            source="cloud_ranges_cloudflare",
        )

        assert classification.ip_type == IPType.CLOUD
        assert classification.provider == "cloudflare"

    def test_classification_datacenter(self) -> None:
        """Test datacenter classification."""
        classification = IPClassification(
            ip_type=IPType.DATACENTER,
            provider="digitalocean",
            confidence=0.75,
            source="datacenter_community_lists",
        )

        assert classification.ip_type == IPType.DATACENTER
        assert classification.provider == "digitalocean"
        assert classification.confidence == 0.75

    def test_classification_residential(self) -> None:
        """Test residential classification."""
        classification = IPClassification(
            ip_type=IPType.RESIDENTIAL,
            provider="Comcast Cable",
            confidence=0.8,
            source="asn_name_heuristic",
        )

        assert classification.ip_type == IPType.RESIDENTIAL
        assert classification.provider == "Comcast Cable"
        assert classification.confidence == 0.8

    def test_classification_unknown(self) -> None:
        """Test unknown classification."""
        classification = IPClassification(
            ip_type=IPType.UNKNOWN,
            provider=None,
            confidence=0.0,
            source="none",
        )

        assert classification.ip_type == IPType.UNKNOWN
        assert classification.provider is None
        assert classification.confidence == 0.0
        assert classification.source == "none"

    def test_classification_string_representation(self) -> None:
        """Test string representation of classification."""
        classification = IPClassification(
            ip_type=IPType.CLOUD,
            provider="aws",
            confidence=0.99,
            source="cloud_ranges_aws",
            classified_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        )

        repr_str = repr(classification)
        assert "IPClassification" in repr_str
        assert "ip_type" in repr_str or "IPType.CLOUD" in repr_str
        assert "aws" in repr_str
        assert "0.99" in repr_str
