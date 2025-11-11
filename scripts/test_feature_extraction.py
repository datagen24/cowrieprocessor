#!/usr/bin/env python3
"""Test feature extraction robustness on 50+ real sessions.

This script validates that feature extraction works correctly across edge cases
and real-world data. It tests extraction on minimum 50 sessions from the database
covering various edge cases like missing data, incomplete enrichment, etc.

Issue: #57 - Feature Extraction Robustness Testing
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import func
from sqlalchemy.orm import Session

from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.db.models import SessionSummary
from cowrieprocessor.features import ProviderClassifier, aggregate_features
from cowrieprocessor.settings import load_database_settings


def _load_sensors_config() -> dict[str, str] | None:
    """Load database configuration from sensors.toml if available."""
    # Try config/ directory first, then fall back to current directory
    sensors_file = Path("config/sensors.toml")
    if not sensors_file.exists():
        sensors_file = Path("sensors.toml")
    if not sensors_file.exists():
        return None

    try:
        # Try tomllib first (Python 3.11+)
        try:
            import tomllib
        except ImportError:
            # Fall back to tomli for older Python versions
            import tomli as tomllib  # type: ignore[no-redef]

        with sensors_file.open("rb") as handle:
            data = tomllib.load(handle)

        # Check for global database configuration
        global_config = data.get("global", {})
        db_url = global_config.get("db")
        if db_url:
            return {"url": db_url}

    except Exception:
        # If sensors.toml doesn't exist or can't be parsed, return None
        pass

    return None


@dataclass
class ExtractionResult:
    """Result of a feature extraction test.

    Attributes:
        session_id: Session identifier
        category: Edge case category tested
        success: Whether extraction succeeded
        extraction_time_ms: Time taken for extraction in milliseconds
        features: Extracted feature dictionary (None if failed)
        error: Error message if extraction failed
        total_commands: Number of commands in session
        auth_attempts: Number of authentication attempts
        enrichment_status: Status of enrichment data
    """

    session_id: str
    category: str
    success: bool
    extraction_time_ms: float
    features: dict[str, Any] | None = None
    error: str | None = None
    total_commands: int = 0
    auth_attempts: int = 0
    enrichment_status: str = "unknown"


@dataclass
class CategoryStats:
    """Statistics for a test category.

    Attributes:
        category: Category name
        total: Total sessions tested
        success: Successful extractions
        failed: Failed extractions
        avg_time_ms: Average extraction time
        min_time_ms: Minimum extraction time
        max_time_ms: Maximum extraction time
        failures: List of failed extraction results
    """

    category: str
    total: int = 0
    success: int = 0
    failed: int = 0
    avg_time_ms: float = 0.0
    min_time_ms: float = float("inf")
    max_time_ms: float = 0.0
    failures: list[ExtractionResult] = field(default_factory=list)


def query_edge_case_sessions(db: Session) -> dict[str, list[SessionSummary]]:
    """Query database for edge case sessions.

    Retrieves sessions covering various edge cases:
    - Sessions with no commands
    - Sessions with many commands (>100)
    - Sessions with no password data (auth_attempts=0)
    - Sessions with incomplete enrichment
    - Sessions spanning multiple days
    - Single-IP sessions

    Args:
        db: SQLAlchemy database session

    Returns:
        Dictionary mapping category names to session lists
    """
    edge_cases: dict[str, list[SessionSummary]] = {}

    # Category 1: No commands (10 sessions)
    edge_cases["no_commands"] = db.query(SessionSummary).filter(SessionSummary.command_count == 0).limit(10).all()

    # Category 2: Many commands (>100, 10 sessions)
    edge_cases["many_commands"] = db.query(SessionSummary).filter(SessionSummary.command_count > 100).limit(10).all()

    # Category 3: No password data (10 sessions)
    edge_cases["no_passwords"] = db.query(SessionSummary).filter(SessionSummary.login_attempts == 0).limit(10).all()

    # Category 4: Incomplete enrichment (10 sessions)
    # Sessions where enrichment field is null or empty
    edge_cases["incomplete_enrichment"] = (
        db.query(SessionSummary)
        .filter((SessionSummary.enrichment.is_(None)) | (SessionSummary.enrichment == {}))
        .limit(10)
        .all()
    )

    # Category 5: Multi-day sessions (10 sessions)
    # Sessions where last_event_at - first_event_at > 1 day
    edge_cases["multi_day"] = (
        db.query(SessionSummary)
        .filter(func.date(SessionSummary.last_event_at) != func.date(SessionSummary.first_event_at))
        .limit(10)
        .all()
    )

    # Category 6: Recent sessions with full enrichment (10 sessions)
    # For baseline comparison
    edge_cases["baseline"] = (
        db.query(SessionSummary)
        .filter(
            SessionSummary.enrichment.isnot(None),
            SessionSummary.command_count > 0,
            SessionSummary.login_attempts > 0,
        )
        .order_by(SessionSummary.first_event_at.desc())
        .limit(10)
        .all()
    )

    return edge_cases


def test_feature_extraction(
    sessions: list[SessionSummary], category: str, classifier: ProviderClassifier
) -> list[ExtractionResult]:
    """Test feature extraction on sessions.

    Args:
        sessions: List of sessions to test
        category: Edge case category being tested
        classifier: Provider classifier instance

    Returns:
        List of extraction results
    """
    results: list[ExtractionResult] = []

    for session in sessions:
        start = time.perf_counter()
        try:
            # Extract features for single session
            features = aggregate_features([session], classifier)
            elapsed_ms = (time.perf_counter() - start) * 1000

            # Determine enrichment status
            enrichment_status = "none"
            if session.enrichment:
                if "dshield" in session.enrichment or "spur" in session.enrichment:
                    enrichment_status = "full"
                else:
                    enrichment_status = "partial"

            result = ExtractionResult(
                session_id=session.session_id,  # type: ignore[arg-type]
                category=category,
                success=True,
                extraction_time_ms=elapsed_ms,
                features=features,
                total_commands=session.command_count,  # type: ignore[arg-type]
                auth_attempts=session.login_attempts,  # type: ignore[arg-type]
                enrichment_status=enrichment_status,
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            result = ExtractionResult(
                session_id=session.session_id,  # type: ignore[arg-type]
                category=category,
                success=False,
                extraction_time_ms=elapsed_ms,
                error=str(e),
                total_commands=session.command_count,  # type: ignore[arg-type]
                auth_attempts=session.login_attempts,  # type: ignore[arg-type]
            )

        results.append(result)

    return results


def calculate_category_stats(results: list[ExtractionResult]) -> CategoryStats:
    """Calculate statistics for a category of results.

    Args:
        results: List of extraction results for a category

    Returns:
        CategoryStats with aggregated statistics
    """
    if not results:
        return CategoryStats(category="empty")

    category = results[0].category
    stats = CategoryStats(category=category)

    stats.total = len(results)
    stats.success = sum(1 for r in results if r.success)
    stats.failed = stats.total - stats.success

    # Time statistics
    times = [r.extraction_time_ms for r in results]
    stats.avg_time_ms = sum(times) / len(times)
    stats.min_time_ms = min(times)
    stats.max_time_ms = max(times)

    # Collect failures
    stats.failures = [r for r in results if not r.success]

    return stats


def print_category_results(stats: CategoryStats) -> None:
    """Print results for a test category.

    Args:
        stats: Category statistics to print
    """
    print(f"\n{stats.category.upper().replace('_', ' ')}:")
    print(f"  Total sessions: {stats.total}")
    print(f"  Success: {stats.success}/{stats.total} ({stats.success / stats.total * 100:.1f}%)")
    print(f"  Failed: {stats.failed}")
    print(f"  Avg time: {stats.avg_time_ms:.2f}ms")
    print(f"  Min time: {stats.min_time_ms:.2f}ms")
    print(f"  Max time: {stats.max_time_ms:.2f}ms")

    # Show failures
    if stats.failures:
        print("\n  FAILURES:")
        for failure in stats.failures:
            print(f"    - {failure.session_id}: {failure.error}")


def print_summary(all_stats: dict[str, CategoryStats]) -> None:
    """Print overall test summary.

    Args:
        all_stats: Dictionary of category statistics
    """
    total_sessions = sum(s.total for s in all_stats.values())
    total_success = sum(s.success for s in all_stats.values())
    total_failed = sum(s.failed for s in all_stats.values())
    overall_success_rate = (total_success / total_sessions * 100) if total_sessions > 0 else 0

    print("\n" + "=" * 70)
    print("OVERALL SUMMARY")
    print("=" * 70)
    print(f"Total sessions tested: {total_sessions}")
    print(f"Success: {total_success}/{total_sessions} ({overall_success_rate:.1f}%)")
    print(f"Failed: {total_failed}")

    # Average times by category
    print("\nAverage Extraction Times by Category:")
    for category, stats in sorted(all_stats.items(), key=lambda x: x[1].avg_time_ms, reverse=True):
        print(f"  {category:20s}: {stats.avg_time_ms:6.2f}ms")

    # Categories with failures
    categories_with_failures = [cat for cat, stats in all_stats.items() if stats.failed > 0]
    if categories_with_failures:
        print("\nCategories with failures:")
        for cat in categories_with_failures:
            stats = all_stats[cat]
            print(f"  {cat}: {stats.failed}/{stats.total} failures")
    else:
        print("\nAll categories passed with 100% success rate!")


def main() -> None:
    """Run feature extraction robustness tests."""
    print("=" * 70)
    print("Feature Extraction Robustness Test (Issue #57)")
    print("=" * 70)

    # Load database connection
    print("\nConnecting to database...")
    config = _load_sensors_config()
    settings = load_database_settings(config)
    engine = create_engine_from_settings(settings)
    db = Session(engine)

    # Load provider classifier
    print("Initializing provider classifier...")
    classifier = ProviderClassifier(
        {
            "use_dshield": True,
            "use_spur": True,
            "max_enrichment_age_days": 365,
            "cloud_provider_keywords": ["amazon", "aws", "google", "azure"],
        }
    )

    # Query edge cases
    print("Querying edge case sessions...")
    edge_case_sessions = query_edge_case_sessions(db)

    # Report session counts
    print("\nSession counts by category:")
    for category, sessions in edge_case_sessions.items():
        print(f"  {category:20s}: {len(sessions):3d} sessions")

    total_sessions = sum(len(sessions) for sessions in edge_case_sessions.values())
    print(f"\nTotal sessions to test: {total_sessions}")

    # Test each category
    print("\n" + "=" * 70)
    print("RUNNING TESTS")
    print("=" * 70)

    all_stats: dict[str, CategoryStats] = {}
    for category, sessions in edge_case_sessions.items():
        if not sessions:
            print(f"\nWARNING: No sessions found for category '{category}'")
            continue

        print(f"\nTesting {category}...")
        results = test_feature_extraction(sessions, category, classifier)
        stats = calculate_category_stats(results)
        all_stats[category] = stats
        print_category_results(stats)

    # Print overall summary
    print_summary(all_stats)

    # Return exit code based on success rate
    total_sessions = sum(s.total for s in all_stats.values())
    total_success = sum(s.success for s in all_stats.values())
    success_rate = (total_success / total_sessions) if total_sessions > 0 else 0

    if success_rate == 1.0:
        print("\n✅ All tests passed!")
        sys.exit(0)
    elif success_rate >= 0.95:
        print(f"\n⚠️  Tests mostly passed ({success_rate * 100:.1f}% success)")
        sys.exit(0)
    else:
        print(f"\n❌ Tests failed ({success_rate * 100:.1f}% success)")
        sys.exit(1)


if __name__ == "__main__":
    main()
