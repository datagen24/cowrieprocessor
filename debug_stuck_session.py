#!/usr/bin/env python3
"""Debug script to investigate the stuck session issue."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def check_database_status(db_url: str):
    """Check database status and session information."""
    try:
        engine = create_engine(db_url)
        
        with engine.connect() as conn:
            # Check if database is accessible
            try:
                # Try to get session count from session_summaries table
                result = conn.execute(text("SELECT COUNT(*) FROM session_summaries")).fetchone()
                session_count = result[0] if result else 0
                print(f"Total sessions in database: {session_count}")
            except Exception as e:
                if "database is locked" in str(e) or "database is busy" in str(e):
                    print("Database is LOCKED - this is the issue!")
                    return True
                else:
                    print(f"Database error: {e}")
                    return True

            # Check recent sessions
            try:
                recent_sessions = conn.execute(
                    text("SELECT session_id, last_event_at FROM session_summaries ORDER BY last_event_at DESC LIMIT 10")
                ).fetchall()
                print("Most recent sessions in database:")
                for session_id, timestamp in recent_sessions:
                    print(f"  {session_id}: {timestamp}")
            except Exception as e:
                print(f"Could not fetch recent sessions: {e}")

            # Check if the stuck session exists
            stuck_session = "84a1c2fd"
            try:
                result = conn.execute(
                    text("SELECT COUNT(*) FROM session_summaries WHERE session_id LIKE :pattern"),
                    {"pattern": f"{stuck_session}%"}
                ).fetchone()
                count = result[0] if result else 0
                print(f"Sessions matching '{stuck_session}': {count}")
            except Exception as e:
                print(f"Could not check for stuck session: {e}")

        engine.dispose()
        return False

    except Exception as e:
        print(f"Error checking database: {e}")
        return True


def check_process_memory(status_file: str):
    """Check if the process is using excessive memory."""
    try:
        # Get the process ID from the status file
        with open(status_file, 'r') as f:
            data = json.load(f)
            pid = data.get('pid')

        if pid:
            with open(f'/proc/{pid}/status', 'r') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        print(f"Process memory usage: {line.strip()}")
                        break
    except Exception as e:
        print(f"Could not check memory usage: {e}")


def check_file_activity(status_file: str):
    """Check if the process is actively reading files."""
    try:
        with open(status_file, 'r') as f:
            data = json.load(f)
            pid = data.get('pid')

        if pid:
            # Check if it's reading from any .bz2 files
            for fd in os.listdir(f'/proc/{pid}/fd'):
                try:
                    link = os.readlink(f'/proc/{pid}/fd/{fd}')
                    if '.bz2' in link:
                        print(f"Process is reading: {link}")
                except OSError:
                    continue
    except Exception as e:
        print(f"Could not check file activity: {e}")


def main():
    """Main entry point for the debug script."""
    parser = argparse.ArgumentParser(description="Debug script to investigate stuck session issues")
    parser.add_argument(
        "--db-url", 
        default="sqlite:////mnt/dshield/data/db/cowrieprocessor.sqlite",
        help="Database URL (default: sqlite:////mnt/dshield/data/db/cowrieprocessor.sqlite)"
    )
    parser.add_argument(
        "--status-file",
        default="/mnt/dshield/data/logs/status/aws-eastus-dshield.json",
        help="Path to status file for process information"
    )
    
    args = parser.parse_args()
    
    print("=== Stuck Session Diagnostic ===")
    print(f"Current time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Database URL: {args.db_url}")

    print("\n=== Database Status ===")
    if check_database_status(args.db_url):
        print("Database is locked - process is likely stuck on a database operation")
    else:
        print("Database appears to be accessible")

    print("\n=== Process Memory ===")
    check_process_memory(args.status_file)

    print("\n=== File Activity ===")
    check_file_activity(args.status_file)


if __name__ == "__main__":
    main()
