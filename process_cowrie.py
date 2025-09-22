"""Process and summarize Cowrie honeypot logs with enrichments.

This script ingests Cowrie JSON logs and produces per-session summaries,
optionally enriched with URLHaus, DShield, VirusTotal, SPUR.us, and Dropbox
upload support. It also persists structured data to a local SQLite database
for sessions, commands, and files.

Run this as a standalone script; arguments are parsed at import time.
"""

import argparse
import bz2
import collections
import datetime
import faulthandler
import gzip
import io
import json
import logging
import os
import re
import signal
import socket
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, Optional

import dropbox
import requests

from enrichment_handlers import (
    dshield_query as enrichment_dshield_query,
)
from enrichment_handlers import (
    read_spur_data as enrichment_read_spur_data,
)
from enrichment_handlers import (
    safe_read_uh_data as enrichment_safe_read_uh_data,
)
from secrets_resolver import is_reference, resolve_secret
from session_enumerator import SessionMetrics, enumerate_sessions

faulthandler.enable()
if hasattr(signal, "SIGUSR1"):
    try:
        faulthandler.register(signal.SIGUSR1, chain=False, all_threads=True)
    except (AttributeError, ValueError):
        pass

# Default logs directory (can be overridden later via --log-dir)
default_logs_dir = Path('/mnt/dshield/data/logs')
try:
    default_logs_dir.mkdir(parents=True, exist_ok=True)
except Exception:
    pass
logging_fhandler = logging.FileHandler(default_logs_dir / "cowrieprocessor.err")
logging.root.addHandler(logging_fhandler)
basic_with_time_format = '%(asctime)s:%(levelname)s:%(name)s:%(filename)s:%(funcName)s:%(message)s'
logging_fhandler.setFormatter(logging.Formatter(basic_with_time_format))
logging_fhandler.setLevel(logging.ERROR)

stdout_handler = logging.StreamHandler(stream=sys.stdout)
stdout_handler.setFormatter(logging.Formatter(basic_with_time_format))
stdout_handler.setLevel(logging.DEBUG)

logging.root.addHandler(logging_fhandler)
logging.root.addHandler(stdout_handler)
logging.root.setLevel(logging.DEBUG)

date = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")

parser = argparse.ArgumentParser(description='DShield Honeypot Cowrie Data Identifiers')
parser.add_argument(
    '--logpath',
    dest='logpath',
    type=str,
    help='Path of cowrie json log files',
    default='/srv/cowrie/var/log/cowrie',
)
parser.add_argument(
    '--ttyfile',
    dest='ttyfile',
    type=str,
    help='Name of TTY associated TTY log file',
)
parser.add_argument(
    '--downloadfile',
    dest='downloadfile',
    type=str,
    help='Name of downloaded file (matches file SHA-256 hash)',
)
parser.add_argument(
    '--session',
    dest='session',
    type=str,
    help='Cowrie session number',
)
parser.add_argument(
    '--vtapi',
    dest='vtapi',
    type=str,
    help='VirusTotal API key (required for VT data lookup)',
)
parser.add_argument(
    '--email',
    dest='email',
    type=str,
    help='Your email address (required for DShield IP lookup)',
)
parser.add_argument(
    '--summarizedays',
    dest='summarizedays',
    type=str,
    help='Will summarize all attacks in the give number of days',
)
parser.add_argument(
    '--dbxapi',
    dest='dbxapi',
    type=str,
    help='Dropbox access token for use with Dropbox upload of summary text files',
)
parser.add_argument(
    '--dbxkey',
    dest='dbxkey',
    type=str,
    help='Dropbox app key to be used to get new short-lived API access key',
)
parser.add_argument(
    '--dbxsecret',
    dest='dbxsecret',
    type=str,
    help='Dropbox app secret to be used to get new short-lived API access key',
)
parser.add_argument(
    '--dbxrefreshtoken',
    dest='dbxrefreshtoken',
    type=str,
    help='Dropbox refresh token to be used to get new short-lived API access key',
)
parser.add_argument(
    '--spurapi',
    dest='spurapi',
    type=str,
    help='SPUR.us API key to be used for SPUR.us data encrichment',
)
parser.add_argument(
    '--urlhausapi',
    dest='urlhausapi',
    type=str,
    help='URLhaus API key for URLhaus data enrichment',
)
parser.add_argument(
    '--data-dir',
    dest='data_dir',
    type=str,
    default='/mnt/dshield/data',
    help='Base directory for data: cache/temp/logs (default: /mnt/dshield/data)',
)
parser.add_argument(
    '--cache-dir', dest='cache_dir', type=str, help='Cache directory (default: <data-dir>/cache/cowrieprocessor)'
)
parser.add_argument(
    '--temp-dir', dest='temp_dir', type=str, help='Temp directory (default: <data-dir>/temp/cowrieprocessor)'
)
parser.add_argument('--log-dir', dest='log_dir', type=str, help='Logs directory (default: <data-dir>/logs)')
parser.add_argument(
    '--bulk-load',
    dest='bulk_load',
    action='store_true',
    help='Enable SQLite bulk load mode (defer commits, relaxed PRAGMAs)',
)
parser.add_argument(
    '--skip-enrich',
    dest='skip_enrich',
    action='store_true',
    help='Skip all external enrichments (VT, DShield, URLhaus, SPUR) for faster ingest',
)
parser.add_argument(
    '--buffer-bytes',
    dest='buffer_bytes',
    type=int,
    default=1048576,
    help='Read buffer size in bytes for compressed log files (default: 1048576)',
)
parser.add_argument(
    '--vt-sleep',
    dest='vt_sleep',
    type=float,
    default=0.0,
    help='Seconds to sleep after a VT lookup to allow propagation (default: 0)',
)
parser.add_argument(
    '--max-line-bytes',
    dest='max_line_bytes',
    type=int,
    default=8388608,
    help='Maximum JSON line size to parse; skip lines larger than this (default: 8MB)',
)
parser.add_argument(
    '--file-timeout',
    dest='file_timeout',
    type=int,
    default=1800,
    help='Maximum seconds to spend on a single file before skipping (default: 1800)',
)
parser.add_argument(
    '--jq-normalize',
    dest='jq_normalize',
    action='store_true',
    help='Normalize JSON files (arrays or non-JSONL) into JSONL using a Python fallback',
)

parser.add_argument(
    '--api-timeout',
    dest='api_timeout',
    type=int,
    default=15,
    help='HTTP timeout in seconds for external APIs (default: 15)',
)
parser.add_argument(
    '--api-retries', dest='api_retries', type=int, default=3, help='Max retries for transient API failures (default: 3)'
)
parser.add_argument(
    '--api-backoff',
    dest='api_backoff',
    type=float,
    default=2.0,
    help='Exponential backoff base in seconds (default: 2.0)',
)
parser.add_argument(
    '--hash-ttl-days',
    dest='hash_ttl_days',
    type=int,
    default=30,
    help='TTL in days for file hash lookups (default: 30)',
)
parser.add_argument(
    '--hash-unknown-ttl-hours',
    dest='hash_unknown_ttl_hours',
    type=int,
    default=12,
    help='TTL in hours to recheck VT for unknown hashes sooner (default: 12)',
)
parser.add_argument(
    '--ip-ttl-hours', dest='ip_ttl_hours', type=int, default=12, help='TTL in hours for IP lookups (default: 12)'
)
parser.add_argument(
    '--rate-vt', dest='rate_vt', type=int, default=4, help='Max VirusTotal requests per minute (default: 4)'
)
parser.add_argument(
    '--rate-dshield', dest='rate_dshield', type=int, default=30, help='Max DShield requests per minute (default: 30)'
)
parser.add_argument(
    '--rate-urlhaus', dest='rate_urlhaus', type=int, default=30, help='Max URLhaus requests per minute (default: 30)'
)
parser.add_argument(
    '--rate-spur', dest='rate_spur', type=int, default=30, help='Max SPUR requests per minute (default: 30)'
)
parser.add_argument(
    '--output-dir',
    dest='output_dir',
    type=str,
    help='Base directory for reports and caches (default: <logpath>/../reports)',
)
parser.add_argument(
    '--sensor', dest='sensor', type=str, help='Sensor name/hostname to tag data with (defaults to system hostname)'
)
parser.add_argument(
    '--db',
    dest='db',
    type=str,
    help='Path to central SQLite database',
    default='../cowrieprocessor.sqlite',
)

args = parser.parse_args()

log_location = args.logpath
tty_file = args.ttyfile
download_file = args.downloadfile
session_id = args.session
vtapi = args.vtapi or os.getenv('VT_API_KEY')
email = args.email or os.getenv('DSHIELD_EMAIL')
summarizedays = args.summarizedays
dbxapi = args.dbxapi or os.getenv('DROPBOX_ACCESS_TOKEN')
dbxkey = args.dbxkey or os.getenv('DROPBOX_APP_KEY')
dbxsecret = args.dbxsecret or os.getenv('DROPBOX_APP_SECRET')
dbxrefreshtoken = args.dbxrefreshtoken or os.getenv('DROPBOX_REFRESH_TOKEN')
spurapi = args.spurapi or os.getenv('SPUR_API_KEY')
urlhausapi = args.urlhausapi or os.getenv('URLHAUS_API_KEY')
skip_enrich = bool(getattr(args, 'skip_enrich', False))

# Resolve secret references if provided directly
try:
    for name in ["vtapi", "email", "dbxapi", "dbxkey", "dbxsecret", "dbxrefreshtoken", "spurapi", "urlhausapi"]:
        val = locals().get(name)
        if is_reference(val):
            locals()[name] = resolve_secret(val)
            globals()[name] = locals()[name]
except Exception:
    # Non-fatal; continue with raw values if resolution failed
    pass

api_timeout = args.api_timeout if hasattr(args, 'api_timeout') else 15
api_retries = args.api_retries if hasattr(args, 'api_retries') else 3
api_backoff = args.api_backoff if hasattr(args, 'api_backoff') else 2.0
vt_sleep = float(getattr(args, 'vt_sleep', 0.0))
max_line_bytes = int(getattr(args, 'max_line_bytes', 8388608))
file_timeout = int(getattr(args, 'file_timeout', 1800))
jq_normalize = bool(getattr(args, 'jq_normalize', False))
hash_ttl_seconds = (args.hash_ttl_days if hasattr(args, 'hash_ttl_days') else 30) * 24 * 3600
hash_unknown_ttl_seconds = (args.hash_unknown_ttl_hours if hasattr(args, 'hash_unknown_ttl_hours') else 12) * 3600
ip_ttl_seconds = (args.ip_ttl_hours if hasattr(args, 'ip_ttl_hours') else 24) * 3600
rate_limits = {
    'vt': getattr(args, 'rate_vt', 4),
    'dshield': getattr(args, 'rate_dshield', 60),
    'urlhaus': getattr(args, 'rate_urlhaus', 30),
    'spur': getattr(args, 'rate_spur', 60),
}

last_request_time = {k: 0.0 for k in rate_limits.keys()}


class TimeoutError(Exception):
    """Custom timeout exception."""

    pass


def timeout_handler(signum, frame):
    """Signal handler for timeout."""
    raise TimeoutError("Operation timed out")


