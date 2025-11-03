"""Vectorization utilities for threat detection.

This package provides utilities for normalizing and vectorizing honeypot commands
for machine learning-based threat detection.
"""

from __future__ import annotations

from cowrieprocessor.vectorization.defanging_normalizer import DefangingAwareNormalizer

__all__ = ['DefangingAwareNormalizer']
