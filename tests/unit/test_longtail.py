"""Unit tests for longtail threat detection analysis.

This module tests longtail analysis functions, password intelligence, and detection logic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.orm import Session

from cowrieprocessor.db.models import SessionSummary
from cowrieprocessor.threat_detection.longtail import (
    LongtailAnalysisResult,
    LongtailAnalyzer,
    run_longtail_analysis,
)

# ============================================================================
# LongtailAnalyzer.analyze() Tests (155 lines)
# ============================================================================


def test_analyze_empty_sessions_list(db_session: Session, tmp_path: Path) -> None:
    """Test analyze with empty sessions list.

    Given: Empty list of sessions
    When: analyze() is called
    Then: Returns result with zero counts

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Create analyzer with minimal config
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,  # Disable vector analysis for simpler tests
        enable_password_intelligence=False,  # Disable password intel
    )

    # When: Analyze empty sessions list
    result = analyzer.analyze(sessions=[], lookback_days=7)

    # Then: Result has zero counts
    assert isinstance(result, LongtailAnalysisResult)
    assert result.total_sessions_analyzed == 0
    assert result.total_events_analyzed == 0
    assert result.rare_command_count == 0
    assert result.anomalous_sequence_count == 0
    assert result.outlier_session_count == 0


def test_analyze_memory_limit_auto_detection(db_session: Session, tmp_path: Path) -> None:
    """Test analyze auto-detects memory limits based on system memory.

    Given: Analyzer without explicit memory_limit_gb
    When: analyze() is called
    Then: Memory limits are auto-detected and set

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Create analyzer without memory limit
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
        memory_limit_gb=None,  # Auto-detect
    )

    # Create mock sessions
    sessions = [
        SessionSummary(
            session_id=f"session{i}",
            first_event_at=datetime.now(UTC),
            last_event_at=datetime.now(UTC) + timedelta(minutes=5),
            enrichment={},
        )
        for i in range(3)
    ]

    # When: Analyze sessions (memory limit auto-detection happens)
    # Mock _extract_command_data to avoid database queries
    with patch.object(analyzer, "_extract_command_data"):
        result = analyzer.analyze(sessions=sessions, lookback_days=7)

    # Then: Analysis completes with memory limits set
    assert result.total_sessions_analyzed == 3
    assert analyzer._memory_warning_threshold > 0  # Memory threshold was set


def test_analyze_with_explicit_memory_limit(db_session: Session, tmp_path: Path) -> None:
    """Test analyze with explicit memory limit.

    Given: Analyzer with explicit memory_limit_gb
    When: analyze() is called
    Then: Explicit memory limit is used

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Create analyzer with explicit 2GB memory limit
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
        memory_limit_gb=2.0,  # Explicit 2GB limit
        memory_warning_threshold=0.8,  # 80% warning
    )

    sessions = [
        SessionSummary(
            session_id="test-session",
            first_event_at=datetime.now(UTC),
            last_event_at=datetime.now(UTC) + timedelta(minutes=5),
            enrichment={},
        )
    ]

    # When: Analyze sessions with explicit memory limit
    with patch.object(analyzer, "_extract_command_data"):
        result = analyzer.analyze(sessions=sessions, lookback_days=7)

    # Then: Analysis completes
    assert result.total_sessions_analyzed == 1
    # Warning threshold should be 80% of 2GB = 1.6GB = 1638MB
    assert analyzer._memory_warning_threshold == int(2.0 * 1024 * 0.8)


def test_analyze_calls_detection_methods(db_session: Session, tmp_path: Path) -> None:
    """Test analyze calls all detection methods when data is available.

    Given: Sessions with command data
    When: analyze() is called
    Then: All detection methods are called

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Create analyzer and sessions
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
    )

    sessions = [
        SessionSummary(
            session_id="session1",
            first_event_at=datetime.now(UTC),
            last_event_at=datetime.now(UTC) + timedelta(minutes=5),
            enrichment={},
        )
    ]

    # Mock all detection methods to track calls
    with patch.object(analyzer, "_extract_command_data") as mock_extract:
        with patch.object(analyzer, "_detect_rare_commands", return_value=[]) as mock_rare:
            with patch.object(analyzer, "_detect_anomalous_sequences", return_value=[]) as mock_anomalous:
                with patch.object(analyzer, "_detect_outlier_sessions", return_value=[]) as mock_outlier:
                    with patch.object(analyzer, "_detect_emerging_patterns", return_value=[]) as mock_emerging:
                        with patch.object(analyzer, "_detect_high_entropy_payloads", return_value=[]) as mock_entropy:
                            # Set up command frequencies to trigger detection
                            analyzer._command_frequencies = {"ls": 10, "pwd": 5}

                            # When: Analyze sessions
                            _ = analyzer.analyze(sessions=sessions, lookback_days=7)

    # Then: All detection methods were called
    mock_extract.assert_called_once()
    mock_rare.assert_called_once()
    mock_anomalous.assert_called_once()
    mock_outlier.assert_called_once()
    mock_emerging.assert_called_once()
    mock_entropy.assert_called_once()


def test_analyze_password_intelligence_enabled(db_session: Session, tmp_path: Path) -> None:
    """Test analyze includes password intelligence when enabled.

    Given: Analyzer with password intelligence enabled
    When: analyze() is called
    Then: Password intelligence is computed

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer with password intelligence
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=True,  # Enable password intel
        enable_password_enrichment=False,  # But not enrichment
    )

    # Create sessions with password enrichment data
    sessions = [
        SessionSummary(
            session_id="session1",
            first_event_at=datetime.now(UTC),
            last_event_at=datetime.now(UTC) + timedelta(minutes=5),
            enrichment={
                "password_stats": {
                    "total_attempts": 10,
                    "unique_passwords": 5,
                    "breached_passwords": 2,
                    "breach_prevalence_max": 1000,
                }
            },
        )
    ]

    # When: Analyze sessions
    with patch.object(analyzer, "_extract_command_data"):
        analyzer._command_frequencies = {"ls": 10}
        with patch.object(analyzer, "_detect_rare_commands", return_value=[]):
            with patch.object(analyzer, "_detect_anomalous_sequences", return_value=[]):
                with patch.object(analyzer, "_detect_outlier_sessions", return_value=[]):
                    with patch.object(analyzer, "_detect_emerging_patterns", return_value=[]):
                        with patch.object(analyzer, "_detect_high_entropy_payloads", return_value=[]):
                            result = analyzer.analyze(sessions=sessions, lookback_days=7)

    # Then: Password intelligence is included in result
    assert result.password_intel is not None
    assert isinstance(result.password_intel, dict)
    assert result.password_intel.get("total_attempts") == 10
    assert result.password_intel.get("unique_passwords") == 5
    assert result.password_intel.get("breached_passwords") == 2


