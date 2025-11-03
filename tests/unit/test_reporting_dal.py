"""Tests for reporting data access layer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cowrieprocessor.db import Base, RawEvent, SessionSummary
from cowrieprocessor.reporting.dal import ReportingRepository


def _session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/reporting.sqlite")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_session_stats_and_top_commands(tmp_path: Path) -> None:
    """Repository aggregates stats and top values correctly."""
    factory = _session_factory(tmp_path)
    repo = ReportingRepository(factory)

    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 2, tzinfo=UTC)

    with factory() as session:
        session.add(
            SessionSummary(
                session_id="s1",
                first_event_at=start,
                last_event_at=end,
                event_count=5,
                command_count=3,
                file_downloads=1,
                login_attempts=1,
                vt_flagged=1,
                dshield_flagged=0,
                matcher="sensor-a",
                enrichment={
                    "session": {
                        "1.2.3.4": {
                            "dshield": {"ip": {"count": "10", "attacks": "12"}},
                            "urlhaus": "malware",
                        }
                    },
                    "virustotal": {
                        "deadbeef": {
                            "data": {
                                "attributes": {
                                    "last_analysis_stats": {"malicious": 5},
                                    "popular_threat_classification": {"suggested_threat_label": "trojan"},
                                }
                            }
                        }
                    },
                },
            )
        )
        session.add(
            RawEvent(
                ingest_id="ing-1",
                source="/tmp/log.json",
                source_offset=0,
                source_generation=0,
                payload={
                    "eventid": "cowrie.command.input",
                    "input_safe": "ls",
                    "src_ip": "1.2.3.4",
                    "sensor": "sensor-a",
                },
                risk_score=0,
                quarantined=False,
                ingest_at=start,
            )
        )
        session.add(
            RawEvent(
                ingest_id="ing-1",
                source="/tmp/log.json",
                source_offset=1,
                source_generation=0,
                payload={
                    "eventid": "cowrie.session.file_download",
                    "url": "http://malicious",
                    "src_ip": "1.2.3.4",
                    "sensor": "sensor-a",
                },
                risk_score=0,
                quarantined=False,
                ingest_at=start,
            )
        )
        session.commit()

    stats = repo.session_stats(start, end, sensor="sensor-a")
    assert stats.total_sessions == 1
    assert stats.file_downloads == 1
    assert stats.unique_ips == 1

    commands = list(repo.top_commands(start, end, top_n=5, sensor="sensor-a"))
    assert commands[0].command == "ls"

    downloads = list(repo.top_file_downloads(start, end, sensor="sensor-a"))
    assert downloads[0].url == "http://malicious"

    assert repo.sensors() == ["sensor-a"]


def test_enriched_sessions(tmp_path: Path) -> None:
    """Repository returns enrichment payload metadata for flagged sessions."""
    factory = _session_factory(tmp_path)
    repo = ReportingRepository(factory)

    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 2, tzinfo=UTC)

    with factory() as session:
        session.add(
            SessionSummary(
                session_id="s1",
                first_event_at=start,
                last_event_at=end,
                event_count=5,
                command_count=3,
                file_downloads=1,
                login_attempts=1,
                vt_flagged=1,
                dshield_flagged=1,
                matcher="sensor-a",
                enrichment={
                    "session": {
                        "1.2.3.4": {
                            "dshield": {"ip": {"count": "10", "attacks": "12"}},
                            "urlhaus": "malware",
                            "spur": ["", "", "", "DATACENTER"],
                        }
                    }
                },
            )
        )
        session.commit()

    rows = repo.enriched_sessions(start, end, sensor="sensor-a", limit=5)
    assert len(rows) == 1
    row = rows[0]
    assert row.session_id == "s1"
    assert row.sensor == "sensor-a"
    assert isinstance(row.enrichment, dict)
    assert "session" in row.enrichment
