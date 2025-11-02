"""Unit tests for refresh_cache_and_reports.py type safety and SQLAlchemy 2.0 compatibility."""

import os

from refresh_cache_and_reports import (
    Refresher,
    ensure_indicator_table,
    main,
    parse_args,
    refresh_reports,
)


class TestRefreshCacheTypes:
    """Test type safety and SQLAlchemy 2.0 compatibility for refresh_cache_and_reports.py."""

    def test_parse_args_type_annotations(self) -> None:
        """Test that parse_args has proper type annotations."""
        # This test ensures we're using proper type annotations

        # Check that the function exists and has proper type annotations
        assert callable(parse_args)

        # Test function signature
        import inspect

        sig = inspect.signature(parse_args)
        assert len(sig.parameters) == 0
        assert sig.return_annotation == argparse.Namespace

    def test_ensure_indicator_table_type_annotations(self) -> None:
        """Test that ensure_indicator_table has proper type annotations."""
        # This test ensures we're using proper type annotations

        # Check that the function exists and has proper type annotations
        assert callable(ensure_indicator_table)

        # Test function signature
        import inspect

        sig = inspect.signature(ensure_indicator_table)
        assert len(sig.parameters) == 1
        assert sig.parameters['conn'].annotation == sqlite3.Connection
        assert sig.return_annotation == None

    def test_refresher_init_type_annotations(self) -> None:
        """Test that Refresher.__init__ has proper type annotations."""
        # This test ensures we're using proper type annotations

        # Check that the class exists and has proper type annotations
        assert callable(Refresher)

        # Test function signature
        import inspect

        sig = inspect.signature(Refresher.__init__)
        assert len(sig.parameters) == 3  # self, args, conn
        assert sig.parameters['args'].annotation == argparse.Namespace
        assert sig.parameters['conn'].annotation == sqlite3.Connection
        assert sig.return_annotation == None

    def test_refresher_rate_limit_type_annotations(self) -> None:
        """Test that Refresher.rate_limit has proper type annotations."""
        # This test ensures we're using proper type annotations

        # Check that the method exists and has proper type annotations
        assert callable(Refresher.rate_limit)

        # Test function signature
        import inspect

        sig = inspect.signature(Refresher.rate_limit)
        assert len(sig.parameters) == 2  # self, service
        assert sig.parameters['service'].annotation == str
        assert sig.return_annotation == None

    def test_refresher_cache_get_type_annotations(self) -> None:
        """Test that Refresher.cache_get has proper type annotations."""
        # This test ensures we're using proper type annotations

        # Check that the method exists and has proper type annotations
        assert callable(Refresher.cache_get)

        # Test function signature
        import inspect

        sig = inspect.signature(Refresher.cache_get)
        assert len(sig.parameters) == 3  # self, service, key
        assert sig.parameters['service'].annotation == str
        assert sig.parameters['key'].annotation == str
        assert sig.return_annotation == object

    def test_refresher_cache_upsert_type_annotations(self) -> None:
        """Test that Refresher.cache_upsert has proper type annotations."""
        # This test ensures we're using proper type annotations

        # Check that the method exists and has proper type annotations
        assert callable(Refresher.cache_upsert)

        # Test function signature
        import inspect

        sig = inspect.signature(Refresher.cache_upsert)
        assert len(sig.parameters) == 4  # self, service, key, data
        assert sig.parameters['service'].annotation == str
        assert sig.parameters['key'].annotation == str
        assert sig.parameters['data'].annotation == str
        assert sig.return_annotation == None

    def test_refresher_should_refresh_vt_type_annotations(self) -> None:
        """Test that Refresher.should_refresh_vt has proper type annotations."""
        # This test ensures we're using proper type annotations

        # Check that the method exists and has proper type annotations
        assert callable(Refresher.should_refresh_vt)

        # Test function signature
        import inspect

        sig = inspect.signature(Refresher.should_refresh_vt)
        assert len(sig.parameters) == 3  # self, key, row
        assert sig.parameters['key'].annotation == str
        assert sig.parameters['row'].annotation == object
        assert sig.return_annotation == bool

    def test_refresher_should_refresh_ip_type_annotations(self) -> None:
        """Test that Refresher.should_refresh_ip has proper type annotations."""
        # This test ensures we're using proper type annotations

        # Check that the method exists and has proper type annotations
        assert callable(Refresher.should_refresh_ip)

        # Test function signature
        import inspect

        sig = inspect.signature(Refresher.should_refresh_ip)
        assert len(sig.parameters) == 2  # self, row
        assert sig.parameters['row'].annotation == object
        assert sig.return_annotation == bool

    def test_refresher_refresh_vt_type_annotations(self) -> None:
        """Test that Refresher.refresh_vt has proper type annotations."""
        # This test ensures we're using proper type annotations

        # Check that the method exists and has proper type annotations
        assert callable(Refresher.refresh_vt)

        # Test function signature
        import inspect

        sig = inspect.signature(Refresher.refresh_vt)
        assert len(sig.parameters) == 2  # self, hash_
        assert sig.parameters['hash_'].annotation == str
        assert sig.return_annotation == None

    def test_refresher_refresh_dshield_type_annotations(self) -> None:
        """Test that Refresher.refresh_dshield has proper type annotations."""
        # This test ensures we're using proper type annotations

        # Check that the method exists and has proper type annotations
        assert callable(Refresher.refresh_dshield)

        # Test function signature
        import inspect

        sig = inspect.signature(Refresher.refresh_dshield)
        assert len(sig.parameters) == 2  # self, ip
        assert sig.parameters['ip'].annotation == str
        assert sig.return_annotation == None

    def test_refresher_refresh_urlhaus_type_annotations(self) -> None:
        """Test that Refresher.refresh_urlhaus has proper type annotations."""
        # This test ensures we're using proper type annotations

        # Check that the method exists and has proper type annotations
        assert callable(Refresher.refresh_urlhaus)

        # Test function signature
        import inspect

        sig = inspect.signature(Refresher.refresh_urlhaus)
        assert len(sig.parameters) == 2  # self, host
        assert sig.parameters['host'].annotation == str
        assert sig.return_annotation == None

    def test_refresher_refresh_spur_type_annotations(self) -> None:
        """Test that Refresher.refresh_spur has proper type annotations."""
        # This test ensures we're using proper type annotations

        # Check that the method exists and has proper type annotations
        assert callable(Refresher.refresh_spur)

        # Test function signature
        import inspect

        sig = inspect.signature(Refresher.refresh_spur)
        assert len(sig.parameters) == 2  # self, ip
        assert sig.parameters['ip'].annotation == str
        assert sig.return_annotation == None

    def test_refresher_seed_missing_type_annotations(self) -> None:
        """Test that Refresher.seed_missing has proper type annotations."""
        # This test ensures we're using proper type annotations

        # Check that the method exists and has proper type annotations
        assert callable(Refresher.seed_missing)

        # Test function signature
        import inspect

        sig = inspect.signature(Refresher.seed_missing)
        assert len(sig.parameters) == 1  # self
        assert sig.return_annotation == None

    def test_refresher_refresh_stale_type_annotations(self) -> None:
        """Test that Refresher.refresh_stale has proper type annotations."""
        # This test ensures we're using proper type annotations

        # Check that the method exists and has proper type annotations
        assert callable(Refresher.refresh_stale)

        # Test function signature
        import inspect

        sig = inspect.signature(Refresher.refresh_stale)
        assert len(sig.parameters) == 1  # self
        assert sig.return_annotation == None

    def test_refresh_reports_type_annotations(self) -> None:
        """Test that refresh_reports has proper type annotations."""
        # This test ensures we're using proper type annotations

        # Check that the function exists and has proper type annotations
        assert callable(refresh_reports)

        # Test function signature
        import inspect

        sig = inspect.signature(refresh_reports)
        assert len(sig.parameters) == 2
        assert sig.parameters['db_path'].annotation == str
        assert sig.parameters['args'].annotation == argparse.Namespace
        assert sig.return_annotation == None

    def test_main_type_annotations(self) -> None:
        """Test that main has proper type annotations."""
        # This test ensures we're using proper type annotations

        # Check that the function exists and has proper type annotations
        assert callable(main)

        # Test function signature
        import inspect

        sig = inspect.signature(main)
        assert len(sig.parameters) == 0
        assert sig.return_annotation == None

    def test_no_deprecated_query_patterns(self) -> None:
        """Test that no deprecated SQLAlchemy query patterns are used."""
        # This test ensures we're using proper SQLAlchemy 2.0 patterns

        # Read the source file and check for deprecated patterns
        current_dir = os.path.dirname(os.path.abspath(__file__))
        source_file = os.path.join(current_dir, '..', '..', 'refresh_cache_and_reports.py')

        with open(source_file, 'r') as f:
            content = f.read()

        # Check that no deprecated patterns are used
        assert 'session.query(' not in content, "Found deprecated session.query() pattern"
        assert '.query(' not in content, "Found deprecated .query() pattern"

        # Check that proper imports are used
        assert 'import sqlite3' in content, "Should import sqlite3"
        assert 'from typing import' in content, "Should import from typing"
