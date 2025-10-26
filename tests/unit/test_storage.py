"""Unit tests for threat detection storage layer."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock, patch

from sqlalchemy.orm import Session, sessionmaker

# Import only the functions we can safely test without sklearn dependencies
from cowrieprocessor.threat_detection.storage import (
    _check_pgvector_available,
    _create_detection_sessions_links,
    _serialize_for_json,
    _store_command_vectors,
    compute_vocabulary_hash,
    create_analysis_checkpoint,
    get_analysis_checkpoint,
    store_longtail_analysis,
)


class TestStorageFunctions:
    """Test cases for storage functions."""

    def test_serialize_for_json_with_datetime(self) -> None:
        """Test _serialize_for_json handles datetime objects."""
        test_datetime = datetime(2025, 1, 15, 10, 30, 45, tzinfo=UTC)
        result = _serialize_for_json(test_datetime)
        assert result == "2025-01-15T10:30:45+00:00"

    def test_serialize_for_json_with_numpy_scalar(self) -> None:
        """Test _serialize_for_json handles numpy scalars."""

        # Mock numpy scalar
        class MockNumpyScalar:
            def item(self) -> int:
                return 42

        mock_scalar = MockNumpyScalar()
        result = _serialize_for_json(mock_scalar)
        assert result == 42

    def test_serialize_for_json_with_dict(self) -> None:
        """Test _serialize_for_json handles nested dictionaries."""
        test_dict = {"key1": "value1", "key2": {"nested": datetime(2025, 1, 15, 10, 30, 45, tzinfo=UTC)}}
        result = _serialize_for_json(test_dict)

        expected = {"key1": "value1", "key2": {"nested": "2025-01-15T10:30:45+00:00"}}
        assert result == expected

    def test_serialize_for_json_with_list(self) -> None:
        """Test _serialize_for_json handles lists."""
        test_list = ["string", datetime(2025, 1, 15, 10, 30, 45, tzinfo=UTC), {"nested": "dict"}]
        result = _serialize_for_json(test_list)

        expected = ["string", "2025-01-15T10:30:45+00:00", {"nested": "dict"}]
        assert result == expected

    def test_serialize_for_json_with_other_types(self) -> None:
        """Test _serialize_for_json handles other types unchanged."""
        test_data = "string"
        result = _serialize_for_json(test_data)
        assert result == "string"

    def test_check_pgvector_available_with_postgresql_and_extension(self) -> None:
        """Test _check_pgvector_available with PostgreSQL and pgvector extension."""
        mock_connection = Mock()
        mock_connection.dialect.name = 'postgresql'

        # Mock the extension check
        mock_result = Mock()
        mock_result.scalar.return_value = True
        mock_connection.execute.return_value = mock_result

        with patch('cowrieprocessor.threat_detection.storage.logger') as mock_logger:
            result = _check_pgvector_available(mock_connection)

            assert result is True
            mock_logger.info.assert_called_once_with("pgvector extension detected, vector storage enabled")

    def test_check_pgvector_available_with_postgresql_no_extension(self) -> None:
        """Test _check_pgvector_available with PostgreSQL but no pgvector extension."""
        mock_connection = Mock()
        mock_connection.dialect.name = 'postgresql'

        # Mock the extension check
        mock_result = Mock()
        mock_result.scalar.return_value = False
        mock_connection.execute.return_value = mock_result

        with patch('cowrieprocessor.threat_detection.storage.logger') as mock_logger:
            result = _check_pgvector_available(mock_connection)

            assert result is False
            mock_logger.debug.assert_called_once_with("pgvector extension not found, skipping vector storage")

    def test_check_pgvector_available_with_sqlite(self) -> None:
        """Test _check_pgvector_available with SQLite."""
        mock_connection = Mock()
        mock_connection.dialect.name = 'sqlite'

        with patch('cowrieprocessor.threat_detection.storage.logger') as mock_logger:
            result = _check_pgvector_available(mock_connection)

            assert result is False
            mock_logger.debug.assert_called_once_with("pgvector only available for PostgreSQL, skipping vector storage")

    def test_check_pgvector_available_handles_exceptions(self) -> None:
        """Test _check_pgvector_available handles exceptions gracefully."""
        mock_connection = Mock()
        mock_connection.dialect.name = 'postgresql'
        mock_connection.execute.side_effect = Exception("Database error")

        with patch('cowrieprocessor.threat_detection.storage.logger') as mock_logger:
            result = _check_pgvector_available(mock_connection)

            assert result is False
            mock_logger.warning.assert_called_once()

    def test_create_detection_sessions_links_with_no_sessions(self) -> None:
        """Test _create_detection_sessions_links with empty sessions list."""
        mock_session = Mock(spec=Session)
        detection_id = 1
        sessions_metadata = []

        # Should not execute any SQL
        _create_detection_sessions_links(mock_session, detection_id, sessions_metadata)
        mock_session.execute.assert_not_called()

    def test_create_detection_sessions_links_with_sessions(self) -> None:
        """Test _create_detection_sessions_links with session metadata."""
        mock_session = Mock(spec=Session)
        detection_id = 1
        sessions_metadata = [{"session_id": "session1"}, {"session_id": "session2"}]

        # Should not raise an exception and should execute SQL
        _create_detection_sessions_links(mock_session, detection_id, sessions_metadata)

        # Should have called execute (the insert operation)
        mock_session.execute.assert_called()

    def test_store_longtail_analysis_function_exists(self) -> None:
        """Test store_longtail_analysis function exists and is callable."""
        # Just test that the function exists and can be called with basic parameters
        # The actual database operations are tested separately
        mock_session_factory = Mock(spec=sessionmaker)

        # Test function signature and basic functionality
        assert callable(store_longtail_analysis)
        assert "session_factory" in store_longtail_analysis.__code__.co_varnames
        assert "result" in store_longtail_analysis.__code__.co_varnames

    def test_store_longtail_analysis_function_signature(self) -> None:
        """Test store_longtail_analysis has correct signature."""
        import inspect

        sig = inspect.signature(store_longtail_analysis)
        assert "session_factory" in sig.parameters
        assert "result" in sig.parameters
        assert "window_start" in sig.parameters
        assert "window_end" in sig.parameters
        assert "lookback_days" in sig.parameters

    def test_get_analysis_checkpoint_function_signature(self) -> None:
        """Test get_analysis_checkpoint has correct signature."""
        import inspect

        sig = inspect.signature(get_analysis_checkpoint)
        assert "session_factory" in sig.parameters
        assert "checkpoint_date" in sig.parameters

    def test_create_analysis_checkpoint_function_signature(self) -> None:
        """Test create_analysis_checkpoint has correct signature."""
        import inspect

        sig = inspect.signature(create_analysis_checkpoint)
        assert "session_factory" in sig.parameters
        assert "checkpoint_date" in sig.parameters

    def test_compute_vocabulary_hash_with_fitted_vectorizer(self) -> None:
        """Test compute_vocabulary_hash with fitted vectorizer."""
        # Mock analyzer with fitted vectorizer
        mock_analyzer = Mock()
        mock_analyzer.command_vectorizer.is_fitted = True
        mock_analyzer.command_vectorizer.vectorizer.vocabulary_ = {"command1": 1, "command2": 2}
        mock_analyzer.command_vectorizer.get_feature_names.return_value = ["command1", "command2"]

        result = compute_vocabulary_hash(mock_analyzer)

        assert isinstance(result, str)
        assert len(result) == 32  # MD5 hash length
        assert result != "unfitted"
        assert result != "error"

    def test_compute_vocabulary_hash_with_unfitted_vectorizer(self) -> None:
        """Test compute_vocabulary_hash with unfitted vectorizer."""
        # Mock analyzer with unfitted vectorizer
        mock_analyzer = Mock()
        mock_analyzer.command_vectorizer.is_fitted = False

        result = compute_vocabulary_hash(mock_analyzer)

        assert result == "unfitted"

    def test_compute_vocabulary_hash_handles_exceptions(self) -> None:
        """Test compute_vocabulary_hash handles exceptions gracefully."""
        # Mock analyzer that raises exception
        mock_analyzer = Mock()
        mock_analyzer.command_vectorizer.is_fitted = True
        mock_analyzer.command_vectorizer.vectorizer.vocabulary_ = {"command1": 1}
        mock_analyzer.command_vectorizer.get_feature_names.side_effect = Exception("Vectorizer error")

        with patch('cowrieprocessor.threat_detection.storage.logger') as mock_logger:
            result = compute_vocabulary_hash(mock_analyzer)

            assert result == "error"
            mock_logger.warning.assert_called_once()

    def test_store_command_vectors_with_pgvector_unavailable(self) -> None:
        """Test _store_command_vectors when pgvector is not available."""
        mock_session = Mock(spec=Session)
        mock_analyzer = Mock()
        mock_sessions = [Mock()]

        with (
            patch('cowrieprocessor.threat_detection.storage._check_pgvector_available') as mock_check,
            patch('cowrieprocessor.threat_detection.storage.logger') as mock_logger,
        ):
            mock_check.return_value = False

            _store_command_vectors(mock_session, mock_analyzer, mock_sessions, 1)

            mock_logger.info.assert_any_call("pgvector not available, skipping vector storage")

    def test_store_command_vectors_with_no_vectorizer(self) -> None:
        """Test _store_command_vectors when analyzer has no vectorizer."""
        mock_session = Mock(spec=Session)
        mock_analyzer = Mock()
        mock_sessions = [Mock()]

        with (
            patch('cowrieprocessor.threat_detection.storage._check_pgvector_available') as mock_check,
            patch('cowrieprocessor.threat_detection.storage.logger') as mock_logger,
        ):
            mock_check.return_value = True
            # Remove vectorizer attribute
            del mock_analyzer.command_vectorizer

            _store_command_vectors(mock_session, mock_analyzer, mock_sessions, 1)

            mock_logger.warning.assert_any_call("Analyzer does not have command_vectorizer attribute")

    def test_store_command_vectors_with_no_transform_method(self) -> None:
        """Test _store_command_vectors when vectorizer has no transform method."""
        mock_session = Mock(spec=Session)
        mock_analyzer = Mock()
        mock_sessions = [Mock()]

        with (
            patch('cowrieprocessor.threat_detection.storage._check_pgvector_available') as mock_check,
            patch('cowrieprocessor.threat_detection.storage.logger') as mock_logger,
        ):
            mock_check.return_value = True
            mock_analyzer.command_vectorizer = Mock()
            # Remove transform method
            del mock_analyzer.command_vectorizer.transform

            _store_command_vectors(mock_session, mock_analyzer, mock_sessions, 1)

            mock_logger.warning.assert_any_call("command_vectorizer does not have transform method")

    def test_store_command_vectors_function_exists(self) -> None:
        """Test _store_command_vectors function exists."""
        assert callable(_store_command_vectors)

    def test_storage_functions_have_correct_signatures(self) -> None:
        """Test storage functions have correct parameter types."""
        # Test function signatures
        import inspect

        # Check store_longtail_analysis
        sig = inspect.signature(store_longtail_analysis)
        assert 'session_factory' in sig.parameters
        assert 'sessionmaker' in str(sig.parameters['session_factory'].annotation)

        # Check get_analysis_checkpoint
        sig = inspect.signature(get_analysis_checkpoint)
        assert 'session_factory' in sig.parameters
        assert 'checkpoint_date' in sig.parameters
        assert 'date' in str(sig.parameters['checkpoint_date'].annotation)

        # Check create_analysis_checkpoint
        sig = inspect.signature(create_analysis_checkpoint)
        assert 'session_factory' in sig.parameters
        assert 'checkpoint_date' in sig.parameters
        assert 'date' in str(sig.parameters['checkpoint_date'].annotation)

        # Check compute_vocabulary_hash
        sig = inspect.signature(compute_vocabulary_hash)
        assert 'analyzer' in sig.parameters
