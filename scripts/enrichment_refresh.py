#!/usr/bin/env python3
"""Refresh enrichment payloads for existing sessions and files."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Optional

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError as exc:  # pragma: no cover - defensive
    raise RuntimeError("Python 3.11+ is required to run this script") from exc

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cowrieprocessor.enrichment import EnrichmentCacheManager  # noqa: E402
from enrichment_handlers import EnrichmentService  # noqa: E402

SENSORS_FILE_DEFAULT = PROJECT_ROOT / "sensors.toml"

SESSION_QUERY = """
    SELECT ss.session_id,
           MAX(json_extract(re.payload, '$.src_ip')) AS src_ip
    FROM session_summaries ss
    JOIN raw_events re ON re.session_id = ss.session_id
    WHERE json_extract(re.payload, '$.src_ip') IS NOT NULL
      AND json_extract(re.payload, '$.src_ip') != ''
    GROUP BY ss.session_id
    ORDER BY ss.last_event_at ASC, ss.session_id ASC
"""

FILE_QUERY = """
    SELECT DISTINCT shasum, filename, session_id
    FROM files
    WHERE shasum IS NOT NULL AND shasum != ''
      AND enrichment_status IN ('pending', 'failed')
    ORDER BY first_seen ASC
"""


def iter_sessions(conn: sqlite3.Connection, limit: int) -> Iterator[tuple[str, str]]:
    """Yield session IDs and source IPs in FIFO order."""
    query = SESSION_QUERY
    params: tuple[int, ...] = ()
    if limit > 0:
        query += " LIMIT ?"
        params = (limit,)
    for row in conn.execute(query, params):
        session_id, src_ip = row
        if session_id and src_ip:
            yield session_id, src_ip


def iter_files(conn: sqlite3.Connection, limit: int) -> Iterator[tuple[str, Optional[str], str]]:
    """Yield file hashes, filenames, and session IDs up to the requested limit."""
    query = FILE_QUERY
    params: tuple[int, ...] = ()
    if limit > 0:
        query += " LIMIT ?"
        params = (limit,)
    for row in conn.execute(query, params):
        shasum, filename, session_id = row
        if shasum:
            yield shasum, filename, session_id


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Return True when ``table_name`` is present in the database."""
    cursor = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def update_session(
    conn: sqlite3.Connection,
    session_id: str,
    enrichment_payload: dict,
    flags: dict,
) -> None:
    """Persist refreshed enrichment JSON and derived flags for a session."""
    sql = """
        UPDATE session_summaries
        SET enrichment = ?,
            vt_flagged = ?,
            dshield_flagged = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE session_id = ?
    """
    conn.execute(
        sql,
        (
            json.dumps(enrichment_payload) if enrichment_payload else None,
            1 if flags.get("vt_flagged") else 0,
            1 if flags.get("dshield_flagged") else 0,
            session_id,
        ),
    )


def update_file(
    conn: sqlite3.Connection,
    file_hash: str,
    enrichment_payload: dict,
) -> None:
    """Persist refreshed VirusTotal fields for a given file hash."""
    vt_data = enrichment_payload.get("virustotal") if isinstance(enrichment_payload, dict) else None
    if vt_data is None:
        # Mark as failed if no VT data
        conn.execute("UPDATE files SET enrichment_status = 'failed' WHERE shasum = ?", (file_hash,))
        return

    attributes = vt_data.get("data", {}).get("attributes", {}) if isinstance(vt_data, dict) else {}
    classification = attributes.get("popular_threat_classification", {})
    last_analysis = attributes.get("last_analysis_stats", {})

    # Extract VT data with proper type conversion
    vt_classification = classification.get("suggested_threat_label") if isinstance(classification, dict) else None
    vt_description = attributes.get("type_description")
    vt_malicious = bool(last_analysis.get("malicious", 0) > 0) if isinstance(last_analysis, dict) else False
    vt_positives = last_analysis.get("malicious", 0) if isinstance(last_analysis, dict) else 0
    vt_total = sum(last_analysis.values()) if isinstance(last_analysis, dict) else 0

    # Parse timestamps
    vt_first_seen = None
    vt_last_analysis = None
    vt_scan_date = None

    if attributes.get("first_submission_date"):
        try:
            vt_first_seen = datetime.fromtimestamp(int(attributes["first_submission_date"]))
        except (ValueError, TypeError):
            pass

    if attributes.get("last_analysis_date"):
        try:
            vt_last_analysis = datetime.fromtimestamp(int(attributes["last_analysis_date"]))
            vt_scan_date = vt_last_analysis
        except (ValueError, TypeError):
            pass

    sql = """
        UPDATE files
        SET vt_classification = ?,
            vt_description = ?,
            vt_malicious = ?,
            vt_first_seen = ?,
            vt_last_analysis = ?,
            vt_positives = ?,
            vt_total = ?,
            vt_scan_date = ?,
            enrichment_status = 'enriched',
            last_updated = CURRENT_TIMESTAMP
        WHERE shasum = ?
    """
    conn.execute(
        sql,
        (
            vt_classification,
            vt_description,
            vt_malicious,
            vt_first_seen,
            vt_last_analysis,
            vt_positives,
            vt_total,
            vt_scan_date,
            file_hash,
        ),
    )


