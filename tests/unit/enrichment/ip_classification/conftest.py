"""Shared fixtures for IP classification tests."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine

from cowrieprocessor.db.models import Base
from tests.fixtures.ip_classification_fixtures import (
    MOCK_AWS_CSV,
    MOCK_AZURE_CSV,
    MOCK_CLOUDFLARE_CSV,
    MOCK_DIGITALOCEAN_CSV,
    MOCK_GCP_CSV,
    MOCK_HETZNER_CSV,
    MOCK_LINODE_CSV,
    MOCK_OVH_CSV,
    MOCK_TOR_EXIT_LIST,
    MOCK_UNIFIED_DATACENTER_CSV,
    MOCK_VULTR_CSV,
)


@pytest.fixture
def mock_db_engine():
    """Create in-memory SQLite engine with ORM models for all IP classification tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def mock_all_network_requests():
    """Mock all network requests for IP classification data sources.

    This fixture ensures that tests don't make real HTTP requests and provides
    consistent mock data for all matchers (TOR, Cloud, Datacenter).
    """

    def mock_response_factory(url: str, **kwargs) -> Mock:
        """Create appropriate mock response based on URL.

        Handles both cloud matcher URLs (rezmoss repo) and datacenter URLs (jhassine repo).
        """
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200

        # TOR matcher
        if "torproject.org" in url or "torbulkexitlist" in url:
            mock_response.text = MOCK_TOR_EXIT_LIST
        # Cloud matchers (rezmoss repo with {provider}/ipv4.txt format)
        elif "rezmoss" in url:
            if "aws" in url:
                mock_response.text = MOCK_AWS_CSV
            elif "azure" in url:
                mock_response.text = MOCK_AZURE_CSV
            elif "gcp" in url:
                mock_response.text = MOCK_GCP_CSV
            elif "cloudflare" in url:
                mock_response.text = MOCK_CLOUDFLARE_CSV
            else:
                mock_response.text = ""
        # Datacenter matchers (jhassine repo with unified data/datacenters.csv format)
        elif "jhassine" in url:
            # New unified CSV format: single file with all providers
            if "datacenters.csv" in url:
                mock_response.text = MOCK_UNIFIED_DATACENTER_CSV
            # Legacy per-provider format (for backward compatibility in tests)
            elif "digitalocean" in url:
                mock_response.text = MOCK_DIGITALOCEAN_CSV
            elif "linode" in url:
                mock_response.text = MOCK_LINODE_CSV
            elif "ovh" in url:
                mock_response.text = MOCK_OVH_CSV
            elif "hetzner" in url:
                mock_response.text = MOCK_HETZNER_CSV
            elif "vultr" in url:
                mock_response.text = MOCK_VULTR_CSV
            else:
                mock_response.text = ""
        else:
            # Return empty for unknown URLs to prevent real requests
            mock_response.text = ""

        return mock_response

    # Patch all requests.get calls in IP classification modules
    with (
        patch("cowrieprocessor.enrichment.ip_classification.tor_matcher.requests.get") as tor_mock,
        patch("cowrieprocessor.enrichment.ip_classification.cloud_matcher.requests.get") as cloud_mock,
        patch("cowrieprocessor.enrichment.ip_classification.datacenter_matcher.requests.get") as dc_mock,
    ):
        # Configure mocks to use factory
        tor_mock.side_effect = mock_response_factory
        cloud_mock.side_effect = mock_response_factory
        dc_mock.side_effect = mock_response_factory

        yield {
            "tor": tor_mock,
            "cloud": cloud_mock,
            "datacenter": dc_mock,
        }
