#!/usr/bin/env python3
"""Test longtail analysis against a real database.

This script provides a simple way to test the longtail analysis implementation
against a populated Cowrie database.

Usage:
    uv run python scripts/test_longtail_with_database.py --db-url postgresql://user:pass@localhost/cowrie
    uv run python scripts/test_longtail_with_database.py --db-url sqlite:///cowrie.db
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from cowrieprocessor.db import apply_migrations, create_engine_from_settings, create_session_maker
from cowrieprocessor.db.models import SessionSummary
from cowrieprocessor.settings import DatabaseSettings
from cowrieprocessor.threat_detection.longtail import LongtailAnalyzer

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_database_connectivity(db_url: str) -> bool:
    """Test basic database connectivity."""
    try:
        logger.info(f"Testing database connectivity: {db_url}")
        db_settings = DatabaseSettings(url=db_url)
        engine = create_engine_from_settings(db_settings)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            logger.info("✅ Database connectivity confirmed")
            return True
    except Exception as e:
        logger.error(f"❌ Database connectivity failed: {e}")
        return False


def get_test_sessions(db_url: str, limit: int = 10) -> list[SessionSummary] | None:
    """Get test sessions from database."""
    try:
        logger.info(f"Fetching {limit} test sessions from database...")
        db_settings = DatabaseSettings(url=db_url)
        engine = create_engine_from_settings(db_settings)
        apply_migrations(engine)
        session_factory = create_session_maker(engine)

        with session_factory() as session:
            # Get sessions from last 30 days
            cutoff_date = datetime.now(UTC) - timedelta(days=30)
            sessions = (
                session.query(SessionSummary).filter(SessionSummary.first_event_at >= cutoff_date).limit(limit).all()
            )

            logger.info(f"✅ Retrieved {len(sessions)} sessions for testing")
            return sessions

    except Exception as e:
        logger.error(f"❌ Failed to fetch test sessions: {e}")
        return None


def run_longtail_analysis_test(db_url: str) -> dict[str, Any]:
    """Run longtail analysis test against database."""
    logger.info("Running longtail analysis test...")

    # Get test sessions
    sessions = get_test_sessions(db_url, limit=5)
    if not sessions:
        return {"success": False, "error": "No test sessions available"}

    # Setup database
    db_settings = DatabaseSettings(url=db_url)
    engine = create_engine_from_settings(db_settings)
    session_factory = create_session_maker(engine)

    # Create analyzer
    analyzer = LongtailAnalyzer(session_factory)

    # Run analysis
    logger.info(f"Analyzing {len(sessions)} sessions...")
    result = analyzer.analyze(sessions, lookback_days=7)

    # Return results
    return {
        "success": True,
        "sessions_analyzed": result.total_sessions_analyzed,
        "events_analyzed": result.total_events_analyzed,
        "rare_commands": result.rare_command_count,
        "anomalous_sequences": result.anomalous_sequence_count,
        "outlier_sessions": result.outlier_session_count,
        "analysis_time": result.analysis_duration_seconds,
        "memory_usage_mb": result.memory_usage_mb,
        "results": result.statistical_summary,
    }


def main() -> int:
    """Main test function."""
    parser = argparse.ArgumentParser(description="Test longtail analysis against real database")
    parser.add_argument("--db-url", required=True, help="Database URL (e.g., postgresql://user:pass@localhost/cowrie)")
    parser.add_argument("--output", help="Output file for test results (default: stdout)")

    args = parser.parse_args()

    logger.info("🚀 Starting longtail analysis database test...")
    logger.info("=" * 60)

    # Test database connectivity
    if not test_database_connectivity(args.db_url):
        logger.error("Cannot proceed without database connectivity")
        return 1

    # Run longtail analysis test
    results = run_longtail_analysis_test(args.db_url)

    # Output results
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"Results written to {args.output}")
    else:
        print(json.dumps(results, indent=2, default=str))

    # Return appropriate exit code
    return 0 if results.get("success", False) else 1


if __name__ == "__main__":
    sys.exit(main())
