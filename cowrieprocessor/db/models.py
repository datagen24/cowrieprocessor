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
    """Tier 3: Aggregated per-session metrics with point-in-time enrichment snapshots.

    This table stores session-level attack data with lightweight snapshot columns for fast
    filtering WITHOUT JOINs. The snapshot columns capture "what was it at time of attack"
    for temporal accuracy in botnet clustering.

    Two enrichment patterns:
    1. **Snapshot columns** (fast filtering): `snapshot_asn`, `snapshot_country`, `snapshot_ip_type`
    2. **Full enrichment JSONB** (deep analysis): `enrichment` column with complete data

    Example use cases:
    - "Find sessions with SSH key abc123 from China" (NO JOIN - use snapshot_country)
    - "Group sessions by ASN at time of attack" (NO JOIN - use snapshot_asn)
    - "Compare snapshot vs current IP state" (JOIN with ip_inventory for delta analysis)
    """

    __tablename__ = "session_summaries"

    session_id = Column(String(64), primary_key=True)

    # Foreign key to IP inventory (for JOIN when current state needed)
    source_ip = Column(
        String(45),
        ForeignKey("ip_inventory.ip_address"),
        nullable=True,
        doc="Source IP address (links to ip_inventory)",
    )

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

    # Behavioral clustering keys (for campaign correlation)
    ssh_key_fingerprint = Column(String(128), nullable=True, doc="SSH key fingerprint for campaign clustering")
    password_hash = Column(String(64), nullable=True, doc="Password hash for credential tracking")
    command_signature = Column(Text, nullable=True, doc="Command pattern signature for behavioral clustering")

    # LIGHTWEIGHT SNAPSHOT COLUMNS (for fast filtering WITHOUT JOIN)
    snapshot_asn = Column(Integer, nullable=True, doc="ASN at time of attack (immutable snapshot)")
    snapshot_country = Column(String(2), nullable=True, doc="Country code at time of attack (immutable snapshot)")
    snapshot_ip_type = Column(
        Text, nullable=True, doc="IP type at time of attack (e.g., 'RESIDENTIAL', 'DATACENTER', 'VPN')"
    )

    # FULL ENRICHMENT SNAPSHOT (for deep analysis - IMMUTABLE)
    enrichment = Column(JSON, nullable=True, doc="Complete enrichment data snapshot at time of attack")
    enrichment_at = Column(
        DateTime(timezone=True), nullable=True, doc="Timestamp when enrichment snapshot was captured"
    )

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_session_summaries_source_ip", "source_ip"),
        Index("ix_session_summaries_first_event", "first_event_at"),
        Index("ix_session_summaries_last_event", "last_event_at"),
        Index("ix_session_summaries_flags", "vt_flagged", "dshield_flagged"),
        Index("ix_session_summaries_ssh_keys", "ssh_key_injections"),
        # Snapshot indexes for fast filtering (NO JOIN required)
        Index("ix_session_summaries_snapshot_asn", "snapshot_asn"),
        Index("ix_session_summaries_snapshot_country", "snapshot_country"),
        Index("ix_session_summaries_snapshot_ip_type", "snapshot_ip_type"),
        # Behavioral clustering indexes
        Index("ix_session_summaries_ssh_key_fp", "ssh_key_fingerprint"),
        Index("ix_session_summaries_password_hash", "password_hash"),
        Index("ix_session_summaries_command_sig", "command_signature"),
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


class EnrichmentCache(Base):
    """Database-backed enrichment cache for API responses.

    This table serves as the L2 cache tier in the hybrid caching architecture:
    Redis L1 → Database L2 → Filesystem L3 fallback

    Stores enrichment data from various security services (VirusTotal, DShield,
    URLHaus, SPUR, etc.) with configurable TTLs and automatic expiration.
    """

    __tablename__ = "enrichment_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    service = Column(String(64), nullable=False)  # virustotal, dshield, urlhaus, spur, hibp
    cache_key = Column(String(256), nullable=False)  # hash, IP address, or other identifier
    cache_value = Column(JSON, nullable=False)  # enrichment data as JSON
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)  # 30-day TTL by default

    __table_args__ = (
        # Composite unique index for fast lookups
        UniqueConstraint("service", "cache_key", name="uq_enrichment_cache_service_key"),
        Index("ix_enrichment_cache_service_key", "service", "cache_key"),
        Index("ix_enrichment_cache_expires_at", "expires_at"),
        Index("ix_enrichment_cache_created_at", "created_at"),
    )


