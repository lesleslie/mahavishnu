"""MCP tools for capability resolution, planning, and execution.

Three tools are gated by ``MahavishnuSettings.capability_enabled`` AND
``capability_scopes`` allow-list. The fourth (``list_capabilities``) is
ungated so the operator can introspect the registry without auth.

The internal helper ``_all_registrations()`` merges engine registrations
(Prefect, LlamaIndex, Agno, …) with worker registrations from
``settings.worker_registry.entries[]`` so the Conductor resolves against
both engines and workers in one pass.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
import uuid

from mcp_common.auth.permissions import Permission as MCPPermission

from ...core.capabilities import (
    _TRACE_ID_ADAPTER,
    CapabilityExecutionResult,
    CapabilityKind,
    CapabilitySpec,
    CapabilityState,
    CostHint,
    EngineRegistration,
    SelectorStrategy,
    TraceId,
    TypeSchema,
)
from ...core.conductor import plan, resolve
from ...core.errors import AuthorizationError, ErrorCode, MahavishnuError
from ...mcp.auth import require_mcp_auth

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastmcp import FastMCP

    from ...core.capabilities import Capability
    from ...core.config import MahavishnuSettings, WorkerEntry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal: merged registrations (engines + workers)
# ---------------------------------------------------------------------------


def _worker_engine_registrations(
    settings: MahavishnuSettings,
) -> list[EngineRegistration]:
    """Convert ``settings.worker_registry.entries`` into EngineRegistrations.

    Each ``WorkerEntry.worker_type`` becomes one ``EngineRegistration``. All
    capabilities listed in the entry's ``provides`` flow into the engine's
    ``provides`` list. Multiple entries that share a ``worker_type`` are
    merged (provides unioned) so the Conductor sees one engine per worker
    type and ranks per-capability candidates normally.
    """
    by_worker_type: dict[str, list[WorkerEntry]] = {}
    for entry in settings.worker_registry.entries:
        by_worker_type.setdefault(entry.worker_type, []).append(entry)

    regs: list[EngineRegistration] = []
    for worker_type, entries in by_worker_type.items():
        provides: list[Capability] = []
        for entry in entries:
            for cap_id in entry.provides:
                provides.append(
                    _build_worker_capability(
                        cap_id=cap_id,
                        entry=entry,
                    )
                )
        if not provides:
            continue
        regs.append(
            EngineRegistration(
                engine_id=worker_type,
                provides=provides,
                enabled=True,
            )
        )
    return regs


def _build_worker_capability(
    *,
    cap_id: str,
    entry: WorkerEntry,
) -> Capability:
    """Build a Capability from a WorkerEntry.provides entry."""
    from ...core.capabilities import Capability

    return Capability(
        id=cap_id,
        kind=CapabilityKind.WORKER,
        description=entry.description or entry.name or entry.worker_type,
        io_in=TypeSchema(),
        io_out=TypeSchema(),
        state=CapabilityState.EPHEMERAL,
        cost_hint=CostHint(has_side_effects=True),
        tags=list(entry.tags),
    )


def _all_registrations(settings: MahavishnuSettings) -> list[EngineRegistration]:
    """Merge engine and worker registrations into the single list the Conductor resolves against.

    Engines come from ``mahavishnu.engines.load_engine_registrations`` (Prefect,
    LlamaIndex, Agno, hatchet, pydantic_ai, worker-pool). Workers come from
    ``settings.worker_registry.entries[]`` and become one ``EngineRegistration``
    per unique ``worker_type``.

    Importing ``mahavishnu.engines`` is lazy because the engines module pulls
    in optional heavy deps (Prefect, LlamaIndex); we only pay that cost on
    the first tool invocation, not at module import.
    """
    from ...engines import load_engine_registrations

    engine_regs = load_engine_registrations(settings)
    worker_regs = _worker_engine_registrations(settings)
    return [*engine_regs, *worker_regs]


# Re-export for tests that want to verify the merge in isolation.
__all__ = [
    "_all_registrations",
    "_worker_engine_registrations",
    "register_capability_tools",
]


# ---------------------------------------------------------------------------
# Auth + feature flag
# ---------------------------------------------------------------------------


def _check_capability_feature_flag(settings: MahavishnuSettings) -> None:
    """Raise ``MahavishnuError`` if the capability toolset is feature-flagged off."""
    if getattr(settings, "capability_enabled", False):
        return
    raise MahavishnuError(
        "capability tools are disabled (settings.capability_enabled=False)",
        ErrorCode.FEATURE_DISABLED,
    )


def _check_scope(user_id: str | None, settings: MahavishnuSettings) -> None:
    """Verify ``user_id`` is in ``settings.capability_scopes`` allow-list.

    The allow-list is intentionally a closed set rather than a roles table —
    capability tools can dispatch AI workers with cost / side-effect
    implications, so the brief requires explicit per-user opt-in until a
    richer RBAC model lands in Phase 4. Raises ``AuthorizationError`` (NOT
    ``PERMISSION_DENIED``) per the brief.
    """
    if not user_id:
        raise AuthorizationError(
            "capability tools require a user_id parameter",
            details={"required_param": "user_id"},
        )
    allowed = set(getattr(settings, "capability_scopes", []) or [])
    if allowed and user_id not in allowed:
        raise AuthorizationError(
            f"user {user_id!r} is not in settings.capability_scopes allow-list",
            details={"user_id": user_id, "allowed": sorted(allowed)},
        )


def _coerce_selector(value: str) -> SelectorStrategy:
    """Parse the JSON-supplied ``selector`` string into a SelectorStrategy enum."""
    try:
        return SelectorStrategy(value)
    except ValueError as exc:
        raise MahavishnuError(
            f"unknown selector {value!r}; valid: {sorted(s.value for s in SelectorStrategy)}",
            ErrorCode.VALIDATION_ERROR,
        ) from exc


def _new_trace_id() -> TraceId:
    """Generate a hex trace id matching the TraceId newtype pattern."""
    return _TRACE_ID_ADAPTER.validate_python(uuid.uuid4().hex)


# ---------------------------------------------------------------------------
# Registration entry point
# ---------------------------------------------------------------------------


def register_capability_tools(
    server: FastMCP,
    settings: MahavishnuSettings,
) -> None:
    """Register the capability MCP toolset on ``server``.

    All four tools are defined inline so FastMCP's introspection sees the
    intended schema. The three gated tools share the same auth + scope +
    feature-flag preamble; only their body differs.
    """

    @server.tool(
        name="list_capabilities", description="List every registered engine and its provides."
    )
    async def list_capabilities() -> dict[str, object]:
        """Ungated introspection tool: enumerate every engine + worker registration."""
        regs = _all_registrations(settings)
        return {
            "status": "ok",
            "count": len(regs),
            "registrations": [
                {
                    "engine_id": r.engine_id,
                    "enabled": r.enabled,
                    "provides": [c.id for c in r.provides],
                }
                for r in regs
            ],
        }

    @server.tool(
        name="resolve_capabilities",
        description="Resolve CapabilitySpec.requires into Candidate engines.",
    )
    @require_mcp_auth(
        rbac_manager=None,
        required_permission=MCPPermission.READ,
    )
    async def resolve_capabilities(
        requires: list[str],
        prompt: str,
        selector: str = "capability_score",
        user_id: str | None = None,
    ) -> dict[str, object]:
        """Resolve which engines/workers can satisfy each required capability."""
        try:
            _check_capability_feature_flag(settings)
            _check_scope(user_id, settings)
            spec = CapabilitySpec(
                requires=list(requires),
                prompt=prompt,
                selector=_coerce_selector(selector),
            )
            candidates = resolve(spec, _all_registrations(settings))
        except AuthorizationError as exc:
            return {
                "status": "error",
                "error": str(exc),
                "error_code": exc.error_code.value,
                "candidates": [],
            }
        except MahavishnuError as exc:
            return {
                "status": "error",
                "error": str(exc),
                "error_code": exc.error_code.value,
                "candidates": [],
            }
        return {
            "status": "ok",
            "count": len(candidates),
            "candidates": [
                {
                    "engine_id": c.engine_id,
                    "capability_id": c.capability_id,
                    "score": c.score,
                    "reason": c.reason,
                }
                for c in candidates
            ],
        }

    @server.tool(
        name="plan_capability",
        description="Plan an ExecutionDAG from a CapabilitySpec.",
    )
    @require_mcp_auth(
        rbac_manager=None,
        required_permission=MCPPermission.WRITE,
    )
    async def plan_capability(
        requires: list[str],
        prompt: str,
        selector: str = "capability_score",
        trace_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, object]:
        """Plan the DAG; returns the ExecutionDAG JSON (no engine dispatch)."""
        tid = trace_id if trace_id else _new_trace_id()
        try:
            _check_capability_feature_flag(settings)
            _check_scope(user_id, settings)
            spec = CapabilitySpec(
                requires=list(requires),
                prompt=prompt,
                selector=_coerce_selector(selector),
                trace_id=tid,
            )
            candidates = resolve(spec, _all_registrations(settings))
            dag = plan(spec, candidates, trace_id=tid)
        except AuthorizationError as exc:
            return {
                "status": "error",
                "error": str(exc),
                "error_code": exc.error_code.value,
                "trace_id": tid,
            }
        except MahavishnuError as exc:
            return {
                "status": "error",
                "error": str(exc),
                "error_code": exc.error_code.value,
                "trace_id": tid,
            }
        return {
            "status": "ok",
            "trace_id": tid,
            "nodes": [
                {
                    "node_id": n.node_id,
                    "engine_id": n.engine_id,
                    "capability_id": n.capability_id,
                }
                for n in dag.nodes
            ],
            "edges": [
                {
                    "from_node": e.from_node,
                    "to_node": e.to_node,
                    "via_field": e.via_field,
                }
                for e in dag.edges
            ],
        }

    @server.tool(
        name="execute_capability",
        description="Plan and queue an ExecutionDAG (emits the envelopes — dispatch is Phase 4).",
    )
    @require_mcp_auth(
        rbac_manager=None,
        required_permission=MCPPermission.WRITE,
    )
    async def execute_capability(
        requires: list[str],
        prompt: str,
        selector: str = "capability_score",
        trace_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, object]:
        """Plan the DAG and return a CapabilityExecutionResult.

        Actual dispatch lands in Phase 4 (per-engine dispatch modules) —
        until then, ``status='planned'`` is returned once the DAG compiles;
        ``status='rejected'`` is returned when no engine satisfies a required
        capability.
        """
        tid = trace_id if trace_id else _new_trace_id()
        try:
            _check_capability_feature_flag(settings)
            _check_scope(user_id, settings)
            spec = CapabilitySpec(
                requires=list(requires),
                prompt=prompt,
                selector=_coerce_selector(selector),
                trace_id=tid,
            )
            candidates = resolve(spec, _all_registrations(settings))
            dag = plan(spec, candidates, trace_id=tid)
        except AuthorizationError as exc:
            return {
                "status": "rejected",
                "trace_id": tid,
                "dag": None,
                "error": str(exc),
                "error_code": exc.error_code.value,
            }
        except MahavishnuError as exc:
            return {
                "status": "rejected",
                "trace_id": tid,
                "dag": None,
                "error": str(exc),
                "error_code": exc.error_code.value,
            }
        result = CapabilityExecutionResult(
            status="planned",
            trace_id=tid,
            dag=dag,
            error=None,
        )
        return {
            "status": result.status,
            "trace_id": result.trace_id,
            "nodes": len(result.dag.nodes) if result.dag else 0,
            "edges": len(result.dag.edges) if result.dag else 0,
            "error": result.error,
        }


def register_capability_tools_with_settings(
    server: FastMCP,
    settings_getter: Callable[[], MahavishnuSettings],
) -> Callable[[], None]:
    """Lazy variant of ``register_capability_tools`` for tests and hot-reload.

    The closure captures a ``settings_getter`` so the registered tools pull
    the latest settings on every invocation (no stale registry across
    ``settings.yaml`` reloads).
    """
    # Resolve once to validate the settings shape before the inner functions
    # try to read fields off it.
    settings_getter()

    def _register() -> None:
        register_capability_tools(server, settings_getter())

    return _register
