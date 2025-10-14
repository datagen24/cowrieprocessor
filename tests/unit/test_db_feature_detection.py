"""Unit tests for database feature detection."""

from __future__ import annotations

from unittest.mock import Mock, patch

from sqlalchemy.engine import Engine

from cowrieprocessor.db.engine import detect_database_features, has_pgvector, is_postgresql


class TestDatabaseFeatureDetection:
    """Test database feature detection functions."""

    def test_is_postgresql_postgresql_engine(self) -> None:
        """Test PostgreSQL engine detection."""
        engine = Mock(spec=Engine)
        engine.dialect = Mock()
        engine.dialect.name = "postgresql"
        
        assert is_postgresql(engine) is True

    def test_is_postgresql_sqlite_engine(self) -> None:
        """Test SQLite engine detection."""
        engine = Mock(spec=Engine)
        engine.dialect = Mock()
        engine.dialect.name = "sqlite"
        
        assert is_postgresql(engine) is False

    def test_has_pgvector_non_postgresql(self) -> None:
        """Test pgvector detection with non-PostgreSQL engine."""
        engine = Mock(spec=Engine)
        engine.dialect = Mock()
        engine.dialect.name = "sqlite"
        
        assert has_pgvector(engine) is False

    def test_has_pgvector_postgresql_no_extension(self) -> None:
        """Test pgvector detection with PostgreSQL but no extension."""
        engine = Mock(spec=Engine)
        engine.dialect = Mock()
        engine.dialect.name = "postgresql"
        
        mock_conn = Mock()
        mock_result = Mock()
        mock_result.scalar.return_value = False
        mock_conn.execute.return_value = mock_result
        
        with patch.object(engine, "connect", return_value=mock_conn):
            assert has_pgvector(engine) is False

    def test_has_pgvector_postgresql_with_extension(self) -> None:
        """Test pgvector detection with PostgreSQL and extension."""
        engine = Mock(spec=Engine)
        engine.dialect = Mock()
        engine.dialect.name = "postgresql"
        
        mock_conn = Mock()
        mock_result = Mock()
        mock_result.scalar.return_value = True
        mock_conn.execute.return_value = mock_result
        
        # Mock the context manager protocol
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        
        with patch.object(engine, "connect", return_value=mock_conn):
            assert has_pgvector(engine) is True

    def test_has_pgvector_postgresql_exception(self) -> None:
        """Test pgvector detection with PostgreSQL but exception."""
        engine = Mock(spec=Engine)
        engine.dialect = Mock()
        engine.dialect.name = "postgresql"
        
        mock_conn = Mock()
        mock_conn.execute.side_effect = Exception("Database error")
        
        with patch.object(engine, "connect", return_value=mock_conn):
            assert has_pgvector(engine) is False

    def test_detect_database_features_postgresql_with_pgvector(self) -> None:
        """Test feature detection for PostgreSQL with pgvector."""
        engine = Mock(spec=Engine)
        engine.dialect = Mock()
        engine.dialect.name = "postgresql"
        
        mock_conn = Mock()
        mock_conn.dialect = Mock()
        mock_conn.dialect.name = "postgresql"
        
        # Mock version query
        version_result = Mock()
        version_result.scalar.return_value = "PostgreSQL 15.4"
        
        # Mock pgvector extension check
        pgvector_result = Mock()
        pgvector_result.scalar.return_value = True
        
        # Mock pgvector version query
        pgvector_version_result = Mock()
        pgvector_version_result.scalar.return_value = "0.5.0"
        
        mock_conn.execute.side_effect = [
            version_result,  # version() query
            pgvector_result,  # pgvector extension check
            pgvector_version_result,  # pgvector version query
        ]
        
        # Mock the context manager protocol
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        
        with patch.object(engine, "connect", return_value=mock_conn):
            features = detect_database_features(engine)
        
        assert features["database_type"] == "postgresql"
        assert features["version"] == "PostgreSQL 15.4"
        assert features["pgvector"] is True
        assert features["pgvector_version"] == "0.5.0"
        assert features["dlq_advanced"] is True
        assert features["vector_longtail"] is True
        assert features["max_dimensions"] == 2000

    def test_detect_database_features_postgresql_without_pgvector(self) -> None:
        """Test feature detection for PostgreSQL without pgvector."""
        engine = Mock(spec=Engine)
        engine.dialect = Mock()
        engine.dialect.name = "postgresql"
        
        mock_conn = Mock()
        mock_conn.dialect = Mock()
        mock_conn.dialect.name = "postgresql"
        
        # Mock version query
        version_result = Mock()
        version_result.scalar.return_value = "PostgreSQL 15.4"
        
        # Mock pgvector extension check
        pgvector_result = Mock()
        pgvector_result.scalar.return_value = False
        
        mock_conn.execute.side_effect = [
            version_result,  # version() query
            pgvector_result,  # pgvector extension check
        ]
        
        # Mock the context manager protocol
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        
        with patch.object(engine, "connect", return_value=mock_conn):
            features = detect_database_features(engine)
        
        assert features["database_type"] == "postgresql"
        assert features["version"] == "PostgreSQL 15.4"
        assert features["pgvector"] is False
        assert features["pgvector_version"] is None
        assert features["dlq_advanced"] is True
        assert features["vector_longtail"] is False
        assert features["max_dimensions"] == 0

    def test_detect_database_features_sqlite(self) -> None:
        """Test feature detection for SQLite."""
        engine = Mock(spec=Engine)
        engine.dialect = Mock()
        engine.dialect.name = "sqlite"
        
        mock_conn = Mock()
        mock_conn.dialect = Mock()
        mock_conn.dialect.name = "sqlite"
        
        # Mock SQLite version query
        version_result = Mock()
        version_result.scalar.return_value = "3.42.0"
        
        mock_conn.execute.return_value = version_result
        
        # Mock the context manager protocol
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        
        with patch.object(engine, "connect", return_value=mock_conn):
            features = detect_database_features(engine)
        
        assert features["database_type"] == "sqlite"
        assert features["version"] == "3.42.0"
        assert features["pgvector"] is False
        assert features["pgvector_version"] is None
        assert features["dlq_advanced"] is False
        assert features["vector_longtail"] is False
        assert features["max_dimensions"] == 0

    def test_detect_database_features_version_exception(self) -> None:
        """Test feature detection with version query exception."""
        engine = Mock(spec=Engine)
        engine.dialect = Mock()
        engine.dialect.name = "postgresql"
        
        mock_conn = Mock()
        mock_conn.dialect = Mock()
        mock_conn.dialect.name = "postgresql"
        mock_conn.execute.side_effect = Exception("Database error")
        
        # Mock the context manager protocol
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        
        with patch.object(engine, "connect", return_value=mock_conn):
            features = detect_database_features(engine)
        
        assert features["database_type"] == "postgresql"
        assert features["version"] == "Unknown"
        assert features["pgvector"] is False
        assert features["pgvector_version"] is None
        assert features["dlq_advanced"] is True
        assert features["vector_longtail"] is False
        assert features["max_dimensions"] == 0

    def test_detect_database_features_pgvector_version_exception(self) -> None:
        """Test feature detection with pgvector version query exception."""
        engine = Mock(spec=Engine)
        engine.dialect = Mock()
        engine.dialect.name = "postgresql"
        
        mock_conn = Mock()
        mock_conn.dialect = Mock()
        mock_conn.dialect.name = "postgresql"
        
        # Mock version query
        version_result = Mock()
        version_result.scalar.return_value = "PostgreSQL 15.4"
        
        # Mock pgvector extension check
        pgvector_result = Mock()
        pgvector_result.scalar.return_value = True
        
        # Mock pgvector version query exception
        pgvector_version_result = Mock()
        pgvector_version_result.scalar.side_effect = Exception("Version query failed")
        
        mock_conn.execute.side_effect = [
            version_result,  # version() query
            pgvector_result,  # pgvector extension check
            pgvector_version_result,  # pgvector version query
        ]
        
        # Mock the context manager protocol
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        
        with patch.object(engine, "connect", return_value=mock_conn):
            features = detect_database_features(engine)
        
        assert features["database_type"] == "postgresql"
        assert features["version"] == "PostgreSQL 15.4"
        assert features["pgvector"] is True
        assert features["pgvector_version"] == "Unknown"
        assert features["dlq_advanced"] is True
        assert features["vector_longtail"] is True
        assert features["max_dimensions"] == 2000
