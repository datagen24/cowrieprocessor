#!/usr/bin/env python3
"""Monitor database growth and process status during long runs."""

import json
import os
import time
from pathlib import Path


def _render_status(name: str, data: dict) -> None:
    phase = data.get('phase') or data.get('state', 'unknown')
    ingest_id = data.get('ingest_id')
    metrics = data.get('metrics')
    if metrics:
        files = metrics.get('files_processed', 0)
        events_inserted = metrics.get('events_inserted', 0)
        events_read = metrics.get('events_read', 0)
        duplicates = metrics.get('duplicates_skipped', 0)
        line = f"[{name}] {phase}"
        if ingest_id:
            line += f" ingest={ingest_id}"
        line += f" files={files} events={events_inserted}/{events_read} dup={duplicates}"
        print(line)

        checkpoint = data.get('checkpoint', {})
        if isinstance(checkpoint, dict) and checkpoint:
            source = checkpoint.get('source')
            offset = checkpoint.get('offset')
            batch = checkpoint.get('batch_index')
            print(f"  checkpoint: source={source} offset={offset} batch={batch}")

        dead_letter = data.get('dead_letter', {})
        if isinstance(dead_letter, dict) and dead_letter.get('total'):
            dlq_total = dead_letter.get('total')
            last_reason = dead_letter.get('last_reason')
            last_source = dead_letter.get('last_source')
            print(f"  dead-letter: total={dlq_total} last_reason={last_reason} last_source={last_source}")
        return

    # Fallback to legacy status shape
    processed = data.get('processed_files', 0)
    total = data.get('total_files', 0)
    state = data.get('state', phase)
    current_file = data.get('current_file', '')
    print(f"[{name}] {state} {processed}/{total} {current_file}")
    total_sessions = data.get('total_sessions', 0)
    if total_sessions:
        sessions_processed = data.get('sessions_processed', 0)
        print(f"  Sessions: {sessions_processed}/{total_sessions}")


def monitor_progress():
    """Monitor database size and status file changes."""
    db_path = "/mnt/dshield/data/db/cowrieprocessor.sqlite"
    status_dir = Path("/mnt/dshield/data/logs/status")

    print("Monitoring database growth and process status...")
    print("Press Ctrl+C to stop")

    last_db_size = 0
    last_status = {}

    try:
        while True:
            # Check database size
            if os.path.exists(db_path):
                current_db_size = os.path.getsize(db_path)
                if current_db_size != last_db_size:
                    current_mb = current_db_size / (1024 * 1024)
                    delta_mb = (current_db_size - last_db_size) / (1024 * 1024)
                    print(f"Database size: {current_mb:.1f} MB (change: +{delta_mb:.1f} MB)")
                    last_db_size = current_db_size

            # Check status files
            if status_dir.exists():
                for status_file in status_dir.glob("*.json"):
                    try:
                        with open(status_file, 'r') as f:
                            data = json.load(f)

                        previous = last_status.get(status_file.name)
                        if data != previous:
                            _render_status(status_file.stem, data)
                            last_status[status_file.name] = data

                    except Exception as e:
                        print(f"Error reading {status_file}: {e}")

            time.sleep(5)  # Check every 5 seconds

    except KeyboardInterrupt:
        print("\nMonitoring stopped")


if __name__ == "__main__":
    monitor_progress()
