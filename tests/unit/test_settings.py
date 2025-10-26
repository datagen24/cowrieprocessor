"""Unit tests for settings module - comprehensive coverage of all settings classes."""

from __future__ import annotations
import pytest

from pathlib import Path

from cowrieprocessor.settings import (
    DatabaseSettings,
    EnrichmentSettings,
    _coerce_bool,
    _coerce_int,
    load_database_settings,
)


class TestCoercionHelpers:
    """Test the helper functions for type coercion."""

    def test_coerce_bool_true_values(self) -> None:
        """Test boolean coercion with truthy string values."""
        true_values = ["1", "true", "TRUE", "t", "T", "yes", "YES", "y", "Y", "on", "ON"]
        for value in true_values:
            assert _coerce_bool(value, False) is True, f"Expected {value} to coerce to True"

    def test_coerce_bool_false_values(self) -> None:
        """Test boolean coercion with falsy string values."""
        false_values = ["0", "false", "FALSE", "f", "F", "no", "NO", "n", "N", "off", "OFF"]
        for value in false_values:
            assert _coerce_bool(value, True) is False, f"Expected {value} to coerce to False"

    def test_coerce_bool_invalid_values_use_default(self) -> None:
        """Test boolean coercion with invalid values falls back to default."""
        invalid_values = ["invalid", "maybe", "2", "", "   "]
        for value in invalid_values:
            assert _coerce_bool(value, True) is True, f"Expected {value} to use default True"
            assert _coerce_bool(value, False) is False, f"Expected {value} to use default False"

    def test_coerce_bool_none_uses_default(self) -> None:
        """Test boolean coercion with None uses default value."""
        assert _coerce_bool(None, True) is True
        assert _coerce_bool(None, False) is False

    def test_coerce_int_valid_values(self) -> None:
        """Test integer coercion with valid string values."""
        assert _coerce_int("123", 0) == 123
        assert _coerce_int("0", 1) == 0
        assert _coerce_int("-456", 0) == -456
        assert _coerce_int("  789  ", 0) == 789

    def test_coerce_int_invalid_values_use_default(self) -> None:
        """Test integer coercion with invalid values falls back to default."""
        invalid_values = ["abc", "12.34", "", "   ", "not-a-number"]
        for value in invalid_values:
            assert _coerce_int(value, 42) == 42, f"Expected {value} to use default 42"

    def test_coerce_int_none_uses_default(self) -> None:
        """Test integer coercion with None uses default value."""
        assert _coerce_int(None, 99) == 99


