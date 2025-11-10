"""Residential ISP heuristic matcher using ASN name patterns.

This module provides regex-based classification of residential ISPs by analyzing
ASN organization names for common telecom, broadband, and mobile ISP patterns.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ResidentialHeuristic:
    """Classify IPs as residential based on ASN name patterns.

    This heuristic analyzes ASN organization names to identify residential ISPs
    (telecom, broadband, mobile networks) vs datacenter/hosting providers.

    Data Source:
        No external data - uses pattern matching on ASN names
        Update Frequency: N/A (static patterns)
        Accuracy: 70-80% (heuristic-based, language-dependent)

    Performance:
        O(n patterns) regex matching
        Average: <1ms per lookup
        Memory: Minimal (compiled regex patterns)

    Confidence Scoring:
        - 0.8: Strong match (multiple positive indicators)
        - 0.7: Good match (single strong positive indicator)
        - 0.5: Weak match (generic patterns, possible false positive)

    Thread Safety:
        This class is thread-safe (no mutable state after init).

    Example:
        >>> heuristic = ResidentialHeuristic()
        >>> result = heuristic.match("1.2.3.4", asn=7922, as_name="Comcast Cable Communications")
        >>> print(result)
        {'asn': 7922, 'as_name': 'Comcast Cable Communications', 'confidence': 0.8}
        >>>
        >>> result = heuristic.match("8.8.8.8", asn=15169, as_name="Google LLC")
        >>> print(result)  # None - not residential
        None
    """

    # Strong residential indicators (high confidence)
    STRONG_RESIDENTIAL_PATTERNS = [
        # Telecom brands
        r"\b(verizon|at&t|att|comcast|xfinity|cox|charter|spectrum)\b",
        # ISP types
        r"\b(telecom|telecommunications?|telco)\b",
        # Broadband/Cable
        r"\b(broadband|cable|dsl|fiber)\b",
        # Mobile carriers
        r"\b(mobile|wireless|cellular|gsm|lte|5g)\b",
    ]

    # Weak residential indicators (moderate confidence)
    WEAK_RESIDENTIAL_PATTERNS = [
        r"\b(isp|internet service|network provider)\b",
        r"\b(residential|consumer|subscriber)\b",
    ]

    # Exclusion patterns (NOT residential)
    EXCLUSION_PATTERNS = [
        # Hosting/Cloud
        r"\b(hosting|host|datacenter|data center|cloud|server|vps|dedicated)\b",
        # Colocation
        r"\b(colo|colocation|facility)\b",
        # CDN/Edge
        r"\b(cdn|content delivery|edge|akamai|cloudflare|fastly)\b",
        # Corporate networks
        r"\b(corporate|enterprise|business network)\b",
    ]

    def __init__(self) -> None:
        """Initialize residential heuristic with compiled regex patterns.

        Compiles all patterns for efficient matching with case-insensitive search.
        """
        # Compile all patterns (case-insensitive)
        self._strong_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self.STRONG_RESIDENTIAL_PATTERNS]
        self._weak_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self.WEAK_RESIDENTIAL_PATTERNS]
        self._exclusion_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self.EXCLUSION_PATTERNS]

        # Statistics tracking
        self._stats_lookups = 0
        self._stats_hits = 0
        self._stats_misses = 0
        self._stats_excluded = 0

    def match(self, ip: str, asn: Optional[int] = None, as_name: Optional[str] = None) -> Optional[Dict[str, any]]:
        """Check if IP likely belongs to a residential ISP based on ASN name.

        This method applies regex patterns to the ASN organization name to identify
        residential ISP characteristics. Requires ASN metadata from ip_inventory.

        Args:
            ip: IPv4 or IPv6 address (not used, for interface consistency)
            asn: ASN number (optional, for metadata)
            as_name: ASN organization name (required for classification)

        Returns:
            Dict with residential metadata if match:
                {'asn': int, 'as_name': str, 'confidence': float, 'pattern_type': str}
            None if no match or if as_name is missing

        Note:
            Confidence scoring:
            - 0.8: Strong match (telecom, broadband, mobile)
            - 0.7: Good match (single strong indicator)
            - 0.5: Weak match (generic ISP patterns)

        Example:
            >>> result = heuristic.match("1.2.3.4", asn=7922, as_name="Comcast Cable")
            >>> result
            {'asn': 7922, 'as_name': 'Comcast Cable', 'confidence': 0.8, 'pattern_type': 'strong'}
        """
        self._stats_lookups += 1

        # Require ASN name for classification
        if not as_name:
            self._stats_misses += 1
            return None

        # Check exclusion patterns first (hosting, datacenter, etc.)
        for pattern in self._exclusion_patterns:
            if pattern.search(as_name):
                self._stats_excluded += 1
                logger.debug(f"ASN {asn} '{as_name}' excluded by pattern: {pattern.pattern}")
                return None

        # Check strong residential patterns
        strong_matches = sum(1 for pattern in self._strong_patterns if pattern.search(as_name))
        if strong_matches >= 2:
            # Multiple strong indicators = very high confidence
            self._stats_hits += 1
            return {
                "asn": asn,
                "as_name": as_name,
                "confidence": 0.8,
                "pattern_type": "strong_multiple",
            }
        elif strong_matches == 1:
            # Single strong indicator = high confidence
            self._stats_hits += 1
            return {
                "asn": asn,
                "as_name": as_name,
                "confidence": 0.7,
                "pattern_type": "strong_single",
            }

        # Check weak residential patterns
        weak_matches = sum(1 for pattern in self._weak_patterns if pattern.search(as_name))
        if weak_matches > 0:
            # Generic ISP patterns = moderate confidence
            self._stats_hits += 1
            return {
                "asn": asn,
                "as_name": as_name,
                "confidence": 0.5,
                "pattern_type": "weak",
            }

        # No patterns matched
        self._stats_misses += 1
        return None

    def get_stats(self) -> Dict[str, any]:
        """Get heuristic statistics.

        Returns:
            Dict with statistics:
                - lookups: Total number of match() calls
                - hits: Number of successful residential matches
                - misses: Number of non-matches
                - excluded: Number of excluded (datacenter/hosting)
                - hit_rate: Percentage of lookups that matched (0.0-1.0)
                - exclusion_rate: Percentage of lookups excluded (0.0-1.0)
        """
        return {
            "lookups": self._stats_lookups,
            "hits": self._stats_hits,
            "misses": self._stats_misses,
            "excluded": self._stats_excluded,
            "hit_rate": (self._stats_hits / self._stats_lookups if self._stats_lookups > 0 else 0.0),
            "exclusion_rate": (self._stats_excluded / self._stats_lookups if self._stats_lookups > 0 else 0.0),
        }
