# tests/unit/test_conductor_resolver.py
from __future__ import annotations

from mahavishnu.core.capabilities import (
    Capability, CapabilityId, CapabilityKind, CapabilitySpec,
    CapabilityState, CostHint, EngineId, EngineRegistration,
    SelectorStrategy, TraceId, TypeSchema,
)
from mahavishnu.core.conductor import resolve


def _cap(cap_id: str) -> Capability:
    return Capability(
        id=CapabilityId(cap_id),
        kind=CapabilityKind.ENGINE,
        description="",
        io_in=TypeSchema(),
        io_out=TypeSchema(),
        state=CapabilityState.DURABLE,
    )


def test_resolver_picks_engine_that_provides_required_capability() -> None:
    reg = EngineRegistration(
        engine_id=EngineId("prefect"),
        provides=[_cap("engine:durable-flow")],
        consumes=[],
    )
    spec = CapabilitySpec(requires=[CapabilityId("engine:durable-flow")], prompt="x")
    candidates = resolve(spec, [reg])
    assert len(candidates) == 1
    assert candidates[0].engine_id == EngineId("prefect")


def test_resolver_skips_disabled_engines() -> None:
    reg = EngineRegistration(
        engine_id=EngineId("prefect"),
        provides=[_cap("engine:durable-flow")],
        enabled=False,
    )
    spec = CapabilitySpec(requires=[CapabilityId("engine:durable-flow")], prompt="x")
    assert resolve(spec, [reg]) == []


def test_resolver_returns_empty_when_no_match() -> None:
    spec = CapabilitySpec(requires=[CapabilityId("engine:nonexistent")], prompt="x")
    assert resolve(spec, []) == []
