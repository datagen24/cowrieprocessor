"""Shared pytest fixtures for Cowrie processor tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Generator, List
from unittest.mock import Mock

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from cowrieprocessor.db.base import Base
from cowrieprocessor.db.models import (
    RawEvent,
)
from cowrieprocessor.settings import DatabaseSettings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================================
# Event Fixtures
# ============================================================================


@pytest.fixture
def sample_cowrie_events() -> list[dict[str, str]]:
    """Provide sample Cowrie events loaded from disk.

    Returns:
        list[dict[str, str]]: Parsed event dictionaries for smoke testing utilities.
    """
    fixture_path = Path(__file__).parent / "fixtures" / "sample_events.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    return list(data)


@pytest.fixture
def cowrie_login_event() -> Dict[str, Any]:
    """Sample cowrie.login.success event."""
    return {
        "session": "c0ffee-01",
        "eventid": "cowrie.login.success",
        "username": "root",
        "password": "password123",
        "src_ip": "203.0.113.10",
        "timestamp": "2024-09-28T12:00:05Z",
    }


@pytest.fixture
def cowrie_command_event() -> Dict[str, Any]:
    """Sample cowrie.command.input event."""
    return {
        "session": "c0ffee-01",
        "eventid": "cowrie.command.input",
        "command": "ls -la /tmp",
        "timestamp": "2024-09-28T12:00:06Z",
    }


@pytest.fixture
def cowrie_file_download_event() -> Dict[str, Any]:
    """Sample cowrie.session.file_download event."""
    return {
        "session": "c0ffee-01",
        "eventid": "cowrie.session.file_download",
        "url": "http://malicious.example.com/malware.bin",
        "shasum": "deadbeef1234567890abcdef1234567890abcdef12",
        "destfile": "/tmp/malware.bin",
        "src_ip": "203.0.113.10",
        "timestamp": "2024-09-28T12:00:07Z",
    }


@pytest.fixture
def malformed_cowrie_event() -> Dict[str, Any]:
    """Malformed event for error path testing."""
    return {
        "session": "invalid-session",
        "eventid": "invalid.event.type",
        "timestamp": "not-a-timestamp",
        "missing_required_field": True,
    }


@pytest.fixture
def orphan_cowrie_event() -> Dict[str, Any]:
    """Event without session for edge case testing."""
    return {
        "eventid": "cowrie.system.info",
        "message": "orphan event without session",
        "timestamp": "2024-09-28T14:00:01Z",
    }


# ============================================================================
# Database Fixtures
# ============================================================================


@pytest.fixture
def db_engine(tmp_path: Path) -> Generator[Engine, None, None]:
    """Provide a SQLite database engine for testing.

    Args:
        tmp_path: Pytest temporary directory fixture

    Yields:
        Engine: SQLAlchemy engine connected to temporary SQLite database
    """
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")

    # Create all tables
    Base.metadata.create_all(engine)

    yield engine

    # Cleanup
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Generator[Session, None, None]:
    """Provide a database session with proper transaction cleanup.

    Args:
        db_engine: Database engine fixture

    Yields:
        Session: SQLAlchemy session with automatic rollback on test completion
    """
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()

    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture
def sample_db_with_events(db_session: Session, sample_cowrie_events: List[Dict[str, Any]]) -> Session:
    """Pre-populated database with sample Cowrie events.

    Args:
        db_session: Database session fixture
        sample_cowrie_events: Sample event data

    Returns:
        Session: Database session with sample data inserted
    """
    # Insert sample events
    for event_data in sample_cowrie_events:
        event = RawEvent(
            session_id=event_data.get("session", ""),
            event_id=event_data["eventid"],
            timestamp=event_data["timestamp"],
            payload=event_data,
        )
        db_session.add(event)

    db_session.commit()
    return db_session


@pytest.fixture
def database_settings() -> DatabaseSettings:
    """Provide default database settings for testing."""
    return DatabaseSettings(
        url="sqlite:///:memory:",
        echo=False,
        sqlite_wal=True,
        sqlite_cache_size=-64000,
        sqlite_synchronous="NORMAL",
    )


@pytest.fixture
def postgresql_database_settings() -> DatabaseSettings:
    """Provide PostgreSQL database settings for testing (requires TEST_POSTGRESQL_URL)."""
    return DatabaseSettings(
        url="postgresql://localhost/cowrie_test",
        echo=False,
        pool_size=5,
        pool_timeout=30,
    )


# ============================================================================
# Mock API Fixtures
# ============================================================================


@pytest.fixture
def mock_virustotal_response() -> Dict[str, Any]:
    """Mocked VirusTotal API response."""
    return {
        "data": {
            "attributes": {
                "last_analysis_stats": {
                    "malicious": 5,
                    "suspicious": 2,
                    "undetected": 3,
                    "harmless": 90,
                },
                "reputation": -50,
                "md5": "deadbeef1234567890abcdef1234567890",
                "sha1": "deadbeef1234567890abcdef1234567890abcdef12",
                "sha256": "deadbeef1234567890abcdef1234567890abcdef1234567890abcdef1234567890ab",
            }
        }
    }


@pytest.fixture
def mock_virustotal_error_response() -> Dict[str, Any]:
    """Mocked VirusTotal API error response."""
    return {
        "error": {
            "code": "NotFoundError",
            "message": "Requested resource not found",
        }
    }


@pytest.fixture
def mock_spur_response() -> Dict[str, Any]:
    """Mocked SPUR API response for IP enrichment."""
    return {
        "ip": "203.0.113.10",
        "country": "US",
        "asn": "AS12345",
        "organization": "Example Corp",
        "threat_score": 75,
        "tags": ["malicious", "botnet"],
    }


@pytest.fixture
def mock_enrichment_service() -> Mock:
    """Mocked enrichment service for testing."""
    service = Mock()
    service.enrich_ip.return_value = {
        "country": "US",
        "asn": "AS12345",
        "threat_score": 75,
    }
    service.enrich_file.return_value = {
        "virustotal": {
            "malicious": 5,
            "suspicious": 2,
            "reputation": -50,
        }
    }
    service.enrich_password.return_value = {
        "hibp_breach_count": 3,
        "pwned": True,
    }
    return service


# ============================================================================
# Test Data Fixtures
# ============================================================================


@pytest.fixture
def sample_session_summary() -> Dict[str, Any]:
    """Sample session summary for testing."""
    return {
        "session_id": "c0ffee-01",
        "first_event_at": "2024-09-28T12:00:00Z",
        "last_event_at": "2024-09-28T12:00:10Z",
        "event_count": 5,
        "command_count": 2,
        "login_attempts": 1,
        "file_downloads": 2,
        "src_ip": "203.0.113.10",
        "enrichment": {
            "session": {
                "203.0.113.10": {
                    "spur": {
                        "country": "US",
                        "asn": "AS12345",
                        "threat_score": 75,
                    }
                }
            }
        },
    }


@pytest.fixture
def sample_threat_detection_result() -> Dict[str, Any]:
    """Sample threat detection result for testing."""
    return {
        "session_id": "c0ffee-01",
        "snowshoe_score": 85,
        "longtail_score": 70,
        "botnet_score": 90,
        "overall_risk": "high",
        "detection_details": {
            "snowshoe": {
                "detected": True,
                "confidence": 0.85,
                "patterns": ["rapid_commands", "common_passwords"],
            },
            "longtail": {
                "detected": True,
                "confidence": 0.70,
                "indicators": ["suspicious_commands", "file_downloads"],
            },
            "botnet": {
                "detected": True,
                "confidence": 0.90,
                "coordination_indicators": ["timing_patterns", "command_sequences"],
            },
        },
    }


# ============================================================================
# Utility Fixtures
# ============================================================================


@pytest.fixture
def temp_cache_dir(tmp_path: Path) -> Path:
    """Provide a temporary cache directory for testing."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    return cache_dir


@pytest.fixture
def mock_file_system(tmp_path: Path) -> Path:
    """Provide a mock file system structure for testing."""
    # Create directory structure
    (tmp_path / "logs").mkdir()
    (tmp_path / "cache").mkdir()
    (tmp_path / "output").mkdir()

    # Create sample log files
    log_file = tmp_path / "logs" / "cowrie.log"
    log_file.write_text("""{"session": "test-01", "eventid": "cowrie.session.connect", "timestamp": "2024-01-01T00:00:00Z"}
{"session": "test-01", "eventid": "cowrie.login.success", "username": "root", "timestamp": "2024-01-01T00:00:01Z"}
""")

    return tmp_path
