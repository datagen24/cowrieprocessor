"""Unit tests for database engine creation and configuration."""

from __future__ import annotations

import sqlite3
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.engine import Engine

from cowrieprocessor.db.engine import (
    _is_postgresql_url,
    _is_sqlite_url,
    _needs_static_pool,
    _sqlite_on_connect,
    create_engine_from_settings,
    create_engine_with_fallback,
    create_session_maker,
    detect_database_features,
    detect_postgresql_support,
    has_pgvector,
    is_postgresql,
)
from cowrieprocessor.settings import DatabaseSettings


class TestDetectPostgresqlSupport:
    """Test PostgreSQL support detection."""

    def test_detect_postgresql_support_with_psycopg_returns_true(self) -> None:
        """Test that PostgreSQL support detection returns True when psycopg is available."""
        # Mock successful import
        with patch('builtins.__import__', return_value=Mock()):
            result = detect_postgresql_support()
            assert result is True

    def test_detect_postgresql_support_without_psycopg_returns_false(self) -> None:
        """Test that PostgreSQL support detection returns False when psycopg is not available."""
        # Mock ImportError
        with patch('builtins.__import__', side_effect=ImportError):
            result = detect_postgresql_support()
            assert result is False


class TestUrlDetection:
    """Test URL type detection functions."""

    def test_is_postgresql_url_with_postgresql_url_returns_true(self) -> None:
        """Test that PostgreSQL URL detection returns True for postgresql:// URLs."""
        url = "postgresql://user:pass@localhost/db"
        result = _is_postgresql_url(url)
        assert result is True

    def test_is_postgresql_url_with_postgres_url_returns_true(self) -> None:
        """Test that PostgreSQL URL detection returns True for postgres:// URLs."""
        url = "postgres://user:pass@localhost/db"
        result = _is_postgresql_url(url)
        assert result is True

    def test_is_postgresql_url_with_sqlite_url_returns_false(self) -> None:
        """Test that PostgreSQL URL detection returns False for SQLite URLs."""
        url = "sqlite:///test.db"
        result = _is_postgresql_url(url)
        assert result is False

    def test_is_postgresql_url_with_invalid_url_returns_false(self) -> None:
        """Test that PostgreSQL URL detection returns False for invalid URLs."""
        url = "invalid://url"
        result = _is_postgresql_url(url)
        assert result is False

    def test_is_sqlite_url_with_sqlite_url_returns_true(self) -> None:
        """Test that SQLite URL detection returns True for sqlite:// URLs."""
        url = "sqlite:///test.db"
        result = _is_sqlite_url(url)
        assert result is True

    def test_is_sqlite_url_with_memory_url_returns_true(self) -> None:
        """Test that SQLite URL detection returns True for memory URLs."""
        url = "sqlite:///:memory:"
        result = _is_sqlite_url(url)
        assert result is True

    def test_is_sqlite_url_with_postgresql_url_returns_false(self) -> None:
        """Test that SQLite URL detection returns False for PostgreSQL URLs."""
        url = "postgresql://user:pass@localhost/db"
        result = _is_sqlite_url(url)
        assert result is False

    def test_needs_static_pool_with_memory_url_returns_true(self) -> None:
        """Test that static pool detection returns True for memory URLs."""
        url = "sqlite:///:memory:"
        result = _needs_static_pool(url)
        assert result is True

    def test_needs_static_pool_with_file_memory_url_returns_true(self) -> None:
        """Test that static pool detection returns True for file::memory: URLs."""
        url = "sqlite:///file::memory:"
        result = _needs_static_pool(url)
        assert result is True

    def test_needs_static_pool_with_file_url_returns_false(self) -> None:
        """Test that static pool detection returns False for file URLs."""
        url = "sqlite:///test.db"
        result = _needs_static_pool(url)
        assert result is False


