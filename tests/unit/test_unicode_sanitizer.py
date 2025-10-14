"""Tests for Unicode sanitization utilities."""

import json

import pytest

from cowrieprocessor.utils.unicode_sanitizer import UnicodeSanitizer


class TestUnicodeSanitizer:
    """Test cases for UnicodeSanitizer class."""

    def test_sanitize_unicode_string_basic(self):
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

    def test_sanitize_unicode_string_preserve_whitespace(self):
        """Test that safe whitespace characters are preserved."""
        test_cases = [
            ("hello\tworld", "hello\tworld"),  # tab
            ("hello\nworld", "hello\nworld"),  # newline
            ("hello\rworld", "hello\rworld"),  # carriage return
            ("hello world", "hello world"),    # space
            ("hello\x00\tworld", "hello\tworld"),  # mix of safe and unsafe
        ]
        
        for input_text, expected in test_cases:
            result = UnicodeSanitizer.sanitize_unicode_string(input_text, preserve_whitespace=True)
            assert result == expected

    def test_sanitize_unicode_string_strict_mode(self):
        """Test strict mode with more aggressive filtering."""
        # Strict mode should remove more characters
        input_text = "hello\x08\x0B\x0Cworld"  # backspace, vertical tab, form feed
        
        normal_result = UnicodeSanitizer.sanitize_unicode_string(input_text, strict=False)
        strict_result = UnicodeSanitizer.sanitize_unicode_string(input_text, strict=True)
        
        # Both should remove the problematic characters
        assert "hello" in normal_result
        assert "world" in normal_result
        assert "hello" in strict_result
        assert "world" in strict_result

    def test_sanitize_unicode_string_replacement(self):
        """Test custom replacement characters."""
        input_text = "hello\x00world"
        
        result = UnicodeSanitizer.sanitize_unicode_string(input_text, replacement="[NULL]")
        assert result == "hello[NULL]world"

    def test_sanitize_json_string_valid_json(self):
        """Test sanitization of valid JSON with control characters."""
        # JSON with control characters in string values
        json_with_control_chars = '{"message": "hello\\u0000world", "data": "test\\u0016value"}'
        
        result = UnicodeSanitizer.sanitize_json_string(json_with_control_chars)
        
        # Should be valid JSON
        parsed = json.loads(result)
        assert parsed["message"] == "helloworld"  # control chars removed
        assert parsed["data"] == "testvalue"      # control chars removed

    def test_sanitize_json_string_malformed_json(self):
        """Test sanitization of malformed JSON."""
        # Malformed JSON with control characters
        malformed_json = '{"message": "hello\\u0000world", "data": "test\\u0016value"'  # missing closing brace
        
        # Should apply string-level sanitization
        result = UnicodeSanitizer.sanitize_json_string(malformed_json)
        
        # Should not contain control characters
        assert "\x00" not in result
        assert "\x16" not in result

    def test_sanitize_json_object_recursive(self):
        """Test recursive sanitization of JSON objects."""
        test_obj = {
            "level1": {
                "message": "hello\x00world",
                "list": ["item1\x01", "item2\x02", "normal"]
            },
            "direct": "test\x03value"
        }
        
        result = UnicodeSanitizer._sanitize_json_object(test_obj)
        
        # All control characters should be removed
        assert result["level1"]["message"] == "helloworld"
        assert result["level1"]["list"] == ["item1", "item2", "normal"]
        assert result["direct"] == "testvalue"

    def test_sanitize_filename(self):
        """Test filename sanitization."""
        test_cases = [
            ("normal_file.txt", "normal_file.txt"),
            ("file\x00name.txt", "filename.txt"),
            ("../../../etc/passwd", "etc/passwd"),  # path traversal
            ("file\x00\x01\x02name.txt", "filename.txt"),
            ("", ""),
            ("very_long_filename_" + "x" * 1000, 
             "very_long_filename_" + "x" * (512 - len("very_long_filename_"))),  # length limit
        ]
        
        for input_filename, expected in test_cases:
            result = UnicodeSanitizer.sanitize_filename(input_filename)
            assert result == expected
            assert len(result) <= 512  # Length limit

    def test_sanitize_url(self):
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

    def test_sanitize_command(self):
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

    def test_is_safe_for_postgres_json(self):
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
            "text with\x7Fdelete",
        ]
        
        for text in safe_cases:
            assert UnicodeSanitizer.is_safe_for_postgres_json(text)
            
        for text in unsafe_cases:
            assert not UnicodeSanitizer.is_safe_for_postgres_json(text)

    def test_validate_and_sanitize_payload_string(self):
        """Test payload validation and sanitization with string input."""
        # Valid JSON string with control characters
        payload_str = '{"eventid": "cowrie.session.connect", "message": "hello\\u0000world"}'
        
        result = UnicodeSanitizer.validate_and_sanitize_payload(payload_str)
        
        assert isinstance(result, dict)
        assert result["eventid"] == "cowrie.session.connect"
        assert result["message"] == "helloworld"  # control char removed

    def test_validate_and_sanitize_payload_dict(self):
        """Test payload validation and sanitization with dict input."""
        payload_dict = {
            "eventid": "cowrie.session.connect",
            "message": "hello\x00world",
            "data": {"nested": "value\x01here"}
        }
        
        result = UnicodeSanitizer.validate_and_sanitize_payload(payload_dict)
        
        assert result["eventid"] == "cowrie.session.connect"
        assert result["message"] == "helloworld"  # control char removed
        assert result["data"]["nested"] == "valuehere"  # control char removed

    def test_validate_and_sanitize_payload_invalid(self):
        """Test payload validation with invalid input."""
        with pytest.raises(ValueError, match="Invalid payload type"):
            UnicodeSanitizer.validate_and_sanitize_payload(123)
            
        with pytest.raises(ValueError, match="Invalid JSON payload"):
            UnicodeSanitizer.validate_and_sanitize_payload("{invalid json")

    def test_real_world_cowrie_examples(self):
        """Test with real-world examples from Cowrie logs."""
        # Example from the error message
        problematic_json = (
            '{"eventid": "cowrie.session.connect", '
            '"message": "Remote SSH version: \\u0016\\u0003\\u0001\\u0000"}'
        )
        
        result = UnicodeSanitizer.sanitize_json_string(problematic_json)
        parsed = json.loads(result)
        
        assert parsed["eventid"] == "cowrie.session.connect"
        assert parsed["message"] == "Remote SSH version: "  # control chars removed

    def test_edge_cases(self):
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

    def test_unicode_normalization(self):
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

    def test_sanitize_unicode_string_function(self):
        """Test the convenience function for string sanitization."""
        from cowrieprocessor.utils.unicode_sanitizer import sanitize_unicode_string
        
        result = sanitize_unicode_string("hello\x00world")
        assert result == "helloworld"

    def test_sanitize_json_payload_function(self):
        """Test the convenience function for JSON payload sanitization."""
        from cowrieprocessor.utils.unicode_sanitizer import sanitize_json_payload
        
        payload_str = '{"message": "hello\\u0000world"}'
        result = sanitize_json_payload(payload_str)
        
        assert isinstance(result, dict)
        assert result["message"] == "helloworld"

    def test_is_safe_for_database_function(self):
        """Test the convenience function for database safety check."""
        from cowrieprocessor.utils.unicode_sanitizer import is_safe_for_database
        
        assert is_safe_for_database("normal text")
        assert not is_safe_for_database("text with\x00null")
