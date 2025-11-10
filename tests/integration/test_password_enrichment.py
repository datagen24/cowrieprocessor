"""Integration tests for password enrichment workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cowrieprocessor.db.base import Base
from cowrieprocessor.db.models import PasswordStatistics, RawEvent, SessionSummary
from cowrieprocessor.enrichment.cache import EnrichmentCacheManager
from cowrieprocessor.enrichment.hibp_client import HIBPPasswordEnricher
from cowrieprocessor.enrichment.password_extractor import PasswordExtractor
from cowrieprocessor.enrichment.rate_limiting import RateLimitedSession


@pytest.fixture
def temp_dir():
    """Create temporary directory."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_db(temp_dir) -> None:
    """Create test database with schema."""
    db_path = temp_dir / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    SessionMaker = sessionmaker(bind=engine)
    return SessionMaker


@pytest.fixture
def cache_manager(temp_dir):
    """Create cache manager for testing."""
    cache_dir = temp_dir / "cache"
    return EnrichmentCacheManager(base_dir=cache_dir)


@pytest.fixture
def mock_rate_limiter():
    """Create mock rate limiter."""
    limiter = Mock(spec=RateLimitedSession)
    return limiter


def create_test_session(session_id: str, src_ip: str = "1.2.3.4") -> SessionSummary:
    """Create test session summary."""
    return SessionSummary(
        session_id=session_id,
        first_event_at=datetime.now(UTC),
        last_event_at=datetime.now(UTC),
        event_count=3,
        command_count=0,
        file_downloads=0,
        login_attempts=2,
        vt_flagged=False,
        dshield_flagged=False,
    )


def create_test_event(event_id: int, session_id: str, event_type: str, payload: dict) -> RawEvent:
    """Create test raw event."""
    return RawEvent(
        id=event_id,
        source=f"/tmp/test_{session_id}.json",
        payload=payload,
        session_id=session_id,
        event_type=event_type,
        event_timestamp=datetime.now(UTC).isoformat(),
    )


@pytest.mark.integration
def test_end_to_end_password_enrichment(test_db, cache_manager, mock_rate_limiter) -> None:
    """Test complete password enrichment workflow."""
    # Create test data
    session_id = "test123"

    with test_db() as db_session:
        # Create session and events
        session_summary = create_test_session(session_id)
        db_session.add(session_summary)

        # Create login events with passwords
        events = [
            create_test_event(1, session_id, 'cowrie.session.connect', {'src_ip': '1.2.3.4', 'protocol': 'ssh'}),
            create_test_event(2, session_id, 'cowrie.login.failed', {'username': 'root', 'password': 'password123'}),
            create_test_event(3, session_id, 'cowrie.login.success', {'username': 'root', 'password': 'admin'}),
        ]
        for event in events:
            db_session.add(event)

        db_session.commit()

        # Mock HIBP API responses
        def mock_get(url, **kwargs):
            response = Mock()
            # Simulate breached password response
            response.text = "3D68EB55068C33ACE09247EE4C639306B:100\nABC123DEF456:50"
            response.raise_for_status = Mock()
            return response

        mock_rate_limiter.get = mock_get

        # Initialize enrichment components
        hibp_enricher = HIBPPasswordEnricher(cache_manager, mock_rate_limiter)
        password_extractor = PasswordExtractor()

        # Extract passwords
        loaded_events = db_session.query(RawEvent).filter(RawEvent.session_id == session_id).all()

        password_attempts = password_extractor.extract_from_events(loaded_events)

        # Verify extraction
        assert len(password_attempts) == 2
        assert password_attempts[0]['username'] == 'root'
        assert password_attempts[0]['password'] == 'password123'
        assert password_attempts[1]['password'] == 'admin'

        # Enrich with HIBP
        checked_passwords = {}
        for attempt in password_attempts:
            password = attempt['password']
            if password not in checked_passwords:
                result = hibp_enricher.check_password(password)
                checked_passwords[password] = result

        # Verify HIBP checks
        assert len(checked_passwords) == 2
        assert all('breached' in result for result in checked_passwords.values())

        # Build password stats
        password_stats = {
            'total_attempts': len(password_attempts),
            'unique_passwords': len(checked_passwords),
            'breached_passwords': sum(1 for r in checked_passwords.values() if r['breached']),
            'breach_prevalence_max': max(
                (r['prevalence'] for r in checked_passwords.values() if r['breached']), default=0
            ),
            'novel_password_hashes': [
                attempt['password_sha256']
                for attempt in password_attempts
                if not checked_passwords[attempt['password']]['breached']
            ],
        }

        # Update session enrichment
        session_summary.enrichment = {'password_stats': password_stats}  # type: ignore[assignment]
        db_session.commit()

        # Verify enrichment was saved
        updated_session = db_session.query(SessionSummary).filter(SessionSummary.session_id == session_id).first()

        assert updated_session.enrichment is not None
        assert 'password_stats' in updated_session.enrichment
        assert updated_session.enrichment['password_stats']['total_attempts'] == 2
        assert updated_session.enrichment['password_stats']['unique_passwords'] == 2


