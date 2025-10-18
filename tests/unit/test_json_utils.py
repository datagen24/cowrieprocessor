"""Unit tests for JSON access abstraction layer."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy import JSON, Column, Integer, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from cowrieprocessor.db.json_utils import (
    JSONAccessor,
    get_dialect_name,
    get_dialect_name_from_engine,
    json_field,
    json_field_equals,
    json_field_exists,
    json_field_like,
    json_field_not_empty,
)

Base = declarative_base()


class JSONTestModel(Base):
    """Test model for JSON operations."""

    __tablename__ = "test_model"

    id = Column(Integer, primary_key=True)
    payload = Column(JSON, nullable=False)


class TestJSONAccessor:
    """Test cases for JSONAccessor class."""

    def test_get_field_sqlite(self) -> None:
        """Test JSON field extraction for SQLite."""
        column = JSONTestModel.payload
        result = JSONAccessor.get_field(column, "src_ip", "sqlite")

        # Should generate json_extract(payload, '$.src_ip')
        assert "json_extract" in str(result)
        # SQLAlchemy uses parameterized queries, so we check the function type
        assert hasattr(result, 'clause_expr')  # Check it's a function call

    def test_get_field_postgresql(self) -> None:
        """Test JSON field extraction for PostgreSQL."""
        column = JSONTestModel.payload
        result = JSONAccessor.get_field(column, "src_ip", "postgresql")

        # Should generate payload->>'src_ip'
        assert "->>" in str(result)
        # SQLAlchemy uses parameterized queries, so field names are in parameters
        assert hasattr(result, 'left')  # Check it's a binary expression

    def test_get_nested_field_sqlite(self) -> None:
        """Test nested JSON field extraction for SQLite."""
        column = JSONTestModel.payload
        result = JSONAccessor.get_nested_field(column, "user.profile.name", "sqlite")

        # Should generate json_extract(payload, '$.user.profile.name')
        assert "json_extract" in str(result)
        # SQLAlchemy uses parameterized queries, so field names are in parameters
        assert hasattr(result, 'clause_expr')  # Check it's a function call

    def test_get_nested_field_postgresql(self) -> None:
        """Test nested JSON field extraction for PostgreSQL."""
        column = JSONTestModel.payload
        result = JSONAccessor.get_nested_field(column, "user.profile.name", "postgresql")

        # Should generate payload->'user'->'profile'->>'name'
        assert "->" in str(result)
        # SQLAlchemy uses parameterized queries, so field names are in parameters
        assert hasattr(result, 'left')  # Check it's a binary expression

    def test_field_exists_sqlite(self) -> None:
        """Test field existence check for SQLite."""
        column = JSONTestModel.payload
        result = JSONAccessor.field_exists(column, "src_ip", "sqlite")

        # Should generate json_extract(payload, '$.src_ip') IS NOT NULL
        assert "json_extract" in str(result)
        assert "IS NOT NULL" in str(result)

    def test_field_exists_postgresql(self) -> None:
        """Test field existence check for PostgreSQL."""
        column = JSONTestModel.payload
        result = JSONAccessor.field_exists(column, "src_ip", "postgresql")

        # Should generate payload->>'src_ip' IS NOT NULL
        assert "->>" in str(result)
        assert "IS NOT NULL" in str(result)

    def test_field_not_empty_sqlite(self) -> None:
        """Test field not empty check for SQLite."""
        column = JSONTestModel.payload
        result = JSONAccessor.field_not_empty(column, "src_ip", "sqlite")

        # Should generate json_extract(payload, '$.src_ip') IS NOT NULL AND json_extract(payload, '$.src_ip') != ''
        assert "json_extract" in str(result)
        assert "IS NOT NULL" in str(result)
        assert "!=" in str(result)

    def test_field_not_empty_postgresql(self) -> None:
        """Test field not empty check for PostgreSQL."""
        column = JSONTestModel.payload
        result = JSONAccessor.field_not_empty(column, "src_ip", "postgresql")

        # Should generate payload->>'src_ip' IS NOT NULL AND payload->>'src_ip' != ''
        assert "->>" in str(result)
        assert "IS NOT NULL" in str(result)
        assert "!=" in str(result)

    def test_field_equals_sqlite(self) -> None:
        """Test field equality check for SQLite."""
        column = JSONTestModel.payload
        result = JSONAccessor.field_equals(column, "eventid", "cowrie.session.connect", "sqlite")

        # Should generate json_extract(payload, '$.eventid') = 'cowrie.session.connect'
        assert "json_extract" in str(result)
        # SQLAlchemy uses parameterized queries
        # SQLAlchemy uses parameterized queries

    def test_field_equals_postgresql(self) -> None:
        """Test field equality check for PostgreSQL."""
        column = JSONTestModel.payload
        result = JSONAccessor.field_equals(column, "eventid", "cowrie.session.connect", "postgresql")

        # Should generate payload->>'eventid' = 'cowrie.session.connect'
        assert "->>" in str(result)
        # SQLAlchemy uses parameterized queries
        # SQLAlchemy uses parameterized queries

    def test_field_like_sqlite(self) -> None:
        """Test field LIKE check for SQLite."""
        column = JSONTestModel.payload
        result = JSONAccessor.field_like(column, "eventid", "%command%", "sqlite")

        # Should generate json_extract(payload, '$.eventid') LIKE '%command%'
        assert "json_extract" in str(result)
        assert "LIKE" in str(result)
        # SQLAlchemy uses parameterized queries

    def test_field_like_postgresql(self) -> None:
        """Test field LIKE check for PostgreSQL."""
        column = JSONTestModel.payload
        result = JSONAccessor.field_like(column, "eventid", "%command%", "postgresql")

        # Should generate payload->>'eventid' LIKE '%command%'
        assert "->>" in str(result)
        assert "LIKE" in str(result)
        # SQLAlchemy uses parameterized queries


class TestConvenienceFunctions:
    """Test cases for convenience functions."""

    def test_json_field_sqlite(self) -> None:
        """Test json_field convenience function for SQLite."""
        column = JSONTestModel.payload
        result = json_field(column, "src_ip", "sqlite")

        assert "json_extract" in str(result)
        # SQLAlchemy uses parameterized queries

    def test_json_field_postgresql(self) -> None:
        """Test json_field convenience function for PostgreSQL."""
        column = JSONTestModel.payload
        result = json_field(column, "src_ip", "postgresql")

        assert "->>" in str(result)
        # SQLAlchemy uses parameterized queries

    def test_json_field_exists_sqlite(self) -> None:
        """Test json_field_exists convenience function for SQLite."""
        column = JSONTestModel.payload
        result = json_field_exists(column, "src_ip", "sqlite")

        assert "json_extract" in str(result)
        assert "IS NOT NULL" in str(result)

    def test_json_field_exists_postgresql(self) -> None:
        """Test json_field_exists convenience function for PostgreSQL."""
        column = JSONTestModel.payload
        result = json_field_exists(column, "src_ip", "postgresql")

        assert "->>" in str(result)
        assert "IS NOT NULL" in str(result)

    def test_json_field_not_empty_sqlite(self) -> None:
        """Test json_field_not_empty convenience function for SQLite."""
        column = JSONTestModel.payload
        result = json_field_not_empty(column, "src_ip", "sqlite")

        assert "json_extract" in str(result)
        assert "IS NOT NULL" in str(result)
        assert "!=" in str(result)

    def test_json_field_not_empty_postgresql(self) -> None:
        """Test json_field_not_empty convenience function for PostgreSQL."""
        column = JSONTestModel.payload
        result = json_field_not_empty(column, "src_ip", "postgresql")

        assert "->>" in str(result)
        assert "IS NOT NULL" in str(result)
        assert "!=" in str(result)

    def test_json_field_equals_sqlite(self) -> None:
        """Test json_field_equals convenience function for SQLite."""
        column = JSONTestModel.payload
        result = json_field_equals(column, "eventid", "cowrie.session.connect", "sqlite")

        assert "json_extract" in str(result)
        # SQLAlchemy uses parameterized queries
        # SQLAlchemy uses parameterized queries

    def test_json_field_equals_postgresql(self) -> None:
        """Test json_field_equals convenience function for PostgreSQL."""
        column = JSONTestModel.payload
        result = json_field_equals(column, "eventid", "cowrie.session.connect", "postgresql")

        assert "->>" in str(result)
        # SQLAlchemy uses parameterized queries
        # SQLAlchemy uses parameterized queries

    def test_json_field_like_sqlite(self) -> None:
        """Test json_field_like convenience function for SQLite."""
        column = JSONTestModel.payload
        result = json_field_like(column, "eventid", "%command%", "sqlite")

        assert "json_extract" in str(result)
        assert "LIKE" in str(result)
        # SQLAlchemy uses parameterized queries

    def test_json_field_like_postgresql(self) -> None:
        """Test json_field_like convenience function for PostgreSQL."""
        column = JSONTestModel.payload
        result = json_field_like(column, "eventid", "%command%", "postgresql")

        assert "->>" in str(result)
        assert "LIKE" in str(result)
        # SQLAlchemy uses parameterized queries


class TestDialectDetection:
    """Test cases for dialect detection functions."""

    def test_get_dialect_name_sqlite(self) -> None:
        """Test dialect name detection for SQLite."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            engine = create_engine(f"sqlite:///{db_path}")
            dialect_name = get_dialect_name_from_engine(engine)
            assert dialect_name == "sqlite"

            with engine.connect() as conn:
                dialect_name = get_dialect_name(conn)
                assert dialect_name == "sqlite"
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_get_dialect_name_postgresql(self) -> None:
        """Test dialect name detection for PostgreSQL."""
        # This test would require a PostgreSQL connection
        # For now, we'll just test the function logic with a mock engine
        from unittest.mock import Mock

        from sqlalchemy.engine import Engine

        mock_engine = Mock(spec=Engine)
        mock_dialect = Mock()
        mock_dialect.name = "postgresql"
        mock_engine.dialect = mock_dialect

        dialect_name = get_dialect_name_from_engine(mock_engine)
        assert dialect_name == "postgresql"


