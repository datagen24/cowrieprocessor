"""Unit tests for refactored Cowrie Processor helpers."""

from pathlib import Path
import pytest

from cowrieprocessor import loader, db, status, sessions, utils


@pytest.fixture
def tmp_dirs(tmp_path: Path):
    """Prepare temporary directories for logs, cache, db, and output."""
    dirs = {
        'logs': tmp_path / "logs",
        'output': tmp_path / "output",
        'data': tmp_path / "data",
        'cache': tmp_path / "cache",
        'temp': tmp_path / "temp",
        'logdir': tmp_path / "logdir",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def test_rate_limit_enforces_minimum_interval(monkeypatch):
    """Ensure the rate limiter respects the per-minute quota."""
    class FakeClock:
        def __init__(self):
            self.now = 0
            self.sleeps = []

        def time(self):
            return self.now

        def sleep(self, sec):
            self.sleeps.append(sec)
            self.now += sec

    clock = FakeClock()
    limiter = utils.RateLimiter(clock=clock)
    limiter.set_rate('vt', per_minute=2)  # 30s interval

    # First call should not sleep
    limiter.wait('vt')
    assert clock.sleeps == []

    # Second call 10s later should sleep 20s
    clock.now = 10
    limiter.wait('vt')
    assert clock.sleeps == [pytest.approx(20)]


def test_cache_upsert_and_get_round_trip(tmp_dirs):
    """Verify cache writes and reads go through SQLite handle."""
    cache_db = tmp_dirs['data'] / "cowrie.sqlite"
    cache_instance = utils.Cache(str(cache_db))

    cache_instance.upsert('vt', 'deadbeef', '{"result": 1}')
    row = cache_instance.get('vt', 'deadbeef')

    assert row is not None
    last_fetched, payload = row
    assert payload == '{"result": 1}'


def test_write_status_throttles_identical_updates(tmp_dirs):
    """Confirm the status writer throttles repeated messages and persists payloads."""
    status_file = tmp_dirs['logdir'] / "status.json"
    writer = status.StatusWriter(status_file, interval=30)

    writer.write('running', total_files=5, processed_files=1, current_file='example.log')
    initial_payload = status_file.read_text()

    # Second call within interval should not change
    writer.write('running', total_files=5, processed_files=1, current_file='example.log')
    throttled_payload = status_file.read_text()
    assert throttled_payload == initial_payload

    # After interval, payload updates
    writer.last_ts -= 31
    writer.write('running', total_files=5, processed_files=2, current_file='example.log')
    updated_payload = status_file.read_text()
    assert '2' in updated_payload


def test_secret_reference_resolution(monkeypatch):
    """Verify reference-style CLI values are resolved before use."""
    captured = []

    def fake_is_ref(val):
        captured.append(val)
        return str(val).startswith("ref:")

    def fake_resolve(val):
        return f"resolved:{val}"

    monkeypatch.setattr(utils, "is_reference", fake_is_ref)
    monkeypatch.setattr(utils, "resolve_secret", fake_resolve)

    value = utils.resolve_secret("ref:vt-key")
    assert value == "resolved:ref:vt-key"
    assert "ref:vt-key" in captured


def test_session_helpers(sample_cowrie_events):
    """Exercise the higher-level session helper functions."""
    connected = sessions.get_connected_sessions(sample_cowrie_events)
    assert "c0ffee-01" in connected

    session_ids = sessions.get_session_ids(sample_cowrie_events, type="all")
    assert "facade-02" in session_ids

    tty_ids = sessions.get_session_ids(sample_cowrie_events, type="tty")
    assert "tty-session" in tty_ids

    download_ids = sessions.get_session_ids(sample_cowrie_events, type="download")
    assert "facade-02" in download_ids

    duration = sessions.get_session_duration("c0ffee-01", sample_cowrie_events)
    assert duration == "0:00:10"

    missing_duration = sessions.get_session_duration("missing", sample_cowrie_events)
    assert missing_duration == ""

    login_data = sessions.get_login_data("c0ffee-01", sample_cowrie_events)
    assert login_data == ("root", "password", "2024-09-28T12:00:05Z", "203.0.113.10")

    command_total = sessions.get_command_total("c0ffee-01", sample_cowrie_events)
    assert command_total == 1

    downloads = sessions.get_file_download("c0ffee-01", sample_cowrie_events)
    assert downloads[0][2] == "198.51.100.20"
    assert downloads[1][2] == "malicious.example.com"

    uploads = sessions.get_file_upload("facade-02", sample_cowrie_events)
    assert uploads[0][2] == "203.0.113.50"


def test_bulk_load_skips_commits(tmp_dirs):
    """When bulk load mode is supplied, intermediate commits are suppressed."""
    db_handle = db.Database(str(tmp_dirs['data'] / "cowrie.sqlite"))
    loader_instance = loader.Loader(db_handle, bulk_load=True)

    # Patch commit to track calls
    calls = []
    db_handle.commit = lambda: calls.append("commit")

    loader_instance.commit_if_needed()
    assert calls == []
