"""End-to-end integration test for execute_capability.

Drives the conductor (resolve -> plan) against real ``MahavishnuSettings``
loaded from ``settings/mahavishnu.yaml``. No live services required:
- Prefect / Dhara are not contacted. ``emit_node`` is still a
  ``NotImplementedError`` (per-engine dispatch lands in Phase 4), so the
  integration test stops at plan() — exactly the surface the conductor ships
  with today.
- The Dhara adapter is not used by the shim path. The shim never invokes
  ``execute_capability_for_test``'s Dhara-side persistence, so no
  ``AsyncMock(dhara.call_tool)`` is needed for these two tests; future
  Phase-4 dispatch tests will mock at the Dhara boundary.

The shim ``execute_capability_for_test`` lives in ``tests/integration/conductor/_helpers.py``
(NOT in production ``mahavishnu/mcp/tools/capability_tools.py``) per v3 reviewer
note #16.

Run with:
    pytest tests/integration/conductor/test_end_to_end_dag.py -v -m integration
"""

from __future__ import annotations

import pytest

from mahavishnu.core.capabilities import (
    CapabilityExecutionResult,
    CapabilityId,
    CapabilitySpec,
    TraceId,
)
from mahavishnu.core.conductor import plan, resolve
from mahavishnu.core.config import MahavishnuSettings

from ._helpers import _all_registrations_for_test, execute_capability_for_test

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


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
