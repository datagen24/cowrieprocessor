"""Unit tests for DLQ stored procedure CLI."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

from cowrieprocessor.loader.dlq_stored_proc_cli import (
    cleanup_dlq_stored_proc,
    create_stored_procedures,
    get_dlq_stats_stored_proc,
    main,
    process_dlq_stored_proc,
    verify_stored_procedures,
)


class TestDLQStoredProcCLI:
    """Test cases for DLQ stored procedure CLI functions."""

    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_engine_from_settings')
    def test_create_stored_procedures_with_postgresql(self, mock_engine_from_settings) -> None:
        """Test create_stored_procedures with PostgreSQL."""
        mock_engine = MagicMock()
        mock_engine.dialect.name = 'postgresql'
        mock_engine_from_settings.return_value = mock_engine

        # Set up context manager for engine.connect()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection
        mock_engine.connect.return_value.__exit__.return_value = None

        with (
            patch(
                'cowrieprocessor.loader.dlq_stored_proc_cli.DLQStoredProcedures.create_dlq_processing_procedures'
            ) as mock_create,
            patch('builtins.print') as mock_print,
        ):
            create_stored_procedures(mock_engine)

            mock_create.assert_called_once_with(mock_connection)
            mock_print.assert_any_call("✅ Stored procedures created successfully")

    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_engine_from_settings')
    def test_create_stored_procedures_with_sqlite(self, mock_engine_from_settings) -> None:
        """Test create_stored_procedures with SQLite."""
        mock_engine = Mock()
        mock_engine.dialect.name = 'sqlite'
        mock_engine_from_settings.return_value = mock_engine

        with patch('builtins.print') as mock_print:
            create_stored_procedures(mock_engine)

            mock_print.assert_any_call("❌ Stored procedures are only supported for PostgreSQL, not sqlite")

    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_engine_from_settings')
    def test_create_stored_procedures_handles_exceptions(self, mock_engine_from_settings) -> None:
        """Test create_stored_procedures handles exceptions gracefully."""
        mock_engine = MagicMock()
        mock_engine.dialect.name = 'postgresql'
        mock_engine_from_settings.return_value = mock_engine

        # Set up context manager for engine.connect()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection
        mock_engine.connect.return_value.__exit__.return_value = None

        with (
            patch(
                'cowrieprocessor.loader.dlq_stored_proc_cli.DLQStoredProcedures.create_dlq_processing_procedures'
            ) as mock_create,
            patch('builtins.print') as mock_print,
        ):
            mock_create.side_effect = Exception("Database error")

            create_stored_procedures(mock_engine)

            mock_print.assert_any_call("❌ Error creating stored procedures: Database error")

    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_engine_from_settings')
    def test_process_dlq_stored_proc_with_results(self, mock_engine_from_settings) -> None:
        """Test process_dlq_stored_proc displays results correctly."""
        mock_engine = MagicMock()
        mock_engine_from_settings.return_value = mock_engine

        # Set up context manager for engine.connect()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection
        mock_engine.connect.return_value.__exit__.return_value = None

        with (
            patch(
                'cowrieprocessor.loader.dlq_stored_proc_cli.DLQStoredProcedures.process_dlq_events_stored_proc'
            ) as mock_process,
            patch('builtins.print') as mock_print,
        ):
            mock_process.return_value = {"processed": 100, "repaired": 80, "failed": 15, "skipped": 5}

            process_dlq_stored_proc(mock_engine, limit=50, reason_filter="json_parsing_failed")

            mock_process.assert_called_once_with(mock_connection, 50, "json_parsing_failed")
            mock_print.assert_any_call("=== DLQ Processing (Stored Procedures) ===")
            mock_print.assert_any_call("Processed: 100")
            mock_print.assert_any_call("Repaired: 80")
            mock_print.assert_any_call("Failed: 15")
            mock_print.assert_any_call("Skipped: 5")
            mock_print.assert_any_call("Success rate: 80.0%")

    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_engine_from_settings')
    def test_process_dlq_stored_proc_with_zero_processed(self, mock_engine_from_settings) -> None:
        """Test process_dlq_stored_proc handles zero processed events."""
        mock_engine = MagicMock()
        mock_engine_from_settings.return_value = mock_engine

        # Set up context manager for engine.connect()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection
        mock_engine.connect.return_value.__exit__.return_value = None

        with (
            patch(
                'cowrieprocessor.loader.dlq_stored_proc_cli.DLQStoredProcedures.process_dlq_events_stored_proc'
            ) as mock_process,
            patch('builtins.print') as mock_print,
        ):
            mock_process.return_value = {"processed": 0, "repaired": 0, "failed": 0, "skipped": 0}

            process_dlq_stored_proc(mock_engine)

            mock_print.assert_any_call("=== DLQ Processing (Stored Procedures) ===")
            mock_print.assert_any_call("Processed: 0")
            # Should not print success rate when no events processed

    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_engine_from_settings')
    def test_get_dlq_stats_stored_proc_with_results(self, mock_engine_from_settings) -> None:
        """Test get_dlq_stats_stored_proc displays statistics correctly."""
        mock_engine = MagicMock()
        mock_engine_from_settings.return_value = mock_engine

        # Set up context manager for engine.connect()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection
        mock_engine.connect.return_value.__exit__.return_value = None

        with (
            patch(
                'cowrieprocessor.loader.dlq_stored_proc_cli.DLQStoredProcedures.get_dlq_statistics_stored_proc'
            ) as mock_stats,
            patch('builtins.print') as mock_print,
        ):
            mock_stats.return_value = {
                "total_events": 1000,
                "unresolved_events": 150,
                "resolved_events": 850,
                "top_reasons": {"json_parsing_failed": 100, "validation_error": 50},
                "oldest_unresolved": "2025-01-01T10:00:00Z",
                "newest_unresolved": "2025-01-15T14:30:00Z",
            }

            get_dlq_stats_stored_proc(mock_engine)

            mock_stats.assert_called_once_with(mock_connection)
            mock_print.assert_any_call("=== DLQ Statistics (Stored Procedures) ===")
            mock_print.assert_any_call("Total Events: 1000")
            mock_print.assert_any_call("Unresolved Events: 150")
            mock_print.assert_any_call("Resolved Events: 850")
            mock_print.assert_any_call("\nTop Failure Reasons:")
            mock_print.assert_any_call("  json_parsing_failed: 100")
            mock_print.assert_any_call("  validation_error: 50")
            mock_print.assert_any_call("\nOldest Unresolved: 2025-01-01T10:00:00Z")
            mock_print.assert_any_call("Newest Unresolved: 2025-01-15T14:30:00Z")

    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_engine_from_settings')
    def test_get_dlq_stats_stored_proc_with_empty_reasons(self, mock_engine_from_settings) -> None:
        """Test get_dlq_stats_stored_proc handles empty top reasons."""
        mock_engine = MagicMock()
        mock_engine_from_settings.return_value = mock_engine

        # Set up context manager for engine.connect()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection
        mock_engine.connect.return_value.__exit__.return_value = None

        with (
            patch(
                'cowrieprocessor.loader.dlq_stored_proc_cli.DLQStoredProcedures.get_dlq_statistics_stored_proc'
            ) as mock_stats,
            patch('builtins.print') as mock_print,
        ):
            mock_stats.return_value = {
                "total_events": 0,
                "unresolved_events": 0,
                "resolved_events": 0,
                "top_reasons": [],
                "oldest_unresolved": None,
                "newest_unresolved": None,
            }

            get_dlq_stats_stored_proc(mock_engine)

            # Should not print top reasons or dates when empty
            mock_print.assert_any_call("=== DLQ Statistics (Stored Procedures) ===")
            mock_print.assert_any_call("Total Events: 0")

    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_engine_from_settings')
    def test_cleanup_dlq_stored_proc_with_results(self, mock_engine_from_settings) -> None:
        """Test cleanup_dlq_stored_proc displays cleanup results."""
        mock_engine = MagicMock()
        mock_engine_from_settings.return_value = mock_engine

        # Set up context manager for engine.connect()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection
        mock_engine.connect.return_value.__exit__.return_value = None

        with (
            patch(
                'cowrieprocessor.loader.dlq_stored_proc_cli.DLQStoredProcedures.cleanup_resolved_dlq_events_stored_proc'
            ) as mock_cleanup,
            patch('builtins.print') as mock_print,
        ):
            mock_cleanup.return_value = 42

            cleanup_dlq_stored_proc(mock_engine, older_than_days=7)

            mock_cleanup.assert_called_once_with(mock_connection, 7)
            mock_print.assert_any_call("=== DLQ Cleanup (Older than 7 days) ===")
            mock_print.assert_any_call("Deleted 42 resolved DLQ events")

    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_engine_from_settings')
    def test_cleanup_dlq_stored_proc_with_zero_deleted(self, mock_engine_from_settings) -> None:
        """Test cleanup_dlq_stored_proc handles zero deleted events."""
        mock_engine = MagicMock()
        mock_engine_from_settings.return_value = mock_engine

        # Set up context manager for engine.connect()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection
        mock_engine.connect.return_value.__exit__.return_value = None

        with (
            patch(
                'cowrieprocessor.loader.dlq_stored_proc_cli.DLQStoredProcedures.cleanup_resolved_dlq_events_stored_proc'
            ) as mock_cleanup,
            patch('builtins.print') as mock_print,
        ):
            mock_cleanup.return_value = 0

            cleanup_dlq_stored_proc(mock_engine)

            mock_print.assert_any_call("=== DLQ Cleanup (Older than 30 days) ===")
            mock_print.assert_any_call("Deleted 0 resolved DLQ events")

    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_engine_from_settings')
    def test_test_stored_procedures_with_results(self, mock_engine_from_settings) -> None:
        """Test verify_stored_procedures displays test results."""
        mock_engine = MagicMock()
        mock_engine_from_settings.return_value = mock_engine

        # Mock both stored procedure calls
        mock_repair_result = Mock()
        mock_repair_result.fetchone.return_value = (
            '{"eventid": "cowrie.session.connect", "timestamp": "2025-01-01T00:00:00Z"}',
        )

        mock_stats_result = Mock()
        mock_stats_result.fetchone.return_value = (100, 10, 90, {"error": 10}, "2025-01-01", "2025-01-15")

        mock_connection = MagicMock()
        mock_connection.execute.side_effect = [mock_repair_result, mock_stats_result]
        mock_engine.connect.return_value.__enter__.return_value = mock_connection
        mock_engine.connect.return_value.__exit__.return_value = None

        with (
            patch(
                'cowrieprocessor.loader.dlq_stored_proc_cli.DLQStoredProcedures.get_dlq_statistics_stored_proc'
            ) as mock_stats,
            patch('builtins.print') as mock_print,
        ):
            mock_stats.return_value = {
                "total_events": 100,
                "unresolved_events": 10,
                "resolved_events": 90,
                "top_reasons": {"error": 10},
                "oldest_unresolved": "2025-01-01",
                "newest_unresolved": "2025-01-15",
            }

            verify_stored_procedures(mock_engine)

            mock_print.assert_any_call("=== Testing Stored Procedures ===")
            mock_print.assert_any_call(
                "Test repair input: {\"eventid\": \"cowrie.client.kex\", \"session\": \"test123\""
            )
            mock_print.assert_any_call(
                "Test repair output: {\"eventid\": \"cowrie.session.connect\", \"timestamp\": \"2025-01-01T00:00:00Z\"}"
            )

    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_engine_from_settings')
    def test_test_stored_procedures_with_no_repair_result(self, mock_engine_from_settings) -> None:
        """Test verify_stored_procedures handles no repair result."""
        mock_engine = MagicMock()
        mock_engine_from_settings.return_value = mock_engine

        # Mock repair result as None
        mock_repair_result = Mock()
        mock_repair_result.fetchone.return_value = None

        mock_connection = MagicMock()
        mock_connection.execute.return_value = mock_repair_result
        mock_engine.connect.return_value.__enter__.return_value = mock_connection
        mock_engine.connect.return_value.__exit__.return_value = None

        with patch('builtins.print') as mock_print:
            verify_stored_procedures(mock_engine)

            mock_print.assert_any_call("Test repair output: No result")

    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_engine_from_settings')
    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.argparse.ArgumentParser.parse_args')
    def test_main_with_create_command(self, mock_args, mock_engine_from_settings) -> None:
        """Test main function with create command."""
        mock_args.return_value = Mock(command="create")
        mock_engine = Mock()
        mock_engine_from_settings.return_value = mock_engine

        with patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_stored_procedures') as mock_create:
            result = main()

            assert result == 0
            mock_create.assert_called_once_with(mock_engine)

    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_engine_from_settings')
    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.argparse.ArgumentParser.parse_args')
    def test_main_with_process_command(self, mock_args, mock_engine_from_settings) -> None:
        """Test main function with process command."""
        mock_args.return_value = Mock(command="process", limit=100, reason="json_parsing_failed")
        mock_engine = Mock()
        mock_engine_from_settings.return_value = mock_engine

        with patch('cowrieprocessor.loader.dlq_stored_proc_cli.process_dlq_stored_proc') as mock_process:
            result = main()

            assert result == 0
            mock_process.assert_called_once_with(mock_engine, 100, "json_parsing_failed")

    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_engine_from_settings')
    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.argparse.ArgumentParser.parse_args')
    def test_main_with_stats_command(self, mock_args, mock_engine_from_settings) -> None:
        """Test main function with stats command."""
        mock_args.return_value = Mock(command="stats")
        mock_engine = Mock()
        mock_engine_from_settings.return_value = mock_engine

        with patch('cowrieprocessor.loader.dlq_stored_proc_cli.get_dlq_stats_stored_proc') as mock_stats:
            result = main()

            assert result == 0
            mock_stats.assert_called_once_with(mock_engine)

    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_engine_from_settings')
    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.argparse.ArgumentParser.parse_args')
    def test_main_with_cleanup_command(self, mock_args, mock_engine_from_settings) -> None:
        """Test main function with cleanup command."""
        mock_args.return_value = Mock(command="cleanup", older_than_days=60)
        mock_engine = Mock()
        mock_engine_from_settings.return_value = mock_engine

        with patch('cowrieprocessor.loader.dlq_stored_proc_cli.cleanup_dlq_stored_proc') as mock_cleanup:
            result = main()

            assert result == 0
            mock_cleanup.assert_called_once_with(mock_engine, 60)

    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_engine_from_settings')
    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.argparse.ArgumentParser.parse_args')
    def test_main_with_test_command(self, mock_args, mock_engine_from_settings) -> None:
        """Test main function with test command."""
        mock_args.return_value = Mock(command="test")
        mock_engine = Mock()
        mock_engine_from_settings.return_value = mock_engine

        with patch('cowrieprocessor.loader.dlq_stored_proc_cli.verify_stored_procedures') as mock_test:
            result = main()

            assert result == 0
            mock_test.assert_called_once_with(mock_engine)

    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_engine_from_settings')
    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.argparse.ArgumentParser.parse_args')
    def test_main_with_no_command(self, mock_args, mock_engine_from_settings) -> None:
        """Test main function with no command shows help."""
        mock_args.return_value = Mock(command=None)
        mock_engine = Mock()
        mock_engine_from_settings.return_value = mock_engine

        with patch('cowrieprocessor.loader.dlq_stored_proc_cli.argparse.ArgumentParser.print_help') as mock_help:
            result = main()

            assert result == 0
            mock_help.assert_called_once()

    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_engine_from_settings')
    @patch('cowrieprocessor.loader.dlq_stored_proc_cli.argparse.ArgumentParser.parse_args')
    def test_main_handles_exceptions(self, mock_args, mock_engine_from_settings) -> None:
        """Test main function handles exceptions gracefully."""
        mock_args.return_value = Mock(command="create")
        mock_engine = Mock()
        mock_engine_from_settings.return_value = mock_engine

        with (
            patch('cowrieprocessor.loader.dlq_stored_proc_cli.create_stored_procedures') as mock_create,
            patch('builtins.print') as mock_print,
        ):
            mock_create.side_effect = Exception("Database connection failed")

            result = main()

            assert result == 1
            mock_print.assert_any_call("Error: Database connection failed")

    def test_cli_functions_have_correct_signatures(self) -> None:
        """Test CLI functions have correct parameter types."""
        # Test function signatures
        import inspect

        from cowrieprocessor.loader.dlq_stored_proc_cli import (
            cleanup_dlq_stored_proc,
            create_stored_procedures,
            get_dlq_stats_stored_proc,
            main,
            process_dlq_stored_proc,
            verify_stored_procedures,
        )

        # Check create_stored_procedures
        sig = inspect.signature(create_stored_procedures)
        assert 'engine' in sig.parameters

        # Check process_dlq_stored_proc
        sig = inspect.signature(process_dlq_stored_proc)
        assert 'engine' in sig.parameters
        assert 'limit' in sig.parameters
        assert 'reason_filter' in sig.parameters

        # Check get_dlq_stats_stored_proc
        sig = inspect.signature(get_dlq_stats_stored_proc)
        assert 'engine' in sig.parameters

        # Check cleanup_dlq_stored_proc
        sig = inspect.signature(cleanup_dlq_stored_proc)
        assert 'engine' in sig.parameters
        assert 'older_than_days' in sig.parameters

        # Check verify_stored_procedures
        sig = inspect.signature(verify_stored_procedures)
        assert 'engine' in sig.parameters

        # Check main
        sig = inspect.signature(main)
        # Compare string representation of annotation to handle type vs class differences
        assert str(sig.return_annotation) == 'int'
