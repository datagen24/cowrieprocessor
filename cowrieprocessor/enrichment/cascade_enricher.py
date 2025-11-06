"""Multi-source IP enrichment orchestrator with intelligent cascade logic.

This module implements Phase 2d of ADR-008: Multi-Source Orchestration for ASN/Geo enrichment.
It coordinates three enrichment sources in a sequential cascade pattern with early termination:

1. MaxMind GeoLite2 (offline, 95% coverage, weekly refresh)
2. Team Cymru whois (online, 89% coverage, 90-day TTL)
3. GreyNoise Community API (online, 93% coverage, 7-day TTL)

Design Principles:
- Early termination: Stop when primary source succeeds (MaxMind covers 99%)
- Source priority: Geo (MaxMind only), ASN (MaxMind > Cymru), Scanner (GreyNoise only)
- Separate timestamps: enrichment_ts (MaxMind/Cymru), scanner_ts (GreyNoise)
- Graceful degradation: Continue if GreyNoise quota exhausted
- Cache-first: Always check ip_inventory before external lookups

Example:
    >>> from cowrieprocessor.enrichment import MaxMindClient, CymruClient, GreyNoiseClient
    >>> from cowrieprocessor.db.engine import get_engine
    >>> from sqlalchemy.orm import Session
    >>>
    >>> engine = get_engine("sqlite:////path/to/db.sqlite")
    >>> with Session(engine) as session:
    ...     cascade = CascadeEnricher(
    ...         maxmind=MaxMindClient(),
    ...         cymru=CymruClient(),
    ...         greynoise=GreyNoiseClient(api_key="..."),
    ...         session=session,
    ...     )
    ...     result = cascade.enrich_ip("1.2.3.4")
    ...     print(f"Country: {result.geo_country}, ASN: {result.current_asn}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, attributes

from cowrieprocessor.db.models import IPInventory, SessionSummary
from cowrieprocessor.enrichment.cymru_client import CymruClient, CymruResult
from cowrieprocessor.enrichment.greynoise_client import GreyNoiseClient, GreyNoiseResult
from cowrieprocessor.enrichment.maxmind_client import MaxMindClient, MaxMindResult

logger = logging.getLogger(__name__)


@dataclass
class CascadeStats:
    """Statistics for cascade enrichment operations.

    Attributes:
        total_ips: Total number of IPs processed
        cache_hits: Number of IPs found in cache with fresh data
        maxmind_hits: Number of successful MaxMind lookups
        cymru_hits: Number of successful Cymru lookups
        greynoise_hits: Number of successful GreyNoise lookups
        errors: Number of errors encountered during enrichment
    """

    total_ips: int = 0
    cache_hits: int = 0
    maxmind_hits: int = 0
    cymru_hits: int = 0
    greynoise_hits: int = 0
    errors: int = 0


class CascadeEnricher:
    """Orchestrate sequential multi-source IP enrichment with early termination.

    This class coordinates three enrichment sources in a cascade pattern:
    1. MaxMind GeoLite2 (offline, always attempted first)
    2. Team Cymru (online, fallback for missing ASN data)
    3. GreyNoise (online, scanner classification)

    The cascade implements intelligent early termination: if MaxMind provides
    complete geo + ASN data (99% of cases), we skip Cymru entirely. GreyNoise
    is always attempted separately for scanner classification.

    Attributes:
        maxmind: MaxMind GeoLite2 client for geo/ASN lookups
        cymru: Team Cymru client for ASN fallback
        greynoise: GreyNoise client for scanner classification
        session: SQLAlchemy database session
    """

    def __init__(
        self,
        maxmind: MaxMindClient,
        cymru: CymruClient,
        greynoise: GreyNoiseClient,
        session: Session,
    ) -> None:
        """Initialize cascade enricher with all clients and database session.

        Args:
            maxmind: MaxMind GeoLite2 client (offline database lookups)
            cymru: Team Cymru client (online whois lookups)
            greynoise: GreyNoise Community API client (online scanner checks)
            session: Active SQLAlchemy session for database operations
        """
        self.maxmind = maxmind
        self.cymru = cymru
        self.greynoise = greynoise
        self.session = session
        self._stats = CascadeStats()

    def enrich_ip(self, ip_address: str) -> IPInventory:
        """Sequential cascade enrichment with early termination.

        Enrichment workflow:
        1. Check if IP exists in ip_inventory (cache check)
        2. If cached and fresh (< source TTL), return cached data
        3. If missing or stale:
           a. Try MaxMind (offline, always succeeds or None)
           b. If MaxMind ASN missing, try Cymru (online, 90-day TTL)
           c. Try GreyNoise (online, 7-day TTL, quota-aware)
        4. Update ip_inventory with merged results
        5. Return IPInventory ORM object

        Args:
            ip_address: IPv4 or IPv6 address to enrich

        Returns:
            IPInventory object with enrichment data from all sources

        Raises:
            ValueError: If ip_address is invalid
            RuntimeError: If database operations fail

        Example:
            >>> result = cascade.enrich_ip("8.8.8.8")
            >>> print(f"Country: {result.geo_country}")
            Country: US
            >>> print(f"ASN: {result.current_asn}")
            ASN: 15169
            >>> print(f"Scanner: {result.is_scanner}")
            Scanner: False
        """
        self._stats.total_ips += 1
        now = datetime.now(timezone.utc)

        # Step 1: Check cache
        cached = self.session.query(IPInventory).filter(IPInventory.ip_address == ip_address).first()

        if cached and self._is_fresh(cached):
            logger.debug(f"Cache hit for {ip_address} (fresh data)")
            self._stats.cache_hits += 1
            return cached

        # Step 2: Cascade enrichment
        maxmind_result: MaxMindResult | None = None
        cymru_result: CymruResult | None = None
        greynoise_result: GreyNoiseResult | None = None

        try:
            # Step 2a: Try MaxMind (offline, always first)
            maxmind_result = self.maxmind.lookup_ip(ip_address)
            if maxmind_result:
                logger.debug(f"MaxMind hit for {ip_address}: {maxmind_result.country_code}, ASN {maxmind_result.asn}")
                self._stats.maxmind_hits += 1

            # Step 2b: Cymru fallback if ASN missing
            if not maxmind_result or maxmind_result.asn is None:
                logger.debug(f"ASN missing for {ip_address}, trying Cymru")
                cymru_result = self.cymru.lookup_asn(ip_address)
                if cymru_result and cymru_result.asn:
                    logger.debug(f"Cymru hit for {ip_address}: ASN {cymru_result.asn}")
                    self._stats.cymru_hits += 1

            # Step 2c: GreyNoise for scanner classification (independent)
            try:
                greynoise_result = self.greynoise.lookup_ip(ip_address)
                if greynoise_result:
                    logger.debug(f"GreyNoise hit for {ip_address}: noise={greynoise_result.noise}")
                    self._stats.greynoise_hits += 1
            except Exception as e:
                # Graceful degradation: Continue if GreyNoise quota exhausted
                logger.warning(f"GreyNoise lookup failed for {ip_address}: {e}")

        except Exception as e:
            logger.error(f"Enrichment error for {ip_address}: {e}")
            self._stats.errors += 1
            # Return cached data if available, otherwise create minimal record
            if cached:
                return cached
            return self._create_minimal_inventory(ip_address, now)

        # Step 3: Merge results
        merged = self._merge_results(cached, maxmind_result, cymru_result, greynoise_result, ip_address)

        # Step 4: Update database
        try:
            if cached:
                # Update existing record directly (SQLAlchemy ORM)
                cached.enrichment = merged.enrichment
                cached.enrichment_updated_at = now
                cached.current_asn = merged.current_asn
                cached.asn_last_verified = now
                cached.last_seen = now
                cached.session_count = (cached.session_count or 0) + 1
                self.session.flush()
                return cached
            else:
                # Insert new record
                setattr(merged, "created_at", now)
                setattr(merged, "updated_at", now)
                setattr(merged, "enrichment_updated_at", now)
                setattr(merged, "asn_last_verified", now)
                setattr(merged, "first_seen", now)
                setattr(merged, "last_seen", now)
                setattr(merged, "session_count", 1)
                self.session.add(merged)
                self.session.flush()
                return merged
        except IntegrityError as e:
            # Handle race condition: another thread inserted the IP
            logger.warning(f"Integrity error for {ip_address}, re-querying: {e}")
            self.session.rollback()
            cached = self.session.query(IPInventory).filter(IPInventory.ip_address == ip_address).first()
            if cached:
                return cached
            raise RuntimeError(f"Failed to insert or retrieve IP {ip_address}") from e

    def enrich_session_ips(self, session_id: int) -> dict[str, IPInventory]:
        """Enrich all IPs in a session (source_ip, dest_ip if present).

        Args:
            session_id: Database ID of session to enrich

        Returns:
            Dictionary mapping IP addresses to IPInventory objects

        Raises:
            ValueError: If session_id does not exist
            RuntimeError: If enrichment fails

        Example:
            >>> results = cascade.enrich_session_ips(12345)
            >>> for ip, inventory in results.items():
            ...     print(f"{ip}: {inventory.geo_country}")
            192.0.2.1: US
            203.0.113.1: CN
        """
        # Fetch session
        session_summary = self.session.query(SessionSummary).filter(SessionSummary.session_id == session_id).first()
        if not session_summary:
            raise ValueError(f"Session {session_id} not found")

        results: dict[str, IPInventory] = {}

        # Enrich source IP
        source_ip_str = str(session_summary.source_ip) if session_summary.source_ip else None
        if source_ip_str:
            results[source_ip_str] = self.enrich_ip(source_ip_str)

        # Enrich dest IP if present (not common in Cowrie logs)
        if hasattr(session_summary, "dst_ip") and session_summary.dst_ip:
            results[session_summary.dst_ip] = self.enrich_ip(session_summary.dst_ip)

        return results

    def backfill_missing_asns(self, limit: int = 1000) -> int:
        """Find IPs with NULL asn_number, enrich with Cymru, return count.

        This is useful for backfilling ASN data for IPs that were enriched
        before Cymru integration or where MaxMind had no ASN data.

        Args:
            limit: Maximum number of IPs to backfill per call

        Returns:
            Number of IPs successfully backfilled with ASN data

        Example:
            >>> count = cascade.backfill_missing_asns(limit=500)
            >>> print(f"Backfilled {count} IPs with ASN data")
            Backfilled 347 IPs with ASN data
        """
        # Query IPs with no ASN
        ips_without_asn = self.session.query(IPInventory).filter(IPInventory.current_asn.is_(None)).limit(limit).all()

        backfilled = 0
        for inventory in ips_without_asn:
            try:
                # Try Cymru lookup
                ip_str = str(inventory.ip_address)
                cymru_result = self.cymru.lookup_asn(ip_str)
                if cymru_result and cymru_result.asn:
                    # Update enrichment JSON
                    enrichment: dict[str, dict[str, str | int | None]] = inventory.enrichment or {}
                    enrichment["cymru"] = {
                        "asn": cymru_result.asn,
                        "asn_org": cymru_result.asn_org,
                        "country": cymru_result.country_code,
                        "registry": cymru_result.registry,
                        "prefix": cymru_result.prefix,
                        "allocation_date": cymru_result.allocation_date,
                        "cached_at": cymru_result.cached_at.isoformat(),
                    }
                    setattr(inventory, "enrichment", enrichment)
                    setattr(inventory, "current_asn", cymru_result.asn)
                    setattr(inventory, "asn_last_verified", datetime.now(timezone.utc))
                    setattr(inventory, "enrichment_updated_at", datetime.now(timezone.utc))
                    backfilled += 1
                    logger.debug(f"Backfilled ASN for {inventory.ip_address}: {cymru_result.asn}")
            except Exception as e:
                logger.warning(f"Failed to backfill ASN for {inventory.ip_address}: {e}")
                continue

        self.session.commit()
        logger.info(f"Backfilled {backfilled} IPs with ASN data (limit: {limit})")
        return backfilled

    def refresh_stale_data(self, source: str | None = None, limit: int = 1000) -> dict[str, int]:
        """Refresh stale enrichment data based on source TTLs.

        Finds IPs with stale data and re-enriches them:
        - Cymru: Last enriched >90 days ago
        - GreyNoise: Last enriched >7 days ago

        Args:
            source: Specific source to refresh ("cymru" or "greynoise"), or None for all
            limit: Maximum number of IPs to refresh per source

        Returns:
            Dictionary with counts of refreshed IPs per source

        Example:
            >>> results = cascade.refresh_stale_data(limit=100)
            >>> print(results)
            {'cymru_refreshed': 45, 'greynoise_refreshed': 78}
        """
        now = datetime.now(timezone.utc)
        refreshed: dict[str, int] = {"cymru_refreshed": 0, "greynoise_refreshed": 0}

        # Refresh stale Cymru data (>90 days old)
        if source is None or source == "cymru":
            cymru_cutoff = now - timedelta(days=90)
            # Fetch candidates and filter in Python for cross-database compatibility
            candidates = (
                self.session.query(IPInventory)
                .filter(IPInventory.enrichment_updated_at < cymru_cutoff)
                .limit(limit * 2)  # Over-fetch to account for filtering
                .all()
            )
            stale_cymru = [inv for inv in candidates if inv.enrichment and "cymru" in inv.enrichment][:limit]

            for inventory in stale_cymru:
                try:
                    ip_str = str(inventory.ip_address)
                    cymru_result = self.cymru.lookup_asn(ip_str)
                    if cymru_result:
                        cymru_enrichment: dict[str, dict[str, str | int | None]] = inventory.enrichment or {}
                        cymru_enrichment["cymru"] = {
                            "asn": cymru_result.asn,
                            "asn_org": cymru_result.asn_org,
                            "country": cymru_result.country_code,
                            "registry": cymru_result.registry,
                            "prefix": cymru_result.prefix,
                            "allocation_date": cymru_result.allocation_date,
                            "cached_at": cymru_result.cached_at.isoformat(),
                        }
                        inventory.enrichment = cymru_enrichment
                        attributes.flag_modified(inventory, "enrichment")  # Mark JSON field as modified
                        inventory.enrichment_updated_at = now
                        if cymru_result.asn:
                            inventory.current_asn = cymru_result.asn
                            inventory.asn_last_verified = now
                        refreshed["cymru_refreshed"] += 1
                        self.session.flush()  # Ensure changes are persisted
                except Exception as e:
                    logger.warning(f"Failed to refresh Cymru for {inventory.ip_address}: {e}")
                    continue

        # Refresh stale GreyNoise data (>7 days old)
        if source is None or source == "greynoise":
            greynoise_cutoff = now - timedelta(days=7)
            # Fetch candidates and filter in Python for cross-database compatibility
            candidates = (
                self.session.query(IPInventory)
                .filter(IPInventory.enrichment_updated_at < greynoise_cutoff)
                .limit(limit * 2)  # Over-fetch to account for filtering
                .all()
            )
            stale_greynoise = [inv for inv in candidates if inv.enrichment and "greynoise" in inv.enrichment][:limit]

            for inventory in stale_greynoise:
                try:
                    ip_str = str(inventory.ip_address)
                    greynoise_result = self.greynoise.lookup_ip(ip_str)
                    if greynoise_result:
                        gn_enrichment: dict[str, dict[str, str | bool | None]] = inventory.enrichment or {}
                        gn_enrichment["greynoise"] = {
                            "noise": greynoise_result.noise,
                            "riot": greynoise_result.riot,
                            "classification": greynoise_result.classification,
                            "name": greynoise_result.name,
                            "last_seen": (
                                greynoise_result.last_seen.isoformat() if greynoise_result.last_seen else None
                            ),
                            "cached_at": greynoise_result.cached_at.isoformat(),
                        }
                        inventory.enrichment = gn_enrichment
                        attributes.flag_modified(inventory, "enrichment")  # Mark JSON field as modified
                        inventory.enrichment_updated_at = now
                        refreshed["greynoise_refreshed"] += 1
                        self.session.flush()  # Ensure changes are persisted
                except Exception as e:
                    logger.warning(f"Failed to refresh GreyNoise for {inventory.ip_address}: {e}")
                    continue

        self.session.commit()
        logger.info(f"Refreshed stale data: {refreshed}")
        return refreshed

    def get_stats(self) -> CascadeStats:
        """Get current cascade statistics.

        Returns:
            CascadeStats object with enrichment operation counts
        """
        return self._stats

    def reset_stats(self) -> None:
        """Reset cascade statistics counters."""
        self._stats = CascadeStats()

    # Private helper methods

    def _is_fresh(self, inventory: IPInventory) -> bool:
        """Check if cached data is within TTL for each source.

        Args:
            inventory: IPInventory object to check freshness

        Returns:
            True if all cached data is fresh, False if any is stale
        """
        now = datetime.now(timezone.utc)
        enrichment: dict[str, dict[str, str | int | float | bool | None]] = inventory.enrichment or {}

        # Empty enrichment is stale (no data yet)
        if not enrichment:
            return False

        # MaxMind: Check database age (updated weekly)
        if "maxmind" in enrichment:
            db_age = self.maxmind.get_database_age()
            if db_age and db_age >= timedelta(days=7):
                logger.debug(f"MaxMind data stale for {inventory.ip_address} (DB age: {db_age.days} days)")
                return False

        # Cymru: 90-day TTL
        if "cymru" in enrichment:
            if not inventory.enrichment_updated_at:
                return False
            # Ensure timezone-aware comparison
            updated_at = inventory.enrichment_updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            age = now - updated_at
            if age >= timedelta(days=90):
                logger.debug(f"Cymru data stale for {inventory.ip_address} (age: {age.days} days)")
                return False

        # GreyNoise: 7-day TTL
        if "greynoise" in enrichment:
            if not inventory.enrichment_updated_at:
                return False
            # Ensure timezone-aware comparison
            updated_at = inventory.enrichment_updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            age = now - updated_at
            if age >= timedelta(days=7):
                logger.debug(f"GreyNoise data stale for {inventory.ip_address} (age: {age.days} days)")
                return False

        return True

    def _merge_results(
        self,
        cached: IPInventory | None,
        maxmind: MaxMindResult | None,
        cymru: CymruResult | None,
        greynoise: GreyNoiseResult | None,
        ip_address: str,
    ) -> IPInventory:
        """Merge results from multiple sources with priority rules.

        Priority rules:
        1. Geo data: MaxMind only (geo_city, geo_country, geo_latitude, geo_longitude)
        2. ASN data: MaxMind preferred, Cymru fallback
        3. Scanner data: GreyNoise only (is_scanner, scanner_classification)
        4. Timestamps: Track per source (enrichment_ts for MaxMind/Cymru, scanner_ts for GreyNoise)
        5. Source tracking: Record which service provided each field

        Args:
            cached: Existing IPInventory record (if any)
            maxmind: MaxMind lookup result (if successful)
            cymru: Cymru lookup result (if attempted)
            greynoise: GreyNoise lookup result (if attempted)
            ip_address: IP address being enriched (used for new records)

        Returns:
            IPInventory object with merged enrichment data
        """
        # Start with cached data or create new inventory
        if cached:
            inventory = cached
            enrichment: dict[str, dict[str, str | int | float | bool | None]] = inventory.enrichment or {}
        else:
            # Create new inventory with provided IP address
            inventory = IPInventory(ip_address=ip_address)
            enrichment = {}

        # Merge MaxMind data (geo + ASN, highest priority)
        if maxmind:
            enrichment["maxmind"] = {
                "country": maxmind.country_code,
                "country_name": maxmind.country_name,
                "city": maxmind.city,
                "latitude": maxmind.latitude,
                "longitude": maxmind.longitude,
                "asn": maxmind.asn,
                "asn_org": maxmind.asn_org,
                "accuracy_radius": maxmind.accuracy_radius,
                "cached_at": maxmind.cached_at.isoformat(),
            }
            # Set ASN if available from MaxMind
            if maxmind.asn:
                inventory.current_asn = maxmind.asn

        # Merge Cymru data (ASN fallback only if MaxMind didn't provide)
        if cymru and (not maxmind or maxmind.asn is None):
            enrichment["cymru"] = {
                "asn": cymru.asn,
                "asn_org": cymru.asn_org,
                "country": cymru.country_code,
                "registry": cymru.registry,
                "prefix": cymru.prefix,
                "allocation_date": cymru.allocation_date,
                "cached_at": cymru.cached_at.isoformat(),
            }
            # Set ASN from Cymru if MaxMind didn't provide
            if cymru.asn:
                inventory.current_asn = cymru.asn

        # Merge GreyNoise data (scanner classification, independent)
        if greynoise:
            enrichment["greynoise"] = {
                "noise": greynoise.noise,
                "riot": greynoise.riot,
                "classification": greynoise.classification,
                "name": greynoise.name,
                "last_seen": greynoise.last_seen.isoformat() if greynoise.last_seen else None,
                "cached_at": greynoise.cached_at.isoformat(),
            }

        inventory.enrichment = enrichment
        return inventory

    def _create_minimal_inventory(self, ip_address: str, now: datetime) -> IPInventory:
        """Create minimal IPInventory record when all lookups fail.

        Args:
            ip_address: IP address to create record for
            now: Current timestamp

        Returns:
            Minimal IPInventory object with empty enrichment
        """
        return IPInventory(
            ip_address=ip_address,
            enrichment={},
            enrichment_updated_at=now,
            enrichment_version="2.2",
            first_seen=now,
            last_seen=now,
            session_count=1,
            created_at=now,
            updated_at=now,
        )


__all__ = ["CascadeEnricher", "CascadeStats"]
