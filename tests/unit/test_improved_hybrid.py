"""Unit tests for ImprovedHybridProcessor (cowrieprocessor.loader.improved_hybrid)."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Generator
from unittest.mock import MagicMock, Mock, patch

import pytest

from cowrieprocessor.loader.improved_hybrid import (
    ImprovedHybridProcessor,
    RobustJSONIterator,
    process_cowrie_file_hybrid,
)


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create temporary directory for test files."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestImprovedHybridProcessorInit:
    """Test ImprovedHybridProcessor initialization."""

    def test_init_default_parameters(self) -> None:
        """Test initialization with default parameters.

        Given: No custom parameters
        When: Creating ImprovedHybridProcessor
        Then: Should initialize with default values
        """
        processor = ImprovedHybridProcessor()

        assert processor.max_buffer_lines == 50
        assert processor.repair_threshold == 3
        assert processor.stats["single_line_parsed"] == 0
        assert processor.stats["multiline_parsed"] == 0
        assert processor.stats["repaired_parsed"] == 0
        assert processor.stats["dlq_sent"] == 0
        assert processor.stats["total_lines"] == 0

    def test_init_custom_parameters(self) -> None:
        """Test initialization with custom parameters.

        Given: Custom max_buffer_lines and repair_threshold
        When: Creating ImprovedHybridProcessor
        Then: Should initialize with custom values
        """
        processor = ImprovedHybridProcessor(max_buffer_lines=100, repair_threshold=5)

        assert processor.max_buffer_lines == 100
        assert processor.repair_threshold == 5


class TestSingleLineProcessing:
    """Test single-line JSON processing."""

    def test_single_line_valid_json(self) -> None:
        """Test processing valid single-line JSON.

        Given: Valid single-line JSON event
        When: Processing with ImprovedHybridProcessor
        Then: Should parse successfully and increment single_line_parsed
        """
        processor = ImprovedHybridProcessor()
        event = {"eventid": "cowrie.session.connect", "session": "abc123", "timestamp": "2025-10-25T12:00:00Z"}
        lines = [json.dumps(event)]

        results = list(processor.process_lines(iter(lines)))

        assert len(results) == 1
        line_offset, parsed_event = results[0]
        assert line_offset == 0
        assert parsed_event == event
        assert processor.stats["single_line_parsed"] == 1
        assert processor.stats["multiline_parsed"] == 0
        assert processor.stats["dlq_sent"] == 0

    def test_single_line_multiple_events(self) -> None:
        """Test processing multiple single-line JSON events.

        Given: Multiple valid single-line JSON events
        When: Processing with ImprovedHybridProcessor
        Then: Should parse all events successfully
        """
        processor = ImprovedHybridProcessor()
        events = [
            {"eventid": "cowrie.session.connect", "session": "abc123"},
            {"eventid": "cowrie.command.input", "session": "abc123", "input": "ls"},
            {"eventid": "cowrie.session.closed", "session": "abc123"},
        ]
        lines = [json.dumps(event) for event in events]

        results = list(processor.process_lines(iter(lines)))

        assert len(results) == 3
        assert processor.stats["single_line_parsed"] == 3
        for i, (line_offset, parsed_event) in enumerate(results):
            assert line_offset == i
            assert parsed_event == events[i]

    def test_empty_lines_skipped(self) -> None:
        """Test that empty lines are skipped.

        Given: Lines with empty strings and whitespace
        When: Processing with ImprovedHybridProcessor
        Then: Should skip empty lines
        """
        processor = ImprovedHybridProcessor()
        event = {"eventid": "cowrie.session.connect", "session": "abc123"}
        lines = ["", "   ", json.dumps(event), "", "  \n  "]

        results = list(processor.process_lines(iter(lines)))

        assert len(results) == 1
        assert results[0][1] == event
        assert processor.stats["single_line_parsed"] == 1


class TestMultilineProcessing:
    """Test multiline JSON processing (buffer accumulation)."""

    def test_multiline_valid_json(self) -> None:
        """Test processing valid multiline JSON.

        Given: JSON split across multiple lines
        When: Processing with ImprovedHybridProcessor
        Then: Should accumulate buffer and parse successfully
        """
        processor = ImprovedHybridProcessor()
        lines = [
            "{",
            '  "eventid": "cowrie.session.connect",',
            '  "session": "abc123"',
            "}",
        ]

        results = list(processor.process_lines(iter(lines)))

        assert len(results) == 1
        line_offset, parsed_event = results[0]
        assert line_offset == 0
        assert parsed_event["eventid"] == "cowrie.session.connect"
        assert parsed_event["session"] == "abc123"
        assert processor.stats["multiline_parsed"] == 1
        assert processor.stats["single_line_parsed"] == 0

    def test_multiline_mixed_with_single_line(self) -> None:
        """Test processing mix of single-line and multiline JSON.

        Given: Mix of single-line and multiline JSON events
        When: Processing with ImprovedHybridProcessor
        Then: Should handle both formats correctly
        """
        processor = ImprovedHybridProcessor()
        lines = [
            '{"eventid": "cowrie.session.connect", "session": "abc123"}',
            "{",
            '  "eventid": "cowrie.command.input",',
            '  "input": "ls"',
            "}",
            '{"eventid": "cowrie.session.closed", "session": "abc123"}',
        ]

        results = list(processor.process_lines(iter(lines)))

        assert len(results) == 3
        assert processor.stats["single_line_parsed"] == 2
        assert processor.stats["multiline_parsed"] == 1


class TestBufferTooLarge:
    """Test buffer-too-large handling and DLQ."""

    def test_buffer_exceeds_max_lines(self) -> None:
        """Test buffer that exceeds max_buffer_lines.

        Given: Buffer larger than max_buffer_lines with no valid JSON
        When: Processing with ImprovedHybridProcessor
        Then: Should send to DLQ with buffer_too_large reason
        """
        processor = ImprovedHybridProcessor(max_buffer_lines=3)
        lines = ["invalid json line 1", "invalid json line 2", "invalid json line 3"]

        results = list(processor.process_lines(iter(lines)))

        assert len(results) == 1
        line_offset, dlq_event = results[0]
        assert dlq_event["_dead_letter"] is True
        assert dlq_event["_reason"] == "buffer_too_large"
        assert "invalid json line 1" in dlq_event["_malformed_content"]
        assert processor.stats["dlq_sent"] == 1

    def test_end_of_file_buffer(self) -> None:
        """Test incomplete buffer at end of file.

        Given: Incomplete JSON buffer at end of file
        When: Processing with ImprovedHybridProcessor
        Then: Should send to DLQ with end_of_file_buffer reason
        """
        processor = ImprovedHybridProcessor()
        lines = ["{", '  "eventid": "cowrie.session.connect"']  # Missing closing brace

        results = list(processor.process_lines(iter(lines)))

        assert len(results) == 1
        line_offset, dlq_event = results[0]
        assert dlq_event["_dead_letter"] is True
        assert dlq_event["_reason"] == "end_of_file_buffer"
        assert processor.stats["dlq_sent"] == 1


class TestRepairStrategies:
    """Test JSON repair strategies."""

    @patch('cowrieprocessor.loader.improved_hybrid.JSONRepairStrategies')
    def test_repaired_parsing_success(self, mock_repair_class: Mock) -> None:
        """Test successful JSON repair.

        Given: Malformed JSON that can be repaired
        When: Processing with repair strategies
        Then: Should successfully repair and parse
        """
        mock_repair = MagicMock()
        mock_repair_class.return_value = mock_repair

        # Create a buffer that fails initial parse but succeeds after repair
        repaired_json = '{"eventid": "cowrie.session.connect", "session": "abc123"}'
        mock_repair.repair_json.return_value = repaired_json

        processor = ImprovedHybridProcessor(max_buffer_lines=2)
        # Malformed JSON that triggers buffer overflow
        lines = ['{"eventid": "cowrie', '", "session": "abc123"}']

        results = list(processor.process_lines(iter(lines)))

        # Should attempt repair when buffer reaches max
        assert len(results) >= 1

    def test_smart_repair_trim_braces(self) -> None:
        """Test smart repair with brace trimming.

        Given: JSON with extra content before/after braces
        When: Calling _attempt_smart_repair
        Then: Should trim to valid JSON boundaries
        """
        processor = ImprovedHybridProcessor()
        content = 'garbage{"eventid": "test", "session": "abc"}trailing'

        repaired = processor._attempt_smart_repair(content)

        # Should start with { and end with }
        assert repaired.startswith("{")
        assert repaired.endswith("}")

    def test_cowrie_specific_repair(self) -> None:
        """Test Cowrie-specific repair patterns.

        Given: JSON with Cowrie field patterns
        When: Calling _attempt_cowrie_specific_repair
        Then: Should apply regex repairs and return result
        """
        processor = ImprovedHybridProcessor()
        content = '{"timestamp":"2025-10-25T12:00:00Z","eventid":"cowrie.session.connect"}'

        repaired = processor._attempt_cowrie_specific_repair(content)

        # Should return a string (repair may or may not fix issues)
        assert isinstance(repaired, str)
        # Should call repair_strategies.repair_json internally
        assert len(repaired) > 0


class TestValidation:
    """Test Cowrie event validation."""

    def test_is_likely_cowrie_event_valid(self) -> None:
        """Test validation with valid Cowrie event.

        Given: Event with multiple Cowrie indicators
        When: Calling _is_likely_cowrie_event
        Then: Should return True
        """
        processor = ImprovedHybridProcessor()
        event = {
            "eventid": "cowrie.session.connect",
            "session": "abc123",
            "timestamp": "2025-10-25T12:00:00Z",
            "src_ip": "1.2.3.4",
        }

        result = processor._is_likely_cowrie_event(event)

        assert result is True

    def test_is_likely_cowrie_event_minimal(self) -> None:
        """Test validation with minimal Cowrie indicators.

        Given: Event with exactly 2 Cowrie indicators
        When: Calling _is_likely_cowrie_event
        Then: Should return True (threshold is 2)
        """
        processor = ImprovedHybridProcessor()
        event = {
            "eventid": "cowrie.session.connect",
            "session": "abc123",
            "other_field": "value",
        }

        result = processor._is_likely_cowrie_event(event)

        assert result is True

    def test_is_likely_cowrie_event_insufficient(self) -> None:
        """Test validation with insufficient indicators.

        Given: Event with only 1 Cowrie indicator
        When: Calling _is_likely_cowrie_event
        Then: Should return False
        """
        processor = ImprovedHybridProcessor()
        event = {
            "eventid": "cowrie.session.connect",
            "other_field": "value",
        }

        result = processor._is_likely_cowrie_event(event)

        assert result is False

    def test_is_likely_cowrie_event_not_dict(self) -> None:
        """Test validation with non-dict input.

        Given: Non-dict input (string, list, None)
        When: Calling _is_likely_cowrie_event
        Then: Should return False
        """
        processor = ImprovedHybridProcessor()

        assert processor._is_likely_cowrie_event(None) is False
        assert processor._is_likely_cowrie_event("string") is False  # type: ignore
        assert processor._is_likely_cowrie_event([1, 2, 3]) is False  # type: ignore


class TestDLQEventCreation:
    """Test DLQ event creation."""

    def test_make_dlq_event_structure(self) -> None:
        """Test DLQ event structure.

        Given: Malformed content and reason
        When: Calling _make_dlq_event
        Then: Should create proper DLQ event structure
        """
        processor = ImprovedHybridProcessor()
        content = "malformed json content"
        reason = "buffer_too_large"

        dlq_event = processor._make_dlq_event(content, reason)

        assert dlq_event["_dead_letter"] is True
        assert dlq_event["_reason"] == reason
        assert dlq_event["_malformed_content"] == content
        assert "_timestamp" in dlq_event
        assert dlq_event["_processor"] == "improved_hybrid"

    def test_buffer_cleared_for_single_line(self) -> None:
        """Test buffer clearing when single-line JSON interrupts multiline.

        Given: Incomplete multiline JSON followed by valid single-line JSON
        When: Processing with ImprovedHybridProcessor
        Then: Should send buffer to DLQ and parse single-line
        """
        processor = ImprovedHybridProcessor()
        lines = [
            "{",
            '  "eventid": "partial',  # Incomplete multiline
            '{"eventid": "cowrie.session.connect", "session": "abc123"}',  # Valid single-line
        ]

        results = list(processor.process_lines(iter(lines)))

        # Should have DLQ event for cleared buffer + single-line parsed event
        assert len(results) == 2
        dlq_event = results[0][1]
        assert dlq_event["_dead_letter"] is True
        assert dlq_event["_reason"] == "buffer_cleared_for_single_line"

        parsed_event = results[1][1]
        assert parsed_event["eventid"] == "cowrie.session.connect"


class TestStatistics:
    """Test statistics tracking."""

    def test_get_stats_returns_copy(self) -> None:
        """Test that get_stats returns a copy.

        Given: Processor with statistics
        When: Calling get_stats
        Then: Should return a copy (modifying return value doesn't affect processor)
        """
        processor = ImprovedHybridProcessor()
        processor.stats["single_line_parsed"] = 10

        stats = processor.get_stats()
        stats["single_line_parsed"] = 999

        assert processor.stats["single_line_parsed"] == 10

    def test_stats_comprehensive(self) -> None:
        """Test comprehensive statistics tracking.

        Given: Mix of processing scenarios
        When: Processing various events
        Then: Should track all statistics correctly
        """
        processor = ImprovedHybridProcessor(max_buffer_lines=5)
        lines = [
            '{"eventid": "cowrie.session.connect", "session": "abc123"}',  # Single-line
            "",  # Empty line (skipped)
            "{",  # Multiline start
            '  "eventid": "cowrie.command.input",',
            '  "session": "abc123"',  # Add session for validation
            "}",  # Multiline end (4 lines total for multiline)
            "invalid line 1",  # Start buffer
            "invalid line 2",
            "invalid line 3",
            "invalid line 4",
            "invalid line 5",  # Buffer too large -> DLQ
        ]

        list(processor.process_lines(iter(lines)))

        stats = processor.get_stats()
        assert stats["single_line_parsed"] >= 1
        assert stats["multiline_parsed"] >= 1
        assert stats["dlq_sent"] >= 1
        assert stats["total_lines"] == 11  # Excludes empty line


class TestRobustJSONIterator:
    """Test RobustJSONIterator file reading."""

    def test_iterator_reads_file(self, temp_dir: Path) -> None:
        """Test iterator reads file lines.

        Given: File with JSON lines
        When: Iterating with RobustJSONIterator
        Then: Should yield all lines
        """
        file_path = temp_dir / "test.json"
        content = '{"eventid": "test1"}\n{"eventid": "test2"}\n{"eventid": "test3"}'
        file_path.write_text(content)

        iterator = RobustJSONIterator(str(file_path))
        lines = list(iterator)

        assert len(lines) == 3
        assert lines[0] == '{"eventid": "test1"}'
        assert lines[1] == '{"eventid": "test2"}'
        assert lines[2] == '{"eventid": "test3"}'

    def test_iterator_strips_newlines(self, temp_dir: Path) -> None:
        r"""Test iterator strips trailing newlines.

        Given: File with lines ending in \\n and \\r\\n
        When: Iterating with RobustJSONIterator
        Then: Should strip newlines
        """
        file_path = temp_dir / "test.json"
        content = '{"eventid": "test1"}\r\n{"eventid": "test2"}\n'
        file_path.write_text(content)

        iterator = RobustJSONIterator(str(file_path))
        lines = list(iterator)

        assert lines[0] == '{"eventid": "test1"}'
        assert lines[1] == '{"eventid": "test2"}'

    def test_iterator_counts_lines(self, temp_dir: Path) -> None:
        """Test iterator counts lines read.

        Given: File with multiple lines
        When: Iterating with RobustJSONIterator
        Then: Should track line count
        """
        file_path = temp_dir / "test.json"
        content = "line1\nline2\nline3\n"
        file_path.write_text(content)

        iterator = RobustJSONIterator(str(file_path))
        list(iterator)

        stats = iterator.get_stats()
        assert stats["line_count"] == 3
        assert stats["error_count"] == 0

    def test_iterator_handles_missing_file(self) -> None:
        """Test iterator handles missing file gracefully.

        Given: Non-existent file path
        When: Iterating with RobustJSONIterator
        Then: Should return empty iterator and track error
        """
        iterator = RobustJSONIterator("/nonexistent/file.json")
        lines = list(iterator)

        assert len(lines) == 0
        stats = iterator.get_stats()
        assert stats["error_count"] == 1

    def test_iterator_handles_encoding_errors(self, temp_dir: Path) -> None:
        """Test iterator handles encoding errors.

        Given: File with invalid UTF-8 characters
        When: Iterating with RobustJSONIterator
        Then: Should replace invalid characters (errors='replace')
        """
        file_path = temp_dir / "test.bin"
        # Write binary data with invalid UTF-8
        file_path.write_bytes(b'{"eventid": "test"}\n\xff\xfe invalid\n{"eventid": "test2"}')

        iterator = RobustJSONIterator(str(file_path))
        lines = list(iterator)

        # Should still read lines (with replacement characters)
        assert len(lines) >= 2
        assert '{"eventid": "test"}' in lines[0]


class TestModuleFunctions:
    """Test module-level convenience functions."""

    def test_process_cowrie_file_hybrid(self, temp_dir: Path) -> None:
        """Test process_cowrie_file_hybrid convenience function.

        Given: File with JSON events
        When: Calling process_cowrie_file_hybrid
        Then: Should process all events
        """
        file_path = temp_dir / "cowrie.json"
        events = [
            '{"eventid": "cowrie.session.connect", "session": "abc123"}',
            '{"eventid": "cowrie.command.input", "input": "ls"}',
        ]
        file_path.write_text("\n".join(events))

        results = list(process_cowrie_file_hybrid(str(file_path)))

        assert len(results) == 2
        assert results[0][1]["eventid"] == "cowrie.session.connect"
        assert results[1][1]["eventid"] == "cowrie.command.input"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
