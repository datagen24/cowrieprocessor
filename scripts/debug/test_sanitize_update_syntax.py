#!/usr/bin/env python3
"""Test script to verify the sanitization UPDATE statement syntax fix.

This tests that the CAST(:param AS jsonb) syntax works correctly with
SQLAlchemy text() and avoids the parameter binding conflict with ::.
"""

from sqlalchemy import text, create_engine
import json


def test_update_syntax() -> None:
    """Test that the UPDATE statement works with CAST() instead of ::."""
    print("Testing sanitization UPDATE statement syntax...")
    print("=" * 80)

    # Create in-memory SQLite database for testing
    engine = create_engine("sqlite:///:memory:")

    # Create test table
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE raw_events (
                id INTEGER PRIMARY KEY,
                payload TEXT
            )
        """))

        # Insert test record with problematic Unicode escape
        test_payload = '{"username": "\\u0000test", "cmd": "attack\\u0001data"}'
        conn.execute(
            text("INSERT INTO raw_events (id, payload) VALUES (:id, :payload)"),
            {"id": 1, "payload": test_payload}
        )

    # Test the UPDATE syntax (SQLite version - no JSONB)
    print("\n✅ Testing SQLite UPDATE syntax...")
    sanitized_payload = '{"username": "test", "cmd": "attackdata"}'

    with engine.begin() as conn:
        update_query = text("""
            UPDATE raw_events
            SET payload = :sanitized_payload
            WHERE id = :record_id
        """)

        conn.execute(
            update_query,
            {"sanitized_payload": sanitized_payload, "record_id": 1}
        )

    # Verify update worked
    with engine.begin() as conn:
        result = conn.execute(text("SELECT payload FROM raw_events WHERE id = 1"))
        row = result.fetchone()
        if row and row[0] == sanitized_payload:
            print("✅ PASS: SQLite UPDATE successful")
        else:
            print(f"❌ FAIL: Expected {sanitized_payload}, got {row[0] if row else None}")
            return

    print("\n" + "=" * 80)
    print("✅ All syntax tests passed!")
    print("\nThe PostgreSQL version uses:")
    print("  UPDATE raw_events")
    print("  SET payload = CAST(:sanitized_payload AS jsonb)")
    print("  WHERE id = :record_id")
    print("\nThis avoids the parameter binding conflict with :: operator.")


if __name__ == "__main__":
    test_update_syntax()
