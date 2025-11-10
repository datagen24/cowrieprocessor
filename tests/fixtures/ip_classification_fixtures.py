"""Test fixtures for IP classification module.

This module provides reusable test data and mock objects for IP classification tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import pytest

from cowrieprocessor.enrichment.ip_classification.models import IPClassification, IPType

# Sample IP addresses for testing
SAMPLE_TOR_IP = "185.220.101.1"
SAMPLE_AWS_IP = "52.0.0.1"
SAMPLE_AZURE_IP = "13.107.0.1"
SAMPLE_GCP_IP = "35.190.0.1"
SAMPLE_CLOUDFLARE_IP = "104.16.0.1"
SAMPLE_DIGITALOCEAN_IP = "104.236.1.1"
SAMPLE_LINODE_IP = "45.79.0.1"
SAMPLE_RESIDENTIAL_IP = "98.97.96.95"  # Comcast range
SAMPLE_UNKNOWN_IP = "192.0.2.1"  # TEST-NET-1

# TOR exit node list (plain text format)
MOCK_TOR_EXIT_LIST = """185.220.101.1
185.220.101.2
185.220.101.3
2001:db8::1"""

# Cloud provider CSV data (AWS example)
MOCK_AWS_CSV = """ip_prefix,region,service
52.0.0.0/16,us-east-1,ec2
52.1.0.0/16,us-west-2,ec2
52.2.0.0/16,eu-west-1,s3"""

MOCK_AZURE_CSV = """ip_prefix,region,service
13.107.0.0/16,eastus,compute
13.108.0.0/16,westus,storage"""

MOCK_GCP_CSV = """ip_prefix,region,service
35.190.0.0/16,us-central1,compute
35.191.0.0/16,us-east1,compute"""

MOCK_CLOUDFLARE_CSV = """ip_prefix,region,service
104.16.0.0/16,global,cdn
104.17.0.0/16,global,cdn"""

# Datacenter CSV data
MOCK_DIGITALOCEAN_CSV = """ip_prefix,region,provider
104.236.0.0/16,nyc1,digitalocean
104.237.0.0/16,nyc2,digitalocean"""

MOCK_LINODE_CSV = """ip_prefix,region,provider
45.79.0.0/16,us-east,linode
45.80.0.0/16,us-west,linode"""

MOCK_OVH_CSV = """ip_prefix,region,provider
51.38.0.0/16,eu,ovh
51.39.0.0/16,us,ovh"""

MOCK_HETZNER_CSV = """ip_prefix,region,provider
5.75.0.0/16,de,hetzner
5.76.0.0/16,fi,hetzner"""

MOCK_VULTR_CSV = """ip_prefix,region,provider
45.76.0.0/16,us,vultr
45.77.0.0/16,eu,vultr"""


@pytest.fixture
def mock_tor_exit_nodes() -> str:
    """Return mock TOR exit node list."""
    return MOCK_TOR_EXIT_LIST


@pytest.fixture
def mock_cloud_provider_csvs() -> Dict[str, str]:
    """Return mock cloud provider CSV data."""
    return {
        "aws": MOCK_AWS_CSV,
        "azure": MOCK_AZURE_CSV,
        "gcp": MOCK_GCP_CSV,
        "cloudflare": MOCK_CLOUDFLARE_CSV,
    }


@pytest.fixture
def mock_datacenter_csvs() -> Dict[str, str]:
    """Return mock datacenter provider CSV data."""
    return {
        "digitalocean": MOCK_DIGITALOCEAN_CSV,
        "linode": MOCK_LINODE_CSV,
        "ovh": MOCK_OVH_CSV,
        "hetzner": MOCK_HETZNER_CSV,
        "vultr": MOCK_VULTR_CSV,
    }


@pytest.fixture
def sample_classification_tor() -> IPClassification:
    """Return sample TOR classification."""
    return IPClassification(
        ip_type=IPType.TOR,
        provider="tor",
        confidence=0.95,
        source="tor_bulk_list",
        classified_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_classification_cloud() -> IPClassification:
    """Return sample cloud classification."""
    return IPClassification(
        ip_type=IPType.CLOUD,
        provider="aws",
        confidence=0.99,
        source="cloud_ranges_aws",
        classified_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_classification_datacenter() -> IPClassification:
    """Return sample datacenter classification."""
    return IPClassification(
        ip_type=IPType.DATACENTER,
        provider="digitalocean",
        confidence=0.75,
        source="datacenter_community_lists",
        classified_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_classification_residential() -> IPClassification:
    """Return sample residential classification."""
    return IPClassification(
        ip_type=IPType.RESIDENTIAL,
        provider="Comcast Cable",
        confidence=0.8,
        source="asn_name_heuristic",
        classified_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_classification_unknown() -> IPClassification:
    """Return sample unknown classification."""
    return IPClassification(
        ip_type=IPType.UNKNOWN,
        provider=None,
        confidence=0.0,
        source="none",
        classified_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_asn_data() -> Dict[str, Any]:
    """Return sample ASN data for testing."""
    return {
        "comcast": {"asn": 7922, "as_name": "Comcast Cable Communications"},
        "verizon": {"asn": 701, "as_name": "Verizon Business"},
        "att": {"asn": 7018, "as_name": "AT&T Services"},
        "google": {"asn": 15169, "as_name": "Google LLC"},
        "amazon": {"asn": 16509, "as_name": "Amazon.com, Inc."},
        "digitalocean": {"asn": 14061, "as_name": "DigitalOcean, LLC"},
    }


@pytest.fixture
def sample_enrichment_jsonb() -> Dict[str, Any]:
    """Return sample enrichment JSONB data."""
    return {
        "ip_type": "cloud",
        "provider": "aws",
        "confidence": 0.99,
        "source": "cloud_ranges_aws",
        "classified_at": "2025-01-01T12:00:00+00:00",
        "region": "us-east-1",
        "service": "ec2",
    }
