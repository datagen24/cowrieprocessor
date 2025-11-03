"""Tests for Unicode sanitization utilities."""

import json

import pytest

from cowrieprocessor.utils.unicode_sanitizer import UnicodeSanitizer


class TestUnicodeSanitizer:
    """Test cases for UnicodeSanitizer class."""

    def test_sanitize_unicode_string_basic(self) -> None:
        """Test basic Unicode control character removal."""
        # Test null bytes and common control characters
        test_cases = [
            ("hello\x00world", "helloworld"),
            ("test\x01\x02\x03", "test"),
            ("normal text", "normal text"),
            ("", ""),
            ("\x00\x01\x02", ""),
        ]

        for input_text, expected in test_cases:
            result = UnicodeSanitizer.sanitize_unicode_string(input_text)
            assert result == expected

    def test_sanitize_unicode_string_preserve_whitespace(self) -> None:
        """Test that safe whitespace characters are preserved."""
        test_cases = [
            ("hello\tworld", "hello\tworld"),  # tab
            ("hello\nworld", "hello\nworld"),  # newline
            ("hello\rworld", "hello\rworld"),  # carriage return
            ("hello world", "hello world"),  # space
            ("hello\x00\tworld", "hello\tworld"),  # mix of safe and unsafe
        ]

        for input_text, expected in test_cases:
            result = UnicodeSanitizer.sanitize_unicode_string(input_text, preserve_whitespace=True)
            assert result == expected

    def test_sanitize_unicode_string_strict_mode(self) -> None:
        """Test strict mode with more aggressive filtering."""
        # Strict mode should remove more characters
        input_text = "hello\x08\x0b\x0cworld"  # backspace, vertical tab, form feed

        normal_result = UnicodeSanitizer.sanitize_unicode_string(input_text, strict=False)
        strict_result = UnicodeSanitizer.sanitize_unicode_string(input_text, strict=True)

        # Both should remove the problematic characters
        assert "hello" in normal_result
        assert "world" in normal_result
        assert "hello" in strict_result
        assert "world" in strict_result

    def test_sanitize_unicode_string_replacement(self) -> None:
        """Test custom replacement characters."""
        input_text = "hello\x00world"

        result = UnicodeSanitizer.sanitize_unicode_string(input_text, replacement="[NULL]")
        assert result == "hello[NULL]world"

    def test_sanitize_json_string_valid_json(self) -> None:
        """Test sanitization of valid JSON with control characters."""
        # JSON with control characters in string values
        json_with_control_chars = '{"message": "hello\\u0000world", "data": "test\\u0016value"}'

        result = UnicodeSanitizer.sanitize_json_string(json_with_control_chars)

        # Should be valid JSON
        parsed = json.loads(result)
        assert parsed["message"] == "helloworld"  # control chars removed
        assert parsed["data"] == "testvalue"  # control chars removed

    def test_sanitize_json_string_malformed_json(self) -> None:
        """Test sanitization of malformed JSON."""
        # Malformed JSON with control characters
        malformed_json = '{"message": "hello\\u0000world", "data": "test\\u0016value"'  # missing closing brace

        # Should apply string-level sanitization
        result = UnicodeSanitizer.sanitize_json_string(malformed_json)

        # Should not contain control characters
        assert "\x00" not in result
        assert "\x16" not in result

    def test_sanitize_json_object_recursive(self) -> None:
        """Test recursive sanitization of JSON objects."""
        test_obj = {
            "level1": {"message": "hello\x00world", "list": ["item1\x01", "item2\x02", "normal"]},
            "direct": "test\x03value",
        }

        result = UnicodeSanitizer._sanitize_json_object(test_obj)

        # All control characters should be removed
        assert result["level1"]["message"] == "helloworld"
        assert result["level1"]["list"] == ["item1", "item2", "normal"]
        assert result["direct"] == "testvalue"

    def test_sanitize_filename(self) -> None:
        """Test filename sanitization."""
        test_cases = [
            ("normal_file.txt", "normal_file.txt"),
            ("file\x00name.txt", "filename.txt"),
            ("../../../etc/passwd", "etc/passwd"),  # path traversal
            ("file\x00\x01\x02name.txt", "filename.txt"),
            ("", ""),
            (
                "very_long_filename_" + "x" * 1000,
                "very_long_filename_" + "x" * (512 - len("very_long_filename_")),
            ),  # length limit
        ]

        for input_filename, expected in test_cases:
            result = UnicodeSanitizer.sanitize_filename(input_filename)
            assert result == expected
            assert len(result) <= 512  # Length limit

    def test_sanitize_url(self) -> None:
        """Test URL sanitization."""
        test_cases = [
            ("https://example.com", "https://example.com"),
            ("https://example.com\x00path", "https://example.compath"),
            ("https://example.com\x01\x02\x03", "https://example.com"),
            ("", ""),
            ("very_long_url_" + "x" * 2000, "very_long_url_" + "x" * (1024 - len("very_long_url_"))),  # length limit
        ]

        for input_url, expected in test_cases:
            result = UnicodeSanitizer.sanitize_url(input_url)
            assert result == expected
            assert len(result) <= 1024  # Length limit

    def test_sanitize_command(self) -> None:
        """Test command sanitization."""
        test_cases = [
            ("ls -la", "ls -la"),
            ("echo 'hello\x00world'", "echo 'helloworld'"),
            ("cat file\x01name.txt", "cat filename.txt"),
            ("command with\ttab", "command with\ttab"),  # preserve tab
            ("multi\nline\ncommand", "multi\nline\ncommand"),  # preserve newlines
        ]

        for input_command, expected in test_cases:
            result = UnicodeSanitizer.sanitize_command(input_command)
            assert result == expected

    def test_is_safe_for_postgres_json(self) -> None:
        """Test PostgreSQL JSON safety check."""
        safe_cases = [
            "normal text",
            "hello world",
            "json: {\"key\": \"value\"}",
            "",
        ]

        unsafe_cases = [
            "text with\x00null",
            "text with\x01control",
            "text with\x16control",
            "text with\x7fdelete",
        ]

        for text in safe_cases:
            assert UnicodeSanitizer.is_safe_for_postgres_json(text)

        for text in unsafe_cases:
            assert not UnicodeSanitizer.is_safe_for_postgres_json(text)

    def test_is_safe_for_postgres_json_escape_sequences(self) -> None:
        r"""Test detection of JSON Unicode escape sequences from PostgreSQL payload::text.

        When PostgreSQL casts JSONB to text, control characters appear as escape sequences
        like \u0000 instead of actual bytes. This was causing all records to be skipped.
        """
        # Safe cases - no problematic escape sequences
        safe_cases = [
            '{"username": "test"}',  # Normal JSON text
            '{"data": "\\u0009"}',  # Tab (safe whitespace)
            '{"data": "\\u000a"}',  # Newline (safe whitespace)
            '{"data": "\\u000d"}',  # Carriage return (safe whitespace)
            '{"data": "\\u0020"}',  # Space (safe)
            '{"data": "\\u00ff"}',  # High byte (safe)
            'normal text without escapes',
        ]

        # Unsafe cases - contain problematic escape sequences
        unsafe_cases = [
            '{"username": "\\u0000test"}',  # Null byte escape
            '{"data": "attack\\u0001data"}',  # SOH control char
            '{"msg": "\\u0002\\u0003"}',  # Multiple control chars
            '{"cmd": "echo\\u0008test"}',  # Backspace
            '{"text": "data\\u001fmore"}',  # Unit separator
            '{"value": "test\\u007f"}',  # DEL character
            '{"value": "test\\u007F"}',  # DEL character (uppercase)
            '{"mix": "\\u0000\\u0001\\u007f"}',  # Multiple problematic escapes
        ]

        for text in safe_cases:
            assert UnicodeSanitizer.is_safe_for_postgres_json(text), f"Should be safe: {text}"

        for text in unsafe_cases:
            assert not UnicodeSanitizer.is_safe_for_postgres_json(text), f"Should be unsafe: {text}"

    def test_is_safe_for_postgres_json_mixed_patterns(self) -> None:
        """Test detection of both actual bytes and escape sequences together."""
        # Mix actual control bytes with escape sequences (edge case)
        unsafe_mixed = [
            'text\x00with byte and \\u0001escape',  # Both patterns
            '{"data": "\\u0000"}\x01',  # Escape sequence + actual byte
        ]

        for text in unsafe_mixed:
            assert not UnicodeSanitizer.is_safe_for_postgres_json(text), f"Should be unsafe: {repr(text)}"

    def test_validate_and_sanitize_payload_string(self) -> None:
        """Test payload validation and sanitization with string input."""
        # Valid JSON string with control characters
        payload_str = '{"eventid": "cowrie.session.connect", "message": "hello\\u0000world"}'

        result = UnicodeSanitizer.validate_and_sanitize_payload(payload_str)

        assert isinstance(result, dict)
        assert result["eventid"] == "cowrie.session.connect"
        assert result["message"] == "helloworld"  # control char removed

    def test_validate_and_sanitize_payload_dict(self) -> None:
        """Test payload validation and sanitization with dict input."""
        payload_dict = {
            "eventid": "cowrie.session.connect",
            "message": "hello\x00world",
            "data": {"nested": "value\x01here"},
        }

        result = UnicodeSanitizer.validate_and_sanitize_payload(payload_dict)

        assert result["eventid"] == "cowrie.session.connect"
        assert result["message"] == "helloworld"  # control char removed
        assert result["data"]["nested"] == "valuehere"  # control char removed

    def test_validate_and_sanitize_payload_invalid(self) -> None:
        """Test payload validation with invalid input."""
        with pytest.raises(ValueError, match="Invalid payload type"):
            UnicodeSanitizer.validate_and_sanitize_payload(123)

        with pytest.raises(ValueError, match="Invalid JSON payload"):
            UnicodeSanitizer.validate_and_sanitize_payload("{invalid json")

    def test_real_world_cowrie_examples(self) -> None:
        """Test with real-world examples from Cowrie logs."""
        # Example from the error message
        problematic_json = (
            '{"eventid": "cowrie.session.connect", "message": "Remote SSH version: \\u0016\\u0003\\u0001\\u0000"}'
        )

        result = UnicodeSanitizer.sanitize_json_string(problematic_json)
        parsed = json.loads(result)

        assert parsed["eventid"] == "cowrie.session.connect"
        assert parsed["message"] == "Remote SSH version: "  # control chars removed

    def test_edge_cases(self) -> None:
        """Test edge cases and boundary conditions."""
        # Empty input
        assert UnicodeSanitizer.sanitize_unicode_string("") == ""
        assert UnicodeSanitizer.sanitize_unicode_string(None) is None

        # Only control characters
        assert UnicodeSanitizer.sanitize_unicode_string("\x00\x01\x02\x03") == ""

        # Mixed Unicode characters
        mixed_text = "hello\x00world\x01test\x02"
        result = UnicodeSanitizer.sanitize_unicode_string(mixed_text)
        assert result == "helloworldtest"

        # Very long string
        long_text = "x" * 10000 + "\x00" + "y" * 10000
        result = UnicodeSanitizer.sanitize_unicode_string(long_text)
        assert "\x00" not in result
        assert len(result) == 20000

    def test_unicode_normalization(self) -> None:
        """Test handling of various Unicode characters."""
        # Test with actual Unicode characters (not just control chars)
        unicode_text = "hello 世界\x00test"
        result = UnicodeSanitizer.sanitize_unicode_string(unicode_text)
        assert result == "hello 世界test"

        # Test with emoji and control chars
        emoji_text = "hello 😀\x00world"
        result = UnicodeSanitizer.sanitize_unicode_string(emoji_text)
        assert result == "hello 😀world"


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_sanitize_unicode_string_function(self) -> None:
        """Test the convenience function for string sanitization."""
        from cowrieprocessor.utils.unicode_sanitizer import sanitize_unicode_string

        result = sanitize_unicode_string("hello\x00world")
        assert result == "helloworld"

    def test_sanitize_json_payload_function(self) -> None:
        """Test the convenience function for JSON payload sanitization."""
        from cowrieprocessor.utils.unicode_sanitizer import sanitize_json_payload

        payload_str = '{"message": "hello\\u0000world"}'
        result = sanitize_json_payload(payload_str)

        assert isinstance(result, dict)
        assert result["message"] == "helloworld"

    def test_is_safe_for_database_function(self) -> None:
        """Test the convenience function for database safety check."""
        from cowrieprocessor.utils.unicode_sanitizer import is_safe_for_database

        assert is_safe_for_database("normal text")
        assert not is_safe_for_database("text with\x00null")

    def test_cowrie_login_event_with_null_byte_username(self) -> None:
        """Regression test for Issue #XX: Null bytes in nested username fields.

        This test simulates the exact error scenario from the production database:
        A Cowrie login event with a null byte (\u0000) in the username field,
        which was causing PostgreSQL JSON processing errors when querying
        session_summaries.enrichment data.
        """
        # Simulate a Cowrie login.success event with null byte in username
        cowrie_event = {
            "eventid": "cowrie.login.success",
            "timestamp": "2024-11-13T17:06:45.665648+00:00",
            "session": "a1b2c3d4e5f6",
            "src_ip": "192.168.1.100",
            "username": "\x00root",  # <-- Null byte at start (actual scenario from logs)
            "password": "toor",
            "message": "login attempt",
        }

        # Sanitize the event (mimics what BulkLoader._sanitize_event does)
        sanitized = UnicodeSanitizer._sanitize_json_object(cowrie_event)

        # Verify null byte is removed from username
        assert sanitized["username"] == "root"
        assert "\x00" not in sanitized["username"]

        # Verify other fields are preserved
        assert sanitized["eventid"] == "cowrie.login.success"
        assert sanitized["session"] == "a1b2c3d4e5f6"
        assert sanitized["password"] == "toor"

        # Verify the sanitized payload is safe for PostgreSQL JSON
        import json

        payload_str = json.dumps(sanitized, ensure_ascii=False)
        assert UnicodeSanitizer.is_safe_for_postgres_json(payload_str)

    def test_cowrie_nested_enrichment_data_sanitization(self) -> None:
        """Test sanitization of deeply nested enrichment data structures.

        This simulates the structure found in session_summaries.enrichment
        which can contain nested login attempt arrays and other enrichment data.
        """
        # Simulate enrichment data with nested login attempts containing null bytes
        enrichment_data = {
            "dshield": {"country": "US", "asn": "AS12345", "network": "192.168.0.0/16"},
            "login_history": [
                {"username": "admin\x00", "password": "password123", "timestamp": "2024-11-13T10:00:00Z"},
                {"username": "\x00root\x01", "password": "toor\x02", "timestamp": "2024-11-13T11:00:00Z"},
                {"username": "user", "password": "pass", "timestamp": "2024-11-13T12:00:00Z"},  # Clean
            ],
            "metadata": {"source": "honeypot-a\x00", "sensor": "cowrie"},
        }

        # Sanitize the entire structure
        sanitized = UnicodeSanitizer._sanitize_json_object(enrichment_data)

        # Verify all null bytes removed from login history
        assert sanitized["login_history"][0]["username"] == "admin"
        assert sanitized["login_history"][1]["username"] == "root"
        assert sanitized["login_history"][1]["password"] == "toor"
        assert sanitized["login_history"][2]["username"] == "user"  # Already clean

        # Verify nested metadata sanitized
        assert sanitized["metadata"]["source"] == "honeypot-a"

        # Verify DShield data preserved (no control chars)
        assert sanitized["dshield"]["country"] == "US"

        # Verify entire structure is safe for PostgreSQL
        import json

        payload_str = json.dumps(sanitized, ensure_ascii=False)
        assert UnicodeSanitizer.is_safe_for_postgres_json(payload_str)
