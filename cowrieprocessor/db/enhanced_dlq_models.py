"""Enhanced DLQ model with security and audit features.

This module extends the DeadLetterEvent model with security enhancements,
audit trails, and operational monitoring capabilities.

Migrated to SQLAlchemy 2.0 DeclarativeBase pattern with full type safety.
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import ColumnElement

from .base import Base


class EnhancedDeadLetterEvent(Base):
    """Enhanced Dead Letter Event with security and audit features."""

    __tablename__ = "enhanced_dead_letter_events"

    # Primary identification
    id: Mapped[int] = mapped_column(primary_key=True)
    ingest_id: Mapped[str | None] = mapped_column(String(64), index=True)

    # Source tracking
    source: Mapped[str | None] = mapped_column(String(512), index=True)
    source_offset: Mapped[int | None] = mapped_column(Integer)
    source_inode: Mapped[str | None] = mapped_column(String(128))

    # Failure information
    reason: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Security & Audit enhancements
    payload_checksum: Mapped[str | None] = mapped_column(String(64), index=True)
    retry_count: Mapped[int] = mapped_column(server_default="0")
    error_history: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    processing_attempts: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)

    # Resolution tracking
    resolved: Mapped[bool] = mapped_column(server_default="false", index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_method: Mapped[str | None] = mapped_column(String(64))  # 'stored_proc', 'application', 'manual'

    # Idempotency and concurrency control
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    processing_lock: Mapped[uuid.UUID | None] = mapped_column(UUID, index=True)
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Priority and classification
    priority: Mapped[int] = mapped_column(server_default="5")  # 1=highest, 10=lowest
    classification: Mapped[str | None] = mapped_column(String(32))  # 'malicious', 'corrupted', 'format_error'

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Constraints
    __table_args__ = (
        CheckConstraint('retry_count >= 0', name='ck_retry_count_positive'),
        CheckConstraint('priority BETWEEN 1 AND 10', name='ck_priority_range'),
        Index('ix_dead_letter_events_resolved_created', 'resolved', 'created_at'),
        Index('ix_dead_letter_events_priority_resolved', 'priority', 'resolved'),
        Index('ix_dead_letter_events_retry_count', 'retry_count'),
        Index('ix_dead_letter_events_lock_expires', 'lock_expires_at'),
        Index('ix_dead_letter_events_classification', 'classification'),
    )

    @hybrid_property
    def is_locked(self) -> bool:
        """Check if event is currently locked for processing."""
        if not self.processing_lock or not self.lock_expires_at:
            return False
        return datetime.now(timezone.utc) < self.lock_expires_at

    @is_locked.expression
    @classmethod
    def _is_locked_expression(cls) -> ColumnElement[bool]:
        """SQL expression for is_locked check."""
        return (cls.processing_lock.is_not(None)) & (func.now() < cls.lock_expires_at)

    @hybrid_property
    def checksum_valid(self) -> bool:
        """Verify payload checksum integrity."""
        if not self.payload_checksum:
            return True  # No checksum to verify

        calculated = self._calculate_payload_checksum()
        return calculated == self.payload_checksum

    def _calculate_payload_checksum(self) -> str:
        """Calculate SHA-256 checksum of payload."""
        payload_str = json.dumps(self.payload, sort_keys=True)
        return hashlib.sha256(payload_str.encode('utf-8')).hexdigest()

    def add_error_record(self, error_type: str, error_message: str, processing_method: str = 'unknown') -> None:
        """Add error record to error history."""
        if not self.error_history:
            self.error_history = []

        error_record = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'error_type': error_type,
            'error_message': error_message,
            'processing_method': processing_method,
            'retry_count': self.retry_count,
        }

        self.error_history.append(error_record)
        self.retry_count += 1
        self.last_processed_at = datetime.now(timezone.utc)

    def add_processing_attempt(self, method: str, success: bool, processing_time_ms: Optional[int] = None) -> None:
        """Record processing attempt for audit trail."""
        if not self.processing_attempts:
            self.processing_attempts = []

        attempt_record = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'method': method,
            'success': success,
            'processing_time_ms': processing_time_ms,
            'retry_count': self.retry_count,
        }

        self.processing_attempts.append(attempt_record)

    def acquire_processing_lock(self, lock_id: str, expires_in_minutes: int = 30) -> bool:
        """Acquire processing lock to prevent concurrent processing."""
        if self.is_locked:
            return False

        self.processing_lock = uuid.UUID(lock_id)
        self.lock_expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)
        return True

    def release_processing_lock(self) -> None:
        """Release processing lock."""
        self.processing_lock = None
        self.lock_expires_at = None

    def mark_resolved(self, method: str = 'unknown') -> None:
        """Mark event as resolved."""
        self.resolved = True
        self.resolved_at = datetime.now(timezone.utc)
        self.resolution_method = method
        self.release_processing_lock()

    def generate_idempotency_key(self) -> str:
        """Generate idempotency key for safe reprocessing."""
        if self.idempotency_key:
            return self.idempotency_key

        # Create deterministic key based on content and source
        key_data = f"{self.source}:{self.source_offset}:{self.payload_checksum}"
        self.idempotency_key = hashlib.sha256(key_data.encode('utf-8')).hexdigest()
        return self.idempotency_key


class DLQProcessingMetrics(Base):
    """Metrics table for DLQ processing performance tracking."""

    __tablename__ = "dlq_processing_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    processing_session_id: Mapped[str] = mapped_column(String(64), index=True)
    processing_method: Mapped[str] = mapped_column(String(32))  # 'stored_proc', 'application'

    # Batch metrics
    batch_size: Mapped[int] = mapped_column(Integer)
    processed_count: Mapped[int] = mapped_column(Integer)
    repaired_count: Mapped[int] = mapped_column(Integer)
    failed_count: Mapped[int] = mapped_column(Integer)
    skipped_count: Mapped[int] = mapped_column(Integer)

    # Performance metrics
    processing_duration_ms: Mapped[int] = mapped_column(Integer)
    avg_processing_time_ms: Mapped[int | None] = mapped_column(Integer)
    peak_memory_mb: Mapped[int | None] = mapped_column(Integer)

    # Error metrics
    circuit_breaker_triggered: Mapped[bool] = mapped_column(server_default="false")
    rate_limit_hits: Mapped[int] = mapped_column(server_default="0")
    lock_timeout_count: Mapped[int] = mapped_column(server_default="0")

    # Timestamps
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index('ix_dlq_metrics_session', 'processing_session_id'),
        Index('ix_dlq_metrics_method', 'processing_method'),
        Index('ix_dlq_metrics_started', 'started_at'),
    )


class DLQCircuitBreakerState(Base):
    """Circuit breaker state for DLQ processing."""

    __tablename__ = "dlq_circuit_breaker_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    breaker_name: Mapped[str] = mapped_column(String(64), unique=True)

    # Circuit breaker state
    state: Mapped[str] = mapped_column(String(16))  # 'closed', 'open', 'half_open'
    failure_count: Mapped[int] = mapped_column(server_default="0")
    last_failure_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Configuration
    failure_threshold: Mapped[int] = mapped_column(server_default="5")
    timeout_seconds: Mapped[int] = mapped_column(server_default="60")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index('ix_circuit_breaker_state', 'state'),
        Index('ix_circuit_breaker_next_attempt', 'next_attempt_time'),
    )
