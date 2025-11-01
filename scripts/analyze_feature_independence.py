#!/usr/bin/env python3
"""Analyze feature independence via correlation analysis.

This script analyzes feature correlation to identify and document redundancies
in the feature set. It calculates Pearson correlation coefficients between all
feature pairs and identifies highly correlated features that may be redundant.

Issue: #58 - Feature Independence Correlation Analysis
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sqlalchemy.orm import Session

from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.db.models import SessionSummary
from cowrieprocessor.features import ProviderClassifier, aggregate_features
from cowrieprocessor.settings import load_database_settings


def _load_sensors_config() -> dict[str, str] | None:
    """Load database configuration from sensors.toml if available."""
    # Try config/ directory first, then fall back to current directory
    sensors_file = Path("config/sensors.toml")
    if not sensors_file.exists():
        sensors_file = Path("sensors.toml")
    if not sensors_file.exists():
        return None

    try:
        # Try tomllib first (Python 3.11+)
        try:
            import tomllib
        except ImportError:
            # Fall back to tomli for older Python versions
            import tomli as tomllib  # type: ignore[no-redef]

        with sensors_file.open("rb") as handle:
            data = tomllib.load(handle)

        # Check for global database configuration
        global_config = data.get("global", {})
        db_url = global_config.get("db")
        if db_url:
            return {"url": db_url}

    except Exception:
        # If sensors.toml doesn't exist or can't be parsed, return None
        pass

    return None


def extract_feature_vectors(sessions: list[SessionSummary], classifier: ProviderClassifier) -> pd.DataFrame:
    """Extract feature vectors from sessions.

    Args:
        sessions: List of SessionSummary objects
        classifier: ProviderClassifier instance

    Returns:
        DataFrame with one row per session and columns for each feature
    """
    feature_dicts: list[dict[str, Any]] = []

    for session in sessions:
        try:
            features = aggregate_features([session], classifier)
            # Add session_id for tracking
            features["session_id"] = session.session_id
            feature_dicts.append(features)
        except Exception as e:
            print(f"Warning: Failed to extract features for session {session.session_id}: {e}")
            continue

    if not feature_dicts:
        raise ValueError("No features extracted from any sessions")

    return pd.DataFrame(feature_dicts)


def calculate_correlation_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate correlation matrix for numeric features.

    Args:
        df: DataFrame with feature columns

    Returns:
        Correlation matrix as DataFrame
    """
    # Select only numeric features (exclude session_id)
    numeric_df = df.select_dtypes(include=[np.number])
    return numeric_df.corr()


def visualize_correlation_matrix(corr: pd.DataFrame, output_path: str = "correlation_matrix.png") -> None:
    """Generate heatmap visualization of correlation matrix.

    Args:
        corr: Correlation matrix DataFrame
        output_path: Path to save visualization
    """
    plt.figure(figsize=(14, 12))

    # Create heatmap with annotations
    sns.heatmap(
        corr,
        annot=True,
        fmt=".2f",
        cmap="coolwarm",
        center=0,
        square=True,
        linewidths=1,
        cbar_kws={"shrink": 0.8},
        vmin=-1,
        vmax=1,
    )

    plt.title("Feature Correlation Matrix (Pearson Coefficient)", fontsize=16, pad=20)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"\n✅ Correlation matrix saved to {output_path}")


def find_high_correlations(corr: pd.DataFrame, threshold: float = 0.90) -> list[tuple[str, str, float]]:
    """Find feature pairs with |r| > threshold.

    Args:
        corr: Correlation matrix DataFrame
        threshold: Minimum absolute correlation coefficient

    Returns:
        List of (feature1, feature2, correlation) tuples sorted by absolute correlation
    """
    high_corr: list[tuple[str, str, float]] = []

    for i in range(len(corr.columns)):
        for j in range(i + 1, len(corr.columns)):
            r = corr.iloc[i, j]
            if abs(r) > threshold:
                high_corr.append((corr.columns[i], corr.columns[j], r))

    return sorted(high_corr, key=lambda x: abs(x[2]), reverse=True)