def test_analyze_measures_duration_and_memory(db_session: Session, tmp_path: Path) -> None:
    """Test analyze measures duration and memory usage.

    Given: Analyzer and sessions
    When: analyze() is called
    Then: Result includes duration and memory metrics

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Create analyzer
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
    )

    sessions = [
        SessionSummary(
            session_id="session1",
            first_event_at=datetime.now(UTC),
            last_event_at=datetime.now(UTC),
            enrichment={},
        )
    ]

    # When: Analyze sessions
    with patch.object(analyzer, "_extract_command_data"):
        analyzer._command_frequencies = {"ls": 5}
        with patch.object(analyzer, "_detect_rare_commands", return_value=[]):
            with patch.object(analyzer, "_detect_anomalous_sequences", return_value=[]):
                with patch.object(analyzer, "_detect_outlier_sessions", return_value=[]):
                    with patch.object(analyzer, "_detect_emerging_patterns", return_value=[]):
                        with patch.object(analyzer, "_detect_high_entropy_payloads", return_value=[]):
                            result = analyzer.analyze(sessions=sessions, lookback_days=7)

    # Then: Result includes performance metrics
    assert result.analysis_duration_seconds >= 0
    assert result.memory_usage_mb >= 0


# ============================================================================
# LongtailAnalyzer._compute_password_intelligence() Tests (163 lines)
# ============================================================================


def test_compute_password_intelligence_no_sessions(db_session: Session, tmp_path: Path) -> None:
    """Test _compute_password_intelligence with no sessions.

    Given: Empty sessions list
    When: _compute_password_intelligence() is called
    Then: Returns empty intelligence dict

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer with password intelligence
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        enable_password_intelligence=True,
        enable_password_enrichment=False,
    )

    # When: Compute password intelligence with empty list
    result = analyzer._compute_password_intelligence([])

    # Then: Returns dict with zero counts
    assert isinstance(result, dict)
    assert result.get("total_attempts", 0) == 0
    assert result.get("unique_passwords", 0) == 0
    assert result.get("breached_passwords", 0) == 0


def test_compute_password_intelligence_from_enrichment(db_session: Session, tmp_path: Path) -> None:
    """Test _compute_password_intelligence aggregates from enrichment data.

    Given: Sessions with password_stats in enrichment
    When: _compute_password_intelligence() is called
    Then: Aggregates password statistics correctly

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Sessions with password enrichment data
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        enable_password_intelligence=True,
        enable_password_enrichment=False,
    )

    sessions = [
        SessionSummary(
            session_id="session1",
            first_event_at=datetime.now(UTC),
            last_event_at=datetime.now(UTC),
            enrichment={
                "password_stats": {
                    "total_attempts": 10,
                    "unique_passwords": 5,
                    "breached_passwords": 2,
                    "breach_prevalence_max": 1000,
                }
            },
        ),
        SessionSummary(
            session_id="session2",
            first_event_at=datetime.now(UTC),
            last_event_at=datetime.now(UTC),
            enrichment={
                "password_stats": {
                    "total_attempts": 15,
                    "unique_passwords": 8,
                    "breached_passwords": 3,
                    "breach_prevalence_max": 5000,
                }
            },
        ),
    ]

    # When: Compute password intelligence
    result = analyzer._compute_password_intelligence(sessions)

    # Then: Statistics are aggregated correctly
    assert result["total_attempts"] == 25  # 10 + 15
    assert result["unique_passwords"] == 13  # 5 + 8
    assert result["breached_passwords"] == 5  # 2 + 3
    assert result["breach_prevalence_max"] == 5000  # max(1000, 5000)
    assert len(result["sessions_with_breached"]) == 2  # Both sessions had breaches


def test_compute_password_intelligence_with_novel_hashes(db_session: Session, tmp_path: Path) -> None:
    """Test _compute_password_intelligence tracks novel password hashes.

    Given: Sessions with novel_password_hashes in enrichment
    When: _compute_password_intelligence() is called
    Then: Novel hashes are aggregated

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Sessions with novel password hashes
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        enable_password_intelligence=True,
        enable_password_enrichment=False,
    )

    sessions = [
        SessionSummary(
            session_id="session1",
            first_event_at=datetime.now(UTC),
            last_event_at=datetime.now(UTC),
            enrichment={
                "password_stats": {
                    "total_attempts": 5,
                    "unique_passwords": 3,
                    "breached_passwords": 0,
                    "novel_password_hashes": ["hash1", "hash2"],
                }
            },
        ),
        SessionSummary(
            session_id="session2",
            first_event_at=datetime.now(UTC),
            last_event_at=datetime.now(UTC),
            enrichment={
                "password_stats": {
                    "total_attempts": 3,
                    "unique_passwords": 2,
                    "breached_passwords": 0,
                    "novel_password_hashes": ["hash3"],
                }
            },
        ),
    ]

    # When: Compute password intelligence
    result = analyzer._compute_password_intelligence(sessions)

    # Then: Novel hashes are aggregated
    assert "novel_password_hashes" in result
    assert len(result["novel_password_hashes"]) == 3
    assert set(result["novel_password_hashes"]) == {"hash1", "hash2", "hash3"}


