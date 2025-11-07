#!/usr/bin/env python3
"""Backfill snapshot columns for existing session_summaries from ip_inventory.

This script implements Phase 2 of ADR-007 snapshot population fix. It backfills the 5 snapshot
columns (source_ip, snapshot_asn, snapshot_country, snapshot_ip_type, enrichment_at) for
existing sessions that lack snapshot data.

**Problem Statement**:
Production database has 1.68M sessions with 0% snapshot coverage despite 100% IP inventory
enrichment. The BulkLoader now populates snapshots for NEW sessions, but existing sessions
need backfilling.

**Design**:
1. Query sessions WHERE source_ip IS NULL (indicating missing snapshots)
2. Extract canonical IPs from enrichment JSON using same logic as BulkLoader
3. Batch lookup snapshot data from ip_inventory (single query per batch)
4. UPDATE sessions with COALESCE for immutability (preserve existing values)
5. Track progress via StatusEmitter and checkpoint files for resume capability

**Safety Features**:
- Dry-run mode for validation without changes
- Configurable batch size (default: 1000)
- Resume capability via checkpoint state
- Transaction rollback on errors
- Progress tracking every 10 batches

**Performance Targets**:
- Process 1000 sessions/batch in ~2-3 seconds
- Total time: ~90 minutes for 1.68M sessions
- Single SQL query per batch (not per-session)

**Usage**:
    # Dry-run validation (no changes)
    uv run python scripts/migrations/backfill_session_snapshots.py \\
        --db "postgresql://user:pass@host:port/database" \\  # pragma: allowlist secret
        --dry-run

    # Production backfill with progress tracking
    uv run python scripts/migrations/backfill_session_snapshots.py \\
        --db "postgresql://user:pass@host:port/database" \\  # pragma: allowlist secret
        --batch-size 1000 \\
        --status-dir /mnt/dshield/data/logs/status \\
        --progress

    # Resume from previous checkpoint
    uv run python scripts/migrations/backfill_session_snapshots.py \\
        --db "postgresql://user:pass@host:port/database" \\  # pragma: allowlist secret
        --resume \\
        --checkpoint-file /path/to/checkpoint.json

**Rationale** (from ADR-007):
- Snapshot columns enable 10x faster queries WITHOUT JOIN to ip_inventory
- Temporal accuracy preserved ("what was it at time of attack")
- 95% of queries avoid JOIN overhead using lightweight snapshot columns
- ASN-level infrastructure clustering for botnet attribution

**References**:
- Design: docs/designs/adr007-snapshot-population-fix.md (lines 272-430)
- Implementation: cowrieprocessor/loader/bulk.py (BulkLoader._lookup_ip_snapshots)
- Models: cowrieprocessor/db/models.py (SessionSummary, IPInventory)
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import Engine, func, update
from sqlalchemy.orm import Session

from cowrieprocessor.db import create_engine_from_settings, create_session_maker
from cowrieprocessor.db.models import SessionSummary
from cowrieprocessor.settings import DatabaseSettings
from cowrieprocessor.status_emitter import StatusEmitter

logger = logging.getLogger(__name__)


def is_private_or_reserved(ip_str: str) -> bool:
    """Check if IP address is private, reserved, or non-routable (RFC1918, bogons, etc.).

    Args:
        ip_str: IP address string

    Returns:
        True if IP is private/reserved/non-routable, False if public

    References:
        - RFC1918: Private networks (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
        - RFC6598: Shared address space (100.64.0.0/10)
        - RFC5737: Documentation (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24)
        - Loopback, link-local, multicast, reserved ranges
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        # Invalid IP format - treat as non-routable
        logger.warning(f"Invalid IP address format: {ip_str}")
        return True


class CheckpointState:
    """Persistent checkpoint state for resume capability."""

    def __init__(self, filepath: Path) -> None:
        """Initialize checkpoint state.

        Args:
            filepath: Path to checkpoint file
        """
        self.filepath = filepath
        self.last_batch: int = 0
        self.total_updated: int = 0
        self.last_session_id: Optional[str] = None
        self.started_at: Optional[str] = None
        self.last_saved_at: Optional[str] = None

    def load(self) -> None:
        """Load checkpoint state from file if exists."""
        if not self.filepath.exists():
            logger.info(f"No checkpoint file found at {self.filepath}, starting fresh")
            return

        try:
            with open(self.filepath, "r") as f:
                data = json.load(f)
            self.last_batch = data.get("last_batch", 0)
            self.total_updated = data.get("total_updated", 0)
            self.last_session_id = data.get("last_session_id")
            self.started_at = data.get("started_at")
            self.last_saved_at = data.get("last_saved_at")
            logger.info(
                f"Loaded checkpoint: batch={self.last_batch}, "
                f"total_updated={self.total_updated}, "
                f"last_session_id={self.last_session_id}"
            )
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load checkpoint from {self.filepath}: {e}")

    def save(self, batch_num: int, total_updated: int, last_session_id: Optional[str] = None) -> None:
        """Save checkpoint state to file.

        Args:
            batch_num: Current batch number
            total_updated: Total sessions updated so far
            last_session_id: Last session ID processed (for ordering)
        """
        self.last_batch = batch_num
        self.total_updated = total_updated
        self.last_session_id = last_session_id
        self.last_saved_at = datetime.now(UTC).isoformat()

        if not self.started_at:
            self.started_at = self.last_saved_at

        data = {
            "last_batch": self.last_batch,
            "total_updated": self.total_updated,
            "last_session_id": self.last_session_id,
            "started_at": self.started_at,
            "last_saved_at": self.last_saved_at,
        }

        # Atomic write via temp file
        tmp_path = self.filepath.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2)
        tmp_path.replace(self.filepath)

        logger.debug(f"Saved checkpoint: batch={batch_num}, total={total_updated}")


