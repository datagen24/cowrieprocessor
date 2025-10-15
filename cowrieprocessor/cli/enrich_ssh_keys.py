"""CLI for enriching sessions with SSH key intelligence data."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy import and_, func, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from tqdm import tqdm

from ..db import apply_migrations, create_engine_from_settings, create_session_maker
from ..db.models import (
    RawEvent,
    SSHKeyIntelligence,
    SSHKeyAssociations,
    SessionSSHKeys,
    SessionSummary,
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
            query = session.query(RawEvent).filter(
                RawEvent.event_type.contains("command")
            )
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
                batch_query = session.query(RawEvent).filter(
                    RawEvent.event_type.contains("command")
                )
                if start_date:
                    batch_query = batch_query.filter(RawEvent.event_timestamp >= start_date)
                if end_date:
                    batch_query = batch_query.filter(RawEvent.event_timestamp <= end_date)
                    
                batch_events = batch_query.order_by(RawEvent.event_timestamp).offset(offset).limit(batch_size).all()
                
                if not batch_events:
                    break
                    
                batch_keys_extracted = 0
                batch_sessions_updated = set()
                
                for event in batch_events:
                    try:
                        # Skip non-Cowrie events (like iptables logs) that don't have expected structure
                        if not event.payload or not isinstance(event.payload, dict):
                            continue
                            
                        # Skip events that don't have session_id (likely not Cowrie events)
                        if not event.session_id:
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
                                    _store_ssh_key_intelligence(
                                        session, key, event.session_id, src_ip, input_data
                                    )
                                    
                                if event.session_id:
                                    batch_sessions_updated.add(event.session_id)
                                        
                    except Exception as e:
                        logger.warning(f"Failed to process event {event.id}: {e}")
                        
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
                    status_emitter.record_metrics({
                        "events_processed": total_processed,
                        "keys_extracted": total_keys_extracted,
                        "sessions_updated": total_sessions_updated,
                        "batch_size": batch_size,
                    })
                    
                except Exception as e:
                    logger.error(f"Failed to commit batch: {e}")
                    session.rollback()
                    
                offset += batch_size
                
            if progress_bar:
                progress_bar.close()
                
        logger.info(f"Backfill complete: {total_processed} events processed, {total_keys_extracted} keys extracted, {total_sessions_updated} sessions updated")
        return 0
        
    except Exception as e:
        logger.error(f"SSH key backfill failed: {e}", exc_info=True)
        return 1
        
    finally:
        engine.dispose()


def _store_ssh_key_intelligence(
    session: Session,
    key: Any,  # ExtractedSSHKey
    session_id: Optional[str],
    src_ip: Optional[str],
    command_text: str,
) -> None:
    """Store SSH key intelligence data.
    
    Args:
        session: Database session
        key: Extracted SSH key object
        session_id: Session ID
        src_ip: Source IP address
        command_text: Original command text
    """
    # Get or create SSH key intelligence record
    key_record = session.query(SSHKeyIntelligence).filter(
        SSHKeyIntelligence.key_hash == key.key_hash
    ).first()
    
    if not key_record:
        key_record = SSHKeyIntelligence(
            key_type=key.key_type,
            key_data=key.key_data,
            key_fingerprint=key.key_fingerprint,
            key_hash=key.key_hash,
            key_comment=key.key_comment,
            key_bits=key.key_bits,
            first_seen=datetime.now(UTC),
            last_seen=datetime.now(UTC),
            total_attempts=1,
            unique_sources=1,
            unique_sessions=1,
        )
        session.add(key_record)
        session.flush()  # Get the ID
    else:
        # Update existing record
        key_record.last_seen = datetime.now(UTC)
        key_record.total_attempts += 1
        if src_ip and src_ip not in key_record.unique_sources:
            key_record.unique_sources += 1
        if session_id and session_id not in key_record.unique_sessions:
            key_record.unique_sessions += 1
            
    # Create session-key link
    if session_id:
        session_key_link = SessionSSHKeys(
            session_id=session_id,
            ssh_key_id=key_record.id,
            command_text=command_text[:1000],  # Truncate for storage
            injection_method=_detect_injection_method(command_text),
            source_ip=src_ip,
            timestamp=datetime.now(UTC),
        )
        session.add(session_key_link)
        
    # Track key associations (co-occurrence)
    _track_key_associations(session, key_record.id, session_id, src_ip)


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


def _track_key_associations(
    session: Session,
    key_id: int,
    session_id: Optional[str],
    src_ip: Optional[str],
) -> None:
    """Track associations between SSH keys for campaign correlation.
    
    Args:
        session: Database session
        key_id: SSH key ID
        session_id: Session ID
        src_ip: Source IP address
    """
    if not session_id:
        return
        
    # Find other keys used in the same session
    other_keys = session.query(SessionSSHKeys.ssh_key_id).filter(
        and_(
            SessionSSHKeys.session_id == session_id,
            SessionSSHKeys.ssh_key_id != key_id
        )
    ).all()
    
    for (other_key_id,) in other_keys:
        # Get or create association record
        association = session.query(SSHKeyAssociations).filter(
            and_(
                SSHKeyAssociations.key_id_1 == min(key_id, other_key_id),
                SSHKeyAssociations.key_id_2 == max(key_id, other_key_id)
            )
        ).first()
        
        if not association:
            association = SSHKeyAssociations(
                key_id_1=min(key_id, other_key_id),
                key_id_2=max(key_id, other_key_id),
                co_occurrence_count=1,
                same_session_count=1,
                same_ip_count=1 if src_ip else 0,
            )
            session.add(association)
        else:
            association.co_occurrence_count += 1
            association.same_session_count += 1
            if src_ip:
                association.same_ip_count += 1


def _update_session_summaries(session: Session, session_ids: set[str]) -> None:
    """Update session summaries with SSH key counts.
    
    Args:
        session: Database session
        session_ids: Set of session IDs to update
    """
    for session_id in session_ids:
        # Count SSH key injections and unique keys for this session
        key_stats = session.query(
            func.count(SessionSSHKeys.id).label("injection_count"),
            func.count(func.distinct(SessionSSHKeys.ssh_key_id)).label("unique_key_count")
        ).filter(SessionSSHKeys.session_id == session_id).first()
        
        if key_stats:
            # Update session summary
            session.query(SessionSummary).filter(
                SessionSummary.session_id == session_id
            ).update({
                "ssh_key_injections": key_stats.injection_count,
                "unique_ssh_keys": key_stats.unique_key_count,
                "updated_at": datetime.now(UTC),
            })


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
                export_data.append({
                    "key_type": key.key_type,
                    "key_fingerprint": key.key_fingerprint,
                    "key_hash": key.key_hash,
                    "key_comment": key.key_comment,
                    "key_size_bits": key.key_size_bits,
                    "first_seen": key.first_seen.isoformat() if key.first_seen else None,
                    "last_seen": key.last_seen.isoformat() if key.last_seen else None,
                    "total_attempts": key.total_attempts,
                    "unique_sources": key.unique_sources,
                    "unique_sessions": key.unique_sessions,
                })
                
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
    export_parser.add_argument('--format', type=str, choices=['json', 'csv'], default='json', help='Output format (default: json)')
    export_parser.add_argument('--output', type=str, help='Output file (default: stdout)')
    export_parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    
    export_parser.set_defaults(func=export_ssh_keys)
    
    # Parse arguments
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
        
    # Validate end_date if start_date is provided
    if hasattr(args, 'start_date') and args.start_date and not args.end_date:
        parser.error("--end-date is required when --start-date is used")
        
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
