#!/usr/bin/env python3
r"""Phase 1A Feature Importance Analysis Script.

Analyzes CSV results from SQL queries to identify discriminative features for
threat actor clustering. Calculates statistical measures (variance, mutual
information, chi-square) to rank features by their ability to distinguish
between different attack campaigns.

Usage:
    uv run python scripts/phase1/analyze_feature_importance.py \\
        --results-dir results/ \\
        --output docs/phase1/feature_discovery_analysis.md \\
        --top-n 40

References:
    - Phase 1 Plan: docs/pdca/phase1-ttp-profiling/plan.md
    - SQL Queries: scripts/phase1/sql_analysis_queries.sql
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency, entropy


@dataclass
class FeatureStats:
    """Statistical measures for a single feature."""

    name: str
    variance: float
    mutual_information: float
    chi_square: float
    p_value: float
    discrimination_score: float  # Combined score (0-1)
    sample_count: int
    unique_values: int
    top_values: list[tuple[Any, int]] = field(default_factory=list)


@dataclass
class FeatureCategory:
    """Grouped features by category for analysis."""

    category: str
    features: list[FeatureStats]
    avg_discrimination: float
    recommended_count: int


class FeatureImportanceAnalyzer:
    """Analyzes SQL query results to identify discriminative features.

    This analyzer processes CSV outputs from Phase 1A SQL queries and calculates
    statistical measures to rank features by their ability to discriminate between
    different threat actor campaigns.
    """

    def __init__(self, results_dir: Path, verbose: bool = False) -> None:
        """Initialize the analyzer.

        Args:
            results_dir: Directory containing CSV results from SQL queries
            verbose: Enable verbose output
        """
        self.results_dir = results_dir
        self.verbose = verbose
        self.feature_stats: list[FeatureStats] = []

    def load_query_results(self) -> dict[str, pd.DataFrame]:
        """Load all CSV query results into DataFrames.

        Returns:
            Dictionary mapping query names to DataFrames

        Raises:
            FileNotFoundError: If results directory doesn't exist
        """
        if not self.results_dir.exists():
            raise FileNotFoundError(f"Results directory not found: {self.results_dir}")

        results = {}
        expected_files = [
            "01_session_activity_patterns.csv",
            "02_ssh_key_reuse.csv",
            "03_command_patterns.csv",
            "04_temporal_behavioral_patterns.csv",
            "05_password_patterns.csv",
            "06_enrichment_analysis.csv",
            "07_high_activity_sessions.csv",
            "08_session_feature_vectors.csv",
            "09_ssh_key_associations.csv",
            "10_weekly_campaign_patterns.csv",
        ]

        for filename in expected_files:
            filepath = self.results_dir / filename
            if filepath.exists():
                try:
                    df = pd.read_csv(filepath)
                    query_name = filename.replace(".csv", "")
                    results[query_name] = df
                    if self.verbose:
                        print(f"✓ Loaded {filename}: {len(df)} rows, {len(df.columns)} columns")
                except Exception as e:
                    print(f"⚠ Error loading {filename}: {e}", file=sys.stderr)
            else:
                print(f"⚠ Missing {filename} (skipped)", file=sys.stderr)

        if not results:
            raise ValueError("No valid CSV files found in results directory")

        return results

    def calculate_variance_score(self, series: pd.Series) -> float:
        """Calculate normalized variance score for a feature.

        High variance indicates the feature varies significantly between campaigns,
        which is desirable for discrimination.

        Args:
            series: Pandas Series containing feature values

        Returns:
            Normalized variance score (0-1)
        """
        if series.isnull().all() or len(series) < 2:
            return 0.0

        # Handle numeric columns
        if pd.api.types.is_numeric_dtype(series):
            # Drop NaN values
            clean_series = series.dropna()
            if len(clean_series) < 2:
                return 0.0

            variance = clean_series.var()
            mean = clean_series.mean()

            # Coefficient of variation (normalized variance)
            if mean != 0:
                cv = variance / (mean**2)
                # Normalize to 0-1 range using tanh to handle outliers
                return float(np.tanh(cv))
            return 0.0

        # Handle categorical columns - measure entropy
        value_counts = series.value_counts()
        if len(value_counts) <= 1:
            return 0.0

        # Shannon entropy normalized by max possible entropy
        probabilities = value_counts / len(series)
        entropy_value = entropy(probabilities)
        max_entropy = np.log(len(value_counts))

        if max_entropy > 0:
            return float(entropy_value / max_entropy)
        return 0.0

    def calculate_mutual_information(self, feature_series: pd.Series, target_series: pd.Series) -> float:
        """Calculate mutual information between feature and target.

        Measures how much information the feature provides about campaign identity.

        Args:
            feature_series: Feature values
            target_series: Campaign identifiers (dates or cluster IDs)

        Returns:
            Normalized mutual information score (0-1)
        """
        if feature_series.isnull().all() or target_series.isnull().all():
            return 0.0

        # Create contingency table
        try:
            # For numeric features, bin them into quartiles
            if pd.api.types.is_numeric_dtype(feature_series):
                feature_binned = pd.qcut(feature_series, q=4, labels=False, duplicates="drop")
            else:
                feature_binned = feature_series

            # Create crosstab
            contingency = pd.crosstab(feature_binned, target_series)

            # Calculate mutual information using entropy
            p_xy = contingency / contingency.sum().sum()
            p_x = p_xy.sum(axis=1)
            p_y = p_xy.sum(axis=0)

            # MI = sum(p(x,y) * log(p(x,y) / (p(x) * p(y))))
            mi = 0.0
            for i in range(len(p_x)):
                for j in range(len(p_y)):
                    if p_xy.iloc[i, j] > 0:
                        mi += p_xy.iloc[i, j] * np.log(p_xy.iloc[i, j] / (p_x.iloc[i] * p_y.iloc[j]))

            # Normalize by min(H(X), H(Y))
            h_x = entropy(p_x)
            h_y = entropy(p_y)
            max_mi = min(h_x, h_y)

            if max_mi > 0:
                return float(mi / max_mi)
            return 0.0

        except Exception as e:
            if self.verbose:
                print(f"⚠ MI calculation error: {e}", file=sys.stderr)
            return 0.0

    def calculate_chi_square(self, feature_series: pd.Series, target_series: pd.Series) -> tuple[float, float]:
        """Calculate chi-square test statistic and p-value.

        Tests independence between feature and campaign identity.

        Args:
            feature_series: Feature values
            target_series: Campaign identifiers

        Returns:
            Tuple of (chi_square_statistic, p_value)
        """
        if feature_series.isnull().all() or target_series.isnull().all():
            return 0.0, 1.0

        try:
            # Bin numeric features
            if pd.api.types.is_numeric_dtype(feature_series):
                feature_binned = pd.qcut(feature_series, q=4, labels=False, duplicates="drop")
            else:
                feature_binned = feature_series

            # Create contingency table
            contingency = pd.crosstab(feature_binned, target_series)

            # Chi-square test
            chi2, p_value, _, _ = chi2_contingency(contingency)
            return float(chi2), float(p_value)

        except Exception as e:
            if self.verbose:
                print(f"⚠ Chi-square calculation error: {e}", file=sys.stderr)
            return 0.0, 1.0

    def analyze_feature(self, name: str, series: pd.Series, target: pd.Series | None = None) -> FeatureStats:
        """Analyze a single feature and calculate all statistics.

        Args:
            name: Feature name
            series: Feature values
            target: Optional campaign identifiers for supervised metrics

        Returns:
            FeatureStats object with all calculated measures
        """
        # Basic statistics
        sample_count = len(series.dropna())
        unique_values = series.nunique()
        top_values = series.value_counts().head(5).items()

        # Calculate scores
        variance_score = self.calculate_variance_score(series)

        if target is not None:
            mi_score = self.calculate_mutual_information(series, target)
            chi2_stat, p_value = self.calculate_chi_square(series, target)
        else:
            mi_score = 0.0
            chi2_stat = 0.0
            p_value = 1.0

        # Combined discrimination score (weighted average)
        # Variance: 30%, MI: 40%, Chi-square: 30%
        # Normalize chi-square by taking tanh(chi2/100) to bound to 0-1
        chi2_normalized = float(np.tanh(chi2_stat / 100))
        discrimination_score = 0.3 * variance_score + 0.4 * mi_score + 0.3 * chi2_normalized

        return FeatureStats(
            name=name,
            variance=variance_score,
            mutual_information=mi_score,
            chi_square=chi2_stat,
            p_value=p_value,
            discrimination_score=discrimination_score,
            sample_count=sample_count,
            unique_values=unique_values,
            top_values=list(top_values),
        )

    def analyze_command_diversity(self, df: pd.DataFrame) -> list[FeatureStats]:
        """Analyze Query 1: Command Diversity Analysis.

        Args:
            df: DataFrame from 01_command_diversity.csv

        Returns:
            List of FeatureStats for this query
        """
        features = []
        target = df["attack_date"] if "attack_date" in df.columns else None

        # Numeric features
        numeric_cols = [
            "unique_ips",
            "unique_commands",
            "unique_passwords",
            "unique_ssh_keys",
            "avg_duration_seconds",
            "session_count",
            "country_count",
            "asn_count",
        ]

        for col in numeric_cols:
            if col in df.columns:
                features.append(self.analyze_feature(f"cmd_div_{col}", df[col], target))

        return features

    def analyze_ttp_sequences(self, df: pd.DataFrame) -> list[FeatureStats]:
        """Analyze Query 2: TTP Sequence Patterns.

        Args:
            df: DataFrame from 02_ttp_sequences.csv

        Returns:
            List of FeatureStats for this query
        """
        features = []
        target = df["attack_date"] if "attack_date" in df.columns else None

        # Analyze N-gram columns
        ngram_cols = [col for col in df.columns if col.startswith("cmd_")]

        for col in ngram_cols:
            if col in df.columns:
                features.append(self.analyze_feature(f"ttp_{col}", df[col], target))

        return features

    def analyze_temporal_patterns(self, df: pd.DataFrame) -> list[FeatureStats]:
        """Analyze Query 3: Temporal Attack Patterns.

        Args:
            df: DataFrame from 03_temporal_patterns.csv

        Returns:
            List of FeatureStats for this query
        """
        features = []
        target = df["attack_date"] if "attack_date" in df.columns else None

        temporal_cols = [
            "hour_of_day",
            "day_of_week",
            "session_count",
            "unique_ips",
            "avg_session_duration",
        ]

        for col in temporal_cols:
            if col in df.columns:
                features.append(self.analyze_feature(f"temporal_{col}", df[col], target))

        return features

    def analyze_asn_clustering(self, df: pd.DataFrame) -> list[FeatureStats]:
        """Analyze Query 4: ASN Infrastructure Clustering.

        Args:
            df: DataFrame from 04_asn_clustering.csv

        Returns:
            List of FeatureStats for this query
        """
        features = []

        # ASN-based features
        if "asn" in df.columns:
            features.append(self.analyze_feature("infra_asn", df["asn"], None))

        numeric_cols = ["unique_ips", "session_count", "days_active"]
        for col in numeric_cols:
            if col in df.columns:
                features.append(self.analyze_feature(f"infra_{col}", df[col], None))

        return features

    def analyze_ssh_key_reuse(self, df: pd.DataFrame) -> list[FeatureStats]:
        """Analyze Query 5: SSH Key Reuse (GOLD MINE).

        Args:
            df: DataFrame from 05_ssh_key_reuse.csv

        Returns:
            List of FeatureStats for this query
        """
        features = []

        # SSH key features - these are critical for actor tracking
        if "ssh_key_fingerprint" in df.columns:
            features.append(self.analyze_feature("ssh_key_fingerprint", df["ssh_key_fingerprint"], None))

        if "ssh_key_type" in df.columns:
            features.append(self.analyze_feature("ssh_key_type", df["ssh_key_type"], None))

        numeric_cols = ["unique_ips", "days_active"]
        for col in numeric_cols:
            if col in df.columns:
                features.append(self.analyze_feature(f"ssh_{col}", df[col], None))

        return features

    def analyze_password_patterns(self, df: pd.DataFrame) -> list[FeatureStats]:
        """Analyze Query 6: Password List Analysis.

        Args:
            df: DataFrame from 06_password_analysis.csv

        Returns:
            List of FeatureStats for this query
        """
        features = []
        target = df["attack_date"] if "attack_date" in df.columns else None

        password_cols = [
            "unique_passwords",
            "password_length_avg",
            "password_entropy",
            "common_password_ratio",
        ]

        for col in password_cols:
            if col in df.columns:
                features.append(self.analyze_feature(f"pwd_{col}", df[col], target))

        return features

    def analyze_mitre_techniques(self, df: pd.DataFrame, technique_type: str) -> list[FeatureStats]:
        """Analyze MITRE technique queries (7, 8, 9).

        Args:
            df: DataFrame from persistence/credential/recon query
            technique_type: One of 'persistence', 'credential', 'recon'

        Returns:
            List of FeatureStats for MITRE techniques
        """
        features = []
        target = df["attack_date"] if "attack_date" in df.columns else None

        # Find boolean technique columns
        technique_cols = [col for col in df.columns if col.startswith("uses_") or col.endswith("_sessions")]

        for col in technique_cols:
            if col in df.columns:
                features.append(self.analyze_feature(f"mitre_{technique_type}_{col}", df[col], target))

        return features

    def analyze_campaign_correlation(self, df: pd.DataFrame) -> list[FeatureStats]:
        """Analyze Query 10: Campaign Correlation Matrix.

        Args:
            df: DataFrame from 10_campaign_correlation.csv

        Returns:
            List of FeatureStats for correlation features
        """
        features = []

        correlation_cols = [
            "ip_count_similarity",
            "command_similarity",
            "infra_match",
            "ttp_similarity",
            "overall_similarity",
        ]

        for col in correlation_cols:
            if col in df.columns:
                features.append(self.analyze_feature(f"corr_{col}", df[col], None))

        return features

    def analyze_all_queries(self, query_results: dict[str, pd.DataFrame]) -> None:
        """Analyze all loaded query results.

        Args:
            query_results: Dictionary of query name to DataFrame
        """
        analyzers = {
            "01_session_activity_patterns": self.analyze_command_diversity,  # Reuse for similar aggregates
            "02_ssh_key_reuse": self.analyze_ssh_key_reuse,
            "03_command_patterns": self.analyze_ttp_sequences,  # Reuse for command analysis
            "04_temporal_behavioral_patterns": self.analyze_temporal_patterns,
            "05_password_patterns": self.analyze_password_patterns,
            "06_enrichment_analysis": self.analyze_asn_clustering,  # Reuse for infrastructure
            "07_high_activity_sessions": self.analyze_temporal_patterns,  # Similar structure
            "08_session_feature_vectors": self.analyze_campaign_correlation,
            "09_ssh_key_associations": self.analyze_ssh_key_reuse,  # Similar to SSH key reuse
            "10_weekly_campaign_patterns": self.analyze_command_diversity,  # Similar aggregates
        }

        for query_name, df in query_results.items():
            if query_name in analyzers:
                if self.verbose:
                    print(f"\n📊 Analyzing {query_name}...")
                features = analyzers[query_name](df)
                self.feature_stats.extend(features)
                if self.verbose:
                    print(f"   → Extracted {len(features)} features")

        # Sort by discrimination score
        self.feature_stats.sort(key=lambda x: x.discrimination_score, reverse=True)

    def categorize_features(self) -> list[FeatureCategory]:
        """Group features into categories and calculate recommendations.

        Returns:
            List of FeatureCategory objects
        """
        categories: dict[str, list[FeatureStats]] = {
            "TTP Sequences": [],
            "Temporal Behavioral": [],
            "Infrastructure Fingerprints": [],
            "Credential Strategies": [],
            "MITRE Techniques": [],
            "Campaign Correlation": [],
        }

        # Categorize features
        for feat in self.feature_stats:
            if feat.name.startswith("ttp_"):
                categories["TTP Sequences"].append(feat)
            elif feat.name.startswith("temporal_"):
                categories["Temporal Behavioral"].append(feat)
            elif feat.name.startswith("infra_") or feat.name.startswith("ssh_"):
                categories["Infrastructure Fingerprints"].append(feat)
            elif feat.name.startswith("pwd_"):
                categories["Credential Strategies"].append(feat)
            elif feat.name.startswith("mitre_"):
                categories["MITRE Techniques"].append(feat)
            elif feat.name.startswith("corr_"):
                categories["Campaign Correlation"].append(feat)

        # Create category objects
        result = []
        for cat_name, features in categories.items():
            if features:
                avg_disc = sum(f.discrimination_score for f in features) / len(features)
                # Recommend top features based on discrimination score threshold
                recommended = len([f for f in features if f.discrimination_score >= 0.6])
                result.append(
                    FeatureCategory(
                        category=cat_name,
                        features=features,
                        avg_discrimination=avg_disc,
                        recommended_count=recommended,
                    )
                )

        return result

    def generate_report(self, output_path: Path, top_n: int = 40) -> None:
        """Generate comprehensive feature discovery analysis report.

        Args:
            output_path: Path to output Markdown report
            top_n: Number of top features to recommend
        """
        categories = self.categorize_features()

        # Calculate overall statistics
        total_features = len(self.feature_stats)
        avg_discrimination = (
            sum(f.discrimination_score for f in self.feature_stats) / total_features if total_features > 0 else 0.0
        )
        recommended_features = [f for f in self.feature_stats if f.discrimination_score >= 0.6]

        # Build report
        lines = [
            "# Phase 1A Feature Discovery Analysis Report",
            "",
            f"**Generated**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Total Features Analyzed**: {total_features}",
            f"**Average Discrimination Score**: {avg_discrimination:.3f}",
            f"**Features Above Threshold (≥0.6)**: {len(recommended_features)}",
            "",
            "---",
            "",
            "## Executive Summary",
            "",
            f"Analyzed {total_features} potential features from 10 SQL queries. "
            f"Identified **{len(recommended_features)} high-discrimination features** suitable for "
            "threat actor clustering.",
            "",
            "### Recommended Feature Count: **{count}**".format(count=min(top_n, len(recommended_features))),
            "",
            "Based on statistical analysis (variance, mutual information, chi-square tests), "
            f"we recommend using the top **{min(top_n, len(recommended_features))} features** "
            "for Phase 1B Random Forest training.",
            "",
            "---",
            "",
            "## Top Features by Discrimination Score",
            "",
            "| Rank | Feature | Disc. Score | Variance | MI | Chi² | Samples |",
            "|------|---------|-------------|----------|-----|------|---------|",
        ]

        # Add top N features
        for rank, feat in enumerate(self.feature_stats[:top_n], 1):
            lines.append(
                f"| {rank} | `{feat.name}` | {feat.discrimination_score:.3f} | "
                f"{feat.variance:.3f} | {feat.mutual_information:.3f} | "
                f"{feat.chi_square:.1f} | {feat.sample_count} |"
            )

        lines.extend(
            [
                "",
                "---",
                "",
                "## Feature Categories Analysis",
                "",
            ]
        )

        # Add category analysis
        for category in sorted(categories, key=lambda c: c.avg_discrimination, reverse=True):
            lines.extend(
                [
                    f"### {category.category}",
                    "",
                    f"- **Features Analyzed**: {len(category.features)}",
                    f"- **Average Discrimination**: {category.avg_discrimination:.3f}",
                    f"- **Recommended Count**: {category.recommended_count}",
                    "",
                    "**Top Features in Category**:",
                    "",
                ]
            )

            for feat in category.features[:5]:
                lines.append(f"- `{feat.name}`: {feat.discrimination_score:.3f} ({feat.unique_values} unique values)")

            lines.extend(["", ""])

        lines.extend(
            [
                "---",
                "",
                "## Statistical Methodology",
                "",
                "### Discrimination Score Calculation",
                "",
                "Combined score (0-1) using weighted average:",
                "- **Variance** (30%): Measures inter-campaign variability",
                "- **Mutual Information** (40%): Measures information gain about campaign identity",
                "- **Chi-Square** (30%): Tests independence from campaign identity",
                "",
                "### Thresholds",
                "",
                "- **High Discrimination**: ≥0.7 (excellent actor discrimination)",
                "- **Moderate Discrimination**: 0.6-0.7 (good discrimination)",
                "- **Low Discrimination**: <0.6 (consider excluding)",
                "",
                "---",
                "",
                "## Recommendations for Phase 1B",
                "",
                f"1. **Feature Set**: Use top {min(top_n, len(recommended_features))} features "
                "for Random Forest training",
                "2. **Implementation**: Create `cowrieprocessor/features/ttp_features.py`",
                "3. **Validation**: Test on 22-incident Phase 0 baseline dataset",
                "4. **Target Metrics**:",
                "   - Recall: ≥0.85 (minimize missed threat actors)",
                "   - Precision: ≥0.70 (acceptable false positive rate)",
                "   - F1 Score: ≥0.75 (30% improvement over 0.667 baseline)",
                "",
                "---",
                "",
                "## Next Steps",
                "",
                "1. **Review SSH Key Features**: Query 5 (SSH key reuse) is **gold mine** - "
                "validate these features on production data",
                "2. **MITRE Mapping**: Implement MITRE ATT&CK mapper for technique-based features",
                "3. **Feature Engineering**: Implement top features in production code",
                "4. **Phase 1B Kickoff**: Begin Random Forest training with selected features",
                "",
                "---",
                "",
                "**Report End**",
            ]
        )

        # Write report
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines))

        if self.verbose:
            print(f"\n✅ Report generated: {output_path}")


def main() -> None:
    """Main entry point for feature importance analysis."""
    parser = argparse.ArgumentParser(
        description="Analyze SQL query results for feature importance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("results"),
        help="Directory containing CSV results from SQL queries (default: results/)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/phase1/feature_discovery_analysis.md"),
        help="Output path for analysis report (default: docs/phase1/feature_discovery_analysis.md)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=40,
        help="Number of top features to recommend (default: 40)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )

    args = parser.parse_args()

    try:
        # Initialize analyzer
        analyzer = FeatureImportanceAnalyzer(results_dir=args.results_dir, verbose=args.verbose)

        # Load query results
        if args.verbose:
            print("📂 Loading SQL query results...")
        query_results = analyzer.load_query_results()
        print(f"✓ Loaded {len(query_results)} query results")

        # Analyze all queries
        if args.verbose:
            print("\n🔬 Analyzing features...")
        analyzer.analyze_all_queries(query_results)
        print(f"✓ Analyzed {len(analyzer.feature_stats)} features")

        # Generate report
        if args.verbose:
            print("\n📝 Generating report...")
        analyzer.generate_report(output_path=args.output, top_n=args.top_n)
        print(f"\n✅ Analysis complete! Report: {args.output}")

        # Print summary
        top_features = analyzer.feature_stats[: args.top_n]
        avg_top_score = sum(f.discrimination_score for f in top_features) / len(top_features) if top_features else 0.0

        print("\n📊 Summary:")
        print(f"   Top {args.top_n} features avg discrimination: {avg_top_score:.3f}")
        print(f"   Feature categories: {len(analyzer.categorize_features())}")
        print(f"\n🎯 Next: Review {args.output} and proceed to Phase 1B")

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
