"""Session enumeration and metric helpers for Cowrie log ingest."""

from __future__ import annotations

import collections
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional, Tuple

SessionEntry = Dict[str, object]
MatchFunc = Callable[[SessionEntry], Optional[str]]


def _coerce_epoch(value: object) -> Optional[int]:
    """Convert common timestamp representations to epoch seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # Normalize trailing Z to UTC designator
        if text.endswith('Z'):
            text = text[:-1]
            fmt_candidates: tuple[str, ...] = (
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S",
            )
            for fmt in fmt_candidates:
                try:
                    dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
                    return int(dt.timestamp())
                except ValueError:
                    continue
        fmt_candidates = (
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
        )
        for fmt in fmt_candidates:
            try:
                dt = datetime.strptime(text, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return int(dt.timestamp())
            except ValueError:
                continue
    return None


def _match_full_delimited(entry: SessionEntry) -> Optional[str]:
    raw = entry.get('session')
    if isinstance(raw, str):
        value = raw.strip()
        if value and '-' in value and '/' in value:
            return value
    return None


def _match_session_id(entry: SessionEntry) -> Optional[str]:
    raw = entry.get('session')
    if isinstance(raw, str):
        value = raw.strip()
        if value:
            return value
    return None


_SESSION_FIELD_CANDIDATES = (
    'sessionid',
    'session_id',
    'sessionID',
    'sid',
    'uuid',
)


_MESSAGE_SESSION_RE = re.compile(r"session(?:\s|['\"]|=)+([A-Za-z0-9._:-]+)")


def _match_event_derived(entry: SessionEntry) -> Optional[str]:
    for key in _SESSION_FIELD_CANDIDATES:
        raw = entry.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    message = entry.get('message')
    if isinstance(message, str):
        match = _MESSAGE_SESSION_RE.search(message)
        if match:
            return match.group(1)
    return None


MATCHERS: List[Tuple[str, MatchFunc]] = [
    ('full_delimited', _match_full_delimited),
    ('session_id_only', _match_session_id),
    ('event_session', _match_event_derived),
]


@dataclass
class SessionMetrics:
    """Aggregated metrics captured during session enumeration."""

    session_id: str
    match_type: str
    first_seen: Optional[int] = None
    last_seen: Optional[int] = None
    command_count: int = 0
    login_attempts: int = 0
    total_events: int = 0
    last_source_file: Optional[str] = None

    def update(self, entry: SessionEntry, source_file: Optional[str]) -> None:
        """Update aggregate counters from a single event entry."""
        self.total_events += 1
        timestamp = _coerce_epoch(entry.get('timestamp'))
        if timestamp is not None:
            if self.first_seen is None or timestamp < self.first_seen:
                self.first_seen = timestamp
            if self.last_seen is None or timestamp > self.last_seen:
                self.last_seen = timestamp
        eventid = entry.get('eventid')
        if isinstance(eventid, str):
            if eventid.startswith('cowrie.command.'):
                self.command_count += 1
            if eventid.startswith('cowrie.login'):
                self.login_attempts += 1
        if source_file:
            self.last_source_file = source_file


@dataclass
class SessionEnumerationResult:
    """Result bundle for session enumeration."""

    by_session: Dict[str, List[SessionEntry]]
    metrics: Dict[str, SessionMetrics]
    match_counts: Dict[str, int]
    events_processed: int


def match_session(entry: SessionEntry) -> Tuple[Optional[str], Optional[str]]:
    """Return the first matching session identifier and its matcher label."""
    for label, func in MATCHERS:
        session_id = func(entry)
        if session_id:
            return session_id, label
    return None, None


ProgressCallback = Callable[[Dict[str, object]], None]
CheckpointCallback = Callable[[Dict[str, object]], None]
SourceGetter = Callable[[SessionEntry], Optional[str]]


def enumerate_sessions(
    entries: Iterable[SessionEntry],
    *,
    progress_callback: Optional[ProgressCallback] = None,
    checkpoint_callback: Optional[CheckpointCallback] = None,
    progress_interval: int = 5000,
    checkpoint_interval: int = 10000,
    source_getter: Optional[SourceGetter] = None,
) -> SessionEnumerationResult:
    """Enumerate session IDs and gather metrics from raw event entries."""
    by_session: Dict[str, List[SessionEntry]] = {}
    metrics: Dict[str, SessionMetrics] = {}
    match_counts: collections.Counter[str] = collections.Counter()
    events_processed = 0

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        events_processed += 1
        session_id, match_type = match_session(entry)
        if not session_id:
            if progress_callback and events_processed % progress_interval == 0:
                progress_callback(
                    {
                        'events_processed': events_processed,
                        'session_count': len(by_session),
                        'match_counts': dict(match_counts),
                    }
                )
            if checkpoint_callback and events_processed % checkpoint_interval == 0:
                checkpoint_callback(
                    {
                        'events_processed': events_processed,
                        'last_session': None,
                        'match_counts': dict(match_counts),
                        'session_count': len(by_session),
                    }
                )
            continue
        container = by_session.setdefault(session_id, [])
        container.append(entry)
        metric = metrics.get(session_id)
        if metric is None:
            metric = SessionMetrics(session_id=session_id, match_type=match_type or 'unknown')
            metrics[session_id] = metric
            if match_type:
                match_counts[match_type] += 1
            else:
                match_counts['unknown'] += 1
        source_file = source_getter(entry) if source_getter else None
        metric.update(entry, source_file)
        if progress_callback and events_processed % progress_interval == 0:
            progress_callback(
                {
                    'events_processed': events_processed,
                    'session_count': len(by_session),
                    'match_counts': dict(match_counts),
                }
            )
        if checkpoint_callback and events_processed % checkpoint_interval == 0:
            checkpoint_callback(
                {
                    'events_processed': events_processed,
                    'last_session': session_id,
                    'match_counts': dict(match_counts),
                    'session_count': len(by_session),
                }
            )

    if progress_callback:
        progress_callback(
            {
                'events_processed': events_processed,
                'session_count': len(by_session),
                'match_counts': dict(match_counts),
            }
        )

    return SessionEnumerationResult(
        by_session=by_session,
        metrics=metrics,
        match_counts=dict(match_counts),
        events_processed=events_processed,
    )


def serialize_metrics(metrics: Dict[str, SessionMetrics]) -> List[Dict[str, object]]:
    """Serialize metrics for JSON/logging helpers."""
    payload: List[Dict[str, object]] = []
    for item in metrics.values():
        payload.append(
            {
                'session_id': item.session_id,
                'match_type': item.match_type,
                'first_seen': item.first_seen,
                'last_seen': item.last_seen,
                'command_count': item.command_count,
                'login_attempts': item.login_attempts,
                'total_events': item.total_events,
                'last_source_file': item.last_source_file,
            }
        )
    return payload


__all__ = [
    'enumerate_sessions',
    'match_session',
    'serialize_metrics',
    'SessionEnumerationResult',
    'SessionMetrics',
]
