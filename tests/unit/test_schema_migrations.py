"""Tests for schema migrations and ORM metadata."""

from __future__ import annotations

from sqlalchemy import inspect, select

from cowrieprocessor.db import (
    CURRENT_SCHEMA_VERSION,
    apply_migrations,
    create_engine_from_settings,
)
from cowrieprocessor.db.models import RawEvent, SchemaState
from cowrieprocessor.settings import DatabaseSettings


def _engine_for_tmp(tmp_path):
    """Create a SQLite engine bound to a temporary file for testing."""
    db_path = tmp_path / "migrate.sqlite"
    settings = DatabaseSettings(url=f"sqlite:///{db_path}")
    return create_engine_from_settings(settings)


def test_apply_migrations_creates_tables(tmp_path) -> None:
    """Applying migrations should create all expected tables and set version."""
    engine = _engine_for_tmp(tmp_path)
    version = apply_migrations(engine)
    assert version == CURRENT_SCHEMA_VERSION

    inspector = inspect(engine)
    for table in (
        "schema_state",
        "raw_events",
        "session_summaries",
        "command_stats",
        "ingest_cursors",
        "dead_letter_events",
    ):
        assert inspector.has_table(table), f"Expected table {table} to be created"

    raw_event_columns = {col["name"] for col in inspector.get_columns("raw_events")}
    assert "source_generation" in raw_event_columns


def test_raw_event_computed_columns(tmp_path) -> None:
    """Computed columns expose session, event type, and timestamp from JSON payloads."""
    engine = _engine_for_tmp(tmp_path)
    apply_migrations(engine)

    payload = {
        "session": "abc123",
        "eventid": "cowrie.session.connect",
        "timestamp": "2024-01-01T00:00:00Z",
    }

    with engine.begin() as conn:
        conn.execute(
            RawEvent.__table__.insert().values(
                source="/tmp/log.json",
                payload=payload,
            )
        )
        row = conn.execute(select(RawEvent.session_id, RawEvent.event_type, RawEvent.event_timestamp)).one()

    assert row.session_id == "abc123"
    assert row.event_type == "cowrie.session.connect"
    assert row.event_timestamp == "2024-01-01T00:00:00Z"


def test_apply_migrations_idempotent(tmp_path) -> None:
    """Running migrations repeatedly keeps the schema version stable."""
    engine = _engine_for_tmp(tmp_path)
    first = apply_migrations(engine)
    second = apply_migrations(engine)
    assert first == second == CURRENT_SCHEMA_VERSION

    with engine.connect() as conn:
        stored = conn.execute(select(SchemaState.value).where(SchemaState.key == "schema_version")).scalar_one()
    assert stored == str(CURRENT_SCHEMA_VERSION)
