#!/usr/bin/env python3
"""Backfill script to populate files table from historical raw_events data."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError as exc:  # pragma: no cover - defensive
    raise RuntimeError("Python 3.11+ is required to run this script") from exc

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.db.models import Files
from cowrieprocessor.settings import load_database_settings


def parse_timestamp(timestamp_str: Optional[str]) -> Optional[datetime]:
    """Parse Cowrie timestamp string to datetime object."""
    if not timestamp_str:
        return None
    
    try:
        # Cowrie timestamps are typically in ISO format
        return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None


def extract_file_data(event_payload: Dict[str, Any], session_id: str) -> Optional[Dict[str, Any]]:
    """Extract file metadata from cowrie.session.file_download event."""
    if event_payload.get("eventid") != "cowrie.session.file_download":
        return None
    
    # Extract required fields
    shasum = event_payload.get("shasum")
    if not shasum or not isinstance(shasum, str) or len(shasum) != 64:
        return None  # Skip invalid hashes
    
    return {
        "session_id": session_id,
        "shasum": shasum,
        "filename": event_payload.get("filename"),
        "file_size": event_payload.get("size"),
        "download_url": event_payload.get("url"),
        "first_seen": parse_timestamp(event_payload.get("timestamp")),
    }


def iter_file_events(engine, batch_size: int = 1000) -> Iterator[Dict[str, Any]]:
    """Iterate through file download events in batches."""
    from sqlalchemy import text
    
    query = text("""
        SELECT session_id, payload
        FROM raw_events
        WHERE json_extract(payload, '$.eventid') = 'cowrie.session.file_download'
          AND json_extract(payload, '$.shasum') IS NOT NULL
          AND json_extract(payload, '$.shasum') != ''
        ORDER BY id ASC
    """)
    
    with engine.connect() as conn:
        result = conn.execute(query)
        
        batch = []
        for row in result:
            try:
                payload = json.loads(row.payload) if isinstance(row.payload, str) else row.payload
                file_data = extract_file_data(payload, row.session_id)
                
                if file_data:
                    batch.append(file_data)
                    
                    if len(batch) >= batch_size:
                        yield batch
                        batch = []
            except (json.JSONDecodeError, TypeError) as e:
                print(f"Warning: Failed to parse event payload: {e}")
                continue
        
        # Yield remaining batch
        if batch:
            yield batch


def insert_files_batch(engine, batch: list[Dict[str, Any]]) -> int:
    """Insert a batch of files into the database."""
    from sqlalchemy import text
    from sqlalchemy.dialects.sqlite import insert
    
    if not batch:
        return 0
    
    with engine.begin() as conn:
        # Use SQLite's INSERT OR IGNORE to handle duplicates
        stmt = insert(Files.__table__)
        
        # Prepare data for insertion
        insert_data = []
        for file_data in batch:
            insert_data.append({
                "session_id": file_data["session_id"],
                "shasum": file_data["shasum"],
                "filename": file_data.get("filename"),
                "file_size": file_data.get("file_size"),
                "download_url": file_data.get("download_url"),
                "first_seen": file_data.get("first_seen"),
                "enrichment_status": "pending",
            })
        
        # Insert with conflict resolution
        result = conn.execute(
            stmt.on_conflict_do_nothing(
                index_elements=["session_id", "shasum"]
            ),
            insert_data
        )
        
        return len(insert_data)


def validate_file_data(engine) -> Tuple[int, int]:
    """Validate files table data integrity."""
    from sqlalchemy import text
    
    with engine.connect() as conn:
        # Count total files
        result = conn.execute(text("SELECT COUNT(*) FROM files"))
        total_files = result.scalar_one()
        
        # Count unique hashes
        result = conn.execute(text("SELECT COUNT(DISTINCT shasum) FROM files"))
        unique_hashes = result.scalar_one()
        
        # Count files with enrichment status
        result = conn.execute(text("SELECT COUNT(*) FROM files WHERE enrichment_status = 'pending'"))
        pending_enrichment = result.scalar_one()
        
        return total_files, unique_hashes, pending_enrichment


def main() -> int:
    """Main backfill function."""
    parser = argparse.ArgumentParser(
        description="Backfill files table from historical raw_events data"
    )
    parser.add_argument(
        "--db",
        type=str,
        help="Database URL (default: from settings)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Batch size for processing (default: 1000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate existing data, don't backfill",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of events to process (for testing)",
    )
    
    args = parser.parse_args()
    
    # Get database engine
    if args.db:
        from sqlalchemy import create_engine
        engine = create_engine(args.db)
    else:
        db_settings = load_database_settings()
        engine = create_engine_from_settings(db_settings)
    
    print(f"Starting files table backfill...")
    print(f"Batch size: {args.batch_size}")
    
    # Check if files table exists
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    if "files" not in inspector.get_table_names():
        print("Error: Files table does not exist. Run migrate_to_v4_schema.py first.")
        return 1
    
    if args.validate_only:
        print("Validating existing files table data...")
        total_files, unique_hashes, pending_enrichment = validate_file_data(engine)
        print(f"Total files: {total_files:,}")
        print(f"Unique hashes: {unique_hashes:,}")
        print(f"Pending enrichment: {pending_enrichment:,}")
        return 0
    
    if args.dry_run:
        print("DRY RUN: Would backfill files table from raw_events")
        print("Scanning for file download events...")
        
        count = 0
        for batch in iter_file_events(engine, args.batch_size):
            count += len(batch)
            if args.limit and count >= args.limit:
                break
            if count % 10000 == 0:
                print(f"Found {count:,} file download events so far...")
        
        print(f"Would process approximately {count:,} file download events")
        return 0
    
    # Perform backfill
    processed_count = 0
    inserted_count = 0
    
    try:
        print("Processing file download events...")
        
        for batch in iter_file_events(engine, args.batch_size):
            if args.limit and processed_count >= args.limit:
                break
                
            inserted = insert_files_batch(engine, batch)
            inserted_count += inserted
            processed_count += len(batch)
            
            if processed_count % 10000 == 0:
                print(f"Processed {processed_count:,} events, inserted {inserted_count:,} files")
        
        print(f"Backfill completed!")
        print(f"Total events processed: {processed_count:,}")
        print(f"Files inserted: {inserted_count:,}")
        
        # Validate results
        total_files, unique_hashes, pending_enrichment = validate_file_data(engine)
        print(f"\nFinal validation:")
        print(f"Total files in table: {total_files:,}")
        print(f"Unique hashes: {unique_hashes:,}")
        print(f"Pending enrichment: {pending_enrichment:,}")
        
        return 0
        
    except Exception as e:
        print(f"Backfill failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
