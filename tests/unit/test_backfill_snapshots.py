"""Unit tests for backfill_session_snapshots.py migration script."""

from __future__ import annotations

import json

# Import functions from the migration script
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from cowrieprocessor.db import Base, create_session_maker
from cowrieprocessor.db.models import IPInventory

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts" / "migrations"))
from backfill_session_snapshots import (
    CheckpointState,
    extract_canonical_ip,
    lookup_ip_snapshots_batch,
)


class TestExtractCanonicalIP:
    """Tests for extract_canonical_ip helper function."""

    def test_extract_from_valid_enrichment(self) -> None:
        """Test extraction from properly formatted enrichment JSON."""
        enrichment = {"session_metadata": {"source_ip": "192.0.2.1"}}
        result = extract_canonical_ip(enrichment)
        assert result == "192.0.2.1"

    def test_extract_ipv6_address(self) -> None:
        """Test extraction of IPv6 addresses."""
        enrichment = {"session_metadata": {"source_ip": "2001:db8::1"}}
        result = extract_canonical_ip(enrichment)
        assert result == "2001:db8::1"

    def test_missing_enrichment(self) -> None:
        """Test behavior when enrichment is None."""
        result = extract_canonical_ip(None)
        assert result is None

    def test_empty_enrichment(self) -> None:
        """Test behavior when enrichment is empty dict."""
        enrichment: Dict[str, Any] = {}
        result = extract_canonical_ip(enrichment)
        assert result is None

    def test_missing_session_metadata(self) -> None:
        """Test behavior when session_metadata key is missing."""
        enrichment = {"other_data": {}}
        result = extract_canonical_ip(enrichment)
        assert result is None

    def test_missing_source_ip(self) -> None:
        """Test behavior when source_ip key is missing."""
        enrichment = {"session_metadata": {}}
        result = extract_canonical_ip(enrichment)
        assert result is None

    def test_null_source_ip(self) -> None:
        """Test behavior when source_ip is null."""
        enrichment = {"session_metadata": {"source_ip": None}}
        result = extract_canonical_ip(enrichment)
        assert result is None

    def test_non_string_source_ip(self) -> None:
        """Test behavior when source_ip is not a string."""
        enrichment = {"session_metadata": {"source_ip": 192}}
        result = extract_canonical_ip(enrichment)
        assert result is None

    def test_non_dict_session_metadata(self) -> None:
        """Test behavior when session_metadata is not a dict."""
        enrichment = {"session_metadata": "not_a_dict"}
        result = extract_canonical_ip(enrichment)
        assert result is None


class TestLookupIPSnapshotsBatch:
    """Tests for lookup_ip_snapshots_batch helper function."""

    @pytest.fixture
    def db_session(self) -> Session:
        """Create in-memory SQLite database session for testing."""
        engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(engine)
        session_maker = create_session_maker(engine)
        session = session_maker()
        yield session
        session.close()

    def test_empty_ip_list(self, db_session: Session) -> None:
        """Test behavior with empty IP list."""
        result = lookup_ip_snapshots_batch(db_session, [])
        assert result == {}

    def test_single_ip_lookup(self, db_session: Session) -> None:
        """Test lookup of single IP with enrichment data."""
        # Insert test IP inventory
        ip_inv = IPInventory(
            ip_address="192.0.2.1",
            first_seen=datetime.now(UTC),
            last_seen=datetime.now(UTC),
            session_count=1,
            enrichment={
                "cymru": {"asn": 15169, "country": "US"},
                "maxmind": {"country": "US"},
                "spur": {"client": {"types": "RESIDENTIAL"}},
            },
            current_asn=15169,
            enrichment_updated_at=datetime.now(UTC),
        )
        db_session.add(ip_inv)
        db_session.commit()

        # Lookup snapshot
        result = lookup_ip_snapshots_batch(db_session, ["192.0.2.1"])

        assert "192.0.2.1" in result
        snapshot = result["192.0.2.1"]
        assert snapshot["asn"] == 15169
        assert snapshot["country"] == "US"
        assert snapshot["ip_type"] == "RESIDENTIAL"
        assert snapshot["enrichment_at"] is not None

    def test_multiple_ip_lookup(self, db_session: Session) -> None:
        """Test batch lookup of multiple IPs."""
        # Insert test IPs
        ips_data = [
            ("192.0.2.1", 15169, "US", "RESIDENTIAL"),
            ("192.0.2.2", 16509, "US", "DATACENTER"),
            ("192.0.2.3", 13335, "US", "PROXY"),
        ]

        for ip, asn, country, ip_type in ips_data:
            ip_inv = IPInventory(
                ip_address=ip,
                first_seen=datetime.now(UTC),
                last_seen=datetime.now(UTC),
                session_count=1,
                enrichment={
                    "cymru": {"asn": asn, "country": country},
                    "spur": {"client": {"types": ip_type}},
                },
                current_asn=asn,
                enrichment_updated_at=datetime.now(UTC),
            )
            db_session.add(ip_inv)
        db_session.commit()

        # Batch lookup
        result = lookup_ip_snapshots_batch(db_session, ["192.0.2.1", "192.0.2.2", "192.0.2.3"])

        assert len(result) == 3
        assert result["192.0.2.1"]["asn"] == 15169
        assert result["192.0.2.2"]["asn"] == 16509
        assert result["192.0.2.3"]["asn"] == 13335

    def test_missing_ip(self, db_session: Session) -> None:
        """Test lookup of IP not in inventory."""
        result = lookup_ip_snapshots_batch(db_session, ["192.0.2.99"])
        assert result == {}

    def test_partial_enrichment(self, db_session: Session) -> None:
        """Test IP with partial enrichment (missing ASN)."""
        ip_inv = IPInventory(
            ip_address="192.0.2.1",
            first_seen=datetime.now(UTC),
            last_seen=datetime.now(UTC),
            session_count=1,
            enrichment={"maxmind": {"country": "US"}},  # No Cymru ASN data
            current_asn=None,
            enrichment_updated_at=datetime.now(UTC),
        )
        db_session.add(ip_inv)
        db_session.commit()

        result = lookup_ip_snapshots_batch(db_session, ["192.0.2.1"])

        assert "192.0.2.1" in result
        snapshot = result["192.0.2.1"]
        assert snapshot["asn"] is None  # Cymru failed
        assert snapshot["country"] == "US"  # MaxMind succeeded

    def test_unknown_country_code(self, db_session: Session) -> None:
        """Test IP with XX country code (unknown) is converted to None."""
        ip_inv = IPInventory(
            ip_address="192.0.2.1",
            first_seen=datetime.now(UTC),
            last_seen=datetime.now(UTC),
            session_count=1,
            enrichment={"cymru": {"asn": 15169, "country": "XX"}},  # Unknown country
            current_asn=15169,
            enrichment_updated_at=datetime.now(UTC),
        )
        db_session.add(ip_inv)
        db_session.commit()

        result = lookup_ip_snapshots_batch(db_session, ["192.0.2.1"])

        assert result["192.0.2.1"]["country"] is None

    def test_ip_type_priority(self, db_session: Session) -> None:
        """Test IP type prioritization when multiple types present."""
        # VPN should win over RESIDENTIAL
        ip_inv = IPInventory(
            ip_address="192.0.2.1",
            first_seen=datetime.now(UTC),
            last_seen=datetime.now(UTC),
            session_count=1,
            enrichment={"spur": {"client": {"types": ["RESIDENTIAL", "VPN", "PROXY"]}}},
            enrichment_updated_at=datetime.now(UTC),
        )
        db_session.add(ip_inv)
        db_session.commit()

        result = lookup_ip_snapshots_batch(db_session, ["192.0.2.1"])

        # VPN has priority 1, should win
        assert result["192.0.2.1"]["ip_type"] == "VPN"


