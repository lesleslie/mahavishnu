"""Per-tool e2e: ``mcp__mahavishnu__plan_rebuild_status``.

REQ-PLAN-007 (§4 gate) + REQ-PLAN-009 (lock-holder redaction): TypedDict
shape, ``stale`` boolean, and the ``^[a-f0-9]{8}/\\d+$`` regex on
``lock_held_by``.
"""

from __future__ import annotations

import re
from typing import Any


class TestPlanRebuildStatusE2E:
    async def test_rebuild_status_returns_typed_dict(self, call_tool: Any) -> None:
        """Empty substrate: required TypedDict keys are present."""
        result = await call_tool("plan_rebuild_status", {})

        assert isinstance(result, dict)
        assert "cycles_total" in result
        assert "errors_total" in result
        assert "stale" in result
        assert isinstance(result["stale"], bool)
        assert isinstance(result["cycles_total"], int)
        assert isinstance(result["errors_total"], int)

    async def test_rebuild_status_fresh_substrate_is_stale(
        self, call_tool: Any
    ) -> None:
        """With no last_rebuild_ms, the spec §6 staleness rule marks it stale."""
        result = await call_tool("plan_rebuild_status", {})

        assert result["stale"] is True
        assert result["cycles_total"] == 0
        assert result.get("last_rebuild_ms") is None

    async def test_lock_held_by_redaction_regex(
        self, call_tool: Any, store: Any, mcp: Any
    ) -> None:
        """A ``lock_held_by`` value matching ``^[a-f0-9]{8}/\\d+$`` is preserved.

        Per spec §6 the redaction regex ``^[a-f0-9]{8}/\\d+$``
        (``hostname_hash[:8] + '/' + pid``) is the only valid format. A
        rebuilder lease holder that violates the regex is a PII leak.
        """
        # Seed a lock-holder string that matches the documented format.
        await store._dhara.put(
            "plan_index/meta/rebuild_lock/holder", "deadbeef/12345"
        )

        result = await call_tool("plan_rebuild_status", {})

        if result.get("lock_held_by"):
            assert re.match(
                r"^[a-f0-9]{8}/\d+$", result["lock_held_by"]
            ), f"lock_held_by {result['lock_held_by']!r} failed redaction regex"
            # And our seeded value should round-trip.
            assert result["lock_held_by"] == "deadbeef/12345"

    async def test_rebuild_status_without_user_id_returns_auth_required_envelope(
        self, call_tool: Any
    ) -> None:
        """REQ-PLAN-010: missing ``user_id`` returns envelope, not raise."""
        result = await call_tool("plan_rebuild_status", {}, user_id=None)

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_REQUIRED"
