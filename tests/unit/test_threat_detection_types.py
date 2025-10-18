"""Unit tests for threat detection type guards and SQLAlchemy 2.0 compatibility.

Tests the type-safe ORM access patterns and ensures no type conflicts.
"""

from __future__ import annotations

from datetime import datetime, timezone

from cowrieprocessor.db.models import RawEvent, SessionSummary
from cowrieprocessor.db.type_guards import (
    get_enrichment_dict,
    get_payload_dict,
    is_dict,
    safe_get_enrichment_field,
    safe_get_payload_field,
    validate_enrichment_structure,
    validate_payload_structure,
)


class TestTypeGuards:
    """Test type guard functions."""

    def test_is_dict_type_guard(self) -> None:
        """Test the is_dict type guard function."""
        assert is_dict({"key": "value"}) is True
        assert is_dict("string") is False
        assert is_dict(None) is False
        assert is_dict(123) is False
        assert is_dict([]) is False

    def test_get_enrichment_dict_with_valid_dict(self) -> None:
        """Test get_enrichment_dict with valid dict enrichment."""
        session = SessionSummary(
            session_id="test-session",
            first_event_at=datetime.now(timezone.utc),
            last_event_at=datetime.now(timezone.utc),
            enrichment={"session": {"192.168.1.1": {"country": "US"}}},
        )

        result = get_enrichment_dict(session)
        assert result == {"session": {"192.168.1.1": {"country": "US"}}}

    def test_get_enrichment_dict_with_none(self) -> None:
        """Test get_enrichment_dict with None enrichment."""
        session = SessionSummary(
            session_id="test-session",
            first_event_at=datetime.now(timezone.utc),
            last_event_at=datetime.now(timezone.utc),
            enrichment=None,
        )

        result = get_enrichment_dict(session)
        assert result is None

    def test_get_enrichment_dict_with_invalid_type(self) -> None:
        """Test get_enrichment_dict with invalid enrichment type."""
        session = SessionSummary(
            session_id="test-session",
            first_event_at=datetime.now(timezone.utc),
            last_event_at=datetime.now(timezone.utc),
            enrichment="invalid-string",  # type: ignore[assignment]
        )

        result = get_enrichment_dict(session)
        assert result is None

    def test_get_payload_dict_with_valid_dict(self) -> None:
        """Test get_payload_dict with valid dict payload."""
        event = RawEvent(
            source="test",
            payload={"eventid": "cowrie.command.input", "input": "ls -la"},
        )

        result = get_payload_dict(event)
        assert result == {"eventid": "cowrie.command.input", "input": "ls -la"}

    def test_get_payload_dict_with_none(self) -> None:
        """Test get_payload_dict with None payload."""
        event = RawEvent(
            source="test",
            payload=None,
        )

        result = get_payload_dict(event)
        assert result is None

    def test_safe_get_enrichment_field_success(self) -> None:
        """Test safe_get_enrichment_field with valid field path."""
        session = SessionSummary(
            session_id="test-session",
            first_event_at=datetime.now(timezone.utc),
            last_event_at=datetime.now(timezone.utc),
            enrichment={"session": {"ip_info": {"spur": {"country": "US", "asn": "AS12345"}}}},
        )

        result = safe_get_enrichment_field(session, "session.ip_info.spur.country")
        assert result == "US"

    def test_safe_get_enrichment_field_missing_field(self) -> None:
        """Test safe_get_enrichment_field with missing field."""
        session = SessionSummary(
            session_id="test-session",
            first_event_at=datetime.now(timezone.utc),
            last_event_at=datetime.now(timezone.utc),
            enrichment={"session": {"192.168.1.1": {"country": "US"}}},
        )

        result = safe_get_enrichment_field(session, "session.missing.field", "default")
        assert result == "default"

    def test_safe_get_enrichment_field_no_enrichment(self) -> None:
        """Test safe_get_enrichment_field with no enrichment."""
        session = SessionSummary(
            session_id="test-session",
            first_event_at=datetime.now(timezone.utc),
            last_event_at=datetime.now(timezone.utc),
            enrichment=None,
        )

        result = safe_get_enrichment_field(session, "session.field", "default")
        assert result == "default"

    def test_safe_get_payload_field_success(self) -> None:
        """Test safe_get_payload_field with valid field."""
        event = RawEvent(
            source="test",
            payload={"eventid": "cowrie.command.input", "input": "ls -la"},
        )

        result = safe_get_payload_field(event, "input")
        assert result == "ls -la"

    def test_safe_get_payload_field_missing_field(self) -> None:
        """Test safe_get_payload_field with missing field."""
        event = RawEvent(
            source="test",
            payload={"eventid": "cowrie.command.input"},
        )

        result = safe_get_payload_field(event, "input", "default")
        assert result == "default"

    def test_safe_get_payload_field_no_payload(self) -> None:
        """Test safe_get_payload_field with no payload."""
        event = RawEvent(
            source="test",
            payload=None,
        )

        result = safe_get_payload_field(event, "input", "default")
        assert result == "default"

    def test_validate_enrichment_structure_valid(self) -> None:
        """Test validate_enrichment_structure with valid structure."""
        session = SessionSummary(
            session_id="test-session",
            first_event_at=datetime.now(timezone.utc),
            last_event_at=datetime.now(timezone.utc),
            enrichment={
                "session": {"192.168.1.1": {"country": "US"}},
                "passwords": {"total_attempts": 5},
            },
        )

        result = validate_enrichment_structure(session)
        assert result is True

    def test_validate_enrichment_structure_invalid(self) -> None:
        """Test validate_enrichment_structure with invalid structure."""
        session = SessionSummary(
            session_id="test-session",
            first_event_at=datetime.now(timezone.utc),
            last_event_at=datetime.now(timezone.utc),
            enrichment={"random_field": "value"},
        )

        result = validate_enrichment_structure(session)
        assert result is False

    def test_validate_enrichment_structure_none(self) -> None:
        """Test validate_enrichment_structure with None enrichment."""
        session = SessionSummary(
            session_id="test-session",
            first_event_at=datetime.now(timezone.utc),
            last_event_at=datetime.now(timezone.utc),
            enrichment=None,
        )

        result = validate_enrichment_structure(session)
        assert result is False

    def test_validate_payload_structure_valid(self) -> None:
        """Test validate_payload_structure with valid payload."""
        event = RawEvent(
            source="test",
            payload={
                "eventid": "cowrie.command.input",
                "session": "test-session",
                "input": "ls -la",
            },
        )

        result = validate_payload_structure(event, "cowrie.command.input")
        assert result is True

    def test_validate_payload_structure_missing_fields(self) -> None:
        """Test validate_payload_structure with missing required fields."""
        event = RawEvent(
            source="test",
            payload={
                "eventid": "cowrie.command.input",
                "session": "test-session",
                # Missing 'input' field
            },
        )

        result = validate_payload_structure(event, "cowrie.command.input")
        assert result is False

    def test_validate_payload_structure_wrong_event_type(self) -> None:
        """Test validate_payload_structure with wrong event type."""
        event = RawEvent(
            source="test",
            payload={
                "eventid": "cowrie.login.success",
                "session": "test-session",
                "username": "admin",
                "password": "password",
            },
        )

        result = validate_payload_structure(event, "cowrie.command.input")
        assert result is False

    def test_validate_payload_structure_none_payload(self) -> None:
        """Test validate_payload_structure with None payload."""
        event = RawEvent(
            source="test",
            payload=None,
        )

        result = validate_payload_structure(event, "cowrie.command.input")
        assert result is False


