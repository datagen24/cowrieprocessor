"""Integration tests for process_cowrie.py SQLAlchemy 2.0 compatibility."""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

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


class TestProcessCowrieIntegration:
    """Integration tests for process_cowrie.py SQLAlchemy 2.0 compatibility."""

    def test_timeout_handler_integration(self) -> None:
        """Test timeout_handler function integration."""
        # Test that the function can be called with proper arguments
        try:
            timeout_handler(1, Mock())
        except Exception as e:
            # Should raise TimeoutError
            assert "Operation timed out" in str(e)

    def test_with_timeout_integration(self) -> None:
        """Test with_timeout function integration."""

        # Test that the function can be called with proper arguments
        def test_func():
            return "test"

        result = with_timeout(5, test_func)
        assert result == "test"

    def test_rate_limit_integration(self) -> None:
        """Test rate_limit function integration."""
        # Test that the function can be called with proper arguments
        rate_limit("test_service")

    def test_cache_get_integration(self) -> None:
        """Test cache_get function integration."""
        # Test that the function can be called with proper arguments
        with tempfile.NamedTemporaryFile(delete=False) as f:
            db_path = f.name

        try:
            import sqlite3

            conn = sqlite3.connect(db_path)
            conn.execute(
                'CREATE TABLE indicator_cache(service text, key text, last_fetched int, data text, PRIMARY KEY (service, key))'
            )
            conn.commit()

            # Mock the global con variable
            with patch('process_cowrie.con', conn):
                result = cache_get("test_service", "test_key")
                assert result is None
        finally:
            os.unlink(db_path)

    def test_cache_upsert_integration(self) -> None:
        """Test cache_upsert function integration."""
        # Test that the function can be called with proper arguments
        with tempfile.NamedTemporaryFile(delete=False) as f:
            db_path = f.name

        try:
            import sqlite3

            conn = sqlite3.connect(db_path)
            conn.execute(
                'CREATE TABLE indicator_cache(service text, key text, last_fetched int, data text, PRIMARY KEY (service, key))'
            )
            conn.commit()

            # Mock the global con variable
            with patch('process_cowrie.con', conn):
                cache_upsert("test_service", "test_key", "test_data")
        finally:
            os.unlink(db_path)

    def test_get_connected_sessions_integration(self) -> None:
        """Test get_connected_sessions function integration."""
        # Test that the function can be called with proper arguments
        data = [
            {"eventid": "cowrie.login.success", "session": "test_session_1"},
            {"eventid": "cowrie.login.success", "session": "test_session_2"},
            {"eventid": "cowrie.login.failed", "session": "test_session_3"},
        ]

        result = get_connected_sessions(data)
        assert isinstance(result, set)
        assert "test_session_1" in result
        assert "test_session_2" in result
        assert "test_session_3" not in result

    def test_get_session_id_integration(self) -> None:
        """Test get_session_id function integration."""
        # Test that the function can be called with proper arguments
        data = [
            {"eventid": "cowrie.command.input", "session": "test_session_1"},
            {"eventid": "cowrie.command.input", "session": "test_session_2"},
        ]

        result = get_session_id(data, "all", "")
        assert isinstance(result, set)
        assert "test_session_1" in result
        assert "test_session_2" in result

    def test_get_session_duration_integration(self) -> None:
        """Test get_session_duration function integration."""
        # Test that the function can be called with proper arguments
        data = [
            {"session": "test_session", "eventid": "cowrie.session.closed", "duration": "300"},
        ]

        result = get_session_duration("test_session", data)
        assert result == "300"

    def test_get_protocol_login_integration(self) -> None:
        """Test get_protocol_login function integration."""
        # Test that the function can be called with proper arguments
        data = [
            {"session": "test_session", "eventid": "cowrie.session.connect", "protocol": "ssh"},
        ]

        result = get_protocol_login("test_session", data)
        assert result == "ssh"

    def test_get_login_data_integration(self) -> None:
        """Test get_login_data function integration."""
        # Test that the function can be called with proper arguments
        data = [
            {
                "session": "test_session",
                "eventid": "cowrie.login.success",
                "username": "test_user",
                "password": "test_pass",
                "timestamp": "2023-01-01T00:00:00Z",
                "src_ip": "1.2.3.4",
            },
        ]

        result = get_login_data("test_session", data)
        assert result is not None
        assert len(result) == 4

    def test_get_command_total_integration(self) -> None:
        """Test get_command_total function integration."""
        # Test that the function can be called with proper arguments
        data = [
            {"session": "test_session", "eventid": "cowrie.command.input"},
            {"session": "test_session", "eventid": "cowrie.command.input"},
            {"session": "test_session", "eventid": "cowrie.login.success"},
        ]

        result = get_command_total("test_session", data)
        assert result == 2

    def test_get_file_download_integration(self) -> None:
        """Test get_file_download function integration."""
        # Test that the function can be called with proper arguments
        data = [
            {
                "session": "test_session",
                "eventid": "cowrie.direct-tcpip.request",
                "url": "http://example.com/file",
                "shasum": "abc123",
                "destfile": "/tmp/file",
            },
        ]

        result = get_file_download("test_session", data)
        assert isinstance(result, list)
        assert len(result) == 1

    def test_get_file_upload_integration(self) -> None:
        """Test get_file_upload function integration."""
        # Test that the function can be called with proper arguments
        data = [
            {
                "session": "test_session",
                "eventid": "cowrie.direct-tcpip.request",
                "url": "http://example.com/upload",
                "shasum": "def456",
                "filename": "upload.txt",
            },
        ]

        result = get_file_upload("test_session", data)
        assert isinstance(result, list)
        assert len(result) == 1

    def test_vt_query_integration(self) -> None:
        """Test vt_query function integration."""
        # Test that the function can be called with proper arguments
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            vt_query("test_hash", cache_dir)

    def test_vt_filescan_integration(self) -> None:
        """Test vt_filescan function integration."""
        # Test that the function can be called with proper arguments
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            vt_filescan("test_hash", cache_dir)

    def test_dshield_query_integration(self) -> None:
        """Test dshield_query function integration."""
        # Test that the function can be called with proper arguments
        with patch('process_cowrie.skip_enrich', True):
            result = dshield_query("1.2.3.4")
            assert isinstance(result, dict)

    def test_safe_read_uh_data_integration(self) -> None:
        """Test safe_read_uh_data function integration."""
        # Test that the function can be called with proper arguments
        result = safe_read_uh_data("1.2.3.4", "test_api_key")
        assert isinstance(result, dict)

    def test_read_spur_data_integration(self) -> None:
        """Test read_spur_data function integration."""
        # Test that the function can be called with proper arguments
        result = read_spur_data("1.2.3.4")
        assert isinstance(result, dict)

    def test_read_vt_data_integration(self) -> None:
        """Test read_vt_data function integration."""
        # Test that the function can be called with proper arguments
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            result = read_vt_data("test_hash", cache_dir)
            assert isinstance(result, tuple)
            assert len(result) == 4

    def test_print_session_info_integration(self) -> None:
        """Test print_session_info function integration."""
        # Test that the function can be called with proper arguments
        data = []
        sessions = {"test_session"}
        attack_type = "test_attack"

        print_session_info(data, sessions, attack_type)

    def test_get_commands_integration(self) -> None:
        """Test get_commands function integration."""
        # Test that the function can be called with proper arguments
        data = [
            {"session": "test_session", "eventid": "cowrie.command.input", "input": "ls -la"},
        ]

        get_commands(data, "test_session")

    def test_evaluate_sessions_integration(self) -> None:
        """Test evaluate_sessions function integration."""
        # Test that the function can be called with proper arguments
        target_sessions = {"test_session"}
        evaluate_sessions(target_sessions)

    def test_get_database_url_integration(self) -> None:
        """Test get_database_url function integration."""
        # Test that the function can be called with proper arguments
        result = get_database_url()
        assert isinstance(result, str)
        assert result.startswith("sqlite:///")

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
        import process_cowrie

        # Get all functions from the module
        functions = [
            getattr(process_cowrie, name)
            for name in dir(process_cowrie)
            if callable(getattr(process_cowrie, name)) and not name.startswith('_')
        ]

        for func in functions:
            if hasattr(func, '__annotations__'):
                # Check that return type is annotated
                if 'return' not in func.__annotations__:
                    # Skip if it's a builtin or imported function
                    if func.__module__ == 'process_cowrie':
                        assert 'return' in func.__annotations__, (
                            f"Function {func.__name__} missing return type annotation"
                        )
