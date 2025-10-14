"""Integration tests for Unicode control character handling in data processing."""

import json
from unittest.mock import Mock

import pytest

from cowrieprocessor.loader.bulk import BulkLoader
from cowrieprocessor.utils.unicode_sanitizer import UnicodeSanitizer


class TestUnicodeHandlingIntegration:
    """Integration tests for Unicode control character handling."""

    def test_bulk_loader_handles_unicode_control_chars(self):
        """Test that BulkLoader properly handles Unicode control characters."""
        # Create mock data with problematic Unicode characters
        problematic_data = [
            '{"eventid": "cowrie.session.connect", "message": "hello\\u0000world"}',
            '{"eventid": "cowrie.session.command", "input": "ls -la\\u0016"}',
            '{"eventid": "cowrie.session.file_download", "filename": "file\\u0001name.txt"}',
        ]

        # Create a mock file handle
        mock_handle = Mock()
        mock_handle.__iter__ = Mock(return_value=iter(problematic_data))

        # Create BulkLoader instance
        bulk_loader = BulkLoader(engine=Mock(), config=Mock())

        # Process the data
        results = list(bulk_loader._iter_line_by_line(mock_handle))

        # Should successfully parse all lines (no DLQ events)
        assert len(results) == 3

        for offset, payload in results:
            assert isinstance(payload, dict)
            # Verify control characters are removed
            if "message" in payload:
                assert "\x00" not in payload["message"]
            if "input" in payload:
                assert "\x16" not in payload["input"]
            if "filename" in payload:
                assert "\x01" not in payload["filename"]

    def test_dlq_processing_repairs_unicode_issues(self):
        """Test that DLQ processing can repair JSON with Unicode control characters."""
        from cowrieprocessor.loader.dlq_processor import JSONRepairStrategies

        # Malformed JSON with actual Unicode control characters (not escape sequences)
        malformed_json = '{"eventid": "cowrie.session.connect", "message": "hello\x00world\x16"}'

        # Apply repair strategies
        repaired = JSONRepairStrategies.repair_json(malformed_json)

        # Should be valid JSON
        parsed = json.loads(repaired)
        assert parsed["eventid"] == "cowrie.session.connect"
        assert parsed["message"] == "helloworld"  # control chars removed

    def test_file_processing_sanitizes_unicode(self):
        """Test that file processing sanitizes Unicode in filenames and URLs."""
        from cowrieprocessor.loader.file_processor import sanitize_filename, sanitize_url

        # Test filename sanitization
        dirty_filename = "file\x00name\x01.txt"
        clean_filename = sanitize_filename(dirty_filename)
        assert clean_filename == "filename.txt"
        assert "\x00" not in clean_filename
        assert "\x01" not in clean_filename

        # Test URL sanitization
        dirty_url = "https://example.com/path\x00\x16"
        clean_url = sanitize_url(dirty_url)
        assert clean_url == "https://example.com/path"
        assert "\x00" not in clean_url
        assert "\x16" not in clean_url

    def test_postgresql_json_compatibility(self):
        """Test that sanitized data is compatible with PostgreSQL JSON processing."""
        # Create test data that would cause PostgreSQL errors
        problematic_payload = {
            "eventid": "cowrie.session.connect",
            "message": "Remote SSH version: \u0016\u0003\u0001\u0000",
            "data": "test\u0000value",
            "nested": {"key": "value\u0016here"},
        }

        # Sanitize the payload
        sanitized_payload = UnicodeSanitizer.validate_and_sanitize_payload(problematic_payload)

        # Convert to JSON string and verify it's safe
        json_str = json.dumps(sanitized_payload, ensure_ascii=False)
        assert UnicodeSanitizer.is_safe_for_postgres_json(json_str)

        # Verify control characters are removed
        assert "\u0000" not in json_str
        assert "\u0001" not in json_str
        assert "\u0003" not in json_str
        assert "\u0016" not in json_str

    def test_real_world_error_scenario(self):
        """Test the specific error scenario from the user's report."""
        # This is the exact error from the user's message
        problematic_json = (
            '{"eventid": "cowrie.session.file_download", "message": "Remote SSH version: \\u0016\\u0003\\u0001\\u0000"}'
        )

        # Process through the sanitizer
        sanitized_json = UnicodeSanitizer.sanitize_json_string(problematic_json)
        parsed = json.loads(sanitized_json)

        # Verify the result is safe for PostgreSQL
        json_str = json.dumps(parsed, ensure_ascii=False)
        assert UnicodeSanitizer.is_safe_for_postgres_json(json_str)

        # Verify the message is cleaned
        assert parsed["message"] == "Remote SSH version: "

        # Verify the eventid is preserved
        assert parsed["eventid"] == "cowrie.session.file_download"

    def test_backfill_operation_handles_unicode(self):
        """Test that backfill operations can handle Unicode control characters."""
        # Mock event with problematic payload
        mock_event = Mock()
        mock_event.payload = (
            '{"eventid": "cowrie.session.file_download", "shasum": "abc123", "filename": "file\\u0000name.txt"}'
        )
        mock_event.session_id = "test_session"

        # Test the sanitization logic that would be used in backfill
        import json

        from cowrieprocessor.utils.unicode_sanitizer import UnicodeSanitizer

        try:
            if isinstance(mock_event.payload, str):
                sanitized_payload = UnicodeSanitizer.sanitize_json_string(mock_event.payload)
                payload = json.loads(sanitized_payload)
            else:
                payload = mock_event.payload
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            pytest.fail(f"Should not raise exception: {e}")

        # Verify the payload is clean
        assert payload["eventid"] == "cowrie.session.file_download"
        assert payload["filename"] == "filename.txt"  # control char removed

    def test_performance_with_large_data(self):
        """Test performance with large amounts of data containing Unicode control chars."""
        # Create a large dataset with control characters
        large_data = []
        for i in range(1000):
            event = {
                "id": i,
                "message": f"Event {i} with control chars \u0000\u0001\u0002",
                "data": f"Large data string {i}" + "\u0016" * 100,
            }
            large_data.append(json.dumps(event, ensure_ascii=False))

        # Process all events
        processed_count = 0
        for json_str in large_data:
            try:
                sanitized = UnicodeSanitizer.sanitize_json_string(json_str)
                json.loads(sanitized)
                processed_count += 1
            except Exception:
                pass

        # Should successfully process all events
        assert processed_count == 1000

    def test_unicode_normalization_edge_cases(self):
        """Test edge cases in Unicode normalization."""
        # Test with various Unicode categories
        test_cases = [
            ("normal text", "normal text"),
            ("text with \t tab", "text with \t tab"),  # preserved
            ("text with \n newline", "text with \n newline"),  # preserved
            ("text with \r carriage return", "text with \r carriage return"),  # preserved
            ("text with \x00 null", "text with  null"),  # removed
            ("text with \x01 start of heading", "text with  start of heading"),  # removed
            ("text with \x16 data link escape", "text with  data link escape"),  # removed
            ("text with \x7f delete", "text with  delete"),  # removed
            ("text with \x80 padding", "text with  padding"),  # removed (C1 control)
        ]

        for input_text, expected in test_cases:
            result = UnicodeSanitizer.sanitize_unicode_string(input_text)
            assert result == expected
