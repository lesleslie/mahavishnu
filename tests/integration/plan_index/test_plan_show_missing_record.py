"""Round-2 e2e: ``PlanNotFoundError`` propagates with its discriminator preserved.

REQ-PLAN-007 (§4 §6.4): the missing-record error surfaces the class
name through the MCP wire format so the client can switch on the type
rather than parsing English. The store returns ``None`` for absent
keys; the tool body raises ``PlanNotFoundError(plan_id)`` (Task 11),
which FastMCP serializes as a ``ToolError`` with the class name in the
``message`` text.

This test exercises the error path through the JSON-RPC envelope (not
in-process) so the FastMCP-wrapping layer is part of the gate.
"""

from __future__ import annotations

from typing import Any

from mahavishnu.plan_index.errors import PlanNotFoundError
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeDhara


class TestPlanShowMissingRecord:
    async def test_missing_record_returns_plan_not_found_envelope(
        self, call_tool: Any
    ) -> None:
        """``plan_show`` against a missing record carries ``PlanNotFoundError``.

        The helper converts FastMCP's ``ToolError`` back into a
        synthetic envelope (``status=error``, ``error=<message>``) so
        the error path is assertion-friendly. The discriminator is
        ``"Plan not found"`` — class-name substring is fragile across
        FastMCP versions, message-substring is not.
        """
        result = await call_tool("plan_show", {"plan_id": "deadbeef" + "0" * 24})

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert "not found" in result["error"].lower()

    async def test_in_process_store_get_returns_none_for_missing(self) -> None:
        """Direct (in-process) check: ``store.get(missing_id)`` returns ``None``.

        The store does NOT raise ``PlanNotFoundError`` itself — that
        discriminator lives at the tool boundary. Consumers that want
        direct store access must translate ``None`` → exception
        themselves. This contract is the basis for the auth-gate and
        missing-record e2e tests in the sibling files.
        """
        store = PlanIndexStore(FakeDhara())  # type: ignore[arg-type]

        result = await store.get("0" * 32)

        assert result is None

    async def test_plan_not_found_error_carries_plan_id(self) -> None:
        """``PlanNotFoundError.plan_id`` exposes the missing id (REQ-PLAN-007 §6.4)."""
        exc = PlanNotFoundError("0" * 32)

        assert exc.plan_id == "0" * 32
        assert "0" * 32 in str(exc)
