"""Unit tests for ADR-007 three-tier enrichment architecture models.

Tests the new ASNInventory, IPInventory, IPASNHistory models and updated
SessionSummary model with snapshot columns and relationships.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from cowrieprocessor.db.base import Base
from cowrieprocessor.db.models import ASNInventory, IPASNHistory, IPInventory, SessionSummary


@pytest.fixture
def in_memory_engine():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(in_memory_engine):
    """Create a database session for testing."""
    with Session(in_memory_engine) as session:
        yield session
        session.rollback()


class TestASNInventory:
    """Test ASN inventory model (Tier 1)."""

    def test_create_asn_inventory(self, db_session: Session) -> None:
        """Test creating an ASN inventory record."""
        now = datetime.now(timezone.utc)
        asn = ASNInventory(
            asn_number=4134,
            organization_name="China Telecom",
            organization_country="CN",
            rir_registry="APNIC",
            asn_type="ISP",
            is_known_hosting=False,
            is_known_vpn=False,
            first_seen=now - timedelta(days=30),
            last_seen=now,
            unique_ip_count=150,
            total_session_count=450,
            enrichment={"source": "dshield", "confidence": 0.95},
            enrichment_updated_at=now,
        )
        db_session.add(asn)
        db_session.commit()

        # Retrieve and verify
        result = db_session.execute(select(ASNInventory).where(ASNInventory.asn_number == 4134)).scalar_one()
        assert result.organization_name == "China Telecom"
        assert result.organization_country == "CN"
        assert result.rir_registry == "APNIC"
        assert result.asn_type == "ISP"
        assert result.unique_ip_count == 150
        assert result.total_session_count == 450
        assert result.is_known_hosting is False
        assert result.is_known_vpn is False
        assert result.enrichment["source"] == "dshield"

    def test_asn_inventory_defaults(self, db_session: Session) -> None:
        """Test ASN inventory default values."""
        now = datetime.now(timezone.utc)
        asn = ASNInventory(
            asn_number=15169,
            first_seen=now,
            last_seen=now,
        )
        db_session.add(asn)
        db_session.commit()

        result = db_session.execute(select(ASNInventory).where(ASNInventory.asn_number == 15169)).scalar_one()
        assert result.unique_ip_count == 0
        assert result.total_session_count == 0
        assert result.is_known_hosting is False
        assert result.is_known_vpn is False
        assert result.enrichment == {}

    def test_asn_inventory_timestamps(self, db_session: Session) -> None:
        """Test ASN inventory automatic timestamp management."""
        now = datetime.now(timezone.utc)
        asn = ASNInventory(
            asn_number=8075,
            organization_name="Microsoft",
            first_seen=now,
            last_seen=now,
        )
        db_session.add(asn)
        db_session.commit()

        result = db_session.execute(select(ASNInventory).where(ASNInventory.asn_number == 8075)).scalar_one()
        assert result.created_at is not None
        assert result.updated_at is not None
        assert result.created_at <= result.updated_at  # type: ignore[operator]


class TestIPInventory:
    """Test IP inventory model (Tier 2)."""

    def test_create_ip_inventory(self, db_session: Session) -> None:
        """Test creating an IP inventory record."""
        now = datetime.now(timezone.utc)

        # Create ASN first (foreign key requirement)
        asn = ASNInventory(
            asn_number=4134,
            organization_name="China Telecom",
            first_seen=now - timedelta(days=30),
            last_seen=now,
        )
        db_session.add(asn)
        db_session.commit()

        # Create IP inventory
        ip = IPInventory(
            ip_address="1.2.3.4",
            current_asn=4134,
            asn_last_verified=now,
            first_seen=now - timedelta(days=7),
            last_seen=now,
            session_count=5,
            enrichment={
                "maxmind": {"country": "CN", "city": "Beijing"},
                "dshield": {"ip": {"ascountry": "CN", "asnum": "4134"}},
                "spur": {"client": {"types": "RESIDENTIAL"}},
                "greynoise": {"noise": True},
                "validation": {"is_bogon": False},
            },
            enrichment_updated_at=now,
            enrichment_version="2.2",
        )
        db_session.add(ip)
        db_session.commit()

        # Retrieve and verify
        result = db_session.execute(select(IPInventory).where(IPInventory.ip_address == "1.2.3.4")).scalar_one()
        assert result.current_asn == 4134
        assert result.session_count == 5
        assert result.enrichment["maxmind"]["country"] == "CN"

    def test_ip_inventory_computed_geo_country(self, db_session: Session) -> None:
        """Test computed geo_country property with fallback priority."""
        now = datetime.now(timezone.utc)

        # Test MaxMind priority (highest)
        ip1 = IPInventory(
            ip_address="10.0.0.1",
            first_seen=now,
            last_seen=now,
            enrichment={
                "maxmind": {"country": "US"},
                "cymru": {"country": "CA"},
                "dshield": {"ip": {"ascountry": "MX"}},
            },
        )
        db_session.add(ip1)
        assert ip1.geo_country == "US"  # MaxMind wins

        # Test Cymru fallback
        ip2 = IPInventory(
            ip_address="10.0.0.2",
            first_seen=now,
            last_seen=now,
            enrichment={
                "cymru": {"country": "CA"},
                "dshield": {"ip": {"ascountry": "MX"}},
            },
        )
        db_session.add(ip2)
        assert ip2.geo_country == "CA"  # Cymru wins

        # Test DShield fallback
        ip3 = IPInventory(
            ip_address="10.0.0.3",
            first_seen=now,
            last_seen=now,
            enrichment={"dshield": {"ip": {"ascountry": "MX"}}},
        )
        db_session.add(ip3)
        assert ip3.geo_country == "MX"  # DShield wins

        # Test default fallback
        ip4 = IPInventory(
            ip_address="10.0.0.4",
            first_seen=now,
            last_seen=now,
            enrichment={},
        )
        db_session.add(ip4)
        assert ip4.geo_country == "XX"  # Default

    def test_ip_inventory_computed_ip_type(self, db_session: Session) -> None:
        """Test computed ip_type property from SPUR data."""
        now = datetime.now(timezone.utc)

        # Test with SPUR data
        ip1 = IPInventory(
            ip_address="10.0.0.1",
            first_seen=now,
            last_seen=now,
            enrichment={"spur": {"client": {"types": "RESIDENTIAL"}}},
        )
        db_session.add(ip1)
        assert ip1.ip_type == "RESIDENTIAL"

        # Test without SPUR data
        ip2 = IPInventory(
            ip_address="10.0.0.2",
            first_seen=now,
            last_seen=now,
            enrichment={},
        )
        db_session.add(ip2)
        assert ip2.ip_type is None

    def test_ip_inventory_computed_is_scanner(self, db_session: Session) -> None:
        """Test computed is_scanner property from GreyNoise."""
        now = datetime.now(timezone.utc)

        # Test scanner detection
        ip1 = IPInventory(
            ip_address="10.0.0.1",
            first_seen=now,
            last_seen=now,
            enrichment={"greynoise": {"noise": True}},
        )
        db_session.add(ip1)
        assert ip1.is_scanner is True

        # Test non-scanner
        ip2 = IPInventory(
            ip_address="10.0.0.2",
            first_seen=now,
            last_seen=now,
            enrichment={"greynoise": {"noise": False}},
        )
        db_session.add(ip2)
        assert ip2.is_scanner is False

        # Test missing data
        ip3 = IPInventory(
            ip_address="10.0.0.3",
            first_seen=now,
            last_seen=now,
            enrichment={},
        )
        db_session.add(ip3)
        assert ip3.is_scanner is False

    def test_ip_inventory_computed_is_bogon(self, db_session: Session) -> None:
        """Test computed is_bogon property from validation data."""
        now = datetime.now(timezone.utc)

        # Test bogon detection
        ip1 = IPInventory(
            ip_address="192.168.1.1",
            first_seen=now,
            last_seen=now,
            enrichment={"validation": {"is_bogon": True}},
        )
        db_session.add(ip1)
        assert ip1.is_bogon is True

        # Test non-bogon
        ip2 = IPInventory(
            ip_address="8.8.8.8",
            first_seen=now,
            last_seen=now,
            enrichment={"validation": {"is_bogon": False}},
        )
        db_session.add(ip2)
        assert ip2.is_bogon is False

    def test_ip_inventory_foreign_key_constraint(self, db_session: Session) -> None:
        """Test foreign key constraint to ASN inventory."""
        now = datetime.now(timezone.utc)

        # Create ASN first
        asn = ASNInventory(
            asn_number=15169,
            organization_name="Google",
            first_seen=now,
            last_seen=now,
        )
        db_session.add(asn)
        db_session.commit()

        # Create IP with valid ASN reference
        ip = IPInventory(
            ip_address="8.8.8.8",
            current_asn=15169,
            first_seen=now,
            last_seen=now,
        )
        db_session.add(ip)
        db_session.commit()

        result = db_session.execute(select(IPInventory).where(IPInventory.ip_address == "8.8.8.8")).scalar_one()
        assert result.current_asn == 15169

    def test_ip_inventory_defaults(self, db_session: Session) -> None:
        """Test IP inventory default values."""
        now = datetime.now(timezone.utc)
        ip = IPInventory(
            ip_address="1.1.1.1",
            first_seen=now,
            last_seen=now,
        )
        db_session.add(ip)
        db_session.commit()

        result = db_session.execute(select(IPInventory).where(IPInventory.ip_address == "1.1.1.1")).scalar_one()
        assert result.session_count == 1
        assert result.enrichment == {}
        assert result.enrichment_version == "2.2"


class TestIPASNHistory:
    """Test IP-ASN history model (optional tracking)."""

    def test_create_ip_asn_history(self, db_session: Session) -> None:
        """Test creating IP-ASN history records."""
        now = datetime.now(timezone.utc)

        # Record 1: Initial observation
        history1 = IPASNHistory(
            ip_address="1.2.3.4",
            asn_number=4134,
            observed_at=now - timedelta(days=30),
            verification_source="dshield",
        )
        db_session.add(history1)

        # Record 2: ASN change detected
        history2 = IPASNHistory(
            ip_address="1.2.3.4",
            asn_number=4837,
            observed_at=now,
            verification_source="maxmind",
        )
        db_session.add(history2)
        db_session.commit()

        # Retrieve all history for IP
        results = (
            db_session.execute(
                select(IPASNHistory).where(IPASNHistory.ip_address == "1.2.3.4").order_by(IPASNHistory.observed_at)
            )
            .scalars()
            .all()
        )

        assert len(results) == 2
        assert results[0].asn_number == 4134
        assert results[0].verification_source == "dshield"
        assert results[1].asn_number == 4837
        assert results[1].verification_source == "maxmind"

    def test_ip_asn_history_composite_primary_key(self, db_session: Session) -> None:
        """Test composite primary key enforcement (ip, asn, observed_at)."""
        now = datetime.now(timezone.utc)

        # First record
        history1 = IPASNHistory(
            ip_address="10.0.0.1",
            asn_number=15169,
            observed_at=now,
        )
        db_session.add(history1)
        db_session.commit()

        # Same IP and ASN at different time should work
        history2 = IPASNHistory(
            ip_address="10.0.0.1",
            asn_number=15169,
            observed_at=now + timedelta(hours=1),
        )
        db_session.add(history2)
        db_session.commit()

        results = db_session.execute(select(IPASNHistory).where(IPASNHistory.ip_address == "10.0.0.1")).scalars().all()
        assert len(results) == 2


class TestSessionSummary:
    """Test updated SessionSummary model (Tier 3) with snapshot columns."""

    def test_create_session_with_snapshots(self, db_session: Session) -> None:
        """Test creating session with snapshot columns."""
        now = datetime.now(timezone.utc)

        # Create dependencies
        asn = ASNInventory(
            asn_number=4134,
            organization_name="China Telecom",
            first_seen=now - timedelta(days=30),
            last_seen=now,
        )
        db_session.add(asn)

        ip = IPInventory(
            ip_address="1.2.3.4",
            current_asn=4134,
            first_seen=now - timedelta(days=7),
            last_seen=now,
            enrichment={
                "maxmind": {"country": "CN"},
                "spur": {"client": {"types": "RESIDENTIAL"}},
            },
        )
        db_session.add(ip)
        db_session.commit()

        # Create session with snapshots
        session = SessionSummary(
            session_id="abc123def456",
            source_ip="1.2.3.4",
            first_event_at=now - timedelta(hours=1),
            last_event_at=now,
            event_count=10,
            command_count=5,
            # Snapshot columns capture state at time of attack
            snapshot_asn=4134,
            snapshot_country="CN",
            snapshot_ip_type="RESIDENTIAL",
            # Behavioral clustering
            ssh_key_fingerprint="SHA256:abc123",
            password_hash="5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8",
            command_signature="wget_curl_pattern",
            # Full enrichment snapshot
            enrichment={
                "maxmind": {"country": "CN", "city": "Beijing"},
                "dshield": {"ip": {"asnum": "4134"}},
            },
            enrichment_at=now,
        )
        db_session.add(session)
        db_session.commit()

        # Retrieve and verify
        result = db_session.execute(
            select(SessionSummary).where(SessionSummary.session_id == "abc123def456")
        ).scalar_one()
        assert result.source_ip == "1.2.3.4"
        assert result.snapshot_asn == 4134
        assert result.snapshot_country == "CN"
        assert result.snapshot_ip_type == "RESIDENTIAL"
        assert result.ssh_key_fingerprint == "SHA256:abc123"
        assert result.enrichment["maxmind"]["country"] == "CN"

    def test_session_foreign_key_to_ip_inventory(self, db_session: Session) -> None:
        """Test foreign key relationship between session and IP inventory."""
        now = datetime.now(timezone.utc)

        # Create IP inventory
        ip = IPInventory(
            ip_address="8.8.8.8",
            first_seen=now,
            last_seen=now,
        )
        db_session.add(ip)
        db_session.commit()

        # Create session referencing IP
        session = SessionSummary(
            session_id="test123",
            source_ip="8.8.8.8",
            first_event_at=now,
            last_event_at=now,
        )
        db_session.add(session)
        db_session.commit()

        result = db_session.execute(select(SessionSummary).where(SessionSummary.session_id == "test123")).scalar_one()
        assert result.source_ip == "8.8.8.8"

    def test_session_backward_compatibility(self, db_session: Session) -> None:
        """Test that existing SessionSummary fields are preserved."""
        now = datetime.now(timezone.utc)

        # Create session with existing fields (no snapshot columns)
        session = SessionSummary(
            session_id="legacy123",
            first_event_at=now,
            last_event_at=now,
            event_count=5,
            command_count=3,
            file_downloads=1,
            login_attempts=2,
            ssh_key_injections=1,
            unique_ssh_keys=1,
            vt_flagged=True,
            dshield_flagged=False,
            risk_score=75,
            matcher="pattern_v1",
            source_files=["file1.json", "file2.json"],
            enrichment={"legacy": "data"},
        )
        db_session.add(session)
        db_session.commit()

        result = db_session.execute(select(SessionSummary).where(SessionSummary.session_id == "legacy123")).scalar_one()
        assert result.event_count == 5
        assert result.vt_flagged is True
        assert result.enrichment["legacy"] == "data"
        # New fields should be None/NULL
        assert result.snapshot_asn is None
        assert result.snapshot_country is None

    def test_session_snapshot_indexes(self, db_session: Session) -> None:
        """Test that snapshot columns have indexes for fast filtering."""
        from sqlalchemy import inspect

        if db_session.bind is None:
            pytest.skip("No database bind available")
        inspector = inspect(db_session.bind)
        indexes = inspector.get_indexes("session_summaries")

        # Check for snapshot indexes
        index_names = [idx["name"] for idx in indexes]
        assert "ix_session_summaries_snapshot_asn" in index_names
        assert "ix_session_summaries_snapshot_country" in index_names
        assert "ix_session_summaries_snapshot_ip_type" in index_names

    def test_session_behavioral_clustering_indexes(self, db_session: Session) -> None:
        """Test that behavioral clustering columns have indexes."""
        from sqlalchemy import inspect

        if db_session.bind is None:
            pytest.skip("No database bind available")
        inspector = inspect(db_session.bind)
        indexes = inspector.get_indexes("session_summaries")

        index_names = [idx["name"] for idx in indexes]
        assert "ix_session_summaries_ssh_key_fp" in index_names
        assert "ix_session_summaries_password_hash" in index_names
        assert "ix_session_summaries_command_sig" in index_names


class TestThreeTierRelationships:
    """Test relationships between all three tiers."""

    def test_complete_three_tier_workflow(self, db_session: Session) -> None:
        """Test complete workflow: ASN → IP → Session."""
        now = datetime.now(timezone.utc)

        # Tier 1: Create ASN
        asn = ASNInventory(
            asn_number=4134,
            organization_name="China Telecom",
            organization_country="CN",
            asn_type="ISP",
            first_seen=now - timedelta(days=365),
            last_seen=now,
            unique_ip_count=1000,
            total_session_count=5000,
        )
        db_session.add(asn)
        db_session.commit()

        # Tier 2: Create IP
        ip = IPInventory(
            ip_address="1.2.3.4",
            current_asn=4134,
            asn_last_verified=now,
            first_seen=now - timedelta(days=30),
            last_seen=now,
            session_count=10,
            enrichment={
                "maxmind": {"country": "CN", "city": "Beijing"},
                "spur": {"client": {"types": "RESIDENTIAL"}},
            },
            enrichment_updated_at=now,
        )
        db_session.add(ip)
        db_session.commit()

        # Tier 3: Create Session with snapshots
        session = SessionSummary(
            session_id="campaign_001",
            source_ip="1.2.3.4",
            first_event_at=now - timedelta(hours=2),
            last_event_at=now - timedelta(hours=1),
            event_count=25,
            command_count=10,
            snapshot_asn=4134,
            snapshot_country="CN",
            snapshot_ip_type="RESIDENTIAL",
            ssh_key_fingerprint="SHA256:botnet_key_1",
            enrichment={"snapshot": "at_attack_time"},
            enrichment_at=now - timedelta(hours=2),
        )
        db_session.add(session)
        db_session.commit()

        # Verify complete chain
        session_result = db_session.execute(
            select(SessionSummary).where(SessionSummary.session_id == "campaign_001")
        ).scalar_one()
        assert session_result.source_ip == "1.2.3.4"
        assert session_result.snapshot_asn == 4134

        ip_result = db_session.execute(select(IPInventory).where(IPInventory.ip_address == "1.2.3.4")).scalar_one()
        assert ip_result.current_asn == 4134

        asn_result = db_session.execute(select(ASNInventory).where(ASNInventory.asn_number == 4134)).scalar_one()
        assert asn_result.organization_name == "China Telecom"

    def test_ip_asn_movement_tracking(self, db_session: Session) -> None:
        """Test tracking IP movement between ASNs over time."""
        now = datetime.now(timezone.utc)

        # Create two ASNs
        asn1 = ASNInventory(asn_number=4134, first_seen=now - timedelta(days=60), last_seen=now)
        asn2 = ASNInventory(asn_number=4837, first_seen=now - timedelta(days=60), last_seen=now)
        db_session.add_all([asn1, asn2])
        db_session.commit()

        # Create IP initially with ASN 4134
        ip = IPInventory(
            ip_address="1.2.3.4",
            current_asn=4134,
            asn_last_verified=now - timedelta(days=30),
            first_seen=now - timedelta(days=30),
            last_seen=now,
        )
        db_session.add(ip)
        db_session.commit()

        # Record history: IP was in ASN 4134
        history1 = IPASNHistory(
            ip_address="1.2.3.4",
            asn_number=4134,
            observed_at=now - timedelta(days=30),
            verification_source="dshield",
        )
        db_session.add(history1)

        # Create session during ASN 4134 period (snapshot preserves this)
        session1 = SessionSummary(
            session_id="old_session",
            source_ip="1.2.3.4",
            first_event_at=now - timedelta(days=25),
            last_event_at=now - timedelta(days=25),
            snapshot_asn=4134,  # Snapshot at time of attack
        )
        db_session.add(session1)
        db_session.commit()

        # IP moves to ASN 4837
        ip.current_asn = 4837  # type: ignore[assignment]
        ip.asn_last_verified = now  # type: ignore[assignment]
        db_session.commit()

        # Record history: IP moved to ASN 4837
        history2 = IPASNHistory(
            ip_address="1.2.3.4",
            asn_number=4837,
            observed_at=now,
            verification_source="maxmind",
        )
        db_session.add(history2)

        # Create new session (snapshot shows new ASN)
        session2 = SessionSummary(
            session_id="new_session",
            source_ip="1.2.3.4",
            first_event_at=now,
            last_event_at=now,
            snapshot_asn=4837,  # Snapshot at time of attack
        )
        db_session.add(session2)
        db_session.commit()

        # Verify: IP current state is ASN 4837
        ip_current = db_session.execute(select(IPInventory).where(IPInventory.ip_address == "1.2.3.4")).scalar_one()
        assert ip_current.current_asn == 4837

        # Verify: Old session preserves ASN 4134 snapshot
        old_session = db_session.execute(
            select(SessionSummary).where(SessionSummary.session_id == "old_session")
        ).scalar_one()
        assert old_session.snapshot_asn == 4134  # Historical accuracy preserved

        # Verify: New session has ASN 4837 snapshot
        new_session = db_session.execute(
            select(SessionSummary).where(SessionSummary.session_id == "new_session")
        ).scalar_one()
        assert new_session.snapshot_asn == 4837

        # Verify: History shows both ASNs
        history = (
            db_session.execute(
                select(IPASNHistory).where(IPASNHistory.ip_address == "1.2.3.4").order_by(IPASNHistory.observed_at)
            )
            .scalars()
            .all()
        )
        assert len(history) == 2
        assert history[0].asn_number == 4134
        assert history[1].asn_number == 4837
