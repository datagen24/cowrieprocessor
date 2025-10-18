"""CLI for enriching sessions with SSH key intelligence data."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Set

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, aliased
from tqdm import tqdm

from ..db import apply_migrations, create_engine_from_settings, create_session_maker
from ..db.json_utils import get_dialect_name, json_field
from ..db.models import (
    RawEvent,
    SessionSSHKeys,
    SessionSummary,
    SSHKeyAssociations,
    SSHKeyIntelligence,
)
from ..enrichment.ssh_key_extractor import SSHKeyExtractor
from ..status_emitter import StatusEmitter
from .db_config import resolve_database_settings

logger = logging.getLogger(__name__)


def _parse_date(date_str: str) -> datetime:
    """Parse date string in YYYY-MM-DD format."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Invalid date format '{date_str}'. Use YYYY-MM-DD.") from e


def backfill_ssh_keys(args: argparse.Namespace) -> int:
    """Backfill SSH key intelligence from existing raw events.

    Args:
        args: Parsed command line arguments

    Returns:
        Exit code (0 for success)
    """
    # Setup logging
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )

    try:
        # Parse date range
        if args.days_back:
            end_date = datetime.now(UTC)
            start_date = end_date - timedelta(days=args.days_back)
        elif args.start_date and args.end_date:
            start_date = _parse_date(args.start_date)
            end_date = _parse_date(args.end_date)
        else:
            # Default to earliest record if no date range specified
            start_date = None
            end_date = datetime.now(UTC)

        logger.info(f"Backfilling SSH keys from {start_date or 'earliest record'} to {end_date}")

        # Resolve database settings from sensors.toml
        # If no sensor specified, use None to get default database settings
        db_settings = resolve_database_settings(args.sensor if args.sensor else None)

        # Create engine and apply migrations
        engine = create_engine_from_settings(db_settings)
        current_version = apply_migrations(engine)
        logger.info(f"Database schema version: {current_version}")

        if current_version < 11:
            logger.error("Database schema must be v11 or higher for SSH key intelligence")
            return 1

        session_maker = create_session_maker(engine)

        # Initialize SSH key extractor
        ssh_extractor = SSHKeyExtractor()

        # Initialize status emitter
        status_dir = Path(args.status_dir) if args.status_dir else None
        status_emitter = StatusEmitter("ssh_key_backfill", status_dir=status_dir)

        # Process events in batches
        total_processed = 0
        total_keys_extracted = 0
        total_sessions_updated = 0

        with session_maker() as session:
            # Get total count for progress bar
            query = session.query(RawEvent).filter(RawEvent.event_type.contains("command"))
            if start_date:
                query = query.filter(RawEvent.event_timestamp >= start_date)
            if end_date:
                query = query.filter(RawEvent.event_timestamp <= end_date)

            total_events = query.count()
            logger.info(f"Processing {total_events} command events")

            if total_events == 0:
                logger.info("No events to process")
                return 0

            # Process in batches
            batch_size = args.batch_size
            offset = 0

            progress_bar = tqdm(total=total_events, desc="Processing events") if args.progress else None

            while offset < total_events:
                # Get batch of events
                batch_query = session.query(RawEvent).filter(RawEvent.event_type.contains("command"))
                if start_date:
                    batch_query = batch_query.filter(RawEvent.event_timestamp >= start_date)
                if end_date:
                    batch_query = batch_query.filter(RawEvent.event_timestamp <= end_date)

                batch_events = batch_query.order_by(RawEvent.event_timestamp).offset(offset).limit(batch_size).all()

                if not batch_events:
                    break

                batch_keys_extracted = 0
                batch_sessions_updated: set[str] = set()

                for event in batch_events:
                    try:
                        # Skip non-Cowrie events (like iptables logs) that don't have expected structure
                        if not event.payload or not isinstance(event.payload, dict):  # type: ignore[unreachable]
                            continue

                        # Skip events that don't have session_id (likely not Cowrie events)
                        if not event.session_id:  # type: ignore[unreachable]
                            continue

                        # Extract SSH keys from command
                        input_data = event.payload.get("input", "")
                        if input_data and "authorized_keys" in input_data:
                            extracted_keys = ssh_extractor.extract_keys_from_command(input_data)

                            if extracted_keys:
                                batch_keys_extracted += len(extracted_keys)

                                # Extract src_ip from payload
                                src_ip = event.payload.get("src_ip")

                                # Store SSH key intelligence
                                for key in extracted_keys:
                                    try:
                                        _store_ssh_key_intelligence(
                                            session,
                                            key,
                                            event.session_id,
                                            src_ip,
                                            input_data,
                                            event.event_timestamp,
                                        )
                                    except Exception as store_error:
                                        logger.error(f"Failed to store key for event {event.id}: {store_error}")
                                        session.rollback()
                                        continue

                                if event.session_id:
                                    batch_sessions_updated.add(event.session_id)

                    except Exception as e:
                        logger.warning(f"Failed to process event {event.id}: {e}")
                        session.rollback()

                    total_processed += 1
                    if progress_bar:
                        progress_bar.update(1)

                # Commit batch
                try:
                    session.commit()
                    total_keys_extracted += batch_keys_extracted
                    total_sessions_updated += len(batch_sessions_updated)

                    # Update session summaries
                    if batch_sessions_updated:
                        _update_session_summaries(session, batch_sessions_updated)
                        session.commit()

                    # Emit status
                    status_emitter.record_metrics(
                        {
                            "events_processed": total_processed,
                            "keys_extracted": total_keys_extracted,
                            "sessions_updated": total_sessions_updated,
                            "batch_size": batch_size,
                        }
                    )

                except Exception as e:
                    logger.error(f"Failed to commit batch: {e}")
                    session.rollback()

                offset += batch_size

            if progress_bar:
                progress_bar.close()

        logger.info(
            f"Backfill complete: {total_processed} events processed, "
            f"{total_keys_extracted} keys extracted, {total_sessions_updated} sessions updated"
        )
        return 0

    except Exception as e:
        logger.error(f"SSH key backfill failed: {e}", exc_info=True)
        return 1

    finally:
        engine.dispose()


