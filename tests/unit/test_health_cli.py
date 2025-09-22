"""Tests for the health check CLI."""

from __future__ import annotations

import json
from pathlib import Path

from cowrieprocessor.cli import health as health_cli


def _write_status(dir_path: Path, name: str, payload: dict) -> None:
    path = dir_path / f"{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_health_cli_json(tmp_path, capsys):
    """Health CLI should report OK for valid db and status files."""
    db_path = tmp_path / "db.sqlite"
    db_path.write_text("", encoding="utf-8")
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    _write_status(status_dir, "status", {"last_updated": "2025-01-01T00:00:00Z"})

    exit_code = health_cli.main([
        "--db",
        str(db_path),
        "--status-dir",
        str(status_dir),
        "--output",
        "json",
    ])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["database_ok"] is True
    assert output["status_files_ok"] is True


def test_health_cli_missing_status(tmp_path, capsys):
    """Health CLI should warn when status files are missing."""
    db_path = tmp_path / "db.sqlite"
    db_path.write_text("", encoding="utf-8")
    exit_code = health_cli.main([
        "--db",
        str(db_path),
        "--status-dir",
        str(tmp_path / "missing"),
    ])

    assert exit_code == 1
    text_out = capsys.readouterr().out
    assert "warning" in text_out.lower()
