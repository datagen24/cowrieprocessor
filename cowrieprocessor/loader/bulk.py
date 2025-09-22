"""Bulk loading pipeline that streams Cowrie events into the ORM schema."""

from __future__ import annotations

import bz2
import gzip
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, MutableMapping, Optional, Sequence, cast

from dateutil import parser as date_parser  # type: ignore[import-untyped]
from sqlalchemy import Table, func
from sqlalchemy.dialects import sqlite as sqlite_dialect

try:  # pragma: no cover - optional dependency
    from sqlalchemy.dialects import postgresql as postgres_dialect
except ModuleNotFoundError:  # pragma: no cover - Postgres optional in tests
    postgres_dialect = cast(Any, None)

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ..db import RawEvent, SessionSummary, create_session_maker

JsonDict = Dict[str, Any]
TelemetryCallback = Callable[["BulkLoaderMetrics"], None]

COMMAND_KEYWORDS = {"curl", "wget", "powershell", "dubious", "nc", "bash", "sh", "python", "perl"}
SUSPICIOUS_PATTERNS = {"/tmp/", "http://", "https://", ";", "&&", "|"}
COMMAND_EVENT_HINTS = {"cowrie.command", "command"}
FILE_EVENT_HINTS = {"file_download", "cowrie.session.file"}
LOGIN_EVENT_HINTS = {"login", "cowrie.login"}


@dataclass(slots=True)
class BulkLoaderConfig:
    """Configuration knobs for the bulk loader."""

    batch_size: int = 500
    quarantine_threshold: int = 80
    batch_risk_threshold: int = 400
    neutralize_commands: bool = True
    telemetry_interval: int = 5  # batches


@dataclass(slots=True)
class SessionAggregate:
    """Rolling aggregate for a session during the current batch."""

    event_count: int = 0
    command_count: int = 0
    file_downloads: int = 0
    login_attempts: int = 0
    first_event_at: Optional[datetime] = None
    last_event_at: Optional[datetime] = None
    highest_risk: int = 0
    source_files: set[str] = field(default_factory=set)

    def update_timestamp(self, ts: Optional[datetime]) -> None:
        if ts is None:
            return
        if self.first_event_at is None or ts < self.first_event_at:
            self.first_event_at = ts
        if self.last_event_at is None or ts > self.last_event_at:
            self.last_event_at = ts


@dataclass(slots=True)
class BulkLoaderMetrics:
    """Telemetry emitted while processing batches."""

    ingest_id: str
    files_processed: int = 0
    events_read: int = 0
    events_inserted: int = 0
    events_quarantined: int = 0
    events_invalid: int = 0
    duplicates_skipped: int = 0
    batches_committed: int = 0
    batches_quarantined: int = 0
    last_source: Optional[str] = None
    last_offset: int = 0
    duration_seconds: float = 0.0


@dataclass(slots=True)
class LoaderCheckpoint:
    """Snapshot emitted after each committed batch."""

    ingest_id: str
    source: str
    offset: int
    batch_index: int
    events_inserted: int
    events_quarantined: int
    sessions: List[str]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class ProcessedEvent:
    """Normalized event ready to be persisted."""

    payload: JsonDict
    risk_score: int
    quarantined: bool
    validation_errors: List[str]
    session_id: Optional[str]
    event_type: Optional[str]
    event_timestamp: Optional[datetime]


