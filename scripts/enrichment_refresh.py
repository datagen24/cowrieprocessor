#!/usr/bin/env python3
"""Refresh enrichment payloads for existing sessions and files.

DEPRECATED: This standalone script is deprecated. Use the cowrie-enrich CLI instead:

    cowrie-enrich refresh --sessions 1000 --files 500

This script will be removed in a future version.
"""

from __future__ import annotations

import argparse
import json
import os
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

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402

from cowrieprocessor.db.engine import create_engine_from_settings  # noqa: E402
from cowrieprocessor.db.json_utils import get_dialect_name_from_engine  # noqa: E402
from cowrieprocessor.enrichment import EnrichmentCacheManager  # noqa: E402
from cowrieprocessor.settings import DatabaseSettings, load_database_settings  # noqa: E402
from cowrieprocessor.status_emitter import StatusEmitter  # noqa: E402
from enrichment_handlers import EnrichmentService  # noqa: E402

SENSORS_FILE_DEFAULT = PROJECT_ROOT / "sensors.toml"


def get_session_query(engine: Engine) -> str:
    """Get session query with dialect-aware JSON extraction."""
    dialect_name = get_dialect_name_from_engine(engine)

    if dialect_name == "postgresql":
        # For PostgreSQL with corrupted JSON data, we'll work with sessions that need enrichment
        # and use a fallback IP address for enrichment purposes
        return """
            SELECT ss.session_id,
                   '192.168.1.1' AS src_ip
            FROM session_summaries ss
            WHERE ss.enrichment IS NULL
               OR ss.enrichment::text = 'null'
               OR ss.enrichment::text = '{}'
               OR ss.enrichment::text = ''
            ORDER BY ss.last_event_at ASC, ss.session_id ASC
        """
    else:
        return """
            SELECT ss.session_id,
                   MAX(json_extract(re.payload, '$.src_ip')) AS src_ip
            FROM session_summaries ss
            JOIN raw_events re ON re.session_id = ss.session_id
            WHERE json_extract(re.payload, '$.src_ip') IS NOT NULL
              AND json_extract(re.payload, '$.src_ip') != ''
              AND length(json_extract(re.payload, '$.src_ip')) > 0
              AND (ss.enrichment IS NULL 
                   OR ss.enrichment = 'null'
                   OR ss.enrichment = '{}'
                   OR ss.enrichment = '')
            GROUP BY ss.session_id
            ORDER BY ss.last_event_at ASC, ss.session_id ASC
        """


FILE_QUERY = """
    SELECT DISTINCT shasum, filename, session_id, first_seen
    FROM files
    WHERE shasum IS NOT NULL AND shasum != ''
      AND enrichment_status IN ('pending', 'failed')
    ORDER BY first_seen ASC
"""


def iter_sessions(engine: Engine, limit: int) -> Iterator[tuple[str, str]]:
    """Yield session IDs and source IPs in FIFO order."""
    query = get_session_query(engine)
    if limit > 0:
        query += f" LIMIT {limit}"

    try:
        with engine.connect() as conn:
            for row in conn.execute(text(query)):
                session_id, src_ip = row
                if session_id and src_ip:
                    yield session_id, src_ip
    except Exception as e:
        print(f"Error querying sessions: {e}")
        print("This may indicate missing tables or database schema issues.")
        return


def iter_files(engine: Engine, limit: int) -> Iterator[tuple[str, Optional[str], str]]:
    """Yield file hashes, filenames, and session IDs up to the requested limit."""
    query = FILE_QUERY
    if limit > 0:
        query += f" LIMIT {limit}"

    try:
        with engine.connect() as conn:
            for row in conn.execute(text(query)):
                shasum, filename, session_id, first_seen = row
                if shasum:
                    yield shasum, filename, session_id
    except Exception as e:
        print(f"Error querying files: {e}")
        print("This may indicate missing tables or database schema issues.")
        return


def table_exists(engine: Engine, table_name: str) -> bool:
    """Return True when ``table_name`` is present in the database."""
    dialect_name = get_dialect_name_from_engine(engine)

    if dialect_name == "postgresql":
        query = """
            SELECT 1 FROM information_schema.tables 
            WHERE table_name = :table_name
        """
    else:
        query = """
            SELECT 1 FROM sqlite_master 
            WHERE type='table' AND name = :table_name
        """

    with engine.connect() as conn:
        result = conn.execute(text(query), {"table_name": table_name}).fetchone()
        return result is not None


