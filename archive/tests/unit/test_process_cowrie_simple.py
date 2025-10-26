"""Simple unit tests for process_cowrie.py type safety."""

import os
from unittest.mock import patch

# Mock sys.exit to prevent the module from exiting during import
with patch('sys.exit'):
    from process_cowrie import (
        cache_get,
        cache_upsert,
        dshield_query,
        evaluate_sessions,
        get_command_total,
        get_commands,
        get_connected_sessions,
        get_database_url,
        get_file_download,
        get_file_upload,
        get_login_data,
        get_protocol_login,
        get_session_duration,
        get_session_id,
        print_session_info,
        rate_limit,
        read_spur_data,
        read_vt_data,
        safe_read_uh_data,
        timeout_handler,
        vt_filescan,
        vt_query,
        with_timeout,
    )


class TestProcessCowrieSimple:
    """Simple tests for process_cowrie.py type safety."""

    def test_functions_exist_and_callable(self) -> None:
        """Test that all functions exist and are callable."""
        functions = [
            timeout_handler,
            with_timeout,
            rate_limit,
            cache_get,
            cache_upsert,
            get_connected_sessions,
            get_session_id,
            get_session_duration,
            get_protocol_login,
            get_login_data,
            get_command_total,
            get_file_download,
            get_file_upload,
            vt_query,
            vt_filescan,
            dshield_query,
            safe_read_uh_data,
            read_spur_data,
            read_vt_data,
            print_session_info,
            get_commands,
            evaluate_sessions,
            get_database_url,
        ]

        for func in functions:
            assert callable(func), f"Function {func.__name__} is not callable"

    def test_functions_have_type_annotations(self) -> None:
        """Test that all functions have type annotations."""
        functions = [
            timeout_handler,
            with_timeout,
            rate_limit,
            cache_get,
            cache_upsert,
            get_connected_sessions,
            get_session_id,
            get_session_duration,
            get_protocol_login,
            get_login_data,
            get_command_total,
            get_file_download,
            get_file_upload,
            vt_query,
            vt_filescan,
            dshield_query,
            safe_read_uh_data,
            read_spur_data,
            read_vt_data,
            print_session_info,
            get_commands,
            evaluate_sessions,
            get_database_url,
        ]

        for func in functions:
            assert hasattr(func, '__annotations__'), f"Function {func.__name__} has no type annotations"
            assert len(func.__annotations__) > 0, f"Function {func.__name__} has empty type annotations"

    def test_no_deprecated_query_patterns(self) -> None:
        """Test that no deprecated SQLAlchemy query patterns are used."""
        # Read the source file and check for deprecated patterns
        current_dir = os.path.dirname(os.path.abspath(__file__))
        source_file = os.path.join(current_dir, '..', '..', 'process_cowrie.py')

        with open(source_file, 'r') as f:
            content = f.read()

        # Check that no deprecated patterns are used
        assert 'session.query(' not in content, "Found deprecated session.query() pattern"
        assert '.query(' not in content, "Found deprecated .query() pattern"

    def test_imports_are_proper(self) -> None:
        """Test that proper imports are used."""
        # Read the source file and check for proper imports
        current_dir = os.path.dirname(os.path.abspath(__file__))
        source_file = os.path.join(current_dir, '..', '..', 'process_cowrie.py')

        with open(source_file, 'r') as f:
            content = f.read()

        # Check that proper imports are used
        assert 'from typing import' in content, "Should import from typing"
        assert 'Any' in content, "Should import Any type"
        assert 'Optional' in content, "Should import Optional type"
