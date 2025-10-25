"""Unit tests for Enhanced DLQ CLI (cowrieprocessor.loader.dlq_enhanced_cli)."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from cowrieprocessor.loader.dlq_enhanced_cli import (
    analyze_dlq_patterns_enhanced,
    cleanup_dlq_enhanced,
    create_enhanced_procedures,
    get_dlq_health,
    main,
    process_dlq_enhanced,
)
from cowrieprocessor.loader.dlq_enhanced_cli import (
    test_enhanced_procedures as run_enhanced_tests,  # Rename to avoid pytest collision
)


class TestMainCLIParsing:
    """Test main() CLI argument parsing and routing."""

    def test_main_no_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main with no command provided.

        Given: No command line arguments
        When: Calling main
        Then: Should print help and return 0
        """
        with patch('sys.argv', ['dlq-enhanced-cli']):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Enhanced PostgreSQL DLQ Processing" in captured.out

    @patch('cowrieprocessor.loader.dlq_enhanced_cli.load_database_settings')
    @patch('cowrieprocessor.loader.dlq_enhanced_cli.create_engine_from_settings')
    @patch('cowrieprocessor.loader.dlq_enhanced_cli.create_enhanced_procedures')
    def test_main_create_command(
        self, mock_create_procs: Mock, mock_create_engine: Mock, mock_load_settings: Mock
    ) -> None:
        """Test main with create command.

        Given: Create command
        When: Calling main
        Then: Should call create_enhanced_procedures
        """
        mock_load_settings.return_value = {'database_url': 'postgresql://test'}
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        with patch('sys.argv', ['dlq-enhanced-cli', 'create']):
            result = main()

        assert result == 0
        mock_create_procs.assert_called_once_with(mock_engine)

    @patch('cowrieprocessor.loader.dlq_enhanced_cli.load_database_settings')
    @patch('cowrieprocessor.loader.dlq_enhanced_cli.create_engine_from_settings')
    @patch('cowrieprocessor.loader.dlq_enhanced_cli.process_dlq_enhanced')
    def test_main_process_command(self, mock_process: Mock, mock_create_engine: Mock, mock_load_settings: Mock) -> None:
        """Test main with process command.

        Given: Process command with filters
        When: Calling main
        Then: Should call process_dlq_enhanced with correct arguments
        """
        mock_load_settings.return_value = {'database_url': 'postgresql://test'}
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        with patch('sys.argv', ['dlq-enhanced-cli', 'process', '--limit', '100', '--priority', '1']):
            result = main()

        assert result == 0
        mock_process.assert_called_once_with(mock_engine, 100, None, 1, None)

    @patch('cowrieprocessor.loader.dlq_enhanced_cli.load_database_settings')
    @patch('cowrieprocessor.loader.dlq_enhanced_cli.create_engine_from_settings')
    @patch('cowrieprocessor.loader.dlq_enhanced_cli.get_dlq_health')
    def test_main_health_command(self, mock_health: Mock, mock_create_engine: Mock, mock_load_settings: Mock) -> None:
        """Test main with health command.

        Given: Health command
        When: Calling main
        Then: Should call get_dlq_health
        """
        mock_load_settings.return_value = {'database_url': 'postgresql://test'}
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        with patch('sys.argv', ['dlq-enhanced-cli', 'health']):
            result = main()

        assert result == 0
        mock_health.assert_called_once_with(mock_engine)

    @patch('cowrieprocessor.loader.dlq_enhanced_cli.load_database_settings')
    @patch('cowrieprocessor.loader.dlq_enhanced_cli.create_engine_from_settings')
    @patch('cowrieprocessor.loader.dlq_enhanced_cli.cleanup_dlq_enhanced')
    def test_main_cleanup_command(self, mock_cleanup: Mock, mock_create_engine: Mock, mock_load_settings: Mock) -> None:
        """Test main with cleanup command.

        Given: Cleanup command with older-than-days
        When: Calling main
        Then: Should call cleanup_dlq_enhanced
        """
        mock_load_settings.return_value = {'database_url': 'postgresql://test'}
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        with patch('sys.argv', ['dlq-enhanced-cli', 'cleanup', '--older-than-days', '60']):
            result = main()

        assert result == 0
        mock_cleanup.assert_called_once_with(mock_engine, 60)

    @patch('cowrieprocessor.loader.dlq_enhanced_cli.get_dlq_health')
    @patch('cowrieprocessor.loader.dlq_enhanced_cli.load_database_settings')
    @patch('cowrieprocessor.loader.dlq_enhanced_cli.create_engine_from_settings')
    def test_main_exception_handling(
        self,
        mock_create_engine: Mock,
        mock_load_settings: Mock,
        mock_get_health: Mock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test main with exception in command handler.

        Given: Command that raises exception
        When: Calling main
        Then: Should print error and return 1
        """
        mock_load_settings.return_value = {'database_url': 'postgresql://test'}
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        mock_get_health.side_effect = RuntimeError("Database connection failed")

        with patch('sys.argv', ['dlq-enhanced-cli', 'health']):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: Database connection failed" in captured.out


class TestCreateEnhancedProcedures:
    """Test create_enhanced_procedures function."""

    @patch('cowrieprocessor.loader.dlq_enhanced_cli.EnhancedDLQStoredProcedures')
    def test_create_procedures_postgresql(self, mock_procedures: Mock, capsys: pytest.CaptureFixture[str]) -> None:
        """Test creating procedures on PostgreSQL.

        Given: PostgreSQL engine
        When: Calling create_enhanced_procedures
        Then: Should create procedures successfully
        """
        mock_engine = MagicMock()
        mock_engine.dialect.name = 'postgresql'
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection

        create_enhanced_procedures(mock_engine)

        captured = capsys.readouterr()
        assert "Creating enhanced DLQ processing stored procedures" in captured.out
        assert "✅ Enhanced stored procedures created successfully" in captured.out
        mock_procedures.create_enhanced_dlq_procedures.assert_called_once_with(mock_connection)
        mock_connection.commit.assert_called_once()

    def test_create_procedures_sqlite(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test creating procedures on SQLite (unsupported).

        Given: SQLite engine
        When: Calling create_enhanced_procedures
        Then: Should print error and return
        """
        mock_engine = MagicMock()
        mock_engine.dialect.name = 'sqlite'

        create_enhanced_procedures(mock_engine)

        captured = capsys.readouterr()
        assert "❌ Enhanced stored procedures are only supported for PostgreSQL, not sqlite" in captured.out
        assert "Use the regular DLQ processor" in captured.out

    @patch('cowrieprocessor.loader.dlq_enhanced_cli.EnhancedDLQStoredProcedures')
    def test_create_procedures_error(self, mock_procedures: Mock, capsys: pytest.CaptureFixture[str]) -> None:
        """Test error handling during procedure creation.

        Given: PostgreSQL engine with failing procedure creation
        When: Calling create_enhanced_procedures
        Then: Should print error message
        """
        mock_engine = MagicMock()
        mock_engine.dialect.name = 'postgresql'
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection
        mock_procedures.create_enhanced_dlq_procedures.side_effect = RuntimeError("SQL syntax error")

        create_enhanced_procedures(mock_engine)

        captured = capsys.readouterr()
        assert "❌ Error creating enhanced stored procedures: SQL syntax error" in captured.out


class TestProcessDLQEnhanced:
    """Test process_dlq_enhanced function."""

    @patch('cowrieprocessor.loader.dlq_enhanced_cli.EnhancedDLQStoredProcedures')
    def test_process_basic(self, mock_procedures: Mock, capsys: pytest.CaptureFixture[str]) -> None:
        """Test basic DLQ processing.

        Given: Engine with processing stats
        When: Calling process_dlq_enhanced
        Then: Should print formatted processing report
        """
        mock_engine = MagicMock()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection

        mock_procedures.process_dlq_events_enhanced.return_value = {
            'processed': 100,
            'repaired': 85,
            'failed': 10,
            'skipped': 5,
            'processing_duration_ms': 1234.5,
            'circuit_breaker_triggered': False,
        }

        process_dlq_enhanced(mock_engine, limit=100, reason_filter='json_error', priority_filter=1)

        captured = capsys.readouterr()
        assert "=== Enhanced DLQ Processing ===" in captured.out
        assert "Filtering by reason: json_error" in captured.out
        assert "Filtering by priority: 1" in captured.out
        assert "Processed: 100" in captured.out
        assert "Success rate: 85.0%" in captured.out
        assert "Processing Duration: 1234.5ms" in captured.out

    @patch('cowrieprocessor.loader.dlq_enhanced_cli.EnhancedDLQStoredProcedures')
    def test_process_circuit_breaker_triggered(self, mock_procedures: Mock, capsys: pytest.CaptureFixture[str]) -> None:
        """Test processing with circuit breaker triggered.

        Given: Circuit breaker triggered during processing
        When: Calling process_dlq_enhanced
        Then: Should print circuit breaker warning
        """
        mock_engine = MagicMock()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection

        mock_procedures.process_dlq_events_enhanced.return_value = {
            'processed': 50,
            'repaired': 40,
            'failed': 10,
            'skipped': 0,
            'processing_duration_ms': 500.0,
            'circuit_breaker_triggered': True,
        }

        process_dlq_enhanced(mock_engine)

        captured = capsys.readouterr()
        assert "⚠️  Circuit breaker triggered - processing halted" in captured.out


class TestGetDLQHealth:
    """Test get_dlq_health function."""

    @patch('cowrieprocessor.loader.dlq_enhanced_cli.EnhancedDLQStoredProcedures')
    def test_health_basic(self, mock_procedures: Mock, capsys: pytest.CaptureFixture[str]) -> None:
        """Test basic health dashboard.

        Given: Engine with health stats
        When: Calling get_dlq_health
        Then: Should print formatted health report
        """
        mock_engine = MagicMock()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection

        mock_procedures.get_dlq_health_stats.return_value = {
            'pending_events': 150,
            'processed_events': 1000,
            'high_retry_events': 25,
            'locked_events': 10,
            'malicious_events': 5,
            'high_priority_events': 30,
            'avg_resolution_time_seconds': 45.5,
            'oldest_unresolved_event': '2025-10-20 12:00:00',
        }

        get_dlq_health(mock_engine)

        captured = capsys.readouterr()
        assert "=== DLQ Health Dashboard ===" in captured.out
        assert "Pending Events: 150" in captured.out
        assert "Processed Events: 1,000" in captured.out
        assert "High Retry Events: 25" in captured.out
        assert "Average Resolution Time: 45.5 seconds" in captured.out
        assert "Oldest Unresolved Event: 2025-10-20 12:00:00" in captured.out
        assert "✅ DLQ is operational" in captured.out

    @patch('cowrieprocessor.loader.dlq_enhanced_cli.EnhancedDLQStoredProcedures')
    def test_health_no_pending(self, mock_procedures: Mock, capsys: pytest.CaptureFixture[str]) -> None:
        """Test health dashboard with no pending events.

        Given: No pending events
        When: Calling get_dlq_health
        Then: Should print healthy status
        """
        mock_engine = MagicMock()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection

        mock_procedures.get_dlq_health_stats.return_value = {
            'pending_events': 0,
            'processed_events': 1000,
            'high_retry_events': 0,
            'locked_events': 0,
            'malicious_events': 0,
            'high_priority_events': 0,
            'avg_resolution_time_seconds': 0,
            'oldest_unresolved_event': None,
        }

        get_dlq_health(mock_engine)

        captured = capsys.readouterr()
        assert "✅ DLQ is healthy - no pending events" in captured.out

    @patch('cowrieprocessor.loader.dlq_enhanced_cli.EnhancedDLQStoredProcedures')
    def test_health_high_retry_warning(self, mock_procedures: Mock, capsys: pytest.CaptureFixture[str]) -> None:
        """Test health dashboard with high retry warning.

        Given: High number of retry events
        When: Calling get_dlq_health
        Then: Should print warning
        """
        mock_engine = MagicMock()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection

        mock_procedures.get_dlq_health_stats.return_value = {
            'pending_events': 200,
            'processed_events': 1000,
            'high_retry_events': 150,  # High!
            'locked_events': 10,
            'malicious_events': 0,
            'high_priority_events': 0,
            'avg_resolution_time_seconds': 0,
            'oldest_unresolved_event': None,
        }

        get_dlq_health(mock_engine)

        captured = capsys.readouterr()
        assert "⚠️  Warning - high number of retry events" in captured.out


class TestCleanupDLQEnhanced:
    """Test cleanup_dlq_enhanced function."""

    @patch('cowrieprocessor.loader.dlq_enhanced_cli.EnhancedDLQStoredProcedures')
    def test_cleanup_basic(self, mock_procedures: Mock, capsys: pytest.CaptureFixture[str]) -> None:
        """Test basic DLQ cleanup.

        Given: Engine with cleanup results
        When: Calling cleanup_dlq_enhanced
        Then: Should print deleted count
        """
        mock_engine = MagicMock()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection

        mock_procedures.cleanup_resolved_events_enhanced.return_value = 5000

        cleanup_dlq_enhanced(mock_engine, older_than_days=60)

        captured = capsys.readouterr()
        assert "=== DLQ Cleanup (Older than 60 days) ===" in captured.out
        assert "🗑️  Deleted 5,000 resolved DLQ events" in captured.out


class TestAnalyzeDLQPatternsEnhanced:
    """Test analyze_dlq_patterns_enhanced function."""

    def test_analyze_basic(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test basic pattern analysis.

        Given: Engine with pattern data
        When: Calling analyze_dlq_patterns_enhanced
        Then: Should print formatted analysis report
        """
        mock_engine = MagicMock()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection

        # Mock SQL query results
        mock_connection.execute.side_effect = [
            MagicMock(
                fetchall=lambda: [
                    ('json_parse_error', 100, 2.5, 25),
                    ('invalid_schema', 50, 1.2, 10),
                ]
            ),
            MagicMock(fetchall=lambda: [(1, 30), (2, 50), (3, 20)]),
            MagicMock(fetchall=lambda: [('malicious', 10), ('suspicious', 20), (None, 70)]),
        ]

        analyze_dlq_patterns_enhanced(mock_engine)

        captured = capsys.readouterr()
        assert "=== Enhanced DLQ Pattern Analysis ===" in captured.out
        assert "json_parse_error: 100 events" in captured.out
        assert "Critical (1): 30 events" in captured.out
        assert "malicious: 10 events" in captured.out
        assert "Unclassified: 70 events" in captured.out


class TestTestEnhancedProcedures:
    """Test test_enhanced_procedures function."""

    @patch('cowrieprocessor.loader.dlq_enhanced_cli.EnhancedDLQStoredProcedures')
    def test_procedures_basic(self, mock_procedures: Mock, capsys: pytest.CaptureFixture[str]) -> None:
        """Test enhanced procedures testing.

        Given: Engine with test results
        When: Calling test_enhanced_procedures
        Then: Should print test results
        """
        mock_engine = MagicMock()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection

        # Mock circuit breaker check
        mock_connection.execute.side_effect = [
            MagicMock(fetchone=lambda: (True,)),  # Circuit breaker
            MagicMock(fetchone=lambda: ('{"eventid": "cowrie.client.kex", "session": "test123"}',)),  # Repair
        ]

        mock_procedures.get_dlq_health_stats.return_value = {'pending_events': 0, 'processed_events': 100}

        run_enhanced_tests(mock_engine)

        captured = capsys.readouterr()
        assert "=== Testing Enhanced Stored Procedures ===" in captured.out
        assert "Testing circuit breaker..." in captured.out
        assert "Testing health view..." in captured.out
        assert "Testing JSON repair..." in captured.out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
