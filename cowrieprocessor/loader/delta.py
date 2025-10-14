"""Delta ingestion pipeline that reuses bulk processing to capture new events."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, cast

from sqlalchemy import Table, func, select
from sqlalchemy.dialects import sqlite as sqlite_dialect

try:  # pragma: no cover - optional dependency
    from sqlalchemy.dialects import postgresql as postgres_dialect
except ModuleNotFoundError:  # pragma: no cover - Postgres optional in tests
    postgres_dialect = cast(Any, None)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import DeadLetterEvent, IngestCursor, RawEvent
from ..telemetry import start_span
from ..enrichment.ssh_key_extractor import SSHKeyExtractor
from .bulk import (
    COMMAND_EVENT_HINTS,
    FILE_EVENT_HINTS,
    LOGIN_EVENT_HINTS,
    BulkLoader,
    BulkLoaderConfig,
    BulkLoaderMetrics,
    LoaderCheckpoint,
    SessionAggregate,
    SessionEnricher,
    TelemetryCallback,
)


@dataclass(slots=True)
class DeltaLoaderConfig:
    """Configuration for delta ingestion."""

    bulk: BulkLoaderConfig = field(default_factory=lambda: BulkLoaderConfig(batch_size=200))
    allow_inode_reset: bool = True
    max_seek_ahead: int = 10_000


class DeltaLoader:
    """Incremental loader that only ingests new events since the last run."""

    def __init__(
        self,
        engine,
        config: Optional[DeltaLoaderConfig] = None,
        *,
        enrichment_service: Optional[SessionEnricher] = None,
    ):
        """Bind the delta loader to a database engine and configuration."""
        self.config = config or DeltaLoaderConfig()
        self._bulk = BulkLoader(engine, self.config.bulk, enrichment_service=enrichment_service)
        self._session_factory = self._bulk._session_factory  # reuse session factory
        self._ssh_key_extractor = SSHKeyExtractor()

    def load_paths(
        self,
        sources: Iterable[str | Path],
        ingest_id: Optional[str] = None,
        telemetry_cb: Optional[TelemetryCallback] = None,
        checkpoint_cb: Optional[Callable[[LoaderCheckpoint], None]] = None,
        dead_letter_cb: Optional[Callable[[int, Optional[str], Optional[str]], None]] = None,
    ) -> BulkLoaderMetrics:
        """Process only new events from the provided sources and return metrics."""
        ingest_ref = ingest_id or uuid.uuid4().hex
        metrics = BulkLoaderMetrics(ingest_id=ingest_ref)

        source_paths = [Path(src) for src in sources]

        pending_records: List[dict] = []
        session_aggregates: Dict[str, SessionAggregate] = {}
        telemetry_counter = 0
        dead_letters: List[dict] = []

        with start_span("cowrie.delta.load", {"ingest.id": ingest_ref, "sources": len(source_paths)}):
            with self._session_factory() as session:
                cursor_map = self._load_cursors(session)
                for path in source_paths:
                    cursor = cursor_map.get(str(path))
                    if cursor is None:
                        cursor = self._bootstrap_cursor(session, cursor_map, str(path), ingest_ref)
                    generation = self._cursor_generation(cursor)
                    inode = self._bulk._source_inode(path)
                    inode_str = str(inode) if inode is not None else None
                    cursor_inode = self._get_cursor_inode(cursor)
                    last_offset = self._get_cursor_last_offset(cursor)
                    cursor_changed = False
                    first_hash_value = self._cursor_first_hash(cursor)
                    metrics.files_processed += 1

                    with start_span(
                        "cowrie.delta.file",
                        {"ingest.id": ingest_ref, "source": str(path)},
                    ):
                        for offset, payload in self._bulk._iter_source(path):
                            inode_changed = (
                                cursor is not None
                                and cursor_inode is not None
                                and inode_str is not None
                                and cursor_inode != inode_str
                            )

                            processed = self._bulk._process_event(payload)
                            event_hash = self._bulk._payload_hash(processed.payload)
                            reset_generation = inode_changed or (
                                cursor is not None
                                and offset == 0
                                and first_hash_value
                                and event_hash != first_hash_value
                            )
                            if reset_generation:
                                self._set_cursor_last_offset(cursor, -1)
                            if not self._should_process(offset, inode, cursor):
                                continue
                            if reset_generation:
                                generation += 1
                            metrics.events_read += 1
                            if processed.validation_errors:
                                metrics.events_invalid += 1
                                dead_letters.append(
                                    self._dead_letter_record(ingest_ref, str(path), offset, "validation", processed)
                                )
                                metrics.last_source = str(path)
                                metrics.last_offset = offset
                                last_offset = max(last_offset, offset)
                                continue
                            if processed.quarantined:
                                metrics.events_quarantined += 1
                                dead_letters.append(
                                    self._dead_letter_record(ingest_ref, str(path), offset, "quarantined", processed)
                                )

                            record = self._bulk._make_raw_event_record(
                                ingest_ref,
                                path,
                                inode,
                                offset,
                                processed,
                                generation,
                            )
                            pending_records.append(record)
                            if offset == 0:
                                first_hash_value = record["payload_hash"]

                            if processed.session_id:
                                aggregate = session_aggregates.setdefault(processed.session_id, SessionAggregate())
                                aggregate.event_count += 1
                                if processed.event_type and any(h in processed.event_type for h in COMMAND_EVENT_HINTS):
                                    aggregate.command_count += 1
                                if processed.event_type and any(h in processed.event_type for h in FILE_EVENT_HINTS):
                                    aggregate.file_downloads += 1
                                if processed.event_type and any(h in processed.event_type for h in LOGIN_EVENT_HINTS):
                                    aggregate.login_attempts += 1
                                if processed.event_timestamp:
                                    aggregate.update_timestamp(processed.event_timestamp)
                                aggregate.highest_risk = max(aggregate.highest_risk, processed.risk_score)
                                aggregate.source_files.add(str(path))
                                
                                # Extract SSH keys from command events
                                if processed.event_type and any(h in processed.event_type for h in COMMAND_EVENT_HINTS):
                                    if processed.input and "authorized_keys" in processed.input:
                                        try:
                                            extracted_keys = self._ssh_key_extractor.extract_keys_from_command(processed.input)
                                            if extracted_keys:
                                                aggregate.ssh_key_injections += len(extracted_keys)
                                                for key in extracted_keys:
                                                    aggregate.unique_ssh_keys.add(key.key_hash)
                                        except Exception:
                                            # Log error but don't fail the ingestion
                                            pass

                            metrics.last_source = str(path)
                            metrics.last_offset = offset
                            last_offset = max(last_offset, offset)

                            if len(pending_records) >= self.config.bulk.batch_size:
                                self._flush(
                                    session,
                                    ingest_ref,
                                    pending_records,
                                    session_aggregates,
                                    metrics,
                                    checkpoint_cb,
                                    dead_letters,
                                    str(path),
                                    last_offset,
                                    inode,
                                    dead_letter_cb,
                                )
                                pending_records = []
                                session_aggregates = {}
                                dead_letters = []
                                cursor = self._update_cursor(
                                    cursor_map,
                                    str(path),
                                    inode,
                                    last_offset,
                                    ingest_ref,
                                    generation,
                                    first_hash_value,
                                )
                                self._save_cursor(session, cursor)
                                cursor_inode = self._get_cursor_inode(cursor)
                                cursor_changed = True
                                telemetry_counter += 1
                                if telemetry_cb and telemetry_counter % self.config.bulk.telemetry_interval == 0:
                                    telemetry_cb(metrics)

                    if pending_records:
                        self._flush(
                            session,
                            ingest_ref,
                            pending_records,
                            session_aggregates,
                            metrics,
                            checkpoint_cb,
                            dead_letters,
                            str(path),
                            last_offset,
                            inode,
                            dead_letter_cb,
                        )
                        pending_records = []
                        session_aggregates = {}
                        dead_letters = []
                        cursor = self._update_cursor(
                            cursor_map,
                            str(path),
                            inode,
                            last_offset,
                            ingest_ref,
                            generation,
                            first_hash_value,
                        )
                        self._save_cursor(session, cursor)
                        cursor_changed = True
                        cursor_inode = self._get_cursor_inode(cursor)

                    if dead_letters:
                        inserted = self._persist_dead_letters(session, dead_letters)
                        if dead_letter_cb and inserted:
                            last = dead_letters[-1]
                            dead_letter_cb(inserted, last.get("reason"), last.get("source"))
                        dead_letters = []

                    if last_offset > (cursor.last_offset if cursor else -1) and not cursor_changed:
                        cursor = self._update_cursor(
                            cursor_map,
                            str(path),
                            inode,
                            last_offset,
                            ingest_ref,
                            generation,
                            first_hash_value,
                        )
                        self._save_cursor(session, cursor)
                        cursor_inode = self._get_cursor_inode(cursor)

                session.commit()

        if telemetry_cb:
            telemetry_cb(metrics)
        return metrics

    def _flush(
        self,
        session: Session,
        ingest_id: str,
        raw_event_records: List[dict],
        session_aggregates: Dict[str, SessionAggregate],
        metrics: BulkLoaderMetrics,
        checkpoint_cb: Optional[Callable[[LoaderCheckpoint], None]],
        dead_letters: List[dict],
        source: str,
        offset: int,
        inode: Optional[int],
        dead_letter_cb: Optional[Callable[[int, Optional[str], Optional[str]], None]],
    ) -> None:
        if session.in_transaction():
            session.commit()
        with start_span(
            "cowrie.delta.flush",
            {
                "ingest.id": ingest_id,
                "records": len(raw_event_records),
                "source": source,
            },
        ):
            self._bulk._flush(
                session,
                raw_event_records,
                dead_letters,
                session_aggregates,
                [],  # pending_files - empty for delta loader
                metrics,
                ingest_id,
                metrics.batches_committed + 1,
                checkpoint_cb,
            )
        if dead_letters:
            inserted = self._persist_dead_letters(session, dead_letters)
            if dead_letter_cb and inserted:
                last = dead_letters[-1]
                dead_letter_cb(inserted, last.get("reason"), last.get("source"))

    def _dead_letter_record(self, ingest_id: str, source: str, offset: int, reason: str, processed) -> dict:
        return {
            "ingest_id": ingest_id,
            "source": source,
            "source_offset": offset,
            "reason": reason,
            "payload": processed.payload,
        }

    def _persist_dead_letters(self, session: Session, records: List[dict]) -> int:
        table = cast(Table, DeadLetterEvent.__table__)
        try:
            result = session.execute(table.insert(), records)
            return int(result.rowcount or 0)
        except IntegrityError:
            session.rollback()
            inserted = 0
            for record in records:
                try:
                    session.execute(table.insert().values(**record))
                    inserted += 1
                except IntegrityError:
                    session.rollback()
            return inserted
        return len(records)

    def _load_cursors(self, session: Session) -> Dict[str, IngestCursor]:
        result = session.execute(select(IngestCursor)).scalars()
        cursor_map: Dict[str, IngestCursor] = {}
        for cursor in result:
            source_value = getattr(cursor, "source", None)
            if source_value is None:
                continue
            cursor_map[str(source_value)] = cursor
        return cursor_map

    def _update_cursor(
        self,
        cursor_map: Dict[str, IngestCursor],
        source: str,
        inode: Optional[int],
        last_offset: int,
        ingest_id: str,
        generation: int,
        first_hash: Optional[str],
    ) -> IngestCursor:
        cursor = cursor_map.get(source)
        inode_value = str(inode) if inode is not None else None
        if cursor is None:
            cursor = IngestCursor(
                source=source,
                inode=inode_value,
                last_offset=last_offset,
                last_ingest_id=ingest_id,
                metadata_json={"generation": generation, "first_hash": first_hash},
            )
            cursor_map[source] = cursor
        else:
            self._set_cursor_inode(cursor, inode_value)
            self._set_cursor_last_offset(cursor, last_offset)
            setattr(cursor, "last_ingest_id", ingest_id)
            meta_obj = getattr(cursor, "metadata_json", None)
            meta: Dict[str, Any]
            if isinstance(meta_obj, dict):
                meta = dict(meta_obj)
            else:
                meta = {}
            meta["generation"] = generation
            if first_hash:
                meta["first_hash"] = first_hash
            setattr(cursor, "metadata_json", meta)
        return cursor

    def _save_cursor(self, session: Session, cursor: IngestCursor) -> None:
        table = cast(Table, IngestCursor.__table__)
        metadata_obj = getattr(cursor, "metadata_json", None)
        metadata_json = dict(metadata_obj) if isinstance(metadata_obj, dict) else metadata_obj
        values = {
            "source": getattr(cursor, "source"),
            "inode": getattr(cursor, "inode", None),
            "last_offset": getattr(cursor, "last_offset", -1),
            "last_ingest_id": getattr(cursor, "last_ingest_id", None),
            "metadata_json": metadata_json,
        }

        dialect_name = session.bind.dialect.name if session.bind else ""

        if dialect_name == "sqlite":
            stmt = sqlite_dialect.insert(table).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["source"],
                set_={
                    "inode": values["inode"],
                    "last_offset": values["last_offset"],
                    "last_ingest_id": values["last_ingest_id"],
                    "metadata_json": values["metadata_json"],
                    "last_ingest_at": func.now(),
                },
            )
            session.execute(stmt)
            return

        if dialect_name == "postgresql" and postgres_dialect is not None:
            stmt = cast(Any, postgres_dialect.insert(table).values(**values))
            stmt = stmt.on_conflict_do_update(
                index_elements=["source"],
                set_={
                    "inode": values["inode"],
                    "last_offset": values["last_offset"],
                    "last_ingest_id": values["last_ingest_id"],
                    "metadata_json": values["metadata_json"],
                    "last_ingest_at": func.now(),
                },
            )
            session.execute(stmt)
            return

        session.merge(cursor)

    def _should_process(self, offset: int, inode: Optional[int], cursor: Optional[IngestCursor]) -> bool:
        if cursor is None:
            return True
        inode_str = str(inode) if inode is not None else None
        cursor_inode = self._get_cursor_inode(cursor)
        current_offset = self._get_cursor_last_offset(cursor)
        if inode_str is not None and cursor_inode is not None and cursor_inode != inode_str:
            self._set_cursor_last_offset(cursor, -1)
            return self.config.allow_inode_reset
        if offset > current_offset:
            return True
        return False

    def _cursor_generation(self, cursor: Optional[IngestCursor]) -> int:
        if cursor and cursor.metadata_json and isinstance(cursor.metadata_json, dict):
            try:
                return int(cursor.metadata_json.get("generation", 0))
            except (TypeError, ValueError):
                return 0
        return 0

    def _cursor_first_hash(self, cursor: Optional[IngestCursor]) -> Optional[str]:
        if cursor and cursor.metadata_json and isinstance(cursor.metadata_json, dict):
            value = cursor.metadata_json.get("first_hash")
            return str(value) if value is not None else None
        return None

    def _get_cursor_inode(self, cursor: Optional[IngestCursor]) -> Optional[str]:
        return str(getattr(cursor, "inode")) if cursor and getattr(cursor, "inode", None) is not None else None

    def _get_cursor_last_offset(self, cursor: Optional[IngestCursor]) -> int:
        return int(getattr(cursor, "last_offset", -1)) if cursor else -1

    def _set_cursor_last_offset(self, cursor: Optional[IngestCursor], value: int) -> None:
        if cursor is not None:
            setattr(cursor, "last_offset", value)

    def _set_cursor_inode(self, cursor: Optional[IngestCursor], value: Optional[str]) -> None:
        if cursor is not None:
            setattr(cursor, "inode", value)

    def _bootstrap_cursor(
        self,
        session: Session,
        cursor_map: Dict[str, IngestCursor],
        source: str,
        ingest_id: str,
    ) -> Optional[IngestCursor]:
        stmt = (
            select(
                RawEvent.source_inode,
                RawEvent.source_generation,
                func.max(RawEvent.source_offset),
            )
            .where(RawEvent.source == source)
            .group_by(RawEvent.source_inode, RawEvent.source_generation)
            .order_by(RawEvent.source_generation.desc())
        )
        row = session.execute(stmt).first()
        if not row:
            return None
        inode_value, generation, max_offset = row
        first_hash_row = session.execute(
            select(RawEvent.payload_hash)
            .where(
                RawEvent.source == source,
                RawEvent.source_generation == generation,
                RawEvent.source_offset == 0,
            )
            .limit(1)
        ).first()
        first_hash = first_hash_row[0] if first_hash_row else None
        cursor = self._update_cursor(
            cursor_map,
            source,
            int(inode_value) if inode_value is not None else None,
            int(max_offset) if max_offset is not None else -1,
            ingest_id,
            int(generation) if generation is not None else 0,
            first_hash,
        )
        self._save_cursor(session, cursor)
        return cursor


__all__ = ["DeltaLoader", "DeltaLoaderConfig"]
