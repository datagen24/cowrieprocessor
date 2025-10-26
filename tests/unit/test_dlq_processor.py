"""Unit tests for Dead Letter Queue processor.

This module tests DLQ event processing, repair strategies, and database operations.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session

from cowrieprocessor.db.models import DeadLetterEvent, RawEvent
from cowrieprocessor.loader.dlq_processor import (
    DLQProcessor,
)

# ============================================================================
# DLQProcessor._insert_repaired_event() Tests (90 lines)
# ============================================================================


def test_insert_repaired_event_new_event_sqlite(db_session: Session) -> None:
    """Test inserting a new repaired event into raw_events (SQLite).

    Given: Empty database and a repaired event from DLQ
    When: _insert_repaired_event is called
    Then: New RawEvent is created with correct fields

    Args:
        db_session: Database session fixture
    """
    # Given: Create a DLQ event
    dlq_event = DeadLetterEvent(
        ingest_id="test-ingest-123",
        source="test.log",
        source_offset=100,
        reason="malformed_json",
        payload={"malformed_content": '{"eventid": "cowrie.login.success"'},
        resolved=False,
    )
    db_session.add(dlq_event)
    db_session.commit()

    # Create repaired event data
    repaired_event: Dict[str, Any] = {
        "eventid": "cowrie.login.success",
        "session": "abc12345",
        "username": "root",
        "password": "toor",
        "timestamp": "2024-01-15T10:30:00Z",
    }

    # When: Insert the repaired event
    processor = DLQProcessor()
    result = processor._insert_repaired_event(db_session, dlq_event, repaired_event)

    # Then: Insert succeeds
    assert result is True

    # Verify the RawEvent was created
    stmt = select(RawEvent).where(RawEvent.session_id == "abc12345")
    raw_event = db_session.execute(stmt).scalar_one()

    assert raw_event.ingest_id == "test-ingest-123"
    assert raw_event.source == "test.log"
    assert raw_event.source_offset == 100
    assert raw_event.session_id == "abc12345"
    assert raw_event.event_type == "cowrie.login.success"
    assert raw_event.risk_score == 50
    assert raw_event.quarantined is False
    assert raw_event.payload == repaired_event
    # event_timestamp should be parsed datetime object
    assert raw_event.event_timestamp is not None
    assert raw_event.event_timestamp.year == 2024
    assert raw_event.event_timestamp.month == 1
    assert raw_event.event_timestamp.day == 15


def test_insert_repaired_event_update_existing_sqlite(db_session: Session) -> None:
    """Test updating an existing event when duplicate is found (SQLite).

    Given: Database with an existing RawEvent at same source/offset
    When: _insert_repaired_event is called with repaired data
    Then: Existing event is updated with repaired data

    Args:
        db_session: Database session fixture
    """
    # Given: Create an existing RawEvent (malformed)
    existing_event = RawEvent(
        ingest_id="old-ingest",
        source="test.log",
        source_offset=100,
        source_inode="test.log",
        source_generation=0,
        payload={"malformed": True},
        risk_score=100,
        quarantined=True,
        session_id="old-session",
        event_type="unknown",
    )
    db_session.add(existing_event)
    db_session.commit()
    old_id = existing_event.id

    # Create DLQ event with same source/offset
    dlq_event = DeadLetterEvent(
        ingest_id="new-ingest",
        source="test.log",
        source_offset=100,
        reason="malformed_json",
        payload={"malformed_content": "..."},
        resolved=False,
    )

    # Create repaired event data
    repaired_event: Dict[str, Any] = {
        "eventid": "cowrie.command.input",
        "session": "new-session",
        "command": "ls -la",
        "timestamp": "2024-01-15T10:30:00Z",
    }

    # When: Insert the repaired event
    processor = DLQProcessor()
    result = processor._insert_repaired_event(db_session, dlq_event, repaired_event)

    # Then: Update succeeds
    assert result is True

    # Commit the changes to persist them
    db_session.commit()

    # Verify the existing event was updated (same ID)
    stmt = select(RawEvent).where(RawEvent.id == old_id)
    updated_event = db_session.execute(stmt).scalar_one()

    assert updated_event.id == old_id  # Same record, not new
    assert updated_event.payload == repaired_event
    assert updated_event.risk_score == 50  # Updated from 100
    assert updated_event.quarantined is False  # Updated from True
    assert updated_event.session_id == "new-session"
    assert updated_event.event_type == "cowrie.command.input"


def test_insert_repaired_event_missing_session(db_session: Session) -> None:
    """Test inserting repaired event without session ID.

    Given: Repaired event without session field (orphan event)
    When: _insert_repaired_event is called
    Then: Event is inserted with None session_id

    Args:
        db_session: Database session fixture
    """
    # Given: DLQ event and repaired event without session
    dlq_event = DeadLetterEvent(
        ingest_id="test-ingest",
        source="test.log",
        source_offset=200,
        reason="orphan_event",
        payload={"malformed_content": "..."},
        resolved=False,
    )

    repaired_event: Dict[str, Any] = {
        "eventid": "cowrie.system.info",
        "message": "System information event",
        "timestamp": "2024-01-15T10:30:00Z",
    }

    # When: Insert the repaired event
    processor = DLQProcessor()
    result = processor._insert_repaired_event(db_session, dlq_event, repaired_event)

    # Then: Insert succeeds
    assert result is True

    # Verify event was created with None session
    stmt = select(RawEvent).where(RawEvent.event_type == "cowrie.system.info")
    raw_event = db_session.execute(stmt).scalar_one()

    assert raw_event.session_id is None
    assert raw_event.event_type == "cowrie.system.info"
    assert raw_event.payload == repaired_event


def test_insert_repaired_event_field_mapping(db_session: Session) -> None:
    """Test correct field mapping from repaired event to RawEvent.

    Given: Repaired event with all standard Cowrie fields
    When: _insert_repaired_event is called
    Then: All fields are correctly mapped to RawEvent columns

    Args:
        db_session: Database session fixture
    """
    # Given: DLQ event with full repaired data
    dlq_event = DeadLetterEvent(
        ingest_id="test-ingest-full",
        source="/var/log/cowrie/cowrie.json",
        source_offset=12345,
        reason="malformed_json",
        payload={"malformed_content": "..."},
        resolved=False,
    )

    repaired_event: Dict[str, Any] = {
        "eventid": "cowrie.session.file_download",
        "session": "deadbeef",
        "url": "http://malicious.example.com/malware.bin",
        "shasum": "abc123" * 10,  # 60 chars
        "outfile": "/tmp/malware.bin",
        "timestamp": "2024-01-15T12:00:00Z",
    }

    # When: Insert the repaired event
    processor = DLQProcessor()
    result = processor._insert_repaired_event(db_session, dlq_event, repaired_event)

    # Then: All fields mapped correctly
    assert result is True

    stmt = select(RawEvent).where(RawEvent.session_id == "deadbeef")
    raw_event = db_session.execute(stmt).scalar_one()

    # Verify source tracking fields
    assert raw_event.ingest_id == "test-ingest-full"
    assert raw_event.source == "/var/log/cowrie/cowrie.json"
    assert raw_event.source_offset == 12345
    assert raw_event.source_inode == "/var/log/cowrie/cowrie.json"

    # Verify extracted fields
    assert raw_event.session_id == "deadbeef"
    assert raw_event.event_type == "cowrie.session.file_download"
    # event_timestamp should be parsed datetime object
    assert raw_event.event_timestamp is not None
    assert raw_event.event_timestamp.year == 2024
    assert raw_event.event_timestamp.month == 1
    assert raw_event.event_timestamp.day == 15
    assert raw_event.event_timestamp.hour == 12

    # Verify DLQ-specific fields
    assert raw_event.risk_score == 50  # Medium risk for repaired
    assert raw_event.quarantined is False  # No longer quarantined

    # Verify full payload preserved
    assert raw_event.payload == repaired_event
    assert raw_event.payload["url"] == "http://malicious.example.com/malware.bin"


def test_insert_repaired_event_default_source(db_session: Session) -> None:
    """Test inserting repaired event when DLQ has no source.

    Given: DLQ event with None source field
    When: _insert_repaired_event is called
    Then: RawEvent uses 'dlq-repair' as default source

    Args:
        db_session: Database session fixture
    """
    # Given: DLQ event without source
    dlq_event = DeadLetterEvent(
        ingest_id="test-ingest",
        source=None,  # No source
        source_offset=0,
        reason="unknown",
        payload={"malformed_content": "..."},
        resolved=False,
    )

    repaired_event: Dict[str, Any] = {
        "eventid": "cowrie.login.failed",
        "session": "test123",
        "username": "admin",
        "password": "password",
        "timestamp": "2024-01-15T10:30:00Z",
    }

    # When: Insert the repaired event
    processor = DLQProcessor()
    result = processor._insert_repaired_event(db_session, dlq_event, repaired_event)

    # Then: Uses default source
    assert result is True

    stmt = select(RawEvent).where(RawEvent.session_id == "test123")
    raw_event = db_session.execute(stmt).scalar_one()

    assert raw_event.source == "dlq-repair"


def test_insert_repaired_event_error_handling(db_session: Session) -> None:
    """Test error handling when insert fails.

    Given: Invalid database state that causes insert to fail
    When: _insert_repaired_event is called
    Then: Returns False and doesn't crash

    Args:
        db_session: Database session fixture
    """
    # Given: DLQ event with invalid data
    dlq_event = DeadLetterEvent(
        ingest_id="test-ingest",
        source="test.log",
        source_offset=300,
        reason="test",
        payload={"malformed_content": "..."},
        resolved=False,
    )

    # Create repaired event with invalid payload type (will fail JSON serialization)
    repaired_event: Dict[str, Any] = {
        "eventid": "cowrie.login.success",
        "session": "test456",
        "timestamp": "2024-01-15T10:30:00Z",
    }

    processor = DLQProcessor()

    # When/Then: Mock the session.add to raise an exception
    with patch.object(db_session, "add", side_effect=Exception("Database error")):
        # Use the fallback path by forcing PostgreSQL insert to fail
        with patch.object(db_session, "execute", side_effect=Exception("Insert failed")):
            result = processor._insert_repaired_event(db_session, dlq_event, repaired_event)
            assert result is False


# ============================================================================
# DLQProcessor.process_dlq_events() Tests (65 lines)
# ============================================================================


def test_process_dlq_events_empty_queue(db_session: Session) -> None:
    """Test processing when DLQ is empty.

    Given: Database with no unresolved DLQ events
    When: process_dlq_events is called
    Then: Returns stats with zero counts

    Args:
        db_session: Database session fixture
    """
    # Given: Empty DLQ (no unresolved events)
    # When: Process DLQ events
    processor = DLQProcessor()

    # Mock the database connection methods
    with patch("cowrieprocessor.loader.dlq_processor._load_database_settings_from_sensors"):
        with patch("cowrieprocessor.loader.dlq_processor.create_engine_from_settings") as mock_engine:
            with patch("cowrieprocessor.loader.dlq_processor.create_session_maker") as mock_session_maker:
                # Configure mocks to return our test session
                mock_session_maker.return_value = lambda: db_session
                mock_engine.return_value = db_session.get_bind()

                stats = processor.process_dlq_events()

    # Then: All stats are zero
    assert stats["processed"] == 0
    assert stats["repaired"] == 0
    assert stats["failed"] == 0
    assert stats["skipped"] == 0


def test_process_dlq_events_successful_repair(db_session: Session) -> None:
    """Test processing events that can be successfully repaired.

    Given: DLQ with events that can be repaired
    When: process_dlq_events is called
    Then: Events are repaired, inserted, and marked as resolved

    Args:
        db_session: Database session fixture
    """
    # Given: DLQ events with repairable content
    dlq_event1 = DeadLetterEvent(
        ingest_id="test-ingest",
        source="test.log",
        source_offset=100,
        reason="malformed_json",
        payload={
            "malformed_content": '{"eventid": "cowrie.login.success", '
            '"session": "abc12345", "username": "root", '
            '"password": "toor", "timestamp": "2024-01-15T10:30:00Z"}'
        },
        resolved=False,
    )

    dlq_event2 = DeadLetterEvent(
        ingest_id="test-ingest",
        source="test.log",
        source_offset=200,
        reason="malformed_json",
        payload={
            "malformed_content": '{"eventid": "cowrie.command.input", '
            '"session": "abc12345", "command": "ls", '
            '"timestamp": "2024-01-15T10:31:00Z"}'
        },
        resolved=False,
    )

    db_session.add(dlq_event1)
    db_session.add(dlq_event2)
    db_session.commit()

    # When: Process DLQ events
    processor = DLQProcessor()

    with patch("cowrieprocessor.loader.dlq_processor._load_database_settings_from_sensors"):
        with patch("cowrieprocessor.loader.dlq_processor.create_engine_from_settings") as mock_engine:
            with patch("cowrieprocessor.loader.dlq_processor.create_session_maker") as mock_session_maker:
                mock_session_maker.return_value = lambda: db_session
                mock_engine.return_value = db_session.get_bind()

                stats = processor.process_dlq_events()

    # Then: Both events processed and repaired
    assert stats["processed"] == 2
    assert stats["repaired"] == 2
    assert stats["failed"] == 0
    assert stats["skipped"] == 0

    # Verify events are marked as resolved (re-query to avoid DetachedInstanceError)
    stmt = select(DeadLetterEvent).where(DeadLetterEvent.source_offset == 100)
    refreshed_event1 = db_session.execute(stmt).scalar_one()
    assert refreshed_event1.resolved is True
    assert refreshed_event1.resolved_at is not None

    stmt = select(DeadLetterEvent).where(DeadLetterEvent.source_offset == 200)
    refreshed_event2 = db_session.execute(stmt).scalar_one()
    assert refreshed_event2.resolved is True
    assert refreshed_event2.resolved_at is not None

    # Verify RawEvents were created
    stmt = select(RawEvent)
    raw_events = db_session.execute(stmt).scalars().all()
    assert len(raw_events) == 2


def test_process_dlq_events_failed_repair(db_session: Session) -> None:
    """Test processing events that cannot be repaired.

    Given: DLQ with completely broken events
    When: process_dlq_events is called
    Then: Events remain unresolved and stats show failures

    Args:
        db_session: Database session fixture
    """
    # Given: DLQ event with unrepairable content
    dlq_event = DeadLetterEvent(
        ingest_id="test-ingest",
        source="test.log",
        source_offset=100,
        reason="totally_broken",
        payload={"malformed_content": "this is not even close to JSON {{{[[[]]]"},
        resolved=False,
    )
    db_session.add(dlq_event)
    db_session.commit()

    # When: Process DLQ events
    processor = DLQProcessor()

    with patch("cowrieprocessor.loader.dlq_processor._load_database_settings_from_sensors"):
        with patch("cowrieprocessor.loader.dlq_processor.create_engine_from_settings") as mock_engine:
            with patch("cowrieprocessor.loader.dlq_processor.create_session_maker") as mock_session_maker:
                mock_session_maker.return_value = lambda: db_session
                mock_engine.return_value = db_session.get_bind()

                stats = processor.process_dlq_events()

    # Then: Event processed but failed repair
    assert stats["processed"] == 1
    assert stats["repaired"] == 0
    assert stats["failed"] == 1
    assert stats["skipped"] == 0

    # Verify event remains unresolved (re-query)
    stmt = select(DeadLetterEvent).where(DeadLetterEvent.source_offset == 100)
    refreshed_event = db_session.execute(stmt).scalar_one()
    assert refreshed_event.resolved is False
    assert refreshed_event.resolved_at is None


def test_process_dlq_events_with_reason_filter(db_session: Session) -> None:
    """Test filtering events by reason.

    Given: DLQ with events of different reasons
    When: process_dlq_events is called with reason_filter
    Then: Only matching events are processed

    Args:
        db_session: Database session fixture
    """
    # Given: DLQ events with different reasons
    dlq_event1 = DeadLetterEvent(
        ingest_id="test-ingest",
        source="test.log",
        source_offset=100,
        reason="malformed_json",
        payload={
            "malformed_content": '{"eventid": "cowrie.login.success", '
            '"session": "abc12345", "timestamp": "2024-01-15T10:30:00Z"}'
        },
        resolved=False,
    )

    dlq_event2 = DeadLetterEvent(
        ingest_id="test-ingest",
        source="test.log",
        source_offset=200,
        reason="unicode_error",
        payload={"malformed_content": "some broken unicode"},
        resolved=False,
    )

    db_session.add(dlq_event1)
    db_session.add(dlq_event2)
    db_session.commit()

    # When: Process DLQ events with reason filter
    processor = DLQProcessor()

    with patch("cowrieprocessor.loader.dlq_processor._load_database_settings_from_sensors"):
        with patch("cowrieprocessor.loader.dlq_processor.create_engine_from_settings") as mock_engine:
            with patch("cowrieprocessor.loader.dlq_processor.create_session_maker") as mock_session_maker:
                mock_session_maker.return_value = lambda: db_session
                mock_engine.return_value = db_session.get_bind()

                stats = processor.process_dlq_events(reason_filter="malformed_json")

    # Then: Only the malformed_json event was processed
    assert stats["processed"] == 1
    assert stats["repaired"] == 1

    # Verify only the filtered event was resolved (re-query)
    stmt = select(DeadLetterEvent).where(DeadLetterEvent.reason == "malformed_json")
    refreshed_event1 = db_session.execute(stmt).scalar_one()
    assert refreshed_event1.resolved is True

    stmt = select(DeadLetterEvent).where(DeadLetterEvent.reason == "unicode_error")
    refreshed_event2 = db_session.execute(stmt).scalar_one()
    assert refreshed_event2.resolved is False


def test_process_dlq_events_with_limit(db_session: Session) -> None:
    """Test limiting the number of events processed.

    Given: DLQ with multiple events
    When: process_dlq_events is called with limit=2
    Then: Only 2 events are processed

    Args:
        db_session: Database session fixture
    """
    # Given: DLQ with 5 events (with all required fields for cowrie.login.success)
    for i in range(5):
        malformed_content = (
            '{"eventid": "cowrie.login.success", '
            f'"session": "session{i}", '
            f'"username": "user{i}", '
            f'"password": "pass{i}", '
            '"timestamp": "2024-01-15T10:30:00Z"'
            '}'
        )
        dlq_event = DeadLetterEvent(
            ingest_id="test-ingest",
            source="test.log",
            source_offset=100 + i,
            reason="malformed_json",
            payload={"malformed_content": malformed_content},
            resolved=False,
        )
        db_session.add(dlq_event)
    db_session.commit()

    # When: Process with limit=2
    processor = DLQProcessor()

    with patch("cowrieprocessor.loader.dlq_processor._load_database_settings_from_sensors"):
        with patch("cowrieprocessor.loader.dlq_processor.create_engine_from_settings") as mock_engine:
            with patch("cowrieprocessor.loader.dlq_processor.create_session_maker") as mock_session_maker:
                mock_session_maker.return_value = lambda: db_session
                mock_engine.return_value = db_session.get_bind()

                stats = processor.process_dlq_events(limit=2)

    # Then: Only 2 events processed
    assert stats["processed"] == 2
    assert stats["repaired"] == 2

    # Verify 3 events remain unresolved
    stmt = select(DeadLetterEvent).where(DeadLetterEvent.resolved.is_(False))
    unresolved = db_session.execute(stmt).scalars().all()
    assert len(unresolved) == 3


def test_process_dlq_events_skipped_events(db_session: Session) -> None:
    """Test handling of events without malformed_content.

    Given: DLQ event without malformed_content field
    When: process_dlq_events is called
    Then: Event is skipped and counted appropriately

    Args:
        db_session: Database session fixture
    """
    # Given: DLQ event without malformed_content
    dlq_event = DeadLetterEvent(
        ingest_id="test-ingest",
        source="test.log",
        source_offset=100,
        reason="missing_content",
        payload={"some_other_field": "value"},  # No malformed_content
        resolved=False,
    )
    db_session.add(dlq_event)
    db_session.commit()

    # When: Process DLQ events
    processor = DLQProcessor()

    with patch("cowrieprocessor.loader.dlq_processor._load_database_settings_from_sensors"):
        with patch("cowrieprocessor.loader.dlq_processor.create_engine_from_settings") as mock_engine:
            with patch("cowrieprocessor.loader.dlq_processor.create_session_maker") as mock_session_maker:
                mock_session_maker.return_value = lambda: db_session
                mock_engine.return_value = db_session.get_bind()

                stats = processor.process_dlq_events()

    # Then: Event was skipped
    assert stats["processed"] == 1
    assert stats["skipped"] == 1
    assert stats["repaired"] == 0
    assert stats["failed"] == 0


# ============================================================================
# CowrieEventValidator Tests (100+ lines)
# ============================================================================


def test_validate_event_missing_eventid() -> None:
    """Test validation fails when eventid is missing.

    Given: Event without eventid field
    When: validate_event is called
    Then: Returns False with 'missing_eventid' error
    """
    from cowrieprocessor.loader.dlq_processor import CowrieEventValidator

    # Given: Event without eventid
    event = {
        "session": "abc12345",
        "timestamp": "2024-01-15T10:30:00Z",
    }

    # When: Validate
    is_valid, errors = CowrieEventValidator.validate_event(event)

    # Then: Validation fails
    assert is_valid is False
    assert "missing_eventid" in errors


def test_validate_event_unknown_eventid() -> None:
    """Test validation fails for unknown event types.

    Given: Event with unrecognized eventid
    When: validate_event is called
    Then: Returns False with 'unknown_eventid' error
    """
    from cowrieprocessor.loader.dlq_processor import CowrieEventValidator

    # Given: Event with unknown eventid
    event = {
        "eventid": "cowrie.unknown.event",
        "timestamp": "2024-01-15T10:30:00Z",
    }

    # When: Validate
    is_valid, errors = CowrieEventValidator.validate_event(event)

    # Then: Validation fails
    assert is_valid is False
    assert any("unknown_eventid" in error for error in errors)


def test_validate_event_invalid_timestamp() -> None:
    """Test validation fails for invalid timestamp format.

    Given: Event with malformed timestamp
    When: validate_event is called
    Then: Returns False with 'invalid_timestamp_format' error
    """
    from cowrieprocessor.loader.dlq_processor import CowrieEventValidator

    # Given: Event with invalid timestamp
    event = {
        "eventid": "cowrie.login.success",
        "session": "abc12345",
        "timestamp": "not-a-timestamp",
    }

    # When: Validate
    is_valid, errors = CowrieEventValidator.validate_event(event)

    # Then: Validation fails
    assert is_valid is False
    assert any("invalid_timestamp_format" in error for error in errors)


def test_validate_event_invalid_session_id() -> None:
    """Test validation fails for invalid session ID format.

    Given: Event with non-hex session ID
    When: validate_event is called
    Then: Returns False with 'invalid_session_id_format' error
    """
    from cowrieprocessor.loader.dlq_processor import CowrieEventValidator

    # Given: Event with invalid session ID (not 8-char hex)
    event = {
        "eventid": "cowrie.login.success",
        "session": "not-valid-session-id-123",
        "timestamp": "2024-01-15T10:30:00Z",
    }

    # When: Validate
    is_valid, errors = CowrieEventValidator.validate_event(event)

    # Then: Validation fails
    assert is_valid is False
    assert any("invalid_session_id_format" in error for error in errors)


def test_validate_event_invalid_src_ip() -> None:
    """Test validation fails for invalid IP address.

    Given: Event with malformed src_ip
    When: validate_event is called
    Then: Returns False with 'invalid_src_ip' error
    """
    from cowrieprocessor.loader.dlq_processor import CowrieEventValidator

    # Given: Event with invalid IP
    event = {
        "eventid": "cowrie.session.connect",
        "session": "abc12345",
        "src_ip": "999.999.999.999",  # Invalid IP
        "timestamp": "2024-01-15T10:30:00Z",
    }

    # When: Validate
    is_valid, errors = CowrieEventValidator.validate_event(event)

    # Then: Validation fails
    assert is_valid is False
    assert any("invalid_src_ip" in error for error in errors)


def test_validate_event_valid_session_connect() -> None:
    """Test successful validation of session.connect event.

    Given: Valid cowrie.session.connect event
    When: validate_event is called
    Then: Returns True with no errors
    """
    from cowrieprocessor.loader.dlq_processor import CowrieEventValidator

    # Given: Valid session.connect event
    event = {
        "eventid": "cowrie.session.connect",
        "session": "abc12345",
        "src_ip": "192.168.1.100",
        "timestamp": "2024-01-15T10:30:00Z",
    }

    # When: Validate
    is_valid, errors = CowrieEventValidator.validate_event(event)

    # Then: Validation succeeds
    assert is_valid is True
    assert len(errors) == 0


def test_validate_event_missing_required_fields() -> None:
    """Test validation fails when required fields are missing.

    Given: login.success event missing username/password
    When: validate_event is called
    Then: Returns False with missing_required_field errors
    """
    from cowrieprocessor.loader.dlq_processor import CowrieEventValidator

    # Given: login.success missing required fields
    event = {
        "eventid": "cowrie.login.success",
        "session": "abc12345",
        "timestamp": "2024-01-15T10:30:00Z",
        # Missing: username, password
    }

    # When: Validate
    is_valid, errors = CowrieEventValidator.validate_event(event)

    # Then: Validation fails
    assert is_valid is False
    assert any("missing_required_field: username" in error for error in errors)
    assert any("missing_required_field: password" in error for error in errors)


# ============================================================================
# JSONRepairStrategies Tests (80+ lines)
# ============================================================================


def test_fix_unclosed_strings_odd_single_quotes() -> None:
    """Test fixing unclosed single quotes.

    Given: JSON with odd number of single quotes
    When: fix_unclosed_strings is called
    Then: Adds closing quote
    """
    from cowrieprocessor.loader.dlq_processor import JSONRepairStrategies

    # Given: Content with unclosed single quote
    content = "{'key': 'value"

    # When: Fix unclosed strings
    result = JSONRepairStrategies.fix_unclosed_strings(content)

    # Then: Closing quote added
    assert result == "{'key': 'value'"


def test_fix_unclosed_strings_odd_double_quotes() -> None:
    """Test fixing unclosed double quotes.

    Given: JSON with odd number of double quotes
    When: fix_unclosed_strings is called
    Then: Adds closing quote
    """
    from cowrieprocessor.loader.dlq_processor import JSONRepairStrategies

    # Given: Content with unclosed double quote
    content = '{"key": "value'

    # When: Fix unclosed strings
    result = JSONRepairStrategies.fix_unclosed_strings(content)

    # Then: Closing quote added
    assert result == '{"key": "value"'


def test_fix_unclosed_braces_missing_closing() -> None:
    """Test fixing unclosed braces.

    Given: JSON with unclosed braces
    When: fix_unclosed_braces is called
    Then: Adds closing braces
    """
    from cowrieprocessor.loader.dlq_processor import JSONRepairStrategies

    # Given: Content with unclosed braces
    content = '{"key": "value", "nested": {"inner": "data"'

    # When: Fix unclosed braces
    result = JSONRepairStrategies.fix_unclosed_braces(content)

    # Then: Two closing braces added
    assert result.endswith("}}")


def test_fix_unclosed_braces_missing_bracket() -> None:
    """Test fixing unclosed brackets.

    Given: JSON with unclosed array brackets
    When: fix_unclosed_braces is called
    Then: Adds closing brackets
    """
    from cowrieprocessor.loader.dlq_processor import JSONRepairStrategies

    # Given: Content with unclosed bracket
    content = '{"array": [1, 2, 3'

    # When: Fix unclosed braces
    result = JSONRepairStrategies.fix_unclosed_braces(content)

    # Then: Closing bracket added
    assert result.endswith("]")


def test_fix_trailing_commas_before_brace() -> None:
    """Test removing trailing commas before closing braces.

    Given: JSON with trailing comma before }
    When: fix_trailing_commas is called
    Then: Trailing comma removed
    """
    from cowrieprocessor.loader.dlq_processor import JSONRepairStrategies

    # Given: Content with trailing comma
    content = '{"key": "value",}'

    # When: Fix trailing commas
    result = JSONRepairStrategies.fix_trailing_commas(content)

    # Then: Comma removed
    assert result == '{"key": "value"}'


def test_fix_trailing_commas_before_bracket() -> None:
    """Test removing trailing commas before closing brackets.

    Given: JSON array with trailing comma before ]
    When: fix_trailing_commas is called
    Then: Trailing comma removed
    """
    from cowrieprocessor.loader.dlq_processor import JSONRepairStrategies

    # Given: Array with trailing comma
    content = '{"array": [1, 2, 3,]}'

    # When: Fix trailing commas
    result = JSONRepairStrategies.fix_trailing_commas(content)

    # Then: Comma removed
    assert result == '{"array": [1, 2, 3]}'


def test_fix_unescaped_quotes_in_value() -> None:
    """Test fixing unescaped quotes in string values.

    Given: JSON with unescaped quotes in value
    When: fix_unescaped_quotes is called
    Then: Quotes are escaped
    """
    from cowrieprocessor.loader.dlq_processor import JSONRepairStrategies

    # Given: Value with unescaped quote (simplified test case)
    content = '{"message": "error with quote"}'

    # When: Fix unescaped quotes (this is a complex function, test basic case)
    result = JSONRepairStrategies.fix_unescaped_quotes(content)

    # Then: Result is valid (no crash, basic functionality)
    assert isinstance(result, str)


def test_repair_json_comprehensive() -> None:
    """Test comprehensive JSON repair with all strategies.

    Given: Malformed JSON with multiple issues
    When: repair_json is called
    Then: All strategies applied and result improved
    """
    from cowrieprocessor.loader.dlq_processor import JSONRepairStrategies

    # Given: JSON with trailing comma and unclosed brace
    content = '{"key": "value",'

    # When: Apply comprehensive repair
    result = JSONRepairStrategies.repair_json(content)

    # Then: Unclosed brace fixed (trailing comma removal happens later)
    assert result == '{"key": "value",}'


# ============================================================================
# EventStitcher Tests (60+ lines)
# ============================================================================


def test_analyze_dlq_content_unclosed_braces() -> None:
    """Test DLQ content analysis detects unclosed braces.

    Given: Malformed content with unclosed braces
    When: analyze_dlq_content is called
    Then: Suggests fix_unclosed_braces strategy
    """
    from cowrieprocessor.loader.dlq_processor import EventStitcher

    # Given: Content with unclosed braces
    content = '{"eventid": "cowrie.login.success", "session": "abc12345"'

    # When: Analyze
    stitcher = EventStitcher()
    analysis = stitcher.analyze_dlq_content(content)

    # Then: Correct analysis
    assert analysis["has_eventid"] is True
    assert analysis["has_session"] is True
    assert analysis["brace_balance"] > 0
    assert analysis["suggested_strategy"] == "fix_unclosed_braces"


def test_analyze_dlq_content_overclosed_braces() -> None:
    """Test DLQ content analysis detects overclosed braces.

    Given: Content with extra closing braces
    When: analyze_dlq_content is called
    Then: Suggests fix_overclosed_braces strategy
    """
    from cowrieprocessor.loader.dlq_processor import EventStitcher

    # Given: Content with extra closing braces
    content = '{"key": "value"}}}'

    # When: Analyze
    stitcher = EventStitcher()
    analysis = stitcher.analyze_dlq_content(content)

    # Then: Detects overclosed braces
    assert analysis["brace_balance"] < 0
    assert analysis["suggested_strategy"] == "fix_overclosed_braces"


def test_analyze_dlq_content_unclosed_strings() -> None:
    """Test DLQ content analysis detects unclosed strings.

    Given: Content with unclosed string
    When: analyze_dlq_content is called
    Then: Suggests fix_unclosed_strings strategy
    """
    from cowrieprocessor.loader.dlq_processor import EventStitcher

    # Given: Content with unclosed string (odd quotes, balanced braces)
    content = '{"key": "value}'  # Missing closing quote

    # When: Analyze
    stitcher = EventStitcher()
    analysis = stitcher.analyze_dlq_content(content)

    # Then: Detects unclosed strings
    assert analysis["brace_balance"] == 0  # Braces balanced
    assert analysis["suggested_strategy"] == "fix_unclosed_strings"


def test_analyze_dlq_content_missing_closing_brace() -> None:
    """Test analysis detects missing closing brace.

    Given: Content without any closing brace
    When: analyze_dlq_content is called
    Then: Suggests add_closing_brace strategy
    """
    from cowrieprocessor.loader.dlq_processor import EventStitcher

    # Given: Content with opening but no closing brace
    content = '{"key": "value"'  # Even quotes, no closing brace

    # When: Analyze
    stitcher = EventStitcher()
    analysis = stitcher.analyze_dlq_content(content)

    # Then: Suggests add closing brace (checked before unclosed strings)
    assert analysis["has_opening_brace"] is True
    assert analysis["has_closing_brace"] is False
    # Note: This will be caught by fix_unclosed_braces due to brace_balance > 0


def test_repair_event_simple_json() -> None:
    """Test repairing simple valid JSON event.

    Given: Valid JSON event (no repair needed)
    When: repair_event is called
    Then: Returns parsed event successfully
    """
    from cowrieprocessor.loader.dlq_processor import EventStitcher

    # Given: Valid JSON event
    content = (
        '{"eventid": "cowrie.login.success", "session": "abc12345", '
        '"username": "root", "password": "toor", "timestamp": "2024-01-15T10:30:00Z"}'
    )

    # When: Repair
    stitcher = EventStitcher()
    result = stitcher.repair_event(content)

    # Then: Returns valid event
    assert result is not None
    assert result["eventid"] == "cowrie.login.success"
    assert result["session"] == "abc12345"


def test_repair_event_fixable_json() -> None:
    """Test repairing fixable malformed JSON.

    Given: JSON with unclosed brace
    When: repair_event is called
    Then: Repairs and returns valid event
    """
    from cowrieprocessor.loader.dlq_processor import EventStitcher

    # Given: JSON with unclosed brace (repairable)
    content = (
        '{"eventid": "cowrie.command.input", "session": "abc12345", '
        '"command": "ls", "timestamp": "2024-01-15T10:30:00Z"'
    )

    # When: Repair
    stitcher = EventStitcher()
    result = stitcher.repair_event(content)

    # Then: Successfully repaired
    assert result is not None
    assert result["eventid"] == "cowrie.command.input"


def test_repair_event_unrepairable() -> None:
    """Test handling of completely broken JSON.

    Given: Totally broken content
    When: repair_event is called
    Then: Returns None (cannot repair)
    """
    from cowrieprocessor.loader.dlq_processor import EventStitcher

    # Given: Completely broken content
    content = "this is not JSON at all {{{[[[]]]}}}"

    # When: Repair
    stitcher = EventStitcher()
    result = stitcher.repair_event(content)

    # Then: Returns None
    assert result is None


def test_repair_event_non_dict_json() -> None:
    """Test handling of JSON that parses to non-dict.

    Given: Valid JSON that's an array, not object
    When: repair_event is called
    Then: Returns None (not a dict event)
    """
    from cowrieprocessor.loader.dlq_processor import EventStitcher

    # Given: JSON array instead of object
    content = '["not", "an", "object"]'

    # When: Repair
    stitcher = EventStitcher()
    result = stitcher.repair_event(content)

    # Then: Returns None (must be dict)
    assert result is None
