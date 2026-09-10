"""Per-tool e2e: ``mcp__mahavishnu__plan_show``.

REQ-PLAN-007 (§4 gate): round-trip upsert→show equality, plus the
missing-record path (FastMCP error serialization).
"""

from __future__ import annotations

from typing import Any

from mahavishnu.plan_index.record import PlanRecord


def _sample_record(plan_id: str = "1" * 32, title: str = "X") -> PlanRecord:
    return PlanRecord(
        plan_id=plan_id,
        path="docs/plans/x.md",
        title=title,
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


class TestPlanShowE2E:
    async def test_round_trip_upsert_then_show(
        self, call_tool: Any, store: Any
    ) -> None:
        """A record seeded via ``store.upsert`` returns the same shape via ``plan_show``.

        The store is the same ``FakeDhara``-backed instance the tool
        reads from (see conftest ``store`` fixture wiring), so a write
        through one path is visible through the other.
        """
        plan_id = "f" * 32
        await store.upsert(_sample_record(plan_id=plan_id, title="Round-trip"))

        result = await call_tool("plan_show", {"plan_id": plan_id})

        assert isinstance(result, dict)
        assert result["plan_id"] == plan_id
        assert result["path"] == "docs/plans/x.md"
        assert result["status"] == "active"
        assert result["title"] == "Round-trip"

    async def test_show_nonexistent_returns_error_envelope(
        self, call_tool: Any
    ) -> None:
        """A missing plan surfaces the ``PlanNotFoundError`` discriminator.

        The store returns ``None`` for missing keys, then the tool
        raises ``PlanNotFoundError(plan_id)``. FastMCP surfaces that
        via the synthetic error envelope; we assert on the textual
        message rather than a structured code so the test stays
        version-portable.
        """
        result = await call_tool("plan_show", {"plan_id": "0" * 32})

        assert isinstance(result, dict)
        assert result["status"] == "error"
        # The original PlanNotFoundError message must surface.
        assert "Plan not found" in result["error"] or "not found" in result["error"].lower()

    async def test_show_invalid_plan_id_raises_value_error(
        self, call_tool: Any
    ) -> None:
        """Non-32-hex plan_ids raise ``ValueError`` from the store (brief concern #2).

        The store's ``_validate_plan_id`` enforces the regex before
        touching Dhara, so the tool body surfaces this as a
        ``ValueError`` — FastMCP re-raises as ``ToolError`` with the
        original message. The test confirms the error reaches the
        client via the envelope, not a Python
        ``pytest.raises(PermissionError)`` style, because the wrapper
        does not raise.
        """
        result = await call_tool("plan_show", {"plan_id": "not-hex"})

        assert isinstance(result, dict)
        assert result["status"] == "error"
        # The original ValueError message must surface in the wrapped error text.
        assert "invalid plan_id" in result["error"]
        assert "32 lowercase hex chars" in result["error"]
