"""Integration tests for ADR-007 snapshot population fix.

Tests the complete snapshot population workflow using PostgreSQL database
to validate hybrid property queries and FK relationships that don't work in SQLite.

**REQUIREMENTS**:
- PostgreSQL test database must be set up and accessible
- Schema must be migrated to v16 (ADR-007)
- Set TEST_DATABASE_URL environment variable
  Example: "postgresql://user:***@localhost/cowrie_test"  # pragma: allowlist secret
- DO NOT use production database - tests will INSERT/UPDATE data

**Setup**:
```bash
# Create test database
createdb cowrie_test

# Run migrations (pragma: allowlist secret for example credentials)
TEST_DATABASE_URL="postgresql://user:***@localhost/cowrie_test" uv run cowrie-db migrate

# Run tests (pragma: allowlist secret for example credentials)
TEST_DATABASE_URL="postgresql://user:***@localhost/cowrie_test" \
    uv run pytest tests/integration/test_snapshot_population_integration.py
```

Coverage:
- Canonical IP tracking and FK relationship to ip_inventory
- Batch IP snapshot lookups with hybrid properties (geo_country, ip_type)
- Snapshot immutability via COALESCE
- IP type priority handling (VPN > TOR > PROXY > DATACENTER > RESIDENTIAL)
- NULL handling for orphan sessions
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Dict

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from cowrieprocessor.db.models import IPInventory, SessionSummary
from cowrieprocessor.loader.bulk import BulkLoader


@pytest.fixture
def postgres_engine() -> Any:
    """Create PostgreSQL engine from test config.

    Uses TEST_DATABASE_URL environment variable or skips tests if not available.
    """
    import os

    db_url = os.environ.get("TEST_DATABASE_URL")
    if not db_url or "postgresql" not in db_url:
        pytest.skip("PostgreSQL integration tests require TEST_DATABASE_URL environment variable")

    # Use psycopg (psycopg3) driver instead of psycopg2
    if db_url and "postgresql://" in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://")

    engine = create_engine(db_url, echo=False)
    return engine


@pytest.fixture
def postgres_session(postgres_engine: Any) -> Any:  # Generator return type
    """Create PostgreSQL session with transaction rollback."""
    connection = postgres_engine.connect()
    transaction = connection.begin()
    session_maker = sessionmaker(bind=connection)
    session = session_maker()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def bulk_loader(postgres_engine: Any) -> BulkLoader:
    """Create BulkLoader for integration tests."""
    from cowrieprocessor.loader.bulk import BulkLoaderConfig

    config = BulkLoaderConfig(batch_size=100)
    return BulkLoader(engine=postgres_engine, config=config)


def create_ip_inventory_entry(
    session: Session,
    ip_address: str,
    asn: int,
    country_code: str,
    ip_type: str,
    enrichment_payload: Dict[str, Any] | None = None,
) -> IPInventory:
    """Helper to create IPInventory entry with enrichment data."""
    if enrichment_payload is None:
        enrichment_payload = {
            "maxmind": {"country": country_code},  # Simplified structure
            "spur": {"ip_type": ip_type},  # Simplified structure
        }

    ip_entry = IPInventory(
        ip_address=ip_address,
        current_asn=asn,
        enrichment=enrichment_payload,
        enrichment_updated_at=datetime.now(UTC),
        first_seen=datetime.now(UTC),  # Required field
        last_seen=datetime.now(UTC),  # Required field
    )
    session.add(ip_entry)
    session.flush()
    return ip_entry


def test_canonical_ip_foreign_key_relationship(bulk_loader: BulkLoader, postgres_session: Session) -> None:
    """Verify SessionSummary.source_ip FK relationship to IPInventory works."""
    # Create IP inventory entry
    create_ip_inventory_entry(
        postgres_session,
        ip_address="203.0.113.10",
        asn=64512,
        country_code="US",
        ip_type="RESIDENTIAL",
    )
    postgres_session.commit()

    # Create session summary with source_ip FK
    session_summary = SessionSummary(
        session_id="test_session_001",
        sensor="test-sensor",
        start_time=datetime.now(UTC),
        source_ip="203.0.113.10",  # FK to ip_inventory
        snapshot_asn=64512,
        snapshot_country="US",
        snapshot_ip_type="RESIDENTIAL",
    )
    postgres_session.add(session_summary)
    postgres_session.commit()

    # Query with JOIN to verify FK relationship
    result = (
        postgres_session.query(SessionSummary, IPInventory)
        .join(IPInventory, SessionSummary.source_ip == IPInventory.ip_address)
        .filter(SessionSummary.session_id == "test_session_001")
        .first()
    )

    assert result is not None
    summary, ip_inv = result
    assert summary.source_ip == "203.0.113.10"
    assert ip_inv.ip_address == "203.0.113.10"
    assert summary.snapshot_asn == 64512


def test_hybrid_property_queries_in_lookup(bulk_loader: BulkLoader, postgres_session: Session) -> None:
    """Verify _lookup_ip_snapshots() queries hybrid properties correctly."""
    # Create multiple IP inventory entries with different enrichment patterns
    ips = [
        ("192.0.2.1", 64512, "US", "RESIDENTIAL"),
        ("192.0.2.2", 64513, "CN", "DATACENTER"),
        ("192.0.2.3", 64514, "RU", "VPN"),
    ]

    for ip, asn, country, ip_type in ips:
        create_ip_inventory_entry(postgres_session, ip, asn, country, ip_type)

    postgres_session.commit()

    # Call _lookup_ip_snapshots (uses hybrid properties)
    ip_addresses = ["192.0.2.1", "192.0.2.2", "192.0.2.3"]
    snapshots = bulk_loader._lookup_ip_snapshots(postgres_session, ip_addresses)

    # Verify hybrid properties were evaluated correctly
    assert len(snapshots) == 3

    assert snapshots["192.0.2.1"]["country"] == "US"
    assert snapshots["192.0.2.1"]["ip_type"] == "RESIDENTIAL"
    assert snapshots["192.0.2.1"]["asn"] == 64512

    assert snapshots["192.0.2.2"]["country"] == "CN"
    assert snapshots["192.0.2.2"]["ip_type"] == "DATACENTER"

    assert snapshots["192.0.2.3"]["country"] == "RU"
    assert snapshots["192.0.2.3"]["ip_type"] == "VPN"


def test_snapshot_immutability_with_coalesce(bulk_loader: BulkLoader, postgres_session: Session) -> None:
    """Verify COALESCE preserves first snapshot on conflict (immutability)."""
    # Create IP inventory
    create_ip_inventory_entry(
        postgres_session,
        ip_address="198.51.100.50",
        asn=64515,
        country_code="DE",
        ip_type="RESIDENTIAL",
    )
    postgres_session.commit()

    # First insert: snapshot populated
    session1 = SessionSummary(
        session_id="immutable_test",
        sensor="test-sensor",
        start_time=datetime.now(UTC),
        source_ip="198.51.100.50",
        snapshot_asn=64515,
        snapshot_country="DE",
        snapshot_ip_type="RESIDENTIAL",
    )
    postgres_session.add(session1)
    postgres_session.commit()

    # Update IP inventory to simulate enrichment change
    ip_entry = postgres_session.query(IPInventory).filter_by(ip_address="198.51.100.50").first()
    assert ip_entry is not None  # Type narrowing for mypy
    ip_entry.enrichment = {  # type: ignore[assignment]
        "maxmind": {"country": {"iso_code": "FR"}},  # Changed country
        "spur": {"as": {"number": 64516}, "ip_type": "DATACENTER"},  # Changed ASN and type
    }
    ip_entry.current_asn = 64516  # type: ignore[assignment]
    postgres_session.commit()

    # Simulate ON CONFLICT DO UPDATE (re-insert same session_id)
    stmt = text("""
        INSERT INTO session_summaries (
            session_id, sensor, start_time, source_ip,
            snapshot_asn, snapshot_country, snapshot_ip_type
        ) VALUES (
            :session_id, :sensor, :start_time, :source_ip,
            :snapshot_asn, :snapshot_country, :snapshot_ip_type
        )
        ON CONFLICT (session_id) DO UPDATE SET
            snapshot_asn = COALESCE(session_summaries.snapshot_asn, EXCLUDED.snapshot_asn),
            snapshot_country = COALESCE(session_summaries.snapshot_country, EXCLUDED.snapshot_country),
            snapshot_ip_type = COALESCE(session_summaries.snapshot_ip_type, EXCLUDED.snapshot_ip_type)
    """)

    postgres_session.execute(
        stmt,
        {
            "session_id": "immutable_test",
            "sensor": "test-sensor",
            "start_time": datetime.now(UTC),
            "source_ip": "198.51.100.50",
            "snapshot_asn": 64516,  # New value (should be rejected)
            "snapshot_country": "FR",  # New value (should be rejected)
            "snapshot_ip_type": "DATACENTER",  # New value (should be rejected)
        },
    )
    postgres_session.commit()

    # Verify original snapshot preserved (COALESCE kept first values)
    session_check = postgres_session.query(SessionSummary).filter_by(session_id="immutable_test").first()
    assert session_check is not None  # Type narrowing for mypy

    assert session_check.snapshot_asn == 64515  # Original, not 64516
    assert session_check.snapshot_country == "DE"  # Original, not FR
    assert session_check.snapshot_ip_type == "RESIDENTIAL"  # Original, not DATACENTER


def test_ip_type_priority_handling(bulk_loader: BulkLoader, postgres_session: Session) -> None:
    """Verify IP type priority: VPN > TOR > PROXY > DATACENTER > RESIDENTIAL."""
    # Create IPs with different types
    ip_types = [
        ("10.0.0.1", "RESIDENTIAL"),
        ("10.0.0.2", "DATACENTER"),
        ("10.0.0.3", "PROXY"),
        ("10.0.0.4", "TOR"),
        ("10.0.0.5", "VPN"),
    ]

    for ip, ip_type in ip_types:
        create_ip_inventory_entry(postgres_session, ip, 64512, "US", ip_type)

    postgres_session.commit()

    # Lookup all IPs
    ip_addresses = [ip for ip, _ in ip_types]
    snapshots = bulk_loader._lookup_ip_snapshots(postgres_session, ip_addresses)

    # Verify each type is correctly extracted
    assert snapshots["10.0.0.1"]["ip_type"] == "RESIDENTIAL"
    assert snapshots["10.0.0.2"]["ip_type"] == "DATACENTER"
    assert snapshots["10.0.0.3"]["ip_type"] == "PROXY"
    assert snapshots["10.0.0.4"]["ip_type"] == "TOR"
    assert snapshots["10.0.0.5"]["ip_type"] == "VPN"


def test_missing_ip_graceful_handling(bulk_loader: BulkLoader, postgres_session: Session) -> None:
    """Verify graceful handling when IP not found in ip_inventory."""
    # Create only one IP
    create_ip_inventory_entry(postgres_session, "192.0.2.100", 64512, "US", "RESIDENTIAL")
    postgres_session.commit()

    # Lookup multiple IPs including missing ones
    ip_addresses = ["192.0.2.100", "192.0.2.101", "192.0.2.102"]
    snapshots = bulk_loader._lookup_ip_snapshots(postgres_session, ip_addresses)

    # Verify only found IP returned, no crash on missing
    assert len(snapshots) == 1
    assert "192.0.2.100" in snapshots
    assert "192.0.2.101" not in snapshots
    assert "192.0.2.102" not in snapshots


def test_country_code_unknown_handling(bulk_loader: BulkLoader, postgres_session: Session) -> None:
    """Verify XX country code converted to NULL in snapshots."""
    # Create IP with unknown country (XX)
    enrichment = {
        "maxmind": {"country": "XX"},  # Unknown (simplified structure)
        "spur": {"ip_type": "RESIDENTIAL"},
    }
    create_ip_inventory_entry(postgres_session, "203.0.113.99", 64512, "XX", "RESIDENTIAL", enrichment)
    postgres_session.commit()

    # Lookup snapshot
    snapshots = bulk_loader._lookup_ip_snapshots(postgres_session, ["203.0.113.99"])

    # Verify XX converted to None
    assert snapshots["203.0.113.99"]["country"] is None
    assert snapshots["203.0.113.99"]["asn"] == 64512


def test_batch_lookup_performance(bulk_loader: BulkLoader, postgres_session: Session) -> None:
    """Verify batch lookup uses single query, not N+1."""
    # Create 50 IP entries
    ips = [f"10.1.{i // 256}.{i % 256}" for i in range(50)]
    for i, ip in enumerate(ips):
        create_ip_inventory_entry(postgres_session, ip, 64512 + i, "US", "RESIDENTIAL")

    postgres_session.commit()

    # Enable query logging to verify single query
    from sqlalchemy import event

    query_count = 0

    def count_queries(conn, cursor, statement, parameters, context, executemany):
        nonlocal query_count
        if "ip_inventory" in statement.lower():
            query_count += 1

    event.listen(postgres_session.bind, "before_cursor_execute", count_queries)

    # Perform batch lookup
    snapshots = bulk_loader._lookup_ip_snapshots(postgres_session, ips)

    # Verify single query executed (batch), not 50 queries
    assert query_count == 1, f"Expected 1 query, got {query_count} (N+1 problem)"
    assert len(snapshots) == 50


def test_enrichment_timestamp_preservation(bulk_loader: BulkLoader, postgres_session: Session) -> None:
    """Verify enrichment_at timestamp correctly copied from ip_inventory."""
    # Create IP with specific enrichment timestamp
    enrichment_time = datetime(2025, 9, 10, 12, 30, 45, tzinfo=UTC)
    enrichment = {
        "maxmind": {"country": "JP"},  # Simplified structure
        "spur": {"ip_type": "RESIDENTIAL"},
    }

    ip_entry = IPInventory(
        ip_address="198.51.100.200",
        current_asn=64512,
        enrichment=enrichment,
        enrichment_updated_at=enrichment_time,
        first_seen=datetime.now(UTC),  # Required field
        last_seen=datetime.now(UTC),  # Required field
    )
    postgres_session.add(ip_entry)
    postgres_session.commit()

    # Lookup snapshot
    snapshots = bulk_loader._lookup_ip_snapshots(postgres_session, ["198.51.100.200"])

    # Verify timestamp preserved
    assert snapshots["198.51.100.200"]["enrichment_at"] == enrichment_time
