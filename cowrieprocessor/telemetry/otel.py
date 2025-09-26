"""OpenTelemetry integration helpers with graceful fallback when unavailable."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional, cast

try:  # pragma: no cover - optional dependency
    from opentelemetry import trace as _trace
    from opentelemetry.trace import Status as _Status
    from opentelemetry.trace import StatusCode as _StatusCode
except ModuleNotFoundError:  # pragma: no cover - executed in environments without OTEL
    _trace = None
    _Status = None
    _StatusCode = None

trace: Optional[Any] = cast(Optional[Any], _trace)
Status: Optional[Any] = cast(Optional[Any], _Status)
StatusCode: Optional[Any] = cast(Optional[Any], _StatusCode)


def _span_set_attributes(span: Any, attributes: Optional[Dict[str, Any]]) -> None:
    if span is None or attributes is None:
        return
    set_attribute = getattr(span, "set_attribute", None)
    if set_attribute is None:
        return
    for key, value in attributes.items():
        if value is not None:
            set_attribute(key, value)


@contextmanager
def start_span(name: str, attributes: Optional[Dict[str, Any]] = None) -> Iterator[Any]:
    """Start an OpenTelemetry span if tracing is available."""
    if trace is None:
        yield None
        return

    tracer = cast(Any, trace).get_tracer("cowrieprocessor")
    with tracer.start_as_current_span(name) as span:
        _span_set_attributes(span, attributes)
        try:
            yield span
        except Exception as exc:  # pragma: no cover - passthrough for tracing
            if span is not None:
                record_exception = getattr(span, "record_exception", None)
                if callable(record_exception):
                    record_exception(exc)
                if Status is not None and StatusCode is not None:
                    try:
                        span.set_status(Status(StatusCode.ERROR, str(exc)))
                    except Exception:
                        pass
            raise