def extract_canonical_ip(enrichment: Optional[Dict[str, Any]]) -> Optional[str]:
    """Extract canonical source IP from enrichment JSON.

    The canonical IP is stored in enrichment.session_metadata.source_ip during initial
    ingestion by BulkLoader. This is the "first IP seen" for the session and serves as
    the stable identifier for snapshot lookups.

    Args:
        enrichment: Enrichment JSON payload from session_summaries

    Returns:
        Canonical source IP string, or None if not found

    Examples:
        >>> extract_canonical_ip({"session_metadata": {"source_ip": "192.0.2.1"}})
        '192.0.2.1'
        >>> extract_canonical_ip({})
        None
        >>> extract_canonical_ip(None)
        None
    """
    if not enrichment:
        return None

    session_metadata = enrichment.get("session_metadata")
    if not session_metadata or not isinstance(session_metadata, dict):
        return None

    source_ip = session_metadata.get("source_ip")
    if source_ip and isinstance(source_ip, str):
        return str(source_ip)  # Explicit cast to satisfy mypy

    return None


def lookup_ip_snapshots_batch(session: Session, ip_addresses: list[str]) -> Dict[str, Dict[str, Any]]:
    """Batch lookup snapshot data from ip_inventory for given IPs.

    This function replicates the logic from BulkLoader._lookup_ip_snapshots() to ensure
    consistency between new ingestion and backfill operations.

    Args:
        session: SQLAlchemy session
        ip_addresses: List of IP addresses to look up

    Returns:
        Dict mapping IP address to snapshot data dict with keys:
        - asn: Integer ASN number
        - country: 2-letter country code (or None if XX/unknown)
        - ip_type: String IP type (e.g., 'RESIDENTIAL', 'DATACENTER', 'VPN')
        - enrichment_at: Timestamp of enrichment

    Note:
        Missing IPs return empty dict. IPs without enrichment return partial data
        (e.g., asn may be None if Cymru failed).
    """
    if not ip_addresses:
        return {}

    # Batch query for all IPs - single query for entire batch
    # Query computed columns from ip_inventory (ADR-007 schema)
    # Use raw SQL text() to access columns directly (avoid hybrid_property evaluation)
    from sqlalchemy import text as sql_text

    results = session.execute(
        sql_text("""
            SELECT ip_address, current_asn, geo_country, ip_types, enrichment_updated_at
            FROM ip_inventory
            WHERE ip_address = ANY(:ip_list)
        """),
        {"ip_list": list(ip_addresses)},
    ).fetchall()

    snapshots: Dict[str, Dict[str, Any]] = {}
    for row in results:
        ip, asn, country, ip_types_array, enriched_at = row

        # Extract primary IP type from array (first element)
        # ip_types is already prioritized by enrichment logic
        primary_type = None
        if ip_types_array and len(ip_types_array) > 0:
            primary_type = ip_types_array[0]  # First element is highest priority

        snapshots[ip] = {
            "asn": asn,
            "country": country if country and country != "XX" else None,  # XX = unknown
            "ip_type": primary_type,
            "enrichment_at": enriched_at,
        }

    return snapshots


