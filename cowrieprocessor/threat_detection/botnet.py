"""Botnet coordination detection algorithms for Cowrie Processor.

This module implements detection algorithms for coordinated botnet attacks,
where multiple compromised machines execute similar commands using shared
credentials, SSH keys, or other coordination mechanisms.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ..db.models import CommandStat, RawEvent, SessionSummary

logger = logging.getLogger(__name__)


class BotnetCoordinatorDetector:
    """Detects coordinated botnet attacks using multiple analysis techniques.

    Botnet coordination is characterized by:
    - Shared credentials (username/password reuse across IPs)
    - Similar command sequences across IPs
    - SSH key reuse patterns (if available)
    - Coordinated timing patterns
    - Geographic clustering of compromised hosts

    This detector uses a composite scoring approach to identify these patterns.
    """

    def __init__(
        self,
        credential_reuse_threshold: int = 3,  # Min IPs sharing same credentials
        command_similarity_threshold: float = 0.7,  # Min similarity for command sequences
        time_cluster_eps: float = 0.5,  # Hours for temporal clustering
        min_cluster_size: int = 3,  # Min IPs in temporal cluster
        geographic_cluster_threshold: float = 0.3,  # Max geographic diversity for clustering
        sensitivity_threshold: float = 0.6,  # Overall detection threshold
    ) -> None:
        """Initialize the botnet coordinator detector.

        Args:
            credential_reuse_threshold: Minimum IPs sharing same credentials to flag
            command_similarity_threshold: Minimum similarity for command sequences
            time_cluster_eps: DBSCAN epsilon for temporal clustering (hours)
            min_cluster_size: Minimum cluster size for DBSCAN
            geographic_cluster_threshold: Maximum geographic diversity for clustering
            sensitivity_threshold: Overall detection sensitivity (0.0-1.0)
        """
        self.credential_reuse_threshold = credential_reuse_threshold
        self.command_similarity_threshold = command_similarity_threshold
        self.time_cluster_eps = time_cluster_eps
        self.min_cluster_size = min_cluster_size
        self.geographic_cluster_threshold = geographic_cluster_threshold
        self.sensitivity_threshold = sensitivity_threshold

    def detect(
        self,
        sessions: List[SessionSummary],
        window_hours: float = 24.0,
        command_stats: Optional[List[CommandStat]] = None,
        raw_events: Optional[List[RawEvent]] = None,
    ) -> Dict[str, Any]:
        """Detect coordinated botnet activity in session data.

        Args:
            sessions: List of session summaries to analyze
            window_hours: Analysis time window in hours
            command_stats: Optional command statistics for similarity analysis
            raw_events: Optional raw events for credential extraction

        Returns:
            Dictionary containing detection results and analysis metadata
        """
        try:
            if not sessions or len(sessions) < 10:
                return self._empty_result("Insufficient session data for analysis")

            # Extract coordination data from sessions
            coordination_data = self._extract_coordination_data(sessions, command_stats, raw_events)

            if len(coordination_data["ips"]) < 5:
                return self._empty_result("Insufficient IP diversity for coordination analysis")

            # Analyze different coordination patterns
            credential_analysis = self._analyze_credential_reuse(coordination_data)
            command_analysis = self._analyze_command_similarity(coordination_data)
            timing_analysis = self._analyze_temporal_coordination(coordination_data, window_hours)
            geographic_analysis = self._analyze_geographic_clustering(coordination_data)

            # Calculate composite botnet coordination score
            coordination_score = self._calculate_coordination_score(
                credential_analysis,
                command_analysis,
                timing_analysis,
                geographic_analysis,
            )

            # Generate recommendation
            is_coordinated = coordination_score >= self.sensitivity_threshold
            recommendation = self._generate_recommendation(
                coordination_score,
                credential_analysis,
                command_analysis,
                timing_analysis,
                geographic_analysis,
            )

            return {
                "is_likely_botnet": is_coordinated,
                "coordination_score": round(coordination_score, 6),
                "credential_reuse_ips": list(credential_analysis["reused_credentials"]),
                "similar_command_ips": list(command_analysis["similar_commands"]),
                "coordinated_timing": timing_analysis["has_clustering"],
                "geographic_clustering": geographic_analysis["is_clustered"],
                "recommendation": recommendation,
                "indicators": {
                    "credentials": credential_analysis,
                    "commands": command_analysis,
                    "timing": timing_analysis,
                    "geographic": geographic_analysis,
                },
                "analysis_metadata": {
                    "total_sessions": len(sessions),
                    "unique_ips": len(coordination_data["ips"]),
                    "window_hours": window_hours,
                    "analysis_timestamp": datetime.now(UTC).isoformat(),
                },
            }

        except Exception as e:
            logger.error("Botnet coordination detection failed: %s", str(e), exc_info=True)
            return self._empty_result(f"Analysis error: {str(e)}")

    def _extract_coordination_data(
        self,
        sessions: List[SessionSummary],
        command_stats: Optional[List[CommandStat]] = None,
        raw_events: Optional[List[RawEvent]] = None,
    ) -> Dict[str, Any]:
        """Extract coordination-relevant data from sessions."""
        ip_data = {}
        credential_data = defaultdict(list)  # credential_hash -> [ips]
        command_data = defaultdict(list)  # ip -> [commands]

        # Process sessions for IP and credential data
        for session in sessions:
            ip = self._extract_ip_from_session(session)
            if not ip:
                continue

            if ip not in ip_data:
                ip_data[ip] = {
                    "sessions": [],
                    "timestamps": [],
                    "countries": set(),
                    "asns": set(),
                    "credentials": set(),
                    "commands": [],
                    "session_durations": [],
                }

            ip_data[ip]["sessions"].append(session)

            # Extract timestamp
            if session.first_event_at:
                ip_data[ip]["timestamps"].append(session.first_event_at)

            # Extract geographic data
            if session.enrichment:
                geo_data = self._extract_geographic_data(session.enrichment)
                ip_data[ip]["countries"].update(geo_data.get("countries", []))
                ip_data[ip]["asns"].update(geo_data.get("asns", []))

            # Extract credentials
            credentials = self._extract_credentials(session, raw_events)
            if credentials:
                credential_hash = self._hash_credentials(credentials)
                ip_data[ip]["credentials"].add(credential_hash)
                credential_data[credential_hash].append(ip)

            # Extract commands
            commands = self._extract_commands(session, command_stats, raw_events)
            if commands:
                ip_data[ip]["commands"].extend(commands)
                command_data[ip] = commands

            # Extract session duration
            if session.first_event_at and session.last_event_at:
                duration = (session.last_event_at - session.first_event_at).total_seconds()
                ip_data[ip]["session_durations"].append(duration)

        return {
            "ips": ip_data,
            "credential_data": credential_data,
            "command_data": command_data,
        }

    def _extract_ip_from_session(self, session: SessionSummary) -> Optional[str]:
        """Extract IP address from session enrichment data."""
        try:
            if not session.enrichment:
                return None

            enrichment = session.enrichment
            if isinstance(enrichment, dict) and "session" in enrichment:
                session_data = enrichment["session"]
                if isinstance(session_data, dict):
                    for key in session_data.keys():
                        try:
                            ip_obj = ipaddress.ip_address(key)
                            # For botnet detection, allow private IPs since botnets often use
                            # compromised internal networks
                            # Only reject loopback and link-local addresses
                            if not (ip_obj.is_loopback or ip_obj.is_link_local):
                                return key
                        except ValueError:
                            continue
            return None
        except Exception:
            return None

    def _extract_geographic_data(self, enrichment: Dict[str, Any]) -> Dict[str, List[str]]:
        """Extract geographic data from enrichment."""
        countries = []
        asns = []

        try:
            if isinstance(enrichment, dict) and "session" in enrichment:
                session_data = enrichment["session"]
                if isinstance(session_data, dict):
                    for ip_data in session_data.values():
                        if isinstance(ip_data, dict) and "spur" in ip_data:
                            spur_data = ip_data["spur"]
                            if isinstance(spur_data, dict):
                                if "country" in spur_data:
                                    countries.append(spur_data["country"])
                                if "asn" in spur_data:
                                    asns.append(spur_data["asn"])
        except Exception:
            pass

        return {"countries": countries, "asns": asns}

    def _extract_credentials(
        self,
        session: SessionSummary,
        raw_events: Optional[List[RawEvent]] = None,
    ) -> Optional[Dict[str, str]]:
        """Extract credentials from session or raw events."""
        # Try to extract from raw events first
        if raw_events:
            for event in raw_events:
                if (
                    event.session_id == session.session_id
                    and event.event_type == "cowrie.login.success"
                    and event.payload
                ):
                    username = event.payload.get("username")
                    password = event.payload.get("password")
                    if username and password:
                        return {"username": username, "password": password}

        # Fallback: try to extract from session enrichment or other sources
        # This would need to be implemented based on how credentials are stored
        return None

    def _hash_credentials(self, credentials: Dict[str, str]) -> str:
        """Create a hash of credentials for comparison."""
        cred_string = f"{credentials.get('username', '')}:{credentials.get('password', '')}"
        return hashlib.sha256(cred_string.encode()).hexdigest()

    def _extract_commands(
        self,
        session: SessionSummary,
        command_stats: Optional[List[CommandStat]] = None,
        raw_events: Optional[List[RawEvent]] = None,
    ) -> List[str]:
        """Extract command sequences from session, command stats, or raw events."""
        commands = []

        # Try to extract from command stats first
        if command_stats:
            for cmd_stat in command_stats:
                if cmd_stat.session_id == session.session_id:
                    commands.append(cmd_stat.command_normalized)

        # Try to extract from raw events
        if raw_events and not commands:
            for event in raw_events:
                if (
                    event.session_id == session.session_id
                    and event.event_type == "cowrie.command.input"
                    and event.payload
                ):
                    command = event.payload.get("input")
                    if command:
                        commands.append(command)

        return commands

    def _analyze_credential_reuse(self, coordination_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze credential reuse patterns across IPs."""
        credential_data = coordination_data["credential_data"]

        reused_credentials = set()
        credential_reuse_count = 0
        total_credential_ips = 0

        for credential_hash, ips in credential_data.items():
            if len(ips) >= self.credential_reuse_threshold:
                reused_credentials.update(ips)
                credential_reuse_count += len(ips)
            total_credential_ips += len(ips)

        reuse_ratio = credential_reuse_count / total_credential_ips if total_credential_ips > 0 else 0

        return {
            "reused_credentials": reused_credentials,
            "credential_reuse_count": credential_reuse_count,
            "total_credential_ips": total_credential_ips,
            "reuse_ratio": reuse_ratio,
            "has_credential_reuse": len(reused_credentials) > 0,
        }

    def _analyze_command_similarity(self, coordination_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze command sequence similarity across IPs."""
        command_data = coordination_data["command_data"]

        if len(command_data) < 2:
            return {
                "similar_commands": set(),
                "similarity_score": 0.0,
                "has_similar_commands": False,
                "avg_similarity": 0.0,
            }

        # Convert commands to text for similarity analysis
        command_texts = []
        ip_list = list(command_data.keys())

        for ip in ip_list:
            commands = command_data[ip]
            command_text = " ".join(commands)
            command_texts.append(command_text)

        if not command_texts or all(not text.strip() for text in command_texts):
            return {
                "similar_commands": set(),
                "similarity_score": 0.0,
                "has_similar_commands": False,
                "avg_similarity": 0.0,
            }

        # Calculate TF-IDF similarity
        try:
            vectorizer = TfidfVectorizer(max_features=1000, stop_words=None)
            tfidf_matrix = vectorizer.fit_transform(command_texts)
            similarity_matrix = cosine_similarity(tfidf_matrix)

            similar_pairs = []
            similarities = []

            for i in range(len(similarity_matrix)):
                for j in range(i + 1, len(similarity_matrix)):
                    similarity = similarity_matrix[i][j]
                    similarities.append(similarity)
                    if similarity >= self.command_similarity_threshold:
                        similar_pairs.append((ip_list[i], ip_list[j]))

            similar_ips = set()
            for ip1, ip2 in similar_pairs:
                similar_ips.add(ip1)
                similar_ips.add(ip2)

            avg_similarity = np.mean(similarities) if similarities else 0.0

            return {
                "similar_commands": similar_ips,
                "similarity_score": avg_similarity,
                "has_similar_commands": len(similar_ips) > 0,
                "avg_similarity": avg_similarity,
            }

        except Exception as e:
            logger.warning("Command similarity analysis failed: %s", str(e))
            return {
                "similar_commands": set(),
                "similarity_score": 0.0,
                "has_similar_commands": False,
                "avg_similarity": 0.0,
            }

    def _analyze_temporal_coordination(
        self,
        coordination_data: Dict[str, Any],
        window_hours: float,
    ) -> Dict[str, Any]:
        """Analyze temporal coordination patterns."""
        ip_data = coordination_data["ips"]

        if len(ip_data) < self.min_cluster_size:
            return {
                "has_clustering": False,
                "cluster_count": 0,
                "largest_cluster_size": 0,
                "coordination_score": 0.0,
                "clustered_points": 0,
            }

        # Prepare timestamps for clustering
        timestamps = []
        ip_list = []

        for ip, data in ip_data.items():
            for timestamp in data["timestamps"]:
                timestamps.append(timestamp.timestamp())
                ip_list.append(ip)

        if len(timestamps) < self.min_cluster_size:
            return {
                "has_clustering": False,
                "cluster_count": 0,
                "largest_cluster_size": 0,
                "coordination_score": 0.0,
                "clustered_points": 0,
            }

        # Perform DBSCAN clustering on timestamps
        timestamps_array = np.array(timestamps).reshape(-1, 1)
        eps_hours = self.time_cluster_eps
        eps_seconds = eps_hours * 3600

        clustering = DBSCAN(eps=eps_seconds, min_samples=self.min_cluster_size)
        cluster_labels = clustering.fit_predict(timestamps_array)

        # Analyze clustering results
        unique_labels = set(cluster_labels)
        unique_labels.discard(-1)  # Remove noise points

        cluster_count = len(unique_labels)
        clustered_points = len([label for label in cluster_labels if label != -1])

        # Find largest cluster
        largest_cluster_size = 0
        if unique_labels:
            cluster_sizes = Counter(cluster_labels)
            cluster_sizes.pop(-1, None)  # Remove noise
            if cluster_sizes:
                largest_cluster_size = max(cluster_sizes.values())

        # Calculate coordination score
        total_points = len(timestamps)
        coordination_score = clustered_points / total_points if total_points > 0 else 0.0

        return {
            "has_clustering": cluster_count > 0,
            "cluster_count": cluster_count,
            "largest_cluster_size": largest_cluster_size,
            "coordination_score": coordination_score,
            "clustered_points": clustered_points,
        }

    def _analyze_geographic_clustering(self, coordination_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze geographic clustering patterns."""
        ip_data = coordination_data["ips"]

        # Collect geographic data
        all_countries = set()
        all_asns = set()
        country_counts = Counter()
        asn_counts = Counter()

        for data in ip_data.values():
            all_countries.update(data["countries"])
            all_asns.update(data["asns"])
            country_counts.update(data["countries"])
            asn_counts.update(data["asns"])

        total_ips = len(ip_data)

        # Calculate diversity metrics
        country_diversity = len(all_countries) / total_ips if total_ips > 0 else 0
        asn_diversity = len(all_asns) / total_ips if total_ips > 0 else 0

        # Check for geographic clustering (low diversity)
        is_clustered = (
            country_diversity <= self.geographic_cluster_threshold or asn_diversity <= self.geographic_cluster_threshold
        )

        # Calculate clustering score (inverse of diversity)
        clustering_score = 1.0 - max(country_diversity, asn_diversity)

        return {
            "countries": list(all_countries),
            "asns": list(all_asns),
            "country_count": len(all_countries),
            "asn_count": len(all_asns),
            "country_diversity": country_diversity,
            "asn_diversity": asn_diversity,
            "clustering_score": clustering_score,
            "is_clustered": is_clustered,
        }

    def _calculate_coordination_score(
        self,
        credential_analysis: Dict[str, Any],
        command_analysis: Dict[str, Any],
        timing_analysis: Dict[str, Any],
        geographic_analysis: Dict[str, Any],
    ) -> float:
        """Calculate composite botnet coordination score."""
        # Weighted scoring based on different coordination indicators
        weights = {
            "credential": 0.4,  # Credential reuse is strong indicator
            "command": 0.3,  # Command similarity is important
            "timing": 0.2,  # Temporal coordination
            "geographic": 0.1,  # Geographic clustering (lower weight)
        }

        # Calculate individual scores
        credential_score = 1.0 if credential_analysis["has_credential_reuse"] else 0.0
        command_score = command_analysis["avg_similarity"]
        timing_score = timing_analysis["coordination_score"]
        geographic_score = geographic_analysis["clustering_score"]

        # Calculate weighted composite score
        composite_score = (
            weights["credential"] * credential_score
            + weights["command"] * command_score
            + weights["timing"] * timing_score
            + weights["geographic"] * geographic_score
        )

        return min(composite_score, 1.0)

    def _generate_recommendation(
        self,
        coordination_score: float,
        credential_analysis: Dict[str, Any],
        command_analysis: Dict[str, Any],
        timing_analysis: Dict[str, Any],
        geographic_analysis: Dict[str, Any],
    ) -> str:
        """Generate human-readable recommendation based on analysis."""
        if coordination_score >= 0.8:
            confidence = "HIGH"
        elif coordination_score >= 0.6:
            confidence = "MODERATE"
        elif coordination_score >= 0.4:
            confidence = "LOW"
        else:
            confidence = "MINIMAL"

        indicators = []

        if credential_analysis["has_credential_reuse"]:
            indicators.append(f"credential reuse ({len(credential_analysis['reused_credentials'])} IPs)")

        if command_analysis["has_similar_commands"]:
            indicators.append(f"command similarity ({len(command_analysis['similar_commands'])} IPs)")

        if timing_analysis["has_clustering"]:
            indicators.append(f"temporal coordination ({timing_analysis['cluster_count']} clusters)")

        if geographic_analysis["is_clustered"]:
            indicators.append(f"geographic clustering ({geographic_analysis['country_count']} countries)")

        if indicators:
            indicator_text = ", ".join(indicators)
            return f"{confidence} CONFIDENCE: Botnet coordination detected via {indicator_text}"
        else:
            return f"{confidence} CONFIDENCE: No clear botnet coordination patterns detected"

    def _empty_result(self, error: Optional[str] = None) -> Dict[str, Any]:
        """Return empty result structure for error cases."""
        result = {
            "is_likely_botnet": False,
            "coordination_score": 0.0,
            "credential_reuse_ips": [],
            "similar_command_ips": [],
            "coordinated_timing": False,
            "geographic_clustering": False,
            "recommendation": (
                "ERROR: Unable to complete analysis" if error else "NO DATA: Insufficient data for analysis"
            ),
            "indicators": {
                "credentials": {"reused_credentials": set(), "has_credential_reuse": False, "reuse_ratio": 0.0},
                "commands": {"similar_commands": set(), "has_similar_commands": False, "avg_similarity": 0.0},
                "timing": {"has_clustering": False, "cluster_count": 0, "coordination_score": 0.0},
                "geographic": {"is_clustered": False, "clustering_score": 0.0, "country_diversity": 0.0},
            },
            "analysis_metadata": {
                "total_sessions": 0,
                "unique_ips": 0,
                "window_hours": 24,
                "analysis_timestamp": datetime.now(UTC).isoformat(),
            },
        }
        if error:
            result["error"] = error
        return result


# Backward compatibility alias
SnowshoeDetector = BotnetCoordinatorDetector
