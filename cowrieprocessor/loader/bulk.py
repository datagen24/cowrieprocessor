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
from typing import Any, Callable, Dict, Iterator, List, Mapping, MutableMapping, Optional, Protocol, Sequence, Set, cast

from dateutil import parser as date_parser
from sqlalchemy import Table, func, select
from sqlalchemy.dialects import sqlite as sqlite_dialect

try:  # pragma: no cover - optional dependency
    from sqlalchemy.dialects import postgresql as postgres_dialect
except ModuleNotFoundError:  # pragma: no cover - Postgres optional in tests
    postgres_dialect = cast(Any, None)

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ..db import Files, RawEvent, SessionSummary, create_session_maker
from ..telemetry import start_span
from .defanging import CommandDefanger, get_command_risk_score
from .file_processor import extract_file_data

JsonDict = Dict[str, Any]
TelemetryCallback = Callable[["BulkLoaderMetrics"], None]

# Legacy patterns - kept for backward compatibility but now using intelligent defanging
COMMAND_KEYWORDS = {"curl", "wget", "powershell", "dubious", "nc", "bash", "sh", "python", "perl"}
SUSPICIOUS_PATTERNS = {"/tmp/", "http://", "https://", ";", "&&", "|"}
COMMAND_EVENT_HINTS = {"cowrie.command", "command"}
FILE_EVENT_HINTS = {"file_download", "cowrie.session.file"}
LOGIN_EVENT_HINTS = {"login", "cowrie.login"}


class SessionEnricher(Protocol):
    """Protocol describing the enrichment service used by the loaders."""

    def enrich_session(self, session_id: str, src_ip: str) -> dict[str, Any]:
        """Return enrichment metadata for a session source IP."""

    def enrich_file(self, file_hash: str, filename: str) -> dict[str, Any]:
        """Return enrichment metadata for a downloaded file hash."""


@dataclass(slots=True)
class BulkLoaderConfig:
    """Configuration knobs for the bulk loader."""

    batch_size: int = 500
    quarantine_threshold: int = 90  # Increased from 80 to be less aggressive
    batch_risk_threshold: int = 400
    neutralize_commands: bool = True
    use_intelligent_defanging: bool = True  # New: Use intelligent defanging instead of simple neutralization
    preserve_original_commands: bool = True  # New: Keep original commands for analysis
    telemetry_interval: int = 5  # batches
    max_flush_retries: int = 3
    flush_retry_backoff: float = 1.5
    max_failure_streak: int = 5
    failure_cooldown_seconds: float = 10.0
    multiline_json: bool = False
    hybrid_json: bool = False  # Auto-detect and handle both single-line and multiline JSON


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
    sensor: Optional[str] = None
    src_ips: Set[str] = field(default_factory=set)
    file_hashes: Set[str] = field(default_factory=set)
    vt_flagged: bool = False
    dshield_flagged: bool = False
    urlhaus_flagged: bool = False
    spur_flagged: bool = False
    enrichment_payload: Dict[str, Any] = field(default_factory=dict)

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
    flush_failures: int = 0
    circuit_break_active: bool = False
    cooldowns_applied: int = 0


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


class LoaderCircuitBreakerError(RuntimeError):
    """Raised when the loader circuit breaker is triggered."""