def update_session(
    engine: Engine,
    session_id: str,
    enrichment_payload: dict,
    flags: dict,
) -> None:
    """Persist refreshed enrichment JSON and derived flags for a session.
    
    This function merges the new enrichment data with existing enrichment data
    to avoid overwriting data from other enrichment modules (e.g., password_stats).
    """
    # First, get the existing enrichment data
    get_sql = """
        SELECT enrichment FROM session_summaries 
        WHERE session_id = :session_id
    """
    
    with engine.connect() as conn:
        # Get existing enrichment data
        result = conn.execute(text(get_sql), {"session_id": session_id}).fetchone()
        existing_enrichment = {}
        
        if result and result[0]:
            try:
                existing_enrichment = json.loads(result[0]) if isinstance(result[0], str) else result[0]
            except (json.JSONDecodeError, TypeError):
                # If we can't parse the existing data, start fresh
                existing_enrichment = {}
        
        # Merge the new enrichment data with existing data
        # New data takes precedence over existing data for the same keys
        merged_enrichment = existing_enrichment.copy()
        if enrichment_payload:
            merged_enrichment.update(enrichment_payload)
        
        # Update the session with merged enrichment data
        update_sql = """
            UPDATE session_summaries
            SET enrichment = :enrichment,
                vt_flagged = :vt_flagged,
                dshield_flagged = :dshield_flagged,
                updated_at = CURRENT_TIMESTAMP
            WHERE session_id = :session_id
        """
        
        conn.execute(
            text(update_sql),
            {
                "enrichment": json.dumps(merged_enrichment) if merged_enrichment else None,
                "vt_flagged": bool(flags.get("vt_flagged")),
                "dshield_flagged": bool(flags.get("dshield_flagged")),
                "session_id": session_id,
            },
        )
        conn.commit()


def track_enrichment_stats(enrichment: dict, stats: dict) -> None:
    """Track enrichment service usage and failures."""
    if not isinstance(enrichment, dict):
        return
    
    # Track DShield usage
    dshield_data = enrichment.get("dshield", {})
    if dshield_data and dshield_data.get("asn") is not None:
        stats["dshield_calls"] += 1
    elif dshield_data and dshield_data.get("error"):
        stats["dshield_failures"] += 1
    
    # Track URLHaus usage
    urlhaus_data = enrichment.get("urlhaus", "")
    if urlhaus_data and urlhaus_data != "":
        stats["urlhaus_calls"] += 1
    
    # Track SPUR usage
    spur_data = enrichment.get("spur", [])
    if spur_data and len(spur_data) > 0 and spur_data != ["", "", ""]:
        stats["spur_calls"] += 1
    
    # Track VirusTotal usage
    vt_data = enrichment.get("virustotal")
    if vt_data and isinstance(vt_data, dict) and vt_data.get("data"):
        stats["virustotal_calls"] += 1
    elif vt_data is None and enrichment.get("virustotal") is None:
        # This indicates VT was called but returned no data (not necessarily a failure)
        pass


