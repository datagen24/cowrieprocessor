"""Database utilities for the refactored Cowrie processor."""

from .base import Base
from .engine import (
    create_engine_from_settings,
    create_session_maker,
    detect_database_features,
    has_pgvector,
    is_postgresql,
)
from .migrations import CURRENT_SCHEMA_VERSION, apply_migrations
from .models import (
    CommandStat,
    DeadLetterEvent,
    Files,
    IngestCursor,
    LongtailAnalysis,
    LongtailDetection,
    RawEvent,
    SchemaMetadata,
    SchemaState,
    SessionSummary,
)

__all__ = [
    "Base",
    "create_engine_from_settings",
    "create_session_maker",
    "detect_database_features",
    "has_pgvector",
    "is_postgresql",
    "apply_migrations",
    "CURRENT_SCHEMA_VERSION",
    "RawEvent",
    "SessionSummary",
    "CommandStat",
    "Files",
    "SchemaMetadata",
    "SchemaState",
    "IngestCursor",
    "DeadLetterEvent",
    "LongtailAnalysis",
    "LongtailDetection",
]
