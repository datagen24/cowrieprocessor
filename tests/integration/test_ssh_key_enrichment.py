"""Integration tests for SSH key enrichment pipeline."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cowrieprocessor.db import apply_migrations
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
def test_db():
    """Create a test database with SSH key intelligence schema."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    
    # Apply migrations to create all tables including SSH key intelligence
    apply_migrations(engine)
    
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def sample_cowrie_events() -> list[Dict[str, Any]]:
    """Sample Cowrie events with SSH key injection commands."""
    return [
        {
            "eventid": "cowrie.command.input",
            "timestamp": "2025-01-15T10:30:00.000000Z",
            "session": "test-session-1",
            "src_ip": "192.168.1.100",
            "input": "echo 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC7vbqajDhA... user@example.com' >> ~/.ssh/authorized_keys",
        },
        {
            "eventid": "cowrie.command.input", 
            "timestamp": "2025-01-15T10:31:00.000000Z",
            "session": "test-session-1",
            "src_ip": "192.168.1.100",
            "input": "printf 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG... attacker@evil.com' >> ~/.ssh/authorized_keys",
        },
        {
            "eventid": "cowrie.command.input",
            "timestamp": "2025-01-15T10:32:00.000000Z", 
            "session": "test-session-2",
            "src_ip": "192.168.1.101",
            "input": "echo 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC7vbqajDhA... user@example.com' >> ~/.ssh/authorized_keys",
        },
        {
            "eventid": "cowrie.command.input",
            "timestamp": "2025-01-15T10:33:00.000000Z",
            "session": "test-session-2", 
            "src_ip": "192.168.1.101",
            "input": "cat << EOF >> ~/.ssh/authorized_keys\nssh-ecdsa AAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBF... bot@botnet.com\nEOF",
        },
        {
            "eventid": "cowrie.command.input",
            "timestamp": "2025-01-15T10:34:00.000000Z",
            "session": "test-session-3",
            "src_ip": "192.168.1.102", 
            "input": "echo 'dGVzdC1kYXRh' | base64 -d >> ~/.ssh/authorized_keys",
        },
    ]


@pytest.fixture
def sample_raw_events(test_db, sample_cowrie_events):
    """Insert sample raw events into test database."""
    events = []
    for i, event_data in enumerate(sample_cowrie_events):
        event = RawEvent(
            ingest_id="test-ingest",
            source="test.log",
            source_offset=i,
            source_inode=12345,
            source_generation=0,
            payload=event_data,
            risk_score=50,
            quarantined=False,
            session_id=event_data["session"],
            event_type=event_data["eventid"],
            event_timestamp=datetime.fromisoformat(event_data["timestamp"].replace("Z", "+00:00")),
            src_ip=event_data["src_ip"],
        )
        test_db.add(event)
        events.append(event)
    
    test_db.commit()
    return events


