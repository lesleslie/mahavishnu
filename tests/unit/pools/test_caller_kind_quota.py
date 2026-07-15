"""Unit tests for CallerKind coercion and per-caller fixed-window quota.

These tests target the Phase 3 Task 3.5 surface:

- ``coerce_caller_kind`` is the wire-boundary funnel that maps any
  inbound string (or ``None``) into the ``CallerKind`` StrEnum. The
  bucket-bypass fix relies on the fact that no unrecognized string can
  ever spawn a fresh bucket — it must collapse to ``UNKNOWN``.
- ``_enforce_caller_quota`` is the fixed-window rate-limit gate that
  runs first inside ``PoolManager.route_task``. The fixed window
  resets at a boundary (not sliding), so window reset semantics and
  ``retry_after_seconds`` computation are both tested here.

The tests are scoped to the unit contract. The manager is built with
``terminal_manager=None`` and a hand-rolled stub pool so neither
async adapters nor Dhara are involved.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.core.errors import RateLimitError
from mahavishnu.pools import PoolManager
from mahavishnu.pools.manager import CallerKind, _QuotaState, coerce_caller_kind

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _StubPool:
    """Minimal pool stand-in for unit tests that only need execute_task."""

    pool_id = "pool_test"
    config = MagicMock(min_workers=1, max_workers=2, pool_type="mahavishnu")
    _workers: dict[str, str] = {"w1": "w1"}

    async def execute_task(self, task):
        return {"pool_id": self.pool_id, "status": "completed", "result": "ok"}

    async def status(self):  # pragma: no cover - not exercised here
        return "running"


@pytest.fixture
def pool_mgr_with_quota() -> PoolManager:
    """A PoolManager pre-loaded with a single stub pool and no Dhara."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(terminal_manager=None, session_buddy_client=None)
    mgr._pools["pool_test"] = _StubPool()  # type: ignore[assignment]
    mgr._pool_worker_counts["pool_test"] = 1
    return mgr


# ---------------------------------------------------------------------------
# 1. coerce_caller_kind known strings
# ---------------------------------------------------------------------------


class TestCoerceCallerKindKnownStrings:
    """Strings that match a known enum member round-trip cleanly."""

    def test_coerce_caller_kind_known_strings(self) -> None:
        assert coerce_caller_kind("ultracode") is CallerKind.ULTRA_CODE
        assert coerce_caller_kind("workflow") is CallerKind.WORKFLOW


# ---------------------------------------------------------------------------
# 2. coerce_caller_kind unknown strings normalize to UNKNOWN bucket
# ---------------------------------------------------------------------------


class TestCoerceCallerKindUnknownStrings:
    """Unknown strings and ``None`` must collapse to ``CallerKind.UNKNOWN``.

    This is the bucket-bypass fix: a malicious or sloppy caller
    cannot inflate quota by inventing novel strings — they always
    land in the canonical ``UNKNOWN`` bucket.
    """

    def test_coerce_caller_kind_unknown_strings_normalize_to_unknown_bucket(self) -> None:
        assert coerce_caller_kind("ultracode-rogue-1") is CallerKind.UNKNOWN
        assert coerce_caller_kind(None) is CallerKind.UNKNOWN


# ---------------------------------------------------------------------------
# 3. coerce_caller_kind passes through CallerKind instances unchanged
# ---------------------------------------------------------------------------


class TestCoerceCallerKindEnumPassthrough:
    """Existing enum members are returned by identity (no copy)."""

    def test_coerce_caller_kind_passes_through_enum(self) -> None:
        original = CallerKind.CLAUDE_CODE
        result = coerce_caller_kind(original)
        assert result is original


# ---------------------------------------------------------------------------
# 4. Quota state initialization
# ---------------------------------------------------------------------------


class TestQuotaFirstRequestInitializesState:
    """A fresh PoolManager has no quota state until the first request."""

    def test_quota_first_request_initializes_state(
        self, pool_mgr_with_quota: PoolManager
    ) -> None:
        assert CallerKind.ULTRA_CODE not in pool_mgr_with_quota._caller_quota
        pool_mgr_with_quota._enforce_caller_quota(CallerKind.ULTRA_CODE)
        state = pool_mgr_with_quota._caller_quota[CallerKind.ULTRA_CODE]
        assert isinstance(state, _QuotaState)
        assert state.request_count == 1


# ---------------------------------------------------------------------------
# 5. Quota raises RateLimitError after max_per_window
# ---------------------------------------------------------------------------


