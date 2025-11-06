"""Unit tests for MaxMind GeoLite2 client."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import geoip2.errors
import pytest

from cowrieprocessor.enrichment.maxmind_client import MaxMindClient, MaxMindResult


@pytest.fixture
def temp_db_path(tmp_path):
    """Create temporary database directory."""
    db_path = tmp_path / "maxmind"
    db_path.mkdir()
    return db_path


@pytest.fixture
def mock_city_response():
    """Create mock City database response."""
    response = Mock()
    response.country.iso_code = "US"
    response.country.name = "United States"
    response.city.name = "Mountain View"
    response.location.latitude = 37.3860
    response.location.longitude = -122.0838
    response.location.accuracy_radius = 1000
    return response


@pytest.fixture
def mock_asn_response():
    """Create mock ASN database response."""
    response = Mock()
    response.autonomous_system_number = 15169
    response.autonomous_system_organization = "GOOGLE"
    return response


class TestMaxMindResult:
    """Test MaxMindResult dataclass."""

    def test_result_creation_with_full_data(self):
        """Test creating result with all fields."""
        now = datetime.now(timezone.utc)
        result = MaxMindResult(
            ip_address="8.8.8.8",
            country_code="US",
            country_name="United States",
            city="Mountain View",
            latitude=37.3860,
            longitude=-122.0838,
            asn=15169,
            asn_org="GOOGLE",
            accuracy_radius=1000,
            cached_at=now,
        )

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
        assert result.cached_at == now

    def test_result_creation_with_partial_data(self):
        """Test creating result with only some fields."""
        result = MaxMindResult(
            ip_address="8.8.8.8",
            country_code="US",
            country_name="United States",
            city=None,
            latitude=None,
            longitude=None,
            asn=15169,
            asn_org="GOOGLE",
            accuracy_radius=None,
        )

        assert result.ip_address == "8.8.8.8"
        assert result.country_code == "US"
        assert result.city is None
        assert result.asn == 15169

    def test_result_default_timestamp(self):
        """Test that cached_at defaults to current time."""
        before = datetime.now(timezone.utc)
        result = MaxMindResult(
            ip_address="8.8.8.8",
            country_code=None,
            country_name=None,
            city=None,
            latitude=None,
            longitude=None,
            asn=None,
            asn_org=None,
            accuracy_radius=None,
        )
        after = datetime.now(timezone.utc)

        assert before <= result.cached_at <= after
        assert result.source == "maxmind"


class TestMaxMindClientInit:
    """Test MaxMindClient initialization."""

    def test_init_creates_directory_if_missing(self, tmp_path):
        """Test that __init__ creates database directory."""
        db_path = tmp_path / "maxmind" / "nested"
        assert not db_path.exists()

        client = MaxMindClient(db_path=db_path)

        assert db_path.exists()
        assert db_path.is_dir()
        assert client.db_path == db_path

    def test_init_with_existing_directory(self, temp_db_path):
        """Test initialization with existing directory."""
        client = MaxMindClient(db_path=temp_db_path)

        assert client.db_path == temp_db_path
        assert client.city_db_path == temp_db_path / "GeoLite2-City.mmdb"
        assert client.asn_db_path == temp_db_path / "GeoLite2-ASN.mmdb"

    def test_init_with_license_key(self, temp_db_path):
        """Test initialization with license key."""
        client = MaxMindClient(db_path=temp_db_path, license_key="test_key_123")

        assert client.license_key == "test_key_123"

    def test_init_with_file_path_raises_error(self, tmp_path):
        """Test that initializing with file path raises ValueError."""
        file_path = tmp_path / "test.txt"
        file_path.write_text("test")

        with pytest.raises(ValueError, match="must be a directory"):
            MaxMindClient(db_path=file_path)

    def test_init_statistics(self, temp_db_path):
        """Test that statistics are initialized."""
        client = MaxMindClient(db_path=temp_db_path)

        assert client.stats == {
            'lookups': 0,
            'city_hits': 0,
            'asn_hits': 0,
            'errors': 0,
            'not_found': 0,
        }


class TestMaxMindClientLookup:
    """Test MaxMindClient IP lookup functionality."""

    @patch('cowrieprocessor.enrichment.maxmind_client.geoip2.database.Reader')
    def test_lookup_ip_success_with_full_data(
        self, mock_reader_class, temp_db_path, mock_city_response, mock_asn_response
    ):
        """Test successful lookup with complete geo and ASN data."""
        # Create database files so readers initialize
        (temp_db_path / "GeoLite2-City.mmdb").touch()
        (temp_db_path / "GeoLite2-ASN.mmdb").touch()

        # Setup mock readers
        mock_city_reader = Mock()
        mock_city_reader.city.return_value = mock_city_response
        mock_asn_reader = Mock()
        mock_asn_reader.asn.return_value = mock_asn_response

        mock_reader_class.side_effect = [mock_city_reader, mock_asn_reader]

        client = MaxMindClient(db_path=temp_db_path)
        result = client.lookup_ip("8.8.8.8")

        assert result is not None
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

        assert client.stats['lookups'] == 1
        assert client.stats['city_hits'] == 1
        assert client.stats['asn_hits'] == 1

    @patch('cowrieprocessor.enrichment.maxmind_client.geoip2.database.Reader')
    def test_lookup_ip_city_only(self, mock_reader_class, temp_db_path, mock_city_response):
        """Test lookup with only City database available."""
        (temp_db_path / "GeoLite2-City.mmdb").touch()

        mock_city_reader = Mock()
        mock_city_reader.city.return_value = mock_city_response

        mock_reader_class.return_value = mock_city_reader

        client = MaxMindClient(db_path=temp_db_path)
        result = client.lookup_ip("8.8.8.8")

        assert result is not None
        assert result.country_code == "US"
        assert result.asn is None
        assert result.asn_org is None

    @patch('cowrieprocessor.enrichment.maxmind_client.geoip2.database.Reader')
    def test_lookup_ip_asn_only(self, mock_reader_class, temp_db_path, mock_asn_response):
        """Test lookup with only ASN database available."""
        (temp_db_path / "GeoLite2-ASN.mmdb").touch()

        mock_asn_reader = Mock()
        mock_asn_reader.asn.return_value = mock_asn_response

        mock_reader_class.return_value = mock_asn_reader

        client = MaxMindClient(db_path=temp_db_path)
        result = client.lookup_ip("8.8.8.8")

        assert result is not None
        assert result.asn == 15169
        assert result.country_code is None
        assert result.city is None

    @patch('cowrieprocessor.enrichment.maxmind_client.geoip2.database.Reader')
    def test_lookup_ip_not_found(self, mock_reader_class, temp_db_path):
        """Test lookup when IP not found in databases."""
        (temp_db_path / "GeoLite2-City.mmdb").touch()
        (temp_db_path / "GeoLite2-ASN.mmdb").touch()

        mock_city_reader = Mock()
        mock_city_reader.city.side_effect = geoip2.errors.AddressNotFoundError("IP not found")
        mock_asn_reader = Mock()
        mock_asn_reader.asn.side_effect = geoip2.errors.AddressNotFoundError("IP not found")

        mock_reader_class.side_effect = [mock_city_reader, mock_asn_reader]

        client = MaxMindClient(db_path=temp_db_path)
        result = client.lookup_ip("192.168.1.1")

        assert result is None
        assert client.stats['lookups'] == 1
        assert client.stats['not_found'] == 1

    def test_lookup_ip_no_databases(self, temp_db_path):
        """Test lookup when no databases exist."""
        client = MaxMindClient(db_path=temp_db_path)
        result = client.lookup_ip("8.8.8.8")

        assert result is None
        assert client.stats['not_found'] == 1

    @patch('cowrieprocessor.enrichment.maxmind_client.geoip2.database.Reader')
    def test_lookup_ip_partial_city_data(self, mock_reader_class, temp_db_path):
        """Test lookup with incomplete city data."""
        (temp_db_path / "GeoLite2-City.mmdb").touch()

        # Mock response with partial data
        mock_response = Mock()
        mock_response.country.iso_code = "US"
        mock_response.country.name = None  # Missing name
        mock_response.city.name = None  # Missing city
        mock_response.location.latitude = None  # Missing coordinates
        mock_response.location.longitude = None
        mock_response.location.accuracy_radius = None

        mock_city_reader = Mock()
        mock_city_reader.city.return_value = mock_response

        mock_reader_class.return_value = mock_city_reader

        client = MaxMindClient(db_path=temp_db_path)
        result = client.lookup_ip("8.8.8.8")

        assert result is not None
        assert result.country_code == "US"
        assert result.country_name is None
        assert result.city is None


class TestMaxMindClientDatabaseUpdate:
    """Test database update functionality."""

    def test_update_database_without_license_key(self, temp_db_path):
        """Test that update_database raises error without license key."""
        client = MaxMindClient(db_path=temp_db_path)

        with pytest.raises(ValueError, match="Cannot update database without license key"):
            client.update_database()

    @patch('cowrieprocessor.enrichment.maxmind_client.requests.get')
    @patch('cowrieprocessor.enrichment.maxmind_client.tarfile.open')
    def test_update_database_success(self, mock_tarfile, mock_requests, temp_db_path):
        """Test successful database update."""
        # Mock HTTP response
        mock_response = Mock()
        mock_response.content = b"fake tar.gz content"
        mock_response.raise_for_status = Mock()
        mock_requests.return_value = mock_response

        # Mock tar extraction
        mock_tar = Mock()
        mock_member = Mock()
        mock_member.name = "GeoLite2-City_20250101/GeoLite2-City.mmdb"
        mock_tar.getmembers.return_value = [mock_member]
        mock_tarfile.return_value.__enter__.return_value = mock_tar

        client = MaxMindClient(db_path=temp_db_path, license_key="test_key")

        # Mock _download_and_extract_database to avoid actual download
        with patch.object(client, '_download_and_extract_database', return_value=True):
            result = client.update_database()

        assert result is True

    @patch('cowrieprocessor.enrichment.maxmind_client.requests.get')
    def test_download_and_extract_network_error(self, mock_requests, temp_db_path):
        """Test update failure due to network error."""
        mock_requests.side_effect = Exception("Network error")

        client = MaxMindClient(db_path=temp_db_path, license_key="test_key")
        result = client._download_and_extract_database(
            url="http://example.com/test.tar.gz",
            db_filename="GeoLite2-City.mmdb",
        )

        assert result is False

    @patch('cowrieprocessor.enrichment.maxmind_client.requests.get')
    @patch('cowrieprocessor.enrichment.maxmind_client.tarfile.open')
    def test_download_and_extract_missing_mmdb(self, mock_tarfile, mock_requests, temp_db_path):
        """Test update failure when .mmdb not found in archive."""
        # Mock HTTP response
        mock_response = Mock()
        mock_response.content = b"fake tar.gz content"
        mock_response.raise_for_status = Mock()
        mock_requests.return_value = mock_response

        # Mock tar with no .mmdb file
        mock_tar = Mock()
        mock_member = Mock()
        mock_member.name = "some_other_file.txt"
        mock_tar.getmembers.return_value = [mock_member]
        mock_tarfile.return_value.__enter__.return_value = mock_tar

        client = MaxMindClient(db_path=temp_db_path, license_key="test_key")
        result = client._download_and_extract_database(
            url="http://example.com/test.tar.gz",
            db_filename="GeoLite2-City.mmdb",
        )

        assert result is False

    @patch('cowrieprocessor.enrichment.maxmind_client.requests.get')
    @patch('cowrieprocessor.enrichment.maxmind_client.tarfile.open')
    def test_download_and_extract_success(self, mock_tarfile, mock_requests, temp_db_path):
        """Test successful download and extraction."""
        # Mock HTTP response
        mock_response = Mock()
        mock_response.content = b"fake tar.gz content"
        mock_response.raise_for_status = Mock()
        mock_requests.return_value = mock_response

        # Mock tar extraction
        mock_tar = Mock()
        mock_member = Mock()
        mock_member.name = "GeoLite2-City_20250101/GeoLite2-City.mmdb"
        mock_tar.getmembers.return_value = [mock_member]
        mock_tar.extract = Mock()
        mock_tarfile.return_value.__enter__.return_value = mock_tar

        client = MaxMindClient(db_path=temp_db_path, license_key="test_key")
        result = client._download_and_extract_database(
            url="http://example.com/test.tar.gz",
            db_filename="GeoLite2-City.mmdb",
        )

        assert result is True
        mock_tar.extract.assert_called_once()

    def test_update_database_partial_failure(self, temp_db_path):
        """Test update when one database succeeds and one fails."""
        client = MaxMindClient(db_path=temp_db_path, license_key="test_key")

        # Mock one success, one failure
        with patch.object(client, '_download_and_extract_database', side_effect=[True, False]):
            result = client.update_database()

        # Overall update fails if any database fails
        assert result is False


class TestMaxMindClientDatabaseAge:
    """Test database age tracking."""

    def test_get_database_age_no_files(self, temp_db_path):
        """Test get_database_age when no databases exist."""
        client = MaxMindClient(db_path=temp_db_path)

        with pytest.raises(FileNotFoundError, match="No MaxMind database files found"):
            client.get_database_age()

    def test_get_database_age_with_files(self, temp_db_path):
        """Test get_database_age with existing databases."""
        # Create database files
        city_db = temp_db_path / "GeoLite2-City.mmdb"
        asn_db = temp_db_path / "GeoLite2-ASN.mmdb"
        city_db.touch()
        asn_db.touch()

        client = MaxMindClient(db_path=temp_db_path)
        age = client.get_database_age()

        assert isinstance(age, timedelta)
        assert age.total_seconds() >= 0
        assert age.total_seconds() < 60  # Should be very recent

    def test_should_update_no_databases(self, temp_db_path):
        """Test should_update returns True when no databases exist."""
        client = MaxMindClient(db_path=temp_db_path)

        assert client.should_update() is True

    def test_should_update_old_databases(self, temp_db_path):
        """Test should_update returns True for old databases."""
        # Create old database file
        city_db = temp_db_path / "GeoLite2-City.mmdb"
        city_db.touch()

        # Mock get_database_age to return old age
        client = MaxMindClient(db_path=temp_db_path)
        with patch.object(client, 'get_database_age', return_value=timedelta(days=8)):
            assert client.should_update() is True

    def test_should_update_recent_databases(self, temp_db_path):
        """Test should_update returns False for recent databases."""
        city_db = temp_db_path / "GeoLite2-City.mmdb"
        city_db.touch()

        client = MaxMindClient(db_path=temp_db_path)
        with patch.object(client, 'get_database_age', return_value=timedelta(days=3)):
            assert client.should_update() is False


class TestMaxMindClientStatistics:
    """Test statistics tracking."""

    def test_get_stats(self, temp_db_path):
        """Test get_stats returns copy of statistics."""
        client = MaxMindClient(db_path=temp_db_path)
        client.stats['lookups'] = 5

        stats = client.get_stats()

        assert stats == {
            'lookups': 5,
            'city_hits': 0,
            'asn_hits': 0,
            'errors': 0,
            'not_found': 0,
        }

        # Verify it's a copy
        stats['lookups'] = 10
        assert client.stats['lookups'] == 5

    def test_reset_stats(self, temp_db_path):
        """Test reset_stats clears all counters."""
        client = MaxMindClient(db_path=temp_db_path)
        client.stats['lookups'] = 10
        client.stats['city_hits'] = 5
        client.stats['errors'] = 2

        client.reset_stats()

        assert client.stats == {
            'lookups': 0,
            'city_hits': 0,
            'asn_hits': 0,
            'errors': 0,
            'not_found': 0,
        }


class TestMaxMindClientReaderErrors:
    """Test reader initialization error handling."""

    @patch('cowrieprocessor.enrichment.maxmind_client.geoip2.database.Reader')
    def test_city_reader_initialization_error(self, mock_reader_class, temp_db_path):
        """Test handling of City database reader initialization error."""
        (temp_db_path / "GeoLite2-City.mmdb").touch()

        # Mock reader initialization failure
        mock_reader_class.side_effect = Exception("Database corrupted")

        client = MaxMindClient(db_path=temp_db_path)

        # First call should catch error and return None
        reader = client._get_city_reader()
        assert reader is None

        # Should still work if called again
        reader = client._get_city_reader()
        assert reader is None

    @patch('cowrieprocessor.enrichment.maxmind_client.geoip2.database.Reader')
    def test_asn_reader_initialization_error(self, mock_reader_class, temp_db_path):
        """Test handling of ASN database reader initialization error."""
        (temp_db_path / "GeoLite2-ASN.mmdb").touch()

        # Mock reader initialization failure
        mock_reader_class.side_effect = Exception("Database corrupted")

        client = MaxMindClient(db_path=temp_db_path)

        # First call should catch error and return None
        reader = client._get_asn_reader()
        assert reader is None


class TestMaxMindClientContextManager:
    """Test context manager functionality."""

    def test_context_manager_closes_readers(self, temp_db_path):
        """Test that context manager closes readers on exit."""
        (temp_db_path / "GeoLite2-City.mmdb").touch()

        with patch('cowrieprocessor.enrichment.maxmind_client.geoip2.database.Reader') as mock_reader_class:
            mock_reader = Mock()
            mock_reader_class.return_value = mock_reader

            with MaxMindClient(db_path=temp_db_path) as client:
                # Force reader initialization
                client._get_city_reader()

            # Verify close was called
            mock_reader.close.assert_called_once()

    def test_close_method(self, temp_db_path):
        """Test explicit close method."""
        (temp_db_path / "GeoLite2-City.mmdb").touch()
        (temp_db_path / "GeoLite2-ASN.mmdb").touch()

        with patch('cowrieprocessor.enrichment.maxmind_client.geoip2.database.Reader') as mock_reader_class:
            mock_city_reader = Mock()
            mock_asn_reader = Mock()
            mock_reader_class.side_effect = [mock_city_reader, mock_asn_reader]

            client = MaxMindClient(db_path=temp_db_path)
            client._get_city_reader()
            client._get_asn_reader()

            client.close()

            mock_city_reader.close.assert_called_once()
            mock_asn_reader.close.assert_called_once()
            assert client._city_reader is None
            assert client._asn_reader is None
