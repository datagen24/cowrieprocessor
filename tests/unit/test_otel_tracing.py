"""Tests for optional OpenTelemetry integration helpers."""

from __future__ import annotations
import pytest

from cowrieprocessor.telemetry import otel


def test_start_span_no_op_when_trace_missing() -> None:
    """start_span should yield None when opentelemetry is unavailable."""
    original_trace = getattr(otel, "trace", None)
    otel.trace = None

    with otel.start_span("test-span") as span:
        assert span is None

    otel.trace = original_trace


def test_start_span_passes_through_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Errors inside the context should propagate even without OTEL."""
    original_trace = getattr(otel, "trace", None)
    otel.trace = None

    class CustomError(Exception):
        pass

    try:
        with otel.start_span("error-span"):
            raise CustomError("boom")
    except CustomError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("CustomError was not raised")

    otel.trace = original_trace
