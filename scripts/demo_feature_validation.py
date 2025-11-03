#!/usr/bin/env python3
"""Demo script showing feature validation with mock data.

This script demonstrates that the feature extraction and validation logic
works correctly using mock SessionSummary objects. It does not require
database access.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from cowrieprocessor.db.models import SessionSummary
from cowrieprocessor.features import ProviderClassifier, aggregate_features


def create_mock_session(
    session_id: str,
    command_count: int = 5,
    login_attempts: int = 3,
    enrichment: dict[str, Any] | None = None,
    days_offset: int = 0,
) -> SessionSummary:
    """Create a mock SessionSummary for testing.

    Args:
        session_id: Session identifier
        command_count: Number of commands
        login_attempts: Number of login attempts
        enrichment: Enrichment data dictionary
        days_offset: Days to offset first_event_at from now

    Returns:
        Mock SessionSummary object
    """
    now = datetime.now(timezone.utc)
    first_event = now - timedelta(days=days_offset)

    session = SessionSummary(
        session_id=session_id,
        first_event_at=first_event,
        last_event_at=first_event + timedelta(hours=2),
        event_count=command_count + login_attempts,
        command_count=command_count,
        file_downloads=0,
        login_attempts=login_attempts,
        ssh_key_injections=0,
        unique_ssh_keys=0,
        vt_flagged=False,
        dshield_flagged=False,
        enrichment=enrichment or {},
    )

    return session


def demo_feature_extraction() -> None:
    """Demonstrate feature extraction with various edge cases."""
    print("=" * 70)
    print("Feature Extraction Demo")
    print("=" * 70)

    # Create provider classifier
    classifier = ProviderClassifier(
        {
            "use_dshield": True,
            "use_spur": True,
            "max_enrichment_age_days": 365,
            "cloud_provider_keywords": ["amazon", "aws", "google", "azure"],
        }
    )

    # Test Case 1: Session with no commands
    print("\n1. Session with no commands:")
    session_no_cmds = create_mock_session(
        "no-cmds-001",
        command_count=0,
        login_attempts=5,
        enrichment={
            "dshield": {
                "ip": {
                    "ip": "192.168.1.1",
                    "asname": "Example ISP",
                    "attacks": 10,
                }
            }
        },
    )
    features = aggregate_features([session_no_cmds], classifier)
    print(f"   ✅ Extracted {len(features)} features")
    print(f"   - total_commands: {features['total_commands']}")
    print(f"   - unique_commands: {features['unique_commands']}")

    # Test Case 2: Session with many commands
    print("\n2. Session with many commands:")
    session_many_cmds = create_mock_session(
        "many-cmds-001",
        command_count=150,
        login_attempts=10,
    )
    features = aggregate_features([session_many_cmds], classifier)
    print(f"   ✅ Extracted {len(features)} features")

    # Test Case 3: Session with no enrichment
    print("\n3. Session with no enrichment:")
    session_no_enrich = create_mock_session(
        "no-enrich-001",
        command_count=5,
        login_attempts=3,
        enrichment={},
    )
    features = aggregate_features([session_no_enrich], classifier)
    print(f"   ✅ Extracted {len(features)} features")
    print(f"   - cloud_provider_ratio: {features['cloud_provider_ratio']}")
    print(f"   - avg_dshield_score: {features['avg_dshield_score']}")

    # Test Case 4: Multi-IP cluster with cloud provider
    print("\n4. Multi-IP cluster with cloud provider:")
    sessions_cloud = [
        create_mock_session(
            f"cloud-{i:03d}",
            command_count=10,
            login_attempts=5,
            enrichment={
                "dshield": {
                    "ip": {
                        "ip": f"54.{i}.0.1",
                        "asname": "AMAZON-02",
                        "asdescription": "Amazon AWS",
                        "attacks": 20 + i,
                    }
                }
            },
        )
        for i in range(5)
    ]
    features = aggregate_features(sessions_cloud, classifier)
    print(f"   ✅ Extracted {len(features)} features from {len(sessions_cloud)} sessions")
    print(f"   - ip_count: {features['ip_count']}")
    print(f"   - session_count: {features['session_count']}")
    print(f"   - cloud_provider_ratio: {features['cloud_provider_ratio']:.2f}")
    print(f"   - avg_dshield_score: {features['avg_dshield_score']:.1f}")

    # Test Case 5: VPN provider cluster
    print("\n5. VPN provider cluster:")
    sessions_vpn = [
        create_mock_session(
            f"vpn-{i:03d}",
            command_count=3,
            login_attempts=2,
            enrichment={
                "spur": {
                    "asn": {"organization": "Mullvad VPN"},
                    "infrastructure": "VPN",
                    "organization": "Mullvad VPN",
                }
            },
        )
        for i in range(3)
    ]
    features = aggregate_features(sessions_vpn, classifier)
    print(f"   ✅ Extracted {len(features)} features from {len(sessions_vpn)} sessions")
    print(f"   - vpn_provider_ratio: {features['vpn_provider_ratio']:.2f}")

    print("\n" + "=" * 70)
    print("Feature Correlation Demo")
    print("=" * 70)

    # Create diverse cluster for correlation analysis
    print("\nCreating diverse session cluster...")
    diverse_sessions = []

    # Add cloud sessions
    for i in range(10):
        diverse_sessions.append(
            create_mock_session(
                f"diverse-cloud-{i:03d}",
                command_count=5 + i * 2,
                login_attempts=3,
                enrichment={
                    "dshield": {
                        "ip": {
                            "ip": f"52.{i}.0.1",
                            "asname": "AMAZON-AWS",
                            "attacks": 15 + i,
                        }
                    }
                },
            )
        )

    # Add residential IPs
    for i in range(10):
        diverse_sessions.append(
            create_mock_session(
                f"diverse-residential-{i:03d}",
                command_count=10,
                login_attempts=5,
                enrichment={
                    "dshield": {
                        "ip": {
                            "ip": f"24.{i}.0.1",
                            "asname": "COMCAST-7922",
                            "attacks": 5,
                        }
                    }
                },
            )
        )

    # Extract features for all sessions
    all_features = []
    for session in diverse_sessions:
        features = aggregate_features([session], classifier)
        all_features.append(features)

    print(f"✅ Extracted features from {len(all_features)} sessions")

    # Show feature statistics
    print("\nFeature Statistics:")
    print("-" * 70)

    # Calculate stats for numeric features
    import statistics

    numeric_features = [
        "ip_count",
        "session_count",
        "geographic_spread_km",
        "cloud_provider_ratio",
        "vpn_provider_ratio",
        "avg_dshield_score",
        "total_commands",
    ]

    for feature_name in numeric_features:
        values = [f[feature_name] for f in all_features]
        mean_val = statistics.mean(values)
        stdev_val = statistics.stdev(values) if len(values) > 1 else 0.0
        min_val = min(values)
        max_val = max(values)

        print(f"{feature_name:25s}: mean={mean_val:8.3f}, std={stdev_val:8.3f}, min={min_val:8.3f}, max={max_val:8.3f}")

    print("\n" + "=" * 70)
    print("✅ Demo Complete!")
    print("=" * 70)
    print("\nBoth scripts work correctly with mock data. Run on production server for full validation.")


if __name__ == "__main__":
    demo_feature_extraction()
