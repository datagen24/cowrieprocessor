"""Unit tests for session parser (loader/session_parser.py)."""

from __future__ import annotations

from typing import Dict, Optional, cast

import pytest

from cowrieprocessor.loader.session_parser import (
    SessionEnumerationResult,
    SessionMetrics,
    _coerce_epoch,
    _match_full_delimited,
    _match_session_id,
    _parse_duration_seconds,
    enumerate_sessions,
    match_session,
    serialize_metrics,
)


class TestCoerceEpoch:
    """Test _coerce_epoch timestamp conversion helper."""

    def test_coerce_none(self) -> None:
        """Test converting None returns None."""
        assert _coerce_epoch(None) is None

    def test_coerce_int(self) -> None:
        """Test converting int returns int."""
        assert _coerce_epoch(1698336000) == 1698336000

    def test_coerce_float(self) -> None:
        """Test converting float returns int."""
        assert _coerce_epoch(1698336000.123) == 1698336000

    def test_coerce_iso_with_z(self) -> None:
        """Test converting ISO timestamp with Z suffix."""
        result = _coerce_epoch("2025-10-25T12:30:45.123Z")
        assert isinstance(result, int)
        assert result > 0

    def test_coerce_iso_without_microseconds_z(self) -> None:
        """Test ISO timestamp without microseconds, with Z."""
        result = _coerce_epoch("2025-10-25T12:30:45Z")
        assert isinstance(result, int)

    def test_coerce_iso_with_microseconds(self) -> None:
        """Test ISO timestamp with microseconds, no Z."""
        result = _coerce_epoch("2025-10-25T12:30:45.123")
        assert isinstance(result, int)

    def test_coerce_iso_without_microseconds(self) -> None:
        """Test ISO timestamp without microseconds or Z."""
        result = _coerce_epoch("2025-10-25T12:30:45")
        assert isinstance(result, int)

    def test_coerce_space_delimited(self) -> None:
        """Test space-delimited timestamp format."""
        result = _coerce_epoch("2025-10-25 12:30:45")
        assert isinstance(result, int)

    def test_coerce_empty_string(self) -> None:
        """Test empty string returns None."""
        assert _coerce_epoch("") is None
        assert _coerce_epoch("   ") is None

    def test_coerce_invalid_string(self) -> None:
        """Test invalid string returns None."""
        assert _coerce_epoch("not-a-timestamp") is None

    def test_coerce_invalid_format(self) -> None:
        """Test invalid timestamp format returns None."""
        assert _coerce_epoch("2025-10-25") is None  # Missing time


class TestParseDurationSeconds:
    """Test _parse_duration_seconds helper."""

    def test_parse_int(self) -> None:
        """Test parsing int directly."""
        assert _parse_duration_seconds(300) == 300

    def test_parse_float(self) -> None:
        """Test parsing float converts to int."""
        assert _parse_duration_seconds(300.5) == 300

    def test_parse_hms_format(self) -> None:
        """Test parsing HH:MM:SS format."""
        assert _parse_duration_seconds("01:30:45") == 5445  # 1*3600 + 30*60 + 45

    def test_parse_zero_padded(self) -> None:
        """Test parsing zero-padded HH:MM:SS."""
        assert _parse_duration_seconds("00:05:30") == 330  # 5*60 + 30

    def test_parse_numeric_string(self) -> None:
        """Test parsing numeric string."""
        assert _parse_duration_seconds("300") == 300

    def test_parse_empty_string(self) -> None:
        """Test empty string returns None."""
        assert _parse_duration_seconds("") is None
        assert _parse_duration_seconds("   ") is None

    def test_parse_invalid_format(self) -> None:
        """Test invalid format returns None."""
        assert _parse_duration_seconds("1:30") is None  # Only 2 parts
        assert _parse_duration_seconds("not-a-duration") is None

    def test_parse_non_numeric_parts(self) -> None:
        """Test HH:MM:SS with non-numeric parts."""
        assert _parse_duration_seconds("01:3a:45") is None