def load_sensor_credentials(sensor_file: Path, sensor_index: int) -> dict[str, Optional[str]]:
    """Load API credentials from a sensors.toml configuration file."""
    if not sensor_file.exists():
        raise RuntimeError(f"Sensors file not found: {sensor_file}")
    with sensor_file.open("rb") as handle:
        data = tomllib.load(handle)
    sensors = data.get("sensor") or []
    if not sensors:
        raise RuntimeError("No sensors defined in sensors file")
    if sensor_index >= len(sensors):
        raise RuntimeError(f"Sensor index {sensor_index} out of range (found {len(sensors)})")
    sensor = sensors[sensor_index]
    return {
        "vt_api": sensor.get("vtapi"),
        "dshield_email": sensor.get("email"),
        "urlhaus_api": sensor.get("urlhausapi"),
        "spur_api": sensor.get("spurapi"),
    }


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments for the enrichment refresh utility."""
    parser = argparse.ArgumentParser(description="Refresh enrichment data in-place")
    parser.add_argument("--db", type=Path, required=True, help="Path to writable SQLite database")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path.home() / ".cache" / "cowrieprocessor" / "enrichment",
        help="Cache directory for enrichment payloads",
    )
    parser.add_argument("--vt-api-key", dest="vt_api", help="VirusTotal API key")
    parser.add_argument("--dshield-email", dest="dshield_email", help="Registered DShield email")
    parser.add_argument("--urlhaus-api-key", dest="urlhaus_api", help="URLHaus API key")
    parser.add_argument("--spur-api-key", dest="spur_api", help="SPUR API token")
    parser.add_argument(
        "--sensors-file",
        type=Path,
        default=SENSORS_FILE_DEFAULT,
        help="Path to sensors.toml (used when API credentials not supplied)",
    )
    parser.add_argument(
        "--sensor-index",
        type=int,
        default=0,
        help="Sensor entry index in sensors file",
    )
    parser.add_argument(
        "--sessions",
        type=int,
        default=1000,
        help="Number of sessions to refresh (0 for all)",
    )
    parser.add_argument(
        "--files",
        type=int,
        default=500,
        help="Number of file hashes to refresh (0 for all)",
    )
    parser.add_argument(
        "--commit-interval",
        type=int,
        default=100,
        help="Commit after this many updates",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    """Entry point for refreshing enrichment payloads in-place."""
    args = parse_args(argv)

    resolved = {
        "vt_api": args.vt_api or os.getenv("VT_API_KEY"),
        "dshield_email": args.dshield_email or os.getenv("DSHIELD_EMAIL"),
        "urlhaus_api": args.urlhaus_api or os.getenv("URLHAUS_API_KEY"),
        "spur_api": args.spur_api or os.getenv("SPUR_API_KEY"),
    }
    if not any(resolved.values()):
        creds = load_sensor_credentials(args.sensors_file, args.sensor_index)
        resolved.update({k: v for k, v in creds.items() if v})
    else:
        # For any missing individual credential, fill from sensors file if available
        try:
            creds = load_sensor_credentials(args.sensors_file, args.sensor_index)
            for key in ("vt_api", "dshield_email", "urlhaus_api", "spur_api"):
                if not resolved.get(key):
                    resolved[key] = creds.get(key)
        except Exception:
            pass

    cache_manager = EnrichmentCacheManager(args.cache_dir)
    service = EnrichmentService(
        cache_dir=args.cache_dir,
        vt_api=resolved.get("vt_api"),
        dshield_email=resolved.get("dshield_email"),
        urlhaus_api=resolved.get("urlhaus_api"),
        spur_api=resolved.get("spur_api"),
        cache_manager=cache_manager,
    )

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        session_limit = args.sessions if args.sessions >= 0 else 0
        file_limit = args.files if args.files >= 0 else 0

        if file_limit != 0 and not table_exists(conn, "files"):
            print("Files table not found; skipping file enrichment refresh")
            file_limit = 0

        session_count = 0
        file_count = 0
        last_commit = time.time()

        for session_id, src_ip in iter_sessions(conn, session_limit):
            session_count += 1
            result = service.enrich_session(session_id, src_ip)
            enrichment = result.get("enrichment", {}) if isinstance(result, dict) else {}
            flags = service.get_session_flags(result)
            update_session(conn, session_id, enrichment, flags)
            if session_count % args.commit_interval == 0:
                conn.commit()
                print(f"[sessions] committed {session_count} rows (elapsed {time.time() - last_commit:.1f}s)")
                last_commit = time.time()
            if session_limit > 0 and session_count >= session_limit:
                break

        if session_count % args.commit_interval:
            conn.commit()
            print(f"[sessions] committed tail {session_count % args.commit_interval}")

        vt_api_key = resolved.get("vt_api")
        if file_limit != 0 and vt_api_key:
            for file_hash, filename, session_id in iter_files(conn, file_limit):
                file_count += 1
                result = service.enrich_file(file_hash, filename or file_hash)
                enrichment = result.get("enrichment", {}) if isinstance(result, dict) else {}
                update_file(conn, file_hash, enrichment)
                if file_count % args.commit_interval == 0:
                    conn.commit()
                    print(f"[files] committed {file_count} rows (elapsed {time.time() - last_commit:.1f}s)")
                    last_commit = time.time()
                if file_limit > 0 and file_count >= file_limit:
                    break
            if file_count % args.commit_interval:
                conn.commit()
                print(f"[files] committed tail {file_count % args.commit_interval}")
        elif file_limit != 0:
            print("No VirusTotal API key available; skipping file enrichment refresh")

        print(
            json.dumps(
                {
                    "sessions_updated": session_count,
                    "files_updated": file_count,
                    "cache_snapshot": cache_manager.snapshot(),
                },
                indent=2,
            )
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
SENSORS_FILE_DEFAULT = PROJECT_ROOT / "sensors.toml"