def with_timeout(timeout_seconds, func, *args, **kwargs):
    """Execute a function with a timeout.

    Args:
        timeout_seconds: Maximum time to wait for the function
        func: Function to execute
        *args: Arguments to pass to the function
        **kwargs: Keyword arguments to pass to the function

    Returns:
        Result of the function call

    Raises:
        TimeoutError: If the function doesn't complete within timeout_seconds
    """
    # Set up the signal handler
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout_seconds)

    try:
        result = func(*args, **kwargs)
        return result
    finally:
        # Restore the old signal handler
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def rate_limit(service):
    """Simple per-service rate limiter based on requests per minute."""
    now = time.time()
    per_min = rate_limits.get(service, 60)
    if per_min <= 0:
        return
    min_interval = 60.0 / float(per_min)
    elapsed = now - last_request_time.get(service, 0.0)
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    last_request_time[service] = time.time()


def cache_get(service, key):
    """Fetch (last_fetched, data) for a service/key from indicator_cache."""
    cur = con.cursor()
    cur.execute('SELECT last_fetched, data FROM indicator_cache WHERE service=? AND key=?', (service, key))
    row = cur.fetchone()
    return row if row else None


def cache_upsert(service, key, data):
    """Upsert indicator_cache row for service/key with current timestamp and data."""
    cur = con.cursor()
    cur.execute(
        'INSERT INTO indicator_cache(service, key, last_fetched, data) VALUES (?,?,?,?) '
        'ON CONFLICT(service, key) DO UPDATE SET last_fetched=excluded.last_fetched, data=excluded.data',
        (service, key, int(time.time()), data),
    )
    db_commit()


# string prepended to filename for report summaries
# may want a '_' at the start of this string for readability
hostname = args.sensor if args.sensor else socket.gethostname()
filename_prepend = f"_{hostname}"

# Configure data directories
base_data_dir = Path(getattr(args, 'data_dir', '/mnt/dshield/data'))
cache_dir = Path(args.cache_dir) if getattr(args, 'cache_dir', None) else (base_data_dir / 'cache' / 'cowrieprocessor')
temp_dir = Path(args.temp_dir) if getattr(args, 'temp_dir', None) else (base_data_dir / 'temp' / 'cowrieprocessor')
for d in (cache_dir, temp_dir):
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        logging.error(f"Failed creating directory {d}", exc_info=True)

# Determine output directory: configurable or derived from log path
try:
    default_base = Path(log_location).parent / 'reports'
except Exception:
    default_base = Path.cwd() / 'reports'
base_output_dir = Path(args.output_dir) if getattr(args, 'output_dir', None) else default_base
run_dir = base_output_dir / hostname / date
run_dir.mkdir(parents=True, exist_ok=True)
os.chdir(run_dir)

# Status file support
status_base = (Path(args.log_dir) if getattr(args, 'log_dir', None) else default_logs_dir) / 'status'
try:
    status_base.mkdir(parents=True, exist_ok=True)
except Exception:
    logging.error("Failed creating status directory", exc_info=True)
status_file = Path(args.status_file) if getattr(args, 'status_file', None) else (status_base / f"{hostname}.json")
status_interval = max(5, int(getattr(args, 'status_interval', 30)))
_last_status_ts = 0.0
_last_state = ""
_last_file = ""


def write_status(state: str, total_files: int, processed_files: int, current_file: str = "", **extra):
    """Write JSON status to the status file at most every status_interval seconds.

    Additional fields can be provided via keyword args and will be merged
    into the payload (e.g., file_lines, elapsed_secs).
    """
    global _last_status_ts, _last_state, _last_file
    now = time.time()
    # Write immediately if state or current_file changed; otherwise throttle
    if (state == _last_state and current_file == _last_file) and (now - _last_status_ts) < status_interval:
        return
    _last_status_ts = now
    _last_state = state
    _last_file = current_file
    payload = {
        'sensor': hostname,
        'pid': os.getpid(),
        'state': state,
        'total_files': total_files,
        'processed_files': processed_files,
        'current_file': current_file,
        'db_path': os.fspath(Path(args.db)),
        'run_dir': os.fspath(run_dir),
        'timestamp': int(now),
    }
    payload.update(extra)
    try:
        tmp = status_file.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(json.dumps(payload))
        tmp.replace(status_file)
    except Exception:
        # Non-fatal
        pass


def _safe_int(value: object, default: int = 0) -> int:
    """Best-effort conversion from arbitrary objects to ``int``."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _safe_match_counts(value: object) -> Dict[str, int]:
    """Normalize match-count dictionaries from enumeration callbacks."""
    if isinstance(value, dict):
        result: Dict[str, int] = {}
        for key, raw in value.items():
            result[str(key)] = _safe_int(raw)
        return result
    return {}


def _safe_optional_str(value: object) -> Optional[str]:
    """Return value when it is a string, otherwise ``None``."""
    if isinstance(value, str):
        return value
    return None


SCHEMA_META_TABLE = 'cp_metadata'
SCHEMA_VERSION = 2


def configure_database(connection: sqlite3.Connection) -> None:
    """Attempt to enable WAL mode with sane fallbacks."""
    wal_enabled = False
    try:
        result = connection.execute('PRAGMA journal_mode=WAL').fetchone()
        wal_enabled = bool(result and str(result[0]).lower() == 'wal')
        if wal_enabled:
            connection.execute('PRAGMA synchronous=NORMAL')
    except sqlite3.OperationalError:
        wal_enabled = False
    except Exception:
        logging.warning("Unexpected error enabling WAL; falling back to TRUNCATE", exc_info=True)
        wal_enabled = False
    if not wal_enabled:
        try:
            connection.execute('PRAGMA journal_mode=TRUNCATE')
            logging.warning("WAL mode unavailable, using TRUNCATE journal")
        except Exception:
            logging.error("Failed to set TRUNCATE journal mode", exc_info=True)
    try:
        connection.execute('PRAGMA busy_timeout=30000')
    except Exception:
        logging.warning("Failed to set busy timeout on SQLite connection", exc_info=True)
    try:
        connection.execute('PRAGMA wal_autocheckpoint=1000')
    except sqlite3.OperationalError:
        # Older SQLite or non-WAL mode – safe to ignore
        pass


def ensure_metadata_table(cursor: sqlite3.Cursor) -> None:
    """Create metadata table if missing."""
    cursor.execute(f"CREATE TABLE IF NOT EXISTS {SCHEMA_META_TABLE}(key TEXT PRIMARY KEY, value TEXT NOT NULL)")


def get_schema_version(cursor: sqlite3.Cursor) -> int:
    """Return current schema version stored in metadata."""
    ensure_metadata_table(cursor)
    cursor.execute(f"SELECT value FROM {SCHEMA_META_TABLE} WHERE key='schema_version'")
    row = cursor.fetchone()
    if not row:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


def set_schema_version(cursor: sqlite3.Cursor, version: int) -> None:
    """Persist the schema version in metadata."""
    cursor.execute(
        f"INSERT INTO {SCHEMA_META_TABLE}(key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(version),),
    )


def ensure_session_metrics_schema(cursor: sqlite3.Cursor) -> None:
    """Ensure the session_metrics table and indexes exist."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS session_metrics (
            session_id TEXT PRIMARY KEY,
            match_type TEXT NOT NULL,
            first_seen INTEGER,
            last_seen INTEGER,
            command_count INTEGER DEFAULT 0,
            login_attempts INTEGER DEFAULT 0,
            total_events INTEGER DEFAULT 0,
            vt_flagged INTEGER DEFAULT 0,
            dshield_flagged INTEGER DEFAULT 0,
            last_source_file TEXT,
            hostname TEXT,
            created_at INTEGER DEFAULT (strftime('%s','now')),
            updated_at INTEGER DEFAULT (strftime('%s','now'))
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_metrics_time ON session_metrics(first_seen, last_seen)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_metrics_flags ON session_metrics(vt_flagged, dshield_flagged) "
        "WHERE vt_flagged=1 OR dshield_flagged=1"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_metrics_hostname ON session_metrics(hostname)")


