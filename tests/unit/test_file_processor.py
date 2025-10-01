"""Unit tests for file processing functionality."""

from __future__ import annotations

import pytest
from datetime import datetime

from cowrieprocessor.loader.file_processor import (
    extract_file_data,
    parse_timestamp,
    create_files_record,
    validate_file_hash,
    sanitize_filename,
    sanitize_url,
)


class TestExtractFileData:
    """Test file data extraction from events."""

    def test_valid_file_download_event(self):
        """Test extraction from valid file download event."""
        event = {
            "eventid": "cowrie.session.file_download",
            "shasum": "a" * 64,  # Valid SHA-256
            "filename": "test.txt",
            "size": 1024,
            "url": "http://example.com/test.txt",
            "timestamp": "2025-01-27T10:00:00Z",
        }
        
        result = extract_file_data(event, "session123")
        
        assert result is not None
        assert result["session_id"] == "session123"
        assert result["shasum"] == "a" * 64
        assert result["filename"] == "test.txt"
        assert result["file_size"] == 1024
        assert result["download_url"] == "http://example.com/test.txt"
        assert result["enrichment_status"] == "pending"

    def test_invalid_event_type(self):
        """Test that non-file-download events return None."""
        event = {
            "eventid": "cowrie.command.input",
            "shasum": "a" * 64,
        }
        
        result = extract_file_data(event, "session123")
        assert result is None

    def test_missing_shasum(self):
        """Test that events without shasum return None."""
        event = {
            "eventid": "cowrie.session.file_download",
            "filename": "test.txt",
        }
        
        result = extract_file_data(event, "session123")
        assert result is None

    def test_invalid_shasum_format(self):
        """Test that invalid shasum formats are rejected."""
        event = {
            "eventid": "cowrie.session.file_download",
            "shasum": "invalid_hash",
        }
        
        result = extract_file_data(event, "session123")
        assert result is None

    def test_short_shasum(self):
        """Test that short shasums are rejected."""
        event = {
            "eventid": "cowrie.session.file_download",
            "shasum": "short",
        }
        
        result = extract_file_data(event, "session123")
        assert result is None

    def test_optional_fields(self):
        """Test that optional fields are handled correctly."""
        event = {
            "eventid": "cowrie.session.file_download",
            "shasum": "a" * 64,
        }
        
        result = extract_file_data(event, "session123")
        
        assert result is not None
        assert result["filename"] is None
        assert result["file_size"] is None
        assert result["download_url"] is None

    def test_filename_sanitization(self):
        """Test that filenames are properly sanitized."""
        event = {
            "eventid": "cowrie.session.file_download",
            "shasum": "a" * 64,
            "filename": "test\x00file.txt",  # Contains null byte
        }
        
        result = extract_file_data(event, "session123")
        
        assert result is not None
        assert result["filename"] == "testfile.txt"

    def test_long_filename_truncation(self):
        """Test that long filenames are truncated."""
        long_filename = "a" * 600  # Longer than 512 char limit
        event = {
            "eventid": "cowrie.session.file_download",
            "shasum": "a" * 64,
            "filename": long_filename,
        }
        
        result = extract_file_data(event, "session123")
        
        assert result is not None
        assert len(result["filename"]) == 512
        assert result["filename"] == "a" * 512

    def test_negative_file_size(self):
        """Test that negative file sizes are handled."""
        event = {
            "eventid": "cowrie.session.file_download",
            "shasum": "a" * 64,
            "size": -100,
        }
        
        result = extract_file_data(event, "session123")
        
        assert result is not None
        assert result["file_size"] is None

    def test_invalid_file_size_type(self):
        """Test that invalid file size types are handled."""
        event = {
            "eventid": "cowrie.session.file_download",
            "shasum": "a" * 64,
            "size": "not_a_number",
        }
        
        result = extract_file_data(event, "session123")
        
        assert result is not None
        assert result["file_size"] is None

    def test_url_sanitization(self):
        """Test that URLs are properly sanitized."""
        event = {
            "eventid": "cowrie.session.file_download",
            "shasum": "a" * 64,
            "url": "http://example.com/test\x00file.txt",
        }
        
        result = extract_file_data(event, "session123")
        
        assert result is not None
        assert result["download_url"] == "http://example.com/testfile.txt"

    def test_long_url_truncation(self):
        """Test that long URLs are truncated."""
        long_url = "http://example.com/" + "a" * 1100  # Longer than 1024 char limit
        event = {
            "eventid": "cowrie.session.file_download",
            "shasum": "a" * 64,
            "url": long_url,
        }
        
        result = extract_file_data(event, "session123")
        
        assert result is not None
        assert len(result["download_url"]) == 1024