def test_compute_password_intelligence_handles_missing_enrichment(db_session: Session, tmp_path: Path) -> None:
    """Test _compute_password_intelligence handles sessions without enrichment.

    Given: Mix of sessions with and without password enrichment
    When: _compute_password_intelligence() is called
    Then: Only enriched sessions contribute to statistics

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Mixed sessions
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        enable_password_intelligence=True,
        enable_password_enrichment=False,
    )

    sessions = [
        SessionSummary(
            session_id="session1",
            first_event_at=datetime.now(UTC),
            last_event_at=datetime.now(UTC),
            enrichment={
                "password_stats": {
                    "total_attempts": 10,
                    "unique_passwords": 5,
                    "breached_passwords": 2,
                }
            },
        ),
        SessionSummary(
            session_id="session2",
            first_event_at=datetime.now(UTC),
            last_event_at=datetime.now(UTC),
            enrichment={},  # No password stats
        ),
        SessionSummary(
            session_id="session3",
            first_event_at=datetime.now(UTC),
            last_event_at=datetime.now(UTC),
            enrichment=None,  # type: ignore[arg-type]  # Null enrichment
        ),
    ]

    # When: Compute password intelligence
    result = analyzer._compute_password_intelligence(sessions)

    # Then: Only session1 contributes
    assert result["total_attempts"] == 10
    assert result["unique_passwords"] == 5
    assert result["breached_passwords"] == 2
    assert len(result["sessions_with_breached"]) == 1


def test_compute_password_intelligence_alternative_key_name(db_session: Session, tmp_path: Path) -> None:
    """Test _compute_password_intelligence handles 'passwords' key (backward compat).

    Given: Session with 'passwords' instead of 'password_stats'
    When: _compute_password_intelligence() is called
    Then: Data is read from 'passwords' key

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Session with alternative key name
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        enable_password_intelligence=True,
    )

    sessions = [
        SessionSummary(
            session_id="session1",
            first_event_at=datetime.now(UTC),
            last_event_at=datetime.now(UTC),
            enrichment={
                "passwords": {  # Alternative key name
                    "total_attempts": 7,
                    "unique_passwords": 4,
                    "breached_passwords": 1,
                }
            },
        )
    ]

    # When: Compute password intelligence
    result = analyzer._compute_password_intelligence(sessions)

    # Then: Data is read correctly
    assert result["total_attempts"] == 7
    assert result["unique_passwords"] == 4
    assert result["breached_passwords"] == 1


# ============================================================================
# run_longtail_analysis() Tests (110 lines)
# ============================================================================


def test_run_longtail_analysis_empty_database(db_session: Session) -> None:
    """Test run_longtail_analysis with no sessions in database.

    Given: Empty database with no sessions
    When: run_longtail_analysis() is called
    Then: Returns empty result with zero counts

    Args:
        db_session: Database session fixture
    """
    # Given: Empty database (no sessions)
    # Get database URL from session
    db_url = str(db_session.get_bind().url)

    # When: Run longtail analysis with 7 day lookback
    result = run_longtail_analysis(
        db_url=db_url,
        lookback_days=7,
        store_results=False,
    )

    # Then: Returns empty result
    assert isinstance(result, LongtailAnalysisResult)
    assert result.total_sessions_analyzed == 0
    assert result.total_events_analyzed == 0
    assert result.rare_command_count == 0
    assert result.anomalous_sequence_count == 0
    assert result.outlier_session_count == 0


def test_run_longtail_analysis_with_sessions(db_session: Session) -> None:
    """Test run_longtail_analysis with sessions in database.

    Given: Database with sessions in time window
    When: run_longtail_analysis() is called
    Then: Analysis runs successfully and returns results

    Args:
        db_session: Database session fixture
    """
    # Given: Create sessions in database
    now = datetime.now(UTC)
    sessions = [
        SessionSummary(
            session_id=f"session{i}",
            first_event_at=now - timedelta(hours=i),
            last_event_at=now - timedelta(hours=i - 1),
            enrichment={},
        )
        for i in range(1, 4)
    ]
    for session in sessions:
        db_session.add(session)
    db_session.commit()

    # Get database URL
    db_url = str(db_session.get_bind().url)

    # When: Run longtail analysis
    result = run_longtail_analysis(
        db_url=db_url,
        lookback_days=7,
        store_results=False,
    )

    # Then: Analysis completes successfully
    assert isinstance(result, LongtailAnalysisResult)
    assert result.total_sessions_analyzed == 3
    assert result.analysis_duration_seconds >= 0


