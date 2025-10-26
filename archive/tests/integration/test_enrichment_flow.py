"""Integration tests for the offline enrichment harness."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests.integration.enrichment_harness import OfflineEnrichmentHarness

REAL_SNAPSHOT = Path("/mnt/dshield/data/db/cowrieprocessor.sqlite")


def _create_synthetic_db(db_path: Path) -> None:
    """Provision a lightweight SQLite database matching expected tables."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE session_summaries (
                session_id TEXT PRIMARY KEY,
                first_event_at TEXT,
                last_event_at TEXT,
                event_count INTEGER DEFAULT 0,
                command_count INTEGER DEFAULT 0,
                file_downloads INTEGER DEFAULT 0,
                login_attempts INTEGER DEFAULT 0,
                vt_flagged INTEGER DEFAULT 0,
                dshield_flagged INTEGER DEFAULT 0,
                risk_score INTEGER,
                matcher TEXT,
                source_files TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                enrichment TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE raw_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                payload TEXT,
                event_timestamp TEXT
            )
            """
        )
        session_id = "session-high-risk"
        payload = {
            "session": session_id,
            "src_ip": "198.51.100.10",
            "timestamp": "2025-07-01T10:00:00Z",
        }
        conn.execute(
            "INSERT INTO session_summaries (session_id, risk_score) VALUES (?, ?)",
            (session_id, 95),
        )
        conn.execute(
            "INSERT INTO raw_events (session_id, payload, event_timestamp) VALUES (?, ?, ?)",
            (session_id, json.dumps(payload), payload["timestamp"]),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(name="synthetic_db")
def fixture_synthetic_db(tmp_path: Path) -> Path:
    """Create a temporary SQLite database with the minimal enrichment schema."""
    db_path = tmp_path / "synthetic.sqlite"
    _create_synthetic_db(db_path)
    return db_path


@pytest.mark.integration
@pytest.mark.enrichment
def test_high_risk_session_full_enrichment(synthetic_db: Path, tmp_path: Path) -> None:
    """Verify all enrichment services populate flags for a high-risk session."""
    cache_dir = tmp_path / "cache"
    with OfflineEnrichmentHarness(synthetic_db, cache_dir) as harness:
        sessions = harness.sample_sessions(limit=1)
        assert sessions, "Expected at least one synthetic session"

        session_id, src_ip = sessions[0]
        result = harness.evaluate_session(session_id, src_ip, file_hashes=["deadbeefdeadbeefdeadbeefdeadbeef"])

        assert set(result.enrichment.keys()) == {"dshield", "urlhaus", "spur", "virustotal"}
        assert result.flags["dshield_flagged"] is True
        assert result.flags["urlhaus_flagged"] is True
        assert result.flags["spur_flagged"] is True
        assert result.flags["vt_flagged"] is True

        snapshot = harness.cache_snapshot()
        assert "hits" in snapshot and "misses" in snapshot and "stores" in snapshot


@pytest.mark.integration
@pytest.mark.enrichment
def test_enrichment_graceful_degradation(synthetic_db: Path, tmp_path: Path) -> None:
    """Ensure enrichment gracefully degrades when services return empty data."""
    cache_dir = tmp_path / "cache"
    stubs = {
        "dshield": {"default": {"ip": {"asname": "", "ascountry": ""}}},
        "urlhaus": {"default": ""},
        "spur": {"default": ["" for _ in range(18)]},
        "virustotal": {"default": None},
    }

    with OfflineEnrichmentHarness(synthetic_db, cache_dir, stubbed_responses=stubs) as harness:
        session_id, src_ip = harness.sample_sessions(limit=1)[0]
        result = harness.evaluate_session(session_id, src_ip, file_hashes=["deadbeefdeadbeefdeadbeefdeadbeef"])

        assert result.enrichment["dshield"] == {"ip": {"asname": "", "ascountry": ""}}
        assert result.enrichment["urlhaus"] == ""
        assert len(result.enrichment["spur"]) == 18
        assert all(value == "" for value in result.enrichment["spur"])
        assert result.enrichment.get("virustotal") is None

        assert all(flag is False for flag in result.flags.values())


@pytest.mark.integration
@pytest.mark.enrichment
@pytest.mark.slow
@pytest.mark.skipif(not REAL_SNAPSHOT.exists(), reason="Real snapshot not available")
def test_real_snapshot_sessions_load_without_network(tmp_path: Path) -> None:
    """Exercise the live snapshot in offline mode to confirm harness safety."""
    cache_dir = tmp_path / "cache"
    with OfflineEnrichmentHarness(REAL_SNAPSHOT, cache_dir) as harness:
        sessions = harness.sample_sessions(limit=3)
        assert sessions, "Expected snapshot to contain session summaries"

        session_id, src_ip = sessions[0]
        result = harness.evaluate_session(session_id, src_ip)

        assert "dshield" in result.enrichment
        assert "spur" in result.enrichment
        assert result.flags["dshield_flagged"] in (True, False)
