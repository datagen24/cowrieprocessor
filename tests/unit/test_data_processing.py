"""Legacy data_processing tests retired after pipeline refactor."""

from __future__ import annotations

import pytest

pytest.skip(
    "Legacy data_processing module removed in favor of process_cowrie helpers",
    allow_module_level=True,
)


def test_pre_index_data_by_session(sample_cowrie_events: list[dict[str, str]]) -> None:
    """Ensure events are grouped under their respective sessions.

    Args:
        sample_cowrie_events: Fixture-supplied Cowrie event dictionaries.

    Returns:
        None: The test passes when sessions are correctly partitioned.
    """
    indexed = pre_index_data_by_session(sample_cowrie_events)

    assert set(indexed) == {"c0ffee-01", "facade-02", "tty-session"}
    assert len(indexed["c0ffee-01"]) == 6


def test_pre_index_data_by_session_ignores_missing_session(sample_cowrie_events: list[dict[str, str]]) -> None:
    """Ensure events without session identifiers are excluded.

    Args:
        sample_cowrie_events: Fixture-supplied Cowrie event dictionaries.

    Returns:
        None: The test passes when the orphan record is not indexed.
    """
    indexed = pre_index_data_by_session(sample_cowrie_events)

    assert "" not in indexed


def test_get_session_id_all(sample_cowrie_events: list[dict[str, str]]) -> None:
    """Validate that successful logins are discovered by the helper.

    Args:
        sample_cowrie_events: Fixture-supplied Cowrie event dictionaries.

    Returns:
        None: The test passes when login-based session extraction works.
    """
    sessions = get_session_id(sample_cowrie_events, "all", "unused")

    assert sessions == ["c0ffee-01"]


def test_get_session_id_tty(sample_cowrie_events: list[dict[str, str]]) -> None:
    """Validate TTY-based session discovery using ttylog identifiers.

    Args:
        sample_cowrie_events: Fixture-supplied Cowrie event dictionaries.

    Returns:
        None: The test passes when the tty session is returned.
    """
    sessions = get_session_id(sample_cowrie_events, "tty", "tty-file")

    assert sessions == ["tty-session"]


def test_get_session_id_download(sample_cowrie_events: list[dict[str, str]]) -> None:
    """Validate download-based session discovery by file hash.

    Args:
        sample_cowrie_events: Fixture-supplied Cowrie event dictionaries.

    Returns:
        None: The test passes when the file download session is returned.
    """
    sessions = get_session_id(sample_cowrie_events, "download", "feedface")

    assert sessions == ["facade-02"]


def test_get_protocol_login(sample_cowrie_events: list[dict[str, str]]) -> None:
    """Confirm that the protocol lookup retrieves the SSH entry.

    Args:
        sample_cowrie_events: Fixture-supplied Cowrie event dictionaries.

    Returns:
        None: The test passes when the expected protocol is returned.
    """
    protocol = get_protocol_login("c0ffee-01", sample_cowrie_events)

    assert protocol == "ssh"


def test_get_session_duration(sample_cowrie_events: list[dict[str, str]]) -> None:
    """Check that session duration extraction uses the closing event.

    Args:
        sample_cowrie_events: Fixture-supplied Cowrie event dictionaries.

    Returns:
        None: The test passes when the recorded duration matches the fixture.
    """
    duration = get_session_duration("c0ffee-01", sample_cowrie_events)

    assert duration == "0:00:10"


def test_get_session_duration_returns_empty_when_absent(sample_cowrie_events: list[dict[str, str]]) -> None:
    """Ensure missing session identifiers yield empty durations.

    Args:
        sample_cowrie_events: Fixture-supplied Cowrie event dictionaries.

    Returns:
        None: The test passes when non-existent sessions return an empty string.
    """
    duration = get_session_duration("unknown-session", sample_cowrie_events)

    assert duration == ""


def test_get_login_data(sample_cowrie_events: list[dict[str, str]]) -> None:
    """Verify login tuple contents for the successful session.

    Args:
        sample_cowrie_events: Fixture-supplied Cowrie event dictionaries.

    Returns:
        None: The test passes when username, password, timestamp, and IP align.
    """
    login_data = get_login_data("c0ffee-01", sample_cowrie_events)

    assert login_data is not None
    assert login_data[0] == "root"
    assert login_data[1] == "password"


def test_get_command_total(sample_cowrie_events: list[dict[str, str]]) -> None:
    """Ensure command events counted per session are accurate.

    Args:
        sample_cowrie_events: Fixture-supplied Cowrie event dictionaries.

    Returns:
        None: The test passes when exactly one command is recorded.
    """
    count = get_command_total("c0ffee-01", sample_cowrie_events)

    assert count == 1


def test_get_file_download(sample_cowrie_events: list[dict[str, str]]) -> None:
    """Ensure download metadata is normalized and captured.

    Args:
        sample_cowrie_events: Fixture-supplied Cowrie event dictionaries.

    Returns:
        None: The test passes when URL and checksum information match expectations.
    """
    downloads = get_file_download("c0ffee-01", sample_cowrie_events)

    assert downloads[0] == [
        "http[://]198[.]51[.]100[.]20/malware[.]bin",
        "deadbeef",
        "198.51.100.20",
        "/tmp/malware.bin",
    ]
    assert downloads[1] == [
        "http[://]malicious[.]example[.]com/dropper[.]bin",
        "badcafe",
        "malicious.example.com",
        "/tmp/dropper.bin",
    ]


def test_get_file_upload(sample_cowrie_events: list[dict[str, str]]) -> None:
    """Ensure upload metadata is normalized and captured.

    Args:
        sample_cowrie_events: Fixture-supplied Cowrie event dictionaries.

    Returns:
        None: The test passes when upload URL and checksum information match expectations.
    """
    uploads = get_file_upload("facade-02", sample_cowrie_events)

    assert uploads == [
        [
            "http[://]203[.]0[.]113[.]50/upload[.]sh",
            "feedface",
            "203.0.113.50",
            "upload.sh",
        ]
    ]
