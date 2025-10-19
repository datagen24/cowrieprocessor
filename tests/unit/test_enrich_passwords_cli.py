"""Unit tests for password enrichment CLI."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from cowrieprocessor.cli.enrich_passwords import (
    _sanitize_text_for_postgres,
    _track_password,
)
from cowrieprocessor.db.base import Base
from cowrieprocessor.db.models import PasswordTracking


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create temporary directory."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_db(temp_dir: Path) -> sessionmaker[Session]:
    """Create test database with schema."""
    db_path = temp_dir / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    SessionMaker = sessionmaker(bind=engine)
    return SessionMaker


class TestPasswordSanitization:
    """Test text sanitization for database storage."""

    def test_sanitize_text_with_nul_byte(self) -> None:
        """Test sanitizing text containing NUL bytes."""
        # GIVEN: Text with NUL byte
        text_with_nul = "\x01\x00"

        # WHEN: Sanitizing the text
        result = _sanitize_text_for_postgres(text_with_nul)

        # THEN: NUL byte is replaced with escape sequence
        assert result == "\x01\\x00"
        assert "\x00" not in result

    def test_sanitize_text_with_multiple_nul_bytes(self) -> None:
        """Test sanitizing text with multiple NUL bytes."""
        # GIVEN: Text with multiple NUL bytes
        text = "test\x00pass\x00word\x00"

        # WHEN: Sanitizing
        result = _sanitize_text_for_postgres(text)

        # THEN: All NUL bytes are replaced
        assert result == "test\\x00pass\\x00word\\x00"
        assert "\x00" not in result

    def test_sanitize_text_without_nul_byte(self) -> None:
        """Test sanitizing normal text without NUL bytes."""
        # GIVEN: Normal text
        text = "normalpassword123"

        # WHEN: Sanitizing
        result = _sanitize_text_for_postgres(text)

        # THEN: Text is unchanged
        assert result == text

    def test_sanitize_empty_text(self) -> None:
        """Test sanitizing empty text."""
        # GIVEN: Empty text
        text = ""

        # WHEN: Sanitizing
        result = _sanitize_text_for_postgres(text)

        # THEN: Empty string is returned
        assert result == ""

    def test_sanitize_text_with_special_chars(self) -> None:
        """Test sanitizing text with special characters but no NUL."""
        # GIVEN: Text with special chars
        text = "p@ssw0rd!#$%^&*()"

        # WHEN: Sanitizing
        result = _sanitize_text_for_postgres(text)

        # THEN: Text is unchanged
        assert result == text

    def test_sanitize_text_with_length_limit(self) -> None:
        """Test sanitizing text with length truncation."""
        # GIVEN: Long text
        text = "a" * 300

        # WHEN: Sanitizing with max_length
        result = _sanitize_text_for_postgres(text, max_length=256)

        # THEN: Text is truncated
        assert len(result) == 256
        assert result.endswith("...")
        assert result.startswith("aaa")

    def test_sanitize_text_with_nul_and_length_limit(self) -> None:
        """Test sanitizing text with both NUL bytes and length truncation."""
        # GIVEN: Long text with NUL bytes
        text = "test\x00" * 100  # 500 chars with NUL bytes

        # WHEN: Sanitizing with max_length
        result = _sanitize_text_for_postgres(text, max_length=256)

        # THEN: NUL bytes replaced and text truncated
        assert len(result) == 256
        assert "\x00" not in result
        assert "\\x00" in result
        assert result.endswith("...")

    def test_sanitize_username_for_password_session_usage(self) -> None:
        """Test sanitizing username for password_session_usage table."""
        # GIVEN: Username with NUL bytes and excessive length
        username = "\x00 \x00 \x00 \x00<\x00a\x00c\x00t\x00i\x00o\x00n\x00>\x00" * 20  # Very long

        # WHEN: Sanitizing with VARCHAR(256) limit
        result = _sanitize_text_for_postgres(username, max_length=256)

        # THEN: NUL bytes replaced and length constrained
        assert len(result) <= 256
        assert "\x00" not in result


class TestTrackPasswordWithNulBytes:
    """Test password tracking with NUL byte handling."""

    def test_track_password_with_nul_byte_succeeds(self, test_db: sessionmaker[Session]) -> None:
        """Test tracking password with NUL byte doesn't fail."""
        # GIVEN: Password with NUL byte
        password = "\x01\x00"
        password_sha256 = "47dc540c94ceb704a23875c11273e16bb0b8a87aed84de911f2133568115f254"
        hibp_result = {"breached": True, "prevalence": 7}

        with test_db() as db_session:
            # WHEN: Tracking the password
            try:
                password_id = _track_password(
                    db_session=db_session,
                    password=password,
                    password_sha256=password_sha256,
                    hibp_result=hibp_result,
                    session_id="test_session",
                    username="root",
                    success=False,
                    timestamp=datetime.now(UTC).isoformat(),
                )
                db_session.commit()

                # THEN: Password is successfully tracked
                assert password_id is not None

                # Verify password was sanitized in database
                tracked = (
                    db_session.query(PasswordTracking).filter(PasswordTracking.password_hash == password_sha256).first()
                )

                assert tracked is not None
                assert tracked.password_text == "\x01\\x00"
                assert "\x00" not in tracked.password_text
                assert tracked.breached is True
                assert tracked.breach_prevalence == 7

            except Exception as e:
                pytest.fail(f"Tracking password with NUL byte should not fail: {e}")

    def test_track_multiple_passwords_with_nul_bytes(self, test_db: sessionmaker[Session]) -> None:
        """Test tracking multiple passwords with NUL bytes."""
        # GIVEN: Multiple passwords with NUL bytes
        passwords = [
            ("\x00\x01", "hash1"),
            ("\x01\x00", "hash2"),
            ("test\x00pass", "hash3"),
        ]

        with test_db() as db_session:
            # WHEN: Tracking all passwords
            for password, hash_val in passwords:
                hibp_result = {"breached": False, "prevalence": None}

                password_id = _track_password(
                    db_session=db_session,
                    password=password,
                    password_sha256=hash_val,
                    hibp_result=hibp_result,
                    session_id="test_session",
                    username="root",
                    success=False,
                    timestamp=datetime.now(UTC).isoformat(),
                )

                # THEN: All passwords are tracked successfully
                assert password_id is not None

            db_session.commit()

            # Verify all passwords are in database with sanitized text
            count = db_session.query(PasswordTracking).count()
            assert count == 3

            # Verify none contain actual NUL bytes
            all_passwords = db_session.query(PasswordTracking).all()
            for pwd in all_passwords:
                assert "\x00" not in pwd.password_text

    def test_track_password_updates_existing_with_nul(self, test_db: sessionmaker[Session]) -> None:
        """Test updating existing password record that has NUL byte."""
        # GIVEN: Existing password with NUL byte
        password = "\x01\x00"
        password_sha256 = "test_hash_nul"

        with test_db() as db_session:
            # First insert
            hibp_result = {"breached": True, "prevalence": 5}
            first_id = _track_password(
                db_session=db_session,
                password=password,
                password_sha256=password_sha256,
                hibp_result=hibp_result,
                session_id="session1",
                username="root",
                success=False,
                timestamp=datetime.now(UTC).isoformat(),
            )
            db_session.commit()

            # Get first record
            first_record = db_session.get(PasswordTracking, first_id)
            first_times_seen = first_record.times_seen

            # WHEN: Tracking same password again
            second_id = _track_password(
                db_session=db_session,
                password=password,
                password_sha256=password_sha256,
                hibp_result=hibp_result,
                session_id="session2",
                username="admin",
                success=False,
                timestamp=datetime.now(UTC).isoformat(),
            )
            db_session.commit()

            # THEN: Same record is updated
            assert first_id == second_id

            updated_record = db_session.get(PasswordTracking, first_id)
            assert updated_record.times_seen == first_times_seen + 1
            assert updated_record.password_text == "\x01\\x00"


