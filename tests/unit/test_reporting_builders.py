"""Tests for report builder classes."""

from __future__ import annotations
from pathlib import Path

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cowrieprocessor.db import Base, RawEvent, SessionSummary
from cowrieprocessor.reporting.builders import DailyReportBuilder, build_context_for_date
from cowrieprocessor.reporting.dal import ReportingRepository


def _prepare_repository(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/builder.sqlite")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

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
                enrichment={
                    "session": {
                        "1.2.3.4": {
                            "dshield": {"ip": {"count": "8"}},
                            "urlhaus": "botnet",
                        }
                    },
                    "virustotal": {
                        "feedface": {
                            "data": {
                                "attributes": {
                                    "last_analysis_stats": {"malicious": 2},
                                    "popular_threat_classification": {"suggested_threat_label": "worm"},
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
                    "input_safe": "uname -a",
                    "src_ip": "1.2.3.4",
                },
                risk_score=0,
                quarantined=False,
                ingest_at=start,
            )
        )
        session.commit()

    return ReportingRepository(factory)


def test_daily_report_builder(tmp_path: Path) -> None:
    """Daily report builder returns expected payload."""
    repo = _prepare_repository(tmp_path)
    builder = DailyReportBuilder(repo, top_n=5)

    context = build_context_for_date("2024-01-01")
    report = builder.build(context)

    assert report["report_type"] == "daily"
    assert report["sessions"]["total"] == 1
    assert report["commands"]["top"][0]["command"] == "uname -a"
    assert report["enrichments"]["flagged"][0]["session"] == "s1"
