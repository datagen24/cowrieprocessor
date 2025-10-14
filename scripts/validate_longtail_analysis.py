#!/usr/bin/env python3
"""Comprehensive validation script for longtail analysis implementation.

This script tests the complete longtail analysis pipeline against a real database
to ensure all components work correctly in production.

Usage:
    uv run python scripts/validate_longtail_analysis.py --db-url postgresql://user:pass@localhost/cowrie
    uv run python scripts/validate_longtail_analysis.py --db-url sqlite:///test.db
"""

from __future__ import annotations

# Limit OpenMP threads to prevent resource issues - MUST be set before importing any libraries
import os

os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['VECLIB_MAXIMUM_THREADS'] = '1'
os.environ['NUMEXPR_NUM_THREADS'] = '1'

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict

from cowrieprocessor.db.engine import create_engine_from_settings, detect_database_features
from cowrieprocessor.db.migrations import apply_migrations
from cowrieprocessor.settings import DatabaseSettings
from cowrieprocessor.threat_detection.longtail import LongtailAnalyzer

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def validate_database_setup(db_url: str) -> Dict[str, Any]:
    """Validate database setup and configuration."""
    logger.info(f"Validating database setup: {db_url}")

    try:
        # Create database settings object
        db_settings = DatabaseSettings(url=db_url)

        # Create engine and detect features
        engine = create_engine_from_settings(db_settings)
        features = detect_database_features(engine)

        logger.info(f"Database type: {features['database_type']}")
        logger.info(f"Database version: {features['version']}")
        logger.info(f"pgvector available: {features['pgvector']}")
        logger.info(f"Vector longtail support: {features['vector_longtail']}")

        # Apply migrations
        logger.info("Applying database migrations...")
        apply_migrations(engine)

        return {
            "success": True,
            "database_type": features["database_type"],
            "pgvector_available": features["pgvector"],
            "vector_longtail": features["vector_longtail"],
            "features": features,
        }

    except Exception as e:
        logger.error(f"Database setup validation failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }


def test_command_extraction(db_url: str, session_factory) -> Dict[str, Any]:
    """Test command extraction from real database."""
    logger.info("Testing command extraction from database...")

    try:
        # Create analyzer
        analyzer = LongtailAnalyzer(session_factory)

        # Test with session factory
        with session_factory() as session:
            # Get some session IDs to test with
            from cowrieprocessor.db.models import SessionSummary

            recent_sessions = session.query(SessionSummary).limit(5).all()
            session_ids = [s.session_id for s in recent_sessions]

            if not session_ids:
                return {
                    "success": False,
                    "error": "No sessions found in database for testing",
                    "sessions_tested": 0,
                }

            logger.info(f"Testing command extraction for {len(session_ids)} sessions")

            # Test command extraction
            commands_by_session = analyzer._extract_commands_for_sessions(session_ids)

            total_commands = sum(len(cmds) for cmds in commands_by_session.values())
            sessions_with_commands = len([s for s, cmds in commands_by_session.items() if cmds])

            logger.info(f"Extracted {total_commands} commands from {sessions_with_commands} sessions")

            return {
                "success": True,
                "sessions_tested": len(session_ids),
                "sessions_with_commands": sessions_with_commands,
                "total_commands": total_commands,
                "avg_commands_per_session": total_commands / len(session_ids) if session_ids else 0,
            }

    except Exception as e:
        logger.error(f"Command extraction test failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }


def test_longtail_analysis(db_url: str) -> Dict[str, Any]:
    """Test complete longtail analysis execution."""
    logger.info("Testing complete longtail analysis execution...")

    try:
        # Setup database
        from cowrieprocessor.db import create_session_maker

        db_settings = DatabaseSettings(url=db_url)
        engine = create_engine_from_settings(db_settings)
        session_factory = create_session_maker(engine)

        # Get sessions for analysis
        from cowrieprocessor.db.models import SessionSummary

        with session_factory() as session:
            # Get sessions from last 7 days
            cutoff_date = datetime.now(UTC) - timedelta(days=7)
            sessions = (
                session.query(SessionSummary).filter(SessionSummary.first_event_at >= cutoff_date).limit(10).all()
            )

            if not sessions:
                return {
                    "success": False,
                    "error": "No recent sessions found for analysis",
                    "sessions_available": 0,
                }

            logger.info(f"Found {len(sessions)} sessions for analysis")

        # Create analyzer
        analyzer = LongtailAnalyzer(session_factory)

        # Run analysis
        logger.info("Running longtail analysis...")
        start_time = time.perf_counter()

        result = analyzer.analyze(sessions, lookback_days=7)

        analysis_time = time.perf_counter() - start_time

        logger.info(f"Analysis completed in {analysis_time:.2f}s")

        # Validate results
        validation = {
            "success": True,
            "sessions_analyzed": result.total_sessions_analyzed,
            "events_analyzed": result.total_events_analyzed,
            "analysis_time": analysis_time,
            "memory_usage_mb": result.memory_usage_mb,
            "rare_commands": result.rare_command_count,
            "anomalous_sequences": result.anomalous_sequence_count,
            "outlier_sessions": result.outlier_session_count,
        }

        # Log detailed results
        logger.info(f"Analysis Results: {validation}")

        return validation

    except Exception as e:
        logger.error(f"Longtail analysis test failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }


def test_dimension_benchmarking(db_url: str) -> Dict[str, Any]:
    """Test dimension benchmarking functionality."""
    logger.info("Testing dimension benchmarking...")

    try:
        # Setup database
        from cowrieprocessor.db import create_session_maker

        db_settings = DatabaseSettings(url=db_url)
        engine = create_engine_from_settings(db_settings)
        session_factory = create_session_maker(engine)

        # Get test sessions
        from cowrieprocessor.db.models import SessionSummary

        with session_factory() as session:
            sessions = session.query(SessionSummary).limit(5).all()

            if not sessions:
                return {
                    "success": False,
                    "error": "No sessions available for benchmarking",
                }

        # Create analyzer
        analyzer = LongtailAnalyzer(session_factory)

        # Test dimension benchmarking
        logger.info("Running dimension benchmarking...")
        benchmark_results = analyzer.benchmark_vector_dimensions(sessions, [32, 64])

        logger.info(f"Benchmark results: {benchmark_results}")

        return {
            "success": True,
            "dimensions_tested": list(benchmark_results.keys()),
            "results": benchmark_results,
        }

    except Exception as e:
        logger.error(f"Dimension benchmarking test failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }


def validate_cli_integration() -> Dict[str, Any]:
    """Test CLI integration."""
    logger.info("Testing CLI integration...")

    try:
        # Test that CLI command exists and shows help
        import subprocess

        result = subprocess.run(
            [sys.executable, "-m", "cowrieprocessor.cli.analyze", "longtail", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )

        if result.returncode == 0 and "longtail" in result.stdout:
            logger.info("CLI command longtail available and functional")
            return {"success": True, "cli_available": True}
        else:
            logger.error(f"CLI command not available: {result.stderr}")
            return {"success": False, "error": "CLI command not available"}

    except Exception as e:
        logger.error(f"CLI integration test failed: {e}")
        return {"success": False, "error": str(e)}


def run_comprehensive_validation(db_url: str) -> Dict[str, Any]:
    """Run comprehensive validation of longtail analysis implementation."""
    logger.info("Starting comprehensive longtail analysis validation...")
    logger.info("=" * 60)

    results = {
        "timestamp": datetime.now(UTC).isoformat(),
        "database_url": db_url,
        "tests": {},
    }

    # 1. Database setup validation
    logger.info("1. Validating database setup...")
    db_validation = validate_database_setup(db_url)
    results["tests"]["database_setup"] = db_validation

    if not db_validation["success"]:
        logger.error("Database setup validation failed - cannot continue")
        return results

    # 2. CLI integration validation
    logger.info("2. Validating CLI integration...")
    cli_validation = validate_cli_integration()
    results["tests"]["cli_integration"] = cli_validation

    # 3. Command extraction validation
    logger.info("3. Testing command extraction...")
    from cowrieprocessor.db import create_session_maker

    db_settings = DatabaseSettings(url=db_url)
    engine = create_engine_from_settings(db_settings)
    session_factory = create_session_maker(engine)

    extraction_validation = test_command_extraction(db_url, session_factory)
    results["tests"]["command_extraction"] = extraction_validation

    # 4. Longtail analysis validation
    logger.info("4. Testing longtail analysis execution...")
    analysis_validation = test_longtail_analysis(db_url)
    results["tests"]["longtail_analysis"] = analysis_validation

    # 5. Dimension benchmarking validation
    logger.info("5. Testing dimension benchmarking...")
    benchmarking_validation = test_dimension_benchmarking(db_url)
    results["tests"]["dimension_benchmarking"] = benchmarking_validation

    # Summary
    successful_tests = sum(1 for test in results["tests"].values() if test.get("success", False))
    total_tests = len(results["tests"])

    results["summary"] = {
        "total_tests": total_tests,
        "successful_tests": successful_tests,
        "success_rate": successful_tests / total_tests if total_tests > 0 else 0,
        "overall_success": successful_tests == total_tests,
    }

    logger.info("=" * 60)
    logger.info("VALIDATION COMPLETE")
    logger.info(f"Tests passed: {successful_tests}/{total_tests}")
    logger.info(f"Success rate: {results['summary']['success_rate']:.1%}")
    logger.info(f"Overall status: {'✅ PASS' if results['summary']['overall_success'] else '❌ FAIL'}")

    return results


def main() -> int:
    """Main validation function."""
    parser = argparse.ArgumentParser(description="Validate longtail analysis implementation against real database")
    parser.add_argument(
        "--db-url",
        required=True,
        help="Database URL (e.g., postgresql://user:pass@localhost/cowrie or sqlite:///path.db)",
    )
    parser.add_argument("--output", help="Output file for validation results (default: stdout)")

    args = parser.parse_args()

    # Run validation
    results = run_comprehensive_validation(args.db_url)

    # Output results
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"Results written to {args.output}")
    else:
        print(json.dumps(results, indent=2, default=str))

    # Return appropriate exit code
    if "summary" in results and "overall_success" in results["summary"]:
        return 0 if results["summary"]["overall_success"] else 1
    else:
        # If no summary was created, it means the validation failed early
        return 1


if __name__ == "__main__":
    sys.exit(main())
