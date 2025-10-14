"""Unit tests for password enrichment CLI."""

from __future__ import annotations

from datetime import UTC, datetime
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
