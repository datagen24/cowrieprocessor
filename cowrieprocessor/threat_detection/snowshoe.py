"""Snowshoe attack detection algorithms for Cowrie Processor.

This module implements detection algorithms for "snowshoe" spam attacks - distributed,
low-volume attacks from many IP addresses designed to evade traditional volume-based detection.
"""

from __future__ import annotations

import ipaddress
import logging
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

from ..db.models import SessionSummary

logger = logging.getLogger(__name__)


class SnowshoeDetector:
    """Detects snowshoe spam attacks using multiple analysis techniques.
    
    Snowshoe attacks use hundreds or thousands of IP addresses, each generating
    minimal traffic to stay under detection thresholds. This detector identifies
    such campaigns through:
    
    - Volume analysis (single-attempt IPs)
    - Time clustering detection (coordinated bursts)
    - Geographic diversity analysis
    - Behavioral similarity analysis
    """
    
    def __init__(
        self,
        single_attempt_threshold: int = 5,
        time_cluster_eps: float = 0.1,
        min_cluster_size: int = 5,
        geographic_diversity_threshold: float = 0.7,
        sensitivity_threshold: float = 0.7,
    ) -> None:
        """Initialize the snowshoe detector.
        
        Args:
            single_attempt_threshold: Maximum attempts per IP to consider "single-attempt"
            time_cluster_eps: DBSCAN epsilon parameter for time clustering (hours)
            min_cluster_size: Minimum cluster size for DBSCAN
            geographic_diversity_threshold: Minimum geographic diversity score
            sensitivity_threshold: Minimum confidence score for snowshoe detection
        """
        self.single_attempt_threshold = single_attempt_threshold
        self.time_cluster_eps = time_cluster_eps
        self.min_cluster_size = min_cluster_size
        self.geographic_diversity_threshold = geographic_diversity_threshold
        self.sensitivity_threshold = sensitivity_threshold
        
        logger.info(
            "Initialized SnowshoeDetector with thresholds: single_attempt=%d, "
            "time_cluster_eps=%.2f, min_cluster_size=%d, geo_diversity=%.2f, sensitivity=%.2f",
            single_attempt_threshold,
            time_cluster_eps,
            min_cluster_size,
            geographic_diversity_threshold,
            sensitivity_threshold,
        )
    
    def detect(
        self, 
        sessions: List[SessionSummary], 
        window_hours: int = 24
    ) -> Dict[str, Any]:
        """Detect snowshoe attacks in the given session data.
        
        Args:
            sessions: List of session summaries to analyze
            window_hours: Time window for analysis in hours
            
        Returns:
            Dictionary containing detection results with:
            - is_likely_snowshoe: Boolean indicating if snowshoe attack detected
            - confidence_score: Float confidence score (0.0-1.0)
            - single_attempt_ips: List of IPs with minimal activity
            - low_volume_ips: List of IPs with low volume activity
            - coordinated_timing: Boolean indicating coordinated timing patterns
            - geographic_spread: Float geographic diversity score
            - recommendation: String recommendation for action
            - indicators: Detailed breakdown of detection indicators
        """
        if not sessions:
            logger.warning("No sessions provided for snowshoe detection")
            return self._empty_result()
        
        logger.info("Starting snowshoe detection analysis on %d sessions", len(sessions))
        
        try:
            # Extract IP addresses and timestamps
            ip_data = self._extract_ip_data(sessions)
            
            if len(ip_data) < 10:  # Need minimum IPs for meaningful analysis
                logger.info("Insufficient IP diversity (%d IPs) for snowshoe detection", len(ip_data))
                return self._empty_result()
            
            # Perform individual analyses
            volume_indicators = self._analyze_volume_patterns(ip_data)
            timing_indicators = self._analyze_timing_patterns(ip_data, window_hours)
            geographic_indicators = self._analyze_geographic_diversity(ip_data)
            behavioral_indicators = self._analyze_behavioral_similarity(ip_data, sessions)
            
            # Calculate composite score
            confidence_score = self._calculate_snowshoe_score({
                "volume": volume_indicators,
                "timing": timing_indicators,
                "geographic": geographic_indicators,
                "behavioral": behavioral_indicators,
            })
            
            # Determine if this is likely a snowshoe attack
            is_likely_snowshoe = confidence_score >= self.sensitivity_threshold
            
            # Generate recommendation
            recommendation = self._generate_recommendation(
                confidence_score, volume_indicators, timing_indicators
            )
            
            result = {
                "is_likely_snowshoe": is_likely_snowshoe,
                "confidence_score": round(confidence_score, 3),
                "single_attempt_ips": volume_indicators["single_attempt_ips"],
                "low_volume_ips": volume_indicators["low_volume_ips"],
                "coordinated_timing": timing_indicators["has_clustering"],
                "geographic_spread": round(geographic_indicators["diversity_score"], 3),
                "recommendation": recommendation,
                "indicators": {
                    "volume": volume_indicators,
                    "timing": timing_indicators,
                    "geographic": geographic_indicators,
                    "behavioral": behavioral_indicators,
                },
                "analysis_metadata": {
                    "total_sessions": len(sessions),
                    "unique_ips": len(ip_data),
                    "window_hours": window_hours,
                    "analysis_timestamp": datetime.now(UTC).isoformat(),
                },
            }
            
            logger.info(
                "Snowshoe detection complete: confidence=%.3f, snowshoe=%s, "
                "single_attempt_ips=%d, coordinated_timing=%s",
                confidence_score,
                is_likely_snowshoe,
                len(volume_indicators["single_attempt_ips"]),
                timing_indicators["has_clustering"],
            )
            
            return result
            
        except Exception as e:
            logger.error("Error during snowshoe detection: %s", str(e), exc_info=True)
            return self._empty_result(error=str(e))
    
    def _extract_ip_data(self, sessions: List[SessionSummary]) -> Dict[str, Dict[str, Any]]:
        """Extract IP addresses and related data from sessions.
        
        Args:
            sessions: List of session summaries
            
        Returns:
            Dictionary mapping IP addresses to their session data
        """
        ip_data: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "sessions": [],
            "timestamps": [],
            "countries": set(),
            "asns": set(),
            "commands": [],
            "session_durations": [],
        })
        
        for session in sessions:
            # Extract IP from enrichment data
            ip_address = self._extract_ip_from_session(session)
            if not ip_address:
                continue
            
            # Validate IP address
            try:
                ip_obj = ipaddress.ip_address(ip_address)
                # Note: In testing, we allow private IPs for test data
                # In production, you might want to filter these out
                if ip_obj.is_reserved or ip_obj.is_loopback:
                    logger.debug("Skipping reserved/loopback IP: %s", ip_address)
                    continue
            except ValueError:
                logger.debug("Invalid IP address: %s", ip_address)
                continue
            
            # Collect session data
            ip_data[ip_address]["sessions"].append(session)
            
            if session.first_event_at:
                ip_data[ip_address]["timestamps"].append(session.first_event_at)
            
            # Extract geographic data from enrichment
            self._extract_geographic_data(session, ip_data[ip_address])
            
            # Extract command data
            self._extract_command_data(session, ip_data[ip_address])
            
            # Calculate session duration
            if session.first_event_at and session.last_event_at:
                duration = (session.last_event_at - session.first_event_at).total_seconds()
                ip_data[ip_address]["session_durations"].append(duration)
        
        return dict(ip_data)
    
    def _extract_ip_from_session(self, session: SessionSummary) -> Optional[str]:
        """Extract IP address from session enrichment data.
        
        Args:
            session: Session summary object
            
        Returns:
            IP address string or None if not found
        """
        if not session.enrichment:
            return None
        
        # Look for IP in session enrichment data
        session_data = session.enrichment.get("session", {})
        if isinstance(session_data, dict):
            # IPs are typically keys in the session data
            for key in session_data.keys():
                try:
                    ipaddress.ip_address(key)
                    return key
                except ValueError:
                    continue
        
        return None
    
    def _extract_geographic_data(self, session: SessionSummary, ip_data: Dict[str, Any]) -> None:
        """Extract geographic information from session enrichment.
        
        Args:
            session: Session summary object
            ip_data: IP data dictionary to update
        """
        if not session.enrichment:
            return
        
        session_data = session.enrichment.get("session", {})
        if isinstance(session_data, dict):
            for ip, details in session_data.items():
                if isinstance(details, dict):
                    # Extract SPUR data for geographic information
                    spur_data = details.get("spur", {})
                    if isinstance(spur_data, dict):
                        if "country" in spur_data:
                            ip_data["countries"].add(spur_data["country"])
                        if "asn" in spur_data:
                            ip_data["asns"].add(spur_data["asn"])
    
    def _extract_command_data(self, session: SessionSummary, ip_data: Dict[str, Any]) -> None:
        """Extract command information from session.
        
        Args:
            session: Session summary object
            ip_data: IP data dictionary to update
        """
        # For now, use session metrics as proxy for command patterns
        # In a full implementation, we'd query CommandStat table
        if session.command_count:
            ip_data["commands"].append({
                "count": session.command_count,
                "risk_score": session.risk_score or 0,
            })
    
    def _analyze_volume_patterns(self, ip_data: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze volume patterns to identify single-attempt and low-volume IPs.
        
        Args:
            ip_data: Dictionary of IP data
            
        Returns:
            Dictionary containing volume analysis results
        """
        single_attempt_ips = []
        low_volume_ips = []
        
        for ip, data in ip_data.items():
            session_count = len(data["sessions"])
            
            if session_count == 1:
                single_attempt_ips.append(ip)
            elif 1 < session_count <= self.single_attempt_threshold:
                low_volume_ips.append(ip)
        
        total_ips = len(ip_data)
        single_attempt_ratio = len(single_attempt_ips) / total_ips if total_ips > 0 else 0
        low_volume_ratio = (len(single_attempt_ips) + len(low_volume_ips)) / total_ips if total_ips > 0 else 0
        
        return {
            "single_attempt_ips": single_attempt_ips,
            "low_volume_ips": low_volume_ips,
            "single_attempt_ratio": single_attempt_ratio,
            "low_volume_ratio": low_volume_ratio,
            "total_ips": total_ips,
        }
    
    def _analyze_timing_patterns(
        self, 
        ip_data: Dict[str, Dict[str, Any]], 
        window_hours: int
    ) -> Dict[str, Any]:
        """Analyze timing patterns for coordinated bursts.
        
        Args:
            ip_data: Dictionary of IP data
            window_hours: Analysis window in hours
            
        Returns:
            Dictionary containing timing analysis results
        """
        # Collect all timestamps
        all_timestamps = []
        for data in ip_data.values():
            all_timestamps.extend(data["timestamps"])
        
        if len(all_timestamps) < self.min_cluster_size:
            return {
                "has_clustering": False,
                "cluster_count": 0,
                "largest_cluster_size": 0,
                "time_coordination_score": 0.0,
            }
        
        # Convert to numeric format for clustering
        timestamps_numeric = []
        for ts in all_timestamps:
            if isinstance(ts, datetime):
                timestamps_numeric.append(ts.timestamp())
        
        if len(timestamps_numeric) < self.min_cluster_size:
            return {
                "has_clustering": False,
                "cluster_count": 0,
                "largest_cluster_size": 0,
                "time_coordination_score": 0.0,
            }
        
        # Perform DBSCAN clustering
        try:
            X = np.array(timestamps_numeric).reshape(-1, 1)
            eps_hours = self.time_cluster_eps
            eps_seconds = eps_hours * 3600  # Convert to seconds
            
            clustering = DBSCAN(
                eps=eps_seconds,
                min_samples=self.min_cluster_size,
                metric='euclidean'
            ).fit(X)
            
            cluster_labels = clustering.labels_
            n_clusters = len(set(cluster_labels)) - (1 if -1 in cluster_labels else 0)
            
            # Calculate cluster statistics
            cluster_sizes = Counter(cluster_labels)
            if -1 in cluster_sizes:
                del cluster_sizes[-1]  # Remove noise points
            
            largest_cluster_size = max(cluster_sizes.values()) if cluster_sizes else 0
            
            # Calculate coordination score
            clustered_points = sum(1 for label in cluster_labels if label != -1)
            time_coordination_score = clustered_points / len(timestamps_numeric) if timestamps_numeric else 0
            
            has_clustering = n_clusters > 0 and time_coordination_score > 0.3
            
            return {
                "has_clustering": has_clustering,
                "cluster_count": n_clusters,
                "largest_cluster_size": largest_cluster_size,
                "time_coordination_score": time_coordination_score,
                "clustered_points": clustered_points,
                "total_points": len(timestamps_numeric),
            }
            
        except Exception as e:
            logger.warning("Error in timing analysis: %s", str(e))
            return {
                "has_clustering": False,
                "cluster_count": 0,
                "largest_cluster_size": 0,
                "time_coordination_score": 0.0,
            }
    
    def _analyze_geographic_diversity(self, ip_data: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze geographic diversity of IP addresses.
        
        Args:
            ip_data: Dictionary of IP data
            
        Returns:
            Dictionary containing geographic analysis results
        """
        all_countries = set()
        all_asns = set()
        
        for data in ip_data.values():
            all_countries.update(data["countries"])
            all_asns.update(data["asns"])
        
        total_ips = len(ip_data)
        country_diversity = len(all_countries) / total_ips if total_ips > 0 else 0
        asn_diversity = len(all_asns) / total_ips if total_ips > 0 else 0
        
        # Combined diversity score
        diversity_score = (country_diversity + asn_diversity) / 2
        
        return {
            "countries": list(all_countries),
            "asns": list(all_asns),
            "country_count": len(all_countries),
            "asn_count": len(all_asns),
            "country_diversity": country_diversity,
            "asn_diversity": asn_diversity,
            "diversity_score": diversity_score,
            "is_diverse": diversity_score >= self.geographic_diversity_threshold,
        }
    
    def _analyze_behavioral_similarity(
        self, 
        ip_data: Dict[str, Dict[str, Any]], 
        sessions: List[SessionSummary]
    ) -> Dict[str, Any]:
        """Analyze behavioral similarity across IPs.
        
        Args:
            ip_data: Dictionary of IP data
            sessions: List of all sessions
            
        Returns:
            Dictionary containing behavioral analysis results
        """
        # Analyze session duration patterns
        durations = []
        for data in ip_data.values():
            durations.extend(data["session_durations"])
        
        avg_duration = np.mean(durations) if durations else 0
        duration_variance = np.var(durations) if durations else 0
        
        # Analyze command patterns (simplified)
        command_counts = [data["commands"] for data in ip_data.values()]
        avg_commands = np.mean([len(cmds) for cmds in command_counts]) if command_counts else 0
        
        # Calculate similarity score based on consistency
        duration_consistency = 1.0 / (1.0 + duration_variance) if duration_variance > 0 else 1.0
        
        return {
            "avg_session_duration": avg_duration,
            "duration_variance": duration_variance,
            "duration_consistency": duration_consistency,
            "avg_commands_per_ip": avg_commands,
            "behavioral_similarity_score": duration_consistency,
            "is_similar_behavior": duration_consistency > 0.7,
        }
    
    def _calculate_snowshoe_score(self, indicators: Dict[str, Dict[str, Any]]) -> float:
        """Calculate composite snowshoe detection score.
        
        Args:
            indicators: Dictionary containing all analysis indicators
            
        Returns:
            Composite confidence score (0.0-1.0)
        """
        volume = indicators["volume"]
        timing = indicators["timing"]
        geographic = indicators["geographic"]
        behavioral = indicators["behavioral"]
        
        score = 0.0
        
        # High ratio of single-attempt IPs (40% weight)
        score += volume["single_attempt_ratio"] * 0.4
        
        # Geographic diversity (30% weight)
        score += geographic["diversity_score"] * 0.3
        
        # Time coordination (20% weight)
        if timing["has_clustering"]:
            score += 0.2
        
        # Low volume ratio (10% weight)
        score += volume["low_volume_ratio"] * 0.1
        
        return round(min(score, 1.0), 6)
    
    def _generate_recommendation(
        self,
        confidence_score: float,
        volume_indicators: Dict[str, Any],
        timing_indicators: Dict[str, Any],
    ) -> str:
        """Generate recommendation based on detection results.
        
        Args:
            confidence_score: Overall confidence score
            volume_indicators: Volume analysis results
            timing_indicators: Timing analysis results
            
        Returns:
            Human-readable recommendation
        """
        if confidence_score >= 0.8:
            return "HIGH CONFIDENCE: Likely snowshoe attack detected. Immediate investigation recommended."
        elif confidence_score >= 0.6:
            return "MODERATE CONFIDENCE: Potential snowshoe attack. Monitor closely and investigate."
        elif confidence_score >= 0.4:
            return "LOW CONFIDENCE: Some snowshoe indicators present. Continue monitoring."
        else:
            return "NO DETECTION: No significant snowshoe attack indicators found."
    
    def _empty_result(self, error: Optional[str] = None) -> Dict[str, Any]:
        """Return empty result structure for error cases.
        
        Args:
            error: Optional error message
            
        Returns:
            Empty result dictionary
        """
        result = {
            "is_likely_snowshoe": False,
            "confidence_score": 0.0,
            "single_attempt_ips": [],
            "low_volume_ips": [],
            "coordinated_timing": False,
            "geographic_spread": 0.0,
            "recommendation": "ERROR: Unable to complete analysis" if error else "NO DATA: Insufficient data for analysis",
            "indicators": {
                "volume": {"single_attempt_ips": [], "low_volume_ips": [], "single_attempt_ratio": 0.0, "low_volume_ratio": 0.0, "total_ips": 0},
                "timing": {"has_clustering": False, "cluster_count": 0, "largest_cluster_size": 0, "time_coordination_score": 0.0},
                "geographic": {"countries": [], "asns": [], "country_count": 0, "asn_count": 0, "country_diversity": 0.0, "asn_diversity": 0.0, "diversity_score": 0.0, "is_diverse": False},
                "behavioral": {"avg_session_duration": 0.0, "duration_variance": 0.0, "duration_consistency": 0.0, "avg_commands_per_ip": 0.0, "behavioral_similarity_score": 0.0, "is_similar_behavior": False},
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
