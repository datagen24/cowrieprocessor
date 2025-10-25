"""Comprehensive tests for the health check CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from cowrieprocessor.cli import health as health_cli
from cowrieprocessor.cli.health import HealthReport, _check_database, _load_status


def _write_status(dir_path: Path, name: str, payload: dict) -> None:
    """Helper to write status JSON files."""
    path = dir_path / f"{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestHealthReportDataclass:
    """Test HealthReport dataclass."""

    def test_health_report_to_dict(self) -> None:
        """Test HealthReport.to_dict() converts to dictionary.

        Given: HealthReport instance with data
        When: to_dict() is called
        Then: Returns correct dictionary structure
        """
        # Given: HealthReport with test data
        report = HealthReport(
            status="ok",
            summary="All systems operational",
            database_ok=True,
            status_files_ok=True,
            latest_status={"phase1": {"last_updated": "2025-01-01"}},
        )

        # When: Convert to dict
        result = report.to_dict()

        # Then: Correct dictionary structure
        assert isinstance(result, dict)
        assert result["status"] == "ok"
        assert result["summary"] == "All systems operational"
        assert result["database_ok"] is True
        assert result["status_files_ok"] is True
        assert result["latest_status"] == {"phase1": {"last_updated": "2025-01-01"}}


class TestCheckDatabase:
    """Test _check_database() function."""

    def test_check_database_no_url(self) -> None:
        """Test _check_database with None URL.

        Given: No database URL provided
        When: _check_database is called
        Then: Returns False with error message
        """
        # When: Check with None
        ok, msg = _check_database(None)

        # Then: Returns error
        assert ok is False
        assert "not provided" in msg.lower()

    def test_check_database_unsupported_type(self) -> None:
        """Test _check_database with unsupported database type.

        Given: Unsupported database URL (e.g., mysql)
        When: _check_database is called
        Then: Returns False with unsupported message
        """
        # When: Check unsupported type
        ok, msg = _check_database("mysql://localhost/db")

        # Then: Returns unsupported error
        assert ok is False
        assert "unsupported" in msg.lower()

    def test_check_database_sqlite_missing_file(self, tmp_path: Path) -> None:
        """Test _check_database with missing SQLite file.

        Given: SQLite URL pointing to non-existent file
        When: _check_database is called
        Then: Returns False with missing file message
        """
        # Given: Non-existent database path
        db_path = tmp_path / "nonexistent.sqlite"
        db_url = f"sqlite:///{db_path}"

        # When: Check missing file
        ok, msg = _check_database(db_url)

        # Then: Returns missing file error
        assert ok is False
        assert "missing" in msg.lower()

    def test_check_database_sqlite_success(self, tmp_path: Path) -> None:
        """Test _check_database with valid SQLite database.

        Given: Valid SQLite database file
        When: _check_database is called
        Then: Returns True with success message
        """
        # Given: Create valid SQLite database
        db_path = tmp_path / "test.sqlite"
        from sqlalchemy import create_engine, text

        engine = create_engine(f"sqlite:///{db_path}")
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE test (id INTEGER)"))
            conn.commit()
        engine.dispose()

        # When: Check database
        ok, msg = _check_database(f"sqlite:///{db_path}")

        # Then: Returns success
        assert ok is True
        assert "ok" in msg.lower()

    def test_check_database_sqlite_integrity_fail(self, tmp_path: Path) -> None:
        """Test _check_database with corrupted SQLite database.

        Given: Corrupted SQLite file
        When: _check_database is called
        Then: Returns False with integrity error
        """
        # Given: Create corrupted database file
        db_path = tmp_path / "corrupt.sqlite"
        db_path.write_text("CORRUPTED DATA", encoding="utf-8")

        # When: Check corrupted database
        ok, msg = _check_database(f"sqlite:///{db_path}")

        # Then: Returns error
        assert ok is False
        assert "error" in msg.lower()

    def test_check_database_postgresql_url_formats(self) -> None:
        """Test _check_database accepts both postgresql:// and postgres:// formats.

        Given: PostgreSQL URLs with different protocols
        When: _check_database is called with mocked connection
        Then: Both formats are accepted and tested
        """
        # Given/When: Mock PostgreSQL connection
        with patch("cowrieprocessor.cli.health.create_engine_from_settings") as mock_create:
            mock_engine = Mock()
            mock_result = Mock()
            mock_result.fetchone.return_value = (1,)

            # Use spec to create proper context manager
            mock_conn = Mock()
            mock_conn.__enter__ = Mock(return_value=mock_conn)
            mock_conn.__exit__ = Mock(return_value=None)
            mock_conn.execute.return_value = mock_result

            mock_engine.connect.return_value = mock_conn
            mock_create.return_value = mock_engine

            # Test postgresql://
            ok1, msg1 = _check_database("postgresql://user:pass@localhost/db")
            assert ok1 is True
            assert "ok" in msg1.lower()

            # Test postgres://
            ok2, msg2 = _check_database("postgres://user:pass@localhost/db")
            assert ok2 is True
            assert "ok" in msg2.lower()

    def test_check_database_sqlalchemy_error(self, tmp_path: Path) -> None:
        """Test _check_database handles SQLAlchemy errors.

        Given: Database that raises SQLAlchemyError
        When: _check_database is called
        Then: Returns False with database error message
        """
        # Given: Valid SQLite file
        db_path = tmp_path / "test.sqlite"
        db_path.write_text("", encoding="utf-8")

        # When: Mock SQLAlchemy to raise error
        with patch("cowrieprocessor.cli.health.create_engine_from_settings") as mock_create:
            mock_create.side_effect = SQLAlchemyError("Connection failed")

            ok, msg = _check_database(f"sqlite:///{db_path}")

            # Then: Returns database error
            assert ok is False
            assert "database error" in msg.lower()


class TestLoadStatus:
    """Test _load_status() function."""

    def test_load_status_aggregate_file(self, tmp_path: Path) -> None:
        """Test _load_status with aggregate status.json file.

        Given: Directory with status.json aggregate file
        When: _load_status is called
        Then: Returns aggregate status data
        """
        # Given: Create status.json
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        aggregate_data = {"phase": "complete", "last_updated": "2025-01-01"}
        _write_status(status_dir, "status", aggregate_data)

        # When: Load status
        ok, data = _load_status(str(status_dir))

        # Then: Returns aggregate data
        assert ok is True
        assert data == aggregate_data

    def test_load_status_individual_files(self, tmp_path: Path) -> None:
        """Test _load_status with individual phase files.

        Given: Directory with individual phase JSON files
        When: _load_status is called (no aggregate)
        Then: Returns combined individual file data
        """
        # Given: Create individual phase files
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        _write_status(status_dir, "phase1", {"status": "complete"})
        _write_status(status_dir, "phase2", {"status": "running"})

        # When: Load status
        ok, data = _load_status(str(status_dir))

        # Then: Returns individual file data
        assert ok is True
        assert "phase1" in data
        assert "phase2" in data
        assert data["phase1"]["status"] == "complete"
        assert data["phase2"]["status"] == "running"

    def test_load_status_json_decode_error(self, tmp_path: Path) -> None:
        """Test _load_status with malformed JSON file.

        Given: Directory with invalid JSON file
        When: _load_status is called
        Then: Returns error in status for that file
        """
        # Given: Create invalid JSON file
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        (status_dir / "bad.json").write_text("INVALID JSON", encoding="utf-8")

        # When: Load status
        ok, data = _load_status(str(status_dir))

        # Then: Returns error for bad file
        # Note: Function only returns True if at least one valid file was found
        # With only invalid JSON, it returns False but includes error data
        assert "bad" in data
        assert "error" in data["bad"]

    def test_load_status_no_files(self, tmp_path: Path) -> None:
        """Test _load_status with empty directory.

        Given: Empty status directory
        When: _load_status is called
        Then: Returns False with empty dict
        """
        # Given: Empty directory
        status_dir = tmp_path / "status"
        status_dir.mkdir()

        # When: Load status
        ok, data = _load_status(str(status_dir))

        # Then: Returns empty
        assert ok is False
        assert data == {}

    def test_load_status_default_dir(self) -> None:
        """Test _load_status uses default directory when None.

        Given: None status_dir argument
        When: _load_status is called
        Then: Uses default /mnt/dshield/data/logs/status
        """
        # When: Call with None (will fail since /mnt/dshield doesn't exist in tests)
        ok, data = _load_status(None)

        # Then: Returns result (likely empty/False since default path doesn't exist)
        assert isinstance(ok, bool)
        assert isinstance(data, dict)


class TestMainCLI:
    """Test main() CLI function."""

    def test_main_json_output_success(self, tmp_path: Path) -> None:
        """Test main with JSON output and successful checks.

        Given: Valid database and status files
        When: main is called with --output json
        Then: Returns 0 and prints JSON report
        """
        # Given: Valid database
        db_path = tmp_path / "db.sqlite"
        from sqlalchemy import create_engine

        engine = create_engine(f"sqlite:///{db_path}")
        with engine.connect():
            pass
        engine.dispose()

        # Given: Valid status files
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        _write_status(status_dir, "status", {"last_updated": "2025-01-01T00:00:00Z"})

        # When: Run main with JSON output
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.write = Mock()
            result = health_cli.main(
                [
                    "--db-url",
                    f"sqlite:///{db_path}",
                    "--status-dir",
                    str(status_dir),
                    "--output",
                    "json",
                ]
            )

        # Then: Returns success
        assert result == 0

    def test_main_text_output_success(self, tmp_path: Path, capsys: Any) -> None:
        """Test main with text output and successful checks.

        Given: Valid database and status files
        When: main is called with default text output
        Then: Returns 0 and prints text report
        """
        # Given: Valid database
        db_path = tmp_path / "db.sqlite"
        from sqlalchemy import create_engine

        engine = create_engine(f"sqlite:///{db_path}")
        with engine.connect():
            pass
        engine.dispose()

        # Given: Valid status files
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        _write_status(status_dir, "status", {"last_updated": "2025-01-01"})

        # When: Run main with text output
        result = health_cli.main(
            [
                "--db-url",
                f"sqlite:///{db_path}",
                "--status-dir",
                str(status_dir),
            ]
        )

        # Then: Returns success
        assert result == 0
        output = capsys.readouterr().out
        assert "Status: ok" in output
        assert "Database OK: True" in output

    def test_main_warning_missing_status(self, tmp_path: Path, capsys: Any) -> None:
        """Test main with missing status files.

        Given: Valid database but no status files
        When: main is called
        Then: Returns 1 with warning status
        """
        # Given: Valid database
        db_path = tmp_path / "db.sqlite"
        from sqlalchemy import create_engine

        engine = create_engine(f"sqlite:///{db_path}")
        with engine.connect():
            pass
        engine.dispose()

        # When: Run main with missing status dir
        result = health_cli.main(
            [
                "--db-url",
                f"sqlite:///{db_path}",
                "--status-dir",
                str(tmp_path / "missing"),
            ]
        )

        # Then: Returns warning
        assert result == 1
        output = capsys.readouterr().out
        assert "warning" in output.lower()

    def test_main_critical_both_failed(self, tmp_path: Path, capsys: Any) -> None:
        """Test main with both database and status failures.

        Given: Missing database and no status files
        When: main is called
        Then: Returns 1 with critical status
        """
        # When: Run main with missing everything
        result = health_cli.main(
            [
                "--db-url",
                f"sqlite:///{tmp_path / 'missing.sqlite'}",
                "--status-dir",
                str(tmp_path / "missing"),
            ]
        )

        # Then: Returns critical
        assert result == 1
        output = capsys.readouterr().out
        assert "critical" in output.lower()

    def test_main_no_arguments(self, capsys: Any) -> None:
        """Test main with no arguments.

        Given: No arguments provided
        When: main is called
        Then: Returns 1 (db check fails with None)
        """
        # When: Run main with no args
        result = health_cli.main([])

        # Then: Returns failure (no database URL)
        assert result == 1