def ensure_ingest_checkpoints_schema(cursor: sqlite3.Cursor) -> None:
    """Ensure checkpoint table exists to store ingest restart data."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ingest_checkpoints (
            checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            last_session TEXT,
            file_offset INTEGER,
            events_processed INTEGER NOT NULL,
            payload TEXT
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ingest_checkpoints_ts ON ingest_checkpoints(timestamp)")


def run_schema_migrations() -> None:
    """Run idempotent schema migrations for session metric storage."""
    cursor = con.cursor()
    ensure_metadata_table(cursor)
    db_commit(force=True)
    version = get_schema_version(cursor)
    if version < 1:
        ensure_session_metrics_schema(cursor)
        ensure_ingest_checkpoints_schema(cursor)
        set_schema_version(cursor, 1)
        db_commit(force=True)
        version = 1
    if version < SCHEMA_VERSION:
        # Future migrations can hook here. For now ensure objects exist and bump version.
        ensure_session_metrics_schema(cursor)
        ensure_ingest_checkpoints_schema(cursor)
        set_schema_version(cursor, SCHEMA_VERSION)
        db_commit(force=True)


data = []
attack_count = 0
number_of_commands = []
vt_classifications = []
vt_recent_submissions = set()
abnormal_attacks = set()
uncommon_command_counts = set()

# All entries in the log directory (Path objects)
path_entries = sorted(Path(log_location).iterdir(), key=os.path.getmtime)

list_of_files = []
for each_file in path_entries:
    if ".json" in each_file.name:
        list_of_files.append(each_file.name)

# Apply day filtering before setting total_files count
if summarizedays:
    days = int(summarizedays)
    print("Days to summarize: " + str(days))
    file_list = []
    i = 0
    while len(list_of_files) > 0 and (i < days):
        if i < days:
            file_list.append(list_of_files.pop())
        i += 1
    list_of_files = file_list

total_files = len(list_of_files)
processed_files = 0
write_status(state='starting', total_files=total_files, processed_files=processed_files)

con = sqlite3.connect(args.db)
configure_database(con)

# Bulk load mode: relax PRAGMAs and gate commits
bulk_load = bool(getattr(args, 'bulk_load', False))
if bulk_load:
    try:
        con.execute('PRAGMA synchronous=OFF')
        con.execute('PRAGMA temp_store=MEMORY')
        con.execute('PRAGMA cache_size=-200000')  # ~200MB cache
        con.execute('PRAGMA mmap_size=268435456')  # 256MB if supported
    except Exception:
        logging.warning("Failed to set some bulk-load PRAGMAs", exc_info=True)


def db_commit(force: bool = False) -> None:
    """Commit the SQLite transaction unless bulk-load is active.

    Args:
        force: When ``True`` the commit executes even in bulk-load mode.

    In ``--bulk-load`` mode, intermediate commits are normally skipped for
    performance and a single commit is issued at the end of processing.
    """
    try:
        if force or not bulk_load:
            con.commit()
            logging.debug("Database transaction committed")
    except Exception:
        logging.error("Commit failed", exc_info=True)


def initialize_database():
    """Create and evolve the local SQLite schema if needed.

    Creates the ``sessions``, ``commands``, and ``files`` tables when absent
    and attempts to add newer SPUR-related columns to existing databases.

    Returns:
        None. Side effects: executes DDL statements and commits changes.
    """
    logging.info("Database initializing...")
    cur = con.cursor()
    cur.execute('''
            CREATE TABLE IF NOT EXISTS sessions(session text,
                session_duration int,
                protocol text,
                username text,
                password text,
                timestamp int,
                source_ip text,
                urlhaus_tag text,
                asname text,
                ascountry text,
                spur_asn text,
                spur_asn_organization text,
                spur_organization text,
                spur_infrastructure text,
                spur_client_behaviors text,
                spur_client_proxies text,
                spur_client_types text,
                spur_client_count text,
                spur_client_concentration text,
                spur_client_countries text,
                spur_geospread text,
                spur_risks text,
                spur_services text,
                spur_location text,
                spur_tunnel_anonymous text,
                spur_tunnel_entries text,
                spur_tunnel_operator text,
                spur_tunnel_type text,
                total_commands int,
                added int,
                hostname text)''')
    cur.execute('''
            CREATE TABLE IF NOT EXISTS commands(session text,
                command text,
                timestamp int,
                added int,
                hostname text)''')
    cur.execute('''
            CREATE TABLE IF NOT EXISTS files(session text,
                download_url text,
                hash text,
                file_path text,
                vt_description text,
                vt_threat_classification text,
                vt_first_submission int,
                vt_hits int,
                src_ip text,
                urlhaus_tag text,
                asname text,
                ascountry text,
                spur_asn text,
                spur_asn_organization text,
                spur_organization text,
                spur_infrastructure text,
                spur_client_behaviors text,
                spur_client_proxies text,
                spur_client_types text,
                spur_client_count text,
                spur_client_concentration text,
                spur_client_countries text,
                spur_geospread text,
                spur_risks text,
                spur_services text,
                spur_location text,
                spur_tunnel_anonymous text,
                spur_tunnel_entries text,
                spur_tunnel_operator text,
                spur_tunnel_type text,
                transfer_method text,
                added int,
                hostname text)''')
    db_commit()

    try:
        # add hostname columns for multi-sensor central DB
        cur.execute('''ALTER TABLE sessions ADD hostname text''')
        cur.execute('''ALTER TABLE commands ADD hostname text''')
        cur.execute('''ALTER TABLE files ADD hostname text''')
        db_commit()
    except Exception:
        logging.info("Hostname columns likely already exist...")

    try:
        # add new columns for spur data in preexisting databases
        cur.execute('''ALTER TABLE sessions ADD spur_asn text''')
        cur.execute('''ALTER TABLE sessions ADD spur_asn_organization text''')
        cur.execute('''ALTER TABLE sessions ADD spur_organization text''')
        cur.execute('''ALTER TABLE sessions ADD spur_infrastructure text''')
        cur.execute('''ALTER TABLE sessions ADD spur_client_behaviors text''')
        cur.execute('''ALTER TABLE sessions ADD spur_client_proxies text''')
        cur.execute('''ALTER TABLE sessions ADD spur_client_types text''')
        cur.execute('''ALTER TABLE sessions ADD spur_client_count text''')
        cur.execute('''ALTER TABLE sessions ADD spur_client_concentration text''')
        cur.execute('''ALTER TABLE sessions ADD spur_client_countries text''')
        cur.execute('''ALTER TABLE sessions ADD spur_geospread text''')
        cur.execute('''ALTER TABLE sessions ADD spur_risks text''')
        cur.execute('''ALTER TABLE sessions ADD spur_services text''')
        cur.execute('''ALTER TABLE sessions ADD spur_location text''')
        cur.execute('''ALTER TABLE sessions ADD spur_tunnel_anonymous text''')
        cur.execute('''ALTER TABLE sessions ADD spur_tunnel_entries text''')
        cur.execute('''ALTER TABLE sessions ADD spur_tunnel_operator text''')
        cur.execute('''ALTER TABLE sessions ADD spur_tunnel_type text''')
        cur.execute('''ALTER TABLE files ADD spur_asn text''')
        cur.execute('''ALTER TABLE files ADD spur_asn_organization text''')
        cur.execute('''ALTER TABLE files ADD spur_organization text''')
        cur.execute('''ALTER TABLE files ADD spur_infrastructure text''')
        cur.execute('''ALTER TABLE files ADD spur_client_behaviors text''')
        cur.execute('''ALTER TABLE files ADD spur_client_proxies text''')
        cur.execute('''ALTER TABLE files ADD spur_client_types text''')
        cur.execute('''ALTER TABLE files ADD spur_client_count text''')
        cur.execute('''ALTER TABLE files ADD spur_client_concentration text''')
        cur.execute('''ALTER TABLE files ADD spur_client_countries text''')
        cur.execute('''ALTER TABLE files ADD spur_geospread text''')
        cur.execute('''ALTER TABLE files ADD spur_risks text''')
        cur.execute('''ALTER TABLE files ADD spur_services text''')
        cur.execute('''ALTER TABLE files ADD spur_location text''')
        cur.execute('''ALTER TABLE files ADD spur_tunnel_anonymous text''')
        cur.execute('''ALTER TABLE files ADD spur_tunnel_entries text''')
        cur.execute('''ALTER TABLE files ADD spur_tunnel_operator text''')
        cur.execute('''ALTER TABLE files ADD spur_tunnel_type text''')
        db_commit()
    except Exception:
        print("Failure adding table columns, likely because they already exist...")

    try:
        # add new columns for spur data in preexisting databases
        cur.execute('''ALTER TABLE sessions ADD spur_tunnel_anonymous text''')
        cur.execute('''ALTER TABLE sessions ADD spur_tunnel_entries text''')
        cur.execute('''ALTER TABLE sessions ADD spur_tunnel_operator text''')
        cur.execute('''ALTER TABLE sessions ADD spur_tunnel_type text''')
        cur.execute('''ALTER TABLE sessions ADD spur_client_proxies text''')
        cur.execute('''ALTER TABLE files ADD spur_tunnel_anonymous text''')
        cur.execute('''ALTER TABLE files ADD spur_tunnel_entries text''')
        cur.execute('''ALTER TABLE files ADD spur_tunnel_operator text''')
        cur.execute('''ALTER TABLE files ADD spur_tunnel_type text''')
        cur.execute('''ALTER TABLE files ADD spur_client_proxies text''')
        db_commit()
    except Exception:
        logging.error("Failure adding table columns, likely because they already exist...")
    try:
        # add new columns for spur data in preexisting databases
        cur.execute('''ALTER TABLE sessions ADD session_duration int''')
        db_commit()
    except Exception:
        logging.error("Failure adding table columns, likely because they already exist...")
    # Create helpful indexes to speed reporting queries
    try:
        cur.execute('''CREATE INDEX IF NOT EXISTS idx_sessions_hostname_ts ON sessions(hostname, timestamp)''')
        cur.execute('''CREATE INDEX IF NOT EXISTS idx_sessions_ts ON sessions(timestamp)''')
        cur.execute('''CREATE INDEX IF NOT EXISTS idx_sessions_session ON sessions(session)''')
        cur.execute('''CREATE INDEX IF NOT EXISTS idx_files_session ON files(session)''')
        cur.execute('''CREATE INDEX IF NOT EXISTS idx_files_hash ON files(hash)''')
        cur.execute('''CREATE INDEX IF NOT EXISTS idx_commands_session ON commands(session)''')
        cur.execute('''CREATE INDEX IF NOT EXISTS idx_commands_ts ON commands(timestamp)''')
        db_commit()
        logging.info("Database indexes ensured (IF NOT EXISTS)")
    except Exception:
        logging.error("Failure creating indexes (may already exist)")
    try:
        cur.execute('''
            CREATE TABLE IF NOT EXISTS indicator_cache(
                service text,
                key text,
                last_fetched int,
                data text,
                PRIMARY KEY (service, key)
            )''')
        db_commit()
    except Exception:
        logging.error("Failure creating indicator_cache table")

    run_schema_migrations()


def persist_session_metrics(metrics: Dict[str, SessionMetrics], *, hostname: str) -> None:
    """Upsert per-session metrics into the SQLite session_metrics table."""
    if not metrics:
        return
    cur = con.cursor()
    now = int(time.time())
    rows = []
    for metric in metrics.values():
        first_seen = int(metric.first_seen) if metric.first_seen is not None else None
        last_seen = int(metric.last_seen) if metric.last_seen is not None else None
        rows.append(
            (
                metric.session_id,
                metric.match_type or 'unknown',
                first_seen,
                last_seen,
                int(metric.command_count),
                int(metric.login_attempts),
                int(metric.total_events),
                metric.last_source_file,
                hostname,
                now,
            )
        )
    cur.executemany(
        """
        INSERT INTO session_metrics(
            session_id,
            match_type,
            first_seen,
            last_seen,
            command_count,
            login_attempts,
            total_events,
            last_source_file,
            hostname,
            updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(session_id) DO UPDATE SET
            match_type=excluded.match_type,
            first_seen=CASE
                WHEN session_metrics.first_seen IS NULL THEN excluded.first_seen
                WHEN excluded.first_seen IS NULL THEN session_metrics.first_seen
                WHEN excluded.first_seen < session_metrics.first_seen THEN excluded.first_seen
                ELSE session_metrics.first_seen
            END,
            last_seen=CASE
                WHEN session_metrics.last_seen IS NULL THEN excluded.last_seen
                WHEN excluded.last_seen IS NULL THEN session_metrics.last_seen
                WHEN excluded.last_seen > session_metrics.last_seen THEN excluded.last_seen
                ELSE session_metrics.last_seen
            END,
            command_count=excluded.command_count,
            login_attempts=excluded.login_attempts,
            total_events=excluded.total_events,
            last_source_file=COALESCE(excluded.last_source_file, session_metrics.last_source_file),
            hostname=COALESCE(excluded.hostname, session_metrics.hostname),
            updated_at=excluded.updated_at
        """,
        rows,
    )
    db_commit()


def save_checkpoint(last_session: Optional[str], events_processed: int, match_counts: Dict[str, int]) -> None:
    """Persist ingest progress checkpoints for restart resilience."""
    payload = json.dumps({'match_counts': match_counts, 'version': SCHEMA_VERSION})
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO ingest_checkpoints(timestamp, last_session, file_offset, events_processed, payload)
        VALUES (?,?,?,?,?)
        """,
        (int(time.time()), last_session, None, int(events_processed), payload),
    )
    db_commit(force=True)


def _source_file_from_entry(entry: Dict[str, object]) -> Optional[str]:
    """Extract the source file name from the injected entry metadata."""
    value = entry.get('__source_file')
    return value if isinstance(value, str) else None


def get_connected_sessions(data):
    """Return unique session IDs that successfully authenticated.

    Args:
        data: Iterable of Cowrie event dictionaries.

    Returns:
        A ``set`` of session ID strings seen with ``cowrie.login.success``.
    """
    logging.info("Extracting unique sessions...")
    sessions = set()
    for each_entry in data:
        if each_entry['eventid'] == "cowrie.login.success":
            sessions.add(each_entry['session'])
    return sessions


def get_session_id(data, type, match):
    """Identify sessions by artifact type.

    Args:
        data: Iterable of Cowrie event dictionaries.
        type: One of ``"tty"``, ``"download"``, or ``"all"``.
        match: For ``tty``, the tty file name; for ``download``, the file
            SHA-256; ignored for ``all``.

    Returns:
        A ``set`` of matching session ID strings.
    """
    logging.info("Extracting unique sessions")
    sessions = set()
    if type == "tty":
        for each_entry in data:
            if "ttylog" in each_entry:
                if each_entry['ttylog'] == ("var/lib/cowrie/tty/" + match):
                    sessions.add(each_entry['session'])
    elif type == "download":
        for each_entry in data:
            if "shasum" in each_entry:
                if each_entry['shasum'] == match:
                    sessions.add(each_entry['session'])
    elif type == "all":
        for each_entry in data:
            if "shasum" in each_entry:
                if "src_ip" in each_entry:
                    sessions.add(each_entry['session'])
            if "ttylog" in each_entry:
                if "src_ip" in each_entry:
                    sessions.add(each_entry['session'])
    return sessions


