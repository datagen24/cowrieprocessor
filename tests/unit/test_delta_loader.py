"""Tests for the delta ingestion workflow."""

from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import func, select

from cowrieprocessor.db import (
    DeadLetterEvent,
    IngestCursor,
    RawEvent,
    apply_migrations,
    create_engine_from_settings,
    create_session_maker,
)
from cowrieprocessor.loader import (
    BulkLoader,
    BulkLoaderConfig,
    DeltaLoader,
    DeltaLoaderConfig,
)
from cowrieprocessor.settings import DatabaseSettings
from cowrieprocessor.status_emitter import StatusEmitter


def _make_engine(tmp_path: Path):
    db_path = tmp_path / "delta.sqlite"
    settings = DatabaseSettings(url=f"sqlite:///{db_path}")
    engine = create_engine_from_settings(settings)
    apply_migrations(engine)
    return engine


def _write_events(path: Path, events: list[dict], mode: str = "w") -> None:
    with path.open(mode, encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event))
            fh.write("\n")


def test_delta_loader_ingests_only_new_events(tmp_path) -> None:
    """Delta loader should append new events without duplicating existing rows."""
    source = tmp_path / "cowrie.log"
    initial_events = [
        {"session": "s1", "eventid": "cowrie.session.connect", "timestamp": "2024-01-01T00:00:00Z"},
        {"session": "s1", "eventid": "cowrie.command.input", "timestamp": "2024-01-01T00:01:00Z", "input": "echo hi"},
    ]
    _write_events(source, initial_events)

    engine = _make_engine(tmp_path)
    bulk = BulkLoader(engine, BulkLoaderConfig(batch_size=2))
    bulk.load_paths([source])

    new_event = {"session": "s1", "eventid": "cowrie.session.file_download", "timestamp": "2024-01-01T00:02:00Z"}
    _write_events(source, [new_event], mode="a")

    status_dir = tmp_path / "status"
    emitter = StatusEmitter("delta-test", status_dir=status_dir)
    delta = DeltaLoader(engine, DeltaLoaderConfig())
    metrics = delta.load_paths(
        [source],
        telemetry_cb=emitter.record_metrics,
        checkpoint_cb=emitter.record_checkpoint,
        dead_letter_cb=emitter.record_dead_letters,
    )

    assert metrics.events_inserted == 1
    with engine.connect() as conn:
        total = conn.execute(select(func.count()).select_from(RawEvent)).scalar_one()
        assert total == 3
    Session = create_session_maker(engine)
    with Session() as db_session:
        cursor = db_session.get(IngestCursor, str(source))
        assert cursor is not None
        assert cursor.last_offset >= 2


def test_delta_loader_handles_file_rotation(tmp_path) -> None:
    """When a file is rewritten with a new inode, delta loader should reprocess events."""
    source = tmp_path / "cowrie.log"
    _write_events(
        source,
        [{"session": "r1", "eventid": "cowrie.session.connect", "timestamp": "2024-02-01T10:00:00Z"}],
    )

    engine = _make_engine(tmp_path)
    bulk = BulkLoader(engine, BulkLoaderConfig(batch_size=1))
    bulk.load_paths([source])

    os.remove(source)
    _write_events(
        source,
        [
            {"session": "r2", "eventid": "cowrie.session.connect", "timestamp": "2024-02-01T11:00:00Z"},
            {
                "session": "r2",
                "eventid": "cowrie.command.input",
                "timestamp": "2024-02-01T11:05:00Z",
                "input": "curl http://x",
            },
        ],
    )

    status_dir = tmp_path / "status"
    emitter = StatusEmitter("delta-rotate", status_dir=status_dir)
    delta = DeltaLoader(engine, DeltaLoaderConfig())
    metrics = delta.load_paths(
        [source],
        telemetry_cb=emitter.record_metrics,
        checkpoint_cb=emitter.record_checkpoint,
        dead_letter_cb=emitter.record_dead_letters,
    )

    assert metrics.events_inserted == 2
    with engine.connect() as conn:
        total = conn.execute(select(func.count()).select_from(RawEvent)).scalar_one()
        assert total == 3  # original + two new from rotated file


def test_delta_loader_records_dead_letters(tmp_path) -> None:
    """Invalid events should populate the dead-letter queue instead of raw table."""
    source = tmp_path / "dlq.log"
    _write_events(source, [{"session": "dlq1", "eventid": "cowrie.command.input", "input": "wget http://bad"}])

    engine = _make_engine(tmp_path)
    status_dir = tmp_path / "status"
    emitter = StatusEmitter("delta-dlq", status_dir=status_dir)
    delta = DeltaLoader(engine, DeltaLoaderConfig())
    metrics = delta.load_paths(
        [source],
        telemetry_cb=emitter.record_metrics,
        checkpoint_cb=emitter.record_checkpoint,
        dead_letter_cb=emitter.record_dead_letters,
    )

    assert metrics.events_invalid == 1
    with engine.connect() as conn:
        total = conn.execute(select(func.count()).select_from(RawEvent)).scalar_one()
        assert total == 0
        dlq_count = conn.execute(select(func.count()).select_from(DeadLetterEvent)).scalar_one()
        assert dlq_count == 1

    status_file = status_dir / "delta-dlq.json"
    assert status_file.exists()
    data = json.loads(status_file.read_text(encoding="utf-8"))
    assert data.get("dead_letter", {}).get("total") == 1