class ASNInventory(Base):
    """Tier 1: ASN-level tracking for organizational attribution.

    ASNs (Autonomous System Numbers) represent organizations that own IP blocks.
    This table tracks ASN metadata and aggregate statistics for infrastructure analysis.
    ASNs are highly stable entities (e.g., China Telecom AS4134 remains consistent over years).

    Example use cases:
    - "What hosting providers are used by this botnet?"
    - "Find other campaigns using the same ASN infrastructure"
    - "Track persistent threat actors by ASN preference"
    """

    __tablename__ = "asn_inventory"

    # Primary key
    asn_number = Column(Integer, primary_key=True, doc="Autonomous System Number (e.g., 4134 for China Telecom)")

    # Organization metadata
    organization_name = Column(Text, nullable=True, doc="ASN owner organization name")
    organization_country = Column(String(2), nullable=True, doc="ISO 3166-1 alpha-2 country code")
    rir_registry = Column(
        String(10), nullable=True, doc="Regional Internet Registry (ARIN, RIPE, APNIC, LACNIC, AFRINIC)"
    )
    asn_type = Column(Text, nullable=True, doc="Classification: HOSTING, ISP, CLOUD, EDUCATION, GOVERNMENT")
    is_known_hosting = Column(
        Boolean, nullable=False, server_default=false(), doc="True if known datacenter/hosting provider"
    )
    is_known_vpn = Column(Boolean, nullable=False, server_default=false(), doc="True if known VPN provider")

    # Aggregate statistics
    first_seen = Column(DateTime(timezone=True), nullable=False, doc="First time any IP from this ASN was observed")
    last_seen = Column(
        DateTime(timezone=True), nullable=False, doc="Most recent time any IP from this ASN was observed"
    )
    unique_ip_count = Column(
        Integer, nullable=False, server_default="0", doc="Count of unique IPs observed in this ASN"
    )
    total_session_count = Column(Integer, nullable=False, server_default="0", doc="Total attack sessions from this ASN")

    # Full enrichment data from multiple sources
    enrichment = Column(
        JSON, nullable=False, server_default='{}', doc="Combined enrichment from DShield, SPUR, MaxMind, etc."
    )
    enrichment_updated_at = Column(DateTime(timezone=True), nullable=True, doc="Last time enrichment data was updated")

    # Metadata
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_asn_inventory_org_name", "organization_name"),
        Index("ix_asn_inventory_asn_type", "asn_type"),
        Index("ix_asn_inventory_session_count", "total_session_count"),
        Index("ix_asn_inventory_first_seen", "first_seen"),
        Index("ix_asn_inventory_last_seen", "last_seen"),
    )


