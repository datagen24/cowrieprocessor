"""Unit tests for residential ISP heuristic matcher."""

from __future__ import annotations

import pytest

from cowrieprocessor.enrichment.ip_classification.residential_heuristic import ResidentialHeuristic


class TestResidentialHeuristic:
    """Test ResidentialHeuristic class."""

    @pytest.fixture
    def heuristic(self) -> ResidentialHeuristic:
        """Create residential heuristic."""
        return ResidentialHeuristic()

    def test_initialization(self, heuristic: ResidentialHeuristic) -> None:
        """Test heuristic initialization."""
        assert len(heuristic._strong_patterns) > 0
        assert len(heuristic._weak_patterns) > 0
        assert len(heuristic._exclusion_patterns) > 0
        assert heuristic._stats_lookups == 0

    def test_match_comcast_cable(self, heuristic: ResidentialHeuristic) -> None:
        """Test matching Comcast Cable Communications."""
        result = heuristic.match("1.2.3.4", asn=7922, as_name="Comcast Cable Communications")

        assert result is not None
        assert result["asn"] == 7922
        assert result["as_name"] == "Comcast Cable Communications"
        assert result["confidence"] >= 0.7
        assert result["pattern_type"] in ["strong_single", "strong_multiple"]

    def test_match_verizon_wireless(self, heuristic: ResidentialHeuristic) -> None:
        """Test matching Verizon Wireless."""
        result = heuristic.match("1.2.3.4", asn=22394, as_name="Verizon Wireless")

        assert result is not None
        assert result["confidence"] >= 0.7

    def test_match_att_mobility(self, heuristic: ResidentialHeuristic) -> None:
        """Test matching AT&T Mobility."""
        result = heuristic.match("1.2.3.4", asn=20057, as_name="AT&T Mobility LLC")

        assert result is not None
        assert result["confidence"] >= 0.7

    def test_match_broadband_isp(self, heuristic: ResidentialHeuristic) -> None:
        """Test matching ISP with 'broadband' keyword."""
        result = heuristic.match("1.2.3.4", asn=12345, as_name="Example Broadband Internet Services")

        assert result is not None
        assert result["confidence"] >= 0.7

    def test_match_telecom_provider(self, heuristic: ResidentialHeuristic) -> None:
        """Test matching telecom provider."""
        result = heuristic.match("1.2.3.4", asn=54321, as_name="Regional Telecommunications Company")

        assert result is not None
        assert result["confidence"] >= 0.7

    def test_match_mobile_network(self, heuristic: ResidentialHeuristic) -> None:
        """Test matching mobile network."""
        result = heuristic.match("1.2.3.4", asn=11111, as_name="Mobile Network Services")

        assert result is not None
        assert result["confidence"] >= 0.7

    def test_match_fiber_isp(self, heuristic: ResidentialHeuristic) -> None:
        """Test matching fiber ISP."""
        result = heuristic.match("1.2.3.4", asn=22222, as_name="Fiber Internet Provider")

        assert result is not None
        assert result["confidence"] >= 0.7

    def test_match_weak_pattern(self, heuristic: ResidentialHeuristic) -> None:
        """Test matching weak residential pattern."""
        result = heuristic.match("1.2.3.4", asn=33333, as_name="Generic Internet Service Provider")

        assert result is not None
        assert result["confidence"] == 0.5
        assert result["pattern_type"] == "weak"

    def test_match_excluded_hosting_provider(self, heuristic: ResidentialHeuristic) -> None:
        """Test that hosting providers are excluded."""
        result = heuristic.match("1.2.3.4", asn=44444, as_name="Web Hosting Services LLC")

        assert result is None

    def test_match_excluded_datacenter(self, heuristic: ResidentialHeuristic) -> None:
        """Test that datacenters are excluded."""
        result = heuristic.match("1.2.3.4", asn=55555, as_name="Datacenter Infrastructure Inc")

        assert result is None

    def test_match_excluded_cloud_provider(self, heuristic: ResidentialHeuristic) -> None:
        """Test that cloud providers are excluded."""
        result = heuristic.match("1.2.3.4", asn=16509, as_name="Amazon.com Cloud Services")

        assert result is None

    def test_match_excluded_cdn(self, heuristic: ResidentialHeuristic) -> None:
        """Test that CDN providers are excluded."""
        result = heuristic.match("1.2.3.4", asn=13335, as_name="Cloudflare Content Delivery Network")

        assert result is None

    def test_match_without_asn_name(self, heuristic: ResidentialHeuristic) -> None:
        """Test matching without AS name returns None."""
        result = heuristic.match("1.2.3.4", asn=7922, as_name=None)

        assert result is None

    def test_match_empty_asn_name(self, heuristic: ResidentialHeuristic) -> None:
        """Test matching with empty AS name returns None."""
        result = heuristic.match("1.2.3.4", asn=7922, as_name="")

        assert result is None

    def test_match_unknown_pattern(self, heuristic: ResidentialHeuristic) -> None:
        """Test matching unknown pattern returns None."""
        result = heuristic.match("1.2.3.4", asn=99999, as_name="Unknown Network Operator")

        assert result is None

    def test_case_insensitive_matching(self, heuristic: ResidentialHeuristic) -> None:
        """Test that pattern matching is case-insensitive."""
        result1 = heuristic.match("1.2.3.4", asn=7922, as_name="COMCAST CABLE")
        result2 = heuristic.match("1.2.3.4", asn=7922, as_name="comcast cable")
        result3 = heuristic.match("1.2.3.4", asn=7922, as_name="Comcast Cable")

        assert result1 is not None
        assert result2 is not None
        assert result3 is not None
        assert result1["confidence"] == result2["confidence"] == result3["confidence"]

    def test_multiple_strong_patterns(self, heuristic: ResidentialHeuristic) -> None:
        """Test matching multiple strong patterns increases confidence."""
        result = heuristic.match("1.2.3.4", asn=12345, as_name="Comcast Cable Broadband Telecommunications")

        assert result is not None
        assert result["confidence"] == 0.8  # Multiple strong indicators
        assert result["pattern_type"] == "strong_multiple"

    def test_get_stats(self, heuristic: ResidentialHeuristic) -> None:
        """Test get_stats() returns correct statistics."""
        heuristic.match("1.2.3.4", asn=7922, as_name="Comcast Cable")
        heuristic.match("2.3.4.5", asn=16509, as_name="Amazon Cloud")
        heuristic.match("3.4.5.6", asn=99999, as_name="Unknown Network")

        stats = heuristic.get_stats()
        assert stats["lookups"] == 3
        assert stats["hits"] == 1
        assert stats["excluded"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 1.0 / 3.0
        assert stats["exclusion_rate"] == 1.0 / 3.0

    def test_statistics_tracking(self, heuristic: ResidentialHeuristic) -> None:
        """Test that match() updates statistics correctly."""
        assert heuristic._stats_lookups == 0

        heuristic.match("1.2.3.4", asn=7922, as_name="Comcast Cable")
        assert heuristic._stats_lookups == 1
        assert heuristic._stats_hits == 1

        heuristic.match("2.3.4.5", asn=16509, as_name="Amazon Cloud")
        assert heuristic._stats_lookups == 2
        assert heuristic._stats_excluded == 1

        heuristic.match("3.4.5.6", asn=99999, as_name="Unknown")
        assert heuristic._stats_lookups == 3
        assert heuristic._stats_misses == 1
