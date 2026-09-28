"""Span-attribute enrichment for tool-call traces.

REQ-TSQ-001 / REQ-TSQ-004 / REQ-TSQ-005 / REQ-TSQ-006 from
``docs/plans/2026-09-26-tool-surface-quality.md``: enrich tool-call spans
with the four attributes Akosha's fitness analyzer consumes plus the
``task_class`` key it filters on:

    - ``task_class="mcp_tool_call"`` — the filter key for
      ``query_local_traces(task_class=...)`` and the
      ``HealthFeedState("mcp_tool_call")`` feed wiring.
    - ``selector=<tool_name>`` — the per-tool breakdown key in
      ``akosha/processing/fitness_analyzer.py:174-181`` (NOT
      ``mcp.tool.name``; that one is set by the upstream middleware
      and we deliberately do not duplicate it).
    - ``outcome=<status>`` — closed enumeration
      (``success|error|cancelled|timeout``) consumed by the analyzer's
      failure_rate computation.
    - ``duration_ms=<float>`` — consumed by the analyzer's p99 latency
      computation.

This module is intentionally a pure helper. It is called by
:class:`mahavishnu.mcp.tool_call_middleware.ToolCallEnrichmentMiddleware`
which owns the timing and method gating.

No PII / secret capture. No tool arguments or return values written to
the span. The four attributes are bounded-cardinality and categorical.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from opentelemetry.trace import Span

# Closed enumeration of outcome values; mirrors ``_classify_tool_result``
# in ``mahavishnu/mcp/server_core.py:220`` so the analyzer's per-tool
# failure_rate computation has signal. Do NOT extend this set without
# also extending the analyzer's outcome-handling.
_OUTCOME_VALUES: Final[frozenset[str]] = frozenset({"success", "error", "cancelled", "timeout"})

# Filter key for Akosha's ``query_local_traces(task_class=...)``. Hardcoded
# so a typo on the writer side surfaces as a missing task_class in Akosha
# rather than a silent cardinality blow-up.
TASK_CLASS: Final[str] = "mcp_tool_call"


def enrich_tool_call_span(
    span: Span,
    *,
    tool_name: str,
    status: str,
    duration_ms: float,
) -> None:
    """Set task_class, selector, outcome, duration_ms on the given span.

    Idempotent. Safe to call with ``span=None`` (used in tests; the
    middleware passes ``trace.get_current_span()`` at runtime which may be
    a no-op span when tracing is disabled).

    Args:
        span: The OpenTelemetry span to enrich. Obtained from
            ``opentelemetry.trace.get_current_span()`` at call time.
        tool_name: The tool's qualified name (``context.message.name``).
            Used as ``selector`` so the analyzer's per-tool breakdown keys
            correctly. Already public via ``tools/list`` — no PII risk.
        status: Closed enumeration from ``_OUTCOME_VALUES``.
            ``outcome="success|error|cancelled|timeout"``.
        duration_ms: Wall-clock duration of the tool call in
            milliseconds. Bounded; no PII.

    Raises:
        ValueError: If ``status`` is not in ``_OUTCOME_VALUES``. Fail-fast
            rather than silently write a value the analyzer can't parse.
    """
    if status not in _OUTCOME_VALUES:
        raise ValueError(f"status must be one of {sorted(_OUTCOME_VALUES)}, got {status!r}")
    if span is None:
        return
    if not hasattr(span, "set_attribute"):
        return

    # 2026-09-28 trace-pipeline Phase 1.5 fix: Akosha's _normalize_span reads
    # the ``task.class`` attribute (dot-separated, per OTel semantic
    # conventions). The original implementation wrote ``task_class``
    # (underscore) which never matched the SQL filter on
    # ``metadata.attributes.task_class`` in
    # ``akosha_query_local_traces`` — so mcp_tool_call_feed stayed at 0
    # entities even with traces flowing. Write BOTH the dot-form (the
    # documented contract) AND the underscore-form (the documented
    # plan name) so either reader picks it up.
    span.set_attribute("task.class", TASK_CLASS)
    span.set_attribute("task_class", TASK_CLASS)
    span.set_attribute("selector", tool_name)
    span.set_attribute("outcome", status)
    span.set_attribute("duration_ms", duration_ms)
