"""Unit tests for DLQ CLI (cowrieprocessor.loader.dlq_cli)."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Generator
from unittest.mock import MagicMock, Mock, patch

import pytest

from cowrieprocessor.loader.dlq_cli import (
    analyze_dlq_patterns,
    export_dlq_events,
    main,
    reprocess_dlq_events,
)
from cowrieprocessor.loader.dlq_cli import (
    test_hybrid_processor as run_hybrid_test,  # Rename to avoid pytest collision
)


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create temporary directory."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestMainCLIParsing:
    """Test main() CLI argument parsing and routing."""

    def test_main_no_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main with no command provided.

        Given: No command line arguments
        When: Calling main
        Then: Should print help and return 1
        """
        with patch('sys.argv', ['dlq-cli']):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "DLQ processing and analysis tools" in captured.out

    @patch('cowrieprocessor.loader.dlq_cli.analyze_dlq_patterns')
    def test_main_analyze_command(self, mock_analyze: Mock) -> None:
        """Test main with analyze command.

        Given: Analyze command with db-path
        When: Calling main
        Then: Should call analyze_dlq_patterns
        """
        with patch('sys.argv', ['dlq-cli', '--db-path', '/path/to/db.sqlite', 'analyze']):
            result = main()

        assert result == 0
        mock_analyze.assert_called_once_with('/path/to/db.sqlite')

    @patch('cowrieprocessor.loader.dlq_cli.reprocess_dlq_events')
    def test_main_reprocess_command(self, mock_reprocess: Mock) -> None:
        """Test main with reprocess command.

        Given: Reprocess command with limit and reason
        When: Calling main
        Then: Should call reprocess_dlq_events with correct arguments
        """
        with patch('sys.argv', ['dlq-cli', 'reprocess', '--limit', '100', '--reason', 'json_error']):
            result = main()

        assert result == 0
        mock_reprocess.assert_called_once_with(None, 100, 'json_error', False)

    @patch('cowrieprocessor.loader.dlq_cli.reprocess_dlq_events')
    def test_main_reprocess_with_dry_run(self, mock_reprocess: Mock) -> None:
        """Test main with reprocess command and dry-run flag.

        Given: Reprocess command with --dry-run
        When: Calling main
        Then: Should pass dry_run=True
        """
        with patch('sys.argv', ['dlq-cli', 'reprocess', '--dry-run']):
            result = main()

        assert result == 0
        mock_reprocess.assert_called_once_with(None, None, None, True)

    @patch('cowrieprocessor.loader.dlq_cli.validate_cowrie_events')
    def test_main_validate_command(self, mock_validate: Mock) -> None:
        """Test main with validate command.

        Given: Validate command with limit
        When: Calling main
        Then: Should call validate_cowrie_events
        """
        with patch('sys.argv', ['dlq-cli', 'validate', '--limit', '50']):
            result = main()

        assert result == 0
        mock_validate.assert_called_once_with(None, 50)

    @patch('cowrieprocessor.loader.dlq_cli.test_hybrid_processor')
    def test_main_test_hybrid_command(self, mock_test_hybrid: Mock) -> None:
        """Test main with test-hybrid command.

        Given: Test-hybrid command with file path
        When: Calling main
        Then: Should call test_hybrid_processor
        """
        with patch('sys.argv', ['dlq-cli', 'test-hybrid', '/path/to/cowrie.log']):
            result = main()

        assert result == 0
        mock_test_hybrid.assert_called_once_with('/path/to/cowrie.log')

    @patch('cowrieprocessor.loader.dlq_cli.export_dlq_events')
    def test_main_export_command(self, mock_export: Mock) -> None:
        """Test main with export command.

        Given: Export command with output file and filters
        When: Calling main
        Then: Should call export_dlq_events with correct arguments
        """
        with patch(
            'sys.argv',
            ['dlq-cli', 'export', '--output-file', 'export.json', '--limit', '200', '--reason', 'parse_error'],
        ):
            result = main()

        assert result == 0
        mock_export.assert_called_once_with(None, 'export.json', 200, 'parse_error')

    @patch('cowrieprocessor.loader.dlq_cli.analyze_dlq_patterns')
    def test_main_exception_handling(self, mock_analyze: Mock, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main with exception in command handler.

        Given: Analyze command that raises exception
        When: Calling main
        Then: Should print error and return 1
        """
        mock_analyze.side_effect = RuntimeError("Database connection failed")

        with patch('sys.argv', ['dlq-cli', 'analyze']):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: Database connection failed" in captured.out


class TestAnalyzeDLQPatterns:
    """Test analyze_dlq_patterns function."""

    @patch('cowrieprocessor.loader.dlq_cli.DLQProcessor')
    def test_analyze_basic(self, mock_processor_class: Mock, capsys: pytest.CaptureFixture[str]) -> None:
        """Test basic DLQ pattern analysis.

        Given: DLQProcessor with sample pattern data
        When: Calling analyze_dlq_patterns
        Then: Should print formatted analysis report
        """
        mock_processor = Mock()
        mock_processor_class.return_value = mock_processor

        mock_processor.analyze_dlq_patterns.return_value = {
            'total_events': 150,
            'by_reason': {'json_parse_error': 100, 'invalid_schema': 50},
            'by_source': {'/logs/cowrie1.json': 80, '/logs/cowrie2.json': 70},
            'common_issues': [
                {'suggested_strategy': 'repair_json'},
                {'suggested_strategy': 'repair_json'},
                {'suggested_strategy': 'skip_invalid'},
            ],
        }

        analyze_dlq_patterns('/path/to/db.sqlite')

        captured = capsys.readouterr()
        assert "=== DLQ Analysis Report ===" in captured.out
        assert "Total unresolved events: 150" in captured.out
        assert "json_parse_error: 100" in captured.out
        assert "invalid_schema: 50" in captured.out
        assert "repair_json: 2" in captured.out
        assert "skip_invalid: 1" in captured.out

    @patch('cowrieprocessor.loader.dlq_cli.DLQProcessor')
    def test_analyze_no_common_issues(self, mock_processor_class: Mock, capsys: pytest.CaptureFixture[str]) -> None:
        """Test analyze with no common issues.

        Given: DLQProcessor with empty common_issues
        When: Calling analyze_dlq_patterns
        Then: Should print "No common issues found"
        """
        mock_processor = Mock()
        mock_processor_class.return_value = mock_processor

        mock_processor.analyze_dlq_patterns.return_value = {
            'total_events': 10,
            'by_reason': {'test_error': 10},
            'by_source': {'/logs/test.json': 10},
            'common_issues': [],
        }

        analyze_dlq_patterns()

        captured = capsys.readouterr()
        assert "No common issues found" in captured.out


class TestReprocessDLQEvents:
    """Test reprocess_dlq_events function."""

    @patch('cowrieprocessor.loader.dlq_cli.DLQProcessor')
    def test_reprocess_basic(self, mock_processor_class: Mock, capsys: pytest.CaptureFixture[str]) -> None:
        """Test basic DLQ reprocessing.

        Given: DLQProcessor with reprocessing stats
        When: Calling reprocess_dlq_events
        Then: Should print formatted reprocessing report
        """
        mock_processor = Mock()
        mock_processor_class.return_value = mock_processor

        mock_processor.process_dlq_events.return_value = {'processed': 100, 'repaired': 85, 'failed': 10, 'skipped': 5}

        reprocess_dlq_events('/path/to/db.sqlite', limit=100, reason_filter='json_error')

        captured = capsys.readouterr()
        assert "=== DLQ Reprocessing ===" in captured.out
        assert "Processed: 100" in captured.out
        assert "Repaired: 85" in captured.out
        assert "Failed: 10" in captured.out
        assert "Skipped: 5" in captured.out
        assert "Success rate: 85.0%" in captured.out

    @patch('cowrieprocessor.loader.dlq_cli.DLQProcessor')
    def test_reprocess_dry_run(self, mock_processor_class: Mock, capsys: pytest.CaptureFixture[str]) -> None:
        """Test reprocess with dry-run mode.

        Given: Dry-run flag enabled
        When: Calling reprocess_dlq_events
        Then: Should print dry-run notice
        """
        mock_processor = Mock()
        mock_processor_class.return_value = mock_processor

        mock_processor.process_dlq_events.return_value = {'processed': 50, 'repaired': 40, 'failed': 5, 'skipped': 5}

        reprocess_dlq_events(dry_run=True)

        captured = capsys.readouterr()
        assert "DRY RUN MODE - No changes will be made" in captured.out

    @patch('cowrieprocessor.loader.dlq_cli.DLQProcessor')
    def test_reprocess_skip_duplicates(self, mock_processor_class: Mock, capsys: pytest.CaptureFixture[str]) -> None:
        """Test reprocess with skip_duplicates enabled.

        Given: skip_duplicates=True
        When: Calling reprocess_dlq_events
        Then: Should print duplicate handling notice
        """
        mock_processor = Mock()
        mock_processor_class.return_value = mock_processor

        mock_processor.process_dlq_events.return_value = {'processed': 100, 'repaired': 100, 'failed': 0, 'skipped': 0}

        reprocess_dlq_events(skip_duplicates=True)

        captured = capsys.readouterr()
        assert "DUPLICATE HANDLING: Updating existing events with repaired data" in captured.out
        assert "All events were successfully processed" in captured.out

    @patch('cowrieprocessor.loader.dlq_cli.DLQProcessor')
    def test_reprocess_zero_processed(self, mock_processor_class: Mock, capsys: pytest.CaptureFixture[str]) -> None:
        """Test reprocess with no events processed.

        Given: DLQProcessor returns zero processed
        When: Calling reprocess_dlq_events
        Then: Should not print success rate
        """
        mock_processor = Mock()
        mock_processor_class.return_value = mock_processor

        mock_processor.process_dlq_events.return_value = {'processed': 0, 'repaired': 0, 'failed': 0, 'skipped': 0}

        reprocess_dlq_events()

        captured = capsys.readouterr()
        assert "Processed: 0" in captured.out
        assert "Success rate" not in captured.out


class TestTestHybridProcessor:
    """Test test_hybrid_processor function."""

    @patch('cowrieprocessor.loader.dlq_cli.ImprovedHybridProcessor')
    @patch('builtins.open', new_callable=MagicMock)
    def test_hybrid_basic(
        self, mock_open: MagicMock, mock_processor_class: Mock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test basic hybrid processor testing.

        Given: File with Cowrie log lines
        When: Calling test_hybrid_processor
        Then: Should process file and print stats
        """
        mock_processor = Mock()
        mock_processor_class.return_value = mock_processor

        # Mock file reading
        mock_file = MagicMock()
        mock_file.__enter__.return_value = mock_file
        mock_file.__iter__.return_value = iter(['line1\n', 'line2\n', 'line3\n'])
        mock_open.return_value = mock_file

        # Mock processor output
        mock_processor.process_lines.return_value = [(0, {}), (1, {}), (2, {})]
        mock_processor.get_stats.return_value = {
            'total_lines': 3,
            'single_line_parsed': 2,
            'multiline_parsed': 1,
            'repaired_parsed': 0,
            'dlq_sent': 0,
        }

        run_hybrid_test('/path/to/cowrie.log')

        captured = capsys.readouterr()
        assert "=== Testing Hybrid Processor on /path/to/cowrie.log ===" in captured.out
        assert "Total lines: 3" in captured.out
        assert "Single-line parsed: 2" in captured.out
        assert "Success rate: 100.0%" in captured.out

    @patch('cowrieprocessor.loader.dlq_cli.ImprovedHybridProcessor')
    @patch('builtins.open', side_effect=FileNotFoundError)
    def test_hybrid_file_not_found(self, mock_open: Mock, mock_processor_class: Mock) -> None:
        """Test hybrid processor with missing file.

        Given: File does not exist
        When: Calling test_hybrid_processor
        Then: Should exit with code 1
        """
        with pytest.raises(SystemExit) as exc_info:
            run_hybrid_test('/nonexistent/file.log')

        assert exc_info.value.code == 1

    @patch('cowrieprocessor.loader.dlq_cli.ImprovedHybridProcessor')
    @patch('builtins.open', side_effect=RuntimeError("Permission denied"))
    def test_hybrid_processing_error(self, mock_open: Mock, mock_processor_class: Mock) -> None:
        """Test hybrid processor with processing error.

        Given: Processing raises exception
        When: Calling test_hybrid_processor
        Then: Should exit with code 1
        """
        with pytest.raises(SystemExit) as exc_info:
            run_hybrid_test('/path/to/file.log')

        assert exc_info.value.code == 1


class TestExportDLQEvents:
    """Test export_dlq_events function."""

    @patch('cowrieprocessor.loader.dlq_cli._load_database_settings_from_sensors')
    @patch('cowrieprocessor.loader.dlq_cli.create_engine_from_settings')
    @patch('cowrieprocessor.loader.dlq_cli.create_session_maker')
    def test_export_basic(
        self,
        mock_session_maker: Mock,
        mock_create_engine: Mock,
        mock_load_settings: Mock,
        temp_dir: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test basic DLQ event export.

        Given: Database with DLQ events
        When: Calling export_dlq_events
        Then: Should export events to JSON file
        """
        # Mock database setup
        mock_load_settings.return_value = {'database_url': 'sqlite:///test.db'}
        mock_engine = Mock()
        mock_create_engine.return_value = mock_engine

        mock_session = Mock()
        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__enter__.return_value = mock_session
        mock_session_maker.return_value = mock_session_factory

        # Mock DLQ events
        from datetime import UTC, datetime

        mock_event1 = Mock()
        mock_event1.id = 1
        mock_event1.ingest_id = 'ingest-123'
        mock_event1.source = '/logs/cowrie.json'
        mock_event1.source_offset = 100
        mock_event1.reason = 'json_parse_error'
        mock_event1.payload = '{"invalid": json}'
        mock_event1.metadata_json = '{"attempt": 1}'
        mock_event1.created_at = datetime(2025, 10, 25, 12, 0, 0, tzinfo=UTC)

        mock_scalars = Mock()
        mock_scalars.all.return_value = [mock_event1]
        mock_execute = Mock()
        mock_execute.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_execute

        output_file = temp_dir / "export.json"

        export_dlq_events(db_path='/path/to/db.sqlite', output_file=str(output_file))

        # Verify JSON file created
        assert output_file.exists()

        with open(output_file) as f:
            data = json.load(f)

        assert len(data) == 1
        assert data[0]['id'] == 1
        assert data[0]['reason'] == 'json_parse_error'
        assert data[0]['created_at'] == '2025-10-25T12:00:00+00:00'

        captured = capsys.readouterr()
        assert "Exported 1 DLQ events" in captured.out

    @patch('cowrieprocessor.loader.dlq_cli._load_database_settings_from_sensors')
    @patch('cowrieprocessor.loader.dlq_cli.create_engine_from_settings')
    @patch('cowrieprocessor.loader.dlq_cli.create_session_maker')
    def test_export_with_filters(
        self, mock_session_maker: Mock, mock_create_engine: Mock, mock_load_settings: Mock, temp_dir: Path
    ) -> None:
        """Test export with limit and reason filter.

        Given: Export with limit=10 and reason filter
        When: Calling export_dlq_events
        Then: Should apply filters to query
        """
        mock_load_settings.return_value = {'database_url': 'sqlite:///test.db'}
        mock_engine = Mock()
        mock_create_engine.return_value = mock_engine

        mock_session = Mock()
        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__enter__.return_value = mock_session
        mock_session_maker.return_value = mock_session_factory

        mock_scalars = Mock()
        mock_scalars.all.return_value = []
        mock_execute = Mock()
        mock_execute.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_execute

        output_file = temp_dir / "filtered_export.json"

        export_dlq_events(
            db_path='/path/to/db.sqlite', output_file=str(output_file), limit=10, reason_filter='json_parse_error'
        )

        # Verify query was executed (filters applied in SQL statement)
        assert mock_session.execute.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
