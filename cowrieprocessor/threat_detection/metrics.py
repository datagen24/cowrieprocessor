"""Metrics and telemetry for threat detection modules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Dict, List, Optional


@dataclass
class SnowshoeDetectionMetrics:
    """Metrics for snowshoe attack detection analysis.

    This class captures comprehensive telemetry data for snowshoe detection
    operations, including performance metrics, detection accuracy, and
    resource utilization.
    """

    # Analysis identification
    analysis_id: str
    window_hours: float
    analysis_timestamp: datetime

    # Input data metrics
    total_sessions: int
    unique_ips: int
    sessions_with_enrichment: int
    sessions_with_geographic_data: int

    # Detection results
    is_likely_snowshoe: bool
    confidence_score: float
    single_attempt_ips: int
    low_volume_ips: int
    coordinated_timing: bool
    geographic_spread: float

    # Performance metrics
    analysis_duration_seconds: float
    memory_usage_mb: Optional[float] = None
    cpu_usage_percent: Optional[float] = None

    # Detection breakdown
    volume_score: float = 0.0
    timing_score: float = 0.0
    geographic_score: float = 0.0
    behavioral_score: float = 0.0

    # Quality metrics
    data_quality_score: float = 1.0
    enrichment_coverage: float = 0.0

    # Error tracking
    errors: List[str] = None
    warnings: List[str] = None

    def __post_init__(self) -> None:
        """Initialize default values for optional fields."""
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []

    @property
    def detection_efficiency(self) -> float:
        """Calculate detection efficiency (sessions analyzed per second)."""
        if self.analysis_duration_seconds <= 0:
            return 0.0
        return round(self.total_sessions / self.analysis_duration_seconds, 2)

    @property
    def ip_coverage(self) -> float:
        """Calculate IP coverage ratio."""
        if self.total_sessions <= 0:
            return 0.0
        return round(self.unique_ips / self.total_sessions, 3)

    @property
    def enrichment_quality(self) -> float:
        """Calculate enrichment data quality score."""
        if self.total_sessions <= 0:
            return 0.0
        return round(self.sessions_with_enrichment / self.total_sessions, 3)

    @property
    def geographic_coverage(self) -> float:
        """Calculate geographic data coverage."""
        if self.sessions_with_enrichment <= 0:
            return 0.0
        return round(self.sessions_with_geographic_data / self.sessions_with_enrichment, 3)

    @property
    def detection_confidence_level(self) -> str:
        """Get human-readable confidence level."""
        if self.confidence_score >= 0.8:
            return "high"
        elif self.confidence_score >= 0.6:
            return "moderate"
        elif self.confidence_score >= 0.4:
            return "low"
        else:
            return "minimal"

    @property
    def risk_level(self) -> str:
        """Get risk level assessment."""
        if not self.is_likely_snowshoe:
            return "none"

        if self.confidence_score >= 0.8 and self.coordinated_timing:
            return "high"
        elif self.confidence_score >= 0.6:
            return "moderate"
        else:
            return "low"

    def to_status_dict(self) -> Dict[str, any]:
        """Convert metrics to dictionary format for StatusEmitter.

        Returns:
            Dictionary representation suitable for status file storage
        """
        return {
            "analysis_id": self.analysis_id,
            "window_hours": self.window_hours,
            "analysis_timestamp": self.analysis_timestamp.isoformat(),
            # Input metrics
            "input": {
                "total_sessions": self.total_sessions,
                "unique_ips": self.unique_ips,
                "sessions_with_enrichment": self.sessions_with_enrichment,
                "sessions_with_geographic_data": self.sessions_with_geographic_data,
                "ip_coverage": self.ip_coverage,
                "enrichment_quality": self.enrichment_quality,
                "geographic_coverage": self.geographic_coverage,
            },
            # Detection results
            "detection": {
                "is_likely_snowshoe": self.is_likely_snowshoe,
                "confidence_score": self.confidence_score,
                "confidence_level": self.detection_confidence_level,
                "risk_level": self.risk_level,
                "single_attempt_ips": self.single_attempt_ips,
                "low_volume_ips": self.low_volume_ips,
                "coordinated_timing": self.coordinated_timing,
                "geographic_spread": self.geographic_spread,
            },
            # Performance metrics
            "performance": {
                "analysis_duration_seconds": self.analysis_duration_seconds,
                "detection_efficiency": self.detection_efficiency,
                "memory_usage_mb": self.memory_usage_mb,
                "cpu_usage_percent": self.cpu_usage_percent,
            },
            # Detection breakdown
            "scores": {
                "volume_score": self.volume_score,
                "timing_score": self.timing_score,
                "geographic_score": self.geographic_score,
                "behavioral_score": self.behavioral_score,
                "data_quality_score": self.data_quality_score,
            },
            # Quality and errors
            "quality": {
                "data_quality_score": self.data_quality_score,
                "enrichment_coverage": self.enrichment_coverage,
                "errors": self.errors,
                "warnings": self.warnings,
            },
        }


@dataclass
class SnowshoeCampaignMetrics:
    """Metrics for tracking snowshoe campaigns over time."""

    campaign_id: str
    first_detected: datetime
    last_detected: datetime
    detection_count: int

    # Campaign characteristics
    total_unique_ips: int
    total_sessions: int
    avg_confidence_score: float
    max_confidence_score: float

    # Geographic spread
    countries_affected: List[str]
    asns_affected: List[str]
    geographic_diversity_score: float

    # Temporal characteristics
    campaign_duration_hours: float
    detection_frequency_per_hour: float

    # Risk assessment
    risk_trend: str  # "increasing", "stable", "decreasing"
    threat_level: str  # "low", "moderate", "high", "critical"

    def __post_init__(self) -> None:
        """Calculate derived metrics."""
        if self.countries_affected is None:
            self.countries_affected = []
        if self.asns_affected is None:
            self.asns_affected = []

    @property
    def campaign_velocity(self) -> float:
        """Calculate campaign velocity (sessions per hour)."""
        if self.campaign_duration_hours <= 0:
            return 0.0
        return round(self.total_sessions / self.campaign_duration_hours, 2)

    @property
    def ip_velocity(self) -> float:
        """Calculate IP velocity (new IPs per hour)."""
        if self.campaign_duration_hours <= 0:
            return 0.0
        return round(self.total_unique_ips / self.campaign_duration_hours, 2)

    def to_status_dict(self) -> Dict[str, any]:
        """Convert campaign metrics to dictionary format for StatusEmitter."""
        return {
            "campaign_id": self.campaign_id,
            "first_detected": self.first_detected.isoformat(),
            "last_detected": self.last_detected.isoformat(),
            "detection_count": self.detection_count,
            "characteristics": {
                "total_unique_ips": self.total_unique_ips,
                "total_sessions": self.total_sessions,
                "avg_confidence_score": self.avg_confidence_score,
                "max_confidence_score": self.max_confidence_score,
                "campaign_velocity": self.campaign_velocity,
                "ip_velocity": self.ip_velocity,
            },
            "geographic": {
                "countries_affected": self.countries_affected,
                "asns_affected": self.asns_affected,
                "geographic_diversity_score": self.geographic_diversity_score,
                "country_count": len(self.countries_affected),
                "asn_count": len(self.asns_affected),
            },
            "temporal": {
                "campaign_duration_hours": self.campaign_duration_hours,
                "detection_frequency_per_hour": self.detection_frequency_per_hour,
            },
            "risk": {
                "risk_trend": self.risk_trend,
                "threat_level": self.threat_level,
            },
        }


def create_snowshoe_metrics_from_detection(
    detection_result: Dict[str, any],
    analysis_duration: float,
    analysis_id: str,
    window_hours: float,
    memory_usage_mb: Optional[float] = None,
    cpu_usage_percent: Optional[float] = None,
) -> SnowshoeDetectionMetrics:
    """Create metrics from a snowshoe detection result.

    Args:
        detection_result: Result from SnowshoeDetector.detect()
        analysis_duration: Time taken for analysis in seconds
        analysis_id: Unique identifier for this analysis
        window_hours: Analysis window in hours
        memory_usage_mb: Optional memory usage in MB
        cpu_usage_percent: Optional CPU usage percentage

    Returns:
        SnowshoeDetectionMetrics object
    """
    metadata = detection_result.get("analysis_metadata", {})
    indicators = detection_result.get("indicators", {})

    # Extract enrichment data quality
    sessions_with_enrichment = 0
    sessions_with_geographic = 0

    # This would be calculated from the actual session data
    # For now, we'll estimate based on the detection result
    total_sessions = metadata.get("total_sessions", 0)
    if total_sessions > 0:
        # Estimate enrichment coverage based on geographic diversity
        geo_spread = detection_result.get("geographic_spread", 0.0)
        sessions_with_enrichment = int(total_sessions * (0.5 + geo_spread * 0.5))
        sessions_with_geographic = int(sessions_with_enrichment * geo_spread)

    return SnowshoeDetectionMetrics(
        analysis_id=analysis_id,
        window_hours=window_hours,
        analysis_timestamp=datetime.now(UTC),
        # Input metrics
        total_sessions=total_sessions,
        unique_ips=metadata.get("unique_ips", 0),
        sessions_with_enrichment=sessions_with_enrichment,
        sessions_with_geographic_data=sessions_with_geographic,
        # Detection results
        is_likely_snowshoe=detection_result.get("is_likely_snowshoe", False),
        confidence_score=detection_result.get("confidence_score", 0.0),
        single_attempt_ips=len(detection_result.get("single_attempt_ips", [])),
        low_volume_ips=len(detection_result.get("low_volume_ips", [])),
        coordinated_timing=detection_result.get("coordinated_timing", False),
        geographic_spread=detection_result.get("geographic_spread", 0.0),
        # Performance metrics
        analysis_duration_seconds=analysis_duration,
        memory_usage_mb=memory_usage_mb,
        cpu_usage_percent=cpu_usage_percent,
        # Detection breakdown
        volume_score=indicators.get("volume", {}).get("single_attempt_ratio", 0.0),
        timing_score=indicators.get("timing", {}).get("time_coordination_score", 0.0),
        geographic_score=indicators.get("geographic", {}).get("diversity_score", 0.0),
        behavioral_score=indicators.get("behavioral", {}).get("behavioral_similarity_score", 0.0),
        # Quality metrics
        data_quality_score=min(1.0, (sessions_with_enrichment / total_sessions) if total_sessions > 0 else 0.0),
        enrichment_coverage=sessions_with_enrichment / total_sessions if total_sessions > 0 else 0.0,
    )


__all__ = [
    "SnowshoeDetectionMetrics",
    "SnowshoeCampaignMetrics",
    "create_snowshoe_metrics_from_detection",
]