def backfill_snapshots(
    engine: Engine,
    batch_size: int = 1000,
    dry_run: bool = False,
    status_dir: Optional[Path] = None,
    show_progress: bool = False,
    resume: bool = False,
    checkpoint_file: Optional[Path] = None,
) -> int:
    """Backfill snapshot columns for sessions missing them.

    Algorithm:
        1. Query sessions WHERE source_ip IS NULL (need backfill)
        2. For each batch, extract canonical source IPs from enrichment JSON
        3. Lookup snapshot data from ip_inventory (single query per batch)
        4. UPDATE session_summaries with snapshot columns using COALESCE

    Args:
        engine: SQLAlchemy engine connected to target database
        batch_size: Number of sessions to process per batch (default: 1000)
        dry_run: If True, show what would be updated without making changes
        status_dir: Directory for status files (None disables status emitter)
        show_progress: If True, log progress every batch
        resume: If True, resume from checkpoint file
        checkpoint_file: Path to checkpoint file for resume (default: /tmp/snapshot_backfill.json)

    Returns:
        Number of sessions updated

    Raises:
        ValueError: If database connection fails or invalid parameters
        RuntimeError: If batch processing encounters unrecoverable errors
    """
    session_maker = create_session_maker(engine)
    status_emitter = StatusEmitter("snapshot_backfill", status_dir=status_dir) if status_dir else None

    # Initialize checkpoint
    if checkpoint_file is None:
        checkpoint_file = Path("/tmp/snapshot_backfill.json")
    checkpoint = CheckpointState(checkpoint_file)

    if resume:
        checkpoint.load()

    total_updated = checkpoint.total_updated
    batch_num = checkpoint.last_batch
    failed_batches: list[int] = []

    with session_maker() as session:
        # Count sessions needing backfill (have source_ip but missing snapshots)
        total_count = (
            session.query(func.count(SessionSummary.session_id))
            .filter(
                SessionSummary.source_ip.isnot(None),  # Must have source IP
                SessionSummary.snapshot_country.is_(None),  # Missing snapshots
            )
            .scalar()
        )

        logger.info(f"Found {total_count:,} sessions needing snapshot backfill")

        if dry_run:
            logger.info("DRY RUN MODE - no changes will be made")

        if total_count == 0:
            logger.info("No sessions need backfilling. Exiting.")
            return 0

        # Progress tracking
        start_time = datetime.now(UTC)
        last_progress_log = start_time

        while True:
            batch_num += 1

            try:
                # Query sessions that HAVE source_ip but are missing snapshots
                batch = (
                    session.query(
                        SessionSummary.session_id,
                        SessionSummary.source_ip,
                        SessionSummary.enrichment,
                    )
                    .filter(
                        SessionSummary.source_ip.isnot(None),  # Must have source IP
                        SessionSummary.snapshot_country.is_(None),  # Missing snapshots
                    )
                    .limit(batch_size)
                    .all()
                )

                if not batch:
                    break  # No more sessions to process

                # Extract canonical IPs for batch lookup
                # Use both SQL-extracted IP and Python extraction as fallback
                session_ip_map: Dict[str, str] = {}
                for row in batch:
                    session_id = row.session_id
                    # Try SQL-extracted IP first, fallback to Python extraction
                    source_ip = row.source_ip or extract_canonical_ip(row.enrichment)
                    if source_ip:
                        session_ip_map[session_id] = source_ip

                if not session_ip_map:
                    logger.warning(f"Batch {batch_num}: No valid IPs extracted, skipping")
                    continue

                unique_ips = list(set(session_ip_map.values()))

                # Batch lookup snapshots from ip_inventory (SINGLE QUERY for entire batch)
                ip_snapshots = lookup_ip_snapshots_batch(session, unique_ips)

                # Update sessions with snapshots
                if not dry_run:
                    updates_performed = 0
                    marked_private = 0
                    marked_no_data = 0

                    for session_id, source_ip in session_ip_map.items():
                        snapshot = ip_snapshots.get(source_ip, {})

                        # Check if IP is private/reserved (RFC1918, bogons, etc.)
                        if is_private_or_reserved(source_ip):
                            # Mark private IPs with sentinel value to prevent re-selection
                            # Use 'XX' as sentinel (DShield convention for non-routable IPs)
                            session.execute(
                                update(SessionSummary)
                                .where(SessionSummary.session_id == session_id)
                                .values(
                                    source_ip=source_ip,
                                    snapshot_country="XX",  # Sentinel: unenrichable (private IP)
                                )
                            )
                            marked_private += 1
                            continue

                        # Only update if we have actual snapshot data (country is required)
                        if snapshot.get("country"):
                            session.execute(
                                update(SessionSummary)
                                .where(SessionSummary.session_id == session_id)
                                .values(
                                    source_ip=source_ip,
                                    snapshot_asn=snapshot.get("asn"),
                                    snapshot_country=snapshot.get("country"),
                                    snapshot_ip_type=snapshot.get("ip_type"),
                                    enrichment_at=snapshot.get("enrichment_at"),
                                )
                            )
                            updates_performed += 1
                        else:
                            # Public IP with no/unknown enrichment data
                            # Mark with sentinel value to prevent re-selection
                            # Use 'XX' as sentinel (DShield convention for non-routable IPs)
                            session.execute(
                                update(SessionSummary)
                                .where(SessionSummary.session_id == session_id)
                                .values(
                                    source_ip=source_ip,
                                    snapshot_country="XX",  # Sentinel: unenrichable (failed enrichment)
                                )
                            )
                            marked_no_data += 1

                    session.commit()
                    # Count ALL processed sessions (enriched + marked) for progress tracking
                    total_updated += updates_performed + marked_private + marked_no_data

                    # Log marked sessions for debugging
                    if marked_private > 0 or marked_no_data > 0:
                        logger.debug(
                            f"Batch {batch_num}: Marked {marked_private} private IPs, "
                            f"{marked_no_data} public IPs with no enrichment data (excluded from future runs)"
                        )
                else:
                    # Dry-run: apply same validation logic
                    updates_performed = 0
                    marked_private = 0
                    marked_no_data = 0

                    for session_id, source_ip in session_ip_map.items():
                        snapshot = ip_snapshots.get(source_ip, {})

                        # Check if IP is private/reserved (RFC1918, bogons, etc.)
                        if is_private_or_reserved(source_ip):
                            marked_private += 1
                            continue

                        # Only count if we have actual snapshot data (country is required)
                        if snapshot.get("country"):
                            updates_performed += 1
                        else:
                            # Public IP with no/unknown enrichment data
                            marked_no_data += 1

                    # Count ALL processed sessions (enriched + marked) for progress tracking
                    total_updated += updates_performed + marked_private + marked_no_data
                    logger.info(
                        f"DRY RUN - Batch {batch_num}: Would update {updates_performed} sessions with snapshots, "
                        f"mark {marked_private + marked_no_data} as unenrichable "
                        f"({len(ip_snapshots)}/{len(unique_ips)} IPs found in inventory)"
                    )

                    # Log breakdown for debugging
                    if marked_private > 0 or marked_no_data > 0:
                        logger.debug(
                            f"DRY RUN - Batch {batch_num}: Would mark {marked_private} private IPs, "
                            f"{marked_no_data} public IPs with no enrichment data"
                        )

                # Save checkpoint every 10 batches
                if batch_num % 10 == 0:
                    last_session_id = batch[-1].session_id if batch else None
                    checkpoint.save(batch_num, total_updated, last_session_id)

                # Emit status every 10 batches
                if status_emitter and batch_num % 10 == 0:
                    elapsed = (datetime.now(UTC) - start_time).total_seconds()
                    percent_complete = (total_updated / total_count * 100) if total_count > 0 else 0
                    rate = total_updated / elapsed if elapsed > 0 else 0

                    status_emitter.record_metrics(
                        {
                            "phase": "backfill",
                            "batch": batch_num,
                            "sessions_processed": total_updated,
                            "total_sessions": total_count,
                            "percent_complete": round(percent_complete, 2),
                            "sessions_per_second": round(rate, 2),
                            "elapsed_seconds": round(elapsed, 2),
                            "failed_batches": len(failed_batches),
                        }
                    )

                # Progress logging
                if show_progress and batch_num % 10 == 0:
                    current_time = datetime.now(UTC)
                    elapsed = (current_time - start_time).total_seconds()
                    batch_elapsed = (current_time - last_progress_log).total_seconds()
                    rate = total_updated / elapsed if elapsed > 0 else 0
                    batch_rate = (batch_size * 10) / batch_elapsed if batch_elapsed > 0 else 0

                    eta_seconds = (total_count - total_updated) / rate if rate > 0 else 0
                    eta_minutes = eta_seconds / 60

                    logger.info(
                        f"Progress: {total_updated:,}/{total_count:,} sessions "
                        f"({percent_complete:.1f}%) | "
                        f"Batch {batch_num} | "
                        f"Rate: {rate:.1f} sess/s (avg), {batch_rate:.1f} sess/s (current) | "
                        f"ETA: {eta_minutes:.1f} min"
                    )
                    last_progress_log = current_time

            except Exception as e:
                logger.error(f"Error processing batch {batch_num}: {e}", exc_info=True)
                session.rollback()
                failed_batches.append(batch_num)
                # Continue with next batch instead of failing entire backfill
                continue

        # Final checkpoint save
        checkpoint.save(batch_num, total_updated)

    # Final summary
    elapsed = (datetime.now(UTC) - start_time).total_seconds()
    rate = total_updated / elapsed if elapsed > 0 else 0

    logger.info("=" * 80)
    logger.info("Backfill complete!")
    logger.info(f"Sessions updated: {total_updated:,} / {total_count:,}")
    logger.info(f"Batches processed: {batch_num}")
    logger.info(f"Failed batches: {len(failed_batches)}")
    logger.info(f"Total time: {elapsed:.1f} seconds ({elapsed / 60:.1f} minutes)")
    logger.info(f"Average rate: {rate:.1f} sessions/second")
    logger.info("=" * 80)

    if failed_batches:
        logger.warning(f"Failed batches: {failed_batches}")

    return total_updated


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Backfill session snapshot columns from ip_inventory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run validation (no changes)
  %(prog)s --db "postgresql://user:pass@host/db" --dry-run

  # Production backfill with progress tracking
  %(prog)s --db "postgresql://user:pass@host/db" --batch-size 1000 --progress

  # Resume from checkpoint
  %(prog)s --db "postgresql://user:pass@host/db" --resume

