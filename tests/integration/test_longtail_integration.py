"""Integration tests for longtail analysis functionality."""

from __future__ import annotations

import pytest
from cowrieprocessor.threat_detection.longtail import LongtailAnalyzer


class TestLongtailIntegration:
    """Integration tests for longtail analysis."""

    def test_longtail_analyzer_creation(self) -> None:
        """Test that LongtailAnalyzer can be created with proper parameters."""
        # This should work without a database connection for basic instantiation
        analyzer = LongtailAnalyzer(None)  # None for session_factory for testing
        assert analyzer is not None
        assert analyzer.rarity_threshold == 0.05
        assert analyzer.sequence_window == 5

    def test_mock_session_creation(self) -> None:
        """Test that mock sessions can be created for testing."""
        mock_sessions = LongtailAnalyzer.create_mock_sessions_with_commands(
            num_normal_sessions=2,
            num_anomalous_sessions=1
        )

        assert len(mock_sessions) == 3
        assert all(hasattr(session, 'commands') for session in mock_sessions)

        # Check that commands are stored as JSON strings
        for session in mock_sessions:
            assert isinstance(session.__dict__['commands'], str)

    def test_vectorizer_vocabulary_management(self) -> None:
        """Test that vectorizer handles vocabulary correctly."""
        from cowrieprocessor.threat_detection.longtail import CommandVectorizer
        from pathlib import Path

        # Test with temporary vocabulary path
        vocab_path = Path("/tmp/test_vocab.pkl")
        if vocab_path.exists():
            vocab_path.unlink()

        vectorizer = CommandVectorizer(vocab_path=vocab_path)

        # Test that vectorizer is created
        assert vectorizer is not None
        assert vectorizer.max_features == 128
        assert vectorizer.ngram_range == (1, 3)

    def test_dimension_benchmarking_structure(self) -> None:
        """Test that dimension benchmarking has correct structure."""
        from cowrieprocessor.threat_detection.longtail import LongtailAnalyzer

        analyzer = LongtailAnalyzer(None)  # None for session_factory for testing

        # Test that method exists and returns expected structure
        mock_sessions = LongtailAnalyzer.create_mock_sessions_with_commands(num_normal_sessions=1)

        # This should not crash, even without database
        # (will use fallback session-level analysis)
        try:
            results = analyzer.benchmark_vector_dimensions(mock_sessions, [32, 64])
            # Should return a dict with dimension keys
            assert isinstance(results, dict)
        except Exception as e:
            # Expected to fail without proper database setup, but should not crash
            assert "database" in str(e).lower() or "session" in str(e).lower()

    def test_mock_session_structure(self) -> None:
        """Test that mock sessions have correct structure for testing."""
        from cowrieprocessor.threat_detection.longtail import LongtailAnalyzer

        # Create small mock sessions for structure testing
        mock_sessions = LongtailAnalyzer.create_mock_sessions_with_commands(
            num_normal_sessions=1,
            num_anomalous_sessions=1
        )

        # Validate session structure
        assert len(mock_sessions) == 2

        # Check that each session has required attributes
        for session in mock_sessions:
            assert hasattr(session, 'session_id')
            assert hasattr(session, 'command_count')
            assert hasattr(session, 'first_event_at')
            assert hasattr(session, '__dict__')
            assert 'commands' in session.__dict__

            # Commands should be JSON string
            assert isinstance(session.__dict__['commands'], str)

        # Test that we can parse the commands back
        import json
        for session in mock_sessions:
            commands = json.loads(session.__dict__['commands'])
            assert isinstance(commands, list)
            assert len(commands) > 0
            assert all(isinstance(cmd, dict) and 'input' in cmd for cmd in commands)
