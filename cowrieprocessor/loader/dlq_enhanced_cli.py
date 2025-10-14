"""Enhanced CLI tool for production-ready DLQ processing.

This provides comprehensive DLQ management with security, monitoring,
and operational features for production environments.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..db.engine import create_engine_from_settings
from ..db.enhanced_stored_procedures import EnhancedDLQStoredProcedures
from ..settings import load_database_settings


def create_enhanced_procedures(engine: Engine) -> None:
    """Create all enhanced DLQ processing stored procedures."""
    print("Creating enhanced DLQ processing stored procedures...")

    # Check database type
    dialect_name = engine.dialect.name
    if dialect_name != 'postgresql':
        print(f"❌ Enhanced stored procedures are only supported for PostgreSQL, not {dialect_name}")
        print("Use the regular DLQ processor for SQLite and other databases.")
        return

    try:
        with engine.connect() as connection:
            EnhancedDLQStoredProcedures.create_enhanced_dlq_procedures(connection)
            connection.commit()
        print("✅ Enhanced stored procedures created successfully")
        print("📊 Features enabled:")
        print("  - Circuit breaker pattern")
        print("  - Rate limiting")
        print("  - Processing locks")
        print("  - Error history tracking")
        print("  - Performance metrics")
        print("  - Security enhancements")
    except Exception as e:
        print(f"❌ Error creating enhanced stored procedures: {e}")


def process_dlq_enhanced(
    engine: Engine,
    limit: Optional[int] = None,
    reason_filter: Optional[str] = None,
    priority_filter: Optional[int] = None,
    session_id: Optional[str] = None,
) -> None:
    """Process DLQ events using enhanced stored procedures."""
    print("=== Enhanced DLQ Processing ===")

    if reason_filter:
        print(f"Filtering by reason: {reason_filter}")
    if priority_filter:
        print(f"Filtering by priority: {priority_filter}")

    with engine.connect() as connection:
        stats = EnhancedDLQStoredProcedures.process_dlq_events_enhanced(
            connection, limit, reason_filter, priority_filter, session_id
        )

    print(f"Processed: {stats['processed']}")
    print(f"Repaired: {stats['repaired']}")
    print(f"Failed: {stats['failed']}")
    print(f"Skipped: {stats['skipped']}")
    print(f"Processing Duration: {stats['processing_duration_ms']:.1f}ms")

    if stats['circuit_breaker_triggered']:
        print("⚠️  Circuit breaker triggered - processing halted")
    else:
        if stats['processed'] > 0:
            success_rate = (stats['repaired'] / stats['processed']) * 100
            print(f"Success rate: {success_rate:.1f}%")


def get_dlq_health(engine: Engine) -> None:
    """Get comprehensive DLQ health statistics."""
    print("=== DLQ Health Dashboard ===")

    with engine.connect() as connection:
        health = EnhancedDLQStoredProcedures.get_dlq_health_stats(connection)

    print("📊 Event Statistics:")
    print(f"  Pending Events: {health['pending_events']:,}")
    print(f"  Processed Events: {health['processed_events']:,}")
    print(f"  High Retry Events: {health['high_retry_events']:,}")
    print(f"  Locked Events: {health['locked_events']:,}")
    print(f"  Malicious Events: {health['malicious_events']:,}")
    print(f"  High Priority Events: {health['high_priority_events']:,}")

    if health['avg_resolution_time_seconds'] > 0:
        print(f"⏱️  Average Resolution Time: {health['avg_resolution_time_seconds']:.1f} seconds")

    if health['oldest_unresolved_event']:
        print(f"📅 Oldest Unresolved Event: {health['oldest_unresolved_event']}")

    # Health status
    if health['pending_events'] == 0:
        print("✅ DLQ is healthy - no pending events")
    elif health['high_retry_events'] > 100:
        print("⚠️  Warning - high number of retry events")
    elif health['locked_events'] > 50:
        print("⚠️  Warning - many events are locked")
    else:
        print("✅ DLQ is operational")


def cleanup_dlq_enhanced(engine: Engine, older_than_days: int = 90) -> None:
    """Cleanup resolved DLQ events with enhanced batching."""
    print(f"=== DLQ Cleanup (Older than {older_than_days} days) ===")

    with engine.connect() as connection:
        deleted_count = EnhancedDLQStoredProcedures.cleanup_resolved_events_enhanced(connection, older_than_days)

    print(f"🗑️  Deleted {deleted_count:,} resolved DLQ events")


def monitor_dlq_processing(engine: Engine, duration_minutes: int = 5) -> None:
    """Monitor DLQ processing in real-time."""
    print(f"=== DLQ Processing Monitor ({duration_minutes} minutes) ===")

    import time

    start_time = time.time()
    end_time = start_time + (duration_minutes * 60)

    with engine.connect() as connection:
        while time.time() < end_time:
            health = EnhancedDLQStoredProcedures.get_dlq_health_stats(connection)

            print(
                f"\r⏱️  {datetime.now().strftime('%H:%M:%S')} | "
                f"Pending: {health['pending_events']:,} | "
                f"Locked: {health['locked_events']:,} | "
                f"High Retry: {health['high_retry_events']:,}",
                end="",
            )

            time.sleep(10)  # Update every 10 seconds

    print("\n✅ Monitoring completed")


def analyze_dlq_patterns_enhanced(engine: Engine) -> None:
    """Analyze DLQ patterns with enhanced insights."""
    print("=== Enhanced DLQ Pattern Analysis ===")

    with engine.connect() as connection:
        # Get failure reasons
        reasons = connection.execute(
            text("""
            SELECT reason, COUNT(*) as count, 
                   AVG(retry_count) as avg_retries,
                   COUNT(*) FILTER (WHERE retry_count > 5) as high_retry_count
            FROM dead_letter_events 
            WHERE resolved = FALSE
            GROUP BY reason
            ORDER BY count DESC
            LIMIT 10
        """)
        ).fetchall()

        print("📊 Top Failure Reasons:")
        for reason, count, avg_retries, high_retry_count in reasons:
            print(f"  {reason}: {count:,} events (avg retries: {avg_retries:.1f}, high retry: {high_retry_count:,})")

        # Get priority distribution
        priorities = connection.execute(
            text("""
            SELECT priority, COUNT(*) as count
            FROM dead_letter_events 
            WHERE resolved = FALSE
            GROUP BY priority
            ORDER BY priority ASC
        """)
        ).fetchall()

        print("\n🎯 Priority Distribution:")
        for priority, count in priorities:
            priority_name = {1: "Critical", 2: "High", 3: "Medium", 4: "Low", 5: "Normal"}.get(
                priority, f"Level {priority}"
            )
            print(f"  {priority_name} ({priority}): {count:,} events")

        # Get classification distribution
        classifications = connection.execute(
            text("""
            SELECT classification, COUNT(*) as count
            FROM dead_letter_events 
            WHERE resolved = FALSE
            GROUP BY classification
            ORDER BY count DESC
        """)
        ).fetchall()

        print("\n🔍 Classification Distribution:")
        for classification, count in classifications:
            print(f"  {classification or 'Unclassified'}: {count:,} events")


def test_enhanced_procedures(engine: Engine) -> None:
    """Test enhanced stored procedure functionality."""
    print("=== Testing Enhanced Stored Procedures ===")

    with engine.connect() as connection:
        # Test circuit breaker
        print("Testing circuit breaker...")
        breaker_check = connection.execute(text("SELECT check_circuit_breaker('test_breaker')")).fetchone()
        print(f"Circuit breaker check: {breaker_check[0]}")

        # Test health view
        print("Testing health view...")
        health = EnhancedDLQStoredProcedures.get_dlq_health_stats(connection)
        print(f"Health stats: {health}")

        # Test JSON repair
        print("Testing JSON repair...")
        test_content = '{"eventid": "cowrie.client.kex", "session": "test123"'
        repair_result = connection.execute(
            text("""
            SELECT repair_cowrie_json_enhanced(:content, 1)
        """),
            {"content": test_content},
        ).fetchone()
        print(f"Repair test: {repair_result[0]}")


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Enhanced PostgreSQL DLQ Processing")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Create procedures command
    subparsers.add_parser("create", help="Create enhanced stored procedures")

    # Process command
    process_parser = subparsers.add_parser("process", help="Process DLQ events")
    process_parser.add_argument("--limit", type=int, help="Limit number of events to process")
    process_parser.add_argument("--reason", help="Filter by failure reason")
    process_parser.add_argument("--priority", type=int, help="Filter by priority (1=highest, 10=lowest)")
    process_parser.add_argument("--session-id", help="Processing session ID")

    # Health command
    subparsers.add_parser("health", help="Get DLQ health statistics")

    # Cleanup command
    cleanup_parser = subparsers.add_parser("cleanup", help="Cleanup resolved DLQ events")
    cleanup_parser.add_argument("--older-than-days", type=int, default=90, help="Delete events older than N days")

    # Monitor command
    monitor_parser = subparsers.add_parser("monitor", help="Monitor DLQ processing")
    monitor_parser.add_argument("--duration", type=int, default=5, help="Monitoring duration in minutes")

    # Analyze command
    subparsers.add_parser("analyze", help="Analyze DLQ patterns")

    # Test command
    subparsers.add_parser("test", help="Test enhanced procedures")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Get database connection
    db_settings = load_database_settings()
    engine = create_engine_from_settings(db_settings)

    try:
        if args.command == "create":
            create_enhanced_procedures(engine)
        elif args.command == "process":
            process_dlq_enhanced(engine, args.limit, args.reason, args.priority, args.session_id)
        elif args.command == "health":
            get_dlq_health(engine)
        elif args.command == "cleanup":
            cleanup_dlq_enhanced(engine, args.older_than_days)
        elif args.command == "monitor":
            monitor_dlq_processing(engine, args.duration)
        elif args.command == "analyze":
            analyze_dlq_patterns_enhanced(engine)
        elif args.command == "test":
            test_enhanced_procedures(engine)
    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
