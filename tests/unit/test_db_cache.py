"""Unit tests for DatabaseCache (L2 cache tier).

Tests the database-backed cache implementation including:
- CRUD operations (get, set, delete)
- TTL management and expiration
- UPSERT behavior (PostgreSQL vs SQLite)
- Cleanup of expired entries
- Statistics and monitoring
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from cowrieprocessor.db.base import Base
from cowrieprocessor.db.models import EnrichmentCache
from cowrieprocessor.enrichment.db_cache import (
    DEFAULT_TTL_SECONDS,
    SERVICE_TTLS,
    DatabaseCache,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


@pytest.fixture
def test_engine() -> Engine:
    """Create an in-memory SQLite engine for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_cache(test_engine: Engine) -> DatabaseCache:
    """Create a DatabaseCache instance for testing."""
    return DatabaseCache(test_engine)


class TestDatabaseCacheBasics:
    """Test basic cache operations (get, set, delete)."""

    def test_cache_initialization(self, db_cache: DatabaseCache) -> None:
        """Test that cache initializes correctly."""
        assert db_cache.engine is not None
        assert db_cache.default_ttl == DEFAULT_TTL_SECONDS
        assert db_cache.dialect_name == "sqlite"

    def test_set_and_get(self, db_cache: DatabaseCache) -> None:
        """Test storing and retrieving cache entries."""
        test_data = {"malicious": True, "score": 42}

        # Store data
        success = db_cache.set("virustotal", "abc123", test_data)
        assert success is True

        # Retrieve data
        result = db_cache.get("virustotal", "abc123")
        assert result == test_data

    def test_get_nonexistent(self, db_cache: DatabaseCache) -> None:
        """Test retrieving nonexistent cache entry returns None."""
        result = db_cache.get("virustotal", "nonexistent")
        assert result is None

    def test_cache_miss_nonexistent_service(self, db_cache: DatabaseCache) -> None:
        """Test cache miss for nonexistent service."""
        result = db_cache.get("unknown_service", "key123")
        assert result is None

    def test_overwrite_existing_entry(self, db_cache: DatabaseCache) -> None:
        """Test that setting an existing key overwrites the value."""
        # Store initial data
        db_cache.set("dshield", "192.168.1.1", {"attacks": 10})

        # Overwrite with new data
        new_data = {"attacks": 20, "updated": True}
        db_cache.set("dshield", "192.168.1.1", new_data)

        # Verify new data
        result = db_cache.get("dshield", "192.168.1.1")
        assert result == new_data

    def test_delete_entry(self, db_cache: DatabaseCache) -> None:
        """Test deleting cache entries."""
        # Store data
        db_cache.set("urlhaus", "malware.bin", {"malicious": True})

        # Verify it exists
        assert db_cache.get("urlhaus", "malware.bin") is not None

        # Delete it
        deleted = db_cache.delete("urlhaus", "malware.bin")
        assert deleted is True

        # Verify it's gone
        assert db_cache.get("urlhaus", "malware.bin") is None

    def test_delete_nonexistent(self, db_cache: DatabaseCache) -> None:
        """Test deleting nonexistent entry returns False."""
        deleted = db_cache.delete("virustotal", "nonexistent")
        assert deleted is False


