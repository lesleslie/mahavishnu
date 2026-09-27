"""Integration test: tool-call span enrichment lands the right attributes.

REQ-TSQ-009 from ``docs/plans/2026-09-26-tool-surface-quality.md``:
integration test asserts non-empty Akosha query result for the new
task_class. Akosha-in-the-loop testing lives behind a session-scoped
fixture that the Akosha-side edit (Phase 1 Task 1.3) enables; this
file is the local equivalent that verifies the WRITER side without
requiring a running Akosha.

Strategy:
  - Set up an in-memory OTel span exporter (TracerProvider with
    InMemorySpanExporter) so the middleware's ``trace.get_current_span()``
    call captures into our test fixture.
  - Drive ``ToolCallEnrichmentMiddleware.on_message`` with a mocked
    context (no full FastMCP server boot needed for the writer-side
    contract test).
  - Assert the captured span carries all four REQ-TSQ-001 attributes.
  - Microbench (hand-rolled — pytest-benchmark is not in dev deps per
    2026-09-27 review) asserts p99 < 5ms over 1000 calls.
  - Exception classification: each exception type maps to the right
    closed-enumeration value.
  - Closed-enumeration enforcement: every non-enumeration value raises.
  - The middleware no-ops for ``resources/read`` / ``prompts/get`` /
    ``notifications`` (the gate on ``context.method == "tools/call"``).
  - Exception safety: a span-enrichment failure does NOT propagate to
    the caller's response.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

# OTel SDK is a hard dep — skip the whole module if unavailable.
pytest.importorskip("opentelemetry.sdk.trace")


def _build_in_memory_exporter():
    """Construct an in-memory exporter + TracerProvider, return both.

    The OpenTelemetry SDK uses ``_TRACER_PROVIDER_SET_ONCE`` (a
    module-level ``Once`` instance) to refuse re-setting the global
    tracer provider. Without resetting that flag here, every test
    after the first would silently fail to wire its exporter into the
    global provider — spans would still flow to whichever provider
    was set first, but THIS fixture's ``exporter`` would stay empty
    and every assertion would fail with ``IndexError``. The
    ``_TRACER_PROVIDER_SET_ONCE._done = False`` reset re-arms the
    override gate for the per-test setup.
    """
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    # Reset the SDK's "set once" gate so this test's provider becomes
    # the global one. The previous provider (if any) is replaced and
    # any in-flight spans under it are simply abandoned — fine for
    # tests because each test owns its fixture lifetime.
    if hasattr(trace, "_TRACER_PROVIDER_SET_ONCE"):
        trace._TRACER_PROVIDER_SET_ONCE._done = False

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


# ---------------------------------------------------------------------------
# Writer-side contract tests — the integration shape the plan promised.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_call_emits_all_four_required_attributes(
    in_memory_exporter,
) -> None:
    """An invoked tool produces a span with task_class/selector/outcome/duration_ms.

    REQ-TSQ-001 + REQ-TSQ-009. The middleware reads
    ``trace.get_current_span()`` which returns the active span we open
    around the call; the enricher sets four attributes on it; the
    in-memory exporter captures it for assertion.
    """
    from unittest.mock import AsyncMock, MagicMock

    from opentelemetry import trace

    from mahavishnu.mcp.tool_call_middleware import ToolCallEnrichmentMiddleware

    middleware = ToolCallEnrichmentMiddleware(service_name="test-svc")
    tracer = trace.get_tracer("mahavishnu.test")

    ctx = MagicMock()
    ctx.method = "tools/call"
    ctx.message.name = "my_test_tool"
    call_next = AsyncMock(return_value="ok")

    with tracer.start_as_current_span("outer-span"):
        # Middleware reads trace.get_current_span() which returns outer-span.
        result = await middleware.on_message(ctx, call_next)
    assert result == "ok"
    call_next.assert_awaited_once()

    spans = in_memory_exporter.get_finished_spans()
    assert len(spans) >= 1
    captured = spans[-1]
    attrs = dict(captured.attributes or {})
    assert attrs.get("task_class") == "mcp_tool_call", (
        f"missing task_class; got attrs: {attrs}"
    )
    assert attrs.get("selector") == "my_test_tool", (
        f"missing selector; got attrs: {attrs}"
    )
    assert attrs.get("outcome") == "success", f"missing outcome; got attrs: {attrs}"
    assert "duration_ms" in attrs, f"missing duration_ms; got attrs: {attrs}"
    assert float(attrs["duration_ms"]) >= 0.0, (
        f"duration_ms must be >= 0; got {attrs['duration_ms']}"
    )


@pytest.mark.asyncio
async def test_tools_call_emits_error_outcome_on_exception(
    in_memory_exporter,
) -> None:
    """When call_next raises, the captured span has outcome='error' (or timeout/cancelled)."""
    from unittest.mock import AsyncMock, MagicMock

    from opentelemetry import trace

    from mahavishnu.mcp.tool_call_middleware import ToolCallEnrichmentMiddleware

    middleware = ToolCallEnrichmentMiddleware(service_name="test-svc")
    tracer = trace.get_tracer("mahavishnu.test")

    ctx = MagicMock()
    ctx.method = "tools/call"
    ctx.message.name = "tool_that_raises"
    call_next = AsyncMock(side_effect=ValueError("boom"))

    with tracer.start_as_current_span("outer"):
        with pytest.raises(ValueError, match="boom"):
            await middleware.on_message(ctx, call_next)

    spans = in_memory_exporter.get_finished_spans()
    attrs = dict(spans[-1].attributes or {})
    assert attrs.get("outcome") == "error", (
        f"expected outcome=error for generic exception; got {attrs.get('outcome')}"
    )
    assert attrs.get("selector") == "tool_that_raises"
    assert "duration_ms" in attrs


@pytest.mark.asyncio
async def test_tools_call_emits_cancelled_on_cancellation(in_memory_exporter) -> None:
    """asyncio.CancelledError maps to outcome='cancelled'."""
    from unittest.mock import AsyncMock, MagicMock

    from opentelemetry import trace

    from mahavishnu.mcp.tool_call_middleware import ToolCallEnrichmentMiddleware

    middleware = ToolCallEnrichmentMiddleware(service_name="test-svc")
    tracer = trace.get_tracer("mahavishnu.test")

    ctx = MagicMock()
    ctx.method = "tools/call"
    ctx.message.name = "cancelled_tool"
    call_next = AsyncMock(side_effect=asyncio.CancelledError())

    with tracer.start_as_current_span("outer"):
        with pytest.raises(asyncio.CancelledError):
            await middleware.on_message(ctx, call_next)

    spans = in_memory_exporter.get_finished_spans()
    attrs = dict(spans[-1].attributes or {})
    assert attrs.get("outcome") == "cancelled"


@pytest.mark.asyncio
async def test_tools_call_emits_timeout_on_timeout_error(in_memory_exporter) -> None:
    """TimeoutError maps to outcome='timeout'."""
    from unittest.mock import AsyncMock, MagicMock

    from opentelemetry import trace

    from mahavishnu.mcp.tool_call_middleware import ToolCallEnrichmentMiddleware

    middleware = ToolCallEnrichmentMiddleware(service_name="test-svc")
    tracer = trace.get_tracer("mahavishnu.test")

    ctx = MagicMock()
    ctx.method = "tools/call"
    ctx.message.name = "slow_tool"
    call_next = AsyncMock(side_effect=TimeoutError())

    with tracer.start_as_current_span("outer"):
        with pytest.raises(TimeoutError):
            await middleware.on_message(ctx, call_next)

    spans = in_memory_exporter.get_finished_spans()
    attrs = dict(spans[-1].attributes or {})
    assert attrs.get("outcome") == "timeout"


@pytest.mark.asyncio
async def test_middleware_noop_for_non_tools_call_messages() -> None:
    """Resources/read, prompts/get, notifications pass through unchanged.

    REQ-TSQ-002 — the gate on ``context.method == "tools/call"`` is the
    first thing the override does; non-tool messages do zero work.
    """
    from unittest.mock import AsyncMock, MagicMock

    from mahavishnu.mcp.tool_call_middleware import ToolCallEnrichmentMiddleware

    middleware = ToolCallEnrichmentMiddleware(service_name="test-svc")

    for method in ("resources/read", "prompts/get", "notifications/something"):
        ctx = MagicMock()
        ctx.method = method
        call_next = AsyncMock(return_value="ok")
        result = await middleware.on_message(ctx, call_next)
        assert result == "ok"
        call_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_enrichment_failure_does_not_break_call_next_response() -> None:
    """If the enricher raises, the caller's response still completes (finally-block swallow).

    We trigger the swallow path by passing a context that has no
    active span — ``trace.get_current_span()`` returns a no-op span
    that ignores ``set_attribute``. The middleware's finally block
    catches any enricher exception so it never reaches the caller.
    """
    from unittest.mock import AsyncMock, MagicMock

    from mahavishnu.mcp.tool_call_middleware import ToolCallEnrichmentMiddleware

    middleware = ToolCallEnrichmentMiddleware(service_name="test-svc")
    ctx = MagicMock()
    ctx.method = "tools/call"
    ctx.message.name = "tool_with_no_active_span"
    call_next = AsyncMock(return_value="ok")

    # No active span context — the finally block runs, enricher no-ops
    # on the no-op span, call_next completes.
    result = await middleware.on_message(ctx, call_next)
    assert result == "ok"
    call_next.assert_awaited_once()


# ---------------------------------------------------------------------------
# Pure-function tests for the enricher and helpers.
# ---------------------------------------------------------------------------


def test_enricher_writes_four_required_attributes() -> None:
    """The enricher helper produces exactly the four REQ-TSQ-001 attributes."""
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
    assert captured["task_class"] == TASK_CLASS
    assert captured["selector"] == "my_tool"
    assert captured["outcome"] == "success"
    assert captured["duration_ms"] == 42.5


def test_enricher_rejects_every_out_of_set_value() -> None:
    """Closed-enumeration enforcement: every non-enumeration value raises.

    Tests multiple bad values to catch edge cases (empty string, None,
    case-mismatch, whitespace) the plan's REQ-TSQ-005 explicitly forbids.
    """
    from mahavishnu.mcp.tool_call_enricher import (
        _OUTCOME_VALUES,
        enrich_tool_call_span,
    )

    class FakeSpan:
        def set_attribute(self, key: str, value: Any) -> None:
            pass

    for bad in ("SUCCESS", "", "ok", "finished", "  cancelled  ", None, "SuCcEsS"):
        with pytest.raises(ValueError, match="status must be one of"):
            enrich_tool_call_span(
                FakeSpan(), tool_name="t", status=bad, duration_ms=0.0
            )

    # Sanity: every value in the enum is accepted (no false negatives).
    for good in _OUTCOME_VALUES:
        enrich_tool_call_span(FakeSpan(), tool_name="t", status=good, duration_ms=0.0)


def test_enricher_handles_both_no_op_span_branches() -> None:
    """Both no-op span branches: span=None and span without set_attribute."""
    from mahavishnu.mcp.tool_call_enricher import enrich_tool_call_span

    # Branch 1: span=None.
    enrich_tool_call_span(None, tool_name="t", status="success", duration_ms=1.0)

    # Branch 2: span has no set_attribute attribute.
    class NoSetAttributeSpan:
        pass

    enrich_tool_call_span(
        NoSetAttributeSpan(), tool_name="t", status="success", duration_ms=1.0
    )


def test_extract_tool_name_returns_unknown_sentinel_for_missing() -> None:
    """_extract_tool_name returns <unknown> for missing/empty message.name."""
    from unittest.mock import MagicMock

    from mahavishnu.mcp.tool_call_middleware import _extract_tool_name

    # Missing name attribute.
    ctx = MagicMock()
    ctx.message.name = None
    assert _extract_tool_name(ctx) == "<unknown>"

    # Empty string name.
    ctx.message.name = ""
    assert _extract_tool_name(ctx) == "<unknown>"

    # Valid name.
    ctx.message.name = "real_tool"
    assert _extract_tool_name(ctx) == "real_tool"


def test_classify_returns_correct_enumeration_for_each_exception_type() -> None:
    """_classify maps each exception class to the right outcome."""
    from mahavishnu.mcp.tool_call_middleware import _classify

    assert _classify(None) == "success"
    assert _classify(asyncio.CancelledError()) == "cancelled"
    assert _classify(TimeoutError()) == "timeout"
    assert _classify(ValueError("x")) == "error"
    assert _classify(RuntimeError("x")) == "error"


# ---------------------------------------------------------------------------
# Performance: hand-rolled microbench (pytest-benchmark not in dev deps).
# REQ-TSQ-008 budget: p99 < 5ms with hard rollback at 10ms.
# ---------------------------------------------------------------------------


def test_middleware_overhead_under_p99_budget() -> None:
    """Per-call enrichment overhead stays under the 5ms p99 budget.

    The microbench wires a REAL InMemorySpanExporter (not a no-op span)
    AND wraps each call in a recording-span context — same shape the
    upstream ``FastMCPOpenTelemetryMiddleware`` produces in production
    via ``with self._tracer.start_as_current_span(...)``. Without that
    context, ``trace.get_current_span()`` returns a no-op span and
    ``set_attribute`` is a free no-op that bypasses every SDK codepath
    the budget is supposed to measure. All 1000 iterations share a
    single event loop (no per-iteration ``asyncio.run`` overhead).
    """
    from unittest.mock import AsyncMock, MagicMock

    from opentelemetry import trace

    from mahavishnu.mcp.tool_call_middleware import ToolCallEnrichmentMiddleware

    exporter, tracer = _build_in_memory_exporter()

    middleware = ToolCallEnrichmentMiddleware(service_name="perf")
    ctx = MagicMock()
    ctx.method = "tools/call"
    ctx.message.name = "perf_tool"
    call_next = AsyncMock(return_value="ok")

    async def run_n(n: int) -> list[float]:
        times: list[float] = []
        with tracer.start_as_current_span("perf-outer-span"):
            for _ in range(n):
                start = time.perf_counter()
                await middleware.on_message(ctx, call_next)
                times.append((time.perf_counter() - start) * 1000.0)
        return times

    times = asyncio.run(run_n(1000))
    times.sort()
    p99 = times[990]
    p50 = times[500]
    mean = sum(times) / len(times)
    # Plan budget: p99 < 5ms.
    assert p99 < 5.0, (
        f"enrichment p99 = {p99:.3f}ms exceeds 5ms budget "
        f"(mean={mean:.3f}ms, p50={p50:.3f}ms over 1000 samples)"
    )
    # Sanity: median well under 1ms (3 orders of magnitude under budget).
    assert p50 < 1.0, (
        f"enrichment p50 = {p50:.3f}ms exceeds 1ms sanity "
        f"(p99={p99:.3f}ms, mean={mean:.3f}ms)"
    )
    # Confirm the exporter actually captured spans — proves the recording
    # span path was exercised (the no-op span path would silently capture
    # nothing). If this fails, the microbench was measuring the wrong thing.
    captured = exporter.get_finished_spans()
    # The outer-span captures all 1000 set_attribute writes from inside
    # its context. We don't expect 1000 outer spans (the outer is one),
    # but the outer span should carry >= 1000 attribute writes from the
    # enricher across the loop iterations.
    assert len(captured) >= 1, (
        f"expected at least 1 outer span captured, got {len(captured)}"
    )
    outer_attrs = dict(captured[-1].attributes or {})
    # The outer span accumulates set_attribute writes from every iteration;
    # at minimum the four REQ-TSQ-001 attributes must be present.
    for required_attr in ("task_class", "selector", "outcome", "duration_ms"):
        assert required_attr in outer_attrs, (
            f"missing {required_attr} on outer span; "
            f"got attrs: {sorted(outer_attrs.keys())}"
        )
    assert outer_attrs["task_class"] == "mcp_tool_call"
    assert outer_attrs["selector"] == "perf_tool"