class BulkLoader:
    """Stream Cowrie JSON lines into the structured database schema."""

    def __init__(
        self,
        engine,
        config: Optional[BulkLoaderConfig] = None,
        *,
        enrichment_service: Optional[SessionEnricher] = None,
    ):
        """Create a loader bound to a database engine."""
        self.engine = engine
        self.config = config or BulkLoaderConfig()
        self._session_factory: sessionmaker[Session] = create_session_maker(engine)
        self._failure_streak = 0
        self._enrichment_service = enrichment_service
        self._defanger = CommandDefanger() if self.config.use_intelligent_defanging else None

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
        pending_dead_letters: List[JsonDict] = []
        session_aggregates: Dict[str, SessionAggregate] = {}
        pending_files: List[Files] = []
        telemetry_counter = 0

        with start_span("cowrie.bulk.load", {"ingest.id": ingest_ref, "sources": len(sources)}):
            with self._session_factory() as session:
                for source in sources:
                    metrics.files_processed += 1
                    source_path = Path(source)
                    source_inode = self._source_inode(source_path)
                    with start_span(
                        "cowrie.bulk.file",
                        {"ingest.id": ingest_ref, "source": str(source_path)},
                    ):
                        for offset, payload in self._iter_source(source_path):
                            metrics.events_read += 1

                            # Check if this is a dead letter event
                            if isinstance(payload, dict) and payload.get("_dead_letter"):
                                # Handle dead letter events
                                dead_letter_record = self._make_dead_letter_record(
                                    ingest_ref,
                                    source_path,
                                    source_inode,
                                    offset,
                                    payload,
                                )
                                pending_dead_letters.append(dead_letter_record)
                                metrics.events_quarantined += 1
                                continue

                            # Process as regular event
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
                                payload_ref = processed.payload
                                if isinstance(payload_ref, Mapping):
                                    sensor_val = payload_ref.get("sensor")
                                    if isinstance(sensor_val, str) and sensor_val and agg.sensor is None:
                                        agg.sensor = sensor_val
                                    src_ip_val = payload_ref.get("src_ip") or payload_ref.get("peer_ip")
                                    if isinstance(src_ip_val, str) and src_ip_val:
                                        agg.src_ips.add(src_ip_val)
                                if processed.event_type and any(
                                    hint in processed.event_type for hint in COMMAND_EVENT_HINTS
                                ):
                                    agg.command_count += 1
                                if processed.event_type and any(
                                    hint in processed.event_type for hint in FILE_EVENT_HINTS
                                ):
                                    agg.file_downloads += 1
                                    if isinstance(processed.payload, Mapping):
                                        file_hash = self._extract_file_hash(processed.payload)
                                        if file_hash:
                                            agg.file_hashes.add(file_hash)

                                        # Extract file data for Files table
                                        file_data = extract_file_data(processed.payload, processed.session_id)
                                        if file_data:
                                            from .file_processor import create_files_record

                                            file_record = create_files_record(file_data)
                                            pending_files.append(file_record)
                                if processed.event_type and any(
                                    hint in processed.event_type for hint in LOGIN_EVENT_HINTS
                                ):
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
                                    pending_dead_letters,
                                    session_aggregates,
                                    pending_files,
                                    metrics,
                                    ingest_ref,
                                    metrics.batches_committed + 1,
                                    checkpoint_cb,
                                )
                                pending_records = []
                                pending_dead_letters = []
                                session_aggregates = {}
                                pending_files = []
                                telemetry_counter += 1
                                if telemetry_cb and telemetry_counter % self.config.telemetry_interval == 0:
                                    telemetry_cb(metrics)

                if pending_records or pending_dead_letters:
                    self._flush(
                        session,
                        pending_records,
                        pending_dead_letters,
                        session_aggregates,
                        pending_files,
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
        dead_letter_records: List[JsonDict],
        session_aggregates: Dict[str, SessionAggregate],
        pending_files: List[Files],
        metrics: BulkLoaderMetrics,
        ingest_id: str,
        batch_index: int,
        checkpoint_cb: Optional[Callable[[LoaderCheckpoint], None]],
    ) -> None:
        batch_risk = sum(record.get("risk_score", 0) or 0 for record in raw_event_records)
        if batch_risk >= self.config.batch_risk_threshold:
            metrics.batches_quarantined += 1

        if self._enrichment_service:
            self._apply_enrichment(session_aggregates)

        attempt = 0
        backoff = 1.0
        with start_span(
            "cowrie.bulk.flush",
            {
                "ingest.id": ingest_id,
                "batch.index": batch_index,
                "records": len(raw_event_records),
            },
        ):
            while True:
                try:
                    inserted = self._execute_flush(
                        session, raw_event_records, dead_letter_records, session_aggregates, pending_files
                    )
                    break
                except SQLAlchemyError as exc:  # pragma: no cover - exercised via integration
                    session.rollback()
                    metrics.flush_failures += 1
                    attempt += 1
                    if attempt <= self.config.max_flush_retries:
                        time.sleep(max(0.0, backoff))
                        backoff *= self.config.flush_retry_backoff
                        continue

                    self._failure_streak += 1
                    if self.config.failure_cooldown_seconds > 0:
                        metrics.cooldowns_applied += 1
                        time.sleep(self.config.failure_cooldown_seconds)

                    if self._failure_streak >= self.config.max_failure_streak:
                        metrics.circuit_break_active = True
                        raise LoaderCircuitBreakerError(
                            "Loader circuit breaker tripped after repeated flush failures"
                        ) from exc
                    raise

        self._failure_streak = 0
        metrics.events_inserted += inserted
        metrics.duplicates_skipped += len(raw_event_records) - inserted
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

    def _execute_flush(
        self,
        session: Session,
        raw_event_records: List[JsonDict],
        dead_letter_records: List[JsonDict],
        session_aggregates: Dict[str, SessionAggregate],
        pending_files: List[Files],
    ) -> int:
        """Execute a single flush attempt returning inserted event count."""
        with session.begin():
            # Insert regular events
            regular_inserted = self._bulk_insert_raw_events(session, raw_event_records) if raw_event_records else 0

            # Insert dead letter events
            dead_letter_inserted = (
                self._bulk_insert_dead_letters(session, dead_letter_records) if dead_letter_records else 0
            )

            self._upsert_session_summaries(session, session_aggregates)
            self._bulk_insert_files(session, pending_files)

        return regular_inserted + dead_letter_inserted

    def _apply_enrichment(self, session_aggregates: Dict[str, SessionAggregate]) -> None:
        """Populate enrichment metadata and flags for the pending session aggregates."""
        if not self._enrichment_service:
            return

        for session_id, aggregate in session_aggregates.items():
            # Resolve and enrich each observed source IP
            session_store = aggregate.enrichment_payload.setdefault("session", {})
            for src_ip in aggregate.src_ips:
                session_result = self._enrichment_service.enrich_session(session_id, src_ip)
                enrichment = session_result.get("enrichment", {})
                session_store[src_ip] = enrichment
                self._update_session_flags(aggregate, enrichment)

            # Resolve VirusTotal metadata for downloaded files
            vt_store = aggregate.enrichment_payload.setdefault("virustotal", {})
            for file_hash in aggregate.file_hashes:
                file_result = self._enrichment_service.enrich_file(file_hash, file_hash)
                vt_data = file_result.get("enrichment", {}).get("virustotal")
                if vt_data is None:
                    continue
                vt_store[file_hash] = vt_data
                self._update_vt_flag(aggregate, vt_data)

    def _update_session_flags(self, aggregate: SessionAggregate, enrichment: Mapping[str, Any]) -> None:
        """Set aggregate flags based on session-level enrichment payload."""
        dshield_data = enrichment.get("dshield")
        if isinstance(dshield_data, Mapping):
            ip_info = dshield_data.get("ip", {})
            if isinstance(ip_info, Mapping):
                count = self._coerce_int(ip_info.get("count"))
                attacks = self._coerce_int(ip_info.get("attacks"))
                aggregate.dshield_flagged = aggregate.dshield_flagged or (count > 0 or attacks > 0)

        urlhaus_tags = enrichment.get("urlhaus")
        if isinstance(urlhaus_tags, str):
            aggregate.urlhaus_flagged = aggregate.urlhaus_flagged or bool(urlhaus_tags.strip())

        spur_data = enrichment.get("spur")
        if isinstance(spur_data, list) and len(spur_data) > 3:
            infrastructure = spur_data[3]
            if isinstance(infrastructure, str):
                aggregate.spur_flagged = aggregate.spur_flagged or infrastructure.upper() in {
                    "DATACENTER",
                    "VPN",
                }

    def _update_vt_flag(self, aggregate: SessionAggregate, vt_data: Mapping[str, Any]) -> None:
        """Update the VirusTotal flag when a malicious verdict is observed."""
        data_obj = vt_data.get("data")
        if not isinstance(data_obj, Mapping):
            return
        attributes = data_obj.get("attributes")
        if not isinstance(attributes, Mapping):
            return
        stats = attributes.get("last_analysis_stats")
        if not isinstance(stats, Mapping):
            return
        malicious = self._coerce_int(stats.get("malicious"))
        aggregate.vt_flagged = aggregate.vt_flagged or malicious > 0

    @staticmethod
    def _coerce_int(value: Any) -> int:
        """Best-effort conversion of heterogeneous number representations to integers."""
        if isinstance(value, bool):
            return int(value)
        try:
            return int(value) if value is not None else 0
        except (TypeError, ValueError):
            return 0

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

    def _bulk_insert_files(self, session: Session, files: List[Files]) -> int:
        """Bulk insert files with conflict resolution."""
        if not files:
            return 0

        dialect_name = session.bind.dialect.name if session.bind else ""
        table = cast(Table, Files.__table__)

        if dialect_name == "sqlite":
            stmt = sqlite_dialect.insert(table)
            stmt = stmt.on_conflict_do_nothing(index_elements=["session_id", "shasum"])
            result = session.execute(stmt, [self._files_to_dict(f) for f in files])
            return int(result.rowcount or 0)
        if dialect_name == "postgresql" and postgres_dialect is not None:
            pg_stmt = postgres_dialect.insert(table)
            pg_stmt = pg_stmt.on_conflict_do_nothing(index_elements=["session_id", "shasum"])
            result = session.execute(pg_stmt, [self._files_to_dict(f) for f in files])
            return int(result.rowcount or 0)

        inserted = 0
        for file_record in files:
            try:
                session.execute(table.insert().values(**self._files_to_dict(file_record)))
                inserted += 1
            except IntegrityError:
                session.rollback()
        return inserted

    def _files_to_dict(self, file_record: Files) -> Dict[str, Any]:
        """Convert Files ORM object to dictionary for bulk insert."""
        return {
            "session_id": file_record.session_id,
            "shasum": file_record.shasum,
            "filename": file_record.filename,
            "file_size": file_record.file_size,
            "download_url": file_record.download_url,
            "vt_classification": file_record.vt_classification,
            "vt_description": file_record.vt_description,
            "vt_malicious": file_record.vt_malicious or False,  # Default to False for NOT NULL field
            "vt_first_seen": file_record.vt_first_seen,
            "vt_last_analysis": file_record.vt_last_analysis,
            "vt_positives": file_record.vt_positives,
            "vt_total": file_record.vt_total,
            "vt_scan_date": file_record.vt_scan_date,
            "first_seen": file_record.first_seen,
            # Don't include last_updated - let the database set it with server_default
            "enrichment_status": file_record.enrichment_status or "pending",  # Default to pending
        }

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
                    "matcher": agg.sensor,
                    "vt_flagged": agg.vt_flagged,  # Keep as boolean, not int
                    "dshield_flagged": agg.dshield_flagged,  # Keep as boolean, not int
                    "enrichment": agg.enrichment_payload or None,
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
                    "matcher": func.coalesce(SessionSummary.matcher, excluded.matcher),
                    "vt_flagged": excluded.vt_flagged,  # Use excluded value directly (boolean)
                    "dshield_flagged": excluded.dshield_flagged,  # Use excluded value directly (boolean)
                    "enrichment": func.coalesce(excluded.enrichment, SessionSummary.enrichment),
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
                    "matcher": func.coalesce(SessionSummary.matcher, excluded.matcher),
                    "vt_flagged": excluded.vt_flagged,  # Use excluded value directly (boolean)
                    "dshield_flagged": excluded.dshield_flagged,  # Use excluded value directly (boolean)
                    "enrichment": func.coalesce(excluded.enrichment, SessionSummary.enrichment),
                    "updated_at": func.now(),
                },
            )
            session.execute(pg_stmt)
            return

        # Use proper upsert for all database types to avoid race conditions
        # The SQLite and PostgreSQL versions already use on_conflict_do_update
        # For other databases, implement a more robust approach
        if dialect_name not in ("sqlite", "postgresql"):
            # For other databases, use a safer approach with explicit locking
            for value in values:
                current_session_id: str = str(value["session_id"])
                try:
                    # Try to insert first
                    session.execute(table.insert().values(**value))
                except IntegrityError:
                    # If it fails due to constraint violation, update instead
                    session.rollback()
                    # Use SELECT FOR UPDATE to lock the row during update
                    existing = session.execute(
                        select(SessionSummary).where(SessionSummary.session_id == current_session_id).with_for_update()
                    ).first()
                    if existing:
                        update_values = {k: value[k] for k in value if k != "session_id"}
                        session.execute(
                            table.update().where(table.c.session_id == current_session_id).values(**update_values)
                        )
                    else:
                        # If no existing row found, try insert again
                        session.execute(table.insert().values(**value))

    def _process_event(self, payload: Any) -> ProcessedEvent:
        validation_errors: List[str] = []

        # Handle dead letter events specially
        if isinstance(payload, dict) and payload.get("_dead_letter"):
            # Dead letter events should be quarantined but preserve their content
            return ProcessedEvent(
                payload=payload,
                risk_score=100,  # High risk for malformed content
                quarantined=True,
                validation_errors=["dead_letter_event"],
                session_id=None,
                event_type="dead_letter",
                event_timestamp=None,
            )

        if not isinstance(payload, dict):
            # Create a proper dead letter event for non-dict payloads
            dead_letter_payload = {
                "_dead_letter": True,
                "_reason": "payload_not_dict",
                "_malformed_content": str(payload),
                "_timestamp": datetime.now(UTC).isoformat(),
            }
            return ProcessedEvent(
                payload=dead_letter_payload,
                risk_score=100,
                quarantined=True,
                validation_errors=["payload_not_dict"],
                session_id=None,
                event_type="dead_letter",
                event_timestamp=None,
            )

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
            "session_id": processed.session_id,
            "event_type": processed.event_type,
            "event_timestamp": processed.event_timestamp.isoformat() if processed.event_timestamp else None,
        }

    def _payload_hash(self, payload: Mapping[str, Any]) -> str:
        return hashlib.blake2b(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            digest_size=32,
        ).hexdigest()

    def _iter_source(self, path: Path) -> Iterator[tuple[int, Any]]:
        opener = self._resolve_opener(path)
        with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
            if self.config.hybrid_json:
                # Use improved hybrid processor
                from .improved_hybrid import ImprovedHybridProcessor

                processor = ImprovedHybridProcessor()
                yield from processor.process_lines(handle)
            elif self.config.multiline_json:
                yield from self._iter_multiline_json(handle)
            else:
                yield from self._iter_line_by_line(handle)

    def _iter_hybrid_json(self, handle) -> Iterator[tuple[int, Any]]:
        """Iterate through JSON that may contain both single-line and multiline objects."""
        accumulated_lines: list[str] = []
        start_offset = 0

        for offset, line in enumerate(handle):
            stripped = line.strip()
            if not stripped:
                continue

            # Try parsing as a single line first
            try:
                payload = json.loads(stripped)
                # If we have accumulated lines, they might be incomplete - send to DLQ
                if accumulated_lines:
                    yield start_offset, self._make_dead_letter_event("\n".join(accumulated_lines))
                    accumulated_lines = []
                yield offset, payload
                continue
            except json.JSONDecodeError:
                pass

            # If single-line parsing failed, add to accumulation
            if not accumulated_lines:
                start_offset = offset
            accumulated_lines.append(stripped)

            # Try to parse accumulated content
            try:
                combined_content = "\n".join(accumulated_lines)
                payload = json.loads(combined_content)
                yield start_offset, payload
                accumulated_lines = []
                continue
            except json.JSONDecodeError:
                # If it's incomplete JSON, continue accumulating
                # If we've accumulated too much, send to DLQ
                if len(accumulated_lines) > 100:  # Reasonable limit for multiline objects
                    yield start_offset, self._make_dead_letter_event("\n".join(accumulated_lines))
                    accumulated_lines = []
                continue

        # Handle any remaining accumulated content
        if accumulated_lines:
            try:
                combined_content = "\n".join(accumulated_lines)
                payload = json.loads(combined_content)
                yield start_offset, payload
            except json.JSONDecodeError:
                yield start_offset, self._make_dead_letter_event("\n".join(accumulated_lines))

    def _make_dead_letter_event(self, malformed_content: str) -> dict:
        """Create a dead letter event for malformed JSON content."""
        return {
            "_dead_letter": True,
            "_reason": "json_parsing_failed",
            "_malformed_content": malformed_content,
            "_timestamp": datetime.now(UTC).isoformat(),
        }

    def _make_dead_letter_record(
        self,
        ingest_id: str,
        source_path: Path,
        source_inode: Optional[int],
        offset: int,
        dead_letter_payload: dict,
    ) -> JsonDict:
        """Create a dead letter record for the DLQ table."""
        return {
            "ingest_id": ingest_id,
            "source": str(source_path),
            "source_offset": offset,
            "reason": dead_letter_payload.get("_reason", "unknown"),
            "payload": {
                "malformed_content": dead_letter_payload.get("_malformed_content"),
                "parsing_timestamp": dead_letter_payload.get("_timestamp"),
                "original_offset": offset,
            },
            "metadata_json": {
                "json_parsing_failed": True,
                "potentially_multiline": True,
                "requires_investigation": True,
            },
        }

    def _bulk_insert_dead_letters(self, session: Session, dead_letter_records: List[JsonDict]) -> int:
        """Bulk insert dead letter events into the DLQ table."""
        from sqlalchemy.exc import IntegrityError

        from ..db import DeadLetterEvent

        if not dead_letter_records:
            return 0

        table = DeadLetterEvent.__table__
        try:
            result = session.execute(table.insert(), dead_letter_records)
            return int(result.rowcount or 0)
        except IntegrityError:
            session.rollback()
            # Fall back to individual inserts if bulk insert fails
            inserted = 0
            for record in dead_letter_records:
                try:
                    session.execute(table.insert().values(**record))
                    inserted += 1
                except IntegrityError:
                    # Skip duplicates
                    pass
            return inserted

    def _iter_line_by_line(self, handle) -> Iterator[tuple[int, Any]]:
        """Iterate through JSON lines, one object per line."""
        for offset, line in enumerate(handle):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                yield offset, self._make_dead_letter_event(stripped)
                continue
            yield offset, payload

    def _iter_multiline_json(self, handle) -> Iterator[tuple[int, Any]]:
        """Iterate through potentially multiline JSON objects."""
        accumulated_lines: list[str] = []
        start_offset = 0

        for offset, line in enumerate(handle):
            stripped = line.strip()
            if not stripped:
                continue

            # If we're not accumulating, this might be the start of a new object
            if not accumulated_lines:
                start_offset = offset
                accumulated_lines.append(stripped)
            else:
                accumulated_lines.append(stripped)

            # Try to parse the accumulated content
            try:
                combined_content = "\n".join(accumulated_lines)
                payload = json.loads(combined_content)
                yield start_offset, payload
                accumulated_lines = []
                continue
            except json.JSONDecodeError:
                # If it's incomplete JSON, continue accumulating
                # If we've accumulated too much, send to DLQ
                if len(accumulated_lines) > 100:  # Reasonable limit for multiline objects
                    yield start_offset, self._make_dead_letter_event("\n".join(accumulated_lines))
                    accumulated_lines = []
                continue

        # Handle any remaining accumulated content
        if accumulated_lines:
            try:
                combined_content = "\n".join(accumulated_lines)
                payload = json.loads(combined_content)
                yield start_offset, payload
            except json.JSONDecodeError:
                yield start_offset, self._make_dead_letter_event("\n".join(accumulated_lines))

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
        """Calculate risk score for an event using intelligent command analysis."""
        score = 0

        # Use intelligent command scoring if available
        command = event.get("input") or event.get("command")
        if isinstance(command, str):
            if self._defanger:
                # Use intelligent scoring from defanger (includes command event base score)
                score = get_command_risk_score(command)
                # Add base score for command events
                if event_type and any(keyword in event_type for keyword in COMMAND_EVENT_HINTS):
                    score += 10
            else:
                # Fallback to legacy scoring
                if event_type and any(keyword in event_type for keyword in COMMAND_EVENT_HINTS):
                    score += 20
                lowered = command.lower()
                if any(keyword in lowered for keyword in COMMAND_KEYWORDS):
                    score += 40
                if any(pattern in lowered for pattern in SUSPICIOUS_PATTERNS):
                    score += 25

        # File downloads get moderate score (reduced from 30 to 20)
        if event.get("eventid") == "cowrie.session.file_download":
            score += 20

        return min(score, 100)

    def _neutralize_payload(self, event: MutableMapping[str, Any]) -> None:
        """Apply intelligent defanging to command payloads while preserving investigative data."""
        command_value = event.get("input") or event.get("command")
        if not isinstance(command_value, str):
            return

        if self._defanger and self.config.use_intelligent_defanging:
            # Use intelligent defanging
            analysis = self._defanger.analyze_command(command_value)

            # Always store analysis
            event["command_analysis"] = analysis

            if analysis["needs_defanging"]:
                # Create defanged version
                defanged_command = self._defanger.create_safe_command(command_value)
                event["input_safe"] = defanged_command
                event["command_safe"] = defanged_command

                # Store hash for integrity
                event["input_hash"] = hashlib.blake2b(command_value.encode("utf-8"), digest_size=32).hexdigest()

                if self.config.preserve_original_commands:
                    # Keep original command for analysis
                    event["input_original"] = command_value
                    event["command_original"] = command_value
                    # Replace original with defanged version
                    event["input"] = defanged_command
                    event["command"] = defanged_command
                else:
                    # Don't preserve original, just use defanged version
                    event["input"] = defanged_command
                    event["command"] = defanged_command
            else:
                # Safe command - no defanging needed
                event["input_safe"] = command_value
                event["command_safe"] = command_value
                # Safe commands don't need original preservation
        else:
            # Legacy neutralization
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

    def _extract_file_hash(self, payload: Mapping[str, Any]) -> Optional[str]:
        """Extract a representative file hash from an event payload when available."""
        for key in ("sha256", "shasum", "sha1", "sha512", "hash"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        return None


__all__ = ["BulkLoader", "BulkLoaderConfig", "BulkLoaderMetrics"]
