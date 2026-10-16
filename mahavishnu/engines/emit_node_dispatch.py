"""Per-engine ``emit_node`` dispatch tables.

Five engines — Prefect, LlamaIndex, Agno, Hatchet, pydantic_ai — each with a
thin dispatcher function ``emit_<engine>_node(spec, mcp) -> NodeHandle``. The
dispatchers share ``_dispatch_with_envelope`` so the body that persists the
``CapabilityEnvelope`` is written once (the only per-engine difference is the
``task`` dict shape and the ``flow_run_id`` field name).

The dispatch table is registered into ``mahavishnu.core.conductor._EMIT_NODE_DISPATCH``
on import. Tests pass a fresh adapter registry to ``register(...)`` per test
(not module-level) — see the ``feedback-workflow-parallel-same-repo-no-isolation``
and test-coverage-review rule on shared mutable state.

Lazy import of :mod:`mahavishnu.adapters.ai.pydantic_ai_adapter` is required
because the ``ai`` PEP 735 dependency group is optional
(see CLAUDE.md "Optional Dependency Groups (PEP 735)").
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING, Any
import uuid

from mahavishnu.core.capabilities import (
    CapabilityEnvelope,
    EnvelopeId,
)
from mahavishnu.core.conductor import _EMIT_NODE_DISPATCH
from mahavishnu.core.conductor_types import NodeHandle, NodeSpec
from mahavishnu.core.envelopes import write_envelope

if TYPE_CHECKING:
    from mahavishnu.core.adapters.base import OrchestratorAdapter
    from mahavishnu.core.mcp_adapter import MCPAdapter

logger = logging.getLogger(__name__)


# Registry of live OrchestratorAdapter instances — populated by ``register()``.
# Tests inject mocks; production code calls ``register()`` from the wiring site.
_REGISTRY: dict[str, OrchestratorAdapter] = {}


def _lookup(engine_id: str) -> OrchestratorAdapter | None:
    """Return the registered adapter for ``engine_id`` (None if absent)."""
    return _REGISTRY.get(engine_id)


def _new_envelope_id() -> EnvelopeId:
    """Generate a fresh UUIDv4 envelope id."""
    return EnvelopeId(str(uuid.uuid4()))


def _build_envelope(
    spec: NodeSpec,
    *,
    status: str,
    io_out: dict[str, str],
    parent_envelope_ids: tuple[EnvelopeId, ...],
) -> CapabilityEnvelope:
    """Assemble a ``CapabilityEnvelope`` from a ``NodeSpec`` + adapter response."""
    return CapabilityEnvelope(
        envelope_id=_new_envelope_id(),
        capability_id=spec.capability_id,
        engine_id=spec.engine_id,
        io_out=io_out,
        produced_at=datetime.now(UTC),
        trace_id=spec.trace_id,
        parent_envelope_ids=list(parent_envelope_ids),
        sensitivity="internal",
    )


def _redact_response_io(results: list[Any]) -> dict[str, str]:
    """Flatten a per-repo result list into a single stringified ``io_out`` dict.

    The ``CapabilityEnvelope.io_out`` field is ``dict[str, str]`` (string-only
    after redaction; see :mod:`mahavishnu.core.capabilities`); one entry per
    repo result, keyed ``result_{i}``.
    """
    io_out: dict[str, str] = {}
    for i, item in enumerate(results):
        if isinstance(item, dict):
            value = ", ".join(f"{k}={v!r}" for k, v in item.items())
        else:
            value = str(item)
        io_out[f"result_{i}"] = value
    return io_out


async def _dispatch_with_envelope(
    spec: NodeSpec,
    *,
    mcp: MCPAdapter,
    adapter: OrchestratorAdapter,
    task: dict[str, Any],
    flow_run_id_field: str | None = None,
) -> NodeHandle:
    """Persist a ``CapabilityEnvelope`` after ``adapter.execute(task, repos)``.

    On exception we still write a ``status="failed"`` envelope so the
    failure is observable via :func:`mahavishnu.core.envelopes.list_envelopes`.
    """
    repos_list = list(spec.repos)
    try:
        response = await adapter.execute(task=task, repos=repos_list)
    except Exception as exc:  # Engine dispatch wraps any adapter exception in a failed CapabilityEnvelope rather than propagating  # background task — broad catch is the documented contract  # noqa: BLE001
        envelope_id = _new_envelope_id()
        envelope = CapabilityEnvelope(
            envelope_id=envelope_id,
            capability_id=spec.capability_id,
            engine_id=spec.engine_id,
            io_out={"error": str(exc)},
            produced_at=datetime.now(UTC),
            trace_id=spec.trace_id,
            parent_envelope_ids=list(spec.parent_envelope_ids),
            sensitivity="internal",
        )
        await write_envelope(envelope, mcp=mcp)
        return NodeHandle(
            envelope_id=envelope_id,
            engine_id=spec.engine_id,
            status="failed",
            flow_run_id=None,
            error=str(exc),
        )

    status = response.get("status", "failed") if isinstance(response, dict) else "failed"
    raw_results = response.get("results", []) if isinstance(response, dict) else []
    if not isinstance(raw_results, list):
        raw_results = []
    io_out = _redact_response_io(raw_results)
    error = response.get("error") if isinstance(response, dict) else None

    envelope = _build_envelope(
        spec,
        status=status,
        io_out=io_out,
        parent_envelope_ids=spec.parent_envelope_ids,
    )
    await write_envelope(envelope, mcp=mcp)

    flow_run_id: str | None = None
    if flow_run_id_field and isinstance(response, dict):
        candidate = response.get(flow_run_id_field)
        if candidate is not None:
            flow_run_id = str(candidate)

    return NodeHandle(
        envelope_id=envelope.envelope_id,
        engine_id=spec.engine_id,
        status=status,
        flow_run_id=flow_run_id,
        error=str(error) if error else None,
    )


# ---------------------------------------------------------------------------
# Per-engine dispatcher functions
# ---------------------------------------------------------------------------


async def emit_prefect_node(spec: NodeSpec, mcp: MCPAdapter) -> NodeHandle:
    """Dispatch a Prefect node.

    Task shape mirrors :func:`mahavishnu.engines.prefect_adapter_impl.PrefectAdapter.execute`:
    ``{"type", "id", "prompt", "trace_id", "parent_envelope_ids"}``. The engine
    returns ``flow_run_id`` on completion.
    """
    adapter = _lookup(spec.engine_id)
    if adapter is None:
        raise NotImplementedError(
            f"per-engine emit_node dispatch registered but no adapter instance wired for engine_id={spec.engine_id!r}"
        )
    task = {
        "type": "code_sweep",
        "id": spec.node_id,
        "prompt": spec.prompt,
        "trace_id": str(spec.trace_id),
        "parent_envelope_ids": [str(p) for p in spec.parent_envelope_ids],
    }
    return await _dispatch_with_envelope(
        spec, mcp=mcp, adapter=adapter, task=task, flow_run_id_field="flow_run_id"
    )


async def emit_llamaindex_node(spec: NodeSpec, mcp: MCPAdapter) -> NodeHandle:
    """Dispatch a LlamaIndex node.

    Task shape mirrors :func:`mahavishnu.engines.llamaindex_adapter_impl.LlamaIndexAdapter.execute`:
    ``{"type", "id", "params": {"prompt", "trace_id"}}``. Defaults to ``type="ingest"``
    until ``CapabilitySpec.io_in`` exposes a downstream query hint.
    """
    adapter = _lookup(spec.engine_id)
    if adapter is None:
        raise NotImplementedError(
            f"per-engine emit_node dispatch registered but no adapter instance wired for engine_id={spec.engine_id!r}"
        )
    task = {
        "type": "ingest",
        "id": spec.node_id,
        "params": {
            "prompt": spec.prompt,
            "trace_id": str(spec.trace_id),
        },
    }
    return await _dispatch_with_envelope(spec, mcp=mcp, adapter=adapter, task=task)


async def emit_agno_node(spec: NodeSpec, mcp: MCPAdapter) -> NodeHandle:
    """Dispatch an Agno node.

    Task shape mirrors :func:`mahavishnu.engines.agno_adapter_impl.AgnoAdapter.execute`:
    ``{"type", "id", "prompt"}``. The engine accepts ``task.get("type")``
    falling back to ``"default"``; we pick ``"agent_run"`` for explicitness.
    """
    adapter = _lookup(spec.engine_id)
    if adapter is None:
        raise NotImplementedError(
            f"per-engine emit_node dispatch registered but no adapter instance wired for engine_id={spec.engine_id!r}"
        )
    task = {
        "type": "agent_run",
        "id": spec.node_id,
        "prompt": spec.prompt,
    }
    return await _dispatch_with_envelope(spec, mcp=mcp, adapter=adapter, task=task)


async def emit_hatchet_node(spec: NodeSpec, mcp: MCPAdapter) -> NodeHandle:
    """Dispatch a Hatchet node.

    Task shape mirrors :func:`mahavishnu.engines.hatchet_adapter_impl.HatchetAdapterImpl.execute`:
    ``{"prompt", "workflow_name", "timeout"}``. The engine returns ``run_id``
    on completion.
    """
    adapter = _lookup(spec.engine_id)
    if adapter is None:
        raise NotImplementedError(
            f"per-engine emit_node dispatch registered but no adapter instance wired for engine_id={spec.engine_id!r}"
        )
    # Strip the "engine:" prefix from the capability id so the engine receives
    # the bare workflow name (matches the Hatchet engine's existing convention).
    workflow_name = (
        spec.capability_id.split(":", 1)[1] if ":" in spec.capability_id else "agent-loop"
    )
    task = {
        "prompt": spec.prompt,
        "workflow_name": workflow_name or "agent-loop",
        "timeout": spec.timeout_seconds,
    }
    return await _dispatch_with_envelope(
        spec, mcp=mcp, adapter=adapter, task=task, flow_run_id_field="run_id"
    )


async def emit_pydanticai_node(spec: NodeSpec, mcp: MCPAdapter) -> NodeHandle:
    """Dispatch a pydantic_ai node.

    The pydantic_ai adapter lives behind the optional ``ai`` PEP 735 dependency
    group (see CLAUDE.md "Optional Dependency Groups"). We lazy-import the
    class on dispatch to preserve that property — if the group isn't installed
    we still return a ``failed`` ``NodeHandle`` AFTER writing a
    ``status="failed"`` envelope so the failure is observable via Dhara list.
    """
    try:
        from mahavishnu.adapters.ai.pydantic_ai_adapter import (
            PydanticAIAdapter,  # type: ignore[import-not-found]
        )
    except ImportError as exc:
        envelope = _build_envelope(
            spec,
            status="failed",
            io_out={"error": "pydantic-ai dependency group not installed"},
            parent_envelope_ids=spec.parent_envelope_ids,
        )
        await write_envelope(envelope, mcp=mcp)
        return NodeHandle(
            envelope_id=envelope.envelope_id,
            engine_id=spec.engine_id,
            status="failed",
            error=(
                "pydantic-ai dependency group not installed; run `uv sync --group ai`"
                f" (cause: {exc})"
            ),
        )

    # Register the live adapter if caller hasn't done so already — this keeps
    # the ai group lazy but lets unit tests skip ``register()`` for the
    # pydantic_ai engine.
    if spec.engine_id not in _REGISTRY:
        instance: OrchestratorAdapter = PydanticAIAdapter()
        _REGISTRY[spec.engine_id] = instance
    adapter = _lookup(spec.engine_id)
    if adapter is None:
        raise NotImplementedError(
            f"per-engine emit_node dispatch registered but no adapter instance wired for engine_id={spec.engine_id!r}"
        )

    task: dict[str, Any] = {
        "prompt": spec.prompt,
        "context": {
            "trace_id": str(spec.trace_id),
            "parent_envelope_ids": [str(p) for p in spec.parent_envelope_ids],
        },
    }
    return await _dispatch_with_envelope(spec, mcp=mcp, adapter=adapter, task=task)


# ---------------------------------------------------------------------------
# Dispatch table + registration
# ---------------------------------------------------------------------------


_EMIT_TABLE: dict[str, Any] = {
    "prefect": emit_prefect_node,
    "llamaindex": emit_llamaindex_node,
    "agno": emit_agno_node,
    "hatchet": emit_hatchet_node,
    "pydantic_ai": emit_pydanticai_node,
}


def register(adapters: dict[str, OrchestratorAdapter]) -> None:
    """Replace the global adapter registry and (re)populate the dispatch table.

    Production wiring (in :mod:`mahavishnu.core.app`) constructs the real
    adapter instances and calls this once at startup. Tests pass mocks per
    test — ``register()`` is global state but the test seam is the
    ``adapters`` dict (not the dispatcher functions), so concurrent
    test classes can flush and re-register without rewriting module code.
    """
    _REGISTRY.clear()
    _REGISTRY.update(adapters)
    _EMIT_NODE_DISPATCH.clear()
    for engine_id, func in _EMIT_TABLE.items():
        _EMIT_NODE_DISPATCH[engine_id] = func
    if not adapters:
        logger.warning(
            "emit_node dispatch registered with no live adapters — DAG runs will fail until wiring is populated"
        )


__all__ = [
    "_EMIT_TABLE",
    "_REGISTRY",
    "emit_agno_node",
    "emit_hatchet_node",
    "emit_llamaindex_node",
    "emit_prefect_node",
    "emit_pydanticai_node",
    "register",
]
