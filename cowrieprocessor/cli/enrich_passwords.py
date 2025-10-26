"""CLI for enriching sessions with HIBP password breach data."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy import and_, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from tqdm import tqdm

from ..db import apply_migrations, create_engine_from_settings, create_session_maker
from ..db.models import PasswordSessionUsage, PasswordStatistics, PasswordTracking, RawEvent, SessionSummary
from ..enrichment.cache import EnrichmentCacheManager
from ..enrichment.hibp_client import HIBPPasswordEnricher
from ..enrichment.password_extractor import PasswordExtractor
from ..enrichment.rate_limiting import RateLimitedSession, get_service_rate_limit
from ..status_emitter import StatusEmitter
from .db_config import resolve_database_settings

logger = logging.getLogger(__name__)


def _sanitize_text_for_postgres(text: str, max_length: int | None = None) -> str:
    """Sanitize text for PostgreSQL storage.

    PostgreSQL TEXT and VARCHAR fields cannot contain NUL (0x00) bytes. This function
    removes NUL bytes and optionally truncates to a maximum length.

    Args:
        text: Raw text string that may contain NUL bytes
        max_length: Optional maximum length to truncate to (e.g., 256 for VARCHAR(256))

    Returns:
        Sanitized text string safe for PostgreSQL storage
    """
    # Replace NUL bytes with escape sequence for visibility
    if '\x00' in text:
        text = text.replace('\x00', '\\x00')

    # Truncate if needed
    if max_length is not None and len(text) > max_length:
        # Leave room for ellipsis
        text = text[: max_length - 3] + '...'

    return text


def _parse_date(date_str: str) -> datetime:
    """Parse date string to datetime.

    Args:
        date_str: Date string in YYYY-MM-DD format

    Returns:
        Datetime object

    Raises:
        ValueError: If date format is invalid
    """
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as e:
        raise ValueError(f"Invalid date format: {date_str}. Use YYYY-MM-DD") from e


def _query_sessions(
    session: Session,
    start_date: datetime,
    end_date: datetime,
    sensor: Optional[str] = None,
    force: bool = False,
) -> List[SessionSummary]:
    """Query sessions for password enrichment.

    Args:
        session: Database session
        start_date: Start of date range
        end_date: End of date range
        sensor: Optional sensor filter
        force: If True, include already-enriched sessions

    Returns:
        List of SessionSummary objects
    """
    query = session.query(SessionSummary).filter(
        and_(
            SessionSummary.first_event_at >= start_date,
            SessionSummary.first_event_at < end_date,
            SessionSummary.login_attempts > 0,  # Only sessions with login attempts
        )
    )

    if sensor:
        # Filter by sensor if matcher contains the sensor name
        query = query.filter(SessionSummary.matcher.like(f'%{sensor}%'))

    # Fetch all sessions and filter in Python for database agnosticism
    all_sessions = query.all()

    if not force:
        # Skip sessions that already have password_stats
        filtered_sessions = [s for s in all_sessions if not s.enrichment or 'password_stats' not in s.enrichment]
        return filtered_sessions

    return all_sessions


def _load_session_events(
    session: Session,
    session_id: str,
) -> List[RawEvent]:
    """Load raw events for a session.

    Args:
        session: Database session
        session_id: Session ID to load events for

    Returns:
        List of RawEvent objects
    """
    return session.query(RawEvent).filter(RawEvent.session_id == session_id).order_by(RawEvent.id).all()


def _track_password(
    db_session: Session,
    password: str,
    password_sha256: str,
    hibp_result: Dict[str, Any],
    session_id: str,
    username: str,
    success: bool,
    timestamp: str,
) -> int:
    """Track password in password_tracking table and create junction record.

    Args:
        db_session: Database session
        password: The actual password text
        password_sha256: SHA-256 hash of password
        hibp_result: HIBP check result
        session_id: Session ID
        username: Username from login attempt
        success: Whether login was successful
        timestamp: Timestamp of attempt

    Returns:
        Password tracking ID
    """
    # Try to parse timestamp
    try:
        timestamp_dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        timestamp_dt = datetime.now(UTC)

    # Upsert password_tracking record
    existing = db_session.query(PasswordTracking).filter(PasswordTracking.password_hash == password_sha256).first()

    if existing:
        # Update existing record
        existing.last_seen = timestamp_dt  # type: ignore[assignment]
        existing.times_seen += 1  # type: ignore[assignment]
        existing.last_hibp_check = datetime.now(UTC)  # type: ignore[assignment]
        existing.updated_at = datetime.now(UTC)  # type: ignore[assignment]

        # Update breach info if it changed
        if existing.breached != hibp_result['breached']:
            existing.breached = hibp_result['breached']
            existing.breach_prevalence = hibp_result.get('prevalence')  # type: ignore[assignment]

        password_id = existing.id
    else:
        # Create new record with sanitized password text
        sanitized_password = _sanitize_text_for_postgres(password)
        new_password = PasswordTracking(
            password_hash=password_sha256,
            password_text=sanitized_password,
            breached=hibp_result['breached'],
            breach_prevalence=hibp_result.get('prevalence'),
            last_hibp_check=datetime.now(UTC),
            first_seen=timestamp_dt,
            last_seen=timestamp_dt,
            times_seen=1,
            unique_sessions=1,
        )
        db_session.add(new_password)
        db_session.flush()  # Get the ID
        password_id = new_password.id

    # Create password_session_usage junction record (if not exists)
    usage_record = next(
        (
            obj
            for obj in db_session.new
            if isinstance(obj, PasswordSessionUsage) and obj.password_id == password_id and obj.session_id == session_id
        ),
        None,
    )

    if usage_record is None:
        usage_record = (
            db_session.query(PasswordSessionUsage)
            .filter(
                and_(
                    PasswordSessionUsage.password_id == password_id,
                    PasswordSessionUsage.session_id == session_id,
                )
            )
            .first()
        )

    sanitized_username = _sanitize_text_for_postgres(username, max_length=256)

    if usage_record:
        # Update existing usage entry with the latest information
        if success and not usage_record.success:
            usage_record.success = True  # type: ignore[assignment]
        if sanitized_username and not usage_record.username:
            usage_record.username = sanitized_username  # type: ignore[assignment]
        if usage_record.timestamp is None or timestamp_dt > usage_record.timestamp:
            usage_record.timestamp = timestamp_dt  # type: ignore[assignment]
    else:
        usage_record = PasswordSessionUsage(
            password_id=password_id,
            session_id=session_id,
            username=sanitized_username,
            success=success,
            timestamp=timestamp_dt,
        )
        db_session.add(usage_record)

        # Increment unique_sessions counter for existing passwords
        if existing:
            existing.unique_sessions += 1  # type: ignore[assignment]

    return int(password_id)


def _enrich_session(
    db_session: Session,
    session_summary: SessionSummary,
    events: List[RawEvent],
    password_extractor: PasswordExtractor,
    hibp_enricher: HIBPPasswordEnricher,
) -> Dict[str, Any]:
    """Enrich a session with password breach data.

    Args:
        db_session: Database session
        session_summary: SessionSummary object
        events: List of RawEvent objects
        password_extractor: PasswordExtractor instance
        hibp_enricher: HIBPPasswordEnricher instance

    Returns:
        Password statistics dictionary
    """
    # Extract passwords from events
    password_attempts = password_extractor.extract_from_events(events)

    if not password_attempts:
        return {
            'total_attempts': 0,
            'unique_passwords': 0,
            'breached_passwords': 0,
            'breach_prevalence_max': 0,
            'novel_password_hashes': [],
            'password_details': [],
        }

    # Track unique passwords and check HIBP
    checked_passwords: Dict[str, Dict[str, Any]] = {}
    password_details = []

    for attempt in password_attempts:
        password = attempt['password']
        password_sha256 = attempt['password_sha256']

        # Check if we've already checked this password
        if password not in checked_passwords:
            hibp_result = hibp_enricher.check_password(password)
            checked_passwords[password] = hibp_result
        else:
            hibp_result = checked_passwords[password]

        # Track password in password_tracking and junction table
        try:
            _track_password(
                db_session=db_session,
                password=password,
                password_sha256=password_sha256,
                hibp_result=hibp_result,
                session_id=str(session_summary.session_id),
                username=attempt['username'],
                success=attempt['success'],
                timestamp=attempt['timestamp'],
            )
        except Exception as e:
            logger.warning(f"Failed to track password: {e}")
            # Rollback the session to recover from any database errors
            db_session.rollback()

        # Add password detail entry
        password_details.append(
            {
                'username': attempt['username'],
                'password_sha256': password_sha256,
                'breached': hibp_result['breached'],
                'prevalence': hibp_result['prevalence'],
                'success': attempt['success'],
                'timestamp': attempt['timestamp'],
            }
        )

    # Calculate statistics
    unique_passwords = len(checked_passwords)
    breached_passwords = sum(1 for r in checked_passwords.values() if r['breached'])
    breach_prevalence_max = max((r['prevalence'] for r in checked_passwords.values() if r['breached']), default=0)
    novel_password_hashes = [
        password_sha256 for attempt in password_attempts if not checked_passwords[attempt['password']]['breached']
    ]

    return {
        'total_attempts': len(password_attempts),
        'unique_passwords': unique_passwords,
        'breached_passwords': breached_passwords,
        'breach_prevalence_max': breach_prevalence_max,
        'novel_password_hashes': list(set(novel_password_hashes)),
        'password_details': password_details,
    }


def _update_session_enrichment(
    db_session: Session,
    session_id: str,
    password_stats: Dict[str, Any],
) -> None:
    """Update SessionSummary with password statistics.

    Args:
        db_session: Database session
        session_id: Session ID to update
        password_stats: Password statistics dictionary
    """
    # Load existing enrichment or create new
    session_summary = db_session.query(SessionSummary).filter(SessionSummary.session_id == session_id).first()

    if not session_summary:
        logger.warning(f"Session {session_id} not found")
        return

    enrichment: Dict[str, Any] = session_summary.enrichment or {}  # type: ignore[assignment]
    enrichment['password_stats'] = password_stats

    # Update the session
    db_session.execute(
        update(SessionSummary).where(SessionSummary.session_id == session_id).values(enrichment=enrichment)
    )


def _aggregate_daily_stats(
    db_session: Session,
    target_date: date,
) -> None:
    """Aggregate password statistics for a specific date.

    Args:
        db_session: Database session
        target_date: Date to aggregate statistics for
    """
    # Query all sessions for this date with password stats
    start_datetime = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=UTC)
    end_datetime = start_datetime + timedelta(days=1)

    # Fetch sessions and filter in Python for database agnosticism
    all_sessions = (
        db_session.query(SessionSummary)
        .filter(
            and_(
                SessionSummary.first_event_at >= start_datetime,
                SessionSummary.first_event_at < end_datetime,
            )
        )
        .all()
    )

    # Filter to sessions with password_stats
    sessions = [s for s in all_sessions if s.enrichment and 'password_stats' in s.enrichment]

    if not sessions:
        return

    # Aggregate statistics
    total_attempts = 0
    unique_passwords_set = set()
    breached_count = 0
    novel_count = 0
    max_prevalence = 0

    for session_summary in sessions:
        if not session_summary.enrichment:
            continue

        pwd_stats = session_summary.enrichment.get('password_stats', {})
        total_attempts += pwd_stats.get('total_attempts', 0)
        breached_count += pwd_stats.get('breached_passwords', 0)
        novel_count += len(pwd_stats.get('novel_password_hashes', []))
        max_prevalence = max(max_prevalence, pwd_stats.get('breach_prevalence_max', 0))

        # Track unique passwords across all sessions (by hash)
        for detail in pwd_stats.get('password_details', []):
            unique_passwords_set.add(detail.get('password_sha256', ''))

    # Insert or update daily statistics
    existing = db_session.query(PasswordStatistics).filter(PasswordStatistics.date == target_date).first()

    if existing:
        existing.total_attempts = total_attempts  # type: ignore[assignment]
        existing.unique_passwords = len(unique_passwords_set)  # type: ignore[assignment]
        existing.breached_count = breached_count  # type: ignore[assignment]
        existing.novel_count = novel_count  # type: ignore[assignment]
        existing.max_prevalence = max_prevalence if max_prevalence > 0 else None  # type: ignore[assignment]
        existing.updated_at = datetime.now(UTC)  # type: ignore[assignment]
    else:
        daily_stats = PasswordStatistics(
            date=target_date,
            total_attempts=total_attempts,
            unique_passwords=len(unique_passwords_set),
            breached_count=breached_count,
            novel_count=novel_count,
            max_prevalence=max_prevalence if max_prevalence > 0 else None,
        )
        db_session.add(daily_stats)


def prune_old_passwords(args: argparse.Namespace) -> int:
    """Prune passwords not seen in specified number of days.

    Args:
        args: Parsed command line arguments

    Returns:
        Exit code (0 for success)
    """
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )

    try:
        retention_days = args.retention_days
        logger.info(f"Pruning passwords not seen in {retention_days} days")

        # Resolve database settings
        db_settings = resolve_database_settings(args.database)
        engine = create_engine_from_settings(db_settings)
        session_maker = create_session_maker(engine)

        with session_maker() as db_session:
            cutoff_date = datetime.now(UTC) - timedelta(days=retention_days)

            # Query passwords to delete
            passwords_to_delete = (
                db_session.query(PasswordTracking).filter(PasswordTracking.last_seen < cutoff_date).all()
            )

            count = len(passwords_to_delete)

            if count == 0:
                print(f"No passwords to prune (all passwords seen within {retention_days} days)")
                return 0

            # Delete passwords (cascade will delete junction records)
            for pwd in passwords_to_delete:
                db_session.delete(pwd)

            db_session.commit()

            print(f"Pruned {count} passwords not seen since {cutoff_date.date()}")
            logger.info(f"Pruned {count} passwords")

            return 0

    except Exception as e:
        logger.error(f"Pruning failed: {e}", exc_info=True)
        return 1


def show_top_passwords(args: argparse.Namespace) -> int:
    """Show most-used passwords in time period.

    Args:
        args: Parsed command line arguments

    Returns:
        Exit code (0 for success)
    """
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )

    try:
        limit = args.limit

        # Parse date range
        if args.last_days:
            end_date = datetime.now(UTC)
            start_date = end_date - timedelta(days=args.last_days)
        elif args.start_date and args.end_date:
            start_date = _parse_date(args.start_date)
            end_date = _parse_date(args.end_date)
        else:
            # Default to last 30 days
            end_date = datetime.now(UTC)
            start_date = end_date - timedelta(days=30)

        logger.info(f"Querying top passwords from {start_date.date()} to {end_date.date()}")

        # Resolve database settings
        db_settings = resolve_database_settings(args.database)
        engine = create_engine_from_settings(db_settings)
        session_maker = create_session_maker(engine)

        with session_maker() as db_session:
            # Query passwords with usage counts in time period
            results = (
                db_session.query(
                    PasswordTracking.password_text,
                    PasswordTracking.breached,
                    PasswordTracking.breach_prevalence,
                    PasswordTracking.times_seen,
                    PasswordTracking.unique_sessions,
                    PasswordTracking.first_seen,
                    PasswordTracking.last_seen,
                )
                .filter(
                    and_(
                        PasswordTracking.last_seen >= start_date,
                        PasswordTracking.last_seen <= end_date,
                    )
                )
                .order_by(PasswordTracking.times_seen.desc())
                .limit(limit)
                .all()
            )

            if not results:
                print(f"No passwords found in time period {start_date.date()} to {end_date.date()}")
                return 0

            print(f"\nTop {limit} Most-Used Passwords ({start_date.date()} to {end_date.date()}):")
            print("=" * 100)
            print(f"{'Password':<30} {'Times Seen':<12} {'Sessions':<10} {'Breached':<10} {'Prevalence':<15}")
            print("-" * 100)

            for row in results:
                password = row[0][:30] if len(row[0]) <= 30 else row[0][:27] + "..."
                breached_str = "Yes" if row[1] else "No"
                prevalence_str = f"{row[2]:,}" if row[2] else "N/A"

                print(f"{password:<30} {row[3]:<12} {row[4]:<10} {breached_str:<10} {prevalence_str:<15}")

            print("=" * 100)

            return 0

    except Exception as e:
        logger.error(f"Top passwords query failed: {e}", exc_info=True)
        return 1


def show_new_passwords(args: argparse.Namespace) -> int:
    """Show newly emerged passwords in time period.

    Args:
        args: Parsed command line arguments

    Returns:
        Exit code (0 for success)
    """
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )

    try:
        limit = args.limit

        # Parse date range
        if args.last_days:
            end_date = datetime.now(UTC)
            start_date = end_date - timedelta(days=args.last_days)
        elif args.start_date and args.end_date:
            start_date = _parse_date(args.start_date)
            end_date = _parse_date(args.end_date)
        else:
            # Default to last 7 days
            end_date = datetime.now(UTC)
            start_date = end_date - timedelta(days=7)

        logger.info(f"Querying new passwords from {start_date.date()} to {end_date.date()}")

        # Resolve database settings
        db_settings = resolve_database_settings(args.database)
        engine = create_engine_from_settings(db_settings)
        session_maker = create_session_maker(engine)

        with session_maker() as db_session:
            # Query passwords first seen in time period
            results = (
                db_session.query(
                    PasswordTracking.password_text,
                    PasswordTracking.breached,
                    PasswordTracking.breach_prevalence,
                    PasswordTracking.times_seen,
                    PasswordTracking.unique_sessions,
                    PasswordTracking.first_seen,
                )
                .filter(
                    and_(
                        PasswordTracking.first_seen >= start_date,
                        PasswordTracking.first_seen <= end_date,
                    )
                )
                .order_by(PasswordTracking.first_seen.desc())
                .limit(limit)
                .all()
            )

            if not results:
                print(f"No new passwords found in time period {start_date.date()} to {end_date.date()}")
                return 0

            print(f"\nNew Passwords ({start_date.date()} to {end_date.date()}):")
            print("=" * 100)
            print(f"{'Password':<30} {'First Seen':<20} {'Times Seen':<12} {'Breached':<10} {'Prevalence':<15}")
            print("-" * 100)

            for row in results:
                password = row[0][:30] if len(row[0]) <= 30 else row[0][:27] + "..."
                first_seen_str = row[5].strftime("%Y-%m-%d %H:%M:%S") if row[5] else "N/A"
                breached_str = "Yes" if row[1] else "No"
                prevalence_str = f"{row[2]:,}" if row[2] else "N/A"

                print(f"{password:<30} {first_seen_str:<20} {row[3]:<12} {breached_str:<10} {prevalence_str:<15}")

            print("=" * 100)

            return 0

    except Exception as e:
        logger.error(f"New passwords query failed: {e}", exc_info=True)
        return 1


def enrich_passwords(args: argparse.Namespace) -> int:
    """Enrich sessions with HIBP password breach data.

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
        if args.last_days:
            end_date = datetime.now(UTC)
            start_date = end_date - timedelta(days=args.last_days)
        elif args.start_date and args.end_date:
            start_date = _parse_date(args.start_date)
            end_date = _parse_date(args.end_date)
        else:
            logger.error("Either --last-days or --start-date/--end-date must be specified")
            return 1

        logger.info(f"Enriching sessions from {start_date.date()} to {end_date.date()}")

        # Resolve database settings
        db_settings = resolve_database_settings(args.database)

        # Create engine and apply migrations
        engine = create_engine_from_settings(db_settings)
        current_version = apply_migrations(engine)
        logger.info(f"Database schema version: {current_version}")

        if current_version < 10:
            logger.error("Database schema must be v10 or higher for password enrichment")
            return 1

        session_maker = create_session_maker(engine)

        # Initialize enrichment components
        cache_dir = Path(args.cache_dir)
        cache_manager = EnrichmentCacheManager(base_dir=cache_dir)

        rate, burst = get_service_rate_limit("hibp")
        rate_limiter = RateLimitedSession(rate_limit=rate, burst=burst)

        hibp_enricher = HIBPPasswordEnricher(cache_manager, rate_limiter)
        password_extractor = PasswordExtractor()

        # Initialize status emitter
        status_dir = Path(args.status_dir) if args.status_dir else None
        status_emitter = StatusEmitter("password_enrichment", status_dir=status_dir) if status_dir else None

        # Query sessions to enrich
        with session_maker() as db_session:
            sessions_to_enrich = _query_sessions(
                db_session,
                start_date,
                end_date,
                sensor=args.sensor,
                force=args.force,
            )

            logger.info(f"Found {len(sessions_to_enrich)} sessions to enrich")

            if not sessions_to_enrich:
                logger.info("No sessions to enrich")
                return 0

            # Track dates for daily aggregation
            dates_to_aggregate = set()

            # Process sessions with progress bar
            enriched_count = 0
            error_count = 0

            for session_summary in tqdm(sessions_to_enrich, desc="Enriching sessions", disable=not args.progress):
                try:
                    # Load events
                    events = _load_session_events(db_session, session_summary.session_id)

                    # Enrich with password data
                    password_stats = _enrich_session(
                        db_session,
                        session_summary,
                        events,
                        password_extractor,
                        hibp_enricher,
                    )

                    # Update session enrichment
                    _update_session_enrichment(
                        db_session,
                        session_summary.session_id,
                        password_stats,
                    )

                    # Track date for aggregation
                    if session_summary.first_event_at:
                        dates_to_aggregate.add(session_summary.first_event_at.date())

                    enriched_count += 1

                    # Commit in batches
                    if enriched_count % args.batch_size == 0:
                        db_session.commit()
                        if status_emitter:
                            status_emitter.record_checkpoint(
                                {
                                    'enriched_sessions': enriched_count,
                                    'errors': error_count,
                                    'hibp_stats': hibp_enricher.get_stats(),
                                }
                            )

                except Exception as e:
                    logger.error(f"Failed to enrich session {session_summary.session_id}: {e}")
                    error_count += 1
                    db_session.rollback()
                    continue

            # Final commit
            db_session.commit()

            # Aggregate daily statistics
            logger.info(f"Aggregating daily statistics for {len(dates_to_aggregate)} dates")
            for target_date in sorted(dates_to_aggregate):
                try:
                    _aggregate_daily_stats(db_session, target_date)
                except Exception as e:
                    logger.error(f"Failed to aggregate statistics for {target_date}: {e}")

            db_session.commit()

        # Print summary
        print("\nPassword Enrichment Summary:")
        print(f"  Sessions enriched: {enriched_count}")
        print(f"  Errors: {error_count}")
        print(f"  Dates aggregated: {len(dates_to_aggregate)}")

        hibp_stats = hibp_enricher.get_stats()
        print("\nHIBP Statistics:")
        print(f"  Password checks: {hibp_stats['checks']}")
        print(f"  Cache hits: {hibp_stats['cache_hits']}")
        print(f"  Cache misses: {hibp_stats['cache_misses']}")
        print(f"  API calls: {hibp_stats['api_calls']}")
        print(f"  Breached passwords found: {hibp_stats['breached_found']}")
        print(f"  Errors: {hibp_stats['errors']}")

        if hibp_stats['checks'] > 0:
            cache_hit_rate = (hibp_stats['cache_hits'] / hibp_stats['checks']) * 100
            print(f"  Cache hit rate: {cache_hit_rate:.1f}%")

        if status_emitter:
            status_emitter.record_checkpoint(
                {
                    'enriched_sessions': enriched_count,
                    'errors': error_count,
                    'hibp_stats': hibp_stats,
                    'dates_aggregated': len(dates_to_aggregate),
                    'completed': True,
                }
            )

        return 0

    except Exception as e:
        logger.error(f"Password enrichment failed: {e}", exc_info=True)
        return 1