class TestMatchFullDelimited:
    """Test _match_full_delimited session matcher."""

    def test_match_with_delimiters(self) -> None:
        """Test matching session ID with both - and /."""
        entry = {"session": "sensor-a/2025-10-25/abc-123"}
        result = _match_full_delimited(entry)
        assert result == "sensor-a/2025-10-25/abc-123"

    def test_match_no_session_field(self) -> None:
        """Test with missing session field."""
        entry: Dict[str, object] = {}
        assert _match_full_delimited(entry) is None

    def test_match_non_string_session(self) -> None:
        """Test with non-string session value."""
        entry = {"session": 12345}
        assert _match_full_delimited(entry) is None

    def test_match_missing_hyphen(self) -> None:
        """Test session without hyphen."""
        entry = {"session": "sensor/2025/abc"}
        assert _match_full_delimited(entry) is None

    def test_match_missing_slash(self) -> None:
        """Test session without slash."""
        entry = {"session": "sensor-abc-123"}
        assert _match_full_delimited(entry) is None

    def test_match_whitespace_trimmed(self) -> None:
        """Test that whitespace is trimmed."""
        entry = {"session": "  sensor-a/session-123  "}
        result = _match_full_delimited(entry)
        assert result == "sensor-a/session-123"

    def test_match_empty_string(self) -> None:
        """Test empty session string."""
        entry = {"session": ""}
        assert _match_full_delimited(entry) is None


class TestMatchSessionId:
    """Test _match_session_id session matcher."""

    def test_match_valid_session(self) -> None:
        """Test matching any non-empty session string."""
        entry = {"session": "abc123"}
        result = _match_session_id(entry)
        assert result == "abc123"

    def test_match_with_whitespace(self) -> None:
        """Test trimming whitespace."""
        entry = {"session": "  abc123  "}
        result = _match_session_id(entry)
        assert result == "abc123"

    def test_match_empty_session(self) -> None:
        """Test empty session returns None."""
        entry = {"session": ""}
        assert _match_session_id(entry) is None

    def test_match_whitespace_only(self) -> None:
        """Test whitespace-only session returns None."""
        entry = {"session": "   "}
        assert _match_session_id(entry) is None

    def test_match_no_session_field(self) -> None:
        """Test missing session field."""
        entry: Dict[str, object] = {}
        assert _match_session_id(entry) is None


class TestSessionMetrics:
    """Test SessionMetrics dataclass and update method."""

    def test_init(self) -> None:
        """Test SessionMetrics initialization."""
        metrics = SessionMetrics(session_id="test-123", match_type="full_delimited")
        assert metrics.session_id == "test-123"
        assert metrics.match_type == "full_delimited"
        assert metrics.command_count == 0
        assert metrics.login_attempts == 0
        assert metrics.total_events == 0

    def test_update_increments_total_events(self) -> None:
        """Test update increments total_events counter."""
        metrics = SessionMetrics(session_id="test-123", match_type="session_id")
        entry: Dict[str, object] = {}
        metrics.update(entry, None)
        assert metrics.total_events == 1

    def test_update_sets_first_seen(self) -> None:
        """Test update sets first_seen timestamp."""
        metrics = SessionMetrics(session_id="test-123", match_type="session_id")
        entry = {"timestamp": "2025-10-25T12:00:00Z"}
        metrics.update(entry, None)
        assert metrics.first_seen is not None
        assert isinstance(metrics.first_seen, int)

    def test_update_sets_last_seen(self) -> None:
        """Test update sets last_seen timestamp."""
        metrics = SessionMetrics(session_id="test-123", match_type="session_id")
        entry = {"timestamp": "2025-10-25T12:00:00Z"}
        metrics.update(entry, None)
        assert metrics.last_seen is not None

    def test_update_tracks_min_first_seen(self) -> None:
        """Test update keeps earliest first_seen."""
        metrics = SessionMetrics(session_id="test-123", match_type="session_id")
        metrics.update(cast(dict[str, object], {"timestamp": 1000}), None)
        metrics.update(cast(dict[str, object], {"timestamp": 500}), None)  # Earlier
        metrics.update(cast(dict[str, object], {"timestamp": 1500}), None)
        assert metrics.first_seen == 500

    def test_update_tracks_max_last_seen(self) -> None:
        """Test update keeps latest last_seen."""
        metrics = SessionMetrics(session_id="test-123", match_type="session_id")
        metrics.update(cast(dict[str, object], {"timestamp": 1000}), None)
        metrics.update(cast(dict[str, object], {"timestamp": 1500}), None)  # Later
        metrics.update(cast(dict[str, object], {"timestamp": 500}), None)
        assert metrics.last_seen == 1500

    def test_update_counts_commands(self) -> None:
        """Test update counts command events."""
        metrics = SessionMetrics(session_id="test-123", match_type="session_id")
        metrics.update(cast(dict[str, object], {"eventid": "cowrie.command.success"}), None)
        metrics.update(cast(dict[str, object], {"eventid": "cowrie.command.failed"}), None)
        assert metrics.command_count == 2

    def test_update_counts_login_attempts(self) -> None:
        """Test update counts login events."""
        metrics = SessionMetrics(session_id="test-123", match_type="session_id")
        metrics.update(cast(dict[str, object], {"eventid": "cowrie.login.success"}), None)
        metrics.update(cast(dict[str, object], {"eventid": "cowrie.login.failed"}), None)
        assert metrics.login_attempts == 2

    def test_update_captures_protocol_from_connect(self) -> None:
        """Test update captures protocol from session connect."""
        metrics = SessionMetrics(session_id="test-123", match_type="session_id")
        entry = {"eventid": "cowrie.session.connect", "protocol": "ssh", "src_ip": "192.168.1.100"}
        metrics.update(entry, None)
        assert metrics.protocol == "ssh"
        assert metrics.src_ip == "192.168.1.100"

    def test_update_captures_login_success_data(self) -> None:
        """Test update captures username/password from login success."""
        metrics = SessionMetrics(session_id="test-123", match_type="session_id")
        entry = {
            "eventid": "cowrie.login.success",
            "username": "root",
            "password": "password123",
            "src_ip": "192.168.1.101",
            "timestamp": "2025-10-25T12:00:00Z",
        }
        metrics.update(entry, None)
        assert metrics.username == "root"
        assert metrics.password == "password123"
        assert metrics.src_ip == "192.168.1.101"
        assert metrics.login_timestamp == "2025-10-25T12:00:00Z"
        assert metrics.login_time is not None

    def test_update_captures_session_duration(self) -> None:
        """Test update captures duration from session closed."""
        metrics = SessionMetrics(session_id="test-123", match_type="session_id")
        entry = {"eventid": "cowrie.session.closed", "duration": "00:05:30"}
        metrics.update(entry, None)
        assert metrics.duration_seconds == 330  # 5*60 + 30

    def test_update_tracks_source_file(self) -> None:
        """Test update tracks last source file."""
        metrics = SessionMetrics(session_id="test-123", match_type="session_id")
        metrics.update({}, "/path/to/log1.json")
        metrics.update({}, "/path/to/log2.json")
        assert metrics.last_source_file == "/path/to/log2.json"


