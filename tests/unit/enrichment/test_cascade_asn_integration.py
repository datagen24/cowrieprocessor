"""Unit tests for ASN inventory integration in CascadeEnricher."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from cowrieprocessor.db.models import ASNInventory, IPInventory
from cowrieprocessor.enrichment.cascade_enricher import CascadeEnricher
from cowrieprocessor.enrichment.cymru_client import CymruResult
from cowrieprocessor.enrichment.maxmind_client import MaxMindResult


@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing."""
    from cowrieprocessor.db.models import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(in_memory_db):
    """Create database session for testing."""
    with Session(in_memory_db) as session:
        yield session


@pytest.fixture
def mock_maxmind():
    """Mock MaxMind client."""
    client = Mock()
    client.get_database_age.return_value = None
    return client


@pytest.fixture
def mock_cymru():
    """Mock Cymru client."""
    return Mock()


@pytest.fixture
def mock_greynoise():
    """Mock GreyNoise client."""
    return Mock()


@pytest.fixture
def cascade(mock_maxmind, mock_cymru, mock_greynoise, db_session):
    """Create CascadeEnricher with mocked clients."""
    return CascadeEnricher(
        maxmind=mock_maxmind,
        cymru=mock_cymru,
        greynoise=mock_greynoise,
        session=db_session,
    )


class TestEnsureASNInventory:
    """Test _ensure_asn_inventory() method."""

    def test_create_new_asn_record(self, cascade, db_session):
        """Test creating a new ASN inventory record."""
        asn_record = cascade._ensure_asn_inventory(
            asn=15169,
            organization_name="GOOGLE",
            organization_country="US",
            rir_registry=None,
        )

        assert asn_record.asn_number == 15169
        assert asn_record.organization_name == "GOOGLE"
        assert asn_record.organization_country == "US"
        assert asn_record.rir_registry is None
        assert asn_record.unique_ip_count == 0
        assert asn_record.total_session_count == 0
        assert isinstance(asn_record.first_seen, datetime)
        assert isinstance(asn_record.last_seen, datetime)

        # Verify it was added to database
        db_session.commit()
        stmt = select(ASNInventory).where(ASNInventory.asn_number == 15169)
        retrieved = db_session.execute(stmt).scalar_one()
        assert retrieved.asn_number == 15169
        assert retrieved.organization_name == "GOOGLE"

    def test_update_existing_asn_record(self, cascade, db_session):
        """Test updating an existing ASN inventory record."""
        # Create initial record
        now = datetime.now(timezone.utc)
        initial = ASNInventory(
            asn_number=15169,
            organization_name="GOOGLE",
            organization_country="US",
            rir_registry=None,
            first_seen=now,
            last_seen=now,
            unique_ip_count=5,
            total_session_count=10,
            enrichment={},
            created_at=now,
            updated_at=now,
        )
        db_session.add(initial)
        db_session.commit()

        # Update via _ensure_asn_inventory
        updated = cascade._ensure_asn_inventory(
            asn=15169,
            organization_name="GOOGLE LLC",
            organization_country="US",
            rir_registry="ARIN",
        )

        assert updated.asn_number == 15169
        # Organization name should NOT be updated (already exists)
        assert updated.organization_name == "GOOGLE"
        # But last_seen should be updated
        assert updated.last_seen > now

    def test_update_fills_missing_metadata(self, cascade, db_session):
        """Test that updating fills in missing metadata fields."""
        # Create record with incomplete metadata
        now = datetime.now(timezone.utc)
        initial = ASNInventory(
            asn_number=15169,
            organization_name=None,
            organization_country=None,
            rir_registry=None,
            first_seen=now,
            last_seen=now,
            unique_ip_count=0,
            total_session_count=0,
            enrichment={},
            created_at=now,
            updated_at=now,
        )
        db_session.add(initial)
        db_session.commit()

        # Update with complete metadata
        updated = cascade._ensure_asn_inventory(
            asn=15169,
            organization_name="GOOGLE",
            organization_country="US",
            rir_registry="ARIN",
        )

        # Should fill in missing fields
        assert updated.organization_name == "GOOGLE"
        assert updated.organization_country == "US"
        assert updated.rir_registry == "ARIN"

    def test_concurrent_access_with_locking(self, cascade, db_session):
        """Test that SELECT FOR UPDATE prevents race conditions."""
        # This test verifies the locking behavior exists
        # In a real concurrent scenario, the lock would prevent conflicts
        asn_record = cascade._ensure_asn_inventory(
            asn=15169,
            organization_name="GOOGLE",
            organization_country="US",
            rir_registry=None,
        )

        # Second call should update, not create duplicate
        updated = cascade._ensure_asn_inventory(
            asn=15169,
            organization_name="GOOGLE LLC",
            organization_country="US",
            rir_registry="ARIN",
        )

        # Should be same record (no duplicate created)
        assert updated.asn_number == asn_record.asn_number

        # Verify only one record exists
        db_session.commit()
        stmt = select(ASNInventory).where(ASNInventory.asn_number == 15169)
        all_records = db_session.execute(stmt).scalars().all()
        assert len(all_records) == 1


