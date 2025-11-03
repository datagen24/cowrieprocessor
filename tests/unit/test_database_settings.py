"""Unit tests for database settings and engine helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from cowrieprocessor.db import create_engine_from_settings, create_session_maker
from cowrieprocessor.settings import DatabaseSettings, load_database_settings


def test_default_settings_use_sqlite_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Settings fall back to a local SQLite URL when no overrides exist."""
    monkeypatch.delenv("COWRIEPROC_DB_URL", raising=False)
    monkeypatch.delenv("COWRIEPROC_DB_PATH", raising=False)

    settings = load_database_settings()
    assert settings.url.startswith("sqlite:///"), "default URL should target SQLite"


def test_env_overrides_database_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Explicit DB URL environment variable takes precedence."""
    db_path = tmp_path / "custom.sqlite"
    monkeypatch.setenv("COWRIEPROC_DB_URL", f"sqlite:///{db_path}")
    settings = load_database_settings()
    assert settings.url.endswith(str(db_path))


def test_env_path_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """DB path override is translated into a SQLite URL when URL is unset."""
    db_path = tmp_path / "path.sqlite"
    monkeypatch.delenv("COWRIEPROC_DB_URL", raising=False)
    monkeypatch.setenv("COWRIEPROC_DB_PATH", str(db_path))
    settings = load_database_settings()
    assert settings.url.endswith(str(db_path))


@pytest.mark.parametrize("wal", [True, False])
def test_sqlite_engine_pragmas(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, wal) -> None:
    """SQLite engines apply WAL preference and fallback PRAGMAs consistently."""
    db_path = tmp_path / "engine.sqlite"
    settings = DatabaseSettings(
        url=f"sqlite:///{db_path}",
        sqlite_wal=wal,
        sqlite_journal_fallback="DELETE",
        sqlite_cache_size=-1024,
        sqlite_synchronous="NORMAL",
    )

    engine = create_engine_from_settings(settings)

    with engine.connect() as conn:
        journal_mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar_one()
        assert journal_mode.lower() in {"wal", settings.sqlite_journal_fallback.lower()}
        cache_size = conn.exec_driver_sql("PRAGMA cache_size").scalar_one()
        assert cache_size == settings.sqlite_cache_size

    session_factory = create_session_maker(engine)
    with session_factory() as session:
        assert session.bind is engine


def test_settings_pool_options_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pool related environment variables populate the settings object."""
    monkeypatch.setenv("COWRIEPROC_DB_POOL_SIZE", "5")
    monkeypatch.setenv("COWRIEPROC_DB_POOL_TIMEOUT", "55")
    monkeypatch.setenv("COWRIEPROC_DB_SQLITE_WAL", "false")
    settings = load_database_settings()
    assert settings.pool_size == 5
    assert settings.pool_timeout == 55
    assert settings.sqlite_wal is False
