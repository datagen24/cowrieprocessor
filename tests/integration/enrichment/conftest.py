"""Pytest fixtures for IP classification integration tests.

Provides fixtures for testing with mock data sources to avoid network dependencies.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def mock_cloud_data(tmp_path: Path) -> dict[str, Path]:
    """Create mock cloud provider IP range files.

    Returns:
        Dict mapping provider name to cache file path
    """
    cache_dir = tmp_path / "cache" / "ip_classification"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Mock AWS IP ranges (CloudFront IPs for 8.8.8.8 test)
    aws_ranges = [
        "8.8.8.0/24",  # Google DNS range (for testing)
        "52.0.0.0/16",  # AWS EC2 range
        "54.0.0.0/8",  # AWS EC2 range
    ]

    # Mock Azure IP ranges
    azure_ranges = [
        "13.64.0.0/11",
        "40.64.0.0/10",
    ]

    # Mock GCP IP ranges
    gcp_ranges = [
        "8.8.4.0/24",  # Google Public DNS
        "8.8.8.0/24",  # Google Public DNS
        "35.184.0.0/13",
    ]

    # Mock Cloudflare IP ranges
    cloudflare_ranges = [
        "1.1.1.0/24",  # Cloudflare DNS
        "104.16.0.0/12",
    ]

    # Write cache files
    providers = {
        "aws": aws_ranges,
        "azure": azure_ranges,
        "gcp": gcp_ranges,
        "cloudflare": cloudflare_ranges,
    }

    cache_files = {}
    for provider, ranges in providers.items():
        cache_file = cache_dir / f"{provider}_ipv4.json"
        data = {
            "cidrs": ranges,
            "provider": provider,
            "last_updated": "2025-11-10T00:00:00Z",
        }
        cache_file.write_text(json.dumps(data))
        cache_files[provider] = cache_file

    return cache_files


@pytest.fixture
def mock_tor_data(tmp_path: Path) -> Path:
    """Create mock TOR exit node list.

    Returns:
        Path to mock TOR exit node cache file
    """
    cache_dir = tmp_path / "cache" / "ip_classification"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Mock TOR exit nodes
    tor_exits = [
        "185.220.100.240",
        "185.220.101.1",
        "192.42.116.16",
    ]

    cache_file = cache_dir / "tor_exit_nodes.json"
    data = {
        "exit_nodes": tor_exits,
        "last_updated": "2025-11-10T00:00:00Z",
    }
    cache_file.write_text(json.dumps(data))

    return cache_file


@pytest.fixture
def mock_datacenter_data(tmp_path: Path) -> Path:
    """Create mock datacenter IP range file.

    Returns:
        Path to mock datacenter cache file
    """
    cache_dir = tmp_path / "cache" / "ip_classification"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Mock datacenter ranges
    datacenter_ranges = [
        {"cidr": "198.51.100.0/24", "provider": "Test Datacenter"},
        {"cidr": "203.0.113.0/24", "provider": "TEST-NET-3"},
    ]

    cache_file = cache_dir / "datacenter_ranges.json"
    data = {
        "ranges": datacenter_ranges,
        "last_updated": "2025-11-10T00:00:00Z",
    }
    cache_file.write_text(json.dumps(data))

    return cache_file


@pytest.fixture
def pre_populated_cache(tmp_path: Path, mock_cloud_data, mock_tor_data, mock_datacenter_data) -> Path:
    """Create pre-populated cache directory with all mock data.

    Returns:
        Path to cache directory with mock data files
    """
    return tmp_path / "cache"