class TestMatchSession:
    """Test match_session function."""

    def test_match_full_delimited(self) -> None:
        """Test matching with full delimited format."""
        entry = {"session": "sensor-a/2025-10-25/abc-123"}
        session_id, match_type = match_session(entry)
        assert session_id == "sensor-a/2025-10-25/abc-123"
        assert match_type == "full_delimited"

    def test_match_sessionid_field(self) -> None:
        """Test matching with sessionid field."""
        entry = {"sessionid": "abc-123"}
        session_id, match_type = match_session(entry)
        assert session_id == "abc-123"
        # Match type depends on matcher order, could be 'event_derived' or 'sessionid'

    def test_match_fallback_to_session(self) -> None:
        """Test fallback to session field."""
        entry = {"session": "simple-session-id"}
        session_id, match_type = match_session(entry)
        assert session_id == "simple-session-id"

    def test_match_no_match(self) -> None:
        """Test entry with no matching session."""
        entry: Dict[str, object] = {}
        session_id, match_type = match_session(entry)
        assert session_id is None
        assert match_type is None


class TestEnumerateSessions:
    """Test enumerate_sessions function."""

    def test_enumerate_empty(self) -> None:
        """Test enumerating empty entry list."""
        result = enumerate_sessions([])
        assert isinstance(result, SessionEnumerationResult)
        assert len(result.by_session) == 0
        assert len(result.metrics) == 0
        assert result.events_processed == 0

    def test_enumerate_single_session(self) -> None:
        """Test enumerating single session with multiple events."""
        entries = [
            {"session": "test-123", "eventid": "cowrie.session.connect"},
            {"session": "test-123", "eventid": "cowrie.command.success"},
            {"session": "test-123", "eventid": "cowrie.session.closed"},
        ]
        result = enumerate_sessions(entries)
        assert len(result.by_session) == 1
        assert "test-123" in result.by_session
        assert len(result.by_session["test-123"]) == 3
        assert result.events_processed == 3

    def test_enumerate_multiple_sessions(self) -> None:
        """Test enumerating multiple distinct sessions."""
        entries = [
            {"session": "session-1", "eventid": "cowrie.session.connect"},
            {"session": "session-2", "eventid": "cowrie.session.connect"},
            {"session": "session-1", "eventid": "cowrie.command.success"},
        ]
        result = enumerate_sessions(entries)
        assert len(result.by_session) == 2
        assert len(result.by_session["session-1"]) == 2
        assert len(result.by_session["session-2"]) == 1

    def test_enumerate_creates_metrics(self) -> None:
        """Test enumeration creates metrics for each session."""
        entries = [
            {"session": "test-123", "eventid": "cowrie.command.success"},
        ]
        result = enumerate_sessions(entries)
        assert "test-123" in result.metrics
        metrics = result.metrics["test-123"]
        assert metrics.session_id == "test-123"
        assert metrics.total_events == 1
        assert metrics.command_count == 1

    def test_enumerate_tracks_match_counts(self) -> None:
        """Test enumeration tracks matcher usage counts."""
        entries = [
            {"session": "sensor-a/2025/abc"},  # full_delimited
            {"session": "simple-id"},  # session_id
        ]
        result = enumerate_sessions(entries)
        assert "full_delimited" in result.match_counts
        # Note: actual counts depend on matcher order

    def test_enumerate_with_progress_callback(self) -> None:
        """Test enumeration calls progress callback."""
        entries = [{"session": f"session-{i}"} for i in range(100)]
        progress_calls = []

        def progress_callback(data: Dict[str, object]) -> None:
            progress_calls.append(data)

        enumerate_sessions(entries, progress_callback=progress_callback, progress_interval=10)
        assert len(progress_calls) > 0  # Should have been called at intervals
        assert progress_calls[-1]["events_processed"] == 100

    def test_enumerate_with_checkpoint_callback(self) -> None:
        """Test enumeration calls checkpoint callback."""
        entries = [{"session": f"session-{i}"} for i in range(100)]
        checkpoint_calls = []

        def checkpoint_callback(data: Dict[str, object]) -> None:
            checkpoint_calls.append(data)

        enumerate_sessions(entries, checkpoint_callback=checkpoint_callback, checkpoint_interval=20)
        assert len(checkpoint_calls) > 0

    def test_enumerate_with_source_getter(self) -> None:
        """Test enumeration uses source_getter for tracking files."""
        entries = [
            {"session": "test-123", "__source": "/path/to/log.json"},
        ]

        def source_getter(entry: Dict[str, object]) -> Optional[str]:
            return str(entry.get("__source"))

        result = enumerate_sessions(entries, source_getter=source_getter)
        metrics = result.metrics["test-123"]
        assert metrics.last_source_file == "/path/to/log.json"


