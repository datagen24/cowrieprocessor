"""Reporting CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Iterable, List, Optional, Tuple

from ..db import apply_migrations, create_engine_from_settings, create_session_maker
from ..enrichment.ssh_key_analytics import SSHKeyAnalytics
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
        # Add approximately one month
        if start_date.month == 12:
            return start_date.replace(year=start_date.year + 1, month=1)
        return start_date.replace(month=start_date.month + 1)
    # Daily reports span one day
    return start_date + timedelta(days=1)


def _normalize_date_input(mode: str, date_str: str) -> Tuple[datetime, str]:
    """Parse and normalize date input for different report modes.

    Args:
        mode: Report mode (daily, weekly, monthly)
        date_str: Date string to parse

    Returns:
        Tuple of (start_datetime, label)
    """
    if mode == "daily":
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
            return dt, date_str
        except ValueError:
            raise ValueError(f"Invalid daily date format '{date_str}'. Use YYYY-MM-DD.")

    elif mode == "weekly":
        try:
            # Parse YYYY-Www format
            year_str, week_str = date_str.split("-W")
            year = int(year_str)
            week = int(week_str)

            # Find the first day of the week (Monday)
            jan_1 = datetime(year, 1, 1).replace(tzinfo=UTC)
            jan_1_weekday = jan_1.weekday()  # 0 = Monday, 6 = Sunday

            # Calculate days to first Monday of the year
            days_to_monday = (7 - jan_1_weekday) % 7
            first_monday = jan_1 + timedelta(days=days_to_monday)

            # Calculate start of target week
            week_start = first_monday + timedelta(weeks=week - 1)
            return week_start, date_str
        except (ValueError, IndexError):
            raise ValueError(f"Invalid weekly date format '{date_str}'. Use YYYY-Www.")

    elif mode == "monthly":
        try:
            # Parse YYYY-MM format
            year_str, month_str = date_str.split("-")
            year = int(year_str)
            month = int(month_str)

            dt = datetime(year, month, 1).replace(tzinfo=UTC)
            return dt, date_str
        except (ValueError, IndexError):
            raise ValueError(f"Invalid monthly date format '{date_str}'. Use YYYY-MM.")

    else:
        raise ValueError(f"Unknown report mode: {mode}")


def _create_publisher(args: argparse.Namespace) -> Optional[ElasticsearchPublisher]:
    """Create Elasticsearch publisher if credentials are available.

    Args:
        args: Parsed command line arguments

    Returns:
        ElasticsearchPublisher instance or None

    Raises:
        RuntimeError: If credentials are provided but incomplete
    """
    if not args.publish:
        return None

    # Check if any Elasticsearch credentials are provided
    es_creds = [
        args.es_host,
        args.es_cloud_id,
        args.es_index_prefix,
    ]

    if not any(es_creds):
        return None

    # Validate required credentials
    if not args.es_index_prefix:
        raise RuntimeError("--es-index-prefix is required when publishing to Elasticsearch")

    if not (args.es_host or args.es_cloud_id):
        raise RuntimeError("Either --es-host or --es-cloud-id is required when publishing to Elasticsearch")

    return ElasticsearchPublisher(
        host=args.es_host,
        cloud_id=args.es_cloud_id,
        index_prefix=args.es_index_prefix,
        pipeline=args.es_pipeline,
        verify_ssl=not args.no_ssl_verify,
    )


def _target_sensors(
    repository: ReportingRepository, mode: str, sensor: Optional[str], all_sensors: bool
) -> List[Optional[str]]:
    """Determine target sensors for report generation.

    Args:
        repository: Reporting repository
        mode: Report mode
        sensor: Specific sensor name
        all_sensors: Whether to generate reports for all sensors

    Returns:
        List of sensor names (None for aggregate)
    """
    if all_sensors:
        sensor_list = repository.get_available_sensors()
        if not sensor_list:
            raise ValueError("No sensors found in database")
        return sensor_list
    if sensor:
        return [sensor]
    return [None]


def generate_ssh_key_report(args: argparse.Namespace) -> int:
    """Generate SSH key intelligence report.

    Args:
        args: Parsed command line arguments

    Returns:
        Exit code (0 for success)
    """
    try:
        # Resolve database settings
        settings = resolve_database_settings(args.db)
        engine = create_engine_from_settings(settings)
        apply_migrations(engine)
        session_factory = create_session_maker(engine)

        with session_factory() as session:
            analytics = SSHKeyAnalytics(session)

            if args.report_type == "summary":
                return _generate_ssh_key_summary(analytics, args)
            elif args.report_type == "campaigns":
                return _generate_ssh_key_campaigns(analytics, args)
            elif args.report_type == "detail":
                return _generate_ssh_key_detail(analytics, args)
            else:
                print(f"Unknown SSH key report type: {args.report_type}")
                return 1

    except Exception as e:
        print(f"SSH key report generation failed: {e}", file=sys.stderr)
        return 1
    finally:
        if 'engine' in locals():
            engine.dispose()


def _generate_ssh_key_summary(analytics: SSHKeyAnalytics, args: argparse.Namespace) -> int:
    """Generate SSH key summary report."""
    days_back = args.days_back or 30
    top_keys = analytics.get_top_keys_by_usage(days_back=days_back, limit=args.limit)

    report = {
        "report_type": "ssh_key_summary",
        "period_days": days_back,
        "total_keys": len(top_keys),
        "top_keys": top_keys,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2, default=str)
    else:
        print(json.dumps(report, indent=2, default=str))

    return 0


def _generate_ssh_key_campaigns(analytics: SSHKeyAnalytics, args: argparse.Namespace) -> int:
    """Generate SSH key campaigns report."""
    campaigns = analytics.identify_campaigns(
        min_attempts=args.min_attempts,
        min_ips=args.min_ips,
        days_back=args.days_back,
        confidence_threshold=args.confidence_threshold,
    )

    report = {
        "report_type": "ssh_key_campaigns",
        "period_days": args.days_back,
        "min_attempts": args.min_attempts,
        "min_ips": args.min_ips,
        "confidence_threshold": args.confidence_threshold,
        "total_campaigns": len(campaigns),
        "campaigns": [
            {
                "campaign_id": campaign.campaign_id,
                "key_count": len(campaign.key_fingerprints),
                "total_sessions": campaign.total_sessions,
                "unique_ips": campaign.unique_ips,
                "confidence_score": campaign.confidence_score,
                "key_types": list(campaign.key_types),
                "injection_methods": list(campaign.injection_methods),
                "date_range": {
                    "first_seen": campaign.date_range[0].isoformat() if campaign.date_range[0] else None,
                    "last_seen": campaign.date_range[1].isoformat() if campaign.date_range[1] else None,
                },
                "key_fingerprints": list(campaign.key_fingerprints),
            }
            for campaign in campaigns
        ],
        "generated_at": datetime.now(UTC).isoformat(),
    }

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2, default=str)
    else:
        print(json.dumps(report, indent=2, default=str))

    return 0


def _generate_ssh_key_detail(analytics: SSHKeyAnalytics, args: argparse.Namespace) -> int:
    """Generate SSH key detail report."""
    if not args.fingerprint:
        print("Error: --fingerprint is required for detail report", file=sys.stderr)
        return 1

    timeline = analytics.get_key_timeline(args.fingerprint)
    if not timeline:
        print(f"Error: SSH key with fingerprint {args.fingerprint} not found", file=sys.stderr)
        return 1

    # Get related keys
    related_keys = analytics.find_related_keys(
        args.fingerprint,
        min_association_strength=args.min_association_strength,
        max_results=args.max_related,
    )

    # Get geographic spread
    geo_spread = analytics.calculate_geographic_spread(args.fingerprint)

    report = {
        "report_type": "ssh_key_detail",
        "key_info": {
            "fingerprint": timeline.key_fingerprint,
            "key_type": timeline.key_type,
            "first_seen": timeline.first_seen.isoformat() if timeline.first_seen else None,
            "last_seen": timeline.last_seen.isoformat() if timeline.last_seen else None,
            "total_attempts": timeline.total_attempts,
            "unique_sources": timeline.unique_sources,
            "unique_sessions": timeline.unique_sessions,
        },
        "sessions": timeline.sessions,
        "related_keys": [
            {
                "fingerprint": assoc.key2_fingerprint,
                "association_strength": assoc.association_strength,
                "co_occurrence_count": assoc.co_occurrence_count,
                "same_session_count": assoc.same_session_count,
                "same_ip_count": assoc.same_ip_count,
            }
            for assoc in related_keys
        ],
        "geographic_spread": geo_spread,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2, default=str)
    else:
        print(json.dumps(report, indent=2, default=str))

    return 0


def _generate_traditional_report(args: argparse.Namespace) -> int:
    """Generate traditional daily/weekly/monthly reports."""
    settings = resolve_database_settings(args.db)
    engine = create_engine_from_settings(settings)
    apply_migrations(engine)
    session_factory = create_session_maker(engine)
    repository = ReportingRepository(session_factory)
    builder = _builder_for_mode(args.mode, repository, args.top_n)

    try:
        sensor_targets = _target_sensors(repository, args.mode, args.sensor, args.all_sensors)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.output and len(sensor_targets) > 1:
        print(
            "Error: --output cannot be used with --all-sensors; provide a single sensor or aggregate report",
            file=sys.stderr,
        )
        return 1

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
            try:
                report = builder.build_report(context)
                reports.append(report)
                metrics.reports_generated += 1

                if args.publish:
                    publisher = ElasticsearchPublisher(
                        host=args.es_host,
                        cloud_id=args.es_cloud_id,
                        index_prefix=args.es_index_prefix,
                        pipeline=args.es_pipeline,
                        verify_ssl=not args.no_ssl_verify,
                    )
                    if publisher.can_publish():
                        publisher.publish_report(report)
                        metrics.published_reports += 1
                    else:
                        print("Warning: Elasticsearch credentials not available, skipping publish", file=sys.stderr)

            except Exception as e:
                print(f"Failed to generate report for {context.sensor or 'aggregate'}: {e}", file=sys.stderr)
                metrics.errors += 1

    metrics.duration_seconds = time.perf_counter() - start_time
    emitter.record_metrics(metrics)

    # Output reports
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(reports[0] if len(reports) == 1 else reports, f, indent=2, default=str)
    else:
        print(json.dumps(reports[0] if len(reports) == 1 else reports, indent=2, default=str))

    return 0


def main(argv: Iterable[str] | None = None) -> int:
    """Entry point for the reporting CLI."""
    parser = argparse.ArgumentParser(description="Generate Cowrie reports from ORM data")

    # Add subcommands
    subparsers = parser.add_subparsers(dest='command', help='Report type')

    # Traditional reports (daily, weekly, monthly)
    traditional_parser = subparsers.add_parser('traditional', help='Generate traditional reports')
    traditional_parser.add_argument("mode", choices=("daily", "weekly", "monthly"))
    traditional_parser.add_argument("date", help="Report date (YYYY-MM-DD, YYYY-Www, or YYYY-MM as applicable)")
    traditional_parser.add_argument("--db")
    traditional_parser.add_argument("--sensor")
    traditional_parser.add_argument(
        "--all-sensors", action="store_true", help="Emit individual reports for each sensor plus aggregate"
    )
    traditional_parser.add_argument("--top-n", type=int, default=10)
    traditional_parser.add_argument("--status-dir", default=None)
    traditional_parser.add_argument("--output", help="Write JSON report to file instead of stdout")
    traditional_parser.add_argument("--ingest-id", help="Status identifier", default=None)
    traditional_parser.add_argument(
        "--publish", action="store_true", help="Force Elasticsearch publishing when credentials provided"
    )
    traditional_parser.add_argument("--es-host")
    traditional_parser.add_argument("--es-cloud-id")
    traditional_parser.add_argument("--es-index-prefix")
    traditional_parser.add_argument("--es-pipeline")
    traditional_parser.add_argument(
        "--no-ssl-verify", action="store_true", help="Disable Elasticsearch SSL verification"
    )
    traditional_parser.set_defaults(func=lambda args: _generate_traditional_report(args))

    # SSH key intelligence reports
    ssh_parser = subparsers.add_parser('ssh-keys', help='Generate SSH key intelligence reports')
    ssh_parser.add_argument("report_type", choices=("summary", "campaigns", "detail"), help="Type of SSH key report")
    ssh_parser.add_argument("--db", help="Database path or connection string")
    ssh_parser.add_argument("--days-back", type=int, default=30, help="Number of days to look back (default: 30)")
    ssh_parser.add_argument("--output", help="Output file (default: stdout)")
    ssh_parser.add_argument("--limit", type=int, default=10, help="Limit number of results (default: 10)")

    # Campaign-specific options
    ssh_parser.add_argument("--min-attempts", type=int, default=5, help="Minimum attempts for campaigns (default: 5)")
    ssh_parser.add_argument("--min-ips", type=int, default=3, help="Minimum IPs for campaigns (default: 3)")
    ssh_parser.add_argument(
        "--confidence-threshold", type=float, default=0.6, help="Minimum confidence for campaigns (default: 0.6)"
    )

    # Detail-specific options
    ssh_parser.add_argument("--fingerprint", help="SSH key fingerprint for detail report")
    ssh_parser.add_argument(
        "--min-association-strength", type=float, default=0.3, help="Minimum association strength (default: 0.3)"
    )
    ssh_parser.add_argument("--max-related", type=int, default=10, help="Maximum related keys to show (default: 10)")

    ssh_parser.set_defaults(func=generate_ssh_key_report)

    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