def get_session_duration(session, data):
    """Return the session duration in seconds, if present.

    Args:
        session: Session ID string.
        data: Iterable of Cowrie event dictionaries.

    Returns:
        Duration in seconds (``str`` or ``int`` as present in log), or
        empty string if not found.
    """
    logging.info("Getting session durations...")
    duration = ""
    for each_entry in data:
        if each_entry['session'] == session:
            if each_entry['eventid'] == "cowrie.session.closed":
                duration = each_entry['duration']

    return duration


def get_protocol_login(session, data):
    """Return the network protocol for a session.

    Args:
        session: Session ID string.
        data: Iterable of Cowrie event dictionaries.

    Returns:
        Protocol string (e.g., ``ssh`` or ``telnet``) if found, else None.
    """
    logging.info("Getting protocol from session connection...")
    for each_entry in data:
        if each_entry['session'] == session:
            if each_entry['eventid'] == "cowrie.session.connect":
                return each_entry['protocol']


def get_login_data(session, data):
    """Extract login details for a session.

    Args:
        session: Session ID string.
        data: Iterable of Cowrie event dictionaries.

    Returns:
        Tuple ``(username, password, timestamp, src_ip)`` for the first
        ``cowrie.login.success`` entry in the session, or ``None`` if absent.
    """
    for each_entry in data:
        if each_entry['session'] == session:
            if each_entry['eventid'] == "cowrie.login.success":
                return each_entry['username'], each_entry['password'], each_entry['timestamp'], each_entry['src_ip']


def get_command_total(session, data):
    """Count commands executed in a session.

    Args:
        session: Session ID string.
        data: Iterable of Cowrie event dictionaries.

    Returns:
        Integer count of events whose ``eventid`` starts with ``cowrie.command.``.
    """
    count = 0
    for each_entry in data:
        if each_entry['session'] == session:
            if "cowrie.command." in each_entry['eventid']:
                count += 1
    return count


def get_file_download(session, data):
    """Collect file download events for a session.

    Args:
        session: Session ID string.
        data: Iterable of Cowrie event dictionaries.

    Returns:
        A list of ``[url, shasum, src_ip, destfile]`` for each download.
    """
    url = ""
    download_ip = ""
    shasum = ""
    destfile = ""
    returndata = []
    for each_entry in data:
        if each_entry['session'] == session:
            if each_entry['eventid'] == "cowrie.session.file_download":
                if "url" in each_entry:
                    url = each_entry['url'].replace(".", "[.]").replace("://", "[://]")
                    try:
                        download_ip = re.findall(
                            r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})",
                            each_entry['url'],
                        )[0]
                    except Exception:
                        download_ip = re.findall(r"\:\/\/(.*?)\/", each_entry['url'])[0]
                if "shasum" in each_entry:
                    shasum = each_entry['shasum']
                if "destfile" in each_entry:
                    destfile = each_entry['destfile']
                returndata.append([url, shasum, download_ip, destfile])
    return returndata


def get_file_upload(session, data):
    """Collect file upload events for a session.

    Args:
        session: Session ID string.
        data: Iterable of Cowrie event dictionaries.

    Returns:
        A list of ``[url, shasum, src_ip, filename]`` for each upload.
    """
    url = ""
    upload_ip = ""
    shasum = ""
    destfile = ""
    returndata = []
    for each_entry in data:
        if each_entry['session'] == session:
            if each_entry['eventid'] == "cowrie.session.file_upload":
                if "url" in each_entry:
                    url = each_entry['url'].replace(".", "[.]").replace("://", "[://]")
                    try:
                        upload_ip = re.findall(
                            r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})",
                            each_entry['url'],
                        )[0]
                    except Exception:
                        upload_ip = re.findall(r"\:\/\/(.*?)\/", each_entry['url'])[0]
                if "shasum" in each_entry:
                    shasum = each_entry['shasum']
                if "filename" in each_entry:
                    destfile = each_entry['filename']
                returndata.append([url, shasum, upload_ip, destfile])
    # vt_filescan(shasum)
    return returndata


def vt_query(hash, cache_dir: Path):
    """Query VirusTotal for a file hash and write the JSON response.

    Args:
        hash: SHA-256 string of the file to look up.
        cache_dir: Directory to write/read cached VT responses.

    Returns:
        None. Side effects: writes a file named after the hash.
    """
    # If cached and TTL valid, restore from DB to file if needed
    cached = cache_get('vt_file', hash)
    vt_path = cache_dir / hash
    if cached:
        last_fetched, data = cached
        ttl = hash_ttl_seconds
        try:
            cached_json = json.loads(data)
            # Treat missing 'data' or explicit error as unknown
            is_unknown = not isinstance(cached_json, dict) or ('data' not in cached_json) or ('error' in cached_json)
            if is_unknown:
                ttl = hash_unknown_ttl_seconds
        except Exception:
            ttl = hash_unknown_ttl_seconds
        if (time.time() - last_fetched) < ttl:
            if not vt_path.exists() and data:
                with open(vt_path, 'w', encoding='utf-8') as f:
                    f.write(data)
            return
    if skip_enrich or not vtapi:
        return
    vt_session.headers.update({'X-Apikey': vtapi})
    url = "https://www.virustotal.com/api/v3/files/" + hash
    attempt = 0
    while attempt < api_retries:
        attempt += 1
        try:
            rate_limit('vt')
            response = vt_session.get(url, timeout=api_timeout)
            if response.status_code == 429:
                time.sleep(api_backoff * attempt)
                continue
            if response.status_code == 404:
                # Cache not found and recheck sooner
                placeholder = json.dumps({"error": "not_found"})
                with open(vt_path, 'w', encoding='utf-8') as f:
                    f.write(placeholder)
                cache_upsert('vt_file', hash, placeholder)
                return
            response.raise_for_status()
            with open(vt_path, 'w', encoding='utf-8') as f:
                f.write(response.text)
            cache_upsert('vt_file', hash, response.text)
            return
        except Exception:
            time.sleep(api_backoff * attempt)
    logging.error("VT query failed for %s after retries", hash)


def vt_filescan(hash, cache_dir: Path):
    """Upload a local file to VirusTotal for scanning.

    Args:
        hash: Filename under Cowrie downloads (usually the SHA-256 hash).
        cache_dir: Directory to write the VT filescan response cache.

    Returns:
        None. Side effects: writes ``files_<hash>`` with the response.
    """
    if not vtapi:
        logging.error("VT filescan requested without VT API key")
        return
    headers = {'X-Apikey': vtapi}
    url = "https://www.virustotal.com/api/v3/files"
    attempt = 0
    with open('/srv/cowrie/var/lib/cowrie/downloads/' + hash, 'rb') as fileh:
        files = {'file': ('/srv/cowrie/var/lib/cowrie/downloads/' + hash, fileh)}
        while attempt < api_retries:
            attempt += 1
            try:
                rate_limit('vt')
                response = vt_session.post(url, headers=headers, files=files, timeout=api_timeout)
                if response.status_code == 429:
                    time.sleep(api_backoff * attempt)
                    continue
                response.raise_for_status()
                with open(cache_dir / ("files_" + hash), 'w') as f:
                    f.write(response.text)
                return
            except Exception:
                time.sleep(api_backoff * attempt)
    logging.error("VT filescan failed for %s", hash)


def dshield_query(ip_address):
    """Return DShield metadata, leveraging the shared enrichment helper."""
    if skip_enrich:
        return {"ip": {"asname": "", "ascountry": ""}}

    cached = cache_get('dshield_ip', ip_address)
    if cached and (time.time() - cached[0]) < ip_ttl_seconds:
        try:
            return json.loads(cached[1])
        except Exception:
            logging.debug("Cached DShield entry for %s was invalid JSON", ip_address, exc_info=True)

    result = enrichment_dshield_query(
        ip_address,
        email or "",
        skip_enrich=skip_enrich,
        cache_base=cache_dir,
        session_factory=requests.session,
        ttl_seconds=ip_ttl_seconds,
        now=time.time,
    )

    try:
        cache_upsert('dshield_ip', ip_address, json.dumps(result))
    except Exception:
        logging.debug("Failed to persist DShield cache entry for %s", ip_address, exc_info=True)
    return result


def safe_read_uh_data(ip_address, urlhausapi):
    """Return URLHaus tags via the shared enrichment helper."""
    return enrichment_safe_read_uh_data(
        ip_address,
        urlhausapi,
        skip_enrich=skip_enrich,
        cache_base=cache_dir,
        session_factory=requests.session,
        timeout=api_timeout,
    )


def read_vt_data(hash, cache_dir: Path):
    """Parse a cached VirusTotal response for selected fields.

    Args:
        hash: SHA-256 string naming the cached VT response file.
        cache_dir: Directory where the cached VT response is stored.

    Returns:
        Tuple ``(description, classification, first_submission, malicious)``.
    """
    hash_info = open(cache_dir / hash, 'r', encoding='utf-8')
    file = ""
    for each_time in hash_info:
        file += each_time
    hash_info.close
    json_data = json.loads(file)

    try:
        vt_description = json_data['data']['attributes']['type_description']
    except Exception:
        vt_description = ""

    try:
        vt_threat_classification = json_data['data']['attributes']['popular_threat_classification'][
            'suggested_threat_label'
        ]
    except Exception:
        vt_threat_classification = ""
    try:
        vt_first_submission = json_data['data']['attributes']['first_submission_date']
    except Exception:
        vt_first_submission = 0
    try:
        vt_malicious = json_data['data']['attributes']['last_analysis_stats']['malicious']
    except Exception:
        vt_malicious = 0

    return vt_description, vt_threat_classification, vt_first_submission, vt_malicious


def read_spur_data(ip_address):
    """Return SPUR attributes via the shared enrichment helper."""
    return enrichment_read_spur_data(
        ip_address,
        spurapi or "",
        skip_enrich=skip_enrich,
        cache_base=cache_dir,
        session_factory=requests.session,
        timeout=api_timeout,
    )


