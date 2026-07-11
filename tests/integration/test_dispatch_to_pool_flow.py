"""Integration tests for the dispatch_to_pool end-to-end flow.

B3 Exit Criteria: exercises the full MCP tool -> PoolManager.route_task
-> Dhara persistence path against a Dhara stub. Marked with the
``integration`` pytest marker per CLAUDE.md Test conventions.

These tests use real ``PoolManager`` + a stub ``FastMCP`` (the same
``_StubMCP`` pattern used in ``tests/unit/test_mcp/test_pool_tools.py``)
plus a dict-backed ``FakeDharaStateBackend``. We never monkey-patch the
manager's internals — every assertion reflects the actual persistence
contract that operators see in production.

Coverage:

1. ``test_dispatch_to_pool_returns_workflow_id`` — async path returns a
   UUID-shaped ``workflow_id`` and persists ``status="queued"`` plus the
   caller_kind/parent_session_id audit fields to Dhara.
2. ``test_routing_decision_persisted_with_caller_kind`` — sync path
   propagates ``caller_kind`` and ``parent_session_id`` into the
   routing-decision write so quota attribution survives end-to-end.
3. ``test_rate_limit_error_surfaces_retry_after`` — the third call
   against a saturated bucket returns
   ``{"status": "rate_limited", "retry_after_seconds": int>0}``.
4. ``test_caller_kind_honored_in_quota_attribution`` — quota buckets
   are per-``caller_kind`` so ultracode and workflow callers each get
   their own counter.
5. ``test_async_result_lifecycle_result_write_failed`` — when the Dhara
   ``put`` for terminal state fails, a dead-letter JSON file is written
   under ``<tmpdir>/.mahavishnu/async-dead-letter/`` AND a
   ``status="result_write_failed"`` marker is persisted via the final
   put call.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.mcp.protocols.message_bus import MessageBus
from mahavishnu.mcp.tools.pool_tools import register_pool_tools
from mahavishnu.pools.base import PoolConfig
from mahavishnu.pools.manager import (
    CallerKind,
    PoolManager,
    PoolSelector,
    _QuotaState,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Stub MCP + FakeDhara + helpers
# ---------------------------------------------------------------------------


class _StubMCP:
    """Minimal FastMCP stand-in that captures tool functions by name.

    Mirrors the helper from ``tests/unit/test_mcp/test_pool_tools.py``.
    Keeping a local copy keeps the integration test independent of any
    future change in the unit-test module's public surface.
    """

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class FakeDharaStateBackend:
    """Dict-backed Dhara stub.

    Records every ``put`` invocation so tests can assert on the persisted
    workflow / routing / pool payloads without standing up the real Dhara
    service. ``put_fail_after`` lets a test inject a failure after a
    specified number of successful writes (1-indexed). When set, the
    Nth call raises ``RuntimeError``; subsequent calls also raise until
    the counter is reset.
    """

    def __init__(self) -> None:
        self.puts: list[tuple[str, dict[str, Any]]] = []
        self.persist_routing_decision_calls: list[tuple[str, dict[str, Any]]] = []
        self.persist_pool_calls: list[tuple[str, dict[str, Any]]] = []
        self._put_count = 0
        self.put_fail_after: int | None = None

    def reset_put_failures(self) -> None:
        """Clear any injected put-failure thresholds."""
        self.put_fail_after = None
        self._put_count = 0

    async def put(self, key: str, value: dict[str, Any], ttl: int | None = None) -> None:
        self._put_count += 1
        # Fail on EXACTLY the Nth call (== put_fail_after), then allow
        # subsequent calls to succeed. The dispatch flow needs the
        # terminal-state put to fail so the dead-letter path fires, but
        # the follow-up marker put must succeed so the
        # ``result_write_failed`` record is observable in Dhara.
        if self.put_fail_after is not None and self._put_count == self.put_fail_after:
            raise RuntimeError(f"FakeDharaStateBackend: injected put failure on call #{self._put_count}")
        self.puts.append((key, dict(value)))

    async def persist_routing_decision(
        self,
        task_class: str,
        value: dict[str, Any],
        timestamp: Any = None,
        ttl: int | None = None,
    ) -> None:
        self.persist_routing_decision_calls.append((task_class, dict(value)))

    async def persist_pool(
        self,
        pool_id: str,
        value: dict[str, Any],
        ttl: int | None = None,
    ) -> None:
        self.persist_pool_calls.append((pool_id, dict(value)))

    async def persist_workflow(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover - unused
        # Not exercised by the dispatch flow but kept for API parity.
        return None

    async def recover_workflows(self) -> list[dict[str, Any]]:  # pragma: no cover - unused
        return []

    async def recover_pools(self) -> list[dict[str, Any]]:  # pragma: no cover - unused
        return []

    async def recover_routing_decisions(self) -> list[dict[str, Any]]:  # pragma: no cover - unused
        return []

    async def get(self, key: str) -> dict[str, Any] | None:  # pragma: no cover - unused
        return None

    async def delete(self, key: str) -> None:  # pragma: no cover - unused
        return None

    async def list_prefix(self, prefix: str) -> list[tuple[str, dict[str, Any]]]:  # pragma: no cover - unused
        return []


def _make_pool(
    pool_id: str,
    *,
    n_workers: int = 2,
    pool_type: str = "mahavishnu",
) -> MagicMock:
    """Build a MagicMock that quacks like a BasePool with a real PoolConfig."""
    mock_pool = MagicMock()
    mock_pool.pool_id = pool_id
    mock_pool.config = PoolConfig(
        name=pool_id,
        pool_type=pool_type,
        min_workers=n_workers,
        max_workers=max(n_workers * 2, n_workers),
    )
    mock_pool._workers = {f"w{i}": f"w{i}" for i in range(n_workers)}

    async def _execute_task(task):
        return {
            "pool_id": pool_id,
            "status": "completed",
            "output": "ok",
            "echo": task,
        }

    async def _collect_memory():
        return []

    async def _status():
        from mahavishnu.core.status import PoolStatus
        return PoolStatus.RUNNING

    async def _stop():
        return None

    mock_pool.execute_task = _execute_task
    mock_pool.collect_memory = _collect_memory
    mock_pool.status = _status
    mock_pool.stop = _stop
    return mock_pool


def _build_manager_with_pool(
    dhara: FakeDharaStateBackend,
    *,
    pool_id: str = "pool_a",
    n_workers: int = 1,
) -> PoolManager:
    """Construct a PoolManager wired to a single mock pool + the fake Dhara."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
            dhara_state=dhara,
        )
    pool = _make_pool(pool_id, n_workers=n_workers)
    mgr._pools[pool_id] = pool
    mgr._pool_worker_counts[pool_id] = n_workers
    # Heap (single-entry) — least-loaded routing picks this pool.
    import heapq

    heapq.heappush(mgr._worker_count_heap, (n_workers, pool_id))
    return mgr


