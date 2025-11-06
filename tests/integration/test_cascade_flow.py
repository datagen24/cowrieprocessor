"""Integration tests for cascade enrichment workflows.

Tests end-to-end cascade flows with real clients (mocked APIs):
- Complete session IP enrichment
- Backfill missing ASNs workflow
- Refresh stale data workflow
- Database update integrity
- Multi-IP session handling
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from cowrieprocessor.db.models import Base, IPInventory, SessionSummary
from cowrieprocessor.enrichment.cascade_enricher import CascadeEnricher
from cowrieprocessor.enrichment.cymru_client import CymruClient, CymruResult
from cowrieprocessor.enrichment.greynoise_client import GreyNoiseClient, GreyNoiseResult
from cowrieprocessor.enrichment.maxmind_client import MaxMindClient, MaxMindResult


@pytest.fixture
def test_db_session():  # type: ignore[misc]
    """Create in-memory SQLite database session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def mock_maxmind_client() -> MaxMindClient:
    """Create mock MaxMind client with test data."""
    client = Mock(spec=MaxMindClient)
    client.get_database_age = Mock(return_value=timedelta(days=2))

    def lookup_ip(ip: str) -> MaxMindResult | None:
        """Mock MaxMind lookups with predefined results."""
        lookup_table = {
            "8.8.8.8": MaxMindResult(
                ip_address="8.8.8.8",
                country_code="US",
                country_name="United States",
                city="Mountain View",
                latitude=37.386,
                longitude=-122.084,
                asn=15169,
                asn_org="GOOGLE",
                accuracy_radius=1000,
            ),
            "1.1.1.1": MaxMindResult(
                ip_address="1.1.1.1",
                country_code="AU",
                country_name="Australia",
                city=None,
                latitude=None,
                longitude=None,
                asn=13335,
                asn_org="CLOUDFLARENET",
                accuracy_radius=None,
            ),
            "203.0.113.1": MaxMindResult(
                ip_address="203.0.113.1",
                country_code="CN",
                country_name="China",
                city="Beijing",
                latitude=39.9075,
                longitude=116.3972,
                asn=None,  # Missing ASN - triggers Cymru fallback
                asn_org=None,
                accuracy_radius=50,
            ),
        }
        return lookup_table.get(ip)

    client.lookup_ip = Mock(side_effect=lookup_ip)
    return client


@pytest.fixture
def mock_cymru_client() -> CymruClient:
    """Create mock Cymru client with test data."""
    client = Mock(spec=CymruClient)

    def lookup_asn(ip: str) -> CymruResult | None:
        """Mock Cymru lookups with predefined results."""
        lookup_table = {
            "203.0.113.1": CymruResult(
                ip_address="203.0.113.1",
                asn=4134,
                asn_org="CHINANET-BACKBONE",
                country_code="CN",
                registry="APNIC",
            ),
            "192.0.2.1": CymruResult(
                ip_address="192.0.2.1",
                asn=7018,
                asn_org="ATT-INTERNET4",
                country_code="US",
                registry="ARIN",
            ),
        }
        return lookup_table.get(ip)

    client.lookup_asn = Mock(side_effect=lookup_asn)
    return client


@pytest.fixture
def mock_greynoise_client() -> GreyNoiseClient:
    """Create mock GreyNoise client with test data."""
    client = Mock(spec=GreyNoiseClient)

    def lookup_ip(ip: str) -> GreyNoiseResult | None:
        """Mock GreyNoise lookups with predefined results."""
        lookup_table = {
            "8.8.8.8": GreyNoiseResult(
                ip_address="8.8.8.8",
                noise=False,
                riot=True,
                classification="benign",
                name="Google Public DNS",
            ),
            "203.0.113.1": GreyNoiseResult(
                ip_address="203.0.113.1",
                noise=True,
                riot=False,
                classification="malicious",
            ),
        }
        return lookup_table.get(ip)

    client.lookup_ip = Mock(side_effect=lookup_ip)
    return client


@pytest.fixture
def cascade_enricher(
    mock_maxmind_client: MaxMindClient,
    mock_cymru_client: CymruClient,
    mock_greynoise_client: GreyNoiseClient,
    test_db_session: Session,
) -> CascadeEnricher:
    """Create CascadeEnricher with mocked clients and test database."""
    return CascadeEnricher(
        maxmind=mock_maxmind_client,
        cymru=mock_cymru_client,
        greynoise=mock_greynoise_client,
        session=test_db_session,
    )


