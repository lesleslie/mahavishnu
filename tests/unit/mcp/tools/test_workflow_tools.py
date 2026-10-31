"""Verify workflow_get_outcome returns a validated WorkflowOutcome struct.

The reader binds the substrate facade (:mod:`mahavishnu.core.substrate`)
directly. The module is imported — not the function — so tests can
substitute it with ``monkeypatch.setattr(
"mahavishnu.mcp.tools.workflow_tools.substrate", ...)``.

The facade's ``get`` is awaitable, so a substituted ``get`` must be an
``AsyncMock`` (or any awaitable). The happy-path tests use the *real*
facade over the process-local store instead of a mock, so the write →
read round trip is exercised end to end.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal
from unittest.mock import AsyncMock, MagicMock

from fastmcp import FastMCP
import pytest
from structlog.testing import capture_logs

from mahavishnu.core import substrate
from mahavishnu.core.models.persistence import WorkflowOutcome
from mahavishnu.mcp.tools.workflow_tools import (
    register_workflow_tools,
    workflow_get_outcome,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolated_kv_store() -> Iterator[None]:
    """Drop any record this module leaves in the shared KV store.

    The suite-wide fixture in ``tests/conftest.py`` already clears the
    shared store around every test; this one keeps the module
    self-contained so the tests stay correct when run in isolation.
    """
    from mahavishnu.core.kv_store import kv_store

    kv_store.clear()
    yield
    kv_store.clear()


class _StubSubstrate:
    """Stand-in for :mod:`mahavishnu.core.substrate`.

    Only ``get`` matters to the reader, and the facade's ``get`` is
    awaitable — hence ``AsyncMock``.
    """

    def __init__(self, payload: Any = None) -> None:
        self.get = AsyncMock(return_value=payload)


def _stub_substrate(monkeypatch: pytest.MonkeyPatch, payload: Any = None) -> _StubSubstrate:
    """Substitute the reader's substrate with a recording stub.

    Patches the module attribute on ``workflow_tools``, so the stub
    replaces the facade for this test only.
    """
    stub = _StubSubstrate(payload)
    monkeypatch.setattr(
        "mahavishnu.mcp.tools.workflow_tools.substrate",
        stub,
    )
    return stub


def _write_outcome(
    workflow_id: str,
    status: Literal["succeeded", "failed", "cancelled"] = "succeeded",
) -> WorkflowOutcome:
    """Persist a record through the real substrate facade.

    Mirrors the outcome writer: ``substrate.put`` the validated struct
    under ``f"workflow-results/{workflow_id}/"``.
    """
    outcome = WorkflowOutcome(
        workflow_id=workflow_id,
        status=status,
        started_at=datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 8, 10, 12, 5, 0, tzinfo=UTC),
        metadata={},
    )
    substrate.put(f"workflow-results/{workflow_id}/", outcome)
    return outcome


def _fake_rbac_manager() -> Any:
    """Return a fake RBAC manager that allows all checks.

    The ``@require_mcp_auth`` decorator calls
    ``rbac_manager.check_permission`` as an awaitable. ``AsyncMock``
    returning ``True`` satisfies the gate so tests can drive the
    AUTH_REQUIRED path (missing ``user_id``) without standing up a
    real RBAC.
    """
    rbac = MagicMock()
    rbac.check_permission = AsyncMock(return_value=True)
    return rbac


@pytest.mark.asyncio
async def test_workflow_get_outcome_returns_validated_struct() -> None:
    """A record written through the facade reads back as a validated struct."""
    written = _write_outcome("wf-abc", status="failed")

    result = await workflow_get_outcome("wf-abc")

    assert isinstance(result, WorkflowOutcome)
    assert result.workflow_id == "wf-abc"
    assert result.status == "failed"
    assert result.started_at == written.started_at
    assert result.finished_at == written.finished_at
    assert result.metadata == written.metadata


@pytest.mark.asyncio
async def test_workflow_get_outcome_returns_none_when_missing() -> None:
    """No record under the key → None (a genuine miss, not a missing substrate)."""
    result = await workflow_get_outcome("wf-never-written")
    assert result is None


@pytest.mark.asyncio
async def test_workflow_get_outcome_reads_the_workflow_results_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reader queries the facade with the documented key layout."""
    stub = _stub_substrate(monkeypatch, payload=None)

    await workflow_get_outcome("wf-key-layout")

    stub.get.assert_awaited_once_with("workflow-results/wf-key-layout/")


@pytest.mark.asyncio
async def test_workflow_get_outcome_emits_no_unbound_warning() -> None:
    """The reader has no "substrate unbound" branch — a miss is just a miss.

    The old call-time lookup could leave the substrate unbound, which
    logged ``workflow_outcome_read_skipped``. The substrate is in-process
    now, so that warning must never fire again.

    Captured through structlog (the oneiric logger is a structlog proxy),
    not ``caplog`` — stdlib capture only sees the event when something
    else routes structlog through the stdlib logging bridge, which makes
    the assertion order-dependent.
    """
    with capture_logs() as logs:
        result = await workflow_get_outcome("wf-no-warning")

    assert result is None
    assert [entry for entry in logs if entry["event"] == "workflow_outcome_read_skipped"] == []


