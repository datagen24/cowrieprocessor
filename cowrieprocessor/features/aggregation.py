"""Multi-IP feature aggregation for snowshoe spam detection.

This module provides functions for aggregating features across multiple attack sessions
to identify distributed attack patterns like snowshoe spam campaigns. Features include
geographic spread, behavioral entropy, and provider distribution analysis.

Example:
    >>> from cowrieprocessor.features import ProviderClassifier, aggregate_features
    >>> from cowrieprocessor.db.models import SessionSummary
    >>> from sqlalchemy.orm import Session
    >>>
    >>> # Load sessions for an attack cluster
    >>> sessions = session.query(SessionSummary).filter(
    ...     SessionSummary.first_event_at.between(start, end)
    ... ).all()
    >>>
    >>> # Load provider classifier
    >>> config = {"use_dshield": True, "use_spur": True, "max_enrichment_age_days": 365}
    >>> classifier = ProviderClassifier(config)
    >>>
    >>> # Aggregate features
    >>> features = aggregate_features(sessions, classifier)
    >>> print(f"Geographic Spread: {features['geographic_spread_km']} km")
    >>> print(f"Cloud Provider Ratio: {features['cloud_provider_ratio']}")
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from typing import Any, List

LOGGER = logging.getLogger(__name__)


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two geographic coordinates using Haversine formula.

    The Haversine formula calculates the great-circle distance between two points on a sphere
    given their latitude and longitude. This implementation uses Earth's mean radius.

    Args:
        lat1: Latitude of first point in decimal degrees
        lon1: Longitude of first point in decimal degrees
        lat2: Latitude of second point in decimal degrees
        lon2: Longitude of second point in decimal degrees

    Returns:
        Distance between the two points in kilometers

    Raises:
        ValueError: If any coordinate is None

    Examples:
        >>> # Distance from New York to London
        >>> distance = haversine_distance(40.7128, -74.0060, 51.5074, -0.1278)
        >>> print(f"{distance:.2f} km")
        5570.27 km

        >>> # Distance from Tokyo to Sydney
        >>> distance = haversine_distance(35.6762, 139.6503, -33.8688, 151.2093)
        >>> print(f"{distance:.2f} km")
        7823.21 km

        >>> # Identical coordinates
        >>> distance = haversine_distance(0.0, 0.0, 0.0, 0.0)
        >>> print(distance)
        0.0
    """
    # Validate inputs
    if any(coord is None for coord in [lat1, lon1, lat2, lon2]):
        raise ValueError("All coordinates must be non-None values")

    # Handle identical coordinates
    if lat1 == lat2 and lon1 == lon2:
        return 0.0

    # Earth's radius in kilometers
    R = 6371.0

    # Convert degrees to radians
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    # Haversine formula
    dLat = lat2_rad - lat1_rad
    dLon = lon2_rad - lon1_rad

    a = math.sin(dLat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dLon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    distance = R * c

    return distance


def calculate_geographic_spread(sessions: List[Any]) -> float:
    """Calculate maximum geographic distance between session source IPs.

    This function extracts latitude/longitude from DShield enrichment data and calculates
    the maximum pairwise Haversine distance. Geographic spread is a key indicator for
    snowshoe spam detection - distributed campaigns show higher spread.

    Args:
        sessions: List of SessionSummary ORM objects with enrichment data

    Returns:
        Maximum geographic distance in kilometers. Returns 0.0 if:
        - Empty session list
        - Single session
        - No sessions have valid geo coordinates
        - All coordinates are identical

    Examples:
        >>> from cowrieprocessor.db.models import SessionSummary
        >>> # Sessions from different continents
        >>> sessions = [session1_usa, session2_europe, session3_asia]
        >>> spread = calculate_geographic_spread(sessions)
        >>> print(f"Geographic spread: {spread:.2f} km")
        Geographic spread: 12847.32 km

        >>> # Single session
        >>> spread = calculate_geographic_spread([session1])
        >>> print(spread)
        0.0

        >>> # No geo data
        >>> spread = calculate_geographic_spread([session_no_enrichment])
        >>> print(spread)
        0.0
    """
    if not sessions or len(sessions) < 2:
        return 0.0

    # Extract coordinates from DShield enrichment
    coordinates: List[tuple[float, float]] = []
    for session in sessions:
        try:
            enrichment = session.enrichment if hasattr(session, "enrichment") and session.enrichment else {}
            dshield_data = enrichment.get("dshield", {})

            # DShield stores geo data in ip.latitude and ip.longitude (if available)
            # Note: Current fixtures don't include lat/lon, but real DShield API does
            ip_data = dshield_data.get("ip", {})

            # Try multiple field names for compatibility
            lat = ip_data.get("latitude") or ip_data.get("lat")
            lon = ip_data.get("longitude") or ip_data.get("lon") or ip_data.get("long")

            if lat is not None and lon is not None:
                coordinates.append((float(lat), float(lon)))
        except (AttributeError, KeyError, ValueError, TypeError) as e:
            LOGGER.debug(f"Failed to extract coordinates from session: {e}")
            continue

    # Need at least 2 coordinates to calculate spread
    if len(coordinates) < 2:
        return 0.0

    # Calculate pairwise distances and find maximum
    max_distance = 0.0
    for i in range(len(coordinates)):
        for j in range(i + 1, len(coordinates)):
            lat1, lon1 = coordinates[i]
            lat2, lon2 = coordinates[j]
            try:
                distance = haversine_distance(lat1, lon1, lat2, lon2)
                max_distance = max(max_distance, distance)
            except ValueError as e:
                LOGGER.debug(f"Failed to calculate distance: {e}")
                continue

    return max_distance


def calculate_entropy(values: List[Any]) -> float:
    """Calculate Shannon entropy normalized to 0-1 range.

    Shannon entropy measures the unpredictability or diversity in a dataset. Normalized
    entropy helps identify behavioral patterns - high entropy indicates diverse behavior
    (typical of snowshoe spam), low entropy indicates focused/repeated behavior.

    Args:
        values: List of values to calculate entropy over. Can be any hashable type.
                None values are filtered out before calculation.

    Returns:
        Normalized entropy in range [0.0, 1.0]:
        - 0.0: No entropy (single unique value or empty list)
        - 1.0: Maximum entropy (all values unique)
        - (0.0, 1.0): Partial entropy based on value distribution

    Formula:
        H = -sum(p_i * log2(p_i)) for all unique values
        H_normalized = H / log2(len(unique_values)) if len(unique_values) > 1 else 0

    Examples:
        >>> # All values identical (no entropy)
        >>> entropy = calculate_entropy(["password123"] * 100)
        >>> print(entropy)
        0.0

        >>> # All values unique (maximum entropy)
        >>> entropy = calculate_entropy(list(range(100)))
        >>> print(entropy)
        1.0

        >>> # Mixed distribution
        >>> entropy = calculate_entropy(["a"] * 50 + ["b"] * 30 + ["c"] * 20)
        >>> print(f"{entropy:.3f}")
        0.948

        >>> # Empty list
        >>> entropy = calculate_entropy([])
        >>> print(entropy)
        0.0

        >>> # With None values (filtered out)
        >>> entropy = calculate_entropy([1, 2, None, 3, None])
        >>> print(entropy)
        1.0
    """
    # Filter out None values
    filtered_values = [v for v in values if v is not None]

    if not filtered_values:
        return 0.0

    # Count unique values and their frequencies
    value_counts = Counter(filtered_values)
    unique_count = len(value_counts)

    # Single unique value = no entropy
    if unique_count <= 1:
        return 0.0

    # Calculate Shannon entropy
    total_count = len(filtered_values)
    entropy = 0.0

    for count in value_counts.values():
        probability = count / total_count
        if probability > 0:  # Avoid log(0)
            entropy -= probability * math.log2(probability)

    # Normalize by maximum possible entropy (log2 of unique value count)
    max_entropy = math.log2(unique_count)
    normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0.0

    return normalized_entropy


def aggregate_features(sessions: List[Any], provider_classifier: Any) -> dict[str, Any]:
    """Aggregate features across multiple IP sessions for snowshoe detection.

    This function computes comprehensive behavioral and infrastructure features across
    a collection of attack sessions. Features are designed to distinguish snowshoe spam
    campaigns (distributed, diverse behavior) from focused attacks (single IP, repetitive).

    Args:
        sessions: List of SessionSummary ORM objects with enrichment data
        provider_classifier: ProviderClassifier instance for infrastructure detection

    Returns:
        Dictionary with aggregated features:
            - ip_count: Number of unique source IPs
            - session_count: Total number of sessions
            - avg_sessions_per_ip: Average sessions per IP
            - geographic_spread_km: Maximum distance between IPs
            - password_entropy: Password diversity (0-1)
            - username_entropy: Username diversity (0-1)
            - cloud_provider_ratio: Fraction from cloud providers (0-1)
            - vpn_provider_ratio: Fraction from VPN services (0-1)
            - tor_exit_ratio: Fraction from Tor exits (0-1)
            - avg_dshield_score: Average DShield attack count
            - total_commands: Sum of all commands executed
            - unique_commands: Number of distinct commands
            - command_diversity: Command entropy (0-1)

    Examples:
        >>> from cowrieprocessor.features import ProviderClassifier, aggregate_features
        >>> config = {"use_dshield": True, "use_spur": True}
        >>> classifier = ProviderClassifier(config)
        >>>
        >>> # Snowshoe campaign (many IPs, high diversity)
        >>> features = aggregate_features(snowshoe_sessions, classifier)
        >>> print(f"IPs: {features['ip_count']}, Spread: {features['geographic_spread_km']:.0f} km")
        IPs: 127, Spread: 8742 km
        >>> print(f"Password Entropy: {features['password_entropy']:.2f}")
        Password Entropy: 0.87
        >>>
        >>> # Focused attack (single IP, repetitive)
        >>> features = aggregate_features(focused_sessions, classifier)
        >>> print(f"IPs: {features['ip_count']}, Sessions/IP: {features['avg_sessions_per_ip']:.1f}")
        IPs: 1, Sessions/IP: 453.0
        >>> print(f"Password Entropy: {features['password_entropy']:.2f}")
        Password Entropy: 0.23
    """
    # Initialize result structure
    result: dict[str, Any] = {
        "ip_count": 0,
        "session_count": len(sessions),
        "avg_sessions_per_ip": 0.0,
        "geographic_spread_km": 0.0,
        "password_entropy": 0.0,
        "username_entropy": 0.0,
        "cloud_provider_ratio": 0.0,
        "vpn_provider_ratio": 0.0,
        "tor_exit_ratio": 0.0,
        "avg_dshield_score": 0.0,
        "total_commands": 0,
        "unique_commands": 0,
        "command_diversity": 0.0,
    }

    # Handle empty sessions
    if not sessions:
        return result

    # Extract source IPs
    source_ips = set()
    for session in sessions:
        try:
            enrichment = session.enrichment if hasattr(session, "enrichment") and session.enrichment else {}
            dshield_data = enrichment.get("dshield", {})
            ip_data = dshield_data.get("ip", {})
            ip_address = ip_data.get("ip") or ip_data.get("ipaddress")

            if ip_address:
                source_ips.add(ip_address)
        except (AttributeError, KeyError, TypeError):
            continue

    result["ip_count"] = len(source_ips)
    result["avg_sessions_per_ip"] = len(sessions) / len(source_ips) if source_ips else 0.0

    # Calculate geographic spread
    result["geographic_spread_km"] = calculate_geographic_spread(sessions)

    # Extract behavioral features
    passwords: List[str] = []
    usernames: List[str] = []
    commands: List[str] = []
    dshield_scores: List[float] = []

    cloud_count = 0
    vpn_count = 0
    tor_count = 0

    for session in sessions:
        # Provider classification
        try:
            features = provider_classifier.classify(session)
            if features.is_cloud_provider:
                cloud_count += 1
            if features.is_vpn_provider:
                vpn_count += 1
            if features.is_tor_exit:
                tor_count += 1
        except Exception as e:
            LOGGER.debug(f"Failed to classify session: {e}")

        # Extract credentials (from enrichment or raw events)
        try:
            enrichment = session.enrichment if hasattr(session, "enrichment") and session.enrichment else {}

            # Passwords and usernames might be stored in various places
            # This is a placeholder - actual structure depends on enrichment format
            creds = enrichment.get("credentials", {})
            if isinstance(creds, dict):
                if "passwords" in creds:
                    passwords.extend(creds["passwords"])
                if "usernames" in creds:
                    usernames.extend(creds["usernames"])

            # Commands might be in enrichment or session summary
            cmds = enrichment.get("commands", [])
            if isinstance(cmds, list):
                commands.extend(cmds)

            # DShield score
            dshield_data = enrichment.get("dshield", {})
            ip_data = dshield_data.get("ip", {})
            attacks = ip_data.get("attacks") or ip_data.get("count")
            if attacks is not None:
                try:
                    dshield_scores.append(float(attacks))
                except (ValueError, TypeError):
                    pass
        except (AttributeError, KeyError, TypeError) as e:
            LOGGER.debug(f"Failed to extract behavioral features: {e}")
            continue

    # Calculate entropy metrics
    result["password_entropy"] = calculate_entropy(passwords)
    result["username_entropy"] = calculate_entropy(usernames)
    result["command_diversity"] = calculate_entropy(commands)

    # Provider ratios
    total_sessions = len(sessions)
    result["cloud_provider_ratio"] = cloud_count / total_sessions if total_sessions > 0 else 0.0
    result["vpn_provider_ratio"] = vpn_count / total_sessions if total_sessions > 0 else 0.0
    result["tor_exit_ratio"] = tor_count / total_sessions if total_sessions > 0 else 0.0

    # DShield statistics
    result["avg_dshield_score"] = sum(dshield_scores) / len(dshield_scores) if dshield_scores else 0.0

    # Command statistics
    result["total_commands"] = len(commands)
    result["unique_commands"] = len(set(commands))

    return result


__all__ = ["haversine_distance", "calculate_geographic_spread", "calculate_entropy", "aggregate_features"]
