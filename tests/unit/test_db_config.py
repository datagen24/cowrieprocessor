"""Unit tests for database configuration resolution (db_config.py)."""

from __future__ import annotations

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Generator
from unittest.mock import Mock, patch

import pytest

from cowrieprocessor.cli.db_config import (
    _load_sensors_config,
    add_database_argument,
    resolve_database_settings,
)


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create temporary directory for test files.

    Yields:
        Path to temporary directory
    """
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestLoadSensorsConfig:
    """Test _load_sensors_config helper function."""

    def test_load_sensors_config_not_found(self) -> None:
        """Test loading when sensors.toml does not exist.

        Given: No sensors.toml file exists
        When: _load_sensors_config is called
        Then: Returns None
        """
        with patch("cowrieprocessor.cli.db_config.Path") as mock_path:
            mock_path.return_value.exists.return_value = False

            result = _load_sensors_config()

            assert result is None

    def test_load_sensors_config_from_config_dir(self, temp_dir: Path) -> None:
        """Test loading from config/sensors.toml.

        Given: Valid sensors.toml in config/ directory
        When: _load_sensors_config is called
        Then: Returns database configuration
        """
        # Create config directory and sensors.toml
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        sensors_file = config_dir / "sensors.toml"
        sensors_file.write_text('[global]\ndb = "postgresql://localhost/test"\n')

        with patch("cowrieprocessor.cli.db_config.Path") as mock_path_class:
            # Mock the Path class to return our temp paths
            def path_factory(path_str: str) -> Mock:
                mock_p = Mock(spec=Path)
                if "config/sensors.toml" in path_str:
                    mock_p.exists.return_value = True
                    mock_p.open = sensors_file.open
                    return mock_p
                mock_p.exists.return_value = False
                return mock_p

            mock_path_class.side_effect = path_factory

            result = _load_sensors_config()

            assert result is not None
            assert result["url"] == "postgresql://localhost/test"

    def test_load_sensors_config_from_current_dir(self, temp_dir: Path) -> None:
        """Test loading from sensors.toml in current directory.

        Given: Valid sensors.toml in current directory (config/ doesn't exist)
        When: _load_sensors_config is called
        Then: Returns database configuration
        """
        sensors_file = temp_dir / "sensors.toml"
        sensors_file.write_text('[global]\ndb = "sqlite:///data/cowrie.db"\n')

        with patch("cowrieprocessor.cli.db_config.Path") as mock_path_class:
            # Mock the Path class
            def path_factory(path_str: str) -> Mock:
                mock_p = Mock(spec=Path)
                if "config/sensors.toml" in path_str:
                    mock_p.exists.return_value = False  # config dir doesn't exist
                elif path_str == "sensors.toml":
                    mock_p.exists.return_value = True
                    mock_p.open = sensors_file.open
                else:
                    mock_p.exists.return_value = False
                return mock_p

            mock_path_class.side_effect = path_factory

            result = _load_sensors_config()

            assert result is not None
            assert result["url"] == "sqlite:///data/cowrie.db"

    def test_load_sensors_config_no_global_section(self, temp_dir: Path) -> None:
        """Test loading sensors.toml without [global] section.

        Given: sensors.toml exists but has no [global] section
        When: _load_sensors_config is called
        Then: Returns None
        """
        sensors_file = temp_dir / "sensors.toml"
        sensors_file.write_text('[some_other_section]\nvalue = "test"\n')

        with patch("cowrieprocessor.cli.db_config.Path") as mock_path_class:

            def path_factory(path_str: str) -> Mock:
                mock_p = Mock(spec=Path)
                if path_str == "sensors.toml":
                    mock_p.exists.return_value = True
                    mock_p.open = sensors_file.open
                else:
                    mock_p.exists.return_value = False
                return mock_p

            mock_path_class.side_effect = path_factory

            result = _load_sensors_config()

            assert result is None

    def test_load_sensors_config_no_db_key(self, temp_dir: Path) -> None:
        """Test loading sensors.toml with [global] but no 'db' key.

        Given: sensors.toml has [global] section but no 'db' key
        When: _load_sensors_config is called
        Then: Returns None
        """
        sensors_file = temp_dir / "sensors.toml"
        sensors_file.write_text('[global]\nother_key = "value"\n')

        with patch("cowrieprocessor.cli.db_config.Path") as mock_path_class:

            def path_factory(path_str: str) -> Mock:
                mock_p = Mock(spec=Path)
                if path_str == "sensors.toml":
                    mock_p.exists.return_value = True
                    mock_p.open = sensors_file.open
                else:
                    mock_p.exists.return_value = False
                return mock_p

            mock_path_class.side_effect = path_factory

            result = _load_sensors_config()

            assert result is None

    def test_load_sensors_config_malformed_toml(self, temp_dir: Path) -> None:
        """Test loading malformed sensors.toml.

        Given: sensors.toml exists but is malformed
        When: _load_sensors_config is called
        Then: Returns None (exception caught)
        """
        sensors_file = temp_dir / "sensors.toml"
        sensors_file.write_text("this is not valid toml [[[")

        with patch("cowrieprocessor.cli.db_config.Path") as mock_path_class:

            def path_factory(path_str: str) -> Mock:
                mock_p = Mock(spec=Path)
                if path_str == "sensors.toml":
                    mock_p.exists.return_value = True
                    mock_p.open = sensors_file.open
                else:
                    mock_p.exists.return_value = False
                return mock_p

            mock_path_class.side_effect = path_factory

            result = _load_sensors_config()

            # Should return None when exception is caught
            assert result is None


class TestResolveDatabaseSettings:
    """Test resolve_database_settings function."""

    @patch("cowrieprocessor.cli.db_config._load_sensors_config")
    @patch("cowrieprocessor.cli.db_config.load_database_settings")
    def test_resolve_with_explicit_db_arg_sqlite_url(self, mock_load_settings: Mock, mock_load_config: Mock) -> None:
        """Test resolution with explicit sqlite:// URL argument.

        Given: Explicit --db-url argument with sqlite:// scheme
        When: resolve_database_settings is called
        Then: Uses the provided URL directly
        """
        from cowrieprocessor.settings import DatabaseSettings

        mock_load_settings.return_value = DatabaseSettings(url="sqlite:///test.db")

        result = resolve_database_settings("sqlite:///test.db")

        # Should call load_database_settings with the config
        mock_load_settings.assert_called_once_with(config={"url": "sqlite:///test.db"})
        # Should not try to load from sensors.toml
        mock_load_config.assert_not_called()

        assert result.url == "sqlite:///test.db"

    @patch("cowrieprocessor.cli.db_config._load_sensors_config")
    @patch("cowrieprocessor.cli.db_config.load_database_settings")
    def test_resolve_with_existing_sqlite_file(
        self, mock_load_settings: Mock, mock_load_config: Mock, temp_dir: Path
    ) -> None:
        """Test resolution with path to existing SQLite file.

        Given: Path to existing .sqlite file
        When: resolve_database_settings is called
        Then: Constructs sqlite:/// URL from path
        """
        # Create a test .sqlite file
        db_file = temp_dir / "test.sqlite"
        db_file.touch()

        expected_url = f"sqlite:///{db_file.resolve()}"

        result = resolve_database_settings(str(db_file))

        # Should create DatabaseSettings with resolved path
        assert result.url == expected_url

    @patch("cowrieprocessor.cli.db_config._load_sensors_config")
    @patch("cowrieprocessor.cli.db_config.load_database_settings")
    def test_resolve_with_sqlite_extension_nonexistent(
        self, mock_load_settings: Mock, mock_load_config: Mock, temp_dir: Path
    ) -> None:
        """Test resolution with .sqlite extension but file doesn't exist.

        Given: Path with .sqlite extension but file doesn't exist
        When: resolve_database_settings is called
        Then: Constructs sqlite:/// URL anyway
        """
        # Don't create the file
        db_file = temp_dir / "nonexistent.sqlite"

        expected_url = f"sqlite:///{db_file.resolve()}"

        result = resolve_database_settings(str(db_file))

        # Should still construct URL even though file doesn't exist
        assert result.url == expected_url

    @patch("cowrieprocessor.cli.db_config._load_sensors_config")
    @patch("cowrieprocessor.cli.db_config.load_database_settings")
    def test_resolve_with_postgresql_url(self, mock_load_settings: Mock, mock_load_config: Mock) -> None:
        """Test resolution with PostgreSQL URL.

        Given: PostgreSQL connection URL
        When: resolve_database_settings is called
        Then: Uses the provided URL via load_database_settings
        """
        from cowrieprocessor.settings import DatabaseSettings

        pg_url = "postgresql://user:pass@localhost:5432/cowrie"
        mock_load_settings.return_value = DatabaseSettings(url=pg_url)

        result = resolve_database_settings(pg_url)

        mock_load_settings.assert_called_once_with(config={"url": pg_url})
        assert result.url == pg_url

    @patch("cowrieprocessor.cli.db_config._load_sensors_config")
    @patch("cowrieprocessor.cli.db_config.load_database_settings")
    def test_resolve_from_sensors_config(self, mock_load_settings: Mock, mock_load_config: Mock) -> None:
        """Test resolution from sensors.toml when no argument provided.

        Given: No --db-url argument, sensors.toml exists with database config
        When: resolve_database_settings is called
        Then: Loads configuration from sensors.toml
        """
        from cowrieprocessor.settings import DatabaseSettings

        sensors_config = {"url": "postgresql://localhost/cowrie"}
        mock_load_config.return_value = sensors_config
        mock_load_settings.return_value = DatabaseSettings(url="postgresql://localhost/cowrie")

        resolve_database_settings(None)

        mock_load_config.assert_called_once()
        mock_load_settings.assert_called_once_with(config=sensors_config)

    @patch("cowrieprocessor.cli.db_config._load_sensors_config")
    @patch("cowrieprocessor.cli.db_config.load_database_settings")
    def test_resolve_from_defaults(self, mock_load_settings: Mock, mock_load_config: Mock) -> None:
        """Test resolution from defaults when no argument or sensors.toml.

        Given: No --db-url argument and no sensors.toml
        When: resolve_database_settings is called
        Then: Falls back to environment variables or default SQLite database
        """
        from cowrieprocessor.settings import DatabaseSettings

        mock_load_config.return_value = None  # No sensors.toml
        mock_load_settings.return_value = DatabaseSettings(url="sqlite:///~/.cowrieprocessor/cowrie.db")

        resolve_database_settings(None)

        mock_load_config.assert_called_once()
        # Should call load_database_settings without config argument
        mock_load_settings.assert_called_once_with()


class TestAddDatabaseArgument:
    """Test add_database_argument helper function."""

    def test_add_database_argument_default_help(self) -> None:
        """Test adding database argument with default help text.

        Given: ArgumentParser instance
        When: add_database_argument is called without help_text
        Then: Adds --db-url argument with default help
        """
        parser = argparse.ArgumentParser()

        add_database_argument(parser)

        # Parse with no arguments
        args = parser.parse_args([])
        assert hasattr(args, "db_url")
        assert args.db_url is None

        # Parse with --db-url
        args = parser.parse_args(["--db-url", "postgresql://localhost/test"])
        assert args.db_url == "postgresql://localhost/test"

    def test_add_database_argument_custom_help(self) -> None:
        """Test adding database argument with custom help text.

        Given: ArgumentParser instance and custom help text
        When: add_database_argument is called with help_text
        Then: Adds --db-url argument with custom help
        """
        parser = argparse.ArgumentParser()
        custom_help = "Custom database help text"

        add_database_argument(parser, help_text=custom_help)

        # Verify the argument was added (can't directly check help text without parsing)
        args = parser.parse_args([])
        assert hasattr(args, "db_url")

    def test_add_database_argument_accepts_sqlite_path(self) -> None:
        """Test that added argument accepts SQLite file path.

        Given: ArgumentParser with --db-url argument
        When: Parsing with SQLite file path
        Then: Accepts the path as argument value
        """
        parser = argparse.ArgumentParser()
        add_database_argument(parser)

        args = parser.parse_args(["--db-url", "/path/to/database.sqlite"])
        assert args.db_url == "/path/to/database.sqlite"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
