"""SSH key intelligence analytics and campaign detection."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple, cast

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..db.models import SessionSSHKeys, SSHKeyAssociations, SSHKeyIntelligence

logger = logging.getLogger(__name__)


@dataclass
class CampaignInfo:
    """Information about a detected SSH key campaign.

    Attributes:
        campaign_id: Unique identifier for the campaign
        key_fingerprints: Set of SSH key fingerprints in this campaign
        total_sessions: Total number of sessions using these keys
        unique_ips: Number of unique source IPs
        date_range: Tuple of (first_seen, last_seen) dates
        confidence_score: Campaign confidence score (0.0 to 1.0)
        key_types: Set of SSH key types used
        injection_methods: Set of injection methods used
    """

    campaign_id: str
    key_fingerprints: Set[str]
    total_sessions: int
    unique_ips: int
    date_range: Tuple[datetime, datetime]
    confidence_score: float
    key_types: Set[str]
    injection_methods: Set[str]


@dataclass
class KeyTimeline:
    """Timeline information for an SSH key.

    Attributes:
        key_fingerprint: SSH key fingerprint
        key_type: Type of SSH key (RSA, Ed25519, etc.)
        first_seen: First time this key was observed
        last_seen: Last time this key was observed
        total_attempts: Total number of injection attempts
        unique_sources: Number of unique source IPs
        unique_sessions: Number of unique sessions
        sessions: List of session information
    """

    key_fingerprint: str
    key_type: str
    first_seen: Optional[datetime]
    last_seen: Optional[datetime]
    total_attempts: int
    unique_sources: int
    unique_sessions: int
    sessions: List[Dict[str, Any]]


@dataclass
class KeyAssociation:
    """Association between two SSH keys.

    Attributes:
        key1_fingerprint: First key fingerprint
        key2_fingerprint: Second key fingerprint
        co_occurrence_count: Number of times these keys were used together
        same_session_count: Number of sessions using both keys
        same_ip_count: Number of IPs using both keys
        association_strength: Calculated association strength (0.0 to 1.0)
    """

    key1_fingerprint: str
    key2_fingerprint: str
    co_occurrence_count: int
    same_session_count: int
    same_ip_count: int
    association_strength: float


class SSHKeyAnalytics:
    """Analytics engine for SSH key intelligence data."""

    def __init__(self, session: Session):
        """Initialize the analytics engine.

        Args:
            session: Database session
        """
        self.session = session

    def identify_campaigns(
        self,
        min_attempts: int = 5,
        min_ips: int = 3,
        min_keys: int = 2,
        days_back: int = 90,
        confidence_threshold: float = 0.6,
    ) -> List[CampaignInfo]:
        """Identify coordinated SSH key campaigns.

        Args:
            min_attempts: Minimum total attempts for campaign consideration
            min_ips: Minimum unique IPs for campaign consideration
            min_keys: Minimum number of keys for campaign consideration
            days_back: Number of days to look back for campaign analysis
            confidence_threshold: Minimum confidence score for campaign inclusion

        Returns:
            List of detected campaigns
        """
        cutoff_date = datetime.now() - timedelta(days=days_back)

        # Find keys that meet minimum criteria
        stmt = select(SSHKeyIntelligence).where(
            and_(
                SSHKeyIntelligence.total_attempts >= min_attempts,
                SSHKeyIntelligence.unique_sources >= min_ips,
                SSHKeyIntelligence.last_seen >= cutoff_date,
            )
        )
        candidate_keys = self.session.execute(stmt).scalars().all()

        if len(candidate_keys) < min_keys:
            return []

        # Build key association graph
        associations = self._build_association_graph(list(candidate_keys))

        # Find connected components (campaigns)
        campaigns = self._find_connected_campaigns(associations, list(candidate_keys), confidence_threshold)

        # Filter campaigns by minimum criteria
        filtered_campaigns = []
        for campaign in campaigns:
            if (
                campaign.total_sessions >= min_attempts
                and campaign.unique_ips >= min_ips
                and len(campaign.key_fingerprints) >= min_keys
            ):
                filtered_campaigns.append(campaign)

        return filtered_campaigns

    def get_key_timeline(self, key_fingerprint: str) -> Optional[KeyTimeline]:
        """Get detailed timeline information for a specific SSH key.

        Args:
            key_fingerprint: SSH key fingerprint to analyze

        Returns:
            KeyTimeline object or None if key not found
        """
        stmt = select(SSHKeyIntelligence).where(SSHKeyIntelligence.key_fingerprint == key_fingerprint)
        key_record = self.session.execute(stmt).scalar_one_or_none()

        if not key_record:
            return None

        # Get session details
        session_stmt = (
            select(SessionSSHKeys).where(SessionSSHKeys.ssh_key_id == key_record.id).order_by(SessionSSHKeys.timestamp)
        )
        sessions = self.session.execute(session_stmt).scalars().all()

        session_info = []
        for session in sessions:
            session_info.append(
                {
                    "session_id": session.session_id,
                    "source_ip": session.source_ip,
                    "injection_method": session.injection_method,
                    "timestamp": session.timestamp,
                    "command_preview": (
                        session.command_text[:100] + "..." if len(session.command_text) > 100 else session.command_text
                    ),
                }
            )

        return KeyTimeline(
            key_fingerprint=str(key_record.key_fingerprint),
            key_type=str(key_record.key_type),
            first_seen=cast(Optional[datetime], key_record.first_seen),
            last_seen=cast(Optional[datetime], key_record.last_seen),
            total_attempts=int(key_record.total_attempts),
            unique_sources=int(key_record.unique_sources),
            unique_sessions=int(key_record.unique_sessions),
            sessions=session_info,
        )

    def find_related_keys(
        self,
        key_fingerprint: str,
        min_association_strength: float = 0.3,
        max_results: int = 10,
    ) -> List[KeyAssociation]:
        """Find keys that are associated with the given key.

        Args:
            key_fingerprint: SSH key fingerprint to find associations for
            min_association_strength: Minimum association strength threshold
            max_results: Maximum number of results to return

        Returns:
            List of key associations
        """
        # Find the key record
        stmt = select(SSHKeyIntelligence).where(SSHKeyIntelligence.key_fingerprint == key_fingerprint)
        key_record = self.session.execute(stmt).scalar_one_or_none()

        if not key_record:
            return []

        # Find associations
        assoc_stmt = select(SSHKeyAssociations).where(
            (SSHKeyAssociations.key_id_1 == key_record.id) | (SSHKeyAssociations.key_id_2 == key_record.id)
        )
        associations = self.session.execute(assoc_stmt).scalars().all()

        # Get related key information and calculate association strength
        related_keys = []
        for assoc in associations:
            # Determine which key is the related one
            if assoc.key_id_1 == key_record.id:
                related_key_id = assoc.key_id_2
            else:
                related_key_id = assoc.key_id_1

            related_stmt = select(SSHKeyIntelligence).where(SSHKeyIntelligence.id == related_key_id)
            related_key = self.session.execute(related_stmt).scalar_one_or_none()

            if related_key:
                # Calculate association strength based on co-occurrence
                total_attempts = key_record.total_attempts + related_key.total_attempts
                association_strength = assoc.co_occurrence_count / total_attempts if total_attempts > 0 else 0.0

                if association_strength >= min_association_strength:
                    related_keys.append(
                        KeyAssociation(
                            key1_fingerprint=str(key_record.key_fingerprint),
                            key2_fingerprint=str(related_key.key_fingerprint),
                            co_occurrence_count=int(assoc.co_occurrence_count),
                            same_session_count=int(assoc.same_session_count),
                            same_ip_count=int(assoc.same_ip_count),
                            association_strength=float(association_strength),
                        )
                    )

        # Sort by association strength and return top results
        related_keys.sort(key=lambda x: x.association_strength, reverse=True)
        return related_keys[:max_results]

    def calculate_geographic_spread(self, key_fingerprint: str) -> Dict[str, Any]:
        """Calculate geographic spread metrics for an SSH key.

        Args:
            key_fingerprint: SSH key fingerprint to analyze

        Returns:
            Dictionary with geographic spread metrics
        """
        stmt = select(SSHKeyIntelligence).where(SSHKeyIntelligence.key_fingerprint == key_fingerprint)
        key_record = self.session.execute(stmt).scalar_one_or_none()

        if not key_record:
            return {}

        # Get unique source IPs from sessions using this key
        ip_stmt = (
            select(SessionSSHKeys.source_ip)
            .where(and_(SessionSSHKeys.ssh_key_id == key_record.id, SessionSSHKeys.source_ip.isnot(None)))
            .distinct()
        )
        sessions = self.session.execute(ip_stmt).scalars().all()

        unique_ips = [ip for ip in sessions if ip]

        # Calculate basic metrics
        ip_count = len(unique_ips)

        # Group IPs by /24 subnet (basic geographic clustering)
        subnets: dict[str, int] = defaultdict(int)
        for ip in unique_ips:
            if '.' in ip:  # IPv4
                subnet = '.'.join(ip.split('.')[:-1]) + '.0/24'
                subnets[subnet] += 1
            else:  # IPv6 - use /64 subnet
                subnet = ':'.join(ip.split(':')[:4]) + '::/64'
                subnets[subnet] += 1

        subnet_count = len(subnets)
        max_subnet_ips = max(subnets.values()) if subnets else 0

        # Calculate spread diversity (lower is more concentrated)
        spread_diversity = subnet_count / ip_count if ip_count > 0 else 0.0

        return {
            "unique_ips": ip_count,
            "unique_subnets": subnet_count,
            "max_ips_per_subnet": max_subnet_ips,
            "spread_diversity": spread_diversity,
            "subnet_distribution": dict(subnets),
        }

    def get_top_keys_by_usage(self, days_back: int = 30, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top SSH keys by usage in the specified time period.

        Args:
            days_back: Number of days to look back
            limit: Maximum number of results

        Returns:
            List of key usage statistics
        """
        cutoff_date = datetime.now() - timedelta(days=days_back)

        keys_stmt = (
            select(SSHKeyIntelligence)
            .where(SSHKeyIntelligence.last_seen >= cutoff_date)
            .order_by(SSHKeyIntelligence.total_attempts.desc(), SSHKeyIntelligence.unique_sources.desc())
            .limit(limit)
        )
        keys = self.session.execute(keys_stmt).scalars().all()

        results = []
        for key in keys:
            results.append(
                {
                    "key_fingerprint": key.key_fingerprint,
                    "key_type": key.key_type,
                    "total_attempts": key.total_attempts,
                    "unique_sources": key.unique_sources,
                    "unique_sessions": key.unique_sessions,
                    "first_seen": key.first_seen,
                    "last_seen": key.last_seen,
                    "key_size_bits": key.key_bits,
                }
            )

        return results

    def _build_association_graph(self, keys: List[SSHKeyIntelligence]) -> Dict[int, Set[int]]:
        """Build an association graph from key relationships.

        Args:
            keys: List of SSH key intelligence records

        Returns:
            Dictionary mapping key IDs to sets of associated key IDs
        """
        graph: dict[int, set[int]] = defaultdict(set)
        key_ids = {key.id for key in keys}

        # Get all associations between candidate keys
        graph_stmt = select(SSHKeyAssociations).where(
            and_(SSHKeyAssociations.key_id_1.in_(key_ids), SSHKeyAssociations.key_id_2.in_(key_ids))
        )
        associations = self.session.execute(graph_stmt).scalars().all()

        for assoc in associations:
            graph[int(assoc.key_id_1)].add(int(assoc.key_id_2))
            graph[int(assoc.key_id_2)].add(int(assoc.key_id_1))

        return dict(graph)

    def _find_connected_campaigns(
        self,
        graph: Dict[int, Set[int]],
        keys: List[SSHKeyIntelligence],
        confidence_threshold: float,
    ) -> List[CampaignInfo]:
        """Find connected components in the association graph as campaigns.

        Args:
            graph: Association graph
            keys: List of SSH key intelligence records
            confidence_threshold: Minimum confidence for campaign inclusion

        Returns:
            List of detected campaigns
        """
        visited: set[int] = set()
        campaigns = []
        campaign_id = 0

        key_map: dict[int, SSHKeyIntelligence] = {int(key.id): key for key in keys}

        for key in keys:
            if key.id not in visited:
                # Start DFS to find connected component
                component = self._dfs_component(int(key.id), graph, visited)

                if len(component) >= 2:  # Campaign needs at least 2 keys
                    campaign_id += 1

                    # Calculate campaign metrics
                    campaign_keys = [key_map[key_id] for key_id in component]

                    total_sessions = sum(int(key.unique_sessions) for key in campaign_keys)
                    unique_ips: set[str] = set()
                    key_types: set[str] = set()
                    injection_methods: set[str] = set()
                    first_seen = None
                    last_seen = None

                    for key_record in campaign_keys:
                        key_types.add(str(key_record.key_type))
                        if key_record.first_seen:
                            if first_seen is None or key_record.first_seen < first_seen:
                                first_seen = key_record.first_seen
                        if key_record.last_seen:
                            if last_seen is None or key_record.last_seen > last_seen:
                                last_seen = key_record.last_seen

                    # Get injection methods from sessions
                    for key_record in campaign_keys:
                        method_stmt = (
                            select(SessionSSHKeys.injection_method)
                            .where(SessionSSHKeys.ssh_key_id == key_record.id)
                            .distinct()
                        )
                        sessions = self.session.execute(method_stmt).scalars().all()
                        for method in sessions:
                            if method:
                                injection_methods.add(method)

                    # Calculate confidence score based on key diversity and usage patterns
                    confidence_score = self._calculate_campaign_confidence(
                        campaign_keys, total_sessions, len(unique_ips)
                    )

                    if confidence_score >= confidence_threshold:
                        campaigns.append(
                            CampaignInfo(
                                campaign_id=f"campaign_{campaign_id}",
                                key_fingerprints={str(key.key_fingerprint) for key in campaign_keys},
                                total_sessions=total_sessions,
                                unique_ips=len(unique_ips),
                                date_range=(
                                    cast(datetime, first_seen) if first_seen else datetime.min,
                                    cast(datetime, last_seen) if last_seen else datetime.min,
                                ),
                                confidence_score=confidence_score,
                                key_types=key_types,
                                injection_methods=injection_methods,
                            )
                        )

        return campaigns

    def _dfs_component(self, start_key_id: int, graph: Dict[int, Set[int]], visited: Set[int]) -> Set[int]:
        """Perform depth-first search to find connected component.

        Args:
            start_key_id: Starting key ID
            graph: Association graph
            visited: Set of visited key IDs

        Returns:
            Set of key IDs in the connected component
        """
        stack = [start_key_id]
        component = set()

        while stack:
            key_id = stack.pop()
            if key_id not in visited:
                visited.add(key_id)
                component.add(key_id)

                # Add neighbors to stack
                for neighbor in graph.get(key_id, set()):
                    if neighbor not in visited:
                        stack.append(neighbor)

        return component

    def _calculate_campaign_confidence(
        self,
        keys: List[SSHKeyIntelligence],
        total_sessions: int,
        unique_ips: int,
    ) -> float:
        """Calculate confidence score for a campaign.

        Args:
            keys: List of SSH keys in the campaign
            total_sessions: Total number of sessions
            unique_ips: Number of unique IPs

        Returns:
            Confidence score between 0.0 and 1.0
        """
        # Base confidence on key diversity, usage volume, and IP spread
        key_diversity = len(set(key.key_type for key in keys)) / 4.0  # Max 4 key types
        usage_volume = min(total_sessions / 100.0, 1.0)  # Normalize to 100 sessions
        ip_spread = min(unique_ips / 20.0, 1.0)  # Normalize to 20 IPs

        # Weighted average
        confidence = key_diversity * 0.3 + usage_volume * 0.4 + ip_spread * 0.3
        return min(confidence, 1.0)
