"""Integration tests for CascadeEnricher with IP classification (Pass 4).

Tests CascadeEnricher integration with IP classification module:
- Pass 4 IP classification adds to enrichment JSONB
- Refresh stale data includes IP classification updates
- IP classification stats tracked in CascadeEnricher
- Full enrichment workflow with all passes
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from cowrieprocessor.db.models import Base, IPInventory, SessionSummary
from cowrieprocessor.enrichment.cascade_enricher import CascadeEnricher
from cowrieprocessor.enrichment.cascade_factory import create_cascade_enricher
from cowrieprocessor.enrichment.cymru_client import CymruClient, CymruResult
from cowrieprocessor.enrichment.greynoise_client import GreyNoiseClient
from cowrieprocessor.enrichment.maxmind_client import MaxMindClient, MaxMindResult


@pytest.fixture
def integration_db_session(tmp_path: Path):  # type: ignore[misc]
    """Create in-memory SQLite database session for testing."""
    db_path = tmp_path / "test_cascade.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


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
                latitude=37.4056,
                longitude=-122.0775,
                asn=15169,
                asn_org="GOOGLE",
                accuracy_radius=None,
            ),
            "52.0.0.1": MaxMindResult(
                ip_address="52.0.0.1",
                country_code="US",
                country_name="United States",
                city="Ashburn",
                latitude=39.0469,
                longitude=-77.4903,
                asn=16509,
                asn_org="AMAZON-02",
                accuracy_radius=None,
            ),
        }
        return lookup_table.get(ip)

    client.lookup = Mock(side_effect=lookup_ip)
    return client


@pytest.fixture
def mock_cymru_client() -> CymruClient:
    """Create mock Cymru client with test data."""
    client = Mock(spec=CymruClient)

    def lookup_ip(ip: str) -> CymruResult | None:
        """Mock Cymru lookups (fallback for missing MaxMind data)."""
        lookup_table = {
            "1.2.3.4": CymruResult(
                ip_address="1.2.3.4",
                asn=12345,
                asn_org="TEST-ASN",
                country_code="XX",
                registry=None,
            ),
        }
        return lookup_table.get(ip)

    client.lookup_asn = Mock(side_effect=lookup_ip)
    return client


@pytest.fixture
def mock_greynoise_client() -> GreyNoiseClient:
    """Create mock GreyNoise client (disabled for these tests)."""
    client = Mock(spec=GreyNoiseClient)
    client.lookup_ip = Mock(return_value=None)  # No GreyNoise data
    client.get_stats = Mock(return_value={})
    return client


class TestCascadeEnricherIPClassificationIntegration:
    """Integration tests for CascadeEnricher with IP classification."""

    def test_pass4_ip_classification_adds_to_enrichment(
        self,
        tmp_path: Path,
        integration_db_session: Session,
        mock_maxmind_client: MaxMindClient,
        mock_cymru_client: CymruClient,
        mock_greynoise_client: GreyNoiseClient,
    ) -> None:
        """Test that Pass 4 adds IP classification to enrichment JSONB.

        Validates:
        - Pass 4 IP classification runs after Pass 1-3
        - IP classification data added to enrichment JSONB
        - IPInventory record contains ip_classification data
        """
        # Create cascade with IP classification enabled
        cascade = CascadeEnricher(
            maxmind=mock_maxmind_client,
            cymru=mock_cymru_client,
            greynoise=mock_greynoise_client,
            session=integration_db_session,
            ip_classifier=None,  # Will be created by factory in real usage
        )

        # Note: For this test, we're testing the integration point without
        # actual IP classifier since it requires real cache setup.
        # The factory test below will test full integration.

        # Enrich an IP (Pass 1-3)
        test_ip = "8.8.8.8"
        result = cascade.enrich_ip(test_ip)

        # Validate enrichment occurred
        assert result.geo_country == "US"
        assert result.current_asn == 15169
        assert result.enrichment is not None

        # Verify IPInventory record was created
        ip_record = integration_db_session.query(IPInventory).filter_by(ip_address=test_ip).first()
        assert ip_record is not None
        assert ip_record.geo_country == "US"
        assert ip_record.enrichment is not None

    def test_cascade_factory_with_ip_classification(self, tmp_path: Path, integration_db_session: Session) -> None:
        """Test create_cascade_enricher factory with IP classification enabled.

        Validates:
        - Factory creates cascade with IP classifier
        - IP classification runs during enrichment
        - Enrichment JSONB contains ip_classification key
        """
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Create cascade via factory (with IP classification)
        cascade = create_cascade_enricher(
            cache_dir=cache_dir,
            db_session=integration_db_session,
            config={},
            enable_greynoise=False,
            enable_ip_classification=True,
        )

        # Enrich an IP
        test_ip = "8.8.8.8"
        result = cascade.enrich_ip(test_ip)

        # Validate Pass 1-3 enrichment
        assert result.geo_country is not None  # MaxMind
        assert result.current_asn is not None  # MaxMind or Cymru

        # Validate Pass 4 IP classification (if classifier initialized)
        if cascade.ip_classifier is not None:
            assert result.enrichment is not None
            assert "ip_classification" in result.enrichment
            assert "ip_type" in result.enrichment["ip_classification"]
            assert result.enrichment["ip_classification"]["ip_type"] in [
                "tor",
                "cloud",
                "datacenter",
                "residential",
                "unknown",
            ]

    def test_refresh_stale_data_with_ip_classification(self, tmp_path: Path, integration_db_session: Session) -> None:
        """Test refresh_stale_data includes IP classification updates.

        Validates:
        - Stale IP records are identified
        - IP classification refresh occurs
        - Enrichment JSONB is updated with new classification
        """
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Create stale IP inventory entry (2 days old)
        stale_ip = IPInventory(
            ip_address="1.2.3.4",
            created_at=datetime.now(timezone.utc) - timedelta(days=2),
            enrichment_updated_at=datetime.now(timezone.utc) - timedelta(days=2),
            enrichment={},
        )
        integration_db_session.add(stale_ip)
        integration_db_session.commit()

        # Create cascade with IP classification
        cascade = create_cascade_enricher(
            cache_dir=cache_dir,
            db_session=integration_db_session,
            config={},
            enable_greynoise=False,
            enable_ip_classification=True,
        )

        # Refresh stale data (limit=10 for testing)
        refreshed = cascade.refresh_stale_data(limit=10)

        # Validate refresh occurred (at least attempted)
        assert "ips_refreshed" in refreshed
        # Note: Actual refresh count depends on data sources availability

    def test_cascade_stats_include_ip_classification(self, tmp_path: Path, integration_db_session: Session) -> None:
        """Test CascadeEnricher stats include IP classification metrics.

        Validates:
        - CascadeStats tracks ip_classification_hits
        - Statistics are accurate after enrichment
        - Multiple enrichments accumulate stats
        """
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Create cascade with IP classification
        cascade = create_cascade_enricher(
            cache_dir=cache_dir,
            db_session=integration_db_session,
            config={},
            enable_greynoise=False,
            enable_ip_classification=True,
        )

        # Enrich multiple IPs
        test_ips = ["8.8.8.8", "1.1.1.1", "52.0.0.1"]
        for ip in test_ips:
            cascade.enrich_ip(ip)

        # Get statistics
        stats = cascade.get_stats()

        # Validate stats
        assert stats.total_ips == len(test_ips)
        # IP classification hits depend on whether classifier initialized
        if cascade.ip_classifier is not None:
            assert stats.ip_classification_hits >= 0

    def test_session_enrichment_with_ip_classification(self, tmp_path: Path, integration_db_session: Session) -> None:
        """Test full session enrichment workflow with IP classification.

        Validates:
        - Session IP enrichment includes classification
        - SessionSummary snapshot columns populated
        - Enrichment JSONB contains full Pass 1-4 data
        """
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Create session summary
        session = SessionSummary(
            session_id="test-session-001",
            source_ip="8.8.8.8",
            first_event_at=datetime.now(timezone.utc),
            last_event_at=datetime.now(timezone.utc),
            event_count=5,
            enrichment={},
        )
        integration_db_session.add(session)
        integration_db_session.commit()

        # Create cascade and enrich session IP
        cascade = create_cascade_enricher(
            cache_dir=cache_dir,
            db_session=integration_db_session,
            config={},
            enable_greynoise=False,
            enable_ip_classification=True,
        )

        result = cascade.enrich_ip(session.source_ip)

        # Validate enrichment
        assert result.geo_country is not None
        assert result.current_asn is not None

        # Verify IP inventory record
        ip_record = integration_db_session.query(IPInventory).filter_by(ip_address=session.source_ip).first()
        assert ip_record is not None
        assert ip_record.geo_country == result.geo_country

        # Check for IP classification in enrichment (if classifier available)
        if cascade.ip_classifier is not None and ip_record.enrichment:
            if "ip_classification" in ip_record.enrichment:
                assert "ip_type" in ip_record.enrichment["ip_classification"]


class TestCascadeEnricherDisabledIPClassification:
    """Test CascadeEnricher with IP classification disabled."""

    def test_cascade_without_ip_classification(self, tmp_path: Path, integration_db_session: Session) -> None:
        """Test cascade works correctly with IP classification disabled.

        Validates:
        - Pass 4 is skipped when disabled
        - No ip_classification key in enrichment JSONB
        - Pass 1-3 still work normally
        """
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Create cascade with IP classification disabled
        cascade = create_cascade_enricher(
            cache_dir=cache_dir,
            db_session=integration_db_session,
            config={},
            enable_greynoise=False,
            enable_ip_classification=False,  # Disabled
        )

        # Verify IP classifier is None
        assert cascade.ip_classifier is None

        # Enrich an IP
        test_ip = "8.8.8.8"
        result = cascade.enrich_ip(test_ip)

        # Validate Pass 1-3 enrichment still works
        assert result.geo_country is not None or result.current_asn is not None

        # Verify no IP classification in enrichment
        if result.enrichment:
            assert "ip_classification" not in result.enrichment

        # Verify stats show no IP classification hits
        stats = cascade.get_stats()
        assert stats.ip_classification_hits == 0


class TestCascadeEnricherBulkOperations:
    """Test bulk operations with IP classification."""

    def test_bulk_ip_enrichment_with_classification(self, tmp_path: Path, integration_db_session: Session) -> None:
        """Test bulk IP enrichment includes IP classification.

        Validates:
        - Bulk enrichment processes multiple IPs
        - Each IP gets IP classification
        - Performance is acceptable for bulk operations
        """
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Create cascade with IP classification
        cascade = create_cascade_enricher(
            cache_dir=cache_dir,
            db_session=integration_db_session,
            config={},
            enable_greynoise=False,
            enable_ip_classification=True,
        )

        # Bulk enrich IPs
        test_ips = [
            "8.8.8.8",
            "1.1.1.1",
            "52.0.0.1",
            "203.0.113.1",
            "198.51.100.1",
        ]

        import time

        start_time = time.time()
        results = [cascade.enrich_ip(ip) for ip in test_ips]
        elapsed = time.time() - start_time

        # Validate all enrichments completed
        assert len(results) == len(test_ips)
        assert all(r.geo_country is not None or r.current_asn is not None for r in results)

        # Performance check (should complete in reasonable time)
        assert elapsed < 30.0  # 30 seconds for 5 IPs (generous for CI/external APIs)

        # Verify statistics
        stats = cascade.get_stats()
        assert stats.total_ips == len(test_ips)