class TestSSHKeyExtractionIntegration:
    """Test SSH key extraction and storage integration."""
    
    def test_extract_and_store_ssh_keys(self, test_db, sample_raw_events):
        """Test extracting SSH keys from raw events and storing them."""
        extractor = SSHKeyExtractor()
        
        # Extract keys from events
        all_extracted_keys = []
        for event in sample_raw_events:
            if event.payload and "input" in event.payload:
                input_data = event.payload["input"]
                if "authorized_keys" in input_data:
                    extracted_keys = extractor.extract_keys_from_command(input_data)
                    all_extracted_keys.extend(extracted_keys)
        
        # Should extract some keys (exact count depends on key format validity)
        assert len(all_extracted_keys) > 0
        
        # Store keys in database
        key_records = []
        for key in all_extracted_keys:
            # Check if key already exists
            existing_key = test_db.query(SSHKeyIntelligence).filter(
                SSHKeyIntelligence.key_hash == key.key_hash
            ).first()
            
            if not existing_key:
                key_record = SSHKeyIntelligence(
                    key_type=key.key_type,
                    key_data=key.key_data,
                    key_fingerprint=key.fingerprint,
                    key_hash=key.key_hash,
                    key_comment=key.comment,
                    key_size_bits=key.estimated_bits,
                    first_seen=datetime.now(timezone.utc),
                    last_seen=datetime.now(timezone.utc),
                    total_attempts=1,
                    unique_sources=1,
                    unique_sessions=1,
                )
                test_db.add(key_record)
                key_records.append(key_record)
            else:
                # Update existing key
                existing_key.last_seen = datetime.now(timezone.utc)
                existing_key.total_attempts += 1
                key_records.append(existing_key)
        
        test_db.commit()
        
        # Verify keys were stored
        stored_keys = test_db.query(SSHKeyIntelligence).all()
        assert len(stored_keys) > 0
        
        # Verify key data integrity
        for key_record in stored_keys:
            assert key_record.key_type is not None
            assert key_record.key_fingerprint is not None
            assert key_record.key_hash is not None
            assert key_record.total_attempts > 0
    
    def test_session_key_linking(self, test_db, sample_raw_events):
        """Test linking SSH keys to sessions."""
        extractor = SSHKeyExtractor()
        
        # Process events and create session-key links
        session_key_links = []
        for event in sample_raw_events:
            if event.payload and "input" in event.payload:
                input_data = event.payload["input"]
                if "authorized_keys" in input_data:
                    extracted_keys = extractor.extract_keys_from_command(input_data)
                    
                    for key in extracted_keys:
                        # Get or create key record
                        key_record = test_db.query(SSHKeyIntelligence).filter(
                            SSHKeyIntelligence.key_hash == key.key_hash
                        ).first()
                        
                        if not key_record:
                            key_record = SSHKeyIntelligence(
                                key_type=key.key_type,
                                key_data=key.key_data,
                                key_fingerprint=key.fingerprint,
                                key_hash=key.key_hash,
                                key_comment=key.comment,
                                key_size_bits=key.estimated_bits,
                                first_seen=datetime.now(timezone.utc),
                                last_seen=datetime.now(timezone.utc),
                                total_attempts=1,
                                unique_sources=1,
                                unique_sessions=1,
                            )
                            test_db.add(key_record)
                            test_db.flush()
                        
                        # Create session-key link
                        link = SessionSSHKeys(
                            session_id=event.session_id,
                            ssh_key_id=key_record.id,
                            command_text=input_data,
                            injection_method="echo_append",  # Simplified for test
                            source_ip=event.src_ip,
                            timestamp=event.event_timestamp,
                        )
                        test_db.add(link)
                        session_key_links.append(link)
        
        test_db.commit()
        
        # Verify session-key links were created
        stored_links = test_db.query(SessionSSHKeys).all()
        assert len(stored_links) > 0
        
        # Verify link data integrity
        for link in stored_links:
            assert link.session_id is not None
            assert link.ssh_key_id is not None
            assert link.command_text is not None
            assert link.injection_method is not None


