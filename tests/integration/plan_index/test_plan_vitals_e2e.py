"""Per-tool e2e: ``mcp__mahavishnu__plan_vitals``.

REQ-PLAN-007 (§4 gate): 9 TypedDict fields, counter invariants, and
tripwire enum membership.
"""

from __future__ import annotations

from typing import Any

from mahavishnu.plan_index.record import PlanRecord


def _record(plan_id: str, *, status: str, role: str, topic: str) -> PlanRecord:
    return PlanRecord(
        plan_id=plan_id,
        path=f"docs/plans/{plan_id[:6]}.md",
        title="Vitals Fixture",
        status=status,
        role=role,
        topic=topic,
        date="2026-09-15",
        last_reviewed="2026-09-15",
        superseded_by=None,
        blocks_on=[],
        sha="f" * 40,
        repo="github.com/example/repo",
        updated_at_ms=1700000000000,
    )


class TestPlanVitalsE2E:
    async def test_vitals_returns_typed_dict_shape(
        self, call_tool: Any
    ) -> None:
        """Empty substrate; required TypedDict keys are still present."""
        result = await call_tool("plan_vitals", {})

        assert isinstance(result, dict)
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
            assert required in result, f"plan_vitals missing field: {required}"

    async def test_vitals_counters_are_non_negative_ints(
        self, call_tool: Any
    ) -> None:
        """Counter invariants per spec §6."""
        result = await call_tool("plan_vitals", {})

        assert isinstance(result["total"], int)
        assert isinstance(result["cycles_total"], int)
        assert isinstance(result["successful_cycles_total"], int)
        assert isinstance(result["errors_total"], int)
        assert result["total"] >= 0
        assert result["cycles_total"] >= 0
        assert result["successful_cycles_total"] >= 0
        assert result["errors_total"] >= 0

    async def test_vitals_by_status_breaks_down_records(
        self, call_tool: Any, store: Any
    ) -> None:
        """``by_status`` reflects the ``Counter`` of the seeded records."""
        await store.upsert(_record("a" * 32, status="active", role="implementation", topic="routing"))
        await store.upsert(_record("b" * 32, status="active", role="implementation", topic="routing"))
        await store.upsert(_record("c" * 32, status="shipped", role="canonical", topic="indexing"))

        result = await call_tool("plan_vitals", {})

        assert result["total"] == 3
        assert result["by_status"] == {"active": 2, "shipped": 1}
        assert result["by_role"] == {"implementation": 2, "canonical": 1}

    async def test_vitals_tripwire_enum_membership(
        self, call_tool: Any
    ) -> None:
        """``tripwire`` is one of the documented enum values (spec §6)."""
        result = await call_tool("plan_vitals", {})

        assert result["tripwire"] in (
            "ok",
            "no_recent_edits",
            "no_recent_reads",
            "review_cadence_lagging",
        )

    async def test_vitals_by_topic_top10_is_a_list(
        self, call_tool: Any, store: Any
    ) -> None:
        """``by_topic_top10`` is a list of ``(topic, count)`` pairs.

        FastMCP serializes Python tuples to JSON arrays over the wire,
        so the round-trip yields a 2-element ``list`` rather than a
        ``tuple``. The test asserts on the serialized shape.
        """
        await store.upsert(_record("a" * 32, status="active", role="implementation", topic="routing"))

        result = await call_tool("plan_vitals", {})

        assert isinstance(result["by_topic_top10"], list)
        for entry in result["by_topic_top10"]:
            assert isinstance(entry, list) and len(entry) == 2
            topic, count = entry
            assert isinstance(topic, str) and isinstance(count, int)

    async def test_vitals_without_user_id_returns_auth_required_envelope(
        self, call_tool: Any
    ) -> None:
        """REQ-PLAN-010: missing ``user_id`` returns envelope, not raise."""
        result = await call_tool("plan_vitals", {}, user_id=None)

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_REQUIRED"
