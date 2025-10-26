"""Tests for the status emitter."""

from __future__ import annotations
from pathlib import Path

import json
from datetime import datetime

from cowrieprocessor.loader.bulk import BulkLoaderMetrics, LoaderCheckpoint
from cowrieprocessor.status_emitter import StatusEmitter


def test_status_emitter_writes_metrics_and_checkpoint(tmp_path: Path) -> None:
    """Status emitter should persist metrics, checkpoints, and DLQ data."""
    status_dir = tmp_path / "status"
    emitter = StatusEmitter("delta", status_dir=status_dir)

    metrics = BulkLoaderMetrics(ingest_id="ing-1", files_processed=2, events_read=5, events_inserted=5)
    emitter.record_metrics(metrics)

    checkpoint = LoaderCheckpoint(
        ingest_id="ing-1",
        source="/tmp/log.json",
        offset=10,
        batch_index=1,
        events_inserted=5,
        events_quarantined=0,
        sessions=["s1"],
    )
    emitter.record_checkpoint(checkpoint)
    emitter.record_dead_letters(2, "validation", "/tmp/log.json")

    status_file = status_dir / "delta.json"
    assert status_file.exists()
    payload = json.loads(status_file.read_text(encoding="utf-8"))
    assert payload["phase"] == "delta"
    assert payload["metrics"]["events_inserted"] == 5
    assert payload["checkpoint"]["offset"] == 10
    assert payload["dead_letter"]["total"] == 2
    assert "last_updated" in payload
    datetime.fromisoformat(payload["last_updated"])

    aggregate_file = status_dir / "status.json"
    assert aggregate_file.exists()
    aggregate = json.loads(aggregate_file.read_text(encoding="utf-8"))
    assert "phases" in aggregate
    delta_phase = aggregate["phases"]["delta"]
    assert delta_phase["metrics"]["events_inserted"] == 5