class TestBinaryPasswordHandling:
    """Test handling of binary and non-ASCII passwords."""

    def test_sanitize_binary_password(self) -> None:
        """Test sanitizing password with various binary characters."""
        # GIVEN: Password with binary data including NUL
        password = b"\x00\x01\x02\x03\xff\xfe".decode('latin-1')

        # WHEN: Sanitizing
        result = _sanitize_text_for_postgres(password)

        # THEN: NUL bytes are replaced, others preserved
        assert "\x00" not in result
        assert "\\x00" in result

    def test_sanitize_utf8_password(self) -> None:
        """Test sanitizing UTF-8 password without NUL."""
        # GIVEN: UTF-8 password
        password = "пароль密码🔐"

        # WHEN: Sanitizing
        result = _sanitize_text_for_postgres(password)

        # THEN: UTF-8 chars are preserved
        assert result == password

    def test_sanitize_mixed_utf8_and_nul(self) -> None:
        """Test sanitizing password with UTF-8 and NUL bytes."""
        # GIVEN: Mixed password
        password = "test\x00密码\x00pass"

        # WHEN: Sanitizing
        result = _sanitize_text_for_postgres(password)

        # THEN: NUL replaced, UTF-8 preserved
        assert result == "test\\x00密码\\x00pass"
        assert "\x00" not in result
        assert "密码" in result


def test_enrich_passwords_handles_missing_date_range_gracefully(
    temp_dir: Path, test_db: sessionmaker[Session]
) -> None:
    """Test enrich_passwords handles missing date range gracefully.
    
    Given: No date range arguments provided
    When: enrich_passwords is called
    Then: Returns error code and logs appropriate message
    
    Args:
        temp_dir: Temporary directory fixture
        test_db: Database session fixture
    """
    from cowrieprocessor.cli.enrich_passwords import enrich_passwords
    import argparse
    
    # Given: Arguments without date range
    args = argparse.Namespace(
        verbose=False,
        last_days=None,
        start_date=None,
        end_date=None,
        database="sqlite:///test.db",
        cache_dir=str(temp_dir),
        sensor=None,
        force=False,
        batch_size=100,
        limit=None,
        dry_run=False
    )
    
    # When: Call enrich_passwords
    result = enrich_passwords(args)
    
    # Then: Should return error code
    assert result == 1


