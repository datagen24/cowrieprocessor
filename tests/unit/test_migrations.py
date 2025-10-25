"""Unit tests for database migration functions."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, inspect, text
from sqlalchemy.engine import Connection

from cowrieprocessor.db import create_engine_from_settings
from cowrieprocessor.db.migrations import (
    CURRENT_SCHEMA_VERSION,
    _column_exists,
    _get_schema_version,
    _is_generated_column,
    _safe_execute_sql,
    _set_schema_version,
    _table_exists,
    _upgrade_to_v2,
    _upgrade_to_v3,
    _upgrade_to_v4,
    _upgrade_to_v9,
    _upgrade_to_v11,
    apply_migrations,
    begin_connection,
)
from cowrieprocessor.settings import DatabaseSettings


def _make_engine(tmp_path: Path) -> Engine:
    """Create a test database engine with basic schema."""
    db_path = tmp_path / "test_migrations.sqlite"
    settings = DatabaseSettings(url=f"sqlite:///{db_path}")
    engine = create_engine_from_settings(settings)
    return engine


def _make_engine_with_base_schema(tmp_path: Path) -> Engine:
    """Create a test database engine with base schema applied."""
    engine = _make_engine(tmp_path)
    # Apply migrations up to version 10 (before v11)
    with begin_connection(engine) as conn:
        # Create basic tables that v11 depends on
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS schema_state (
                key VARCHAR(64) PRIMARY KEY,
                value TEXT NOT NULL
            )
        """
            )
        )
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS session_summaries (
                session_id VARCHAR(64) PRIMARY KEY,
                event_count INTEGER DEFAULT 0
            )
        """
            )
        )
        _set_schema_version(conn, 10)
    return engine


# ============================================================================
# Helper Function Tests
# ============================================================================


def test_table_exists_returns_true_for_existing_table(tmp_path: Path) -> None:
    """Test _table_exists returns True when table exists.

    Given: A database with a test table
    When: _table_exists is called with the table name
    Then: Returns True
    """
    engine = _make_engine(tmp_path)
    with begin_connection(engine) as conn:
        conn.execute(text("CREATE TABLE test_table (id INTEGER PRIMARY KEY)"))
        assert _table_exists(conn, "test_table") is True


def test_table_exists_returns_false_for_missing_table(tmp_path: Path) -> None:
    """Test _table_exists returns False when table does not exist.

    Given: A database without a specific table
    When: _table_exists is called with a non-existent table name
    Then: Returns False
    """
    engine = _make_engine(tmp_path)
    with begin_connection(engine) as conn:
        assert _table_exists(conn, "nonexistent_table") is False


def test_column_exists_returns_true_for_existing_column(tmp_path: Path) -> None:
    """Test _column_exists returns True when column exists.

    Given: A database table with specific columns
    When: _column_exists is called with an existing column name
    Then: Returns True
    """
    engine = _make_engine(tmp_path)
    with begin_connection(engine) as conn:
        conn.execute(text("CREATE TABLE test_table (id INTEGER, name TEXT)"))
        assert _column_exists(conn, "test_table", "name") is True


def test_column_exists_returns_false_for_missing_column(tmp_path: Path) -> None:
    """Test _column_exists returns False when column does not exist.

    Given: A database table without a specific column
    When: _column_exists is called with a non-existent column name
    Then: Returns False
    """
    engine = _make_engine(tmp_path)
    with begin_connection(engine) as conn:
        conn.execute(text("CREATE TABLE test_table (id INTEGER)"))
        assert _column_exists(conn, "test_table", "missing_column") is False


def test_column_exists_returns_false_for_missing_table(tmp_path: Path) -> None:
    """Test _column_exists returns False when table does not exist.

    Given: A database without a specific table
    When: _column_exists is called with a non-existent table
    Then: Returns False
    """
    engine = _make_engine(tmp_path)
    with begin_connection(engine) as conn:
        assert _column_exists(conn, "nonexistent_table", "any_column") is False


def test_get_schema_version_returns_zero_for_new_database(tmp_path: Path) -> None:
    """Test _get_schema_version returns 0 for uninitialized database.

    Given: A new database without schema_state table
    When: _get_schema_version is called
    Then: Returns 0
    """
    engine = _make_engine(tmp_path)
    with begin_connection(engine) as conn:
        # Create schema_state table but don't set version
        conn.execute(
            text(
                """
            CREATE TABLE schema_state (
                key VARCHAR(64) PRIMARY KEY,
                value TEXT NOT NULL
            )
        """
            )
        )
        version = _get_schema_version(conn)
        assert version == 0


def test_set_and_get_schema_version(tmp_path: Path) -> None:
    """Test setting and retrieving schema version.

    Given: A database with schema_state table
    When: Schema version is set to 5 and then retrieved
    Then: Returns the set version (5)
    """
    engine = _make_engine(tmp_path)
    with begin_connection(engine) as conn:
        conn.execute(
            text(
                """
            CREATE TABLE schema_state (
                key VARCHAR(64) PRIMARY KEY,
                value TEXT NOT NULL
            )
        """
            )
        )
        _set_schema_version(conn, 5)
        version = _get_schema_version(conn)
        assert version == 5


def test_set_schema_version_updates_existing_value(tmp_path: Path) -> None:
    """Test _set_schema_version updates existing version.

    Given: A database with schema version already set
    When: Schema version is updated to a new value
    Then: The new version is persisted correctly
    """
    engine = _make_engine(tmp_path)
    with begin_connection(engine) as conn:
        conn.execute(
            text(
                """
            CREATE TABLE schema_state (
                key VARCHAR(64) PRIMARY KEY,
                value TEXT NOT NULL
            )
        """
            )
        )
        _set_schema_version(conn, 3)
        _set_schema_version(conn, 7)
        version = _get_schema_version(conn)
        assert version == 7


def test_is_generated_column_returns_false_for_regular_column(tmp_path: Path) -> None:
    """Test _is_generated_column returns False for regular columns.

    Given: A table with a regular (non-generated) column
    When: _is_generated_column is called
    Then: Returns False
    """
    engine = _make_engine(tmp_path)
    with begin_connection(engine) as conn:
        conn.execute(text("CREATE TABLE test_table (id INTEGER, name TEXT)"))
        assert _is_generated_column(conn, "test_table", "name") is False


def test_is_generated_column_returns_false_for_missing_column(tmp_path: Path) -> None:
    """Test _is_generated_column returns False for non-existent columns.

    Given: A table without a specific column
    When: _is_generated_column is called with non-existent column
    Then: Returns False
    """
    engine = _make_engine(tmp_path)
    with begin_connection(engine) as conn:
        conn.execute(text("CREATE TABLE test_table (id INTEGER)"))
        assert _is_generated_column(conn, "test_table", "nonexistent") is False


def test_safe_execute_sql_executes_valid_sql(tmp_path: Path) -> None:
    """Test _safe_execute_sql successfully executes valid SQL.

    Given: A database connection
    When: _safe_execute_sql is called with valid SQL
    Then: SQL is executed and returns True
    """
    engine = _make_engine(tmp_path)
    with begin_connection(engine) as conn:
        result = _safe_execute_sql(conn, "CREATE TABLE test_table (id INTEGER PRIMARY KEY)", "Create test table")
        assert result is True
        assert _table_exists(conn, "test_table") is True


def test_safe_execute_sql_handles_invalid_sql(tmp_path: Path) -> None:
    """Test _safe_execute_sql handles invalid SQL gracefully.

    Given: A database connection
    When: _safe_execute_sql is called with invalid SQL
    Then: Returns False and logs error
    """
    engine = _make_engine(tmp_path)
    with begin_connection(engine) as conn:
        result = _safe_execute_sql(conn, "INVALID SQL STATEMENT", "Invalid SQL test")
        assert result is False


# ============================================================================
# Migration v11 Tests (SSH Key Intelligence)
# ============================================================================


def test_upgrade_to_v11_creates_ssh_key_intelligence_table(tmp_path: Path) -> None:
    """Test _upgrade_to_v11 creates ssh_key_intelligence table.

    Given: A database without SSH key tracking tables
    When: _upgrade_to_v11 is executed
    Then: ssh_key_intelligence table is created with correct schema
    """
    engine = _make_engine_with_base_schema(tmp_path)
    with begin_connection(engine) as conn:
        _upgrade_to_v11(conn)

        # Verify table exists
        assert _table_exists(conn, "ssh_key_intelligence") is True

        # Verify table structure
        inspector = inspect(conn)
        columns = {col["name"] for col in inspector.get_columns("ssh_key_intelligence")}
        expected_columns = {
            "id",
            "key_type",
            "key_data",
            "key_fingerprint",
            "key_hash",
            "key_comment",
            "first_seen",
            "last_seen",
            "total_attempts",
            "unique_sources",
            "unique_sessions",
            "key_bits",
            "key_full",
            "pattern_type",
            "target_path",
            "created_at",
            "updated_at",
        }
        assert columns == expected_columns


def test_upgrade_to_v11_creates_session_ssh_keys_table(tmp_path: Path) -> None:
    """Test _upgrade_to_v11 creates session_ssh_keys table.

    Given: A database without SSH key tracking tables
    When: _upgrade_to_v11 is executed
    Then: session_ssh_keys table is created with correct schema
    """
    engine = _make_engine_with_base_schema(tmp_path)
    with begin_connection(engine) as conn:
        _upgrade_to_v11(conn)

        # Verify table exists
        assert _table_exists(conn, "session_ssh_keys") is True

        # Verify table structure
        inspector = inspect(conn)
        columns = {col["name"] for col in inspector.get_columns("session_ssh_keys")}
        expected_columns = {
            "id",
            "session_id",
            "ssh_key_id",
            "command_text",
            "command_hash",
            "injection_method",
            "timestamp",
            "source_ip",
            "successful_injection",
        }
        assert columns == expected_columns


def test_upgrade_to_v11_creates_ssh_key_associations_table(tmp_path: Path) -> None:
    """Test _upgrade_to_v11 creates ssh_key_associations table.

    Given: A database without SSH key tracking tables
    When: _upgrade_to_v11 is executed
    Then: ssh_key_associations table is created with correct schema
    """
    engine = _make_engine_with_base_schema(tmp_path)
    with begin_connection(engine) as conn:
        _upgrade_to_v11(conn)

        # Verify table exists
        assert _table_exists(conn, "ssh_key_associations") is True

        # Verify table structure
        inspector = inspect(conn)
        columns = {col["name"] for col in inspector.get_columns("ssh_key_associations")}
        expected_columns = {
            "id",
            "key_id_1",
            "key_id_2",
            "co_occurrence_count",
            "first_seen",
            "last_seen",
            "same_session_count",
            "same_ip_count",
        }
        assert columns == expected_columns


def test_upgrade_to_v11_adds_columns_to_session_summaries(tmp_path: Path) -> None:
    """Test _upgrade_to_v11 adds SSH key columns to session_summaries.

    Given: A database with session_summaries table
    When: _upgrade_to_v11 is executed
    Then: ssh_key_injections and unique_ssh_keys columns are added
    """
    engine = _make_engine_with_base_schema(tmp_path)
    with begin_connection(engine) as conn:
        _upgrade_to_v11(conn)

        # Verify columns exist
        assert _column_exists(conn, "session_summaries", "ssh_key_injections") is True
        assert _column_exists(conn, "session_summaries", "unique_ssh_keys") is True


def test_upgrade_to_v11_creates_indexes_on_ssh_key_intelligence(tmp_path: Path) -> None:
    """Test _upgrade_to_v11 creates indexes on ssh_key_intelligence table.

    Given: A database without SSH key tracking tables
    When: _upgrade_to_v11 is executed
    Then: Indexes are created for key performance columns
    """
    engine = _make_engine_with_base_schema(tmp_path)
    with begin_connection(engine) as conn:
        _upgrade_to_v11(conn)

        # Verify indexes exist
        inspector = inspect(conn)
        indexes = {idx["name"] for idx in inspector.get_indexes("ssh_key_intelligence")}
        expected_indexes = {
            "ix_ssh_key_fingerprint",
            "ix_ssh_key_type",
            "ix_ssh_key_timeline",
            "ix_ssh_key_attempts",
            "ix_ssh_key_sources",
            "ix_ssh_key_sessions",
        }
        assert expected_indexes.issubset(indexes)


def test_upgrade_to_v11_creates_indexes_on_session_ssh_keys(tmp_path: Path) -> None:
    """Test _upgrade_to_v11 creates indexes on session_ssh_keys table.

    Given: A database without SSH key tracking tables
    When: _upgrade_to_v11 is executed
    Then: Indexes are created for key performance columns
    """
    engine = _make_engine_with_base_schema(tmp_path)
    with begin_connection(engine) as conn:
        _upgrade_to_v11(conn)

        # Verify indexes exist
        inspector = inspect(conn)
        indexes = {idx["name"] for idx in inspector.get_indexes("session_ssh_keys")}
        expected_indexes = {
            "ix_session_ssh_keys_session",
            "ix_session_ssh_keys_timestamp",
            "ix_session_ssh_keys_ssh_key",
            "ix_session_ssh_keys_source_ip",
        }
        assert expected_indexes.issubset(indexes)


def test_upgrade_to_v11_is_idempotent(tmp_path: Path) -> None:
    """Test _upgrade_to_v11 can be run multiple times safely.

    Given: A database with v11 migration already applied
    When: _upgrade_to_v11 is executed again
    Then: No errors occur and schema remains correct
    """
    engine = _make_engine_with_base_schema(tmp_path)
    with begin_connection(engine) as conn:
        # Run migration twice
        _upgrade_to_v11(conn)
        _upgrade_to_v11(conn)

        # Verify tables still exist and are correct
        assert _table_exists(conn, "ssh_key_intelligence") is True
        assert _table_exists(conn, "session_ssh_keys") is True
        assert _table_exists(conn, "ssh_key_associations") is True
        assert _column_exists(conn, "session_summaries", "ssh_key_injections") is True


# ============================================================================
# apply_migrations() Tests
# ============================================================================


def test_apply_migrations_creates_schema(tmp_path: Path) -> None:
    """Test apply_migrations creates complete schema for new database.

    Given: A new empty database
    When: apply_migrations is called
    Then: Schema is created at current version
    """
    engine = _make_engine(tmp_path)
    version = apply_migrations(engine)

    # Verify version is set to current
    assert version == CURRENT_SCHEMA_VERSION

    # Verify key tables exist
    with begin_connection(engine) as conn:
        assert _table_exists(conn, "schema_state") is True
        assert _table_exists(conn, "raw_events") is True
        assert _table_exists(conn, "session_summaries") is True


def test_apply_migrations_upgrades_from_v10_to_current(tmp_path: Path) -> None:
    """Test apply_migrations upgrades from v10 to current version.

    Given: A database at schema version 10
    When: apply_migrations is called
    Then: Database is upgraded to current version
    """
    engine = _make_engine_with_base_schema(tmp_path)

    # Verify we're at v10
    with begin_connection(engine) as conn:
        assert _get_schema_version(conn) == 10

    # Apply migrations
    version = apply_migrations(engine)

    # Verify we're now at current version
    assert version == CURRENT_SCHEMA_VERSION

    # Verify v11+ features exist
    with begin_connection(engine) as conn:
        assert _table_exists(conn, "ssh_key_intelligence") is True


def test_apply_migrations_is_idempotent(tmp_path: Path) -> None:
    """Test apply_migrations can be called multiple times safely.

    Given: A database with migrations already applied
    When: apply_migrations is called again
    Then: No errors occur and version remains current
    """
    engine = _make_engine(tmp_path)

    # Apply migrations twice
    version1 = apply_migrations(engine)
    version2 = apply_migrations(engine)

    # Both should return current version
    assert version1 == CURRENT_SCHEMA_VERSION
    assert version2 == CURRENT_SCHEMA_VERSION


# ============================================================================
# Migration v9 Tests (Longtail Analysis)
# ============================================================================


def _make_engine_with_v8_schema(tmp_path: Path) -> Engine:
    """Create a test database engine with schema up to version 8."""
    engine = _make_engine(tmp_path)
    with begin_connection(engine) as conn:
        # Create basic tables that v9 depends on
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS schema_state (
                key VARCHAR(64) PRIMARY KEY,
                value TEXT NOT NULL
            )
        """
            )
        )
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS raw_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL
            )
        """
            )
        )
        _set_schema_version(conn, 8)
    return engine


def test_upgrade_to_v9_creates_longtail_analysis_table(tmp_path: Path) -> None:
    """Test _upgrade_to_v9 creates longtail_analysis table.

    Given: A database at version 8 without longtail tables
    When: _upgrade_to_v9 is executed
    Then: longtail_analysis table is created with correct schema
    """
    engine = _make_engine_with_v8_schema(tmp_path)
    with begin_connection(engine) as conn:
        _upgrade_to_v9(conn)

        # Verify table exists
        assert _table_exists(conn, "longtail_analysis") is True

        # Verify key columns exist
        inspector = inspect(conn)
        columns = {col["name"] for col in inspector.get_columns("longtail_analysis")}
        expected_columns = {
            "id",
            "analysis_time",
            "window_start",
            "window_end",
            "lookback_days",
            "confidence_score",
            "total_events_analyzed",
            "rare_command_count",
            "anomalous_sequence_count",
            "outlier_session_count",
            "emerging_pattern_count",
            "high_entropy_payload_count",
            "analysis_results",
            "statistical_summary",
            "recommendation",
            "analysis_duration_seconds",
            "memory_usage_mb",
            "data_quality_score",
            "enrichment_coverage",
            "created_at",
        }
        assert columns == expected_columns


def test_upgrade_to_v9_creates_longtail_detections_table(tmp_path: Path) -> None:
    """Test _upgrade_to_v9 creates longtail_detections table.

    Given: A database at version 8 without longtail tables
    When: _upgrade_to_v9 is executed
    Then: longtail_detections table is created with correct schema
    """
    engine = _make_engine_with_v8_schema(tmp_path)
    with begin_connection(engine) as conn:
        _upgrade_to_v9(conn)

        # Verify table exists
        assert _table_exists(conn, "longtail_detections") is True

        # Verify key columns exist
        inspector = inspect(conn)
        columns = {col["name"] for col in inspector.get_columns("longtail_detections")}
        expected_columns = {
            "id",
            "analysis_id",
            "detection_type",
            "session_id",
            "event_id",
            "detection_data",
            "confidence_score",
            "severity_score",
            "timestamp",
            "source_ip",
            "created_at",
        }
        assert columns == expected_columns


def test_upgrade_to_v9_creates_indexes_on_longtail_analysis(tmp_path: Path) -> None:
    """Test _upgrade_to_v9 creates indexes on longtail_analysis table.

    Given: A database at version 8
    When: _upgrade_to_v9 is executed
    Then: Performance indexes are created
    """
    engine = _make_engine_with_v8_schema(tmp_path)
    with begin_connection(engine) as conn:
        _upgrade_to_v9(conn)

        # Verify indexes exist
        inspector = inspect(conn)
        indexes = {idx["name"] for idx in inspector.get_indexes("longtail_analysis")}
        expected_indexes = {
            "ix_longtail_analysis_time",
            "ix_longtail_analysis_window",
            "ix_longtail_analysis_confidence",
            "ix_longtail_analysis_created",
        }
        assert expected_indexes.issubset(indexes)


def test_upgrade_to_v9_creates_indexes_on_longtail_detections(tmp_path: Path) -> None:
    """Test _upgrade_to_v9 creates indexes on longtail_detections table.

    Given: A database at version 8
    When: _upgrade_to_v9 is executed
    Then: Performance indexes are created
    """
    engine = _make_engine_with_v8_schema(tmp_path)
    with begin_connection(engine) as conn:
        _upgrade_to_v9(conn)

        # Verify indexes exist
        inspector = inspect(conn)
        indexes = {idx["name"] for idx in inspector.get_indexes("longtail_detections")}
        expected_indexes = {
            "ix_longtail_detections_analysis",
            "ix_longtail_detections_type",
            "ix_longtail_detections_session",
            "ix_longtail_detections_timestamp",
            "ix_longtail_detections_created",
        }
        assert expected_indexes.issubset(indexes)


def test_upgrade_to_v9_is_idempotent(tmp_path: Path) -> None:
    """Test _upgrade_to_v9 can be run multiple times safely.

    Given: A database with v9 migration already applied
    When: _upgrade_to_v9 is executed again
    Then: No errors occur and schema remains correct
    """
    engine = _make_engine_with_v8_schema(tmp_path)
    with begin_connection(engine) as conn:
        # Run migration twice
        _upgrade_to_v9(conn)
        _upgrade_to_v9(conn)

        # Verify tables still exist and are correct
        assert _table_exists(conn, "longtail_analysis") is True
        assert _table_exists(conn, "longtail_detections") is True


def test_upgrade_to_v9_skips_pgvector_tables_on_sqlite(tmp_path: Path) -> None:
    """Test _upgrade_to_v9 skips PostgreSQL-specific pgvector tables on SQLite.

    Given: A SQLite database at version 8
    When: _upgrade_to_v9 is executed
    Then: pgvector tables are not created (PostgreSQL-only feature)
    """
    engine = _make_engine_with_v8_schema(tmp_path)
    with begin_connection(engine) as conn:
        _upgrade_to_v9(conn)

        # Verify pgvector tables don't exist (SQLite doesn't support pgvector)
        assert _table_exists(conn, "command_sequence_vectors") is False
        assert _table_exists(conn, "behavioral_vectors") is False


# ============================================================================
# Smaller Migration Tests (v2, v3, v4)
# ============================================================================


def _make_engine_with_v1_schema(tmp_path: Path) -> Engine:
    """Create a test database engine with schema at version 1."""
    engine = _make_engine(tmp_path)
    with begin_connection(engine) as conn:
        # Create minimal tables for v2+ migrations
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS schema_state (
                key VARCHAR(64) PRIMARY KEY,
                value TEXT NOT NULL
            )
        """
            )
        )
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS raw_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL,
                source TEXT,
                source_inode INTEGER,
                source_offset INTEGER
            )
        """
            )
        )
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS session_summaries (
                session_id VARCHAR(64) PRIMARY KEY,
                event_count INTEGER DEFAULT 0
            )
        """
            )
        )
        _set_schema_version(conn, 1)
    return engine