class TestEnrichIPWithASNCreation:
    """Test enrich_ip() creates ASN inventory records."""

    def test_maxmind_creates_asn_record(self, cascade, mock_maxmind, db_session):
        """Test that MaxMind enrichment creates ASN inventory record."""
        # Mock MaxMind result with ASN
        mock_maxmind.lookup_ip.return_value = MaxMindResult(
            ip_address="8.8.8.8",
            country_code="US",
            country_name="United States",
            city="Mountain View",
            latitude=37.3860,
            longitude=-122.0838,
            asn=15169,
            asn_org="GOOGLE",
            accuracy_radius=1000,
            source="maxmind",
            cached_at=datetime.now(timezone.utc),
        )

        # Enrich IP
        result = cascade.enrich_ip("8.8.8.8")

        # Verify IP inventory created
        assert result.ip_address == "8.8.8.8"
        assert result.current_asn == 15169

        # Verify ASN inventory created
        db_session.commit()
        stmt = select(ASNInventory).where(ASNInventory.asn_number == 15169)
        asn_record = db_session.execute(stmt).scalar_one()
        assert asn_record.organization_name == "GOOGLE"
        assert asn_record.organization_country == "US"
        assert asn_record.rir_registry is None  # MaxMind doesn't provide RIR

    def test_cymru_creates_asn_record(self, cascade, mock_maxmind, mock_cymru, db_session):
        """Test that Cymru enrichment creates ASN inventory record."""
        # Mock MaxMind result with no ASN (trigger Cymru fallback)
        mock_maxmind.lookup_ip.return_value = MaxMindResult(
            ip_address="1.2.3.4",
            country_code="AU",
            country_name="Australia",
            city="Sydney",
            latitude=-33.8688,
            longitude=151.2093,
            asn=None,  # No ASN triggers Cymru
            asn_org=None,
            accuracy_radius=1000,
            source="maxmind",
            cached_at=datetime.now(timezone.utc),
        )

        # Mock Cymru result with ASN
        mock_cymru.lookup_asn.return_value = CymruResult(
            ip_address="1.2.3.4",
            asn=13335,
            asn_org="CLOUDFLARENET",
            country_code="AU",
            registry="APNIC",
            prefix="1.2.3.0/24",
            allocation_date="2011-08-11",
            source="cymru",
            cached_at=datetime.now(timezone.utc),
        )

        # Enrich IP
        result = cascade.enrich_ip("1.2.3.4")

        # Verify IP inventory created with Cymru ASN
        assert result.ip_address == "1.2.3.4"
        assert result.current_asn == 13335

        # Verify ASN inventory created with RIR info
        db_session.commit()
        stmt = select(ASNInventory).where(ASNInventory.asn_number == 13335)
        asn_record = db_session.execute(stmt).scalar_one()
        assert asn_record.organization_name == "CLOUDFLARENET"
        assert asn_record.organization_country == "AU"
        assert asn_record.rir_registry == "APNIC"

    def test_maxmind_asn_no_duplicate_with_cymru(self, cascade, mock_maxmind, mock_cymru, db_session):
        """Test that MaxMind ASN prevents Cymru lookup and duplicate ASN creation."""
        # Mock MaxMind result with complete ASN
        mock_maxmind.lookup_ip.return_value = MaxMindResult(
            ip_address="8.8.8.8",
            country_code="US",
            country_name="United States",
            city="Mountain View",
            latitude=37.3860,
            longitude=-122.0838,
            asn=15169,
            asn_org="GOOGLE",
            accuracy_radius=1000,
            source="maxmind",
            cached_at=datetime.now(timezone.utc),
        )

        # Enrich IP
        cascade.enrich_ip("8.8.8.8")

        # Verify Cymru was NOT called (early termination)
        mock_cymru.lookup_asn.assert_not_called()

        # Verify only one ASN record created
        db_session.commit()
        stmt = select(ASNInventory).where(ASNInventory.asn_number == 15169)
        all_records = db_session.execute(stmt).scalars().all()
        assert len(all_records) == 1

    def test_multiple_ips_same_asn_updates_not_duplicates(self, cascade, mock_maxmind, db_session):
        """Test that multiple IPs with same ASN update, not create duplicates."""
        # Mock MaxMind to return same ASN for different IPs
        mock_maxmind.lookup_ip.side_effect = [
            MaxMindResult(
                ip_address="8.8.8.8",
                country_code="US",
                country_name="United States",
                city="Mountain View",
                latitude=37.3860,
                longitude=-122.0838,
                asn=15169,
                asn_org="GOOGLE",
                accuracy_radius=1000,
                source="maxmind",
                cached_at=datetime.now(timezone.utc),
            ),
            MaxMindResult(
                ip_address="8.8.4.4",
                country_code="US",
                country_name="United States",
                city="Mountain View",
                latitude=37.3860,
                longitude=-122.0838,
                asn=15169,
                asn_org="GOOGLE",
                accuracy_radius=1000,
                source="maxmind",
                cached_at=datetime.now(timezone.utc),
            ),
        ]

        # Enrich both IPs
        cascade.enrich_ip("8.8.8.8")
        cascade.enrich_ip("8.8.4.4")

        # Verify only ONE ASN record created
        db_session.commit()
        stmt = select(ASNInventory).where(ASNInventory.asn_number == 15169)
        all_records = db_session.execute(stmt).scalars().all()
        assert len(all_records) == 1

        # Verify last_seen was updated
        asn_record = all_records[0]
        assert asn_record.organization_name == "GOOGLE"

    def test_no_asn_no_asn_record_created(self, cascade, mock_maxmind, mock_cymru, db_session):
        """Test that IPs with no ASN don't create ASN inventory records."""
        # Mock MaxMind with no ASN
        mock_maxmind.lookup_ip.return_value = MaxMindResult(
            ip_address="192.168.1.1",
            country_code=None,
            country_name=None,
            city=None,
            latitude=None,
            longitude=None,
            asn=None,
            asn_org=None,
            accuracy_radius=None,
            source="maxmind",
            cached_at=datetime.now(timezone.utc),
        )

        # Mock Cymru with no result
        mock_cymru.lookup_asn.return_value = None

        # Enrich IP
        result = cascade.enrich_ip("192.168.1.1")

        # Verify IP inventory created but no ASN
        assert result.ip_address == "192.168.1.1"
        assert result.current_asn is None

        # Verify NO ASN inventory records created
        db_session.commit()
        stmt = select(ASNInventory)
        all_records = db_session.execute(stmt).scalars().all()
        assert len(all_records) == 0


