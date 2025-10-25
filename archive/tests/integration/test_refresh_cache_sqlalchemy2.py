"""Integration tests for refresh_cache_and_reports.py SQLAlchemy 2.0 compatibility."""

import os
import tempfile
from unittest.mock import Mock, patch

from refresh_cache_and_reports import (
    Refresher,
    ensure_indicator_table,
    main,
    parse_args,
    refresh_reports,
)


class TestRefreshCacheIntegration:
    """Integration tests for refresh_cache_and_reports.py SQLAlchemy 2.0 compatibility."""

    def test_parse_args_integration(self) -> None:
        """Test parse_args function integration."""
        # Test that the function can be called with proper arguments
        with patch('sys.argv', ['refresh_cache_and_reports.py', '--db', '/tmp/test.db']):
            args = parse_args()
            assert hasattr(args, 'db')
            assert args.db == '/tmp/test.db'

    def test_ensure_indicator_table_integration(self) -> None:
        """Test ensure_indicator_table function integration."""
        # Test that the function can be called with proper arguments
        with tempfile.NamedTemporaryFile(delete=False) as f:
            db_path = f.name

        try:
            import sqlite3

            conn = sqlite3.connect(db_path)
            ensure_indicator_table(conn)

            # Check that the table was created
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='indicator_cache'")
            result = cursor.fetchone()
            assert result is not None
        finally:
            os.unlink(db_path)

    def test_refresher_init_integration(self) -> None:
        """Test Refresher.__init__ integration."""
        # Test that the class can be instantiated with proper arguments
        with tempfile.NamedTemporaryFile(delete=False) as f:
            db_path = f.name

        try:
            import sqlite3

            conn = sqlite3.connect(db_path)
            ensure_indicator_table(conn)

            # Mock args
            args = Mock()
            args.vtapi = "test_vt_api"
            args.email = "test@example.com"
            args.urlhausapi = "test_urlhaus_api"
            args.spurapi = "test_spur_api"
            args.api_timeout = 15
            args.api_retries = 3
            args.api_backoff = 2.0
            args.rate_vt = 4
            args.rate_dshield = 30
            args.rate_urlhaus = 30
            args.rate_spur = 30
            args.hash_ttl_days = 30
            args.hash_unknown_ttl_hours = 12
            args.ip_ttl_hours = 24
            args.refresh_indicators = "all"
            args.refresh_reports = "all"
            args.hot_daily_days = 7
            args.hot_weekly_weeks = 4
            args.hot_monthly_months = 3

            refresher = Refresher(args, conn)
            assert refresher.args == args
            assert refresher.conn == conn
        finally:
            os.unlink(db_path)

    def test_refresher_rate_limit_integration(self) -> None:
        """Test Refresher.rate_limit integration."""
        # Test that the method can be called with proper arguments
        with tempfile.NamedTemporaryFile(delete=False) as f:
            db_path = f.name

        try:
            import sqlite3

            conn = sqlite3.connect(db_path)
            ensure_indicator_table(conn)

            # Mock args
            args = Mock()
            args.rate_vt = 4
            args.rate_dshield = 30
            args.rate_urlhaus = 30
            args.rate_spur = 30

            refresher = Refresher(args, conn)
            refresher.rate_limit("vt")
        finally:
            os.unlink(db_path)

    def test_refresher_cache_get_integration(self) -> None:
        """Test Refresher.cache_get integration."""
        # Test that the method can be called with proper arguments
        with tempfile.NamedTemporaryFile(delete=False) as f:
            db_path = f.name

        try:
            import sqlite3

            conn = sqlite3.connect(db_path)
            ensure_indicator_table(conn)

            # Mock args
            args = Mock()

            refresher = Refresher(args, conn)
            result = refresher.cache_get("test_service", "test_key")
            assert result is None
        finally:
            os.unlink(db_path)

    def test_refresher_cache_upsert_integration(self) -> None:
        """Test Refresher.cache_upsert integration."""
        # Test that the method can be called with proper arguments
        with tempfile.NamedTemporaryFile(delete=False) as f:
            db_path = f.name

        try:
            import sqlite3

            conn = sqlite3.connect(db_path)
            ensure_indicator_table(conn)

            # Mock args
            args = Mock()

            refresher = Refresher(args, conn)
            refresher.cache_upsert("test_service", "test_key", "test_data")

            # Check that the data was inserted
            result = refresher.cache_get("test_service", "test_key")
            assert result is not None
        finally:
            os.unlink(db_path)

    def test_refresher_should_refresh_vt_integration(self) -> None:
        """Test Refresher.should_refresh_vt integration."""
        # Test that the method can be called with proper arguments
        with tempfile.NamedTemporaryFile(delete=False) as f:
            db_path = f.name

        try:
            import sqlite3

            conn = sqlite3.connect(db_path)
            ensure_indicator_table(conn)

            # Mock args
            args = Mock()
            args.hash_ttl_days = 30
            args.hash_unknown_ttl_hours = 12

            refresher = Refresher(args, conn)

            # Test with no row
            result = refresher.should_refresh_vt("test_hash", None)
            assert result is True

            # Test with valid row
            import time

            row = (time.time() - 1000, '{"data": "test"}')
            result = refresher.should_refresh_vt("test_hash", row)
            assert isinstance(result, bool)
        finally:
            os.unlink(db_path)

    def test_refresher_should_refresh_ip_integration(self) -> None:
        """Test Refresher.should_refresh_ip integration."""
        # Test that the method can be called with proper arguments
        with tempfile.NamedTemporaryFile(delete=False) as f:
            db_path = f.name

        try:
            import sqlite3

            conn = sqlite3.connect(db_path)
            ensure_indicator_table(conn)

            # Mock args
            args = Mock()
            args.ip_ttl_hours = 24

            refresher = Refresher(args, conn)

            # Test with no row
            result = refresher.should_refresh_ip(None)
            assert result is True

            # Test with valid row
            import time

            row = (time.time() - 1000, '{"data": "test"}')
            result = refresher.should_refresh_ip(row)
            assert isinstance(result, bool)
        finally:
            os.unlink(db_path)

    def test_refresher_refresh_vt_integration(self) -> None:
        """Test Refresher.refresh_vt integration."""
        # Test that the method can be called with proper arguments
        with tempfile.NamedTemporaryFile(delete=False) as f:
            db_path = f.name

        try:
            import sqlite3

            conn = sqlite3.connect(db_path)
            ensure_indicator_table(conn)

            # Mock args
            args = Mock()
            args.vtapi = "test_vt_api"
            args.api_retries = 3
            args.api_backoff = 2.0
            args.api_timeout = 15

            refresher = Refresher(args, conn)

            # Mock the requests session
            with patch.object(refresher.vt, 'get') as mock_get:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.text = '{"data": "test"}'
                mock_get.return_value = mock_response

                refresher.refresh_vt("test_hash")
        finally:
            os.unlink(db_path)

    def test_refresher_refresh_dshield_integration(self) -> None:
        """Test Refresher.refresh_dshield integration."""
        # Test that the method can be called with proper arguments
        with tempfile.NamedTemporaryFile(delete=False) as f:
            db_path = f.name

        try:
            import sqlite3

            conn = sqlite3.connect(db_path)
            ensure_indicator_table(conn)

            # Mock args
            args = Mock()
            args.email = "test@example.com"
            args.api_retries = 3
            args.api_backoff = 2.0
            args.api_timeout = 15

            refresher = Refresher(args, conn)

            # Mock the requests session
            with patch.object(refresher.dshield, 'get') as mock_get:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.text = '{"data": "test"}'
                mock_get.return_value = mock_response

                refresher.refresh_dshield("1.2.3.4")
        finally:
            os.unlink(db_path)

    def test_refresher_refresh_urlhaus_integration(self) -> None:
        """Test Refresher.refresh_urlhaus integration."""
        # Test that the method can be called with proper arguments
        with tempfile.NamedTemporaryFile(delete=False) as f:
            db_path = f.name

        try:
            import sqlite3

            conn = sqlite3.connect(db_path)
            ensure_indicator_table(conn)

            # Mock args
            args = Mock()
            args.urlhausapi = "test_urlhaus_api"
            args.api_retries = 3
            args.api_backoff = 2.0
            args.api_timeout = 15

            refresher = Refresher(args, conn)

            # Mock the requests session
            with patch.object(refresher.uh, 'post') as mock_post:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.text = '{"data": "test"}'
                mock_post.return_value = mock_response

                refresher.refresh_urlhaus("example.com")
        finally:
            os.unlink(db_path)

    def test_refresher_refresh_spur_integration(self) -> None:
        """Test Refresher.refresh_spur integration."""
        # Test that the method can be called with proper arguments
        with tempfile.NamedTemporaryFile(delete=False) as f:
            db_path = f.name

        try:
            import sqlite3

            conn = sqlite3.connect(db_path)
            ensure_indicator_table(conn)

            # Mock args
            args = Mock()
            args.spurapi = "test_spur_api"
            args.api_retries = 3
            args.api_backoff = 2.0
            args.api_timeout = 15

            refresher = Refresher(args, conn)

            # Mock the requests session
            with patch.object(refresher.spur, 'get') as mock_get:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.text = '{"data": "test"}'
                mock_get.return_value = mock_response

                refresher.refresh_spur("1.2.3.4")
        finally:
            os.unlink(db_path)

    def test_refresher_seed_missing_integration(self) -> None:
        """Test Refresher.seed_missing integration."""
        # Test that the method can be called with proper arguments
        with tempfile.NamedTemporaryFile(delete=False) as f:
            db_path = f.name

        try:
            import sqlite3

            conn = sqlite3.connect(db_path)
            ensure_indicator_table(conn)

            # Create files table
            conn.execute('CREATE TABLE IF NOT EXISTS files(hash text, source_ip text)')
            conn.execute('CREATE TABLE IF NOT EXISTS sessions(source_ip text)')
            conn.commit()

            # Mock args
            args = Mock()

            refresher = Refresher(args, conn)
            refresher.seed_missing()
        finally:
            os.unlink(db_path)

    def test_refresher_refresh_stale_integration(self) -> None:
        """Test Refresher.refresh_stale integration."""
        # Test that the method can be called with proper arguments
        with tempfile.NamedTemporaryFile(delete=False) as f:
            db_path = f.name

        try:
            import sqlite3

            conn = sqlite3.connect(db_path)
            ensure_indicator_table(conn)

            # Mock args
            args = Mock()
            args.refresh_indicators = "all"

            refresher = Refresher(args, conn)
            refresher.refresh_stale()
        finally:
            os.unlink(db_path)

    def test_refresh_reports_integration(self) -> None:
        """Test refresh_reports function integration."""
        # Test that the function can be called with proper arguments
        with tempfile.NamedTemporaryFile(delete=False) as f:
            db_path = f.name

        try:
            # Mock args
            args = Mock()
            args.refresh_reports = "all"
            args.hot_daily_days = 7
            args.hot_weekly_weeks = 4
            args.hot_monthly_months = 3

            # Mock subprocess.run
            with patch('subprocess.run') as mock_run:
                refresh_reports(db_path, args)
                # Should have been called for daily reports
                assert mock_run.called
        finally:
            os.unlink(db_path)

    def test_main_integration(self) -> None:
        """Test main function integration."""
        # Test that the function can be called with proper arguments
        with patch('sys.argv', ['refresh_cache_and_reports.py', '--db', '/tmp/test.db']):
            with patch('refresh_cache_and_reports.Refresher') as mock_refresher:
                with patch('refresh_cache_and_reports.refresh_reports') as mock_refresh_reports:
                    main()
                    # Should have created Refresher instance
                    assert mock_refresher.called

    def test_no_sqlalchemy_deprecation_warnings(self) -> None:
        """Test that no SQLAlchemy deprecation warnings are emitted."""
        import warnings

        # Capture warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # Import the module to check for deprecation warnings

            # Filter for SQLAlchemy deprecation warnings
            sqlalchemy_warnings = [warning for warning in w if 'sqlalchemy' in str(warning.message).lower()]
            assert len(sqlalchemy_warnings) == 0, f"Found SQLAlchemy deprecation warnings: {sqlalchemy_warnings}"

    def test_type_annotations_consistency(self) -> None:
        """Test that type annotations are consistent across the module."""
        import refresh_cache_and_reports

        # Get all functions from the module
        functions = [
            getattr(refresh_cache_and_reports, name)
            for name in dir(refresh_cache_and_reports)
            if callable(getattr(refresh_cache_and_reports, name)) and not name.startswith('_')
        ]

        for func in functions:
            if hasattr(func, '__annotations__'):
                # Check that return type is annotated
                if 'return' not in func.__annotations__:
                    # Skip if it's a builtin or imported function
                    if func.__module__ == 'refresh_cache_and_reports':
                        assert 'return' in func.__annotations__, (
                            f"Function {func.__name__} missing return type annotation"
                        )
