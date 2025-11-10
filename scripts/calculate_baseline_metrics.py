#!/usr/bin/env python3
"""Calculate baseline detection metrics on MVP test dataset.

This script runs the current snowshoe detection algorithm on the labeled
MVP test dataset and calculates precision, recall, F1 score, and accuracy.
It also identifies common failure modes to guide algorithm improvements.

Usage:
    uv run python scripts/calculate_baseline_metrics.py

The script expects test data in:
    tests/fixtures/snowshoe_baseline/
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class DetectionResult:
    """Result of detection for a single incident."""

    incident_id: str
    category: str
    ground_truth: str
    detected_as: str
    correct: bool
    ip_count: int
    session_count: int
    characteristics: dict[str, Any]


def load_test_dataset() -> list[dict[str, Any]]:
    """Load all incidents from snowshoe_baseline fixtures.

    Returns:
        List of incident dictionaries with metadata and data.
    """
    fixtures_dir = Path(__file__).parent.parent / "tests" / "fixtures" / "snowshoe_baseline"
    incidents = []

    # Iterate through category directories
    for category_dir in fixtures_dir.iterdir():
        if not category_dir.is_dir() or category_dir.name.startswith("."):
            continue

        # Load all metadata files in this category
        for metadata_file in category_dir.glob("*_metadata.json"):
            with metadata_file.open() as f:
                metadata = json.load(f)

            # Load corresponding data file
            data_file = metadata_file.parent / metadata_file.name.replace("_metadata.json", "_data.json")
            if data_file.exists():
                with data_file.open() as f:
                    data = json.load(f)
                metadata["sessions"] = data.get("sessions", [])
                metadata["events"] = data.get("events", [])

            incidents.append(metadata)

    return incidents


def run_baseline_detector(incident: dict[str, Any]) -> str:
    """Run baseline snowshoe detector on incident.

    This implements a simple heuristic-based detector to establish baseline
    performance before implementing the full longtail analyzer.

    Baseline detection rules:
    1. High IP count (>=50) + password reuse = snowshoe_spam
    2. Medium IP count (10-49) + command execution = targeted_attack
    3. Mixed patterns (IP rotation + exploitation) = hybrid
    4. Low IP count (<10) OR clean reputation = legitimate_traffic

    Args:
        incident: Incident dictionary with metadata and session data.

    Returns:
        Detected label: snowshoe_spam, targeted_attack, hybrid, or legitimate_traffic.
    """
    ip_count = incident.get("ip_count", 0)
    session_count = incident.get("session_count", 0)
    characteristics = incident.get("attack_characteristics", {})

    password_reuse = characteristics.get("password_reuse", False)
    command_similarity = characteristics.get("command_similarity", "none")
    geographic_spread = characteristics.get("geographic_spread", "local")

    # Count sessions with command execution
    sessions = incident.get("sessions", [])
    sessions_with_commands = sum(1 for s in sessions if s.get("command_count", 0) > 0)
    command_execution_rate = sessions_with_commands / session_count if session_count > 0 else 0

    # Rule 1: High IP count + password reuse = snowshoe spam
    if ip_count >= 50 and password_reuse:
        return "snowshoe_spam"

    # Rule 2: Medium-high IP count + global spread + no commands = snowshoe spam
    if ip_count >= 30 and geographic_spread == "global" and command_similarity == "none":
        return "snowshoe_spam"

    # Rule 3: Significant IP count + commands = hybrid
    if ip_count >= 20 and command_execution_rate > 0.1:
        return "hybrid"

    # Rule 4: Medium IP count + sustained + commands = targeted attack
    if 10 <= ip_count < 50 and command_execution_rate > 0.2:
        return "targeted_attack"

    # Rule 5: Low IP count + commands = targeted attack
    if ip_count < 10 and command_execution_rate > 0:
        return "targeted_attack"

    # Rule 6: Low IP count + no pattern indicators = legitimate
    if ip_count < 10 and not password_reuse:
        return "legitimate_traffic"

    # Default: classify based on IP count threshold
    if ip_count >= 50:
        return "snowshoe_spam"
    if ip_count >= 10:
        return "hybrid"
    return "legitimate_traffic"


def calculate_metrics(results: list[DetectionResult]) -> dict[str, Any]:
    """Calculate precision, recall, F1, and accuracy metrics.

    For snowshoe spam detection, we use:
    - Positive class: snowshoe_spam
    - Negative class: all other labels

    Args:
        results: List of detection results.

    Returns:
        Dictionary with TP, FP, FN, TN, precision, recall, F1, accuracy.
    """
    # Snowshoe spam is the positive class
    tp = sum(1 for r in results if r.ground_truth == "snowshoe_spam" and r.detected_as == "snowshoe_spam")
    fp = sum(1 for r in results if r.ground_truth != "snowshoe_spam" and r.detected_as == "snowshoe_spam")
    fn = sum(1 for r in results if r.ground_truth == "snowshoe_spam" and r.detected_as != "snowshoe_spam")
    tn = sum(1 for r in results if r.ground_truth != "snowshoe_spam" and r.detected_as != "snowshoe_spam")

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy = (tp + tn) / len(results) if results else 0.0

    return {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "precision": precision,
        "recall": recall,
        "f1_score": f1,
        "accuracy": accuracy,
        "total_incidents": len(results),
    }


def analyze_failures(results: list[DetectionResult]) -> dict[str, list[str]]:
    """Analyze failure modes to identify patterns.

    Args:
        results: List of detection results.

    Returns:
        Dictionary categorizing failure types with examples.
    """
    failures = [r for r in results if not r.correct]

    failure_modes: dict[str, list[str]] = {
        "false_positives_legitimate_as_snowshoe": [],
        "false_positives_targeted_as_snowshoe": [],
        "false_negatives_snowshoe_as_legitimate": [],
        "false_negatives_snowshoe_as_targeted": [],
        "misclassified_hybrid": [],
        "other_misclassifications": [],
    }

    for failure in failures:
        incident_info = f"{failure.incident_id} (IPs:{failure.ip_count}, Sessions:{failure.session_count})"

        if failure.ground_truth == "legitimate_traffic" and failure.detected_as == "snowshoe_spam":
            failure_modes["false_positives_legitimate_as_snowshoe"].append(incident_info)
        elif failure.ground_truth == "targeted_attack" and failure.detected_as == "snowshoe_spam":
            failure_modes["false_positives_targeted_as_snowshoe"].append(incident_info)
        elif failure.ground_truth == "snowshoe_spam" and failure.detected_as == "legitimate_traffic":
            failure_modes["false_negatives_snowshoe_as_legitimate"].append(incident_info)
        elif failure.ground_truth == "snowshoe_spam" and failure.detected_as == "targeted_attack":
            failure_modes["false_negatives_snowshoe_as_targeted"].append(incident_info)
        elif failure.ground_truth == "hybrid" or failure.detected_as == "hybrid":
            failure_modes["misclassified_hybrid"].append(incident_info)
        else:
            failure_modes["other_misclassifications"].append(incident_info)

    return failure_modes


def main() -> None:
    """Calculate baseline metrics and report results."""
    print("=" * 70)
    print("Snowshoe Detection - Baseline Metrics Calculation")
    print("=" * 70)
    print()

    # Load test dataset
    print("Loading test dataset...")
    incidents = load_test_dataset()
    print(f"✅ Loaded {len(incidents)} labeled incidents")
    print()

    # Run detector on each incident
    print("Running baseline detector on all incidents...")
    results = []

    for incident in incidents:
        detected = run_baseline_detector(incident)
        ground_truth = incident["ground_truth_label"]

        result = DetectionResult(
            incident_id=incident["incident_id"],
            category=incident["category"],
            ground_truth=ground_truth,
            detected_as=detected,
            correct=(ground_truth == detected),
            ip_count=incident["ip_count"],
            session_count=incident["session_count"],
            characteristics=incident["attack_characteristics"],
        )
        results.append(result)

        # Show progress
        status = "✅" if result.correct else "❌"
        print(f"  {status} {result.incident_id}: {result.ground_truth} → {result.detected_as}")

    print()

    # Calculate metrics
    metrics = calculate_metrics(results)

    print("=" * 70)
    print("Baseline Detection Results")
    print("=" * 70)
    print()
    print(f"Total Incidents Tested: {metrics['total_incidents']}")
    print()
    print("Confusion Matrix (Snowshoe Spam as Positive Class):")
    print(f"  True Positives (TP):  {metrics['true_positives']:3d}  (correctly detected snowshoe spam)")
    print(f"  False Positives (FP): {metrics['false_positives']:3d}  (legitimate/targeted flagged as snowshoe)")
    print(f"  False Negatives (FN): {metrics['false_negatives']:3d}  (missed snowshoe spam)")
    print(f"  True Negatives (TN):  {metrics['true_negatives']:3d}  (correctly identified non-snowshoe)")
    print()
    print("Performance Metrics:")
    print(f"  Precision: {metrics['precision']:.3f}  (TP / (TP + FP)) - How many detections were correct?")
    print(f"  Recall:    {metrics['recall']:.3f}  (TP / (TP + FN)) - How many attacks did we catch?")
    print(f"  F1 Score:  {metrics['f1_score']:.3f}  (Harmonic mean of precision and recall)")
    print(f"  Accuracy:  {metrics['accuracy']:.3f}  ((TP + TN) / Total) - Overall correctness")
    print()

    # Analyze failure modes
    failure_modes = analyze_failures(results)

    print("=" * 70)
    print("Failure Mode Analysis")
    print("=" * 70)
    print()

    total_failures = sum(len(incidents) for incidents in failure_modes.values())
    if total_failures == 0:
        print("✅ No failures detected! Perfect baseline performance.")
    else:
        print(f"Total Misclassifications: {total_failures}")
        print()

        for mode, incidents in failure_modes.items():
            if incidents:
                mode_name = mode.replace("_", " ").title()
                print(f"{mode_name} ({len(incidents)}):")
                for incident in list(incidents):  # Convert to list for type safety
                    print(f"  - {incident}")
                print()

    # Recommendations
    print("=" * 70)
    print("Recommendations for Algorithm Improvement")
    print("=" * 70)
    print()

    if metrics["precision"] < 0.8:
        print("⚠️  Low Precision: Too many false positives")
        print("    → Tighten detection thresholds to reduce false alarms")
        print("    → Add more sophisticated features beyond IP count")
        print()

    if metrics["recall"] < 0.8:
        print("⚠️  Low Recall: Missing too many attacks")
        print("    → Lower detection thresholds or add alternative detection paths")
        print("    → Improve handling of edge cases and hybrid attacks")
        print()

    if len(failure_modes["misclassified_hybrid"]) > 0:
        print("⚠️  Hybrid Attack Confusion")
        print("    → Develop separate detection logic for hybrid patterns")
        print("    → Consider multi-label classification approach")
        print()

    if metrics["f1_score"] < 0.7:
        print("⚠️  Overall F1 Score Below Target")
        print("    → Current heuristic-based approach needs enhancement")
        print("    → Consider machine learning approach with feature engineering")
        print("    → Add temporal, behavioral, and enrichment-based features")
        print()

    print("=" * 70)
    print()
    print("Next Steps:")
    print("1. Document these baseline metrics in Phase 0 research document")
    print("2. Use failure analysis to guide longtail algorithm development")
    print("3. Re-run metrics after implementing improved detector")
    print("4. Target: Precision ≥0.90, Recall ≥0.85, F1 ≥0.87")
    print()


if __name__ == "__main__":
    main()