@pytest.mark.asyncio
async def test_register_workflow_tools_registers_tool() -> None:
    """register_workflow_tools registers workflow_get_outcome as an MCP tool."""
    mcp = FastMCP(name="test-workflow-tools")
    register_workflow_tools(mcp)
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    # FastMCP derives tool name from the inline function's __name__
    assert "workflow_get_outcome_tool" in tool_names

    # And: the registered coroutine is async, matching the FastMCP contract.
    tool = next(t for t in tools if t.name == "workflow_get_outcome_tool")
    assert asyncio.iscoroutinefunction(tool.fn)


@pytest.mark.asyncio
async def test_registered_tool_delegates_to_module_function() -> None:
    """End-to-end: calling the registered MCP tool returns a validated struct."""
    _write_outcome("wf-e2e", status="succeeded")

    mcp = FastMCP(name="test-workflow-tools")
    register_workflow_tools(mcp, rbac_manager=_fake_rbac_manager())
    tool = next(t for t in await mcp.list_tools() if t.name == "workflow_get_outcome_tool")
    result = await tool.fn(workflow_id="wf-e2e", user_id="viewer-1")
    assert isinstance(result, WorkflowOutcome)
    assert result.workflow_id == "wf-e2e"
    assert result.status == "succeeded"


@pytest.mark.asyncio
async def test_workflow_get_outcome_is_coroutine_function() -> None:
    """workflow_get_outcome is async — FastMCP requires coroutines for tools."""
    assert asyncio.iscoroutinefunction(workflow_get_outcome)


@pytest.mark.asyncio
async def test_workflow_get_outcome_rejects_path_traversal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Module-level guard: caller-supplied path-traversal workflow_id is refused.

    Mirrors the sibling parity gate in ``pool_tools.workflow_result``: when
    ``workflow_id`` is anything other than ``^[A-Za-z0-9._-]{1,128}$``, the
    function returns the sentinel ``{"status": "invalid_workflow_id"}`` and
    the substrate is never queried. Without this gate, a caller could read
    arbitrary keys via ``workflow_id="../../etc/passwd"``.
    """
    stub = _stub_substrate(monkeypatch)

    result = await workflow_get_outcome("../../etc/passwd")

    assert result == {
        "workflow_id": "../../etc/passwd",
        "status": "invalid_workflow_id",
    }
    stub.get.assert_not_called()


@pytest.mark.asyncio
async def test_registered_tool_rejects_path_traversal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: registered MCP tool returns sentinel and never touches substrate.

    Walks the FastMCP-registered ``workflow_get_outcome_tool`` so we know the
    guard is wired in the production registration path, not only on the
    module-level coroutine.
    """
    stub = _stub_substrate(monkeypatch)

    mcp = FastMCP(name="test-workflow-tools-traversal")
    register_workflow_tools(mcp, rbac_manager=_fake_rbac_manager())
    tool = next(t for t in await mcp.list_tools() if t.name == "workflow_get_outcome_tool")

    result = await tool.fn(workflow_id="../../etc/passwd", user_id="viewer-1")

    assert result == {
        "workflow_id": "../../etc/passwd",
        "status": "invalid_workflow_id",
    }
    stub.get.assert_not_called()


async def test_workflow_get_outcome_tool_rejects_without_user_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """@require_mcp_auth wrapper rejects calls missing user_id.

    Without user_id the wrapper returns the AUTH_REQUIRED error envelope
    before the underlying workflow_get_outcome runs.
    """
    from mcp_common.fastmcp import FastMCP

    from mahavishnu.mcp.tools.workflow_tools import register_workflow_tools

    stub = _stub_substrate(monkeypatch)

    mcp = FastMCP(name="test-workflow-tools-auth")
    register_workflow_tools(mcp, rbac_manager=_fake_rbac_manager())
    tool = next(t for t in await mcp.list_tools() if t.name == "workflow_get_outcome_tool")

    result = await tool.fn(workflow_id="wf-1")

    assert isinstance(result, dict)
    assert result.get("status") == "error"
    assert result.get("error_code") == "AUTH_REQUIRED"
    stub.get.assert_not_called()


async def test_workflow_get_outcome_tool_passes_with_user_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """@require_mcp_auth wrapper passes when user_id is supplied.

    With user_id the wrapper falls through to workflow_get_outcome, which
    reads the substrate and finds no record — we assert the wrapper did
    NOT short-circuit on auth.
    """
    from mcp_common.fastmcp import FastMCP

    from mahavishnu.mcp.tools.workflow_tools import register_workflow_tools

    stub = _stub_substrate(monkeypatch, payload=None)

    mcp = FastMCP(name="test-workflow-tools-auth-ok")
    register_workflow_tools(mcp, rbac_manager=_fake_rbac_manager())
    tool = next(t for t in await mcp.list_tools() if t.name == "workflow_get_outcome_tool")

    result = await tool.fn(workflow_id="wf-ok", user_id="viewer-1")

    # No AUTH_REQUIRED envelope → wrapper fell through.
    if isinstance(result, dict):
        assert result.get("error_code") != "AUTH_REQUIRED"
    stub.get.assert_awaited_once_with("workflow-results/wf-ok/")
