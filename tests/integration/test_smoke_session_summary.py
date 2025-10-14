"""Legacy smoke tests for the removed data_processing module."""

from __future__ import annotations

import pytest

pytest.skip(
    "Legacy data_processing module retired; functionality covered elsewhere",
    allow_module_level=True,
)


def test_session_summary_smoke(sample_cowrie_events: list[dict[str, str]]) -> None:
    """Validate a high-level summary flow over sample event data.

    Args:
        sample_cowrie_events: Fixture-supplied Cowrie event dictionaries.

    Returns:
        None: The test passes when the combined helpers surface expected details.
    """
    indexed = pre_index_data_by_session(sample_cowrie_events)
    login = get_login_data("c0ffee-01", sample_cowrie_events)
    downloads = get_file_download("c0ffee-01", sample_cowrie_events)

    assert "c0ffee-01" in indexed
    assert login == ("root", "password", "2024-09-28T12:00:05Z", "203.0.113.10")
    assert len(downloads) == 2
    assert downloads[1][2] == "malicious.example.com"