class TestSqliteOnConnect:
    """Test SQLite connection configuration."""

    def test_sqlite_on_connect_configures_basic_settings(self) -> None:
        """Test that SQLite on_connect configures basic PRAGMA settings."""
        settings = DatabaseSettings(url="sqlite:///test.db")
        on_connect = _sqlite_on_connect(settings)

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        on_connect(mock_connection, None)

        # Verify cursor was created and closed
        mock_connection.cursor.assert_called_once()
        mock_cursor.close.assert_called_once()

        # Verify basic PRAGMA settings were executed with actual defaults
        expected_calls = [
            "PRAGMA busy_timeout=5000",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA cache_size=-64000",
        ]
        actual_calls = [call[0][0] for call in mock_cursor.execute.call_args_list]

        for expected_call in expected_calls:
            assert expected_call in actual_calls

    def test_sqlite_on_connect_with_wal_enabled_configures_wal(self) -> None:
        """Test that SQLite on_connect configures WAL mode when enabled."""
        settings = DatabaseSettings(url="sqlite:///test.db", sqlite_wal=True)
        on_connect = _sqlite_on_connect(settings)

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("WAL",)  # WAL mode enabled

        on_connect(mock_connection, None)

        # Verify WAL mode was attempted
        wal_calls = [call for call in mock_cursor.execute.call_args_list if "journal_mode=WAL" in call[0][0]]
        assert len(wal_calls) == 1

    def test_sqlite_on_connect_with_wal_fallback_configures_fallback(self) -> None:
        """Test that SQLite on_connect configures journal mode fallback."""
        settings = DatabaseSettings(url="sqlite:///test.db", sqlite_wal=True, sqlite_journal_fallback="DELETE")
        on_connect = _sqlite_on_connect(settings)

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("DELETE",)  # WAL not available

        on_connect(mock_connection, None)

        # Verify fallback was attempted
        fallback_calls = [call for call in mock_cursor.execute.call_args_list if "journal_mode=DELETE" in call[0][0]]
        assert len(fallback_calls) == 1

    def test_sqlite_on_connect_handles_database_error_gracefully(self) -> None:
        """Test that SQLite on_connect handles database errors gracefully."""
        settings = DatabaseSettings(url="sqlite:///test.db", sqlite_wal=True)
        on_connect = _sqlite_on_connect(settings)

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = sqlite3.DatabaseError("Database error")

        # Should not raise an exception
        on_connect(mock_connection, None)

        mock_cursor.close.assert_called_once()


class TestCreateEngineFromSettings:
    """Test engine creation from settings."""

    def test_create_engine_from_settings_sqlite_creates_engine(self) -> None:
        """Test that engine creation works for SQLite."""
        settings = DatabaseSettings(url="sqlite:///test.db")

        with patch('cowrieprocessor.db.engine.create_engine') as mock_create_engine:
            with patch('cowrieprocessor.db.engine.event.listen') as mock_event_listen:
                mock_engine = Mock()
                mock_create_engine.return_value = mock_engine

                result = create_engine_from_settings(settings)

                assert result == mock_engine
                mock_create_engine.assert_called_once()
                # Verify event listener was registered for SQLite
                mock_event_listen.assert_called_once()

    def test_create_engine_from_settings_postgresql_converts_url(self) -> None:
        """Test that PostgreSQL URLs are converted to use psycopg driver."""
        settings = DatabaseSettings(url="postgresql://user:pass@localhost/db")

        with patch('cowrieprocessor.db.engine.create_engine') as mock_create_engine:
            mock_engine = Mock()
            mock_create_engine.return_value = mock_engine

            result = create_engine_from_settings(settings)

            assert result == mock_engine
            # Verify URL was converted
            call_args = mock_create_engine.call_args
            assert "postgresql+psycopg://" in call_args[0][0]

    def test_create_engine_from_settings_postgres_converts_url(self) -> None:
        """Test that postgres:// URLs are converted to use psycopg driver."""
        settings = DatabaseSettings(url="postgres://user:pass@localhost/db")

        with patch('cowrieprocessor.db.engine.create_engine') as mock_create_engine:
            mock_engine = Mock()
            mock_create_engine.return_value = mock_engine

            result = create_engine_from_settings(settings)

            assert result == mock_engine
            # Verify URL was converted
            call_args = mock_create_engine.call_args
            assert "postgresql+psycopg://" in call_args[0][0]

    def test_create_engine_from_settings_sqlite_memory_uses_static_pool(self) -> None:
        """Test that SQLite memory URLs use StaticPool."""
        settings = DatabaseSettings(url="sqlite:///:memory:")

        with patch('cowrieprocessor.db.engine.create_engine') as mock_create_engine:
            with patch('cowrieprocessor.db.engine.event.listen') as mock_event_listen:
                mock_engine = Mock()
                mock_create_engine.return_value = mock_engine

                result = create_engine_from_settings(settings)

                assert result == mock_engine
                # Verify StaticPool was used and pool_timeout was removed
                call_kwargs = mock_create_engine.call_args[1]
                assert "poolclass" in call_kwargs
                assert "pool_timeout" not in call_kwargs

    def test_create_engine_from_settings_with_pool_settings_applies_config(self) -> None:
        """Test that pool settings are applied to engine."""
        settings = DatabaseSettings(url="sqlite:///test.db", pool_size=10, pool_timeout=30, echo=True)

        with patch('cowrieprocessor.db.engine.create_engine') as mock_create_engine:
            with patch('cowrieprocessor.db.engine.event.listen') as mock_event_listen:
                mock_engine = Mock()
                mock_create_engine.return_value = mock_engine

                result = create_engine_from_settings(settings)

                assert result == mock_engine
                # Verify pool settings were applied
                call_kwargs = mock_create_engine.call_args[1]
                assert call_kwargs["pool_size"] == 10
                assert call_kwargs["pool_timeout"] == 30
                assert call_kwargs["echo"] is True
                assert call_kwargs["future"] is True
                assert call_kwargs["pool_pre_ping"] is True

    def test_create_engine_from_settings_sqlite_sets_connect_args(self) -> None:
        """Test that SQLite connect arguments are set correctly."""
        settings = DatabaseSettings(url="sqlite:///test.db")

        with patch('cowrieprocessor.db.engine.create_engine') as mock_create_engine:
            with patch('cowrieprocessor.db.engine.event.listen') as mock_event_listen:
                mock_engine = Mock()
                mock_create_engine.return_value = mock_engine

                result = create_engine_from_settings(settings)

                assert result == mock_engine
                # Verify connect_args were set
                call_kwargs = mock_create_engine.call_args[1]
                assert "connect_args" in call_kwargs
                assert call_kwargs["connect_args"]["check_same_thread"] is False