class TestDatabaseSettings:
    """Test DatabaseSettings class functionality."""

    def test_database_settings_default_values(self) -> None:
        """Test DatabaseSettings with default values."""
        settings = DatabaseSettings(url="sqlite:///test.db")

        assert settings.url == "sqlite:///test.db"
        assert settings.echo is False
        assert settings.pool_size is None
        assert settings.pool_timeout == 30
        assert settings.sqlite_wal is True
        assert settings.sqlite_cache_size == -64000
        assert settings.sqlite_synchronous == "NORMAL"
        assert settings.sqlite_journal_fallback == "DELETE"

    def test_database_settings_custom_values(self) -> None:
        """Test DatabaseSettings with custom values."""
        settings = DatabaseSettings(
            url="postgresql://localhost/test",
            echo=True,
            pool_size=10,
            pool_timeout=60,
            sqlite_wal=False,
            sqlite_cache_size=-32000,
            sqlite_synchronous="FULL",
            sqlite_journal_fallback="WAL",
        )

        assert settings.url == "postgresql://localhost/test"
        assert settings.echo is True
        assert settings.pool_size == 10
        assert settings.pool_timeout == 60
        assert settings.sqlite_wal is False
        assert settings.sqlite_cache_size == -32000
        assert settings.sqlite_synchronous == "FULL"
        assert settings.sqlite_journal_fallback == "WAL"

    def test_database_settings_from_sources_defaults(self) -> None:
        """Test DatabaseSettings.from_sources with no overrides."""
        settings = DatabaseSettings.from_sources()

        assert settings.url.startswith("sqlite:///")
        assert settings.echo is False
        assert settings.pool_size is None
        assert settings.pool_timeout == 30
        assert settings.sqlite_wal is True
        assert settings.sqlite_cache_size == -64000

    def test_database_settings_from_sources_config_override(self) -> None:
        """Test DatabaseSettings.from_sources with config mapping override."""
        config = {
            "echo": True,
            "pool_size": 5,
            "sqlite_cache_size": -32000,
            "sqlite_synchronous": "FULL",
        }
        settings = DatabaseSettings.from_sources(config=config)

        assert settings.echo is True
        assert settings.pool_size == 5
        assert settings.sqlite_cache_size == -32000
        assert settings.sqlite_synchronous == "FULL"

    def test_database_settings_from_sources_config_none_values_ignored(self) -> None:
        """Test that None values in config are ignored (don't override defaults)."""
        config = {
            "echo": True,
            "pool_size": None,  # Should be ignored
            "sqlite_cache_size": -32000,
        }
        settings = DatabaseSettings.from_sources(config=config)

        assert settings.echo is True
        assert settings.pool_size is None  # Default value, not overridden
        assert settings.sqlite_cache_size == -32000

    def test_database_settings_from_sources_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test DatabaseSettings.from_sources with environment variable overrides."""
        monkeypatch.setenv("COWRIEPROC_DB_URL", "postgresql://localhost/env_test")
        monkeypatch.setenv("COWRIEPROC_DB_ECHO", "true")
        monkeypatch.setenv("COWRIEPROC_DB_POOL_SIZE", "15")
        monkeypatch.setenv("COWRIEPROC_DB_SQLITE_CACHE_SIZE", "-16000")

        settings = DatabaseSettings.from_sources()

        assert settings.url == "postgresql://localhost/env_test"
        assert settings.echo is True
        assert settings.pool_size == 15
        assert settings.sqlite_cache_size == -16000

    def test_database_settings_from_sources_env_path_override(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Test DatabaseSettings.from_sources with DB_PATH environment variable."""
        db_path = tmp_path / "custom.sqlite"
        monkeypatch.delenv("COWRIEPROC_DB_URL", raising=False)
        monkeypatch.setenv("COWRIEPROC_DB_PATH", str(db_path))

        settings = DatabaseSettings.from_sources()

        assert settings.url.endswith(str(db_path))
        assert settings.url.startswith("sqlite:///")

    def test_database_settings_from_sources_custom_env_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test DatabaseSettings.from_sources with custom environment prefix."""
        monkeypatch.setenv("CUSTOM_DB_URL", "postgresql://localhost/custom")
        monkeypatch.setenv("CUSTOM_DB_ECHO", "true")

        settings = DatabaseSettings.from_sources(env_prefix="CUSTOM_")

        assert settings.url == "postgresql://localhost/custom"
        assert settings.echo is True

    def test_database_settings_env_bool_coercion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test environment variable boolean coercion."""
        test_cases = [
            ("COWRIEPROC_DB_ECHO", "true", True),
            ("COWRIEPROC_DB_ECHO", "false", False),
            ("COWRIEPROC_DB_ECHO", "invalid", False),  # Default
            ("COWRIEPROC_DB_SQLITE_WAL", "1", True),
            ("COWRIEPROC_DB_SQLITE_WAL", "0", False),
            ("COWRIEPROC_DB_SQLITE_WAL", "yes", True),
            ("COWRIEPROC_DB_SQLITE_WAL", "no", False),
        ]

        for env_var, value, expected in test_cases:
            monkeypatch.setenv(env_var, value)
            settings = DatabaseSettings.from_sources()

            if env_var == "COWRIEPROC_DB_ECHO":
                assert settings.echo is expected
            elif env_var == "COWRIEPROC_DB_SQLITE_WAL":
                assert settings.sqlite_wal is expected

    def test_database_settings_env_int_coercion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test environment variable integer coercion."""
        test_cases = [
            ("COWRIEPROC_DB_POOL_SIZE", "10", 10),
            ("COWRIEPROC_DB_POOL_SIZE", "0", 0),
            ("COWRIEPROC_DB_POOL_SIZE", "invalid", None),  # Default
            ("COWRIEPROC_DB_POOL_TIMEOUT", "45", 45),
            ("COWRIEPROC_DB_POOL_TIMEOUT", "invalid", 30),  # Default
            ("COWRIEPROC_DB_SQLITE_CACHE_SIZE", "-32000", -32000),
            ("COWRIEPROC_DB_SQLITE_CACHE_SIZE", "invalid", -64000),  # Default
        ]

        for env_var, value, expected in test_cases:
            monkeypatch.setenv(env_var, value)
            settings = DatabaseSettings.from_sources()

            if env_var == "COWRIEPROC_DB_POOL_SIZE":
                assert settings.pool_size == expected
            elif env_var == "COWRIEPROC_DB_POOL_TIMEOUT":
                assert settings.pool_timeout == expected
            elif env_var == "COWRIEPROC_DB_SQLITE_CACHE_SIZE":
                assert settings.sqlite_cache_size == expected

    def test_database_settings_env_string_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test environment variable string overrides."""
        monkeypatch.setenv("COWRIEPROC_DB_SQLITE_SYNCHRONOUS", "full")
        monkeypatch.setenv("COWRIEPROC_DB_SQLITE_JOURNAL_FALLBACK", "wal")

        settings = DatabaseSettings.from_sources()

        assert settings.sqlite_synchronous == "FULL"  # Uppercased
        assert settings.sqlite_journal_fallback == "WAL"  # Uppercased

    def test_database_settings_precedence_config_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that config mapping takes precedence over environment variables."""
        config = {"echo": False, "pool_size": 5}
        monkeypatch.setenv("COWRIEPROC_DB_ECHO", "true")
        monkeypatch.setenv("COWRIEPROC_DB_POOL_SIZE", "10")

        settings = DatabaseSettings.from_sources(config=config)

        assert settings.echo is False  # Config wins
        assert settings.pool_size == 5  # Config wins

    def test_database_settings_precedence_env_over_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that environment variables take precedence over defaults."""
        monkeypatch.setenv("COWRIEPROC_DB_URL", "postgresql://localhost/env")
        monkeypatch.setenv("COWRIEPROC_DB_ECHO", "true")

        settings = DatabaseSettings.from_sources()

        assert settings.url == "postgresql://localhost/env"
        assert settings.echo is True


