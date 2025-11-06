"""Unit tests for cascade enrichment orchestrator.

Tests cover:
- Sequential cascade logic with early termination
- Freshness checks with source-specific TTLs
- Result merging with source priority rules
- Cache hit/miss scenarios
- Graceful degradation (GreyNoise quota exhausted)
- Database update logic
- Statistics tracking
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import IntegrityError

from cowrieprocessor.db.models import IPInventory
from cowrieprocessor.enrichment.cascade_enricher import CascadeEnricher, CascadeStats
from cowrieprocessor.enrichment.cymru_client import CymruResult
from cowrieprocessor.enrichment.greynoise_client import GreyNoiseResult
from cowrieprocessor.enrichment.maxmind_client import MaxMindResult


@pytest.fixture
def mock_session() -> Mock:
    """Mock SQLAlchemy session."""
    session = Mock()
    session.query = Mock()
    session.add = Mock()
    session.flush = Mock()
    session.commit = Mock()
    session.rollback = Mock()
    return session


@pytest.fixture
def mock_maxmind() -> Mock:
    """Mock MaxMind client."""
    client = Mock()
    client.get_database_age = Mock(return_value=timedelta(days=2))
    return client


@pytest.fixture
def mock_cymru() -> Mock:
    """Mock Cymru client."""
    return Mock()


@pytest.fixture
def mock_greynoise() -> Mock:
    """Mock GreyNoise client."""
    return Mock()


@pytest.fixture
def cascade_enricher(mock_maxmind: Mock, mock_cymru: Mock, mock_greynoise: Mock, mock_session: Mock) -> CascadeEnricher:
    """Create CascadeEnricher with mocked clients."""
    return CascadeEnricher(
        maxmind=mock_maxmind,
        cymru=mock_cymru,
        greynoise=mock_greynoise,
        session=mock_session,
    )


class TestCascadeEnricher:
    """Test suite for CascadeEnricher class."""

    def test_init(self, cascade_enricher: CascadeEnricher) -> None:
        """Test enricher initialization."""
        assert cascade_enricher.maxmind is not None
        assert cascade_enricher.cymru is not None
        assert cascade_enricher.greynoise is not None
        assert cascade_enricher.session is not None
        assert isinstance(cascade_enricher._stats, CascadeStats)

    def test_enrich_ip_cache_hit_fresh(self, cascade_enricher: CascadeEnricher, mock_session: Mock) -> None:
        """Test cache hit with fresh data - no external lookups."""
        now = datetime.now(timezone.utc)
        cached_inventory = IPInventory(
            ip_address="1.2.3.4",
            current_asn=15169,
            enrichment={
                "maxmind": {
                    "country": "US",
                    "asn": 15169,
                    "cached_at": now.isoformat(),
                }
            },
            enrichment_updated_at=now - timedelta(days=1),  # Fresh (< 7 days)
            first_seen=now - timedelta(days=10),
            last_seen=now - timedelta(days=1),
            session_count=5,
        )

        # Mock query to return cached data
        query_mock = Mock()
        filter_mock = Mock()
        filter_mock.first = Mock(return_value=cached_inventory)
        query_mock.filter = Mock(return_value=filter_mock)
        mock_session.query = Mock(return_value=query_mock)

        result = cascade_enricher.enrich_ip("1.2.3.4")

        # Should return cached data without lookups
        assert result == cached_inventory
        assert cascade_enricher._stats.cache_hits == 1
        assert cascade_enricher._stats.total_ips == 1
        assert cascade_enricher.maxmind.lookup_ip.call_count == 0  # type: ignore[attr-defined]
        assert cascade_enricher.greynoise.lookup_ip.call_count == 0  # type: ignore[attr-defined]

    def test_enrich_ip_maxmind_complete(
        self, cascade_enricher: CascadeEnricher, mock_maxmind: Mock, mock_cymru: Mock, mock_session: Mock
    ) -> None:
        """Test MaxMind provides complete data - no Cymru fallback needed."""
        # No cached data
        query_mock = Mock()
        filter_mock = Mock()
        filter_mock.first = Mock(return_value=None)
        query_mock.filter = Mock(return_value=filter_mock)
        mock_session.query = Mock(return_value=query_mock)

        # MaxMind returns complete data (geo + ASN)
        maxmind_result = MaxMindResult(
            ip_address="8.8.8.8",
            country_code="US",
            country_name="United States",
            city="Mountain View",
            latitude=37.386,
            longitude=-122.084,
            asn=15169,
            asn_org="GOOGLE",
            accuracy_radius=1000,
        )
        mock_maxmind.lookup_ip = Mock(return_value=maxmind_result)

        # Mock GreyNoise (independent)
        greynoise_result = GreyNoiseResult(
            ip_address="8.8.8.8",
            noise=False,
            riot=True,
            classification="benign",
        )
        cascade_enricher.greynoise.lookup_ip = Mock(return_value=greynoise_result)

        result = cascade_enricher.enrich_ip("8.8.8.8")

        # Verify MaxMind called, Cymru NOT called (early termination)
        assert mock_maxmind.lookup_ip.call_count == 1  # type: ignore[attr-defined]
        assert mock_cymru.lookup_asn.call_count == 0  # type: ignore[attr-defined]

        # Verify result has MaxMind data
        assert result.ip_address == "8.8.8.8"
        assert result.current_asn == 15169
        assert result.enrichment["maxmind"]["country"] == "US"
        assert result.enrichment["maxmind"]["asn"] == 15169

        # Verify stats
        assert cascade_enricher._stats.maxmind_hits == 1
        assert cascade_enricher._stats.cymru_hits == 0
        assert cascade_enricher._stats.greynoise_hits == 1

    def test_enrich_ip_maxmind_partial_cymru_fallback(
        self,
        cascade_enricher: CascadeEnricher,
        mock_maxmind: Mock,
        mock_cymru: Mock,
        mock_session: Mock,
    ) -> None:
        """Test MaxMind partial data (no ASN) triggers Cymru fallback."""
        # No cached data
        query_mock = Mock()
        filter_mock = Mock()
        filter_mock.first = Mock(return_value=None)
        query_mock.filter = Mock(return_value=filter_mock)
        mock_session.query = Mock(return_value=query_mock)

        # MaxMind returns geo but NO ASN
        maxmind_result = MaxMindResult(
            ip_address="203.0.113.1",
            country_code="CN",
            country_name="China",
            city="Beijing",
            latitude=39.9075,
            longitude=116.3972,
            asn=None,  # Missing ASN
            asn_org=None,
            accuracy_radius=50,
        )
        mock_maxmind.lookup_ip = Mock(return_value=maxmind_result)  # type: ignore[method-assign]

        # Cymru provides ASN fallback
        cymru_result = CymruResult(
            ip_address="203.0.113.1",
            asn=4134,
            asn_org="CHINANET-BACKBONE",
            country_code="CN",
            registry="APNIC",
        )
        mock_cymru.lookup_asn = Mock(return_value=cymru_result)  # type: ignore[method-assign]

        # Mock GreyNoise
        cascade_enricher.greynoise.lookup_ip = Mock(return_value=None)  # type: ignore[method-assign]

        result = cascade_enricher.enrich_ip("203.0.113.1")

        # Verify both MaxMind and Cymru called
        assert mock_maxmind.lookup_ip.call_count == 1  # type: ignore[attr-defined]
        assert mock_cymru.lookup_asn.call_count == 1  # type: ignore[attr-defined]

        # Verify result has both sources
        assert result.enrichment["maxmind"]["country"] == "CN"
        assert result.enrichment["maxmind"]["asn"] is None
        assert result.enrichment["cymru"]["asn"] == 4134
        assert result.current_asn == 4134  # Cymru ASN used

        # Verify stats
        assert cascade_enricher._stats.maxmind_hits == 1
        assert cascade_enricher._stats.cymru_hits == 1

    def test_enrich_ip_greynoise_failure_graceful(
        self, cascade_enricher: CascadeEnricher, mock_maxmind: Mock, mock_session: Mock
    ) -> None:
        """Test graceful degradation when GreyNoise quota exhausted."""
        # No cached data
        query_mock = Mock()
        filter_mock = Mock()
        filter_mock.first = Mock(return_value=None)
        query_mock.filter = Mock(return_value=filter_mock)
        mock_session.query = Mock(return_value=query_mock)

        # MaxMind succeeds
        maxmind_result = MaxMindResult(
            ip_address="192.0.2.1",
            country_code="US",
            country_name="United States",
            city=None,
            latitude=None,
            longitude=None,
            asn=7018,
            asn_org="ATT-INTERNET4",
            accuracy_radius=None,
        )
        mock_maxmind.lookup_ip = Mock(return_value=maxmind_result)

        # GreyNoise fails (quota exhausted)
        cascade_enricher.greynoise.lookup_ip = Mock(side_effect=Exception("Quota exceeded"))

        result = cascade_enricher.enrich_ip("192.0.2.1")

        # Should still have MaxMind data, no GreyNoise data
        assert result.enrichment["maxmind"]["asn"] == 7018
        assert "greynoise" not in result.enrichment

        # Error should NOT fail the entire enrichment
        assert cascade_enricher._stats.maxmind_hits == 1

    def test_enrich_ip_all_failures_minimal_record(
        self, cascade_enricher: CascadeEnricher, mock_maxmind: Mock, mock_cymru: Mock, mock_session: Mock
    ) -> None:
        """Test all lookups fail - create minimal record."""
        # No cached data
        query_mock = Mock()
        filter_mock = Mock()
        filter_mock.first = Mock(return_value=None)
        query_mock.filter = Mock(return_value=filter_mock)
        mock_session.query = Mock(return_value=query_mock)

        # All lookups return None - will cause exception and create minimal record
        mock_maxmind.lookup_ip = Mock(return_value=None)
        mock_cymru.lookup_asn = Mock(return_value=None)
        cascade_enricher.greynoise.lookup_ip = Mock(return_value=None)

        result = cascade_enricher.enrich_ip("198.51.100.1")

        # Should create record with IP address even when all lookups fail
        assert result.ip_address == "198.51.100.1"  # Got IP from parameter
        assert result.enrichment == {}
        assert result.session_count == 1

    def test_enrich_ip_update_existing(
        self, cascade_enricher: CascadeEnricher, mock_maxmind: Mock, mock_session: Mock
    ) -> None:
        """Test updating existing stale record."""
        now = datetime.now(timezone.utc)
        cached_inventory = IPInventory(
            ip_address="1.1.1.1",
            current_asn=None,
            enrichment={"maxmind": {"country": "OLD"}},  # Has enrichment data (will trigger staleness check)
            enrichment_updated_at=now - timedelta(days=10),  # Stale (>7 days for MaxMind)
            first_seen=now - timedelta(days=30),
            last_seen=now - timedelta(days=10),
            session_count=3,
        )

        # Mock query to return stale cached data
        query_mock = Mock()
        filter_mock = Mock()
        filter_mock.first = Mock(return_value=cached_inventory)
        query_mock.filter = Mock(return_value=filter_mock)
        mock_session.query = Mock(return_value=query_mock)

        # Mock MaxMind DB age to be stale (>7 days)
        cascade_enricher.maxmind.get_database_age = Mock(return_value=timedelta(days=10))

        # MaxMind provides new data
        maxmind_result = MaxMindResult(
            ip_address="1.1.1.1",
            country_code="AU",
            country_name="Australia",
            city=None,
            latitude=None,
            longitude=None,
            asn=13335,
            asn_org="CLOUDFLARENET",
            accuracy_radius=None,
        )
        mock_maxmind.lookup_ip = Mock(return_value=maxmind_result)
        cascade_enricher.greynoise.lookup_ip = Mock(return_value=None)

        result = cascade_enricher.enrich_ip("1.1.1.1")

        # Should update existing record
        assert result == cached_inventory
        assert result.current_asn == 13335
        assert result.enrichment["maxmind"]["country"] == "AU"
        assert result.session_count == 4  # Incremented
        mock_session.flush.assert_called()

    def test_enrich_ip_integrity_error_recovery(
        self, cascade_enricher: CascadeEnricher, mock_maxmind: Mock, mock_session: Mock
    ) -> None:
        """Test race condition handling with IntegrityError."""
        # No cached data initially
        query_mock = Mock()
        filter_mock = Mock()

        # First call: No cached data
        # Second call (after rollback): Return cached data
        cached_inventory = IPInventory(
            ip_address="10.0.0.1",
            current_asn=12345,
            enrichment={"maxmind": {"country": "US"}},
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            session_count=1,
        )
        filter_mock.first = Mock(side_effect=[None, cached_inventory])
        query_mock.filter = Mock(return_value=filter_mock)
        mock_session.query = Mock(return_value=query_mock)

        # MaxMind succeeds
        maxmind_result = MaxMindResult(
            ip_address="10.0.0.1",
            country_code="US",
            country_name="United States",
            city=None,
            latitude=None,
            longitude=None,
            asn=12345,
            asn_org="TEST-AS",
            accuracy_radius=None,
        )
        mock_maxmind.lookup_ip = Mock(return_value=maxmind_result)
        cascade_enricher.greynoise.lookup_ip = Mock(return_value=None)

        # Flush raises IntegrityError (race condition)
        mock_session.flush = Mock(side_effect=IntegrityError("duplicate key", None, None))

        result = cascade_enricher.enrich_ip("10.0.0.1")

        # Should recover by re-querying
        assert result == cached_inventory
        mock_session.rollback.assert_called_once()

    def test_is_fresh_maxmind_stale_database(self, cascade_enricher: CascadeEnricher, mock_maxmind: Mock) -> None:
        """Test freshness check fails when MaxMind DB is stale."""
        now = datetime.now(timezone.utc)
        inventory = IPInventory(
            ip_address="1.2.3.4",
            enrichment={"maxmind": {"country": "US"}},
            enrichment_updated_at=now - timedelta(days=2),
        )

        # MaxMind DB is 10 days old (stale)
        mock_maxmind.get_database_age = Mock(return_value=timedelta(days=10))

        assert cascade_enricher._is_fresh(inventory) is False

    def test_is_fresh_cymru_ttl_exceeded(self, cascade_enricher: CascadeEnricher) -> None:
        """Test freshness check fails when Cymru TTL exceeded (>90 days)."""
        now = datetime.now(timezone.utc)
        inventory = IPInventory(
            ip_address="1.2.3.4",
            enrichment={"cymru": {"asn": 12345}},
            enrichment_updated_at=now - timedelta(days=91),  # Stale
        )

        assert cascade_enricher._is_fresh(inventory) is False

    def test_is_fresh_greynoise_ttl_exceeded(self, cascade_enricher: CascadeEnricher) -> None:
        """Test freshness check fails when GreyNoise TTL exceeded (>7 days)."""
        now = datetime.now(timezone.utc)
        inventory = IPInventory(
            ip_address="1.2.3.4",
            enrichment={"greynoise": {"noise": True}},
            enrichment_updated_at=now - timedelta(days=8),  # Stale
        )

        assert cascade_enricher._is_fresh(inventory) is False

    def test_is_fresh_all_sources_fresh(self, cascade_enricher: CascadeEnricher, mock_maxmind: Mock) -> None:
        """Test freshness check passes when all sources are fresh."""
        now = datetime.now(timezone.utc)
        inventory = IPInventory(
            ip_address="1.2.3.4",
            enrichment={
                "maxmind": {"country": "US"},
                "cymru": {"asn": 12345},
                "greynoise": {"noise": False},
            },
            enrichment_updated_at=now - timedelta(days=1),  # Fresh
        )

        # MaxMind DB is fresh
        mock_maxmind.get_database_age = Mock(return_value=timedelta(days=2))

        assert cascade_enricher._is_fresh(inventory) is True

    def test_merge_results_maxmind_only(self, cascade_enricher: CascadeEnricher) -> None:
        """Test merging results with MaxMind only."""
        maxmind_result = MaxMindResult(
            ip_address="8.8.8.8",
            country_code="US",
            country_name="United States",
            city="Mountain View",
            latitude=37.386,
            longitude=-122.084,
            asn=15169,
            asn_org="GOOGLE",
            accuracy_radius=1000,
        )

        result = cascade_enricher._merge_results(None, maxmind_result, None, None, "8.8.8.8")

        assert result.ip_address == "8.8.8.8"
        assert result.current_asn == 15169
        assert result.enrichment["maxmind"]["country"] == "US"
        assert result.enrichment["maxmind"]["asn"] == 15169
        assert "cymru" not in result.enrichment
        assert "greynoise" not in result.enrichment

    def test_merge_results_maxmind_cymru_fallback(self, cascade_enricher: CascadeEnricher) -> None:
        """Test merging with Cymru fallback when MaxMind has no ASN."""
        maxmind_result = MaxMindResult(
            ip_address="203.0.113.1",
            country_code="CN",
            country_name="China",
            city="Beijing",
            latitude=39.9075,
            longitude=116.3972,
            asn=None,  # No ASN
            asn_org=None,
            accuracy_radius=50,
        )

        cymru_result = CymruResult(
            ip_address="203.0.113.1",
            asn=4134,
            asn_org="CHINANET-BACKBONE",
            country_code="CN",
            registry="APNIC",
        )

        result = cascade_enricher._merge_results(None, maxmind_result, cymru_result, None, "203.0.113.1")

        # Should have both sources
        assert result.enrichment["maxmind"]["country"] == "CN"
        assert result.enrichment["maxmind"]["asn"] is None
        assert result.enrichment["cymru"]["asn"] == 4134
        assert result.current_asn == 4134  # Cymru ASN used

    def test_merge_results_all_sources(self, cascade_enricher: CascadeEnricher) -> None:
        """Test merging with all three sources."""
        maxmind_result = MaxMindResult(
            ip_address="1.1.1.1",
            country_code="AU",
            country_name="Australia",
            city=None,
            latitude=None,
            longitude=None,
            asn=13335,
            asn_org="CLOUDFLARENET",
            accuracy_radius=None,
        )

        greynoise_result = GreyNoiseResult(
            ip_address="1.1.1.1",
            noise=True,
            riot=False,
            classification="malicious",
        )

        result = cascade_enricher._merge_results(None, maxmind_result, None, greynoise_result, "1.1.1.1")

        # Should have both MaxMind and GreyNoise
        assert result.enrichment["maxmind"]["country"] == "AU"
        assert result.enrichment["maxmind"]["asn"] == 13335
        assert result.enrichment["greynoise"]["noise"] is True
        assert result.enrichment["greynoise"]["classification"] == "malicious"

    def test_merge_results_preserve_cached(self, cascade_enricher: CascadeEnricher) -> None:
        """Test merging preserves cached data when no new results."""
        now = datetime.now(timezone.utc)
        cached = IPInventory(
            ip_address="1.2.3.4",
            current_asn=7018,
            enrichment={"maxmind": {"country": "US", "asn": 7018}},
            enrichment_updated_at=now - timedelta(days=5),
            first_seen=now - timedelta(days=30),
            last_seen=now - timedelta(days=1),
            session_count=10,
        )

        result = cascade_enricher._merge_results(cached, None, None, None, "1.2.3.4")

        # Should preserve cached data
        assert result == cached
        assert result.enrichment["maxmind"]["country"] == "US"
        assert result.current_asn == 7018

    def test_backfill_missing_asns(
        self, cascade_enricher: CascadeEnricher, mock_cymru: Mock, mock_session: Mock
    ) -> None:
        """Test backfilling IPs with missing ASNs."""
        # Create IPs without ASNs
        ip1 = IPInventory(
            ip_address="1.2.3.4",
            current_asn=None,
            enrichment={},
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            session_count=1,
        )
        ip2 = IPInventory(
            ip_address="5.6.7.8",
            current_asn=None,
            enrichment={},
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            session_count=1,
        )

        # Mock query
        query_mock = Mock()
        filter_mock = Mock()
        limit_mock = Mock()
        limit_mock.all = Mock(return_value=[ip1, ip2])
        filter_mock.limit = Mock(return_value=limit_mock)
        query_mock.filter = Mock(return_value=filter_mock)
        mock_session.query = Mock(return_value=query_mock)

        # Cymru provides ASN data
        mock_cymru.lookup_asn = Mock(
            side_effect=[
                CymruResult(
                    ip_address="1.2.3.4",
                    asn=12345,
                    asn_org="TEST-AS-1",
                    country_code="US",
                    registry="ARIN",
                ),
                CymruResult(
                    ip_address="5.6.7.8",
                    asn=67890,
                    asn_org="TEST-AS-2",
                    country_code="DE",
                    registry="RIPE",
                ),
            ]
        )

        count = cascade_enricher.backfill_missing_asns(limit=10)

        assert count == 2
        assert ip1.current_asn == 12345
        assert ip2.current_asn == 67890
        mock_session.commit.assert_called_once()

    def test_refresh_stale_cymru(self, cascade_enricher: CascadeEnricher, mock_cymru: Mock, mock_session: Mock) -> None:
        """Test refreshing stale Cymru data (>90 days)."""
        now = datetime.now(timezone.utc)
        stale_ip = IPInventory(
            ip_address="1.2.3.4",
            current_asn=12345,
            enrichment={"cymru": {"asn": 12345}},
            enrichment_updated_at=now - timedelta(days=91),  # Stale
            first_seen=now - timedelta(days=100),
            last_seen=now - timedelta(days=1),
            session_count=5,
        )

        # Mock query
        query_mock = Mock()
        filter_mock = Mock()
        limit_mock = Mock()
        limit_mock.all = Mock(return_value=[stale_ip])
        filter_mock.limit = Mock(return_value=limit_mock)
        filter_mock.filter = Mock(return_value=filter_mock)
        query_mock.filter = Mock(return_value=filter_mock)
        mock_session.query = Mock(return_value=query_mock)

        # Cymru provides updated data
        mock_cymru.lookup_asn = Mock(
            return_value=CymruResult(
                ip_address="1.2.3.4",
                asn=12345,
                asn_org="UPDATED-ORG",
                country_code="US",
                registry="ARIN",
            )
        )

        results = cascade_enricher.refresh_stale_data(source="cymru", limit=10)

        assert results["cymru_refreshed"] == 1
        assert stale_ip.enrichment["cymru"]["asn_org"] == "UPDATED-ORG"
        mock_session.commit.assert_called_once()

    def test_get_stats(self, cascade_enricher: CascadeEnricher) -> None:
        """Test getting cascade statistics."""
        cascade_enricher._stats.total_ips = 100
        cascade_enricher._stats.cache_hits = 75
        cascade_enricher._stats.maxmind_hits = 20
        cascade_enricher._stats.cymru_hits = 3
        cascade_enricher._stats.greynoise_hits = 22

        stats = cascade_enricher.get_stats()

        assert stats.total_ips == 100
        assert stats.cache_hits == 75
        assert stats.maxmind_hits == 20
        assert stats.cymru_hits == 3
        assert stats.greynoise_hits == 22

    def test_reset_stats(self, cascade_enricher: CascadeEnricher) -> None:
        """Test resetting cascade statistics."""
        cascade_enricher._stats.total_ips = 100
        cascade_enricher._stats.cache_hits = 75

        cascade_enricher.reset_stats()

        stats = cascade_enricher.get_stats()
        assert stats.total_ips == 0
        assert stats.cache_hits == 0

    def test_create_minimal_inventory(self, cascade_enricher: CascadeEnricher) -> None:
        """Test creating minimal inventory record."""
        now = datetime.now(timezone.utc)
        result = cascade_enricher._create_minimal_inventory("192.0.2.1", now)

        assert result.ip_address == "192.0.2.1"
        assert result.enrichment == {}
        assert result.session_count == 1
        assert result.enrichment_version == "2.2"

    def test_refresh_greynoise_only(
        self, cascade_enricher: CascadeEnricher, mock_greynoise: Mock, mock_session: Mock
    ) -> None:
        """Test refreshing only GreyNoise data."""
        now = datetime.now(timezone.utc)
        stale_ip = IPInventory(
            ip_address="1.2.3.4",
            current_asn=15169,
            enrichment={"greynoise": {"noise": False, "riot": False}},
            enrichment_updated_at=now - timedelta(days=8),  # Stale GreyNoise
            first_seen=now - timedelta(days=30),
            last_seen=now,
            session_count=5,
        )
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [stale_ip]

        results = cascade_enricher.refresh_stale_data(source="greynoise", limit=10)

        assert results["greynoise_refreshed"] == 1
        assert results["cymru_refreshed"] == 0

    def test_backfill_missing_asns_exception(
        self, cascade_enricher: CascadeEnricher, mock_cymru: Mock, mock_session: Mock
    ) -> None:
        """Test backfill continues after exception."""
        ip1 = IPInventory(
            ip_address="1.2.3.4",
            current_asn=None,
            enrichment={},
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            session_count=1,
        )
        ip2 = IPInventory(
            ip_address="5.6.7.8",
            current_asn=None,
            enrichment={},
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            session_count=1,
        )
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [ip1, ip2]

        # First lookup raises exception, second succeeds
        mock_cymru.lookup_asn.side_effect = [
            Exception("Network error"),
            CymruResult("5.6.7.8", 7018, "ATT", "US", "ARIN"),
        ]

        count = cascade_enricher.backfill_missing_asns(limit=10)

        assert count == 1  # Only one succeeded
        assert mock_cymru.lookup_asn.call_count == 2

    def test_refresh_stale_data_exception(
        self, cascade_enricher: CascadeEnricher, mock_cymru: Mock, mock_session: Mock
    ) -> None:
        """Test refresh continues after exception."""
        now = datetime.now(timezone.utc)
        stale_ip = IPInventory(
            ip_address="1.2.3.4",
            current_asn=4134,
            enrichment={"cymru": {"asn": 4134, "asn_org": "OLD"}},
            enrichment_updated_at=now - timedelta(days=91),
            first_seen=now - timedelta(days=100),
            last_seen=now,
            session_count=5,
        )
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [stale_ip]
        mock_cymru.lookup_asn.side_effect = Exception("Timeout")

        results = cascade_enricher.refresh_stale_data(source="cymru", limit=10)

        assert results["cymru_refreshed"] == 0  # Failed
        assert mock_cymru.lookup_asn.call_count == 1

    def test_is_fresh_empty_enrichment(self, cascade_enricher: CascadeEnricher) -> None:
        """Test that empty enrichment is considered stale."""
        inventory = IPInventory(
            ip_address="1.2.3.4",
            current_asn=None,
            enrichment={},
            enrichment_updated_at=datetime.now(timezone.utc),
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            session_count=1,
        )

        assert not cascade_enricher._is_fresh(inventory)
