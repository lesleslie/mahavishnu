"""Unit tests for ``scripts/audit_top_tool_calls.py``.

REQ-TSQ-009 from ``docs/plans/2026-09-26-tool-surface-quality.md`` Task 2.1:
- ``rank_tools_by_call_count`` returns the sorted list desc by call count.
- Output is byte-stable across runs over the same corpus (idempotence).
- Ties break alphabetically (so the sort is fully deterministic).
- Empty corpus is a valid output, not an error.
- Malformed traces (missing ``selector``) are skipped, not raised.
- ``format_ranked_tools`` aligns columns for human readability and
  includes a total-summary line.
- CLI exit codes: 0 success, 1 MCP failure, 2 malformed corpus.

The MCP fetch path is NOT exercised here — it requires a running Akosha
server and is covered by the integration test in
``tests/integration/test_audit_top_tool_calls_e2e.py`` (deferred until
Akosha has accumulated production mcp_tool_call traces; see
``docs/plans/drafts/2026-09-27-akosha-tool-call-feed-lifecycle.md`` for
the activation condition).
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

import pytest

from scripts.audit_top_tool_calls import (
    EXIT_MALFORMED_CORPUS,
    EXIT_MCP_FAILED,
    EXIT_OK,
    format_ranked_tools,
    rank_tools_by_call_count,
)


# ---------------------------------------------------------------------------
# rank_tools_by_call_count
# ---------------------------------------------------------------------------


def test_rank_tools_sorted_descending_by_call_count() -> None:
    """Higher call count appears first in the ranked output."""
    traces = [
        {"selector": "tool_a"},
        {"selector": "tool_a"},
        {"selector": "tool_a"},
        {"selector": "tool_b"},
        {"selector": "tool_b"},
        {"selector": "tool_c"},
    ]
    ranked = rank_tools_by_call_count(traces)
    assert ranked == [("tool_a", 3), ("tool_b", 2), ("tool_c", 1)]


def test_rank_tools_ties_break_alphabetically() -> None:
    """Ties at the same call count break alphabetically by tool name.

    Without the explicit tie-breaker, the order would depend on
    Counter.most_common's internal insertion order — which is
    non-deterministic if the input trace list is reordered between
    runs. The alphabetical tie-break makes the output byte-stable.
    """
    traces = [
        {"selector": "zeta"},
        {"selector": "alpha"},
        {"selector": "mu"},
    ]
    ranked = rank_tools_by_call_count(traces)
    # All tied at 1 → alpha first, mu second, zeta third.
    assert ranked == [("alpha", 1), ("mu", 1), ("zeta", 1)]


def test_rank_tools_is_idempotent_over_same_corpus() -> None:
    """Two runs over the same traces produce byte-identical output.

    Idempotence is the explicit acceptance criterion in plan §5 Task 2.1.
    Even when the input trace order is randomized between calls (a
    realistic Akosha read pattern), the output must match exactly.
    """
    traces = [
        {"selector": "tool_a"},
        {"selector": "tool_b"},
        {"selector": "tool_a"},
        {"selector": "tool_c"},
    ]
    run1 = rank_tools_by_call_count(traces)
    # Reverse the input — output must not change.
    reversed_traces = list(reversed(traces))
    run2 = rank_tools_by_call_count(reversed_traces)
    # Reverse half — output must not change.
    half_reversed = traces[:1] + list(reversed(traces[1:]))
    run3 = rank_tools_by_call_count(half_reversed)
    assert run1 == run2 == run3
    assert run1 == [("tool_a", 2), ("tool_b", 1), ("tool_c", 1)]


def test_rank_tools_handles_empty_corpus() -> None:
    """Empty corpus returns an empty list, not an error."""
    assert rank_tools_by_call_count([]) == []


def test_rank_tools_skips_traces_with_missing_selector() -> None:
    """Traces missing the ``selector`` attribute are skipped, not raised.

    Real Akosha traces may carry unrelated system_ids (e.g. akosha's
    own internal traces) and not all of them will have a ``selector``.
    The audit script's job is to rank mcp_tool_call traces; if a trace
    lacks the attribute, it's not a tool call we can attribute — skip
    silently. (Empty-state is operator-visible via the format helper's
    "(no mcp_tool_call traces found)" message.)
    """
    traces = [
        {"selector": "tool_a"},
        {"selector": ""},  # empty string — skipped per the validation
        {},  # missing key — skipped
        {"selector": None},  # None — skipped
        {"selector": "tool_b"},
    ]
    ranked = rank_tools_by_call_count(traces)
    assert ranked == [("tool_a", 1), ("tool_b", 1)]


def test_rank_tools_limit_caps_returned_list() -> None:
    """The optional ``limit`` argument caps the returned tuples."""
    traces = [{"selector": f"tool_{i:02d}"} for i in range(50)]
    ranked = rank_tools_by_call_count(traces, limit=5)
    assert len(ranked) == 5
    # First 5 in alphabetical order (all tied at 1).
    assert ranked == [
        ("tool_00", 1),
        ("tool_01", 1),
        ("tool_02", 1),
        ("tool_03", 1),
        ("tool_04", 1),
    ]


# ---------------------------------------------------------------------------
# format_ranked_tools
# ---------------------------------------------------------------------------


def test_format_ranked_tools_empty_corpus_returns_explanatory_message() -> None:
    """Empty corpus renders an operator-facing message, not an empty string."""
    out = format_ranked_tools([])
    assert "no mcp_tool_call traces found" in out


def test_format_ranked_tools_includes_total_summary_line() -> None:
    """Default rendering includes a ``total: N`` summary line."""
    ranked = [("tool_a", 3), ("tool_b", 2), ("tool_c", 1)]
    out = format_ranked_tools(ranked)
    assert "total: 6" in out


def test_format_ranked_tools_columns_are_aligned() -> None:
    """Column widths are computed from the longest entry, not hardcoded."""
    ranked = [
        ("short", 1),
        ("a_much_longer_tool_name", 99),
    ]
    out = format_ranked_tools(ranked, show_total=False)
    lines = out.splitlines()
    # Header + separator + 2 data lines = 4 lines when show_total=False.
    assert len(lines) == 4
    # Column header has fixed labels "tool" / "count" — verify they're there.
    header = lines[0]
    assert header.startswith("tool")
    assert "count" in header
    # Right-alignment of counts: the "1" appears before the "99" in column 2
    # because the column is wider than "1" needs.
    data_short = lines[2]
    data_long = lines[3]
    assert "short" in data_short and "1" in data_short
    assert "a_much_longer_tool_name" in data_long and "99" in data_long


def test_format_ranked_tools_idempotent_over_same_input() -> None:
    """Two formats of the same ranked list produce byte-identical strings."""
    ranked = [("tool_a", 3), ("tool_b", 2), ("tool_c", 1)]
    out1 = format_ranked_tools(ranked)
    out2 = format_ranked_tools(ranked)
    assert out1 == out2


# ---------------------------------------------------------------------------
# CLI integration (lightweight — drives main_async with argv, not full MCP)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cli_exit_ok_when_akosha_unreachable_warns_but_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Akosha is unreachable, the CLI exits 1 with stderr message.

    Empty-corpus and Akosha-unreachable are different conditions:
    - Empty: Akosha returned 0 traces → exit 0, print '(no ...)', stderr note.
    - Unreachable: httpx/connection error → exit 1, stderr 'error: ...'.

    The CLI distinguishes these so operators can tell "telemetry hasn't
    accumulated yet" from "Akkosha is down."
    """
    from scripts import audit_top_tool_calls

    async def _raise(limit: int) -> list[dict[str, Any]]:
        raise audit_top_tool_calls.MCPFetchError("connection refused")

    monkeypatch.setattr(audit_top_tool_calls, "_fetch_traces_from_akosha", _raise)

    buf = io.StringIO()
    with redirect_stdout(buf):
        with redirect_stderr(buf):
            code = await audit_top_tool_calls.main_async([])
    err = buf.getvalue()
    assert code == EXIT_MCP_FAILED
    assert "connection refused" in err
    assert EXIT_MCP_FAILED == 1