def get_session_query(engine: Engine) -> str:
    """Get session query with dialect-aware JSON extraction for enrichment refresh."""
    from ..db.json_utils import get_dialect_name_from_engine

    dialect_name = get_dialect_name_from_engine(engine)

    if dialect_name == "postgresql":
        # For PostgreSQL, we'll use a Python-based approach to safely extract IPs
        # This avoids the Unicode corruption issues in the raw_events payload
        return """
            SELECT ss.session_id,
                   '192.168.1.1' AS src_ip
            FROM session_summaries ss
            WHERE (ss.enrichment IS NULL 
                   OR ss.enrichment::text = 'null'
                   OR ss.enrichment::text = '{}'
                   OR ss.enrichment::text = '')
            ORDER BY ss.last_event_at ASC, ss.session_id ASC
        """
    else:
        return """
            SELECT ss.session_id,
                   MAX(json_extract(re.payload, '$.src_ip')) AS src_ip
            FROM session_summaries ss
            JOIN raw_events re ON re.session_id = ss.session_id
            WHERE json_extract(re.payload, '$.src_ip') IS NOT NULL
              AND json_extract(re.payload, '$.src_ip') != ''
              AND length(json_extract(re.payload, '$.src_ip')) > 0
              AND (ss.enrichment IS NULL 
                   OR ss.enrichment = 'null'
                   OR ss.enrichment = '{}'
                   OR ss.enrichment = '')
            GROUP BY ss.session_id
            ORDER BY ss.last_event_at ASC, ss.session_id ASC
        """


