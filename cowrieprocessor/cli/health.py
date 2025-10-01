"""Lightweight health check CLI for Cowrie processor services."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from ..db.engine import create_engine_from_settings
from ..settings import DatabaseSettings


@dataclass(slots=True)
class HealthReport:
    """Consolidated health information for the processor."""

    status: str
    summary: str
    database_ok: bool
    status_files_ok: bool
    latest_status: dict

    def to_dict(self) -> dict:
        """Return this report as a plain dictionary for JSON/text output."""
        return {
            "status": self.status,
            "summary": self.summary,
            "database_ok": self.database_ok,
            "status_files_ok": self.status_files_ok,
            "latest_status": self.latest_status,
        }


def _check_database(db_url: Optional[str]) -> tuple[bool, str]:
    if not db_url:
        return False, "database URL not provided"
    
    # Check for unsupported database types first
    if not (db_url.startswith("sqlite://") or db_url.startswith("postgresql://") or db_url.startswith("postgres://")):
        return False, f"unsupported database type: {db_url}"
    
    # For SQLite, check file existence before creating engine
    if db_url.startswith("sqlite://"):
        db_path = db_url.replace("sqlite:///", "")
        if not Path(db_path).exists():
            return False, "sqlite database file missing"
    
    try:
        settings = DatabaseSettings(url=db_url)
        engine = create_engine_from_settings(settings)
        
        # Test database connection and basic query
        with engine.connect() as conn:
            # Try a simple query to test connectivity
            if db_url.startswith("sqlite://"):
                # SQLite integrity check
                result = conn.execute(text("PRAGMA integrity_check")).fetchone()
                if result and result[0] == 'ok':
                    return True, "sqlite integrity ok"
                else:
                    return False, "sqlite integrity check failed"
            elif db_url.startswith("postgresql://") or db_url.startswith("postgres://"):
                # PostgreSQL connectivity test
                result = conn.execute(text("SELECT 1")).fetchone()
                if result and result[0] == 1:
                    return True, "postgresql connection ok"
                else:
                    return False, "postgresql connection test failed"
                
    except SQLAlchemyError as exc:
        return False, f"database error: {exc}"
    except Exception as exc:
        return False, f"connection error: {exc}"


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
    """Run the health check CLI and return an exit status."""
    parser = argparse.ArgumentParser(description="Cowrie processor health check")
    parser.add_argument("--db-url", help="Database connection URL (SQLite or PostgreSQL)")
    parser.add_argument("--status-dir", help="Directory containing status JSON")
    parser.add_argument("--output", choices=("json", "text"), default="text")
    args = parser.parse_args(list(argv) if argv is not None else None)

    db_ok, db_summary = _check_database(args.db_url)
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
