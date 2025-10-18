"""Integration tests for migration system across both SQLite and PostgreSQL backends."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.db.migrations import CURRENT_SCHEMA_VERSION, apply_migrations
from cowrieprocessor.db.models import RawEvent, SchemaState
from cowrieprocessor.settings import DatabaseSettings


class TestMigrationSystem:
    """Test migration system functionality."""

    def test_migration_application_sqlite(self) -> None:
        """Test migration application on SQLite database."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            # Create engine and apply migrations
            settings = DatabaseSettings(url=f"sqlite:///{db_path}")
            engine = create_engine_from_settings(settings)

            # Apply migrations
            final_version = apply_migrations(engine)
            assert final_version == CURRENT_SCHEMA_VERSION

            # Verify schema state
            Session = sessionmaker(bind=engine)
            session = Session()

            schema_state = session.query(SchemaState).filter(SchemaState.key == "schema_version").first()
            assert schema_state is not None
            assert int(schema_state.value) == CURRENT_SCHEMA_VERSION

            # Verify tables exist
            from sqlalchemy import inspect

            inspector = inspect(engine)
            table_names = inspector.get_table_names()

            expected_tables = [
                "raw_events",
                "session_summaries",
                "command_stats",
                "dead_letter_events",
                "files",
                "schema_state",
            ]
            for table_name in expected_tables:
                assert table_name in table_names, f"Table {table_name} not found"

            # Verify columns exist in raw_events
            columns = {col["name"] for col in inspector.get_columns("raw_events")}
            expected_columns = [
                "id",
                "source",
                "source_offset",
                "source_inode",
                "source_generation",
                "payload",
                "payload_hash",
                "risk_score",
                "quarantined",
                "session_id",
                "event_type",
                "event_timestamp",
            ]
            for column_name in expected_columns:
                assert column_name in columns, f"Column {column_name} not found in raw_events"

            session.close()

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_migration_idempotency_sqlite(self) -> None:
        """Test that migrations are idempotent on SQLite."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            settings = DatabaseSettings(url=f"sqlite:///{db_path}")
            engine = create_engine_from_settings(settings)

            # Apply migrations twice
            version1 = apply_migrations(engine)
            version2 = apply_migrations(engine)

            assert version1 == CURRENT_SCHEMA_VERSION
            assert version2 == CURRENT_SCHEMA_VERSION

            # Verify schema state is consistent
            Session = sessionmaker(bind=engine)
            session = Session()

            schema_states = session.query(SchemaState).filter(SchemaState.key == "schema_version").all()
            assert len(schema_states) == 1
            assert int(schema_states[0].value) == CURRENT_SCHEMA_VERSION

            session.close()

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_migration_with_data_sqlite(self) -> None:
        """Test migration with existing data in SQLite."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            settings = DatabaseSettings(url=f"sqlite:///{db_path}")
            engine = create_engine_from_settings(settings)

            # Create initial schema (version 1)
            from cowrieprocessor.db.base import Base

            Base.metadata.create_all(engine)

            # Insert some test data
            Session = sessionmaker(bind=engine)
            session = Session()

            # Create schema state for version 1
            schema_state = SchemaState(key="schema_version", value="1")
            session.add(schema_state)

            # Insert test raw event
            raw_event = RawEvent(
                source="test",
                source_offset=1,
                payload={
                    "session": "test-session-123",
                    "eventid": "cowrie.session.connect",
                    "timestamp": "2025-01-27T10:00:00Z",
                },
            )
            session.add(raw_event)
            session.commit()

            # Apply migrations
            final_version = apply_migrations(engine)
            assert final_version == CURRENT_SCHEMA_VERSION

            # Verify data was preserved and new columns populated
            updated_event = session.query(RawEvent).first()
            assert updated_event.session_id == "test-session-123"
            assert updated_event.event_type == "cowrie.session.connect"
            assert updated_event.event_timestamp == "2025-01-27T10:00:00Z"

            session.close()

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_migration_error_handling(self) -> None:
        """Test migration error handling."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            settings = DatabaseSettings(url=f"sqlite:///{db_path}")
            engine = create_engine_from_settings(settings)

            # Create tables first
            from cowrieprocessor.db.base import Base

            Base.metadata.create_all(engine)

            # Create a corrupted schema state
            Session = sessionmaker(bind=engine)
            session = Session()

            # Create schema state with invalid version
            schema_state = SchemaState(key="schema_version", value="invalid")
            session.add(schema_state)
            session.commit()

            # Apply migrations - should handle invalid version gracefully
            final_version = apply_migrations(engine)
            assert final_version == CURRENT_SCHEMA_VERSION

            session.close()

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_migration_from_scratch(self) -> None:
        """Test migration from completely empty database."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            settings = DatabaseSettings(url=f"sqlite:///{db_path}")
            engine = create_engine_from_settings(settings)

            # Apply migrations to empty database
            final_version = apply_migrations(engine)
            assert final_version == CURRENT_SCHEMA_VERSION

            # Verify all tables and columns were created
            from sqlalchemy import inspect

            inspector = inspect(engine)
            table_names = inspector.get_table_names()

            expected_tables = [
                "raw_events",
                "session_summaries",
                "command_stats",
                "dead_letter_events",
                "files",
                "schema_state",
            ]
            for table_name in expected_tables:
                assert table_name in table_names, f"Table {table_name} not found"

        finally:
            Path(db_path).unlink(missing_ok=True)


