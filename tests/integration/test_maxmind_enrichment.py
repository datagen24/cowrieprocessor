"""Integration tests for MaxMind enrichment workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from cowrieprocessor.enrichment.maxmind_client import MaxMindClient, MaxMindResult


@pytest.fixture
def integration_db_path(tmp_path):
    """Create temporary database path for integration tests."""
    db_path = tmp_path / "integration_maxmind"
    db_path.mkdir()
    return db_path


@pytest.fixture
def mock_complete_city_response():
    """Mock complete city response for integration testing."""
    response = Mock()
    response.country.iso_code = "US"
    response.country.name = "United States"
    response.city.name = "Mountain View"
    response.location.latitude = 37.3860
    response.location.longitude = -122.0838
    response.location.accuracy_radius = 1000
    return response


@pytest.fixture
def mock_complete_asn_response():
    """Mock complete ASN response for integration testing."""
    response = Mock()
    response.autonomous_system_number = 15169
    response.autonomous_system_organization = "GOOGLE"
    return response


class TestMaxMindEndToEndLookup:
    """Test complete lookup workflow from initialization to result."""

    @patch('cowrieprocessor.enrichment.maxmind_client.geoip2.database.Reader')
    def test_complete_lookup_workflow(
        self,
        mock_reader_class,
        integration_db_path,
        mock_complete_city_response,
        mock_complete_asn_response,
    ):
        """Test full workflow: init -> lookup -> result parsing."""
        # Setup database files
        (integration_db_path / "GeoLite2-City.mmdb").touch()
        (integration_db_path / "GeoLite2-ASN.mmdb").touch()

        # Setup mocks
        mock_city_reader = Mock()
        mock_city_reader.city.return_value = mock_complete_city_response
        mock_asn_reader = Mock()
        mock_asn_reader.asn.return_value = mock_complete_asn_response

        mock_reader_class.side_effect = [mock_city_reader, mock_asn_reader]

        # Execute workflow
        with MaxMindClient(db_path=integration_db_path) as client:
            result = client.lookup_ip("8.8.8.8")

            # Verify result completeness
            assert result is not None
            assert isinstance(result, MaxMindResult)
            assert result.ip_address == "8.8.8.8"
            assert result.country_code == "US"
            assert result.country_name == "United States"
            assert result.city == "Mountain View"
            assert result.latitude == 37.3860
            assert result.longitude == -122.0838
            assert result.asn == 15169
            assert result.asn_org == "GOOGLE"
            assert result.accuracy_radius == 1000
            assert result.source == "maxmind"

            # Verify timestamp is recent
            age = datetime.now(timezone.utc) - result.cached_at
            assert age.total_seconds() < 5

            # Verify statistics
            stats = client.get_stats()
            assert stats['lookups'] == 1
            assert stats['city_hits'] == 1
            assert stats['asn_hits'] == 1
            assert stats['errors'] == 0

    @patch('cowrieprocessor.enrichment.maxmind_client.geoip2.database.Reader')
    def test_batch_lookup_workflow(
        self,
        mock_reader_class,
        integration_db_path,
        mock_complete_city_response,
        mock_complete_asn_response,
    ):
        """Test processing multiple IP lookups in sequence."""
        (integration_db_path / "GeoLite2-City.mmdb").touch()
        (integration_db_path / "GeoLite2-ASN.mmdb").touch()

        mock_city_reader = Mock()
        mock_city_reader.city.return_value = mock_complete_city_response
        mock_asn_reader = Mock()
        mock_asn_reader.asn.return_value = mock_complete_asn_response

        mock_reader_class.side_effect = [mock_city_reader, mock_asn_reader]

        test_ips = ["8.8.8.8", "1.1.1.1", "9.9.9.9"]

        with MaxMindClient(db_path=integration_db_path) as client:
            results = []
            for ip in test_ips:
                result = client.lookup_ip(ip)
                results.append(result)

            # Verify all lookups succeeded
            assert len(results) == 3
            assert all(r is not None for r in results)
            assert all(r and r.ip_address == ip for r, ip in zip(results, test_ips))

            # Verify statistics
            stats = client.get_stats()
            assert stats['lookups'] == 3
            assert stats['city_hits'] == 3
            assert stats['asn_hits'] == 3


class TestMaxMindDatabaseLifecycle:
    """Test database initialization, update, and age tracking."""

    def test_database_lifecycle_no_initial_databases(self, integration_db_path):
        """Test lifecycle when starting with no databases."""
        client = MaxMindClient(db_path=integration_db_path)

        # Verify databases don't exist initially
        assert not client.city_db_path.exists()
        assert not client.asn_db_path.exists()

        # Check should_update returns True
        assert client.should_update() is True

        # Lookup should return None without databases
        result = client.lookup_ip("8.8.8.8")
        assert result is None

    def test_database_lifecycle_with_existing_databases(self, integration_db_path):
        """Test lifecycle with pre-existing databases."""
        # Create database files
        city_db = integration_db_path / "GeoLite2-City.mmdb"
        asn_db = integration_db_path / "GeoLite2-ASN.mmdb"
        city_db.touch()
        asn_db.touch()

        client = MaxMindClient(db_path=integration_db_path)

        # Verify databases exist
        assert client.city_db_path.exists()
        assert client.asn_db_path.exists()

        # Check database age
        age = client.get_database_age()
        assert age.total_seconds() < 60  # Very recent

        # Should not need update for fresh databases
        assert client.should_update() is False

    @patch('cowrieprocessor.enrichment.maxmind_client.requests.get')
    @patch('cowrieprocessor.enrichment.maxmind_client.tarfile.open')
    def test_update_workflow_with_license_key(self, mock_tarfile, mock_requests, integration_db_path):
        """Test complete update workflow with license key."""
        client = MaxMindClient(db_path=integration_db_path, license_key="test_key_123")

        # Mock successful update
        with patch.object(client, '_download_and_extract_database', return_value=True):
            success = client.update_database()

        assert success is True


class TestMaxMindErrorHandling:
    """Test error handling and edge cases in integration scenarios."""

    @patch('cowrieprocessor.enrichment.maxmind_client.geoip2.database.Reader')
    def test_graceful_degradation_missing_city_db(
        self, mock_reader_class, integration_db_path, mock_complete_asn_response
    ):
        """Test that client works with only ASN database."""
        # Only create ASN database
        (integration_db_path / "GeoLite2-ASN.mmdb").touch()

        mock_asn_reader = Mock()
        mock_asn_reader.asn.return_value = mock_complete_asn_response
        mock_reader_class.return_value = mock_asn_reader

        with MaxMindClient(db_path=integration_db_path) as client:
            result = client.lookup_ip("8.8.8.8")

            # Should get ASN data even without city database
            assert result is not None
            assert result.asn == 15169
            assert result.country_code is None

    @patch('cowrieprocessor.enrichment.maxmind_client.geoip2.database.Reader')
    def test_graceful_degradation_missing_asn_db(
        self, mock_reader_class, integration_db_path, mock_complete_city_response
    ):
        """Test that client works with only City database."""
        # Only create City database
        (integration_db_path / "GeoLite2-City.mmdb").touch()

        mock_city_reader = Mock()
        mock_city_reader.city.return_value = mock_complete_city_response
        mock_reader_class.return_value = mock_city_reader

        with MaxMindClient(db_path=integration_db_path) as client:
            result = client.lookup_ip("8.8.8.8")

            # Should get city data even without ASN database
            assert result is not None
            assert result.country_code == "US"
            assert result.asn is None

    @patch('cowrieprocessor.enrichment.maxmind_client.geoip2.database.Reader')
    def test_reader_error_handling(self, mock_reader_class, integration_db_path):
        """Test handling of reader initialization errors."""
        (integration_db_path / "GeoLite2-City.mmdb").touch()

        # Mock reader that fails to initialize
        mock_reader_class.side_effect = Exception("Corrupted database")

        client = MaxMindClient(db_path=integration_db_path)
        result = client.lookup_ip("8.8.8.8")

        # Should handle error gracefully
        assert result is None
        assert client.stats['not_found'] == 1

    @patch('cowrieprocessor.enrichment.maxmind_client.geoip2.database.Reader')
    def test_lookup_error_recovery(self, mock_reader_class, integration_db_path, mock_complete_city_response):
        """Test that client recovers from lookup errors."""
        (integration_db_path / "GeoLite2-City.mmdb").touch()

        mock_city_reader = Mock()
        # First call fails, second succeeds
        mock_city_reader.city.side_effect = [
            Exception("Temporary error"),
            mock_complete_city_response,
        ]

        mock_reader_class.return_value = mock_city_reader

        with MaxMindClient(db_path=integration_db_path) as client:
            # First lookup fails (exception during city lookup)
            result1 = client.lookup_ip("8.8.8.8")
            # Result is None because no data was found (city errored, no ASN db)
            assert result1 is None
            assert client.stats['lookups'] == 1

            # Second lookup succeeds
            result2 = client.lookup_ip("8.8.8.8")
            assert result2 is not None
            assert result2.country_code == "US"


class TestMaxMindStatisticsTracking:
    """Test statistics tracking across integration scenarios."""

    @patch('cowrieprocessor.enrichment.maxmind_client.geoip2.database.Reader')
    def test_statistics_across_multiple_operations(
        self,
        mock_reader_class,
        integration_db_path,
        mock_complete_city_response,
        mock_complete_asn_response,
    ):
        """Test that statistics accurately track across operations."""
        import geoip2.errors

        (integration_db_path / "GeoLite2-City.mmdb").touch()
        (integration_db_path / "GeoLite2-ASN.mmdb").touch()

        mock_city_reader = Mock()
        mock_asn_reader = Mock()

        # Setup various scenarios
        mock_city_reader.city.side_effect = [
            mock_complete_city_response,  # Success
            geoip2.errors.AddressNotFoundError("IP not found"),  # Not found
            mock_complete_city_response,  # Success
        ]
        mock_asn_reader.asn.side_effect = [
            mock_complete_asn_response,  # Success
            mock_complete_asn_response,  # Success
            geoip2.errors.AddressNotFoundError("IP not found"),  # Not found
        ]

        mock_reader_class.side_effect = [mock_city_reader, mock_asn_reader]

        with MaxMindClient(db_path=integration_db_path) as client:
            # Lookup 1: Full success
            result1 = client.lookup_ip("8.8.8.8")
            assert result1 is not None

            # Lookup 2: ASN only
            result2 = client.lookup_ip("192.168.1.1")
            assert result2 is not None
            assert result2.country_code is None

            # Lookup 3: City only
            result3 = client.lookup_ip("10.0.0.1")
            assert result3 is not None
            assert result3.asn is None

            # Verify comprehensive statistics
            stats = client.get_stats()
            assert stats['lookups'] == 3
            assert stats['city_hits'] == 2
            assert stats['asn_hits'] == 2
            assert stats['errors'] == 0
            assert stats['not_found'] == 0  # Had partial data

    def test_statistics_reset(self, integration_db_path):
        """Test statistics reset functionality."""
        client = MaxMindClient(db_path=integration_db_path)

        # Generate some activity
        client.stats['lookups'] = 10
        client.stats['city_hits'] = 5
        client.stats['errors'] = 2

        # Reset
        client.reset_stats()

        # Verify all counters reset
        stats = client.get_stats()
        assert all(count == 0 for count in stats.values())


class TestMaxMindContextManagerIntegration:
    """Test context manager usage in integration scenarios."""

    @patch('cowrieprocessor.enrichment.maxmind_client.geoip2.database.Reader')
    def test_context_manager_full_workflow(
        self,
        mock_reader_class,
        integration_db_path,
        mock_complete_city_response,
    ):
        """Test full workflow using context manager."""
        (integration_db_path / "GeoLite2-City.mmdb").touch()

        mock_city_reader = Mock()
        mock_city_reader.city.return_value = mock_complete_city_response
        mock_reader_class.return_value = mock_city_reader

        # Use context manager for automatic cleanup
        with MaxMindClient(db_path=integration_db_path) as client:
            result = client.lookup_ip("8.8.8.8")
            assert result is not None

        # Verify readers were closed
        mock_city_reader.close.assert_called_once()

    @patch('cowrieprocessor.enrichment.maxmind_client.geoip2.database.Reader')
    def test_context_manager_exception_handling(self, mock_reader_class, integration_db_path):
        """Test that context manager closes readers even on exception."""
        (integration_db_path / "GeoLite2-City.mmdb").touch()

        mock_city_reader = Mock()
        mock_city_reader.city.side_effect = Exception("Test error")
        mock_reader_class.return_value = mock_city_reader

        with MaxMindClient(db_path=integration_db_path) as client:
            try:
                # This will fail but shouldn't prevent cleanup
                client.lookup_ip("8.8.8.8")
            except Exception:
                pass

        # Verify cleanup happened despite exception
        mock_city_reader.close.assert_called_once()