class TestCascadeFlow:
    """Integration tests for cascade enrichment workflows."""

    def test_enrich_ip_full_cascade(self, cascade_enricher: CascadeEnricher, test_db_session: Session) -> None:
        """Test complete cascade: MaxMind + GreyNoise."""
        result = cascade_enricher.enrich_ip("8.8.8.8")

        # Verify database record created
        assert result.ip_address == "8.8.8.8"
        assert result.current_asn == 15169

        # Verify MaxMind data
        assert result.enrichment["maxmind"]["country"] == "US"
        assert result.enrichment["maxmind"]["asn"] == 15169
        assert result.enrichment["maxmind"]["city"] == "Mountain View"

        # Verify GreyNoise data
        assert result.enrichment["greynoise"]["noise"] is False
        assert result.enrichment["greynoise"]["riot"] is True
        assert result.enrichment["greynoise"]["classification"] == "benign"

        # Verify record persisted
        test_db_session.commit()
        persisted = test_db_session.query(IPInventory).filter(IPInventory.ip_address == "8.8.8.8").first()
        assert persisted is not None
        assert persisted.current_asn == 15169

    def test_enrich_ip_cymru_fallback(self, cascade_enricher: CascadeEnricher, test_db_session: Session) -> None:
        """Test Cymru fallback when MaxMind has no ASN."""
        result = cascade_enricher.enrich_ip("203.0.113.1")

        # Verify MaxMind geo data present
        assert result.enrichment["maxmind"]["country"] == "CN"
        assert result.enrichment["maxmind"]["city"] == "Beijing"
        assert result.enrichment["maxmind"]["asn"] is None

        # Verify Cymru ASN fallback
        assert result.enrichment["cymru"]["asn"] == 4134
        assert result.enrichment["cymru"]["asn_org"] == "CHINANET-BACKBONE"
        assert result.current_asn == 4134

        # Verify GreyNoise data
        assert result.enrichment["greynoise"]["noise"] is True
        assert result.enrichment["greynoise"]["classification"] == "malicious"

        # Verify both lookups were called
        assert cascade_enricher.maxmind.lookup_ip.call_count > 0  # type: ignore[attr-defined]
        assert cascade_enricher.cymru.lookup_asn.call_count > 0  # type: ignore[attr-defined]

    def test_enrich_session_ips(self, cascade_enricher: CascadeEnricher, test_db_session: Session) -> None:
        """Test enriching all IPs in a session."""
        # Create test session
        session = SessionSummary(
            session_id="test-session-001",
            source_ip="8.8.8.8",
            first_event_at=datetime.now(timezone.utc),
            last_event_at=datetime.now(timezone.utc),
        )
        test_db_session.add(session)
        test_db_session.commit()

        # Enrich session IPs
        results = cascade_enricher.enrich_session_ips(session.session_id)

        assert len(results) == 1
        assert "8.8.8.8" in results
        assert results["8.8.8.8"].current_asn == 15169

        # Verify enrichment persisted
        test_db_session.commit()
        ip_record = test_db_session.query(IPInventory).filter(IPInventory.ip_address == "8.8.8.8").first()
        assert ip_record is not None
        assert ip_record.enrichment["maxmind"]["country"] == "US"

    def test_enrich_session_ips_invalid_session(self, cascade_enricher: CascadeEnricher) -> None:
        """Test error handling for invalid session ID."""
        with pytest.raises(ValueError, match="Session .* not found"):
            cascade_enricher.enrich_session_ips(99999)

    def test_backfill_missing_asns_workflow(self, cascade_enricher: CascadeEnricher, test_db_session: Session) -> None:
        """Test backfilling ASNs for IPs without ASN data."""
        # Create IPs without ASNs
        ip1 = IPInventory(
            ip_address="192.0.2.1",
            current_asn=None,
            enrichment={},
            enrichment_updated_at=datetime.now(timezone.utc),
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            session_count=1,
        )
        ip2 = IPInventory(
            ip_address="203.0.113.1",
            current_asn=None,
            enrichment={},
            enrichment_updated_at=datetime.now(timezone.utc),
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            session_count=1,
        )
        test_db_session.add_all([ip1, ip2])
        test_db_session.commit()

        # Backfill ASNs
        count = cascade_enricher.backfill_missing_asns(limit=10)

        assert count == 2

        # Verify ASNs were added
        test_db_session.refresh(ip1)
        test_db_session.refresh(ip2)

        assert ip1.current_asn == 7018
        assert ip1.enrichment["cymru"]["asn_org"] == "ATT-INTERNET4"

        assert ip2.current_asn == 4134
        assert ip2.enrichment["cymru"]["asn_org"] == "CHINANET-BACKBONE"

    def test_refresh_stale_cymru_workflow(self, cascade_enricher: CascadeEnricher, test_db_session: Session) -> None:
        """Test refreshing stale Cymru data."""
        now = datetime.now(timezone.utc)

        # Create IP with stale Cymru data
        stale_ip = IPInventory(
            ip_address="203.0.113.1",
            current_asn=4134,
            enrichment={"cymru": {"asn": 4134, "asn_org": "OLD-ORG"}},
            enrichment_updated_at=now - timedelta(days=91),  # Stale
            first_seen=now - timedelta(days=100),
            last_seen=now - timedelta(days=1),
            session_count=5,
        )
        test_db_session.add(stale_ip)
        test_db_session.commit()

        # Refresh stale data
        results = cascade_enricher.refresh_stale_data(source="cymru", limit=10)

        assert results["cymru_refreshed"] == 1

        # Verify data was refreshed
        test_db_session.refresh(stale_ip)
        assert stale_ip.enrichment["cymru"]["asn_org"] == "CHINANET-BACKBONE"
        # Handle timezone-naive datetime from SQLite
        updated_at = stale_ip.enrichment_updated_at
        if updated_at and updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        assert updated_at and updated_at > now - timedelta(minutes=1)

    def test_cache_hit_workflow(self, cascade_enricher: CascadeEnricher, test_db_session: Session) -> None:
        """Test cache hit avoids external lookups."""
        now = datetime.now(timezone.utc)

        # Create fresh cached data
        cached_ip = IPInventory(
            ip_address="1.1.1.1",
            current_asn=13335,
            enrichment={
                "maxmind": {
                    "country": "AU",
                    "asn": 13335,
                    "cached_at": now.isoformat(),
                }
            },
            enrichment_updated_at=now - timedelta(days=1),  # Fresh
            first_seen=now - timedelta(days=10),
            last_seen=now - timedelta(days=1),
            session_count=5,
        )
        test_db_session.add(cached_ip)
        test_db_session.commit()

        # Reset call history
        cascade_enricher.maxmind.lookup_ip.call_count = 0  # type: ignore[attr-defined]
        cascade_enricher.greynoise.lookup_ip.call_count = 0  # type: ignore[attr-defined]

        # Enrich IP
        result = cascade_enricher.enrich_ip("1.1.1.1")

        # Verify cache hit
        assert result.ip_address == "1.1.1.1"
        assert result.current_asn == 13335

        # Verify no new external lookups (call counts should still be 0)
        assert cascade_enricher.maxmind.lookup_ip.call_count == 0  # type: ignore[attr-defined]
        assert cascade_enricher.greynoise.lookup_ip.call_count == 0  # type: ignore[attr-defined]

        # Verify stats
        stats = cascade_enricher.get_stats()
        assert stats.cache_hits == 1
        assert stats.maxmind_hits == 0

    def test_update_existing_stale_record(self, cascade_enricher: CascadeEnricher, test_db_session: Session) -> None:
        """Test updating existing record with stale data."""
        now = datetime.now(timezone.utc)

        # Create stale record
        stale_ip = IPInventory(
            ip_address="1.1.1.1",
            current_asn=None,
            enrichment={},
            enrichment_updated_at=now - timedelta(days=10),  # Stale
            first_seen=now - timedelta(days=30),
            last_seen=now - timedelta(days=10),
            session_count=3,
        )
        test_db_session.add(stale_ip)
        test_db_session.commit()

        # Enrich IP
        result = cascade_enricher.enrich_ip("1.1.1.1")

        # Verify record updated
        assert result.current_asn == 13335
        assert result.session_count == 4  # Incremented
        assert result.enrichment["maxmind"]["country"] == "AU"

        # Verify database persisted
        test_db_session.commit()
        test_db_session.refresh(stale_ip)
        assert stale_ip.current_asn == 13335
        assert stale_ip.session_count == 4

    def test_statistics_tracking(self, cascade_enricher: CascadeEnricher, test_db_session: Session) -> None:
        """Test cascade statistics are tracked correctly."""
        # Reset stats
        cascade_enricher.reset_stats()

        # Enrich multiple IPs
        cascade_enricher.enrich_ip("8.8.8.8")  # MaxMind + GreyNoise
        cascade_enricher.enrich_ip("203.0.113.1")  # MaxMind + Cymru + GreyNoise
        cascade_enricher.enrich_ip("8.8.8.8")  # Cache hit

        # Verify stats
        stats = cascade_enricher.get_stats()
        assert stats.total_ips == 3
        assert stats.cache_hits == 1
        assert stats.maxmind_hits == 2
        assert stats.cymru_hits == 1
        assert stats.greynoise_hits == 2

    def test_concurrent_enrichment_no_duplicates(
        self, cascade_enricher: CascadeEnricher, test_db_session: Session
    ) -> None:
        """Test concurrent enrichment doesn't create duplicate records."""
        # Enrich same IP twice (simulates concurrent requests)
        result1 = cascade_enricher.enrich_ip("1.1.1.1")
        result2 = cascade_enricher.enrich_ip("1.1.1.1")

        # Verify both return same record
        assert result1.ip_address == result2.ip_address
        assert result1.current_asn == result2.current_asn

        # Verify only one database record
        test_db_session.commit()
        count = test_db_session.query(IPInventory).filter(IPInventory.ip_address == "1.1.1.1").count()
        assert count == 1

    def test_graceful_degradation_greynoise_failure(
        self, cascade_enricher: CascadeEnricher, test_db_session: Session
    ) -> None:
        """Test graceful degradation when GreyNoise fails."""
        # Mock GreyNoise to raise exception

        def raise_exception(ip: str) -> None:
            raise Exception("Quota exceeded")

        cascade_enricher.greynoise.lookup_ip = Mock(side_effect=raise_exception)  # type: ignore[method-assign]

        # Enrich IP
        result = cascade_enricher.enrich_ip("8.8.8.8")

        # Should still have MaxMind data
        assert result.current_asn == 15169
        assert result.enrichment["maxmind"]["country"] == "US"

        # Should NOT have GreyNoise data
        assert "greynoise" not in result.enrichment
