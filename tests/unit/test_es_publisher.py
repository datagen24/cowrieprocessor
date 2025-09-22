"""Tests for Elasticsearch publisher helper."""

from __future__ import annotations

import importlib

import pytest

from cowrieprocessor.reporting.es_publisher import ElasticsearchPublisher


class _DummyClient:
    pass


def test_elasticsearch_publisher_builds_actions(monkeypatch):
    """Publisher should generate bulk actions with ILM aliases and doc ids."""
    recorded = {}

    class _HelpersModule:
        @staticmethod
        def bulk(client, actions):
            recorded["client"] = client
            recorded["actions"] = list(actions)

    original_import = importlib.import_module

    def _import_module(module_name: str):
        if module_name == "elasticsearch.helpers":
            return _HelpersModule
        return original_import(module_name)

    monkeypatch.setattr(importlib, "import_module", _import_module)

    publisher = ElasticsearchPublisher(_DummyClient(), index_prefix="cowrie.reports")

    publisher.publish(
        [
            {"report_type": "daily", "sensor": "alpha", "date": "2024-01-01"},
            {"report_type": "weekly", "sensor": None, "date": "2024-W01"},
        ]
    )

    actions = recorded["actions"]
    assert actions[0]["_index"] == "cowrie.reports.daily-write"
    assert actions[0]["_id"] == "alpha:daily:2024-01-01"
    assert actions[1]["_index"] == "cowrie.reports.weekly-write"
    assert actions[1]["_id"] == "aggregate:weekly:2024-W01"


def test_elasticsearch_publisher_requires_client():
    """Publisher should raise when client is missing."""
    with pytest.raises(RuntimeError):
        ElasticsearchPublisher(None, index_prefix="cowrie.reports")
