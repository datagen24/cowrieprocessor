#!/usr/bin/env python3
"""Debug script to investigate the stuck session issue."""

import json
import os
import sqlite3
import time


def check_database_status():
    """Check database status and session information."""
    try:
        con = sqlite3.connect('/mnt/dshield/data/db/cowrieprocessor.sqlite')
        cur = con.cursor()
        
        # Check if database is locked
        try:
            cur.execute("SELECT COUNT(*) FROM sessions")
            session_count = cur.fetchone()[0]
            print(f"Total sessions in database: {session_count}")
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                print("Database is LOCKED - this is the issue!")
                return True
            else:
                print(f"Database error: {e}")
                return True
        
        # Check recent sessions
        cur.execute("SELECT session, timestamp FROM sessions ORDER BY timestamp DESC LIMIT 10")
        recent_sessions = cur.fetchall()
        print("Most recent sessions in database:")
        for session, timestamp in recent_sessions:
            print(f"  {session}: {timestamp}")
        
        # Check if the stuck session exists
        stuck_session = "84a1c2fd"
        cur.execute("SELECT COUNT(*) FROM sessions WHERE session LIKE ?", (f"{stuck_session}%",))
        count = cur.fetchone()[0]
        print(f"Sessions matching '{stuck_session}': {count}")
        
        con.close()
        return False
        
    except Exception as e:
        print(f"Error checking database: {e}")
        return True

def check_process_memory():
    """Check if the process is using excessive memory."""
    try:
        # Get the process ID from the status file
        with open('/mnt/dshield/data/logs/status/aws-eastus-dshield.json', 'r') as f:
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

def check_file_activity():
    """Check if the process is actively reading files."""
    try:
        with open('/mnt/dshield/data/logs/status/aws-eastus-dshield.json', 'r') as f:
            data = json.load(f)
            pid = data.get('pid')
            
        if pid:
            # Check if it's reading from any .bz2 files
            with open(f'/proc/{pid}/fd', 'r') as f:
                for fd in f:
                    try:
                        link = os.readlink(f'/proc/{pid}/fd/{fd.strip()}')
                        if '.bz2' in link:
                            print(f"Process is reading: {link}")
                    except Exception:
                        pass
    except Exception as e:
        print(f"Could not check file activity: {e}")

if __name__ == "__main__":
    print("=== Stuck Session Diagnostic ===")
    print(f"Current time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    print("\n=== Database Status ===")
    if check_database_status():
        print("Database is locked - process is likely stuck on a database operation")
    else:
        print("Database appears to be accessible")
    
    print("\n=== Process Memory ===")
    check_process_memory()
    
    print("\n=== File Activity ===")
    check_file_activity()
