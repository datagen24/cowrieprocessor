"""IP classification enrichment module.

This module provides infrastructure classification for IP addresses using:
- TOR exit node detection (official Tor Project data)
- Cloud provider matching (AWS, Azure, GCP, CloudFlare)
- Datacenter identification (community-maintained lists)
- Residential ISP heuristics (ASN name patterns)

Example:
    >>> from pathlib import Path
    >>> from cowrieprocessor.db.engine import get_engine
    >>> from cowrieprocessor.enrichment.ip_classification import create_ip_classifier
    >>>
    >>> engine = get_engine("postgresql://...")
    >>> classifier = create_ip_classifier(
    ...     cache_dir=Path("/mnt/dshield/data/cache"),
    ...     db_engine=engine
    ... )
    >>> result = classifier.classify("52.0.0.1")
    >>> print(f"{result.ip_type.value}: {result.provider}")
    cloud: aws
"""

from .classifier import IPClassifier
from .factory import create_ip_classifier
from .models import IPClassification, IPType

__all__ = [
    "IPClassifier",
    "IPClassification",
    "IPType",
    "create_ip_classifier",
]
