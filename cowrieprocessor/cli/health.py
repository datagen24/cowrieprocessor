"""Lightweight health check CLI for Cowrie processor services."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass(slots=True)
class HealthReport:
    """Consolidated health information for the processor."""

    status: str
    summary: str
    database_ok: bool
    status_files_ok: bool
    latest_status: dict

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "summary": self.summary,
            "database_ok": self.database_ok,
            "status_files_ok": self.status_files_ok,
            "latest_status": self.latest_status,
        }


def _check_database(db_path: Optional[str]) -> tuple[bool, str]:
    if not db_path:
        return False, "database path not provided"
    path = Path(db_path)
    if not path.exists():
        return False, "database file missing"
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.execute("PRAGMA integrity_check")
        conn.close()
    except sqlite3.Error as exc:  # pragma: no cover - depends on corruption scenarios
        return False, f"sqlite error: {exc}"  # best-effort message
    return True, "sqlite integrity ok"


def _load_status(status_dir: Optional[str]) -> tuple[bool, dict]:
    if not status_dir:
        status_dir = "/mnt/dshield/data/logs/status"
    base = Path(status_dir)
    aggregate = base / "status.json"
    if aggregate.exists():
        try:
            return True, json.loads(aggregate.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    latest = {}
    status_files_ok = False
    for phase_file in sorted(base.glob("*.json")):
        try:
            payload = json.loads(phase_file.read_text(encoding="utf-8"))
            latest[phase_file.stem] = payload
            status_files_ok = True
        except json.JSONDecodeError:
            latest[phase_file.stem] = {"error": "invalid json"}
    return status_files_ok, latest


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cowrie processor health check")
    parser.add_argument("--db", help="Path to SQLite database")
    parser.add_argument("--status-dir", help="Directory containing status JSON")
    parser.add_argument("--output", choices=("json", "text"), default="text")
    args = parser.parse_args(list(argv) if argv is not None else None)

    db_ok, db_summary = _check_database(args.db)
    status_ok, latest_status = _load_status(args.status_dir)

    if db_ok and status_ok:
        status = "ok"
        summary = "Database accessible and status telemetry available"
    elif not db_ok and not status_ok:
        status = "critical"
        summary = f"Database check failed ({db_summary}); status telemetry unavailable"
    elif not db_ok:
        status = "warning"
        summary = f"Database check failed ({db_summary})"
    else:
        status = "warning"
        summary = "Status telemetry unavailable"

    report = HealthReport(
        status=status,
        summary=summary,
        database_ok=db_ok,
        status_files_ok=status_ok,
        latest_status=latest_status,
    )

    if args.output == "json":
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"Status: {report.status}")
        print(f"Summary: {report.summary}")
        print(f"Database OK: {report.database_ok} ({db_summary})")
        print(f"Status files OK: {report.status_files_ok}")
        if report.latest_status:
            for phase, payload in report.latest_status.items():
                last = payload.get("last_updated") if isinstance(payload, dict) else None
                print(f"  - {phase}: last_updated={last}")

    return 0 if report.status == "ok" else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