class BulkLoader:
    """Stream Cowrie JSON lines into the structured database schema."""

    def __init__(self, engine, config: Optional[BulkLoaderConfig] = None):
        """Create a loader bound to a database engine."""
        self.engine = engine
        self.config = config or BulkLoaderConfig()
        self._session_factory: sessionmaker[Session] = create_session_maker(engine)

    def load_paths(
        self,
        sources: Sequence[str | Path],
        ingest_id: Optional[str] = None,
        telemetry_cb: Optional[TelemetryCallback] = None,
        checkpoint_cb: Optional[Callable[[LoaderCheckpoint], None]] = None,
    ) -> BulkLoaderMetrics:
        """Ingest a sequence of log files and return metrics."""
        ingest_ref = ingest_id or uuid.uuid4().hex
        metrics = BulkLoaderMetrics(ingest_id=ingest_ref)
        start_time = time.perf_counter()

        pending_records: List[JsonDict] = []
        session_aggregates: Dict[str, SessionAggregate] = {}
        telemetry_counter = 0

        with self._session_factory() as session:
            for source in sources:
                metrics.files_processed += 1
                source_path = Path(source)
                source_inode = self._source_inode(source_path)
                for offset, payload in self._iter_source(source_path):
                    metrics.events_read += 1
                    processed = self._process_event(payload)
                    if processed.validation_errors:
                        metrics.events_invalid += 1
                    if processed.quarantined:
                        metrics.events_quarantined += 1

                    record = self._make_raw_event_record(
                        ingest_ref,
                        source_path,
                        source_inode,
                        offset,
                        processed,
                    )
                    pending_records.append(record)

                    if processed.session_id:
                        agg = session_aggregates.setdefault(processed.session_id, SessionAggregate())
                        agg.event_count += 1
                        if processed.event_type and any(hint in processed.event_type for hint in COMMAND_EVENT_HINTS):
                            agg.command_count += 1
                        if processed.event_type and any(hint in processed.event_type for hint in FILE_EVENT_HINTS):
                            agg.file_downloads += 1
                        if processed.event_type and any(hint in processed.event_type for hint in LOGIN_EVENT_HINTS):
                            agg.login_attempts += 1
                        agg.update_timestamp(processed.event_timestamp)
                        agg.highest_risk = max(agg.highest_risk, processed.risk_score)
                        agg.source_files.add(str(source_path))

                    metrics.last_source = str(source_path)
                    metrics.last_offset = offset

                    if len(pending_records) >= self.config.batch_size:
                        self._flush(
                            session,
                            pending_records,
                            session_aggregates,
                            metrics,
                            ingest_ref,
                            metrics.batches_committed + 1,
                            checkpoint_cb,
                        )
                        pending_records = []
                        session_aggregates = {}
                        telemetry_counter += 1
                        if telemetry_cb and telemetry_counter % self.config.telemetry_interval == 0:
                            telemetry_cb(metrics)

            if pending_records:
                self._flush(
                    session,
                    pending_records,
                    session_aggregates,
                    metrics,
                    ingest_ref,
                    metrics.batches_committed + 1,
                    checkpoint_cb,
                )

        metrics.duration_seconds = time.perf_counter() - start_time
        if telemetry_cb:
            telemetry_cb(metrics)
        return metrics

    def _flush(
        self,
        session: Session,
        raw_event_records: List[JsonDict],
        session_aggregates: Dict[str, SessionAggregate],
        metrics: BulkLoaderMetrics,
        ingest_id: str,
        batch_index: int,
        checkpoint_cb: Optional[Callable[[LoaderCheckpoint], None]],
    ) -> None:
        batch_risk = sum(record.get("risk_score", 0) or 0 for record in raw_event_records)
        if batch_risk >= self.config.batch_risk_threshold:
            metrics.batches_quarantined += 1

        with session.begin():
            inserted = self._bulk_insert_raw_events(session, raw_event_records)
            metrics.events_inserted += inserted
            metrics.duplicates_skipped += len(raw_event_records) - inserted
            self._upsert_session_summaries(session, session_aggregates)
        metrics.batches_committed += 1
        if checkpoint_cb:
            last_record = raw_event_records[-1]
            session_ids = list(session_aggregates.keys())
            checkpoint_cb(
                LoaderCheckpoint(
                    ingest_id=ingest_id,
                    source=str(last_record.get("source", "")),
                    offset=int(last_record.get("source_offset", 0)),
                    batch_index=batch_index,
                    events_inserted=inserted,
                    events_quarantined=sum(1 for rec in raw_event_records if rec.get("quarantined")),
                    sessions=session_ids,
                )
            )

    def _bulk_insert_raw_events(self, session: Session, records: List[JsonDict]) -> int:
        if not records:
            return 0

        dialect_name = session.bind.dialect.name if session.bind else ""
        table = cast(Table, RawEvent.__table__)

        if dialect_name == "sqlite":
            stmt = sqlite_dialect.insert(table).values(records)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["source", "source_inode", "source_generation", "source_offset"]
            )
            result = session.execute(stmt)
            return int(result.rowcount or 0)
        if dialect_name == "postgresql" and postgres_dialect is not None:
            pg_stmt = postgres_dialect.insert(table).values(records)
            pg_stmt = pg_stmt.on_conflict_do_nothing(
                index_elements=["source", "source_inode", "source_generation", "source_offset"]
            )
            result = session.execute(pg_stmt)
            return int(result.rowcount or 0)

        inserted = 0
        for record in records:
            try:
                session.execute(table.insert().values(**record))
                inserted += 1
            except IntegrityError:
                session.rollback()
        return inserted

    def _upsert_session_summaries(self, session: Session, aggregates: Dict[str, SessionAggregate]) -> None:
        if not aggregates:
            return

        dialect_name = session.bind.dialect.name if session.bind else ""
        table = cast(Table, SessionSummary.__table__)
        values = []
        for session_id, agg in aggregates.items():
            values.append(
                {
                    "session_id": session_id,
                    "event_count": agg.event_count,
                    "command_count": agg.command_count,
                    "file_downloads": agg.file_downloads,
                    "login_attempts": agg.login_attempts,
                    "first_event_at": agg.first_event_at,
                    "last_event_at": agg.last_event_at,
                    "risk_score": agg.highest_risk,
                    "source_files": sorted(agg.source_files) or None,
                }
            )

        if dialect_name == "sqlite":
            stmt = sqlite_dialect.insert(table).values(values)
            excluded = stmt.excluded
            stmt = stmt.on_conflict_do_update(
                index_elements=["session_id"],
                set_={
                    "event_count": SessionSummary.event_count + excluded.event_count,
                    "command_count": SessionSummary.command_count + excluded.command_count,
                    "file_downloads": SessionSummary.file_downloads + excluded.file_downloads,
                    "login_attempts": SessionSummary.login_attempts + excluded.login_attempts,
                    "first_event_at": func.coalesce(SessionSummary.first_event_at, excluded.first_event_at),
                    "last_event_at": func.max(SessionSummary.last_event_at, excluded.last_event_at),
                    "risk_score": func.max(SessionSummary.risk_score, excluded.risk_score),
                    "source_files": excluded.source_files,
                    "updated_at": func.now(),
                },
            )
            session.execute(stmt)
            return

        if dialect_name == "postgresql" and postgres_dialect is not None:
            pg_stmt = postgres_dialect.insert(table).values(values)
            excluded = pg_stmt.excluded
            pg_stmt = pg_stmt.on_conflict_do_update(
                index_elements=["session_id"],
                set_={
                    "event_count": SessionSummary.event_count + excluded.event_count,
                    "command_count": SessionSummary.command_count + excluded.command_count,
                    "file_downloads": SessionSummary.file_downloads + excluded.file_downloads,
                    "login_attempts": SessionSummary.login_attempts + excluded.login_attempts,
                    "first_event_at": func.least(SessionSummary.first_event_at, excluded.first_event_at),
                    "last_event_at": func.greatest(SessionSummary.last_event_at, excluded.last_event_at),
                    "risk_score": func.greatest(SessionSummary.risk_score, excluded.risk_score),
                    "source_files": excluded.source_files,
                    "updated_at": func.now(),
                },
            )
            session.execute(pg_stmt)
            return

        for value in values:
            try:
                session.execute(table.insert().values(**value))
            except IntegrityError:
                session.rollback()
                session.execute(
                    table.update()
                    .where(SessionSummary.session_id == value["session_id"])
                    .values(**{k: value[k] for k in value if k != "session_id"})
                )

    def _process_event(self, payload: Any) -> ProcessedEvent:
        validation_errors: List[str] = []
        if not isinstance(payload, dict):
            return ProcessedEvent({}, 0, True, ["payload_not_dict"], None, None, None)

        event = dict(payload)
        session_id = event.get("session") or event.get("session_id")
        event_type = event.get("eventid")
        timestamp_raw = event.get("timestamp") or event.get("time")
        event_timestamp = self._parse_timestamp(timestamp_raw)

        if not event_type:
            validation_errors.append("missing_eventid")
        if not timestamp_raw:
            validation_errors.append("missing_timestamp")

        risk_score = self._score_event(event_type, event)
        if self.config.neutralize_commands:
            self._neutralize_payload(event)

        quarantined = bool(validation_errors) or risk_score >= self.config.quarantine_threshold

        return ProcessedEvent(
            payload=event,
            risk_score=risk_score,
            quarantined=quarantined,
            validation_errors=validation_errors,
            session_id=session_id,
            event_type=event_type,
            event_timestamp=event_timestamp,
        )

    def _make_raw_event_record(
        self,
        ingest_id: str,
        source_path: Path,
        source_inode: Optional[int],
        offset: int,
        processed: ProcessedEvent,
        generation: int = 0,
    ) -> JsonDict:
        payload_hash = self._payload_hash(processed.payload)
        return {
            "ingest_id": ingest_id,
            "source": str(source_path),
            "source_offset": offset,
            "source_inode": str(source_inode) if source_inode is not None else None,
            "source_generation": generation,
            "payload": processed.payload,
            "payload_hash": payload_hash,
            "risk_score": processed.risk_score,
            "quarantined": processed.quarantined,
        }

    def _payload_hash(self, payload: Mapping[str, Any]) -> str:
        return hashlib.blake2b(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            digest_size=32,
        ).hexdigest()

    def _iter_source(self, path: Path) -> Iterator[tuple[int, Any]]:
        opener = self._resolve_opener(path)
        with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
            for offset, line in enumerate(handle):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError:
                    yield offset, {"malformed": stripped}
                    continue
                yield offset, payload

    def _resolve_opener(self, path: Path):
        if path.suffix == ".gz":
            return gzip.open
        if path.suffix == ".bz2":
            return bz2.open
        return open

    def _parse_timestamp(self, raw: Any) -> Optional[datetime]:
        if not raw:
            return None
        if isinstance(raw, (int, float)):
            try:
                return datetime.fromtimestamp(float(raw))
            except (OSError, OverflowError):
                return None
        if isinstance(raw, str):
            try:
                return date_parser.isoparse(raw)
            except (ValueError, TypeError):
                return None
        return None

    def _score_event(self, event_type: Optional[str], event: Mapping[str, Any]) -> int:
        score = 0
        if event_type and any(keyword in event_type for keyword in COMMAND_EVENT_HINTS):
            score += 20
        command = event.get("input") or event.get("command")
        if isinstance(command, str):
            lowered = command.lower()
            if any(keyword in lowered for keyword in COMMAND_KEYWORDS):
                score += 40
            if any(pattern in lowered for pattern in SUSPICIOUS_PATTERNS):
                score += 25
        if event.get("eventid") == "cowrie.session.file_download":
            score += 30
        return min(score, 100)

    def _neutralize_payload(self, event: MutableMapping[str, Any]) -> None:
        command_value = event.get("input") or event.get("command")
        if isinstance(command_value, str):
            safe_command = self._neutralize_command(command_value)
            event["input_safe"] = safe_command
            event["input_hash"] = hashlib.blake2b(command_value.encode("utf-8"), digest_size=32).hexdigest()
            event["input"] = None
            event["command"] = None

    def _neutralize_command(self, command: str) -> str:
        sanitized = command
        for pattern in ("http://", "https://"):
            sanitized = sanitized.replace(pattern, "[URL]")
        sanitized = sanitized.replace(";", " [SC] ")
        sanitized = sanitized.replace("&&", " [AND] ")
        sanitized = sanitized.replace("|", " [PIPE] ")
        return " ".join(part for part in sanitized.split() if part)

    def _source_inode(self, path: Path) -> Optional[int]:
        try:
            return path.stat().st_ino
        except (OSError, FileNotFoundError):
            return None


__all__ = ["BulkLoader", "BulkLoaderConfig", "BulkLoaderMetrics"]
