"""MaxMind GeoLite2 offline database client for geo/ASN enrichment."""

from __future__ import annotations

import logging
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import geoip2.database
import geoip2.errors
import requests

logger = logging.getLogger(__name__)


@dataclass
class MaxMindResult:
    """Result from MaxMind GeoLite2 database lookup.

    Attributes:
        ip_address: The IP address that was looked up
        country_code: ISO 3166-1 alpha-2 country code (e.g., "US")
        country_name: Full country name (e.g., "United States")
        city: City name if available
        latitude: Latitude coordinate
        longitude: Longitude coordinate
        asn: Autonomous System Number
        asn_org: AS organization name
        accuracy_radius: Accuracy radius in kilometers
        source: Data source identifier (always "maxmind")
        cached_at: Timestamp when result was retrieved from database
    """

    ip_address: str
    country_code: str | None
    country_name: str | None
    city: str | None
    latitude: float | None
    longitude: float | None
    asn: int | None
    asn_org: str | None
    accuracy_radius: int | None
    source: str = "maxmind"
    cached_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MaxMindClient:
    """Offline GeoLite2 database client with automatic updates.

    Provides geo-location and ASN enrichment using MaxMind GeoLite2 databases.
    Supports automatic weekly updates if license key is provided.

    Database files:
        - GeoLite2-City.mmdb: City, country, coordinates
        - GeoLite2-ASN.mmdb: ASN numbers and organizations

    Usage:
        client = MaxMindClient(
            db_path=Path("/mnt/dshield/data/cache/maxmind"),
            license_key="your_license_key"
        )
        result = client.lookup_ip("8.8.8.8")
        if result:
            print(f"Country: {result.country_name}")
            print(f"ASN: {result.asn} ({result.asn_org})")
    """

    # MaxMind GeoLite2 download URLs
    CITY_DB_URL_TEMPLATE = (
        "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&license_key={key}&suffix=tar.gz"
    )
    ASN_DB_URL_TEMPLATE = (
        "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-ASN&license_key={key}&suffix=tar.gz"
    )

    # Database update interval (7 days)
    UPDATE_INTERVAL = timedelta(days=7)

    def __init__(self, db_path: Path, license_key: str | None = None) -> None:
        """Initialize MaxMind client with database path and optional license key.

        Args:
            db_path: Directory containing MaxMind database files
            license_key: MaxMind license key for automatic updates (optional)

        Raises:
            ValueError: If db_path is not a directory
        """
        if not db_path.exists():
            db_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created MaxMind database directory: {db_path}")

        if not db_path.is_dir():
            raise ValueError(f"Database path must be a directory: {db_path}")

        self.db_path = db_path
        self.license_key = license_key

        # Paths to database files
        self.city_db_path = db_path / "GeoLite2-City.mmdb"
        self.asn_db_path = db_path / "GeoLite2-ASN.mmdb"

        # Initialize readers (lazy-loaded)
        self._city_reader: Optional[geoip2.database.Reader] = None
        self._asn_reader: Optional[geoip2.database.Reader] = None

        # Statistics
        self.stats: Dict[str, int] = {
            'lookups': 0,
            'city_hits': 0,
            'asn_hits': 0,
            'errors': 0,
            'not_found': 0,
        }

        logger.info(f"MaxMind client initialized with database path: {db_path}")

    def _get_city_reader(self) -> Optional[geoip2.database.Reader]:
        """Get or create the City database reader.

        Returns:
            City database reader or None if database unavailable
        """
        if self._city_reader is None:
            if not self.city_db_path.exists():
                logger.warning(f"City database not found: {self.city_db_path}")
                return None

            try:
                self._city_reader = geoip2.database.Reader(str(self.city_db_path))
                logger.debug("City database reader opened successfully")
            except Exception as e:
                logger.error(f"Failed to open City database: {e}")
                return None

        return self._city_reader

    def _get_asn_reader(self) -> Optional[geoip2.database.Reader]:
        """Get or create the ASN database reader.

        Returns:
            ASN database reader or None if database unavailable
        """
        if self._asn_reader is None:
            if not self.asn_db_path.exists():
                logger.warning(f"ASN database not found: {self.asn_db_path}")
                return None

            try:
                self._asn_reader = geoip2.database.Reader(str(self.asn_db_path))
                logger.debug("ASN database reader opened successfully")
            except Exception as e:
                logger.error(f"Failed to open ASN database: {e}")
                return None

        return self._asn_reader

    def lookup_ip(self, ip_address: str) -> MaxMindResult | None:
        """Look up geo and ASN data for an IP address.

        Args:
            ip_address: IP address to look up (IPv4 or IPv6)

        Returns:
            MaxMindResult with available data or None if IP not found

        Examples:
            >>> client = MaxMindClient(Path("/var/cache/maxmind"))
            >>> result = client.lookup_ip("8.8.8.8")
            >>> if result:
            ...     print(f"{result.city}, {result.country_name}")
            ...     print(f"ASN: {result.asn}")
        """
        self.stats['lookups'] += 1

        try:
            # Initialize result with IP address
            result_data: Dict[str, Any] = {
                'ip_address': ip_address,
                'country_code': None,
                'country_name': None,
                'city': None,
                'latitude': None,
                'longitude': None,
                'asn': None,
                'asn_org': None,
                'accuracy_radius': None,
            }

            # Look up city/geo data
            city_reader = self._get_city_reader()
            if city_reader:
                try:
                    city_response = city_reader.city(ip_address)
                    self.stats['city_hits'] += 1

                    # Extract geo data
                    if city_response.country.iso_code:
                        result_data['country_code'] = city_response.country.iso_code
                    if city_response.country.name:
                        result_data['country_name'] = city_response.country.name
                    if city_response.city.name:
                        result_data['city'] = city_response.city.name
                    if city_response.location.latitude is not None:
                        result_data['latitude'] = city_response.location.latitude
                    if city_response.location.longitude is not None:
                        result_data['longitude'] = city_response.location.longitude
                    if city_response.location.accuracy_radius is not None:
                        result_data['accuracy_radius'] = city_response.location.accuracy_radius

                except geoip2.errors.AddressNotFoundError:
                    logger.debug(f"IP {ip_address} not found in City database")
                except Exception as e:
                    logger.error(f"City lookup failed for {ip_address}: {e}")

            # Look up ASN data
            asn_reader = self._get_asn_reader()
            if asn_reader:
                try:
                    asn_response = asn_reader.asn(ip_address)
                    self.stats['asn_hits'] += 1

                    if asn_response.autonomous_system_number:
                        result_data['asn'] = asn_response.autonomous_system_number
                    if asn_response.autonomous_system_organization:
                        result_data['asn_org'] = asn_response.autonomous_system_organization

                except geoip2.errors.AddressNotFoundError:
                    logger.debug(f"IP {ip_address} not found in ASN database")
                except Exception as e:
                    logger.error(f"ASN lookup failed for {ip_address}: {e}")

            # Return result if we got any data
            if any(result_data[k] is not None for k in result_data if k != 'ip_address'):
                return MaxMindResult(**result_data)

            # No data found for this IP
            self.stats['not_found'] += 1
            return None

        except Exception as e:
            logger.error(f"MaxMind lookup failed for {ip_address}: {e}")
            self.stats['errors'] += 1
            return None

    def update_database(self) -> bool:
        """Download and install latest GeoLite2 databases.

        Requires license_key to be set. Downloads both City and ASN databases
        from MaxMind and extracts them to the database directory.

        Returns:
            True if update succeeded, False otherwise

        Raises:
            ValueError: If license key not configured
        """
        if not self.license_key:
            raise ValueError("Cannot update database without license key")

        logger.info("Starting MaxMind database update...")

        try:
            # Update City database
            city_success = self._download_and_extract_database(
                url=self.CITY_DB_URL_TEMPLATE.format(key=self.license_key),
                db_filename="GeoLite2-City.mmdb",
            )

            # Update ASN database
            asn_success = self._download_and_extract_database(
                url=self.ASN_DB_URL_TEMPLATE.format(key=self.license_key),
                db_filename="GeoLite2-ASN.mmdb",
            )

            success = city_success and asn_success

            if success:
                # Reload readers with new databases
                self._close_readers()
                logger.info("MaxMind database update completed successfully")
            else:
                logger.warning("MaxMind database update partially failed")

            return success

        except Exception as e:
            logger.error(f"MaxMind database update failed: {e}")
            return False

    def _download_and_extract_database(self, url: str, db_filename: str) -> bool:
        """Download and extract a MaxMind database archive.

        Args:
            url: Download URL
            db_filename: Name of the .mmdb file to extract

        Returns:
            True if download and extraction succeeded
        """
        try:
            logger.info(f"Downloading {db_filename}...")

            # Download tar.gz archive
            response = requests.get(url, timeout=300)
            response.raise_for_status()

            # Save to temporary file
            temp_archive = self.db_path / f"{db_filename}.tar.gz"
            temp_archive.write_bytes(response.content)

            # Extract .mmdb file from archive
            logger.info(f"Extracting {db_filename}...")
            with tarfile.open(temp_archive, 'r:gz') as tar:
                # Find the .mmdb file in the archive
                mmdb_member = None
                for member in tar.getmembers():
                    if member.name.endswith(db_filename):
                        mmdb_member = member
                        break

                if not mmdb_member:
                    logger.error(f"Could not find {db_filename} in archive")
                    return False

                # Extract to database directory
                mmdb_member.name = db_filename  # Rename to simple filename
                tar.extract(mmdb_member, path=self.db_path)

            # Clean up temporary archive
            temp_archive.unlink()

            logger.info(f"Successfully updated {db_filename}")
            return True

        except Exception as e:
            logger.error(f"Failed to download/extract {db_filename}: {e}")
            return False

    def get_database_age(self) -> timedelta:
        """Get age of the oldest database file.

        Returns:
            Age of the oldest database as timedelta

        Raises:
            FileNotFoundError: If no database files exist
        """
        ages = []

        for db_path in [self.city_db_path, self.asn_db_path]:
            if db_path.exists():
                mtime = datetime.fromtimestamp(db_path.stat().st_mtime, tz=timezone.utc)
                age = datetime.now(timezone.utc) - mtime
                ages.append(age)

        if not ages:
            raise FileNotFoundError("No MaxMind database files found")

        # Return oldest age
        return max(ages)

    def should_update(self) -> bool:
        """Check if databases should be updated.

        Returns:
            True if databases are older than UPDATE_INTERVAL
        """
        try:
            age = self.get_database_age()
            return age > self.UPDATE_INTERVAL
        except FileNotFoundError:
            # No databases exist - should update
            return True

    def _close_readers(self) -> None:
        """Close database readers to allow file updates."""
        if self._city_reader:
            self._city_reader.close()
            self._city_reader = None

        if self._asn_reader:
            self._asn_reader.close()
            self._asn_reader = None

    def close(self) -> None:
        """Close all database readers and release resources."""
        self._close_readers()
        logger.debug("MaxMind client closed")

    def get_stats(self) -> Dict[str, int]:
        """Get client statistics.

        Returns:
            Dictionary with lookup statistics
        """
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Reset statistics counters."""
        for key in self.stats:
            self.stats[key] = 0

    def __enter__(self) -> MaxMindClient:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - close readers."""
        self.close()


__all__ = ['MaxMindClient', 'MaxMindResult']
