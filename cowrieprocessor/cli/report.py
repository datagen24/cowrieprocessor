"""Reporting CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

from ..db import apply_migrations, create_engine_from_settings, create_session_maker
from ..loader import BulkLoaderMetrics, LoaderCheckpoint
from ..reporting import DailyReportBuilder, MonthlyReportBuilder, ReportingRepository, WeeklyReportBuilder
from ..reporting.builders import BaseReportBuilder, build_context_for_date
from ..settings import DatabaseSettings, load_database_settings
from ..status_emitter import StatusEmitter


def _resolve_db_settings(db_arg: Optional[str]) -> DatabaseSettings:
    if not db_arg:
        return load_database_settings()
    if db_arg.startswith("sqlite:"):
        return load_database_settings(config={"url": db_arg})
    db_path = Path(db_arg)
    if db_path.exists() or db_arg.endswith(".sqlite"):
        return DatabaseSettings(url=f"sqlite:///{db_path.resolve()}")
    return load_database_settings(config={"url": db_arg})


def _builder_for_mode(mode: str, repository: ReportingRepository, top_n: int) -> BaseReportBuilder:
    if mode == "daily":
        return DailyReportBuilder(repository, top_n=top_n)
    if mode == "weekly":
        return WeeklyReportBuilder(repository, top_n=top_n)
    if mode == "monthly":
        return MonthlyReportBuilder(repository, top_n=top_n)
    raise ValueError(f"Unknown report mode: {mode}")


def _date_range_for_mode(mode: str, start_date: datetime) -> datetime:
    if mode == "weekly":
        return start_date + timedelta(days=7)
    if mode == "monthly":
        return start_date + timedelta(days=30)
    return start_date + timedelta(days=1)


def main(argv: Iterable[str] | None = None) -> int:
    """Entry point for the reporting CLI."""
    parser = argparse.ArgumentParser(description="Generate Cowrie reports from ORM data")
    parser.add_argument("mode", choices=("daily", "weekly", "monthly"))
    parser.add_argument("date", help="Report date (YYYY-MM-DD)")
    parser.add_argument("--db")
    parser.add_argument("--sensor")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--status-dir", default=None)
    parser.add_argument("--output", help="Write JSON report to file instead of stdout")
    parser.add_argument("--ingest-id", help="Status identifier", default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)

    settings = _resolve_db_settings(args.db)
    engine = create_engine_from_settings(settings)
    apply_migrations(engine)
    session_factory = create_session_maker(engine)
    repository = ReportingRepository(session_factory)
    builder = _builder_for_mode(args.mode, repository, args.top_n)

    emitter = StatusEmitter("reporting", status_dir=args.status_dir)

    start = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=UTC)
    end = _date_range_for_mode(args.mode, start)

    context = build_context_for_date(args.date, args.sensor)
    context.end = end  # update for weekly/monthly

    emitter.record_metrics(
        BulkLoaderMetrics(ingest_id=args.ingest_id or f"report-{args.mode}-{args.date}")
    )

    report = builder.build(context)
    output_json = json.dumps(report, indent=2)

    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
    else:
        print(output_json)

    emitter.record_checkpoint(
        LoaderCheckpoint(
            ingest_id=str(args.ingest_id or report.get("report_type", "report")),
            source=args.mode,
            offset=0,
            batch_index=0,
            events_inserted=1,
            events_quarantined=0,
            sessions=[str(report.get("sensor", "aggregate"))],
        )
    )

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
