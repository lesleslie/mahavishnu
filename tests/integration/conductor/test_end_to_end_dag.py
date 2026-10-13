"""End-to-end integration test for execute_capability.

Drives the conductor (resolve -> plan -> dispatch) against real ``MahavishnuSettings``
loaded from ``settings/mahavishnu.yaml``. No live services required:
- Prefect / Dhara are not contacted. The dispatch path is exercised
  through ``_dispatch_dag_waves`` against a ``_FakeMCPClient`` and
  mocked ``OrchestratorAdapter`` instances (per Plan 2026-10-12 Phase 4
  / Phase 5 wiring).
- The Dhara adapter is not used by the shim path. The shim's envelope
  persistence absorbs into the in-memory fake so no ``AsyncMock(mcp.call_tool)``
  is needed for these tests.

The shim ``execute_capability_for_test`` (and its dispatch variant
``execute_capability_with_dispatch_for_test``) lives in
``tests/integration/conductor/_helpers.py`` (NOT in production
``mahavishnu/mcp/tools/capability_tools.py``) per v3 reviewer note #16.

Run with:
    pytest tests/integration/conductor/test_end_to_end_dag.py -v -m integration
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.adapters.base import OrchestratorAdapter
from mahavishnu.core.capabilities import (
    CapabilityExecutionResult,
    CapabilityId,
    CapabilitySpec,
    TraceId,
)
from mahavishnu.core.conductor import plan, resolve
from mahavishnu.core.config import MahavishnuSettings

from ._helpers import (
    _all_registrations_for_test,
    execute_capability_for_test,
    execute_capability_with_dispatch_for_test,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class _FakeMCPClient:
    """In-memory MCP stub for the integration test (mirrors tests/unit/core)."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    async def put(self, key: str, value, ttl: int | None = None):
        if isinstance(value, str):
            self.store[key] = value.encode()
        else:
            self.store[key] = bytes(value)
        return None

    async def call_tool(self, name: str, arguments):
        if name == "get":
            return self.store.get(arguments["key"])
        if name == "list_keys":
            return [k for k in self.store if k.startswith(arguments.get("prefix", ""))]
        return None


def _make_adapter_mock():
    adapter = MagicMock(spec=OrchestratorAdapter)
    adapter.execute = AsyncMock(
        return_value={
            "status": "completed",
            "results": [{"status": "completed", "output": "ok"}],
            "flow_run_id": "fr-1",
        }
    )
    return adapter


async def test_execute_capability_returns_valid_dag() -> None:
    """``execute_capability`` resolves a 2-capability spec into a 2-node DAG."""
    settings = MahavishnuSettings.model_validate(
        {
            "capability_enabled": True,
            "capability_scopes": ["execute_capability"],
        }
    )
    spec = CapabilitySpec(
        requires=[
            CapabilityId("engine:durable-flow"),
            CapabilityId("worker:ai-context"),
        ],
        prompt="integration test",
    )
    # Drive the conductor directly against the merged engine+worker registry
    # (the shim's _all_registrations_for_test does the same merge).
    candidates = resolve(spec, _all_registrations_for_test(settings))
    assert len(candidates) >= 2, f"expected ≥2 candidates, got {candidates}"

    dag = plan(spec, candidates, trace_id=TraceId("a" * 32))
    assert len(dag.nodes) == 2
    node_ids = {n.engine_id for n in dag.nodes}
    assert "prefect" in node_ids  # provides engine:durable-flow


async def test_execute_capability_with_no_match_returns_rejected() -> None:
    """A spec with no available engines returns rejected status."""
    settings = MahavishnuSettings()
    spec = CapabilitySpec(
        requires=[CapabilityId("engine:nonexistent")],
        prompt="should fail",
    )
    result = await execute_capability_for_test(spec, settings)
    assert isinstance(result, CapabilityExecutionResult)
    assert result.status == "rejected"
    assert result.error is not None


async def test_execute_capability_runs_two_node_dag() -> None:
    """The dispatch path runs a 2-node DAG end-to-end and persists one envelope per node.

    This test exercises the level-by-level dispatch in
    ``mahavishnu.core.conductor._dispatch_dag_waves`` via the test helper
    ``execute_capability_with_dispatch_for_test``. Both engines' mock
    ``execute()`` invocations are asserted; persisted envelopes are
    counted under ``envelopes/<trace_id>/``.
    """
    settings = MahavishnuSettings.model_validate(
        {
            "capability_enabled": True,
            "capability_scopes": ["execute_capability"],
        }
    )
    spec = CapabilitySpec(
        requires=[
            CapabilityId("engine:durable-flow"),
        ],
        prompt="integration dispatch test",
        trace_id=TraceId("b" * 32),
    )
    prefect_mock = _make_adapter_mock()
    adapters = {"prefect": prefect_mock}

    mcp = _FakeMCPClient()
    result, envelope_ids = await execute_capability_with_dispatch_for_test(
        spec, settings, mcp=mcp, adapters=adapters
    )
    assert result.status == "queued"
    assert result.dag is not None
    assert len(envelope_ids) == 1, f"expected 1 envelope, got {sorted(envelope_ids)}"
    prefect_mock.execute.assert_awaited_once()
    # Exactly one persisted envelope at the expected key prefix.
    keys = [k for k in mcp.store if k.startswith(f"envelopes/{'b' * 32}/")]
    assert len(keys) == 1
