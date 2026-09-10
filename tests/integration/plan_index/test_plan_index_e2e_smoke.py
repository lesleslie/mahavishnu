"""§2 CI smoke gate for the five ``plan_*`` MCP tools.

REQ-PLAN-007 / REQ-PLAN-013: every registered MCP tool MUST have a
smoke test that exercises the server's actual tool-registration path
and asserts a non-empty, structurally-complete result.

Why this exists in ``integration/`` rather than ``unit/mcp/``:
the gate runs after ``register_plan_tools(mcp, store_provider=...)``
mounts the five tools onto a real ``FastMCP`` server. Wiring regressions
(decorator order, DI plumbing, profile surface) are caught here, not
in the in-process unit tests that exercise ``FakeMCP``.
"""

from __future__ import annotations

from typing import Any

PLAN_TOOL_NAMES = (
    "plan_list",
    "plan_show",
    "plan_search",
    "plan_vitals",
    "plan_rebuild_status",
)


class TestPlanIndexE2ESmoke:
    """Smoke-level coverage for the five ``plan_*`` MCP tools (REQ-PLAN-007)."""

    async def test_fast_mcp_list_tools_exposes_all_five_plan_tools(
        self, mcp: Any
    ) -> None:
        """The live ``FastMCP.list_tools()`` returns all 5 plan_* names.

        Using the server's introspection API (rather than parsing source)
        proves the tools were registered on the server instance, not just
        defined in the source file. Any wiring regression — wrong
        ``@mcp.tool(name=...)`` argument, missing decorator, misordered
        DI — surfaces here.
        """
        tools = await mcp.list_tools()
        names = {tool.name for tool in tools}

        for required in PLAN_TOOL_NAMES:
            assert required in names, (
                f"{required} missing from FastMCP.list_tools(): "
                f"got names={sorted(names)}"
            )

    async def test_all_five_tools_respond_with_structured_envelope(
        self, call_tool: Any, store: Any
    ) -> None:
        """Each tool returns a structurally complete envelope.

        Seeds one record via the helper so ``plan_list`` / ``plan_search``
        / ``plan_show`` / ``plan_vitals`` all have at least one record to
        reflect. ``plan_rebuild_status`` is exercised empty: it must
        still return the typed-dict envelope per spec §6.
        """
        from mahavishnu.plan_index.record import PlanRecord

        seed_id = "f" * 32
        await store.upsert(
            PlanRecord(
                plan_id=seed_id,
                path="docs/plans/smoke.md",
                title="Smoke Plan",
                status="active",
                role="implementation",
                topic="routing",
                date="2026-09-15",
                last_reviewed="2026-09-15",
                superseded_by=None,
                blocks_on=[],
                sha="f" * 40,
                repo="github.com/example/repo",
                updated_at_ms=1700000000000,
            )
        )

        # plan_list
        listed = await call_tool("plan_list", {"status": "active"})
        assert isinstance(listed, dict)
        assert {"plans", "total", "status"} <= set(listed.keys())
        assert listed["status"] in ("ok", "degraded")
        assert listed["total"] == len(listed["plans"])

        # plan_show (round-trip through the JSON-RPC envelope)
        shown = await call_tool("plan_show", {"plan_id": seed_id})
        assert isinstance(shown, dict)
        assert shown["plan_id"] == seed_id
        assert shown["path"] == "docs/plans/smoke.md"

        # plan_search
        searched = await call_tool("plan_search", {"query": "routing"})
        assert isinstance(searched, list)

        # plan_vitals (9 required keys per spec §6)
        vitals = await call_tool("plan_vitals", {})
        for required in (
            "total",
            "by_status",
            "by_role",
            "by_topic_top10",
            "cycles_total",
            "successful_cycles_total",
            "errors_total",
            "recent_errors",
            "tripwire",
        ):
            assert required in vitals, f"plan_vitals missing field: {required}"

        # plan_rebuild_status
        status = await call_tool("plan_rebuild_status", {})
        assert {"cycles_total", "errors_total", "stale"} <= set(status.keys())
        assert isinstance(status["stale"], bool)
