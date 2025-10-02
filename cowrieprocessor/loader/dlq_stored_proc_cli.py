"""CLI tool for PostgreSQL stored procedure-based DLQ processing.

This provides high-performance DLQ processing using PostgreSQL stored procedures
that operate directly in the database without pulling records to the application.
"""

from __future__ import annotations

import argparse
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..db.engine import create_engine_from_settings
from ..db.stored_procedures import DLQStoredProcedures
from ..settings import load_database_settings


def create_stored_procedures(engine: Engine) -> None:
    """Create all DLQ processing stored procedures."""
    print("Creating DLQ processing stored procedures...")

    # Check database type
    dialect_name = engine.dialect.name
    if dialect_name != 'postgresql':
        print(f"❌ Stored procedures are only supported for PostgreSQL, not {dialect_name}")
        print("Use the regular DLQ processor for SQLite and other databases.")
        return

    try:
        with engine.connect() as connection:
            DLQStoredProcedures.create_dlq_processing_procedures(connection)
            connection.commit()
        print("✅ Stored procedures created successfully")
    except Exception as e:
        print(f"❌ Error creating stored procedures: {e}")


def process_dlq_stored_proc(engine: Engine, limit: Optional[int] = None, reason_filter: Optional[str] = None) -> None:
    """Process DLQ events using stored procedures."""
    print("=== DLQ Processing (Stored Procedures) ===")

    with engine.connect() as connection:
        stats = DLQStoredProcedures.process_dlq_events_stored_proc(connection, limit, reason_filter)

    print(f"Processed: {stats['processed']}")
    print(f"Repaired: {stats['repaired']}")
    print(f"Failed: {stats['failed']}")
    print(f"Skipped: {stats['skipped']}")

    if stats['processed'] > 0:
        success_rate = (stats['repaired'] / stats['processed']) * 100
        print(f"Success rate: {success_rate:.1f}%")


def get_dlq_stats_stored_proc(engine: Engine) -> None:
    """Get DLQ statistics using stored procedures."""
    print("=== DLQ Statistics (Stored Procedures) ===")

    with engine.connect() as connection:
        stats = DLQStoredProcedures.get_dlq_statistics_stored_proc(connection)

    print(f"Total Events: {stats['total_events']}")
    print(f"Unresolved Events: {stats['unresolved_events']}")
    print(f"Resolved Events: {stats['resolved_events']}")

    if stats['top_reasons']:
        print("\nTop Failure Reasons:")
        for reason, count in stats['top_reasons'].items():
            print(f"  {reason}: {count}")

    if stats['oldest_unresolved']:
        print(f"\nOldest Unresolved: {stats['oldest_unresolved']}")
        print(f"Newest Unresolved: {stats['newest_unresolved']}")


def cleanup_dlq_stored_proc(engine: Engine, older_than_days: int = 30) -> None:
    """Cleanup resolved DLQ events using stored procedures."""
    print(f"=== DLQ Cleanup (Older than {older_than_days} days) ===")

    with engine.connect() as connection:
        deleted_count = DLQStoredProcedures.cleanup_resolved_dlq_events_stored_proc(connection, older_than_days)

    print(f"Deleted {deleted_count} resolved DLQ events")


def test_stored_procedures(engine: Engine) -> None:
    """Test stored procedure functionality."""
    print("=== Testing Stored Procedures ===")

    with engine.connect() as connection:
        # Test JSON repair function
        test_content = '{"eventid": "cowrie.client.kex", "session": "test123"'
        result = connection.execute(
            text("""
            SELECT repair_cowrie_json(:content)
        """),
            {"content": test_content},
        ).fetchone()

        print(f"Test repair input: {test_content}")
        print(f"Test repair output: {result[0]}")

        # Test statistics function
        stats = DLQStoredProcedures.get_dlq_statistics_stored_proc(connection)
        print(f"\nCurrent DLQ stats: {stats}")


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="PostgreSQL DLQ Processing with Stored Procedures")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Create procedures command
    create_parser = subparsers.add_parser("create", help="Create stored procedures")

    # Process command
    process_parser = subparsers.add_parser("process", help="Process DLQ events")
    process_parser.add_argument("--limit", type=int, help="Limit number of events to process")
    process_parser.add_argument("--reason", help="Filter by failure reason")

    # Stats command
    stats_parser = subparsers.add_parser("stats", help="Get DLQ statistics")

    # Cleanup command
    cleanup_parser = subparsers.add_parser("cleanup", help="Cleanup resolved DLQ events")
    cleanup_parser.add_argument("--older-than-days", type=int, default=30, help="Delete events older than N days")

    # Test command
    test_parser = subparsers.add_parser("test", help="Test stored procedures")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Get database connection
    db_settings = load_database_settings()
    engine = create_engine_from_settings(db_settings)

    try:
        if args.command == "create":
            create_stored_procedures(engine)
        elif args.command == "process":
            process_dlq_stored_proc(engine, args.limit, args.reason)
        elif args.command == "stats":
            get_dlq_stats_stored_proc(engine)
        elif args.command == "cleanup":
            cleanup_dlq_stored_proc(engine, args.older_than_days)
        elif args.command == "test":
            test_stored_procedures(engine)
    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