def print_session_info(data, sessions, attack_type, data_by_session=None):
    """Render and persist details for the provided sessions.

    For each session, prints a formatted report, enriches from external
    sources when configured, and inserts or updates rows in SQLite.

    Args:
        data: Iterable of Cowrie event dictionaries (used for fallback).
        sessions: Iterable of session ID strings to include.
        attack_type: Either ``"standard"`` or ``"abnormal"`` controlling
            which report file the output is appended to.
        data_by_session: Optional pre-indexed data by session for better performance.

    Returns:
        None.
    """
    total_sessions = len(sessions)
    processed_sessions = 0

    for session in sessions:
        processed_sessions += 1
        # Update status with progress during report generation
        write_status(
            state='generating_reports',
            total_files=total_files,
            processed_files=processed_files,
            current_file=f"Session {processed_sessions}/{total_sessions}: {session[:8]}...",
        )
        logging.info(f"Processing session {processed_sessions}/{total_sessions}: {session}")
        logging.info(f"Session {session} - Starting database operations")
        cur = con.cursor()
        global attack_count
        attack_count += 1
        # Use pre-indexed data if available, otherwise fall back to full data
        session_data = data_by_session.get(session, data) if data_by_session else data

        logging.info(f"Session {session} - Getting protocol and duration")
        protocol = get_protocol_login(session, session_data)
        session_duration = get_session_duration(session, session_data)
        logging.info(f"Session {session} - Protocol: {protocol}, Duration: {session_duration}")

        # try block for partially available data
        # this is usually needed due to an attack spanning multiple log files not included for processing
        try:
            logging.info(f"Session {session} - Getting login data")
            username, password, timestamp, src_ip = get_login_data(session, session_data)
            logging.info(f"Session {session} - Login data retrieved: {username}, {src_ip}")
        except Exception:
            continue
        command_count = get_command_total(session, session_data)
        print("Command Count: " + str(command_count))
        number_of_commands.append(command_count)

        logging.info(f"Getting download/upload data for session {session}")
        downloaddata = get_file_download(session, session_data)
        uploaddata = get_file_upload(session, session_data)
        logging.info(f"Found {len(downloaddata)} downloads, {len(uploaddata)} uploads for session {session}")

        attackstring = "{:>30s}  {:50s}".format("Session", str(session)) + "\n"
        attackstring += "{:>30s}  {:50s}".format("Session Duration", str(session_duration)[0:5] + " seconds") + "\n"
        attackstring += "{:>30s}  {:50s}".format("Protocol", str(protocol)) + "\n"
        attackstring += "{:>30s}  {:50s}".format("Username", str(username)) + "\n"
        attackstring += "{:>30s}  {:50s}".format("Password", str(password)) + "\n"
        attackstring += "{:>30s}  {:50s}".format("Timestamp", str(timestamp)) + "\n"
        attackstring += "{:>30s}  {:50s}".format("Source IP Address", str(src_ip)) + "\n"

        if not skip_enrich and urlhausapi:
            logging.info(f"Querying URLHaus for IP {src_ip}")
            uh_data = safe_read_uh_data(src_ip, urlhausapi)
            attackstring += "{:>30s}  {:50s}".format("URLhaus IP Tags", str(uh_data)) + "\n"

        if not skip_enrich and email:
            logging.info(f"Querying DShield for IP {src_ip}")
            try:
                json_data = with_timeout(30, dshield_query, src_ip)
                attackstring += "{:>30s}  {:50s}".format("ASNAME", (json_data['ip']['asname'])) + "\n"
                attackstring += "{:>30s}  {:50s}".format("ASCOUNTRY", (json_data['ip']['ascountry'])) + "\n"
                attackstring += "{:>30s}  {:<6d}".format("Total Commands Run", command_count) + "\n"
            except TimeoutError:
                logging.warning(f"DShield query timed out for IP {src_ip}")
                attackstring += "{:>30s}  {:50s}".format("ASNAME", "TIMEOUT") + "\n"
                attackstring += "{:>30s}  {:50s}".format("ASCOUNTRY", "TIMEOUT") + "\n"
                attackstring += "{:>30s}  {:<6d}".format("Total Commands Run", command_count) + "\n"

        if not skip_enrich and spurapi:
            logging.info(f"Querying SPUR for IP {src_ip}")
            try:
                spur_session_data = with_timeout(30, read_spur_data, src_ip)
            except TimeoutError:
                logging.warning(f"SPUR query timed out for IP {src_ip}")
                spur_session_data = ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]
            if spur_session_data[0] != "":
                attackstring += "{:>30s}  {:<50s}".format("SPUR ASN", str(spur_session_data[0])) + "\n"
            if spur_session_data[1] != "":
                attackstring += "{:>30s}  {:<50s}".format("SPUR ASN Organization", str(spur_session_data[1])) + "\n"
            if spur_session_data[2] != "":
                attackstring += "{:>30s}  {:<50s}".format("SPUR Organization", str(spur_session_data[2])) + "\n"
            if spur_session_data[3] != "":
                attackstring += "{:>30s}  {:<50s}".format("SPUR Infrastructure", str(spur_session_data[3])) + "\n"
            if spur_session_data[4] != "":
                attackstring += "{:>30s}  {:<50s}".format("SPUR Client Behaviors", str(spur_session_data[4])) + "\n"
            if spur_session_data[5] != "":
                attackstring += "{:>30s}  {:<50s}".format("SPUR Client Proxies", str(spur_session_data[5])) + "\n"
            if spur_session_data[6] != "":
                attackstring += "{:>30s}  {:<50s}".format("SPUR Client Types", str(spur_session_data[6])) + "\n"
            if spur_session_data[7] != "":
                attackstring += "{:>30s}  {:<50s}".format("SPUR Client Count", str(spur_session_data[7])) + "\n"
            if spur_session_data[8] != "":
                attackstring += "{:>30s}  {:<50s}".format("SPUR Client Concentration", str(spur_session_data[8])) + "\n"
            if spur_session_data[9] != "":
                attackstring += "{:>30s}  {:<50s}".format("SPUR Client Countries", str(spur_session_data[9])) + "\n"
            if spur_session_data[10] != "":
                attackstring += "{:>30s}  {:<50s}".format("SPUR Client Geo-spread", str(spur_session_data[10])) + "\n"
            if spur_session_data[11] != "":
                attackstring += "{:>30s}  {:<50s}".format("SPUR Risks", str(spur_session_data[11])) + "\n"
            if spur_session_data[12] != "":
                attackstring += "{:>30s}  {:<50s}".format("SPUR Services", str(spur_session_data[12])) + "\n"
            if spur_session_data[13] != "":
                attackstring += "{:>30s}  {:<50s}".format("SPUR Location", str(spur_session_data[13])) + "\n"
            if spur_session_data[14] != "":
                attackstring += "{:>30s}  {:<50s}".format("SPUR Anonymous Tunnel", str(spur_session_data[14])) + "\n"
            if spur_session_data[15] != "":
                attackstring += "{:>30s}  {:<50s}".format("SPUR Tunnel Entries", str(spur_session_data[15])) + "\n"
            if spur_session_data[16] != "":
                attackstring += "{:>30s}  {:<50s}".format("SPUR Tunnel Operator", str(spur_session_data[16])) + "\n"
            if spur_session_data[17] != "":
                attackstring += "{:>30s}  {:<50s}".format("SPUR Tunnel Type", str(spur_session_data[17])) + "\n"

        if len(downloaddata) > 0:
            attackstring += "\n------------------- DOWNLOAD DATA -------------------\n"
            logging.info(f"Processing {len(downloaddata)} downloads for session {session}")
        for each_download in downloaddata:
            if each_download[1]:
                attackstring += "\n"
                attackstring += "{:>30s}  {:50s}".format("Download URL", each_download[0]) + "\n"
                attackstring += "{:>30s}  {:50s}".format("Download SHA-256 Hash", each_download[1]) + "\n"
                attackstring += "{:>30s}  {:50s}".format("Destination File", each_download[3]) + "\n"

                sql = '''SELECT * FROM files WHERE session=? and hash=? and file_path=? and hostname=?'''
                max_retries = 3
                for retry in range(max_retries):
                    try:
                        cur.execute(sql, (session, each_download[1], each_download[3], hostname))
                        rows = cur.fetchall()
                        download_data_needed = len(rows)
                        break
                    except sqlite3.OperationalError as e:
                        if "database is locked" in str(e) and retry < max_retries - 1:
                            logging.warning(
                                f"Database locked, retrying in 1 second (attempt {retry + 1}/{max_retries})"
                            )
                            time.sleep(1)
                            continue
                        else:
                            logging.error(f"Database error after {max_retries} retries: {e}")
                            raise

                if download_data_needed > 0:
                    print("Download data for session " + session + " was already stored within database")
                else:
                    sql = '''INSERT INTO files(session, download_url, hash, file_path, hostname) VALUES (?,?,?,?,?)'''
                    for retry in range(max_retries):
                        try:
                            cur.execute(sql, (session, each_download[0], each_download[1], each_download[3], hostname))
                            db_commit()
                            break
                        except sqlite3.OperationalError as e:
                            if "database is locked" in str(e) and retry < max_retries - 1:
                                logging.warning(
                                    f"Database locked during insert, retrying in 1 second "
                                    f"(attempt {retry + 1}/{max_retries})"
                                )
                                time.sleep(1)
                                continue
                            else:
                                logging.error(f"Database insert error after {max_retries} retries: {e}")
                                raise

                vt_cache_path = cache_dir / each_download[1]
                if not skip_enrich and not vt_cache_path.exists() and vtapi:
                    logging.info(f"Querying VirusTotal for hash {each_download[1]}")
                    try:
                        with_timeout(60, vt_query, each_download[1], cache_dir)
                        if vt_sleep > 0:
                            time.sleep(vt_sleep)
                    except TimeoutError:
                        logging.warning(f"VT query timed out for hash {each_download[1]}")

                if vt_cache_path.exists() and vtapi:
                    vt_description, vt_threat_classification, vt_first_submission, vt_malicious = read_vt_data(
                        each_download[1], cache_dir
                    )
                    attackstring += "{:>30s}  {:50s}".format("VT Description", (vt_description)) + "\n"
                    attackstring += (
                        "{:>30s}  {:50s}".format("VT Threat Classification", (vt_threat_classification)) + "\n"
                    )
                    if download_data_needed == 0:
                        sql = '''UPDATE files SET vt_description=?, vt_threat_classification=?, vt_first_submission=?, 
                            vt_hits=?, transfer_method=?, added=? WHERE session=? and hash=? and hostname=?'''
                        cur.execute(
                            sql,
                            (
                                vt_description,
                                vt_threat_classification,
                                vt_first_submission,
                                vt_malicious,
                                "DOWNLOAD",
                                time.time(),
                                session,
                                each_download[1],
                                hostname,
                            ),
                        )
                        db_commit()
                    if vt_threat_classification == "":
                        vt_classifications.append("<blank>")
                        # commented out due to too many inclusions from hosts.deny data
                        # abnormal_attacks.add(session)
                    else:
                        vt_classifications.append(vt_threat_classification)
                    attackstring += (
                        "{:>30s}  {}".format(
                            "VT First Submssion",
                            (datetime.datetime.fromtimestamp(int(vt_first_submission))),
                        )
                        + "\n"
                    )
                    if (datetime.datetime.now() - datetime.datetime.fromtimestamp(int(vt_first_submission))).days <= 5:
                        abnormal_attacks.add(session)
                        vt_recent_submissions.add(session)
                    attackstring += "{:>30s}  {:<6d}".format("VT Malicious Hits", (vt_malicious)) + "\n"

                if each_download[2] != "" and email:
                    if re.search('[a-zA-Z]', each_download[2]):
                        attackstring += "{:>30s}  {:50s}".format("Download Source Address", each_download[2]) + "\n"
                        urlhaus_tags = (
                            safe_read_uh_data(each_download[2], urlhausapi) if not skip_enrich and urlhausapi else ""
                        )
                        if urlhaus_tags:
                            attackstring += "{:>30s}  {:50s}".format("URLhaus Source Tags", urlhaus_tags) + "\n"
                        sql = '''UPDATE files SET src_ip=?, urlhaus_tag=? WHERE session=? and hash=? and hostname=?'''
                        cur.execute(
                            sql,
                            (
                                each_download[2],
                                urlhaus_tags,
                                session,
                                each_download[1],
                                hostname,
                            ),
                        )
                        db_commit()
                    else:
                        if not skip_enrich and email:
                            try:
                                json_data = with_timeout(30, dshield_query, each_download[2])
                            except TimeoutError:
                                logging.warning(f"DShield query timed out for download source IP {each_download[2]}")
                                json_data = {'ip': {'asname': 'TIMEOUT', 'ascountry': 'TIMEOUT'}}
                        else:
                            json_data = {'ip': {'asname': '', 'ascountry': ''}}
                        attackstring += "{:>30s}  {:50s}".format("Download Source Address", each_download[2]) + "\n"
                        urlhaus_ip_tags = (
                            safe_read_uh_data(each_download[2], urlhausapi) if not skip_enrich and urlhausapi else ""
                        )
                        if urlhaus_ip_tags:
                            attackstring += "{:>30s}  {:50s}".format("URLhaus IP Tags", urlhaus_ip_tags) + "\n"
                        attackstring += "{:>30s}  {:50s}".format("ASNAME", json_data['ip']['asname']) + "\n"
                        attackstring += "{:>30s}  {:50s}".format("ASCOUNTRY", json_data['ip']['ascountry']) + "\n"

                        if not skip_enrich and spurapi:
                            try:
                                spur_data = with_timeout(30, read_spur_data, src_ip)
                            except TimeoutError:
                                logging.warning(f"SPUR query timed out for download source IP {src_ip}")
                                spur_data = ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]
                        else:
                            spur_data = ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]
                        if spur_data[0] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR ASN", str(spur_data[0])) + "\n"
                        if spur_data[1] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR ASN Organization", str(spur_data[1])) + "\n"
                        if spur_data[2] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Organization", str(spur_data[2])) + "\n"
                        if spur_data[3] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Infrastructure", str(spur_data[3])) + "\n"
                        if spur_data[4] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Client Behaviors", str(spur_data[4])) + "\n"
                        if spur_data[5] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Client Proxies", str(spur_data[5])) + "\n"
                        if spur_data[6] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Client Types", str(spur_data[6])) + "\n"
                        if spur_data[7] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Client Count", str(spur_data[7])) + "\n"
                        if spur_data[8] != "":
                            attackstring += (
                                "{:>30s}  {:<50s}".format("SPUR Client Concentration", str(spur_data[8])) + "\n"
                            )
                        if spur_data[9] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Client Countries", str(spur_data[9])) + "\n"
                        if spur_data[10] != "":
                            attackstring += (
                                "{:>30s}  {:<50s}".format("SPUR Client Geo-spread", str(spur_data[10])) + "\n"
                            )
                        if spur_data[11] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Risks", str(spur_data[11])) + "\n"
                        if spur_data[12] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Services", str(spur_data[12])) + "\n"
                        if spur_data[13] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Location", str(spur_data[13])) + "\n"
                        if spur_data[14] != "":
                            attackstring += (
                                "{:>30s}  {:<50s}".format("SPUR Anonymous Tunnel", str(spur_data[14])) + "\n"
                            )
                        if spur_data[15] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Tunnel Entries", str(spur_data[15])) + "\n"
                        if spur_data[16] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Tunnel Operator", str(spur_data[16])) + "\n"
                        if spur_data[17] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Tunnel Type", str(spur_data[17])) + "\n"

                            sql = '''UPDATE files SET src_ip=?, urlhaus_tag=?, asname=?, ascountry=?,
                                spur_asn=?,
                                spur_asn_organization=?,
                                spur_organization=?,
                                spur_infrastructure=?,
                                spur_client_behaviors=?,
                                spur_client_proxies=?,
                                spur_client_types=?,
                                spur_client_count=?,
                                spur_client_concentration=?,
                                spur_client_countries=?,
                                spur_geospread=?,
                                spur_risks=?,
                                spur_services=?,
                                spur_location=?,
                                spur_tunnel_anonymous=?,
                                spur_tunnel_entries=?,
                                spur_tunnel_operator=?,
                                spur_tunnel_type=?                             

                                WHERE session=? and hash=? and hostname=?'''
                            cur.execute(
                                sql,
                                (
                                    each_download[2],
                                    urlhaus_ip_tags,
                                    json_data['ip']['asname'],
                                    json_data['ip']['ascountry'],
                                    *(str(value) for value in spur_data[0:18]),
                                    session,
                                    each_download[1],
                                    hostname,
                                ),
                            )
                            db_commit()

        if len(uploaddata) > 0:
            attackstring += "\n------------------- UPLOAD DATA -------------------\n"
        for each_upload in uploaddata:
            if each_upload[1]:
                attackstring += "\n"
                attackstring += "{:>30s}  {:50s}".format("Upload URL", each_upload[0]) + "\n"
                attackstring += "{:>30s}  {:50s}".format("Upload SHA-256 Hash", each_upload[1]) + "\n"
                attackstring += "{:>30s}  {:50s}".format("Destination File", each_upload[3]) + "\n"

                sql = '''SELECT * FROM files WHERE session=? and hash=? and file_path=? and hostname=?'''
                cur.execute(sql, (session, each_upload[1], each_upload[3], hostname))
                rows = cur.fetchall()
                upload_data_needed = len(rows)

                if upload_data_needed > 0:
                    print("Upload data for session " + session + " was already stored within database")
                else:
                    sql = '''INSERT INTO files(session, download_url, hash, file_path, hostname) VALUES (?,?,?,?,?)'''
                    cur.execute(sql, (session, each_upload[0], each_upload[1], each_upload[3], hostname))
                    db_commit()

                up_vt_cache_path = cache_dir / each_upload[1]
                if not skip_enrich and not up_vt_cache_path.exists() and vtapi:
                    try:
                        with_timeout(60, vt_query, each_upload[1], cache_dir)
                        if vt_sleep > 0:
                            time.sleep(vt_sleep)
                    except TimeoutError:
                        logging.warning(f"VT query timed out for upload hash {each_upload[1]}")

                if up_vt_cache_path.exists() and vtapi:
                    vt_description, vt_threat_classification, vt_first_submission, vt_malicious = read_vt_data(
                        each_upload[1], cache_dir
                    )
                    attackstring += "{:>30s}  {:50s}".format("VT Description", (vt_description)) + "\n"
                    attackstring += (
                        "{:>30s}  {:50s}".format("VT Threat Classification", (vt_threat_classification)) + "\n"
                    )
                    attackstring += (
                        "{:>30s}  {}".format(
                            "VT First Submssion",
                            (datetime.datetime.fromtimestamp(int(vt_first_submission))),
                        )
                        + "\n"
                    )
                    attackstring += "{:>30s}  {:<6d}".format("VT Malicious Hits", (vt_malicious)) + "\n"

                    if upload_data_needed == 0:
                        sql = '''UPDATE files SET vt_description=?, vt_threat_classification=?, vt_first_submission=?,
                            vt_hits=?, transfer_method=?, added=? WHERE session=? and hash=? and hostname=?'''
                        cur.execute(
                            sql,
                            (
                                vt_description,
                                vt_threat_classification,
                                vt_first_submission,
                                vt_malicious,
                                "UPLOAD",
                                time.time(),
                                session,
                                each_upload[1],
                                hostname,
                            ),
                        )
                        db_commit()

                if each_upload[2] != "" and email:
                    if re.search('[a-zA-Z]', each_upload[2]):
                        attackstring += "{:>30s}  {:50s}".format("Upload Source Address", each_upload[2]) + "\n"
                        upload_tags = (
                            safe_read_uh_data(each_upload[2], urlhausapi) if not skip_enrich and urlhausapi else ""
                        )
                        if upload_tags:
                            attackstring += "{:>30s}  {:50s}".format("URLhaus IP Tags", upload_tags) + "\n"

                        sql = '''UPDATE files SET src_ip=?, urlhaus_tag=? WHERE session=? and hash=? and hostname=?'''
                        cur.execute(
                            sql,
                            (
                                each_upload[2],
                                upload_tags,
                                session,
                                each_upload[1],
                                hostname,
                            ),
                        )
                        db_commit()

                    else:
                        if not skip_enrich and email:
                            try:
                                json_data = with_timeout(30, dshield_query, each_upload[2])
                            except TimeoutError:
                                logging.warning(f"DShield query timed out for upload source IP {each_upload[2]}")
                                json_data = {'ip': {'asname': 'TIMEOUT', 'ascountry': 'TIMEOUT'}}
                        else:
                            json_data = {'ip': {'asname': '', 'ascountry': ''}}
                        attackstring += "{:>30s}  {:50s}".format("Upload Source Address", each_upload[2]) + "\n"
                        upload_ip_tags = (
                            safe_read_uh_data(each_upload[2], urlhausapi) if not skip_enrich and urlhausapi else ""
                        )
                        if upload_ip_tags:
                            attackstring += "{:>30s}  {:50s}".format("URLhaus IP Tags", upload_ip_tags) + "\n"
                        attackstring += "{:>30s}  {:50s}".format("ASNAME", json_data['ip']['asname']) + "\n"
                        attackstring += "{:>30s}  {:50s}".format("ASCOUNTRY", json_data['ip']['ascountry']) + "\n"

                        if not skip_enrich and spurapi:
                            try:
                                spur_data = with_timeout(30, read_spur_data, src_ip)
                            except TimeoutError:
                                logging.warning(f"SPUR query timed out for upload source IP {src_ip}")
                                spur_data = ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]
                        else:
                            spur_data = ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]
                        if spur_data[0] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR ASN", str(spur_data[0])) + "\n"
                        if spur_data[1] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR ASN Organization", str(spur_data[1])) + "\n"
                        if spur_data[2] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Organization", str(spur_data[2])) + "\n"
                        if spur_data[3] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Infrastructure", str(spur_data[3])) + "\n"
                        if spur_data[4] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Client Behaviors", str(spur_data[4])) + "\n"
                        if spur_data[5] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Client Proxies", str(spur_data[5])) + "\n"
                        if spur_data[6] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Client Types", str(spur_data[6])) + "\n"
                        if spur_data[7] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Client Count", str(spur_data[7])) + "\n"
                        if spur_data[8] != "":
                            attackstring += (
                                "{:>30s}  {:<50s}".format("SPUR Client Concentration", str(spur_data[8])) + "\n"
                            )
                        if spur_data[9] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Client Countries", str(spur_data[9])) + "\n"
                        if spur_data[10] != "":
                            attackstring += (
                                "{:>30s}  {:<50s}".format("SPUR Client Geo-spread", str(spur_data[10])) + "\n"
                            )
                        if spur_data[11] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Risks", str(spur_data[11])) + "\n"
                        if spur_data[12] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Services", str(spur_data[12])) + "\n"
                        if spur_data[13] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Location", str(spur_data[13])) + "\n"
                        if spur_data[14] != "":
                            attackstring += (
                                "{:>30s}  {:<50s}".format(
                                    "SPUR Anonymous Tunnel",
                                    str(spur_data[14]),
                                )
                                + "\n"
                            )
                        if spur_data[15] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Tunnel Entries", str(spur_data[15])) + "\n"
                        if spur_data[16] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Tunnel Operator", str(spur_data[16])) + "\n"
                        if spur_data[17] != "":
                            attackstring += "{:>30s}  {:<50s}".format("SPUR Tunnel Type", str(spur_data[17])) + "\n"

                        sql = '''UPDATE files SET src_ip=?, urlhaus_tag=?, asname=?, ascountry=?,
                            spur_asn=?,
                            spur_asn_organization=?,
                            spur_organization=?,
                            spur_infrastructure=?,
                            spur_client_behaviors=?,
                            spur_client_proxies=?,
                            spur_client_types=?,
                            spur_client_count=?,
                            spur_client_concentration=?,
                            spur_client_countries=?,
                            spur_geospread=?,
                            spur_risks=?,
                            spur_services=?,
                            spur_location=?,
                            spur_tunnel_anonymous=?,
                            spur_tunnel_entries=?,
                            spur_tunnel_operator=?,
                            spur_tunnel_type=?                             

                            WHERE session=? and hash=? and hostname=?'''
                        cur.execute(
                            sql,
                            (
                                each_upload[2],
                                upload_ip_tags,
                                json_data['ip']['asname'],
                                json_data['ip']['ascountry'],
                                *(str(value) for value in spur_data[0:18]),
                                session,
                                each_upload[1],
                                hostname,
                            ),
                        )
                        db_commit()

        attackstring += "\n////////////////// COMMANDS ATTEMPTED //////////////////\n\n"
        attackstring += get_commands(data, session) + "\n"
        attackstring += (
            "\nXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX\n"
            "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXX\n\n"
        )
        print(attackstring)

        utc_time = datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
        epoch_time = (utc_time - datetime.datetime(1970, 1, 1)).total_seconds()
        sql = '''SELECT * FROM sessions WHERE session=? and timestamp=? and hostname=?'''
        cur.execute(sql, (session, epoch_time, hostname))

        rows = cur.fetchall()
        if len(rows) > 0:
            print("Data for session " + session + " was already stored within database")
        else:
            session_urlhaus_tags = safe_read_uh_data(src_ip, urlhausapi) if not skip_enrich and urlhausapi else ""
            sql = (
                "INSERT INTO sessions( session, session_duration, protocol, username, password, "
                "timestamp, source_ip, urlhaus_tag, asname, ascountry, total_commands, added, hostname) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
            )

            if 'json_data' in locals():
                cur.execute(
                    sql,
                    (
                        session,
                        session_duration,
                        protocol,
                        username,
                        password,
                        epoch_time,
                        src_ip,
                        session_urlhaus_tags,
                        json_data['ip']['asname'],
                        json_data['ip']['ascountry'],
                        command_count,
                        time.time(),
                        hostname,
                    ),
                )
                db_commit()
            else:
                cur.execute(
                    sql,
                    (
                        session,
                        session_duration,
                        protocol,
                        username,
                        password,
                        epoch_time,
                        src_ip,
                        session_urlhaus_tags,
                        "",
                        "",
                        command_count,
                        time.time(),
                        hostname,
                    ),
                )
                db_commit()

            if spurapi:
                sql = '''UPDATE sessions SET 
                    spur_asn=?,
                    spur_asn_organization=?,
                    spur_organization=?,
                    spur_infrastructure=?,
                    spur_client_behaviors=?,
                    spur_client_proxies=?,
                    spur_client_types=?,
                    spur_client_count=?,
                    spur_client_concentration=?,
                    spur_client_countries=?,
                    spur_geospread=?,
                    spur_risks=?,
                    spur_services=?,
                    spur_location=?,
                    spur_tunnel_anonymous=?,
                    spur_tunnel_entries=?,
                    spur_tunnel_operator=?,
                    spur_tunnel_type=?                             
                    WHERE session=? and timestamp=? and hostname=?'''
                cur.execute(
                    sql,
                    (
                        str(spur_session_data[0]),
                        str(spur_session_data[1]),
                        str(spur_session_data[2]),
                        str(spur_session_data[3]),
                        str(spur_session_data[4]),
                        str(spur_session_data[5]),
                        str(spur_session_data[6]),
                        str(spur_session_data[7]),
                        str(spur_session_data[8]),
                        str(spur_session_data[9]),
                        str(spur_session_data[10]),
                        str(spur_session_data[11]),
                        str(spur_session_data[12]),
                        str(spur_session_data[13]),
                        str(spur_session_data[14]),
                        str(spur_session_data[15]),
                        str(spur_session_data[16]),
                        str(spur_session_data[17]),
                        session,
                        epoch_time,
                        hostname,
                    ),
                )
                db_commit()

        if attack_type == "abnormal":
            if summarizedays:
                report_file = open(date + "_abnormal_" + summarizedays + "-day_report.txt", "a", encoding="utf-8")
            else:
                report_file = open(date + "abnormal_report.txt", "a", encoding="utf-8")
            report_file.write(attackstring)
            report_file.close()
        else:
            if summarizedays:
                report_file = open(date + "_" + summarizedays + "_day_report.txt", "a", encoding="utf-8")
            else:
                report_file = open(date + "_report.txt", "a", encoding="utf-8")
            report_file.write(attackstring)
            report_file.close()