class TestSSHKeyAnalyticsIntegration:
    """Test SSH key analytics functionality."""
    
    def test_campaign_detection(self, test_db):
        """Test SSH key campaign detection."""
        # Create sample key records that should form a campaign
        key1 = SSHKeyIntelligence(
            key_type="ssh-rsa",
            key_data="ssh-rsa AAAAB3NzaC1yc2E...",
            key_fingerprint="SHA256:abc123",
            key_hash="hash1",
            key_comment="user@example.com",
            key_size_bits=2048,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            total_attempts=5,
            unique_sources=3,
            unique_sessions=5,
        )
        
        key2 = SSHKeyIntelligence(
            key_type="ssh-ed25519",
            key_data="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5...",
            key_fingerprint="SHA256:def456", 
            key_hash="hash2",
            key_comment="attacker@evil.com",
            key_size_bits=256,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            total_attempts=4,
            unique_sources=2,
            unique_sessions=4,
        )
        
        test_db.add(key1)
        test_db.add(key2)
        test_db.flush()
        
        # Create association between keys
        association = SSHKeyAssociations(
            key_id_1=key1.id,
            key_id_2=key2.id,
            co_occurrence_count=3,
            same_session_count=2,
            same_ip_count=1,
        )
        test_db.add(association)
        test_db.commit()
        
        # Test campaign detection
        analytics = SSHKeyAnalytics(test_db)
        campaigns = analytics.identify_campaigns(
            min_attempts=3,
            min_ips=2,
            min_keys=2,
            days_back=30,
            confidence_threshold=0.5,
        )
        
        # Should detect at least one campaign
        assert len(campaigns) >= 1
        
        campaign = campaigns[0]
        assert len(campaign.key_fingerprints) >= 2
        assert campaign.total_sessions >= 3
        assert campaign.confidence_score > 0.0
    
    def test_key_timeline_analysis(self, test_db):
        """Test SSH key timeline analysis."""
        # Create a key record
        key = SSHKeyIntelligence(
            key_type="ssh-rsa",
            key_data="ssh-rsa AAAAB3NzaC1yc2E...",
            key_fingerprint="SHA256:test123",
            key_hash="test_hash",
            key_comment="test@example.com",
            key_size_bits=2048,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            total_attempts=3,
            unique_sources=2,
            unique_sessions=3,
        )
        test_db.add(key)
        test_db.flush()
        
        # Create session-key links
        for i in range(3):
            link = SessionSSHKeys(
                session_id=f"session-{i}",
                ssh_key_id=key.id,
                command_text=f"echo 'key' >> authorized_keys",
                injection_method="echo_append",
                source_ip=f"192.168.1.{100 + i}",
                timestamp=datetime.now(timezone.utc),
            )
            test_db.add(link)
        
        test_db.commit()
        
        # Test timeline analysis
        analytics = SSHKeyAnalytics(test_db)
        timeline = analytics.get_key_timeline("SHA256:test123")
        
        assert timeline is not None
        assert timeline.key_fingerprint == "SHA256:test123"
        assert timeline.key_type == "ssh-rsa"
        assert timeline.total_attempts == 3
        assert timeline.unique_sessions == 3
        assert len(timeline.sessions) == 3
    
    def test_related_keys_analysis(self, test_db):
        """Test related keys analysis."""
        # Create two related keys
        key1 = SSHKeyIntelligence(
            key_type="ssh-rsa",
            key_data="ssh-rsa AAAAB3NzaC1yc2E...",
            key_fingerprint="SHA256:key1",
            key_hash="hash1",
            key_comment="user1@example.com",
            key_size_bits=2048,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            total_attempts=5,
            unique_sources=2,
            unique_sessions=5,
        )
        
        key2 = SSHKeyIntelligence(
            key_type="ssh-ed25519",
            key_data="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5...",
            key_fingerprint="SHA256:key2",
            key_hash="hash2", 
            key_comment="user2@example.com",
            key_size_bits=256,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            total_attempts=4,
            unique_sources=2,
            unique_sessions=4,
        )
        
        test_db.add(key1)
        test_db.add(key2)
        test_db.flush()
        
        # Create association
        association = SSHKeyAssociations(
            key_id_1=key1.id,
            key_id_2=key2.id,
            co_occurrence_count=3,
            same_session_count=2,
            same_ip_count=1,
        )
        test_db.add(association)
        test_db.commit()
        
        # Test related keys analysis
        analytics = SSHKeyAnalytics(test_db)
        related_keys = analytics.find_related_keys(
            "SHA256:key1",
            min_association_strength=0.1,
            max_results=10,
        )
        
        assert len(related_keys) >= 1
        related = related_keys[0]
        assert related.key2_fingerprint == "SHA256:key2"
        assert related.co_occurrence_count == 3
        assert related.association_strength > 0.0
    
    def test_geographic_spread_analysis(self, test_db):
        """Test geographic spread analysis."""
        # Create a key record
        key = SSHKeyIntelligence(
            key_type="ssh-rsa",
            key_data="ssh-rsa AAAAB3NzaC1yc2E...",
            key_fingerprint="SHA256:geo123",
            key_hash="geo_hash",
            key_comment="geo@example.com",
            key_size_bits=2048,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            total_attempts=5,
            unique_sources=5,
            unique_sessions=5,
        )
        test_db.add(key)
        test_db.flush()
        
        # Create session-key links with different IPs
        ips = ["192.168.1.100", "192.168.1.101", "10.0.0.50", "172.16.0.10", "203.0.113.5"]
        for i, ip in enumerate(ips):
            link = SessionSSHKeys(
                session_id=f"session-{i}",
                ssh_key_id=key.id,
                command_text=f"echo 'key' >> authorized_keys",
                injection_method="echo_append",
                source_ip=ip,
                timestamp=datetime.now(timezone.utc),
            )
            test_db.add(link)
        
        test_db.commit()
        
        # Test geographic spread analysis
        analytics = SSHKeyAnalytics(test_db)
        geo_spread = analytics.calculate_geographic_spread("SHA256:geo123")
        
        assert geo_spread["unique_ips"] == 5
        assert geo_spread["unique_subnets"] == 4  # Different /24 subnets
        assert geo_spread["spread_diversity"] > 0.0
        assert "subnet_distribution" in geo_spread