def test_upgrade_to_v2_adds_source_generation_column(tmp_path: Path) -> None:
    """Test _upgrade_to_v2 adds source_generation column to raw_events.

    Given: A database at version 1 without source_generation column
    When: _upgrade_to_v2 is executed
    Then: source_generation column is added
    """
    engine = _make_engine_with_v1_schema(tmp_path)
    with begin_connection(engine) as conn:
        _upgrade_to_v2(conn)

        # Verify column exists
        assert _column_exists(conn, "raw_events", "source_generation") is True


def test_upgrade_to_v2_creates_unique_index(tmp_path: Path) -> None:
    """Test _upgrade_to_v2 creates unique index on raw_events.

    Given: A database at version 1
    When: _upgrade_to_v2 is executed
    Then: Unique index is created
    """
    engine = _make_engine_with_v1_schema(tmp_path)
    with begin_connection(engine) as conn:
        _upgrade_to_v2(conn)

        # Verify index exists
        inspector = inspect(conn)
        indexes = {idx["name"] for idx in inspector.get_indexes("raw_events")}
        assert "uq_raw_events_source_gen" in indexes


def test_upgrade_to_v2_is_idempotent(tmp_path: Path) -> None:
    """Test _upgrade_to_v2 can be run multiple times safely.

    Given: A database with v2 migration already applied
    When: _upgrade_to_v2 is executed again
    Then: No errors occur
    """
    engine = _make_engine_with_v1_schema(tmp_path)
    with begin_connection(engine) as conn:
        _upgrade_to_v2(conn)
        _upgrade_to_v2(conn)  # Should not fail

        assert _column_exists(conn, "raw_events", "source_generation") is True