def print_summary():
    """Legacy no-op summary function retained for compatibility.

    The previous implementation referenced undefined globals. This
    placeholder remains to avoid breaking callers but intentionally does
    nothing.
    """
    return None


def get_commands(data, session):
    """Collect input commands for a session and persist them.

    Args:
        data: Iterable of Cowrie event dictionaries.
        session: Session ID string.

    Returns:
        A string with each command prefixed by ``# `` and a newline.
    """
    cur = con.cursor()
    commands = ""
    for each_entry in data:
        if each_entry['session'] == session:
            if "cowrie.command.input" in each_entry['eventid']:
                commands += "# " + each_entry['input'] + "\n"
                utc_time = datetime.datetime.strptime(each_entry['timestamp'], "%Y-%m-%dT%H:%M:%S.%fZ")
                epoch_time = (utc_time - datetime.datetime(1970, 1, 1)).total_seconds()
                sql = '''SELECT * FROM commands WHERE session=? and command=? and timestamp=? and hostname=?'''
                cur.execute(sql, (session, each_entry['input'], epoch_time, hostname))
                rows = cur.fetchall()
                if len(rows) > 0:
                    print("Command data for session " + session + " was already stored within database")
                else:
                    sql = '''INSERT INTO commands(session, command, timestamp, added, hostname) VALUES (?,?,?,?,?)'''
                    # utc_time = datetime.datetime.strptime(each_entry['timestamp'], "%Y-%m-%dT%H:%M:%S.%fZ")
                    # epoch_time = (utc_time - datetime.datetime(1970, 1, 1)).total_seconds()
                    cur.execute(sql, (session, each_entry['input'], epoch_time, time.time(), hostname))
    db_commit()
    return commands


