"""ORM models for the refactored Cowrie processor database."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Computed,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from .base import Base


class SchemaState(Base):
    """Key/value metadata used to track schema versions and flags."""

    __tablename__ = "schema_state"

    key = Column(String(128), primary_key=True)
    value = Column(String(256), nullable=False)


class RawEvent(Base):
    """Persistent copy of raw Cowrie events with JSON payloads and virtual columns."""

    __tablename__ = "raw_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ingest_id = Column(String(64), nullable=True)
    ingest_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    source = Column(String(512), nullable=False)
    source_offset = Column(BigInteger, nullable=True)
    source_inode = Column(String(128), nullable=True)
    source_generation = Column(Integer, nullable=False, server_default="0")
    payload = Column(JSON, nullable=False)
    payload_hash = Column(String(64), nullable=True)
    risk_score = Column(Integer, nullable=True)
    quarantined = Column(Boolean, nullable=False, server_default="0")

    session_id = Column(
        String(64),
        Computed("json_extract(payload, '$.session')", persisted=False),
    )
    event_type = Column(
        String(128),
        Computed("json_extract(payload, '$.eventid')", persisted=False),
    )
    event_timestamp = Column(
        String(64),
        Computed("json_extract(payload, '$.timestamp')", persisted=False),
    )

    __table_args__ = (
        UniqueConstraint(
            "source",
            "source_inode",
            "source_generation",
            "source_offset",
            name="uq_raw_events_source_offset",
        ),
        Index("ix_raw_events_session_id", "session_id"),
        Index("ix_raw_events_event_type", "event_type"),
        Index("ix_raw_events_event_timestamp", "event_timestamp"),
        Index("ix_raw_events_ingest_at", "ingest_at"),
    )


class SessionSummary(Base):
    """Aggregated per-session metrics derived during ingest."""

    __tablename__ = "session_summaries"

    session_id = Column(String(64), primary_key=True)
    first_event_at = Column(DateTime(timezone=True))
    last_event_at = Column(DateTime(timezone=True))
    event_count = Column(Integer, nullable=False, server_default="0")
    command_count = Column(Integer, nullable=False, server_default="0")
    file_downloads = Column(Integer, nullable=False, server_default="0")
    login_attempts = Column(Integer, nullable=False, server_default="0")
    vt_flagged = Column(Boolean, nullable=False, server_default="0")
    dshield_flagged = Column(Boolean, nullable=False, server_default="0")
    risk_score = Column(Integer, nullable=True)
    matcher = Column(String(32), nullable=True)
    source_files = Column(JSON, nullable=True)
    enrichment = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_session_summaries_first_event", "first_event_at"),
        Index("ix_session_summaries_last_event", "last_event_at"),
        Index("ix_session_summaries_flags", "vt_flagged", "dshield_flagged"),
    )


class CommandStat(Base):
    """Per-session command aggregation used by reporting workflows."""

    __tablename__ = "command_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), nullable=False)
    command_normalized = Column(Text, nullable=False)
    occurrences = Column(Integer, nullable=False, server_default="0")
    first_seen = Column(DateTime(timezone=True))
    last_seen = Column(DateTime(timezone=True))
    high_risk = Column(Boolean, nullable=False, server_default="0")

    __table_args__ = (
        UniqueConstraint("session_id", "command_normalized", name="uq_command_stats_session_command"),
        Index("ix_command_stats_session", "session_id"),
        Index("ix_command_stats_command", "command_normalized"),
    )


class IngestCursor(Base):
    """Tracks the last processed offset for delta ingestion per source file."""

    __tablename__ = "ingest_cursors"

    source = Column(String(512), primary_key=True)
    inode = Column(String(128), nullable=True)
    last_offset = Column(Integer, nullable=False, server_default="-1")
    last_ingest_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    last_ingest_id = Column(String(64), nullable=True)
    metadata_json = Column(JSON, nullable=True)

    __table_args__ = (Index("ix_ingest_cursors_offset", "last_offset"),)


class DeadLetterEvent(Base):
    """Stores hostile or invalid events encountered during ingestion."""

    __tablename__ = "dead_letter_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ingest_id = Column(String(64), nullable=True)
    source = Column(String(512), nullable=True)
    source_offset = Column(Integer, nullable=True)
    reason = Column(String(128), nullable=False)
    payload = Column(JSON, nullable=False)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved = Column(Boolean, nullable=False, server_default="0")
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_dead_letter_events_created", "created_at"),
        Index("ix_dead_letter_events_source", "source"),
    )


class Files(Base):
    """Normalized files table with VirusTotal enrichment data."""

    __tablename__ = "files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), nullable=False)
    shasum = Column(String(64), nullable=False)  # SHA-256 hash
    filename = Column(String(512), nullable=True)
    file_size = Column(BigInteger, nullable=True)
    download_url = Column(String(1024), nullable=True)
    
    # VirusTotal enrichment fields
    vt_classification = Column(String(128), nullable=True)
    vt_description = Column(Text, nullable=True)
    vt_malicious = Column(Boolean, nullable=False, server_default="0")
    vt_first_seen = Column(DateTime(timezone=True), nullable=True)
    vt_last_analysis = Column(DateTime(timezone=True), nullable=True)
    vt_positives = Column(Integer, nullable=True)
    vt_total = Column(Integer, nullable=True)
    vt_scan_date = Column(DateTime(timezone=True), nullable=True)
    
    # Metadata
    first_seen = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_updated = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    enrichment_status = Column(String(32), nullable=False, server_default="pending")

    __table_args__ = (
        UniqueConstraint("session_id", "shasum", name="uq_files_session_hash"),
        Index("ix_files_shasum", "shasum"),
        Index("ix_files_vt_malicious", "vt_malicious"),
        Index("ix_files_enrichment_status", "enrichment_status"),
        Index("ix_files_first_seen", "first_seen"),
        Index("ix_files_session_id", "session_id"),
    )


__all__ = [
    "SchemaState",
    "RawEvent",
    "SessionSummary",
    "CommandStat",
    "IngestCursor",
    "DeadLetterEvent",
    "Files",
]