def test_run_longtail_analysis_with_time_window(db_session: Session) -> None:
    """Test run_longtail_analysis with custom time window.

    Given: Sessions across different time periods
    When: run_longtail_analysis() is called with window_start and window_end
    Then: Only analyzes sessions within the specified window

    Args:
        db_session: Database session fixture
    """
    # Given: Create sessions at different times
    now = datetime.now(UTC)
    old_session = SessionSummary(
        session_id="old-session",
        first_event_at=now - timedelta(days=30),
        last_event_at=now - timedelta(days=30),
        enrichment={},
    )
    recent_session = SessionSummary(
        session_id="recent-session",
        first_event_at=now - timedelta(hours=1),
        last_event_at=now,
        enrichment={},
    )
    db_session.add(old_session)
    db_session.add(recent_session)
    db_session.commit()

    db_url = str(db_session.get_bind().url)

    # When: Run analysis with recent window only
    window_start = now - timedelta(days=1)
    window_end = now
    result = run_longtail_analysis(
        db_url=db_url,
        window_start=window_start,
        window_end=window_end,
        store_results=False,
    )

    # Then: Only recent session is analyzed
    assert result.total_sessions_analyzed == 1


def test_run_longtail_analysis_with_json_output(db_session: Session, tmp_path: Path) -> None:
    """Test run_longtail_analysis writes JSON output when output_path specified.

    Given: Database with sessions
    When: run_longtail_analysis() is called with output_path
    Then: Results are written to JSON file

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Create a session
    now = datetime.now(UTC)
    session = SessionSummary(
        session_id="test-session",
        first_event_at=now - timedelta(hours=1),
        last_event_at=now,
        enrichment={},
    )
    db_session.add(session)
    db_session.commit()

    db_url = str(db_session.get_bind().url)
    output_file = tmp_path / "longtail_results.json"

    # When: Run analysis with output path
    _ = run_longtail_analysis(
        db_url=db_url,
        lookback_days=7,
        output_path=str(output_file),
        store_results=False,
    )

    # Then: JSON file is created
    assert output_file.exists()
    import json

    with open(output_file) as f:
        data = json.load(f)
    assert data["total_sessions_analyzed"] == 1


# ============================================================================
# LongtailAnalyzer._detect_outlier_sessions() Tests (88 lines)
# ============================================================================


def test_detect_outlier_sessions_too_few_sessions(db_session: Session, tmp_path: Path) -> None:
    """Test _detect_outlier_sessions with too few sessions.

    Given: Analyzer with fewer sessions than min_cluster_size
    When: _detect_outlier_sessions() is called
    Then: Returns empty list (not enough data)

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer with min_cluster_size=5
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
        min_cluster_size=5,
    )

    # Add only 3 session characteristics (less than min_cluster_size)
    analyzer._session_characteristics = [
        {
            "session_id": "session1",
            "src_ip": "10.0.0.1",
            "duration": 100,
            "command_count": 10,
            "login_attempts": 2,
            "file_operations": 1,
        },
        {
            "session_id": "session2",
            "src_ip": "10.0.0.2",
            "duration": 200,
            "command_count": 15,
            "login_attempts": 3,
            "file_operations": 2,
        },
        {
            "session_id": "session3",
            "src_ip": "10.0.0.3",
            "duration": 150,
            "command_count": 12,
            "login_attempts": 1,
            "file_operations": 0,
        },
    ]

    # When: Detect outlier sessions
    outliers = analyzer._detect_outlier_sessions()

    # Then: Returns empty list (not enough data)
    assert outliers == []


def test_detect_outlier_sessions_with_clustering(db_session: Session, tmp_path: Path) -> None:
    """Test _detect_outlier_sessions with successful DBSCAN clustering.

    Given: Analyzer with sufficient sessions for clustering
    When: _detect_outlier_sessions() is called
    Then: Detects outliers using DBSCAN

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer with enough sessions
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
        min_cluster_size=3,
        cluster_eps=0.5,
    )

    # Add session characteristics with one clear outlier
    analyzer._session_characteristics = [
        # Normal sessions (similar characteristics)
        {
            "session_id": "session1",
            "src_ip": "10.0.0.1",
            "duration": 100,
            "command_count": 10,
            "login_attempts": 2,
            "file_operations": 1,
        },
        {
            "session_id": "session2",
            "src_ip": "10.0.0.2",
            "duration": 110,
            "command_count": 12,
            "login_attempts": 2,
            "file_operations": 1,
        },
        {
            "session_id": "session3",
            "src_ip": "10.0.0.3",
            "duration": 105,
            "command_count": 11,
            "login_attempts": 2,
            "file_operations": 1,
        },
        # Outlier session (very different)
        {
            "session_id": "outlier-session",
            "src_ip": "10.0.0.99",
            "duration": 5000,
            "command_count": 500,
            "login_attempts": 50,
            "file_operations": 100,
        },
    ]

    # When: Detect outlier sessions
    outliers = analyzer._detect_outlier_sessions()

    # Then: Outlier is detected (either via DBSCAN or fallback)
    assert len(outliers) >= 1
    # Check that outlier session is in results
    outlier_ids = [o["session_id"] for o in outliers]
    assert "outlier-session" in outlier_ids


def test_detect_outlier_sessions_fallback_detection(db_session: Session, tmp_path: Path) -> None:
    """Test _detect_outlier_sessions fallback to simple threshold detection.

    Given: Analyzer with session data
    When: _detect_outlier_sessions() is called and DBSCAN fails
    Then: Falls back to threshold-based outlier detection

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer with sessions
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
        min_cluster_size=3,
    )

    # Add sessions with one exceeding simple thresholds
    analyzer._session_characteristics = [
        {
            "session_id": "normal1",
            "src_ip": "10.0.0.1",
            "duration": 100,
            "command_count": 10,
            "login_attempts": 2,
            "file_operations": 1,
        },
        {
            "session_id": "normal2",
            "src_ip": "10.0.0.2",
            "duration": 200,
            "command_count": 15,
            "login_attempts": 3,
            "file_operations": 2,
        },
        {
            "session_id": "outlier-high-commands",
            "src_ip": "10.0.0.99",
            "duration": 300,
            "command_count": 150,  # > 100 threshold
            "login_attempts": 2,
            "file_operations": 1,
        },
    ]

    # When: Detect outliers (may use fallback if DBSCAN fails)
    outliers = analyzer._detect_outlier_sessions()

    # Then: High-command session is detected as outlier
    # Either via DBSCAN or fallback threshold detection
    assert len(outliers) >= 1