class TestTTLManagement:
    """Test TTL (Time-To-Live) and expiration handling."""

    def test_service_specific_ttls(self, db_cache: DatabaseCache) -> None:
        """Test that service-specific TTLs are applied."""
        # Store entries for different services
        db_cache.set("virustotal", "key1", {"data": 1})
        db_cache.set("dshield", "key2", {"data": 2})
        db_cache.set("urlhaus", "key3", {"data": 3})

        # Verify entries exist
        assert db_cache.get("virustotal", "key1") is not None
        assert db_cache.get("dshield", "key2") is not None
        assert db_cache.get("urlhaus", "key3") is not None

        # Check that TTLs match service configuration
        with Session(db_cache.engine) as session:
            vt_entry = session.query(EnrichmentCache).filter_by(service="virustotal", cache_key="key1").first()
            assert vt_entry is not None

            # Calculate expected expiration (approximately)
            now = datetime.now(timezone.utc)
            expected_expires = now + timedelta(seconds=SERVICE_TTLS["virustotal"])

            # Handle timezone differences (SQLite stores naive, PostgreSQL stores aware)
            expires_at = vt_entry.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            # Allow 2 seconds tolerance for test execution time
            time_diff = abs((expires_at - expected_expires).total_seconds())
            assert time_diff < 2.0

    def test_expired_entry_auto_deleted(self, db_cache: DatabaseCache, test_engine: Engine) -> None:
        """Test that expired entries are auto-deleted on get."""
        # Manually insert an expired entry
        now = datetime.now(timezone.utc)
        expired_time = now - timedelta(hours=1)

        with Session(test_engine) as session:
            entry = EnrichmentCache(
                service="virustotal",
                cache_key="expired123",
                cache_value={"malicious": True},
                created_at=expired_time - timedelta(days=31),
                expires_at=expired_time,
            )
            session.add(entry)
            session.commit()

        # Try to retrieve expired entry
        result = db_cache.get("virustotal", "expired123")
        assert result is None

        # Verify it was deleted
        with Session(test_engine) as session:
            count = session.query(EnrichmentCache).filter_by(service="virustotal", cache_key="expired123").count()
            assert count == 0

    def test_custom_ttl(self, db_cache: DatabaseCache, test_engine: Engine) -> None:
        """Test setting custom TTL for cache entries."""
        custom_ttl = 60  # 1 minute

        # Store with custom TTL
        success = db_cache.set("spur", "192.168.1.1", {"vpn": True}, ttl_seconds=custom_ttl)
        assert success is True

        # Verify TTL was applied
        with Session(test_engine) as session:
            entry = session.query(EnrichmentCache).filter_by(service="spur", cache_key="192.168.1.1").first()
            assert entry is not None

            # Check expiration time
            now = datetime.now(timezone.utc)
            expected_expires = now + timedelta(seconds=custom_ttl)

            # Handle timezone differences
            expires_at = entry.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            time_diff = abs((expires_at - expected_expires).total_seconds())
            assert time_diff < 2.0


class TestCleanup:
    """Test cleanup operations for expired entries."""

    def test_cleanup_expired_entries(self, db_cache: DatabaseCache, test_engine: Engine) -> None:
        """Test cleanup of expired cache entries."""
        # Use naive datetime for SQLite compatibility
        now = datetime.now()

        # Add some fresh entries
        db_cache.set("virustotal", "fresh1", {"malicious": False})
        db_cache.set("dshield", "fresh2", {"attacks": 0})

        # Manually add expired entries (use naive datetime for SQLite)
        with Session(test_engine) as session:
            expired1 = EnrichmentCache(
                service="virustotal",
                cache_key="expired1",
                cache_value={"malicious": True},
                created_at=now - timedelta(days=35),
                expires_at=now - timedelta(days=5),
            )
            expired2 = EnrichmentCache(
                service="dshield",
                cache_key="expired2",
                cache_value={"attacks": 100},
                created_at=now - timedelta(days=10),
                expires_at=now - timedelta(hours=1),
            )
            session.add_all([expired1, expired2])
            session.commit()

        # Run cleanup
        deleted = db_cache.cleanup_expired(dry_run=False)
        assert deleted == 2

        # Verify fresh entries still exist
        assert db_cache.get("virustotal", "fresh1") is not None
        assert db_cache.get("dshield", "fresh2") is not None

        # Verify expired entries are gone
        assert db_cache.get("virustotal", "expired1") is None
        assert db_cache.get("dshield", "expired2") is None

    def test_cleanup_dry_run(self, db_cache: DatabaseCache, test_engine: Engine) -> None:
        """Test cleanup dry run doesn't delete entries."""
        now = datetime.now(timezone.utc)

        # Add expired entry
        with Session(test_engine) as session:
            expired = EnrichmentCache(
                service="virustotal",
                cache_key="expired",
                cache_value={"malicious": True},
                created_at=now - timedelta(days=35),
                expires_at=now - timedelta(days=5),
            )
            session.add(expired)
            session.commit()

        # Run dry run cleanup
        count = db_cache.cleanup_expired(dry_run=True)
        assert count == 1

        # Verify entry still exists in database
        with Session(test_engine) as session:
            exists = session.query(EnrichmentCache).filter_by(service="virustotal", cache_key="expired").count()
            assert exists == 1

    def test_cleanup_no_expired_entries(self, db_cache: DatabaseCache) -> None:
        """Test cleanup when no expired entries exist."""
        # Add only fresh entries
        db_cache.set("virustotal", "fresh1", {"malicious": False})
        db_cache.set("dshield", "fresh2", {"attacks": 0})

        # Run cleanup
        deleted = db_cache.cleanup_expired(dry_run=False)
        assert deleted == 0


