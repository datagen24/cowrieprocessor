"""ORM models for the refactored Cowrie processor database."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
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
from sqlalchemy.sql.elements import Case, ColumnElement

from .base import Base
from .json_utils import get_dialect_name_from_engine


class SchemaState(Base):
    """Key/value metadata used to track schema versions and flags."""

    __tablename__ = "schema_state"

    key = Column(String(128), primary_key=True)
    value = Column(String(256), nullable=False)


class SchemaMetadata(Base):
    """Track schema version and available features."""

    __tablename__ = "schema_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(Integer, nullable=False)
    database_type = Column(String(16), nullable=False)  # 'postgresql' or 'sqlite'
    features = Column(JSON, nullable=False)
    upgraded_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_schema_metadata_version", "version"),
        Index("ix_schema_metadata_database_type", "database_type"),
    )


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
    event_timestamp = Column(DateTime(timezone=True), nullable=True, index=True)

    @hybrid_property
    def session_id_computed(self) -> Any:
        """Backward compatibility for computed access to session_id.

        Returns:
            The session_id from the real column, or extracted from payload if null.
        """
        return self.session_id or (self.payload.get("session") if self.payload else None)

    @session_id_computed.expression
    @classmethod
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
    @classmethod
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
    @classmethod
    def event_timestamp_computed_expr(cls) -> Case:
        """SQL expression for backward compatibility with computed event_timestamp.

        Returns:
            SQLAlchemy case expression that uses real column or extracts from JSON.
        """
        from sqlalchemy.dialects import postgresql

        # For PostgreSQL, we need to cast the JSON string to timestamp
        # For SQLite, we'll use the string as-is for backward compatibility
        dialect_name = get_dialect_name_from_engine(cls.__table__.bind) if hasattr(cls.__table__, 'bind') else None

        if dialect_name == "postgresql":
            # PostgreSQL: cast JSON string to TIMESTAMP WITH TIME ZONE
            json_timestamp: ColumnElement[Any] = func.cast(
                func.json_extract(cls.payload, "$.timestamp"), postgresql.TIMESTAMP(timezone=True)
            )
        else:
            # SQLite: keep as string for backward compatibility
            json_timestamp = func.json_extract(cls.payload, "$.timestamp")

        return case((cls.event_timestamp.isnot(None), cls.event_timestamp), else_=json_timestamp)

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
    ssh_key_injections = Column(Integer, nullable=False, server_default="0")
    unique_ssh_keys = Column(Integer, nullable=False, server_default="0")
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
        Index("ix_session_summaries_ssh_keys", "ssh_key_injections"),
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


class LongtailAnalysis(Base):
    """Store longtail analysis results and metadata - following SnowshoeDetection pattern."""

    __tablename__ = "longtail_analysis"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_time = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    window_start = Column(DateTime(timezone=True), nullable=False)  # Follow snowshoe pattern
    window_end = Column(DateTime(timezone=True), nullable=False)
    lookback_days = Column(Integer, nullable=False)

    # Analysis results (corrected data types - NOT following snowshoe mistake)
    confidence_score = Column(Float, nullable=False)  # Proper Float type for numeric data
    total_events_analyzed = Column(Integer, nullable=False)
    rare_command_count = Column(Integer, nullable=False, server_default="0")
    anomalous_sequence_count = Column(Integer, nullable=False, server_default="0")
    outlier_session_count = Column(Integer, nullable=False, server_default="0")
    emerging_pattern_count = Column(Integer, nullable=False, server_default="0")
    high_entropy_payload_count = Column(Integer, nullable=False, server_default="0")

    # Results storage
    analysis_results = Column(JSON, nullable=False)
    statistical_summary = Column(JSON, nullable=True)
    recommendation = Column(Text, nullable=True)

    # Performance metrics (proper numeric types)
    analysis_duration_seconds = Column(Float, nullable=True)  # Float for seconds
    memory_usage_mb = Column(Float, nullable=True)  # Float for MB

    # Quality metrics (proper numeric types)
    data_quality_score = Column(Float, nullable=True)  # Float 0.0-1.0
    enrichment_coverage = Column(Float, nullable=True)  # Float 0.0-1.0

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_longtail_analysis_time", "analysis_time"),
        Index("ix_longtail_analysis_window", "window_start", "window_end"),  # Follow snowshoe
        Index("ix_longtail_analysis_confidence", "confidence_score"),
        Index("ix_longtail_analysis_created", "created_at"),
    )


class LongtailDetection(Base):
    """Store individual longtail detections - simplified version."""

    __tablename__ = "longtail_detections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_id = Column(Integer, ForeignKey("longtail_analysis.id"), nullable=False)
    detection_type = Column(String(32), nullable=False)  # rare_command, anomalous_sequence, etc.
    session_id = Column(String(64), nullable=True, index=True)
    event_id = Column(Integer, ForeignKey("raw_events.id"), nullable=True)

    # Detection details
    detection_data = Column(JSON, nullable=False)
    confidence_score = Column(Float, nullable=False)  # Proper Float type
    severity_score = Column(Float, nullable=False)  # Proper Float type

    # Context
    timestamp = Column(DateTime(timezone=True), nullable=False)
    source_ip = Column(String(45), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_longtail_detections_analysis", "analysis_id"),
        Index("ix_longtail_detections_type", "detection_type"),
        Index("ix_longtail_detections_session", "session_id"),
        Index("ix_longtail_detections_timestamp", "timestamp"),
        Index("ix_longtail_detections_created", "created_at"),  # Follow snowshoe pattern
    )


class LongtailDetectionSession(Base):
    """Junction table linking longtail detections to sessions for Many-to-Many relationships."""

    __tablename__ = "longtail_detection_sessions"

    detection_id = Column(Integer, ForeignKey("longtail_detections.id", ondelete="CASCADE"), primary_key=True)
    session_id = Column(String(64), ForeignKey("session_summaries.session_id", ondelete="CASCADE"), primary_key=True)

    __table_args__ = (
        Index("ix_longtail_detection_sessions_detection", "detection_id"),
        Index("ix_longtail_detection_sessions_session", "session_id"),
    )


class LongtailAnalysisCheckpoint(Base):
    """Track analysis checkpoints for incremental processing and performance optimization."""

    __tablename__ = "longtail_analysis_checkpoints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    checkpoint_date = Column(Date, nullable=False, unique=True)
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    sessions_analyzed = Column(Integer, nullable=False)
    vocabulary_hash = Column(String(64), nullable=False)
    last_analysis_id = Column(Integer, ForeignKey("longtail_analysis.id"), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_longtail_checkpoints_date", "checkpoint_date"),
        Index("ix_longtail_checkpoints_window", "window_start", "window_end"),
        Index("ix_longtail_checkpoints_analysis", "last_analysis_id"),
    )


class PasswordStatistics(Base):
    """Aggregated password breach statistics by date."""

    __tablename__ = "password_statistics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, unique=True)
    total_attempts = Column(Integer, nullable=False, server_default="0")
    unique_passwords = Column(Integer, nullable=False, server_default="0")
    breached_count = Column(Integer, nullable=False, server_default="0")
    novel_count = Column(Integer, nullable=False, server_default="0")
    max_prevalence = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("ix_password_statistics_created", "created_at"),)


class PasswordTracking(Base):
    """Track individual passwords with HIBP results and temporal usage patterns."""

    __tablename__ = "password_tracking"

    id = Column(Integer, primary_key=True, autoincrement=True)
    password_hash = Column(String(64), nullable=False, unique=True, index=True)
    password_text = Column(Text, nullable=False)

    # HIBP enrichment
    breached = Column(Boolean, nullable=False, server_default=false())
    breach_prevalence = Column(Integer, nullable=True)
    last_hibp_check = Column(DateTime(timezone=True), nullable=True)

    # Temporal tracking
    first_seen = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    times_seen = Column(Integer, nullable=False, server_default="1")
    unique_sessions = Column(Integer, nullable=False, server_default="1")

    # Metadata
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_password_tracking_hash", "password_hash", unique=True),
        Index("ix_password_tracking_last_seen", "last_seen"),
        Index("ix_password_tracking_breached", "breached"),
        Index("ix_password_tracking_times_seen", "times_seen"),
    )


class PasswordSessionUsage(Base):
    """Junction table linking passwords to sessions for detailed tracking."""

    __tablename__ = "password_session_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    password_id = Column(Integer, ForeignKey("password_tracking.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(String(64), ForeignKey("session_summaries.session_id"), nullable=False)
    username = Column(String(256), nullable=True)
    success = Column(Boolean, nullable=False, server_default=false())
    timestamp = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("password_id", "session_id", name="uq_password_session"),
        Index("ix_password_session_password", "password_id"),
        Index("ix_password_session_session", "session_id"),
        Index("ix_password_session_timestamp", "timestamp"),
    )


class SSHKeyIntelligence(Base):
    """Track SSH public keys with intelligence metadata and temporal patterns."""

    __tablename__ = "ssh_key_intelligence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_type = Column(String(32), nullable=False)  # 'ssh-rsa', 'ssh-ed25519', 'ecdsa-sha2-nistp256', etc.
    key_data = Column(Text, nullable=False)  # Full public key (base64 portion)
    key_fingerprint = Column(String(64), nullable=False)  # SSH key fingerprint (SHA256)
    key_hash = Column(String(64), nullable=False, unique=True)  # SHA-256 hash for deduplication
    key_comment = Column(Text, nullable=True)  # Optional comment from key (often username@host)

    # Temporal tracking
    first_seen = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    total_attempts = Column(Integer, nullable=False, server_default="1")

    # Aggregated metrics
    unique_sources = Column(Integer, nullable=False, server_default="1")  # Unique IPs injecting this key
    unique_sessions = Column(Integer, nullable=False, server_default="1")  # Unique sessions using this key

    # Key metadata
    key_bits = Column(Integer, nullable=True)  # Key size (2048, 4096, etc.)
    key_full = Column(Text, nullable=False)  # Complete key line as extracted
    pattern_type = Column(String(32), nullable=False)  # 'direct_echo', 'heredoc', 'base64_encoded', 'script'
    target_path = Column(Text, nullable=True)  # Target file path (usually ~/.ssh/authorized_keys)

    # Metadata
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_ssh_key_fingerprint", "key_fingerprint"),
        Index("ix_ssh_key_type", "key_type"),
        Index("ix_ssh_key_timeline", "first_seen", "last_seen"),
        Index("ix_ssh_key_attempts", "total_attempts"),
        Index("ix_ssh_key_sources", "unique_sources"),
        Index("ix_ssh_key_sessions", "unique_sessions"),
    )


class SessionSSHKeys(Base):
    """Link SSH keys to sessions with injection context and details."""

    __tablename__ = "session_ssh_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), nullable=False)
    ssh_key_id = Column(Integer, ForeignKey("ssh_key_intelligence.id"), nullable=False)

    # Command context
    command_text = Column(Text, nullable=True)  # Original command that injected the key
    command_hash = Column(String(64), nullable=True)  # Hash of neutralized command
    injection_method = Column(String(32), nullable=False)  # 'echo_append', 'echo_overwrite', 'heredoc', 'script'

    # Temporal and source info
    timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    source_ip = Column(String(45), nullable=True)
    successful_injection = Column(Boolean, nullable=False, server_default=false())  # Did the injection succeed?

    __table_args__ = (
        Index("ix_session_ssh_keys_session", "session_id"),
        Index("ix_session_ssh_keys_timestamp", "timestamp"),
        Index("ix_session_ssh_keys_ssh_key", "ssh_key_id"),
        Index("ix_session_ssh_keys_source_ip", "source_ip"),
    )


class SSHKeyAssociations(Base):
    """Track keys used together (campaign correlation and co-occurrence patterns)."""

    __tablename__ = "ssh_key_associations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_id_1 = Column(Integer, ForeignKey("ssh_key_intelligence.id"), nullable=False)
    key_id_2 = Column(Integer, ForeignKey("ssh_key_intelligence.id"), nullable=False)

    # Co-occurrence metrics
    co_occurrence_count = Column(Integer, nullable=False, server_default="1")
    first_seen = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    same_session_count = Column(Integer, nullable=False, server_default="0")  # Times seen in same session
    same_ip_count = Column(Integer, nullable=False, server_default="0")  # Times seen from same IP

    __table_args__ = (
        UniqueConstraint("key_id_1", "key_id_2", name="uq_ssh_key_associations_keys"),
        Index("ix_ssh_key_associations_keys", "key_id_1", "key_id_2"),
        Index("ix_ssh_key_associations_co_occurrence", "co_occurrence_count"),
        Index("ix_ssh_key_associations_timeline", "first_seen", "last_seen"),
    )


__all__ = [
    "SchemaState",
    "SchemaMetadata",
    "RawEvent",
    "SessionSummary",
    "CommandStat",
    "IngestCursor",
    "DeadLetterEvent",
    "Files",
    "SnowshoeDetection",
    "LongtailAnalysis",
    "LongtailDetection",
    "PasswordStatistics",
    "PasswordTracking",
    "PasswordSessionUsage",
    "SSHKeyIntelligence",
    "SessionSSHKeys",
    "SSHKeyAssociations",
]