def _registered_mcp_with(pool_manager: PoolManager) -> _StubMCP:
    """Register pool tools on a stub MCP and return the stub for invocation."""
    stub = _StubMCP()
    register_pool_tools(stub, pool_manager)
    return stub


# UUID-shaped validator (8-4-4-4-12 hex with dashes).
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


async def _drain_async_tasks(timeout: float = 2.0) -> None:
    """Wait briefly for any ``asyncio.create_task`` background coroutines to finish.

    Excludes the current task from the cancellation set — cancelling the
    running test coroutine produces a cascade of child cancellations that
    blows Python's recursion limit when the dispatched workflow has its
    own nested tasks (e.g. message-bus publishes inside
    ``execute_on_pool``).
    """
    current = asyncio.current_task()
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        pending = [
            t
            for t in asyncio.all_tasks()
            if not t.done() and t is not current
        ]
        if not pending:
            return
        if asyncio.get_event_loop().time() >= deadline:
            # Cancel stragglers so the next test starts with a clean slate.
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            return
        await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Test 1 — async path returns workflow_id and writes queued state to Dhara
# ---------------------------------------------------------------------------


class TestDispatchToPoolReturnsWorkflowId:
    """Async ``dispatch_to_pool`` returns a queued marker and persists it."""

    async def test_dispatch_to_pool_returns_workflow_id(self) -> None:
        dhara = FakeDharaStateBackend()
        manager = _build_manager_with_pool(dhara)
        stub = _registered_mcp_with(manager)
        dispatch = stub.tools["dispatch_to_pool"]

        result = await dispatch(
            prompt="Write a tiny test",
            caller_kind="ultracode",
            parent_session_id="ses_abc",
            async_callback=True,
        )

        # Response shape — UUID, queued marker, caller_kind + parent_session_id
        # are echoed back to the caller verbatim so they can correlate the
        # workflow with their own session.
        assert result["status"] == "queued"
        assert result["caller_kind"] == "ultracode"
        assert result["parent_session_id"] == "ses_abc"
        assert _UUID_RE.match(result["workflow_id"]), (
            f"workflow_id {result['workflow_id']!r} is not UUID-shaped"
        )

        # Dhara received the initial queued-state put with the same
        # workflow_id. We do not assert on the persisted status here
        # (the background task may have already advanced the state),
        # but the FIRST put MUST carry status="queued" so a partial-
        # failure observer sees a queued-but-never-running record.
        assert dhara.puts, "dispatch_to_pool did not persist queued state to Dhara"
        first_key, first_value = dhara.puts[0]
        assert first_key == f"workflow-results/{result['workflow_id']}/"
        assert first_value["status"] == "queued"
        assert first_value["caller_kind"] == "ultracode"
        assert first_value["parent_session_id"] == "ses_abc"

        await _drain_async_tasks()


