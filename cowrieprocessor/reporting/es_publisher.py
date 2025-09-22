"""Elasticsearch publishing helpers."""

from __future__ import annotations

import importlib
from typing import Any, Dict, Iterable, Optional


class ElasticsearchPublisher:
    """Publish reports to Elasticsearch with optional bulk indexing."""

    def __init__(
        self,
        client: Any,
        index_prefix: str,
        pipeline: Optional[str] = None,
    ) -> None:
        """Initialise the publisher with an Elasticsearch client and index naming."""
        if client is None:
            raise RuntimeError("Elasticsearch client is not available; install elasticsearch package")
        self.client = client
        self.index_prefix = index_prefix
        self.pipeline = pipeline

    def publish(self, reports: Iterable[Dict[str, Any]]) -> None:
        """Bulk index the provided report documents."""
        actions = []
        for report in reports:
            index_name = f"{self.index_prefix}-{report['report_type']}"
            action: Dict[str, Any] = {
                "_index": index_name,
                "_source": report,
            }
            if self.pipeline:
                action["pipeline"] = self.pipeline
            actions.append(action)
        if not actions:
            return
        try:
            helpers_module = importlib.import_module("elasticsearch.helpers")
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RuntimeError("Elasticsearch helpers are not available") from exc
        helpers_module.bulk(self.client, actions)
