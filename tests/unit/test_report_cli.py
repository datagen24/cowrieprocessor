"""Tests for the reporting CLI."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cowrieprocessor.cli import report as report_cli
from cowrieprocessor.db import Base, SessionSummary


def _seed_db(path: Path) -> str:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as session:
        session.add(
            SessionSummary(
                session_id="s1",
                first_event_at=datetime(2024, 1, 1, tzinfo=UTC),
                last_event_at=datetime(2024, 1, 1, 1, tzinfo=UTC),
                event_count=4,
                command_count=2,
                file_downloads=1,
                login_attempts=0,
                vt_flagged=0,
                dshield_flagged=0,
                matcher="sensor-a",
            )
        )
        session.commit()

    return f"sqlite:///{path}"


def test_report_cli_dry_run(tmp_path, capsys):
    """CLI should emit report JSON and status file in dry-run mode."""
    db_path = tmp_path / "report.sqlite"
    db_url = _seed_db(db_path)
    status_dir = tmp_path / "status"

    exit_code = report_cli.main(
        [
            "daily",
            "2024-01-01",
            "--db",
            db_url,
            "--status-dir",
            str(status_dir),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["report_type"] == "daily"

    status_file = status_dir / "reporting.json"
    assert status_file.exists()


def test_report_cli_all_sensors(tmp_path, capsys):
    """CLI should handle --all-sensors by emitting no stdout and multiple checkpoints."""
    db_path = tmp_path / "report.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as session:
        session.add_all(
            [
                SessionSummary(
                    session_id="s1",
                    first_event_at=datetime(2024, 1, 1, tzinfo=UTC),
                    last_event_at=datetime(2024, 1, 1, 1, tzinfo=UTC),
                    event_count=4,
                    command_count=2,
                    file_downloads=1,
                    login_attempts=0,
                    vt_flagged=0,
                    dshield_flagged=0,
                    matcher="sensor-a",
                ),
                SessionSummary(
                    session_id="s2",
                    first_event_at=datetime(2024, 1, 1, tzinfo=UTC),
                    last_event_at=datetime(2024, 1, 1, 2, tzinfo=UTC),
                    event_count=3,
                    command_count=1,
                    file_downloads=0,
                    login_attempts=0,
                    vt_flagged=0,
                    dshield_flagged=0,
                    matcher="sensor-b",
                ),
            ]
        )
        session.commit()

    exit_code = report_cli.main(
        [
            "daily",
            "2024-01-01",
            "--db",
            f"sqlite:///{db_path}",
            "--all-sensors",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out == ""
