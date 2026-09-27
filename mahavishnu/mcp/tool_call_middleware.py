"""Local FastMCP middleware subclass that enriches tool-call spans.

REQ-TSQ-002 from ``docs/plans/2026-09-26-tool-surface-quality.md``:
the enrichment layer lives in a local subclass of
:class:`mcp_common.server.telemetry.FastMCPOpenTelemetryMiddleware`.
``mcp_common`` is NOT modified.

The subclass:
- Overrides ``on_message`` (the FastMCP middleware hook — NOT
  ``on_call_tool`` which doesn't exist; verified against
  ``mcp-common/mcp_common/server/telemetry.py:61``).
- Gates enrichment on ``context.method == "tools/call"`` so the
  overhead is paid only for tool calls, not for resources/read,
  prompts/get, notifications.
- Times the ``call_next`` invocation to produce ``duration_ms`` and
  classifies the result/exception into the closed enumeration
  ``success|error|cancelled|timeout`` mirroring
  ``_classify_tool_result`` in ``mahavishnu/mcp/server_core.py:220``.
- Reads the tool name from ``context.message.name`` (same source the
  upstream middleware uses for ``mcp.tool.name``).
- Sets attributes on the upstream's active span via
  ``opentelemetry.trace.get_current_span()``. We do NOT start a new
  span (that would create a child span and double the cardinality of
  the Akosha trace feed).

The subclass is registered AFTER the upstream in
:meth:`FastMCPServer._register_telemetry_middleware`, so it runs
INSIDE the upstream's span context. The ``task_class`` attribute set
here is what Akosha's ``query_local_traces(task_class="mcp_tool_call")``
filters on, and what the ``HealthFeedState("mcp_tool_call")`` feed wires
to.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from mcp_common.server.telemetry import FastMCPOpenTelemetryMiddleware

from .tool_call_enricher import enrich_tool_call_span

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastmcp.server.middleware import MiddlewareContext

    type CallNext = Callable[[MiddlewareContext[Any]], Awaitable[Any]]


def _extract_tool_name(context: "MiddlewareContext[Any]") -> str:
    """Return ``context.message.name`` or ``"<unknown>"`` if missing.

    Mirrors the upstream middleware's ``_component_name`` shape — for
    ``tools/call``, ``context.message.name`` is the qualified tool name.
    Falls back to a sentinel so the analyzer's per-selector breakdown
    never has a null/empty key (which would bucket every unknown call
    into the same selector and defeat the per-tool signal).
    """
    message = context.message
    name = getattr(message, "name", None)
    if isinstance(name, str) and name:
        return name
    return "<unknown>"


def _classify(call_next_result: Any, exc: BaseException | None) -> str:
    """Map a call_next outcome to the closed enumeration.

    Mirrors ``_classify_tool_result`` in
    ``mahavishnu/mcp/server_core.py:220`` plus the explicit exception
    classes that ``_wrap_tool_handler`` classifies. The two systems
    classify independently; both produce the same enumeration.
    """
    if exc is None:
        return "success"
    if isinstance(exc, asyncio.CancelledError):
        return "cancelled"
    if isinstance(exc, TimeoutError):
        return "timeout"
    return "error"


class ToolCallEnrichmentMiddleware(FastMCPOpenTelemetryMiddleware):
    """Enrich tool-call spans with task_class, selector, outcome, duration_ms.

    Subclasses the upstream telemetry middleware. The override lives
    here rather than in a separate ``add_middleware`` call so the
    enrichment lifecycle is tied to the upstream's tracing lifecycle
    (same tracer, same OTel context).
    """

    async def on_message(
        self, context: "MiddlewareContext[Any]", call_next: "CallNext"
    ) -> Any:
        """Gate on ``tools/call`` and enrich the upstream's span."""
        if context.method != "tools/call":
            # Pass through unchanged. The upstream middleware still emits
            # its own span attributes for resources/read, prompts/get,
            # notifications — we only add ours for tool calls.
            return await call_next(context)

        tool_name = _extract_tool_name(context)
        span = trace.get_current_span()
        start = time.perf_counter()
        exc: BaseException | None = None
        try:
            return await call_next(context)
        except asyncio.CancelledError as e:
            exc = e
            raise
        except TimeoutError as e:
            exc = e
            raise
        except Exception as e:
            exc = e
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            status = _classify(None, exc)
            try:
                enrich_tool_call_span(
                    span,
                    tool_name=tool_name,
                    status=status,
                    duration_ms=duration_ms,
                )
            except Exception:  # noqa: BLE001 - middleware MUST NOT raise
                # Span enrichment is best-effort. A failure here must
                # never propagate to the caller; the only consequence is
                # that Akosha won't see the per-tool signal for this call.
                # The upstream middleware's own exception recording will
                # still mark the span.
                pass