def get_file_query() -> str:
    """Get file query for enrichment refresh."""
    return """
        SELECT DISTINCT shasum, filename, session_id, first_seen
        FROM files
        WHERE shasum IS NOT NULL AND shasum != ''
          AND enrichment_status IN ('pending', 'failed')
        ORDER BY first_seen ASC
    """


def _extract_ip_from_raw_events(engine: Engine, session_id: str) -> Optional[str]:
    """Safely extract source IP from raw_events using Unicode sanitizer."""
    from ..db.json_utils import get_dialect_name_from_engine
    from ..utils.unicode_sanitizer import UnicodeSanitizer

    dialect_name = get_dialect_name_from_engine(engine)

    try:
        with engine.connect() as conn:
            if dialect_name == "postgresql":
                # For PostgreSQL, get the raw payload and sanitize it
                query = """
                    SELECT payload FROM raw_events 
                    WHERE session_id = :session_id 
                    AND payload::text LIKE '%src_ip%'
                    LIMIT 1
                """
                result = conn.execute(text(query), {"session_id": session_id}).fetchone()
                if result and result[0]:
                    payload = result[0]
                    if isinstance(payload, dict):
                        return payload.get('src_ip')
                    elif isinstance(payload, str):
                        # Try to sanitize and parse the JSON
                        sanitized = UnicodeSanitizer.sanitize_json_string(payload)
                        try:
                            parsed = json.loads(sanitized)
                            parsed_result: str | None = parsed.get('src_ip')
                            return parsed_result
                        except (json.JSONDecodeError, ValueError):
                            pass
            else:
                # For SQLite, use json_extract
                query = """
                    SELECT json_extract(payload, '$.src_ip') as src_ip
                    FROM raw_events 
                    WHERE session_id = :session_id 
                    AND json_extract(payload, '$.src_ip') IS NOT NULL
                    LIMIT 1
                """
                result = conn.execute(text(query), {"session_id": session_id}).fetchone()
                if result and result[0]:
                    result_value: str | None = str(result[0])
                    return result_value
    except Exception as e:
        logger.debug(f"Failed to extract IP for session {session_id}: {e}")

    return None