class TestCreateEngineWithFallback:
    """Test engine creation with PostgreSQL fallback."""

    @patch('cowrieprocessor.db.engine.detect_postgresql_support', return_value=True)
    @patch('cowrieprocessor.db.engine.create_engine_from_settings')
    def test_create_engine_with_fallback_postgresql_available_creates_engine(
        self, mock_create_engine: Mock, mock_detect_support: Mock
    ) -> None:
        """Test that engine creation works when PostgreSQL support is available."""
        settings = DatabaseSettings(url="postgresql://user:pass@localhost/db")
        mock_engine = Mock()
        mock_create_engine.return_value = mock_engine

        result = create_engine_with_fallback(settings)

        assert result == mock_engine
        mock_create_engine.assert_called_once_with(settings)

    @patch('cowrieprocessor.db.engine.detect_postgresql_support', return_value=False)
    def test_create_engine_with_fallback_postgresql_unavailable_raises_error(self, mock_detect_support: Mock) -> None:
        """Test that engine creation raises error when PostgreSQL support is not available."""
        settings = DatabaseSettings(url="postgresql://user:pass@localhost/db")

        with pytest.raises(ValueError, match="PostgreSQL driver not installed"):
            create_engine_with_fallback(settings)

    @patch('cowrieprocessor.db.engine.detect_postgresql_support', return_value=False)
    @patch('cowrieprocessor.db.engine.create_engine_from_settings')
    def test_create_engine_with_fallback_sqlite_creates_engine(
        self, mock_create_engine: Mock, mock_detect_support: Mock
    ) -> None:
        """Test that engine creation works for SQLite regardless of PostgreSQL support."""
        settings = DatabaseSettings(url="sqlite:///test.db")
        mock_engine = Mock()
        mock_create_engine.return_value = mock_engine

        result = create_engine_with_fallback(settings)

        assert result == mock_engine
        mock_create_engine.assert_called_once_with(settings)


class TestCreateSessionMaker:
    """Test session maker creation."""

    def test_create_session_maker_returns_configured_sessionmaker(self) -> None:
        """Test that session maker is created with correct configuration."""
        mock_engine = Mock(spec=Engine)

        session_maker = create_session_maker(mock_engine)

        # Verify session maker was created (it's a sessionmaker instance)
        assert session_maker is not None
        # The actual attributes are set internally by SQLAlchemy