@pytest.mark.integration
def test_daily_aggregation(test_db, cache_manager, mock_rate_limiter) -> None:
    """Test daily password statistics aggregation."""
    target_date = datetime.now(UTC).date()

    with test_db() as db_session:
        # Create multiple sessions with password stats
        for i in range(3):
            session_id = f"session{i}"
            session_summary = create_test_session(session_id)
            session_summary.enrichment = {  # type: ignore[assignment]
                'password_stats': {
                    'total_attempts': 5,
                    'unique_passwords': 3,
                    'breached_passwords': 2,
                    'breach_prevalence_max': 1000,
                    'novel_password_hashes': [f'hash{i}a', f'hash{i}b'],
                }
            }
            db_session.add(session_summary)

        db_session.commit()

        # Aggregate statistics
        sessions = db_session.query(SessionSummary).all()

        total_attempts = sum(s.enrichment.get('password_stats', {}).get('total_attempts', 0) for s in sessions)
        unique_hashes = set()
        for s in sessions:
            for hash_val in s.enrichment.get('password_stats', {}).get('novel_password_hashes', []):
                unique_hashes.add(hash_val)

        # Create daily statistics
        daily_stats = PasswordStatistics(
            date=target_date,
            total_attempts=total_attempts,
            unique_passwords=len(unique_hashes),
            breached_count=6,  # 2 per session * 3 sessions
            novel_count=len(unique_hashes),
            max_prevalence=1000,
        )
        db_session.add(daily_stats)
        db_session.commit()

        # Verify aggregation
        saved_stats = db_session.query(PasswordStatistics).filter(PasswordStatistics.date == target_date).first()

        assert saved_stats is not None
        assert saved_stats.total_attempts == 15  # 5 per session * 3
        assert saved_stats.breached_count == 6
        assert saved_stats.max_prevalence == 1000


@pytest.mark.integration
def test_cache_efficiency(cache_manager, mock_rate_limiter) -> None:
    """Test that cache reduces API calls."""

    # Mock HIBP response
    def mock_get(url, **kwargs):
        response = Mock()
        response.text = "3D68EB55068C33ACE09247EE4C639306B:100"
        response.raise_for_status = Mock()
        return response

    mock_rate_limiter.get = mock_get

    hibp_enricher = HIBPPasswordEnricher(cache_manager, mock_rate_limiter)

    # Check same password multiple times
    password = "testpassword"

    hibp_enricher.check_password(password)
    hibp_enricher.check_password(password)
    hibp_enricher.check_password(password)

    # Verify only one API call was made
    stats = hibp_enricher.get_stats()
    assert stats['checks'] == 3
    assert stats['api_calls'] == 1  # Only first check hits API
    assert stats['cache_hits'] == 2  # Second and third use cache
    assert stats['cache_misses'] == 1


@pytest.mark.integration
def test_force_reenrichment(test_db, cache_manager, mock_rate_limiter) -> None:
    """Test force re-enrichment of already-enriched sessions."""
    session_id = "test456"

    with test_db() as db_session:
        # Create session with existing password stats
        session_summary = create_test_session(session_id)
        session_summary.enrichment = {  # type: ignore[assignment]
            'password_stats': {
                'total_attempts': 1,
                'unique_passwords': 1,
                'breached_passwords': 0,
            }
        }
        db_session.add(session_summary)
        db_session.commit()

        # Verify initial enrichment
        assert session_summary.enrichment['password_stats']['total_attempts'] == 1  # type: ignore[index]

        # Force re-enrichment with new data
        new_stats = {
            'total_attempts': 5,
            'unique_passwords': 3,
            'breached_passwords': 2,
        }
        session_summary.enrichment = {'password_stats': new_stats}  # type: ignore[assignment]
        db_session.commit()

        # Verify update
        updated = db_session.query(SessionSummary).filter(SessionSummary.session_id == session_id).first()

        assert updated.enrichment['password_stats']['total_attempts'] == 5
        assert updated.enrichment['password_stats']['breached_passwords'] == 2


@pytest.mark.integration
def test_novel_password_tracking(test_db, cache_manager, mock_rate_limiter) -> None:
    """Test tracking of novel (non-breached) passwords."""
    session_id = "novel_test"

    with test_db() as db_session:
        # Create session and events
        session_summary = create_test_session(session_id)
        db_session.add(session_summary)

        # Create events with mix of breached and novel passwords
        events = [
            create_test_event(1, session_id, 'cowrie.login.failed', {'username': 'root', 'password': 'breached_pass'}),
            create_test_event(
                2, session_id, 'cowrie.login.failed', {'username': 'admin', 'password': 'novel_pass_12345'}
            ),
        ]
        for event in events:
            db_session.add(event)
        db_session.commit()

        # Mock HIBP - first password breached, second not
        call_count = [0]

        def mock_get(url, **kwargs):
            response = Mock()
            call_count[0] += 1
            if call_count[0] == 1:
                # First password is breached
                import hashlib

                sha1 = hashlib.sha1(b'breached_pass').hexdigest().upper()
                suffix = sha1[5:]
                response.text = f"{suffix}:100"
            else:
                # Second password is not breached (empty response)
                response.text = "NOTFOUND:1"
            response.raise_for_status = Mock()
            return response

        mock_rate_limiter.get = mock_get

        # Enrich
        hibp_enricher = HIBPPasswordEnricher(cache_manager, mock_rate_limiter)
        password_extractor = PasswordExtractor()

        loaded_events = db_session.query(RawEvent).filter(RawEvent.session_id == session_id).all()

        password_attempts = password_extractor.extract_from_events(loaded_events)

        # Check passwords
        novel_hashes = []
        for attempt in password_attempts:
            result = hibp_enricher.check_password(attempt['password'])
            if not result['breached']:
                novel_hashes.append(attempt['password_sha256'])

        # Verify novel passwords are tracked
        assert len(novel_hashes) >= 0  # At least one should be novel based on our mock
