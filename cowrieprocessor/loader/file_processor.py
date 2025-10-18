"""Shared file processing logic for loaders."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from ..db.models import Files


def extract_file_data(event_payload: Dict[str, Any], session_id: str) -> Optional[Dict[str, Any]]:
    """Extract file metadata from cowrie.session.file_download event.

    Args:
        event_payload: The raw event payload dictionary
        session_id: The session ID associated with the event

    Returns:
        Dictionary with file data ready for Files table insertion, or None if invalid
    """
    if event_payload.get("eventid") != "cowrie.session.file_download":
        return None

    # Extract and validate shasum
    shasum = event_payload.get("shasum")
    if not shasum or not isinstance(shasum, str):
        return None

    # Validate SHA-256 hash format (64 hex characters)
    if len(shasum) != 64 or not all(c in "0123456789abcdefABCDEF" for c in shasum):
        return None

    # Extract filename with basic validation
    filename = event_payload.get("filename")
    if filename and isinstance(filename, str):
        # Basic filename sanitization - remove null bytes and limit length
        filename = filename.replace("\x00", "").strip()
        if len(filename) > 512:  # Match Files table column length
            filename = filename[:512]
    else:
        filename = None

    # Extract file size with validation
    file_size = event_payload.get("size")
    if file_size is not None:
        try:
            file_size = int(file_size)
            if file_size < 0:  # Negative sizes are invalid
                file_size = None
        except (ValueError, TypeError):
            file_size = None

    # Extract download URL with validation
    download_url = event_payload.get("url")
    if download_url and isinstance(download_url, str):
        # Basic URL sanitization - remove null bytes and limit length
        download_url = download_url.replace("\x00", "").strip()
        if len(download_url) > 1024:  # Match Files table column length
            download_url = download_url[:1024]
    else:
        download_url = None

    # Parse timestamp
    first_seen = parse_timestamp(event_payload.get("timestamp"))

    return {
        "session_id": session_id,
        "shasum": shasum.lower(),  # Normalize to lowercase
        "filename": filename,
        "file_size": file_size,
        "download_url": download_url,
        "first_seen": first_seen,
        "enrichment_status": "pending",
    }


def parse_timestamp(timestamp_str: Optional[str]) -> Optional[datetime]:
    """Parse Cowrie timestamp string to datetime object.

    Args:
        timestamp_str: Timestamp string from Cowrie event

    Returns:
        Parsed datetime object or None if invalid
    """
    if not timestamp_str:
        return None

    try:
        # Cowrie timestamps are typically in ISO format
        if timestamp_str.endswith('Z'):
            timestamp_str = timestamp_str[:-1] + '+00:00'
        return datetime.fromisoformat(timestamp_str)
    except (ValueError, AttributeError):
        return None


def create_files_record(file_data: Dict[str, Any]) -> Files:
    """Create a Files record from extracted file data.

    Args:
        file_data: Dictionary with file metadata from extract_file_data()

    Returns:
        Files ORM record ready for database insertion
    """
    return Files(
        session_id=file_data["session_id"],
        shasum=file_data["shasum"],
        filename=file_data.get("filename"),
        file_size=file_data.get("file_size"),
        download_url=file_data.get("download_url"),
        first_seen=file_data.get("first_seen"),
        enrichment_status=file_data.get("enrichment_status", "pending"),
    )


def validate_file_hash(shasum: str | None) -> bool:
    """Validate that a string is a proper SHA-256 hash.

    Args:
        shasum: String to validate

    Returns:
        True if valid SHA-256 hash, False otherwise
    """
    if not isinstance(shasum, str):
        return False

    if len(shasum) != 64:
        return False

    try:
        # Try to decode as hex
        bytes.fromhex(shasum)
        return True
    except ValueError:
        return False


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal and other issues.

    Args:
        filename: Raw filename from event

    Returns:
        Sanitized filename safe for storage
    """
    from ..utils.unicode_sanitizer import UnicodeSanitizer

    if not filename:
        return ""

    # Use centralized Unicode sanitization
    sanitized = UnicodeSanitizer.sanitize_filename(filename)

    return sanitized


def sanitize_url(url: str) -> str:
    """Sanitize URL to prevent injection and other issues.

    Args:
        url: Raw URL from event

    Returns:
        Sanitized URL safe for storage
    """
    from ..utils.unicode_sanitizer import UnicodeSanitizer

    if not url:
        return ""

    # Use centralized Unicode sanitization
    sanitized = UnicodeSanitizer.sanitize_url(url)

    return sanitized