initialize_database()

if len(list_of_files) == 0:
    sys.exit(0)


def open_json_lines(path: str):
    """Open a JSONL file (supports .bz2 and .gz) for text reading."""
    if path.endswith('.bz2'):
        bz2_raw = bz2.BZ2File(path, 'rb')
        return io.TextIOWrapper(bz2_raw, encoding='utf-8', errors='replace')
    if path.endswith('.gz'):
        gz_raw = gzip.GzipFile(filename=path, mode='rb')
        return io.TextIOWrapper(gz_raw, encoding='utf-8', errors='replace')
    return open(path, 'r', encoding='utf-8', errors='replace')


for filename in list_of_files:
    file_path_obj = Path(log_location) / filename
    filepath_str = os.fspath(file_path_obj)
    print("Processing file " + filepath_str)
    logging.info(f"Starting to process file {filename} ({processed_files + 1}/{total_files})")
    write_status(state='reading', total_files=total_files, processed_files=processed_files, current_file=filename)
    try:
        file_started_at = time.time()
        # Optional normalization pass: attempt to read entire file and parse non-JSONL formats
        if jq_normalize:
            with open_json_lines(filepath_str) as file:
                contents = file.read()
            try:
                obj = json.loads(contents)
                emit_count = 0
                t_last = time.time()
                if isinstance(obj, list):
                    for rec in obj:
                        if isinstance(rec, dict):
                            data.append(rec)
                        emit_count += 1
                        if emit_count % 100 == 0 or (time.time() - t_last) >= max(5, status_interval):
                            write_status(
                                state='normalizing',
                                total_files=total_files,
                                processed_files=processed_files,
                                current_file=filename,
                                file_lines=emit_count,
                                elapsed_secs=round(time.time() - file_started_at, 2),
                            )
                            t_last = time.time()
                elif isinstance(obj, dict):
                    data.append(obj)
                else:
                    # Fallback to line-by-line using splitlines
                    for line in contents.splitlines():
                        if max_line_bytes and len(line) > max_line_bytes:
                            continue
                        try:
                            rec = json.loads(line.replace('\0', ''))
                            if isinstance(rec, dict):
                                data.append(rec)
                        except Exception:
                            continue
                processed_files += 1
                write_status(
                    state='reading',
                    total_files=total_files,
                    processed_files=processed_files,
                    current_file=filename,
                )
                continue
            except Exception:
                # Fallback to streaming line-by-line parsing
                pass

        with open_json_lines(filepath_str) as file:
            line_count = 0
            t_last = time.time()
            started_at = file_started_at
            for each_line in file:
                # Bail out if a single file exceeds processing time budget
                if file_timeout and (time.time() - started_at) > file_timeout:
                    logging.error(
                        "File processing timeout after %ss: %s (lines=%s)",
                        file_timeout,
                        filepath_str,
                        line_count,
                    )
                    break
                try:
                    # Skip pathological oversized lines to avoid stalls
                    if max_line_bytes and len(each_line) > max_line_bytes:
                        logging.warning(
                            "Oversized JSON line skipped in %s (size=%s bytes > %s)",
                            filepath_str,
                            len(each_line),
                            max_line_bytes,
                        )
                        continue
                    json_file = json.loads(each_line.replace('\0', ''))
                    if isinstance(json_file, dict):
                        json_file['__source_file'] = filename
                        data.append(json_file)
                except Exception:
                    # Skip malformed JSON lines
                    continue
                line_count += 1
                # heartbeat during large files
                if line_count % 5000 == 0:
                    logging.info(
                        "Read %s lines from %s after %.2fs",
                        line_count,
                        filename,
                        time.time() - file_started_at,
                    )
                if line_count % 100 == 0 or (time.time() - t_last) >= max(5, status_interval):
                    write_status(
                        state='reading',
                        total_files=total_files,
                        processed_files=processed_files,
                        current_file=filename,
                        file_lines=line_count,
                        elapsed_secs=round(time.time() - file_started_at, 2),
                    )
                    t_last = time.time()
    except EOFError:
        logging.warning("Compressed file appears truncated; skipping: %s", filepath_str)
        processed_files += 1
        write_status(state='reading', total_files=total_files, processed_files=processed_files, current_file=filename)
        continue
    except Exception as e:
        logging.error("Error reading file %s; skipping due to: %s", filepath_str, e, exc_info=True)
        processed_files += 1
        write_status(state='reading', total_files=total_files, processed_files=processed_files, current_file=filename)
        continue
    file_elapsed = time.time() - file_started_at
    write_status(
        state='file_complete',
        total_files=total_files,
        processed_files=processed_files + 1,
        current_file=filename,
        file_lines=(line_count if 'line_count' in locals() else len(data)),
        elapsed_secs=round(file_elapsed, 2),
    )
    processed_files += 1
    logging.info(
        "Completed processing file %s - %s log entries in %.2fs",
        filename,
        len(data),
        file_elapsed,
    )

    # Check database size periodically
    if processed_files % 10 == 0:  # Every 10 files
        try:
            db_size = os.path.getsize(args.db)
            logging.info(f"Database size after {processed_files} files: {db_size / (1024 * 1024):.1f} MB")
        except Exception:
            pass

    write_status(
        state='reading',
        total_files=total_files,
        processed_files=processed_files,
        current_file='',
    )