class TestEnrichmentSettings:
    """Test EnrichmentSettings class functionality."""

    def test_enrichment_settings_default_values(self) -> None:
        """Test EnrichmentSettings with default values."""
        settings = EnrichmentSettings()

        assert settings.cache_dir == Path.home() / ".cache" / "cowrieprocessor"
        assert isinstance(settings.cache_ttls, dict)
        assert isinstance(settings.rate_limits, dict)
        assert "virustotal" in settings.rate_limits
        assert settings.rate_limits["virustotal"] == 4

    def test_enrichment_settings_custom_values(self) -> None:
        """Test EnrichmentSettings with custom values."""
        cache_dir = Path("/custom/cache")
        cache_ttls = {"virustotal": 3600, "spur": 1800}
        rate_limits = {"virustotal": 2, "spur": 15}

        settings = EnrichmentSettings(
            cache_dir=cache_dir,
            cache_ttls=cache_ttls,
            rate_limits=rate_limits,
        )

        assert settings.cache_dir == cache_dir
        assert settings.cache_ttls == cache_ttls
        assert settings.rate_limits == rate_limits

    def test_enrichment_settings_rate_limits_defaults(self) -> None:
        """Test that default rate limits include expected services."""
        settings = EnrichmentSettings()

        expected_services = ["virustotal", "dshield", "urlhaus", "spur"]
        for service in expected_services:
            assert service in settings.rate_limits, f"Expected {service} in rate limits"

        assert settings.rate_limits["virustotal"] == 4
        assert settings.rate_limits["dshield"] == 100
        assert settings.rate_limits["urlhaus"] == 60
        assert settings.rate_limits["spur"] == 30


