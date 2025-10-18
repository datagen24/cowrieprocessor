"""Integration tests for reporting queries with JSON abstraction layer."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.db.migrations import apply_migrations
from cowrieprocessor.db.models import RawEvent, SessionSummary
from cowrieprocessor.reporting.dal import ReportingRepository
from cowrieprocessor.settings import DatabaseSettings


class TestReportingQueries:
    """Test reporting queries with JSON abstraction layer."""

    def test_session_stats_with_json_abstraction(self) -> None:
        """Test session statistics using JSON abstraction layer."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            # Create database and apply migrations
            settings = DatabaseSettings(url=f"sqlite:///{db_path}")
            engine = create_engine_from_settings(settings)
            apply_migrations(engine)

            # Create session and insert test data
            Session = sessionmaker(bind=engine)
            session = Session()

            # Insert test raw events
            test_time = datetime(2025, 1, 27, 10, 0, 0, tzinfo=timezone.utc)
            test_events = [
                RawEvent(
                    source="test",
                    source_offset=1,
                    ingest_at=test_time,
                    payload={
                        "session": "session-1",
                        "src_ip": "192.168.1.1",
                        "sensor": "test-sensor",
                        "eventid": "cowrie.session.connect",
                        "timestamp": "2025-01-27T10:00:00Z",
                    },
                ),
                RawEvent(
                    source="test",
                    source_offset=2,
                    ingest_at=test_time,
                    payload={
                        "session": "session-1",
                        "src_ip": "192.168.1.1",
                        "sensor": "test-sensor",
                        "eventid": "cowrie.session.command",
                        "input_safe": "ls -la",
                        "timestamp": "2025-01-27T10:01:00Z",
                    },
                ),
                RawEvent(
                    source="test",
                    source_offset=3,
                    ingest_at=test_time,
                    payload={
                        "session": "session-2",
                        "src_ip": "192.168.1.2",
                        "sensor": "test-sensor",
                        "eventid": "cowrie.session.file_download",
                        "url": "http://example.com/malware.exe",
                        "timestamp": "2025-01-27T10:02:00Z",
                    },
                ),
            ]

            for event in test_events:
                session.add(event)

            # Insert test session summaries
            test_summaries = [
                SessionSummary(
                    session_id="session-1",
                    matcher="test-sensor",
                    first_event_at=datetime(2025, 1, 27, 10, 0, 0, tzinfo=timezone.utc),
                    command_count=1,
                    file_downloads=0,
                    login_attempts=1,
                    vt_flagged=False,
                    dshield_flagged=False,
                ),
                SessionSummary(
                    session_id="session-2",
                    matcher="test-sensor",
                    first_event_at=datetime(2025, 1, 27, 10, 2, 0, tzinfo=timezone.utc),
                    command_count=0,
                    file_downloads=1,
                    login_attempts=0,
                    vt_flagged=True,
                    dshield_flagged=False,
                ),
            ]

            for summary in test_summaries:
                session.add(summary)

            session.commit()

            # Test reporting repository
            repo = ReportingRepository(sessionmaker(bind=engine))

            # Test session stats
            start_time = datetime(2025, 1, 27, 9, 0, 0, tzinfo=timezone.utc)
            end_time = datetime(2025, 1, 27, 11, 0, 0, tzinfo=timezone.utc)

            stats = repo.session_stats(start_time, end_time, sensor="test-sensor")

            # Verify statistics
            assert stats.total_sessions == 2
            assert stats.avg_commands == 0.5  # (1 + 0) / 2
            assert stats.max_commands == 1
            assert stats.min_commands == 0
            assert stats.file_downloads == 1
            assert stats.login_attempts == 1
            assert stats.vt_flagged == 1
            assert stats.dshield_flagged == 0
            assert stats.unique_ips == 2  # 192.168.1.1 and 192.168.1.2

            session.close()

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_top_commands_with_json_abstraction(self) -> None:
        """Test top commands query using JSON abstraction layer."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            # Create database and apply migrations
            settings = DatabaseSettings(url=f"sqlite:///{db_path}")
            engine = create_engine_from_settings(settings)
            apply_migrations(engine)

            # Create session and insert test data
            Session = sessionmaker(bind=engine)
            session = Session()

            # Insert test command events
            test_time = datetime(2025, 1, 27, 10, 0, 0, tzinfo=timezone.utc)
            test_commands = [
                RawEvent(
                    source="test",
                    source_offset=1,
                    ingest_at=test_time,
                    payload={
                        "session": "session-1",
                        "sensor": "test-sensor",
                        "eventid": "cowrie.session.command",
                        "input_safe": "ls -la",
                        "timestamp": "2025-01-27T10:00:00Z",
                    },
                ),
                RawEvent(
                    source="test",
                    source_offset=2,
                    ingest_at=test_time,
                    payload={
                        "session": "session-2",
                        "sensor": "test-sensor",
                        "eventid": "cowrie.session.command",
                        "input_safe": "ls -la",
                        "timestamp": "2025-01-27T10:01:00Z",
                    },
                ),
                RawEvent(
                    source="test",
                    source_offset=3,
                    ingest_at=test_time,
                    payload={
                        "session": "session-3",
                        "sensor": "test-sensor",
                        "eventid": "cowrie.session.command",
                        "input_safe": "cat /etc/passwd",
                        "timestamp": "2025-01-27T10:02:00Z",
                    },
                ),
            ]

            for event in test_commands:
                session.add(event)

            session.commit()

            # Test reporting repository
            repo = ReportingRepository(sessionmaker(bind=engine))

            # Test top commands
            start_time = datetime(2025, 1, 27, 9, 0, 0, tzinfo=timezone.utc)
            end_time = datetime(2025, 1, 27, 11, 0, 0, tzinfo=timezone.utc)

            commands = list(repo.top_commands(start_time, end_time, top_n=5, sensor="test-sensor"))

            # Verify results
            assert len(commands) == 2
            assert commands[0].command == "ls -la"
            assert commands[0].occurrences == 2
            assert commands[1].command == "cat /etc/passwd"
            assert commands[1].occurrences == 1

            session.close()

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_top_file_downloads_with_json_abstraction(self) -> None:
        """Test top file downloads query using JSON abstraction layer."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            # Create database and apply migrations
            settings = DatabaseSettings(url=f"sqlite:///{db_path}")
            engine = create_engine_from_settings(settings)
            apply_migrations(engine)

            # Create session and insert test data
            Session = sessionmaker(bind=engine)
            session = Session()

            # Insert test file download events
            test_time = datetime(2025, 1, 27, 10, 0, 0, tzinfo=timezone.utc)
            test_downloads = [
                RawEvent(
                    source="test",
                    source_offset=1,
                    ingest_at=test_time,
                    payload={
                        "session": "session-1",
                        "sensor": "test-sensor",
                        "eventid": "cowrie.session.file_download",
                        "url": "http://example.com/malware.exe",
                        "timestamp": "2025-01-27T10:00:00Z",
                    },
                ),
                RawEvent(
                    source="test",
                    source_offset=2,
                    ingest_at=test_time,
                    payload={
                        "session": "session-2",
                        "sensor": "test-sensor",
                        "eventid": "cowrie.session.file_download",
                        "url": "http://example.com/malware.exe",
                        "timestamp": "2025-01-27T10:01:00Z",
                    },
                ),
                RawEvent(
                    source="test",
                    source_offset=3,
                    ingest_at=test_time,
                    payload={
                        "session": "session-3",
                        "sensor": "test-sensor",
                        "eventid": "cowrie.session.file_download",
                        "url": "http://malicious.com/trojan.zip",
                        "timestamp": "2025-01-27T10:02:00Z",
                    },
                ),
            ]

            for event in test_downloads:
                session.add(event)

            session.commit()

            # Test reporting repository
            repo = ReportingRepository(sessionmaker(bind=engine))

            # Test top file downloads
            start_time = datetime(2025, 1, 27, 9, 0, 0, tzinfo=timezone.utc)
            end_time = datetime(2025, 1, 27, 11, 0, 0, tzinfo=timezone.utc)

            downloads = list(repo.top_file_downloads(start_time, end_time, top_n=5, sensor="test-sensor"))

            # Verify results
            assert len(downloads) == 2
            assert downloads[0].url == "http://example.com/malware.exe"
            assert downloads[0].occurrences == 2
            assert downloads[1].url == "http://malicious.com/trojan.zip"
            assert downloads[1].occurrences == 1

            session.close()

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_reporting_queries_without_sensor_filter(self) -> None:
        """Test reporting queries without sensor filter."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            # Create database and apply migrations
            settings = DatabaseSettings(url=f"sqlite:///{db_path}")
            engine = create_engine_from_settings(settings)
            apply_migrations(engine)

            # Create session and insert test data
            Session = sessionmaker(bind=engine)
            session = Session()

            # Insert test events from multiple sensors
            test_time = datetime(2025, 1, 27, 10, 0, 0, tzinfo=timezone.utc)
            test_events = [
                RawEvent(
                    source="test",
                    source_offset=1,
                    ingest_at=test_time,
                    payload={
                        "session": "session-1",
                        "src_ip": "192.168.1.1",
                        "sensor": "sensor-1",
                        "eventid": "cowrie.session.command",
                        "input_safe": "ls -la",
                        "timestamp": "2025-01-27T10:00:00Z",
                    },
                ),
                RawEvent(
                    source="test",
                    source_offset=2,
                    ingest_at=test_time,
                    payload={
                        "session": "session-2",
                        "src_ip": "192.168.1.2",
                        "sensor": "sensor-2",
                        "eventid": "cowrie.session.command",
                        "input_safe": "cat /etc/passwd",
                        "timestamp": "2025-01-27T10:01:00Z",
                    },
                ),
            ]

            for event in test_events:
                session.add(event)

            session.commit()

            # Test reporting repository
            repo = ReportingRepository(sessionmaker(bind=engine))

            # Test top commands without sensor filter
            start_time = datetime(2025, 1, 27, 9, 0, 0, tzinfo=timezone.utc)
            end_time = datetime(2025, 1, 27, 11, 0, 0, tzinfo=timezone.utc)

            commands = list(repo.top_commands(start_time, end_time, top_n=5))

            # Verify results (should include both sensors)
            assert len(commands) == 2
            assert commands[0].command == "ls -la"
            assert commands[0].occurrences == 1
            assert commands[1].command == "cat /etc/passwd"
            assert commands[1].occurrences == 1

            session.close()

        finally:
            Path(db_path).unlink(missing_ok=True)


@pytest.mark.integration
class TestReportingIntegration:
    """Integration tests for reporting system."""

    def test_full_reporting_workflow(self) -> None:
        """Test complete reporting workflow with JSON abstraction."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            # Create database and apply migrations
            settings = DatabaseSettings(url=f"sqlite:///{db_path}")
            engine = create_engine_from_settings(settings)
            apply_migrations(engine)

            # Create session and insert comprehensive test data
            Session = sessionmaker(bind=engine)
            session = Session()

            # Insert mixed event types
            test_time = datetime(2025, 1, 27, 10, 0, 0, tzinfo=timezone.utc)
            test_events = [
                # Session connect
                RawEvent(
                    source="test",
                    source_offset=1,
                    ingest_at=test_time,
                    payload={
                        "session": "session-1",
                        "src_ip": "192.168.1.1",
                        "sensor": "test-sensor",
                        "eventid": "cowrie.session.connect",
                        "timestamp": "2025-01-27T10:00:00Z",
                    },
                ),
                # Commands
                RawEvent(
                    source="test",
                    source_offset=2,
                    ingest_at=test_time,
                    payload={
                        "session": "session-1",
                        "src_ip": "192.168.1.1",
                        "sensor": "test-sensor",
                        "eventid": "cowrie.session.command",
                        "input_safe": "ls -la",
                        "timestamp": "2025-01-27T10:01:00Z",
                    },
                ),
                RawEvent(
                    source="test",
                    source_offset=3,
                    ingest_at=test_time,
                    payload={
                        "session": "session-1",
                        "src_ip": "192.168.1.1",
                        "sensor": "test-sensor",
                        "eventid": "cowrie.session.command",
                        "input_safe": "cat /etc/passwd",
                        "timestamp": "2025-01-27T10:02:00Z",
                    },
                ),
                # File download
                RawEvent(
                    source="test",
                    source_offset=4,
                    ingest_at=test_time,
                    payload={
                        "session": "session-1",
                        "src_ip": "192.168.1.1",
                        "sensor": "test-sensor",
                        "eventid": "cowrie.session.file_download",
                        "url": "http://example.com/malware.exe",
                        "timestamp": "2025-01-27T10:03:00Z",
                    },
                ),
            ]

            for event in test_events:
                session.add(event)

            # Insert session summary
            session_summary = SessionSummary(
                session_id="session-1",
                matcher="test-sensor",
                first_event_at=datetime(2025, 1, 27, 10, 0, 0, tzinfo=timezone.utc),
                command_count=2,
                file_downloads=1,
                login_attempts=1,
                vt_flagged=True,
                dshield_flagged=False,
            )
            session.add(session_summary)

            session.commit()

            # Test reporting repository
            repo = ReportingRepository(sessionmaker(bind=engine))

            # Test all reporting functions
            start_time = datetime(2025, 1, 27, 9, 0, 0, tzinfo=timezone.utc)
            end_time = datetime(2025, 1, 27, 11, 0, 0, tzinfo=timezone.utc)

            # Session stats
            stats = repo.session_stats(start_time, end_time, sensor="test-sensor")
            assert stats.total_sessions == 1
            assert stats.avg_commands == 2.0
            assert stats.file_downloads == 1
            assert stats.login_attempts == 1
            assert stats.vt_flagged == 1
            assert stats.unique_ips == 1

            # Top commands
            commands = list(repo.top_commands(start_time, end_time, sensor="test-sensor"))
            assert len(commands) == 2
            assert commands[0].command == "ls -la"
            assert commands[1].command == "cat /etc/passwd"

            # Top file downloads
            downloads = list(repo.top_file_downloads(start_time, end_time, sensor="test-sensor"))
            assert len(downloads) == 1
            assert downloads[0].url == "http://example.com/malware.exe"
            assert downloads[0].occurrences == 1

            session.close()

        finally:
            Path(db_path).unlink(missing_ok=True)