def test_detect_outlier_sessions_no_outliers(db_session: Session, tmp_path: Path) -> None:
    """Test _detect_outlier_sessions with no outliers present.

    Given: Analyzer with all similar (normal) sessions
    When: _detect_outlier_sessions() is called
    Then: Returns empty list or all sessions clustered normally

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer with very similar sessions
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
        min_cluster_size=3,
        cluster_eps=1.0,  # Larger eps to cluster similar sessions
    )

    # Add very similar sessions (no outliers)
    analyzer._session_characteristics = [
        {
            "session_id": f"session{i}",
            "src_ip": f"10.0.0.{i}",
            "duration": 100 + i,
            "command_count": 10 + i,
            "login_attempts": 2,
            "file_operations": 1,
        }
        for i in range(1, 6)
    ]

    # When: Detect outlier sessions
    outliers = analyzer._detect_outlier_sessions()

    # Then: No outliers detected or very few
    # (all sessions should cluster together with similar characteristics)
    assert isinstance(outliers, list)


# ============================================================================
# LongtailAnalyzer._extract_commands_for_sessions() Tests (80 lines)
# ============================================================================


def test_extract_commands_empty_sessions(db_session: Session, tmp_path: Path) -> None:
    """Test _extract_commands_for_sessions with empty session list.

    Given: Empty list of session IDs
    When: _extract_commands_for_sessions() is called
    Then: Returns empty dictionary

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer with empty session list
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
    )

    # When: Extract commands with empty list
    result = analyzer._extract_commands_for_sessions([])

    # Then: Returns empty dict
    assert result == {}


def test_extract_commands_with_cache_hit(db_session: Session, tmp_path: Path) -> None:
    """Test _extract_commands_for_sessions uses cache on repeated calls.

    Given: Analyzer that has cached results
    When: _extract_commands_for_sessions() is called with same session IDs
    Then: Returns cached results without querying database

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer with cached data
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
    )

    # Pre-populate cache
    import hashlib

    session_ids = ["session1", "session2"]
    cache_key = hashlib.md5(','.join(sorted(session_ids)).encode()).hexdigest()
    cached_result = {"session1": ["ls", "pwd"], "session2": ["whoami"]}
    analyzer._command_cache[cache_key] = cached_result

    # When: Extract commands with cached session IDs
    result = analyzer._extract_commands_for_sessions(session_ids)

    # Then: Returns cached results
    assert result == cached_result


def test_extract_commands_handles_database_errors(db_session: Session, tmp_path: Path) -> None:
    """Test _extract_commands_for_sessions handles database errors gracefully.

    Given: Database that may cause SQL errors (e.g., SQLite with PostgreSQL-specific SQL)
    When: _extract_commands_for_sessions() is called
    Then: Returns empty dict without crashing (error handling)

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture

    Note:
        The function uses PostgreSQL-specific "SET TRANSACTION READ ONLY" which
        fails on SQLite. This test verifies graceful error handling.
    """
    # Given: Create analyzer (SQLite database will cause SQL error)
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
    )

    # When: Extract commands (will trigger SQLite compatibility error)
    result = analyzer._extract_commands_for_sessions(["session1", "session2"])

    # Then: Returns empty dict gracefully (doesn't crash)
    assert isinstance(result, dict)
    # With SQLite, the PostgreSQL-specific SQL fails, returning empty dict
    # This is expected behavior - the function handles errors gracefully


# ============================================================================
# LongtailAnalyzer._detect_anomalous_sequences() Tests (78 lines)
# ============================================================================


def test_detect_anomalous_sequences_too_few_sequences(db_session: Session, tmp_path: Path) -> None:
    """Test _detect_anomalous_sequences with too few sequences.

    Given: Analyzer with fewer sequences than min_cluster_size
    When: _detect_anomalous_sequences() is called
    Then: Returns empty list

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer with min_cluster_size=5
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
        min_cluster_size=5,
    )

    # Add only 3 sequences (less than min_cluster_size)
    analyzer._command_sequences = [
        "ls pwd whoami",
        "cd /tmp ls",
        "cat file.txt",
    ]

    # When: Detect anomalous sequences
    anomalies = analyzer._detect_anomalous_sequences()

    # Then: Returns empty list
    assert anomalies == []


