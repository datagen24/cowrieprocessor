#!/usr/bin/env python3
"""Monitor database growth and process status during long runs."""

import json
import os
import time
from pathlib import Path
from typing import Any


def _render_status(name: str, data: dict) -> None:
    if "phases" in data:
        last_updated = data.get("last_updated")
        print(f"[{name}] aggregate last_updated={last_updated}")
        for phase_name, snapshot in sorted(data["phases"].items()):
            metrics = snapshot.get("metrics", {})
            ingest_id = snapshot.get("ingest_id")
            phase_label = snapshot.get("phase", phase_name)

            # Sanitization-specific rendering
            if phase_label == "sanitization":
                line = f"  - {phase_label}"
                if ingest_id:
                    line += f" ingest={ingest_id}"
                processed = metrics.get("records_processed")
                updated = metrics.get("records_updated")
                skipped = metrics.get("records_skipped")
                errors = metrics.get("errors")
                batches = metrics.get("batches_processed")
                if processed is not None:
                    line += f" processed={processed}"
                if updated is not None:
                    line += f" updated={updated}"
                if skipped is not None:
                    line += f" skipped={skipped}"
                if errors is not None:
                    line += f" errors={errors}"
                if batches is not None:
                    line += f" batches={batches}"
                print(line)
                continue

            # Default rendering for other phases
            line = f"  - {phase_label}"
            if ingest_id:
                line += f" ingest={ingest_id}"
            if metrics:
                files = metrics.get("files_processed")
                events = metrics.get("events_inserted")
                reports = metrics.get("reports_generated")
                if files is not None:
                    line += f" files={files}"
                if events is not None:
                    line += f" events={events}"
                if reports is not None:
                    line += f" reports={reports}"
                throughput = metrics.get("events_per_second") or metrics.get("reports_per_second")
                if throughput:
                    line += f" rate={throughput}"  # Already rounded
            print(line)
        return

    phase = data.get('phase') or data.get('state', 'unknown')
    ingest_id = data.get('ingest_id')
    metrics = data.get('metrics')
    if metrics:
        # Sanitization-specific rendering
        if phase == 'sanitization' or ('records_processed' in metrics and 'records_updated' in metrics):
            processed = metrics.get('records_processed', 0)
            updated = metrics.get('records_updated', 0)
            skipped = metrics.get('records_skipped', 0)
            errors = metrics.get('errors', 0)
            batches = metrics.get('batches_processed', 0)
            line = f"[{name}] {phase}"
            if ingest_id:
                line += f" ingest={ingest_id}"
            line += f" processed={processed} updated={updated} skipped={skipped} errors={errors} batches={batches}"
            print(line)
        else:
            # Default rendering for other phases
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


def monitor_progress() -> None:
    """Monitor database size and status file changes."""
    db_path = "/mnt/dshield/data/db/cowrieprocessor.sqlite"
    status_dir = Path("/mnt/dshield/data/logs/status")

    print("Monitoring database growth and process status...")
    print("Press Ctrl+C to stop")

    last_db_size = 0
    last_status: dict[str, Any] = {}

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