def categorize_correlations(high_corr: list[tuple[str, str, float]]) -> dict[str, list[tuple[str, str, float]]]:
    """Categorize correlations as expected vs unexpected.

    Args:
        high_corr: List of high correlation tuples

    Returns:
        Dictionary with 'expected' and 'unexpected' lists
    """
    # Define expected correlations based on feature design
    expected_pairs = [
        ("ip_count", "session_count"),  # More IPs → more sessions (not 1:1)
        ("total_commands", "unique_commands"),  # More commands → more unique
        ("geographic_spread_km", "ip_count"),  # More IPs → wider spread
        ("cloud_provider_ratio", "vpn_provider_ratio"),  # VPN often uses cloud
        ("cloud_provider_ratio", "avg_dshield_score"),  # Cloud IPs often have history
        ("vpn_provider_ratio", "tor_exit_ratio"),  # Some overlap in anonymization
    ]

    expected_list: list[tuple[str, str, float]] = []
    unexpected_list: list[tuple[str, str, float]] = []

    for f1, f2, r in high_corr:
        is_expected = any((f1 == e1 and f2 == e2) or (f1 == e2 and f2 == e1) for e1, e2 in expected_pairs)

        if is_expected:
            expected_list.append((f1, f2, r))
        else:
            unexpected_list.append((f1, f2, r))

    return {"expected": expected_list, "unexpected": unexpected_list}


def recommend_removals(high_corr: list[tuple[str, str, float]], threshold: float = 0.95) -> list[str]:
    """Recommend features to remove if |r| > 0.95.

    Features with extremely high correlation (>0.95) are likely redundant.
    This function recommends which features to remove using heuristics.

    Args:
        high_corr: List of high correlation tuples
        threshold: Minimum correlation for removal consideration

    Returns:
        List of feature names recommended for removal
    """
    removals: list[str] = []

    for f1, f2, r in high_corr:
        if abs(r) <= threshold:
            continue

        # Heuristic: prefer keeping raw counts over derived ratios/averages
        if "ratio" in f1 and "ratio" not in f2:
            removals.append(f1)
        elif "ratio" in f2 and "ratio" not in f1:
            removals.append(f2)
        elif "avg" in f1 and "avg" not in f2:
            removals.append(f1)
        elif "avg" in f2 and "avg" not in f1:
            removals.append(f2)
        elif "entropy" in f1 and "diversity" in f1:
            removals.append(f1)  # Remove redundant entropy/diversity metrics
        elif "entropy" in f2 and "diversity" in f2:
            removals.append(f2)
        else:
            # Default: remove second feature alphabetically
            removals.append(f2 if f1 < f2 else f1)

    return list(set(removals))


def print_feature_summary(df: pd.DataFrame) -> None:
    """Print summary statistics for extracted features.

    Args:
        df: DataFrame with feature columns
    """
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    print("\nFeature Summary Statistics:")
    print("=" * 70)
    for col in numeric_cols:
        values = df[col]
        print(
            f"{col:25s}: mean={values.mean():8.3f}, std={values.std():8.3f}, "
            f"min={values.min():8.3f}, max={values.max():8.3f}"
        )


