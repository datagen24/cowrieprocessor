"""Shared pytest fixtures for Cowrie processor tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def sample_cowrie_events() -> list[dict[str, str]]:
    """Provide sample Cowrie events loaded from disk.

    Returns:
        list[dict[str, str]]: Parsed event dictionaries for smoke testing utilities.
    """
    fixture_path = Path(__file__).parent / "fixtures" / "sample_events.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    return list(data)