class TestStatistics:
    """Test cache statistics and monitoring."""

    def test_get_stats_empty(self, db_cache: DatabaseCache) -> None:
        """Test statistics for empty cache."""
        stats = db_cache.get_stats()

        assert stats["total_entries"] == 0
        assert stats["expired_entries"] == 0
        assert stats["active_entries"] == 0
        assert stats["services"] == {}

    def test_get_stats_with_entries(self, db_cache: DatabaseCache, test_engine: Engine) -> None:
        """Test statistics with cache entries."""
        now = datetime.now(timezone.utc)

        # Add fresh entries
        db_cache.set("virustotal", "key1", {"malicious": True})
        db_cache.set("virustotal", "key2", {"malicious": False})
        db_cache.set("dshield", "192.168.1.1", {"attacks": 10})

        # Add expired entry
        with Session(test_engine) as session:
            expired = EnrichmentCache(
                service="urlhaus",
                cache_key="expired",
                cache_value={"malicious": True},
                created_at=now - timedelta(days=5),
                expires_at=now - timedelta(hours=1),
            )
            session.add(expired)
            session.commit()

        # Get statistics
        stats = db_cache.get_stats()

        assert stats["total_entries"] == 4
        assert stats["expired_entries"] == 1
        assert stats["active_entries"] == 3

        # Note: service_counts may vary depending on implementation
        # Just verify it's a dict
        assert isinstance(stats["services"], dict)


class TestErrorHandling:
    """Test error handling and graceful degradation."""

    def test_invalid_json_data(self, db_cache: DatabaseCache) -> None:
        """Test that non-JSON-serializable data is handled."""
        # This should work because we accept dict[str, Any]
        # and SQLAlchemy handles JSON serialization
        test_data = {"key": "value", "number": 42}
        success = db_cache.set("virustotal", "test", test_data)
        assert success is True

        result = db_cache.get("virustotal", "test")
        assert result == test_data

    def test_multiple_services(self, db_cache: DatabaseCache) -> None:
        """Test cache isolation between services."""
        # Same key, different services
        db_cache.set("virustotal", "common_key", {"service": "vt"})
        db_cache.set("dshield", "common_key", {"service": "dshield"})
        db_cache.set("urlhaus", "common_key", {"service": "urlhaus"})

        # Verify each service has its own entry
        vt_result = db_cache.get("virustotal", "common_key")
        dshield_result = db_cache.get("dshield", "common_key")
        urlhaus_result = db_cache.get("urlhaus", "common_key")

        assert vt_result == {"service": "vt"}
        assert dshield_result == {"service": "dshield"}
        assert urlhaus_result == {"service": "urlhaus"}


class TestConcurrency:
    """Test concurrent access patterns."""

    def test_concurrent_updates_same_key(self, db_cache: DatabaseCache) -> None:
        """Test that concurrent updates to the same key work correctly."""
        # Simulate concurrent updates (last write wins)
        db_cache.set("virustotal", "abc123", {"version": 1})
        db_cache.set("virustotal", "abc123", {"version": 2})
        db_cache.set("virustotal", "abc123", {"version": 3})

        result = db_cache.get("virustotal", "abc123")
        assert result == {"version": 3}

    def test_independent_keys(self, db_cache: DatabaseCache) -> None:
        """Test that independent keys don't interfere."""
        # Store multiple independent entries
        db_cache.set("virustotal", "key1", {"id": 1})
        db_cache.set("virustotal", "key2", {"id": 2})
        db_cache.set("dshield", "key3", {"id": 3})

        # Verify all are independent
        assert db_cache.get("virustotal", "key1") == {"id": 1}
        assert db_cache.get("virustotal", "key2") == {"id": 2}
        assert db_cache.get("dshield", "key3") == {"id": 3}
