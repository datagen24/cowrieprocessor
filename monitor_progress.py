#!/usr/bin/env python3
"""Monitor database growth and process status during long runs."""

import json
import os
import time
from pathlib import Path


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

                        current_status = {
                            'state': data.get('state', ''),
                            'processed_files': data.get('processed_files', 0),
                            'total_files': data.get('total_files', 0),
                            'current_file': data.get('current_file', ''),
                            'sessions_processed': data.get('sessions_processed', 0),
                            'total_sessions': data.get('total_sessions', 0),
                        }

                        previous = last_status.get(status_file.name, {})
                        if current_status != previous:
                            processed = current_status['processed_files']
                            total = current_status['total_files']
                            current_file = current_status['current_file']
                            print(f"[{status_file.stem}] {current_status['state']} {processed}/{total} {current_file}")
                            total_sessions = current_status['total_sessions']
                            if total_sessions > 0:
                                sessions_processed = current_status['sessions_processed']
                                print(f"  Sessions: {sessions_processed}/{total_sessions}")
                            last_status[status_file.name] = current_status

                    except Exception as e:
                        print(f"Error reading {status_file}: {e}")

            time.sleep(5)  # Check every 5 seconds

    except KeyboardInterrupt:
        print("\nMonitoring stopped")


if __name__ == "__main__":
    monitor_progress()
