"""ORM models for the refactored Cowrie processor database."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    case,
    false,
    func,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql.elements import Case

from .base import Base


class SchemaState(Base):
    """Key/value metadata used to track schema versions and flags."""

    __tablename__ = "schema_state"

    key = Column(String(128), primary_key=True)
    value = Column(String(256), nullable=False)


class RawEvent(Base):
    """Persistent copy of raw Cowrie events with JSON payloads and extracted columns."""

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
    quarantined = Column(Boolean, nullable=False, server_default=false())

    # Real columns for extracted JSON fields (replacing computed columns)
    session_id = Column(String(64), nullable=True, index=True)
    event_type = Column(String(128), nullable=True, index=True)
    event_timestamp = Column(String(64), nullable=True, index=True)

    @hybrid_property
    def session_id_computed(self) -> Any:
        """Backward compatibility for computed access to session_id.

        Returns:
            The session_id from the real column, or extracted from payload if null.
        """
        return self.session_id or (self.payload.get("session") if self.payload else None)

    @session_id_computed.expression
    def session_id_computed_expr(cls) -> Case:
        """SQL expression for backward compatibility with computed session_id.

        Returns:
            SQLAlchemy case expression that uses real column or extracts from JSON.
        """
        return case((cls.session_id.isnot(None), cls.session_id), else_=func.json_extract(cls.payload, "$.session"))

    @hybrid_property
    def event_type_computed(self) -> Any:
        """Backward compatibility for computed access to event_type.

        Returns:
            The event_type from the real column, or extracted from payload if null.
        """
        return self.event_type or (self.payload.get("eventid") if self.payload else None)

    @event_type_computed.expression
    def event_type_computed_expr(cls) -> Case:
        """SQL expression for backward compatibility with computed event_type.

        Returns:
            SQLAlchemy case expression that uses real column or extracts from JSON.
        """
        return case((cls.event_type.isnot(None), cls.event_type), else_=func.json_extract(cls.payload, "$.eventid"))

    @hybrid_property
    def event_timestamp_computed(self) -> Any:
        """Backward compatibility for computed access to event_timestamp.

        Returns:
            The event_timestamp from the real column, or extracted from payload if null.
        """
        return self.event_timestamp or (self.payload.get("timestamp") if self.payload else None)

    @event_timestamp_computed.expression
    def event_timestamp_computed_expr(cls) -> Case:
        """SQL expression for backward compatibility with computed event_timestamp.

        Returns:
            SQLAlchemy case expression that uses real column or extracts from JSON.
        """
        return case(
            (cls.event_timestamp.isnot(None), cls.event_timestamp), else_=func.json_extract(cls.payload, "$.timestamp")
        )

    __table_args__ = (
        UniqueConstraint(
            "source",
            "source_inode",
            "source_generation",
            "source_offset",
            name="uq_raw_events_source_offset",
        ),
        # Indexes are now defined inline with the columns above
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
    vt_flagged = Column(Boolean, nullable=False, server_default=false())
    dshield_flagged = Column(Boolean, nullable=False, server_default=false())
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
    high_risk = Column(Boolean, nullable=False, server_default=false())

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
    resolved = Column(Boolean, nullable=False, server_default=false())
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
    vt_malicious = Column(Boolean, nullable=False, server_default=false())
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


class SnowshoeDetection(Base):
    """Stores snowshoe attack detection results and analysis metadata."""

    __tablename__ = "snowshoe_detections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    detection_time = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    confidence_score = Column(String(10), nullable=False)  # Store as string to preserve precision
    unique_ips = Column(Integer, nullable=False)
    single_attempt_ips = Column(Integer, nullable=False)
    geographic_spread = Column(String(10), nullable=False)  # Store as string to preserve precision
    indicators = Column(JSON, nullable=False)
    is_likely_snowshoe = Column(Boolean, nullable=False, server_default=false())
    coordinated_timing = Column(Boolean, nullable=False, server_default=false())
    recommendation = Column(Text, nullable=True)
    analysis_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_snowshoe_detections_detection_time", "detection_time"),
        Index("ix_snowshoe_detections_window", "window_start", "window_end"),
        Index("ix_snowshoe_detections_confidence", "confidence_score"),
        Index("ix_snowshoe_detections_likely", "is_likely_snowshoe"),
        Index("ix_snowshoe_detections_created", "created_at"),
    )


__all__ = [
    "SchemaState",
    "RawEvent",
    "SessionSummary",
    "CommandStat",
    "IngestCursor",
    "DeadLetterEvent",
    "Files",
    "SnowshoeDetection",
]
