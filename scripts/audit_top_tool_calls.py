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

# Selector attribute name — set by the ToolCallEnrichmentMiddleware
# (Phase 1, commit 67095d98). Mirrored here so the script does NOT depend
# on importing mahavishnu at runtime (it's a top-level command).
SELECTOR_ATTR = "selector"

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
        selector = trace.get(SELECTOR_ATTR)
        if isinstance(selector, str) and selector:
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

    The MCP call is a thin HTTP wrapper around the FastMCP server on
    ``akosha_url`` (default ``http://localhost:8682/mcp``). Importing
    the full FastMCP client here would force the script to depend on
    mahavishnu's venv; instead we call the endpoint via the standard
    httpx client (already a transitive dep via FastMCP). Errors are
    caught and re-raised as ``MCPFetchError`` so ``main()`` can return
    a clean exit code.

    Note: this function is best-effort. Phase 1 of the parent plan
    ships the writer-side enrichment; until production traffic
    accumulates, this will typically return an empty list (which is
    a valid output, not an error).
    """
    import httpx

    akosha_url = "http://localhost:8682/mcp"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                akosha_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "query_local_traces",
                        "arguments": {
                            "system_id": "mahavishnu",
                            "task_class": "mcp_tool_call",
                            "limit": limit,
                        },
                    },
                },
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise MCPFetchError(f"Akosha MCP query failed: {exc}") from exc

    # MCP JSON-RPC envelope: {"result": {"content": [{"type": "text",
    # "text": "<json string>"}]}}. Parse the inner text blob.
    try:
        inner_text = payload["result"]["content"][0]["text"]
        traces = __import__("json").loads(inner_text)
    except (KeyError, IndexError, TypeError, __import__("json").JSONDecodeError) as exc:
        raise MCPFetchError(f"Akosha MCP payload malformed: {exc}") from exc

    if not isinstance(traces, list):
        raise MCPFetchError(f"Akosha MCP returned non-list payload (type={type(traces).__name__})")
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