def test_upgrade_to_v3_adds_enrichment_column_sqlite(tmp_path: Path) -> None:
    """Test _upgrade_to_v3 adds enrichment column to session_summaries (SQLite).

    Given: A database at version 2 without enrichment column
    When: _upgrade_to_v3 is executed
    Then: enrichment column is added with JSON type
    """
    engine = _make_engine_with_v1_schema(tmp_path)
    with begin_connection(engine) as conn:
        _upgrade_to_v3(conn)

        # Verify column exists
        assert _column_exists(conn, "session_summaries", "enrichment") is True


def test_upgrade_to_v3_is_idempotent(tmp_path: Path) -> None:
    """Test _upgrade_to_v3 can be run multiple times safely.

    Given: A database with v3 migration already applied
    When: _upgrade_to_v3 is executed again
    Then: No errors occur (early return)
    """
    engine = _make_engine_with_v1_schema(tmp_path)
    with begin_connection(engine) as conn:
        _upgrade_to_v3(conn)
        _upgrade_to_v3(conn)  # Should return early

        assert _column_exists(conn, "session_summaries", "enrichment") is True


def test_upgrade_to_v4_creates_files_table(tmp_path: Path) -> None:
    """Test _upgrade_to_v4 creates files table.

    Given: A database at version 3 without files table
    When: _upgrade_to_v4 is executed
    Then: files table is created
    """
    engine = _make_engine_with_v1_schema(tmp_path)
    with begin_connection(engine) as conn:
        _upgrade_to_v4(conn)

        # Verify table exists
        assert _table_exists(conn, "files") is True


def test_upgrade_to_v4_is_idempotent(tmp_path: Path) -> None:
    """Test _upgrade_to_v4 can be run multiple times safely.

    Given: A database with v4 migration already applied
    When: _upgrade_to_v4 is executed again
    Then: No errors occur (early return)
    """
    engine = _make_engine_with_v1_schema(tmp_path)
    with begin_connection(engine) as conn:
        _upgrade_to_v4(conn)
        _upgrade_to_v4(conn)  # Should return early

        assert _table_exists(conn, "files") is True
