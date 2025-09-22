"""Utilities for publishing loader telemetry to status files."""

from __future__ import annotations

import json
import threading
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .loader.bulk import BulkLoaderMetrics, LoaderCheckpoint

_DEFAULT_STATUS_DIR = Path("/mnt/dshield/data/logs/status")


def _to_dict(obj: Any) -> Dict[str, Any]:
    if hasattr(obj, "__dataclass_fields__"):
        if is_dataclass(obj):
            try:
                return _normalize({field.name: getattr(obj, field.name) for field in fields(obj)})
            except TypeError:
                pass
        dataclass_fields = getattr(obj, "__dataclass_fields__")
        return _normalize({name: getattr(obj, name) for name in dataclass_fields})
    if hasattr(obj, "__dict__"):
        return _normalize(dict(obj.__dict__))
    if isinstance(obj, dict):
        return _normalize(dict(obj))
    raise TypeError(f"Unsupported object type for status serialization: {type(obj)!r}")


class StatusEmitter:
    """Writes loader progress to JSON files consumable by monitors."""

    def __init__(self, phase: str, status_dir: str | Path | None = None) -> None:
        """Create an emitter for the given ingest phase."""
        self.phase = phase
        self.status_dir = Path(status_dir) if status_dir else _DEFAULT_STATUS_DIR
        self.status_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.status_dir / f"{phase}.json"
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = {
            "phase": phase,
            "ingest_id": None,
            "last_updated": None,
            "metrics": {},
            "checkpoint": {},
            "dead_letter": {"total": 0},
        }
        self._dead_letter_total = 0

    def record_metrics(self, metrics: BulkLoaderMetrics) -> None:
        """Persist the latest loader metrics snapshot."""
        with self._lock:
            metrics_dict = _to_dict(metrics)
            self._state["ingest_id"] = metrics.ingest_id
            self._state["metrics"] = metrics_dict
            self._state["last_updated"] = datetime.now(UTC).isoformat()
            self._write_state()

    def record_checkpoint(self, checkpoint: LoaderCheckpoint) -> None:
        """Update the emitted status with the latest batch checkpoint."""
        with self._lock:
            checkpoint_dict = _to_dict(checkpoint)
            self._state["checkpoint"] = checkpoint_dict
            self._write_state()

    def record_dead_letters(
        self,
        count: int,
        last_reason: Optional[str] = None,
        last_source: Optional[str] = None,
    ) -> None:
        """Increment dead-letter totals and note the latest failure context."""
        if count <= 0:
            return
        with self._lock:
            self._dead_letter_total += count
            self._state.setdefault("dead_letter", {})
            dead_letter = self._state["dead_letter"]
            if isinstance(dead_letter, dict):
                dead_letter["total"] = self._dead_letter_total
                dead_letter["last_reason"] = last_reason
                dead_letter["last_source"] = last_source
                dead_letter["last_updated"] = datetime.now(UTC).isoformat()
            self._write_state()

    def _write_state(self) -> None:
        tmp_path = self.path.with_suffix(".tmp")
        payload = json.dumps(self._state, separators=(",", ":"))
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(self.path)


def _normalize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(val) for key, val in value.items()}
    return value


__all__ = ["StatusEmitter"]
