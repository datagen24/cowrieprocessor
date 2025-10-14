"""Simple integration tests for SSH key enrichment pipeline."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cowrieprocessor.db.models import Base
from cowrieprocessor.db.models import (
    RawEvent,
    SSHKeyIntelligence,
    SSHKeyAssociations,
    SessionSSHKeys,
    SessionSummary,
)
from cowrieprocessor.enrichment.ssh_key_analytics import SSHKeyAnalytics
from cowrieprocessor.enrichment.ssh_key_extractor import SSHKeyExtractor


@pytest.fixture
def simple_test_db():
    """Create a simple test database with just the SSH key tables."""
    # Create temporary SQLite database
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    temp_file.close()
    
    engine = create_engine(f"sqlite:///{temp_file.name}", echo=False)
    
    # Create only the tables we need for SSH key testing
    # This avoids the migration issues with other tables
    Base.metadata.create_all(engine, tables=[
        SSHKeyIntelligence.__table__,
        SessionSSHKeys.__table__,
        SSHKeyAssociations.__table__,
        SessionSummary.__table__,
        RawEvent.__table__,
    ])
    
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        Path(temp_file.name).unlink(missing_ok=True)


def test_ssh_key_extraction_and_storage(simple_test_db):
    """Test basic SSH key extraction and storage."""
    extractor = SSHKeyExtractor()
    
    # Test command with SSH key
    command = "echo 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC7vbqajDhA... user@example.com' >> ~/.ssh/authorized_keys"
    
    # Extract keys
    extracted_keys = extractor.extract_keys_from_command(command)
    assert len(extracted_keys) > 0
    
    # Store key in database
    key = extracted_keys[0]
    key_record = SSHKeyIntelligence(
        key_type=key.key_type,
        key_data=key.key_data,
        key_fingerprint=key.key_fingerprint,
        key_hash=key.key_hash,
        key_comment=key.key_comment,
        key_bits=key.key_bits,
        key_full=key.key_full,
        pattern_type=key.extraction_method,
        target_path=key.target_path,
        first_seen=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
        total_attempts=1,
        unique_sources=1,
        unique_sessions=1,
    )
    simple_test_db.add(key_record)
    simple_test_db.commit()
    
    # Verify storage
    stored_keys = simple_test_db.query(SSHKeyIntelligence).all()
    assert len(stored_keys) == 1
    assert stored_keys[0].key_fingerprint == key.key_fingerprint


def test_session_key_linking(simple_test_db):
    """Test linking SSH keys to sessions."""
    extractor = SSHKeyExtractor()
    
    # Create a key record
    command = "echo 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC7vbqajDhA... user@example.com' >> ~/.ssh/authorized_keys"
    extracted_keys = extractor.extract_keys_from_command(command)
    
    key = extracted_keys[0]
    key_record = SSHKeyIntelligence(
        key_type=key.key_type,
        key_data=key.key_data,
        key_fingerprint=key.key_fingerprint,
        key_hash=key.key_hash,
        key_comment=key.key_comment,
        key_bits=key.key_bits,
        key_full=key.key_full,
        pattern_type=key.extraction_method,
        target_path=key.target_path,
        first_seen=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
        total_attempts=1,
        unique_sources=1,
        unique_sessions=1,
    )
    simple_test_db.add(key_record)
    simple_test_db.flush()  # Get the ID
    
    # Create session-key link
    link = SessionSSHKeys(
        session_id="test-session-1",
        ssh_key_id=key_record.id,
        command_text=command,
        injection_method="echo_append",
        source_ip="192.168.1.100",
        timestamp=datetime.now(timezone.utc),
    )
    simple_test_db.add(link)
    simple_test_db.commit()
    
    # Verify link
    stored_links = simple_test_db.query(SessionSSHKeys).all()
    assert len(stored_links) == 1
    assert stored_links[0].session_id == "test-session-1"
    assert stored_links[0].ssh_key_id == key_record.id


def test_ssh_key_analytics_basic(simple_test_db):
    """Test basic SSH key analytics functionality."""
    # Create sample key records
    key1 = SSHKeyIntelligence(
        key_type="ssh-rsa",
        key_data="ssh-rsa AAAAB3NzaC1yc2E...",
        key_fingerprint="SHA256:test1",
        key_hash="hash1",
        key_comment="user1@example.com",
        key_bits=2048,
        key_full="ssh-rsa AAAAB3NzaC1yc2E... user1@example.com",
        pattern_type="direct_echo",
        target_path="~/.ssh/authorized_keys",
        first_seen=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
        total_attempts=3,
        unique_sources=2,
        unique_sessions=3,
    )
    
    key2 = SSHKeyIntelligence(
        key_type="ssh-ed25519",
        key_data="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5...",
        key_fingerprint="SHA256:test2",
        key_hash="hash2",
        key_comment="user2@example.com",
        key_bits=256,
        key_full="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5... user2@example.com",
        pattern_type="direct_echo",
        target_path="~/.ssh/authorized_keys",
        first_seen=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
        total_attempts=2,
        unique_sources=1,
        unique_sessions=2,
    )
    
    simple_test_db.add(key1)
    simple_test_db.add(key2)
    simple_test_db.commit()
    
    # Test analytics
    analytics = SSHKeyAnalytics(simple_test_db)
    
    # Test top keys
    top_keys = analytics.get_top_keys_by_usage(days_back=30, limit=10)
    assert len(top_keys) == 2
    assert top_keys[0]["total_attempts"] == 3  # Should be sorted by usage
    
    # Test key timeline
    timeline = analytics.get_key_timeline("SHA256:test1")
    assert timeline is not None
    assert timeline.key_fingerprint == "SHA256:test1"
    assert timeline.total_attempts == 3


def test_session_summary_ssh_key_counts(simple_test_db):
    """Test session summary with SSH key counts."""
    # Create session summary with SSH key counts
    summary = SessionSummary(
        session_id="test-session",
        event_count=5,
        command_count=3,
        file_downloads=0,
        login_attempts=1,
        first_event_at=datetime.now(timezone.utc),
        last_event_at=datetime.now(timezone.utc),
        risk_score=75,
        source_files=["test.log"],
        matcher="test-sensor",
        vt_flagged=False,
        dshield_flagged=False,
        enrichment=None,
        ssh_key_injections=2,
        unique_ssh_keys=1,
    )
    simple_test_db.add(summary)
    simple_test_db.commit()
    
    # Verify the session summary
    stored_summary = simple_test_db.query(SessionSummary).filter(
        SessionSummary.session_id == "test-session"
    ).first()
    
    assert stored_summary is not None
    assert stored_summary.ssh_key_injections == 2
    assert stored_summary.unique_ssh_keys == 1


def test_geographic_spread_analysis(simple_test_db):
    """Test geographic spread analysis."""
    # Create a key record
    key = SSHKeyIntelligence(
        key_type="ssh-rsa",
        key_data="ssh-rsa AAAAB3NzaC1yc2E...",
        key_fingerprint="SHA256:geo123",
        key_hash="geo_hash",
        key_comment="geo@example.com",
        key_bits=2048,
        key_full="ssh-rsa AAAAB3NzaC1yc2E... geo@example.com",
        pattern_type="direct_echo",
        target_path="~/.ssh/authorized_keys",
        first_seen=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
        total_attempts=3,
        unique_sources=3,
        unique_sessions=3,
    )
    simple_test_db.add(key)
    simple_test_db.flush()
    
    # Create session-key links with different IPs
    ips = ["192.168.1.100", "192.168.1.101", "10.0.0.50"]
    for i, ip in enumerate(ips):
        link = SessionSSHKeys(
            session_id=f"session-{i}",
            ssh_key_id=key.id,
            command_text="echo 'key' >> authorized_keys",
            injection_method="echo_append",
            source_ip=ip,
            timestamp=datetime.now(timezone.utc),
        )
        simple_test_db.add(link)
    
    simple_test_db.commit()
    
    # Test geographic spread analysis
    analytics = SSHKeyAnalytics(simple_test_db)
    geo_spread = analytics.calculate_geographic_spread("SHA256:geo123")
    
    assert geo_spread["unique_ips"] == 3
    assert geo_spread["unique_subnets"] == 2  # Different /24 subnets
    assert geo_spread["spread_diversity"] > 0.0
    assert "subnet_distribution" in geo_spread


def test_end_to_end_simple_pipeline(simple_test_db):
    """Test a simple end-to-end pipeline."""
    extractor = SSHKeyExtractor()
    
    # Sample commands with SSH keys
    commands = [
        "echo 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC7vbqajDhA... user@example.com' >> ~/.ssh/authorized_keys",
        "printf 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG... attacker@evil.com' >> ~/.ssh/authorized_keys",
    ]
    
    # Process commands
    key_records = []
    session_links = []
    
    for i, command in enumerate(commands):
        extracted_keys = extractor.extract_keys_from_command(command)
        
        for key in extracted_keys:
            # Store key intelligence
            key_record = SSHKeyIntelligence(
                key_type=key.key_type,
                key_data=key.key_data,
                key_fingerprint=key.key_fingerprint,
                key_hash=key.key_hash,
                key_comment=key.key_comment,
                key_bits=key.key_bits,
                key_full=key.key_full,
                pattern_type=key.extraction_method,
                target_path=key.target_path,
                first_seen=datetime.now(timezone.utc),
                last_seen=datetime.now(timezone.utc),
                total_attempts=1,
                unique_sources=1,
                unique_sessions=1,
            )
            simple_test_db.add(key_record)
            simple_test_db.flush()  # Get the ID
            key_records.append(key_record)
            
            # Create session-key link
            link = SessionSSHKeys(
                session_id=f"session-{i}",
                ssh_key_id=key_record.id,
                command_text=command,
                injection_method="echo_append",
                source_ip=f"192.168.1.{100 + i}",
                timestamp=datetime.now(timezone.utc),
            )
            simple_test_db.add(link)
            session_links.append(link)
    
    simple_test_db.commit()
    
    # Create session summary
    summary = SessionSummary(
        session_id="session-0",
        event_count=5,
        command_count=3,
        file_downloads=0,
        login_attempts=1,
        first_event_at=datetime.now(timezone.utc),
        last_event_at=datetime.now(timezone.utc),
        risk_score=75,
        source_files=["test.log"],
        matcher="test-sensor",
        vt_flagged=False,
        dshield_flagged=False,
        enrichment=None,
        ssh_key_injections=len([l for l in session_links if l.session_id == "session-0"]),
        unique_ssh_keys=len(set(l.ssh_key_id for l in session_links if l.session_id == "session-0")),
    )
    simple_test_db.add(summary)
    simple_test_db.commit()
    
    # Test analytics
    analytics = SSHKeyAnalytics(simple_test_db)
    top_keys = analytics.get_top_keys_by_usage(days_back=30, limit=10)
    
    # Verify results
    assert len(top_keys) > 0
    assert len(key_records) > 0
    assert len(session_links) > 0
    
    # Verify session summary has SSH key counts
    stored_summary = simple_test_db.query(SessionSummary).filter(
        SessionSummary.session_id == "session-0"
    ).first()
    assert stored_summary.ssh_key_injections > 0
    assert stored_summary.unique_ssh_keys > 0
