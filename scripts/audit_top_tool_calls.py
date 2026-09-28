"""Enumerate the top-N most-called Mahavishnu MCP tools.

REQ-TSQ-009 from ``docs/plans/2026-09-26-tool-surface-quality.md``:
reads Akosha traces via ``mcp__akosha__query_local_traces(system_id="mahavishnu",
task_class="mcp_tool_call", limit=200)``, groups by the per-tool ``selector``
attribute, ranks by call count descending, prints the sorted list.

Idempotent: two consecutive runs over the same Akosha trace corpus produce
byte-identical output. Asserted by ``tests/unit/test_audit_top_tool_calls.py``.

The script's inner ``rank_tools_by_call_count`` function is pure (input: list
of trace dicts; output: sorted list of ``(tool_name, call_count)`` tuples).
The ``main()`` glue handles the Akosha MCP call + stdout rendering so the
test can drive ``rank_tools_by_call_count`` directly with mocked trace data.

CLI exit codes:
  0  — success (zero or more tools ranked; empty list is a valid output)
  1  — Akosha MCP call failed (network / MCP server unavailable / auth)
  2  — trace corpus malformed (no ``selector`` attribute on any trace)

Usage::

    cd /Users/les/Projects/mahavishnu && uv run python scripts/audit_top_tool_calls.py
    # or with a custom limit:
    cd /Users/les/Projects/mahavishnu && uv run python scripts/audit_top_tool_calls.py --limit 50
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from typing import Any

# Selector attribute location — set by the ToolCallEnrichmentMiddleware
# (Phase 1, commit 67095d98) on each span as a top-level OTel attribute.
# After the OtelTraceIngester ingests a span, the ``selector`` lives
# nested at ``metadata.attributes.selector`` (alongside ``task_class``,
# ``outcome``, ``duration_ms``). The previous flat-top-level contract
# (``trace["selector"]``) only held when the audit script ran against
# an adapter that copied the attribute up — Akosha's hot_store does not,
# so the audit script now digs into the metadata attributes.
SELECTOR_ATTR = "selector"


def _selector_from_trace(trace: dict[str, Any]) -> str | None:
    """Pull the per-tool ``selector`` string out of an Akosha trace dict.

    Returns the selector when present (and non-empty), else ``None``.
    Looks at the nested ``metadata.attributes.selector`` location first
    (current Akosha layout) and falls back to a top-level
    ``trace["selector"]`` for forward compatibility with adapters that
    promote the attribute.

    Akosha returns ``metadata`` as a JSON-encoded STRING on the wire
    (FastMCP serialises dict-typed metadata that way through DuckDB's
    JSON column). When the value is a string we parse it here so the
    audit script doesn't have to do that at every call site.
    """
    meta = trace.get("metadata")
    attrs: Any = None
    if isinstance(meta, dict):
        attrs = meta.get("attributes")
    elif isinstance(meta, str) and meta:
        try:
            import json as _json
            parsed = _json.loads(meta)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            attrs = parsed.get("attributes")
    if isinstance(attrs, dict):
        sel = attrs.get(SELECTOR_ATTR)
        if isinstance(sel, str) and sel:
            return sel
    sel = trace.get(SELECTOR_ATTR)
    if isinstance(sel, str) and sel:
        return sel
    return None

# Exit codes — exported so tests can assert CLI behavior without parsing stdout.
EXIT_OK = 0
EXIT_MCP_FAILED = 1
EXIT_MALFORMED_CORPUS = 2


def rank_tools_by_call_count(
    traces: list[dict[str, Any]],
    *,
    limit: int | None = None,
) -> list[tuple[str, int]]:
    """Group traces by selector, sort desc by call count, optionally truncate.

    Pure function: no I/O, no side effects. Deterministic ordering:
    ties broken alphabetically by tool name so the output is byte-stable
    across runs over the same input (idempotence requirement).

    Args:
        traces: List of trace dicts. Each must carry a ``selector`` key
            with the tool name string. Missing ``selector`` keys are
            skipped (counted as "unknown", not raised — the empty-state
            behavior is "rank what we know").
        limit: Optional cap on returned tuples. ``None`` returns all.

    Returns:
        List of ``(tool_name, call_count)`` tuples, sorted by
        ``(-call_count, tool_name)`` so the highest-call tool comes
        first and ties break alphabetically.
    """
    counts: Counter[str] = Counter()
    for trace in traces:
        selector = _selector_from_trace(trace)
        if selector is not None:
            counts[selector] += 1

    # Counter.most_common is NOT stable for ties — it uses insertion order,
    # which is non-deterministic if the input list is reordered. Build the
    # sort key explicitly so identical corpora produce identical output
    # regardless of how the traces were ordered internally.
    sorted_tools = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if limit is not None:
        sorted_tools = sorted_tools[:limit]
    return sorted_tools


def format_ranked_tools(
    ranked: list[tuple[str, int]],
    *,
    show_total: bool = True,
) -> str:
    """Render the ranked list as a deterministic text block.

    Two-pass render: first compute column widths so the output is
    column-aligned regardless of the longest tool name. Stable ordering
    matches ``rank_tools_by_call_count``.

    Args:
        ranked: Output of ``rank_tools_by_call_count``.
        show_total: When True, append a summary line with the total
            call count (matches Akosha's tool_selection_accuracy test
            output format).
    """
    if not ranked:
        return "(no mcp_tool_call traces found — Phase 1 enrichment may not have produced data yet)"

    # Compute widths from BOTH the column headers AND the data so the
    # header column doesn't visually shrink below the longest data row.
    name_width = max(len("tool"), max(len(name) for name, _ in ranked))
    count_width = max(len("count"), max(len(str(count)) for _, count in ranked))
    lines = [
        f"{'tool':<{name_width}}  {'count':>{count_width}}",
        f"{'-' * name_width}  {'-' * count_width}",
    ]
    for name, count in ranked:
        lines.append(f"{name:<{name_width}}  {count:>{count_width}}")
    if show_total:
        lines.append("")
        lines.append(f"total: {sum(c for _, c in ranked)}")
    return "\n".join(lines)


async def _fetch_traces_from_akosha(limit: int) -> list[dict[str, Any]]:
    """Call Akosha MCP to fetch mcp_tool_call traces for mahavishnu.

    Uses the official FastMCP streamable-HTTP client (``mcp.client.
    streamable_http.streamable_http_client`` + ``ClientSession``) so the
    handshake, session-ID negotiation, and reconnection logic are
    handled correctly. The previous raw ``httpx.AsyncClient.post(json=...)``
    approach returned HTTP 400 against Akosha v0.21.0 + FastMCP 4.x,
    which require ``initialize`` first plus ``Accept:
    application/json, text/event-stream`` headers and session-ID tracking.

    Errors are caught and re-raised as ``MCPFetchError`` so ``main()`` can
    return a clean exit code.

    Note: this function is best-effort. Phase 1 of the parent plan ships
    the writer-side enrichment; until the trace pipeline delivers data
    into Akosha's hot_store, this will typically return an empty list
    (which is a valid output, not an error).
    """
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    akosha_url = "http://localhost:8682/mcp"
    try:
        async with streamable_http_client(akosha_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "akosha_query_local_traces",
                    arguments={
                        "system_id": "mahavishnu",
                        "task_class": "mcp_tool_call",
                        "limit": limit,
                    },
                )
    except Exception as exc:
        raise MCPFetchError(f"Akosha MCP query failed: {exc}") from exc

    # FastMCP wraps tools with an output schema as ``structured_content``;
    # tools without an output schema return text via ``content[0].text``.
    # The ``akosha_query_local_traces`` tool returns structured content
    # shaped ``{"result": [...spans...]}``, so prefer that path and
    # fall back to the text path for tools that don't declare a schema.
    import json as _json
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        if not isinstance(structured, dict) or "result" not in structured:
            raise MCPFetchError(
                f"Akosha MCP structured_content missing 'result' key "
                f"(keys={list(structured.keys()) if isinstance(structured, dict) else 'n/a'})"
            )
        traces = structured["result"]
    else:
        try:
            text_payload = result.content[0].text
            traces = _json.loads(text_payload)
        except (AttributeError, IndexError, KeyError, TypeError,
                _json.JSONDecodeError) as exc:
            raise MCPFetchError(f"Akosha MCP payload malformed: {exc}") from exc

    if not isinstance(traces, list):
        raise MCPFetchError(
            f"Akosha MCP returned non-list payload (type={type(traces).__name__})"
        )
    return traces


class MCPFetchError(RuntimeError):
    """Akkosha MCP query failed; surfaced as a clean CLI exit code."""


async def main_async(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Print the top-N most-called Mahavishnu MCP tools by reading "
            "the mcp_tool_call task_class from Akosha's hot_store."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Maximum traces to read from Akosha (default: 200)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        help="Cap the printed ranking at N tools (default: print all)",
    )
    args = parser.parse_args(argv)

    try:
        traces = await _fetch_traces_from_akosha(args.limit)
    except MCPFetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_MCP_FAILED

    ranked = rank_tools_by_call_count(traces, limit=args.top)

    # Empty corpus is a valid output (Phase 1 just shipped; production
    # traffic may not have accumulated yet). The format helper handles it.
    if not traces:
        # Distinguish "no data" from "Akosha returned no rows" — both are
        # EXIT_OK but operators need to know which.
        print(
            f"note: Akosha returned 0 traces for system_id=mahavishnu "
            f"task_class=mcp_tool_call limit={args.limit}; "
            f"Phase 1 enrichment may not have produced data yet",
            file=sys.stderr,
        )

    print(format_ranked_tools(ranked))
    return EXIT_OK


def main() -> int:
    """Sync entry point for setuptools/console_scripts."""
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
