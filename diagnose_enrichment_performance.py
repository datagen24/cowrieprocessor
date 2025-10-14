#!/usr/bin/env python3
"""Diagnose password enrichment performance."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cowrieprocessor.cli.db_config import resolve_database_settings
from cowrieprocessor.db import create_engine_from_settings, create_session_maker
from cowrieprocessor.db.models import RawEvent, SessionSummary


def analyze_password_diversity(args: argparse.Namespace) -> None:
    """Analyze password diversity in sessions to understand cache effectiveness."""
    # Parse date range
    if args.last_days:
        end_date = datetime.now(UTC)
        start_date = end_date - timedelta(days=args.last_days)
    else:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=UTC)
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=UTC)

    print(f"\n{'=' * 70}")
    print("Password Enrichment Performance Analysis")
    print(f"Date Range: {start_date.date()} to {end_date.date()}")
    print(f"{'=' * 70}\n")

    # Check cache statistics
    cache_dir = Path(args.cache_dir)
    if (cache_dir / "hibp").exists():
        import subprocess

        result = subprocess.run(
            ["find", str(cache_dir / "hibp"), "-name", "*.json", "-type", "f"],
            capture_output=True,
            text=True,
        )
        cache_count = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
        print(f"✓ HIBP Cache Entries: {cache_count:,}")

        # Get cache size
        result = subprocess.run(["du", "-sh", str(cache_dir / "hibp")], capture_output=True, text=True)
        cache_size = result.stdout.split()[0] if result.stdout else "unknown"
        print(f"✓ HIBP Cache Size: {cache_size}")
    else:
        print("✗ HIBP cache directory not found!")

    # Connect to database
    db_settings = resolve_database_settings(args.database)
    engine = create_engine_from_settings(db_settings)
    session_maker = create_session_maker(engine)

    with session_maker() as db_session:
        # Count sessions in date range
        total_sessions = (
            db_session.query(SessionSummary)
            .filter(SessionSummary.first_event_at >= start_date, SessionSummary.first_event_at < end_date)
            .count()
        )

        print(f"\n✓ Total Sessions in Range: {total_sessions:,}")

        # Count sessions with login attempts
        sessions_with_logins = (
            db_session.query(SessionSummary)
            .filter(
                SessionSummary.first_event_at >= start_date,
                SessionSummary.first_event_at < end_date,
                SessionSummary.login_attempts > 0,
            )
            .count()
        )

        print(f"✓ Sessions with Login Attempts: {sessions_with_logins:,}")

        # Count already enriched sessions
        enriched_sessions = (
            db_session.query(SessionSummary)
            .filter(
                SessionSummary.first_event_at >= start_date,
                SessionSummary.first_event_at < end_date,
                SessionSummary.login_attempts > 0,
            )
            .all()
        )

        already_enriched = sum(1 for s in enriched_sessions if s.enrichment and "password_stats" in s.enrichment)

        print(f"✓ Already Enriched: {already_enriched:,}")
        print(f"✓ Remaining to Enrich: {sessions_with_logins - already_enriched:,}")

        # Sample some sessions to estimate password events per session
        sample_sessions = (
            db_session.query(SessionSummary)
            .filter(
                SessionSummary.first_event_at >= start_date,
                SessionSummary.first_event_at < end_date,
                SessionSummary.login_attempts > 0,
            )
            .limit(100)
            .all()
        )

        if sample_sessions:
            total_login_events = 0
            for session in sample_sessions:
                login_event_count = (
                    db_session.query(RawEvent)
                    .filter(
                        RawEvent.session_id == session.session_id,
                        RawEvent.event_type.in_(["cowrie.login.success", "cowrie.login.failed"]),
                    )
                    .count()
                )
                total_login_events += login_event_count

            avg_logins_per_session = total_login_events / len(sample_sessions)
            print(f"\n📊 Average Login Attempts per Session: {avg_logins_per_session:.1f}")

            # Estimate unique passwords per session (rough estimate)
            print(f"📊 Estimated unique passwords per session: {avg_logins_per_session * 0.7:.1f}")

        # Performance estimates
        print(f"\n{'=' * 70}")
        print("Performance Estimates:")
        print(f"{'=' * 70}")

        remaining = sessions_with_logins - already_enriched
        if remaining > 0:
            # HIBP rate limit: 0.625 req/sec = 1.6s per request
            # Assuming 30% cache miss rate for unique passwords
            cache_entries = cache_count if "cache_count" in locals() else 0
            estimated_cache_hit_rate = min(95, (cache_entries / 16384) * 100)  # 16384 = 16^4 possible 5-char prefixes

            print(f"\nEstimated Cache Hit Rate: {estimated_cache_hit_rate:.1f}%")
            print(f"Estimated Cache Miss Rate: {100 - estimated_cache_hit_rate:.1f}%")

            # Time estimates
            if estimated_cache_hit_rate < 50:
                # Cache is cold - mostly API calls
                estimated_seconds_per_session = 1.5
                print(f"\n⚠️  Cache is cold - expect ~{estimated_seconds_per_session:.1f}s per session")
            else:
                # Cache is warm - faster
                estimated_seconds_per_session = 0.3
                print(f"\n✓ Cache is warm - expect ~{estimated_seconds_per_session:.1f}s per session")

            total_time_seconds = remaining * estimated_seconds_per_session
            total_time_hours = total_time_seconds / 3600

            print(f"\nEstimated Time Remaining: {total_time_hours:.1f} hours ({total_time_seconds / 60:.0f} minutes)")

            if total_time_hours > 24:
                print(f"                         = {total_time_hours / 24:.1f} days")

        print(f"\n{'=' * 70}")
        print("Recommendations:")
        print(f"{'=' * 70}\n")

        if estimated_cache_hit_rate < 50:
            print("⚠️  First-time enrichment - cache is being built")
            print("   • Subsequent runs will be MUCH faster (5-10x)")
            print("   • Consider running on a smaller date range first")
            print("   • Use --batch-size 500 to reduce database overhead")
        else:
            print("✓ Cache is well-populated")
            print("   • Most common passwords should be cached")
            print("   • Increase --batch-size to 500-1000 for faster processing")

        print(f"\n{'=' * 70}\n")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Diagnose password enrichment performance")

    # Date range
    date_group = parser.add_mutually_exclusive_group(required=True)
    date_group.add_argument("--last-days", type=int, help="Analyze last N days")
    date_group.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")

    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD), required with --start-date")

    # Config
    parser.add_argument("--database", type=str, help="Database path or connection string")
    parser.add_argument("--cache-dir", type=str, default="/mnt/dshield/data/cache", help="Cache directory")

    args = parser.parse_args()

    if args.start_date and not args.end_date:
        parser.error("--end-date is required when --start-date is used")

    analyze_password_diversity(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