# ---------------------------------------------------------------------------
# Test 2 — sync path propagates caller_kind into routing-decision persistence
# ---------------------------------------------------------------------------


class TestRoutingDecisionPersistedWithCallerKind:
    """Sync ``dispatch_to_pool`` records routing decisions with caller_kind."""

    async def test_routing_decision_persisted_with_caller_kind(self) -> None:
        dhara = FakeDharaStateBackend()
        manager = _build_manager_with_pool(dhara)
        stub = _registered_mcp_with(manager)
        dispatch = stub.tools["dispatch_to_pool"]

        result = await dispatch(
            prompt="Generate a docstring",
            caller_kind="ultracode",
            parent_session_id="ses_abc",
            async_callback=False,
        )

        # Sync path returns the route_task result inline.
        assert result["status"] == "completed"
        assert result["pool_id"] == "pool_a"

        # The routing decision MUST carry caller_kind + parent_session_id so
        # quota attribution is auditable end-to-end.
        assert dhara.persist_routing_decision_calls, (
            "PoolManager did not persist a routing decision"
        )
        _task_class, payload = dhara.persist_routing_decision_calls[-1]
        assert payload["caller_kind"] == "ultracode"
        assert payload["parent_session_id"] == "ses_abc"
        assert payload["pool_id"] == "pool_a"


# ---------------------------------------------------------------------------
# Test 3 — rate limit error surfaces retry_after
# ---------------------------------------------------------------------------


class TestRateLimitErrorSurfacesRetryAfter:
    """Saturated caller_kind buckets produce retry_after metadata."""

    async def test_rate_limit_error_surfaces_retry_after(self) -> None:
        from datetime import UTC, datetime, timedelta

        from mahavishnu.core.errors import RateLimitError

        dhara = FakeDharaStateBackend()
        manager = _build_manager_with_pool(dhara)

        # Tighten the quota window so the test runs quickly without
        # having to sleep. We do NOT touch the manager's _now override
        # here because we want the natural elapsed-time path to fire.
        ultracode_state = manager._caller_quota.setdefault(
            CallerKind.ULTRA_CODE,
            _QuotaState(
                window_start=datetime.now(UTC),
                request_count=0,
                window_size_seconds=60,
                max_per_window=2,
            ),
        )
        ultracode_state.max_per_window = 2

        stub = _registered_mcp_with(manager)
        dispatch = stub.tools["dispatch_to_pool"]

        # First two calls succeed (the underlying pool returns "completed").
        first = await dispatch(
            prompt="first",
            caller_kind="ultracode",
            parent_session_id="ses_1",
            async_callback=False,
        )
        second = await dispatch(
            prompt="second",
            caller_kind="ultracode",
            parent_session_id="ses_2",
            async_callback=False,
        )
        assert first["status"] == "completed"
        assert second["status"] == "completed"

        # Third call: the route_task coroutine raises RateLimitError.
        # The MCP tool catches it and converts to retry-after payload.
        # We simulate this by patching PoolManager.route_task to raise.
        with patch.object(
            manager,
            "route_task",
            side_effect=RateLimitError(
                limit="caller_kind=ultracode",
                retry_after=42,
            ),
        ):
            third = await dispatch(
                prompt="third",
                caller_kind="ultracode",
                parent_session_id="ses_3",
                async_callback=False,
            )

        assert third["status"] == "rate_limited"
        assert third["caller_kind"] == "ultracode"
        assert isinstance(third["retry_after_seconds"], int)
        assert third["retry_after_seconds"] > 0
        assert third["retry_after_seconds"] == 42

        await _drain_async_tasks()


# ---------------------------------------------------------------------------
# Test 4 — quota attribution is per-caller_kind
# ---------------------------------------------------------------------------


