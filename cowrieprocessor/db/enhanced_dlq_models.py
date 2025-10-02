"""Enhanced DLQ model with security and audit features.

This module extends the DeadLetterEvent model with security enhancements,
audit trails, and operational monitoring capabilities.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class EnhancedDeadLetterEvent(Base):
    """Enhanced Dead Letter Event with security and audit features."""

    __tablename__ = "dead_letter_events"

    # Primary identification
    id = Column(Integer, primary_key=True, autoincrement=True)
    ingest_id = Column(String(64), nullable=True, index=True)

    # Source tracking
    source = Column(String(512), nullable=True, index=True)
    source_offset = Column(Integer, nullable=True)
    source_inode = Column(String(128), nullable=True)

    # Failure information
    reason = Column(String(128), nullable=False, index=True)
    payload = Column(JSONB, nullable=False)
    metadata_json = Column(JSONB, nullable=True)

    # Security & Audit enhancements
    payload_checksum = Column(String(64), nullable=True, index=True)
    retry_count = Column(Integer, nullable=False, server_default="0")
    error_history = Column(JSONB, nullable=True)
    processing_attempts = Column(JSONB, nullable=True)

    # Resolution tracking
    resolved = Column(Boolean, nullable=False, server_default="false", index=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolution_method = Column(String(64), nullable=True)  # 'stored_proc', 'application', 'manual'

    # Idempotency and concurrency control
    idempotency_key = Column(String(128), nullable=True, unique=True, index=True)
    processing_lock = Column(UUID, nullable=True, index=True)
    lock_expires_at = Column(DateTime(timezone=True), nullable=True)

    # Priority and classification
    priority = Column(Integer, nullable=False, server_default="5")  # 1=highest, 10=lowest
    classification = Column(String(32), nullable=True)  # 'malicious', 'corrupted', 'format_error'

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    last_processed_at = Column(DateTime(timezone=True), nullable=True)

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

        self.processing_lock = lock_id
        self.lock_expires_at = datetime.now(timezone.utc) + datetime.timedelta(minutes=expires_in_minutes)
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

    id = Column(Integer, primary_key=True, autoincrement=True)
    processing_session_id = Column(String(64), nullable=False, index=True)
    processing_method = Column(String(32), nullable=False)  # 'stored_proc', 'application'

    # Batch metrics
    batch_size = Column(Integer, nullable=False)
    processed_count = Column(Integer, nullable=False)
    repaired_count = Column(Integer, nullable=False)
    failed_count = Column(Integer, nullable=False)
    skipped_count = Column(Integer, nullable=False)

    # Performance metrics
    processing_duration_ms = Column(Integer, nullable=False)
    avg_processing_time_ms = Column(Integer, nullable=True)
    peak_memory_mb = Column(Integer, nullable=True)

    # Error metrics
    circuit_breaker_triggered = Column(Boolean, nullable=False, server_default="false")
    rate_limit_hits = Column(Integer, nullable=False, server_default="0")
    lock_timeout_count = Column(Integer, nullable=False, server_default="0")

    # Timestamps
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index('ix_dlq_metrics_session', 'processing_session_id'),
        Index('ix_dlq_metrics_method', 'processing_method'),
        Index('ix_dlq_metrics_started', 'started_at'),
    )


class DLQCircuitBreakerState(Base):
    """Circuit breaker state for DLQ processing."""

    __tablename__ = "dlq_circuit_breaker_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    breaker_name = Column(String(64), nullable=False, unique=True)

    # Circuit breaker state
    state = Column(String(16), nullable=False)  # 'closed', 'open', 'half_open'
    failure_count = Column(Integer, nullable=False, server_default="0")
    last_failure_time = Column(DateTime(timezone=True), nullable=True)
    next_attempt_time = Column(DateTime(timezone=True), nullable=True)

    # Configuration
    failure_threshold = Column(Integer, nullable=False, server_default="5")
    timeout_seconds = Column(Integer, nullable=False, server_default="60")

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('ix_circuit_breaker_state', 'state'),
        Index('ix_circuit_breaker_next_attempt', 'next_attempt_time'),
    )
