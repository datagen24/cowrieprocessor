"""Analysis CLI for Cowrie Processor threat detection."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from ..db import apply_migrations, create_engine_from_settings, create_session_maker
from ..db.models import SessionSummary, SnowshoeDetection, RawEvent
from ..settings import DatabaseSettings, load_database_settings
from ..status_emitter import StatusEmitter
from ..telemetry import start_span
from ..threat_detection import BotnetCoordinatorDetector, LongtailAnalyzer, LongtailAnalysisResult, SnowshoeDetector, create_snowshoe_metrics_from_detection
from sqlalchemy import and_, func
from .db_config import resolve_database_settings, add_database_argument


def _parse_window_arg(window_str: str) -> timedelta:
    """Parse window argument into timedelta.
    
    Args:
        window_str: Window string (e.g., "24h", "7d", "48h")
        
    Returns:
        Timedelta object
        
    Raises:
        ValueError: If window format is invalid
    """
    window_str = window_str.lower().strip()
    
    if window_str.endswith('h'):
        hours = int(window_str[:-1])
        return timedelta(hours=hours)
    elif window_str.endswith('d'):
        days = int(window_str[:-1])
        return timedelta(days=days)
    else:
        raise ValueError(f"Invalid window format: {window_str}. Use format like '24h' or '7d'")


def _query_sessions_for_analysis(
    session_factory,
    window_start: datetime,
    window_end: datetime,
    sensor: Optional[str] = None,
) -> list[SessionSummary]:
    """Query sessions for snowshoe analysis.
    
    Args:
        session_factory: SQLAlchemy session factory
        window_start: Start of analysis window
        window_end: End of analysis window
        sensor: Optional sensor filter
        
    Returns:
        List of session summaries
    """
    with session_factory() as session:
        query = session.query(SessionSummary).filter(
            and_(
                SessionSummary.first_event_at >= window_start,
                SessionSummary.first_event_at < window_end,
            )
        )
        
        if sensor:
            # Filter by sensor if source_files contains the sensor name
            query = query.filter(
                func.json_extract(SessionSummary.source_files, '$.sensor').like(f'%{sensor}%')
            )
        
        return query.all()


def snowshoe_analyze(args: argparse.Namespace) -> int:
    """Analyze sessions for snowshoe attacks.
    
    Args:
        args: Parsed command line arguments
        
    Returns:
        Exit code (0 for success)
    """
    try:
        # Parse window
        window_delta = _parse_window_arg(args.window)
        window_end = datetime.now(UTC)
        window_start = window_end - window_delta
        
        logger.info(
            "Starting snowshoe analysis: window=%s, sensitivity=%.2f, sensor=%s",
            args.window,
            args.sensitivity,
            args.sensor or "all",
        )
        
        # Setup database
        settings = resolve_database_settings(args.db)
        engine = create_engine_from_settings(settings)
        apply_migrations(engine)
        session_factory = create_session_maker(engine)
        
        # Query sessions
        sessions = _query_sessions_for_analysis(
            session_factory, window_start, window_end, args.sensor
        )
        
        if not sessions:
            logger.warning("No sessions found for analysis window")
            return 1
        
        logger.info("Found %d sessions for analysis", len(sessions))
        
        # Initialize detector
        detector = SnowshoeDetector(sensitivity_threshold=args.sensitivity)
        
        # Perform analysis
        analysis_start_time = time.perf_counter()
        with start_span(
            "cowrie.snowshoe.analyze",
            {
                "window_hours": window_delta.total_seconds() / 3600,
                "session_count": len(sessions),
                "sensor": args.sensor or "all",
            },
        ):
            result = detector.detect(sessions, window_delta.total_seconds() / 3600)
        
        analysis_duration = time.perf_counter() - analysis_start_time
        
        # Store results in database if requested
        if args.store_results:
            _store_detection_result(session_factory, result, window_start, window_end)
        
        # Output results
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open('w') as f:
                json.dump(result, f, indent=2)
            logger.info("Results written to %s", output_path)
        else:
            print(json.dumps(result, indent=2))
        
        # Emit metrics
        if args.status_dir:
            analysis_id = args.ingest_id or f"snowshoe-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            window_hours = window_delta.total_seconds() / 3600
            
            # Create comprehensive metrics
            metrics = create_snowshoe_metrics_from_detection(
                detection_result=result,
                analysis_duration=analysis_duration,
                analysis_id=analysis_id,
                window_hours=window_hours,
            )
            
            emitter = StatusEmitter("snowshoe-analysis", status_dir=args.status_dir)
            emitter.record_metrics(metrics)
        
        return 0 if result["is_likely_snowshoe"] else 1
        
    except Exception as e:
        logger.error("Snowshoe analysis failed: %s", str(e), exc_info=True)
        return 2


def _store_detection_result(
    session_factory,
    result: dict,
    window_start: datetime,
    window_end: datetime,
) -> None:
    """Store detection result in database.
    
    Args:
        session_factory: SQLAlchemy session factory
        result: Detection result dictionary
        window_start: Analysis window start
        window_end: Analysis window end
    """
    try:
        with session_factory() as session:
            detection = SnowshoeDetection(
                window_start=window_start,
                window_end=window_end,
                confidence_score=str(result["confidence_score"]),
                unique_ips=result["analysis_metadata"]["unique_ips"],
                single_attempt_ips=len(result["single_attempt_ips"]),
                geographic_spread=str(result["geographic_spread"]),
                indicators=result["indicators"],
                is_likely_snowshoe=result["is_likely_snowshoe"],
                coordinated_timing=result["coordinated_timing"],
                recommendation=result["recommendation"],
                analysis_metadata=result["analysis_metadata"],
            )
            session.add(detection)
            session.commit()
            logger.info("Stored detection result with ID %d", detection.id)
    except Exception as e:
        logger.error("Failed to store detection result: %s", str(e))


def snowshoe_report(args: argparse.Namespace) -> int:
    """Generate snowshoe detection reports.
    
    Args:
        args: Parsed command line arguments
        
    Returns:
        Exit code (0 for success)
    """
    try:
        # Setup database
        settings = resolve_database_settings(args.db)
        engine = create_engine_from_settings(settings)
        session_factory = create_session_maker(engine)
        
        # Parse date range
        if args.date:
            # Single date report
            start_date = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=UTC)
            end_date = start_date + timedelta(days=1)
        else:
            # Default to last 7 days
            end_date = datetime.now(UTC)
            start_date = end_date - timedelta(days=7)
        
        # Query detection results
        with session_factory() as session:
            query = session.query(SnowshoeDetection).filter(
                and_(
                    SnowshoeDetection.detection_time >= start_date,
                    SnowshoeDetection.detection_time < end_date,
                )
            )
            
            if args.min_confidence:
                query = query.filter(SnowshoeDetection.confidence_score >= str(args.min_confidence))
            
            detections = query.order_by(SnowshoeDetection.detection_time.desc()).all()
        
        # Generate report
        report = {
            "report_type": "snowshoe_detection_summary",
            "generated_at": datetime.now(UTC).isoformat(),
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "summary": {
                "total_detections": len(detections),
                "high_confidence_detections": len([d for d in detections if d.is_likely_snowshoe]),
                "coordinated_attacks": len([d for d in detections if d.coordinated_timing]),
                "avg_confidence": sum(float(d.confidence_score) for d in detections) / len(detections) if detections else 0,
            },
            "detections": [
                {
                    "id": d.id,
                    "detection_time": d.detection_time.isoformat(),
                    "confidence_score": float(d.confidence_score),
                    "is_likely_snowshoe": d.is_likely_snowshoe,
                    "coordinated_timing": d.coordinated_timing,
                    "unique_ips": d.unique_ips,
                    "single_attempt_ips": d.single_attempt_ips,
                    "geographic_spread": float(d.geographic_spread),
                    "recommendation": d.recommendation,
                }
                for d in detections
            ],
        }
        
        # Output report
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open('w') as f:
                json.dump(report, f, indent=2)
            logger.info("Report written to %s", output_path)
        else:
            print(json.dumps(report, indent=2))
        
        return 0
        
    except Exception as e:
        logger.error("Snowshoe report generation failed: %s", str(e), exc_info=True)
        return 2


def main(argv: Iterable[str] | None = None) -> int:
    """Main CLI entry point for analysis commands."""
    parser = argparse.ArgumentParser(
        description="Analyze Cowrie data for threat patterns",
        prog="cowrie-analyze",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available analysis commands")
    
    # Botnet coordination detection command
    botnet_parser = subparsers.add_parser(
        "botnet", 
        help="Detect coordinated botnet attacks"
    )
    botnet_parser.add_argument(
        "--window",
        type=int,
        default=24,
        help="Time window for analysis in hours (default: 24)",
    )
    botnet_parser.add_argument(
        "--sensitivity",
        type=float,
        default=0.6,
        help="Detection sensitivity threshold (0.0-1.0, default: 0.6)",
    )
    botnet_parser.add_argument(
        "--credential-threshold",
        type=int,
        default=3,
        help="Minimum IPs sharing credentials to flag (default: 3)",
    )
    botnet_parser.add_argument(
        "--command-similarity",
        type=float,
        default=0.7,
        help="Minimum command sequence similarity (0.0-1.0, default: 0.7)",
    )
    botnet_parser.add_argument(
        "--output", help="Write JSON report to file instead of stdout"
    )
    botnet_parser.add_argument(
        "--store-results", action="store_true", help="Store results in database"
    )
    botnet_parser.add_argument(
        "--db", help="Database URL or SQLite path. If omitted, reads from settings."
    )
    botnet_parser.add_argument(
        "--status-dir", help="Directory for status JSON", default=None
    )
    botnet_parser.add_argument(
        "--ingest-id", help="Explicit ingest identifier", default=None
    )
    botnet_parser.add_argument(
        "--sensor", help="Filter analysis by specific sensor", default=None
    )
    
    # Snowshoe analyze command
    snowshoe_parser = subparsers.add_parser(
        "snowshoe", 
        help="Analyze sessions for snowshoe attacks"
    )
    snowshoe_parser.add_argument(
        "--window", 
        default="24h", 
        help="Analysis window (e.g., 24h, 7d) (default: 24h)"
    )
    snowshoe_parser.add_argument(
        "--sensitivity", 
        type=float, 
        default=0.7, 
        help="Detection sensitivity threshold (0.0-1.0) (default: 0.7)"
    )
    snowshoe_parser.add_argument(
        "--sensor", 
        help="Filter by specific sensor name"
    )
    snowshoe_parser.add_argument(
        "--output", 
        help="Output file path (default: stdout)"
    )
    snowshoe_parser.add_argument(
        "--store-results", 
        action="store_true", 
        help="Store results in database"
    )
    snowshoe_parser.add_argument(
        "--db", 
        help="Database URL or SQLite path"
    )
    snowshoe_parser.add_argument(
        "--status-dir", 
        help="Directory for status JSON files"
    )
    snowshoe_parser.add_argument(
        "--ingest-id",
        help="Ingest identifier for status tracking"
    )

    # Longtail analyze command
    longtail_parser = subparsers.add_parser(
        "longtail",
        help="Analyze sessions for rare, unusual, and emerging attack patterns"
    )
    longtail_parser.add_argument(
        "--lookback-days",
        type=int,
        default=7,
        help="Number of days to look back for analysis (default: 7)"
    )
    longtail_parser.add_argument(
        "--rarity-threshold",
        type=float,
        default=0.05,
        help="Threshold for rare command detection (0.0-1.0, default: 0.05)"
    )
    longtail_parser.add_argument(
        "--sequence-window",
        type=int,
        default=5,
        help="Number of commands in sequence analysis (default: 5)"
    )
    longtail_parser.add_argument(
        "--cluster-eps",
        type=float,
        default=0.3,
        help="DBSCAN epsilon parameter for clustering (default: 0.3)"
    )
    longtail_parser.add_argument(
        "--min-cluster-size",
        type=int,
        default=5,
        help="Minimum cluster size for DBSCAN (default: 5)"
    )
    longtail_parser.add_argument(
        "--entropy-threshold",
        type=float,
        default=0.8,
        help="High entropy threshold for payload detection (default: 0.8)"
    )
    longtail_parser.add_argument(
        "--sensitivity-threshold",
        type=float,
        default=0.95,
        help="Overall detection sensitivity threshold (default: 0.95)"
    )
    longtail_parser.add_argument(
        "--sensor",
        help="Filter by specific sensor name"
    )
    longtail_parser.add_argument(
        "--output",
        help="Output file path (default: stdout)"
    )
    longtail_parser.add_argument(
        "--store-results",
        action="store_true",
        help="Store results in database"
    )
    longtail_parser.add_argument(
        "--db",
        help="Database URL or SQLite path"
    )
    longtail_parser.add_argument(
        "--status-dir",
        help="Directory for status JSON files"
    )
    longtail_parser.add_argument(
        "--ingest-id",
        help="Ingest identifier for status tracking"
    )

    # Snowshoe report command
    report_parser = subparsers.add_parser(
        "snowshoe-report", 
        help="Generate snowshoe detection reports"
    )
    report_parser.add_argument(
        "--date", 
        help="Report date (YYYY-MM-DD) (default: last 7 days)"
    )
    report_parser.add_argument(
        "--min-confidence", 
        type=float, 
        help="Minimum confidence score for detections"
    )
    report_parser.add_argument(
        "--output", 
        help="Output file path (default: stdout)"
    )
    report_parser.add_argument(
        "--db", 
        help="Database URL or SQLite path"
    )
    
    args = parser.parse_args(list(argv) if argv is not None else None)
    
    if not args.command:
        parser.print_help()
        return 1
    
    if args.command == "botnet":
        return _run_botnet_analysis(args)
    elif args.command == "snowshoe":
        return snowshoe_analyze(args)
    elif args.command == "snowshoe-report":
        return snowshoe_report(args)
    elif args.command == "longtail":
        return longtail_analyze(args)
    else:
        parser.error(f"Unknown command: {args.command}")
        return 1


def longtail_analyze(args: argparse.Namespace) -> int:
    """Run longtail analysis on Cowrie data.

    Args:
        args: Parsed command line arguments

    Returns:
        Exit code (0 for success)
    """
    try:
        # Parse lookback days
        lookback_days = args.lookback_days
        window_delta = timedelta(days=lookback_days)
        window_end = datetime.now(UTC)
        window_start = window_end - window_delta

        logger.info(
            "Starting longtail analysis: lookback=%dd, sensitivity=%.2f, sensor=%s",
            lookback_days,
            args.sensitivity_threshold,
            args.sensor or "all",
        )

        # Setup database
        settings = resolve_database_settings(args.db)
        engine = create_engine_from_settings(settings)
        apply_migrations(engine)
        session_factory = create_session_maker(engine)

        # Query sessions
        sessions = _query_sessions_for_analysis(
            session_factory, window_start, window_end, args.sensor
        )

        if not sessions:
            logger.warning("No sessions found for analysis window")
            return 1

        logger.info("Found %d sessions for analysis", len(sessions))

        # Initialize analyzer
        analyzer = LongtailAnalyzer(
            rarity_threshold=args.rarity_threshold,
            sequence_window=args.sequence_window,
            cluster_eps=args.cluster_eps,
            min_cluster_size=args.min_cluster_size,
            entropy_threshold=args.entropy_threshold,
            sensitivity_threshold=args.sensitivity_threshold,
        )

        # Perform analysis with database session
        analysis_start_time = time.perf_counter()
        with start_span(
            "cowrie.longtail.analyze",
            {
                "lookback_days": lookback_days,
                "session_count": len(sessions),
                "sensor": args.sensor or "all",
            },
        ):
            # Create a database session for command extraction
            with session_factory() as db_session:
                result = analyzer.analyze(sessions, lookback_days, db_session)

        analysis_duration = time.perf_counter() - analysis_start_time

        # Store results if requested
        if args.store_results:
            _store_longtail_result(session_factory, result, window_start, window_end)

        # Output results
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(result, f, indent=2, default=str)
        else:
            print(json.dumps(result, indent=2, default=str))

        return 0

    except Exception as e:
        logger.error(f"Longtail analysis failed: {e}", exc_info=True)
        return 2


def _store_longtail_result(
    session_factory,
    result: LongtailAnalysisResult,
    window_start: datetime,
    window_end: datetime
) -> None:
    """Store longtail analysis results in database.

    Args:
        session_factory: Database session factory
        result: Analysis results to store
        window_start: Analysis window start time
        window_end: Analysis window end time
    """
    try:
        with session_factory() as session:
            # TODO: Implement when we have the LongtailAnalysis model
            logger.info("Longtail result storage not yet implemented")
    except Exception as e:
        logger.error(f"Failed to store longtail results: {e}")


# Import logger at module level
import logging
logger = logging.getLogger(__name__)


def _run_botnet_analysis(args) -> int:
    """Run botnet coordination analysis."""
    try:
        # Resolve database settings
        settings = resolve_database_settings(args.db)
        engine = create_engine_from_settings(settings)
        apply_migrations(engine)
        session_factory = create_session_maker(engine)
        
        # Parse time window
        window_hours = int(args.window)
        window_delta = timedelta(hours=window_hours)
        window_end = datetime.now(UTC)
        window_start = window_end - window_delta
        
        # Fetch sessions and raw events for analysis
        with session_factory() as session:
            # Get session IDs first
            session_query = session.query(SessionSummary).filter(
                and_(
                    SessionSummary.first_event_at >= window_start,
                    SessionSummary.first_event_at <= window_end,
                )
            )
            
            if args.sensor:
                session_query = session_query.filter(SessionSummary.source_files.contains([args.sensor]))
            
            sessions = session_query.all()
            
            # Get raw events for credential and command extraction
            session_ids = [s.session_id for s in sessions]
            raw_events = []
            if session_ids:
                raw_events = session.query(RawEvent).filter(
                    and_(
                        RawEvent.session_id.in_(session_ids),
                        RawEvent.event_type.in_(["cowrie.login.success", "cowrie.command.input"]),
                    )
                ).all()
        
        if not sessions:
            logger.warning("No sessions found for analysis window")
            return 1
        
        logger.info("Found %d sessions and %d raw events for botnet analysis", len(sessions), len(raw_events))
        
        # Initialize detector
        detector = BotnetCoordinatorDetector(
            credential_reuse_threshold=args.credential_threshold,
            command_similarity_threshold=args.command_similarity,
            sensitivity_threshold=args.sensitivity,
        )
        
        # Perform analysis
        analysis_start_time = time.perf_counter()
        with start_span(
            "cowrie.botnet.analyze",
            {
                "window_hours": window_delta.total_seconds() / 3600,
                "session_count": len(sessions),
                "sensor": args.sensor or "all",
            },
        ):
            result = detector.detect(sessions, window_delta.total_seconds() / 3600, raw_events=raw_events)
        
        analysis_duration = time.perf_counter() - analysis_start_time
        
        # Store results in database if requested
        if args.store_results:
            _store_botnet_detection_result(session_factory, result, window_start, window_end)
        
        # Output results
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w") as f:
                json.dump(result, f, indent=2)
            logger.info("Results written to %s", output_path)
        else:
            print(json.dumps(result, indent=2))
        
        # Emit metrics
        if args.status_dir:
            analysis_id = args.ingest_id or f"botnet-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            window_hours = window_delta.total_seconds() / 3600
            
            # Create comprehensive metrics
            metrics = create_snowshoe_metrics_from_detection(
                detection_result=result,
                analysis_duration=analysis_duration,
                analysis_id=analysis_id,
                window_hours=window_hours,
            )
            
            emitter = StatusEmitter("botnet-analysis", status_dir=args.status_dir)
            emitter.record_metrics(metrics)
        
        return 0 if result["is_likely_botnet"] else 1
        
    except Exception as e:
        logger.error("Botnet analysis failed: %s", str(e), exc_info=True)
        return 1


def _store_botnet_detection_result(
    session_factory, 
    result: Dict[str, Any], 
    window_start: datetime, 
    window_end: datetime,
) -> None:
    """Store botnet detection results in database."""
    try:
        with session_factory() as session:
            # Create a BotnetDetection record (we'll need to add this model)
            # For now, we'll use the existing SnowshoeDetection model
            detection = SnowshoeDetection(
                window_start=window_start,
                window_end=window_end,
                confidence_score=str(result["coordination_score"]),
                unique_ips=result["analysis_metadata"]["unique_ips"],
                single_attempt_ips=len(result["credential_reuse_ips"]),
                geographic_spread=str(result["geographic_clustering"]),
                indicators=result["indicators"],
                is_likely_snowshoe=result["is_likely_botnet"],  # Reusing field
                coordinated_timing=result["coordinated_timing"],
                recommendation=result["recommendation"],
                analysis_metadata=result["analysis_metadata"],
            )
            
            session.add(detection)
            session.commit()
            logger.info("Botnet detection results stored in database")
            
    except Exception as e:
        logger.error("Failed to store botnet detection results: %s", str(e))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