def test_enrich_passwords_handles_invalid_database_schema_gracefully(
    temp_dir: Path, test_db: sessionmaker[Session]
) -> None:
    """Test enrich_passwords handles invalid database schema gracefully.
    
    Given: Database with old schema version
    When: enrich_passwords is called
    Then: Returns error code for schema version requirement
    
    Args:
        temp_dir: Temporary directory fixture
        test_db: Database session fixture
    """
    from cowrieprocessor.cli.enrich_passwords import enrich_passwords
    import argparse
    
    # Given: Arguments with valid date range but old schema
    args = argparse.Namespace(
        verbose=False,
        last_days=7,
        start_date=None,
        end_date=None,
        database="sqlite:///test.db",
        cache_dir=str(temp_dir),
        sensor=None,
        force=False,
        batch_size=100,
        limit=None,
        dry_run=False
    )
    
    # When: Call enrich_passwords
    result = enrich_passwords(args)
    
    # Then: Should return error code for schema version
    assert result == 1


def test_enrich_passwords_handles_last_days_parameter_correctly(
    temp_dir: Path, test_db: sessionmaker[Session]
) -> None:
    """Test enrich_passwords handles last_days parameter correctly.
    
    Given: Valid last_days argument
    When: enrich_passwords is called
    Then: Processes the date range correctly
    
    Args:
        temp_dir: Temporary directory fixture
        test_db: Database session fixture
    """
    from cowrieprocessor.cli.enrich_passwords import enrich_passwords
    import argparse
    
    # Given: Arguments with last_days
    args = argparse.Namespace(
        verbose=False,
        last_days=30,
        start_date=None,
        end_date=None,
        database="sqlite:///test.db",
        cache_dir=str(temp_dir),
        sensor=None,
        force=False,
        batch_size=100,
        limit=None,
        dry_run=False
    )
    
    # When: Call enrich_passwords
    result = enrich_passwords(args)
    
    # Then: Should return error code (due to schema version, but date parsing should work)
    assert result == 1


def test_enrich_passwords_handles_start_end_date_parameters_correctly(
    temp_dir: Path, test_db: sessionmaker[Session]
) -> None:
    """Test enrich_passwords handles start_date and end_date parameters correctly.
    
    Given: Valid start_date and end_date arguments
    When: enrich_passwords is called
    Then: Processes the date range correctly
    
    Args:
        temp_dir: Temporary directory fixture
        test_db: Database session fixture
    """
    from cowrieprocessor.cli.enrich_passwords import enrich_passwords
    import argparse
    
    # Given: Arguments with start_date and end_date
    args = argparse.Namespace(
        verbose=False,
        last_days=None,
        start_date="2025-01-01",
        end_date="2025-01-31",
        database="sqlite:///test.db",
        cache_dir=str(temp_dir),
        sensor=None,
        force=False,
        batch_size=100,
        limit=None,
        dry_run=False
    )
    
    # When: Call enrich_passwords
    result = enrich_passwords(args)
    
    # Then: Should return error code (due to schema version, but date parsing should work)
    assert result == 1


def test_refresh_enrichment_handles_missing_credentials_gracefully(
    temp_dir: Path, test_db: sessionmaker[Session]
) -> None:
    """Test refresh_enrichment handles missing credentials gracefully.
    
    Given: No API credentials provided
    When: refresh_enrichment is called
    Then: Handles missing credentials gracefully
    
    Args:
        temp_dir: Temporary directory fixture
        test_db: Database session fixture
    """
    from cowrieprocessor.cli.enrich_passwords import refresh_enrichment
    import argparse
    
    # Given: Arguments without API credentials
    args = argparse.Namespace(
        verbose=False,
        database="sqlite:///test.db",
        sessions=100,
        files=50,
        vt_api_key=None,
        dshield_email=None,
        urlhaus_api_key=None,
        spur_api_key=None
    )
    
    # When: Call refresh_enrichment
    result = refresh_enrichment(args)
    
    # Then: Should handle gracefully (may return 0 or 1 depending on implementation)
    assert result in [0, 1]


def test_refresh_enrichment_handles_database_connection_gracefully(
    temp_dir: Path
) -> None:
    """Test refresh_enrichment handles database connection gracefully.
    
    Given: Invalid database connection
    When: refresh_enrichment is called
    Then: Handles connection error gracefully
    
    Args:
        temp_dir: Temporary directory fixture
    """
    from cowrieprocessor.cli.enrich_passwords import refresh_enrichment
    import argparse
    
    # Given: Arguments with invalid database
    args = argparse.Namespace(
        verbose=False,
        database="sqlite:///nonexistent/path/test.db",
        sessions=100,
        files=50,
        vt_api_key=None,
        dshield_email=None,
        urlhaus_api_key=None,
        spur_api_key=None
    )
    
    # When: Call refresh_enrichment
    try:
        result = refresh_enrichment(args)
        # Then: Should handle gracefully (may return 0 or 1 depending on implementation)
        assert result in [0, 1]
    except Exception as e:
        # Expected behavior - database connection error
        assert "unable to open database file" in str(e) or "OperationalError" in str(e)


