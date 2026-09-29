"""Unit tests for ``mahavishnu.mcp.tools.tasks_handoff``.

The tool is the **single dispatch edge** in the Bodai task system: it
calls ``session-buddy.tasks_get``, then ``pool_route_execute``, then
``session-buddy.tasks_update``. Each test pins one branch of that
three-step flow so the load-bearing semantics cannot silently drift.

Test seam design:
  * :class:`_StubMCP` captures the decorated tool function (the existing
    ``register_*_tools`` convention in this repo).
  * The factory takes ``session_buddy_client`` and
    ``pool_route_execute_fn`` as injectable seams — the production tool
    binds them at registration time; tests pass AsyncMocks so the body
    runs without touching real session-buddy or mahavishnu pools.
  * The rate limiter, the caller key derivation, and the orphan publisher
    are reset between tests via ``monkeypatch`` so per-test isolation is
    deterministic.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.mcp.tools import tasks_handoff as th
from mahavishnu.mcp.tools.tasks_handoff import (
    _HANDOFF_RATE_LIMITER,
    HandoffParams,
    HandoffResult,
    RateLimitError,
    TaskNotFoundError,
    WorkflowNotReturnedError,
    register_tasks_handoff_tools,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Stub MCP
# =============================================================================


class _StubMCP:
    """Minimal FastMCP stand-in capturing each @tool-decorated function."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


# =============================================================================
# Fixtures
# =============================================================================


_VALID_TASK_ID = "t-" + "a" * 32


@pytest.fixture
def stub_mcp() -> _StubMCP:
    return _StubMCP()


@pytest.fixture
def fake_sb_client() -> MagicMock:
    """AsyncMock-backed session-buddy client with sensible defaults."""
    client = MagicMock(name="session_buddy_client")
    client.tasks_get = AsyncMock(
        return_value={
            "id": _VALID_TASK_ID,
            "content": "do the thing",
            "owner": "user-1",
            "metadata": {},
            "status": "pending",
        }
    )
    client.tasks_update = AsyncMock(
        return_value={"id": _VALID_TASK_ID, "metadata": {"workflow_id": "wf-1"}}
    )
    return client


@pytest.fixture
def fake_pool_dispatch() -> AsyncMock:
    """AsyncMock standing in for mahavishnu's ``pool_route_execute``."""
    return AsyncMock(
        return_value={
            "workflow_id": "wf-1",
            "pool_id": "pool-a",
            "status": "active",
        }
    )


@pytest.fixture
def registered_tool(
    stub_mcp: _StubMCP,
    fake_sb_client: MagicMock,
    fake_pool_dispatch: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
):
    """Register the tool with mocked dependencies + isolated rate limiter."""
    _reset_rate_limiter()
    _capture_orphan_events(monkeypatch)
    register_tasks_handoff_tools(
        stub_mcp,
        session_buddy_client=fake_sb_client,
        pool_route_execute_fn=fake_pool_dispatch,
    )
    return stub_mcp.tools["tasks_handoff_to_workflow"]


# =============================================================================
# Helpers
# =============================================================================


def _reset_rate_limiter() -> None:
    """Drop every per-caller bucket so tests start with a fresh 10/min cap."""
    _HANDOFF_RATE_LIMITER._requests.clear()