class TestSerializeMetrics:
    """Test serialize_metrics function."""

    def test_serialize_empty(self) -> None:
        """Test serializing empty metrics dict."""
        result = serialize_metrics({})
        assert result == []

    def test_serialize_single_metric(self) -> None:
        """Test serializing single metric."""
        metrics = {
            "test-123": SessionMetrics(
                session_id="test-123", match_type="session_id", command_count=5, login_attempts=2
            )
        }
        result = serialize_metrics(metrics)
        assert len(result) == 1
        assert result[0]["session_id"] == "test-123"
        assert result[0]["match_type"] == "session_id"
        assert result[0]["command_count"] == 5
        assert result[0]["login_attempts"] == 2

    def test_serialize_all_fields(self) -> None:
        """Test serialization includes all metric fields."""
        metrics = {
            "test-123": SessionMetrics(
                session_id="test-123",
                match_type="full_delimited",
                first_seen=1000,
                last_seen=2000,
                command_count=10,
                login_attempts=3,
                total_events=15,
                last_source_file="/path/to/log.json",
                protocol="ssh",
                username="root",
                password="password123",
                src_ip="192.168.1.100",
                login_time=1500,
                login_timestamp="2025-10-25T12:00:00Z",
                duration_seconds=300,
            )
        }
        result = serialize_metrics(metrics)
        serialized = result[0]
        assert serialized["first_seen"] == 1000
        assert serialized["last_seen"] == 2000
        assert serialized["protocol"] == "ssh"
        assert serialized["username"] == "root"
        assert serialized["password"] == "password123"
        assert serialized["src_ip"] == "192.168.1.100"
        assert serialized["login_time"] == 1500
        assert serialized["duration_seconds"] == 300


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