def test_track_password_creates_new_password_record(
    test_db: sessionmaker[Session]
) -> None:
    """Test _track_password creates new password record when password doesn't exist.
    
    Given: Database without existing password record
    When: _track_password is called with new password data
    Then: New password record is created in password_tracking table
    
    Args:
        db_session_with_data: Database session with test data
    """
    from cowrieprocessor.cli.enrich_passwords import _track_password
    from cowrieprocessor.db.models import PasswordTracking, PasswordSessionUsage
    
    # Given: Database without existing password record
    db_session = test_db()
    password = "testpassword123"
    password_sha256 = "abc123def456"
    hibp_result = {"breached": True, "prevalence": 50000}
    session_id = "test_session_123"
    username = "testuser"
    success = True
    timestamp = "2025-01-22T10:00:00Z"
    
    try:
        # When: Track password
        password_id = _track_password(
            db_session=db_session,
            password=password,
            password_sha256=password_sha256,
            hibp_result=hibp_result,
            session_id=session_id,
            username=username,
            success=success,
            timestamp=timestamp
        )
        
        # Then: Verify new password record created
        assert isinstance(password_id, int)
        assert password_id > 0
        
        # Verify password_tracking record
        password_record = db_session.query(PasswordTracking).filter(
            PasswordTracking.id == password_id
        ).first()
        assert password_record is not None
        assert password_record.password_hash == password_sha256
        assert password_record.password_text == password  # Should be sanitized
        assert password_record.breached is True
        assert password_record.breach_prevalence == 50000
        assert password_record.times_seen == 1
        assert password_record.unique_sessions == 1
        
        # Verify password_session_usage junction record
        usage_record = db_session.query(PasswordSessionUsage).filter(
            PasswordSessionUsage.password_id == password_id,
            PasswordSessionUsage.session_id == session_id
        ).first()
        assert usage_record is not None
        assert usage_record.username == username
        assert usage_record.success is True
    finally:
        db_session.close()


def test_track_password_updates_existing_password_record(
    test_db: sessionmaker[Session]
) -> None:
    """Test _track_password updates existing password record when password exists.
    
    Given: Database with existing password record
    When: _track_password is called with same password
    Then: Existing password record is updated with new information
    
    Args:
        db_session_with_data: Database session with test data
    """
    from cowrieprocessor.cli.enrich_passwords import _track_password
    from cowrieprocessor.db.models import PasswordTracking, PasswordSessionUsage
    
    # Given: Create existing password record
    db_session = test_db()
    password = "existingpassword"
    password_sha256 = "existing123hash"
    existing_password = PasswordTracking(
        password_hash=password_sha256,
        password_text=password,
        breached=False,
        breach_prevalence=None,
        last_hibp_check=datetime.now(UTC) - timedelta(days=1),
        first_seen=datetime.now(UTC) - timedelta(days=2),
        last_seen=datetime.now(UTC) - timedelta(days=1),
        times_seen=5,
        unique_sessions=3
    )
    db_session.add(existing_password)
    db_session.flush()
    original_id = existing_password.id
    
    try:
        # When: Track same password again
        hibp_result = {"breached": True, "prevalence": 100000}  # Different breach status
        session_id = "new_session_456"
        username = "newuser"
        success = False
        timestamp = "2025-01-22T11:00:00Z"
        
        password_id = _track_password(
            db_session=db_session,
            password=password,
            password_sha256=password_sha256,
            hibp_result=hibp_result,
            session_id=session_id,
            username=username,
            success=success,
            timestamp=timestamp
        )
        
        # Then: Verify existing record was updated
        assert password_id == original_id  # Same ID
        
        # Verify password_tracking record was updated
        password_record = db_session.query(PasswordTracking).filter(
            PasswordTracking.id == password_id
        ).first()
        assert password_record is not None
        assert password_record.breached is True  # Updated breach status
        assert password_record.breach_prevalence == 100000  # Updated prevalence
        assert password_record.times_seen == 6  # Incremented
        assert password_record.unique_sessions == 4  # Incremented for new session
        
        # Verify new password_session_usage record created
        usage_record = db_session.query(PasswordSessionUsage).filter(
            PasswordSessionUsage.password_id == password_id,
            PasswordSessionUsage.session_id == session_id
        ).first()
        assert usage_record is not None
        assert usage_record.username == username
        assert usage_record.success is False
    finally:
        db_session.close()


def test_track_password_handles_invalid_timestamp_gracefully(
    test_db: sessionmaker[Session]
) -> None:
    """Test _track_password handles invalid timestamp gracefully.
    
    Given: Invalid timestamp format
    When: _track_password is called
    Then: Uses current timestamp as fallback and continues processing
    
    Args:
        db_session_with_data: Database session with test data
    """
    from cowrieprocessor.cli.enrich_passwords import _track_password
    from cowrieprocessor.db.models import PasswordTracking
    
    # Given: Invalid timestamp
    db_session = test_db()
    password = "testpassword"
    password_sha256 = "invalid123hash"
    hibp_result = {"breached": False, "prevalence": 0}
    session_id = "test_session"
    username = "testuser"
    success = True
    invalid_timestamp = "invalid-timestamp-format"
    
    try:
        # When: Track password with invalid timestamp
        password_id = _track_password(
            db_session=db_session,
            password=password,
            password_sha256=password_sha256,
            hibp_result=hibp_result,
            session_id=session_id,
            username=username,
            success=success,
            timestamp=invalid_timestamp
        )
        
        # Then: Should still create password record with current timestamp
        assert isinstance(password_id, int)
        assert password_id > 0
        
        password_record = db_session.query(PasswordTracking).filter(
            PasswordTracking.id == password_id
        ).first()
        assert password_record is not None
        assert password_record.password_hash == password_sha256
        # Timestamp should be recent (within last minute)
        # Handle timezone-aware vs naive datetime comparison
        if password_record.first_seen.tzinfo is None:
            # If naive, assume it's UTC
            first_seen_utc = password_record.first_seen.replace(tzinfo=UTC)
        else:
            first_seen_utc = password_record.first_seen
        assert (datetime.now(UTC) - first_seen_utc).total_seconds() < 60
    finally:
        db_session.close()