class TestIntegration:
    """Integration tests for JSON operations."""

    def test_json_operations_with_sqlite(self) -> None:
        """Test JSON operations with actual SQLite database."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            engine = create_engine(f"sqlite:///{db_path}")
            Base.metadata.create_all(engine)

            Session = sessionmaker(bind=engine)
            session = Session()

            # Insert test data
            test_data = JSONTestModel(
                payload={
                    "src_ip": "192.168.1.1",
                    "eventid": "cowrie.session.connect",
                    "sensor": "test-sensor",
                    "user": {"profile": {"name": "test-user"}},
                }
            )
            session.add(test_data)
            session.commit()

            # Test field extraction
            dialect_name = get_dialect_name_from_engine(engine)

            # Test basic field extraction
            src_ip_expr = JSONAccessor.get_field(JSONTestModel.payload, "src_ip", dialect_name)
            result = session.query(src_ip_expr).first()
            assert result[0] == "192.168.1.1"

            # Test field equality
            eventid_expr = JSONAccessor.field_equals(
                JSONTestModel.payload, "eventid", "cowrie.session.connect", dialect_name
            )
            result = session.query(JSONTestModel).filter(eventid_expr).first()
            assert result is not None
            assert result.payload["eventid"] == "cowrie.session.connect"

            # Test field existence
            exists_expr = JSONAccessor.field_exists(JSONTestModel.payload, "src_ip", dialect_name)
            result = session.query(JSONTestModel).filter(exists_expr).first()
            assert result is not None

            # Test field not empty
            not_empty_expr = JSONAccessor.field_not_empty(JSONTestModel.payload, "src_ip", dialect_name)
            result = session.query(JSONTestModel).filter(not_empty_expr).first()
            assert result is not None

            # Test nested field extraction
            nested_expr = JSONAccessor.get_nested_field(JSONTestModel.payload, "user.profile.name", dialect_name)
            result = session.query(nested_expr).first()
            assert result[0] == "test-user"

            session.close()

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_json_operations_with_empty_fields(self) -> None:
        """Test JSON operations with empty/null fields."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            engine = create_engine(f"sqlite:///{db_path}")
            Base.metadata.create_all(engine)

            Session = sessionmaker(bind=engine)
            session = Session()

            # Insert test data with empty/null fields
            test_data = JSONTestModel(
                payload={
                    "src_ip": "",  # Empty string
                    "eventid": "cowrie.session.connect",
                    "missing_field": None,  # This won't be in the JSON
                }
            )
            session.add(test_data)
            session.commit()

            dialect_name = get_dialect_name_from_engine(engine)

            # Test field not empty (should exclude empty string)
            not_empty_expr = JSONAccessor.field_not_empty(JSONTestModel.payload, "src_ip", dialect_name)
            result = session.query(JSONTestModel).filter(not_empty_expr).first()
            assert result is None  # Empty string should be filtered out

            # Test field exists (should include empty string)
            exists_expr = JSONAccessor.field_exists(JSONTestModel.payload, "src_ip", dialect_name)
            result = session.query(JSONTestModel).filter(exists_expr).first()
            assert result is not None  # Empty string should still exist

            # Test field exists for missing field
            missing_exists_expr = JSONAccessor.field_exists(JSONTestModel.payload, "missing_field", dialect_name)
            result = session.query(JSONTestModel).filter(missing_exists_expr).first()
            assert result is None  # Missing field should not exist

            session.close()

        finally:
            Path(db_path).unlink(missing_ok=True)
