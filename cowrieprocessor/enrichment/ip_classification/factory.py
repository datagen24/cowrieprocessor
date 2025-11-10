"""Factory function for creating IPClassifier with proper dependency injection."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Union

from sqlalchemy.engine import Connection, Engine

from .classifier import IPClassifier

logger = logging.getLogger(__name__)


def create_ip_classifier(
    cache_dir: Path,
    db_engine: Union[Engine, Connection],
    enable_redis: bool = True,
    tor_url: Optional[str] = None,
    cloud_base_url: Optional[str] = None,
    datacenter_url: Optional[str] = None,
) -> IPClassifier:
    """Create fully initialized IPClassifier service.

    Args:
        cache_dir: Base directory for disk cache (L3)
        db_engine: SQLAlchemy engine or connection for database cache (L2)
        enable_redis: Enable Redis cache (L1), default True
        tor_url: Optional custom TOR exit node list URL
        cloud_base_url: Optional custom cloud provider IP ranges URL
        datacenter_url: Optional custom datacenter IP ranges URL

    Returns:
        IPClassifier instance ready for use

    Example:
        >>> from pathlib import Path
        >>> from cowrieprocessor.db.engine import get_engine
        >>>
        >>> engine = get_engine("postgresql://...")
        >>> classifier = create_ip_classifier(
        ...     cache_dir=Path("/mnt/dshield/data/cache"),
        ...     db_engine=engine
        ... )
        >>> result = classifier.classify("1.2.3.4")
    """
    classifier = IPClassifier(
        cache_dir=cache_dir,
        db_engine=db_engine,
        enable_redis=enable_redis,
        tor_url=tor_url or "https://check.torproject.org/torbulkexitlist",
        cloud_base_url=cloud_base_url or "https://raw.githubusercontent.com/rezmoss/cloud-provider-ip-addresses/main",
        datacenter_url=datacenter_url or "https://raw.githubusercontent.com/jhassine/server-ip-addresses/master",
    )

    logger.info("IPClassifier initialized successfully")
    return classifier