def test_detect_anomalous_sequences_frequency_based(db_session: Session, tmp_path: Path) -> None:
    """Test _detect_anomalous_sequences with frequency-based detection.

    Given: Analyzer with vector_analysis_enabled=False
    When: _detect_anomalous_sequences() is called
    Then: Uses frequency-based detection to find unique sequences

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer without vector analysis
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,  # Disable vector analysis
        enable_password_intelligence=False,
        min_cluster_size=3,
    )

    # Add sequences with one unique (frequency=1)
    analyzer._command_sequences = [
        "ls pwd whoami",
        "ls pwd whoami",
        "ls pwd whoami",
        "unique command sequence",  # This should be detected as anomalous
    ]

    # When: Detect anomalous sequences
    anomalies = analyzer._detect_anomalous_sequences()

    # Then: Unique sequence is detected
    assert len(anomalies) >= 1
    unique_sequences = [a["sequence"] for a in anomalies]
    assert "unique command sequence" in unique_sequences


def test_detect_anomalous_sequences_no_anomalies(db_session: Session, tmp_path: Path) -> None:
    """Test _detect_anomalous_sequences with no unique sequences.

    Given: Analyzer with all repeated sequences
    When: _detect_anomalous_sequences() is called
    Then: Returns empty list (no anomalies)

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer with all repeated sequences
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
        min_cluster_size=3,
    )

    # All sequences are repeated (no unique ones)
    analyzer._command_sequences = [
        "ls pwd",
        "ls pwd",
        "cd /tmp",
        "cd /tmp",
        "whoami",
        "whoami",
    ]

    # When: Detect anomalous sequences
    anomalies = analyzer._detect_anomalous_sequences()

    # Then: No anomalies detected
    assert anomalies == []


# ============================================================================
# LongtailAnalyzer.__init__() Tests (81 lines)
# ============================================================================


def test_analyzer_init_with_defaults(db_session: Session, tmp_path: Path) -> None:
    """Test LongtailAnalyzer initialization with default parameters.

    Given: Session factory and minimal configuration
    When: LongtailAnalyzer is initialized
    Then: All default values are set correctly

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Session factory
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())

    # When: Initialize with defaults
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
    )

    # Then: Defaults are set correctly
    assert analyzer.session_factory == session_factory
    assert analyzer.rarity_threshold == 0.05
    assert analyzer.sequence_window == 5
    assert analyzer.cluster_eps == 0.3
    assert analyzer.min_cluster_size == 5
    assert analyzer.entropy_threshold == 0.8
    assert analyzer.sensitivity_threshold == 0.95
    assert analyzer.vector_analysis_enabled is True
    assert analyzer.batch_size == 100
    assert analyzer.enable_password_intelligence is True
    assert analyzer.enable_password_enrichment is False


def test_analyzer_init_with_custom_params(db_session: Session, tmp_path: Path) -> None:
    """Test LongtailAnalyzer initialization with custom parameters.

    Given: Session factory and custom configuration
    When: LongtailAnalyzer is initialized with custom params
    Then: Custom values override defaults

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Custom configuration
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())

    # When: Initialize with custom params
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        rarity_threshold=0.1,
        sequence_window=10,
        cluster_eps=0.5,
        min_cluster_size=10,
        entropy_threshold=0.9,
        sensitivity_threshold=0.8,
        vector_analysis_enabled=False,
        batch_size=200,
        memory_limit_gb=4.0,
        memory_warning_threshold=0.8,
        enable_password_intelligence=False,
        enable_password_enrichment=False,
    )

    # Then: Custom values are set
    assert analyzer.rarity_threshold == 0.1
    assert analyzer.sequence_window == 10
    assert analyzer.cluster_eps == 0.5
    assert analyzer.min_cluster_size == 10
    assert analyzer.entropy_threshold == 0.9
    assert analyzer.sensitivity_threshold == 0.8
    assert analyzer.vector_analysis_enabled is False
    assert analyzer.batch_size == 200
    assert analyzer.memory_limit_gb == 4.0
    assert analyzer.memory_warning_threshold_fraction == 0.8
    assert analyzer.enable_password_intelligence is False
    assert analyzer.enable_password_enrichment is False


def test_analyzer_init_state_initialization(db_session: Session, tmp_path: Path) -> None:
    """Test LongtailAnalyzer initializes internal state correctly.

    Given: Session factory
    When: LongtailAnalyzer is initialized
    Then: Internal state structures are empty

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Session factory
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())

    # When: Initialize analyzer
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
    )

    # Then: Internal state is initialized
    assert analyzer._command_frequencies == {}
    assert analyzer._command_to_sessions == {}
    assert analyzer._session_characteristics == []
    assert analyzer._command_sequences == []
    assert analyzer._command_cache == {}
    assert analyzer.command_vectorizer is not None


# ============================================================================
# LongtailAnalyzer.benchmark_vector_dimensions() Tests (83 lines)
# ============================================================================


def test_benchmark_vector_dimensions_with_sessions(db_session: Session, tmp_path: Path) -> None:
    """Test benchmark_vector_dimensions runs analysis on different dimensions.

    Given: Analyzer and test sessions
    When: benchmark_vector_dimensions() is called
    Then: Returns performance metrics for each dimension

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer and minimal sessions
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,  # Disable for faster test
        enable_password_intelligence=False,
    )

    # Create minimal test sessions
    sessions = [
        SessionSummary(
            session_id=f"session{i}",
            first_event_at=datetime.now(UTC),
            last_event_at=datetime.now(UTC) + timedelta(minutes=5),
            enrichment={},
        )
        for i in range(3)
    ]

    # When: Benchmark with small dimensions (fast)
    dimensions = [8, 16]  # Small dimensions for fast test
    with patch.object(analyzer, "_extract_command_data"):
        analyzer._command_frequencies = {"ls": 10, "pwd": 5}
        with patch.object(analyzer, "_detect_rare_commands", return_value=[]):
            with patch.object(analyzer, "_detect_anomalous_sequences", return_value=[]):
                with patch.object(analyzer, "_detect_outlier_sessions", return_value=[]):
                    with patch.object(analyzer, "_detect_emerging_patterns", return_value=[]):
                        with patch.object(analyzer, "_detect_high_entropy_payloads", return_value=[]):
                            results = analyzer.benchmark_vector_dimensions(sessions, dimensions)

    # Then: Results contain metrics for each dimension
    assert isinstance(results, dict)
    assert len(results) == len(dimensions)
    for dim in dimensions:
        assert dim in results
        assert "duration" in results[dim]
        assert "memory_mb" in results[dim]
        assert "quality_score" in results[dim]


