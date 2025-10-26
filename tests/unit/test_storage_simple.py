"""Unit tests for threat detection storage layer."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock, patch

# Import only the functions we can safely test without sklearn dependencies
from cowrieprocessor.threat_detection.storage import (
    _serialize_for_json,
    compute_vocabulary_hash,
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

    def test_compute_vocabulary_hash_function_exists(self) -> None:
        """Test compute_vocabulary_hash function exists and is callable."""
        assert callable(compute_vocabulary_hash)

    def test_serialize_for_json_function_exists(self) -> None:
        """Test _serialize_for_json function exists and is callable."""
        assert callable(_serialize_for_json)

    def test_storage_functions_have_correct_return_types(self) -> None:
        """Test storage functions have correct return types."""
        # Test compute_vocabulary_hash return type
        mock_analyzer = Mock()
        mock_analyzer.command_vectorizer.is_fitted = False
        result = compute_vocabulary_hash(mock_analyzer)
        assert isinstance(result, str)

        # Test _serialize_for_json return type
        test_data = "test"
        result = _serialize_for_json(test_data)
        assert isinstance(result, str)
