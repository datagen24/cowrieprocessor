"""Data access helpers for reporting."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Iterator, List, Optional, cast

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from ..db import RawEvent, SessionSummary
from ..telemetry import start_span


@dataclass(slots=True)
class SessionStatistics:
    """Aggregate metrics describing a reporting window."""

    total_sessions: int
    avg_commands: float
    max_commands: int
    min_commands: int
    file_downloads: int
    login_attempts: int
    vt_flagged: int
    dshield_flagged: int
    unique_ips: int


@dataclass(slots=True)
class CommandStatRow:
    """Top command result row."""

    command: str
    occurrences: int


@dataclass(slots=True)
class FileDownloadRow:
    """Top file download result row."""

    url: str
    occurrences: int


@dataclass(slots=True)
class EnrichedSessionRow:
    """Session metadata paired with stored enrichment payload."""

    session_id: str
    sensor: Optional[str]
    first_event_at: Optional[datetime]
    last_event_at: Optional[datetime]
    enrichment: dict[str, Any]


class ReportingRepository:
    """Repository for querying aggregated report data."""

    def __init__(self, session_factory: sessionmaker[Session]):
        """Create a repository using the provided SQLAlchemy session factory."""
        self._session_factory = session_factory

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Yield a managed session."""
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    def session_stats(self, start: datetime, end: datetime, sensor: Optional[str] = None) -> SessionStatistics:
        """Return aggregated session metrics for the requested window."""
        span_attributes = {
            "report.window.start": start.isoformat(),
            "report.window.end": end.isoformat(),
            "report.sensor": sensor or "aggregate",
        }
        with start_span("cowrie.reporting.repo.session_stats", span_attributes):
            with self.session() as session:
                filters = [SessionSummary.first_event_at >= start, SessionSummary.first_event_at < end]
                if sensor:
                    filters.append(SessionSummary.matcher == sensor)

                totals = session.execute(
                    select(
                        func.count(SessionSummary.session_id),
                        func.coalesce(func.avg(SessionSummary.command_count), 0),
                        func.coalesce(func.max(SessionSummary.command_count), 0),
                        func.coalesce(func.min(SessionSummary.command_count), 0),
                        func.coalesce(func.sum(SessionSummary.file_downloads), 0),
                        func.coalesce(func.sum(SessionSummary.login_attempts), 0),
                        func.coalesce(func.sum(SessionSummary.vt_flagged), 0),
                        func.coalesce(func.sum(SessionSummary.dshield_flagged), 0),
                    ).where(and_(*filters))
                ).one()

                ip_filters = [
                    RawEvent.ingest_at >= start,
                    RawEvent.ingest_at < end,
                ]
                if sensor:
                    ip_filters.append(func.json_extract(RawEvent.payload, "$.sensor") == sensor)

                unique_ips = session.execute(
                    select(func.count(func.distinct(func.json_extract(RawEvent.payload, "$.src_ip")))).where(
                        and_(*ip_filters)
                    )
                ).scalar_one()

                return SessionStatistics(
                    total_sessions=int(totals[0] or 0),
                    avg_commands=float(totals[1] or 0),
                    max_commands=int(totals[2] or 0),
                    min_commands=int(totals[3] or 0),
                    file_downloads=int(totals[4] or 0),
                    login_attempts=int(totals[5] or 0),
                    vt_flagged=int(totals[6] or 0),
                    dshield_flagged=int(totals[7] or 0),
                    unique_ips=int(unique_ips or 0),
                )

    def top_commands(
        self,
        start: datetime,
        end: datetime,
        top_n: int = 10,
        sensor: Optional[str] = None,
    ) -> Iterable[CommandStatRow]:
        """Yield top commands observed in the time range."""
        span_attributes = {
            "report.window.start": start.isoformat(),
            "report.window.end": end.isoformat(),
            "report.sensor": sensor or "aggregate",
            "report.top_n": top_n,
        }
        with start_span("cowrie.reporting.repo.top_commands", span_attributes):
            with self.session() as session:
                filters = [
                    RawEvent.ingest_at >= start,
                    RawEvent.ingest_at < end,
                    func.json_extract(RawEvent.payload, "$.eventid").like("%command%"),
                ]
                if sensor:
                    filters.append(func.json_extract(RawEvent.payload, "$.sensor") == sensor)

                stmt = (
                    select(
                        func.json_extract(RawEvent.payload, "$.input_safe").label("command"),
                        func.count().label("count"),
                    )
                    .where(and_(*filters))
                    .group_by("command")
                    .order_by(func.count().desc())
                    .limit(top_n)
                )

                for row in session.execute(stmt):
                    command = row.command or "<unknown>"
                    occurrences = cast(int, row.count) if row.count is not None else 0
                    yield CommandStatRow(command=command, occurrences=occurrences)

    def top_file_downloads(
        self,
        start: datetime,
        end: datetime,
        top_n: int = 10,
        sensor: Optional[str] = None,
    ) -> Iterable[FileDownloadRow]:
        """Yield the most common file download URLs in the time range."""
        span_attributes = {
            "report.window.start": start.isoformat(),
            "report.window.end": end.isoformat(),
            "report.sensor": sensor or "aggregate",
            "report.top_n": top_n,
        }
        with start_span("cowrie.reporting.repo.top_files", span_attributes):
            with self.session() as session:
                filters = [
                    RawEvent.ingest_at >= start,
                    RawEvent.ingest_at < end,
                    func.json_extract(RawEvent.payload, "$.eventid") == "cowrie.session.file_download",
                ]
                if sensor:
                    filters.append(func.json_extract(RawEvent.payload, "$.sensor") == sensor)

                stmt = (
                    select(
                        func.json_extract(RawEvent.payload, "$.url").label("url"),
                        func.count().label("count"),
                    )
                    .where(and_(*filters))
                    .group_by("url")
                    .order_by(func.count().desc())
                    .limit(top_n)
                )

                for row in session.execute(stmt):
                    url = row.url or "<unknown>"
                    occurrences = cast(int, row.count) if row.count is not None else 0
                    yield FileDownloadRow(url=url, occurrences=occurrences)

    def sensors(self) -> List[str]:
        """Return a sorted list of sensor identifiers present in summaries."""
        with start_span("cowrie.reporting.repo.sensors", {}):
            with self.session() as session_ctx:
                rows = session_ctx.execute(
                    select(func.distinct(SessionSummary.matcher)).where(SessionSummary.matcher.isnot(None))
                ).scalars()
                return sorted({row for row in rows if row})

    def enriched_sessions(
        self,
        start: datetime,
        end: datetime,
        *,
        sensor: Optional[str] = None,
        limit: int = 20,
    ) -> List[EnrichedSessionRow]:
        """Return sessions with persisted enrichment metadata in the window."""
        span_attributes = {
            "report.window.start": start.isoformat(),
            "report.window.end": end.isoformat(),
            "report.sensor": sensor or "aggregate",
            "report.limit": limit,
        }
        with start_span("cowrie.reporting.repo.enriched_sessions", span_attributes):
            with self.session() as session_ctx:
                filters = [
                    SessionSummary.first_event_at >= start,
                    SessionSummary.first_event_at < end,
                    SessionSummary.enrichment.isnot(None),
                    or_(SessionSummary.vt_flagged == 1, SessionSummary.dshield_flagged == 1),
                ]
                if sensor:
                    filters.append(SessionSummary.matcher == sensor)

                stmt = (
                    select(
                        SessionSummary.session_id,
                        SessionSummary.matcher,
                        SessionSummary.enrichment,
                        SessionSummary.first_event_at,
                        SessionSummary.last_event_at,
                    )
                    .where(and_(*filters))
                    .order_by(SessionSummary.last_event_at.desc())
                    .limit(limit)
                )

                results: List[EnrichedSessionRow] = []
                for row in session_ctx.execute(stmt):
                    enrichment_value = row.enrichment if isinstance(row.enrichment, dict) else {}
                    results.append(
                        EnrichedSessionRow(
                            session_id=row.session_id,
                            sensor=row.matcher,
                            first_event_at=row.first_event_at,
                            last_event_at=row.last_event_at,
                            enrichment=enrichment_value,
                        )
                    )
                return results