def iter_sessions(engine: Engine, limit: int) -> Iterator[tuple[str, str]]:
    """Yield session IDs and source IPs in FIFO order."""
    from ..db.json_utils import get_dialect_name_from_engine

    dialect_name = get_dialect_name_from_engine(engine)
    query = get_session_query(engine)
    if limit > 0:
        query += f" LIMIT {limit}"

    try:
        with engine.connect() as conn:
            for row in conn.execute(text(query)):
                session_id, fallback_ip = row
                if session_id:
                    # For PostgreSQL, try to extract real IP from raw_events
                    if dialect_name == "postgresql" and fallback_ip == "192.168.1.1":
                        real_ip = _extract_ip_from_raw_events(engine, session_id)
                        src_ip = real_ip if real_ip else fallback_ip
                    else:
                        src_ip = fallback_ip

                    if src_ip:
                        yield session_id, src_ip
    except Exception as e:
        logger.error(f"Error querying sessions: {e}")
        logger.error("This may indicate missing tables or database schema issues.")
        return


def iter_files(engine: Engine, limit: int) -> Iterator[tuple[str, Optional[str], str]]:
    """Yield file hashes, filenames, and session IDs up to the requested limit."""
    query = get_file_query()
    if limit > 0:
        query += f" LIMIT {limit}"

    try:
        with engine.connect() as conn:
            for row in conn.execute(text(query)):
                shasum, filename, session_id, first_seen = row
                if shasum:
                    yield shasum, filename, session_id
    except Exception as e:
        logger.error(f"Error querying files: {e}")
        logger.error("This may indicate missing tables or database schema issues.")
        return


