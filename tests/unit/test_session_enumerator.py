"""Unit tests for the session enumeration helpers."""

from session_enumerator import enumerate_sessions


def test_enumerate_sessions_basic_metrics() -> None:
    """Session metrics capture counts and fallback matchers."""
    events: list[dict[str, object]] = [
        {
            'session': 'alpha-01',
            'eventid': 'cowrie.session.connect',
            'timestamp': '2024-01-01T00:00:00Z',
        },
        {
            'session': 'alpha-01',
            'eventid': 'cowrie.command.input',
            'timestamp': '2024-01-01T00:00:01Z',
        },
        {
            'sessionid': 'bravo-02',
            'eventid': 'cowrie.login.failed',
            'timestamp': '2024-01-01T00:00:02Z',
        },
        {
            'eventid': 'cowrie.command.input',
            'message': "session charlie-03 issued command",
            'timestamp': '2024-01-01T00:00:03Z',
        },
    ]

    result = enumerate_sessions(events)

    assert set(result.by_session) == {'alpha-01', 'bravo-02', 'charlie-03'}
    assert result.metrics['alpha-01'].command_count == 1
    assert result.metrics['bravo-02'].login_attempts == 1
    assert result.metrics['charlie-03'].match_type == 'event_session'
    assert result.match_counts['session_id_only'] == 1
    assert result.match_counts['event_session'] == 2


def test_enumerate_sessions_callbacks_invoked() -> None:
    """Progress and checkpoint callbacks receive payloads."""
    events: list[dict[str, object]] = [
        {
            'session': 'delta-04',
            'eventid': 'cowrie.session.connect',
            'timestamp': '2024-01-01T00:00:00Z',
        }
    ]

    calls = []

    def progress(stats):
        calls.append(('progress', stats))

    def checkpoint(snapshot):
        calls.append(('checkpoint', snapshot))

    enumerate_sessions(
        events,
        progress_callback=progress,
        checkpoint_callback=checkpoint,
        progress_interval=1,
        checkpoint_interval=1,
    )

    assert any(tag == 'progress' for tag, _ in calls)
    assert any(tag == 'checkpoint' for tag, _ in calls)
    checkpoint_payload = next(payload for tag, payload in calls if tag == 'checkpoint')
    assert checkpoint_payload['session_count'] == 1
