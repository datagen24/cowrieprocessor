"""Regression tests for password tracking helper logic."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cowrieprocessor.cli.enrich_passwords import _track_password
from cowrieprocessor.db.base import Base
from cowrieprocessor.db.models import PasswordSessionUsage, PasswordTracking, SessionSummary


def _session_factory():
    """Create a SQLite-backed session maker mirroring production settings."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, future=True)


def test_track_password_de_dupes_usage_rows() -> None:
    """Ensure multiple attempts in a session do not violate the usage unique constraint."""

    session_maker = _session_factory()

    with session_maker() as db_session:
        session_id = "test-session"
        now = datetime.now(UTC)

        db_session.add(
            SessionSummary(
                session_id=session_id,
                first_event_at=now,
                last_event_at=now,
                event_count=0,
                command_count=0,
                file_downloads=0,
                login_attempts=0,
            )
        )
        db_session.commit()

        password = "admin"
        password_sha256 = hashlib.sha256(password.encode("utf-8")).hexdigest()
        hibp_result = {"breached": False, "prevalence": 0, "cached": False, "error": None}

        # First attempt creates password tracking + usage row
        _track_password(
            db_session=db_session,
            password=password,
            password_sha256=password_sha256,
            hibp_result=hibp_result,
            session_id=session_id,
            username="root",
            success=False,
            timestamp=now.isoformat(),
        )

        # Second attempt (same password/session) should update existing usage, not add a duplicate
        later = now + timedelta(seconds=1)
        _track_password(
            db_session=db_session,
            password=password,
            password_sha256=password_sha256,
            hibp_result=hibp_result,
            session_id=session_id,
            username="root",
            success=True,
            timestamp=later.isoformat(),
        )

        db_session.commit()

        usage_rows = db_session.query(PasswordSessionUsage).filter_by(session_id=session_id).all()
        assert len(usage_rows) == 1
        usage = usage_rows[0]
        assert usage.success is True
        usage_ts = usage.timestamp
        if usage_ts.tzinfo is None:
            usage_ts = usage_ts.replace(tzinfo=UTC)
        assert usage_ts == later

        tracking = db_session.query(PasswordTracking).filter_by(password_hash=password_sha256).one()
        assert tracking.times_seen == 2
        assert tracking.unique_sessions == 1
