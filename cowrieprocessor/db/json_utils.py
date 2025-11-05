"""JSON field access abstraction for cross-backend compatibility.

This module provides backend-agnostic JSON field access operations,
supporting both SQLite's json_extract() and PostgreSQL's ->> operators.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Column, func
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.sql.elements import BinaryExpression, ColumnElement
from sqlalchemy.sql.expression import BooleanClauseList


class JSONAccessor:
    """Backend-agnostic JSON field access for SQLAlchemy operations.

    This class provides methods to extract JSON fields in a way that works
    across both SQLite and PostgreSQL backends.

    Example:
        # Instead of:
        func.json_extract(RawEvent.payload, "$.src_ip")

        # Use:
        JSONAccessor.get_field(RawEvent.payload, "src_ip", dialect_name)
    """

    @staticmethod
    def get_field(column: Column[Any], field: str, dialect_name: str) -> ColumnElement[Any]:
        """Extract a JSON field using the appropriate backend syntax.

        Args:
            column: The JSON column to extract from
            field: The field name to extract (without $.)
            dialect_name: The database dialect name ('sqlite' or 'postgresql')

        Returns:
            SQLAlchemy expression for the extracted field

        Example:
            # SQLite: json_extract(payload, '$.src_ip')
            # PostgreSQL: payload->>'src_ip'
        """
        if dialect_name == "postgresql":
            return column.op('->>')(field)
        else:
            return func.json_extract(column, f"$.{field}")

    @staticmethod
    def get_nested_field(column: Column[Any], path: str, dialect_name: str) -> ColumnElement[Any]:
        """Extract a nested JSON field using the appropriate backend syntax.

        Args:
            column: The JSON column to extract from
            path: The JSON path (e.g., "user.profile.name")
            dialect_name: The database dialect name ('sqlite' or 'postgresql')

        Returns:
            SQLAlchemy expression for the extracted field

        Example:
            # SQLite: json_extract(payload, '$.user.profile.name')
            # PostgreSQL: payload->'user'->'profile'->>'name'
        """
        if dialect_name == "postgresql":
            # Split path and build nested access
            parts = path.split(".")
            expr: ColumnElement[Any] = column
            for part in parts[:-1]:
                expr = expr.op('->')(part)
            return expr.op('->>')(parts[-1])
        else:
            return func.json_extract(column, f"$.{path}")

    @staticmethod
    def field_exists(column: Column[Any], field: str, dialect_name: str) -> BinaryExpression[bool]:
        """Check if a JSON field exists and is not null.

        Args:
            column: The JSON column to check
            field: The field name to check
            dialect_name: The database dialect name ('sqlite' or 'postgresql')

        Returns:
            SQLAlchemy boolean expression

        Example:
            # SQLite: json_extract(payload, '$.src_ip') IS NOT NULL
            # PostgreSQL: payload->>'src_ip' IS NOT NULL
        """
        field_expr = JSONAccessor.get_field(column, field, dialect_name)
        return field_expr.isnot(None)

    @staticmethod
    def field_not_empty(column: Column[Any], field: str, dialect_name: str) -> BooleanClauseList:
        """Check if a JSON field exists, is not null, and is not empty string.

        Args:
            column: The JSON column to check
            field: The field name to check
            dialect_name: The database dialect name ('sqlite' or 'postgresql')

        Returns:
            SQLAlchemy boolean expression

        Example:
            # SQLite: json_extract(payload, '$.src_ip') IS NOT NULL AND json_extract(payload, '$.src_ip') != ''
            # PostgreSQL: payload->>'src_ip' IS NOT NULL AND payload->>'src_ip' != ''
        """
        field_expr = JSONAccessor.get_field(column, field, dialect_name)
        return field_expr.isnot(None) & (field_expr != "")

    @staticmethod
    def field_equals(column: Column[Any], field: str, value: Any, dialect_name: str) -> BinaryExpression[bool]:
        """Check if a JSON field equals a specific value.

        Args:
            column: The JSON column to check
            field: The field name to check
            value: The value to compare against
            dialect_name: The database dialect name ('sqlite' or 'postgresql')

        Returns:
            SQLAlchemy boolean expression

        Example:
            # SQLite: json_extract(payload, '$.eventid') = 'cowrie.session.connect'
            # PostgreSQL: payload->>'eventid' = 'cowrie.session.connect'
        """
        field_expr = JSONAccessor.get_field(column, field, dialect_name)
        result: BinaryExpression[bool] = field_expr == value
        return result

    @staticmethod
    def field_like(column: Column[Any], field: str, pattern: str, dialect_name: str) -> BinaryExpression[bool]:
        """Check if a JSON field matches a LIKE pattern.

        Args:
            column: The JSON column to check
            field: The field name to check
            pattern: The LIKE pattern to match
            dialect_name: The database dialect name ('sqlite' or 'postgresql')

        Returns:
            SQLAlchemy boolean expression

        Example:
            # SQLite: json_extract(payload, '$.eventid') LIKE '%command%'
            # PostgreSQL: payload->>'eventid' LIKE '%command%'
        """
        field_expr = JSONAccessor.get_field(column, field, dialect_name)
        return field_expr.like(pattern)


def get_dialect_name(connection: Connection) -> str:
    """Get the database dialect name from a connection.

    Args:
        connection: SQLAlchemy connection object

    Returns:
        Dialect name ('sqlite' or 'postgresql')
    """
    return str(connection.dialect.name)


def get_dialect_name_from_engine(engine: Engine) -> str:
    """Get the database dialect name from an engine.

    Args:
        engine: SQLAlchemy engine object

    Returns:
        Dialect name ('sqlite' or 'postgresql')
    """
    return str(engine.dialect.name)


# Convenience functions for common operations
def json_field(column: Column[Any], field: str, dialect_name: str) -> ColumnElement[Any]:
    """Convenience function for JSON field extraction.

    Args:
        column: The JSON column to extract from
        field: The field name to extract
        dialect_name: The database dialect name

    Returns:
        SQLAlchemy expression for the extracted field
    """
    return JSONAccessor.get_field(column, field, dialect_name)


def json_field_exists(column: Column[Any], field: str, dialect_name: str) -> BinaryExpression[bool]:
    """Convenience function for JSON field existence check.

    Args:
        column: The JSON column to check
        field: The field name to check
        dialect_name: The database dialect name

    Returns:
        SQLAlchemy boolean expression
    """
    return JSONAccessor.field_exists(column, field, dialect_name)


def json_field_not_empty(column: Column[Any], field: str, dialect_name: str) -> BooleanClauseList:
    """Convenience function for JSON field not empty check.

    Args:
        column: The JSON column to check
        field: The field name to check
        dialect_name: The database dialect name

    Returns:
        SQLAlchemy boolean expression
    """
    return JSONAccessor.field_not_empty(column, field, dialect_name)


def json_field_equals(column: Column[Any], field: str, value: Any, dialect_name: str) -> BinaryExpression[bool]:
    """Convenience function for JSON field equality check.

    Args:
        column: The JSON column to check
        field: The field name to check
        value: The value to compare against
        dialect_name: The database dialect name

    Returns:
        SQLAlchemy boolean expression
    """
    return JSONAccessor.field_equals(column, field, value, dialect_name)


def json_field_like(column: Column[Any], field: str, pattern: str, dialect_name: str) -> BinaryExpression[bool]:
    """Convenience function for JSON field LIKE pattern check.

    Args:
        column: The JSON column to check
        field: The field name to check
        pattern: The LIKE pattern to match
        dialect_name: The database dialect name

    Returns:
        SQLAlchemy boolean expression
    """
    return JSONAccessor.field_like(column, field, pattern, dialect_name)