class TestParseTimestamp:
    """Test timestamp parsing functionality."""

    def test_valid_iso_timestamp(self):
        """Test parsing valid ISO timestamp."""
        result = parse_timestamp("2025-01-27T10:00:00Z")
        assert isinstance(result, datetime)

    def test_valid_iso_timestamp_with_timezone(self):
        """Test parsing ISO timestamp with timezone."""
        result = parse_timestamp("2025-01-27T10:00:00+00:00")
        assert isinstance(result, datetime)

    def test_invalid_timestamp(self):
        """Test parsing invalid timestamp."""
        result = parse_timestamp("invalid_timestamp")
        assert result is None

    def test_none_timestamp(self):
        """Test parsing None timestamp."""
        result = parse_timestamp(None)
        assert result is None

    def test_empty_timestamp(self):
        """Test parsing empty timestamp."""
        result = parse_timestamp("")
        assert result is None


class TestCreateFilesRecord:
    """Test Files record creation."""

    def test_create_files_record(self):
        """Test creating Files record from file data."""
        file_data = {
            "session_id": "session123",
            "shasum": "a" * 64,
            "filename": "test.txt",
            "file_size": 1024,
            "download_url": "http://example.com/test.txt",
            "first_seen": datetime.now(),
            "enrichment_status": "pending",
        }
        
        record = create_files_record(file_data)
        
        assert record.session_id == "session123"
        assert record.shasum == "a" * 64
        assert record.filename == "test.txt"
        assert record.file_size == 1024
        assert record.download_url == "http://example.com/test.txt"
        assert record.enrichment_status == "pending"


class TestValidateFileHash:
    """Test file hash validation."""

    def test_valid_sha256_hash(self):
        """Test validation of valid SHA-256 hash."""
        valid_hash = "a" * 64
        assert validate_file_hash(valid_hash) is True

    def test_valid_hex_hash(self):
        """Test validation of valid hex hash."""
        valid_hash = "0123456789abcdef" * 4
        assert validate_file_hash(valid_hash) is True

    def test_invalid_length(self):
        """Test validation of hash with invalid length."""
        invalid_hash = "a" * 32  # Too short
        assert validate_file_hash(invalid_hash) is False

    def test_invalid_characters(self):
        """Test validation of hash with invalid characters."""
        invalid_hash = "g" * 64  # Contains non-hex character
        assert validate_file_hash(invalid_hash) is False

    def test_none_hash(self):
        """Test validation of None hash."""
        assert validate_file_hash(None) is False

    def test_empty_hash(self):
        """Test validation of empty hash."""
        assert validate_file_hash("") is False


class TestSanitizeFilename:
    """Test filename sanitization."""

    def test_normal_filename(self):
        """Test sanitization of normal filename."""
        result = sanitize_filename("test.txt")
        assert result == "test.txt"

    def test_filename_with_null_bytes(self):
        """Test sanitization of filename with null bytes."""
        result = sanitize_filename("test\x00file.txt")
        assert result == "testfile.txt"

    def test_filename_with_path_traversal(self):
        """Test sanitization of filename with path traversal."""
        result = sanitize_filename("../../../etc/passwd")
        assert result == "etc/passwd"

    def test_long_filename(self):
        """Test sanitization of long filename."""
        long_name = "a" * 600
        result = sanitize_filename(long_name)
        assert len(result) == 512

    def test_empty_filename(self):
        """Test sanitization of empty filename."""
        result = sanitize_filename("")
        assert result == ""

    def test_none_filename(self):
        """Test sanitization of None filename."""
        result = sanitize_filename(None)
        assert result == ""


class TestSanitizeUrl:
    """Test URL sanitization."""

    def test_normal_url(self):
        """Test sanitization of normal URL."""
        result = sanitize_url("http://example.com/test.txt")
        assert result == "http://example.com/test.txt"

    def test_url_with_null_bytes(self):
        """Test sanitization of URL with null bytes."""
        result = sanitize_url("http://example.com/test\x00file.txt")
        assert result == "http://example.com/testfile.txt"

    def test_long_url(self):
        """Test sanitization of long URL."""
        long_url = "http://example.com/" + "a" * 1100
        result = sanitize_url(long_url)
        assert len(result) == 1024

    def test_empty_url(self):
        """Test sanitization of empty URL."""
        result = sanitize_url("")
        assert result == ""

    def test_none_url(self):
        """Test sanitization of None URL."""
        result = sanitize_url(None)
        assert result == ""
