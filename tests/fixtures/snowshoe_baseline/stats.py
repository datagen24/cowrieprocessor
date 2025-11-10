#!/usr/bin/env python3
"""Generate summary statistics for the snowshoe baseline dataset.

This script analyzes all labeled incidents and produces comprehensive statistics
about the dataset composition, coverage, and quality metrics.

Usage:
    uv run python stats.py
    uv run python stats.py --verbose
    uv run python stats.py --export stats.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


def load_all_incidents(base_dir: Path) -> list[dict[str, Any]]:
    """Load all incidents from the dataset.

    Args:
        base_dir: Base directory containing category subdirectories

    Returns:
        List of dictionaries with 'metadata' and 'data' keys
    """
    categories = [
        "credential_stuffing",
        "targeted_attacks",
        "hybrid_attacks",
        "legitimate_traffic",
        "edge_cases",
    ]

    incidents = []

    for category in categories:
        category_dir = base_dir / category
        if not category_dir.exists():
            continue

        metadata_files = list(category_dir.glob("*_metadata.json"))
        for metadata_file in metadata_files:
            # Derive data filename
            incident_id = metadata_file.stem.replace("_metadata", "")
            data_file = category_dir / f"{incident_id}_data.json"

            try:
                with open(metadata_file) as f:
                    metadata = json.load(f)

                data = None
                if data_file.exists():
                    with open(data_file) as f:
                        data = json.load(f)

                incidents.append(
                    {
                        "incident_id": incident_id,
                        "category": category,
                        "metadata": metadata,
                        "data": data,
                    }
                )
            except Exception as e:
                print(f"⚠️  Error loading {metadata_file.name}: {e}", file=sys.stderr)

    return incidents


def calculate_statistics(incidents: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate comprehensive dataset statistics.

    Args:
        incidents: List of incident dictionaries

    Returns:
        Dictionary with statistics
    """
    if not incidents:
        return {"error": "No incidents found"}

    # Basic counts
    total_incidents = len(incidents)
    category_counts = Counter(inc["category"] for inc in incidents)
    label_counts = Counter(inc["metadata"]["ground_truth_label"] for inc in incidents)
    confidence_counts = Counter(inc["metadata"]["confidence"] for inc in incidents)

    # IP and session statistics
    ip_counts = [inc["metadata"]["ip_count"] for inc in incidents]
    session_counts = [inc["metadata"]["session_count"] for inc in incidents]

    # Date range analysis
    all_dates = []
    for inc in incidents:
        date_str = inc["metadata"]["date_range"]["start"]
        date_obj = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        all_dates.append(date_obj)

    if all_dates:
        min_date = min(all_dates)
        max_date = max(all_dates)
        date_span_days = (max_date - min_date).days
    else:
        min_date = max_date = None
        date_span_days = 0

    # Attack characteristics analysis
    characteristics: dict[str, Counter[str]] = defaultdict(Counter)
    for inc in incidents:
        chars = inc["metadata"]["attack_characteristics"]
        for key, value in chars.items():
            characteristics[key][str(value)] += 1

    # Enrichment coverage
    enrichment_stats: dict[str, list[float]] = {
        "virustotal": [],
        "dshield": [],
        "hibp": [],
    }
    for inc in incidents:
        coverage = inc["metadata"].get("enrichment_coverage", {})
        for service, value in coverage.items():
            if service in enrichment_stats:
                enrichment_stats[service].append(value)

    # Calculate averages
    avg_enrichment = {}
    for service, values in enrichment_stats.items():
        if values:
            avg_enrichment[service] = sum(values) / len(values)
        else:
            avg_enrichment[service] = 0.0

    # Reviewer analysis
    reviewer_counts = Counter(inc["metadata"]["reviewer"] for inc in incidents)

    # Session/event data statistics (if available)
    data_stats = {
        "incidents_with_data": sum(1 for inc in incidents if inc["data"] is not None),
        "total_sessions": 0,
        "total_events": 0,
    }

    for inc in incidents:
        if inc["data"]:
            data_stats["total_sessions"] += len(inc["data"].get("sessions", []))
            data_stats["total_events"] += len(inc["data"].get("events", []))

    return {
        "summary": {
            "total_incidents": total_incidents,
            "categories": dict(category_counts),
            "labels": dict(label_counts),
            "confidence": dict(confidence_counts),
        },
        "ip_statistics": {
            "min": min(ip_counts) if ip_counts else 0,
            "max": max(ip_counts) if ip_counts else 0,
            "mean": sum(ip_counts) / len(ip_counts) if ip_counts else 0,
            "median": sorted(ip_counts)[len(ip_counts) // 2] if ip_counts else 0,
        },
        "session_statistics": {
            "min": min(session_counts) if session_counts else 0,
            "max": max(session_counts) if session_counts else 0,
            "mean": sum(session_counts) / len(session_counts) if session_counts else 0,
            "median": sorted(session_counts)[len(session_counts) // 2] if session_counts else 0,
        },
        "temporal_coverage": {
            "start_date": min_date.isoformat() if min_date else None,
            "end_date": max_date.isoformat() if max_date else None,
            "span_days": date_span_days,
        },
        "attack_characteristics": dict(characteristics),
        "enrichment_coverage": {
            "average": avg_enrichment,
            "by_service": {
                service: {
                    "min": min(values) if values else 0,
                    "max": max(values) if values else 0,
                    "mean": avg_enrichment[service],
                }
                for service, values in enrichment_stats.items()
            },
        },
        "reviewers": dict(reviewer_counts),
        "data_availability": data_stats,
    }


def print_statistics(stats: dict[str, Any], verbose: bool = False) -> None:
    """Print formatted statistics to stdout.

    Args:
        stats: Statistics dictionary
        verbose: Whether to print verbose output
    """
    if "error" in stats:
        print(f"❌ {stats['error']}")
        return

    print("=" * 70)
    print("Snowshoe Baseline Dataset - Summary Statistics")
    print("=" * 70)

    # Summary
    summary = stats["summary"]
    print("\n📊 Dataset Overview:")
    print(f"  Total incidents: {summary['total_incidents']}")
    print(f"  Categories: {', '.join(f'{k}={v}' for k, v in summary['categories'].items())}")
    print(f"  Ground truth labels: {', '.join(f'{k}={v}' for k, v in summary['labels'].items())}")
    print(f"  Confidence levels: {', '.join(f'{k}={v}' for k, v in summary['confidence'].items())}")

    # IP statistics
    ip_stats = stats["ip_statistics"]
    print("\n🌐 IP Count Distribution:")
    print(f"  Range: {ip_stats['min']} - {ip_stats['max']}")
    print(f"  Mean: {ip_stats['mean']:.1f}")
    print(f"  Median: {ip_stats['median']}")

    # Session statistics
    session_stats = stats["session_statistics"]
    print("\n📈 Session Count Distribution:")
    print(f"  Range: {session_stats['min']} - {session_stats['max']}")
    print(f"  Mean: {session_stats['mean']:.1f}")
    print(f"  Median: {session_stats['median']}")

    # Temporal coverage
    temporal = stats["temporal_coverage"]
    print("\n📅 Temporal Coverage:")
    print(f"  Start: {temporal['start_date']}")
    print(f"  End: {temporal['end_date']}")
    print(f"  Span: {temporal['span_days']} days")

    # Attack characteristics
    if verbose:
        print("\n🔍 Attack Characteristics:")
        for char_name, char_values in stats["attack_characteristics"].items():
            print(f"  {char_name}:")
            for value, count in char_values.items():
                print(f"    {value}: {count}")

    # Enrichment coverage
    enrichment = stats["enrichment_coverage"]["average"]
    print("\n💎 Enrichment Coverage (average):")
    for service, coverage in enrichment.items():
        print(f"  {service}: {coverage:.1%}")

    # Reviewers
    reviewers = stats["reviewers"]
    print(f"\n👥 Reviewers: {', '.join(f'{k}={v}' for k, v in reviewers.items())}")

    # Data availability
    data_avail = stats["data_availability"]
    print("\n📦 Data Availability:")
    print(f"  Incidents with session data: {data_avail['incidents_with_data']}")
    print(f"  Total sessions: {data_avail['total_sessions']}")
    print(f"  Total events: {data_avail['total_events']}")

    print("\n" + "=" * 70)


def main() -> int:
    """Main statistics generation workflow.

    Returns:
        Exit code (0 = success, 1 = errors)
    """
    parser = argparse.ArgumentParser(description="Generate summary statistics for snowshoe baseline dataset")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print verbose statistics",
    )
    parser.add_argument(
        "--export",
        type=Path,
        help="Export statistics to JSON file",
    )

    args = parser.parse_args()

    # Load all incidents
    base_dir = Path(__file__).parent
    incidents = load_all_incidents(base_dir)

    if not incidents:
        print("❌ No incidents found in dataset", file=sys.stderr)
        return 1

    # Calculate statistics
    stats = calculate_statistics(incidents)

    # Print to stdout
    print_statistics(stats, verbose=args.verbose)

    # Export if requested
    if args.export:
        with open(args.export, "w") as f:
            json.dump(stats, f, indent=2, default=str)
        print(f"\n✅ Statistics exported to: {args.export}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