Environment Variables:
  DB_URI        Database connection string (overridden by --db)
  LOG_LEVEL     Logging level (DEBUG, INFO, WARNING, ERROR)
        """,
    )

    parser.add_argument(
        "--db",
        type=str,
        help="Database connection string (postgresql://... or sqlite:///...)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Number of sessions to process per batch (default: 1000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes",
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help="Show progress updates every 10 batches",
    )
    parser.add_argument(
        "--status-dir",
        type=Path,
        help="Directory for status files (default: None, disables status emitter)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from previous checkpoint file",
    )
    parser.add_argument(
        "--checkpoint-file",
        type=Path,
        default=Path("/tmp/snapshot_backfill.json"),
        help="Path to checkpoint file for resume (default: /tmp/snapshot_backfill.json)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Get database URI
    db_uri_arg = args.db or (sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else None)
    if not db_uri_arg:
        logger.error("Database URI required via --db argument or DB_URI environment variable")
        return 1

    # Ensure we have a proper string for the database URI
    db_uri: str = str(db_uri_arg)

    # Create database engine
    try:
        # Create DatabaseSettings with the URI
        db_settings = DatabaseSettings(url=db_uri)
        engine = create_engine_from_settings(db_settings)
        logger.info(f"Connected to database: {engine.url.database} ({engine.dialect.name})")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        return 1

    # Run backfill
    try:
        total_updated = backfill_snapshots(
            engine=engine,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            status_dir=args.status_dir,
            show_progress=args.progress,
            resume=args.resume,
            checkpoint_file=args.checkpoint_file,
        )

        if args.dry_run:
            logger.info(f"DRY RUN complete. Would have updated {total_updated:,} sessions")
        else:
            logger.info(f"Backfill complete. Updated {total_updated:,} sessions")

        return 0

    except Exception as e:
        logger.error(f"Backfill failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