class TestLoadDatabaseSettings:
    """Test the load_database_settings convenience function."""

    def test_load_database_settings_no_args(self) -> None:
        """Test load_database_settings with no arguments."""
        settings = load_database_settings()

        assert isinstance(settings, DatabaseSettings)
        assert settings.url.startswith("sqlite:///")

    def test_load_database_settings_with_config(self) -> None:
        """Test load_database_settings with config mapping."""
        config = {"echo": True, "pool_size": 10}
        settings = load_database_settings(config=config)

        assert settings.echo is True
        assert settings.pool_size == 10

    def test_load_database_settings_with_env_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test load_database_settings with custom environment prefix."""
        monkeypatch.setenv("TEST_DB_URL", "postgresql://localhost/test")
        settings = load_database_settings(env_prefix="TEST_")

        assert settings.url == "postgresql://localhost/test"

    def test_load_database_settings_with_both_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test load_database_settings with both config and env_prefix."""
        config = {"echo": False}
        monkeypatch.setenv("TEST_DB_ECHO", "true")

        # Config should take precedence over env
        settings = load_database_settings(config=config, env_prefix="TEST_")

        assert settings.echo is False  # Config wins


class TestSettingsErrorHandling:
    """Test error handling and edge cases in settings."""

    def test_database_settings_invalid_url_format(self) -> None:
        """Test DatabaseSettings with invalid URL format."""
        # This should not raise an error - URL validation happens at engine creation
        settings = DatabaseSettings(url="invalid-url-format")
        assert settings.url == "invalid-url-format"

    def test_database_settings_negative_pool_size(self) -> None:
        """Test DatabaseSettings with negative pool size."""
        settings = DatabaseSettings(url="sqlite:///test.db", pool_size=-5)
        assert settings.pool_size == -5

    def test_database_settings_zero_pool_timeout(self) -> None:
        """Test DatabaseSettings with zero pool timeout."""
        settings = DatabaseSettings(url="sqlite:///test.db", pool_timeout=0)
        assert settings.pool_timeout == 0

    def test_database_settings_large_cache_size(self) -> None:
        """Test DatabaseSettings with large cache size."""
        settings = DatabaseSettings(url="sqlite:///test.db", sqlite_cache_size=1000000)
        assert settings.sqlite_cache_size == 1000000

    def test_enrichment_settings_empty_rate_limits(self) -> None:
        """Test EnrichmentSettings with empty rate limits."""
        settings = EnrichmentSettings(rate_limits={})
        assert settings.rate_limits == {}

    def test_enrichment_settings_empty_cache_ttls(self) -> None:
        """Test EnrichmentSettings with empty cache TTLs."""
        settings = EnrichmentSettings(cache_ttls={})
        assert settings.cache_ttls == {}


class TestSettingsIntegration:
    """Integration tests for settings with real environment scenarios."""

    def test_settings_with_typical_production_config(self) -> None:
        """Test settings with typical production configuration."""
        config = {
            "echo": False,
            "pool_size": 20,
            "pool_timeout": 60,
            "sqlite_wal": True,
            "sqlite_cache_size": -128000,
            "sqlite_synchronous": "NORMAL",
        }

        settings = DatabaseSettings.from_sources(config=config)

        assert settings.echo is False
        assert settings.pool_size == 20
        assert settings.pool_timeout == 60
        assert settings.sqlite_wal is True
        assert settings.sqlite_cache_size == -128000
        assert settings.sqlite_synchronous == "NORMAL"

    def test_settings_with_development_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test settings with typical development configuration."""
        monkeypatch.setenv("COWRIEPROC_DB_ECHO", "true")
        monkeypatch.setenv("COWRIEPROC_DB_SQLITE_WAL", "false")

        settings = DatabaseSettings.from_sources()

        assert settings.echo is True
        assert settings.sqlite_wal is False

    def test_settings_with_mixed_override_scenarios(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Test settings with mixed config and environment overrides."""
        db_path = tmp_path / "mixed.sqlite"
        config = {"echo": True, "pool_size": 5}

        monkeypatch.setenv("COWRIEPROC_DB_PATH", str(db_path))
        monkeypatch.setenv("COWRIEPROC_DB_ECHO", "false")  # Should be overridden by config
        monkeypatch.setenv("COWRIEPROC_DB_POOL_TIMEOUT", "45")

        settings = DatabaseSettings.from_sources(config=config)

        assert settings.url.endswith(str(db_path))
        assert settings.echo is True  # Config wins over env
        assert settings.pool_size == 5  # From config
        assert settings.pool_timeout == 45  # From env
