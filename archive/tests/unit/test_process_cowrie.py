"""Unit tests for helper utilities inside ``process_cowrie.py``."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
import uuid
from pathlib import Path
from typing import Callable, Iterable

import pytest

import secrets_resolver


def _load_process_cowrie(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    extra_args: Iterable[str] | None = None,
    pre_exec: Callable[[], None] | None = None,
):
    """Load ``process_cowrie`` with optional argument overrides and pre-exec hooks."""
    script_path = Path(__file__).resolve().parents[2] / "process_cowrie.py"

    log_source = tmp_path / "logs"
    output_dir = tmp_path / "output"
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    temp_dir = tmp_path / "temp"
    log_dir = tmp_path / "logdir"
    for directory in (log_source, output_dir, data_dir, cache_dir, temp_dir, log_dir):
        directory.mkdir(parents=True, exist_ok=True)

    argv = [
        str(script_path),
        "--logpath",
        str(log_source),
        "--output-dir",
        str(output_dir),
        "--data-dir",
        str(data_dir),
        "--cache-dir",
        str(cache_dir),
        "--temp-dir",
        str(temp_dir),
        "--log-dir",
        str(log_dir),
        "--db",
        str(tmp_path / "cowrie.sqlite"),
        "--sensor",
        "pytest-sensor",
        "--skip-enrich",
    ]
    if extra_args:
        argv.extend(list(extra_args))
    monkeypatch.setattr(sys, "argv", argv)

    dummy_dropbox = types.SimpleNamespace(
        Dropbox=lambda *args, **kwargs: types.SimpleNamespace(files_upload=lambda *a, **k: None)
    )
    monkeypatch.setitem(sys.modules, "dropbox", dummy_dropbox)

    if pre_exec is not None:
        pre_exec()

    module_name = f"process_cowrie_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    previous_cwd = Path.cwd()
    try:
        assert spec.loader is not None
        try:
            spec.loader.exec_module(module)
        except SystemExit:
            pass
    finally:
        os.chdir(previous_cwd)

    return module_name, module


@pytest.fixture
def load_process_cowrie(monkeypatch: pytest.MonkeyPatch):
    """Provide a loader that returns isolated ``process_cowrie`` module instances."""
    loaded_modules: list[str] = []

    def _loader(
        tmp_path: Path,
        *,
        extra_args: Iterable[str] | None = None,
        pre_exec: Callable[[], None] | None = None,
    ):
        module_name, module = _load_process_cowrie(
            tmp_path,
            monkeypatch,
            extra_args=extra_args,
            pre_exec=pre_exec,
        )
        loaded_modules.append(module_name)
        return module

    yield _loader

    for name in loaded_modules:
        sys.modules.pop(name, None)


@pytest.fixture
def process_cowrie_module(tmp_path: Path, load_process_cowrie):
    """Return a default-loaded ``process_cowrie`` module for helper tests."""
    return load_process_cowrie(tmp_path)


def test_rate_limit_enforces_minimum_interval(process_cowrie_module, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the rate limiter sleeps to satisfy the per-minute quota."""
    module = process_cowrie_module

    class FakeClock:
        def __init__(self) -> None:
            self.now = 0.0
            self.sleeps: list[float] = []

        def time(self) -> float:
            return self.now

        def sleep(self, seconds: float) -> None:
            self.sleeps.append(seconds)
            self.now += seconds

    clock = FakeClock()
    monkeypatch.setattr(module.time, "time", clock.time)
    monkeypatch.setattr(module.time, "sleep", clock.sleep)

    module.rate_limits['vt'] = 2  # 2 per minute => 30s interval
    module.last_request_time['vt'] = -100.0

    clock.now = 0.0
    module.rate_limit('vt')  # First call should not sleep
    assert clock.sleeps == []
    assert module.last_request_time['vt'] == pytest.approx(0.0)

    clock.now = 10.0
    module.rate_limit('vt')  # Second call should pause for 20 seconds
    assert clock.sleeps == [pytest.approx(20.0)]
    assert module.last_request_time['vt'] == pytest.approx(30.0)