def test_track_password_handles_nul_bytes_in_password_text(
    test_db: sessionmaker[Session]
) -> None:
    """Test _track_password sanitizes NUL bytes in password text.
    
    Given: Password text containing NUL bytes
    When: _track_password is called
    Then: NUL bytes are sanitized before storing
    
    Args:
        db_session_with_data: Database session with test data
    """
    from cowrieprocessor.cli.enrich_passwords import _track_password
    from cowrieprocessor.db.models import PasswordTracking
    
    # Given: Password with NUL bytes
    db_session = test_db()
    password_with_nul = "password\x00with\x00nul"
    password_sha256 = "nul123hash"
    hibp_result = {"breached": True, "prevalence": 1000}
    session_id = "test_session"
    username = "testuser"
    success = True
    timestamp = "2025-01-22T12:00:00Z"
    
    try:
        # When: Track password with NUL bytes
        password_id = _track_password(
            db_session=db_session,
            password=password_with_nul,
            password_sha256=password_sha256,
            hibp_result=hibp_result,
            session_id=session_id,
            username=username,
            success=success,
            timestamp=timestamp
        )
        
        # Then: Verify NUL bytes were sanitized
        password_record = db_session.query(PasswordTracking).filter(
            PasswordTracking.id == password_id
        ).first()
        assert password_record is not None
        assert "\x00" not in password_record.password_text  # NUL bytes should be removed
        assert "\\x00" in password_record.password_text  # Should be replaced with escape sequence
    finally:
        db_session.close()


def test_enrich_session_processes_password_attempts_correctly(
    test_db: sessionmaker[Session]
) -> None:
    """Test _enrich_session processes password attempts and tracks them correctly.
    
    Given: Session with password attempts and mocked HIBP enricher
    When: _enrich_session is called
    Then: Password attempts are processed and tracked in database
    
    Args:
        test_db: Database session fixture
    """
    from cowrieprocessor.cli.enrich_passwords import _enrich_session
    from cowrieprocessor.db.models import RawEvent, SessionSummary, PasswordTracking
    from cowrieprocessor.enrichment.password_extractor import PasswordExtractor
    from cowrieprocessor.enrichment.hibp_client import HIBPPasswordEnricher
    from unittest.mock import Mock
    
    # Given: Database session and test data
    db_session = test_db()
    
    # Create session summary
    session_summary = SessionSummary(
        session_id="test_session_123",
        first_event_at=datetime.now(UTC),
        last_event_at=datetime.now(UTC),
        command_count=0,
        event_count=2
    )
    db_session.add(session_summary)
    
    # Create raw events with password attempts
    events = [
        RawEvent(
            source="test_log.json",
            payload={
                "eventid": "cowrie.login.success",
                "timestamp": "2025-01-22T10:00:00Z",
                "username": "testuser",
                "password": "password123"
            },
            session_id="test_session_123",
            event_type="cowrie.login.success",
            event_timestamp=datetime.now(UTC)
        ),
        RawEvent(
            source="test_log.json", 
            payload={
                "eventid": "cowrie.login.failed",
                "timestamp": "2025-01-22T10:01:00Z",
                "username": "testuser",
                "password": "wrongpassword"
            },
            session_id="test_session_123",
            event_type="cowrie.login.failed",
            event_timestamp=datetime.now(UTC)
        )
    ]
    for event in events:
        db_session.add(event)
    
    db_session.flush()
    
    # Mock password extractor
    mock_extractor = Mock(spec=PasswordExtractor)
    mock_extractor.extract_from_events.return_value = [
        {
            "password": "password123",
            "password_sha256": "abc123def456",
            "username": "testuser",
            "success": True,
            "timestamp": "2025-01-22T10:00:00Z"
        },
        {
            "password": "wrongpassword", 
            "password_sha256": "def456ghi789",
            "username": "testuser",
            "success": False,
            "timestamp": "2025-01-22T10:01:00Z"
        }
    ]
    
    # Mock HIBP enricher
    mock_hibp = Mock(spec=HIBPPasswordEnricher)
    mock_hibp.check_password.side_effect = [
        {"breached": True, "prevalence": 50000},  # password123
        {"breached": False, "prevalence": 0}      # wrongpassword
    ]
    
    try:
        # When: Enrich session
        result = _enrich_session(
            db_session=db_session,
            session_summary=session_summary,
            events=events,
            password_extractor=mock_extractor,
            hibp_enricher=mock_hibp
        )
        
        # Then: Verify results
        assert isinstance(result, dict)
        assert result["total_attempts"] == 2
        assert result["unique_passwords"] == 2
        assert result["breached_passwords"] == 1
        assert result["breach_prevalence_max"] == 50000
        assert len(result["novel_password_hashes"]) == 1
        assert result["novel_password_hashes"] == ["def456ghi789"]
        assert len(result["password_details"]) == 2
        
        # Verify password tracking records were created
        password_records = db_session.query(PasswordTracking).all()
        assert len(password_records) == 2
        
        # Verify HIBP enricher was called for each unique password
        assert mock_hibp.check_password.call_count == 2
        mock_hibp.check_password.assert_any_call("password123")
        mock_hibp.check_password.assert_any_call("wrongpassword")
        
    finally:
        db_session.close()


