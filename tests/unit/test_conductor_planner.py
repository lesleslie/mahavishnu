# tests/unit/test_conductor_planner.py
from __future__ import annotations

from mahavishnu.core.capabilities import (
    Capability, CapabilityId, CapabilityKind, CapabilitySpec,
    CapabilityState, CostHint, EngineId, EngineRegistration,
    ExecutionDAG, SelectorStrategy, TraceId, TypeSchema,
)
from mahavishnu.core.conductor import plan, resolve, select_candidates


def _cap(cap_id: str, io_in: TypeSchema | None = None, io_out: TypeSchema | None = None) -> Capability:
    return Capability(
        id=CapabilityId(cap_id),
        kind=CapabilityKind.ENGINE,
        description="",
        io_in=io_in or TypeSchema(),
        io_out=io_out or TypeSchema(),
        state=CapabilityState.DURABLE,
    )


def test_plan_compiles_one_node_per_required_capability() -> None:
    reg = EngineRegistration(
        engine_id=EngineId("prefect"),
        provides=[_cap("engine:durable-flow")],
    )
    spec = CapabilitySpec(requires=[CapabilityId("engine:durable-flow")], prompt="x")
    candidates = resolve(spec, [reg])
    dag = plan(spec, candidates, trace_id=TraceId("0" * 32))
    assert isinstance(dag, ExecutionDAG)
    assert len(dag.nodes) == 1
    assert dag.nodes[0].engine_id == EngineId("prefect")


def test_plan_emits_edges_when_io_matches() -> None:
    """If node A's io_out has a field that node B's io_in requires, plan emits an edge."""
    a_cap = _cap(
        "engine:rag-retrieve",
        io_out=TypeSchema(fields={"chunks": "list[str]"}),
    )
    b_cap = _cap(
        "engine:summarize",
        io_in=TypeSchema(fields={"chunks": "list[str]"}),
    )
    regs = [
        EngineRegistration(engine_id=EngineId("llamaindex"), provides=[a_cap]),
        EngineRegistration(engine_id=EngineId("prefect"), provides=[b_cap]),
    ]
    spec = CapabilitySpec(
        requires=[CapabilityId("engine:rag-retrieve"), CapabilityId("engine:summarize")],
        prompt="x",
    )
    candidates = resolve(spec, regs)
    dag = plan(spec, candidates, trace_id=TraceId("0" * 32))
    assert len(dag.edges) == 1
    assert dag.edges[0].via_field == "chunks"


def test_plan_raises_when_no_engine_provides_a_required_capability() -> None:
    from mahavishnu.core.errors import MahavishnuError
    import pytest

    spec = CapabilitySpec(
        requires=[CapabilityId("engine:durable-flow"), CapabilityId("engine:nope")],
        prompt="x",
    )
    regs = [
        EngineRegistration(
            engine_id=EngineId("prefect"),
            provides=[_cap("engine:durable-flow")],
        ),
    ]
    candidates = resolve(spec, regs)
    with pytest.raises(MahavishnuError):
        plan(spec, candidates, trace_id=TraceId("0" * 32))


def test_select_candidates_raises_on_empty_list() -> None:
    """select_candidates([]) must raise rather than silently return None."""
    from mahavishnu.core.errors import MahavishnuError
    import pytest

    with pytest.raises(MahavishnuError):
        select_candidates([], SelectorStrategy.CAPABILITY_SCORE)


def test_select_candidates_random_picks_from_list() -> None:
    """RANDOM strategy selects one of the candidates (no determinism guaranteed)."""
    caps = [
        _cap("engine:rag-retrieve"),
        _cap("engine:rag-retrieve"),
        _cap("engine:rag-retrieve"),
    ]
    spec = CapabilitySpec(requires=[CapabilityId("engine:rag-retrieve")], prompt="x")
    regs = [EngineRegistration(engine_id=EngineId("prefect"), provides=caps)]
    candidates = resolve(spec, regs)
    assert len(candidates) == 3

    spec_random = CapabilitySpec(
        requires=[CapabilityId("engine:rag-retrieve")],
        prompt="x",
        selector=SelectorStrategy.RANDOM,
    )
    picked = select_candidates(candidates, spec_random.selector)
    assert picked in candidates
    assert picked.engine_id == EngineId("prefect")


def test_select_candidates_least_loaded_falls_back_to_cost_max() -> None:
    """LEAST_LOADED is unimplemented; falls back to max(cost_hint.estimated_seconds)."""
    caps = [
        _cap("engine:rag-retrieve"),
        _cap("engine:rag-retrieve"),
        _cap("engine:rag-retrieve"),
    ]
    spec = CapabilitySpec(requires=[CapabilityId("engine:rag-retrieve")], prompt="x")
    regs = [EngineRegistration(engine_id=EngineId("prefect"), provides=caps)]
    candidates = resolve(spec, regs)

    spec_least = CapabilitySpec(
        requires=[CapabilityId("engine:rag-retrieve")],
        prompt="x",
        selector=SelectorStrategy.LEAST_LOADED,
    )
    picked = select_candidates(candidates, spec_least.selector)
    # All caps have identical cost_hint.estimated_seconds=1.0, so max returns
    # the first one (stable contract for ties).
    assert picked is candidates[0]
