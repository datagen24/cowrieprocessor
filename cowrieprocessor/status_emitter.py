"""Utilities for publishing loader telemetry to status files."""

from __future__ import annotations

import json
import threading
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Optional

# LoaderCheckpoint imported lazily to avoid circular imports

_DEFAULT_STATUS_DIR = Path("/mnt/dshield/data/logs/status")


def _to_dict(obj: Any) -> Dict[str, Any]:
    if hasattr(obj, "__dataclass_fields__"):
        if is_dataclass(obj):
            try:
                result = _normalize({field.name: getattr(obj, field.name) for field in fields(obj)})
                if isinstance(result, dict):
                    return result
                else:
                    return {}
            except TypeError:
                pass
        dataclass_fields = getattr(obj, "__dataclass_fields__")
        result = _normalize({name: getattr(obj, name) for name in dataclass_fields})
        if isinstance(result, dict):
            return result
        else:
            return {}
    if hasattr(obj, "__dict__"):
        result = _normalize(dict(obj.__dict__))
        if isinstance(result, dict):
            return result
        else:
            return {}
    if isinstance(obj, dict):
        result = _normalize(dict(obj))
        if isinstance(result, dict):
            return result
        else:
            return {}
    raise TypeError(f"Unsupported object type for status serialization: {type(obj)!r}")


class StatusEmitter:
    """Writes loader/reporting progress to JSON files consumable by monitors."""

    def __init__(
        self,
        phase: str,
        status_dir: str | Path | None = None,
        *,
        aggregate: bool = True,
    ) -> None:
        """Create an emitter for the given ingest phase."""
        self.phase = phase
        self.status_dir = Path(status_dir) if status_dir else _DEFAULT_STATUS_DIR
        self.status_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.status_dir / f"{phase}.json"
        self._aggregate_enabled = aggregate
        self._aggregate_path = self.status_dir / "status.json"
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

    def record_metrics(self, metrics: Any) -> None:
        """Persist the latest loader metrics snapshot."""
        with self._lock:
            metrics_dict = _to_dict(metrics)
            ingest_id = metrics_dict.get("ingest_id") or getattr(metrics, "ingest_id", None)
            if ingest_id:
                self._state["ingest_id"] = ingest_id
            metrics_dict = _enhance_metrics(metrics_dict)
            self._state["metrics"] = metrics_dict
            self._state["last_updated"] = datetime.now(UTC).isoformat()
            self._write_state()

    def record_checkpoint(self, checkpoint: Any) -> None:
        """Update the emitted status with the latest batch checkpoint."""
        # Lazy import to avoid circular dependency

        with self._lock:
            checkpoint_dict = _to_dict(checkpoint)
            self._state["checkpoint"] = checkpoint_dict
            self._state["last_updated"] = datetime.now(UTC).isoformat()
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
            self._state["last_updated"] = datetime.now(UTC).isoformat()
            self._write_state()

    def _write_state(self) -> None:
        tmp_path = self.path.with_suffix(".tmp")
        payload = json.dumps(self._state, separators=(",", ":"))
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(self.path)
        if self._aggregate_enabled:
            self._update_aggregate()

    def _update_aggregate(self) -> None:
        """Update the consolidated status file with the current phase snapshot."""
        aggregate_snapshot = {
            "phase": self.phase,
            "ingest_id": self._state.get("ingest_id"),
            "last_updated": self._state.get("last_updated"),
            "metrics": self._state.get("metrics", {}),
            "checkpoint": self._state.get("checkpoint", {}),
            "dead_letter": self._state.get("dead_letter", {}),
            "status_file": self.path.name,
        }

        try:
            current = json.loads(self._aggregate_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            current = {}
        except json.JSONDecodeError:
            current = {}

        phases = current.get("phases", {})
        phases[self.phase] = aggregate_snapshot
        aggregate = {
            "last_updated": datetime.now(UTC).isoformat(),
            "phases": phases,
        }

        aggregate_tmp = self._aggregate_path.with_suffix(".tmp")
        aggregate_tmp.write_text(json.dumps(aggregate, separators=(",", ":")), encoding="utf-8")
        aggregate_tmp.replace(self._aggregate_path)


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


def _enhance_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Add derived telemetry fields to metrics dictionaries."""
    duration = metrics.get("duration_seconds") or 0
    if duration and duration > 0:
        if metrics.get("events_inserted") is not None:
            events = metrics.get("events_inserted") or 0
            metrics["events_per_second"] = round(events / duration, 2)
        if metrics.get("reports_generated") is not None:
            reports = metrics.get("reports_generated") or 0
            metrics["reports_per_second"] = round(reports / duration, 2)

    files_processed = metrics.get("files_processed")
    events_inserted = metrics.get("events_inserted")
    if files_processed and files_processed > 0 and events_inserted is not None:
        metrics["events_per_file"] = round((events_inserted or 0) / files_processed, 2)

    return metrics


__all__ = ["StatusEmitter"]