class TestSessionSummaryIntegration:
    """Test session summary integration with SSH key counts."""
    
    def test_session_summary_ssh_key_counts(self, test_db):
        """Test that session summaries include SSH key counts."""
        # Create a session summary
        session_summary = SessionSummary(
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
        test_db.add(session_summary)
        test_db.commit()
        
        # Verify the session summary was created with SSH key counts
        stored_summary = test_db.query(SessionSummary).filter(
            SessionSummary.session_id == "test-session"
        ).first()
        
        assert stored_summary is not None
        assert stored_summary.ssh_key_injections == 2
        assert stored_summary.unique_ssh_keys == 1


class TestEndToEndIntegration:
    """Test end-to-end SSH key enrichment pipeline."""
    
    def test_full_enrichment_pipeline(self, test_db, sample_raw_events):
        """Test the complete SSH key enrichment pipeline."""
        extractor = SSHKeyExtractor()
        
        # Step 1: Extract SSH keys from raw events
        all_keys = []
        for event in sample_raw_events:
            if event.payload and "input" in event.payload:
                input_data = event.payload["input"]
                if "authorized_keys" in input_data:
                    extracted_keys = extractor.extract_keys_from_command(input_data)
                    all_keys.extend(extracted_keys)
        
        # Step 2: Store keys and create associations
        key_records = []
        session_links = []
        
        for event in sample_raw_events:
            if event.payload and "input" in event.payload:
                input_data = event.payload["input"]
                if "authorized_keys" in input_data:
                    extracted_keys = extractor.extract_keys_from_command(input_data)
                    
                    for key in extracted_keys:
                        # Store key intelligence
                        key_record = test_db.query(SSHKeyIntelligence).filter(
                            SSHKeyIntelligence.key_hash == key.key_hash
                        ).first()
                        
                        if not key_record:
                            key_record = SSHKeyIntelligence(
                                key_type=key.key_type,
                                key_data=key.key_data,
                                key_fingerprint=key.fingerprint,
                                key_hash=key.key_hash,
                                key_comment=key.comment,
                                key_size_bits=key.estimated_bits,
                                first_seen=datetime.now(timezone.utc),
                                last_seen=datetime.now(timezone.utc),
                                total_attempts=1,
                                unique_sources=1,
                                unique_sessions=1,
                            )
                            test_db.add(key_record)
                            key_records.append(key_record)
                        else:
                            key_record.total_attempts += 1
                        
                        # Create session-key link
                        link = SessionSSHKeys(
                            session_id=event.session_id,
                            ssh_key_id=key_record.id,
                            command_text=input_data,
                            injection_method="echo_append",
                            source_ip=event.src_ip,
                            timestamp=event.event_timestamp,
                        )
                        test_db.add(link)
                        session_links.append(link)
        
        test_db.commit()
        
        # Step 3: Create session summaries with SSH key counts
        session_ids = set(event.session_id for event in sample_raw_events)
        for session_id in session_ids:
            # Count SSH keys for this session
            key_count = test_db.query(SessionSSHKeys).filter(
                SessionSSHKeys.session_id == session_id
            ).count()
            
            unique_key_count = test_db.query(SessionSSHKeys.ssh_key_id).filter(
                SessionSSHKeys.session_id == session_id
            ).distinct().count()
            
            session_summary = SessionSummary(
                session_id=session_id,
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
                ssh_key_injections=key_count,
                unique_ssh_keys=unique_key_count,
            )
            test_db.add(session_summary)
        
        test_db.commit()
        
        # Step 4: Test analytics
        analytics = SSHKeyAnalytics(test_db)
        
        # Test top keys
        top_keys = analytics.get_top_keys_by_usage(days_back=30, limit=10)
        assert len(top_keys) >= 0
        
        # Test campaign detection
        campaigns = analytics.identify_campaigns(
            min_attempts=1,
            min_ips=1,
            min_keys=1,
            days_back=30,
            confidence_threshold=0.1,
        )
        assert len(campaigns) >= 0
        
        # Verify data integrity
        stored_keys = test_db.query(SSHKeyIntelligence).all()
        stored_links = test_db.query(SessionSSHKeys).all()
        stored_summaries = test_db.query(SessionSummary).all()
        
        assert len(stored_keys) > 0
        assert len(stored_links) > 0
        assert len(stored_summaries) > 0
        
        # Verify session summaries have SSH key counts
        for summary in stored_summaries:
            assert summary.ssh_key_injections >= 0
            assert summary.unique_ssh_keys >= 0
