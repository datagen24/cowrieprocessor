#!/usr/bin/env python3
"""Rebuild session_summaries table from raw_events.

Critical fix for Issue #37 - incorrect session aggregation.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure tqdm works properly in terminal
os.environ['TQDM_POSITION'] = '0'

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from tqdm import tqdm

from cowrieprocessor.db import CommandStat, RawEvent, SessionSummary
from cowrieprocessor.db.engine import create_engine_from_settings, create_session_maker
from cowrieprocessor.settings import load_database_settings
from cowrieprocessor.telemetry.otel import start_span


def _load_sensors_config() -> dict[str, str] | None:
    """Load database configuration from sensors.toml if available."""
    # Try config/ directory first, then fall back to current directory
    sensors_file = Path("config/sensors.toml")
    if not sensors_file.exists():
        sensors_file = Path("sensors.toml")
    if not sensors_file.exists():
        return None

    try:
        # Try tomllib first (Python 3.11+)
        try:
            import tomllib
        except ImportError:
            # Fall back to tomli for older Python versions
            import tomli as tomllib

        with sensors_file.open("rb") as handle:
            data = tomllib.load(handle)

        # Check for global database configuration
        global_config = data.get("global", {})
        db_url = global_config.get("db")
        if db_url:
            return {"url": db_url}

    except Exception:
        # If sensors.toml doesn't exist or can't be parsed, return None
        pass

    return None


# Configure logging to work with tqdm
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Ensure tqdm can properly handle terminal output
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)


class SessionSummaryRebuilder:
    """Rebuild session_summaries table from raw_events."""

    def __init__(self, db_url: Optional[str] = None, batch_size: int = 5000, memory_limit_mb: int = 4096):
        """Initialize the rebuilder with database connection and batch size.

        Args:
            db_url: Database URL override
            batch_size: Number of sessions to process before flushing to database
            memory_limit_mb: Memory limit in MB before forcing garbage collection
        """
        # Try to load from sensors.toml first, then use explicit URL or default
        if not db_url:
            config = _load_sensors_config()
            if config:
                self.settings = load_database_settings(config=config)
            else:
                self.settings = load_database_settings()
        else:
            # Create minimal settings for custom URL
            from cowrieprocessor.settings import DatabaseSettings

            self.settings = DatabaseSettings(url=db_url)

        assert self.settings is not None  # Type guard for mypy
        self.engine = create_engine_from_settings(self.settings)
        self.Session = create_session_maker(self.engine)
        self.batch_size = batch_size
        self.memory_limit_mb = memory_limit_mb

        # Initialize telemetry (lazy-loaded to avoid circular imports)
        self.status_emitter: Optional[Any] = None
        self._current_metrics: Dict[str, Any] = {
            'sessions_processed': 0,
            'events_processed': 0,
            'batches_completed': 0,
            'memory_usage_mb': 0.0,
            'start_time': None,
            'errors': 0,
        }

    def rebuild(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        dry_run: bool = False,
        preserve_enrichment: bool = True,
        sample_events: int = 0,
    ) -> Dict[str, Any]:
        """Rebuild session_summaries from raw_events.

        Args:
            start_date: Only rebuild sessions after this date
            end_date: Only rebuild sessions before this date
            dry_run: Validate without writing
            preserve_enrichment: Keep existing enrichment data
            sample_events: Number of events to sample for verification (0 = disabled)

        Returns:
            Statistics about the rebuild
        """
        # Initialize telemetry for this rebuild operation
        self._current_metrics['start_time'] = datetime.now()
        self._current_metrics['sessions_processed'] = 0
        self._current_metrics['events_processed'] = 0
        self._current_metrics['batches_completed'] = 0
        self._current_metrics['errors'] = 0

        # Create tracing span
        span_attributes = {
            'operation': 'rebuild_session_summaries',
            'dry_run': dry_run,
            'preserve_enrichment': preserve_enrichment,
            'batch_size': self.batch_size,
            'memory_limit_mb': self.memory_limit_mb,
        }

        with start_span("rebuild_session_summaries", span_attributes):
            stats: Dict[str, Any] = {
                'sessions_found': 0,
                'sessions_rebuilt': 0,
                'events_processed': 0,
                'errors': [],
                'batches_processed': 0,
            }

        with self.Session() as session:
            # Get total count for progress tracking (with date filters applied)
            count_query = select(func.count()).select_from(RawEvent)
            if start_date:
                count_query = count_query.where(RawEvent.ingest_at >= start_date)
            if end_date:
                count_query = count_query.where(RawEvent.ingest_at <= end_date)

            total_events = session.execute(count_query).scalar_one()
            logger.info(f"Processing {total_events:,} events")

            # Emit initial status
            self._emit_status({'total_events': total_events, 'phase': 'counting_complete'})

            # Sample events for verification if requested
            if sample_events > 0:
                self._sample_events_for_verification(session, sample_events, start_date, end_date)

            # Process in smaller chunks to avoid memory exhaustion
            offset = 0
            chunk_size = min(self.batch_size * 5, 25000)  # Process in controlled chunks
            memory_check_interval = chunk_size * 2  # Check memory every 2 chunks

            with tqdm(
                total=total_events, desc="Processing events", unit="events", dynamic_ncols=True, leave=True, position=0
            ) as pbar:
                while offset < total_events:
                    # Build query for this chunk
                    query = select(RawEvent).offset(offset).limit(chunk_size)

                    if start_date:
                        query = query.where(RawEvent.ingest_at >= start_date)
                    if end_date:
                        query = query.where(RawEvent.ingest_at <= end_date)

                    # Process this chunk
                    events = session.execute(query).scalars().all()

                    if not events:
                        break

                    # Process events in this chunk
                    chunk_aggregates = {}
                    chunk_events_processed = 0

                    for event in events:
                        chunk_events_processed += 1
                        stats['events_processed'] += 1

                        # Extract session_id from payload
                        session_id = self._extract_session_id(event)
                        if not session_id:
                            continue

                        # Build aggregate
                        if session_id not in chunk_aggregates:
                            chunk_aggregates[session_id] = self._create_aggregate()
                            stats['sessions_found'] += 1

                        self._update_aggregate(chunk_aggregates[session_id], event)

                    # Flush this chunk's aggregates
                    if chunk_aggregates and not dry_run:
                        self._flush_aggregates(session, chunk_aggregates, preserve_enrichment)
                        stats['sessions_rebuilt'] += len(chunk_aggregates)
                        stats['batches_processed'] += 1

                    # Update and emit status periodically (much less frequently to avoid progress bar interference)
                    if stats['batches_processed'] % 50 == 0:  # Only log every 50 batches
                        self._current_metrics['sessions_processed'] = stats['sessions_found']
                        self._current_metrics['events_processed'] = stats['events_processed']
                        self._current_metrics['batches_completed'] = stats['batches_processed']
                        self._emit_status({'phase': 'processing'})

                    # Update progress (without frequent logging to avoid progress bar interference)
                    pbar.update(chunk_events_processed)

                    # Move to next chunk
                    offset += chunk_size

                    # Memory management - check memory usage periodically (less frequently)
                    if offset % (memory_check_interval * 5) == 0:  # Check every 5 intervals
                        import gc
                        import os

                        import psutil

                        process = psutil.Process(os.getpid())
                        memory_mb = process.memory_info().rss / 1024 / 1024

                        if memory_mb > self.memory_limit_mb:
                            logger.warning(
                                f"Memory usage high ({memory_mb:.1f}MB > "
                                f"{self.memory_limit_mb}MB), forcing garbage collection"
                            )
                            gc.collect()

                        # Log progress periodically (minimal logging during progress bar)
                        progress_pct = (offset / total_events) * 100
                        logger.debug(
                            f"Progress: {progress_pct:.1f}% "
                            f"({offset:,}/{total_events:,} events, "
                            f"{memory_mb:.1f}MB memory)"
                        )

            logger.info(f"Processed {stats['events_processed']:,} events in {stats['batches_processed']} batches")

            # Emit final status
            self._emit_status({'final_stats': stats, 'phase': 'completed'})

        return stats

    def _emit_status(self, additional_metrics: Dict[str, Any]) -> None:
        """Emit current status to telemetry systems."""
        # Update metrics
        self._current_metrics.update(additional_metrics)

        # Lazy-load status emitter to avoid circular imports
        if self.status_emitter is None:
            from cowrieprocessor.status_emitter import StatusEmitter

            self.status_emitter = StatusEmitter("rebuild_session_summaries")

        # Emit to status emitter
        assert self.status_emitter is not None  # Type guard for mypy
        self.status_emitter.record_metrics(self._current_metrics)

    def _sample_events_for_verification(
        self, session, sample_count: int, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None
    ) -> None:
        """Sample events for verification and display summary statistics."""
        logger.info(f"Sampling {sample_count} events for verification...")

        # Build sample query
        sample_query = select(RawEvent).limit(sample_count)

        if start_date:
            sample_query = sample_query.where(RawEvent.ingest_at >= start_date)
        if end_date:
            sample_query = sample_query.where(RawEvent.ingest_at <= end_date)

        # Execute sample query
        sample_events = session.execute(sample_query).scalars().all()

        # Analyze sample events
        sample_stats: Dict[str, Any] = {
            'total_sampled': len(sample_events),
            'sessions_found': set(),
            'event_types': {},
            'sources': set(),
            'risk_scores': [],
            'with_commands': 0,
            'with_files': 0,
            'with_logins': 0,
        }

        for event in sample_events:
            # Extract session_id
            session_id = self._extract_session_id(event)
            if session_id:
                sample_stats['sessions_found'].add(session_id)

            # Count event types
            event_type = event.event_type or (event.payload.get('eventid') if event.payload else None)
            if event_type:
                sample_stats['event_types'][event_type] = sample_stats['event_types'].get(event_type, 0) + 1

            # Track sources
            if event.source:
                sample_stats['sources'].add(event.source)

            # Track risk scores
            if event.risk_score is not None:
                sample_stats['risk_scores'].append(event.risk_score)

            # Count specific event types
            if event_type and 'command' in event_type.lower():
                sample_stats['with_commands'] += 1
            if event_type and 'file' in event_type.lower():
                sample_stats['with_files'] += 1
            if event_type and 'login' in event_type.lower():
                sample_stats['with_logins'] += 1

        # Display sample results
        logger.info("=== SAMPLE VERIFICATION RESULTS ===")
        logger.info(f"Sampled {sample_stats['total_sampled']} events")
        logger.info(f"Unique sessions found: {len(sample_stats['sessions_found'])}")
        logger.info(f"Unique sources: {len(sample_stats['sources'])}")

        logger.info("Event type distribution:")
        for event_type, count in sorted(sample_stats['event_types'].items(), key=lambda x: x[1], reverse=True):
            logger.info(f"  {event_type}: {count}")

        logger.info("Event characteristics:")
        logger.info(f"  Events with commands: {sample_stats['with_commands']}")
        logger.info(f"  Events with files: {sample_stats['with_files']}")
        logger.info(f"  Events with logins: {sample_stats['with_logins']}")

        if sample_stats['risk_scores']:
            avg_risk = sum(sample_stats['risk_scores']) / len(sample_stats['risk_scores'])
            max_risk = max(sample_stats['risk_scores'])
            logger.info(f"Risk score stats - Avg: {avg_risk:.2f}, Max: {max_risk}")

        logger.info("=== SAMPLE VERIFICATION COMPLETE ===\n")

    def monitor_progress(self) -> Dict[str, Any]:
        """Monitor rebuild progress and data integrity."""
        with self.Session() as session:
            # Get current counts
            raw_sessions = session.execute(
                select(func.count(func.distinct(RawEvent.session_id))).where(RawEvent.session_id.isnot(None))
            ).scalar_one()

            summary_sessions = session.execute(select(func.count()).select_from(SessionSummary)).scalar_one()

            total_events = session.execute(select(func.count()).select_from(RawEvent)).scalar_one()

            # Check data integrity by sampling a few sessions
            sample_sessions = session.execute(
                select(SessionSummary.session_id, SessionSummary.event_count)
                .order_by(SessionSummary.session_id)
                .limit(10)
            ).all()

            integrity_issues = []
            for session_id, recorded_count in sample_sessions:
                # Get actual count from raw_events
                actual_count = session.execute(
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

            # Check for sessions that exist in raw_events but not in summaries
            raw_session_ids = (
                session.execute(
                    select(func.distinct(RawEvent.session_id))
                    .where(RawEvent.session_id.isnot(None))
                    .limit(100)  # Sample for performance
                )
                .scalars()
                .all()
            )

            summary_session_ids = set()
            if summary_sessions > 0:
                summary_session_ids = set(
                    session.execute(select(SessionSummary.session_id).limit(1000)).scalars().all()
                )

            missing_in_summaries = 0
            for raw_session_id in raw_session_ids[:50]:  # Check first 50
                if raw_session_id not in summary_session_ids:
                    missing_in_summaries += 1

            return {
                'raw_sessions': raw_sessions,
                'summary_sessions': summary_sessions,
                'total_events': total_events,
                'missing_sessions': raw_sessions - summary_sessions,
                'integrity_issues': integrity_issues,
                'sample_missing_in_summaries': missing_in_summaries,
                'data_quality_score': len(integrity_issues) / max(len(sample_sessions), 1) * 100,
            }

    def rebuild_command_stats(self) -> Dict[str, Any]:
        """Rebuild command_stats table from raw_events."""
        stats: Dict[str, Any] = {
            'commands_processed': 0,
            'commands_aggregated': 0,
            'sessions_with_commands': 0,
            'errors': [],
        }

        with self.Session() as session:
            # Clear existing command_stats
            deleted_count = session.execute(delete(CommandStat)).rowcount
            logger.info(f"Cleared {deleted_count} existing command_stats records")
            session.commit()

            # Get total command events for progress tracking
            total_commands = session.execute(
                select(func.count()).select_from(RawEvent).where(RawEvent.event_type.like('%command%'))
            ).scalar_one()

            logger.info(f"Processing {total_commands:,} command events")

            # Process in chunks
            offset = 0
            chunk_size = min(self.batch_size * 5, 25000)

            with tqdm(
                total=total_commands,
                desc="Processing command events",
                unit="commands",
                dynamic_ncols=True,
                leave=True,
                position=0,
            ) as pbar:
                while offset < total_commands:
                    # Get command events for this chunk
                    command_events = (
                        session.execute(
                            select(RawEvent)
                            .where(RawEvent.event_type.like('%command%'))
                            .offset(offset)
                            .limit(chunk_size)
                        )
                        .scalars()
                        .all()
                    )

                    if not command_events:
                        break

                    # Aggregate commands by session and command
                    command_aggregates: Dict[tuple, Dict[str, Any]] = {}

                    for event in command_events:
                        stats['commands_processed'] += 1

                        session_id = self._extract_session_id(event)
                        if not session_id:
                            continue

                        # Extract command from payload
                        command = self._extract_command_from_event(event)
                        if not command:
                            continue

                        # Normalize command (you might want more sophisticated normalization)
                        normalized_command = command.strip().lower()

                        key = (session_id, normalized_command)
                        if key not in command_aggregates:
                            # Convert string timestamp to datetime if needed
                            ts = event.event_timestamp
                            if isinstance(ts, str):
                                try:
                                    ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                                except ValueError:
                                    try:
                                        ts = datetime.fromisoformat(ts)
                                    except ValueError:
                                        ts = None

                            command_aggregates[key] = {
                                'session_id': session_id,
                                'command_normalized': normalized_command,
                                'occurrences': 0,
                                'first_seen': ts,
                                'last_seen': ts,
                                'high_risk': event.risk_score and event.risk_score > 5,
                            }

                        agg = command_aggregates[key]
                        agg['occurrences'] += 1

                        # Update timestamps
                        if event.event_timestamp:
                            # Convert string timestamp to datetime if needed
                            ts = event.event_timestamp
                            if isinstance(ts, str):
                                try:
                                    ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                                except ValueError:
                                    try:
                                        ts = datetime.fromisoformat(ts)
                                    except ValueError:
                                        ts = None

                            if ts:
                                if not agg['first_seen'] or ts < agg['first_seen']:
                                    agg['first_seen'] = ts
                                if not agg['last_seen'] or ts > agg['last_seen']:
                                    agg['last_seen'] = ts

                        # Update high_risk flag
                        if event.risk_score and event.risk_score > 5:
                            agg['high_risk'] = True

                    # Insert aggregated command stats with PostgreSQL ON CONFLICT
                    if command_aggregates:
                        # Convert aggregates to CommandStat objects
                        cmd_stats_to_insert = []
                        for agg in command_aggregates.values():
                            cmd_stat = CommandStat(
                                session_id=agg['session_id'],
                                command_normalized=agg['command_normalized'],
                                occurrences=agg['occurrences'],
                                first_seen=agg['first_seen'],
                                last_seen=agg['last_seen'],
                                high_risk=agg['high_risk'],
                            )
                            cmd_stats_to_insert.append(cmd_stat)

                        # Use bulk insert with ON CONFLICT for PostgreSQL
                        if cmd_stats_to_insert:
                            try:
                                # For PostgreSQL, use ON CONFLICT DO UPDATE
                                stmt = insert(CommandStat).values(
                                    [
                                        {
                                            'session_id': cmd.session_id,
                                            'command_normalized': cmd.command_normalized,
                                            'occurrences': cmd.occurrences,
                                            'first_seen': cmd.first_seen,
                                            'last_seen': cmd.last_seen,
                                            'high_risk': cmd.high_risk,
                                        }
                                        for cmd in cmd_stats_to_insert
                                    ]
                                )

                                # PostgreSQL ON CONFLICT DO UPDATE
                                stmt = stmt.on_conflict_do_update(
                                    index_elements=['session_id', 'command_normalized'],
                                    set_=dict(
                                        occurrences=stmt.excluded.occurrences,
                                        first_seen=stmt.excluded.first_seen,
                                        last_seen=stmt.excluded.last_seen,
                                        high_risk=stmt.excluded.high_risk,
                                    ),
                                )

                                session.execute(stmt)
                                stats['commands_aggregated'] += len(cmd_stats_to_insert)

                            except Exception as e:
                                # Fallback to individual merges if bulk insert fails
                                logger.warning(f"Bulk insert failed, falling back to individual merges: {e}")
                                for cmd in cmd_stats_to_insert:
                                    try:
                                        session.merge(cmd)
                                        stats['commands_aggregated'] += 1
                                    except Exception as merge_error:
                                        logger.error(
                                            f"Failed to merge command stat {cmd.session_id}/"
                                            f"{cmd.command_normalized}: {merge_error}"
                                        )

                        # Update session count
                        unique_sessions = len(set(agg['session_id'] for agg in command_aggregates.values()))
                        stats['sessions_with_commands'] += unique_sessions

                    session.commit()

                    # Update progress
                    pbar.update(len(command_events))
                    offset += chunk_size

                    # Memory management
                    if offset % (chunk_size * 10) == 0:
                        import gc

                        gc.collect()

            logger.info(
                f"Processed {stats['commands_processed']:,} commands into "
                f"{stats['commands_aggregated']:,} command_stats records"
            )
            logger.info(f"Sessions with commands: {stats['sessions_with_commands']:,}")

        return stats

    def _extract_command_from_event(self, event: RawEvent) -> Optional[str]:
        """Extract command string from event payload."""
        if not event.payload or not isinstance(event.payload, dict):
            return None

        # Look for command input in various fields
        command = (
            event.payload.get('input')
            or event.payload.get('command')
            or event.payload.get('cmd')
            or event.payload.get('message')
        )

        # If we found a command in the message field, extract just the command part
        if command and command.startswith('CMD: '):
            command = command[5:]  # Remove 'CMD: ' prefix

        return command if command else None

    def _extract_session_id(self, event: RawEvent) -> Optional[str]:
        """Extract session_id from event payload."""
        # Try computed column first
        if hasattr(event, 'session_id') and event.session_id:
            return str(event.session_id)

        # Fallback to manual extraction
        if event.payload and isinstance(event.payload, dict):
            return event.payload.get('session') or event.payload.get('session_id')

        return None

    def _create_aggregate(self) -> Dict[str, Any]:
        """Create empty session aggregate."""
        return {
            'event_count': 0,
            'command_count': 0,
            'file_downloads': 0,
            'login_attempts': 0,
            'first_event_at': None,
            'last_event_at': None,
            'risk_score': 0,
            'sensor': None,
            'src_ips': set(),
            'vt_flagged': False,
            'dshield_flagged': False,
            'source_files': set(),
        }

    def _update_aggregate(self, aggregate: Dict[str, Any], event: RawEvent) -> None:
        """Update aggregate with event data."""
        aggregate['event_count'] += 1

        # Extract timestamp
        if event.event_timestamp:
            ts = event.event_timestamp
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                except ValueError:
                    # Try without timezone
                    try:
                        ts = datetime.fromisoformat(ts)
                    except ValueError:
                        ts = None

            if ts:
                if not aggregate['first_event_at'] or ts < aggregate['first_event_at']:
                    aggregate['first_event_at'] = ts
                if not aggregate['last_event_at'] or ts > aggregate['last_event_at']:
                    aggregate['last_event_at'] = ts

        # Event type detection
        event_type = event.event_type or (event.payload.get('eventid') if event.payload else None)

        if event_type and 'command' in event_type.lower():
            aggregate['command_count'] += 1
        if event_type and 'file' in event_type.lower():
            aggregate['file_downloads'] += 1
        if event_type and 'login' in event_type.lower():
            aggregate['login_attempts'] += 1

        # Risk score
        if event.risk_score:
            aggregate['risk_score'] = max(aggregate['risk_score'], event.risk_score)

        # Source tracking
        if event.source:
            aggregate['source_files'].add(event.source)

        # Extract sensor and IPs
        if event.payload and isinstance(event.payload, dict):
            sensor = event.payload.get('sensor')
            if sensor and not aggregate['sensor']:
                aggregate['sensor'] = sensor

            src_ip = event.payload.get('src_ip') or event.payload.get('peer_ip')
            if src_ip:
                aggregate['src_ips'].add(src_ip)

    def _flush_aggregates(
        self, session: Session, aggregates: Dict[str, Dict[str, Any]], preserve_enrichment: bool
    ) -> None:
        """Write aggregates to session_summaries table."""
        session_ids = list(aggregates.keys())

        # Get existing enrichment data if preserving
        existing_enrichment = {}
        if preserve_enrichment:
            existing = session.execute(
                select(SessionSummary.session_id, SessionSummary.enrichment).where(
                    SessionSummary.session_id.in_(session_ids)
                )
            ).all()
            existing_enrichment = {row[0]: row[1] for row in existing}

        # Delete existing summaries
        session.execute(delete(SessionSummary).where(SessionSummary.session_id.in_(session_ids)))

        # Insert new summaries
        for session_id, agg in aggregates.items():
            # Convert sets to lists for JSON storage
            source_files = list(agg['source_files']) if agg['source_files'] else None

            summary = SessionSummary(
                session_id=session_id,
                event_count=agg['event_count'],
                command_count=agg['command_count'],
                file_downloads=agg['file_downloads'],
                login_attempts=agg['login_attempts'],
                first_event_at=agg['first_event_at'],
                last_event_at=agg['last_event_at'],
                risk_score=agg['risk_score'],
                matcher=agg['sensor'],
                vt_flagged=agg['vt_flagged'],
                dshield_flagged=agg['dshield_flagged'],
                source_files=source_files,
                enrichment=existing_enrichment.get(session_id),
            )
            session.add(summary)

        session.commit()

    def validate(self) -> Dict[str, Any]:
        """Validate session_summaries against raw_events."""
        with self.Session() as session:
            # Count distinct sessions in raw_events
            raw_sessions = session.execute(
                select(func.count(func.distinct(RawEvent.session_id))).where(RawEvent.session_id.isnot(None))
            ).scalar_one()

            # Count sessions in session_summaries
            summary_sessions = session.execute(select(func.count()).select_from(SessionSummary)).scalar_one()

            # Sample validation - check a few sessions
            sample_issues = []
            sample_sessions = session.execute(select(SessionSummary.session_id).limit(100)).scalars().all()

            for sid in sample_sessions:
                # Get actual event count
                actual_count = session.execute(
                    select(func.count()).select_from(RawEvent).where(RawEvent.session_id == sid)
                ).scalar_one()

                # Get recorded count
                recorded = session.execute(
                    select(SessionSummary.event_count).where(SessionSummary.session_id == sid)
                ).scalar_one()

                if actual_count != recorded:
                    sample_issues.append({'session_id': sid, 'actual': actual_count, 'recorded': recorded})

            return {
                'raw_sessions': raw_sessions,
                'summary_sessions': summary_sessions,
                'missing_sessions': raw_sessions - summary_sessions,
                'sample_issues': sample_issues,
            }


def main():
    """Main entry point for the rebuild script."""
    parser = argparse.ArgumentParser(description='Rebuild session_summaries from raw_events')
    parser.add_argument('--db', help='Database URL (uses config if not specified)')
    parser.add_argument('--start-date', type=datetime.fromisoformat, help='Start date (ISO format)')
    parser.add_argument('--end-date', type=datetime.fromisoformat, help='End date (ISO format)')
    parser.add_argument('--batch-size', type=int, default=5000, help='Batch size for processing (default: 5000)')
    parser.add_argument('--memory-limit', type=int, default=4096, help='Memory limit in MB (default: 4096)')
    parser.add_argument('--dry-run', action='store_true', help='Validate without writing')
    parser.add_argument(
        '--no-preserve-enrichment', action='store_true', help='Do not preserve existing enrichment data'
    )
    parser.add_argument('--validate-only', action='store_true', help='Only validate, do not rebuild')
    parser.add_argument(
        '--sample-events', type=int, default=0, help='Sample N events for verification (default: 0, disabled)'
    )
    parser.add_argument(
        '--assume-backup', action='store_true', help='Skip backup confirmation prompt (for automated runs)'
    )
    parser.add_argument('--monitor', action='store_true', help='Monitor rebuild progress and data integrity')
    parser.add_argument('--fix-command-stats', action='store_true', help='Rebuild command_stats table from raw_events')

    args = parser.parse_args()

    rebuilder = SessionSummaryRebuilder(args.db, args.batch_size, args.memory_limit)

    if args.validate_only:
        logger.info("Validating session_summaries...")
        results = rebuilder.validate()
        print(json.dumps(results, indent=2, default=str))

    elif args.monitor:
        logger.info("Monitoring rebuild progress and data integrity...")
        results = rebuilder.monitor_progress()
        print(json.dumps(results, indent=2, default=str))

    elif args.fix_command_stats:
        logger.info("Rebuilding command_stats table from raw_events...")
        results = rebuilder.rebuild_command_stats()
        print(json.dumps(results, indent=2, default=str))
    else:
        logger.info("Starting session summary rebuild...")

        # Backup warning
        if not args.dry_run and not args.assume_backup:
            response = input("Have you backed up the database? (yes/no): ")
            if response.lower() != 'yes':
                logger.error("Please backup the database first!")
                sys.exit(1)
        elif not args.dry_run and args.assume_backup:
            logger.warning("Skipping backup confirmation (--assume-backup flag used)")

        results = rebuilder.rebuild(
            start_date=args.start_date,
            end_date=args.end_date,
            dry_run=args.dry_run,
            preserve_enrichment=not args.no_preserve_enrichment,
            sample_events=args.sample_events,
        )

        print(f"\nRebuild {'(DRY RUN) ' if args.dry_run else ''}complete:")
        print(json.dumps(results, indent=2, default=str))

        # Validate after rebuild
        if not args.dry_run:
            logger.info("Validating rebuild...")
            validation = rebuilder.validate()

            if validation['missing_sessions'] > 0:
                logger.warning(f"Still have {validation['missing_sessions']} missing sessions")
            else:
                logger.info("✅ All sessions successfully rebuilt!")


if __name__ == '__main__':
    main()
