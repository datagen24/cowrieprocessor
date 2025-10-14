"""Reporting CLI entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from secrets_resolver import is_reference, resolve_secret

from ..db import apply_migrations, create_engine_from_settings, create_session_maker
from ..loader import LoaderCheckpoint
from ..reporting import (
    DailyReportBuilder,
    ElasticsearchPublisher,
    MonthlyReportBuilder,
    ReportingRepository,
    WeeklyReportBuilder,
)
from ..reporting.builders import BaseReportBuilder, ReportContext
from ..status_emitter import StatusEmitter
from ..telemetry import start_span
from .db_config import resolve_database_settings


@dataclass(slots=True)
class ReportingMetrics:
    """Telemetry snapshot for reporting workflows."""

    ingest_id: str
    reports_requested: int
    reports_generated: int = 0
    sensors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    published_reports: int = 0
    errors: int = 0


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
        month = start_date.month
        year = start_date.year
        if month == 12:
            return start_date.replace(year=year + 1, month=1, day=1)
        return start_date.replace(year=year, month=month + 1, day=1)
    return start_date + timedelta(days=1)


def _normalize_date_input(mode: str, value: str) -> Tuple[datetime, str]:
    """Return the UTC window start and canonical label for the requested mode."""
    if mode == "weekly" and "W" in value:
        year_str, _, week_str = value.partition("-W")
        start = datetime.fromisocalendar(int(year_str), int(week_str), 1).replace(tzinfo=UTC)
        return start, f"{int(year_str):04d}-W{int(week_str):02d}"
    if mode == "monthly" and value.count("-") == 1 and len(value) == 7:
        year_str, month_str = value.split("-", 1)
        start = datetime(int(year_str), int(month_str), 1, tzinfo=UTC)
        return start, f"{int(year_str):04d}-{int(month_str):02d}"

    start = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    if mode == "weekly":
        iso_year, iso_week, _ = start.isocalendar()
        label = f"{iso_year:04d}-W{iso_week:02d}"
    elif mode == "monthly":
        label = start.strftime("%Y-%m")
    else:
        label = value
    return start, label


def _resolve_secret_value(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    try:
        if is_reference(value):
            return resolve_secret(value)
    except Exception:
        return value
    return value


def _create_publisher(args: argparse.Namespace) -> Optional[ElasticsearchPublisher]:
    """Create an Elasticsearch publisher when credentials are provided."""
    es_host = args.es_host or os.getenv("ES_HOST")
    es_cloud_id = args.es_cloud_id or os.getenv("ES_CLOUD_ID")
    es_username = _resolve_secret_value(os.getenv("ES_USERNAME"))
    es_password = _resolve_secret_value(os.getenv("ES_PASSWORD"))
    es_api_key = _resolve_secret_value(os.getenv("ES_API_KEY"))
    verify_env = os.getenv("ES_VERIFY_SSL")
    verify_ssl = True
    if args.no_ssl_verify:
        verify_ssl = False
    elif verify_env and verify_env.lower() in {"false", "0", "no", "off"}:
        verify_ssl = False

    intent_to_publish = args.publish or bool(es_host or es_cloud_id)
    if not intent_to_publish:
        return None
    if not (es_host or es_cloud_id):
        raise RuntimeError("Elasticsearch host or cloud ID is required for publishing")

    try:
        from elasticsearch import Elasticsearch
    except ModuleNotFoundError as exc:  # pragma: no cover - import guard
        raise RuntimeError("Install the 'elasticsearch' package to enable publishing") from exc

    client_kwargs: dict[str, object] = {"verify_certs": verify_ssl}
    if es_cloud_id:
        client_kwargs["cloud_id"] = es_cloud_id
    elif es_host:
        client_kwargs["hosts"] = [es_host]

    if es_api_key:
        client_kwargs["api_key"] = es_api_key
    elif es_username and es_password:
        client_kwargs["basic_auth"] = (es_username, es_password)

    client = Elasticsearch(**client_kwargs)
    if not client.ping():
        raise RuntimeError("Unable to reach Elasticsearch cluster; ping failed")

    index_prefix = args.es_index_prefix or os.getenv("ES_INDEX_PREFIX") or "cowrie.reports"
    pipeline = args.es_pipeline or os.getenv("ES_INGEST_PIPELINE")
    return ElasticsearchPublisher(client, index_prefix=index_prefix, pipeline=pipeline)


def _target_sensors(
    repository: ReportingRepository, mode: str, sensor: Optional[str], all_sensors: bool
) -> List[Optional[str]]:
    """Determine which sensors should be rendered for this invocation."""
    if sensor and all_sensors:
        raise ValueError("--sensor and --all-sensors are mutually exclusive")
    if all_sensors:
        if mode != "daily":
            raise ValueError("--all-sensors is only supported for daily reports")
        sensor_list: List[Optional[str]] = [name for name in repository.sensors()]
        sensor_list.append(None)
        return sensor_list
    if sensor:
        return [sensor]
    return [None]


def main(argv: Iterable[str] | None = None) -> int:
    """Entry point for the reporting CLI."""
    parser = argparse.ArgumentParser(description="Generate Cowrie reports from ORM data")
    parser.add_argument("mode", choices=("daily", "weekly", "monthly"))
    parser.add_argument("date", help="Report date (YYYY-MM-DD, YYYY-Www, or YYYY-MM as applicable)")
    parser.add_argument("--db")
    parser.add_argument("--sensor")
    parser.add_argument(
        "--all-sensors",
        action="store_true",
        help="Emit individual reports for each sensor plus aggregate",
    )
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--status-dir", default=None)
    parser.add_argument("--output", help="Write JSON report to file instead of stdout")
    parser.add_argument("--ingest-id", help="Status identifier", default=None)
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Force Elasticsearch publishing when credentials provided",
    )
    parser.add_argument("--es-host")
    parser.add_argument("--es-cloud-id")
    parser.add_argument("--es-index-prefix")
    parser.add_argument("--es-pipeline")
    parser.add_argument("--no-ssl-verify", action="store_true", help="Disable Elasticsearch SSL verification")
    args = parser.parse_args(list(argv) if argv is not None else None)

    settings = resolve_database_settings(args.db)
    engine = create_engine_from_settings(settings)
    apply_migrations(engine)
    session_factory = create_session_maker(engine)
    repository = ReportingRepository(session_factory)
    builder = _builder_for_mode(args.mode, repository, args.top_n)

    try:
        sensor_targets = _target_sensors(repository, args.mode, args.sensor, args.all_sensors)
    except ValueError as exc:
        parser.error(str(exc))

    if args.output and len(sensor_targets) > 1:
        parser.error("--output cannot be used with --all-sensors; provide a single sensor or aggregate report")

    start, label = _normalize_date_input(args.mode, args.date)
    end = _date_range_for_mode(args.mode, start)

    contexts = [ReportContext(start=start, end=end, date_label=label, sensor=s) for s in sensor_targets]
    ingest_id = args.ingest_id or f"report-{args.mode}-{label}"

    emitter = StatusEmitter("reporting", status_dir=args.status_dir)
    sensor_labels = [context.sensor or "aggregate" for context in contexts]
    metrics = ReportingMetrics(ingest_id=ingest_id, reports_requested=len(contexts), sensors=sensor_labels)
    emitter.record_metrics(metrics)

    start_time = time.perf_counter()

    with start_span(
        "cowrie.reporting.run",
        {
            "ingest.id": ingest_id,
            "mode": args.mode,
            "reports.requested": len(contexts),
        },
    ):
        reports = []
        for idx, context in enumerate(contexts):
            with start_span(
                "cowrie.reporting.build",
                {
                    "ingest.id": ingest_id,
                    "sensor": context.sensor or "aggregate",
                    "date": context.date_label,
                },
            ):
                report = builder.build(context)
                reports.append(report)
                payload = json.dumps(report, indent=2)

            metrics.reports_generated = len(reports)
            metrics.duration_seconds = time.perf_counter() - start_time
            emitter.record_metrics(metrics)

            if args.output:
                output_path = Path(args.output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(payload, encoding="utf-8")
            elif not args.all_sensors:
                print(payload)

            sensor_label = context.sensor or "aggregate"
            emitter.record_checkpoint(
                LoaderCheckpoint(
                    ingest_id=ingest_id,
                    source=f"{args.mode}:{context.date_label}",
                    offset=idx,
                    batch_index=idx,
                    events_inserted=1,
                    events_quarantined=0,
                    sessions=[sensor_label],
                )
            )

        try:
            publisher = _create_publisher(args)
        except RuntimeError as exc:
            parser.error(str(exc))
            return 2

        if publisher and reports:
            with start_span(
                "cowrie.reporting.publish",
                {
                    "ingest.id": ingest_id,
                    "reports": len(reports),
                },
            ):
                try:
                    publisher.publish(reports)
                    metrics.published_reports = len(reports)
                except Exception:
                    metrics.errors = len(reports)
                    metrics.duration_seconds = time.perf_counter() - start_time
                    emitter.record_metrics(metrics)
                    raise
        metrics.duration_seconds = time.perf_counter() - start_time
        emitter.record_metrics(metrics)

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
