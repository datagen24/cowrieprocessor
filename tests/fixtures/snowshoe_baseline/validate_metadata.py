#!/usr/bin/env python3
"""Metadata schema validation for snowshoe baseline dataset.

This script validates incident metadata JSON files against the canonical schema.
Used to ensure all labeled incidents have complete and accurate metadata.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# JSON Schema for incident metadata
METADATA_SCHEMA = {
    "type": "object",
    "required": [
        "incident_id",
        "category",
        "date_range",
        "ip_count",
        "session_count",
        "attack_characteristics",
        "ground_truth_label",
        "confidence",
        "reviewer",
        "review_date",
    ],
    "properties": {
        "incident_id": {
            "type": "string",
            "pattern": r"^[a-z_]+_\d{3}_\d{8}$",
            "description": "Format: {category}_{number}_{YYYYMMDD}",
        },
        "category": {
            "type": "string",
            "enum": [
                "credential_stuffing",
                "targeted_attacks",
                "hybrid_attacks",
                "legitimate_traffic",
                "edge_cases",
            ],
        },
        "date_range": {
            "type": "object",
            "required": ["start", "end"],
            "properties": {
                "start": {"type": "string", "format": "date-time"},
                "end": {"type": "string", "format": "date-time"},
            },
        },
        "ip_count": {"type": "integer", "minimum": 1},
        "session_count": {"type": "integer", "minimum": 1},
        "attack_characteristics": {
            "type": "object",
            "required": [
                "password_reuse",
                "username_reuse",
                "geographic_spread",
                "temporal_pattern",
                "command_similarity",
            ],
            "properties": {
                "password_reuse": {"type": "boolean"},
                "username_reuse": {"type": "boolean"},
                "geographic_spread": {
                    "type": "string",
                    "enum": ["local", "regional", "national", "global"],
                },
                "temporal_pattern": {
                    "type": "string",
                    "enum": ["burst", "sustained", "sporadic", "mixed"],
                },
                "command_similarity": {
                    "type": "string",
                    "enum": ["none", "low", "medium", "high", "identical"],
                },
            },
        },
        "ground_truth_label": {
            "type": "string",
            "enum": [
                "snowshoe_spam",
                "targeted_attack",
                "legitimate_traffic",
                "unknown",
                "hybrid",
            ],
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
        "reviewer": {"type": "string"},
        "review_date": {"type": "string", "format": "date"},
        "notes": {"type": "string"},
        "enrichment_coverage": {
            "type": "object",
            "properties": {
                "virustotal": {"type": "number", "minimum": 0, "maximum": 1},
                "dshield": {"type": "number", "minimum": 0, "maximum": 1},
                "hibp": {"type": "number", "minimum": 0, "maximum": 1},
            },
        },
    },
}


def validate_date_format(date_str: str, field_name: str) -> bool:
    """Validate ISO 8601 date/datetime format.

    Args:
        date_str: Date string to validate
        field_name: Name of field for error messages

    Returns:
        True if valid, False otherwise
    """
    try:
        datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return True
    except ValueError as e:
        print(f"  ❌ {field_name}: Invalid date format: {e}")
        return False


def validate_incident_id(incident_id: str, category: str) -> bool:
    """Validate incident_id follows naming convention.

    Args:
        incident_id: Incident ID to validate
        category: Expected category

    Returns:
        True if valid, False otherwise
    """
    parts = incident_id.split("_")
    if len(parts) < 3:
        print("  ❌ incident_id: Must have format {category}_{number}_{date}")
        return False

    id_category = "_".join(parts[:-2])  # Everything except last 2 parts
    if id_category != category:
        print(f"  ❌ incident_id: Category mismatch (ID: {id_category}, metadata: {category})")
        return False

    # Validate date part (YYYYMMDD)
    date_part = parts[-1]
    if len(date_part) != 8 or not date_part.isdigit():
        print(f"  ❌ incident_id: Date must be YYYYMMDD format, got: {date_part}")
        return False

    return True


def validate_metadata(metadata: dict[str, Any], filename: str) -> bool:
    """Validate metadata against schema.

    Args:
        metadata: Metadata dictionary to validate
        filename: Source filename for error messages

    Returns:
        True if valid, False otherwise
    """
    print(f"\nValidating {filename}...")
    valid = True

    # Check required fields
    required_fields: list[str] = METADATA_SCHEMA["required"]  # type: ignore[assignment]
    for field in required_fields:
        if field not in metadata:
            print(f"  ❌ Missing required field: {field}")
            valid = False

    if not valid:
        return False

    # Validate incident_id format
    incident_id = metadata.get("incident_id", "")
    category = metadata.get("category", "")
    if not validate_incident_id(incident_id, category):
        valid = False

    # Validate category
    if category not in METADATA_SCHEMA["properties"]["category"]["enum"]:
        print(f"  ❌ Invalid category: {category}")
        valid = False

    # Validate date_range
    date_range = metadata.get("date_range", {})
    if "start" not in date_range or "end" not in date_range:
        print("  ❌ date_range must have 'start' and 'end' fields")
        valid = False
    else:
        if not validate_date_format(date_range["start"], "date_range.start"):
            valid = False
        if not validate_date_format(date_range["end"], "date_range.end"):
            valid = False

    # Validate counts
    for count_field in ["ip_count", "session_count"]:
        count = metadata.get(count_field, 0)
        if not isinstance(count, int) or count < 1:
            print(f"  ❌ {count_field} must be positive integer, got: {count}")
            valid = False

    # Validate attack_characteristics
    attack_chars = metadata.get("attack_characteristics", {})
    required_chars: list[str] = METADATA_SCHEMA["properties"]["attack_characteristics"]["required"]  # type: ignore[assignment]
    for char_field in required_chars:
        if char_field not in attack_chars:
            print(f"  ❌ attack_characteristics.{char_field} is required")
            valid = False

    # Validate enums
    for enum_field in ["geographic_spread", "temporal_pattern", "command_similarity"]:
        value = attack_chars.get(enum_field)
        allowed: list[str] = METADATA_SCHEMA["properties"]["attack_characteristics"]["properties"][enum_field]["enum"]  # type: ignore[assignment]
        if value not in allowed:
            print(f"  ❌ attack_characteristics.{enum_field}: '{value}' not in {allowed}")
            valid = False

    # Validate ground_truth_label
    label = metadata.get("ground_truth_label", "")
    allowed_labels: list[str] = METADATA_SCHEMA["properties"]["ground_truth_label"]["enum"]  # type: ignore[assignment]
    if label not in allowed_labels:
        print(f"  ❌ ground_truth_label: '{label}' not in {allowed_labels}")
        valid = False

    # Validate confidence
    confidence = metadata.get("confidence", "")
    if confidence not in ["high", "medium", "low"]:
        print(f"  ❌ confidence must be high/medium/low, got: {confidence}")
        valid = False

    # Validate review_date
    review_date = metadata.get("review_date", "")
    if not validate_date_format(review_date, "review_date"):
        valid = False

    if valid:
        print("  ✅ Valid metadata")

    return valid


def main() -> int:
    """Validate all metadata files in the baseline dataset.

    Returns:
        Exit code (0 = all valid, 1 = validation errors)
    """
    baseline_dir = Path(__file__).parent
    categories = [
        "credential_stuffing",
        "targeted_attacks",
        "hybrid_attacks",
        "legitimate_traffic",
        "edge_cases",
    ]

    total_files = 0
    valid_files = 0
    errors = []

    print("=" * 60)
    print("Snowshoe Baseline Dataset - Metadata Validation")
    print("=" * 60)

    for category in categories:
        category_dir = baseline_dir / category
        if not category_dir.exists():
            print(f"\n⚠️  Category directory not found: {category}")
            continue

        metadata_files = list(category_dir.glob("*_metadata.json"))
        if not metadata_files:
            print(f"\n⚠️  No metadata files in: {category}")
            continue

        for metadata_file in metadata_files:
            total_files += 1
            try:
                with open(metadata_file) as f:
                    metadata = json.load(f)

                if validate_metadata(metadata, f"{category}/{metadata_file.name}"):
                    valid_files += 1
                else:
                    errors.append(f"{category}/{metadata_file.name}")
            except json.JSONDecodeError as e:
                print(f"\n❌ {category}/{metadata_file.name}: Invalid JSON - {e}")
                errors.append(f"{category}/{metadata_file.name}")
            except Exception as e:
                print(f"\n❌ {category}/{metadata_file.name}: Error - {e}")
                errors.append(f"{category}/{metadata_file.name}")

    # Summary
    print("\n" + "=" * 60)
    print(f"Validation Summary: {valid_files}/{total_files} files valid")
    print("=" * 60)

    if errors:
        print("\n❌ Files with errors:")
        for error_file in errors:
            print(f"  - {error_file}")
        return 1
    else:
        print("\n✅ All metadata files are valid!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