def table_exists(engine: Engine, table_name: str) -> bool:
    """Return True when ``table_name`` is present in the database."""
    from ..db.json_utils import get_dialect_name_from_engine

    dialect_name = get_dialect_name_from_engine(engine)

    if dialect_name == "postgresql":
        query = """
            SELECT 1 FROM information_schema.tables 
            WHERE table_name = :table_name
        """
    else:
        query = """
            SELECT 1 FROM sqlite_master 
            WHERE type='table' AND name = :table_name
        """

    with engine.connect() as conn:
        result = conn.execute(text(query), {"table_name": table_name}).fetchone()
        return result is not None


def update_session(
    engine: Engine,
    session_id: str,
    enrichment_payload: dict,
    flags: dict,
) -> None:
    """Persist refreshed enrichment JSON and derived flags for a session.

    This function merges the new enrichment data with existing enrichment data
    to avoid overwriting data from other enrichment modules (e.g., password_stats).
    """
    # First, get the existing enrichment data
    get_sql = """
        SELECT enrichment FROM session_summaries 
        WHERE session_id = :session_id
    """

    with engine.connect() as conn:
        # Get existing enrichment data
        result = conn.execute(text(get_sql), {"session_id": session_id}).fetchone()
        existing_enrichment = {}

        if result and result[0]:
            try:
                existing_enrichment = json.loads(result[0]) if isinstance(result[0], str) else result[0]
            except (json.JSONDecodeError, TypeError):
                # If we can't parse the existing data, start fresh
                existing_enrichment = {}

        # Merge the new enrichment data with existing data
        # New data takes precedence over existing data for the same keys
        merged_enrichment = existing_enrichment.copy()
        if enrichment_payload:
            merged_enrichment.update(enrichment_payload)

        # Update the session with merged enrichment data
        update_sql = """
            UPDATE session_summaries
            SET enrichment = :enrichment,
                vt_flagged = :vt_flagged,
                dshield_flagged = :dshield_flagged,
                updated_at = CURRENT_TIMESTAMP
            WHERE session_id = :session_id
        """

        conn.execute(
            text(update_sql),
            {
                "enrichment": json.dumps(merged_enrichment) if merged_enrichment else None,
                "vt_flagged": bool(flags.get("vt_flagged")),
                "dshield_flagged": bool(flags.get("dshield_flagged")),
                "session_id": session_id,
            },
        )
        conn.commit()