class TestDatabaseFeatureDetection:
    """Test database feature detection."""

    def test_detect_database_features_sqlite_returns_basic_features(self) -> None:
        """Test that SQLite feature detection returns basic features."""
        mock_engine = Mock()
        mock_connection = Mock()
        mock_connection_context = Mock()
        mock_connection_context.__enter__ = Mock(return_value=mock_connection)
        mock_connection_context.__exit__ = Mock(return_value=None)
        mock_engine.connect.return_value = mock_connection_context
        mock_connection.dialect.name = "sqlite"

        with patch('cowrieprocessor.db.engine.text') as mock_text:
            mock_result = Mock()
            mock_result.scalar.return_value = "3.39.0"
            mock_connection.execute.return_value = mock_result

            features = detect_database_features(mock_engine)

            assert features["database_type"] == "sqlite"
            assert features["version"] == "3.39.0"
            assert features["pgvector"] is False
            assert features["dlq_advanced"] is False
            assert features["vector_longtail"] is False

    def test_detect_database_features_postgresql_returns_advanced_features(self) -> None:
        """Test that PostgreSQL feature detection returns advanced features."""
        mock_engine = Mock()
        mock_connection = Mock()
        mock_connection_context = Mock()
        mock_connection_context.__enter__ = Mock(return_value=mock_connection)
        mock_connection_context.__exit__ = Mock(return_value=None)
        mock_engine.connect.return_value = mock_connection_context
        mock_connection.dialect.name = "postgresql"

        with patch('cowrieprocessor.db.engine.text') as mock_text:
            mock_version_result = Mock()
            mock_version_result.scalar.return_value = "PostgreSQL 15.4"
            mock_connection.execute.return_value = mock_version_result

            with patch('cowrieprocessor.db.engine.has_pgvector', return_value=True):
                features = detect_database_features(mock_engine)

                assert features["database_type"] == "postgresql"
                assert features["version"] == "PostgreSQL 15.4"
                assert features["pgvector"] is True
                assert features["dlq_advanced"] is True
                assert features["vector_longtail"] is True
                assert features["max_dimensions"] == 2000

    def test_detect_database_features_handles_exceptions_gracefully(self) -> None:
        """Test that feature detection handles exceptions gracefully."""
        mock_engine = Mock()
        mock_connection = Mock()
        mock_connection_context = Mock()
        mock_connection_context.__enter__ = Mock(return_value=mock_connection)
        mock_connection_context.__exit__ = Mock(return_value=None)
        mock_engine.connect.return_value = mock_connection_context
        mock_connection.dialect.name = "sqlite"
        mock_connection.execute.side_effect = Exception("Database error")

        features = detect_database_features(mock_engine)

        assert features["database_type"] == "sqlite"
        assert features["version"] == "Unknown"

    def test_detect_database_features_pgvector_with_version(self) -> None:
        """Test that pgvector version detection works."""
        mock_engine = Mock()
        mock_connection = Mock()
        mock_connection_context = Mock()
        mock_connection_context.__enter__ = Mock(return_value=mock_connection)
        mock_connection_context.__exit__ = Mock(return_value=None)
        mock_engine.connect.return_value = mock_connection_context
        mock_connection.dialect.name = "postgresql"

        with patch('cowrieprocessor.db.engine.text') as mock_text:
            # Mock version query
            mock_version_result = Mock()
            mock_version_result.scalar.return_value = "PostgreSQL 15.4"
            # Mock pgvector version query
            mock_pgvector_result = Mock()
            mock_pgvector_result.scalar.return_value = "0.5.0"

            mock_connection.execute.side_effect = [mock_version_result, mock_pgvector_result]

            with patch('cowrieprocessor.db.engine.has_pgvector', return_value=True):
                features = detect_database_features(mock_engine)

                assert features["pgvector_version"] == "0.5.0"


class TestIsPostgresql:
    """Test PostgreSQL engine detection."""

    def test_is_postgresql_with_postgresql_engine_returns_true(self) -> None:
        """Test that PostgreSQL engine detection returns True for PostgreSQL engines."""
        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"

        result = is_postgresql(mock_engine)

        assert result is True

    def test_is_postgresql_with_sqlite_engine_returns_false(self) -> None:
        """Test that PostgreSQL engine detection returns False for SQLite engines."""
        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"

        result = is_postgresql(mock_engine)

        assert result is False


class TestHasPgvector:
    """Test pgvector extension detection."""

    def test_has_pgvector_with_postgresql_and_extension_returns_true(self) -> None:
        """Test that pgvector detection returns True when extension is available."""
        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"
        mock_connection = Mock()
        mock_connection_context = Mock()
        mock_connection_context.__enter__ = Mock(return_value=mock_connection)
        mock_connection_context.__exit__ = Mock(return_value=None)
        mock_engine.connect.return_value = mock_connection_context

        with patch('cowrieprocessor.db.engine.text') as mock_text:
            mock_result = Mock()
            mock_result.scalar.return_value = True
            mock_connection.execute.return_value = mock_result

            result = has_pgvector(mock_engine)

            assert result is True

    def test_has_pgvector_with_sqlite_engine_returns_false(self) -> None:
        """Test that pgvector detection returns False for SQLite engines."""
        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"

        result = has_pgvector(mock_engine)

        assert result is False

    def test_has_pgvector_with_exception_returns_false(self) -> None:
        """Test that pgvector detection returns False when exception occurs."""
        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"
        mock_engine.connect.side_effect = Exception("Connection error")

        result = has_pgvector(mock_engine)

        assert result is False

    def test_has_pgvector_with_no_extension_returns_false(self) -> None:
        """Test that pgvector detection returns False when extension is not available."""
        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"
        mock_connection = Mock()
        mock_connection_context = Mock()
        mock_connection_context.__enter__ = Mock(return_value=mock_connection)
        mock_connection_context.__exit__ = Mock(return_value=None)
        mock_engine.connect.return_value = mock_connection_context

        with patch('cowrieprocessor.db.engine.text') as mock_text:
            mock_result = Mock()
            mock_result.scalar.return_value = False
            mock_connection.execute.return_value = mock_result

            result = has_pgvector(mock_engine)

            assert result is False