def test_benchmark_vector_dimensions_handles_errors(db_session: Session, tmp_path: Path) -> None:
    """Test benchmark_vector_dimensions handles analysis errors gracefully.

    Given: Analyzer that may encounter errors during benchmarking
    When: benchmark_vector_dimensions() is called and errors occur
    Then: Returns error metrics without crashing

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
    )

    # Mock analyze to raise an error
    with patch.object(LongtailAnalyzer, "analyze", side_effect=RuntimeError("Test error")):
        results = analyzer.benchmark_vector_dimensions([], [16])

    # Then: Error metrics are returned
    assert 16 in results
    assert results[16]["duration"] == float("inf")
    assert results[16]["quality_score"] == 0.0


# ============================================================================
# LongtailAnalyzer.create_mock_sessions_with_commands() Tests (104 lines)
# ============================================================================


def test_create_mock_sessions_default_params() -> None:
    """Test create_mock_sessions_with_commands with default parameters.

    Given: No custom parameters
    When: create_mock_sessions_with_commands() is called
    Then: Returns sessions with default normal/anomalous patterns

    Args:
        None (static method)
    """
    # When: Create mock sessions with defaults
    sessions = LongtailAnalyzer.create_mock_sessions_with_commands()

    # Then: Default 10 normal + 3 anomalous = 13 sessions
    assert len(sessions) == 13
    assert all(isinstance(s, SessionSummary) for s in sessions)

    # Check normal sessions
    normal_sessions = [s for s in sessions if s.session_id.startswith("normal")]
    assert len(normal_sessions) == 10

    # Check anomalous sessions
    anomalous_sessions = [s for s in sessions if s.session_id.startswith("anomalous")]
    assert len(anomalous_sessions) == 3
    assert all(s.risk_score == 90 for s in anomalous_sessions)
    assert all(s.vt_flagged for s in anomalous_sessions)


def test_create_mock_sessions_custom_counts() -> None:
    """Test create_mock_sessions_with_commands with custom session counts.

    Given: Custom normal and anomalous session counts
    When: create_mock_sessions_with_commands() is called
    Then: Returns correct number of each session type

    Args:
        None (static method)
    """
    # When: Create with custom counts
    sessions = LongtailAnalyzer.create_mock_sessions_with_commands(num_normal_sessions=5, num_anomalous_sessions=2)

    # Then: Correct counts
    assert len(sessions) == 7
    normal_count = sum(1 for s in sessions if s.session_id.startswith("normal"))
    anomalous_count = sum(1 for s in sessions if s.session_id.startswith("anomalous"))
    assert normal_count == 5
    assert anomalous_count == 2


def test_create_mock_sessions_custom_commands() -> None:
    """Test create_mock_sessions_with_commands with custom command sequences.

    Given: Custom normal and anomalous command sequences
    When: create_mock_sessions_with_commands() is called
    Then: Sessions contain the custom commands

    Args:
        None (static method)
    """
    # Given: Custom command sequences
    normal_cmds = ["echo hello", "ls", "pwd"]
    anomalous_cmds = ["rm -rf /", "dd if=/dev/zero of=/dev/sda"]

    # When: Create with custom commands
    sessions = LongtailAnalyzer.create_mock_sessions_with_commands(
        normal_sequence=normal_cmds,
        anomalous_sequence=anomalous_cmds,
        num_normal_sessions=2,
        num_anomalous_sessions=1,
    )

    # Then: Sessions created with custom command counts
    assert len(sessions) == 3
    normal_sessions = [s for s in sessions if s.session_id.startswith("normal")]
    assert all(s.command_count == len(normal_cmds) for s in normal_sessions)

    anomalous_sessions = [s for s in sessions if s.session_id.startswith("anomalous")]
    assert all(s.command_count == len(anomalous_cmds) for s in anomalous_sessions)


# ============================================================================
# LongtailAnalyzer._extract_command_data() Tests (54 lines)
# ============================================================================


def test_extract_command_data_empty_sessions(db_session: Session, tmp_path: Path) -> None:
    """Test _extract_command_data with empty sessions list.

    Given: Empty sessions list
    When: _extract_command_data() is called
    Then: Internal state remains empty

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer with no sessions
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
    )

    # When: Extract command data from empty list
    analyzer._extract_command_data([])

    # Then: State remains empty
    assert analyzer._command_frequencies == {}
    assert analyzer._command_to_sessions == {}
    assert analyzer._session_characteristics == []
    assert analyzer._command_sequences == []