class TestCheckpointState:
    """Tests for CheckpointState class."""

    @pytest.fixture
    def temp_checkpoint(self, tmp_path: Path) -> Path:
        """Create temporary checkpoint file path."""
        return tmp_path / "checkpoint.json"

    def test_initial_state(self, temp_checkpoint: Path) -> None:
        """Test initial checkpoint state."""
        checkpoint = CheckpointState(temp_checkpoint)
        assert checkpoint.last_batch == 0
        assert checkpoint.total_updated == 0
        assert checkpoint.last_session_id is None
        assert checkpoint.started_at is None

    def test_save_and_load(self, temp_checkpoint: Path) -> None:
        """Test saving and loading checkpoint state."""
        checkpoint = CheckpointState(temp_checkpoint)
        checkpoint.save(batch_num=10, total_updated=5000, last_session_id="abc123")

        # Load in new instance
        checkpoint2 = CheckpointState(temp_checkpoint)
        checkpoint2.load()

        assert checkpoint2.last_batch == 10
        assert checkpoint2.total_updated == 5000
        assert checkpoint2.last_session_id == "abc123"
        assert checkpoint2.started_at is not None
        assert checkpoint2.last_saved_at is not None

    def test_load_nonexistent_file(self, temp_checkpoint: Path) -> None:
        """Test loading checkpoint when file doesn't exist."""
        checkpoint = CheckpointState(temp_checkpoint)
        checkpoint.load()  # Should not raise

        assert checkpoint.last_batch == 0
        assert checkpoint.total_updated == 0

    def test_load_corrupted_json(self, temp_checkpoint: Path) -> None:
        """Test loading checkpoint with corrupted JSON."""
        temp_checkpoint.write_text("not valid json{[")

        checkpoint = CheckpointState(temp_checkpoint)
        checkpoint.load()  # Should not raise, should log warning

        assert checkpoint.last_batch == 0
        assert checkpoint.total_updated == 0

    def test_incremental_saves(self, temp_checkpoint: Path) -> None:
        """Test multiple incremental saves."""
        checkpoint = CheckpointState(temp_checkpoint)

        checkpoint.save(batch_num=1, total_updated=1000)
        checkpoint.save(batch_num=2, total_updated=2000)
        checkpoint.save(batch_num=3, total_updated=3000, last_session_id="xyz789")

        checkpoint2 = CheckpointState(temp_checkpoint)
        checkpoint2.load()

        assert checkpoint2.last_batch == 3
        assert checkpoint2.total_updated == 3000
        assert checkpoint2.last_session_id == "xyz789"

    def test_atomic_write(self, temp_checkpoint: Path) -> None:
        """Test checkpoint file is written atomically."""
        checkpoint = CheckpointState(temp_checkpoint)
        checkpoint.save(batch_num=10, total_updated=5000)

        # Checkpoint file should exist
        assert temp_checkpoint.exists()

        # Temp file should NOT exist (atomic replace)
        tmp_file = temp_checkpoint.with_suffix(".tmp")
        assert not tmp_file.exists()

        # File should be valid JSON
        data = json.loads(temp_checkpoint.read_text())
        assert data["last_batch"] == 10
        assert data["total_updated"] == 5000
