#!/usr/bin/env python3
"""Monitor rebuild progress over time.

Run this script periodically to track rebuild progress.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, func, select

from cowrieprocessor.db import RawEvent, SessionSummary


def monitor_progress(db_url: str) -> dict:
    """Monitor rebuild progress and return current statistics."""
    engine = create_engine(db_url)

    with engine.connect() as conn:
        # Get current counts
        raw_sessions = conn.execute(
            select(func.count(func.distinct(RawEvent.session_id))).where(RawEvent.session_id.isnot(None))
        ).scalar_one()

        summary_sessions = conn.execute(select(func.count()).select_from(SessionSummary)).scalar_one()

        total_events = conn.execute(select(func.count()).select_from(RawEvent)).scalar_one()

        # Check data integrity by sampling sessions
        sample_sessions = conn.execute(
            select(SessionSummary.session_id, SessionSummary.event_count)
            .order_by(SessionSummary.session_id)
            .limit(20)  # Sample more for better accuracy
        ).all()

        integrity_issues = []
        for session_id, recorded_count in sample_sessions:
            # Get actual count from raw_events
            actual_count = conn.execute(
                select(func.count()).select_from(RawEvent).where(RawEvent.session_id == session_id)
            ).scalar_one()

            if actual_count != recorded_count:
                integrity_issues.append(
                    {
                        'session_id': session_id,
                        'actual': actual_count,
                        'recorded': recorded_count,
                        'difference': actual_count - recorded_count,
                    }
                )

        # Calculate progress percentage
        expected_sessions = 956209  # From our earlier validation
        progress_pct = (summary_sessions / expected_sessions) * 100 if expected_sessions > 0 else 0

        return {
            'timestamp': datetime.now().isoformat(),
            'raw_sessions': raw_sessions,
            'summary_sessions': summary_sessions,
            'total_events': total_events,
            'expected_sessions': expected_sessions,
            'progress_percent': round(progress_pct, 2),
            'missing_sessions': raw_sessions - summary_sessions,
            'integrity_issues_count': len(integrity_issues),
            'data_quality_score': round(len(integrity_issues) / max(len(sample_sessions), 1) * 100, 2),
        }


def main() -> None:
    """Main monitoring function."""
    if len(sys.argv) != 2:
        print("Usage: uv run python scripts/monitor_rebuild.py <database_url>")
        sys.exit(1)

    db_url = sys.argv[1]

    print("🔍 Monitoring rebuild progress...")
    print(f"📊 Database: {db_url}")
    print("=" * 60)

    try:
        stats = monitor_progress(db_url)

        print(f"⏰ Timestamp: {stats['timestamp']}")
        print(
            f"📈 Progress: {stats['progress_percent']}% "
            f"({stats['summary_sessions']:,}/{stats['expected_sessions']:,} sessions)"
        )
        print(f"📊 Total events: {stats['total_events']:,}")
        print(f"🔍 Missing sessions: {stats['missing_sessions']:,}")
        print(f"⚠️  Integrity issues: {stats['integrity_issues_count']} out of 20 sampled")
        print(f"📊 Data quality score: {stats['data_quality_score']}%")

        if stats['integrity_issues_count'] > 0:
            print("\n🚨 Data integrity issues found:")
            for issue in stats.get('integrity_issues', []):
                print(
                    f"   Session {issue['session_id']}: "
                    f"recorded={issue['recorded']}, actual={issue['actual']} "
                    f"(diff={issue['difference']})"
                )

        # Recommendations
        print("\n💡 Recommendations:")
        if stats['progress_percent'] < 10:
            print("   🟡 Rebuild just starting - monitor closely")
        elif stats['progress_percent'] < 50:
            print("   🟢 Rebuild in progress - looking good")
        elif stats['progress_percent'] < 90:
            print("   🟢 Rebuild progressing well")
        else:
            print("   🟢 Rebuild nearly complete")

        if stats['data_quality_score'] > 20:
            print(f"   ⚠️  High integrity issues ({stats['data_quality_score']:.1f}%) - investigate data quality")
        elif stats['data_quality_score'] > 5:
            print(f"   🟡 Some integrity issues ({stats['data_quality_score']:.1f}%) - monitor closely")
        else:
            print(f"   ✅ Data quality excellent ({stats['data_quality_score']:.1f}%)")

        if abs(stats['missing_sessions']) > 1000:
            print(f"   ⚠️  Large session count discrepancy ({stats['missing_sessions']:,}) - investigate")

    except Exception as e:
        print(f"❌ Error monitoring progress: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