# File processing complete - update status
write_status(state='files_complete', total_files=total_files, processed_files=processed_files, current_file='')


def update_stage_status(state, **extra):
    """Helper to emit status updates for post-file phases."""
    write_status(
        state=state,
        total_files=total_files,
        processed_files=processed_files,
        current_file='',
        **extra,
    )


total_log_entries = len(data)
index_stage_started = time.time()
update_stage_status('indexing_sessions', log_entries=total_log_entries, log_entries_indexed=0, elapsed_secs=0)

vt_session = requests.session()

# Report generation starting - update status
write_status(state='generating_reports', total_files=total_files, processed_files=processed_files, current_file='')

# Enumerate sessions and capture metrics using the new matcher pipeline
logging.info("Enumerating sessions and gathering metrics...")


def _enum_progress(stats: Dict[str, object]) -> None:
    events_processed = _safe_int(stats.get('events_processed'))
    session_count = _safe_int(stats.get('session_count'))
    match_counts_payload = _safe_match_counts(stats.get('match_counts'))
    update_stage_status(
        'indexing_sessions',
        log_entries=total_log_entries,
        log_entries_indexed=events_processed,
        total_sessions=session_count,
        elapsed_secs=round(time.time() - index_stage_started, 2),
        match_type_counts=match_counts_payload,
    )


def _enum_checkpoint(snapshot: Dict[str, object]) -> None:
    events_processed = _safe_int(snapshot.get('events_processed'))
    session_count = _safe_int(snapshot.get('session_count'))
    match_counts_payload = _safe_match_counts(snapshot.get('match_counts'))
    last_session = _safe_optional_str(snapshot.get('last_session'))
    save_checkpoint(
        last_session=last_session,
        events_processed=events_processed,
        match_counts=match_counts_payload,
    )
    update_stage_status(
        'indexing_sessions',
        log_entries=total_log_entries,
        log_entries_indexed=events_processed,
        total_sessions=session_count,
        elapsed_secs=round(time.time() - index_stage_started, 2),
        match_type_counts=match_counts_payload,
        checkpoint=True,
    )


enumeration_result = enumerate_sessions(
    data,
    progress_callback=_enum_progress,
    checkpoint_callback=_enum_checkpoint,
    progress_interval=1000,
    checkpoint_interval=10000,
    source_getter=_source_file_from_entry,
)

data_by_session = enumeration_result.by_session
match_counts = enumeration_result.match_counts
persist_session_metrics(enumeration_result.metrics, hostname=hostname)

if enumeration_result.events_processed:
    save_checkpoint(
        last_session=None,
        events_processed=enumeration_result.events_processed,
        match_counts=match_counts,
    )

total_sessions_indexed = len(data_by_session)
update_stage_status(
    'indexing_sessions',
    log_entries=total_log_entries,
    log_entries_indexed=enumeration_result.events_processed,
    total_sessions=total_sessions_indexed,
    elapsed_secs=round(time.time() - index_stage_started, 2),
    match_type_counts=match_counts,
)

selected_sessions: list[str] = []

if summarizedays:
    session_id = get_session_id(data, "all", "unnecessary")
    selected_sessions = list(session_id)
    print_session_info(data, session_id, "standard", data_by_session)

elif session_id:
    sessions = [session_id]
    selected_sessions = list(sessions)
    print_session_info(data, sessions, "standard", data_by_session)

elif tty_file:
    session_id = get_session_id(data, "tty", tty_file)
    selected_sessions = list(session_id)
    print_session_info(data, session_id, "standard", data_by_session)

elif download_file:
    session_id = get_session_id(data, "download", download_file)
    selected_sessions = list(session_id)
    print_session_info(data, session_id, "standard", data_by_session)

else:
    session_id = get_session_id(data, "all", "unnecessary")
    selected_sessions = list(session_id)
    print_session_info(data, session_id, "standard", data_by_session)

update_stage_status('session_selection', total_sessions=len(selected_sessions))


counts = collections.Counter(number_of_commands)
number_of_commands = sorted(number_of_commands, key=lambda x: -counts[x])
commands = set()
for num_count in number_of_commands:
    commands.add(num_count)

command_number_dict = {}
abnormal_command_counts = []
for command in commands:
    # number of commands --> command
    # number of times the number of commands has been seen --> number_of_commands.count(command)
    command_number_dict[command] = number_of_commands.count(command)

sorted_command_counts = sorted(command_number_dict.items(), key=lambda x: x[1])
for key, value in sorted_command_counts:
    abnormal_command_counts.append(key)

abnormal_command_counts = abnormal_command_counts[0 : int(len(abnormal_command_counts) * (2 / 3))]


def evaluate_sessions(target_sessions):
    """Inspect selected sessions and update abnormal/command-count sets."""
    total_sessions_local = len(target_sessions)
    sessions_processed_local = 0
    stage_started = time.time()
    update_stage_status(
        'session_metrics',
        total_sessions=total_sessions_local,
        sessions_processed=sessions_processed_local,
        elapsed_secs=0,
    )
    if not total_sessions_local:
        return
    for session_key in target_sessions:
        session_data = data_by_session.get(session_key, data) if data_by_session else data
        command_count = get_command_total(session_key, session_data)
        if command_count in abnormal_command_counts:
            abnormal_attacks.add(session_key)
            uncommon_command_counts.add(session_key)
        sessions_processed_local += 1
        if sessions_processed_local % 50 == 0:
            update_stage_status(
                'session_metrics',
                total_sessions=total_sessions_local,
                sessions_processed=sessions_processed_local,
                elapsed_secs=round(time.time() - stage_started, 2),
            )
    update_stage_status(
        'session_metrics',
        total_sessions=total_sessions_local,
        sessions_processed=sessions_processed_local,
        elapsed_secs=round(time.time() - stage_started, 2),
    )


vt_counts = collections.Counter(vt_classifications)
vt_classifications = sorted(vt_classifications, key=lambda x: -vt_counts[x])
vt_class = set()
for classification in vt_classifications:
    vt_class.add(classification)


evaluate_sessions(selected_sessions)

vt_session.close()

# Final commit if bulk-load deferred commits
try:
    if bulk_load:
        commit_stage_started = time.time()
        update_stage_status(
            'final_commit',
            total_sessions=len(selected_sessions),
            sessions_processed=len(selected_sessions),
            elapsed_secs=0,
        )
        logging.info("Performing final bulk-load commit to database")
        con.commit()
        logging.info("Bulk-load commit completed")
        update_stage_status(
            'final_commit',
            total_sessions=len(selected_sessions),
            sessions_processed=len(selected_sessions),
            elapsed_secs=round(time.time() - commit_stage_started, 2),
        )
except Exception:
    logging.error("Final commit failed in bulk-load mode", exc_info=True)

report_stage_started = time.time()
update_stage_status(
    'report_generation',
    total_sessions=len(selected_sessions),
    sessions_processed=len(selected_sessions),
    elapsed_secs=0,
)

summarystring = "{:>40s}  {:10s}".format("Total Number of Attacks:", str(attack_count)) + "\n"
if number_of_commands:
    summarystring += "{:>40s}  {:10s}".format("Most Common Number of Commands:", str(number_of_commands[0])) + "\n"
else:
    summarystring += "{:>40s}  {:10s}".format("Most Common Number of Commands:", "N/A") + "\n"
summarystring += "\n"
summarystring += "{:>40s}  {:10s}".format("Number of Commands", "Times Seen") + "\n"
summarystring += "{:>40s}  {:10s}".format("------------------", "----------") + "\n"
for key, value in command_number_dict.items():
    summarystring += "{:>40s}  {:10s}".format(str(key), str(value)) + "\n"
summarystring += "\n"
summarystring += "{:>48s}".format("VT Classifications") + "\n"
summarystring += "{:>48s}".format("------------------") + "\n"
for classification in vt_class:
    summarystring += "{:>40s}  {:10s}".format(classification, str(vt_classifications.count(classification))) + "\n"
summarystring += "\n"
summarystring += (
    "{:>60s}".format(
        "Attacks With Uncommon Command Counts",
    )
    + "\n"
)
summarystring += "{:>60s}".format("------------------------------------") + "\n"
for each_submission in uncommon_command_counts:
    summarystring += "{:>40s}  {:10s}".format("", each_submission) + "\n"
summarystring += "\n"
summarystring += "{:>60s}".format("Attacks With Recent VT First Submission") + "\n"
summarystring += "{:>60s}".format("---------------------------------------") + "\n"
for each_submission in vt_recent_submissions:
    summarystring += "{:>40s}  {:10s}".format("", each_submission) + "\n"
summarystring += "\n"
summarystring += "{:>50s}".format("Abnormal Attacks") + "\n"
summarystring += "{:>50s}".format("----------------") + "\n"

for each_attack in abnormal_attacks:
    summarystring += "{:>40s}  {:10s}".format("", each_attack) + "\n"
summarystring += "\n\n"

if summarizedays:
    report_file = open(date + "_" + summarizedays + "_day_report.txt", "a")
else:
    report_file = open(date + "_report.txt", "a")
report_file.write(summarystring)
report_file.close()

if summarizedays:
    report_file = open(date + "_abnormal_" + summarizedays + "-day_report.txt", "a")
else:
    report_file = open(date + "_abnormal_report.txt", "a")
report_file.write(summarystring)
report_file.close()
print_session_info(data, abnormal_attacks, "abnormal")

update_stage_status(
    'report_generation',
    total_sessions=len(selected_sessions),
    sessions_processed=len(selected_sessions),
    elapsed_secs=round(time.time() - report_stage_started, 2),
)

if dbxapi:
    dbx = dropbox.Dropbox(dbxapi)
    with open(date + "_" + summarizedays + "_day_report.txt", 'rb') as f:
        dbx.files_upload(f.read(), "/" + date + filename_prepend + "_" + summarizedays + "_day_report.txt")

    with open(date + "_abnormal_" + summarizedays + "-day_report.txt", 'rb') as f:
        dbx.files_upload(f.read(), "/" + date + filename_prepend + "_abnormal_" + summarizedays + "-day_report.txt")

    with open("../cowrieprocessor.sqlite", 'rb') as f:
        dbx.files_upload(f.read(), "/" + date + filename_prepend + "_cowrieprocessor.sqlite")

elif dbxkey and dbxsecret and dbxrefreshtoken:
    dbx = dropbox.Dropbox(app_key=dbxkey, app_secret=dbxsecret, oauth2_refresh_token=dbxrefreshtoken)
    with open(date + "_" + summarizedays + "_day_report.txt", 'rb') as f:
        dbx.files_upload(f.read(), "/" + date + filename_prepend + "_" + summarizedays + "_day_report.txt")

    with open(date + "_abnormal_" + summarizedays + "-day_report.txt", 'rb') as f:
        dbx.files_upload(f.read(), "/" + date + filename_prepend + "_abnormal_" + summarizedays + "-day_report.txt")

    try:
        with open(args.db, 'rb') as f:
            dbx.files_upload(f.read(), "/" + date + filename_prepend + "_cowrieprocessor.sqlite")
    except Exception:
        logging.error("Failed to upload DB file to Dropbox", exc_info=True)

else:
    print("No Dropbox account information supplied to allow upload")

print(summarystring)
db_commit()

# Process complete - final status update
write_status(state='complete', total_files=total_files, processed_files=processed_files, current_file='')
