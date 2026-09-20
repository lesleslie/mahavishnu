"""OpenTelemetry instrumentation + structured log lines for the ACP server.

Per plan §Phase 2 Task 5. Provides:

- :func:`get_session_tracer` — returns the ``mahavishnu.acp.session``
  tracer (no-op ``None`` if OpenTelemetry is not configured).
- :class:`SessionSpanContext` — context manager that wraps an
  ``execute_fn`` invocation in an OTel span with the four attributes
  the plan enumerates (``session.id``, ``session.stop_reason``,
  ``session.duration_ms``, ``session.status``).
- :func:`emit_session_completed_log` — emits the structured
  ``acp.session_completed`` log line.

If OpenTelemetry isn't installed or no provider is configured, all
operations are no-ops. The dispatcher test (``test_observability_validation``)
sets up an in-memory exporter and asserts on the captured spans.
"""

from __future__ import annotations

from collections.abc import Iterator  # noqa: TC003 — used as the return type of the contextmanager
from contextlib import contextmanager
import logging
import time
from typing import Any

logger = logging.getLogger("mahavishnu.acp.observability")

# OpenTelemetry is an optional dependency in some environments. We
# import lazily so the rest of the ACP server works without it.
_OTEL_IMPORT_ERROR: Exception | None = None
try:
    from opentelemetry import trace  # type: ignore[import-untyped]
    from opentelemetry.trace import Status, StatusCode, Tracer  # type: ignore[import-untyped]

    _OTEL_AVAILABLE = True
except ImportError as exc:  # pragma: no cover — exercised when OTel missing
    _OTEL_AVAILABLE = False
    _OTEL_IMPORT_ERROR = exc
    trace = None  # type: ignore[assignment]
    Status = None  # type: ignore[assignment,misc]
    StatusCode = None  # type: ignore[assignment,misc]
    Tracer = None  # type: ignore[assignment,misc]


def get_session_tracer() -> Any:
    """Return the ACP session tracer, or ``None`` if OTel isn't configured.

    A ``None`` return signals to the caller that span emission is a
    no-op. The dispatcher must still emit structured log lines
    regardless of OTel state.
    """
    if not _OTEL_AVAILABLE:
        return None
    try:
        return trace.get_tracer("mahavishnu.acp.session")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 — best-effort init; missing provider is expected
        # Provider not configured or other init issue — treat as no-op.
        return None


def is_otel_active() -> bool:
    """Return True if a real tracer provider is configured and spans will be recorded.

    Used by the validation test to skip when no exporter is configured
    (the plan's explicit requirement: "If the OTel exporter is not
    configured for the test environment, the test must explicitly skip
    with a clear reason (not silently pass)").
    """
    if not _OTEL_AVAILABLE or trace is None:
        return False
    try:
        provider = trace.get_tracer_provider()
        # The default tracer provider is a no-op ProxyTracer; check if
        # it's been overridden with a real provider.
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-untyped]

        return isinstance(provider, TracerProvider)
    except Exception:
        return False


@contextmanager
def session_span(
    session_id: str,
    *,
    attributes: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Wrap an ``execute_fn`` invocation in a span with the plan's 4 attributes.

    Yields a mutable dict the caller uses to record the outcome:

    .. code-block:: python

        with session_span(session_id) as span_state:
            try:
                result = await execute_fn(...)
                span_state["stop_reason"] = "completed"
                span_state["status"] = "ok"
            except Exception:
                span_state["stop_reason"] = "error"
                span_state["status"] = "error"
                raise

    The context manager sets the OTel span attributes from ``span_state``
    on exit and emits the ``acp.session_completed`` log line. If OTel
    isn't configured, the span emission is skipped but the log line
    still fires.
    """
    state: dict[str, Any] = {
        "stop_reason": "unknown",
        "status": "unknown",
    }
    tracer = get_session_tracer()
    start_ms = time.time() * 1000.0
    if tracer is not None:
        with tracer.start_as_current_span("mahavishnu.acp.session") as span:
            span.set_attribute("session.id", session_id)
            for k, v in (attributes or {}).items():
                try:
                    span.set_attribute(k, v)
                except Exception:  # noqa: BLE001 — non-string attrs are skipped silently
                    pass
            try:
                yield state
            finally:
                duration_ms = time.time() * 1000.0 - start_ms
                span.set_attribute("session.stop_reason", state["stop_reason"])
                span.set_attribute("session.duration_ms", duration_ms)
                span.set_attribute("session.status", state["status"])
                if state["status"] == "error":
                    try:
                        span.set_status(Status(StatusCode.ERROR))  # type: ignore[arg-type]
                    except Exception:
                        pass
                logger.info(
                    "acp.session_completed session_id=%s stop_reason=%s duration_ms=%.1f",
                    session_id,
                    state["stop_reason"],
                    duration_ms,
                )
    else:
        # OTel not configured — no span, but still emit the log line.
        try:
            yield state
        finally:
            duration_ms = time.time() * 1000.0 - start_ms
            logger.info(
                "acp.session_completed session_id=%s stop_reason=%s duration_ms=%.1f",
                session_id,
                state["stop_reason"],
                duration_ms,
            )


__all__ = [
    "get_session_tracer",
    "is_otel_active",
    "session_span",
]