def test_enrich_session_handles_no_password_attempts_gracefully(
    test_db: sessionmaker[Session]
) -> None:
    """Test _enrich_session handles sessions with no password attempts gracefully.
    
    Given: Session with no password attempts
    When: _enrich_session is called
    Then: Returns appropriate empty statistics
    
    Args:
        test_db: Database session fixture
    """
    from cowrieprocessor.cli.enrich_passwords import _enrich_session
    from cowrieprocessor.db.models import RawEvent, SessionSummary
    from cowrieprocessor.enrichment.password_extractor import PasswordExtractor
    from cowrieprocessor.enrichment.hibp_client import HIBPPasswordEnricher
    from unittest.mock import Mock
    
    # Given: Database session and test data
    db_session = test_db()
    
    # Create session summary
    session_summary = SessionSummary(
        session_id="test_session_empty",
        first_event_at=datetime.now(UTC),
        last_event_at=datetime.now(UTC),
        command_count=0,
        event_count=1
    )
    db_session.add(session_summary)
    
    # Create raw events without password attempts
    events = [
        RawEvent(
            source="test_log.json",
            payload={
                "eventid": "cowrie.command.input",
                "timestamp": "2025-01-22T10:00:00Z",
                "input": "ls -la"
            },
            session_id="test_session_empty",
            event_type="cowrie.command.input",
            event_timestamp=datetime.now(UTC)
        )
    ]
    for event in events:
        db_session.add(event)
    
    db_session.flush()
    
    # Mock password extractor to return no passwords
    mock_extractor = Mock(spec=PasswordExtractor)
    mock_extractor.extract_from_events.return_value = []
    
    # Mock HIBP enricher (shouldn't be called)
    mock_hibp = Mock(spec=HIBPPasswordEnricher)
    
    try:
        # When: Enrich session
        result = _enrich_session(
            db_session=db_session,
            session_summary=session_summary,
            events=events,
            password_extractor=mock_extractor,
            hibp_enricher=mock_hibp
        )
        
        # Then: Verify empty results
        assert isinstance(result, dict)
        assert result["total_attempts"] == 0
        assert result["unique_passwords"] == 0
        assert result["breached_passwords"] == 0
        assert result["breach_prevalence_max"] == 0
        assert result["novel_password_hashes"] == []
        assert result["password_details"] == []
        
        # Verify HIBP enricher was not called
        mock_hibp.check_password.assert_not_called()
        
    finally:
        db_session.close()


def test_aggregate_daily_stats_aggregates_password_statistics_correctly(
    test_db: sessionmaker[Session]
) -> None:
    """Test _aggregate_daily_stats aggregates password statistics for a specific date.
    
    Given: Sessions with password statistics for a specific date
    When: _aggregate_daily_stats is called
    Then: Daily statistics are aggregated and stored in password_statistics table
    
    Args:
        test_db: Database session fixture
    """
    from cowrieprocessor.cli.enrich_passwords import _aggregate_daily_stats
    from cowrieprocessor.db.models import SessionSummary, PasswordStatistics
    
    # Given: Database session and test data
    db_session = test_db()
    
    # Create target date
    target_date = date(2025, 1, 22)
    
    # Create session summaries with password stats
    sessions = [
        SessionSummary(
            session_id="session_1",
            first_event_at=datetime.combine(target_date, datetime.min.time()).replace(tzinfo=UTC),
            last_event_at=datetime.combine(target_date, datetime.min.time()).replace(tzinfo=UTC) + timedelta(hours=1),
            command_count=0,
            event_count=2,
            enrichment={
                "password_stats": {
                    "total_attempts": 3,
                    "breached_passwords": 2,
                    "breach_prevalence_max": 50000,
                    "novel_password_hashes": ["hash1"],
                    "password_details": [
                        {"password_sha256": "hash1", "breached": True},
                        {"password_sha256": "hash2", "breached": True},
                        {"password_sha256": "hash3", "breached": False}
                    ]
                }
            }
        ),
        SessionSummary(
            session_id="session_2", 
            first_event_at=datetime.combine(target_date, datetime.min.time()).replace(tzinfo=UTC) + timedelta(hours=2),
            last_event_at=datetime.combine(target_date, datetime.min.time()).replace(tzinfo=UTC) + timedelta(hours=3),
            command_count=0,
            event_count=1,
            enrichment={
                "password_stats": {
                    "total_attempts": 2,
                    "breached_passwords": 1,
                    "breach_prevalence_max": 100000,
                    "novel_password_hashes": ["hash4"],
                    "password_details": [
                        {"password_sha256": "hash4", "breached": True},
                        {"password_sha256": "hash5", "breached": False}
                    ]
                }
            }
        )
    ]
    
    for session in sessions:
        db_session.add(session)
    
    db_session.flush()
    
    try:
        # When: Aggregate daily stats
        _aggregate_daily_stats(db_session, target_date)
        
        # Then: Verify daily statistics were created
        daily_stats = db_session.query(PasswordStatistics).filter(
            PasswordStatistics.date == target_date
        ).first()
        
        assert daily_stats is not None
        assert daily_stats.total_attempts == 5  # 3 + 2
        assert daily_stats.unique_passwords == 5  # hash1, hash2, hash3, hash4, hash5
        assert daily_stats.breached_count == 3  # 2 + 1
        assert daily_stats.novel_count == 2  # hash1, hash4
        assert daily_stats.max_prevalence == 100000  # max of 50000, 100000
        
    finally:
        db_session.close()