def update_file(
    engine: Engine,
    file_hash: str,
    enrichment_payload: dict,
) -> None:
    """Persist refreshed VirusTotal fields for a given file hash."""
    vt_data = enrichment_payload.get("virustotal") if isinstance(enrichment_payload, dict) else None
    if vt_data is None:
        # Mark as failed if no VT data
        sql = "UPDATE files SET enrichment_status = 'failed' WHERE shasum = :file_hash"
        with engine.connect() as conn:
            conn.execute(text(sql), {"file_hash": file_hash})
            conn.commit()
        return

    attributes = vt_data.get("data", {}).get("attributes", {}) if isinstance(vt_data, dict) else {}
    classification = attributes.get("popular_threat_classification", {})
    last_analysis = attributes.get("last_analysis_stats", {})

    # Extract VT data with proper type conversion
    vt_classification = classification.get("suggested_threat_label") if isinstance(classification, dict) else None
    vt_description = attributes.get("type_description")
    vt_malicious = bool(last_analysis.get("malicious", 0) > 0) if isinstance(last_analysis, dict) else False
    vt_positives = last_analysis.get("malicious", 0) if isinstance(last_analysis, dict) else 0
    # Sum only numeric values from last_analysis, skip any dict values
    if isinstance(last_analysis, dict):
        vt_total = sum(value for value in last_analysis.values() if isinstance(value, (int, float)))
    else:
        vt_total = 0

    # Parse timestamps
    vt_first_seen = None
    vt_last_analysis = None
    vt_scan_date = None

    if attributes.get("first_submission_date"):
        try:
            vt_first_seen = datetime.fromtimestamp(int(attributes["first_submission_date"]))
        except (ValueError, TypeError):
            pass

    if attributes.get("last_analysis_date"):
        try:
            vt_last_analysis = datetime.fromtimestamp(int(attributes["last_analysis_date"]))
            vt_scan_date = vt_last_analysis
        except (ValueError, TypeError):
            pass

    sql = """
        UPDATE files
        SET vt_classification = :vt_classification,
            vt_description = :vt_description,
            vt_malicious = :vt_malicious,
            vt_first_seen = :vt_first_seen,
            vt_last_analysis = :vt_last_analysis,
            vt_positives = :vt_positives,
            vt_total = :vt_total,
            vt_scan_date = :vt_scan_date,
            enrichment_status = 'enriched',
            last_updated = CURRENT_TIMESTAMP
        WHERE shasum = :file_hash
    """
    with engine.connect() as conn:
        conn.execute(
            text(sql),
            {
                "vt_classification": vt_classification,
                "vt_description": vt_description,
                "vt_malicious": vt_malicious,
                "vt_first_seen": vt_first_seen,
                "vt_last_analysis": vt_last_analysis,
                "vt_positives": vt_positives,
                "vt_total": vt_total,
                "vt_scan_date": vt_scan_date,
                "file_hash": file_hash,
            },
        )
        conn.commit()


def track_enrichment_stats(enrichment: Any, stats: dict) -> None:
    """Track enrichment service usage and failures."""
    if not isinstance(enrichment, dict):
        return

    # Track DShield usage
    dshield_data = enrichment.get("dshield", {})
    if dshield_data and dshield_data.get("ip", {}).get("asname", ""):
        stats["dshield_calls"] += 1
    elif dshield_data and dshield_data.get("error"):
        stats["dshield_failures"] += 1

    # Track URLHaus usage
    urlhaus_data = enrichment.get("urlhaus", "")
    if urlhaus_data and urlhaus_data != "":
        stats["urlhaus_calls"] += 1

    # Track SPUR usage
    spur_data = enrichment.get("spur", [])
    if spur_data and len(spur_data) > 0 and spur_data != ["", "", ""]:
        stats["spur_calls"] += 1

    # Track VirusTotal usage
    vt_data = enrichment.get("virustotal")
    if vt_data and isinstance(vt_data, dict) and vt_data.get("data"):
        stats["virustotal_calls"] += 1
    elif vt_data is None and enrichment.get("virustotal") is None:
        # This indicates VT was called but returned no data (not necessarily a failure)
        pass


def load_sensor_credentials(sensor_file: Path, sensor_index: int) -> dict[str, Optional[str]]:
    """Load API credentials from a sensors.toml configuration file."""
    if not sensor_file.exists():
        raise RuntimeError(f"Sensors file not found: {sensor_file}")

    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:
        raise RuntimeError("Python 3.11+ is required for sensors.toml support")

    with sensor_file.open("rb") as handle:
        data = tomllib.load(handle)
    sensors = data.get("sensor") or []
    if not sensors:
        raise RuntimeError("No sensors defined in sensors file")
    if sensor_index >= len(sensors):
        raise RuntimeError(f"Sensor index {sensor_index} out of range (found {len(sensors)})")
    sensor = sensors[sensor_index]
    return {
        "vt_api": sensor.get("vtapi"),
        "dshield_email": sensor.get("email"),
        "urlhaus_api": sensor.get("urlhausapi"),
        "spur_api": sensor.get("spurapi"),
    }


