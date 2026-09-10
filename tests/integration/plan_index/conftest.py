"""Shared fixtures for plan_index e2e tests.

Exercises the five ``plan_*`` MCP tools through a real FastMCP server
constructed in-process, with a ``FakeDhara``-backed :class:`PlanIndexStore`
injected via the ``store_provider`` DI parameter on
``register_plan_tools``. The conftest mirrors the integration-test pattern
already used in ``tests/unit/test_goal_team_tools.py``: build a real
FastMCP, register the tools, then call them via the standard
``mcp.call_tool(...)`` coroutine (the same path a JSON-RPC client at
``/mcp`` exercises in production).

Why in-process rather than a subprocess boot of ``mahavishnu mcp start``
as the brief's header suggests:

1. ``mahavishnu mcp start`` does NOT accept ``--profile``; the CLI's
   ``mcp start`` command exposes only ``--host``/``--port``.
2. The production wire that mounts ``register_plan_tools`` into any
   ``PROFILE_REGISTRATIONS[ToolProfile.*]`` list is Task 12 work; until
   that ships, ``mcp start`` registers zero plan_index tools regardless
   of profile.
3. The env vars the brief header assumes — ``MAHAVISHNU_PLAN_INDEX_DHARA_URL``
   and ``MAHAVISHNU_DEV_BYPASS_TOKEN`` — are not implemented anywhere in
   this repo (verified by grep).
4. ``tests/integration/jot/test_read_e2e.py`` documents the same
   subprocess path as unreliable and marks it ``@pytest.mark.slow`` /
   skipped in CI.

In-process FastMCP reaches the EXACT same wiring: ``register_plan_tools``
runs its ``@mcp.tool(name=...)`` decorator on the real ``FastMCP``
instance, the ``require_mcp_auth`` decorator wraps each tool body, and
the JSON-RPC layer presents them at ``/mcp``. That is the §4 gate the
brief is after.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
import pytest

from mahavishnu.mcp.tools.plan_tools import register_plan_tools
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeDhara


@pytest.fixture
def store() -> PlanIndexStore:
    """A fresh ``FakeDhara``-backed :class:`PlanIndexStore` for each test.

    Using ``FakeDhara`` (not a real Dhara subprocess) means each test
    starts with a clean substrate — no rebuilder cycles, no last_rebuild,
    no records. The Round-2 tests at the bottom of the suite depend on
    that contract.
    """
    return PlanIndexStore(FakeDhara())


@pytest.fixture
def mcp(store: PlanIndexStore) -> FastMCP:
    """A real FastMCP server with the five ``plan_*`` tools registered.

    ``register_plan_tools`` requires a keyword-only ``store_provider`` —
    we pass the per-test ``store`` fixture so any tools written by one
    test are visible to that same test only.
    """
    server = FastMCP("plan_index-test")

    def provider() -> PlanIndexStore:
        return store

    register_plan_tools(server, store_provider=provider)
    return server


async def _call_tool(
    mcp: FastMCP,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    user_id: str = "test-user",
) -> Any:
    """Invoke a tool by name and unwrap the MCP ``ToolResult`` envelope.

    Tool functions registered by ``plan_tools`` return either:
      * a ``dict`` (the four read tools), or
      * a ``list[dict]`` (``plan_search``), or
      * a ``dict`` ``{"status": "error", "error_code": "AUTH_REQUIRED", ...}``
        when ``require_mcp_auth`` denies a missing-``user_id`` call.

    When the tool body raises (``PlanNotFoundError``, ``ValueError``,
    etc.), FastMCP re-raises as ``fastmcp.exceptions.ToolError`` with the
    original message in the exception text. The helper catches that
    and converts it into a synthetic envelope dict whose ``"error"``
    field carries the original exception text — tests that drive the
    error path can assert on the class-name substring.

    FastMCP's ``call_tool`` returns a ``ToolResult`` whose
    ``structured_content`` is wrapped under the bare key ``"result"`` for
    schema-less tools (our case — none of the five tools declare an
    ``output_schema``). Tests that want the raw return value therefore
    need to unwrap ``structured_content["result"]`` for happy paths, or
    return the whole envelope when the error path is in play.

    ``user_id`` is forwarded by default — the ``require_mcp_auth``
    decorator returns the ``AUTH_REQUIRED`` envelope when omitted
    (REQ-PLAN-010; verified by ``tests/unit/mcp/test_plan_tools_auth_gate.py``).
    Tests that intentionally exercise the missing-user-id path call
    ``_call_tool(..., user_id=None)`` to inspect the envelope shape.
    """
    args: dict[str, Any] = dict(arguments or {})
    if user_id is not None:
        args["user_id"] = user_id

    try:
        result = await mcp.call_tool(tool_name, args)
    except ToolError as exc:
        # FastMCP wraps the original exception as ToolError("Error calling
        # tool {name!r}: {exc}"). Preserve the textual message so tests
        # can grep for the original exception class name.
        return {"status": "error", "error": str(exc), "error_code": "TOOL_ERROR"}

    structured = getattr(result, "structured_content", None)
    if structured is None:
        # Fall back to parsing the text content payload.
        if getattr(result, "content", None):
            import json

            text = result.content[0].text
            try:
                return json.loads(text)
            except (ValueError, TypeError):
                return text
        return result

    # Auth-gate envelopes are returned as-is (no "result" wrapper).
    if isinstance(structured, dict) and set(structured).issuperset(
        {"status", "error_code"}
    ):
        return structured

    # Tools without an output_schema get wrapped as ``{"result": <value>}``.
    if isinstance(structured, dict) and "result" in structured and len(structured) == 1:
        return structured["result"]

    return structured


@pytest.fixture
def call_tool(mcp: FastMCP) -> Any:
    """Async-style callable: ``await call_tool('plan_list', {'status': 'active'})``.

    Exposed as a fixture (rather than a pytest-asyncio helper) to avoid
    a fixture-loop with pytest-asyncio's ``@pytest.mark.asyncio`` wiring
    and to keep the call-site signature short.
    """

    async def _bound(
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        user_id: str | None = "test-user",
    ) -> Any:
        return await _call_tool(mcp, tool_name, arguments, user_id=user_id)

    return _bound
