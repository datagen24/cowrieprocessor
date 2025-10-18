"""Tests for Unicode cleanup utility in cowrie_db."""

from unittest.mock import Mock, patch

import pytest

from cowrieprocessor.cli.cowrie_db import CowrieDatabase


class TestUnicodeCleanupUtility:
    """Test cases for Unicode cleanup utility."""

    def setup_method(self):
        """Set up test fixtures."""
        self.db = CowrieDatabase("sqlite:///:memory:")
        self.db._get_engine = Mock()
        self.db._table_exists = Mock(return_value=True)

        # Mock engine and connection with proper context manager setup
        self.mock_engine = Mock()
        self.mock_connection = Mock()

        # Set up context managers properly
        connect_context = Mock()
        connect_context.__enter__ = Mock(return_value=self.mock_connection)
        connect_context.__exit__ = Mock(return_value=None)
        self.mock_engine.connect.return_value = connect_context

        begin_context = Mock()
        begin_context.__enter__ = Mock(return_value=self.mock_connection)
        begin_context.__exit__ = Mock(return_value=None)
        self.mock_engine.begin.return_value = begin_context

        self.db._get_engine.return_value = self.mock_engine

    def test_sanitize_unicode_in_database_dry_run(self) -> None:
        """Test dry run functionality."""
        # Mock database records with Unicode control characters
        mock_records = [
            Mock(id=1, payload_text='{"eventid": "cowrie.session.connect", "message": "hello\x00world"}'),
            Mock(id=2, payload_text='{"eventid": "cowrie.session.command", "input": "normal command"}'),
            Mock(id=3, payload_text='{"eventid": "cowrie.session.file_download", "filename": "file\x16name.txt"}'),
        ]

        self.mock_connection.execute.return_value.fetchall.return_value = mock_records

        # Run dry run
        result = self.db.sanitize_unicode_in_database(dry_run=True, limit=3)

        # Verify results
        assert result['dry_run'] is True
        assert result['records_processed'] == 3
        assert result['records_updated'] == 2  # Records 1 and 3 have control characters
        assert result['records_skipped'] == 1  # Record 2 is clean
        assert result['errors'] == 0
        assert result['batches_processed'] == 1

        # Verify no database updates were made in dry run
        self.mock_connection.execute.assert_called_once()
        # Should only be called once for the SELECT query, not for any UPDATE queries

    def test_sanitize_unicode_in_database_actual_run(self) -> None:
        """Test actual sanitization run."""
        # Mock database records with Unicode control characters
        mock_records = [
            Mock(id=1, payload_text='{"eventid": "cowrie.session.connect", "message": "hello\x00world"}'),
            Mock(id=2, payload_text='{"eventid": "cowrie.session.command", "input": "normal command"}'),
        ]

        self.mock_connection.execute.return_value.fetchall.return_value = mock_records

        # Run actual sanitization
        result = self.db.sanitize_unicode_in_database(dry_run=False, limit=2)

        # Verify results
        assert result['dry_run'] is False
        assert result['records_processed'] == 2
        assert result['records_updated'] == 1  # Record 1 has control characters
        assert result['records_skipped'] == 1  # Record 2 is clean
        assert result['errors'] == 0

        # Verify database updates were made
        # Should be called twice: once for SELECT, once for UPDATE
        assert self.mock_connection.execute.call_count == 2

    def test_sanitize_unicode_in_database_no_table(self) -> None:
        """Test error handling when raw_events table doesn't exist."""
        self.db._table_exists.return_value = False

        with pytest.raises(Exception, match="Raw events table does not exist"):
            self.db.sanitize_unicode_in_database()

    def test_sanitize_unicode_in_database_batch_processing(self) -> None:
        """Test batch processing with multiple batches."""
        # Mock first batch
        mock_records_batch1 = [
            Mock(id=1, payload_text='{"eventid": "test", "message": "hello\x00world"}'),
            Mock(id=2, payload_text='{"eventid": "test", "message": "normal"}'),
        ]

        # Mock second batch
        mock_records_batch2 = [
            Mock(id=3, payload_text='{"eventid": "test", "message": "another\x16message"}'),
        ]

        # Mock empty batch (end of data)
        mock_records_batch3 = []

        # Configure mock to return different results for each call
        self.mock_connection.execute.return_value.fetchall.side_effect = [
            mock_records_batch1,
            mock_records_batch2,
            mock_records_batch3,
        ]

        # Run with small batch size to force multiple batches
        result = self.db.sanitize_unicode_in_database(dry_run=True, batch_size=2)

        # Verify results
        assert result['records_processed'] == 3
        assert result['records_updated'] == 2  # Records 1 and 3 have control characters
        assert result['records_skipped'] == 1  # Record 2 is clean
        assert result['batches_processed'] == 2  # Two batches processed

    def test_sanitize_unicode_in_database_limit(self) -> None:
        """Test limit functionality."""
        mock_records = [
            Mock(id=1, payload_text='{"eventid": "test", "message": "hello\x00world"}'),
            Mock(id=2, payload_text='{"eventid": "test", "message": "normal"}'),
            Mock(id=3, payload_text='{"eventid": "test", "message": "another\x16message"}'),
        ]

        # Mock the query to return only the limited number of records
        def mock_execute(query, params=None):
            # Return only the first 2 records when limit is applied
            if params and params.get('batch_size', 0) > 0:
                return Mock(fetchall=Mock(return_value=mock_records[:2]))
            return Mock(fetchall=Mock(return_value=mock_records))

        self.mock_connection.execute.side_effect = mock_execute

        # Run with limit
        result = self.db.sanitize_unicode_in_database(dry_run=True, limit=2)

        # Verify results respect the limit
        assert result['records_processed'] == 2
        assert result['records_updated'] == 1  # Record 1 has control characters
        assert result['records_skipped'] == 1  # Record 2 is clean

    def test_sanitize_unicode_in_database_error_handling(self) -> None:
        """Test error handling for individual records."""
        # Mock records with one that has problematic data
        mock_records = [
            Mock(id=1, payload_text='{"eventid": "test", "message": "hello\x00world"}'),
            Mock(id=2, payload_text='{"eventid": "test", "message": "normal"}'),
        ]

        self.mock_connection.execute.return_value.fetchall.return_value = mock_records

        # Run sanitization
        result = self.db.sanitize_unicode_in_database(dry_run=True, limit=2)

        # Verify results - should handle all records successfully
        assert result['records_processed'] == 2
        assert result['records_updated'] == 1  # Record 1 has control characters
        assert result['records_skipped'] == 1  # Record 2 is clean
        assert result['errors'] == 0  # No errors should occur

    def test_sanitize_unicode_in_database_postgresql_vs_sqlite(self) -> None:
        """Test different database dialects."""
        # Test PostgreSQL
        with patch('cowrieprocessor.db.json_utils.get_dialect_name_from_engine', return_value='postgresql'):
            mock_records = [
                Mock(id=1, payload_text='{"eventid": "test", "message": "hello\x00world"}'),
            ]
            self.mock_connection.execute.return_value.fetchall.return_value = mock_records

            result = self.db.sanitize_unicode_in_database(dry_run=False, limit=1)

            assert result['records_processed'] == 1
            assert result['records_updated'] == 1

        # Test SQLite
        with patch('cowrieprocessor.db.json_utils.get_dialect_name_from_engine', return_value='sqlite'):
            mock_records = [
                Mock(id=1, payload_text='{"eventid": "test", "message": "hello\x00world"}'),
            ]
            self.mock_connection.execute.return_value.fetchall.return_value = mock_records

            result = self.db.sanitize_unicode_in_database(dry_run=False, limit=1)

            assert result['records_processed'] == 1
            assert result['records_updated'] == 1

    def test_sanitize_unicode_in_database_json_validation(self) -> None:
        """Test JSON validation during sanitization."""
        # Mock records with various JSON states
        mock_records = [
            # Valid JSON with control characters
            Mock(id=1, payload_text='{"eventid": "test", "message": "hello\x00world"}'),
            # Invalid JSON that becomes valid after sanitization
            Mock(id=2, payload_text='{"eventid": "test", "message": "hello\x00world"'),  # missing closing brace
            # Invalid JSON that remains invalid after sanitization
            Mock(id=3, payload_text='{"eventid": "test", "message": "hello\x00world"{"}'),  # malformed
        ]

        self.mock_connection.execute.return_value.fetchall.return_value = mock_records

        result = self.db.sanitize_unicode_in_database(dry_run=True, limit=3)

        # Verify results
        assert result['records_processed'] == 3
        assert result['records_updated'] == 1  # Only record 1 should be successfully updated
        assert result['records_skipped'] == 2  # Records 2 and 3 should be skipped due to JSON issues
        assert result['errors'] == 0

    def test_sanitize_unicode_in_database_progress_logging(self) -> None:
        """Test that progress logging works without hanging."""
        # Mock a small number of records to test logging without performance issues
        mock_records = [Mock(id=i, payload_text='{"eventid": "test", "message": "normal"}') for i in range(50)]
        self.mock_connection.execute.return_value.fetchall.return_value = mock_records

        with patch('cowrieprocessor.cli.cowrie_db.logger'):
            result = self.db.sanitize_unicode_in_database(dry_run=True, batch_size=10, limit=50)

            # Verify the operation completed successfully
            assert result['records_processed'] == 50
            assert result['records_skipped'] == 50  # All records are clean
            assert result['records_updated'] == 0
            assert result['errors'] == 0

    def test_sanitize_unicode_in_database_real_world_scenario(self) -> None:
        """Test with real-world Cowrie log data."""
        # Mock records with actual Cowrie log patterns
        mock_records = [
            Mock(
                id=1,
                payload_text=(
                    '{"eventid": "cowrie.session.connect", "message": "Remote SSH version: \x16\x03\x01\x00"}'
                ),
            ),
            Mock(id=2, payload_text='{"eventid": "cowrie.session.command", "input": "ls -la"}'),
            Mock(id=3, payload_text='{"eventid": "cowrie.session.file_download", "filename": "malware\x00.exe"}'),
        ]

        self.mock_connection.execute.return_value.fetchall.return_value = mock_records

        result = self.db.sanitize_unicode_in_database(dry_run=True, limit=3)

        # Verify results
        assert result['records_processed'] == 3
        assert result['records_updated'] == 2  # Records 1 and 3 have control characters
        assert result['records_skipped'] == 1  # Record 2 is clean
        assert result['errors'] == 0

    def test_sanitize_unicode_in_database_empty_database(self) -> None:
        """Test behavior with empty database."""
        # Mock empty result set
        self.mock_connection.execute.return_value.fetchall.return_value = []

        result = self.db.sanitize_unicode_in_database(dry_run=True)

        # Verify results
        assert result['records_processed'] == 0
        assert result['records_updated'] == 0
        assert result['records_skipped'] == 0
        assert result['errors'] == 0
        assert result['batches_processed'] == 0
        assert "0 records" in result['message']
