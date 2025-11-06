"""Integration tests for end-to-end ASN inventory workflows."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from cowrieprocessor.cli.enrich_asn import build_asn_inventory
from cowrieprocessor.db.models import ASNInventory, IPInventory
from cowrieprocessor.enrichment.cascade_enricher import CascadeEnricher
from cowrieprocessor.enrichment.maxmind_client import MaxMindResult


@pytest.fixture
def integration_db(tmp_path):
    """Create temporary SQLite database for integration testing."""
    from cowrieprocessor.db.models import Base

    db_path = tmp_path / "integration_test.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return engine, str(f"sqlite:///{db_path}")


@pytest.fixture
def integration_session(integration_db):
    """Create database session for integration testing."""
    engine, _ = integration_db
    with Session(engine) as session:
        yield session


class TestEndToEndASNInventoryFlow:
    """Test complete ASN inventory workflow from enrichment to backfill."""

    def test_complete_workflow_maxmind_to_backfill(self, integration_db, integration_session):
        """Test: Enrich IPs with MaxMind -> Verify ASNs created -> Backfill."""
        engine, db_url = integration_db

        # Mock clients
        mock_maxmind = Mock()
        mock_cymru = Mock()
        mock_greynoise = Mock()

        mock_maxmind.get_database_age.return_value = None
        mock_greynoise.lookup_ip.return_value = None

        # Create cascade enricher
        cascade = CascadeEnricher(
            maxmind=mock_maxmind,
            cymru=mock_cymru,
            greynoise=mock_greynoise,
            session=integration_session,
        )

        # Step 1: Enrich multiple IPs with different ASNs
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
                ip_address="1.1.1.1",
                country_code="AU",
                country_name="Australia",
                city="Sydney",
                latitude=-33.8688,
                longitude=151.2093,
                asn=13335,
                asn_org="CLOUDFLARENET",
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
                asn=15169,  # Same ASN as 8.8.8.8
                asn_org="GOOGLE",
                accuracy_radius=1000,
                source="maxmind",
                cached_at=datetime.now(timezone.utc),
            ),
        ]

        # Enrich IPs
        cascade.enrich_ip("8.8.8.8")
        cascade.enrich_ip("1.1.1.1")
        cascade.enrich_ip("8.8.4.4")

        integration_session.commit()

        # Step 2: Verify ASN inventory was created during enrichment
        stmt = select(ASNInventory).order_by(ASNInventory.asn_number)
        asn_records = integration_session.execute(stmt).scalars().all()

        assert len(asn_records) == 2  # Two unique ASNs
        assert asn_records[0].asn_number == 13335
        assert asn_records[0].organization_name == "CLOUDFLARENET"
        assert asn_records[1].asn_number == 15169
        assert asn_records[1].organization_name == "GOOGLE"

        # Step 3: Verify IP inventory has correct foreign keys
        stmt = select(IPInventory).order_by(IPInventory.ip_address)
        ip_records = integration_session.execute(stmt).scalars().all()

        assert len(ip_records) == 3
        assert ip_records[0].ip_address == "1.1.1.1"
        assert ip_records[0].current_asn == 13335
        assert ip_records[1].ip_address == "8.8.4.4"
        assert ip_records[1].current_asn == 15169
        assert ip_records[2].ip_address == "8.8.8.8"
        assert ip_records[2].current_asn == 15169

        # Step 4: Add IP with no ASN (simulating older data)
        now = datetime.now(timezone.utc)
        ip_no_asn = IPInventory(
            ip_address="192.168.1.1",
            current_asn=None,
            enrichment={"maxmind": {"country": "US"}},
            first_seen=now,
            last_seen=now,
            session_count=1,
            created_at=now,
            updated_at=now,
        )
        integration_session.add(ip_no_asn)
        integration_session.commit()

        # Step 5: Run CLI backfill tool
        created = build_asn_inventory(
            db_url=db_url,
            batch_size=10,
            progress=False,
            verbose=False,
        )

        # Should create 0 new ASNs (all already exist from enrichment)
        assert created == 0

        # Step 6: Verify final state
        stmt = select(ASNInventory)
        final_asn_count = len(integration_session.execute(stmt).scalars().all())
        assert final_asn_count == 2

    def test_backfill_populates_empty_asn_inventory(self, integration_db, integration_session):
        """Test backfill CLI can populate ASN inventory from scratch."""
        engine, db_url = integration_db

        # Step 1: Manually create IP inventory records WITHOUT ASN inventory
        # (simulating data created before ASN inventory integration)
        now = datetime.now(timezone.utc)

        ips = [
            IPInventory(
                ip_address="8.8.8.8",
                current_asn=15169,
                enrichment={
                    "maxmind": {
                        "country": "US",
                        "asn": 15169,
                        "asn_org": "GOOGLE",
                    }
                },
                first_seen=now,
                last_seen=now,
                session_count=1,
                created_at=now,
                updated_at=now,
            ),
            IPInventory(
                ip_address="8.8.4.4",
                current_asn=15169,
                enrichment={
                    "maxmind": {
                        "country": "US",
                        "asn": 15169,
                        "asn_org": "GOOGLE",
                    }
                },
                first_seen=now,
                last_seen=now,
                session_count=1,
                created_at=now,
                updated_at=now,
            ),
            IPInventory(
                ip_address="1.1.1.1",
                current_asn=13335,
                enrichment={
                    "cymru": {
                        "asn": 13335,
                        "asn_org": "CLOUDFLARENET",
                        "country": "AU",
                        "registry": "APNIC",
                    }
                },
                first_seen=now,
                last_seen=now,
                session_count=1,
                created_at=now,
                updated_at=now,
            ),
        ]

        for ip in ips:
            integration_session.add(ip)
        integration_session.commit()

        # Step 2: Verify ASN inventory is empty
        stmt = select(ASNInventory)
        asn_count = len(integration_session.execute(stmt).scalars().all())
        assert asn_count == 0

        # Step 3: Run backfill CLI
        created = build_asn_inventory(
            db_url=db_url,
            batch_size=10,
            progress=False,
            verbose=False,
        )

        assert created == 2  # Two unique ASNs

        # Step 4: Verify ASN inventory was populated
        stmt = select(ASNInventory).order_by(ASNInventory.asn_number)
        asn_records = integration_session.execute(stmt).scalars().all()

        assert len(asn_records) == 2

        # Verify ASN 13335 (Cloudflare)
        cloudflare = next(asn for asn in asn_records if asn.asn_number == 13335)
        assert cloudflare.organization_name == "CLOUDFLARENET"
        assert cloudflare.organization_country == "AU"
        assert cloudflare.rir_registry == "APNIC"
        assert cloudflare.unique_ip_count == 1

        # Verify ASN 15169 (Google)
        google = next(asn for asn in asn_records if asn.asn_number == 15169)
        assert google.organization_name == "GOOGLE"
        assert google.organization_country == "US"
        assert google.rir_registry is None  # MaxMind doesn't provide RIR
        assert google.unique_ip_count == 2  # Two IPs with this ASN

    def test_backfill_idempotent_no_duplicates(self, integration_db, integration_session):
        """Test that running backfill multiple times is safe (idempotent)."""
        engine, db_url = integration_db

        # Create IP inventory
        now = datetime.now(timezone.utc)
        ip = IPInventory(
            ip_address="8.8.8.8",
            current_asn=15169,
            enrichment={
                "maxmind": {
                    "country": "US",
                    "asn": 15169,
                    "asn_org": "GOOGLE",
                }
            },
            first_seen=now,
            last_seen=now,
            session_count=1,
            created_at=now,
            updated_at=now,
        )
        integration_session.add(ip)
        integration_session.commit()

        # Run backfill first time
        created_first = build_asn_inventory(
            db_url=db_url,
            batch_size=10,
            progress=False,
            verbose=False,
        )

        assert created_first == 1

        # Run backfill second time (should be no-op)
        created_second = build_asn_inventory(
            db_url=db_url,
            batch_size=10,
            progress=False,
            verbose=False,
        )

        assert created_second == 0  # No new records created

        # Verify still only one ASN record
        stmt = select(ASNInventory)
        asn_records = integration_session.execute(stmt).scalars().all()
        assert len(asn_records) == 1

    def test_backfill_handles_ips_without_asn(self, integration_db, integration_session):
        """Test that backfill skips IPs with no ASN."""
        engine, db_url = integration_db

        # Create IPs with and without ASNs
        now = datetime.now(timezone.utc)

        ips = [
            IPInventory(
                ip_address="8.8.8.8",
                current_asn=15169,
                enrichment={
                    "maxmind": {
                        "country": "US",
                        "asn": 15169,
                        "asn_org": "GOOGLE",
                    }
                },
                first_seen=now,
                last_seen=now,
                session_count=1,
                created_at=now,
                updated_at=now,
            ),
            IPInventory(
                ip_address="192.168.1.1",
                current_asn=None,  # No ASN
                enrichment={"maxmind": {"country": "US"}},
                first_seen=now,
                last_seen=now,
                session_count=1,
                created_at=now,
                updated_at=now,
            ),
        ]

        for ip in ips:
            integration_session.add(ip)
        integration_session.commit()

        # Run backfill
        created = build_asn_inventory(
            db_url=db_url,
            batch_size=10,
            progress=False,
            verbose=False,
        )

        # Should only create ASN for IP with ASN
        assert created == 1

        # Verify only one ASN record
        stmt = select(ASNInventory)
        asn_records = integration_session.execute(stmt).scalars().all()
        assert len(asn_records) == 1
        assert asn_records[0].asn_number == 15169
