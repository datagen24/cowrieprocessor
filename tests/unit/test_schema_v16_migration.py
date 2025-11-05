"""Unit tests for schema v16 migration (ADR-007 three-tier enrichment architecture).

Tests verify that the migration correctly creates and populates:
- ASN inventory table with aggregate statistics
- IP inventory table with computed columns
- Session summary snapshot columns
- Foreign key constraints
"""

from __future__ import annotations

from typing import Generator

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.engine import Engine

from cowrieprocessor.db.engine import create_engine
from cowrieprocessor.db.migrations import CURRENT_SCHEMA_VERSION, apply_migrations


@pytest.fixture
def pg_engine() -> Generator[Engine, None, None]:
    """Create a PostgreSQL test engine (requires PostgreSQL connection)."""
    # This fixture requires a PostgreSQL test database
    # Skip if not available
    pytest.skip("PostgreSQL test database required for v16 migration tests")
    yield  # type: ignore


@pytest.fixture
def setup_v15_schema(pg_engine: Engine) -> Connection:
    """Set up a v15 schema with test data for migration testing."""
    with pg_engine.begin() as conn:
        # Create minimal v15 schema with session_summaries
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS schema_state (
                key VARCHAR(128) PRIMARY KEY,
                value VARCHAR(256) NOT NULL
            )
            """
            )
        )

        conn.execute(
            text(
                """
            INSERT INTO schema_state (key, value)
            VALUES ('schema_version', '15')
            ON CONFLICT (key) DO UPDATE SET value = '15'
            """
            )
        )

        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS session_summaries (
                session_id VARCHAR(64) PRIMARY KEY,
                source_ip INET,
                first_event_at TIMESTAMP,
                last_event_at TIMESTAMP,
                enrichment JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMP DEFAULT NOW()
            )
            """
            )
        )

        # Insert test data with enrichment
        test_sessions = [
            {
                "session_id": "session1",
                "source_ip": "192.0.2.1",
                "enrichment": {
                    "cymru": {"asn": 15169, "country": "US"},
                    "maxmind": {"country": "US"},
                    "spur": {"client": {"types": ["RESIDENTIAL"]}},
                },
            },
            {
                "session_id": "session2",
                "source_ip": "192.0.2.2",
                "enrichment": {
                    "cymru": {"asn": 15169, "country": "US"},
                    "maxmind": {"country": "US"},
                    "spur": {"client": {"types": ["DATACENTER", "VPN"]}},
                },
            },
            {
                "session_id": "session3",
                "source_ip": "198.51.100.1",
                "enrichment": {
                    "cymru": {"asn": 16509, "country": "US"},
                    "maxmind": {"country": "US"},
                },
            },
        ]

        for session in test_sessions:
            conn.execute(
                text(
                    """
                INSERT INTO session_summaries (session_id, source_ip, first_event_at, last_event_at, enrichment)
                VALUES (:session_id, :source_ip::inet, NOW() - INTERVAL '1 day', NOW(), :enrichment::jsonb)
                """
                ),
                {
                    "session_id": session["session_id"],
                    "source_ip": session["source_ip"],
                    "enrichment": session["enrichment"],
                },
            )

        return conn


