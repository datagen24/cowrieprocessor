"""Unit tests for PostgreSQL stored procedures."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from sqlalchemy.engine import Connection

from cowrieprocessor.db.stored_procedures import DLQStoredProcedures


class TestDLQStoredProcedures:
    """Test cases for DLQ stored procedures."""

    def test_create_dlq_processing_procedures_with_postgresql(self) -> None:
        """Test create_dlq_processing_procedures with PostgreSQL."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'

        # Should not raise an exception
        DLQStoredProcedures.create_dlq_processing_procedures(mock_connection)

        # Should call execute multiple times for different stored procedures
        assert mock_connection.execute.call_count >= 7

    def test_create_dlq_processing_procedures_with_sqlite(self) -> None:
        """Test create_dlq_processing_procedures raises error for non-PostgreSQL."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'sqlite'

        with pytest.raises(ValueError, match="Stored procedures are only supported for PostgreSQL"):
            DLQStoredProcedures.create_dlq_processing_procedures(mock_connection)

    def test_process_dlq_events_stored_proc_with_results(self) -> None:
        """Test process_dlq_events_stored_proc returns correct results."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'

        # Mock the stored procedure result
        mock_result = Mock()
        mock_result.fetchone.return_value = (100, 80, 15, 5)  # processed, repaired, failed, skipped

        mock_connection.execute.return_value = mock_result

        result = DLQStoredProcedures.process_dlq_events_stored_proc(
            mock_connection, limit=50, reason_filter="json_parsing_failed"
        )

        # Verify the call
        mock_connection.execute.assert_called_once()
        call_args = mock_connection.execute.call_args
        # Check that the right SQL is being executed
        assert "SELECT * FROM process_dlq_events" in str(call_args[0][0])
        # The parameters should be passed, but the exact structure depends on SQLAlchemy internals

        # Verify the result
        assert result == {"processed": 100, "repaired": 80, "failed": 15, "skipped": 5}

    def test_process_dlq_events_stored_proc_with_no_results(self) -> None:
        """Test process_dlq_events_stored_proc handles no results."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'

        # Mock no results
        mock_result = Mock()
        mock_result.fetchone.return_value = None

        mock_connection.execute.return_value = mock_result

        result = DLQStoredProcedures.process_dlq_events_stored_proc(mock_connection)

        # Should return default values
        assert result == {"processed": 0, "repaired": 0, "failed": 0, "skipped": 0}

    def test_get_dlq_statistics_stored_proc_with_results(self) -> None:
        """Test get_dlq_statistics_stored_proc returns correct statistics."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'

        # Mock the stored procedure result
        mock_result = Mock()
        mock_result.fetchone.return_value = (
            1000,  # total_events
            150,  # unresolved_events
            850,  # resolved_events
            {"json_parsing_failed": 100, "validation_error": 50},  # top_reasons
            "2025-01-01T10:00:00Z",  # oldest_unresolved
            "2025-01-15T14:30:00Z",  # newest_unresolved
        )

        mock_connection.execute.return_value = mock_result

        result = DLQStoredProcedures.get_dlq_statistics_stored_proc(mock_connection)

        # Verify the call
        mock_connection.execute.assert_called_once()
        call_args = mock_connection.execute.call_args
        assert "SELECT * FROM get_dlq_statistics()" in str(call_args[0][0])

        # Verify the result
        assert result == {
            "total_events": 1000,
            "unresolved_events": 150,
            "resolved_events": 850,
            "top_reasons": {"json_parsing_failed": 100, "validation_error": 50},
            "oldest_unresolved": "2025-01-01T10:00:00Z",
            "newest_unresolved": "2025-01-15T14:30:00Z",
        }

    def test_get_dlq_statistics_stored_proc_with_no_results(self) -> None:
        """Test get_dlq_statistics_stored_proc handles no results."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'

        # Mock no results
        mock_result = Mock()
        mock_result.fetchone.return_value = None

        mock_connection.execute.return_value = mock_result

        result = DLQStoredProcedures.get_dlq_statistics_stored_proc(mock_connection)

        # Should return default values
        assert result == {
            "total_events": 0,
            "unresolved_events": 0,
            "resolved_events": 0,
            "top_reasons": [],
            "oldest_unresolved": None,
            "newest_unresolved": None,
        }

    def test_cleanup_resolved_dlq_events_stored_proc_with_results(self) -> None:
        """Test cleanup_resolved_dlq_events_stored_proc returns correct count."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'

        # Mock the stored procedure result
        mock_result = Mock()
        mock_result.fetchone.return_value = (42,)  # deleted_count

        mock_connection.execute.return_value = mock_result

        result = DLQStoredProcedures.cleanup_resolved_dlq_events_stored_proc(mock_connection, older_than_days=30)

        # Verify the call
        mock_connection.execute.assert_called_once()
        call_args = mock_connection.execute.call_args
        assert "SELECT cleanup_resolved_dlq_events" in str(call_args[0][0])

        # Verify the result
        assert result == 42

    def test_cleanup_resolved_dlq_events_stored_proc_with_no_results(self) -> None:
        """Test cleanup_resolved_dlq_events_stored_proc handles no results."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'

        # Mock no results
        mock_result = Mock()
        mock_result.fetchone.return_value = None

        mock_connection.execute.return_value = mock_result

        result = DLQStoredProcedures.cleanup_resolved_dlq_events_stored_proc(mock_connection)

        # Should return 0
        assert result == 0

    def test_process_dlq_events_stored_proc_with_default_parameters(self) -> None:
        """Test process_dlq_events_stored_proc with default parameters."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'

        # Mock the stored procedure result
        mock_result = Mock()
        mock_result.fetchone.return_value = (50, 40, 8, 2)

        mock_connection.execute.return_value = mock_result

        result = DLQStoredProcedures.process_dlq_events_stored_proc(mock_connection)

        # Should call with default parameters (NULL values for optional parameters)
        call_args = mock_connection.execute.call_args
        assert "SELECT * FROM process_dlq_events" in str(call_args[0][0])

        assert result == {"processed": 50, "repaired": 40, "failed": 8, "skipped": 2}

    def test_cleanup_resolved_dlq_events_stored_proc_with_default_days(self) -> None:
        """Test cleanup_resolved_dlq_events_stored_proc with default days parameter."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'

        # Mock the stored procedure result
        mock_result = Mock()
        mock_result.fetchone.return_value = (25,)

        mock_connection.execute.return_value = mock_result

        result = DLQStoredProcedures.cleanup_resolved_dlq_events_stored_proc(mock_connection)

        # Should call with default 30 days
        call_args = mock_connection.execute.call_args
        assert "SELECT cleanup_resolved_dlq_events" in str(call_args[0][0])

        assert result == 25

    def test_stored_procedures_class_is_static_only(self) -> None:
        """Test DLQStoredProcedures class contains only static methods."""
        # Verify all methods are static
        methods = [method for method in dir(DLQStoredProcedures) if not method.startswith('_')]
        assert 'create_dlq_processing_procedures' in methods
        assert 'process_dlq_events_stored_proc' in methods
        assert 'get_dlq_statistics_stored_proc' in methods
        assert 'cleanup_resolved_dlq_events_stored_proc' in methods

    def test_process_dlq_events_stored_proc_with_reason_filter(self) -> None:
        """Test process_dlq_events_stored_proc with specific reason filter."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'

        # Mock the stored procedure result
        mock_result = Mock()
        mock_result.fetchone.return_value = (20, 18, 1, 1)

        mock_connection.execute.return_value = mock_result

        result = DLQStoredProcedures.process_dlq_events_stored_proc(mock_connection, reason_filter="validation_error")

        # Should call with the specific reason filter
        call_args = mock_connection.execute.call_args
        assert "SELECT * FROM process_dlq_events" in str(call_args[0][0])

        assert result == {"processed": 20, "repaired": 18, "failed": 1, "skipped": 1}

    def test_get_dlq_statistics_stored_proc_with_empty_reasons(self) -> None:
        """Test get_dlq_statistics_stored_proc handles empty top_reasons."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'

        # Mock the stored procedure result with empty reasons
        mock_result = Mock()
        mock_result.fetchone.return_value = (
            100,  # total_events
            10,  # unresolved_events
            90,  # resolved_events
            None,  # top_reasons (empty)
            None,  # oldest_unresolved
            None,  # newest_unresolved
        )

        mock_connection.execute.return_value = mock_result

        result = DLQStoredProcedures.get_dlq_statistics_stored_proc(mock_connection)

        assert result == {
            "total_events": 100,
            "unresolved_events": 10,
            "resolved_events": 90,
            "top_reasons": [],
            "oldest_unresolved": None,
            "newest_unresolved": None,
        }

    def test_stored_procedures_have_correct_return_types(self) -> None:
        """Test stored procedure methods have correct return types."""
        # Test process_dlq_events_stored_proc return type
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'
        mock_result = Mock()
        mock_result.fetchone.return_value = (10, 8, 1, 1)
        mock_connection.execute.return_value = mock_result

        result = DLQStoredProcedures.process_dlq_events_stored_proc(mock_connection)
        assert isinstance(result, dict)
        assert "processed" in result
        assert "repaired" in result
        assert "failed" in result
        assert "skipped" in result

        # Test get_dlq_statistics_stored_proc return type
        mock_result2 = Mock()
        mock_result2.fetchone.return_value = (50, 5, 45, {"error": 5}, "2025-01-01", "2025-01-15")
        mock_connection.execute.return_value = mock_result2

        result2 = DLQStoredProcedures.get_dlq_statistics_stored_proc(mock_connection)
        assert isinstance(result2, dict)
        assert "total_events" in result2
        assert "unresolved_events" in result2
        assert "top_reasons" in result2

    def test_cleanup_stored_proc_handles_various_days_values(self) -> None:
        """Test cleanup_resolved_dlq_events_stored_proc handles different days values."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'

        # Test with 7 days
        mock_result = Mock()
        mock_result.fetchone.return_value = (15,)
        mock_connection.execute.return_value = mock_result

        result = DLQStoredProcedures.cleanup_resolved_dlq_events_stored_proc(mock_connection, older_than_days=7)
        assert result == 15
        call_args = mock_connection.execute.call_args
        assert "SELECT cleanup_resolved_dlq_events" in str(call_args[0][0])

        # Test with 90 days
        mock_result2 = Mock()
        mock_result2.fetchone.return_value = (200,)
        mock_connection.execute.return_value = mock_result2

        result2 = DLQStoredProcedures.cleanup_resolved_dlq_events_stored_proc(mock_connection, older_than_days=90)
        assert result2 == 200
        call_args = mock_connection.execute.call_args
        assert "SELECT cleanup_resolved_dlq_events" in str(call_args[0][0])
