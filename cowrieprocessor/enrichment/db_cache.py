"""Database-backed cache layer for enrichment data (L2 tier).

This module implements the database cache layer that sits between Redis L1 cache
and filesystem L3 fallback in the hybrid caching architecture:

    Redis L1 → Database L2 → Filesystem L3 → API

The database cache provides:
- Persistent storage with ACID guarantees
- Automatic TTL-based expiration
- JSONB support for efficient querying (PostgreSQL)
- Thread-safe UPSERT operations
- Graceful degradation on failure

Typical TTL: 30 days (configurable per service)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from cowrieprocessor.db.models import EnrichmentCache

LOGGER = logging.getLogger(__name__)

# Default TTL: 30 days
DEFAULT_TTL_SECONDS = 30 * 24 * 60 * 60

# Service-specific TTLs (in seconds)
SERVICE_TTLS = {
    "virustotal": 30 * 24 * 60 * 60,  # 30 days
    "dshield": 7 * 24 * 60 * 60,  # 7 days
    "urlhaus": 3 * 24 * 60 * 60,  # 3 days
    "spur": 7 * 24 * 60 * 60,  # 7 days
    "hibp": 90 * 24 * 60 * 60,  # 90 days
}


class DatabaseCache:
    """Database-backed cache for enrichment data.

    This class provides CRUD operations for the enrichment_cache table,
    implementing the L2 cache tier in the hybrid caching architecture.

    Features:
    - Atomic UPSERT operations for cache updates
    - Automatic TTL calculation and expiration
    - JSON/JSONB storage (PostgreSQL-optimized)
    - Thread-safe operations via SQLAlchemy sessions
    - Graceful error handling with fallback

    Example:
        >>> from cowrieprocessor.db.engine import get_engine
        >>> engine = get_engine("postgresql://...")
        >>> cache = DatabaseCache(engine)
        >>>
        >>> # Store data
        >>> cache.set("virustotal", "abc123", {"malicious": True})
        >>>
        >>> # Retrieve data
        >>> data = cache.get("virustotal", "abc123")
        >>> print(data)  # {"malicious": True}
        >>>
        >>> # Cleanup expired entries
        >>> deleted = cache.cleanup_expired()
        >>> print(f"Deleted {deleted} expired entries")
    """

    def __init__(self, engine: Engine, ttl_seconds: Optional[int] = None) -> None:
        """Initialize database cache with SQLAlchemy engine.

        Args:
            engine: SQLAlchemy engine for database connections
            ttl_seconds: Default TTL in seconds (default: 30 days)
        """
        self.engine = engine
        self.default_ttl = ttl_seconds or DEFAULT_TTL_SECONDS
        self.dialect_name = engine.dialect.name
        LOGGER.info(
            f"DatabaseCache initialized with {self.dialect_name} backend, default TTL: {self.default_ttl // 86400} days"
        )

    def __enter__(self) -> DatabaseCache:
        """Support context manager protocol for resource cleanup."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Clean up database resources on context manager exit."""
        self.close()

    def close(self) -> None:
        """Close database engine and dispose of connection pool.

        This should be called when the cache is no longer needed to ensure
        proper cleanup of database connections.
        """
        try:
            self.engine.dispose()
            LOGGER.debug("DatabaseCache resources cleaned up")
        except Exception as e:
            LOGGER.warning(f"Error during DatabaseCache cleanup: {e}")

    def get(self, service: str, cache_key: str) -> Optional[dict[str, Any]]:
        """Retrieve cached data for the given service and key.

        Args:
            service: Service name (e.g., "virustotal", "dshield")
            cache_key: Cache key (hash, IP address, etc.)

        Returns:
            Cached data as dictionary, or None if not found/expired
        """
        try:
            with Session(self.engine) as session:
                stmt = select(EnrichmentCache).where(
                    EnrichmentCache.service == service,
                    EnrichmentCache.cache_key == cache_key,
                )
                result = session.execute(stmt).scalar_one_or_none()

                if result is None:
                    return None

                # Check expiration
                now = datetime.now(timezone.utc)
                # Handle both naive and timezone-aware datetimes (SQLite vs PostgreSQL)
                expires_at = result.expires_at
                if expires_at.tzinfo is None:
                    # Naive datetime from SQLite - assume UTC
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at < now:
                    # Entry expired, delete it
                    session.delete(result)
                    session.commit()
                    LOGGER.debug(f"Expired cache entry deleted: {service}/{cache_key}")
                    return None

                # Return cached value
                LOGGER.debug(f"Cache hit: {service}/{cache_key}")
                return result.cache_value  # type: ignore[no-any-return]

        except SQLAlchemyError as e:
            LOGGER.error(f"Database cache get error: {e}", exc_info=True)
            return None

    def set(
        self,
        service: str,
        cache_key: str,
        cache_value: dict[str, Any],
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """Store data in cache with automatic expiration.

        Uses UPSERT (INSERT ... ON CONFLICT) for atomic updates.

        Args:
            service: Service name (e.g., "virustotal", "dshield")
            cache_key: Cache key (hash, IP address, etc.)
            cache_value: Data to cache (must be JSON-serializable)
            ttl_seconds: Override default TTL (optional)

        Returns:
            True if successful, False on error
        """
        try:
            ttl = ttl_seconds or SERVICE_TTLS.get(service, self.default_ttl)
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=ttl)

            with Session(self.engine) as session:
                if self.dialect_name == "postgresql":
                    # PostgreSQL: Use INSERT ... ON CONFLICT for atomic UPSERT
                    stmt = pg_insert(EnrichmentCache).values(
                        service=service,
                        cache_key=cache_key,
                        cache_value=cache_value,
                        created_at=now,
                        expires_at=expires_at,
                    )
                    stmt = stmt.on_conflict_do_update(
                        constraint="uq_enrichment_cache_service_key",
                        set_={
                            "cache_value": cache_value,
                            "created_at": now,
                            "expires_at": expires_at,
                        },
                    )
                    session.execute(stmt)
                else:
                    # SQLite: Use merge (less efficient but works)
                    existing = session.execute(
                        select(EnrichmentCache).where(
                            EnrichmentCache.service == service,
                            EnrichmentCache.cache_key == cache_key,
                        )
                    ).scalar_one_or_none()

                    if existing:
                        existing.cache_value = cache_value
                        existing.created_at = now
                        existing.expires_at = expires_at
                    else:
                        entry = EnrichmentCache(
                            service=service,
                            cache_key=cache_key,
                            cache_value=cache_value,
                            created_at=now,
                            expires_at=expires_at,
                        )
                        session.add(entry)

                session.commit()
                LOGGER.debug(f"Cache stored: {service}/{cache_key} (expires in {ttl // 86400} days)")
                return True

        except SQLAlchemyError as e:
            LOGGER.error(f"Database cache set error: {e}", exc_info=True)
            return False

    def delete(self, service: str, cache_key: str) -> bool:
        """Delete a specific cache entry.

        Args:
            service: Service name
            cache_key: Cache key

        Returns:
            True if deleted, False if not found or error
        """
        try:
            with Session(self.engine) as session:
                stmt = delete(EnrichmentCache).where(
                    EnrichmentCache.service == service,
                    EnrichmentCache.cache_key == cache_key,
                )
                result = session.execute(stmt)
                session.commit()
                rowcount = result.rowcount
                deleted = bool(rowcount > 0 if rowcount is not None else False)
                if deleted:
                    LOGGER.debug(f"Cache entry deleted: {service}/{cache_key}")
                return deleted

        except SQLAlchemyError as e:
            LOGGER.error(f"Database cache delete error: {e}", exc_info=True)
            return False

    def cleanup_expired(self, dry_run: bool = False) -> int:
        """Remove expired cache entries from the database.

        This method should be run periodically (e.g., via cron) to clean up
        expired entries and reclaim storage space.

        Args:
            dry_run: If True, only count expired entries without deleting

        Returns:
            Number of expired entries deleted (or counted in dry_run mode)
        """
        try:
            # Use naive datetime for SQLite, timezone-aware for PostgreSQL
            if self.dialect_name == "sqlite":
                now = datetime.now()
            else:
                now = datetime.now(timezone.utc)

            with Session(self.engine) as session:
                # Count expired entries
                count_stmt = select(EnrichmentCache).where(EnrichmentCache.expires_at < now)
                expired_entries = session.execute(count_stmt).scalars().all()
                count = len(expired_entries)

                if count == 0:
                    LOGGER.info("No expired cache entries to clean up")
                    return 0

                if dry_run:
                    LOGGER.info(f"DRY RUN: Would delete {count} expired cache entries")
                    return count

                # Delete expired entries
                delete_stmt = delete(EnrichmentCache).where(EnrichmentCache.expires_at < now)
                result = session.execute(delete_stmt)
                session.commit()

                rowcount = result.rowcount
                deleted = int(rowcount if rowcount is not None else 0)
                LOGGER.info(f"Deleted {deleted} expired cache entries")
                return deleted

        except SQLAlchemyError as e:
            LOGGER.error(f"Database cache cleanup error: {e}", exc_info=True)
            return 0

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics:
            - total_entries: Total number of cached entries
            - expired_entries: Number of expired entries
            - services: Per-service entry counts
        """
        try:
            with Session(self.engine) as session:
                from sqlalchemy import func

                # Total entries (use COUNT instead of loading all rows)
                total_stmt = select(func.count()).select_from(EnrichmentCache)
                total = session.execute(total_stmt).scalar() or 0

                # Expired entries (use COUNT instead of loading all rows)
                if self.dialect_name == "sqlite":
                    now = datetime.now()
                else:
                    now = datetime.now(timezone.utc)
                expired_stmt = select(func.count()).select_from(EnrichmentCache).where(EnrichmentCache.expires_at < now)
                expired = session.execute(expired_stmt).scalar() or 0

                # Per-service counts (use SQL GROUP BY instead of Python aggregation)
                services_stmt = select(EnrichmentCache.service, func.count(EnrichmentCache.id)).group_by(
                    EnrichmentCache.service
                )
                services_data = session.execute(services_stmt).all()
                service_counts = {service: count for service, count in services_data}

                return {
                    "total_entries": total,
                    "expired_entries": expired,
                    "active_entries": total - expired,
                    "services": service_counts,
                }

        except SQLAlchemyError as e:
            LOGGER.error(f"Database cache stats error: {e}", exc_info=True)
            return {
                "total_entries": 0,
                "expired_entries": 0,
                "active_entries": 0,
                "services": {},
            }


__all__ = ["DatabaseCache", "DEFAULT_TTL_SECONDS", "SERVICE_TTLS"]
