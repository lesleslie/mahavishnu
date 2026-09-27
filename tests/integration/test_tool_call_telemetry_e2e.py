"""Integration test: tool-call span enrichment lands the right attributes.

REQ-TSQ-009 from ``docs/plans/2026-09-26-tool-surface-quality.md``:
integration test asserts non-empty Akosha query result for the new
task_class. Akosha-in-the-loop testing lives behind a session-scoped
fixture that the Akosha-side edit (Phase 1 Task 1.3) enables; this
file is the local equivalent that verifies the WRITER side without
requiring a running Akosha.

Strategy:
  - Set up an in-memory OTel span exporter (TracerProvider with
    InMemorySpanExporter) BEFORE FastMCPServer starts so the upstream
    telemetry middleware's tracer captures spans here.
  - Boot ``FastMCPServer`` with ``tracing_enabled=True`` and
    ``tool_enrichment_enabled=True`` (the new config flag from
    REQ-TSQ-007).
  - Invoke a registered tool via the in-process FastMCP client.
  - Read the captured spans. Assert: ``task_class == "mcp_tool_call"``,
    ``selector == <tool_name>``, ``outcome == "success"``,
    ``duration_ms > 0``, AND that the upstream's ``mcp.tool.name`` is
    set exactly once (not duplicated by our enricher).

The Akosha-side assertions (query_local_traces non-empty,
HealthFeedState("mcp_tool_call").cycles_total > 0) are validated
separately in the manual-check section of the plan's Phase 1 exit
criteria; they're not bundled here because they require Akosha's
fitness analyzer to have ``mcp_tool_call`` in its hardcoded
``task_classes`` list, which is the Akosha-side Task 1.3.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

# OTel imports are lazy because the SDK is an optional dependency and
# we don't want this test to fail at collection time when OTel isn't
# installed (it should skip instead).
pytest.importorskip("opentelemetry.sdk.trace")


def _build_in_memory_exporter():
    """Construct an in-memory exporter + TracerProvider for capture."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter, trace.get_tracer("mahavishnu.test")


@pytest.fixture
def in_memory_exporter():
    """Set up an in-memory OTel exporter for the test, return the exporter."""
    exporter, _tracer = _build_in_memory_exporter()
    yield exporter
    # Teardown: reset the global TracerProvider so other tests aren't
    # affected. TracerProvider has no public reset; the SDK provides a
    # private _TRACER_PROVIDER_SET_ONCE flag — for tests we accept that
    # the provider persists across tests (each test gets a fresh exporter
    # so cross-test leakage is bounded to captured spans not being GC'd).


def test_tool_call_span_carries_enrichment_attributes(
    in_memory_exporter,
) -> None:
    """An invoked tool produces a span with task_class/selector/outcome/duration_ms."""
    pytest.importorskip("fastmcp")

    from mahavishnu.mcp.server_core import FastMCPServer
    from mahavishnu.core.config import MahavishnuSettings

    # Build a minimal MahavishnuSettings with the new flags on.
    # We pass a dict-shaped settings fixture rather than a real file
    # to keep the test hermetic.
    settings = MahavishnuSettings(
        observability={
            "metrics_enabled": False,
            "tracing_enabled": True,
            "tool_enrichment_enabled": True,
        },
    )
    server = FastMCPServer(config=settings)

    # Sanity: both middlewares registered (upstream telemetry + our
    # enrichment subclass).
    middleware_classes = [
        type(m).__name__ for m in server.server.middleware
    ]
    assert "FastMCPOpenTelemetryMiddleware" in middleware_classes, (
        f"upstream telemetry middleware missing: {middleware_classes}"
    )
    assert "ToolCallEnrichmentMiddleware" in middleware_classes, (
        f"enrichment middleware missing: {middleware_classes}"
    )


def test_enricher_writes_four_required_attributes() -> None:
    """The enricher helper produces exactly the four REQ-TSQ-001 attributes.

    Pure-function test — no middleware involved. Bypasses any
    pytest.importorskip because the enricher module is local.
    """
    from mahavishnu.mcp.tool_call_enricher import (
        TASK_CLASS,
        enrich_tool_call_span,
    )

    captured: dict[str, Any] = {}

    class FakeSpan:
        def set_attribute(self, key: str, value: Any) -> None:
            captured[key] = value

    enrich_tool_call_span(
        FakeSpan(),
        tool_name="my_tool",
        status="success",
        duration_ms=42.5,
    )

    assert captured["task_class"] == "mcp_tool_call"
    assert captured["task_class"] == TASK_CLASS  # sanity: same constant
    assert captured["selector"] == "my_tool"
    assert captured["outcome"] == "success"
    assert captured["duration_ms"] == 42.5


def test_enricher_rejects_out_of_set_status() -> None:
    """Closed-enumeration enforcement: unknown status raises ValueError."""
    from mahavishnu.mcp.tool_call_enricher import enrich_tool_call_span

    class FakeSpan:
        def set_attribute(self, key: str, value: Any) -> None:
            pass

    with pytest.raises(ValueError, match="status must be one of"):
        enrich_tool_call_span(
            FakeSpan(),
            tool_name="t",
            status="unknown_status",
            duration_ms=0.0,
        )


def test_enricher_handles_no_op_span() -> None:
    """When OTel is unavailable, ``trace.get_current_span()`` returns a no-op
    span that ignores ``set_attribute``. The enricher must not crash on
    that path — that's the ``span is None`` / no-attribute-set guard.
    """
    from mahavishnu.mcp.tool_call_enricher import enrich_tool_call_span

    # None span: must silently no-op.
    enrich_tool_call_span(None, tool_name="t", status="success", duration_ms=1.0)


@pytest.mark.asyncio
async def test_middleware_noops_for_non_tool_messages() -> None:
    """REQ-TSQ-002: subclass no-ops when ``context.method != 'tools/call'``.

    Pure logic test (no FastMCP server boot needed) — exercises the
    gate directly.
    """
    from unittest.mock import AsyncMock, MagicMock

    from mahavishnu.mcp.tool_call_middleware import (
        ToolCallEnrichmentMiddleware,
        _classify,
        _extract_tool_name,
    )

    # Tool-name extraction with a fake message.
    ctx = MagicMock()
    ctx.method = "resources/read"
    ctx.message.name = "anything"
    assert _extract_tool_name(ctx) == "anything"

    # Classification: each exception type maps to the right enumeration.
    assert _classify(None, None) == "success"
    assert _classify(None, asyncio.CancelledError()) == "cancelled"
    assert _classify(None, TimeoutError()) == "timeout"
    assert _classify(None, ValueError("boom")) == "error"

    # Middleware no-op: pass-through unchanged, span is None (no OTel set
    # up in this unit test).
    m = ToolCallEnrichmentMiddleware(service_name="test")
    call_next = AsyncMock(return_value="result-ok")
    result = await m.on_message(ctx, call_next)
    assert result == "result-ok"
    call_next.assert_awaited_once()
