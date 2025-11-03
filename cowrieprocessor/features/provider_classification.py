"""Dynamic provider classification using enrichment data.

This module classifies attack sources (cloud/VPN/Tor) using existing enrichment data
instead of hardcoded ASN lists. This enables behavioral profiling for snowshoe spam detection.

Example:
    >>> from cowrieprocessor.features import ProviderClassifier
    >>> from cowrieprocessor.db.models import SessionSummary
    >>> from sqlalchemy.orm import Session
    >>>
    >>> classifier = ProviderClassifier(config)
    >>> features = classifier.classify(session_summary)
    >>> if features.is_cloud_provider and features.cloud_confidence == "high":
    ...     print(f"Cloud provider detected: {features.provider_name}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

LOGGER = logging.getLogger(__name__)


@dataclass
class ProviderFeatures:
    """Classification features for attack source providers.

    Attributes:
        is_cloud_provider: Whether source is identified as cloud/datacenter
        is_vpn_provider: Whether source is identified as VPN service
        is_tor_exit: Whether source is identified as Tor exit node
        cloud_confidence: Confidence level for cloud classification ("high", "medium", "low", "none")
        vpn_confidence: Confidence level for VPN classification
        tor_confidence: Confidence level for Tor classification
        provider_name: Identified provider name (e.g., "Amazon AWS", "Mullvad VPN")
        enrichment_age_days: Age of enrichment data in days
        enrichment_stale: Whether enrichment data is stale (>max_age_days)
    """

    is_cloud_provider: bool
    is_vpn_provider: bool
    is_tor_exit: bool
    cloud_confidence: str  # "high", "medium", "low", "none"
    vpn_confidence: str
    tor_confidence: str
    provider_name: Optional[str]
    enrichment_age_days: Optional[int]
    enrichment_stale: bool


class ProviderClassifier:
    """Classifies attack sources using enrichment data.

    Uses DShield and Spur enrichment data to dynamically classify attack sources
    as cloud providers, VPN services, or Tor exit nodes.

    Args:
        config: Configuration dictionary with enrichment settings
        logger: Optional logger instance

    Example:
        >>> config = {
        ...     "use_dshield": True,
        ...     "use_spur": True,
        ...     "max_enrichment_age_days": 365,
        ...     "treat_stale_as_unknown": False,
        ...     "cloud_provider_keywords": ["amazon", "aws", "google", "azure"],
        ... }
        >>> classifier = ProviderClassifier(config)
        >>> features = classifier.classify(session_summary)
    """

    def __init__(self, config: dict[str, Any], logger: Optional[logging.Logger] = None) -> None:
        """Initialize provider classifier.

        Args:
            config: Configuration dictionary with:
                - use_dshield: Enable DShield for cloud detection
                - use_spur: Enable Spur for VPN/Tor detection
                - max_enrichment_age_days: Maximum enrichment age (default: 365)
                - treat_stale_as_unknown: Treat stale enrichment as unknown (default: False)
                - cloud_provider_keywords: Keywords for cloud provider detection
            logger: Optional logger instance
        """
        self.config = config
        self.logger = logger or LOGGER

        self.use_dshield = config.get("use_dshield", True)
        self.use_spur = config.get("use_spur", True)
        self.max_enrichment_age_days = config.get("max_enrichment_age_days", 365)
        self.treat_stale_as_unknown = config.get("treat_stale_as_unknown", False)
        self.cloud_keywords = [
            kw.lower()
            for kw in config.get(
                "cloud_provider_keywords",
                [
                    "amazon",
                    "aws",
                    "google",
                    "gcp",
                    "azure",
                    "microsoft",
                    "digitalocean",
                    "linode",
                    "vultr",
                    "ovh",
                ],
            )
        ]

    def classify(self, session_summary: Any) -> ProviderFeatures:
        """Classify attack source from session enrichment data.

        Args:
            session_summary: SessionSummary ORM object with enrichment data

        Returns:
            ProviderFeatures with classification results and confidence levels

        Example:
            >>> features = classifier.classify(session_summary)
            >>> if features.is_cloud_provider:
            ...     print(f"Cloud: {features.provider_name} (confidence: {features.cloud_confidence})")
        """
        # Extract enrichment data
        enrichment = session_summary.enrichment if session_summary.enrichment else {}
        dshield_data = enrichment.get("dshield", {})
        spur_data = enrichment.get("spur", {})

        # Calculate enrichment age
        enrichment_age_days: Optional[int] = None
        enrichment_stale = False
        if hasattr(session_summary, "updated_at") and session_summary.updated_at:
            age_delta = datetime.now(timezone.utc) - session_summary.updated_at
            enrichment_age_days = age_delta.days
            enrichment_stale = enrichment_age_days > self.max_enrichment_age_days

        # Detect provider types
        is_cloud, cloud_name = self._detect_cloud_provider(dshield_data, spur_data)
        is_vpn, vpn_name = self._detect_vpn_provider(spur_data)
        is_tor, tor_name = self._detect_tor_exit(spur_data)

        # Calculate confidence levels
        has_dshield = bool(dshield_data and dshield_data.get("ip"))
        has_spur = bool(spur_data and spur_data.get("asn"))

        cloud_confidence = self._calculate_confidence(
            enrichment_age_days, enrichment_stale, has_dshield or has_spur, is_cloud
        )
        vpn_confidence = self._calculate_confidence(enrichment_age_days, enrichment_stale, has_spur, is_vpn)
        tor_confidence = self._calculate_confidence(enrichment_age_days, enrichment_stale, has_spur, is_tor)

        # Determine provider name (convert empty string to None)
        provider_name = cloud_name or vpn_name or tor_name or None

        # Handle stale enrichment
        if self.treat_stale_as_unknown and enrichment_stale:
            is_cloud = False
            is_vpn = False
            is_tor = False
            cloud_confidence = "none"
            vpn_confidence = "none"
            tor_confidence = "none"

        return ProviderFeatures(
            is_cloud_provider=is_cloud,
            is_vpn_provider=is_vpn,
            is_tor_exit=is_tor,
            cloud_confidence=cloud_confidence,
            vpn_confidence=vpn_confidence,
            tor_confidence=tor_confidence,
            provider_name=provider_name,
            enrichment_age_days=enrichment_age_days,
            enrichment_stale=enrichment_stale,
        )

    def _detect_cloud_provider(self, dshield_data: dict[str, Any], spur_data: dict[str, Any]) -> tuple[bool, str]:
        """Detect cloud provider from DShield and Spur data.

        Args:
            dshield_data: DShield enrichment data
            spur_data: Spur enrichment data

        Returns:
            Tuple of (is_cloud_provider, provider_name)

        Example:
            >>> is_cloud, name = classifier._detect_cloud_provider(dshield_data, {})
            >>> if is_cloud:
            ...     print(f"Detected cloud provider: {name}")
        """
        if not self.use_dshield and not self.use_spur:
            return False, ""

        # Try DShield ASN name
        if self.use_dshield and dshield_data:
            ip_data = dshield_data.get("ip", {})
            asn_name = ip_data.get("asname", "").lower()

            if asn_name:
                for keyword in self.cloud_keywords:
                    if keyword in asn_name:
                        return True, ip_data.get("asdescription", asn_name)

        # Try Spur infrastructure classification
        if self.use_spur and spur_data:
            infrastructure = spur_data.get("infrastructure", "").upper()
            if infrastructure == "DATACENTER":
                org = spur_data.get("organization", "")
                asn_org = spur_data.get("asn", {}).get("organization", "")
                return True, org or asn_org or "Datacenter"

            # Check Spur ASN organization for cloud keywords
            asn_org = spur_data.get("asn", {}).get("organization", "").lower()
            if asn_org:
                for keyword in self.cloud_keywords:
                    if keyword in asn_org:
                        return True, spur_data.get("organization", asn_org)

        return False, ""

    def _detect_vpn_provider(self, spur_data: dict[str, Any]) -> tuple[bool, str]:
        """Detect VPN provider from Spur data.

        Args:
            spur_data: Spur enrichment data

        Returns:
            Tuple of (is_vpn_provider, provider_name)

        Example:
            >>> is_vpn, name = classifier._detect_vpn_provider(spur_data)
            >>> if is_vpn:
            ...     print(f"Detected VPN: {name}")
        """
        if not self.use_spur or not spur_data:
            return False, ""

        # Check infrastructure type
        infrastructure = spur_data.get("infrastructure", "").upper()
        if infrastructure == "VPN":
            return True, spur_data.get("organization", "VPN Provider")

        # Check for VPN operator in tunnels
        tunnels = spur_data.get("tunnels", [])
        for tunnel in tunnels:
            if isinstance(tunnel, dict):
                operator = tunnel.get("operator", "")
                if operator and operator.lower() != "":
                    return True, operator

        # Check client behaviors for VPN
        client = spur_data.get("client", {})
        behaviors = client.get("behaviors", [])
        if "VPN" in behaviors:
            return True, spur_data.get("organization", "VPN Provider")

        # Check proxies field
        proxies = client.get("proxies", "")
        if proxies and proxies.upper() == "VPN":
            return True, spur_data.get("organization", "VPN Provider")

        return False, ""

    def _detect_tor_exit(self, spur_data: dict[str, Any]) -> tuple[bool, str]:
        """Detect Tor exit node from Spur data.

        Args:
            spur_data: Spur enrichment data

        Returns:
            Tuple of (is_tor_exit, provider_name)

        Example:
            >>> is_tor, name = classifier._detect_tor_exit(spur_data)
            >>> if is_tor:
            ...     print("Detected Tor exit node")
        """
        if not self.use_spur or not spur_data:
            return False, ""

        # Check for Tor in client behaviors
        client = spur_data.get("client", {})
        behaviors = client.get("behaviors", [])
        if "TOR" in behaviors:
            # Try to get operator name from tunnels first
            tunnels = spur_data.get("tunnels", [])
            for tunnel in tunnels:
                if isinstance(tunnel, dict):
                    operator = tunnel.get("operator", "")
                    if operator and operator.lower() != "":
                        return True, operator
            return True, "Tor Exit"

        # Check for Tor in tunnels
        tunnels = spur_data.get("tunnels", [])
        for tunnel in tunnels:
            if isinstance(tunnel, dict):
                tunnel_type = tunnel.get("type", "").upper()
                if tunnel_type == "TOR":
                    operator = tunnel.get("operator", "")
                    return True, operator if operator else "Tor Exit"

        return False, ""

    def _calculate_confidence(
        self, enrichment_age_days: Optional[int], enrichment_stale: bool, has_data: bool, detected: bool
    ) -> str:
        """Calculate confidence level for classification.

        Args:
            enrichment_age_days: Age of enrichment data in days
            enrichment_stale: Whether enrichment is stale (>max_age_days)
            has_data: Whether enrichment data is present
            detected: Whether provider type was detected

        Returns:
            Confidence level: "high", "medium", "low", or "none"

        Confidence rules:
            - High: Fresh enrichment (<30 days), positive detection
            - Medium: Fresh enrichment (<30 days), no detection OR stale enrichment (<365 days), positive detection
            - Low: Stale enrichment (<365 days), no detection
            - None: No enrichment data OR enrichment too old (>365 days)
        """
        if not has_data or enrichment_age_days is None:
            return "none"

        # Too old
        if enrichment_stale:
            if detected:
                return "medium"
            return "low"

        # Fresh data
        if enrichment_age_days < 30:
            if detected:
                return "high"
            return "medium"

        # Moderate age (30-365 days)
        if detected:
            return "medium"
        return "low"


__all__ = ["ProviderFeatures", "ProviderClassifier"]
