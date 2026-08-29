"""Test helpers for the Stage 3a conductor integration tests.

These helpers live in the test tree (NOT in ``mahavishnu/mcp/tools/capability_tools.py``)
per the v3 reviewer note #16: production modules must not export ``_all_registrations``
or a test-only shim that bypasses the FastMCP server.

The shim mirrors ``execute_capability``'s body without the MCP envelope / auth /
scope checks. Tests that exercise the public MCP surface should hit
``tests/unit/mcp/test_capability_tools.py`` instead — those tests mock the Dhara
adapter and the require_mcp_auth decorator at the FastMCP boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mahavishnu.core.capabilities import (
    CapabilityExecutionResult,
    EngineRegistration,
    TraceId,
)
from mahavishnu.core.conductor import plan, resolve
from mahavishnu.engines import load_engine_registrations
from mahavishnu.mcp.tools.capability_tools import _worker_engine_registrations

if TYPE_CHECKING:
    from mahavishnu.core.capabilities import CapabilitySpec
    from mahavishnu.core.config import MahavishnuSettings


def _all_registrations_for_test(
    settings: MahavishnuSettings,
) -> list[EngineRegistration]:
    """Same merge as ``capability_tools._all_registrations``, test-scope.

    NOTE: Brief v1's draft used ``load_capabilities_from_settings`` and built
    one ``EngineRegistration(engine_id=cap.id, ...)`` per capability, but
    ``cap.id`` carries a ``:`` separator (``worker:bash``) which violates the
    ``EngineId`` pattern ``^[a-z][a-z0-9_-]{1,63}$`` — Pydantic rejects it.
    Reusing the production ``_worker_engine_registrations`` helper preserves
    the brief's "merge engines + workers into one list" intent while keeping
    ``engine_id`` valid.
    """
    engine_regs = load_engine_registrations(settings)
    worker_regs = _worker_engine_registrations(settings)
    return [*engine_regs, *worker_regs]


async def execute_capability_for_test(
    spec: CapabilitySpec,
    settings: MahavishnuSettings,
) -> CapabilityExecutionResult:
    """Test-only entrypoint that mirrors ``execute_capability`` without FastMCP.

    Skips the auth gate, the scope allow-list, and the FastMCP envelope so the
    test can drive the conductor directly. Returns a real ``CapabilityExecutionResult``
    (status='planned' when at least one engine satisfies the spec, 'rejected' otherwise).
    """
    all_engines = _all_registrations_for_test(settings)
    candidates = resolve(spec, all_engines)
    tid = spec.trace_id or TraceId("0" * 32)
    if not candidates:
        return CapabilityExecutionResult(
            status="rejected",
            trace_id=tid,
            error="no engine provides any required capability",
        )
    dag = plan(spec, candidates, trace_id=tid)
    return CapabilityExecutionResult(status="planned", trace_id=dag.trace_id, dag=dag)


__all__ = [
    "_all_registrations_for_test",
    "execute_capability_for_test",
]
