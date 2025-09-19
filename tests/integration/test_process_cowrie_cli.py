"""Integration-style tests for the process_cowrie CLI argument parsing."""

from __future__ import annotations

import argparse
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

PROCESS_SCRIPT = Path(__file__).resolve().parents[2] / "process_cowrie.py"


def test_help_describes_skip_enrich(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invoke the CLI help and ensure key options are present."""
    result = subprocess.run(
        [sys.executable, str(PROCESS_SCRIPT), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--skip-enrich" in result.stdout
    assert "--bulk-load" in result.stdout


def test_argument_defaults_and_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Capture parsed arguments without executing the heavy pipeline."""
    original_parse_args = argparse.ArgumentParser.parse_args
    captured: dict[str, argparse.Namespace] = {}

    def intercept(self: argparse.ArgumentParser, args=None, namespace=None):
        namespace_obj = original_parse_args(self, args, namespace)
        captured["namespace"] = namespace_obj
        raise SystemExit(0)

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", intercept)

    cache_dir = tmp_path / "cache"
    temp_dir = tmp_path / "temp"
    logs_dir = tmp_path / "logs"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(PROCESS_SCRIPT),
            "--logpath",
            str(tmp_path / "logs-source"),
            "--summarizedays",
            "7",
            "--skip-enrich",
            "--bulk-load",
            "--cache-dir",
            str(cache_dir),
            "--temp-dir",
            str(temp_dir),
            "--log-dir",
            str(logs_dir),
            "--buffer-bytes",
            "2048",
        ],
    )

    with pytest.raises(SystemExit):
        runpy.run_path(str(PROCESS_SCRIPT), run_name="__main__")

    namespace = captured["namespace"]

    assert namespace.logpath == str(tmp_path / "logs-source")
    assert namespace.summarizedays == "7"
    assert namespace.skip_enrich is True
    assert namespace.bulk_load is True
    assert namespace.cache_dir == str(cache_dir)
    assert namespace.temp_dir == str(temp_dir)
    assert namespace.log_dir == str(logs_dir)
    assert namespace.buffer_bytes == 2048