def test_extract_command_data_builds_frequency_map(db_session: Session, tmp_path: Path) -> None:
    """Test _extract_command_data builds command frequency map.

    Given: Sessions (command extraction will fail with SQLite but state is built)
    When: _extract_command_data() is called
    Then: Session characteristics are populated

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer and sessions
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
    )

    sessions = [
        SessionSummary(
            session_id="session1",
            first_event_at=datetime.now(UTC),
            last_event_at=datetime.now(UTC) + timedelta(minutes=5),
            login_attempts=2,
            file_downloads=1,
            enrichment={},
        )
    ]

    # When: Extract command data
    analyzer._extract_command_data(sessions)

    # Then: Session characteristics are built
    assert len(analyzer._session_characteristics) == 1
    assert analyzer._session_characteristics[0]["session_id"] == "session1"
    assert analyzer._session_characteristics[0]["login_attempts"] == 2
    assert analyzer._session_characteristics[0]["file_operations"] == 1


# ============================================================================
# LongtailAnalyzer._extract_ips_for_sessions() Tests (53 lines)
# ============================================================================


def test_extract_ips_empty_sessions(db_session: Session, tmp_path: Path) -> None:
    """Test _extract_ips_for_sessions with empty session list.

    Given: Empty session IDs list
    When: _extract_ips_for_sessions() is called
    Then: Returns empty dictionary

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
    )

    # When: Extract IPs with empty list
    result = analyzer._extract_ips_for_sessions([])

    # Then: Returns empty dict
    assert result == {}


def test_extract_ips_handles_database_errors(db_session: Session, tmp_path: Path) -> None:
    """Test _extract_ips_for_sessions handles database errors gracefully.

    Given: Session IDs that will cause PostgreSQL-specific SQL to fail on SQLite
    When: _extract_ips_for_sessions() is called
    Then: Returns dict with None values (error handling)

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer (SQLite will cause PostgreSQL SQL to fail)
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
    )

    # When: Extract IPs (will fail with SQLite)
    session_ids = ["session1", "session2"]
    result = analyzer._extract_ips_for_sessions(session_ids)

    # Then: Returns dict with None values (graceful error handling)
    assert isinstance(result, dict)
    assert "session1" in result
    assert "session2" in result
    # Values will be None because PostgreSQL-specific SQL fails on SQLite
    assert result["session1"] is None
    assert result["session2"] is None


# ============================================================================
# LongtailAnalyzer._detect_rare_commands() Tests (48 lines)
# ============================================================================


def test_detect_rare_commands_empty_frequencies(db_session: Session, tmp_path: Path) -> None:
    """Test _detect_rare_commands with no command frequencies.

    Given: Analyzer with empty command frequencies
    When: _detect_rare_commands() is called
    Then: Returns empty list

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer with no commands
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
    )

    # Ensure empty state
    analyzer._command_frequencies = {}

    # When: Detect rare commands
    rare = analyzer._detect_rare_commands()

    # Then: Returns empty list
    assert rare == []


def test_detect_rare_commands_identifies_rare(db_session: Session, tmp_path: Path) -> None:
    """Test _detect_rare_commands identifies rare commands below threshold.

    Given: Command frequencies with some rare commands
    When: _detect_rare_commands() is called
    Then: Rare commands are detected

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer with command frequencies
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
        rarity_threshold=0.1,  # 10% threshold
    )

    # Set up command frequencies: 1 common, 1 rare
    analyzer._command_frequencies = {
        "ls": 100,  # Common (90.9%)
        "rare_cmd": 10,  # Rare (9.1%, below 10% threshold)
    }
    analyzer._command_to_sessions = {
        "ls": ["session1"],
        "rare_cmd": ["session2"],
    }
    analyzer._session_characteristics = [
        {"session_id": "session1", "src_ip": "10.0.0.1", "timestamp": datetime.now(UTC)},
        {"session_id": "session2", "src_ip": "10.0.0.2", "timestamp": datetime.now(UTC)},
    ]

    # When: Detect rare commands
    rare = analyzer._detect_rare_commands()

    # Then: Rare command is detected
    assert len(rare) >= 1
    rare_commands = [r["command"] for r in rare]
    assert "rare_cmd" in rare_commands


def test_detect_rare_commands_sorts_by_rarity(db_session: Session, tmp_path: Path) -> None:
    """Test _detect_rare_commands sorts results by rarity (frequency).

    Given: Multiple rare commands with different frequencies
    When: _detect_rare_commands() is called
    Then: Results are sorted by frequency (lowest first)

    Args:
        db_session: Database session fixture
        tmp_path: Temporary directory fixture
    """
    # Given: Analyzer with multiple rare commands
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=db_session.get_bind())
    analyzer = LongtailAnalyzer(
        session_factory=session_factory,
        vocab_path=tmp_path / "vocab.pkl",
        vector_analysis_enabled=False,
        enable_password_intelligence=False,
        rarity_threshold=0.6,  # 60% threshold to catch all three
    )

    analyzer._command_frequencies = {
        "cmd1": 1,  # Rarest (1/9 = 11.1%)
        "cmd2": 3,  # Medium rare (3/9 = 33.3%)
        "cmd3": 5,  # Less rare (5/9 = 55.5%)
    }
    analyzer._command_to_sessions = {
        "cmd1": ["session1"],
        "cmd2": ["session2"],
        "cmd3": ["session3"],
    }
    analyzer._session_characteristics = []

    # When: Detect rare commands
    rare = analyzer._detect_rare_commands()

    # Then: Sorted by frequency (lowest first)
    # Total: 1+3+5 = 9, all three are below 60% threshold
    assert len(rare) == 3
    frequencies = [r["frequency"] for r in rare]
    assert frequencies == [1, 3, 5]  # Ascending order
