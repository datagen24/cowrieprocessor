"""Unit tests for password extraction from Cowrie events."""

from __future__ import annotations

import hashlib
from unittest.mock import Mock

import pytest

from cowrieprocessor.db.models import RawEvent
from cowrieprocessor.enrichment.password_extractor import PasswordExtractor


@pytest.fixture
def password_extractor():
    """Create password extractor for testing."""
    return PasswordExtractor()


def create_mock_event(event_type: str, payload: dict) -> RawEvent:
    """Create mock RawEvent for testing."""
    event = Mock(spec=RawEvent)
    event.event_type = event_type
    event.payload = payload
    event.event_timestamp = "2025-10-10T10:00:00Z"
    return event


def test_extract_from_login_success(password_extractor):
    """Test extracting password from successful login."""
    events = [
        create_mock_event(
            'cowrie.login.success',
            {'username': 'root', 'password': 'password123'}
        )
    ]
    
    results = password_extractor.extract_from_events(events)
    
    assert len(results) == 1
    assert results[0]['password'] == 'password123'
    assert results[0]['username'] == 'root'
    assert results[0]['success'] is True
    assert 'password_sha256' in results[0]


def test_extract_from_login_failed(password_extractor):
    """Test extracting password from failed login."""
    events = [
        create_mock_event(
            'cowrie.login.failed',
            {'username': 'admin', 'password': 'wrongpass'}
        )
    ]
    
    results = password_extractor.extract_from_events(events)
    
    assert len(results) == 1
    assert results[0]['password'] == 'wrongpass'
    assert results[0]['username'] == 'admin'
    assert results[0]['success'] is False


def test_extract_multiple_attempts(password_extractor):
    """Test extracting multiple password attempts."""
    events = [
        create_mock_event('cowrie.login.failed', {'username': 'root', 'password': 'pass1'}),
        create_mock_event('cowrie.login.failed', {'username': 'root', 'password': 'pass2'}),
        create_mock_event('cowrie.login.success', {'username': 'root', 'password': 'pass3'}),
    ]
    
    results = password_extractor.extract_from_events(events)
    
    assert len(results) == 3
    assert results[0]['password'] == 'pass1'
    assert results[1]['password'] == 'pass2'
    assert results[2]['password'] == 'pass3'
    assert results[2]['success'] is True


def test_skip_non_login_events(password_extractor):
    """Test that non-login events are skipped."""
    events = [
        create_mock_event('cowrie.session.connect', {'src_ip': '1.2.3.4'}),
        create_mock_event('cowrie.command.input', {'input': 'ls -la'}),
        create_mock_event('cowrie.login.success', {'username': 'root', 'password': 'pass123'}),
    ]
    
    results = password_extractor.extract_from_events(events)
    
    assert len(results) == 1
    assert results[0]['password'] == 'pass123'


def test_skip_events_without_password(password_extractor):
    """Test that events without password field are skipped."""
    events = [
        create_mock_event('cowrie.login.success', {'username': 'root'}),  # No password
        create_mock_event('cowrie.login.failed', {'username': 'admin', 'password': None}),  # Null password
        create_mock_event('cowrie.login.success', {'username': 'root', 'password': 'valid'}),
    ]
    
    results = password_extractor.extract_from_events(events)
    
    assert len(results) == 1
    assert results[0]['password'] == 'valid'


def test_skip_events_without_payload(password_extractor):
    """Test that events without payload are skipped."""
    event = Mock(spec=RawEvent)
    event.event_type = 'cowrie.login.success'
    event.payload = None
    event.event_timestamp = "2025-10-10T10:00:00Z"
    
    results = password_extractor.extract_from_events([event])
    
    assert len(results) == 0


def test_password_sha256_hash_correct(password_extractor):
    """Test that SHA-256 hash is calculated correctly."""
    test_password = "testpassword123"
    expected_hash = hashlib.sha256(test_password.encode('utf-8')).hexdigest()
    
    events = [
        create_mock_event(
            'cowrie.login.success',
            {'username': 'root', 'password': test_password}
        )
    ]
    
    results = password_extractor.extract_from_events(events)
    
    assert results[0]['password_sha256'] == expected_hash


def test_extract_with_missing_username(password_extractor):
    """Test extraction when username is missing."""
    events = [
        create_mock_event(
            'cowrie.login.success',
            {'password': 'password123'}  # No username
        )
    ]
    
    results = password_extractor.extract_from_events(events)
    
    assert len(results) == 1
    assert results[0]['password'] == 'password123'
    assert results[0]['username'] == ''  # Default empty string


def test_extract_unique_passwords(password_extractor):
    """Test extracting unique passwords from events."""
    events = [
        create_mock_event('cowrie.login.failed', {'username': 'root', 'password': 'pass1'}),
        create_mock_event('cowrie.login.failed', {'username': 'root', 'password': 'pass2'}),
        create_mock_event('cowrie.login.failed', {'username': 'admin', 'password': 'pass1'}),  # Duplicate
        create_mock_event('cowrie.login.success', {'username': 'root', 'password': 'pass3'}),
    ]
    
    unique_passwords = password_extractor.extract_unique_passwords(events)
    
    assert len(unique_passwords) == 3
    assert 'pass1' in unique_passwords
    assert 'pass2' in unique_passwords
    assert 'pass3' in unique_passwords


def test_extract_unique_passwords_empty(password_extractor):
    """Test extracting unique passwords from empty events."""
    events = []
    
    unique_passwords = password_extractor.extract_unique_passwords(events)
    
    assert len(unique_passwords) == 0


def test_event_type_preserved(password_extractor):
    """Test that event_type is preserved in results."""
    events = [
        create_mock_event('cowrie.login.success', {'username': 'root', 'password': 'pass1'}),
        create_mock_event('cowrie.login.failed', {'username': 'admin', 'password': 'pass2'}),
    ]
    
    results = password_extractor.extract_from_events(events)
    
    assert results[0]['event_type'] == 'cowrie.login.success'
    assert results[1]['event_type'] == 'cowrie.login.failed'


def test_timestamp_preserved(password_extractor):
    """Test that timestamp is preserved in results."""
    test_timestamp = "2025-09-15T14:30:00Z"
    event = Mock(spec=RawEvent)
    event.event_type = 'cowrie.login.success'
    event.payload = {'username': 'root', 'password': 'pass123'}
    event.event_timestamp = test_timestamp
    
    results = password_extractor.extract_from_events([event])
    
    assert results[0]['timestamp'] == test_timestamp


def test_handles_non_string_password(password_extractor):
    """Test that non-string passwords are skipped."""
    events = [
        create_mock_event('cowrie.login.success', {'username': 'root', 'password': 12345}),  # Integer
        create_mock_event('cowrie.login.success', {'username': 'root', 'password': ['pass']}),  # List
        create_mock_event('cowrie.login.success', {'username': 'root', 'password': 'validpass'}),
    ]
    
    results = password_extractor.extract_from_events(events)
    
    # Only the valid string password should be extracted
    assert len(results) == 1
    assert results[0]['password'] == 'validpass'


def test_empty_events_list(password_extractor):
    """Test extraction from empty events list."""
    results = password_extractor.extract_from_events([])
    
    assert len(results) == 0
    assert isinstance(results, list)

