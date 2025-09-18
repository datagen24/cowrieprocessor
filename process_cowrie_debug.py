#!/usr/bin/env python3
"""Debug version of process_cowrie.py with enhanced logging and modular design.

This script processes and summarizes Cowrie honeypot logs with enrichments,
but with enhanced debugging capabilities and modular design.
"""

import argparse
import bz2
import datetime
import gzip
import json
import logging
import os
import socket
import sqlite3
import sys
import time
from pathlib import Path

from data_processing import (
    get_command_total,
    get_file_download,
    get_file_upload,
    get_login_data,
    get_protocol_login,
    get_session_duration,
    get_session_id,
    pre_index_data_by_session,
)
from secrets_resolver import is_reference, resolve_secret


# Enhanced logging setup
def setup_logging(log_level=logging.DEBUG):
    """Set up enhanced logging for debugging."""
    # Create logs directory
    default_logs_dir = Path('/mnt/dshield/data/logs')
    try:
        default_logs_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    
    # Configure logging
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s:%(levelname)s:%(name)s:%(filename)s:%(funcName)s:%(message)s',
        handlers=[
            logging.FileHandler(default_logs_dir / "cowrieprocessor_debug.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Set specific loggers
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    
    return logging.getLogger(__name__)

logger = setup_logging()

# Default logs directory
default_logs_dir = Path('/mnt/dshield/data/logs')
try:
    default_logs_dir.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

date = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")

# Argument parsing
parser = argparse.ArgumentParser(description='DShield Honeypot Cowrie Data Identifiers (Debug Version)')
parser.add_argument(
    '--logpath', 
    dest='logpath', 
    type=str, 
    help='Path of cowrie json log files', 
    default='/srv/cowrie/var/log/cowrie'
)
parser.add_argument('--ttyfile', dest='ttyfile', type=str, help='Name of TTY associated TTY log file')
parser.add_argument(
    '--downloadfile', 
    dest='downloadfile', 
    type=str, 
    help='Name of downloaded file (matches file SHA-256 hash)'
)
parser.add_argument('--session', dest='session', type=str, help='Cowrie session number')
parser.add_argument('--vtapi', dest='vtapi', type=str, help='VirusTotal API key (required for VT data lookup)')
parser.add_argument('--email', dest='email', type=str, help='Your email address (required for DShield IP lookup)')
parser.add_argument(
    '--summarizedays', 
    dest='summarizedays', 
    type=str, 
    help='Will summarize all attacks in the give number of days'
)
parser.add_argument('--dbxapi', dest='dbxapi', type=str, help='Dropbox API key (required for Dropbox upload)')
parser.add_argument('--dbxkey', dest='dbxkey', type=str, help='Dropbox app key (required for Dropbox upload)')
parser.add_argument('--dbxsecret', dest='dbxsecret', type=str, help='Dropbox app secret (required for Dropbox upload)')
parser.add_argument(
    '--dbxrefreshtoken', 
    dest='dbxrefreshtoken', 
    type=str, 
    help='Dropbox refresh token (required for Dropbox upload)'
)
parser.add_argument('--spurapi', dest='spurapi', type=str, help='SPUR.us API key (required for SPUR data lookup)')
parser.add_argument(
    '--urlhausapi', 
    dest='urlhausapi', 
    type=str, 
    help='URLHaus API key (required for URLHaus data lookup)'
)
parser.add_argument('--sensor', dest='sensor', type=str, help='Sensor name for this run')
parser.add_argument('--db', dest='db', type=str, help='Database file path')
parser.add_argument('--output-dir', dest='output_dir', type=str, help='Output directory for reports')
parser.add_argument('--status-file', dest='status_file', type=str, help='Status file path')
parser.add_argument('--status-interval', dest='status_interval', type=int, help='Status update interval in seconds')
parser.add_argument(
    '--temp-dir', 
    dest='temp_dir', 
    type=str, 
    help='Temp directory (default: <data-dir>/temp/cowrieprocessor)'
)
parser.add_argument('--log-dir', dest='log_dir', type=str, help='Logs directory (default: <data-dir>/logs)')
parser.add_argument(
    '--bulk-load', 
    dest='bulk_load', 
    action='store_true', 
    help='Enable SQLite bulk load mode (defer commits, relaxed PRAGMAs)'
)
parser.add_argument(
    '--skip-enrich', 
    dest='skip_enrich', 
    action='store_true', 
    help='Skip all external enrichments (VT, DShield, URLhaus, SPUR) for faster ingest'
)
parser.add_argument('--buffer-bytes', dest='buffer_bytes', type=int, help='Buffer size for file reading')
parser.add_argument('--debug', action='store_true', help='Enable debug logging')

args = parser.parse_args()

# Set debug logging if requested
if args.debug:
    logger.setLevel(logging.DEBUG)
    logger.debug("Debug logging enabled")

# Global variables
data = []
attack_count = 0
number_of_commands = []
vt_classifications: list[str] = []
vt_recent_submissions: set[str] = set()
abnormal_attacks: set[str] = set()
uncommon_command_counts: set[int] = set()

# Configuration
hostname = socket.gethostname()
vtapi = args.vtapi or os.getenv('VT_API_KEY')
email = args.email or os.getenv('DSHIELD_EMAIL')
dbxapi = args.dbxapi or os.getenv('DROPBOX_ACCESS_TOKEN')
dbxkey = args.dbxkey or os.getenv('DROPBOX_APP_KEY')
dbxsecret = args.dbxsecret or os.getenv('DROPBOX_APP_SECRET')
dbxrefreshtoken = args.dbxrefreshtoken or os.getenv('DROPBOX_REFRESH_TOKEN')
spurapi = args.spurapi or os.getenv('SPUR_API_KEY')
urlhausapi = args.urlhausapi or os.getenv('URLHAUS_API_KEY')
skip_enrich = bool(getattr(args, 'skip_enrich', False))

logger.info(f"Starting Cowrie processor with skip_enrich={skip_enrich}")

# Resolve secret references if provided directly
try:
    if vtapi and is_reference(vtapi):
        vtapi = resolve_secret(vtapi)
    if email and is_reference(email):
        email = resolve_secret(email)
    if dbxapi and is_reference(dbxapi):
        dbxapi = resolve_secret(dbxapi)
    if dbxkey and is_reference(dbxkey):
        dbxkey = resolve_secret(dbxkey)
    if dbxsecret and is_reference(dbxsecret):
        dbxsecret = resolve_secret(dbxsecret)
    if dbxrefreshtoken and is_reference(dbxrefreshtoken):
        dbxrefreshtoken = resolve_secret(dbxrefreshtoken)
    if spurapi and is_reference(spurapi):
        spurapi = resolve_secret(spurapi)
    if urlhausapi and is_reference(urlhausapi):
        urlhausapi = resolve_secret(urlhausapi)
except Exception as e:
    logger.error(f"Failed to resolve secrets: {e}")
    sys.exit(1)

# Status file setup
status_base = (Path(args.log_dir) if getattr(args, 'log_dir', None) else default_logs_dir) / 'status'
try:
    status_base.mkdir(parents=True, exist_ok=True)
except Exception:
    logger.error("Failed creating status directory", exc_info=True)

status_file = Path(args.status_file) if getattr(args, 'status_file', None) else (status_base / f"{hostname}.json")
status_interval = max(5, int(getattr(args, 'status_interval', 30) or 30))
_last_status_ts = 0.0
_last_state = ""
_last_file = ""

def write_status(state='', total_files=0, processed_files=0, current_file='', extra=None):
    """Write status information to file."""
    global _last_status_ts, _last_state, _last_file
    
    now = time.time()
    if now - _last_status_ts < status_interval and state == _last_state and current_file == _last_file:
        return
    
    _last_status_ts = now
    _last_state = state
    _last_file = current_file
    
    payload = {
        'state': state,
        'total_files': total_files,
        'processed_files': processed_files,
        'current_file': current_file,
        'hostname': hostname,
        'run_dir': os.fspath(Path.cwd()),
        'timestamp': int(now),
    }
    if extra:
        payload.update(extra)
    
    try:
        tmp = status_file.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(json.dumps(payload))
        tmp.replace(status_file)
    except Exception as e:
        logger.warning(f"Failed to write status file: {e}")

def main():
    """Main processing function with enhanced debugging."""
    global data, attack_count, number_of_commands
    
    logger.info("Starting Cowrie log processing")
    
    # File processing
    list_of_files = []
    if os.path.isdir(args.logpath):
        for file in os.listdir(args.logpath):
            if file.endswith('.json') or file.endswith('.json.bz2') or file.endswith('.json.gz'):
                list_of_files.append(os.path.join(args.logpath, file))
    else:
        list_of_files.append(args.logpath)
    
    total_files = len(list_of_files)
    processed_files = 0
    write_status(state='starting', total_files=total_files, processed_files=processed_files)
    
    logger.info(f"Processing {total_files} files")
    
    # Database setup
    con = sqlite3.connect(args.db)
    try:
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA busy_timeout=30000')
        con.execute('PRAGMA wal_autocheckpoint=1000')
    except Exception as e:
        logger.warning(f"Failed to set some database PRAGMAs: {e}")
    
    # Process files
    for file_path in list_of_files:
        logger.info(f"Processing file {file_path}")
        write_status(
            state='reading', 
            total_files=total_files, 
            processed_files=processed_files, 
            current_file=os.path.basename(file_path)
        )
        
        try:
            if file_path.endswith('.bz2'):
                with bz2.open(file_path, 'rt', encoding='utf-8') as f:
                    contents = f.read()
            elif file_path.endswith('.gz'):
                with gzip.open(file_path, 'rt', encoding='utf-8') as f:
                    contents = f.read()
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    contents = f.read()
            
            # Parse JSON data - handle both array and line-delimited formats
            try:
                # First try to parse as a single JSON object
                obj = json.loads(contents)
                if isinstance(obj, list):
                    for rec in obj:
                        if isinstance(rec, dict):
                            data.append(rec)
                elif isinstance(obj, dict):
                    data.append(obj)
            except json.JSONDecodeError:
                # Fallback to line-by-line parsing (most common format)
                logger.debug("Parsing as line-delimited JSON")
                for line in contents.splitlines():
                    if line.strip():
                        try:
                            rec = json.loads(line.replace('\0', ''))
                            if isinstance(rec, dict):
                                data.append(rec)
                        except Exception as e:
                            logger.debug(f"Failed to parse line: {e}")
                            continue
            
            processed_files += 1
            write_status(
                state='reading', 
                total_files=total_files, 
                processed_files=processed_files, 
                current_file=os.path.basename(file_path)
            )
            
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
            continue
    
    logger.info(f"Loaded {len(data)} log entries")
    
    # Pre-index data by session for better performance
    data_by_session = pre_index_data_by_session(data)
    
    # Get sessions to process
    if args.summarizedays:
        session_id = get_session_id(data, "all", "unnecessary")
        logger.info(f"Found {len(session_id)} sessions to process")
    else:
        session_id = [args.session] if args.session else []
    
    # Process sessions
    write_status(state='generating_reports', total_files=total_files, processed_files=processed_files, current_file='')
    
    for i, session in enumerate(session_id):
        logger.info(f"Processing session {i+1}/{len(session_id)}: {session}")
        write_status(
            state='generating_reports', 
            total_files=total_files, 
            processed_files=processed_files, 
            current_file=f"Session {i+1}/{len(session_id)}: {session[:8]}..."
        )
        
        try:
            # Get session data
            session_data = data_by_session.get(session, data)
            
            # Get basic session info
            get_protocol_login(session, session_data)
            get_session_duration(session, session_data)
            
            try:
                username, password, timestamp, src_ip = get_login_data(session, session_data)
            except Exception as e:
                logger.warning(f"Failed to get login data for session {session}: {e}")
                continue
            
            command_count = get_command_total(session, session_data)
            logger.info(f"Session {session}: {command_count} commands")
            number_of_commands.append(command_count)
            
            # Get file data
            downloaddata = get_file_download(session, session_data)
            uploaddata = get_file_upload(session, session_data)
            logger.info(f"Session {session}: {len(downloaddata)} downloads, {len(uploaddata)} uploads")
            
            # Process downloads
            for download in downloaddata:
                if download[1]:  # if shasum exists
                    logger.debug(f"Processing download: {download[0]}")
                    # Add your download processing logic here
            
            # Process uploads
            for upload in uploaddata:
                if upload[1]:  # if shasum exists
                    logger.debug(f"Processing upload: {upload[0]}")
                    # Add your upload processing logic here
            
            attack_count += 1
            
        except Exception as e:
            logger.error(f"Error processing session {session}: {e}")
            continue
    
    logger.info(f"Completed processing {attack_count} attacks")
    
    # Generate summary
    if number_of_commands:
        summary = f"Total attacks: {attack_count}\n"
        summary += f"Most common command count: {max(set(number_of_commands), key=number_of_commands.count)}\n"
        summary += f"Average command count: {sum(number_of_commands) / len(number_of_commands):.2f}\n"
        logger.info(f"Summary:\n{summary}")
    else:
        logger.warning("No commands found in any sessions")
    
    con.close()
    logger.info("Processing completed successfully")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Processing interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
