"""Simple unit tests for refresh_cache_and_reports.py type safety."""

from unittest.mock import Mock, patch
import os

import pytest

from refresh_cache_and_reports import (
    parse_args,
    ensure_indicator_table,
    Refresher,
    refresh_reports,
    main,
)


class TestRefreshCacheSimple:
    """Simple tests for refresh_cache_and_reports.py type safety."""

    def test_functions_exist_and_callable(self) -> None:
        """Test that all functions exist and are callable."""
        functions = [
            parse_args,
            ensure_indicator_table,
            refresh_reports,
            main,
        ]
        
        for func in functions:
            assert callable(func), f"Function {func.__name__} is not callable"

    def test_class_exists_and_callable(self) -> None:
        """Test that Refresher class exists and is callable."""
        assert callable(Refresher), "Refresher class is not callable"

    def test_functions_have_type_annotations(self) -> None:
        """Test that all functions have type annotations."""
        functions = [
            parse_args,
            ensure_indicator_table,
            refresh_reports,
            main,
        ]
        
        for func in functions:
            assert hasattr(func, '__annotations__'), f"Function {func.__name__} has no type annotations"
            assert len(func.__annotations__) > 0, f"Function {func.__name__} has empty type annotations"

    def test_class_methods_have_type_annotations(self) -> None:
        """Test that Refresher class methods have type annotations."""
        methods = [
            Refresher.__init__,
            Refresher.rate_limit,
            Refresher.cache_get,
            Refresher.cache_upsert,
            Refresher.should_refresh_vt,
            Refresher.should_refresh_ip,
            Refresher.refresh_vt,
            Refresher.refresh_dshield,
            Refresher.refresh_urlhaus,
            Refresher.refresh_spur,
            Refresher.seed_missing,
            Refresher.refresh_stale,
        ]
        
        for method in methods:
            assert hasattr(method, '__annotations__'), f"Method {method.__name__} has no type annotations"
            assert len(method.__annotations__) > 0, f"Method {method.__name__} has empty type annotations"

    def test_no_deprecated_query_patterns(self) -> None:
        """Test that no deprecated SQLAlchemy query patterns are used."""
        # Read the source file and check for deprecated patterns
        current_dir = os.path.dirname(os.path.abspath(__file__))
        source_file = os.path.join(current_dir, '..', '..', 'refresh_cache_and_reports.py')
        
        with open(source_file, 'r') as f:
            content = f.read()
        
        # Check that no deprecated patterns are used
        assert 'session.query(' not in content, "Found deprecated session.query() pattern"
        assert '.query(' not in content, "Found deprecated .query() pattern"

    def test_imports_are_proper(self) -> None:
        """Test that proper imports are used."""
        # Read the source file and check for proper imports
        current_dir = os.path.dirname(os.path.abspath(__file__))
        source_file = os.path.join(current_dir, '..', '..', 'refresh_cache_and_reports.py')
        
        with open(source_file, 'r') as f:
            content = f.read()
        
        # Check that proper imports are used
        assert 'from typing import' in content, "Should import from typing"
        assert 'Any' in content, "Should import Any type"
        assert 'Optional' in content, "Should import Optional type"