def main() -> None:
    """Run feature independence analysis."""
    print("=" * 70)
    print("Feature Independence Analysis (Issue #58)")
    print("=" * 70)

    # Configuration
    num_sessions = 100
    correlation_threshold_90 = 0.90
    correlation_threshold_95 = 0.95
    output_file = "correlation_matrix.png"

    # Load database and sessions
    print("\nConnecting to database...")
    config = _load_sensors_config()
    settings = load_database_settings(config)
    engine = create_engine_from_settings(settings)
    db = Session(engine)

    print(f"Querying {num_sessions} sessions with full enrichment...")
    sessions = (
        db.query(SessionSummary)
        .filter(
            SessionSummary.enrichment.isnot(None),
            SessionSummary.command_count > 0,
        )
        .order_by(SessionSummary.first_event_at.desc())
        .limit(num_sessions)
        .all()
    )

    if len(sessions) < num_sessions:
        print(f"Warning: Only found {len(sessions)} sessions (requested {num_sessions})")

    # Load classifier
    print("Initializing provider classifier...")
    classifier = ProviderClassifier(
        {
            "use_dshield": True,
            "use_spur": True,
            "max_enrichment_age_days": 365,
            "cloud_provider_keywords": ["amazon", "aws", "google", "azure"],
        }
    )

    # Extract features
    print(f"Extracting features from {len(sessions)} sessions...")
    feature_df = extract_feature_vectors(sessions, classifier)
    print(f"✅ Extracted {len(feature_df)} feature vectors")

    # Print feature summary
    print_feature_summary(feature_df)

    # Calculate correlation
    print("\nCalculating correlation matrix...")
    corr_matrix = calculate_correlation_matrix(feature_df)
    print(f"✅ Correlation matrix: {corr_matrix.shape[0]}x{corr_matrix.shape[1]}")

    # Visualize
    print("Generating visualization...")
    visualize_correlation_matrix(corr_matrix, output_file)

    # Find high correlations
    high_corr_90 = find_high_correlations(corr_matrix, threshold=correlation_threshold_90)
    high_corr_95 = find_high_correlations(corr_matrix, threshold=correlation_threshold_95)

    # Categorize correlations
    categorized = categorize_correlations(high_corr_90)

    # Print results
    print("\n" + "=" * 70)
    print("CORRELATION ANALYSIS RESULTS")
    print("=" * 70)

    print(f"\nFound {len(high_corr_90)} highly correlated feature pairs (|r| > {correlation_threshold_90}):")
    print(f"  Expected correlations: {len(categorized['expected'])}")
    print(f"  Unexpected correlations: {len(categorized['unexpected'])}")

    if categorized["expected"]:
        print("\nExpected Correlations (|r| > 0.90):")
        print("-" * 70)
        for f1, f2, r in categorized["expected"]:
            print(f"  {f1:25s} <-> {f2:25s}: r={r:6.3f}")

    if categorized["unexpected"]:
        print("\n⚠️  Unexpected High Correlations (INVESTIGATE):")
        print("-" * 70)
        for f1, f2, r in categorized["unexpected"]:
            print(f"  {f1:25s} <-> {f2:25s}: r={r:6.3f}")
    else:
        print("\n✅ No unexpected high correlations found!")

    # Recommend removals for extremely high correlations
    removals = recommend_removals(high_corr_95, threshold=correlation_threshold_95)

    print("\n" + "=" * 70)
    print(f"FEATURE REMOVAL RECOMMENDATIONS (|r| > {correlation_threshold_95})")
    print("=" * 70)

    if removals:
        print(f"\nFound {len(removals)} features with extremely high correlation:")
        print("Consider removing the following features to reduce redundancy:\n")
        for feature in removals:
            # Find which features this is correlated with
            related = [
                (f1, f2, r)
                for f1, f2, r in high_corr_95
                if (f1 == feature or f2 == feature) and abs(r) > correlation_threshold_95
            ]
            print(f"  ❌ {feature}")
            for f1, f2, r in related:
                other = f2 if f1 == feature else f1
                print(f"     Correlated with {other} (r={r:.3f})")
    else:
        print("\n✅ No extremely high correlations (|r| > 0.95) found!")
        print("All features appear to be independent enough for ML training.")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Sessions analyzed: {len(feature_df)}")
    print(f"Features extracted: {corr_matrix.shape[0]}")
    print(f"High correlations (|r| > {correlation_threshold_90}): {len(high_corr_90)}")
    print(f"Extreme correlations (|r| > {correlation_threshold_95}): {len(high_corr_95)}")
    print(f"Recommended removals: {len(removals)}")
    print(f"Visualization saved: {output_file}")

    # Return exit code
    if len(removals) > 0:
        print("\n⚠️  Feature redundancy detected - review recommendations")
        sys.exit(1)
    else:
        print("\n✅ Feature set has acceptable independence!")
        sys.exit(0)


if __name__ == "__main__":
    main()
