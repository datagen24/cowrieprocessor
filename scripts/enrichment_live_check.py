#!/usr/bin/env python3
"""Run live enrichment checks against real APIs for a small sample."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Optional, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError as exc:  # pragma: no cover - defensive
    raise RuntimeError("Python 3.11+ is required to run this script") from exc

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cowrieprocessor.db.json_utils import JSONAccessor, get_dialect_name_from_engine  # noqa: E402
from cowrieprocessor.enrichment import EnrichmentCacheManager  # noqa: E402
from enrichment_handlers import EnrichmentService  # noqa: E402

DEFAULT_DB = Path("/mnt/dshield/data/db/cowrieprocessor.sqlite")
DEFAULT_CACHE = Path("/mnt/dshield/data/cache")
SENSORS_FILE = Path("sensors.toml")


def load_sensor_credentials(sensor_index: int = 0) -> dict:
    """Fetch API credentials from sensors.toml for the given index."""
    if not SENSORS_FILE.exists():
        raise RuntimeError(f"Missing sensors file: {SENSORS_FILE}")
    with SENSORS_FILE.open("rb") as handle:
        data = tomllib.load(handle)

    sensors = data.get("sensor") or []
    if not sensors:
        raise RuntimeError("No sensors configured in sensors.toml")
    if sensor_index >= len(sensors):
        raise RuntimeError(f"Sensor index {sensor_index} out of range (have {len(sensors)})")
    sensor = sensors[sensor_index]

    creds = {
        "vt_api": sensor.get("vtapi"),
        "dshield_email": sensor.get("email"),
        "urlhaus_api": sensor.get("urlhausapi"),
        "spur_api": sensor.get("spurapi"),
    }
    return creds


def create_readonly_engine(db_url: str) -> Engine:
    """Create a read-only engine for the database."""
    if db_url.startswith("sqlite://"):
        # For SQLite, add read-only parameters
        if "?" in db_url:
            db_url += "&mode=ro&immutable=1"
        else:
            db_url += "?mode=ro&immutable=1"

    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    # Set read-only mode for SQLite
    if db_url.startswith("sqlite://"):
        try:

            @engine.event.listens_for(engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA query_only=1")
                cursor.close()
        except AttributeError:
            # Fallback for older SQLAlchemy versions
            pass

    return engine


def sample_sessions(engine: Engine, limit: int) -> Iterator[Tuple[str, str]]:
    """Yield session IDs and source IP tuples up to the requested limit."""
    dialect_name = get_dialect_name_from_engine(engine)

    if dialect_name == "postgresql":
        base_query = """
            SELECT session_id,
                   MAX(payload->>'src_ip') AS src_ip
            FROM raw_events
            WHERE payload->>'src_ip' IS NOT NULL
              AND payload->>'src_ip' != ''
            GROUP BY session_id
        """
    else:
        base_query = """
            SELECT session_id,
                   MAX(json_extract(payload, '$.src_ip')) AS src_ip
            FROM raw_events
            WHERE json_extract(payload, '$.src_ip') IS NOT NULL
              AND json_extract(payload, '$.src_ip') != ''
            GROUP BY session_id
        """

    if limit > 0:
        base_query += f" LIMIT {limit}"

    with engine.connect() as conn:
        for session_id, src_ip in conn.execute(text(base_query)):
            if src_ip:
                yield session_id, src_ip


def sample_file_hashes(engine: Engine, limit: int) -> Iterator[str]:
    """Yield file hashes extracted from raw_events up to the limit."""
    dialect_name = JSONAccessor.get_dialect_name_from_engine(engine)

    if dialect_name == "postgresql":
        base_query = """
            SELECT MAX(payload->>'shasum') AS shasum
            FROM raw_events
            WHERE payload->>'eventid' = 'cowrie.session.file_download'
              AND payload->>'shasum' IS NOT NULL
              AND payload->>'shasum' != ''
            GROUP BY payload->>'shasum'
        """
    else:
        base_query = """
            SELECT MAX(json_extract(payload, '$.shasum')) AS shasum
            FROM raw_events
            WHERE json_extract(payload, '$.eventid') = 'cowrie.session.file_download'
              AND json_extract(payload, '$.shasum') IS NOT NULL
              AND json_extract(payload, '$.shasum') != ''
            GROUP BY json_extract(payload, '$.shasum')
        """

    if limit > 0:
        base_query += f" LIMIT {limit}"

    with engine.connect() as conn:
        for (shasum,) in conn.execute(text(base_query)):
            if shasum:
                yield shasum


def summarise_session_enrichment(enrichment: Mapping[str, object] | None) -> dict:
    """Condense session-level enrichment payload into a printable summary."""
    summary: dict[str, object] = {}
    enrichment_dict = enrichment or {}
    dshield_raw = enrichment_dict.get("dshield") if isinstance(enrichment_dict, Mapping) else None
    dshield = dshield_raw if isinstance(dshield_raw, Mapping) else {}
    ip_info_raw = dshield.get("ip") if isinstance(dshield, Mapping) else None
    ip_info = ip_info_raw if isinstance(ip_info_raw, Mapping) else {}
    summary["dshield_asname"] = ip_info.get("asname")
    summary["dshield_country"] = ip_info.get("ascountry")
    summary["dshield_count"] = ip_info.get("count")

    urlhaus = enrichment_dict.get("urlhaus") if isinstance(enrichment_dict, Mapping) else None
    summary["urlhaus_tags"] = urlhaus if isinstance(urlhaus, str) else ""

    spur = enrichment_dict.get("spur") if isinstance(enrichment_dict, Mapping) else None
    if isinstance(spur, list) and len(spur) >= 4:
        summary["spur_infra"] = spur[3]
    else:
        summary["spur_infra"] = None
    return summary


def summarise_file_enrichment(enrichment: Mapping[str, object] | None) -> dict:
    """Extract key VirusTotal attributes for reporting."""
    enrichment_dict = enrichment or {}
    vt_raw = enrichment_dict.get("virustotal") if isinstance(enrichment_dict, Mapping) else None
    vt = vt_raw if isinstance(vt_raw, Mapping) else {}
    data_raw = vt.get("data") if isinstance(vt, Mapping) else None
    data = data_raw if isinstance(data_raw, Mapping) else {}
    attributes_raw = data.get("attributes") if isinstance(data, Mapping) else None
    attributes = attributes_raw if isinstance(attributes_raw, Mapping) else {}
    stats_raw = attributes.get("last_analysis_stats") if isinstance(attributes, Mapping) else None
    stats = stats_raw if isinstance(stats_raw, Mapping) else {}
    return {
        "label": attributes.get("popular_threat_classification", {}).get("suggested_threat_label")
        if isinstance(attributes.get("popular_threat_classification"), dict)
        else None,
        "malicious": stats.get("malicious") if isinstance(stats, dict) else None,
        "first_submission": attributes.get("first_submission_date") if isinstance(attributes, dict) else None,
    }


def run_enrichment(
    *,
    db_url: str,
    cache_dir: Path,
    sensor_index: int,
    session_limit: int,
    file_limit: int,
) -> None:
    """Execute enrichment lookups over the requested session/file sample."""
    creds = load_sensor_credentials(sensor_index)
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache_manager = EnrichmentCacheManager(cache_dir)
    service = EnrichmentService(
        cache_dir,
        vt_api=creds.get("vt_api"),
        dshield_email=creds.get("dshield_email"),
        urlhaus_api=creds.get("urlhaus_api"),
        spur_api=creds.get("spur_api"),
        cache_manager=cache_manager,
    )

    engine = create_readonly_engine(db_url)
    try:
        session_total = 0
        print("Fetching session/IP pairs...")
        for session_id, src_ip in sample_sessions(engine, session_limit):
            session_total += 1
            result = service.enrich_session(session_id, src_ip)
            summary = summarise_session_enrichment(result.get("enrichment", {}))
            if session_limit <= 0:
                if session_total <= 10 or session_total % 100 == 0:
                    print(
                        json.dumps(
                            {
                                "session": session_id,
                                "src_ip": src_ip,
                                "summary": summary,
                            }
                        )
                    )
            else:
                print(
                    json.dumps(
                        {
                            "session": session_id,
                            "src_ip": src_ip,
                            "summary": summary,
                        }
                    )
                )

        print(f"Processed {session_total} session/IP pairs")

        file_total = 0
        if (file_limit > 0 or file_limit == 0) and creds.get("vt_api"):
            for shasum in sample_file_hashes(engine, file_limit):
                file_total += 1
                result = service.enrich_file(shasum, shasum)
                summary = summarise_file_enrichment(result.get("enrichment", {}))
                if file_limit <= 0:
                    if file_total <= 10 or file_total % 100 == 0:
                        print(
                            json.dumps(
                                {
                                    "sha256": shasum,
                                    "summary": summary,
                                }
                            )
                        )
                else:
                    print(
                        json.dumps(
                            {
                                "sha256": shasum,
                                "summary": summary,
                            }
                        )
                    )

            print(f"Processed {file_total} file hashes")
        else:
            print("Skipping file hash enrichment (no VirusTotal API key or limit=0)")

        print("Cache stats:", cache_manager.snapshot())
    finally:
        engine.dispose()


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments for the live enrichment harness."""
    parser = argparse.ArgumentParser(description="Run live enrichment sample checks")
    parser.add_argument(
        "--db-url",
        default=f"sqlite:///{DEFAULT_DB}",
        help="Database URL (sqlite:///path or postgresql://user:pass@host/db)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE,
        help="Directory for enrichment cache files",
    )
    parser.add_argument(
        "--sensor-index",
        type=int,
        default=0,
        help="Index of the sensor entry in sensors.toml for API credentials",
    )
    parser.add_argument("--sessions", type=int, default=3, help="Number of sessions to sample")
    parser.add_argument("--files", type=int, default=1, help="Number of file hashes to sample")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    """Entrypoint for sampling live enrichment against the snapshot."""
    args = parse_args(list(argv) if argv is not None else None)
    try:
        run_enrichment(
            db_url=args.db_url,
            cache_dir=args.cache_dir,
            sensor_index=args.sensor_index,
            session_limit=args.sessions,
            file_limit=args.files,
        )
    except Exception as exc:  # pragma: no cover - operator feedback
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