def test_cache_upsert_and_get_round_trip(process_cowrie_module, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify cache writes and reads go through the shared SQLite handle."""
    module = process_cowrie_module

    monkeypatch.setattr(module.time, "time", lambda: 1_700_000_000)

    module.cache_upsert('vt', 'deadbeef', '{"result": 1}')
    row = module.cache_get('vt', 'deadbeef')

    assert row is not None
    last_fetched, payload = row
    assert last_fetched == 1_700_000_000
    assert payload == '{"result": 1}'


def test_write_status_throttles_identical_updates(process_cowrie_module, monkeypatch: pytest.MonkeyPatch) -> None:
    """Confirm the status writer throttles repeated messages and persists payloads."""
    module = process_cowrie_module
    status_file = module.status_file

    # Reset internal throttling state and fix the clock.
    module._last_status_ts = 0.0
    module._last_state = ""
    module._last_file = ""

    monkeypatch.setattr(module, "status_interval", 30)

    times = iter([100.0, 102.0, 200.0])
    monkeypatch.setattr(module.time, "time", lambda: next(times))

    module.write_status('running', total_files=5, processed_files=1, current_file='example.log', elapsed_secs=3)
    initial_payload = json.loads(status_file.read_text(encoding='utf-8'))
    assert initial_payload['processed_files'] == 1

    # Second call within the interval should be throttled (no file change).
    module.write_status('running', total_files=5, processed_files=1, current_file='example.log')
    throttled_payload = json.loads(status_file.read_text(encoding='utf-8'))
    assert throttled_payload == initial_payload

    # After the interval elapses, payload should refresh.
    module.write_status('running', total_files=5, processed_files=2, current_file='example.log')
    updated_payload = json.loads(status_file.read_text(encoding='utf-8'))
    assert updated_payload['processed_files'] == 2
    assert updated_payload['timestamp'] >= initial_payload['timestamp']


def test_secret_reference_resolution(tmp_path: Path, load_process_cowrie, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify reference-style CLI values are resolved before use."""
    captured: list[str] = []

    def pre_exec() -> None:
        def fake_is_reference(value: object) -> bool:
            captured.append(str(value))
            return str(value).startswith("ref:")

        def fake_resolve(value: object) -> str:
            return f"resolved:{value}"

        monkeypatch.setattr(secrets_resolver, "is_reference", fake_is_reference)
        monkeypatch.setattr(secrets_resolver, "resolve_secret", fake_resolve)

    module = load_process_cowrie(
        tmp_path,
        extra_args=["--vtapi", "ref:vt-key", "--urlhausapi", "literal-token"],
        pre_exec=pre_exec,
    )

    assert "ref:vt-key" in captured
    assert module.vtapi == "resolved:ref:vt-key"
    assert module.urlhausapi == "literal-token"


def test_with_timeout_resets_signal(process_cowrie_module, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure ``with_timeout`` configures and restores the signal alarm."""
    module = process_cowrie_module

    class DummySignal:
        SIGALRM = object()

        def __init__(self) -> None:
            self.calls: list[tuple[object, object]] = []
            self.alarms: list[int] = []

        def signal(self, sig, handler):
            self.calls.append((sig, handler))
            return "old-handler"

        def alarm(self, seconds: int) -> None:
            self.alarms.append(seconds)

    dummy = DummySignal()
    monkeypatch.setattr(module, "signal", dummy)

    result = module.with_timeout(5, lambda value: value + 1, 2)

    assert result == 3
    assert dummy.alarms == [5, 0]
    assert dummy.calls[0][1] is module.timeout_handler
    assert dummy.calls[1][1] == "old-handler"


def test_with_timeout_propagates_timeout(process_cowrie_module, monkeypatch: pytest.MonkeyPatch) -> None:
    """The helper should restore alarms even when the wrapped call fails."""
    module = process_cowrie_module

    class DummySignal:
        SIGALRM = object()

        def __init__(self) -> None:
            self.calls: list[tuple[object, object]] = []
            self.alarms: list[int] = []

        def signal(self, sig, handler):
            self.calls.append((sig, handler))
            return "old-handler"

        def alarm(self, seconds: int) -> None:
            self.alarms.append(seconds)

    dummy = DummySignal()
    monkeypatch.setattr(module, "signal", dummy)

    def boom() -> None:
        raise module.TimeoutError("boom")

    with pytest.raises(module.TimeoutError):
        module.with_timeout(3, boom)

    assert dummy.alarms == [3, 0]
    assert dummy.calls[-1][1] == "old-handler"


def test_session_helpers(process_cowrie_module, sample_cowrie_events: list[dict[str, str]]) -> None:
    """Exercise the higher-level session helper functions."""
    module = process_cowrie_module

    connected = module.get_connected_sessions(sample_cowrie_events)
    assert connected == {"c0ffee-01"}

    assert set(module.get_session_id(sample_cowrie_events, "all", "")) == {"c0ffee-01", "facade-02", "tty-session"}
    assert set(module.get_session_id(sample_cowrie_events, "tty", "tty-file")) == {"tty-session"}
    assert set(module.get_session_id(sample_cowrie_events, "download", "feedface")) == {"facade-02"}

    assert module.get_session_duration("c0ffee-01", sample_cowrie_events) == "0:00:10"
    assert module.get_session_duration("missing", sample_cowrie_events) == ""

    login = module.get_login_data("c0ffee-01", sample_cowrie_events)
    assert login == ("root", "password", "2024-09-28T12:00:05Z", "203.0.113.10")

    assert module.get_command_total("c0ffee-01", sample_cowrie_events) == 1

    downloads = module.get_file_download("c0ffee-01", sample_cowrie_events)
    assert downloads[0][2] == "198.51.100.20"
    assert downloads[1][2] == "malicious.example.com"

    uploads = module.get_file_upload("facade-02", sample_cowrie_events)
    assert uploads[0][2] == "203.0.113.50"


def test_bulk_load_skips_commits(tmp_path: Path, load_process_cowrie, monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``--bulk-load`` is supplied, intermediate commits are suppressed."""
    module = load_process_cowrie(tmp_path, extra_args=["--bulk-load"])
    assert module.bulk_load is True

    calls: list[str] = []

    module.con = types.SimpleNamespace(commit=lambda: calls.append("commit"))

    module.db_commit()

    assert calls == []