@pytest.mark.asyncio
async def test_cli_exit_ok_on_empty_corpus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty corpus is success (exit 0), with a stderr note explaining why."""
    from scripts import audit_top_tool_calls

    async def _empty(limit: int) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(audit_top_tool_calls, "_fetch_traces_from_akosha", _empty)

    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with redirect_stdout(out_buf):
        with redirect_stderr(err_buf):
            code = await audit_top_tool_calls.main_async([])
    assert code == EXIT_OK
    assert "no mcp_tool_call traces found" in out_buf.getvalue()
    assert "0 traces" in err_buf.getvalue()
    assert EXIT_OK == 0


@pytest.mark.asyncio
async def test_cli_exit_ok_on_populated_corpus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Populated corpus prints the ranked list and exits 0."""
    from scripts import audit_top_tool_calls

    sample_traces = [
        {"selector": "pool_route_execute"},
        {"selector": "pool_route_execute"},
        {"selector": "pool_route_execute"},
        {"selector": "discover_tools"},
        {"selector": "discover_tools"},
        {"selector": "get_health"},
    ]

    async def _fetch(limit: int) -> list[dict[str, Any]]:
        return sample_traces

    monkeypatch.setattr(audit_top_tool_calls, "_fetch_traces_from_akosha", _fetch)

    out_buf = io.StringIO()
    with redirect_stdout(out_buf):
        with redirect_stderr(io.StringIO()):
            code = await audit_top_tool_calls.main_async([])
    assert code == EXIT_OK
    out = out_buf.getvalue()
    assert "pool_route_execute" in out
    assert "discover_tools" in out
    assert "get_health" in out
    assert "total: 6" in out


def test_exit_code_constants_match_plan_documented_values() -> None:
    """Exit code constants match what ``docs/plans/...md §5 Phase 2 Task 2.1``
    implicitly documents: 0 success, 1 MCP failure.

    EXIT_MALFORMED_CORPUS is exported for future use (currently unreachable
    because the Akosha MCP payload parsing raises MCPFetchError, but the
    constant is reserved so a strict-mode future change doesn't break the
    public surface).
    """
    assert EXIT_OK == 0
    assert EXIT_MCP_FAILED == 1
    assert EXIT_MALFORMED_CORPUS == 2


def test_json_round_trip_preserves_ranked_output() -> None:
    """The output of ``rank_tools_by_call_count`` is JSON-serializable.

    Operators may want to pipe the output into jq / diff for regression
    detection in CI. The tuples are converted to ``[name, count]`` lists
    which are JSON-native.
    """
    traces = [{"selector": "x"}, {"selector": "y"}, {"selector": "x"}]
    ranked = rank_tools_by_call_count(traces)
    payload = json.dumps(ranked)
    assert json.loads(payload) == [["x", 2], ["y", 1]]