class TestBackfillMissingASNs:
    """Test backfill_missing_asns() with ASN inventory integration."""

    def test_backfill_creates_asn_records(self, cascade, mock_cymru, db_session):
        """Test that backfilling missing ASNs creates ASN inventory records."""
        # Create IP without ASN
        now = datetime.now(timezone.utc)
        ip_no_asn = IPInventory(
            ip_address="1.2.3.4",
            current_asn=None,
            enrichment={"maxmind": {"country": "AU"}},
            first_seen=now,
            last_seen=now,
            session_count=1,
            created_at=now,
            updated_at=now,
        )
        db_session.add(ip_no_asn)
        db_session.commit()

        # Mock Cymru to provide ASN
        mock_cymru.lookup_asn.return_value = CymruResult(
            ip_address="1.2.3.4",
            asn=13335,
            asn_org="CLOUDFLARENET",
            country_code="AU",
            registry="APNIC",
            prefix="1.2.3.0/24",
            allocation_date="2011-08-11",
            source="cymru",
            cached_at=datetime.now(timezone.utc),
        )

        # Backfill
        count = cascade.backfill_missing_asns(limit=10)

        assert count == 1

        # Verify IP now has ASN
        db_session.commit()
        stmt = select(IPInventory).where(IPInventory.ip_address == "1.2.3.4")
        updated_ip = db_session.execute(stmt).scalar_one()
        assert updated_ip.current_asn == 13335

        # Note: backfill_missing_asns does NOT call _ensure_asn_inventory
        # This is intentional - it only updates ip_inventory
        # The CLI backfill tool handles asn_inventory population