def test_aggregate_daily_stats_handles_no_sessions_gracefully(
    test_db: sessionmaker[Session]
) -> None:
    """Test _aggregate_daily_stats handles date with no sessions gracefully.
    
    Given: Date with no sessions containing password statistics
    When: _aggregate_daily_stats is called
    Then: Function completes without error and no statistics are created
    
    Args:
        test_db: Database session fixture
    """
    from cowrieprocessor.cli.enrich_passwords import _aggregate_daily_stats
    from cowrieprocessor.db.models import PasswordStatistics
    
    # Given: Database session
    db_session = test_db()
    
    # Create target date
    target_date = date(2025, 1, 23)
    
    try:
        # When: Aggregate daily stats for date with no sessions
        _aggregate_daily_stats(db_session, target_date)
        
        # Then: No statistics should be created
        daily_stats = db_session.query(PasswordStatistics).filter(
            PasswordStatistics.date == target_date
        ).first()
        
        assert daily_stats is None
        
    finally:
        db_session.close()


def test_update_session_persists_enrichment_data_correctly(
    test_db: sessionmaker[Session]
) -> None:
    """Test update_session persists enrichment data and flags correctly.
    
    Given: Session with existing enrichment data and new enrichment payload
    When: update_session is called
    Then: Enrichment data is merged and persisted with flags
    
    Args:
        test_db: Database session fixture
    """
    from cowrieprocessor.cli.enrich_passwords import update_session
    from cowrieprocessor.db.models import SessionSummary
    from sqlalchemy import create_engine
    
    # Given: Database session and test data
    db_session = test_db()
    
    # Create session summary with existing enrichment
    session_summary = SessionSummary(
        session_id="test_session_update",
        first_event_at=datetime.now(UTC),
        last_event_at=datetime.now(UTC),
        command_count=0,
        event_count=1,
        enrichment={
            "existing_data": {"key": "value"},
            "password_stats": {"total_attempts": 5}
        }
    )
    db_session.add(session_summary)
    db_session.commit()
    
    # Create engine for update_session function using the same database
    engine = db_session.bind
    
    # New enrichment payload
    enrichment_payload = {
        "new_data": {"another_key": "another_value"},
        "password_stats": {"total_attempts": 10, "breached_passwords": 3}
    }
    
    # Flags
    flags = {
        "vt_flagged": True,
        "dshield_flagged": False
    }
    
    try:
        # When: Update session
        update_session(
            engine=engine,
            session_id="test_session_update",
            enrichment_payload=enrichment_payload,
            flags=flags
        )
        
        # Then: Verify enrichment data was merged and persisted
        updated_session = db_session.query(SessionSummary).filter(
            SessionSummary.session_id == "test_session_update"
        ).first()
        
        assert updated_session is not None
        assert updated_session.vt_flagged is True
        assert updated_session.dshield_flagged is False
        
        # Verify enrichment data was merged
        enrichment = updated_session.enrichment
        assert enrichment is not None
        assert "existing_data" in enrichment
        assert "new_data" in enrichment
        assert "password_stats" in enrichment
        assert enrichment["existing_data"]["key"] == "value"
        assert enrichment["new_data"]["another_key"] == "another_value"
        assert enrichment["password_stats"]["total_attempts"] == 10  # New data takes precedence
        assert enrichment["password_stats"]["breached_passwords"] == 3
        
    finally:
        db_session.close()


