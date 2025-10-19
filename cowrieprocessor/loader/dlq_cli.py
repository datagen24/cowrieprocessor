"""CLI tool for reprocessing Dead Letter Queue events.

This module provides command-line tools for analyzing and reprocessing
events that were sent to the DLQ due to JSON parsing failures.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from ..db.engine import create_engine_from_settings, create_session_maker
from ..db.models import DeadLetterEvent, RawEvent
from .dlq_processor import CowrieEventValidator, DLQProcessor, _load_database_settings_from_sensors
from .improved_hybrid import ImprovedHybridProcessor


def analyze_dlq_patterns(db_path: Optional[str] = None) -> None:
    """Analyze patterns in DLQ events."""
    processor = DLQProcessor(db_path)
    patterns = processor.analyze_dlq_patterns()

    print("=== DLQ Analysis Report ===")
    print(f"Total unresolved events: {patterns['total_events']}")

    print("\n--- Events by Reason ---")
    for reason, count in sorted(patterns['by_reason'].items(), key=lambda x: x[1], reverse=True):
        print(f"  {reason}: {count}")

    print("\n--- Events by Source ---")
    for source, count in sorted(patterns['by_source'].items(), key=lambda x: x[1], reverse=True):
        print(f"  {source}: {count}")

    print("\n--- Common Issues ---")
    if patterns['common_issues']:
        # Analyze common issues
        issue_counts: dict[str, int] = {}
        for issue in patterns['common_issues']:
            strategy = issue.get('suggested_strategy', 'unknown')
            issue_counts[strategy] = issue_counts.get(strategy, 0) + 1

        for strategy, count in sorted(issue_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {strategy}: {count}")
    else:
        print("  No common issues found")


def reprocess_dlq_events(
    db_path: Optional[str] = None,
    limit: Optional[int] = None,
    reason_filter: Optional[str] = None,
    dry_run: bool = False,
    skip_duplicates: bool = True,
) -> None:
    """Reprocess events from the DLQ."""
    processor = DLQProcessor(db_path)

    print("=== DLQ Reprocessing ===")
    if dry_run:
        print("DRY RUN MODE - No changes will be made")
    if skip_duplicates:
        print("DUPLICATE HANDLING: Updating existing events with repaired data")

    stats = processor.process_dlq_events(limit, reason_filter)

    print(f"Processed: {stats['processed']}")
    print(f"Repaired: {stats['repaired']}")
    print(f"Failed: {stats['failed']}")
    print(f"Skipped: {stats['skipped']}")

    if stats['processed'] > 0:
        success_rate = (stats['repaired'] / stats['processed']) * 100
        print(f"Success rate: {success_rate:.1f}%")

        if skip_duplicates and stats['repaired'] == stats['processed']:
            print("Note: All events were successfully processed (existing events updated with repaired data)")


def validate_cowrie_events(db_path: Optional[str] = None, limit: Optional[int] = None) -> None:
    """Validate Cowrie events in the database."""
    validator = CowrieEventValidator()

    print("=== Cowrie Event Validation ===")

    # Create database connection using sensors.toml or explicit path
    settings = _load_database_settings_from_sensors(db_path)
    engine = create_engine_from_settings(settings)
    session_factory = create_session_maker(engine)

    with session_factory() as session:
        query = session.query(RawEvent)
        if limit:
            query = query.limit(limit)

        events = query.all()

        validation_stats: dict[str, Any] = {
            "total": len(events),
            "valid": 0,
            "invalid": 0,
            "errors": {},
        }

        for event in events:
            payload = event.payload
            # Handle SQLAlchemy Column type - use getattr to avoid type issues
            payload_data = getattr(event, 'payload', None)
            if hasattr(payload_data, 'items') and callable(getattr(payload_data, 'items')):
                is_valid, errors = validator.validate_event(payload_data)  # type: ignore[arg-type]

                if is_valid:
                    validation_stats["valid"] += 1
                else:
                    validation_stats["invalid"] += 1
                    for error in errors:
                        validation_stats["errors"][error] = validation_stats["errors"].get(error, 0) + 1

        print(f"Total events: {validation_stats['total']}")
        print(f"Valid events: {validation_stats['valid']}")
        print(f"Invalid events: {validation_stats['invalid']}")

        if validation_stats['errors']:
            print("\n--- Validation Errors ---")
            for error, count in sorted(validation_stats['errors'].items(), key=lambda x: x[1], reverse=True):
                print(f"  {error}: {count}")


def test_hybrid_processor(file_path: str) -> None:
    """Test the improved hybrid processor on a file."""
    print(f"=== Testing Hybrid Processor on {file_path} ===")

    processor = ImprovedHybridProcessor()

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = (line.rstrip('\n\r') for line in f)

            processed_count = 0
            for line_offset, event in processor.process_lines(lines):
                processed_count += 1

                if processed_count % 1000 == 0:
                    stats = processor.get_stats()
                    print(f"Processed {processed_count} events: {stats}")

        # Final statistics
        stats = processor.get_stats()
        print("\nFinal Statistics:")
        print(f"Total lines: {stats['total_lines']}")
        print(f"Single-line parsed: {stats['single_line_parsed']}")
        print(f"Multiline parsed: {stats['multiline_parsed']}")
        print(f"Repaired parsed: {stats['repaired_parsed']}")
        print(f"DLQ sent: {stats['dlq_sent']}")

        if stats['total_lines'] > 0:
            success_rate = (
                (stats['single_line_parsed'] + stats['multiline_parsed'] + stats['repaired_parsed'])
                / stats['total_lines']
            ) * 100
            print(f"Success rate: {success_rate:.1f}%")

    except FileNotFoundError:
        print(f"Error: File not found: {file_path}")
        sys.exit(1)
    except Exception as e:
        print(f"Error processing file: {e}")
        sys.exit(1)


def export_dlq_events(
    db_path: Optional[str] = None,
    output_file: str = "dlq_events.json",
    limit: Optional[int] = None,
    reason_filter: Optional[str] = None,
) -> None:
    """Export DLQ events to a JSON file for analysis."""
    print(f"=== Exporting DLQ Events to {output_file} ===")

    # Create database connection using sensors.toml or explicit path
    settings = _load_database_settings_from_sensors(db_path)
    engine = create_engine_from_settings(settings)
    session_factory = create_session_maker(engine)

    with session_factory() as session:
        from sqlalchemy import select

        stmt = select(DeadLetterEvent).where(DeadLetterEvent.resolved == False)

        if reason_filter:
            stmt = stmt.where(DeadLetterEvent.reason == reason_filter)

        if limit:
            stmt = stmt.limit(limit)

        dlq_events = session.execute(stmt).scalars().all()

        export_data = []
        for event in dlq_events:
            export_data.append(
                {
                    "id": event.id,
                    "ingest_id": event.ingest_id,
                    "source": event.source,
                    "source_offset": event.source_offset,
                    "reason": event.reason,
                    "payload": event.payload,
                    "metadata_json": event.metadata_json,
                    "created_at": event.created_at.isoformat() if event.created_at else None,
                }
            )

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, default=str)

        print(f"Exported {len(export_data)} DLQ events to {output_file}")


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="DLQ processing and analysis tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze DLQ patterns
  python -m cowrieprocessor.loader.dlq_cli analyze --db-path /path/to/db.sqlite
  
  # Reprocess DLQ events
  python -m cowrieprocessor.loader.dlq_cli reprocess --limit 100
  
  # Test hybrid processor on a file
  python -m cowrieprocessor.loader.dlq_cli test-hybrid /path/to/cowrie.log
  
  # Export DLQ events for analysis
  python -m cowrieprocessor.loader.dlq_cli export --output-file dlq_export.json
        """,
    )

    parser.add_argument("--db-path", help="Path to SQLite database")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Analyze command
    subparsers.add_parser("analyze", help="Analyze DLQ patterns")

    # Reprocess command
    reprocess_parser = subparsers.add_parser("reprocess", help="Reprocess DLQ events")
    reprocess_parser.add_argument("--limit", type=int, help="Maximum events to process")
    reprocess_parser.add_argument("--reason", help="Only process events with this reason")
    reprocess_parser.add_argument("--dry-run", action="store_true", help="Dry run mode")

    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate Cowrie events")
    validate_parser.add_argument("--limit", type=int, help="Maximum events to validate")

    # Test hybrid command
    test_hybrid_parser = subparsers.add_parser("test-hybrid", help="Test hybrid processor")
    test_hybrid_parser.add_argument("file_path", help="Path to Cowrie log file")

    # Export command
    export_parser = subparsers.add_parser("export", help="Export DLQ events")
    export_parser.add_argument("--output-file", default="dlq_events.json", help="Output file path")
    export_parser.add_argument("--limit", type=int, help="Maximum events to export")
    export_parser.add_argument("--reason", help="Only export events with this reason")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    try:
        if args.command == "analyze":
            analyze_dlq_patterns(args.db_path)
        elif args.command == "reprocess":
            reprocess_dlq_events(args.db_path, args.limit, args.reason, args.dry_run)
        elif args.command == "validate":
            validate_cowrie_events(args.db_path, args.limit)
        elif args.command == "test-hybrid":
            test_hybrid_processor(args.file_path)
        elif args.command == "export":
            export_dlq_events(args.db_path, args.output_file, args.limit, args.reason)
        else:
            print(f"Unknown command: {args.command}")
            return 1

        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