class TestMigrationCompatibility:
    """Test migration compatibility across different scenarios."""

    def test_boolean_defaults_migration(self) -> None:
        """Test boolean defaults migration specifically."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            settings = DatabaseSettings(url=f"sqlite:///{db_path}")
            engine = create_engine_from_settings(settings)

            # Create schema up to version 5 (before boolean fixes)
            from cowrieprocessor.db.base import Base

            Base.metadata.create_all(engine)

            # Set schema version to 5
            Session = sessionmaker(bind=engine)
            session = Session()

            schema_state = SchemaState(key="schema_version", value="5")
            session.add(schema_state)
            session.commit()

            # Apply migration to version 6
            final_version = apply_migrations(engine)
            assert final_version == CURRENT_SCHEMA_VERSION

            # Verify boolean columns exist
            from sqlalchemy import inspect

            inspector = inspect(engine)
            columns = {col["name"] for col in inspector.get_columns("raw_events")}
            assert "quarantined" in columns

            session.close()

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_json_extraction_migration(self) -> None:
        """Test JSON extraction migration specifically."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            settings = DatabaseSettings(url=f"sqlite:///{db_path}")
            engine = create_engine_from_settings(settings)

            # Create schema up to version 4 (before computed columns)
            from cowrieprocessor.db.base import Base

            Base.metadata.create_all(engine)

            # Set schema version to 4
            Session = sessionmaker(bind=engine)
            session = Session()

            schema_state = SchemaState(key="schema_version", value="4")
            session.add(schema_state)
            session.commit()

            # Insert test data with JSON payload
            raw_event = RawEvent(
                source="test",
                source_offset=1,
                payload={
                    "session": "test-session-456",
                    "eventid": "cowrie.session.file_download",
                    "timestamp": "2025-01-27T11:00:00Z",
                },
            )
            session.add(raw_event)
            session.commit()

            # Apply migration to version 5 (computed columns)
            final_version = apply_migrations(engine)
            assert final_version >= 5

            # Verify JSON extraction worked
            updated_event = session.query(RawEvent).first()
            assert updated_event.session_id == "test-session-456"
            assert updated_event.event_type == "cowrie.session.file_download"
            assert updated_event.event_timestamp == "2025-01-27T11:00:00Z"

            session.close()

        finally:
            Path(db_path).unlink(missing_ok=True)


@pytest.mark.integration
class TestMigrationIntegration:
    """Integration tests for migration system."""

    def test_full_migration_cycle(self) -> None:
        """Test complete migration cycle from version 0 to current."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            settings = DatabaseSettings(url=f"sqlite:///{db_path}")
            engine = create_engine_from_settings(settings)

            # Start with empty database
            final_version = apply_migrations(engine)
            assert final_version == CURRENT_SCHEMA_VERSION

            # Verify we can insert and query data
            Session = sessionmaker(bind=engine)
            session = Session()

            # Insert test data
            raw_event = RawEvent(
                source="test",
                source_offset=1,
                payload={
                    "session": "integration-test-session",
                    "eventid": "cowrie.session.connect",
                    "timestamp": "2025-01-27T12:00:00Z",
                },
            )
            session.add(raw_event)
            session.commit()

            # Query data
            events = session.query(RawEvent).all()
            assert len(events) == 1
            # Check if the real columns were populated by the migration
            if events[0].session_id is not None:
                assert events[0].session_id == "integration-test-session"
                assert events[0].event_type == "cowrie.session.connect"
            else:
                # If real columns weren't populated, check hybrid properties
                assert events[0].session_id_computed == "integration-test-session"
                assert events[0].event_type_computed == "cowrie.session.connect"

            session.close()

        finally:
            Path(db_path).unlink(missing_ok=True)