def refresh_enrichment(args: argparse.Namespace) -> int:
    """Refresh enrichment data for existing sessions and files."""
    # Set up logging
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )

    logger.info("Starting enrichment refresh...")

    # Load database settings
    db_settings = resolve_database_settings(args.database)
    engine = create_engine_from_settings(db_settings)

    # Apply migrations to ensure schema is up to date
    apply_migrations(engine)

    # Resolve API credentials from command line, environment, or sensors.toml
    resolved_credentials = {
        "vt_api": args.vt_api_key or os.getenv("VT_API_KEY"),
        "dshield_email": args.dshield_email or os.getenv("DSHIELD_EMAIL"),
        "urlhaus_api": args.urlhaus_api_key or os.getenv("URLHAUS_API_KEY"),
        "spur_api": args.spur_api_key or os.getenv("SPUR_API_KEY"),
    }

    # If no credentials provided via command line or environment, try to load from sensors.toml
    if not any(resolved_credentials.values()):
        try:
            # Look for sensors.toml in the project root (config/ first, then root)
            from pathlib import Path

            project_root = Path(__file__).resolve().parents[2]
            sensors_file = project_root / "config" / "sensors.toml"
            if not sensors_file.exists():
                sensors_file = project_root / "sensors.toml"

            if sensors_file.exists():
                logger.info(f"Loading API credentials from {sensors_file}")
                creds = load_sensor_credentials(sensors_file, 0)  # Use first sensor by default
                resolved_credentials.update({k: v for k, v in creds.items() if v})
            else:
                logger.warning("No sensors.toml file found in project root")
        except Exception as e:
            logger.warning(f"Failed to load credentials from sensors.toml: {e}")
    else:
        # For any missing individual credential, try to fill from sensors file if available
        try:
            from pathlib import Path

            project_root = Path(__file__).resolve().parents[2]
            sensors_file = project_root / "sensors.toml"

            if sensors_file.exists():
                creds = load_sensor_credentials(sensors_file, 0)
                for key in ("vt_api", "dshield_email", "urlhaus_api", "spur_api"):
                    if not resolved_credentials.get(key):
                        resolved_credentials[key] = creds.get(key)
        except Exception:
            pass

    # Initialize enrichment service
    try:
        # Import here to avoid circular imports
        from pathlib import Path

        from ..enrichment import EnrichmentCacheManager
        from ..enrichment.handlers import EnrichmentService

        cache_dir_path = Path(args.cache_dir)
        cache_manager = EnrichmentCacheManager(cache_dir_path)
        service = EnrichmentService(
            cache_dir=cache_dir_path,
            vt_api=resolved_credentials.get("vt_api"),
            dshield_email=resolved_credentials.get("dshield_email"),
            urlhaus_api=resolved_credentials.get("urlhaus_api"),
            spur_api=resolved_credentials.get("spur_api"),
            cache_manager=cache_manager,
            enable_telemetry=False,  # Disable telemetry to avoid status directory issues
        )

        # Initialize status emitter for progress monitoring
        # Use local temp directory if no status directory is provided and default doesn't exist
        status_dir = args.status_dir
        if not status_dir:
            from pathlib import Path

            default_status_dir = Path("/mnt/dshield/data/logs/status")
            if not default_status_dir.exists():
                # Use a local temp directory if the default doesn't exist
                status_dir = Path.home() / ".cache" / "cowrieprocessor" / "status"
                logger.info(f"Using local status directory: {status_dir}")

        status_emitter = StatusEmitter("enrichment_refresh", status_dir=status_dir)

        # Log available enrichment services
        available_services = []
        if resolved_credentials.get("dshield_email"):
            available_services.append("DShield (IP→ASN/Geo)")
        if resolved_credentials.get("urlhaus_api"):
            available_services.append("URLHaus (IP reputation)")
        if resolved_credentials.get("spur_api"):
            available_services.append("SPUR (IP intelligence)")
        if resolved_credentials.get("vt_api"):
            available_services.append("VirusTotal (file analysis)")

        if available_services:
            logger.info(f"Available enrichment services: {', '.join(available_services)}")
        else:
            logger.warning("No enrichment services configured - only database updates will be performed")

        with service:  # Use context manager for proper cleanup
            session_limit = args.sessions if args.sessions >= 0 else 0
            file_limit = args.files if args.files >= 0 else 0

            if file_limit != 0 and not table_exists(engine, "files"):
                logger.info("Files table not found; skipping file enrichment refresh")
                file_limit = 0

            session_count = 0
            file_count = 0
            last_commit = time.time()
            last_status_update = time.time()

            # Track enrichment statistics
            enrichment_stats = {
                "dshield_calls": 0,
                "urlhaus_calls": 0,
                "spur_calls": 0,
                "virustotal_calls": 0,
                "dshield_failures": 0,
                "urlhaus_failures": 0,
                "spur_failures": 0,
                "virustotal_failures": 0,
            }

            # Record initial status
            status_emitter.record_metrics(
                {
                    "sessions_processed": 0,
                    "files_processed": 0,
                    "sessions_total": session_limit if session_limit > 0 else "unlimited",
                    "files_total": file_limit if file_limit > 0 else "unlimited",
                    "enrichment_stats": enrichment_stats,
                }
            )

            # Process sessions
            for session_id, src_ip in iter_sessions(engine, session_limit):
                session_count += 1
                result = service.enrich_session(session_id, src_ip)
                enrichment = result.get("enrichment", {}) if isinstance(result, dict) else {}
                flags = service.get_session_flags(result)

                # Track enrichment statistics for this session
                track_enrichment_stats(enrichment, enrichment_stats)

                update_session(engine, session_id, enrichment, flags)
                if session_count % args.commit_interval == 0:
                    stats_summary = (
                        f"dshield={enrichment_stats['dshield_calls']}, "
                        f"urlhaus={enrichment_stats['urlhaus_calls']}, "
                        f"spur={enrichment_stats['spur_calls']}"
                    )
                    logger.info(
                        f"[sessions] committed {session_count} rows "
                        f"(elapsed {time.time() - last_commit:.1f}s) [{stats_summary}]"
                    )
                    last_commit = time.time()

                # Update status every 10 items or every 30 seconds
                if session_count % 10 == 0 or time.time() - last_status_update > 30:
                    status_emitter.record_metrics(
                        {
                            "sessions_processed": session_count,
                            "files_processed": file_count,
                            "sessions_total": session_limit if session_limit > 0 else "unlimited",
                            "files_total": file_limit if file_limit > 0 else "unlimited",
                            "enrichment_stats": enrichment_stats.copy(),
                        }
                    )
                    last_status_update = time.time()

                if session_limit > 0 and session_count >= session_limit:
                    break

            if session_count % args.commit_interval:
                logger.info(f"[sessions] committed tail {session_count % args.commit_interval}")

            # Process files
            if file_limit != 0 and resolved_credentials.get("vt_api"):
                for file_hash, filename, session_id in iter_files(engine, file_limit):
                    file_count += 1
                    result = service.enrich_file(file_hash, filename or file_hash)
                    enrichment = result.get("enrichment", {}) if isinstance(result, dict) else {}

                    # Track VirusTotal statistics for this file
                    track_enrichment_stats(enrichment, enrichment_stats)

                    update_file(engine, file_hash, enrichment)
                    if file_count % args.commit_interval == 0:
                        vt_stats = f"vt={enrichment_stats['virustotal_calls']}"
                        logger.info(
                            f"[files] committed {file_count} rows "
                            f"(elapsed {time.time() - last_commit:.1f}s) [{vt_stats}]"
                        )
                        last_commit = time.time()

                    # Update status every 10 items or every 30 seconds
                    if file_count % 10 == 0 or time.time() - last_status_update > 30:
                        status_emitter.record_metrics(
                            {
                                "sessions_processed": session_count,
                                "files_processed": file_count,
                                "sessions_total": session_limit if session_limit > 0 else "unlimited",
                                "files_total": file_limit if file_limit > 0 else "unlimited",
                                "enrichment_stats": enrichment_stats.copy(),
                            }
                        )
                        last_status_update = time.time()

                    if file_limit > 0 and file_count >= file_limit:
                        break
                if file_count % args.commit_interval:
                    logger.info(f"[files] committed tail {file_count % args.commit_interval}")
            elif file_limit != 0:
                logger.info("No VirusTotal API key available; skipping file enrichment refresh")

            # Record final status
            status_emitter.record_metrics(
                {
                    "sessions_processed": session_count,
                    "files_processed": file_count,
                    "sessions_total": session_limit if session_limit > 0 else "unlimited",
                    "files_total": file_limit if file_limit > 0 else "unlimited",
                    "enrichment_stats": enrichment_stats,
                    "cache_snapshot": cache_manager.snapshot(),
                }
            )

            logger.info(f"Enrichment refresh completed: {session_count} sessions, {file_count} files updated")
            return 0

    except Exception as e:
        logger.error(f"Enrichment refresh failed: {e}", exc_info=True)
        return 1
    finally:
        engine.dispose()