class IPInventory(Base):
    """Tier 2: IP-level tracking with current enrichment state.

    Tracks individual source IPs with their current enrichment data and temporal patterns.
    IPs can move between ASNs (cloud reassignments, residential DHCP), so we track
    the current ASN relationship with last verification timestamp.

    This table serves as the L2 cache for IP enrichment data, reducing redundant API calls
    by 80%+ (300K unique IPs vs 1.68M sessions).

    Example use cases:
    - "What is the current state of this IP?"
    - "Has this IP changed ASN ownership?"
    - "Find IPs active for >30 days"
    - "What IPs are VPN/proxy vs residential?"
    """

    __tablename__ = "ip_inventory"

    # Primary key
    ip_address = Column(String(45), primary_key=True, doc="IPv4 or IPv6 address in string format")

    # Current ASN relationship (mutable - IPs can move between ASNs)
    current_asn = Column(
        Integer, ForeignKey("asn_inventory.asn_number"), nullable=True, doc="Current ASN owning this IP"
    )
    asn_last_verified = Column(DateTime(timezone=True), nullable=True, doc="Last time ASN ownership was verified")

    # Temporal tracking
    first_seen = Column(DateTime(timezone=True), nullable=False, doc="First time this IP was observed attacking")
    last_seen = Column(DateTime(timezone=True), nullable=False, doc="Most recent attack from this IP")
    session_count = Column(
        Integer, nullable=False, server_default="1", doc="Total number of attack sessions from this IP"
    )

    # Current enrichment data (MUTABLE - can be refreshed)
    enrichment = Column(
        JSON, nullable=False, server_default='{}', doc="Full enrichment from DShield, SPUR, MaxMind, URLHaus, etc."
    )
    enrichment_updated_at = Column(
        DateTime(timezone=True), nullable=True, doc="Last time enrichment was updated/refreshed"
    )
    enrichment_version = Column(String(10), nullable=False, server_default="2.2", doc="Enrichment schema version")

    # Metadata
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    @hybrid_property
    def geo_country(self) -> str:
        """Computed country code from enrichment sources (priority: MaxMind > Cymru > DShield).

        Returns:
            ISO 3166-1 alpha-2 country code, or 'XX' if unknown.
        """
        if not self.enrichment:
            return 'XX'
        return (
            (self.enrichment.get('maxmind', {}) or {}).get('country')
            or (self.enrichment.get('cymru', {}) or {}).get('country')
            or (self.enrichment.get('dshield', {}) or {}).get('ip', {}).get('ascountry')
            or 'XX'
        )

    @geo_country.expression
    @classmethod
    def geo_country_expr(cls) -> ColumnElement[str]:
        """SQL expression for extracting country code from enrichment JSONB.

        Returns:
            SQLAlchemy case expression with COALESCE fallback logic.
        """
        dialect_name = get_dialect_name_from_engine(cls.__table__.bind) if hasattr(cls.__table__, 'bind') else None

        if dialect_name == "postgresql":
            # PostgreSQL: Use -> and ->> operators for JSONB access
            return func.coalesce(
                cls.enrichment.op('->')('maxmind').op('->>')('country'),
                cls.enrichment.op('->')('cymru').op('->>')('country'),
                cls.enrichment.op('->')('dshield').op('->')('ip').op('->>')('ascountry'),
                'XX',
            )
        else:
            # SQLite: Use json_extract function
            return func.coalesce(
                func.json_extract(cls.enrichment, '$.maxmind.country'),
                func.json_extract(cls.enrichment, '$.cymru.country'),
                func.json_extract(cls.enrichment, '$.dshield.ip.ascountry'),
                'XX',
            )

    @hybrid_property
    def ip_type(self) -> Any:
        """IP type classification from SPUR (e.g., 'RESIDENTIAL', 'DATACENTER', 'VPN').

        Returns:
            IP type string or None if not enriched.
        """
        if not self.enrichment:
            return None
        return (self.enrichment.get('spur', {}) or {}).get('client', {}).get('types')

    @ip_type.expression
    @classmethod
    def ip_type_expr(cls) -> ColumnElement[Any]:
        """SQL expression for extracting IP type from enrichment JSONB.

        Returns:
            SQLAlchemy expression for IP type extraction.
        """
        dialect_name = get_dialect_name_from_engine(cls.__table__.bind) if hasattr(cls.__table__, 'bind') else None

        if dialect_name == "postgresql":
            return cls.enrichment.op('->')('spur').op('->')('client').op('->>')('types')
        else:
            return func.json_extract(cls.enrichment, '$.spur.client.types')

    @hybrid_property
    def is_scanner(self) -> bool:
        """Whether this IP is flagged as a known scanner by GreyNoise.

        Returns:
            True if flagged as scanner noise, False otherwise.
        """
        if not self.enrichment:
            return False
        return bool((self.enrichment.get('greynoise', {}) or {}).get('noise', False))

    @is_scanner.expression
    @classmethod
    def is_scanner_expr(cls) -> ColumnElement[bool]:
        """SQL expression for scanner detection from enrichment JSONB.

        Returns:
            SQLAlchemy expression returning boolean.
        """
        dialect_name = get_dialect_name_from_engine(cls.__table__.bind) if hasattr(cls.__table__, 'bind') else None

        if dialect_name == "postgresql":
            return func.coalesce(func.cast(cls.enrichment.op('->')('greynoise').op('->>')('noise'), Boolean), False)
        else:
            return func.coalesce(func.cast(func.json_extract(cls.enrichment, '$.greynoise.noise'), Boolean), False)

    @hybrid_property
    def is_bogon(self) -> bool:
        """Whether this IP is a bogon (invalid/reserved IP address).

        Returns:
            True if bogon, False otherwise.
        """
        if not self.enrichment:
            return False
        return bool((self.enrichment.get('validation', {}) or {}).get('is_bogon', False))

    @is_bogon.expression
    @classmethod
    def is_bogon_expr(cls) -> ColumnElement[bool]:
        """SQL expression for bogon detection from enrichment JSONB.

        Returns:
            SQLAlchemy expression returning boolean.
        """
        dialect_name = get_dialect_name_from_engine(cls.__table__.bind) if hasattr(cls.__table__, 'bind') else None

        if dialect_name == "postgresql":
            return func.coalesce(func.cast(cls.enrichment.op('->')('validation').op('->>')('is_bogon'), Boolean), False)
        else:
            return func.coalesce(func.cast(func.json_extract(cls.enrichment, '$.validation.is_bogon'), Boolean), False)

    __table_args__ = (
        Index("ix_ip_inventory_current_asn", "current_asn"),
        Index("ix_ip_inventory_first_seen", "first_seen"),
        Index("ix_ip_inventory_last_seen", "last_seen"),
        Index("ix_ip_inventory_session_count", "session_count"),
        Index("ix_ip_inventory_enrichment_updated", "enrichment_updated_at"),
    )


class IPASNHistory(Base):
    """Optional: Track IP→ASN movement over time for infrastructure analysis.

    Records historical ASN ownership changes for IPs, useful for detecting:
    - Cloud IP reassignments
    - ISP IP block transfers
    - IP hijacking attempts
    - Infrastructure migration patterns
    """

    __tablename__ = "ip_asn_history"

    ip_address = Column(String(45), primary_key=True, doc="IPv4 or IPv6 address")
    asn_number = Column(Integer, primary_key=True, doc="ASN number at this observation")
    observed_at = Column(
        DateTime(timezone=True),
        primary_key=True,
        server_default=func.now(),
        doc="When this ASN assignment was observed",
    )
    verification_source = Column(
        String(50), nullable=True, doc="Source of verification (e.g., 'dshield', 'maxmind', 'cymru')"
    )

    __table_args__ = (
        Index("ix_ip_asn_history_ip", "ip_address"),
        Index("ix_ip_asn_history_asn", "asn_number"),
        Index("ix_ip_asn_history_observed", "observed_at"),
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
    "EnrichmentCache",
    "ASNInventory",
    "IPInventory",
    "IPASNHistory",
]
