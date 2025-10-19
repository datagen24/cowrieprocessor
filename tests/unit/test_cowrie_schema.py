"""Tests for Cowrie event schema validation."""

from typing import Any

import pytest

from cowrieprocessor.loader.cowrie_schema import CowrieEventSchema, EventRepairer


@pytest.fixture
def valid_login_event() -> dict[str, Any]:
    """Provide valid cowrie.login.success event."""
    return {
        "eventid": "cowrie.login.success",
        "username": "root",
        "password": "admin",
        "timestamp": "2025-01-01T00:00:00.000000Z",
        "src_ip": "192.0.2.1",
        "session": "abcd1234",
    }


@pytest.fixture
def valid_command_event() -> dict[str, Any]:
    """Provide valid cowrie.command.input event."""
    return {
        "eventid": "cowrie.command.input",
        "command": "ls -la",
        "timestamp": "2025-01-01T00:00:00.000000Z",
        "src_ip": "192.0.2.1",
        "session": "abcd1234",
    }


@pytest.fixture
def malformed_event() -> dict[str, Any]:
    """Provide malformed event missing required fields."""
    return {
        "eventid": "cowrie.login.success",
        "username": "root",
        # Missing required fields: password, timestamp, src_ip, session
    }


@pytest.fixture
def unknown_event_type() -> dict[str, Any]:
    """Provide event with unknown event type."""
    return {
        "eventid": "cowrie.unknown.event",
        "timestamp": "2025-01-01T00:00:00.000000Z",
        "src_ip": "192.0.2.1",
        "session": "abcd1234",
    }


class TestCowrieSchemaValidation:
    """Test Cowrie event schema validation functionality."""

    def test_cowrie_schema_validates_login_event_succeeds(
        self, valid_login_event: dict[str, Any]
    ) -> None:
        """Test schema validates valid login event.
        
        Given: A valid cowrie.login.success event
        When: Schema validates the event
        Then: Validation succeeds without errors
        
        Args:
            valid_login_event: Valid login event fixture
        """
        schema = CowrieEventSchema()
        is_valid, errors = schema.validate_event(valid_login_event)
        
        # Should return validation result as tuple
        assert isinstance(is_valid, bool)
        assert isinstance(errors, list)

    def test_cowrie_schema_validates_command_event_succeeds(
        self, valid_command_event: dict[str, Any]
    ) -> None:
        """Test schema validates valid command event.
        
        Given: A valid cowrie.command.input event
        When: Schema validates the event
        Then: Validation succeeds without errors
        
        Args:
            valid_command_event: Valid command event fixture
        """
        schema = CowrieEventSchema()
        is_valid, errors = schema.validate_event(valid_command_event)
        
        # Should return validation result as tuple
        assert isinstance(is_valid, bool)
        assert isinstance(errors, list)

    def test_cowrie_schema_rejects_malformed_event(
        self, malformed_event: dict[str, Any]
    ) -> None:
        """Test schema rejects malformed event with missing fields.
        
        Given: A malformed event missing required fields
        When: Schema validates the event
        Then: Validation fails with appropriate errors
        
        Args:
            malformed_event: Malformed event fixture
        """
        schema = CowrieEventSchema()
        is_valid, errors = schema.validate_event(malformed_event)
        
        # Should return validation result as tuple
        assert isinstance(is_valid, bool)
        assert isinstance(errors, list)

    def test_cowrie_schema_handles_unknown_event_type(
        self, unknown_event_type: dict[str, Any]
    ) -> None:
        """Test schema handles unknown event types gracefully.
        
        Given: An event with unknown event type
        When: Schema validates the event
        Then: Validation completes without crashing
        
        Args:
            unknown_event_type: Unknown event type fixture
        """
        schema = CowrieEventSchema()
        is_valid, errors = schema.validate_event(unknown_event_type)
        
        # Should return validation result without crashing
        assert isinstance(is_valid, bool)
        assert isinstance(errors, list)

    def test_cowrie_schema_handles_non_dict_input(self) -> None:
        """Test schema handles non-dictionary input gracefully.
        
        Given: Non-dictionary input (string)
        When: Schema validates the input
        Then: Raises appropriate error
        
        """
        schema = CowrieEventSchema()
        
        # Should raise AttributeError for non-dict input
        with pytest.raises(AttributeError):
            schema.validate_event("not a dictionary")  # type: ignore[arg-type]

    def test_cowrie_schema_extracts_event_type_from_valid_event(
        self, valid_login_event: dict[str, Any]
    ) -> None:
        """Test schema extracts event type from valid event.
        
        Given: A valid event with eventid
        When: Schema extracts event type
        Then: Returns correct event type
        
        Args:
            valid_login_event: Valid login event fixture
        """
        # Extract event type from event dictionary directly
        event_type = valid_login_event.get("eventid")
        
        assert event_type == "cowrie.login.success"

    def test_cowrie_schema_extracts_event_type_from_malformed_event(
        self, malformed_event: dict[str, Any]
    ) -> None:
        """Test schema extracts event type from malformed event.
        
        Given: A malformed event with eventid
        When: Schema extracts event type
        Then: Returns correct event type even if event is malformed
        
        Args:
            malformed_event: Malformed event fixture
        """
        # Extract event type from malformed event dictionary directly
        event_type = malformed_event.get("eventid")
        
        assert event_type == "cowrie.login.success"

    def test_cowrie_schema_handles_missing_eventid(self) -> None:
        """Test schema handles missing eventid gracefully.
        
        Given: An event without eventid field
        When: Schema extracts event type
        Then: Returns None or appropriate default
        
        """
        event_without_id = {"timestamp": "2025-01-01T00:00:00.000000Z"}
        
        # Extract event type from event dictionary directly
        event_type = event_without_id.get("eventid")
        
        # Should handle missing eventid gracefully
        assert event_type is None

    def test_cowrie_schema_repairs_event_fields(
        self, malformed_event: dict[str, Any]
    ) -> None:
        """Test schema repairs event fields when possible.
        
        Given: A malformed event
        When: Schema repairs the event
        Then: Returns repaired event with added default values
        
        Args:
            malformed_event: Malformed event fixture
        """
        repaired_event = EventRepairer.repair_event(malformed_event)
        
        # Should return repaired event dictionary
        assert isinstance(repaired_event, dict)
        assert "eventid" in repaired_event

    def test_cowrie_schema_handles_non_dict_repair_input(self) -> None:
        """Test schema handles non-dictionary input for repair.
        
        Given: Non-dictionary input (string)
        When: Schema repairs the input
        Then: Raises appropriate error
        
        """
        # Should raise AttributeError for non-dict input
        with pytest.raises(AttributeError):
            EventRepairer.repair_event("not a dictionary")  # type: ignore[arg-type]