def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcards in a value."""
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _normalize_event_timestamp(event_timestamp: Optional[datetime]) -> Optional[datetime]:
    """Normalize event timestamps to timezone-aware UTC datetimes.

    Args:
        event_timestamp: Timestamp sourced from the dataset.

    Returns:
        A timezone-aware UTC datetime or ``None`` when unavailable.
    """
    if event_timestamp is None:
        return None

    if event_timestamp.tzinfo is None:
        return event_timestamp.replace(tzinfo=UTC)

    return event_timestamp.astimezone(UTC)


def _store_ssh_key_intelligence(
    session: Session,
    key: Any,  # ExtractedSSHKey
    session_id: Optional[str],
    src_ip: Optional[str],
    command_text: str,
    event_timestamp: Optional[datetime],
) -> None:
    """Store SSH key intelligence data.

    Args:
        session: Database session
        key: Extracted SSH key object
        session_id: Session ID
        src_ip: Source IP address
        command_text: Original command text
        event_timestamp: Timestamp sourced from the underlying dataset event
    """
    # Validate required fields before attempting insert
    if not getattr(key, 'key_full', None):
        logger.error(f"Missing key_full for key {getattr(key, 'key_hash', 'unknown')}: {vars(key)}")
        return
    if not getattr(key, 'extraction_method', None):
        logger.error(f"Missing extraction_method for key {getattr(key, 'key_hash', 'unknown')}")
        return

    observed_at = _normalize_event_timestamp(event_timestamp) or datetime.now(UTC)

    # Get or create SSH key intelligence record
    key_record = session.query(SSHKeyIntelligence).filter(SSHKeyIntelligence.key_hash == key.key_hash).first()

    if not key_record:
        key_record = SSHKeyIntelligence(
            key_type=key.key_type,
            key_data=key.key_data,
            key_fingerprint=key.key_fingerprint,
            key_hash=key.key_hash,
            key_comment=key.key_comment,
            key_bits=key.key_bits,
            key_full=key.key_full,
            pattern_type=key.extraction_method,
            target_path=key.target_path,
            first_seen=None,  # Will be set from actual event timestamps
            last_seen=None,  # Will be set from actual event timestamps
            total_attempts=0,
            unique_sources=0,
            unique_sessions=0,
        )
        session.add(key_record)
        session.flush()  # Get the ID
    else:
        # Update existing record - temporal data will be recomputed below
        pass

    # Create session-key link
    if session_id:
        session_key_link = SessionSSHKeys(
            session_id=session_id,
            ssh_key_id=key_record.id,
            command_text=command_text[:1000],  # Truncate for storage
            injection_method=_detect_injection_method(command_text),
            source_ip=src_ip,
            timestamp=observed_at,
        )
        session.add(session_key_link)
        session.flush()

    # Track key associations (co-occurrence)
    _track_key_associations(session, int(key_record.id), session_id, src_ip, observed_at)

    # Recompute aggregates and temporal data from actual events
    try:
        stats = (
            session.query(
                func.count(SessionSSHKeys.id),
                func.count(func.distinct(SessionSSHKeys.source_ip)),
                func.count(func.distinct(SessionSSHKeys.session_id)),
                func.min(SessionSSHKeys.timestamp),
                func.max(SessionSSHKeys.timestamp),
            )
            .filter(SessionSSHKeys.ssh_key_id == key_record.id)
            .one()
        )

        key_record.total_attempts = int(stats[0] or 0)  # type: ignore[assignment]
        key_record.unique_sources = int(stats[1] or 0)  # type: ignore[assignment]
        key_record.unique_sessions = int(stats[2] or 0)  # type: ignore[assignment]

        # Update temporal data from actual event timestamps
        if stats[3]:  # min timestamp
            key_record.first_seen = stats[3]
        if stats[4]:  # max timestamp
            key_record.last_seen = stats[4]

    except Exception as agg_err:
        logger.error(f"Failed to recompute aggregates for key_id={key_record.id}: {agg_err}")


def _detect_injection_method(command_text: str) -> str:
    """Detect the method used to inject the SSH key.

    Args:
        command_text: The command that contained the SSH key

    Returns:
        Injection method string
    """
    command_lower = command_text.lower()

    if "echo" in command_lower and ">>" in command_lower:
        return "echo_append"
    elif "echo" in command_lower and ">" in command_lower:
        return "echo_redirect"
    elif "printf" in command_lower:
        return "printf"
    elif "cat" in command_lower and "<<" in command_lower:
        return "heredoc"
    elif "base64" in command_lower:
        return "base64_decode"
    else:
        return "unknown"


def _find_dataset_timestamp_for_session_key(
    session: Session,
    dialect_name: str,
    record: SessionSSHKeys,
    key_data_cache: Dict[int, Optional[str]],
) -> Optional[datetime]:
    """Locate the dataset timestamp corresponding to a session SSH key link.

    Args:
        session: Active database session.
        dialect_name: Database dialect name for JSON access helpers.
        record: SessionSSHKeys record to repair.
        key_data_cache: Memoized mapping of key_id to key_data.

    Returns:
        The best-effort dataset timestamp for the record or None if not determinable.
    """
    if not record.session_id:
        return None

    input_field = json_field(RawEvent.payload, "input", dialect_name)
    command_field = json_field(RawEvent.payload, "command", dialect_name)

    timestamp_query = (
        session.query(func.min(RawEvent.event_timestamp))
        .filter(RawEvent.session_id == record.session_id)
        .filter(RawEvent.event_timestamp.isnot(None))
        .filter(RawEvent.event_type.contains("command"))
    )

    command_filters = []
    if record.command_text:
        command_filters.append(input_field == record.command_text)
        command_filters.append(command_field == record.command_text)

        if len(record.command_text) >= 1000:
            like_pattern = f"{_escape_like(str(record.command_text))}%"
            command_filters.append(input_field.like(like_pattern, escape='\\'))
            command_filters.append(command_field.like(like_pattern, escape='\\'))

    if command_filters:
        dataset_timestamp = timestamp_query.filter(or_(*command_filters)).scalar()
        if dataset_timestamp:
            return _normalize_event_timestamp(dataset_timestamp)

    key_data = key_data_cache.get(int(record.ssh_key_id))
    if int(record.ssh_key_id) not in key_data_cache:
        key_record = session.get(SSHKeyIntelligence, record.ssh_key_id)
        key_data = str(key_record.key_data) if key_record and key_record.key_data else None
        key_data_cache[int(record.ssh_key_id)] = key_data

    if key_data:
        like_pattern = f"%{_escape_like(key_data)}%"
        dataset_timestamp = (
            timestamp_query.filter(
                or_(
                    input_field.like(like_pattern, escape='\\'),
                    command_field.like(like_pattern, escape='\\'),
                )
            )
        ).scalar()
        if dataset_timestamp:
            return _normalize_event_timestamp(dataset_timestamp)

    dataset_timestamp = (
        session.query(func.min(RawEvent.event_timestamp))
        .filter(RawEvent.session_id == record.session_id)
        .filter(RawEvent.event_timestamp.isnot(None))
        .scalar()
    )
    if dataset_timestamp:
        return _normalize_event_timestamp(dataset_timestamp)

    return None


def _track_key_associations(
    session: Session,
    key_id: int,
    session_id: Optional[str],
    src_ip: Optional[str],
    observed_at: datetime,
) -> None:
    """Track associations between SSH keys for campaign correlation.

    Args:
        session: Database session
        key_id: SSH key ID
        session_id: Session ID
        src_ip: Source IP address
        observed_at: Timestamp of the co-occurrence derived from the dataset
    """
    if not session_id:
        return

    observed_at = observed_at.astimezone(UTC)

    # Find other keys used in the same session
    other_keys = (
        session.query(SessionSSHKeys.ssh_key_id)
        .filter(and_(SessionSSHKeys.session_id == session_id, SessionSSHKeys.ssh_key_id != key_id))
        .all()
    )

    for (other_key_id,) in other_keys:
        # Get or create association record
        association = (
            session.query(SSHKeyAssociations)
            .filter(
                and_(
                    SSHKeyAssociations.key_id_1 == min(key_id, other_key_id),
                    SSHKeyAssociations.key_id_2 == max(key_id, other_key_id),
                )
            )
            .first()
        )

        if not association:
            association = SSHKeyAssociations(
                key_id_1=min(key_id, other_key_id),
                key_id_2=max(key_id, other_key_id),
                co_occurrence_count=1,
                same_session_count=1,
                same_ip_count=1 if src_ip else 0,
                first_seen=observed_at,
                last_seen=observed_at,
            )
            session.add(association)
        else:
            association.co_occurrence_count += 1  # type: ignore[assignment]
            association.same_session_count += 1  # type: ignore[assignment]
            if src_ip:
                association.same_ip_count += 1  # type: ignore[assignment]

            if association.first_seen is None or observed_at < association.first_seen:
                association.first_seen = observed_at  # type: ignore[assignment]
            if association.last_seen is None or observed_at > association.last_seen:
                association.last_seen = observed_at  # type: ignore[assignment]


def _update_session_summaries(session: Session, session_ids: set[str]) -> None:
    """Update session summaries with SSH key counts.

    Args:
        session: Database session
        session_ids: Set of session IDs to update
    """
    for session_id in session_ids:
        # Count SSH key injections and unique keys for this session
        key_stats = (
            session.query(
                func.count(SessionSSHKeys.id).label("injection_count"),
                func.count(func.distinct(SessionSSHKeys.ssh_key_id)).label("unique_key_count"),
            )
            .filter(SessionSSHKeys.session_id == session_id)
            .first()
        )

        if key_stats:
            # Update session summary
            session.query(SessionSummary).filter(SessionSummary.session_id == session_id).update(
                {
                    "ssh_key_injections": key_stats.injection_count,
                    "unique_ssh_keys": key_stats.unique_key_count,
                    "updated_at": datetime.now(UTC),
                }
            )


def export_ssh_keys(args: argparse.Namespace) -> int:
    """Export SSH key intelligence data.

    Args:
        args: Parsed command line arguments

    Returns:
        Exit code (0 for success)
    """
    # Setup logging
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )

    try:
        # Parse date range
        if args.days_back:
            end_date = datetime.now(UTC)
            start_date = end_date - timedelta(days=args.days_back)
        else:
            start_date = None
            end_date = None

        # Resolve database settings
        # If no sensor specified, use None to get default database settings
        db_settings = resolve_database_settings(args.sensor if args.sensor else None)
        engine = create_engine_from_settings(db_settings)
        session_maker = create_session_maker(engine)

        with session_maker() as session:
            # Query SSH keys
            query = session.query(SSHKeyIntelligence)
            if start_date:
                query = query.filter(SSHKeyIntelligence.last_seen >= start_date)
            if end_date:
                query = query.filter(SSHKeyIntelligence.last_seen <= end_date)

            keys = query.all()

            # Export data
            export_data = []
            for key in keys:
                export_data.append(
                    {
                        "key_type": key.key_type,
                        "key_fingerprint": key.key_fingerprint,
                        "key_hash": key.key_hash,
                        "key_comment": key.key_comment,
                        "key_size_bits": key.key_bits,
                        "first_seen": key.first_seen.isoformat() if key.first_seen else None,
                        "last_seen": key.last_seen.isoformat() if key.last_seen else None,
                        "total_attempts": key.total_attempts,
                        "unique_sources": key.unique_sources,
                        "unique_sessions": key.unique_sessions,
                    }
                )

            # Write output
            if args.output:
                output_path = Path(args.output)
                with output_path.open('w') as f:
                    if args.format == 'json':
                        json.dump(export_data, f, indent=2)
                    else:  # CSV
                        import csv

                        if export_data:
                            writer = csv.DictWriter(f, fieldnames=export_data[0].keys())
                            writer.writeheader()
                            writer.writerows(export_data)
            else:
                # Write to stdout
                if args.format == 'json':
                    print(json.dumps(export_data, indent=2))
                else:  # CSV
                    import csv
                    import sys

                    if export_data:
                        writer = csv.DictWriter(sys.stdout, fieldnames=export_data[0].keys())
                        writer.writeheader()
                        writer.writerows(export_data)

            logger.info(f"Exported {len(export_data)} SSH keys")
            return 0

    except Exception as e:
        logger.error(f"SSH key export failed: {e}", exc_info=True)
        return 1

    finally:
        engine.dispose()


def repair_ssh_key_timestamps(args: argparse.Namespace) -> int:
    """Repair historical SSH key timestamps using dataset event times.

    Args:
        args: Parsed command line arguments.

    Returns:
        Exit code (0 for success).
    """
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )

    engine = None

    try:
        db_settings = resolve_database_settings(args.sensor if args.sensor else None)
        engine = create_engine_from_settings(db_settings)
        session_maker = create_session_maker(engine)

        total_links = 0
        updated_links = 0
        key_ids_to_refresh: Set[int] = set()

        with session_maker() as session:
            connection = session.connection()
            dialect_name = get_dialect_name(connection)
            key_data_cache: Dict[int, Optional[str]] = {}

            total_links = int(session.query(func.count(SessionSSHKeys.id)).scalar() or 0)
            logger.info(f"Scanning {total_links} session_ssh_keys records for timestamp repair")

            batch_size = args.batch_size
            offset = 0

            while True:
                records = (
                    session.query(SessionSSHKeys).order_by(SessionSSHKeys.id).offset(offset).limit(batch_size).all()
                )

                if not records:
                    break

                for record in records:
                    dataset_timestamp = _find_dataset_timestamp_for_session_key(
                        session, dialect_name, record, key_data_cache
                    )
                    if not dataset_timestamp:
                        continue

                    if record.timestamp != dataset_timestamp:
                        record.timestamp = dataset_timestamp  # type: ignore[assignment]
                        updated_links += 1
                        key_ids_to_refresh.add(int(record.ssh_key_id))

                session.commit()
                offset += batch_size

            logger.info(f"Updated {updated_links} session_ssh_keys records")

            if not key_ids_to_refresh:
                logger.info("No aggregate refresh required; exiting")
                return 0

            logger.info(f"Refreshing aggregates for {len(key_ids_to_refresh)} SSH keys")

            for key_id in key_ids_to_refresh:
                stats = (
                    session.query(
                        func.count(SessionSSHKeys.id),
                        func.count(func.distinct(SessionSSHKeys.source_ip)),
                        func.count(func.distinct(SessionSSHKeys.session_id)),
                        func.min(SessionSSHKeys.timestamp),
                        func.max(SessionSSHKeys.timestamp),
                    )
                    .filter(SessionSSHKeys.ssh_key_id == key_id)
                    .one()
                )

                key_record = session.get(SSHKeyIntelligence, key_id)
                if not key_record:
                    continue

                key_record.total_attempts = int(stats[0] or 0)  # type: ignore[assignment]
                key_record.unique_sources = int(stats[1] or 0)  # type: ignore[assignment]
                key_record.unique_sessions = int(stats[2] or 0)  # type: ignore[assignment]

                if stats[3]:
                    key_record.first_seen = _normalize_event_timestamp(stats[3])  # type: ignore[assignment]
                if stats[4]:
                    key_record.last_seen = _normalize_event_timestamp(stats[4])  # type: ignore[assignment]

            session.commit()

            logger.info("Refreshing affected SSH key associations")

            associations = (
                session.query(SSHKeyAssociations)
                .filter(
                    or_(
                        SSHKeyAssociations.key_id_1.in_(key_ids_to_refresh),
                        SSHKeyAssociations.key_id_2.in_(key_ids_to_refresh),
                    )
                )
                .all()
            )

            for association in associations:
                key1 = aliased(SessionSSHKeys)
                key2 = aliased(SessionSSHKeys)
                rows = (
                    session.query(key1.timestamp, key2.timestamp)
                    .filter(key1.session_id == key2.session_id)
                    .filter(key1.ssh_key_id == association.key_id_1)
                    .filter(key2.ssh_key_id == association.key_id_2)
                    .all()
                )

                if not rows:
                    continue

                first_candidates = [min(t1, t2) for t1, t2 in rows if t1 and t2]
                last_candidates = [max(t1, t2) for t1, t2 in rows if t1 and t2]

                if first_candidates:
                    association.first_seen = _normalize_event_timestamp(min(first_candidates))  # type: ignore[assignment]
                if last_candidates:
                    association.last_seen = _normalize_event_timestamp(max(last_candidates))  # type: ignore[assignment]

            session.commit()

        logger.info("Timestamp repair complete")
        return 0

    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.error(f"Failed to repair SSH key timestamps: {exc}", exc_info=True)
        return 1

    finally:
        if engine is not None:
            engine.dispose()


def main() -> int:
    """Main entry point for cowrie-enrich-ssh-keys command.

    Returns:
        Exit code
    """
    parser = argparse.ArgumentParser(
        description="Enrich Cowrie sessions with SSH key intelligence data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Backfill SSH keys for last 30 days
  cowrie-enrich-ssh-keys backfill --days-back 30
  
  # Backfill SSH keys for specific date range
  cowrie-enrich-ssh-keys backfill --start-date 2025-01-01 --end-date 2025-01-31
  
  # Backfill all SSH keys (from earliest record)
  cowrie-enrich-ssh-keys backfill
  
  # Export SSH keys to JSON file
  cowrie-enrich-ssh-keys export --format json --output ssh_keys.json
  
  # Export SSH keys from last 7 days to CSV
  cowrie-enrich-ssh-keys export --days-back 7 --format csv
  
  # Use specific sensor (optional, for debugging)
  cowrie-enrich-ssh-keys backfill --sensor prod-sensor-01 --days-back 30

  # Repair historical first/last seen timestamps after upgrading the extractor
  cowrie-enrich-ssh-keys repair-timestamps --sensor prod-sensor-01
        """,
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Subcommand to run')

    # backfill subcommand
    backfill_parser = subparsers.add_parser('backfill', help='Backfill SSH key intelligence from existing events')

    # Sensor configuration (optional - for debugging)
    backfill_parser.add_argument('--sensor', type=str, help='Sensor name from sensors.toml (optional, for debugging)')

    # Date range options
    date_group = backfill_parser.add_mutually_exclusive_group()
    date_group.add_argument('--days-back', type=int, help='Process last N days (default: all records from earliest)')
    date_group.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')

    backfill_parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD), required if --start-date is used')

    # Processing options
    backfill_parser.add_argument('--batch-size', type=int, default=100, help='Batch size for processing (default: 100)')
    backfill_parser.add_argument('--progress', action='store_true', help='Show progress bar')
    backfill_parser.add_argument('--status-dir', type=str, help='Directory for status files (optional)')
    backfill_parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')

    backfill_parser.set_defaults(func=backfill_ssh_keys)

    # export subcommand
    export_parser = subparsers.add_parser('export', help='Export SSH key intelligence data')

    # Sensor configuration (optional - for debugging)
    export_parser.add_argument('--sensor', type=str, help='Sensor name from sensors.toml (optional, for debugging)')

    # Date range options
    export_parser.add_argument('--days-back', type=int, help='Export keys from last N days (default: all)')

    # Output options
    export_parser.add_argument(
        '--format', type=str, choices=['json', 'csv'], default='json', help='Output format (default: json)'
    )
    export_parser.add_argument('--output', type=str, help='Output file (default: stdout)')
    export_parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')

    export_parser.set_defaults(func=export_ssh_keys)

    # repair subcommand
    repair_parser = subparsers.add_parser(
        'repair-timestamps',
        help='Repair first/last seen timestamps to align with dataset observation times',
    )

    repair_parser.add_argument('--sensor', type=str, help='Sensor name from sensors.toml (optional)')
    repair_parser.add_argument('--batch-size', type=int, default=500, help='Batch size for database repairs')
    repair_parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')

    repair_parser.set_defaults(func=repair_ssh_key_timestamps)

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Validate end_date if start_date is provided
    if hasattr(args, 'start_date') and args.start_date and not args.end_date:
        parser.error("--end-date is required when --start-date is used")

    result: int = args.func(args)
    return result


if __name__ == '__main__':
    sys.exit(main())
