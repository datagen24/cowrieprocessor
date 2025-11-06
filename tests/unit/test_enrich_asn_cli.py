"""Unit tests for ASN enrichment CLI error handling."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from cowrieprocessor.cli.enrich_asn import build_asn_inventory
from cowrieprocessor.db.base import Base
from cowrieprocessor.db.models import ASNInventory, IPInventory


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create temporary directory."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_db(temp_dir: Path) -> tuple[str, sessionmaker[Session]]:
    """Create test database with schema."""
    db_path = temp_dir / "test.db"
    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    SessionMaker = sessionmaker(bind=engine)
    return db_url, SessionMaker


class TestASNEnrichmentErrorHandling:
    """Test error handling for malformed enrichment data."""

    def test_build_asn_inventory_with_valid_data(self, test_db: tuple[str, sessionmaker[Session]]) -> None:
        """Test normal operation with valid enrichment data."""
        # GIVEN: IP inventory with valid MaxMind enrichment
        db_url, session_maker = test_db
        now = datetime.now(UTC)

        with session_maker() as session:
            ip_record = IPInventory(
                ip_address="192.0.2.1",
                current_asn=64512,
                first_seen=now,
                last_seen=now,
                enrichment={
                    "maxmind": {
                        "asn_org": "Example Organization",
                        "country": "US",
                    }
                },
            )
            session.add(ip_record)
            session.commit()

        # WHEN: Building ASN inventory
        created_count = build_asn_inventory(db_url=db_url, batch_size=100, progress=False, verbose=False)

        # THEN: ASN record is created with proper metadata
        assert created_count == 1

        with session_maker() as session:
            asn_record = session.query(ASNInventory).filter_by(asn_number=64512).first()
            assert asn_record is not None
            assert asn_record.organization_name == "Example Organization"  # type: ignore[unreachable]
            assert asn_record.organization_country == "US"  # type: ignore[unreachable]
            assert asn_record.unique_ip_count == 1  # type: ignore[unreachable]

    def test_build_asn_inventory_with_non_dict_enrichment(self, test_db: tuple[str, sessionmaker[Session]]) -> None:
        """Test handling when enrichment is not a dict."""
        # GIVEN: IP inventory with non-dict enrichment data
        db_url, session_maker = test_db
        now = datetime.now(UTC)

        with session_maker() as session:
            ip_record = IPInventory(
                ip_address="192.0.2.2",
                current_asn=64513,
                first_seen=now,
                last_seen=now,
                enrichment="not_a_dict",  # Invalid type
            )
            session.add(ip_record)
            session.commit()

        # WHEN: Building ASN inventory
        created_count = build_asn_inventory(db_url=db_url, batch_size=100, progress=False, verbose=False)

        # THEN: ASN record is created without metadata (no crash)
        assert created_count == 1

        with session_maker() as session:
            asn_record = session.query(ASNInventory).filter_by(asn_number=64513).first()
            assert asn_record is not None
            assert asn_record.organization_name is None  # type: ignore[unreachable]
            assert asn_record.organization_country is None  # type: ignore[unreachable]
            assert asn_record.unique_ip_count == 1  # type: ignore[unreachable]

    def test_build_asn_inventory_with_non_dict_maxmind(self, test_db: tuple[str, sessionmaker[Session]]) -> None:
        """Test handling when maxmind field is not a dict."""
        # GIVEN: IP inventory with maxmind as non-dict
        db_url, session_maker = test_db
        now = datetime.now(UTC)

        with session_maker() as session:
            ip_record = IPInventory(
                ip_address="192.0.2.3",
                current_asn=64514,
                first_seen=now,
                last_seen=now,
                enrichment={
                    "maxmind": "invalid_string",  # Should be dict
                },
            )
            session.add(ip_record)
            session.commit()

        # WHEN: Building ASN inventory
        created_count = build_asn_inventory(db_url=db_url, batch_size=100, progress=False, verbose=False)

        # THEN: ASN record is created without metadata (no crash)
        assert created_count == 1

        with session_maker() as session:
            asn_record = session.query(ASNInventory).filter_by(asn_number=64514).first()
            assert asn_record is not None
            assert asn_record.organization_name is None  # type: ignore[unreachable]

    def test_build_asn_inventory_with_wrong_type_fields(self, test_db: tuple[str, sessionmaker[Session]]) -> None:
        """Test handling when enrichment fields have wrong types."""
        # GIVEN: IP inventory with numeric values instead of strings
        db_url, session_maker = test_db
        now = datetime.now(UTC)

        with session_maker() as session:
            ip_record = IPInventory(
                ip_address="192.0.2.4",
                current_asn=64515,
                first_seen=now,
                last_seen=now,
                enrichment={
                    "maxmind": {
                        "asn_org": 12345,  # Should be string
                        "country": ["US"],  # Should be string
                    }
                },
            )
            session.add(ip_record)
            session.commit()

        # WHEN: Building ASN inventory
        created_count = build_asn_inventory(db_url=db_url, batch_size=100, progress=False, verbose=False)

        # THEN: ASN record is created with converted values
        assert created_count == 1

        with session_maker() as session:
            asn_record = session.query(ASNInventory).filter_by(asn_number=64515).first()
            assert asn_record is not None
            assert asn_record.organization_name == "12345"  # type: ignore[unreachable]  # Converted to string
            assert asn_record.organization_country == "['US']"  # type: ignore[unreachable]  # Converted to string

    def test_build_asn_inventory_with_cymru_fallback(self, test_db: tuple[str, sessionmaker[Session]]) -> None:
        """Test fallback to Cymru when MaxMind is missing."""
        # GIVEN: IP inventory with only Cymru enrichment
        db_url, session_maker = test_db
        now = datetime.now(UTC)

        with session_maker() as session:
            ip_record = IPInventory(
                ip_address="192.0.2.5",
                current_asn=64516,
                first_seen=now,
                last_seen=now,
                enrichment={
                    "cymru": {
                        "asn_org": "Cymru Organization",
                        "country": "GB",
                        "registry": "RIPE",
                    }
                },
            )
            session.add(ip_record)
            session.commit()

        # WHEN: Building ASN inventory
        created_count = build_asn_inventory(db_url=db_url, batch_size=100, progress=False, verbose=False)

        # THEN: ASN record uses Cymru data
        assert created_count == 1

        with session_maker() as session:
            asn_record = session.query(ASNInventory).filter_by(asn_number=64516).first()
            assert asn_record is not None
            assert asn_record.organization_name == "Cymru Organization"  # type: ignore[unreachable]
            assert asn_record.organization_country == "GB"  # type: ignore[unreachable]
            assert asn_record.rir_registry == "RIPE"  # type: ignore[unreachable]

    def test_build_asn_inventory_with_missing_nested_keys(self, test_db: tuple[str, sessionmaker[Session]]) -> None:
        """Test handling when nested keys are missing."""
        # GIVEN: IP inventory with incomplete maxmind data
        db_url, session_maker = test_db
        now = datetime.now(UTC)

        with session_maker() as session:
            ip_record = IPInventory(
                ip_address="192.0.2.6",
                current_asn=64517,
                first_seen=now,
                last_seen=now,
                enrichment={
                    "maxmind": {},  # Empty dict
                },
            )
            session.add(ip_record)
            session.commit()

        # WHEN: Building ASN inventory
        created_count = build_asn_inventory(db_url=db_url, batch_size=100, progress=False, verbose=False)

        # THEN: ASN record is created with None values
        assert created_count == 1

        with session_maker() as session:
            asn_record = session.query(ASNInventory).filter_by(asn_number=64517).first()
            assert asn_record is not None
            assert asn_record.organization_name is None  # type: ignore[unreachable]
            assert asn_record.organization_country is None  # type: ignore[unreachable]

    def test_build_asn_inventory_with_null_enrichment(self, test_db: tuple[str, sessionmaker[Session]]) -> None:
        """Test handling when enrichment is None."""
        # GIVEN: IP inventory with null enrichment
        db_url, session_maker = test_db
        now = datetime.now(UTC)

        with session_maker() as session:
            ip_record = IPInventory(
                ip_address="192.0.2.7",
                current_asn=64518,
                first_seen=now,
                last_seen=now,
                enrichment=None,
            )
            session.add(ip_record)
            session.commit()

        # WHEN: Building ASN inventory
        created_count = build_asn_inventory(db_url=db_url, batch_size=100, progress=False, verbose=False)

        # THEN: ASN record is created without metadata
        assert created_count == 1

        with session_maker() as session:
            asn_record = session.query(ASNInventory).filter_by(asn_number=64518).first()
            assert asn_record is not None
            assert asn_record.organization_name is None  # type: ignore[unreachable]
            assert asn_record.organization_country is None  # type: ignore[unreachable]

    def test_build_asn_inventory_skips_no_sample_ip(self, test_db: tuple[str, sessionmaker[Session]]) -> None:
        """Test that ASNs without sample IPs are skipped."""
        # GIVEN: Empty database
        db_url, _ = test_db

        # WHEN: Building ASN inventory with no IPs
        created_count = build_asn_inventory(db_url=db_url, batch_size=100, progress=False, verbose=False)

        # THEN: No records created
        assert created_count == 0

    def test_build_asn_inventory_batch_processing(self, test_db: tuple[str, sessionmaker[Session]]) -> None:
        """Test batch processing with multiple ASNs."""
        # GIVEN: Multiple IP records with different ASNs
        db_url, session_maker = test_db
        now = datetime.now(UTC)

        with session_maker() as session:
            for asn in range(64520, 64525):
                ip_record = IPInventory(
                    ip_address=f"192.0.2.{asn - 64520 + 10}",
                    current_asn=asn,
                    first_seen=now,
                    last_seen=now,
                    enrichment={
                        "maxmind": {
                            "asn_org": f"Org {asn}",
                            "country": "US",
                        }
                    },
                )
                session.add(ip_record)
            session.commit()

        # WHEN: Building ASN inventory with small batch size
        created_count = build_asn_inventory(db_url=db_url, batch_size=2, progress=False, verbose=False)

        # THEN: All ASN records are created
        assert created_count == 5

        with session_maker() as session:
            asn_count = session.query(ASNInventory).count()
            assert asn_count == 5

    def test_build_asn_inventory_idempotent(self, test_db: tuple[str, sessionmaker[Session]]) -> None:
        """Test that re-running doesn't create duplicates."""
        # GIVEN: IP inventory with an ASN
        db_url, session_maker = test_db
        now = datetime.now(UTC)

        with session_maker() as session:
            ip_record = IPInventory(
                ip_address="192.0.2.30",
                current_asn=64530,
                first_seen=now,
                last_seen=now,
                enrichment={
                    "maxmind": {
                        "asn_org": "Test Org",
                        "country": "US",
                    }
                },
            )
            session.add(ip_record)
            session.commit()

        # WHEN: Running build twice
        first_run = build_asn_inventory(db_url=db_url, batch_size=100, progress=False, verbose=False)
        second_run = build_asn_inventory(db_url=db_url, batch_size=100, progress=False, verbose=False)

        # THEN: First run creates record, second run creates nothing
        assert first_run == 1
        assert second_run == 0

        with session_maker() as session:
            asn_count = session.query(ASNInventory).filter_by(asn_number=64530).count()
            assert asn_count == 1
