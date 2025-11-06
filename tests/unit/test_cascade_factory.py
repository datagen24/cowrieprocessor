"""Unit tests for CascadeEnricher factory with secrets management integration.

Tests verify:
- Factory creates properly wired CascadeEnricher instances
- Secrets resolver integration works correctly
- Graceful degradation for missing API keys
- Mock client fallback for disabled services
- Proper cache manager initialization
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from cowrieprocessor.enrichment.cascade_enricher import CascadeEnricher
from cowrieprocessor.enrichment.cascade_factory import MockGreyNoiseClient, create_cascade_enricher
from cowrieprocessor.enrichment.greynoise_client import GreyNoiseClient


class TestMockGreyNoiseClient:
    """Test MockGreyNoiseClient fallback behavior."""

    def test_mock_client_returns_none(self) -> None:
        """Mock client should return None for all lookups."""
        client = MockGreyNoiseClient()
        result = client.lookup_ip("8.8.8.8")
        assert result is None

    def test_mock_client_tracks_stats(self) -> None:
        """Mock client should track lookup statistics."""
        client = MockGreyNoiseClient()
        client.lookup_ip("8.8.8.8")
        client.lookup_ip("1.1.1.1")

        stats = client.get_stats()
        assert stats['lookups'] == 2
        assert stats['api_failures'] == 2
        assert stats['api_success'] == 0

    def test_mock_client_reports_zero_quota(self) -> None:
        """Mock client should report zero quota available."""
        client = MockGreyNoiseClient()
        quota = client.get_remaining_quota()
        assert quota == 0

    def test_mock_client_reset_stats(self) -> None:
        """Mock client should reset statistics counters."""
        client = MockGreyNoiseClient()
        client.lookup_ip("8.8.8.8")
        assert client.get_stats()['lookups'] == 1

        client.reset_stats()
        assert client.get_stats()['lookups'] == 0


class TestCascadeFactory:
    """Test create_cascade_enricher factory function."""

    @pytest.fixture
    def mock_session(self) -> Session:
        """Create mock SQLAlchemy session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def temp_cache_dir(self, tmp_path: Path) -> Path:
        """Create temporary cache directory."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True)
        return cache_dir

    def test_factory_creates_cascade_enricher(self, temp_cache_dir: Path, mock_session: Session) -> None:
        """Factory should create properly initialized CascadeEnricher."""
        config: dict[str, str] = {}
        cascade = create_cascade_enricher(
            cache_dir=temp_cache_dir,
            db_session=mock_session,
            config=config,
            enable_greynoise=False,
        )

        assert isinstance(cascade, CascadeEnricher)
        assert cascade.session == mock_session
        assert cascade.maxmind is not None
        assert cascade.cymru is not None
        assert cascade.greynoise is not None

    def test_factory_initializes_cache_manager(self, temp_cache_dir: Path, mock_session: Session) -> None:
        """Factory should initialize EnrichmentCacheManager with proper TTLs."""
        config: dict[str, str] = {}
        cascade = create_cascade_enricher(
            cache_dir=temp_cache_dir,
            db_session=mock_session,
            config=config,
        )

        # Verify cache directories created
        assert (temp_cache_dir / "maxmind").exists()

        # Verify cache manager has correct TTLs (indirectly via client)
        assert cascade.cymru.ttl_days == 90

    def test_factory_resolves_greynoise_api_key_from_env(self, temp_cache_dir: Path, mock_session: Session) -> None:
        """Factory should resolve GreyNoise API key from environment variable."""
        os.environ['TEST_GREYNOISE_KEY'] = 'test_api_key_abc123'

        try:
            config = {'greynoise_api': 'env:TEST_GREYNOISE_KEY'}
            cascade = create_cascade_enricher(
                cache_dir=temp_cache_dir,
                db_session=mock_session,
                config=config,
                enable_greynoise=True,
            )

            # Should create real GreyNoiseClient when API key available
            assert isinstance(cascade.greynoise, GreyNoiseClient)
            assert cascade.greynoise.api_key == 'test_api_key_abc123'
        finally:
            del os.environ['TEST_GREYNOISE_KEY']

    def test_factory_uses_mock_client_when_greynoise_disabled(
        self, temp_cache_dir: Path, mock_session: Session
    ) -> None:
        """Factory should use MockGreyNoiseClient when GreyNoise disabled."""
        config: dict[str, str] = {}
        cascade = create_cascade_enricher(
            cache_dir=temp_cache_dir,
            db_session=mock_session,
            config=config,
            enable_greynoise=False,
        )

        assert isinstance(cascade.greynoise, MockGreyNoiseClient)

    def test_factory_uses_mock_client_when_api_key_missing(self, temp_cache_dir: Path, mock_session: Session) -> None:
        """Factory should use MockGreyNoiseClient when API key not configured."""
        config: dict[str, str] = {}  # No greynoise_api key
        cascade = create_cascade_enricher(
            cache_dir=temp_cache_dir,
            db_session=mock_session,
            config=config,
            enable_greynoise=True,
        )

        assert isinstance(cascade.greynoise, MockGreyNoiseClient)

    def test_factory_uses_mock_client_when_secret_resolution_fails(
        self, temp_cache_dir: Path, mock_session: Session
    ) -> None:
        """Factory should use MockGreyNoiseClient when secret resolution fails."""
        config = {'greynoise_api': 'env:NONEXISTENT_KEY'}
        cascade = create_cascade_enricher(
            cache_dir=temp_cache_dir,
            db_session=mock_session,
            config=config,
            enable_greynoise=True,
        )

        # Should gracefully fall back to mock client
        assert isinstance(cascade.greynoise, MockGreyNoiseClient)

    @patch('cowrieprocessor.enrichment.cascade_factory.resolve_secret')
    def test_factory_handles_secret_resolver_exception(
        self, mock_resolve: MagicMock, temp_cache_dir: Path, mock_session: Session
    ) -> None:
        """Factory should handle exceptions from secrets resolver gracefully."""
        mock_resolve.side_effect = RuntimeError("Secret vault unavailable")

        config = {'greynoise_api': 'vault://secrets/greynoise#api_key'}
        cascade = create_cascade_enricher(
            cache_dir=temp_cache_dir,
            db_session=mock_session,
            config=config,
            enable_greynoise=True,
        )

        # Should fall back to mock client on exception
        assert isinstance(cascade.greynoise, MockGreyNoiseClient)
        mock_resolve.assert_called_once()

    def test_factory_resolves_maxmind_license_key(self, temp_cache_dir: Path, mock_session: Session) -> None:
        """Factory should resolve MaxMind license key for automatic updates."""
        os.environ['TEST_MAXMIND_KEY'] = 'test_maxmind_license'

        try:
            config: dict[str, str] = {}
            cascade = create_cascade_enricher(
                cache_dir=temp_cache_dir,
                db_session=mock_session,
                config=config,
                maxmind_license_key='env:TEST_MAXMIND_KEY',
            )

            # Should pass resolved license key to MaxMind client
            assert cascade.maxmind.license_key == 'test_maxmind_license'
        finally:
            del os.environ['TEST_MAXMIND_KEY']

    def test_factory_handles_missing_maxmind_license_key(self, temp_cache_dir: Path, mock_session: Session) -> None:
        """Factory should handle missing MaxMind license key gracefully."""
        config: dict[str, str] = {}
        cascade = create_cascade_enricher(
            cache_dir=temp_cache_dir,
            db_session=mock_session,
            config=config,
            maxmind_license_key=None,
        )

        # Should create MaxMind client without license key (manual updates)
        assert cascade.maxmind.license_key is None

    def test_factory_validates_cache_dir_type(self, mock_session: Session) -> None:
        """Factory should validate cache_dir is Path object."""
        with pytest.raises(ValueError, match="cache_dir must be Path object"):
            create_cascade_enricher(
                cache_dir="/invalid/string/path",  # type: ignore[arg-type]
                db_session=mock_session,
                config={},
            )

    def test_factory_validates_cache_dir_not_file(self, tmp_path: Path, mock_session: Session) -> None:
        """Factory should validate cache_dir is not an existing file."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("not a directory")

        with pytest.raises(ValueError, match="cache_dir exists but is not a directory"):
            create_cascade_enricher(
                cache_dir=file_path,
                db_session=mock_session,
                config={},
            )

    def test_factory_creates_cache_dir_if_missing(self, tmp_path: Path, mock_session: Session) -> None:
        """Factory should create cache directory if it doesn't exist."""
        cache_dir = tmp_path / "nonexistent_cache"
        assert not cache_dir.exists()

        cascade = create_cascade_enricher(
            cache_dir=cache_dir,
            db_session=mock_session,
            config={},
        )

        assert cache_dir.exists()
        assert cache_dir.is_dir()
        assert isinstance(cascade, CascadeEnricher)

    def test_factory_rate_limiters_configured_correctly(self, temp_cache_dir: Path, mock_session: Session) -> None:
        """Factory should configure rate limiters per ADR-008 specification."""
        os.environ['TEST_GREYNOISE_KEY'] = 'test_key'

        try:
            config = {'greynoise_api': 'env:TEST_GREYNOISE_KEY'}
            cascade = create_cascade_enricher(
                cache_dir=temp_cache_dir,
                db_session=mock_session,
                config=config,
                enable_greynoise=True,
            )

            # Cymru: 100 requests/second
            assert cascade.cymru.rate_limiter.rate == 100.0

            # GreyNoise: 10 requests/second
            if isinstance(cascade.greynoise, GreyNoiseClient):
                assert cascade.greynoise.rate_limiter.rate == 10.0
        finally:
            del os.environ['TEST_GREYNOISE_KEY']

    def test_factory_supports_multiple_secret_resolver_schemes(
        self, temp_cache_dir: Path, mock_session: Session
    ) -> None:
        """Factory should support all secrets resolver URI schemes."""
        # Test file:// scheme
        secret_file = temp_cache_dir / "greynoise_secret.txt"
        secret_file.write_text("file_based_api_key")

        config = {'greynoise_api': f'file:{secret_file}'}
        cascade = create_cascade_enricher(
            cache_dir=temp_cache_dir,
            db_session=mock_session,
            config=config,
            enable_greynoise=True,
        )

        # Should successfully resolve file-based secret
        assert isinstance(cascade.greynoise, GreyNoiseClient)
        assert cascade.greynoise.api_key == 'file_based_api_key'

    def test_factory_security_warning_for_plaintext_keys(self, temp_cache_dir: Path, mock_session: Session) -> None:
        """Factory should document security warning for plaintext keys in docstring."""
        # Verify docstring contains security warning
        docstring = create_cascade_enricher.__doc__ or ""
        assert "Security:" in docstring
        assert "MUST be provided via secrets resolver URIs" in docstring
        assert "Plaintext keys" in docstring  # Matches actual docstring text
        assert "security violation" in docstring
