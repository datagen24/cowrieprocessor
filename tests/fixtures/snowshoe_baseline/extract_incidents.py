#!/usr/bin/env python3
"""Extract labeled attack incidents from production database.

This script queries the cowrieprocessor database to identify and extract
candidate attack incidents for the snowshoe baseline dataset. It generates
both session data JSON and metadata templates for manual review.

Usage:
    # Extract credential stuffing attacks from last 90 days
    uv run python extract_incidents.py --category credential_stuffing --days 90 --limit 5

    # Extract all categories with default settings
    uv run python extract_incidents.py --all-categories --limit 20

    # Use specific database
    uv run python extract_incidents.py --db "postgresql://..." --category targeted_attacks
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from cowrieprocessor.db.models import RawEvent, SessionSummary
from cowrieprocessor.utils.secrets import resolve_secret

# Category-specific SQL queries
QUERY_TEMPLATES = {
    "credential_stuffing": """
        SELECT
            DATE(first_event_at) as attack_date,
            COUNT(DISTINCT enrichment->>'src_ip') as ip_count,
            COUNT(*) as session_count,
            MIN(first_event_at) as window_start,
            MAX(last_event_at) as window_end,
            SUM(login_attempts) as total_attempts,
            ARRAY_AGG(DISTINCT session_id) as session_ids
        FROM session_summaries
        WHERE first_event_at >= :start_date
            AND login_attempts > 0
        GROUP BY DATE(first_event_at)
        HAVING COUNT(DISTINCT enrichment->>'src_ip') BETWEEN :min_ips AND :max_ips
            AND COUNT(*) >= :min_sessions
        ORDER BY attack_date DESC
        LIMIT :limit
    """,
    "targeted_attacks": """
        SELECT
            DATE(first_event_at) as attack_date,
            COUNT(DISTINCT enrichment->>'src_ip') as ip_count,
            COUNT(*) as session_count,
            MIN(first_event_at) as window_start,
            MAX(last_event_at) as window_end,
            SUM(login_attempts) as total_attempts,
            ARRAY_AGG(DISTINCT session_id) as session_ids
        FROM session_summaries
        WHERE first_event_at >= :start_date
            AND login_attempts > 3
            AND command_count > 5
        GROUP BY DATE(first_event_at)
        HAVING COUNT(DISTINCT enrichment->>'src_ip') BETWEEN :min_ips AND :max_ips
            AND COUNT(*) >= :min_sessions
        ORDER BY attack_date DESC
        LIMIT :limit
    """,
    "hybrid_attacks": """
        SELECT
            DATE(first_event_at) as attack_date,
            COUNT(DISTINCT enrichment->>'src_ip') as ip_count,
            COUNT(*) as session_count,
            MIN(first_event_at) as window_start,
            MAX(last_event_at) as window_end,
            SUM(login_attempts) as total_attempts,
            ARRAY_AGG(DISTINCT session_id) as session_ids
        FROM session_summaries
        WHERE first_event_at >= :start_date
            AND login_attempts > 0
            AND (vt_flagged = true OR dshield_flagged = true)
        GROUP BY DATE(first_event_at)
        HAVING COUNT(DISTINCT enrichment->>'src_ip') BETWEEN :min_ips AND :max_ips
            AND COUNT(*) >= :min_sessions
        ORDER BY attack_date DESC
        LIMIT :limit
    """,
    "legitimate_traffic": """
        SELECT
            DATE(first_event_at) as attack_date,
            COUNT(DISTINCT enrichment->>'src_ip') as ip_count,
            COUNT(*) as session_count,
            MIN(first_event_at) as window_start,
            MAX(last_event_at) as window_end,
            SUM(login_attempts) as total_attempts,
            ARRAY_AGG(DISTINCT session_id) as session_ids
        FROM session_summaries
        WHERE first_event_at >= :start_date
            AND login_attempts <= 3
            AND command_count <= 5
            AND vt_flagged = false
            AND dshield_flagged = false
        GROUP BY DATE(first_event_at)
        HAVING COUNT(DISTINCT enrichment->>'src_ip') <= :max_ips
            AND COUNT(*) <= :max_sessions
        ORDER BY attack_date DESC
        LIMIT :limit
    """,
}

# Category-specific parameters
QUERY_PARAMS = {
    "credential_stuffing": {
        "min_ips": 50,
        "max_ips": 200,
        "min_sessions": 100,
        "max_sessions": 10000,
    },
    "targeted_attacks": {
        "min_ips": 10,
        "max_ips": 30,
        "min_sessions": 20,
        "max_sessions": 200,
    },
    "hybrid_attacks": {
        "min_ips": 20,
        "max_ips": 100,
        "min_sessions": 50,
        "max_sessions": 500,
    },
    "legitimate_traffic": {
        "min_ips": 1,
        "max_ips": 10,
        "min_sessions": 1,
        "max_sessions": 20,
    },
}


def extract_session_data(session_obj: Session, session_ids: list[str]) -> dict[str, Any]:
    """Extract full session data including events.

    Args:
        session_obj: SQLAlchemy session
        session_ids: List of session IDs to extract

    Returns:
        Dictionary with sessions and events
    """
    # Get session summaries
    sessions_query = select(SessionSummary).where(SessionSummary.session_id.in_(session_ids))
    sessions = session_obj.execute(sessions_query).scalars().all()

    # Get raw events for these sessions
    events_query = select(RawEvent).where(RawEvent.session_id.in_(session_ids)).order_by(RawEvent.event_timestamp)
    events = session_obj.execute(events_query).scalars().all()

    # Convert to dictionaries
    session_data = {
        "sessions": [
            {
                "session_id": s.session_id,
                "first_event_at": s.first_event_at.isoformat() if s.first_event_at else None,
                "last_event_at": s.last_event_at.isoformat() if s.last_event_at else None,
                "event_count": s.event_count,
                "command_count": s.command_count,
                "file_downloads": s.file_downloads,
                "login_attempts": s.login_attempts,
                "vt_flagged": s.vt_flagged,
                "dshield_flagged": s.dshield_flagged,
                "enrichment": s.enrichment,
            }
            for s in sessions
        ],
        "events": [
            {
                "id": e.id,
                "session_id": e.session_id,
                "event_type": e.event_type,
                "event_timestamp": e.event_timestamp.isoformat() if e.event_timestamp else None,
                "payload": e.payload,
            }
            for e in events
        ],
    }

    return session_data


def create_metadata_template(
    category: str,
    attack_date: str,
    ip_count: int,
    session_count: int,
    window_start: str,
    window_end: str,
    incident_number: int,
) -> dict[str, Any]:
    """Create metadata template for manual review.

    Args:
        category: Attack category
        attack_date: Date of attack (YYYY-MM-DD)
        ip_count: Number of unique IPs
        session_count: Number of sessions
        window_start: Start timestamp
        window_end: End timestamp
        incident_number: Incident number in category

    Returns:
        Metadata dictionary template
    """
    date_str = attack_date.replace("-", "")
    incident_id = f"{category}_{incident_number:03d}_{date_str}"

    # Default characteristics based on category
    default_chars = {
        "credential_stuffing": {
            "password_reuse": True,
            "username_reuse": False,
            "geographic_spread": "global",
            "temporal_pattern": "burst",
            "command_similarity": "high",
        },
        "targeted_attacks": {
            "password_reuse": False,
            "username_reuse": True,
            "geographic_spread": "regional",
            "temporal_pattern": "sustained",
            "command_similarity": "medium",
        },
        "hybrid_attacks": {
            "password_reuse": True,
            "username_reuse": True,
            "geographic_spread": "global",
            "temporal_pattern": "mixed",
            "command_similarity": "medium",
        },
        "legitimate_traffic": {
            "password_reuse": False,
            "username_reuse": False,
            "geographic_spread": "local",
            "temporal_pattern": "sporadic",
            "command_similarity": "none",
        },
    }

    # Default labels
    default_labels = {
        "credential_stuffing": "snowshoe_spam",
        "targeted_attacks": "targeted_attack",
        "hybrid_attacks": "hybrid",
        "legitimate_traffic": "legitimate_traffic",
    }

    metadata = {
        "incident_id": incident_id,
        "category": category,
        "date_range": {
            "start": window_start,
            "end": window_end,
        },
        "ip_count": ip_count,
        "session_count": session_count,
        "attack_characteristics": default_chars.get(category, {}),
        "ground_truth_label": default_labels.get(category, "unknown"),
        "confidence": "medium",  # Requires manual review
        "reviewer": "automated_extraction",
        "review_date": datetime.now(timezone.utc).date().isoformat(),
        "notes": "⚠️ REQUIRES MANUAL REVIEW - Automatically extracted based on heuristics",
        "enrichment_coverage": {
            "virustotal": 0.0,
            "dshield": 0.0,
            "hibp": 0.0,
        },
    }

    return metadata


def extract_category_incidents(
    db_url: str,
    category: str,
    days: int,
    limit: int,
    output_dir: Path,
) -> int:
    """Extract incidents for a specific category.

    Args:
        db_url: Database connection URL
        category: Category to extract
        days: Number of days to look back
        limit: Maximum incidents to extract
        output_dir: Output directory for category

    Returns:
        Number of incidents extracted
    """
    print(f"\n{'=' * 60}")
    print(f"Extracting {category} incidents")
    print(f"{'=' * 60}")

    engine = create_engine(db_url)
    start_date = datetime.now(timezone.utc) - timedelta(days=days)

    # Get query template and parameters
    query_template = QUERY_TEMPLATES.get(category)
    if not query_template:
        print(f"⚠️  No query template for category: {category}")
        return 0

    params = QUERY_PARAMS.get(category, {})
    params.update({"start_date": start_date, "limit": limit})

    with Session(engine) as session_obj:
        # Execute query to find candidate incidents
        result = session_obj.execute(text(query_template), params)
        incidents = result.fetchall()

        if not incidents:
            print(f"⚠️  No incidents found for {category}")
            return 0

        print(f"Found {len(incidents)} candidate incidents")

        # Extract each incident
        for idx, incident in enumerate(incidents, start=1):
            attack_date = (
                incident.attack_date.isoformat()
                if hasattr(incident.attack_date, "isoformat")
                else str(incident.attack_date)
            )
            date_str = attack_date.replace("-", "")
            incident_id = f"{category}_{idx:03d}_{date_str}"

            print(f"\n  [{idx}/{len(incidents)}] {incident_id}")
            print(f"    IPs: {incident.ip_count}, Sessions: {incident.session_count}")

            # Extract session data
            session_data = extract_session_data(session_obj, incident.session_ids)

            # Save session data
            data_file = output_dir / f"{incident_id}_data.json"
            with open(data_file, "w") as f:
                json.dump(session_data, f, indent=2, default=str)
            print(f"    ✅ Saved session data: {data_file.name}")

            # Create metadata template
            metadata = create_metadata_template(
                category=category,
                attack_date=attack_date,
                ip_count=incident.ip_count,
                session_count=incident.session_count,
                window_start=incident.window_start.isoformat(),  # type: ignore[union-attr]
                window_end=incident.window_end.isoformat(),  # type: ignore[union-attr]
                incident_number=idx,
            )

            # Save metadata
            metadata_file = output_dir / f"{incident_id}_metadata.json"
            with open(metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)
            print(f"    ✅ Saved metadata: {metadata_file.name}")

    return len(incidents)


def main() -> int:
    """Main extraction workflow.

    Returns:
        Exit code (0 = success, 1 = errors)
    """
    parser = argparse.ArgumentParser(description="Extract labeled attack incidents from cowrieprocessor database")
    parser.add_argument(
        "--db",
        default="env:DATABASE_URL",
        help="Database URL (supports env:, file:, op:// notation)",
    )
    parser.add_argument(
        "--category",
        choices=[
            "credential_stuffing",
            "targeted_attacks",
            "hybrid_attacks",
            "legitimate_traffic",
        ],
        help="Attack category to extract",
    )
    parser.add_argument(
        "--all-categories",
        action="store_true",
        help="Extract incidents for all categories",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Number of days to look back (default: 90)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum incidents per category (default: 5)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output directory (default: current directory)",
    )

    args = parser.parse_args()

    # Resolve database URL
    db_url = resolve_secret(args.db)

    # Determine categories to extract
    if args.all_categories:
        categories = ["credential_stuffing", "targeted_attacks", "hybrid_attacks", "legitimate_traffic"]
    elif args.category:
        categories = [args.category]
    else:
        print("❌ Must specify --category or --all-categories")
        return 1

    # Determine output directory
    if args.output:
        base_dir = args.output
    else:
        base_dir = Path(__file__).parent

    # Extract incidents for each category
    total_extracted = 0
    for category in categories:
        output_dir = base_dir / category
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            count = extract_category_incidents(
                db_url=db_url,
                category=category,
                days=args.days,
                limit=args.limit,
                output_dir=output_dir,
            )
            total_extracted += count
        except Exception as e:
            print(f"\n❌ Error extracting {category}: {e}")
            import traceback

            traceback.print_exc()

    # Summary
    print(f"\n{'=' * 60}")
    print(f"Extraction complete: {total_extracted} incidents extracted")
    print(f"{'=' * 60}")
    print("\n⚠️  IMPORTANT: Review and update metadata files!")
    print("    - Verify attack characteristics")
    print("    - Confirm ground truth labels")
    print("    - Update confidence levels")
    print("    - Add detailed notes")
    print(f"\nRun validation: uv run python {Path(__file__).parent}/validate_metadata.py")

    return 0


if __name__ == "__main__":
    sys.exit(main())
