"""Unit tests for Enhanced DLQ models (cowrieprocessor.db.enhanced_dlq_models)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from cowrieprocessor.db.base import Base
from cowrieprocessor.db.enhanced_dlq_models import (
    DLQCircuitBreakerState,
    DLQProcessingMetrics,
    EnhancedDeadLetterEvent,
)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Create an in-memory SQLite database session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionMaker = sessionmaker(bind=engine)
    session = SessionMaker()

    yield session

    session.close()


class TestEnhancedDeadLetterEventBasics:
    """Test EnhancedDeadLetterEvent model basic functionality."""

    def test_create_minimal_event(self, db_session: Session) -> None:
        """Test creating minimal enhanced DLQ event.

        Given: Minimal required fields
        When: Creating EnhancedDeadLetterEvent
        Then: Should create with defaults
        """
        event = EnhancedDeadLetterEvent(
            reason="json_parse_error",
            payload={"raw_data": "invalid json"},
        )

        db_session.add(event)
        db_session.commit()

        assert event.id is not None
        assert event.reason == "json_parse_error"
        assert event.retry_count == 0
        assert event.resolved is False
        assert event.priority == 5

    def test_create_full_event(self, db_session: Session) -> None:
        """Test creating enhanced DLQ event with all fields.

        Given: All available fields
        When: Creating EnhancedDeadLetterEvent
        Then: Should create with all values
        """
        event = EnhancedDeadLetterEvent(
            ingest_id="test-ingest-123",
            source="/var/log/cowrie.json",
            source_offset=1024,
            source_inode="987654",
            reason="schema_validation_error",
            payload={"eventid": "cowrie.session.connect", "session": "abc123"},
            metadata_json={"processor": "hybrid", "version": "2.0"},
            payload_checksum="abcd1234",
            retry_count=2,
            priority=1,
            classification="format_error",
        )

        db_session.add(event)
        db_session.commit()

        assert event.id is not None
        assert event.ingest_id == "test-ingest-123"
        assert event.source == "/var/log/cowrie.json"
        assert event.classification == "format_error"
        assert event.priority == 1


class TestEnhancedDeadLetterEventChecksum:
    """Test checksum calculation and validation."""

    def test_calculate_payload_checksum(self, db_session: Session) -> None:
        """Test payload checksum calculation.

        Given: Event with payload
        When: Calling _calculate_payload_checksum
        Then: Should return consistent SHA-256 hash
        """
        event = EnhancedDeadLetterEvent(
            reason="test",
            payload={"key1": "value1", "key2": "value2"},
        )

        checksum1 = event._calculate_payload_checksum()
        checksum2 = event._calculate_payload_checksum()

        assert checksum1 == checksum2
        assert len(checksum1) == 64  # SHA-256 hex digest length

    def test_checksum_deterministic(self, db_session: Session) -> None:
        """Test checksum is deterministic (key order doesn't matter).

        Given: Two events with same data but different key order
        When: Calculating checksums
        Then: Should produce identical checksums
        """
        event1 = EnhancedDeadLetterEvent(
            reason="test",
            payload={"key1": "value1", "key2": "value2"},
        )

        event2 = EnhancedDeadLetterEvent(
            reason="test",
            payload={"key2": "value2", "key1": "value1"},  # Different order
        )

        assert event1._calculate_payload_checksum() == event2._calculate_payload_checksum()

    def test_checksum_valid_no_checksum(self, db_session: Session) -> None:
        """Test checksum validation when no checksum is set.

        Given: Event without payload_checksum
        When: Checking checksum_valid
        Then: Should return True (no checksum to verify)
        """
        event = EnhancedDeadLetterEvent(
            reason="test",
            payload={"data": "test"},
        )

        assert event.checksum_valid is True

    def test_checksum_valid_correct(self, db_session: Session) -> None:
        """Test checksum validation with correct checksum.

        Given: Event with correct payload_checksum
        When: Checking checksum_valid
        Then: Should return True
        """
        event = EnhancedDeadLetterEvent(
            reason="test",
            payload={"data": "test"},
        )

        event.payload_checksum = event._calculate_payload_checksum()

        assert event.checksum_valid is True

    def test_checksum_valid_incorrect(self, db_session: Session) -> None:
        """Test checksum validation with incorrect checksum.

        Given: Event with mismatched payload_checksum
        When: Checking checksum_valid
        Then: Should return False
        """
        event = EnhancedDeadLetterEvent(
            reason="test",
            payload={"data": "test"},
        )

        event.payload_checksum = "invalid_checksum_12345"

        assert event.checksum_valid is False


class TestEnhancedDeadLetterEventLocking:
    """Test processing lock functionality."""

    def test_is_locked_no_lock(self, db_session: Session) -> None:
        """Test is_locked when no lock is set.

        Given: Event without processing_lock
        When: Checking is_locked
        Then: Should return False
        """
        event = EnhancedDeadLetterEvent(
            reason="test",
            payload={"data": "test"},
        )

        assert event.is_locked is False

    def test_acquire_processing_lock_success(self, db_session: Session) -> None:
        """Test successful lock acquisition.

        Given: Unlocked event
        When: Acquiring processing lock
        Then: Should succeed and set lock details
        """
        event = EnhancedDeadLetterEvent(
            reason="test",
            payload={"data": "test"},
        )

        lock_id = str(uuid.uuid4())
        result = event.acquire_processing_lock(lock_id, expires_in_minutes=30)

        assert result is True
        assert event.processing_lock == uuid.UUID(lock_id)
        assert event.lock_expires_at is not None
        assert event.is_locked is True

    def test_acquire_processing_lock_already_locked(self, db_session: Session) -> None:
        """Test lock acquisition when already locked.

        Given: Event with active lock
        When: Attempting to acquire lock again
        Then: Should fail
        """
        event = EnhancedDeadLetterEvent(
            reason="test",
            payload={"data": "test"},
        )

        lock_id1 = str(uuid.uuid4())
        event.acquire_processing_lock(lock_id1)

        lock_id2 = str(uuid.uuid4())
        result = event.acquire_processing_lock(lock_id2)

        assert result is False
        assert event.processing_lock == uuid.UUID(lock_id1)  # Original lock preserved

    def test_is_locked_expired(self, db_session: Session) -> None:
        """Test is_locked with expired lock.

        Given: Event with expired lock
        When: Checking is_locked
        Then: Should return False
        """
        event = EnhancedDeadLetterEvent(
            reason="test",
            payload={"data": "test"},
        )

        event.processing_lock = uuid.uuid4()
        event.lock_expires_at = datetime.now(UTC) - timedelta(minutes=1)  # Expired

        assert event.is_locked is False

    def test_release_processing_lock(self, db_session: Session) -> None:
        """Test lock release.

        Given: Event with active lock
        When: Releasing lock
        Then: Should clear lock details
        """
        event = EnhancedDeadLetterEvent(
            reason="test",
            payload={"data": "test"},
        )

        event.acquire_processing_lock(str(uuid.uuid4()))
        event.release_processing_lock()

        assert event.processing_lock is None
        assert event.lock_expires_at is None
        assert event.is_locked is False


class TestEnhancedDeadLetterEventErrorTracking:
    """Test error and processing attempt tracking."""

    def test_add_error_record_first(self, db_session: Session) -> None:
        """Test adding first error record.

        Given: Event with no error history
        When: Adding error record
        Then: Should initialize error_history and increment retry_count
        """
        event = EnhancedDeadLetterEvent(
            reason="test",
            payload={"data": "test"},
        )

        event.add_error_record("json_error", "Invalid JSON syntax", "hybrid_processor")

        assert len(event.error_history) == 1
        assert event.error_history[0]["error_type"] == "json_error"
        assert event.error_history[0]["error_message"] == "Invalid JSON syntax"
        assert event.error_history[0]["processing_method"] == "hybrid_processor"
        assert event.retry_count == 1
        assert event.last_processed_at is not None

    def test_add_error_record_multiple(self, db_session: Session) -> None:
        """Test adding multiple error records.

        Given: Event with existing error history
        When: Adding another error record
        Then: Should append and increment retry_count
        """
        event = EnhancedDeadLetterEvent(
            reason="test",
            payload={"data": "test"},
        )

        event.add_error_record("error1", "First error")
        event.add_error_record("error2", "Second error")
        event.add_error_record("error3", "Third error")

        assert len(event.error_history) == 3
        assert event.retry_count == 3
        assert event.error_history[2]["error_type"] == "error3"

    def test_add_processing_attempt_first(self, db_session: Session) -> None:
        """Test adding first processing attempt.

        Given: Event with no processing attempts
        When: Adding processing attempt
        Then: Should initialize processing_attempts
        """
        event = EnhancedDeadLetterEvent(
            reason="test",
            payload={"data": "test"},
        )

        event.add_processing_attempt("stored_proc", success=True, processing_time_ms=150)

        assert len(event.processing_attempts) == 1
        assert event.processing_attempts[0]["method"] == "stored_proc"
        assert event.processing_attempts[0]["success"] is True
        assert event.processing_attempts[0]["processing_time_ms"] == 150

    def test_add_processing_attempt_success_and_failure(self, db_session: Session) -> None:
        """Test adding mix of successful and failed attempts.

        Given: Event
        When: Adding both successful and failed attempts
        Then: Should track both with correct details
        """
        event = EnhancedDeadLetterEvent(
            reason="test",
            payload={"data": "test"},
        )

        event.add_processing_attempt("method1", success=True, processing_time_ms=100)
        event.add_processing_attempt("method2", success=False, processing_time_ms=50)
        event.add_processing_attempt("method3", success=True, processing_time_ms=200)

        assert len(event.processing_attempts) == 3
        assert event.processing_attempts[0]["success"] is True
        assert event.processing_attempts[1]["success"] is False
        assert event.processing_attempts[2]["success"] is True


class TestEnhancedDeadLetterEventResolution:
    """Test event resolution functionality."""

    def test_mark_resolved_basic(self, db_session: Session) -> None:
        """Test marking event as resolved.

        Given: Unresolved event
        When: Calling mark_resolved
        Then: Should set resolved flags
        """
        event = EnhancedDeadLetterEvent(
            reason="test",
            payload={"data": "test"},
        )

        event.mark_resolved("stored_proc")

        assert event.resolved is True
        assert event.resolved_at is not None
        assert event.resolution_method == "stored_proc"

    def test_mark_resolved_releases_lock(self, db_session: Session) -> None:
        """Test mark_resolved releases processing lock.

        Given: Event with active lock
        When: Calling mark_resolved
        Then: Should release lock
        """
        event = EnhancedDeadLetterEvent(
            reason="test",
            payload={"data": "test"},
        )

        event.acquire_processing_lock(str(uuid.uuid4()))
        assert event.is_locked is True

        event.mark_resolved("manual")

        assert event.is_locked is False
        assert event.processing_lock is None


class TestEnhancedDeadLetterEventIdempotency:
    """Test idempotency key generation."""

    def test_generate_idempotency_key_first_time(self, db_session: Session) -> None:
        """Test idempotency key generation.

        Given: Event without idempotency_key
        When: Calling generate_idempotency_key
        Then: Should generate and store key
        """
        event = EnhancedDeadLetterEvent(
            reason="test",
            payload={"data": "test"},
            source="/var/log/test.json",
            source_offset=1024,
        )

        event.payload_checksum = event._calculate_payload_checksum()
        key = event.generate_idempotency_key()

        assert key is not None
        assert len(key) == 64  # SHA-256 hex digest
        assert event.idempotency_key == key

    def test_generate_idempotency_key_idempotent(self, db_session: Session) -> None:
        """Test idempotency key generation is idempotent.

        Given: Event with existing idempotency_key
        When: Calling generate_idempotency_key again
        Then: Should return same key
        """
        event = EnhancedDeadLetterEvent(
            reason="test",
            payload={"data": "test"},
            source="/var/log/test.json",
            source_offset=1024,
        )

        event.payload_checksum = event._calculate_payload_checksum()
        key1 = event.generate_idempotency_key()
        key2 = event.generate_idempotency_key()

        assert key1 == key2


class TestDLQProcessingMetrics:
    """Test DLQProcessingMetrics model."""

    def test_create_metrics(self, db_session: Session) -> None:
        """Test creating processing metrics.

        Given: Metrics data
        When: Creating DLQProcessingMetrics
        Then: Should create with all fields
        """
        now = datetime.now(UTC)
        metrics = DLQProcessingMetrics(
            processing_session_id="session-123",
            processing_method="stored_proc",
            batch_size=100,
            processed_count=95,
            repaired_count=10,
            failed_count=5,
            skipped_count=0,
            processing_duration_ms=5000,
            avg_processing_time_ms=50,
            peak_memory_mb=256,
            circuit_breaker_triggered=False,
            rate_limit_hits=2,
            lock_timeout_count=0,
            started_at=now,
            completed_at=now + timedelta(seconds=5),
        )

        db_session.add(metrics)
        db_session.commit()

        assert metrics.id is not None
        assert metrics.processing_session_id == "session-123"
        assert metrics.batch_size == 100
        assert metrics.processed_count == 95
        assert metrics.circuit_breaker_triggered is False


class TestDLQCircuitBreakerState:
    """Test DLQCircuitBreakerState model."""

    def test_create_circuit_breaker_state(self, db_session: Session) -> None:
        """Test creating circuit breaker state.

        Given: Circuit breaker configuration
        When: Creating DLQCircuitBreakerState
        Then: Should create with all fields
        """
        breaker = DLQCircuitBreakerState(
            breaker_name="dlq_processor_main",
            state="closed",
            failure_count=0,
            failure_threshold=5,
            timeout_seconds=60,
        )

        db_session.add(breaker)
        db_session.commit()

        assert breaker.id is not None
        assert breaker.breaker_name == "dlq_processor_main"
        assert breaker.state == "closed"
        assert breaker.failure_threshold == 5

    def test_circuit_breaker_state_update(self, db_session: Session) -> None:
        """Test updating circuit breaker state.

        Given: Existing circuit breaker
        When: Updating state and failure_count
        Then: Should persist changes
        """
        breaker = DLQCircuitBreakerState(
            breaker_name="test_breaker",
            state="closed",
            failure_count=0,
        )

        db_session.add(breaker)
        db_session.commit()

        # Simulate failures
        breaker.failure_count = 3
        breaker.state = "half_open"
        breaker.last_failure_time = datetime.now(UTC)

        db_session.commit()

        assert breaker.failure_count == 3
        assert breaker.state == "half_open"
        assert breaker.last_failure_time is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