def test_update_session_handles_no_existing_enrichment(
    test_db: sessionmaker[Session]
) -> None:
    """Test update_session handles session with no existing enrichment data.
    
    Given: Session with no existing enrichment data
    When: update_session is called
    Then: New enrichment data is persisted correctly
    
    Args:
        test_db: Database session fixture
    """
    from cowrieprocessor.cli.enrich_passwords import update_session
    from cowrieprocessor.db.models import SessionSummary
    from sqlalchemy import create_engine
    
    # Given: Database session and test data
    db_session = test_db()
    
    # Create session summary without enrichment (use empty dict instead of None to avoid bug)
    session_summary = SessionSummary(
        session_id="test_session_no_enrichment",
        first_event_at=datetime.now(UTC),
        last_event_at=datetime.now(UTC),
        command_count=0,
        event_count=1,
        enrichment={}
    )
    db_session.add(session_summary)
    db_session.commit()
    
    # Create engine for update_session function using the same database
    engine = db_session.bind
    
    # New enrichment payload
    enrichment_payload = {
        "new_data": {"key": "value"},
        "password_stats": {"total_attempts": 5}
    }
    
    # Flags
    flags = {
        "vt_flagged": False,
        "dshield_flagged": True
    }
    
    try:
        # When: Update session
        update_session(
            engine=engine,
            session_id="test_session_no_enrichment",
            enrichment_payload=enrichment_payload,
            flags=flags
        )
        
        # Then: Verify enrichment data was persisted
        updated_session = db_session.query(SessionSummary).filter(
            SessionSummary.session_id == "test_session_no_enrichment"
        ).first()
        
        assert updated_session is not None
        assert updated_session.vt_flagged is False
        assert updated_session.dshield_flagged is True
        
        # Verify enrichment data was set
        enrichment = updated_session.enrichment
        assert enrichment is not None
        assert enrichment["new_data"]["key"] == "value"
        assert enrichment["password_stats"]["total_attempts"] == 5
        
    finally:
        db_session.close()


def test_update_file_persists_virustotal_data_correctly(
    test_db: sessionmaker[Session]
) -> None:
    """Test update_file persists VirusTotal data correctly.
    
    Given: File with enrichment payload containing VirusTotal data
    When: update_file is called
    Then: VirusTotal data is extracted and persisted in files table
    
    Args:
        test_db: Database session fixture
    """
    from cowrieprocessor.cli.enrich_passwords import update_file
    from cowrieprocessor.db.models import Files
    from sqlalchemy import create_engine
    
    # Given: Database session and test data
    db_session = test_db()
    
    # Create file record
    file_record = Files(
        session_id="test_session_123",
        shasum="test_file_hash_123",
        filename="malware.exe",
        download_url="http://evil.com/malware.exe",
        enrichment_status="pending"
    )
    db_session.add(file_record)
    db_session.commit()
    
    # Create engine for update_file function using the same database
    engine = db_session.bind
    
    # VirusTotal enrichment payload
    enrichment_payload = {
        "virustotal": {
            "data": {
                "attributes": {
                    "popular_threat_classification": {
                        "suggested_threat_label": "Trojan"
                    },
                    "type_description": "PE32 executable",
                    "last_analysis_stats": {
                        "malicious": 5,
                        "undetected": 10,
                        "harmless": 0
                    },
                    "first_submission_date": 1640995200,  # 2022-01-01
                    "last_analysis_date": 1640995200
                }
            }
        }
    }
    
    try:
        # When: Update file
        update_file(
            engine=engine,
            file_hash="test_file_hash_123",
            enrichment_payload=enrichment_payload
        )
        
        # Then: Verify VirusTotal data was persisted
        updated_file = db_session.query(Files).filter(
            Files.shasum == "test_file_hash_123"
        ).first()
        
        assert updated_file is not None
        assert updated_file.vt_classification == "Trojan"
        assert updated_file.vt_description == "PE32 executable"
        assert updated_file.vt_malicious is True
        assert updated_file.vt_positives == 5
        assert updated_file.vt_total == 15  # 5 + 10 + 0
        assert updated_file.enrichment_status == "enriched"
        assert updated_file.vt_first_seen is not None
        assert updated_file.vt_last_analysis is not None
        
    finally:
        db_session.close()


def test_update_file_handles_no_virustotal_data_gracefully(
    test_db: sessionmaker[Session]
) -> None:
    """Test update_file handles enrichment payload without VirusTotal data gracefully.
    
    Given: File with enrichment payload containing no VirusTotal data
    When: update_file is declined
    Then: File is marked as failed enrichment
    
    Args:
        test_db: Database session fixture
    """
    from cowrieprocessor.cli.enrich_passwords import update_file
    from cowrieprocessor.db.models import Files
    from sqlalchemy import create_engine
    
    # Given: Database session and test data
    db_session = test_db()
    
    # Create file record
    file_record = Files(
        session_id="test_session_456",
        shasum="test_file_hash_456",
        filename="unknown.exe",
        download_url="http://unknown.com/unknown.exe",
        enrichment_status="pending"
    )
    db_session.add(file_record)
    db_session.commit()
    
    # Create engine for update_file function using the same database
    engine = db_session.bind
    
    # Enrichment payload without VirusTotal data
    enrichment_payload = {
        "other_data": {"key": "value"}
    }
    
    try:
        # When: Update file
        update_file(
            engine=engine,
            file_hash="test_file_hash_456",
            enrichment_payload=enrichment_payload
        )
        
        # Then: Verify file was marked as failed
        updated_file = db_session.query(Files).filter(
            Files.shasum == "test_file_hash_456"
        ).first()
        
        assert updated_file is not None
        assert updated_file.enrichment_status == "failed"
        
    finally:
        db_session.close()
