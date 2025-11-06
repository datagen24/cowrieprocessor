"""Factory functions for creating CascadeEnricher with proper cache wiring and secrets management.

This module provides factory functions to construct a fully initialized CascadeEnricher with:
- 3-tier caching architecture (Redis L1 → Database L2 → Disk L3)
- Secure API key management via secrets resolver
- Rate limiting per ADR-008 specification
- Graceful degradation for optional services

Security:
    All API keys MUST be provided via secrets resolver URIs, not plaintext:
    - env:KEY_NAME - Environment variable
    - file:/path/to/secret - File contents
    - op://vault/item/field - 1Password CLI
    - aws-sm://[region/]secret_id[#json_key] - AWS Secrets Manager
    - vault://path[#field] - HashiCorp Vault
    - sops://path[#json.key] - SOPS-encrypted files

    WARNING: Plaintext API keys in configuration files are a security violation.
    Always use secrets resolver URIs to prevent credential exposure in logs/repos.

Example:
    >>> from pathlib import Path
    >>> from sqlalchemy.orm import Session
    >>> from cowrieprocessor.db.engine import get_engine
    >>>
    >>> # Configuration with secrets resolver URIs
    >>> config = {
    ...     'greynoise_api': 'env:GREYNOISE_API_KEY',  # Secure
    ...     # OR: 'greynoise_api': 'op://vault/greynoise/api_key',
    ...     # OR: 'greynoise_api': 'aws-sm://secrets/greynoise#api_key',
    ... }
    >>>
    >>> # Create enricher with all components wired
    >>> engine = get_engine("postgresql://...")
    >>> with Session(engine) as session:
    ...     cascade = create_cascade_enricher(
    ...         cache_dir=Path("/mnt/dshield/data/cache"),
    ...         db_session=session,
    ...         config=config,
    ...         maxmind_license_key="env:MAXMIND_LICENSE_KEY",
    ...         enable_greynoise=True,
    ...     )
    ...
    ...     # Use cascade enricher
    ...     result = cascade.enrich_ip("8.8.8.8")
    ...     print(f"Country: {result.geo_country}, ASN: {result.current_asn}")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from ..utils.secrets import resolve_secret
from .cache import EnrichmentCacheManager
from .cascade_enricher import CascadeEnricher
from .cymru_client import CymruClient
from .greynoise_client import GreyNoiseClient
from .maxmind_client import MaxMindClient
from .rate_limiting import RateLimiter

logger = logging.getLogger(__name__)


class MockGreyNoiseClient:
    """Mock GreyNoise client that returns None for all lookups.

    Used when GreyNoise API key is not available or service is disabled.
    Maintains the same interface as GreyNoiseClient for transparent fallback.
    """

    def __init__(self) -> None:
        """Initialize mock client."""
        self.stats = {
            'lookups': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'api_success': 0,
            'api_failures': 0,
            'quota_exceeded': 0,
            'errors': 0,
        }

    def lookup_ip(self, ip_address: str) -> None:
        """Return None for all lookups (service unavailable).

        Args:
            ip_address: IP address to look up (ignored)

        Returns:
            None (GreyNoise unavailable)
        """
        self.stats['lookups'] += 1
        self.stats['api_failures'] += 1
        return None

    def get_remaining_quota(self) -> int:
        """Return 0 (no quota available).

        Returns:
            0 (service unavailable)
        """
        return 0

    def get_stats(self) -> dict[str, int]:
        """Get mock client statistics.

        Returns:
            Dictionary with all lookups recorded as failures
        """
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Reset statistics counters."""
        for key in self.stats:
            self.stats[key] = 0