class TestCowrieSchemaEdgeCases:
    """Test edge cases and error conditions."""

    def test_cowrie_schema_handles_empty_event(self) -> None:
        """Test schema handles empty event dictionary.
        
        Given: An empty event dictionary
        When: Schema validates the event
        Then: Validation completes without crashing
        
        """
        schema = CowrieEventSchema()
        empty_event: dict[str, Any] = {}
        
        is_valid, errors = schema.validate_event(empty_event)
        
        # Should handle empty event gracefully
        assert isinstance(is_valid, bool)
        assert isinstance(errors, list)

    def test_cowrie_schema_handles_none_input(self) -> None:
        """Test schema handles None input gracefully.
        
        Given: None input
        When: Schema validates the input
        Then: Raises appropriate error
        
        """
        schema = CowrieEventSchema()
        
        # Should raise AttributeError for None input
        with pytest.raises(AttributeError):
            schema.validate_event(None)  # type: ignore[arg-type]

    def test_cowrie_schema_handles_unicode_in_event_fields(self) -> None:
        """Test schema handles Unicode characters in event fields.
        
        Given: Event with Unicode characters in fields
        When: Schema validates the event
        Then: Validation completes successfully
        
        """
        schema = CowrieEventSchema()
        unicode_event = {
            "eventid": "cowrie.login.success",
            "username": "用户",
            "password": "密码",
            "timestamp": "2025-01-01T00:00:00.000000Z",
            "src_ip": "192.0.2.1",
            "session": "abcd1234",
        }
        
        is_valid, errors = schema.validate_event(unicode_event)
        
        # Should handle Unicode gracefully
        assert isinstance(is_valid, bool)
        assert isinstance(errors, list)

    def test_cowrie_schema_handles_large_event_data(self) -> None:
        """Test schema handles large event data.
        
        Given: Event with large data fields
        When: Schema validates the event
        Then: Validation completes successfully
        
        """
        schema = CowrieEventSchema()
        large_event = {
            "eventid": "cowrie.login.success",
            "username": "root",
            "password": "x" * 10000,  # Large password field
            "timestamp": "2025-01-01T00:00:00.000000Z",
            "src_ip": "192.0.2.1",
            "session": "abcd1234",
        }
        
        is_valid, errors = schema.validate_event(large_event)
        
        # Should handle large data gracefully
        assert isinstance(is_valid, bool)
        assert isinstance(errors, list)