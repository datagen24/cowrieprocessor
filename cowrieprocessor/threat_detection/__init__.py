"""Threat detection modules for Cowrie Processor."""

from __future__ import annotations

from .botnet import BotnetCoordinatorDetector
from .longtail import CommandVectorizer, LongtailAnalysisResult, LongtailAnalyzer
from .metrics import (
    SnowshoeCampaignMetrics,
    SnowshoeDetectionMetrics,
    create_snowshoe_metrics_from_detection,
)
from .snowshoe import SnowshoeDetector

__all__ = [
    "BotnetCoordinatorDetector",
    "SnowshoeDetector",
    "SnowshoeDetectionMetrics",
    "SnowshoeCampaignMetrics",
    "create_snowshoe_metrics_from_detection",
    "LongtailAnalyzer",
    "LongtailAnalysisResult",
    "CommandVectorizer",
]
