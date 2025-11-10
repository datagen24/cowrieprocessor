"""Data models for IP classification.

This module provides the core data structures for IP infrastructure classification,
including type enums and immutable classification results.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class IPType(str, Enum):
    """IP classification types.

    Categories are ordered by threat priority (TOR highest, UNKNOWN lowest).
    Used to classify IPs into infrastructure categories for threat analysis.

    Attributes:
        TOR: TOR exit node (anonymization network)
        CLOUD: Cloud provider (AWS, Azure, GCP, CloudFlare)
        DATACENTER: Datacenter or hosting provider
        RESIDENTIAL: Residential ISP or mobile network
        UNKNOWN: Unable to classify with available data
    """

    TOR = "tor"
    CLOUD = "cloud"
    DATACENTER = "datacenter"
    RESIDENTIAL = "residential"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class IPClassification:
    """Immutable IP classification result.

    Represents the result of IP infrastructure classification with confidence
    scoring and source attribution. Immutable to prevent accidental modification
    after caching.

    Attributes:
        ip_type: Classification category (TOR, Cloud, Datacenter, Residential, Unknown)
        provider: Optional provider name (e.g., "aws", "tor", "digital_ocean")
        confidence: Classification confidence score (0.0 to 1.0)
            - 0.95-1.0: Very high (official data sources)
            - 0.7-0.95: High (community-maintained lists)
            - 0.5-0.7: Medium (heuristic-based)
            - <0.5: Low (fallback classification)
        source: Data source identifier (e.g., "tor_bulk_list", "cloud_ranges_aws")
        classified_at: UTC timestamp of classification

    Example:
        >>> from cowrieprocessor.enrichment.ip_classification.models import IPType, IPClassification
        >>> classification = IPClassification(
        ...     ip_type=IPType.CLOUD,
        ...     provider="aws",
        ...     confidence=0.99,
        ...     source="cloud_ranges_aws",
        ... )
        >>> print(f"{classification.ip_type.value}: {classification.provider}")
        cloud: aws

    Raises:
        ValueError: If confidence is not between 0.0 and 1.0

    Note:
        This is a frozen dataclass - all fields are immutable after creation.
        The classified_at field is auto-populated with current UTC time if not provided.
    """

    ip_type: IPType
    provider: Optional[str]
    confidence: float
    source: str
    classified_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        """Validate fields and set defaults.

        Validates that confidence is within acceptable range [0.0, 1.0] and
        sets classified_at to current UTC time if not provided.

        Raises:
            ValueError: If confidence is outside the range [0.0, 1.0]
        """
        # Validate confidence range
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be between 0.0 and 1.0, got {self.confidence}")

        # Set classified_at to current UTC time if not provided
        # Use object.__setattr__ because dataclass is frozen
        if self.classified_at is None:
            object.__setattr__(self, "classified_at", datetime.now(timezone.utc))
