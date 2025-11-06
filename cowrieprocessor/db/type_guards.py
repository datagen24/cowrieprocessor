"""Type guards for safe ORM column access in SQLAlchemy 2.0.

This module provides type-safe access patterns for JSON columns and ORM models
to prevent type conflicts where Column[Any] objects are incorrectly treated as dict objects.
"""

from __future__ import annotations

from typing import Any, TypeGuard

from .models import RawEvent, SessionSummary


def is_dict(value: Any) -> TypeGuard[dict[str, Any]]:
    """Type guard for dict checking.

    Args:
        value: Value to check

    Returns:
        True if value is a dict, False otherwise
    """
    return isinstance(value, dict)


def get_enrichment_dict(session: SessionSummary) -> dict[str, Any] | None:
    """Safely extract enrichment dict from SessionSummary.

    Args:
        session: SessionSummary instance

    Returns:
        Enrichment dict if available and valid, None otherwise
    """
    enrichment = session.enrichment
    if enrichment is None:
        return None
    # Use type guard to safely check if it's a dict
    if is_dict(enrichment):
        return enrichment
    return None


def get_payload_dict(event: RawEvent) -> dict[str, Any] | None:
    """Safely extract payload dict from RawEvent.

    Args:
        event: RawEvent instance

    Returns:
        Payload dict if available and valid, None otherwise
    """
    payload = event.payload
    if payload is None:
        return None
    # Use type guard to safely check if it's a dict
    if is_dict(payload):
        return payload
    return None


def get_payload_dict_from_row(row: Any) -> dict[str, Any] | None:
    """Safely extract payload dict from database row.

    Args:
        row: Database row with payload attribute

    Returns:
        Payload dict if available and valid, None otherwise
    """
    if not hasattr(row, 'payload'):
        return None
    payload = row.payload
    if payload is None:
        return None
    if isinstance(payload, dict):
        return payload
    return None


def safe_get_enrichment_field(session: SessionSummary, field_path: str, default: Any = None) -> Any:
    """Safely extract a field from session enrichment.

    Args:
        session: SessionSummary instance
        field_path: Dot-separated field path (e.g., 'session.src_ip')
        default: Default value if field not found

    Returns:
        Field value or default
    """
    enrichment = get_enrichment_dict(session)
    if enrichment is None:
        return default

    # Navigate through nested dict structure
    current = enrichment
    for field in field_path.split('.'):
        if not isinstance(current, dict) or field not in current:
            return default
        current = current[field]

    return current


def safe_get_payload_field(event: RawEvent, field: str, default: Any = None) -> Any:
    """Safely extract a field from event payload.

    Args:
        event: RawEvent instance
        field: Field name to extract
        default: Default value if field not found

    Returns:
        Field value or default
    """
    payload = get_payload_dict(event)
    if payload is None:
        return default

    return payload.get(field, default)


def validate_enrichment_structure(session: SessionSummary) -> bool:
    """Validate that session enrichment has expected structure.

    Args:
        session: SessionSummary instance

    Returns:
        True if enrichment structure is valid, False otherwise
    """
    enrichment = get_enrichment_dict(session)
    if enrichment is None:
        return False

    # Check for expected top-level keys
    expected_keys = {'session', 'passwords', 'password_stats'}
    return any(key in enrichment for key in expected_keys)


def validate_payload_structure(event: RawEvent, expected_type: str) -> bool:
    """Validate that event payload has expected structure for event type.

    Args:
        event: RawEvent instance
        expected_type: Expected event type (e.g., 'cowrie.command.input')

    Returns:
        True if payload structure is valid for event type, False otherwise
    """
    payload = get_payload_dict(event)
    if payload is None:
        return False

    # Check for eventid match
    if payload.get('eventid') != expected_type:
        return False

    # Check for required fields based on event type
    required_fields = {
        'cowrie.command.input': ['session', 'input'],
        'cowrie.login.success': ['session', 'username', 'password'],
        'cowrie.login.failed': ['session', 'username', 'password'],
        'cowrie.session.connect': ['session', 'src_ip'],
        'cowrie.session.file_download': ['session', 'url', 'shasum'],
    }

    required = required_fields.get(expected_type, [])
    return all(field in payload for field in required)
