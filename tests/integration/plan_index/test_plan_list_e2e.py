"""Per-tool e2e: ``mcp__mahavishnu__plan_list``.

REQ-PLAN-007 (§4 gate): verifies the typed-dict envelope shape, the
``status`` filter routing, and the empty-store contract.
"""

from __future__ import annotations

from typing import Any

from mahavishnu.plan_index.record import PlanRecord


def _record(
    *,
    plan_id: str,
    status: str = "active",
    topic: str = "routing",
    title: str = "Listed",
    date: str = "2026-09-15",
) -> PlanRecord:
    return PlanRecord(
        plan_id=plan_id,
        path=f"docs/plans/{plan_id[:6]}.md",
        title=title,
        status=status,
        role="implementation",
        topic=topic,
        date=date,
        last_reviewed=date,
        superseded_by=None,
        blocks_on=[],
        sha="f" * 40,
        repo="github.com/example/repo",
        updated_at_ms=1700000000000,
    )


class TestPlanListE2E:
    async def test_list_with_status_filter_returns_typed_dict(
        self, call_tool: Any, store: Any
    ) -> None:
        """Status filter routes to ``list_by_status`` and returns the typed envelope."""
        await store.upsert(_record(plan_id="a" * 32, status="active"))
        await store.upsert(_record(plan_id="b" * 32, status="shipped"))

        result = await call_tool("plan_list", {"status": "active"})

        assert isinstance(result, dict)
        assert {"plans", "total", "status"} <= set(result.keys())
        assert result["status"] in ("ok", "degraded")
        # total must equal length of plans (TypedDict invariant)
        assert result["total"] == len(result["plans"])
        # Only active records appear
        assert {p["status"] for p in result["plans"]} == {"active"}

    async def test_list_with_topic_filter(
        self, call_tool: Any, store: Any
    ) -> None:
        """Topic filter routes to ``list_by_topic`` and isolates the topic."""
        await store.upsert(_record(plan_id="c" * 32, topic="routing"))
        await store.upsert(_record(plan_id="d" * 32, topic="observability"))

        matched = await call_tool("plan_list", {"topic": "routing"})
        unmatched = await call_tool("plan_list", {"topic": "unrelated"})

        assert matched["total"] == 1
        assert {p["topic"] for p in matched["plans"]} == {"routing"}
        assert unmatched["total"] == 0
        assert unmatched["plans"] == []

    async def test_list_with_no_filter_returns_all_records(
        self, call_tool: Any, store: Any
    ) -> None:
        """No filter → ``list_all`` returns every plan in the index."""
        await store.upsert(_record(plan_id="e" * 32, title="A"))
        await store.upsert(_record(plan_id="f" * 32, title="B"))
        await store.upsert(_record(plan_id="1" * 32, title="C"))

        result = await call_tool("plan_list", {})

        assert result["total"] == 3
        assert {p["title"] for p in result["plans"]} == {"A", "B", "C"}

    async def test_list_empty_store_returns_zero_total(
        self, call_tool: Any
    ) -> None:
        """An empty store returns ``total=0`` and ``plans=[]``."""
        result = await call_tool("plan_list", {})

        assert result["total"] == 0
        assert result["plans"] == []
        assert result["status"] == "ok"

    async def test_list_without_user_id_returns_auth_required_envelope(
        self, call_tool: Any
    ) -> None:
        """REQ-PLAN-010: missing ``user_id`` returns the envelope (no raise)."""
        result = await call_tool("plan_list", {}, user_id=None)

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_REQUIRED"
