"""Unit tests for enhanced DLQ migration."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from sqlalchemy.engine import Connection

from cowrieprocessor.db.enhanced_dlq_migration import downgrade_from_enhanced_dlq, upgrade_to_enhanced_dlq


class TestEnhancedDLQMigration:
    """Test cases for enhanced DLQ migration functions."""

    def test_upgrade_to_enhanced_dlq_with_postgresql(self) -> None:
        """Test upgrade_to_enhanced_dlq with PostgreSQL database."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'

        with patch('builtins.print') as mock_print:
            upgrade_to_enhanced_dlq(mock_connection)

            # Should call execute multiple times for different SQL statements
            assert mock_connection.execute.call_count >= 10
            mock_print.assert_any_call("Upgrading to enhanced DLQ models...")
            mock_print.assert_any_call("✅ Enhanced DLQ migration completed successfully")

    def test_upgrade_to_enhanced_dlq_with_sqlite(self) -> None:
        """Test upgrade_to_enhanced_dlq skips non-PostgreSQL databases."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'sqlite'

        with patch('builtins.print') as mock_print:
            upgrade_to_enhanced_dlq(mock_connection)

            # Should not execute any SQL statements
            mock_connection.execute.assert_not_called()
            mock_print.assert_any_call("Skipping enhanced DLQ migration for sqlite - PostgreSQL only")

    def test_upgrade_to_enhanced_dlq_with_other_database(self) -> None:
        """Test upgrade_to_enhanced_dlq skips other database types."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'mysql'

        with patch('builtins.print') as mock_print:
            upgrade_to_enhanced_dlq(mock_connection)

            # Should not execute any SQL statements
            mock_connection.execute.assert_not_called()
            mock_print.assert_any_call("Skipping enhanced DLQ migration for mysql - PostgreSQL only")

    def test_downgrade_from_enhanced_dlq_with_postgresql(self) -> None:
        """Test downgrade_from_enhanced_dlq with PostgreSQL database."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'

        with patch('builtins.print') as mock_print:
            downgrade_from_enhanced_dlq(mock_connection)

            # Should call execute multiple times for different SQL statements
            assert mock_connection.execute.call_count >= 10
            mock_print.assert_any_call("Downgrading from enhanced DLQ models...")
            mock_print.assert_any_call("✅ Enhanced DLQ downgrade completed successfully")

    def test_downgrade_from_enhanced_dlq_with_sqlite(self) -> None:
        """Test downgrade_from_enhanced_dlq skips non-PostgreSQL databases."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'sqlite'

        with patch('builtins.print') as mock_print:
            downgrade_from_enhanced_dlq(mock_connection)

            # Should not execute any SQL statements
            mock_connection.execute.assert_not_called()
            mock_print.assert_any_call("Skipping enhanced DLQ downgrade for sqlite - PostgreSQL only")

    def test_upgrade_creates_all_expected_sql_objects(self) -> None:
        """Test upgrade_to_enhanced_dlq creates all expected database objects."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'

        # Track all execute calls
        execute_calls = []

        def mock_execute(sql_text):
            execute_calls.append(str(sql_text))

        mock_connection.execute.side_effect = mock_execute

        with patch('builtins.print'):
            upgrade_to_enhanced_dlq(mock_connection)

        # Verify all major SQL components are present
        sql_text = '\n'.join(execute_calls)

        # Check for table alterations
        assert 'ALTER TABLE dead_letter_events' in sql_text

        # Check for new columns
        assert 'payload_checksum' in sql_text
        assert 'retry_count' in sql_text
        assert 'error_history' in sql_text
        assert 'processing_attempts' in sql_text
        assert 'resolution_method' in sql_text
        assert 'idempotency_key' in sql_text
        assert 'processing_lock' in sql_text
        assert 'lock_expires_at' in sql_text
        assert 'priority' in sql_text
        assert 'classification' in sql_text
        assert 'updated_at' in sql_text
        assert 'last_processed_at' in sql_text

        # Check for indexes
        assert 'CREATE INDEX IF NOT EXISTS' in sql_text
        assert 'ix_dead_letter_events_payload_checksum' in sql_text
        assert 'ix_dead_letter_events_retry_count' in sql_text
        assert 'ix_dead_letter_events_idempotency_key' in sql_text
        assert 'ix_dead_letter_events_processing_lock' in sql_text

        # Check for constraints
        assert 'ADD CONSTRAINT IF NOT EXISTS' in sql_text
        assert 'ck_retry_count_positive' in sql_text
        assert 'ck_priority_range' in sql_text
        assert 'uq_idempotency_key' in sql_text

        # Check for new tables
        assert 'CREATE TABLE IF NOT EXISTS dlq_processing_metrics' in sql_text
        assert 'CREATE TABLE IF NOT EXISTS dlq_circuit_breaker_state' in sql_text

        # Check for view
        assert 'CREATE OR REPLACE VIEW dlq_health' in sql_text

        # Check for functions
        assert 'CREATE OR REPLACE FUNCTION update_updated_at_column' in sql_text

        # Check for triggers
        assert 'CREATE TRIGGER update_dead_letter_events_updated_at' in sql_text
        assert 'CREATE TRIGGER update_circuit_breaker_updated_at' in sql_text

        # Check for data migration
        assert 'UPDATE dead_letter_events' in sql_text
        assert 'payload_checksum = encode(digest(payload::TEXT' in sql_text
        assert 'idempotency_key = encode(digest' in sql_text

    def test_downgrade_removes_all_expected_sql_objects(self) -> None:
        """Test downgrade_from_enhanced_dlq removes all expected database objects."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'

        # Track all execute calls
        execute_calls = []

        def mock_execute(sql_text):
            execute_calls.append(str(sql_text))

        mock_connection.execute.side_effect = mock_execute

        with patch('builtins.print'):
            downgrade_from_enhanced_dlq(mock_connection)

        # Verify all major SQL components are removed
        sql_text = '\n'.join(execute_calls)

        # Check for view removal
        assert 'DROP VIEW IF EXISTS dlq_health' in sql_text

        # Check for trigger removal
        assert 'DROP TRIGGER IF EXISTS update_dead_letter_events_updated_at' in sql_text
        assert 'DROP TRIGGER IF EXISTS update_circuit_breaker_updated_at' in sql_text

        # Check for function removal
        assert 'DROP FUNCTION IF EXISTS update_updated_at_column' in sql_text

        # Check for table removal
        assert 'DROP TABLE IF EXISTS dlq_circuit_breaker_state' in sql_text
        assert 'DROP TABLE IF EXISTS dlq_processing_metrics' in sql_text

        # Check for index removal
        assert 'DROP INDEX IF EXISTS ix_dead_letter_events_payload_checksum' in sql_text
        assert 'DROP INDEX IF EXISTS ix_dead_letter_events_retry_count' in sql_text
        assert 'DROP INDEX IF EXISTS ix_dead_letter_events_idempotency_key' in sql_text

        # Check for constraint removal
        assert 'DROP CONSTRAINT IF EXISTS ck_retry_count_positive' in sql_text
        assert 'DROP CONSTRAINT IF EXISTS ck_priority_range' in sql_text
        assert 'DROP CONSTRAINT IF EXISTS uq_idempotency_key' in sql_text

        # Check for column removal
        assert 'DROP COLUMN IF EXISTS payload_checksum' in sql_text
        assert 'DROP COLUMN IF EXISTS retry_count' in sql_text
        assert 'DROP COLUMN IF EXISTS error_history' in sql_text
        assert 'DROP COLUMN IF EXISTS processing_attempts' in sql_text
        assert 'DROP COLUMN IF EXISTS resolution_method' in sql_text
        assert 'DROP COLUMN IF EXISTS idempotency_key' in sql_text
        assert 'DROP COLUMN IF EXISTS processing_lock' in sql_text
        assert 'DROP COLUMN IF EXISTS lock_expires_at' in sql_text
        assert 'DROP COLUMN IF EXISTS priority' in sql_text
        assert 'DROP COLUMN IF EXISTS classification' in sql_text
        assert 'DROP COLUMN IF EXISTS updated_at' in sql_text
        assert 'DROP COLUMN IF EXISTS last_processed_at' in sql_text

    def test_upgrade_handles_execution_errors_gracefully(self) -> None:
        """Test upgrade_to_enhanced_dlq handles SQL execution errors."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'
        mock_connection.execute.side_effect = Exception("SQL execution failed")

        with patch('builtins.print'), pytest.raises(Exception, match="SQL execution failed"):
            upgrade_to_enhanced_dlq(mock_connection)

    def test_downgrade_handles_execution_errors_gracefully(self) -> None:
        """Test downgrade_from_enhanced_dlq handles SQL execution errors."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'
        mock_connection.execute.side_effect = Exception("SQL execution failed")

        with patch('builtins.print'), pytest.raises(Exception, match="SQL execution failed"):
            downgrade_from_enhanced_dlq(mock_connection)

    def test_upgrade_creates_processing_metrics_table_with_correct_columns(self) -> None:
        """Test upgrade creates processing metrics table with all required columns."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'

        execute_calls = []

        def mock_execute(sql_text):
            execute_calls.append(str(sql_text))

        mock_connection.execute.side_effect = mock_execute

        with patch('builtins.print'):
            upgrade_to_enhanced_dlq(mock_connection)

        sql_text = '\n'.join(execute_calls)

        # Check for processing metrics table structure
        assert 'CREATE TABLE IF NOT EXISTS dlq_processing_metrics' in sql_text
        assert 'id SERIAL PRIMARY KEY' in sql_text
        assert 'processing_session_id VARCHAR(64)' in sql_text
        assert 'processing_method VARCHAR(32)' in sql_text
        assert 'batch_size INTEGER' in sql_text
        assert 'processed_count INTEGER' in sql_text
        assert 'repaired_count INTEGER' in sql_text
        assert 'failed_count INTEGER' in sql_text
        assert 'skipped_count INTEGER' in sql_text
        assert 'processing_duration_ms INTEGER' in sql_text
        assert 'avg_processing_time_ms INTEGER' in sql_text
        assert 'peak_memory_mb INTEGER' in sql_text
        assert 'circuit_breaker_triggered BOOLEAN' in sql_text
        assert 'rate_limit_hits INTEGER' in sql_text
        assert 'lock_timeout_count INTEGER' in sql_text
        assert 'started_at TIMESTAMP WITH TIME ZONE' in sql_text
        assert 'completed_at TIMESTAMP WITH TIME ZONE' in sql_text

    def test_upgrade_creates_circuit_breaker_table_with_correct_structure(self) -> None:
        """Test upgrade creates circuit breaker table with all required columns."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'

        execute_calls = []

        def mock_execute(sql_text):
            execute_calls.append(str(sql_text))

        mock_connection.execute.side_effect = mock_execute

        with patch('builtins.print'):
            upgrade_to_enhanced_dlq(mock_connection)

        sql_text = '\n'.join(execute_calls)

        # Check for circuit breaker table structure
        assert 'CREATE TABLE IF NOT EXISTS dlq_circuit_breaker_state' in sql_text
        assert 'id SERIAL PRIMARY KEY' in sql_text
        assert 'breaker_name VARCHAR(64)' in sql_text
        assert 'state VARCHAR(16)' in sql_text
        assert 'failure_count INTEGER' in sql_text
        assert 'last_failure_time TIMESTAMP WITH TIME ZONE' in sql_text
        assert 'next_attempt_time TIMESTAMP WITH TIME ZONE' in sql_text
        assert 'failure_threshold INTEGER' in sql_text
        assert 'timeout_seconds INTEGER' in sql_text
        assert 'created_at TIMESTAMP WITH TIME ZONE' in sql_text
        assert 'updated_at TIMESTAMP WITH TIME ZONE' in sql_text

    def test_upgrade_creates_health_view_with_correct_aggregations(self) -> None:
        """Test upgrade creates health view with correct aggregations."""
        mock_connection = Mock(spec=Connection)
        mock_connection.dialect = Mock()
        mock_connection.dialect.name = 'postgresql'

        execute_calls = []

        def mock_execute(sql_text):
            execute_calls.append(str(sql_text))

        mock_connection.execute.side_effect = mock_execute

        with patch('builtins.print'):
            upgrade_to_enhanced_dlq(mock_connection)

        sql_text = '\n'.join(execute_calls)

        # Check for health view structure
        assert 'CREATE OR REPLACE VIEW dlq_health' in sql_text
        assert 'pending_events' in sql_text
        assert 'processed_events' in sql_text
        assert 'avg_resolution_time_seconds' in sql_text
        assert 'oldest_unresolved_event' in sql_text
        assert 'high_retry_events' in sql_text
        assert 'locked_events' in sql_text
        assert 'malicious_events' in sql_text
        assert 'high_priority_events' in sql_text

    def test_migration_functions_have_correct_signatures(self) -> None:
        """Test migration functions have correct parameter types."""
        # Test upgrade function signature
        import inspect

        from cowrieprocessor.db.enhanced_dlq_migration import upgrade_to_enhanced_dlq

        sig = inspect.signature(upgrade_to_enhanced_dlq)
        assert 'connection' in sig.parameters
        assert 'Connection' in str(sig.parameters['connection'].annotation)

        # Test downgrade function signature
        from cowrieprocessor.db.enhanced_dlq_migration import downgrade_from_enhanced_dlq

        sig = inspect.signature(downgrade_from_enhanced_dlq)
        assert 'connection' in sig.parameters
        assert 'Connection' in str(sig.parameters['connection'].annotation)
