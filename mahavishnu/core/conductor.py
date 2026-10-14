"""Conductor: capability resolution, binding planning, Prefect flow emission.

Three responsibilities:

1. ``resolve(spec, engines) -> list[Candidate]`` — find every engine that
   provides each required capability (returning Candidates, not direct picks).
2. ``plan(spec, candidates, trace_id) -> ExecutionDAG`` — pick one candidate
   per required capability (via selector) and emit DAG edges when an upstream
   node's io_out matches a downstream node's io_in (per ``TypeSchema.matches``).
3. ``emit_flow(dag)`` — compile the DAG into a Prefect flow that wires nodes
   via typed ``submit()`` futures (so upstream output types flow into downstream
   inputs without serialization loss).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
import random
from types import ModuleType
from typing import TYPE_CHECKING

from mahavishnu.core.capabilities import (
    Candidate,
    CapabilityId,
    CapabilitySpec,
    DAGEdge,
    DAGNode,
    EngineRegistration,
    EnvelopeId,
    ExecutionDAG,
    SelectorStrategy,
    TraceId,
)
from mahavishnu.core.conductor_types import NodeHandle, NodeSpec
from mahavishnu.core.errors import ErrorCode, MahavishnuError

if TYPE_CHECKING:
    from types import ModuleType

    from mahavishnu.core.mcp_adapter import MCPAdapter

logger = logging.getLogger(__name__)


# Dispatch-function signature: takes a frozen NodeSpec and returns the NodeHandle
# the per-engine dispatcher produced. Populated at import time by
# ``mahavishnu.engines.emit_node_dispatch.register()``.
_EmitNodeFn = Callable[[NodeSpec, "MCPAdapter"], Awaitable[NodeHandle]]
_EMIT_NODE_DISPATCH: dict[str, _EmitNodeFn] = {}


def resolve(
    spec: CapabilitySpec,
    engines: list[EngineRegistration],
) -> list[Candidate]:
    """For each required capability, list engines that provide it.

    Candidates are returned unsorted; ranking happens in ``select_candidates``.
    The Candidate carries ``capability`` (the resolved Capability object) so
    that ``plan()`` can populate DAGNode inputs/outputs from the same source.
    """
    out: list[Candidate] = []
    for required_id in spec.requires:
        for engine in engines:
            if not engine.enabled:
                continue
            for cap in engine.provides:
                if cap.id == required_id:
                    out.append(
                        Candidate(
                            engine_id=engine.engine_id,
                            capability_id=required_id,
                            score=1.0,
                            reason=f"engine {engine.engine_id} provides {required_id}",
                            capability=cap,
                        )
                    )
    return out


def select_candidates(
    candidates: list[Candidate],
    strategy: SelectorStrategy,
) -> Candidate:
    """Pick the winning candidate from a list of Candidates for one slot.

    Phase 3a implements CAPABILITY_SCORE (highest cost_hint.estimated_seconds
    wins) and RANDOM. LEAST_LOADED / ROUND_ROBIN / AFFINITY land in a follow-up
    plan when pool telemetry is wired into Conductor.

    Takes ``list[Candidate]`` (not dict, not Capability) per the v3 reviewer
    note; the ``capability`` field on Candidate is the source of cost_hint.
    """
    if not candidates:
        raise MahavishnuError(
            "select_candidates called with empty list",
            ErrorCode.RESOURCE_NOT_FOUND,
        )
    if strategy == SelectorStrategy.CAPABILITY_SCORE:
        return max(candidates, key=lambda c: c.capability.cost_hint.estimated_seconds)
    if strategy == SelectorStrategy.RANDOM:
        return random.choice(candidates)
    # Fallback strategies: TODO when pool telemetry is wired.
    return max(candidates, key=lambda c: c.capability.cost_hint.estimated_seconds)


def plan(
    spec: CapabilitySpec,
    candidates: list[Candidate],
    trace_id: TraceId,
) -> ExecutionDAG:
    """Greedy fill: one node per required capability, top candidate wins.

    Emits a DAG edge from node A -> node B when B's io_in field is satisfied
    by A's io_out field (per ``TypeSchema.matches``).
    """
    by_cap: dict[CapabilityId, list[Candidate]] = {}
    for c in candidates:
        by_cap.setdefault(c.capability_id, []).append(c)

    nodes: list[DAGNode] = []
    for req in spec.requires:
        winners = by_cap.get(req, [])
        if not winners:
            raise MahavishnuError(
                f"no engine provides required capability {req!r}",
                ErrorCode.RESOURCE_NOT_FOUND,
            )
        # Pick the best candidate for THIS capability slot. select_candidates
        # takes a list of Candidates, not a dict — see v3 reviewer note.
        winner = select_candidates(winners, spec.selector)
        # Populate node inputs/outputs from the resolved Capability so the
        # edge loop below can match io_out to io_in. (v3 reviewer note #5.)
        nodes.append(
            DAGNode(
                node_id=f"n{len(nodes)}",
                engine_id=winner.engine_id,
                capability_id=winner.capability_id,
                inputs=winner.capability.io_in,
                outputs=winner.capability.io_out,
            )
        )

    # Emit edges: for each downstream node n_i, look at every earlier node
    # n_j and emit an edge if n_j.outputs.matches(n_i.inputs) (true iff
    # n_j.outputs.fields is a non-empty subset of n_i.inputs.fields).
    edges: list[DAGEdge] = []
    for i, downstream in enumerate(nodes):
        for upstream in nodes[:i]:
            for field, ty in downstream.inputs.fields.items():
                if upstream.outputs.fields.get(field) == ty:
                    edges.append(
                        DAGEdge(
                            from_node=upstream.node_id,
                            to_node=downstream.node_id,
                            via_field=field,
                        )
                    )
                    break  # one edge per (upstream, downstream) pair
    return ExecutionDAG(nodes=tuple(nodes), edges=tuple(edges), trace_id=trace_id)


async def emit_node(
    node: DAGNode,
    *,
    trace_id: TraceId,
    mcp: MCPAdapter,
    prompt: str,
    parent_envelope_ids: tuple[EnvelopeId, ...] = (),
    repos: tuple[str, ...] = (),
) -> EnvelopeId:
    """Dispatch one node to its engine. Returns the produced envelope id.

    Concrete dispatch lives in ``mahavishnu/engines/emit_node_dispatch.py`` —
    this function is the routing layer that picks the right dispatcher
    by looking up ``node.engine_id`` in ``_EMIT_NODE_DISPATCH``. If the
    lookup misses (a new engine was added without a dispatcher), we raise
    ``NotImplementedError`` with a distinctive message so production
    alerts can grep for it.
    """
    spec = NodeSpec(
        node_id=node.node_id,
        engine_id=node.engine_id,
        capability_id=node.capability_id,
        trace_id=trace_id,
        prompt=prompt,
        parent_envelope_ids=parent_envelope_ids,
        repos=repos,
    )
    dispatch = _EMIT_NODE_DISPATCH.get(node.engine_id)
    if dispatch is None:
        logger.warning(
            "per-engine emit_node dispatch not registered for engine_id=%r",
            node.engine_id,
        )
        raise NotImplementedError(
            f"per-engine emit_node dispatch not registered for engine_id={node.engine_id!r}"
        )
    handle: NodeHandle = await dispatch(spec, mcp)
    return handle.envelope_id


async def _dispatch_dag_waves(
    dag: ExecutionDAG,
    *,
    trace_id: TraceId,
    mcp: MCPAdapter,
    prompt_for_root: str,
) -> dict[str, EnvelopeId]:
    """Level-by-level dispatch across the DAG's ``DAGEdge`` topology.

    The original conductor iterated ``for node in dag.nodes``, which
    serialized independent branches. The level-by-level algorithm finds
    the next wave as the set of nodes whose incoming edges all come from
    already-completed nodes, then dispatches the wave concurrently via
    ``asyncio.gather``. This is the only correct DAG semantics — a node
    with multiple independent upstreams waits for ALL of them, not the
    LAST one in iteration order.

    For root nodes (no incoming edges) the prompt is ``prompt_for_root``;
    for downstream nodes the prompt is synthesized from upstream
    io_out (current placeholder: empty — downstream prompt synthesis
    is documented as a follow-up that targets ``CapabilitySpec.io_in``;
    see ``docs/plans/2026-10-12-per-engine-emit-node-dispatch.md``
    Phase 5 Step 5.2).
    """
    by_id: dict[str, DAGNode] = {n.node_id: n for n in dag.nodes}
    incoming: dict[str, list[str]] = {n.node_id: [] for n in dag.nodes}
    for edge in dag.edges:
        incoming[edge.to_node].append(edge.from_node)

    envelope_ids: dict[str, EnvelopeId] = {}
    remaining = set(by_id)
    wave = [nid for nid, parents in incoming.items() if not parents]

    while wave:
        # Dispatch wave concurrently via asyncio.gather so independent branches
        # actually run in parallel rather than sequentially.
        handles = await asyncio.gather(
            *(
                emit_node(
                    node=by_id[nid],
                    trace_id=trace_id,
                    mcp=mcp,
                    prompt=(prompt_for_root if not incoming[nid] else ""),
                    parent_envelope_ids=tuple(envelope_ids[p] for p in incoming[nid]),
                )
                for nid in wave
            )
        )
        for nid, eid in zip(wave, handles, strict=True):
            envelope_ids[nid] = eid
            remaining.discard(nid)
        wave = [nid for nid in remaining if all(p in envelope_ids for p in incoming[nid])]
    return envelope_ids


def emit_flow(
    dag: ExecutionDAG,
    *,
    prefect_factory: ModuleType | None = None,
) -> object:
    """Compile an ExecutionDAG into a Prefect flow definition.

    Wires nodes via typed Prefect ``task.submit(..., wait_for=[upstream_future])``
    — Prefect 3's actual API (NOT the invented ``task.submit_with_dependencies``).
    The edge loop must NOT re-submit each downstream node once per edge
    (that was v2's duplicate-execution bug).
    """
    if prefect_factory is None:
        import prefect as _prefect

        prefect_factory = _prefect

    # Prefect is a hard dependency; the lazy-import fallback above
    # guarantees ``prefect_factory`` is a module exposing ``.task`` and
    # ``.flow``. The parameter widens to ``ModuleType | None`` for the
    # optional test-injection seam only.

    task_decorator = prefect_factory.task
    flow_decorator = prefect_factory.flow

    @task_decorator
    def _node(node_id: str, capability_id: str) -> str:
        # Each node task returns an opaque envelope id (the dispatcher
        # writes the envelope to MCP and returns its id).
        return f"envelope-of-{node_id}"

    @flow_decorator(name=f"mahavishnu-dag-{dag.trace_id}")
    def _dag() -> dict[str, object]:
        futures: dict[str, object] = {}
        # First pass: submit every node with no upstream dependencies.
        upstream_of: dict[str, list[str]] = {n.node_id: [] for n in dag.nodes}
        for edge in dag.edges:
            upstream_of[edge.to_node].append(edge.from_node)

        for node in dag.nodes:
            wait_for = [futures[u] for u in upstream_of[node.node_id] if u in futures]
            futures[node.node_id] = _node.submit(
                node.node_id,
                node.capability_id,
                wait_for=wait_for,
            )
        return {nid: str(f) for nid, f in futures.items()}

    return _dag


__all__ = [
    "emit_flow",
    "emit_node",
    "plan",
    "resolve",
    "select_candidates",
]