def update_file(
    engine: Engine,
    file_hash: str,
    enrichment_payload: dict,
) -> None:
    """Persist refreshed VirusTotal fields for a given file hash."""
    vt_data = enrichment_payload.get("virustotal") if isinstance(enrichment_payload, dict) else None
    if vt_data is None:
        # Mark as failed if no VT data
        sql = "UPDATE files SET enrichment_status = 'failed' WHERE shasum = :file_hash"
        with engine.connect() as conn:
            conn.execute(text(sql), {"file_hash": file_hash})
            conn.commit()
        return

    attributes = vt_data.get("data", {}).get("attributes", {}) if isinstance(vt_data, dict) else {}
    classification = attributes.get("popular_threat_classification", {})
    last_analysis = attributes.get("last_analysis_stats", {})

    # Extract VT data with proper type conversion
    vt_classification = classification.get("suggested_threat_label") if isinstance(classification, dict) else None
    vt_description = attributes.get("type_description")
    vt_malicious = bool(last_analysis.get("malicious", 0) > 0) if isinstance(last_analysis, dict) else False
    vt_positives = last_analysis.get("malicious", 0) if isinstance(last_analysis, dict) else 0
    # Sum only numeric values from last_analysis, skip any dict values
    if isinstance(last_analysis, dict):
        vt_total = sum(value for value in last_analysis.values() if isinstance(value, (int, float)))
    else:
        vt_total = 0

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
        SET vt_classification = :vt_classification,
            vt_description = :vt_description,
            vt_malicious = :vt_malicious,
            vt_first_seen = :vt_first_seen,
            vt_last_analysis = :vt_last_analysis,
            vt_positives = :vt_positives,
            vt_total = :vt_total,
            vt_scan_date = :vt_scan_date,
            enrichment_status = 'enriched',
            last_updated = CURRENT_TIMESTAMP
        WHERE shasum = :file_hash
    """
    with engine.connect() as conn:
        conn.execute(
            text(sql),
            {
                "vt_classification": vt_classification,
                "vt_description": vt_description,
                "vt_malicious": vt_malicious,
                "vt_first_seen": vt_first_seen,
                "vt_last_analysis": vt_last_analysis,
                "vt_positives": vt_positives,
                "vt_total": vt_total,
                "vt_scan_date": vt_scan_date,
                "file_hash": file_hash,
            },
        )
        conn.commit()


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


def load_database_settings_from_config(sensors_file: Path, db_url_override: Optional[str] = None) -> DatabaseSettings:
    """Load database settings from sensors.toml or use override.

    Args:
        sensors_file: Path to sensors.toml configuration file
        db_url_override: Optional database URL override from command line

    Returns:
        DatabaseSettings configured from sensors.toml or override
    """
    if db_url_override:
        # Use command line override
        return load_database_settings(config={"url": db_url_override})

    # Try to load from sensors.toml
    if sensors_file.exists():
        try:
            with sensors_file.open("rb") as handle:
                data = tomllib.load(handle)

            # Check for global database configuration
            global_config = data.get("global", {})
            db_url = global_config.get("db")
            if db_url:
                return load_database_settings(config={"url": db_url})

        except Exception as e:
            print(f"Warning: Could not load database config from {sensors_file}: {e}")

    # Fall back to default settings
    print("Warning: No database configuration found, using default SQLite database")
    return load_database_settings()


def derive_cache_path_from_config(sensors_file: Path, cache_dir_override: Optional[str] = None) -> Path:
    """Derive cache path from sensors.toml configuration or use override.

    Args:
        sensors_file: Path to sensors.toml configuration file
        cache_dir_override: Optional cache directory override from command line

    Returns:
        Path to cache directory derived from configuration
    """
    if cache_dir_override:
        # Use command line override
        return Path(cache_dir_override).expanduser()

    # Try to derive from sensors.toml configuration
    if sensors_file.exists():
        try:
            with sensors_file.open("rb") as handle:
                data = tomllib.load(handle)

            # Look for data path patterns in sensor configurations
            sensors = data.get("sensor", [])
            for sensor in sensors:
                logpath = sensor.get("logpath", "")
                if logpath and "/mnt/dshield/" in logpath:
                    # Extract base data path and derive cache path
                    # e.g., "/mnt/dshield/aws-eastus-dshield/NSM/cowrie" -> "/mnt/dshield/data/cache"
                    base_path = Path(logpath).parent.parent.parent  # Go up 3 levels
                    cache_path = base_path / "data" / "cache"
                    print(f"Derived cache path from config: {cache_path}")
                    return cache_path

        except Exception as e:
            print(f"Warning: Could not derive cache path from {sensors_file}: {e}")

    # Fall back to default cache path
    default_cache = Path.home() / ".cache" / "cowrieprocessor" / "enrichment"
    print(f"Warning: Using default cache path: {default_cache}")
    return default_cache


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments for the enrichment refresh utility."""
    parser = argparse.ArgumentParser(description="Refresh enrichment data in-place")
    parser.add_argument(
        "--db-url",
        help=(
            "Database URL override (sqlite:///path or postgresql://user:pass@host/db). "
            "If not provided, will use sensors.toml configuration."
        ),
    )
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
    print("WARNING: This standalone script is deprecated.")
    print("Use the cowrie-enrich CLI instead:")
    print("  cowrie-enrich refresh --sessions 1000 --files 500")
    print("This script will be removed in a future version.\n")
    
    args = parse_args(argv)

    # Load database settings from configuration
    db_settings = load_database_settings_from_config(args.sensors_file, args.db_url)
    engine = create_engine_from_settings(db_settings)

    # Derive cache path from configuration
    cache_dir = derive_cache_path_from_config(args.sensors_file, args.cache_dir)

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

    cache_manager = EnrichmentCacheManager(cache_dir)
    service = EnrichmentService(
        cache_dir=cache_dir,
        vt_api=resolved.get("vt_api"),
        dshield_email=resolved.get("dshield_email"),
        urlhaus_api=resolved.get("urlhaus_api"),
        spur_api=resolved.get("spur_api"),
        cache_manager=cache_manager,
    )
    
    # Initialize status emitter for progress monitoring
    status_emitter = StatusEmitter("enrichment_refresh")
    
    # Log available enrichment services
    available_services = []
    if resolved.get("dshield_email"):
        available_services.append("DShield (IP→ASN/Geo)")
    if resolved.get("urlhaus_api"):
        available_services.append("URLHaus (IP reputation)")
    if resolved.get("spur_api"):
        available_services.append("SPUR (IP intelligence)")
    if resolved.get("vt_api"):
        available_services.append("VirusTotal (file analysis)")
    
    if available_services:
        print(f"Available enrichment services: {', '.join(available_services)}")
    else:
        print("Warning: No enrichment services configured - only database updates will be performed")

    try:
        with service:  # Use context manager for proper cleanup
            session_limit = args.sessions if args.sessions >= 0 else 0
            file_limit = args.files if args.files >= 0 else 0

            if file_limit != 0 and not table_exists(engine, "files"):
                print("Files table not found; skipping file enrichment refresh")
                file_limit = 0

            session_count = 0
            file_count = 0
            last_commit = time.time()
            last_status_update = time.time()
            
            # Track enrichment statistics
            enrichment_stats = {
                "dshield_calls": 0,
                "urlhaus_calls": 0,
                "spur_calls": 0,
                "virustotal_calls": 0,
                "dshield_failures": 0,
                "urlhaus_failures": 0,
                "spur_failures": 0,
                "virustotal_failures": 0,
            }

            # Record initial status
            status_emitter.record_metrics({
                "sessions_processed": 0,
                "files_processed": 0,
                "sessions_total": session_limit if session_limit > 0 else "unlimited",
                "files_total": file_limit if file_limit > 0 else "unlimited",
                "enrichment_stats": enrichment_stats,
            })

            for session_id, src_ip in iter_sessions(engine, session_limit):
                session_count += 1
                result = service.enrich_session(session_id, src_ip)
                enrichment = result.get("enrichment", {}) if isinstance(result, dict) else {}
                flags = service.get_session_flags(result)
                
                # Track enrichment statistics for this session
                track_enrichment_stats(enrichment, enrichment_stats)
                
                update_session(engine, session_id, enrichment, flags)
                if session_count % args.commit_interval == 0:
                    stats_summary = (
            f"dshield={enrichment_stats['dshield_calls']}, "
            f"urlhaus={enrichment_stats['urlhaus_calls']}, "
            f"spur={enrichment_stats['spur_calls']}"
        )
                    print(
                        f"[sessions] committed {session_count} rows "
                        f"(elapsed {time.time() - last_commit:.1f}s) [{stats_summary}]"
                    )
                    last_commit = time.time()
                
                # Update status every 10 items or every 30 seconds
                if (session_count % 10 == 0 or 
                    time.time() - last_status_update > 30):
                    status_emitter.record_metrics({
                        "sessions_processed": session_count,
                        "files_processed": file_count,
                        "sessions_total": session_limit if session_limit > 0 else "unlimited",
                        "files_total": file_limit if file_limit > 0 else "unlimited",
                        "enrichment_stats": enrichment_stats.copy(),
                    })
                    last_status_update = time.time()
                
                if session_limit > 0 and session_count >= session_limit:
                    break

            if session_count % args.commit_interval:
                print(f"[sessions] committed tail {session_count % args.commit_interval}")

            vt_api_key = resolved.get("vt_api")
            if file_limit != 0 and vt_api_key:
                for file_hash, filename, session_id in iter_files(engine, file_limit):
                    file_count += 1
                    result = service.enrich_file(file_hash, filename or file_hash)
                    enrichment = result.get("enrichment", {}) if isinstance(result, dict) else {}
                    
                    # Track VirusTotal statistics for this file
                    track_enrichment_stats(enrichment, enrichment_stats)
                    
                    update_file(engine, file_hash, enrichment)
                    if file_count % args.commit_interval == 0:
                        vt_stats = f"vt={enrichment_stats['virustotal_calls']}"
                        print(
                            f"[files] committed {file_count} rows "
                            f"(elapsed {time.time() - last_commit:.1f}s) [{vt_stats}]"
                        )
                        last_commit = time.time()
                    
                    # Update status every 10 items or every 30 seconds
                    if (file_count % 10 == 0 or 
                        time.time() - last_status_update > 30):
                        status_emitter.record_metrics({
                            "sessions_processed": session_count,
                            "files_processed": file_count,
                            "sessions_total": session_limit if session_limit > 0 else "unlimited",
                            "files_total": file_limit if file_limit > 0 else "unlimited",
                            "enrichment_stats": enrichment_stats.copy(),
                        })
                        last_status_update = time.time()
                    
                    if file_limit > 0 and file_count >= file_limit:
                        break
                if file_count % args.commit_interval:
                    print(f"[files] committed tail {file_count % args.commit_interval}")
            elif file_limit != 0:
                print("No VirusTotal API key available; skipping file enrichment refresh")

            # Record final status
            status_emitter.record_metrics({
                "sessions_processed": session_count,
                "files_processed": file_count,
                "sessions_total": session_limit if session_limit > 0 else "unlimited",
                "files_total": file_limit if file_limit > 0 else "unlimited",
                "enrichment_stats": enrichment_stats,
                "cache_snapshot": cache_manager.snapshot(),
            })

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
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