class TestTypeSafetyEdgeCases:
    """Test edge cases for type safety."""

    def test_enrichment_with_unexpected_types(self) -> None:
        """Test enrichment access with unexpected data types."""
        session = SessionSummary(
            session_id="test-session",
            first_event_at=datetime.now(timezone.utc),
            last_event_at=datetime.now(timezone.utc),
            enrichment={
                "session": "not-a-dict",  # Invalid type
                "passwords": 123,  # Invalid type
            },
        )

        # Should handle gracefully
        result = get_enrichment_dict(session)
        assert isinstance(result, dict)

        # Should return default for invalid paths
        field_result = safe_get_enrichment_field(session, "session.field", "default")
        assert field_result == "default"

    def test_payload_with_unexpected_types(self) -> None:
        """Test payload access with unexpected data types."""
        event = RawEvent(
            source="test",
            payload={
                "eventid": 123,  # Invalid type
                "session": ["not", "a", "string"],  # Invalid type
            },
        )

        # Should handle gracefully
        result = get_payload_dict(event)
        assert isinstance(result, dict)

        # Should return default for invalid fields
        field_result = safe_get_payload_field(event, "input", "default")
        assert field_result == "default"

    def test_nested_dict_access_with_invalid_structure(self) -> None:
        """Test nested dict access with invalid structure."""
        session = SessionSummary(
            session_id="test-session",
            first_event_at=datetime.now(timezone.utc),
            last_event_at=datetime.now(timezone.utc),
            enrichment={
                "session": {
                    "192.168.1.1": "not-a-dict",  # Invalid nested structure
                }
            },
        )

        # Should handle gracefully and return default
        result = safe_get_enrichment_field(session, "session.192.168.1.1.country", "default")
        assert result == "default"
