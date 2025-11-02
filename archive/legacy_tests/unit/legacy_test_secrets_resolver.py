"""Smoke tests covering secret resolution helpers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from secrets_resolver import is_reference, resolve_secret, set_env_if_ref


def test_is_reference_detects_supported_prefixes() -> None:
    """Confirm that reference detection handles all supported schemes.

    Returns:
        None: The test passes when each sample value is recognized as a reference.
    """
    references = [
        "env:API_KEY",
        "file:/tmp/secret",
        "op://vault/item/field",
        "aws-sm://us-east-1/my-secret#token",
        "vault://kv/data#password",
        "sops://secure.json#apiKey",
        "${SOME_ENV}",
    ]

    for value in references:
        assert is_reference(value)


def test_is_reference_returns_false_for_literals() -> None:
    """Ensure plain strings are not mistaken for secret references.

    Returns:
        None: The test passes when literal inputs are not flagged as references.
    """
    assert not is_reference("plain-text-value")


def test_resolve_secret_env_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure environment backed references round-trip through resolution.

    Args:
        monkeypatch: Pytest helper for temporary environment overrides.

    Returns:
        None: The test passes when the resolved value matches the environment.
    """
    monkeypatch.setenv("TEST_SECRET", "resolved-value")

    resolved = resolve_secret("env:TEST_SECRET")

    assert resolved == "resolved-value"


def test_resolve_secret_literal_passthrough() -> None:
    """Ensure literal values are returned unchanged by the resolver.

    Returns:
        None: The test passes when the input string is returned verbatim.
    """
    assert resolve_secret("literal") == "literal"


def test_resolve_secret_file_reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate file-based references and environment mutation helper.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest helper for temporary environment overrides.

    Returns:
        None: The test passes when secrets are loaded and exported to the environment.
    """
    secret_path = tmp_path / "secret.txt"
    secret_path.write_text("swordfish", encoding="utf-8")
    env: dict[str, str] = {}

    resolved = set_env_if_ref(env, "SECRET", f"file:{secret_path}")

    assert resolved == "swordfish"
    assert env["SECRET"] == "swordfish"
    assert os.getenv("SECRET") is None


def test_set_env_if_ref_handles_non_reference_values() -> None:
    """Verify that literal values are set in the environment mapping.

    Returns:
        None: The test passes when literals propagate into the env dict.
    """
    env: dict[str, str] = {}

    resolved = set_env_if_ref(env, "TOKEN", "literal")

    assert resolved == "literal"
    assert env["TOKEN"] == "literal"
