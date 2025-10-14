"""Analysis CLI for Cowrie Processor threat detection."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import and_, func

from ..db import apply_migrations, create_engine_from_settings, create_session_maker
from ..db.models import LongtailAnalysis, LongtailDetection, RawEvent, SessionSummary, SnowshoeDetection
from ..status_emitter import StatusEmitter
from ..telemetry import start_span
from ..threat_detection import (
    BotnetCoordinatorDetector,
    LongtailAnalysisResult,
    LongtailAnalyzer,
    SnowshoeDetector,
    create_snowshoe_metrics_from_detection,
)
from .db_config import resolve_database_settings

logger = logging.getLogger(__name__)


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
                "avg_confidence": (
                    sum(float(d.confidence_score) for d in detections) / len(detections)
                    if detections else 0
                ),
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
        "--batch-size",
        type=int,
        default=100,
        help="Number of sessions to process in each batch (default: 100)"
    )
    longtail_parser.add_argument(
        "--memory-limit-gb",
        type=float,
        help="Memory limit in GB for analysis (default: auto-detect based on system memory)"
    )
    longtail_parser.add_argument(
        "--detailed",
        action="store_true",
        help="Show detailed JSON output instead of summary report"
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
    # Password intelligence flags
    longtail_parser.add_argument(
        "--password-intelligence",
        action="store_true",
        help="Enable password intelligence indicator in longtail analysis",
    )
    longtail_parser.add_argument(
        "--password-enrichment",
        action="store_true",
        help="Opportunistically enrich up to a limited number of sessions with HIBP",
    )
    longtail_parser.add_argument(
        "--max-enrichment-sessions",
        type=int,
        default=50,
        help="Maximum sessions to enrich when --password-enrichment is enabled (default: 50)",
    )
    longtail_parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Cache directory for HIBP prefix responses (default: ~/.cache/cowrieprocessor)",
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

        # Derive vocabulary path from configuration
        vocab_path = _derive_vocab_path_from_config()
        
        # Load memory configuration from sensors.toml
        memory_config = _load_memory_config_from_sensors()
        
        # Use CLI override if provided, otherwise use config value
        memory_limit_gb = args.memory_limit_gb or memory_config["memory_limit_gb"]
        
        # Initialize analyzer with database access and vocabulary management
        analyzer = LongtailAnalyzer(
            session_factory,
            vocab_path=vocab_path,
            rarity_threshold=args.rarity_threshold,
            sequence_window=args.sequence_window,
            cluster_eps=args.cluster_eps,
            min_cluster_size=args.min_cluster_size,
            entropy_threshold=args.entropy_threshold,
            sensitivity_threshold=args.sensitivity_threshold,
            batch_size=args.batch_size,
            memory_limit_gb=memory_limit_gb,
            memory_warning_threshold=memory_config["memory_warning_threshold"],
            enable_password_intelligence=bool(args.password_intelligence),
            enable_password_enrichment=bool(args.password_enrichment),
            max_enrichment_sessions=int(args.max_enrichment_sessions),
            cache_dir=args.cache_dir,
        )

        # Perform analysis
        with start_span(
            "cowrie.longtail.analyze",
            {
                "lookback_days": lookback_days,
                "session_count": len(sessions),
                "sensor": args.sensor or "all",
            },
        ):
            result = analyzer.analyze(sessions, lookback_days)

        # Store results if requested
        if args.store_results:
            _store_longtail_result(session_factory, result, window_start, window_end)

        # Output results
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(result, f, indent=2, default=str)
        elif args.detailed:
            # Print detailed JSON output
            print(json.dumps(result, indent=2, default=str))
        else:
            # Print human-readable summary
            _print_longtail_summary(result)

        return 0

    except Exception as e:
        logger.error(f"Longtail analysis failed: {e}", exc_info=True)
        return 2


def _derive_vocab_path_from_config() -> Optional[Path]:
    """Derive vocabulary path from sensors.toml configuration or use sensible default.
    
    Returns:
        Path to vocabulary file, or None to disable persistent vocabulary
    """
    sensors_file = Path("sensors.toml")
    if not sensors_file.exists():
        # No config file, use default cache location
        default_cache = Path.home() / ".cache" / "cowrieprocessor"
        vocab_path = default_cache / "vocab.pkl"
        logger.info(f"No sensors.toml found, using default vocab path: {vocab_path}")
        return vocab_path
    
    try:
        # Try tomllib first (Python 3.11+)
        try:
            import tomllib
        except ImportError:
            # Fall back to tomli for older Python versions
            import tomli as tomllib

        with sensors_file.open("rb") as handle:
            data = tomllib.load(handle)

        # Look for data path patterns in sensor configurations
        sensors = data.get("sensor", [])
        for sensor in sensors:
            logpath = sensor.get("logpath", "")
            if logpath:
                # Extract base data path and derive vocab path
                # e.g., "/mnt/dshield/aws-eastus-dshield/NSM/cowrie" -> "/mnt/dshield/data/cache"
                logpath_obj = Path(logpath)
                if logpath_obj.is_absolute():
                    # Go up to find base data directory
                    base_path = logpath_obj.parent.parent.parent  # Go up 3 levels
                    vocab_path = base_path / "data" / "cache" / "vocab.pkl"
                    logger.info(f"Derived vocab path from config: {vocab_path}")
                    return vocab_path
                    
    except Exception as e:
        logger.warning(f"Could not derive vocab path from {sensors_file}: {e}")
    
    # Fall back to default cache path
    default_cache = Path.home() / ".cache" / "cowrieprocessor"
    vocab_path = default_cache / "vocab.pkl"
    logger.info(f"Using default vocab path: {vocab_path}")
    return vocab_path


def _load_memory_config_from_sensors() -> Dict[str, float]:
    """Load memory configuration from sensors.toml.
    
    Returns:
        Dictionary with memory_limit_gb and memory_warning_threshold
    """
    sensors_file = Path("sensors.toml")
    if not sensors_file.exists():
        logger.info("No sensors.toml found, using default memory configuration")
        return {
            "memory_limit_gb": None,  # Will trigger auto-detection
            "memory_warning_threshold": 0.75
        }
    
    try:
        # Try tomllib first (Python 3.11+)
        try:
            import tomllib
        except ImportError:
            # Fall back to tomli for older Python versions
            import tomli as tomllib

        with sensors_file.open("rb") as handle:
            data = tomllib.load(handle)

        # Get global configuration
        global_config = data.get("global", {})
        
        memory_config = {
            "memory_limit_gb": global_config.get("memory_limit_gb"),
            "memory_warning_threshold": global_config.get("memory_warning_threshold", 0.75)
        }
        
        if memory_config["memory_limit_gb"]:
            logger.info(
                f"Loaded memory configuration from sensors.toml: "
                f"{memory_config['memory_limit_gb']}GB limit, "
                f"{memory_config['memory_warning_threshold']*100:.0f}% warning threshold"
            )
        else:
            logger.info("No memory_limit_gb in sensors.toml, will use auto-detection")
            
        return memory_config
                    
    except Exception as e:
        logger.warning(f"Could not load memory config from {sensors_file}: {e}")
        return {
            "memory_limit_gb": None,  # Will trigger auto-detection
            "memory_warning_threshold": 0.75
        }


def _print_longtail_summary(result: LongtailAnalysisResult) -> None:
    """Print a human-readable summary of longtail analysis results.
    
    Args:
        result: LongtailAnalysisResult object to summarize
    """
    print("=" * 80)
    print("LONGTAIL THREAT ANALYSIS REPORT")
    print("=" * 80)
    
    # Analysis summary
    print("\n📊 ANALYSIS SUMMARY")
    print(f"   Sessions analyzed: {result.total_sessions_analyzed:,}")
    print(f"   Events analyzed: {result.total_events_analyzed:,}")
    print(f"   Analysis duration: {result.analysis_duration_seconds:.2f}s")
    print(f"   Memory usage: {result.memory_usage_mb:.1f} MB")
    
    # Detection counts
    print("\n🎯 THREAT DETECTIONS")
    print(f"   Rare commands: {result.rare_command_count}")
    print(f"   Anomalous sequences: {result.anomalous_sequence_count}")
    print(f"   Outlier sessions: {result.outlier_session_count}")
    print(f"   Emerging patterns: {result.emerging_pattern_count}")
    print(f"   High entropy payloads: {result.high_entropy_payload_count}")
    
    # Top rare commands (most suspicious)
    if result.rare_commands:
        print("\n🚨 TOP RARE COMMANDS (Most Suspicious)")
        # Sort by rarity score (lower = more rare)
        sorted_commands = sorted(result.rare_commands, key=lambda x: x['rarity_score'])[:10]
        
        for i, cmd in enumerate(sorted_commands, 1):
            command = cmd['command']
            frequency = cmd['frequency']
            rarity_score = cmd['rarity_score']
            session_count = cmd.get('session_count', 0)
            
            print(f"   {i:2d}. [{frequency:3d}x] {command}")
            print(f"       Rarity: {rarity_score:.6f} | Sessions: {session_count}")
            
            # Show session details for this command
            sessions = cmd.get('sessions', [])
            if sessions:
                print("       Sessions:")
                for j, session in enumerate(sessions[:3]):  # Show first 3 sessions
                    src_ip = session.get('src_ip', 'Unknown')
                    session_id = session.get('session_id', 'Unknown')
                    timestamp = session.get('timestamp', 'Unknown')
                    if isinstance(timestamp, datetime):
                        timestamp = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                    print(f"         {j+1}. {src_ip} ({session_id[:8]}...) - {timestamp}")
                if len(sessions) > 3:
                    print(f"         ... and {len(sessions) - 3} more sessions")
            print()
    
    # Top frequent rare commands (most common among rare)
    if result.rare_commands:
        print("\n📈 MOST FREQUENT RARE COMMANDS")
        # Sort by frequency (higher = more frequent)
        sorted_by_freq = sorted(result.rare_commands, key=lambda x: x['frequency'], reverse=True)[:5]
        
        for i, cmd in enumerate(sorted_by_freq, 1):
            command = cmd['command']
            frequency = cmd['frequency']
            
            print(f"   {i:2d}. [{frequency:3d}x] {command}")
    
    # Anomalous sequences
    if result.anomalous_sequences:
        print("\n🔍 ANOMALOUS COMMAND SEQUENCES")
        for i, seq in enumerate(result.anomalous_sequences[:5], 1):
            sequence = seq.get('sequence', 'Unknown')
            if len(sequence) > 80:
                sequence = sequence[:77] + "..."
            print(f"   {i:2d}. {sequence}")
    
    # Outlier sessions
    if result.outlier_sessions:
        print("\n👤 OUTLIER SESSIONS")
        for i, session in enumerate(result.outlier_sessions[:5], 1):
            session_id = session.get('session_id', 'Unknown')
            outlier_score = session.get('outlier_score', 0.0)
            print(f"   {i:2d}. Session: {session_id} (Score: {outlier_score:.3f})")
    
    # Emerging patterns
    if result.emerging_patterns:
        print("\n🌱 EMERGING PATTERNS")
        for i, pattern in enumerate(result.emerging_patterns[:5], 1):
            pattern_text = pattern.get('pattern', 'Unknown')
            if len(pattern_text) > 80:
                pattern_text = pattern_text[:77] + "..."
            print(f"   {i:2d}. {pattern_text}")
    
    # High entropy payloads
    if result.high_entropy_payloads:
        print("\n🔐 HIGH ENTROPY PAYLOADS")
        for i, payload in enumerate(result.high_entropy_payloads[:5], 1):
            payload_text = payload.get('payload', 'Unknown')
            entropy = payload.get('entropy', 0.0)
            if len(payload_text) > 60:
                payload_text = payload_text[:57] + "..."
            print(f"   {i:2d}. Entropy: {entropy:.3f} - {payload_text}")
    
    # Statistical summary
    if result.statistical_summary:
        stats = result.statistical_summary
        print("\n📈 STATISTICAL SUMMARY")
        
        if 'data_characteristics' in stats:
            data = stats['data_characteristics']
            print(f"   Total commands: {data.get('total_commands', 0):,}")
            print(f"   Unique commands: {data.get('unique_commands', 0):,}")
            print(f"   Command sequences: {data.get('command_sequences', 0):,}")
        
        if 'performance_metrics' in stats:
            perf = stats['performance_metrics']
            events_per_sec = perf.get('events_per_second', 0)
            if events_per_sec > 0:
                print(f"   Processing rate: {events_per_sec:.0f} events/sec")
    
    print("\n" + "=" * 80)
    print("Analysis complete. Use --output FILE to save detailed JSON results.")
    print("=" * 80)


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
            # Create main analysis record
            analysis_record = LongtailAnalysis(
                window_start=window_start,
                window_end=window_end,
                lookback_days=30,  # Default, could be passed as parameter
                confidence_score=result.statistical_summary.get("confidence_score", 0.0),
                total_events_analyzed=result.total_events_analyzed,
                rare_command_count=result.rare_command_count,
                anomalous_sequence_count=result.anomalous_sequence_count,
                outlier_session_count=result.outlier_session_count,
                emerging_pattern_count=result.emerging_pattern_count,
                high_entropy_payload_count=result.high_entropy_payload_count,
                analysis_results={
                    "rare_commands": result.rare_commands,
                    "anomalous_sequences": result.anomalous_sequences,
                    "outlier_sessions": result.outlier_sessions,
                    "emerging_patterns": result.emerging_patterns,
                    "high_entropy_payloads": result.high_entropy_payloads,
                },
                statistical_summary=result.statistical_summary,
                analysis_duration_seconds=result.analysis_duration_seconds,
                memory_usage_mb=getattr(result, 'memory_usage_mb', None),
                data_quality_score=result.statistical_summary.get("data_quality_score"),
                enrichment_coverage=result.statistical_summary.get("enrichment_coverage"),
            )
            
            session.add(analysis_record)
            session.flush()  # Get the ID
            
            # Store individual detections
            for detection in result.rare_commands:
                detection_record = LongtailDetection(
                    analysis_id=analysis_record.id,
                    detection_type="rare_command",
                    session_id=detection.get("session_id"),
                    detection_data=detection,
                    confidence_score=detection.get("confidence_score", 0.0),
                    severity_score=detection.get("severity_score", 0.0),
                    timestamp=detection.get("timestamp", window_start),
                    source_ip=detection.get("source_ip"),
                )
                session.add(detection_record)
            
            session.commit()
            logger.info(f"Stored longtail analysis results with {len(result.rare_commands)} detections")
            
    except Exception as e:
        logger.error(f"Failed to store longtail results: {e}")
        raise


# Logger is already defined at module level above


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