def main() -> int:
    """Main entry point for cowrie-enrich command.

    Returns:
        Exit code
    """
    parser = argparse.ArgumentParser(
        description="Enrich Cowrie sessions with intelligence data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Enrich passwords for last 30 days
  cowrie-enrich passwords --last-days 30
  
  # Enrich passwords for specific date range
  cowrie-enrich passwords --start-date 2025-09-01 --end-date 2025-09-30
  
  # Enrich passwords for specific sensor
  cowrie-enrich passwords --sensor prod-sensor-01 --last-days 7
  
  # Force re-enrichment of already-enriched sessions
  cowrie-enrich passwords --last-days 30 --force
  
  # Refresh enrichment data for existing sessions and files
  cowrie-enrich refresh --sessions 1000 --files 500
  
  # Refresh all enrichment data (sessions and files)
  cowrie-enrich refresh --sessions 0 --files 0 --vt-api-key $VT_API_KEY --dshield-email your.email@example.com
        """,
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Subcommand to run')

    # passwords subcommand
    passwords_parser = subparsers.add_parser('passwords', help='Enrich sessions with HIBP password breach data')

    # Date range options
    date_group = passwords_parser.add_mutually_exclusive_group(required=True)
    date_group.add_argument('--last-days', type=int, help='Enrich sessions from last N days')
    date_group.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')

    passwords_parser.add_argument(
        '--end-date', type=str, help='End date (YYYY-MM-DD), required if --start-date is used'
    )

    # Filter options
    passwords_parser.add_argument('--sensor', type=str, help='Filter by sensor name')

    passwords_parser.add_argument(
        '--force', action='store_true', help='Force re-enrichment of already-enriched sessions'
    )

    # Database options
    passwords_parser.add_argument(
        '--database', type=str, help='Path to SQLite database or PostgreSQL connection string'
    )

    passwords_parser.add_argument(
        '--db-type', type=str, choices=['sqlite', 'postgresql'], help='Database type (auto-detected if not specified)'
    )

    # Cache and status options
    passwords_parser.add_argument(
        '--cache-dir',
        type=str,
        default='/mnt/dshield/data/cache',
        help='Cache directory for HIBP responses (default: /mnt/dshield/data/cache)',
    )

    passwords_parser.add_argument('--status-dir', type=str, help='Directory for status files (optional)')

    # Processing options
    passwords_parser.add_argument(
        '--batch-size', type=int, default=100, help='Batch size for committing updates (default: 100)'
    )

    passwords_parser.add_argument('--progress', action='store_true', help='Show progress bar')

    passwords_parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')

    passwords_parser.set_defaults(func=enrich_passwords)

    # prune subcommand
    prune_parser = subparsers.add_parser('prune', help='Prune passwords not seen in N days')

    prune_parser.add_argument(
        '--retention-days', type=int, default=180, help='Delete passwords not seen in N days (default: 180)'
    )

    prune_parser.add_argument('--database', type=str, help='Path to SQLite database or PostgreSQL connection string')

    prune_parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')

    prune_parser.set_defaults(func=prune_old_passwords)

    # top-passwords subcommand
    top_parser = subparsers.add_parser('top-passwords', help='Show most-used passwords in time period')

    top_date_group = top_parser.add_mutually_exclusive_group()
    top_date_group.add_argument('--last-days', type=int, help='Show passwords from last N days (default: 30)')
    top_date_group.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')

    top_parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD), required if --start-date is used')

    top_parser.add_argument('--limit', type=int, default=10, help='Number of passwords to show (default: 10)')

    top_parser.add_argument('--database', type=str, help='Path to SQLite database or PostgreSQL connection string')

    top_parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')

    top_parser.set_defaults(func=show_top_passwords)

    # new-passwords subcommand
    new_parser = subparsers.add_parser('new-passwords', help='Show newly emerged passwords in time period')

    new_date_group = new_parser.add_mutually_exclusive_group()
    new_date_group.add_argument('--last-days', type=int, help='Show passwords from last N days (default: 7)')
    new_date_group.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')

    new_parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD), required if --start-date is used')

    new_parser.add_argument('--limit', type=int, default=20, help='Number of passwords to show (default: 20)')

    new_parser.add_argument('--database', type=str, help='Path to SQLite database or PostgreSQL connection string')

    new_parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')

    new_parser.set_defaults(func=show_new_passwords)

    # refresh subcommand
    refresh_parser = subparsers.add_parser('refresh', help='Refresh enrichment data for existing sessions and files')

    # Processing limits
    refresh_parser.add_argument(
        '--sessions', type=int, default=1000, help='Number of sessions to refresh (0 for all, default: 1000)'
    )
    refresh_parser.add_argument(
        '--files', type=int, default=500, help='Number of files to refresh (0 for all, default: 500)'
    )
    refresh_parser.add_argument(
        '--commit-interval', type=int, default=100, help='Commit after this many updates (default: 100)'
    )

    # Database options
    refresh_parser.add_argument('--database', type=str, help='Path to SQLite database or PostgreSQL connection string')
    refresh_parser.add_argument(
        '--db-type', type=str, choices=['sqlite', 'postgresql'], help='Database type (auto-detected if not specified)'
    )

    # API credentials (optional - will auto-load from sensors.toml if not provided)
    refresh_parser.add_argument('--vt-api-key', help='VirusTotal API key (overrides sensors.toml)')
    refresh_parser.add_argument('--dshield-email', help='Registered DShield email (overrides sensors.toml)')
    refresh_parser.add_argument('--urlhaus-api-key', help='URLHaus API key (overrides sensors.toml)')
    refresh_parser.add_argument('--spur-api-key', help='SPUR API token (overrides sensors.toml)')

    # Cache and status options
    refresh_parser.add_argument(
        '--cache-dir',
        type=str,
        default='/mnt/dshield/data/cache',
        help='Cache directory for enrichment responses (default: /mnt/dshield/data/cache)',
    )
    refresh_parser.add_argument('--status-dir', type=str, help='Directory for status files (optional)')

    refresh_parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')

    refresh_parser.set_defaults(func=refresh_enrichment)

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