class TestQuotaRaisesAfterMaxPerWindow:
    """Saturating the bucket raises ``RateLimitError`` with retry_after_seconds."""

    def test_quota_raises_after_max_per_window(
        self, pool_mgr_with_quota: PoolManager
    ) -> None:
        # Tighten the window for the test: 2 requests per window.
        pool_mgr_with_quota._caller_quota[CallerKind.ULTRA_CODE] = _QuotaState(
            window_start=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            request_count=0,
            window_size_seconds=60,
            max_per_window=2,
        )
        # First two calls succeed.
        pool_mgr_with_quota._enforce_caller_quota(
            CallerKind.ULTRA_CODE,
            now=datetime(2026, 1, 1, 12, 0, 5, tzinfo=UTC),
        )
        pool_mgr_with_quota._enforce_caller_quota(
            CallerKind.ULTRA_CODE,
            now=datetime(2026, 1, 1, 12, 0, 10, tzinfo=UTC),
        )
        # Third call exceeds the window and must raise.
        with pytest.raises(RateLimitError) as excinfo:
            pool_mgr_with_quota._enforce_caller_quota(
                CallerKind.ULTRA_CODE,
                now=datetime(2026, 1, 1, 12, 0, 15, tzinfo=UTC),
            )
        assert excinfo.value.details["retry_after_seconds"] > 0


# ---------------------------------------------------------------------------
# 6. Quota window resets after expiry
# ---------------------------------------------------------------------------


class TestQuotaWindowResetsAfterExpiry:
    """A new fixed window resets the counter, not just decrements it."""

    def test_quota_window_resets_after_expiry(
        self, pool_mgr_with_quota: PoolManager
    ) -> None:
        # Anchor first window.
        pool_mgr_with_quota._enforce_caller_quota(
            CallerKind.ULTRA_CODE,
            now=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        )
        state = pool_mgr_with_quota._caller_quota[CallerKind.ULTRA_CODE]
        assert state.request_count == 1

        # 61s later → window expired, counter resets to 1.
        pool_mgr_with_quota._enforce_caller_quota(
            CallerKind.ULTRA_CODE,
            now=datetime(2026, 1, 1, 12, 1, 1, tzinfo=UTC),
        )
        assert state.request_count == 1


# ---------------------------------------------------------------------------
# 7. retry_after_seconds equals remaining window time
# ---------------------------------------------------------------------------


class TestQuotaRetryAfterEqualsRemainingWindow:
    """``retry_after_seconds`` = ``max(0, window_size - elapsed)``."""

    def test_quota_retry_after_seconds_equals_remaining_window(
        self, pool_mgr_with_quota: PoolManager
    ) -> None:
        pool_mgr_with_quota._caller_quota[CallerKind.ULTRA_CODE] = _QuotaState(
            window_start=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            request_count=999,
            window_size_seconds=60,
            max_per_window=1,
        )
        with pytest.raises(RateLimitError) as excinfo:
            pool_mgr_with_quota._enforce_caller_quota(
                CallerKind.ULTRA_CODE,
                now=datetime(2026, 1, 1, 12, 0, 30, tzinfo=UTC),
            )
        # 60s window, 30s elapsed → 30s remaining.
        assert excinfo.value.details["retry_after_seconds"] == 30


# ---------------------------------------------------------------------------
# 8. Quotas are per-caller_kind — one bucket's saturation does not block another
# ---------------------------------------------------------------------------


class TestQuotaSeparatePerCallerKind:
    """Saturating ULTRA_CODE leaves CLI quota untouched."""

    def test_quota_separate_per_caller_kind(
        self, pool_mgr_with_quota: PoolManager
    ) -> None:
        # Saturate ULTRA_CODE.
        pool_mgr_with_quota._caller_quota[CallerKind.ULTRA_CODE] = _QuotaState(
            window_start=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            request_count=10,
            window_size_seconds=60,
            max_per_window=1,
        )
        with pytest.raises(RateLimitError):
            pool_mgr_with_quota._enforce_caller_quota(
                CallerKind.ULTRA_CODE,
                now=datetime(2026, 1, 1, 12, 0, 5, tzinfo=UTC),
            )
        # CLI bucket must still be empty (request_count == 0 after first call).
        pool_mgr_with_quota._enforce_caller_quota(
            CallerKind.CLI,
            now=datetime(2026, 1, 1, 12, 0, 5, tzinfo=UTC),
        )
        cli_state = pool_mgr_with_quota._caller_quota[CallerKind.CLI]
        assert cli_state.request_count == 1
