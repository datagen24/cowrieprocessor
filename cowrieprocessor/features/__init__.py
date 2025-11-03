"""Feature extraction for threat detection and classification."""

from __future__ import annotations

__all__ = [
    "ProviderFeatures",
    "ProviderClassifier",
    "haversine_distance",
    "calculate_geographic_spread",
    "calculate_entropy",
    "aggregate_features",
]

from cowrieprocessor.features.aggregation import (
    aggregate_features,
    calculate_entropy,
    calculate_geographic_spread,
    haversine_distance,
)
from cowrieprocessor.features.provider_classification import ProviderClassifier, ProviderFeatures