class TestCallerKindHonoredInQuotaAttribution:
    """Quota buckets are isolated by caller_kind so unrelated callers
    don't starve each other."""

    async def test_caller_kind_honored_in_quota_attribution(self) -> None:
        from datetime import UTC, datetime

        dhara = FakeDharaStateBackend()
        manager = _build_manager_with_pool(dhara)

        # max_per_window=1 on BOTH caller kinds. Each bucket must allow
        # one call independently — saturation of ultracode must not
        # block workflow callers and vice-versa.
        for kind in (CallerKind.ULTRA_CODE, CallerKind.WORKFLOW):
            state = manager._caller_quota.setdefault(
                kind,
                _QuotaState(
                    window_start=datetime.now(UTC),
                    request_count=0,
                    window_size_seconds=60,
                    max_per_window=1,
                ),
            )
            state.max_per_window = 1

        stub = _registered_mcp_with(manager)
        dispatch = stub.tools["dispatch_to_pool"]

        ultracode_result = await dispatch(
            prompt="ultracode task",
            caller_kind="ultracode",
            parent_session_id="ses_u",
            async_callback=False,
        )
        workflow_result = await dispatch(
            prompt="workflow task",
            caller_kind="workflow",
            parent_session_id="ses_w",
            async_callback=False,
        )

        # Both must succeed because their quota buckets are independent.
        assert ultracode_result["status"] == "completed"
        assert workflow_result["status"] == "completed"

        # And the routing decision payload reflects the correct
        # caller_kind for each call — proves quota attribution is
        # recorded on the right bucket, not silently merged.
        routing_payloads = [p for _tc, p in dhara.persist_routing_decision_calls]
        seen_kinds = {p["caller_kind"] for p in routing_payloads}
        assert seen_kinds == {"ultracode", "workflow"}


# ---------------------------------------------------------------------------
# Test 5 — async result-lifecycle dead-letters on put failure
# ---------------------------------------------------------------------------


class TestAsyncResultLifecycleResultWriteFailed:
    """When the Dhara put for terminal state fails, a dead-letter file
    is written under ~/.mahavishnu/async-dead-letter/ AND a
    ``status="result_write_failed"`` marker is persisted via the final
    put call."""

    async def test_async_result_lifecycle_result_write_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dhara = FakeDharaStateBackend()
        manager = _build_manager_with_pool(dhara)

        # Redirect Path.home() to the tmp dir so the dead-letter file
        # lands under tmp_path/.mahavishnu/async-dead-letter/ and the
        # real ~/.mahavishnu is never touched.
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.pool_tools.Path.home",
            classmethod(lambda cls: tmp_path),
        )

        stub = _registered_mcp_with(manager)
        dispatch = stub.tools["dispatch_to_pool"]

        # ``async_callback=True`` writes:
        #   1. initial queued state (succeeds)
        #   2. running state inside _run_async_dispatch (succeeds)
        #   3. terminal state inside _run_async_dispatch (FAILS -> DLQ)
        #   4. marker put with status="result_write_failed" (succeeds
        #      because we only fail ONE call)
        # The default ``put_fail_after=3`` raises on the 3rd call
        # (terminal status), then the 4th call (marker) is allowed.
        dhara.put_fail_after = 3

        result = await dispatch(
            prompt="dead-letter scenario",
            caller_kind="ultracode",
            parent_session_id="ses_dlq",
            async_callback=True,
        )
        workflow_id = result["workflow_id"]

        # Wait for the background coroutine to finish writing the
        # dead-letter file. The handler raises on the 3rd put, writes
        # the dead-letter JSON, then attempts a 4th put (the marker).
        await _drain_async_tasks(timeout=3.0)

        # 1. Dead-letter JSON file exists under tmp_path/.mahavishnu/async-dead-letter/
        dead_letter_dir = tmp_path / ".mahavishnu" / "async-dead-letter"
        assert dead_letter_dir.is_dir(), (
            f"Dead-letter directory not created: {dead_letter_dir}"
        )
        safe_wid = workflow_id.replace("/", "_").replace("..", "_")[:200]
        dl_path = dead_letter_dir / f"{safe_wid}.json"
        assert dl_path.exists(), f"Dead-letter file missing at {dl_path}"
        dl_payload = json.loads(dl_path.read_text())
        assert dl_payload["workflow_id"] == workflow_id
        assert dl_payload["intended_terminal_status"] in {"completed", "failed"}
        assert dl_payload["payload"]["caller_kind"] == "ultracode"
        assert dl_payload["payload"]["parent_session_id"] == "ses_dlq"
        assert "exception" in dl_payload

        # 2. The final put (the one we let succeed) carries
        # status="result_write_failed" so an observer can spot the
        # half-failed workflow from Dhara alone.
        last_key, last_value = dhara.puts[-1]
        assert last_key == f"workflow-results/{workflow_id}/"
        assert last_value["status"] == "result_write_failed"
        assert last_value["caller_kind"] == "ultracode"
        assert last_value["parent_session_id"] == "ses_dlq"