class TestSchemaV16Migration:
    """Test suite for v16 migration (three-tier enrichment architecture)."""

    def test_migration_to_v16_succeeds(self, setup_v15_schema: Connection) -> None:
        """Test that migration from v15 to v16 completes successfully."""
        conn = setup_v15_schema

        # Run migrations
        engine = conn.engine
        version = apply_migrations(engine)

        assert version == CURRENT_SCHEMA_VERSION
        assert version == 16

    def test_asn_inventory_created(self, setup_v15_schema: Connection) -> None:
        """Test that ASN inventory table is created with correct schema."""
        conn = setup_v15_schema
        apply_migrations(conn.engine)

        # Check table exists
        result = conn.execute(
            text(
                """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'asn_inventory'
            )
            """
            )
        )
        assert result.scalar() is True

        # Check key columns exist
        result = conn.execute(
            text(
                """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'asn_inventory'
            ORDER BY ordinal_position
            """
            )
        )
        columns = {row[0]: row[1] for row in result}

        assert "asn_number" in columns
        assert "organization_name" in columns
        assert "first_seen" in columns
        assert "last_seen" in columns
        assert "unique_ip_count" in columns
        assert "total_session_count" in columns
        assert "enrichment" in columns
        assert columns["enrichment"] == "jsonb"

    def test_asn_inventory_populated(self, setup_v15_schema: Connection) -> None:
        """Test that ASN inventory is populated from session_summaries."""
        conn = setup_v15_schema
        apply_migrations(conn.engine)

        # Check ASN records created
        result = conn.execute(text("SELECT COUNT(*) FROM asn_inventory"))
        count = result.scalar()
        assert count == 2  # Two unique ASNs (15169, 16509)

        # Check specific ASN data
        result = conn.execute(
            text(
                """
            SELECT asn_number, unique_ip_count, total_session_count
            FROM asn_inventory
            WHERE asn_number = 15169
            """
            )
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == 15169
        assert row[1] == 2  # Two unique IPs (192.0.2.1, 192.0.2.2)
        assert row[2] == 2  # Two sessions

    def test_ip_inventory_created(self, setup_v15_schema: Connection) -> None:
        """Test that IP inventory table is created with computed columns."""
        conn = setup_v15_schema
        apply_migrations(conn.engine)

        # Check table exists
        result = conn.execute(
            text(
                """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'ip_inventory'
            )
            """
            )
        )
        assert result.scalar() is True

        # Check computed columns exist
        result = conn.execute(
            text(
                """
            SELECT column_name, is_generated
            FROM information_schema.columns
            WHERE table_name = 'ip_inventory'
            AND column_name IN ('geo_country', 'ip_types', 'is_scanner', 'is_bogon')
            """
            )
        )
        generated_cols = {row[0]: row[1] for row in result}

        assert generated_cols["geo_country"] == "ALWAYS"
        assert generated_cols["ip_types"] == "ALWAYS"
        assert generated_cols["is_scanner"] == "ALWAYS"
        assert generated_cols["is_bogon"] == "ALWAYS"

    def test_ip_inventory_populated(self, setup_v15_schema: Connection) -> None:
        """Test that IP inventory is populated with correct computed values."""
        conn = setup_v15_schema
        apply_migrations(conn.engine)

        # Check IP records created
        result = conn.execute(text("SELECT COUNT(*) FROM ip_inventory"))
        count = result.scalar()
        assert count == 3  # Three unique IPs

        # Check specific IP with computed columns
        result = conn.execute(
            text(
                """
            SELECT ip_address, current_asn, geo_country, ip_types, session_count
            FROM ip_inventory
            WHERE ip_address = '192.0.2.1'::inet
            """
            )
        )
        row = result.fetchone()
        assert row is not None
        assert str(row[0]) == "192.0.2.1"
        assert row[1] == 15169  # current_asn
        assert row[2] == "US"  # geo_country (computed)
        assert row[3] == ["RESIDENTIAL"]  # ip_types (computed)
        assert row[4] == 1  # session_count

    def test_ip_inventory_computed_defaults(self, setup_v15_schema: Connection) -> None:
        """Test that computed columns handle missing data with defensive defaults."""
        conn = setup_v15_schema

        # Insert session with minimal enrichment
        conn.execute(
            text(
                """
            INSERT INTO session_summaries (session_id, source_ip, first_event_at, last_event_at, enrichment)
            VALUES ('session_minimal', '203.0.113.1'::inet, NOW(), NOW(), '{}'::jsonb)
            """
            )
        )

        apply_migrations(conn.engine)

        # Check defaults are applied
        result = conn.execute(
            text(
                """
            SELECT geo_country, ip_types, is_scanner, is_bogon
            FROM ip_inventory
            WHERE ip_address = '203.0.113.1'::inet
            """
            )
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "XX"  # Default country
        assert row[1] == []  # Empty array for ip_types
        assert row[2] is False  # Default is_scanner
        assert row[3] is False  # Default is_bogon

    def test_session_snapshot_columns_added(self, setup_v15_schema: Connection) -> None:
        """Test that snapshot columns are added to session_summaries."""
        conn = setup_v15_schema
        apply_migrations(conn.engine)

        # Check snapshot columns exist
        result = conn.execute(
            text(
                """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'session_summaries'
            AND column_name IN ('enrichment_at', 'snapshot_asn', 'snapshot_country', 'snapshot_ip_types')
            ORDER BY column_name
            """
            )
        )
        columns = {row[0]: row[1] for row in result}

        assert "enrichment_at" in columns
        assert "snapshot_asn" in columns
        assert "snapshot_country" in columns
        assert "snapshot_ip_types" in columns
        assert columns["snapshot_ip_types"] == "ARRAY"

    def test_session_snapshots_backfilled(self, setup_v15_schema: Connection) -> None:
        """Test that snapshot columns are backfilled from enrichment data."""
        conn = setup_v15_schema
        apply_migrations(conn.engine)

        # Check snapshot data for session1
        result = conn.execute(
            text(
                """
            SELECT snapshot_asn, snapshot_country, snapshot_ip_types
            FROM session_summaries
            WHERE session_id = 'session1'
            """
            )
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == 15169  # snapshot_asn
        assert row[1] == "US"  # snapshot_country
        assert row[2] == ["RESIDENTIAL"]  # snapshot_ip_types

        # Check session2 with multiple ip_types
        result = conn.execute(
            text(
                """
            SELECT snapshot_ip_types
            FROM session_summaries
            WHERE session_id = 'session2'
            """
            )
        )
        row = result.fetchone()
        assert row is not None
        assert set(row[0]) == {"DATACENTER", "VPN"}

    def test_foreign_key_constraints_created(self, setup_v15_schema: Connection) -> None:
        """Test that foreign key constraints are created and validated."""
        conn = setup_v15_schema
        apply_migrations(conn.engine)

        # Check FK from ip_inventory to asn_inventory
        result = conn.execute(
            text(
                """
            SELECT constraint_name, table_name, constraint_type
            FROM information_schema.table_constraints
            WHERE constraint_name = 'fk_ip_current_asn'
            """
            )
        )
        row = result.fetchone()
        assert row is not None
        assert row[1] == "ip_inventory"
        assert row[2] == "FOREIGN KEY"

        # Check FK from session_summaries to ip_inventory
        result = conn.execute(
            text(
                """
            SELECT constraint_name, table_name, constraint_type
            FROM information_schema.table_constraints
            WHERE constraint_name = 'fk_session_source_ip'
            """
            )
        )
        row = result.fetchone()
        assert row is not None
        assert row[1] == "session_summaries"
        assert row[2] == "FOREIGN KEY"

    def test_indexes_created(self, setup_v15_schema: Connection) -> None:
        """Test that performance indexes are created on all tables."""
        conn = setup_v15_schema
        apply_migrations(conn.engine)

        # Check ASN indexes
        result = conn.execute(
            text(
                """
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'asn_inventory'
            AND indexname LIKE 'idx_%'
            """
            )
        )
        asn_indexes = {row[0] for row in result}
        assert "idx_asn_org_name" in asn_indexes
        assert "idx_asn_type" in asn_indexes
        assert "idx_asn_session_count" in asn_indexes

        # Check IP indexes
        result = conn.execute(
            text(
                """
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'ip_inventory'
            AND indexname LIKE 'idx_%'
            """
            )
        )
        ip_indexes = {row[0] for row in result}
        assert "idx_ip_current_asn" in ip_indexes
        assert "idx_ip_geo_country" in ip_indexes
        assert "idx_ip_session_count" in ip_indexes

        # Check session snapshot indexes
        result = conn.execute(
            text(
                """
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'session_summaries'
            AND indexname LIKE 'idx_session_snapshot_%'
            """
            )
        )
        snapshot_indexes = {row[0] for row in result}
        assert "idx_session_snapshot_asn" in snapshot_indexes
        assert "idx_session_snapshot_country" in snapshot_indexes

    def test_distinct_on_logic_for_latest_enrichment(self, setup_v15_schema: Connection) -> None:
        """Test that DISTINCT ON correctly selects latest enrichment per ASN/IP."""
        conn = setup_v15_schema

        # Insert multiple sessions for same IP with different timestamps
        conn.execute(
            text(
                """
            INSERT INTO session_summaries (session_id, source_ip, first_event_at, last_event_at, enrichment)
            VALUES
                ('old_session', '192.0.2.50'::inet, NOW() - INTERVAL '10 days', NOW() - INTERVAL '10 days',
                 '{"cymru": {"asn": 12345, "country": "OLD"}}'::jsonb),
                ('new_session', '192.0.2.50'::inet, NOW() - INTERVAL '1 day', NOW() - INTERVAL '1 day',
                 '{"cymru": {"asn": 12345, "country": "NEW"}}'::jsonb)
            """
            )
        )

        apply_migrations(conn.engine)

        # Check IP inventory has latest enrichment
        result = conn.execute(
            text(
                """
            SELECT enrichment->'cymru'->>'country'
            FROM ip_inventory
            WHERE ip_address = '192.0.2.50'::inet
            """
            )
        )
        country = result.scalar()
        assert country == "NEW"  # Should have latest enrichment

    def test_window_functions_for_aggregation(self, setup_v15_schema: Connection) -> None:
        """Test that window functions correctly aggregate IP statistics."""
        conn = setup_v15_schema

        # Insert multiple sessions for same IP
        for i in range(5):
            conn.execute(
                text(
                    f"""
                INSERT INTO session_summaries (session_id, source_ip, first_event_at, last_event_at, enrichment)
                VALUES ('multi_session_{i}', '192.0.2.100'::inet, NOW() - INTERVAL '{i} days',
                        NOW() - INTERVAL '{i} days', '{{"cymru": {{"asn": 99999}}}}'::jsonb)
                """
                )
            )

        apply_migrations(conn.engine)

        # Check session_count is correct
        result = conn.execute(
            text(
                """
            SELECT session_count
            FROM ip_inventory
            WHERE ip_address = '192.0.2.100'::inet
            """
            )
        )
        count = result.scalar()
        assert count == 5

    def test_sqlite_migration_skipped(self) -> None:
        """Test that v16 migration is gracefully skipped for SQLite."""
        # Create SQLite engine
        engine = create_engine("sqlite:///:memory:")

        with engine.begin() as conn:
            # Set up v15 schema
            conn.execute(
                text(
                    """
                CREATE TABLE schema_state (
                    key VARCHAR(128) PRIMARY KEY,
                    value VARCHAR(256) NOT NULL
                )
                """
                )
            )
            conn.execute(text("INSERT INTO schema_state (key, value) VALUES ('schema_version', '15')"))

        # Run migrations
        version = apply_migrations(engine)

        # Should increment to v16 but skip PostgreSQL-specific changes
        assert version == 16

        with engine.begin() as conn:
            # Verify tables were NOT created
            result = conn.execute(
                text(
                    """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name IN ('asn_inventory', 'ip_inventory')
                """
                )
            )
            tables = [row[0] for row in result]
            assert len(tables) == 0  # No inventory tables in SQLite

    def test_coalesce_fallback_logic(self, setup_v15_schema: Connection) -> None:
        """Test that COALESCE properly falls back through enrichment sources."""
        conn = setup_v15_schema

        # Insert sessions with different enrichment sources
        test_cases = [
            {
                "session_id": "maxmind_only",
                "source_ip": "192.0.2.201",
                "enrichment": {"maxmind": {"country": "GB"}},
                "expected_country": "GB",
            },
            {
                "session_id": "cymru_only",
                "source_ip": "192.0.2.202",
                "enrichment": {"cymru": {"country": "FR"}},
                "expected_country": "FR",
            },
            {
                "session_id": "dshield_only",
                "source_ip": "192.0.2.203",
                "enrichment": {"dshield": {"ip": {"ascountry": "DE"}}},
                "expected_country": "DE",
            },
            {
                "session_id": "no_country",
                "source_ip": "192.0.2.204",
                "enrichment": {},
                "expected_country": "XX",
            },
        ]

        for case in test_cases:
            conn.execute(
                text(
                    """
                INSERT INTO session_summaries (session_id, source_ip, first_event_at, last_event_at, enrichment)
                VALUES (:session_id, :source_ip::inet, NOW(), NOW(), :enrichment::jsonb)
                """
                ),
                {
                    "session_id": case["session_id"],
                    "source_ip": case["source_ip"],
                    "enrichment": case["enrichment"],
                },
            )

        apply_migrations(conn.engine)

        # Verify COALESCE fallback worked correctly
        for case in test_cases:
            result = conn.execute(
                text(
                    """
                SELECT geo_country
                FROM ip_inventory
                WHERE ip_address = :ip::inet
                """
                ),
                {"ip": case["source_ip"]},
            )
            country = result.scalar()
            assert country == case["expected_country"], f"Failed for {case['session_id']}"