def create_cascade_enricher(
    cache_dir: Path,
    db_session: Session,
    config: dict[str, str],
    maxmind_license_key: Optional[str] = None,
    enable_greynoise: bool = True,
) -> CascadeEnricher:
    """Create CascadeEnricher with proper cache wiring and secrets management.

    This factory function constructs a fully initialized CascadeEnricher with:

    1. **3-Tier Caching Architecture**:
       - L1 (Redis): Hot data, sub-millisecond latency (when available)
       - L2 (Database): ip_inventory table, session-persistent
       - L3 (Disk): Long-term cache with service-specific TTLs

    2. **Secure Secrets Management**:
       - All API keys resolved via secrets resolver (env:, file:, op://, aws-sm://, vault://, sops://)
       - No plaintext credentials in configuration or logs
       - Graceful degradation when secrets are unavailable

    3. **Rate Limiting per ADR-008**:
       - Cymru: 100 requests/second, 90-day TTL
       - GreyNoise: 10 requests/second, 7-day TTL, 10K/day quota
       - MaxMind: Offline database, no rate limits

    4. **Graceful Degradation**:
       - Missing GreyNoise API key → Mock client (returns None)
       - GreyNoise disabled → Mock client
       - MaxMind database missing → Continue with Cymru fallback

    Args:
        cache_dir: Base directory for disk-based enrichment cache
        db_session: Active SQLAlchemy session for database operations
        config: Configuration dictionary with secrets resolver URIs:
            - greynoise_api: GreyNoise Community API key URI (e.g., "env:GREYNOISE_API_KEY")
        maxmind_license_key: Optional MaxMind license key URI for automatic database updates
        enable_greynoise: Whether to enable GreyNoise scanner detection (default: True)

    Returns:
        Fully initialized CascadeEnricher ready for IP enrichment operations

    Raises:
        ValueError: If cache_dir is invalid or required configuration is malformed
        RuntimeError: If secrets resolver fails to resolve required secrets

    Security:
        All API keys MUST be provided via secrets resolver URIs:
        - ✅ Secure: "env:GREYNOISE_API_KEY"
        - ✅ Secure: "op://vault/greynoise/api_key"
        - ✅ Secure: "file:/etc/secrets/greynoise_key"
        - ❌ VIOLATION: "gn_abc123xyz" (plaintext key)

        Plaintext keys in configuration are a security violation per ADR-007.

    Examples:
        >>> # Create enricher with GreyNoise enabled
        >>> config = {'greynoise_api': 'env:GREYNOISE_API_KEY'}
        >>> cascade = create_cascade_enricher(
        ...     cache_dir=Path("/cache"),
        ...     db_session=session,
        ...     config=config,
        ...     maxmind_license_key="env:MAXMIND_LICENSE_KEY",
        ...     enable_greynoise=True,
        ... )
        >>>
        >>> # Create enricher without GreyNoise (MaxMind + Cymru only)
        >>> cascade = create_cascade_enricher(
        ...     cache_dir=Path("/cache"),
        ...     db_session=session,
        ...     config={},
        ...     enable_greynoise=False,
        ... )
        >>>
        >>> # Use enricher
        >>> result = cascade.enrich_ip("8.8.8.8")
        >>> print(f"Country: {result.geo_country}, ASN: {result.current_asn}")
        Country: US, ASN: 15169
    """
    # Validate cache directory
    if not isinstance(cache_dir, Path):
        raise ValueError(f"cache_dir must be Path object, got {type(cache_dir)}")

    cache_dir = cache_dir.resolve()
    if cache_dir.exists() and not cache_dir.is_dir():
        raise ValueError(f"cache_dir exists but is not a directory: {cache_dir}")

    logger.info(f"Creating CascadeEnricher with cache_dir: {cache_dir}")

    # Initialize shared 3-tier cache manager (L3: Disk)
    cache_manager = EnrichmentCacheManager(
        base_dir=cache_dir,
        ttls={
            'cymru': 90 * 24 * 3600,  # 90 days per ADR-008
            'greynoise': 7 * 24 * 3600,  # 7 days per ADR-008
            'maxmind': 7 * 24 * 3600,  # 7 days (database refresh interval)
        },
    )
    logger.debug("Initialized EnrichmentCacheManager with service-specific TTLs")

    # Initialize MaxMind client (offline database, no cache manager needed)
    maxmind_db_path = cache_dir / "maxmind"
    maxmind_license = None

    if maxmind_license_key:
        try:
            maxmind_license = resolve_secret(maxmind_license_key)
            if maxmind_license:
                logger.info("Resolved MaxMind license key for automatic database updates")
            else:
                logger.warning("MaxMind license key URI resolved to None (manual database updates required)")
        except Exception as e:
            logger.warning(f"Failed to resolve MaxMind license key: {e} (manual updates required)")

    maxmind_client = MaxMindClient(
        db_path=maxmind_db_path,
        license_key=maxmind_license,
    )
    logger.info("Initialized MaxMindClient for offline geo/ASN enrichment")

    # Initialize Cymru client with cache manager + rate limiter
    cymru_rate_limiter = RateLimiter(
        rate=100.0,  # 100 requests/second per ADR-008
        burst=100,
    )
    cymru_client = CymruClient(
        cache=cache_manager,
        rate_limiter=cymru_rate_limiter,
        ttl_days=90,  # 90-day TTL per ADR-008
    )
    logger.info("Initialized CymruClient with 100 req/sec rate limiter and 90-day TTL")

    # Initialize GreyNoise client with cache manager + rate limiter (or mock)
    greynoise_client: GreyNoiseClient | MockGreyNoiseClient

    if enable_greynoise:
        # Attempt to resolve GreyNoise API key from secrets resolver
        greynoise_secret_uri = config.get('greynoise_api', '')
        greynoise_api_key: Optional[str] = None

        if greynoise_secret_uri:
            try:
                greynoise_api_key = resolve_secret(greynoise_secret_uri)
                if not greynoise_api_key:
                    logger.warning(
                        f"GreyNoise API key URI '{greynoise_secret_uri}' resolved to None "
                        "(using mock client, scanner detection disabled)"
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to resolve GreyNoise API key from '{greynoise_secret_uri}': {e} "
                    "(using mock client, scanner detection disabled)"
                )
        else:
            logger.info("No GreyNoise API key configured (using mock client, scanner detection disabled)")

        if greynoise_api_key:
            # Real GreyNoise client with API key
            greynoise_rate_limiter = RateLimiter(
                rate=10.0,  # 10 requests/second per ADR-008
                burst=10,
            )
            greynoise_client = GreyNoiseClient(
                api_key=greynoise_api_key,
                cache=cache_manager,
                rate_limiter=greynoise_rate_limiter,
                ttl_days=7,  # 7-day TTL per ADR-008
            )
            logger.info("Initialized GreyNoiseClient with 10 req/sec rate limiter and 7-day TTL")
        else:
            # Mock client (API key unavailable)
            greynoise_client = MockGreyNoiseClient()
            logger.warning("Using MockGreyNoiseClient (GreyNoise API key not available)")
    else:
        # Mock client (GreyNoise disabled)
        greynoise_client = MockGreyNoiseClient()
        logger.info("GreyNoise disabled (using MockGreyNoiseClient)")

    # Create CascadeEnricher with all components wired
    cascade_enricher = CascadeEnricher(
        maxmind=maxmind_client,
        cymru=cymru_client,
        greynoise=greynoise_client,  # type: ignore[arg-type]  # Mock satisfies interface
        session=db_session,
    )

    logger.info(
        "Successfully created CascadeEnricher with MaxMind + Cymru + "
        f"{'GreyNoise' if isinstance(greynoise_client, GreyNoiseClient) else 'Mock GreyNoise'}"
    )

    return cascade_enricher


__all__ = ["create_cascade_enricher", "MockGreyNoiseClient"]
