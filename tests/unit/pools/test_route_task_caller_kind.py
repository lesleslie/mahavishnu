"""Unit tests for route_task's caller_kind / parent_session_id wiring.

Phase 3 Task 3.5 exit criteria items 9-12 — these tests pin the
behaviour of ``PoolManager.route_task`` end-to-end with respect to
the new caller-kind contract:

- ``caller_kind`` must be coerced via ``coerce_caller_kind`` so
  novel strings cannot inflate quota buckets.
- The persisted Dhara record must carry both ``caller_kind`` (as
  the enum's underlying string) and ``parent_session_id`` (as
  supplied) under ``routing-decisions/``.
- Quota enforcement is the FIRST gate — it must raise
  ``RateLimitError`` BEFORE any Dhara write happens, otherwise a
  saturated caller would still produce audit noise.

The tests use a MagicMock for ``_dhara_state`` so the persist call
arguments are inspectable; no real Dhara is involved.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.errors import RateLimitError
from mahavishnu.pools import PoolManager
from mahavishnu.pools.manager import CallerKind, _QuotaState, coerce_caller_kind

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _StubPool:
    """Minimal pool stand-in returning a fixed result."""

    pool_id = "pool_test"
    config = MagicMock(min_workers=1, max_workers=2, pool_type="mahavishnu")
    _workers: dict[str, str] = {"w1": "w1"}

    async def execute_task(self, task):
        return {"pool_id": self.pool_id, "status": "completed", "result": "ok"}

    async def status(self):  # pragma: no cover - not exercised here
        return "running"


@pytest.fixture
def dhara_state() -> MagicMock:
    """An async-friendly MagicMock for the Dhara state backend."""
    mock = MagicMock()
    mock.persist_routing_decision = AsyncMock(return_value=None)
    mock.persist_pool = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def pool_mgr(dhara_state: MagicMock) -> PoolManager:
    """PoolManager with a stub pool and a mock Dhara backend attached."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=None,
            session_buddy_client=None,
            dhara_state=dhara_state,
        )
    mgr._pools["pool_test"] = _StubPool()  # type: ignore[assignment]
    mgr._pool_worker_counts["pool_test"] = 1
    return mgr


# ---------------------------------------------------------------------------
# 9. route_task persists caller_kind and parent_session_id
# ---------------------------------------------------------------------------


class TestRouteTaskPersistsCallerKind:
    """The persisted Dhara record must carry both new fields."""

    async def test_route_task_persists_caller_kind(self, pool_mgr: PoolManager) -> None:
        await pool_mgr.route_task(
            task={"prompt": "hi"},
            caller_kind="ultracode",
            parent_session_id="ses_abc",
        )
        # Find the persist call for routing decisions.
        assert pool_mgr._dhara_state.persist_routing_decision.await_count == 1
        value = pool_mgr._dhara_state.persist_routing_decision.call_args.args[1]
        assert value["caller_kind"] == "ultracode"
        assert value["parent_session_id"] == "ses_abc"


# ---------------------------------------------------------------------------
# 10. Quota is enforced BEFORE the Dhara persist call
# ---------------------------------------------------------------------------


class TestRouteTaskEnforcesQuotaAtEntry:
    """Saturated callers never produce Dhara writes — quota gate is first."""

    async def test_route_task_enforces_quota_at_entry(self, pool_mgr: PoolManager) -> None:
        # Pre-saturate the bucket anchored at the *current* time so the
        # window is not yet expired when route_task runs.
        now = datetime.now(UTC)
        pool_mgr._caller_quota[CallerKind.ULTRA_CODE] = _QuotaState(
            window_start=now,
            request_count=999,
            window_size_seconds=60,
            max_per_window=2,
        )
        # The next attempt must be rejected.
        with pytest.raises(RateLimitError):
            await pool_mgr.route_task(
                task={"prompt": "hi"},
                caller_kind="ultracode",
                parent_session_id="ses_abc",
            )
        # Critical: NO persist call should have been issued.
        pool_mgr._dhara_state.persist_routing_decision.assert_not_awaited()


# ---------------------------------------------------------------------------
# 11. Novel strings normalize to the UNKNOWN bucket
# ---------------------------------------------------------------------------


class TestCallerKindUnknownNormalizes:
    """``ultracode-rogue-1`` lands in ``UNKNOWN`` — never spawns a fresh bucket."""

    async def test_caller_kind_unknown_normalizes_to_unknown_bucket(
        self, pool_mgr: PoolManager
    ) -> None:
        await pool_mgr.route_task(
            task={"prompt": "hi"},
            caller_kind="ultracode-rogue-1",
            parent_session_id="ses_abc",
        )
        # The bucket that got incremented is UNKNOWN — not a fresh bucket.
        assert CallerKind.UNKNOWN in pool_mgr._caller_quota
        # And no rogue-1 bucket exists.
        rogue_bucket = coerce_caller_kind("ultracode-rogue-1")
        assert rogue_bucket is CallerKind.UNKNOWN
        # The persisted value carries the canonical UNKNOWN string.
        value = pool_mgr._dhara_state.persist_routing_decision.call_args.args[1]
        assert value["caller_kind"] == "unknown"


# ---------------------------------------------------------------------------
# 12. StrEnum coercion at the boundary
# ---------------------------------------------------------------------------


class TestCallerKindStrEnumCoercionAtBoundary:
    """Passing a ``CallerKind`` enum persists its underlying string value."""

    async def test_caller_kind_strenum_coercion_at_boundary(
        self, pool_mgr: PoolManager
    ) -> None:
        await pool_mgr.route_task(
            task={"prompt": "hi"},
            caller_kind=CallerKind.ULTRA_CODE,
            parent_session_id="ses_abc",
        )
        value = pool_mgr._dhara_state.persist_routing_decision.call_args.args[1]
        # Persisted as the enum's underlying string, not the enum repr.
        assert value["caller_kind"] == "ultracode"
