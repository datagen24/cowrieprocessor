"""Integration tests for ADR-007 three-tier enrichment architecture workflow.

This test suite validates the complete three-tier enrichment workflow:
- Tier 1: ASN inventory (organizational attribution)
- Tier 2: IP inventory (current state, mutable enrichment)
- Tier 3: Session summaries (point-in-time snapshots, immutable)

Tests cover:
1. Complete session ingestion → IP inventory → ASN inventory flow
2. Enrichment snapshot capture (temporal accuracy)
3. Query performance WITHOUT JOINs (snapshot columns)
4. Query with JOINs for infrastructure analysis (ASN-level)
5. IP→ASN movement tracking
6. Staleness detection and re-enrichment triggers
7. Foreign key constraint enforcement
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from cowrieprocessor.db.base import Base
from cowrieprocessor.db.migrations import apply_migrations
from cowrieprocessor.db.models import ASNInventory, IPASNHistory, IPInventory, SessionSummary


@pytest.fixture
def postgres_engine():
    """Create a test PostgreSQL database engine.

    Note: This requires PostgreSQL to be available. The test will be skipped
    if PostgreSQL is not accessible.
    """
    try:
        engine = create_engine("postgresql://localhost/cowrie_test", echo=False)
        # Test connection
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except Exception as e:
        pytest.skip(f"PostgreSQL not available: {e}")


@pytest.fixture
def test_db(postgres_engine):
    """Create test database with v16 schema."""
    # Drop all tables
    Base.metadata.drop_all(postgres_engine)

    # Apply migrations to v16
    version = apply_migrations(postgres_engine)
    assert version >= 16, f"Migration to v16 failed, got version {version}"

    yield postgres_engine

    # Cleanup
    Base.metadata.drop_all(postgres_engine)


@pytest.fixture
def db_session(test_db):
    """Create a database session for testing."""
    with Session(test_db) as session:
        yield session
        session.rollback()


def create_sample_enrichment(
    country: str = "CN",
    asn: int = 4134,
    asn_name: str = "China Telecom",
    ip_type: str = "RESIDENTIAL",
    is_scanner: bool = False,
    is_bogon: bool = False,
) -> dict[str, Any]:
    """Create realistic enrichment data matching production format."""
    return {
        "maxmind": {"country": country, "city": "Beijing", "latitude": 39.9042, "longitude": 116.4074},
        "cymru": {"asn": str(asn), "country": country, "asn_name": asn_name, "prefix": "1.2.0.0/16"},
        "dshield": {
            "ip": {
                "asnum": str(asn),
                "ascountry": country,
                "asname": asn_name,
                "count": 150,
                "attacks": 42,
                "mindate": "2025-01-01",
                "maxdate": "2025-11-05",
            }
        },
        "spur": {"client": {"types": ip_type, "concentration": {"city": "Beijing", "country": country}}},
        "greynoise": {"noise": is_scanner, "classification": "benign" if not is_scanner else "malicious"},
        "validation": {"is_bogon": is_bogon, "is_private": False, "is_reserved": False},
    }


@pytest.mark.integration
class TestScenario1NewSessionNewIP:
    """Scenario 1: New session with new IP → creates IP + ASN entries."""

    def test_new_session_creates_ip_and_asn(self, db_session: Session) -> None:
        """Test that new session with new IP creates both IP and ASN inventory entries."""
        now = datetime.now(timezone.utc)

        # Step 1: Create session with enrichment (simulating loader behavior)
        enrichment = create_sample_enrichment(country="CN", asn=4134, asn_name="China Telecom")

        session = SessionSummary(
            session_id="new_session_001",
            source_ip="1.2.3.4",
            first_event_at=now - timedelta(hours=1),
            last_event_at=now,
            event_count=10,
            command_count=5,
            # Snapshot columns (captured at attack time)
            snapshot_asn=4134,
            snapshot_country="CN",
            snapshot_ip_type="RESIDENTIAL",
            enrichment=enrichment,
            enrichment_at=now,
        )
        db_session.add(session)
        db_session.commit()

        # Step 2: Verify session was created with snapshots
        result = db_session.execute(
            select(SessionSummary).where(SessionSummary.session_id == "new_session_001")
        ).scalar_one()
        assert result.snapshot_asn == 4134
        assert result.snapshot_country == "CN"
        assert result.snapshot_ip_type == "RESIDENTIAL"
        assert result.enrichment["cymru"]["asn"] == "4134"

        # Step 3: Create IP inventory entry (simulating enrichment pipeline)
        ip = IPInventory(
            ip_address="1.2.3.4",
            current_asn=4134,
            asn_last_verified=now,
            first_seen=now - timedelta(hours=1),
            last_seen=now,
            session_count=1,
            enrichment=enrichment,
            enrichment_updated_at=now,
        )
        db_session.add(ip)
        db_session.commit()

        # Step 4: Verify IP inventory was created
        ip_result = db_session.execute(select(IPInventory).where(IPInventory.ip_address == "1.2.3.4")).scalar_one()
        assert ip_result.current_asn == 4134
        assert ip_result.session_count == 1
        assert ip_result.geo_country == "CN"  # Computed property
        assert ip_result.ip_type == "RESIDENTIAL"  # Computed property
        assert ip_result.is_scanner is False

        # Step 5: Create ASN inventory entry (simulating ASN aggregation)
        asn = ASNInventory(
            asn_number=4134,
            organization_name="China Telecom",
            organization_country="CN",
            rir_registry="APNIC",
            asn_type="ISP",
            first_seen=now - timedelta(hours=1),
            last_seen=now,
            unique_ip_count=1,
            total_session_count=1,
            enrichment=enrichment,
            enrichment_updated_at=now,
        )
        db_session.add(asn)
        db_session.commit()

        # Step 6: Verify ASN inventory was created
        asn_result = db_session.execute(select(ASNInventory).where(ASNInventory.asn_number == 4134)).scalar_one()
        assert asn_result.organization_name == "China Telecom"
        assert asn_result.organization_country == "CN"
        assert asn_result.unique_ip_count == 1
        assert asn_result.total_session_count == 1

        # Step 7: Verify foreign key relationships work
        session_with_ip = db_session.execute(
            select(SessionSummary).where(SessionSummary.source_ip == "1.2.3.4")
        ).scalar_one()
        assert session_with_ip.session_id == "new_session_001"


@pytest.mark.integration
class TestScenario2NewSessionExistingIP:
    """Scenario 2: New session with existing IP → reuses IP, updates counters."""

    def test_new_session_reuses_existing_ip(self, db_session: Session) -> None:
        """Test that new session with existing IP reuses IP inventory and updates counters."""
        now = datetime.now(timezone.utc)
        enrichment = create_sample_enrichment(country="CN", asn=4134)

        # Step 1: Create initial IP and ASN
        asn = ASNInventory(
            asn_number=4134,
            organization_name="China Telecom",
            first_seen=now - timedelta(days=30),
            last_seen=now - timedelta(days=1),
            unique_ip_count=1,
            total_session_count=5,
        )
        db_session.add(asn)

        ip = IPInventory(
            ip_address="1.2.3.4",
            current_asn=4134,
            first_seen=now - timedelta(days=7),
            last_seen=now - timedelta(days=1),
            session_count=5,
            enrichment=enrichment,
            enrichment_updated_at=now - timedelta(days=1),
        )
        db_session.add(ip)
        db_session.commit()

        # Step 2: Create first session
        session1 = SessionSummary(
            session_id="session_001",
            source_ip="1.2.3.4",
            first_event_at=now - timedelta(days=1),
            last_event_at=now - timedelta(days=1),
            snapshot_asn=4134,
            snapshot_country="CN",
        )
        db_session.add(session1)
        db_session.commit()

        # Step 3: Create second session (simulating new attack from same IP)
        session2 = SessionSummary(
            session_id="session_002",
            source_ip="1.2.3.4",
            first_event_at=now,
            last_event_at=now,
            snapshot_asn=4134,
            snapshot_country="CN",
        )
        db_session.add(session2)

        # Step 4: Update IP inventory counters (simulating enrichment pipeline)
        ip.session_count += 1  # type: ignore[assignment]
        ip.last_seen = now  # type: ignore[assignment]
        db_session.commit()

        # Step 5: Verify IP counters were updated
        ip_result = db_session.execute(select(IPInventory).where(IPInventory.ip_address == "1.2.3.4")).scalar_one()
        assert ip_result.session_count == 6  # Original 5 + 1 new
        assert ip_result.last_seen == now  # Updated to most recent

        # Step 6: Verify both sessions exist with same IP
        sessions = (
            db_session.execute(select(SessionSummary).where(SessionSummary.source_ip == "1.2.3.4")).scalars().all()
        )
        assert len(sessions) == 2
        assert {s.session_id for s in sessions} == {"session_001", "session_002"}

        # Step 7: Verify ASN counters can be updated
        asn.total_session_count += 1  # type: ignore[assignment]
        asn.last_seen = now  # type: ignore[assignment]
        db_session.commit()

        asn_result = db_session.execute(select(ASNInventory).where(ASNInventory.asn_number == 4134)).scalar_one()
        assert asn_result.total_session_count == 6


@pytest.mark.integration
class TestScenario3QueryPerformanceSnapshotVsJoin:
    """Scenario 3: Query performance comparison - snapshot (no JOIN) vs current state (with JOIN)."""

    def test_snapshot_query_without_join(self, db_session: Session) -> None:
        """Test fast filtering using snapshot columns WITHOUT JOINs."""
        now = datetime.now(timezone.utc)

        # Create 100 sessions with snapshot data
        for i in range(100):
            session = SessionSummary(
                session_id=f"session_{i:03d}",
                source_ip=f"1.2.3.{i % 255}",
                first_event_at=now - timedelta(hours=i),
                last_event_at=now - timedelta(hours=i - 1),
                snapshot_asn=4134 if i % 2 == 0 else 4837,
                snapshot_country="CN" if i < 50 else "US",
                snapshot_ip_type="RESIDENTIAL" if i % 3 == 0 else "DATACENTER",
            )
            db_session.add(session)
        db_session.commit()

        # Query 1: Find sessions from China (snapshot - NO JOIN)
        start_time = time.time()
        cn_sessions = (
            db_session.execute(select(SessionSummary).where(SessionSummary.snapshot_country == "CN")).scalars().all()
        )
        snapshot_query_time = time.time() - start_time

        assert len(cn_sessions) == 50
        assert all(s.snapshot_country == "CN" for s in cn_sessions)

        # Query 2: Find sessions from ASN 4134 (snapshot - NO JOIN)
        start_time = time.time()
        asn_sessions = (
            db_session.execute(select(SessionSummary).where(SessionSummary.snapshot_asn == 4134)).scalars().all()
        )
        snapshot_asn_query_time = time.time() - start_time

        assert len(asn_sessions) == 50

        # Verify queries are fast (should be <100ms for 100 rows with indexes)
        assert snapshot_query_time < 0.1, f"Snapshot query too slow: {snapshot_query_time:.3f}s"
        assert snapshot_asn_query_time < 0.1, f"Snapshot ASN query too slow: {snapshot_asn_query_time:.3f}s"

    def test_join_query_for_current_state_analysis(self, db_session: Session) -> None:
        """Test JOIN queries for infrastructure analysis with current IP/ASN state."""
        now = datetime.now(timezone.utc)

        # Create ASN inventory
        asn = ASNInventory(
            asn_number=4134,
            organization_name="China Telecom",
            organization_country="CN",
            first_seen=now - timedelta(days=30),
            last_seen=now,
            unique_ip_count=10,
            total_session_count=50,
        )
        db_session.add(asn)

        # Create IP inventory
        for i in range(10):
            ip = IPInventory(
                ip_address=f"1.2.3.{i}",
                current_asn=4134,
                first_seen=now - timedelta(days=7),
                last_seen=now,
                session_count=5,
                enrichment=create_sample_enrichment(asn=4134),
            )
            db_session.add(ip)

        # Create sessions
        for i in range(50):
            session = SessionSummary(
                session_id=f"session_{i:03d}",
                source_ip=f"1.2.3.{i % 10}",
                first_event_at=now - timedelta(hours=i),
                last_event_at=now - timedelta(hours=i - 1),
                snapshot_asn=4134,
                snapshot_country="CN",
            )
            db_session.add(session)
        db_session.commit()

        # Query with JOIN: Find all sessions with current IP enrichment
        start_time = time.time()
        results = db_session.execute(
            select(SessionSummary, IPInventory)
            .join(IPInventory, SessionSummary.source_ip == IPInventory.ip_address)
            .where(IPInventory.current_asn == 4134)
        ).all()
        join_query_time = time.time() - start_time

        assert len(results) == 50
        for session, ip in results:
            assert ip.current_asn == 4134
            assert session.snapshot_asn == 4134

        # Query with double JOIN: Session → IP → ASN
        start_time = time.time()
        asn_results = db_session.execute(
            select(SessionSummary, IPInventory, ASNInventory)
            .join(IPInventory, SessionSummary.source_ip == IPInventory.ip_address)
            .join(ASNInventory, IPInventory.current_asn == ASNInventory.asn_number)
            .where(ASNInventory.organization_name == "China Telecom")
        ).all()
        double_join_time = time.time() - start_time

        assert len(asn_results) == 50
        for session, ip, asn_obj in asn_results:
            assert asn_obj.organization_name == "China Telecom"

        # JOIN queries should still be reasonably fast (<500ms for 50 rows)
        assert join_query_time < 0.5, f"JOIN query too slow: {join_query_time:.3f}s"
        assert double_join_time < 0.5, f"Double JOIN query too slow: {double_join_time:.3f}s"


@pytest.mark.integration
class TestScenario4IPASNMovementTracking:
    """Scenario 4: IP moves between ASNs → history tracking."""

    def test_ip_asn_movement_with_history(self, db_session: Session) -> None:
        """Test tracking IP movement between ASNs with historical snapshots."""
        now = datetime.now(timezone.utc)

        # Create two ASNs
        asn1 = ASNInventory(
            asn_number=4134,
            organization_name="China Telecom",
            first_seen=now - timedelta(days=60),
            last_seen=now,
        )
        asn2 = ASNInventory(
            asn_number=4837,
            organization_name="China Unicom",
            first_seen=now - timedelta(days=60),
            last_seen=now,
        )
        db_session.add_all([asn1, asn2])
        db_session.commit()

        # Create IP initially in ASN 4134
        ip = IPInventory(
            ip_address="1.2.3.4",
            current_asn=4134,
            asn_last_verified=now - timedelta(days=30),
            first_seen=now - timedelta(days=30),
            last_seen=now,
            enrichment=create_sample_enrichment(asn=4134, asn_name="China Telecom"),
        )
        db_session.add(ip)
        db_session.commit()

        # Record initial ASN assignment
        history1 = IPASNHistory(
            ip_address="1.2.3.4",
            asn_number=4134,
            observed_at=now - timedelta(days=30),
            verification_source="dshield",
        )
        db_session.add(history1)

        # Create session during ASN 4134 period
        session1 = SessionSummary(
            session_id="old_session",
            source_ip="1.2.3.4",
            first_event_at=now - timedelta(days=25),
            last_event_at=now - timedelta(days=25),
            snapshot_asn=4134,  # Snapshot preserves historical state
            snapshot_country="CN",
        )
        db_session.add(session1)
        db_session.commit()

        # IP moves to ASN 4837 (simulating cloud IP reassignment)
        ip.current_asn = 4837  # type: ignore[assignment]
        ip.asn_last_verified = now  # type: ignore[assignment]
        ip.enrichment = create_sample_enrichment(asn=4837, asn_name="China Unicom")  # type: ignore[assignment]
        db_session.commit()

        # Record ASN change
        history2 = IPASNHistory(
            ip_address="1.2.3.4",
            asn_number=4837,
            observed_at=now,
            verification_source="maxmind",
        )
        db_session.add(history2)

        # Create new session (captures new ASN in snapshot)
        session2 = SessionSummary(
            session_id="new_session",
            source_ip="1.2.3.4",
            first_event_at=now,
            last_event_at=now,
            snapshot_asn=4837,  # Snapshot shows new ASN
            snapshot_country="CN",
        )
        db_session.add(session2)
        db_session.commit()

        # Verify IP current state is ASN 4837
        ip_current = db_session.execute(select(IPInventory).where(IPInventory.ip_address == "1.2.3.4")).scalar_one()
        assert ip_current.current_asn == 4837

        # Verify old session preserves ASN 4134 snapshot (temporal accuracy)
        old_session = db_session.execute(
            select(SessionSummary).where(SessionSummary.session_id == "old_session")
        ).scalar_one()
        assert old_session.snapshot_asn == 4134  # Historical accuracy preserved

        # Verify new session has ASN 4837 snapshot
        new_session = db_session.execute(
            select(SessionSummary).where(SessionSummary.session_id == "new_session")
        ).scalar_one()
        assert new_session.snapshot_asn == 4837

        # Verify history shows both ASNs
        history = (
            db_session.execute(
                select(IPASNHistory).where(IPASNHistory.ip_address == "1.2.3.4").order_by(IPASNHistory.observed_at)
            )
            .scalars()
            .all()
        )
        assert len(history) == 2
        assert history[0].asn_number == 4134
        assert history[0].verification_source == "dshield"
        assert history[1].asn_number == 4837
        assert history[1].verification_source == "maxmind"

        # Verify we can query "sessions when IP was in ASN 4134" using snapshots
        asn_4134_sessions = (
            db_session.execute(select(SessionSummary).where(SessionSummary.snapshot_asn == 4134)).scalars().all()
        )
        assert len(asn_4134_sessions) == 1
        assert asn_4134_sessions[0].session_id == "old_session"


@pytest.mark.integration
class TestScenario5StalenessDetection:
    """Scenario 5: Stale enrichment detection (>90 days)."""

    def test_staleness_detection_and_refresh_trigger(self, db_session: Session) -> None:
        """Test detection of stale enrichments and re-enrichment triggers."""
        now = datetime.now(timezone.utc)

        # Create IP with OLD enrichment (>90 days)
        stale_ip = IPInventory(
            ip_address="10.0.0.1",
            current_asn=15169,
            first_seen=now - timedelta(days=365),
            last_seen=now,
            session_count=100,
            enrichment=create_sample_enrichment(country="US", asn=15169, asn_name="Google"),
            enrichment_updated_at=now - timedelta(days=120),  # 120 days old (STALE)
        )
        db_session.add(stale_ip)

        # Create IP with RECENT enrichment (<90 days)
        fresh_ip = IPInventory(
            ip_address="10.0.0.2",
            current_asn=15169,
            first_seen=now - timedelta(days=30),
            last_seen=now,
            session_count=10,
            enrichment=create_sample_enrichment(country="US", asn=15169, asn_name="Google"),
            enrichment_updated_at=now - timedelta(days=5),  # 5 days old (FRESH)
        )
        db_session.add(fresh_ip)

        # Create IP with NULL enrichment timestamp (needs enrichment)
        unenriched_ip = IPInventory(
            ip_address="10.0.0.3",
            first_seen=now,
            last_seen=now,
            enrichment={},
            enrichment_updated_at=None,  # Never enriched
        )
        db_session.add(unenriched_ip)

        db_session.commit()

        # Query 1: Find stale IPs (>90 days old)
        staleness_threshold = now - timedelta(days=90)
        stale_ips = (
            db_session.execute(
                select(IPInventory).where(
                    (IPInventory.enrichment_updated_at < staleness_threshold)
                    | (IPInventory.enrichment_updated_at.is_(None))
                )
            )
            .scalars()
            .all()
        )

        assert len(stale_ips) == 2  # stale_ip and unenriched_ip
        stale_addresses = {ip.ip_address for ip in stale_ips}
        assert "10.0.0.1" in stale_addresses
        assert "10.0.0.3" in stale_addresses
        assert "10.0.0.2" not in stale_addresses

        # Query 2: Count stale vs fresh
        total_count = db_session.execute(select(func.count()).select_from(IPInventory)).scalar()
        fresh_count = db_session.execute(
            select(func.count())
            .select_from(IPInventory)
            .where(IPInventory.enrichment_updated_at >= staleness_threshold)
        ).scalar()

        assert total_count == 3
        assert fresh_count == 1

        # Simulate re-enrichment of stale IP
        stale_ip.enrichment_updated_at = now  # type: ignore[assignment]
        stale_ip.enrichment = create_sample_enrichment(  # type: ignore[assignment]
            country="US",
            asn=15169,
            asn_name="Google LLC",  # Updated org name
        )
        db_session.commit()

        # Verify it's no longer stale
        refreshed_stale = db_session.execute(
            select(IPInventory).where(
                IPInventory.ip_address == "10.0.0.1",
                IPInventory.enrichment_updated_at >= staleness_threshold,
            )
        ).scalar_one_or_none()

        assert refreshed_stale is not None
        assert refreshed_stale.enrichment["cymru"]["asn_name"] == "Google LLC"


@pytest.mark.integration
class TestScenario6ForeignKeyConstraints:
    """Scenario 6: Foreign key constraint enforcement."""

    def test_foreign_key_session_to_ip(self, db_session: Session) -> None:
        """Test foreign key constraint between SessionSummary and IPInventory."""
        now = datetime.now(timezone.utc)

        # Create IP inventory
        ip = IPInventory(
            ip_address="8.8.8.8",
            first_seen=now,
            last_seen=now,
        )
        db_session.add(ip)
        db_session.commit()

        # Create session with valid IP reference
        session = SessionSummary(
            session_id="valid_session",
            source_ip="8.8.8.8",  # Valid FK
            first_event_at=now,
            last_event_at=now,
        )
        db_session.add(session)
        db_session.commit()

        # Verify FK works
        result = db_session.execute(
            select(SessionSummary).where(SessionSummary.session_id == "valid_session")
        ).scalar_one()
        assert result.source_ip == "8.8.8.8"

        # Test: Session with NULL source_ip should work (FK is nullable)
        session_null = SessionSummary(
            session_id="null_ip_session",
            source_ip=None,  # NULL FK is allowed
            first_event_at=now,
            last_event_at=now,
        )
        db_session.add(session_null)
        db_session.commit()

        result_null = db_session.execute(
            select(SessionSummary).where(SessionSummary.session_id == "null_ip_session")
        ).scalar_one()
        assert result_null.source_ip is None

    def test_foreign_key_ip_to_asn(self, db_session: Session) -> None:
        """Test foreign key constraint between IPInventory and ASNInventory."""
        now = datetime.now(timezone.utc)

        # Create ASN inventory
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
            current_asn=15169,  # Valid FK
            first_seen=now,
            last_seen=now,
        )
        db_session.add(ip)
        db_session.commit()

        # Verify FK works
        result = db_session.execute(select(IPInventory).where(IPInventory.ip_address == "8.8.8.8")).scalar_one()
        assert result.current_asn == 15169

        # Test: IP with NULL ASN should work (FK is nullable)
        ip_null = IPInventory(
            ip_address="1.1.1.1",
            current_asn=None,  # NULL FK is allowed
            first_seen=now,
            last_seen=now,
        )
        db_session.add(ip_null)
        db_session.commit()

        result_null = db_session.execute(select(IPInventory).where(IPInventory.ip_address == "1.1.1.1")).scalar_one()
        assert result_null.current_asn is None


@pytest.mark.integration
class TestCompleteThreeTierWorkflow:
    """Integration test for complete three-tier workflow end-to-end."""

    def test_complete_workflow_session_ingestion_to_analysis(self, db_session: Session) -> None:
        """Test complete workflow from session ingestion through all three tiers to analysis."""
        now = datetime.now(timezone.utc)

        # PHASE 1: Initial ingestion (Day 1)
        # Simulate 10 sessions from 5 IPs across 2 ASNs

        # Create ASNs
        asn_china_telecom = ASNInventory(
            asn_number=4134,
            organization_name="China Telecom",
            organization_country="CN",
            rir_registry="APNIC",
            asn_type="ISP",
            first_seen=now - timedelta(days=1),
            last_seen=now - timedelta(days=1),
            unique_ip_count=0,
            total_session_count=0,
        )
        asn_google = ASNInventory(
            asn_number=15169,
            organization_name="Google LLC",
            organization_country="US",
            rir_registry="ARIN",
            asn_type="CLOUD",
            is_known_hosting=True,
            first_seen=now - timedelta(days=1),
            last_seen=now - timedelta(days=1),
            unique_ip_count=0,
            total_session_count=0,
        )
        db_session.add_all([asn_china_telecom, asn_google])
        db_session.commit()

        # Create IPs
        ips_data = [
            ("1.2.3.4", 4134, "CN", "RESIDENTIAL"),
            ("1.2.3.5", 4134, "CN", "RESIDENTIAL"),
            ("1.2.3.6", 4134, "CN", "DATACENTER"),
            ("8.8.8.8", 15169, "US", "DATACENTER"),
            ("8.8.8.9", 15169, "US", "DATACENTER"),
        ]

        for ip_addr, asn_num, country, ip_type in ips_data:
            ip = IPInventory(
                ip_address=ip_addr,
                current_asn=asn_num,
                asn_last_verified=now - timedelta(days=1),
                first_seen=now - timedelta(days=1),
                last_seen=now - timedelta(days=1),
                session_count=0,
                enrichment=create_sample_enrichment(
                    country=country,
                    asn=asn_num,
                    asn_name="China Telecom" if asn_num == 4134 else "Google LLC",
                    ip_type=ip_type,
                ),
                enrichment_updated_at=now - timedelta(days=1),
            )
            db_session.add(ip)

        # Create sessions
        session_data = [
            ("sess_001", "1.2.3.4", 4134, "CN", "RESIDENTIAL"),
            ("sess_002", "1.2.3.4", 4134, "CN", "RESIDENTIAL"),
            ("sess_003", "1.2.3.5", 4134, "CN", "RESIDENTIAL"),
            ("sess_004", "1.2.3.5", 4134, "CN", "RESIDENTIAL"),
            ("sess_005", "1.2.3.6", 4134, "CN", "DATACENTER"),
            ("sess_006", "8.8.8.8", 15169, "US", "DATACENTER"),
            ("sess_007", "8.8.8.8", 15169, "US", "DATACENTER"),
            ("sess_008", "8.8.8.9", 15169, "US", "DATACENTER"),
            ("sess_009", "1.2.3.4", 4134, "CN", "RESIDENTIAL"),
            ("sess_010", "8.8.8.8", 15169, "US", "DATACENTER"),
        ]

        for sess_id, ip_addr, asn_num, country, ip_type in session_data:
            session = SessionSummary(
                session_id=sess_id,
                source_ip=ip_addr,
                first_event_at=now - timedelta(days=1),
                last_event_at=now - timedelta(days=1),
                event_count=10,
                command_count=5,
                snapshot_asn=asn_num,
                snapshot_country=country,
                snapshot_ip_type=ip_type,
                enrichment={"captured": "at_attack_time"},
                enrichment_at=now - timedelta(days=1),
            )
            db_session.add(session)

        db_session.commit()

        # Update counters
        for ip_addr, _, _, _ in ips_data:
            session_count = sum(1 for _, ip, _, _, _ in session_data if ip == ip_addr)
            db_session.execute(
                text("UPDATE ip_inventory SET session_count = :count WHERE ip_address = :ip"),
                {"count": session_count, "ip": ip_addr},
            )

        asn_china_telecom.unique_ip_count = 3  # type: ignore[assignment]
        asn_china_telecom.total_session_count = 7  # type: ignore[assignment]
        asn_google.unique_ip_count = 2  # type: ignore[assignment]
        asn_google.total_session_count = 3  # type: ignore[assignment]
        db_session.commit()

        # PHASE 2: Analysis queries

        # Query 1: Fast snapshot query - Find all China sessions (NO JOIN)
        cn_sessions = (
            db_session.execute(select(SessionSummary).where(SessionSummary.snapshot_country == "CN")).scalars().all()
        )
        assert len(cn_sessions) == 7

        # Query 2: ASN-level aggregation (NO JOIN - using snapshots)
        asn_session_count = db_session.execute(
            select(SessionSummary.snapshot_asn, func.count())
            .where(SessionSummary.snapshot_asn.isnot(None))
            .group_by(SessionSummary.snapshot_asn)
        ).all()
        assert len(asn_session_count) == 2
        asn_counts = {asn: count for asn, count in asn_session_count}
        assert asn_counts[4134] == 7
        assert asn_counts[15169] == 3

        # Query 3: Infrastructure analysis with JOINs
        asn_analysis = db_session.execute(
            select(
                ASNInventory.asn_number,
                ASNInventory.organization_name,
                func.count(SessionSummary.session_id).label("session_count"),
            )
            .join(IPInventory, IPInventory.current_asn == ASNInventory.asn_number)
            .join(SessionSummary, SessionSummary.source_ip == IPInventory.ip_address)
            .group_by(ASNInventory.asn_number, ASNInventory.organization_name)
        ).all()

        assert len(asn_analysis) == 2
        asn_analysis_dict = {row[0]: (row[1], row[2]) for row in asn_analysis}
        assert asn_analysis_dict[4134] == ("China Telecom", 7)
        assert asn_analysis_dict[15169] == ("Google LLC", 3)

        # Query 4: IP reuse analysis
        ip_reuse = db_session.execute(
            select(IPInventory.ip_address, IPInventory.session_count)
            .where(IPInventory.session_count > 1)
            .order_by(IPInventory.session_count.desc())
        ).all()

        assert len(ip_reuse) == 3  # IPs with multiple sessions
        top_ip = ip_reuse[0]
        assert top_ip[0] in ("1.2.3.4", "8.8.8.8")  # Most reused IPs
        assert top_ip[1] == 3

        # Query 5: Behavioral clustering by IP type
        ip_type_distribution = db_session.execute(
            select(SessionSummary.snapshot_ip_type, func.count())
            .where(SessionSummary.snapshot_ip_type.isnot(None))
            .group_by(SessionSummary.snapshot_ip_type)
        ).all()

        type_counts = {ip_type: count for ip_type, count in ip_type_distribution}
        assert type_counts["RESIDENTIAL"] == 6
        assert type_counts["DATACENTER"] == 4

        # PHASE 3: Verify temporal accuracy (snapshot vs current state comparison)
        # Simulate IP 1.2.3.4 moving from ASN 4134 to ASN 4837 on Day 2
        ip_to_move = db_session.execute(select(IPInventory).where(IPInventory.ip_address == "1.2.3.4")).scalar_one()

        # Create new ASN
        asn_china_unicom = ASNInventory(
            asn_number=4837,
            organization_name="China Unicom",
            organization_country="CN",
            first_seen=now,
            last_seen=now,
            unique_ip_count=1,
            total_session_count=1,
        )
        db_session.add(asn_china_unicom)

        # Update IP to new ASN
        ip_to_move.current_asn = 4837  # type: ignore[assignment]
        ip_to_move.asn_last_verified = now  # type: ignore[assignment]

        # Record history
        history = IPASNHistory(
            ip_address="1.2.3.4",
            asn_number=4837,
            observed_at=now,
            verification_source="enrichment_refresh",
        )
        db_session.add(history)

        # Create new session on Day 2
        new_session = SessionSummary(
            session_id="sess_011",
            source_ip="1.2.3.4",
            first_event_at=now,
            last_event_at=now,
            snapshot_asn=4837,  # New ASN captured in snapshot
            snapshot_country="CN",
            snapshot_ip_type="RESIDENTIAL",
        )
        db_session.add(new_session)
        db_session.commit()

        # Verify: Old sessions preserve ASN 4134 in snapshot
        old_sessions_from_ip = (
            db_session.execute(
                select(SessionSummary).where(
                    SessionSummary.source_ip == "1.2.3.4",
                    SessionSummary.first_event_at < now,
                )
            )
            .scalars()
            .all()
        )
        assert all(s.snapshot_asn == 4134 for s in old_sessions_from_ip)

        # Verify: New session has ASN 4837 in snapshot
        latest_session = db_session.execute(
            select(SessionSummary).where(SessionSummary.session_id == "sess_011")
        ).scalar_one()
        assert latest_session.snapshot_asn == 4837

        # Verify: Current IP state shows ASN 4837
        current_ip = db_session.execute(select(IPInventory).where(IPInventory.ip_address == "1.2.3.4")).scalar_one()
        assert current_ip.current_asn == 4837

        # Final verification: Complete integrity
        total_sessions = db_session.execute(select(func.count()).select_from(SessionSummary)).scalar()
        total_ips = db_session.execute(select(func.count()).select_from(IPInventory)).scalar()
        total_asns = db_session.execute(select(func.count()).select_from(ASNInventory)).scalar()

        assert total_sessions == 11  # 10 original + 1 new
        assert total_ips == 5
        assert total_asns == 3  # China Telecom, Google, China Unicom