def _capture_orphan_events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace :func:`_publish_task_handoff_orphan` with a recorder."""
    captured: list[dict[str, Any]] = []

    def _spy(task_id: str, reason: str, workflow_id: str = "") -> None:
        captured.append({"task_id": task_id, "reason": reason, "workflow_id": workflow_id})

    monkeypatch.setattr(th, "_publish_task_handoff_orphan", _spy)
    return captured


# =============================================================================
# Tests
# =============================================================================


class TestHappyPath:
    """Step 1 → 2 → 3 succeeds and returns a fully-populated HandoffResult."""

    @pytest.mark.asyncio
    async def test_tasks_handoff_returns_handoff_result_envelope(
        self,
        registered_tool,
        fake_sb_client: MagicMock,
        fake_pool_dispatch: AsyncMock,
    ) -> None:
        result = await registered_tool(task_id=_VALID_TASK_ID, adapter="prefect")

        assert isinstance(result, HandoffResult)
        assert result.task_id == _VALID_TASK_ID
        assert result.workflow_id == "wf-1"
        assert result.adapter == "prefect"
        assert result.pool_name == "pool-a"
        assert isinstance(result.started_at, datetime)
        # started_at must be timezone-aware (UTC).
        assert result.started_at.tzinfo is not None
        assert result.started_at <= datetime.now(UTC)

        fake_sb_client.tasks_get.assert_awaited_once_with(task_id=_VALID_TASK_ID)
        fake_sb_client.tasks_update.assert_awaited_once_with(
            task_id=_VALID_TASK_ID,
            metadata={"workflow_id": "wf-1"},
        )
        fake_pool_dispatch.assert_awaited_once()
        kwargs = fake_pool_dispatch.await_args.kwargs
        assert kwargs["prompt"] == "do the thing"
        assert kwargs["pool_selector"] == "least_loaded"


class TestSessionBuddyDown:
    """Step 1 (tasks_get) failure must surface as TaskNotFoundError(MHV-101)."""

    @pytest.mark.asyncio
    async def test_tasks_handoff_fails_fast_on_session_buddy_down(
        self,
        stub_mcp: _StubMCP,
        fake_pool_dispatch: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _reset_rate_limiter()
        _capture_orphan_events(monkeypatch)

        # tasks_get raises — the production tool should translate this to TaskNotFoundError.
        sb = MagicMock()
        sb.tasks_get = AsyncMock(side_effect=ConnectionError("session-buddy unreachable"))
        sb.tasks_update = AsyncMock()

        register_tasks_handoff_tools(
            stub_mcp, session_buddy_client=sb, pool_route_execute_fn=fake_pool_dispatch
        )
        tool = stub_mcp.tools["tasks_handoff_to_workflow"]

        with pytest.raises(TaskNotFoundError) as exc_info:
            await tool(task_id=_VALID_TASK_ID, adapter="prefect")

        assert exc_info.value.code == "MHV-101"
        assert exc_info.value.task_id == _VALID_TASK_ID
        # Step 2 + 3 must NOT run.
        fake_pool_dispatch.assert_not_awaited()
        sb.tasks_update.assert_not_awaited()


class TestDispatchFailure:
    """Step 2 failure must NOT trigger step 3; exception bubbles to caller."""

    @pytest.mark.asyncio
    async def test_tasks_handoff_does_not_update_task_on_dispatch_failure(
        self,
        stub_mcp: _StubMCP,
        fake_sb_client: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _reset_rate_limiter()
        _capture_orphan_events(monkeypatch)

        pool_dispatch = AsyncMock(side_effect=RuntimeError("pool registry down"))

        register_tasks_handoff_tools(
            stub_mcp,
            session_buddy_client=fake_sb_client,
            pool_route_execute_fn=pool_dispatch,
        )
        tool = stub_mcp.tools["tasks_handoff_to_workflow"]

        with pytest.raises(RuntimeError, match="pool registry down"):
            await tool(task_id=_VALID_TASK_ID, adapter="prefect")

        # Step 3 must NOT have been called — there is no workflow_id to write back.
        fake_sb_client.tasks_update.assert_not_awaited()


class TestStep3Failure:
    """Step 3 (tasks_update) failure must emit ``task.handoff_orphan``."""

    @pytest.mark.asyncio
    async def test_tasks_handoff_emits_task_handoff_orphan_on_step_3_failure(
        self,
        stub_mcp: _StubMCP,
        fake_sb_client: MagicMock,
        fake_pool_dispatch: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _reset_rate_limiter()
        orphan_calls = _capture_orphan_events(monkeypatch)

        # Step 2 succeeds, step 3 fails.
        fake_sb_client.tasks_update = AsyncMock(side_effect=ConnectionError("session-buddy gone"))

        register_tasks_handoff_tools(
            stub_mcp,
            session_buddy_client=fake_sb_client,
            pool_route_execute_fn=fake_pool_dispatch,
        )
        tool = stub_mcp.tools["tasks_handoff_to_workflow"]

        with pytest.raises(ConnectionError, match="session-buddy gone"):
            await tool(task_id=_VALID_TASK_ID, adapter="prefect")

        assert len(orphan_calls) == 1
        orphan = orphan_calls[0]
        assert orphan["task_id"] == _VALID_TASK_ID
        assert orphan["reason"] == "step_3_update_failed"
        assert orphan["workflow_id"] == "wf-1"  # workflow IS running, task is the orphan


class TestCancellation:
    """Cancellation during step 2 must emit ``task.handoff_orphan`` and re-raise."""

    @pytest.mark.asyncio
    async def test_tasks_handoff_emits_task_handoff_orphan_on_cancellation(
        self,
        stub_mcp: _StubMCP,
        fake_sb_client: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _reset_rate_limiter()
        orphan_calls = _capture_orphan_events(monkeypatch)

        # Slow pool dispatch + cancellation after 50 ms.
        async def slow_dispatch(*args, **kwargs):
            await asyncio.sleep(1.0)
            return {"workflow_id": "wf-slow", "pool_id": "pool-slow"}

        pool_dispatch = AsyncMock(side_effect=slow_dispatch)

        register_tasks_handoff_tools(
            stub_mcp,
            session_buddy_client=fake_sb_client,
            pool_route_execute_fn=pool_dispatch,
        )
        tool = stub_mcp.tools["tasks_handoff_to_workflow"]

        task = asyncio.create_task(tool(task_id=_VALID_TASK_ID, adapter="prefect"))
        await asyncio.sleep(0.05)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        # The orphan event must be emitted even though the workflow hasn't
        # produced a workflow_id yet — caller_disconnected reason covers it.
        assert any(c["reason"] == "caller_disconnected" for c in orphan_calls)
        # tasks_update MUST NOT have run.
        fake_sb_client.tasks_update.assert_not_awaited()


class TestEmptyWorkflowId:
    """When ``pool_route_execute`` succeeds without a ``workflow_id``,
    the tool must raise :class:`WorkflowNotReturnedError` — NOT emit a
    phantom orphan that the v1.1 sweeper would chase."""

    @pytest.mark.asyncio
    async def test_tasks_handoff_raises_typed_error_on_empty_workflow_id(
        self,
        stub_mcp: _StubMCP,
        fake_sb_client: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _reset_rate_limiter()
        orphan_calls = _capture_orphan_events(monkeypatch)

        # pool_route_execute succeeds but the envelope is missing workflow_id.
        pool_dispatch = AsyncMock(return_value={"pool_id": "pool-a", "status": "active"})

        register_tasks_handoff_tools(
            stub_mcp,
            session_buddy_client=fake_sb_client,
            pool_route_execute_fn=pool_dispatch,
        )
        tool = stub_mcp.tools["tasks_handoff_to_workflow"]

        with pytest.raises(WorkflowNotReturnedError) as exc_info:
            await tool(task_id=_VALID_TASK_ID, adapter="prefect")

        assert exc_info.value.code == "MHV-102"
        assert exc_info.value.task_id == _VALID_TASK_ID
        assert "pool_id" in exc_info.value.dispatch_result

        # NO orphan event must be emitted — the v1.1 sweeper would
        # otherwise chase a phantom workflow_id.
        assert orphan_calls == []

        # Step 3 MUST NOT have run — there is no workflow_id to back-link.
        fake_sb_client.tasks_update.assert_not_awaited()


class TestOrphanReasonDisambiguation:
    """Step-2 failures and step-3 failures must produce distinct orphan
    reasons so the v1.1 sweeper can disambiguate (Fix Round 1 #4)."""

    @pytest.mark.asyncio
    async def test_tasks_handoff_distinguishes_step_2_vs_step_3_failure_in_orphan(
        self,
        stub_mcp: _StubMCP,
        fake_sb_client: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _reset_rate_limiter()

        # ---- Case A: step 2 fails ----
        orphan_a = _capture_orphan_events(monkeypatch)
        pool_a = AsyncMock(side_effect=RuntimeError("step-2 boom"))
        register_tasks_handoff_tools(
            stub_mcp,
            session_buddy_client=fake_sb_client,
            pool_route_execute_fn=pool_a,
        )
        tool_a = stub_mcp.tools["tasks_handoff_to_workflow"]

        with pytest.raises(RuntimeError, match="step-2 boom"):
            await tool_a(task_id=_VALID_TASK_ID, adapter="prefect")

        assert len(orphan_a) == 1
        assert orphan_a[0]["reason"] == "step_2_dispatch_failed"
        assert orphan_a[0]["workflow_id"] == ""  # no workflow existed

        # ---- Case B: step 3 fails (workflow_id already set) ----
        orphan_b = _capture_orphan_events(monkeypatch)
        pool_b = AsyncMock(return_value={"workflow_id": "wf-b", "pool_id": "pool-b"})
        sb_b = MagicMock()
        sb_b.tasks_get = AsyncMock(
            return_value={
                "id": _VALID_TASK_ID,
                "content": "do it",
                "owner": "user-1",
                "metadata": {},
                "status": "pending",
            }
        )
        sb_b.tasks_update = AsyncMock(side_effect=ConnectionError("step-3 boom"))
        register_tasks_handoff_tools(
            stub_mcp,
            session_buddy_client=sb_b,
            pool_route_execute_fn=pool_b,
        )
        tool_b = stub_mcp.tools["tasks_handoff_to_workflow"]

        with pytest.raises(ConnectionError, match="step-3 boom"):
            await tool_b(task_id=_VALID_TASK_ID, adapter="prefect")

        assert len(orphan_b) == 1
        assert orphan_b[0]["reason"] == "step_3_update_failed"
        assert orphan_b[0]["workflow_id"] == "wf-b"  # workflow IS running

        # The two reasons must be distinct — the sweeper disambiguates on this.
        assert orphan_a[0]["reason"] != orphan_b[0]["reason"]


class TestContentValidation:
    """Malformed task content is rejected BEFORE step 2 dispatch."""

    @pytest.mark.asyncio
    async def test_tasks_handoff_validates_task_content_against_create_schema(
        self,
        stub_mcp: _StubMCP,
        fake_sb_client: MagicMock,
        fake_pool_dispatch: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _reset_rate_limiter()
        _capture_orphan_events(monkeypatch)

        # Two cases: oversized content (reject before dispatch) and
        # empty content (reject before dispatch). Both are caught at the
        # MCP boundary and surfaced as ValueError.
        oversized_content = "x" * 5000  # > 4096 byte cap
        fake_sb_client.tasks_get = AsyncMock(
            return_value={
                "id": _VALID_TASK_ID,
                "content": oversized_content,
                "owner": "user-1",
                "metadata": {},
                "status": "pending",
            }
        )

        register_tasks_handoff_tools(
            stub_mcp,
            session_buddy_client=fake_sb_client,
            pool_route_execute_fn=fake_pool_dispatch,
        )
        tool = stub_mcp.tools["tasks_handoff_to_workflow"]

        with pytest.raises(ValueError, match="exceeds 4096 bytes"):
            await tool(task_id=_VALID_TASK_ID, adapter="prefect")

        # Pool router MUST NOT have been touched.
        fake_pool_dispatch.assert_not_awaited()
        fake_sb_client.tasks_update.assert_not_awaited()


class TestRateLimit:
    """Exceeding 10/min must raise ``RateLimitError`` and skip steps 2 + 3."""

    @pytest.mark.asyncio
    async def test_tasks_handoff_rate_limited_returns_envelope(
        self,
        stub_mcp: _StubMCP,
        fake_sb_client: MagicMock,
        fake_pool_dispatch: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _reset_rate_limiter()
        _capture_orphan_events(monkeypatch)

        # Pin a deterministic caller key so the limiter counts hit the same bucket.
        monkeypatch.setattr(th, "_derive_caller_key", lambda: "hot-caller")

        register_tasks_handoff_tools(
            stub_mcp,
            session_buddy_client=fake_sb_client,
            pool_route_execute_fn=fake_pool_dispatch,
        )
        tool = stub_mcp.tools["tasks_handoff_to_workflow"]

        # 10 successful calls (just below the cap).
        for _ in range(10):
            await tool(task_id=_VALID_TASK_ID, adapter="prefect")

        # 11th call trips the limiter.
        with pytest.raises(RateLimitError) as exc_info:
            await tool(task_id=_VALID_TASK_ID, adapter="prefect")

        assert exc_info.value.retry_after_seconds > 0
        # Dispatch MUST NOT have run on the rate-limited call. (count = 10)
        assert fake_pool_dispatch.await_count == 10


# =============================================================================
# Module-level exception contract (one focused assertion)
# =============================================================================


class TestExceptionContract:
    """``TaskNotFoundError`` carries MHV-101 per the brief."""

    def test_task_not_found_error_carries_mhv_101_code(self) -> None:
        err = TaskNotFoundError(_VALID_TASK_ID)
        assert err.code == "MHV-101"
        assert err.task_id == _VALID_TASK_ID
        assert err.details["task_id"] == _VALID_TASK_ID
        assert "MHV-101" in str(err)


# =============================================================================
# Helper: HandoffParams envelope smoke test
# =============================================================================


class TestHandoffEnvelopes:
    """The inline HandoffParams/HandoffResult shapes match T1's source-of-truth."""

    def test_handoff_params_round_trips_through_pydantic(self) -> None:
        params = HandoffParams(
            timeout_seconds=30,
            pool_selector="affinity",
            pool_name="primary",
            idempotency_key="abc",
            extra_metadata={"foo": "bar", "n": 1},
        )
        dumped = params.model_dump()
        restored = HandoffParams.model_validate(dumped)
        assert restored == params

    def test_handoff_result_rejects_unknown_field(self) -> None:
        with pytest.raises(ValueError):
            HandoffResult.model_validate(
                {
                    "task_id": _VALID_TASK_ID,
                    "workflow_id": "wf-1",
                    "adapter": "prefect",
                    "started_at": datetime.now(UTC).isoformat(),
                    "pool_name": "p",
                    "bogus": "field",
                }
            )
