"""Schema validation tests for mahavishnu.core.capabilities.

Verifies ID newtype patterns, model frozen/forbid semantics, and required
field constraints.
"""
from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import StringConstraints, TypeAdapter, ValidationError

from mahavishnu.core.capabilities import (
    Capability, CapabilityEnvelope, CapabilityId, CapabilityKind,
    CapabilitySpec, CapabilityState, Candidate, CostHint, DAGEdge,
    DAGNode, EngineId, EngineRegistration, EnvelopeAddress, EnvelopeId,
    ExecutionDAG, HealthRef, HealthStatus, SelectorStrategy, TraceId,
    TypeSchema,
)


# `CapabilityId`, `EngineId`, `TraceId` are `Annotated[str, StringConstraints]`
# aliases. Calling the alias directly delegates to str() and never validates;
# use TypeAdapter to actually exercise the constraint.
_capability_id_t = TypeAdapter(CapabilityId)
_engine_id_t = TypeAdapter(EngineId)
_trace_id_t = TypeAdapter(TraceId)


def test_capability_id_rejects_bad_format() -> None:
    with pytest.raises(ValidationError):
        _capability_id_t.validate_python("BAD")  # missing colon


def test_capability_id_accepts_kind_colon_name() -> None:
    assert _capability_id_t.validate_python("worker:bash") == "worker:bash"


def test_trace_id_must_be_32_hex() -> None:
    _trace_id_t.validate_python("0" * 32)  # ok
    with pytest.raises(ValidationError):
        _trace_id_t.validate_python("not-hex")


def test_capability_model_is_frozen_and_forbids_extras() -> None:
    cap = Capability(
        id="worker:bash",
        kind=CapabilityKind.WORKER,
        description="",
        io_in=TypeSchema(),
        io_out=TypeSchema(),
    )
    with pytest.raises(ValidationError):
        cap.description = "new"  # frozen
    with pytest.raises(ValidationError):
        Capability.model_validate({
            "id": "worker:bash",
            "kind": "worker",
            "description": "",
            "io_in": {},
            "io_out": {},
            "unknown_field": "x",
        })


def test_capability_spec_requires_nonempty_prompt() -> None:
    with pytest.raises(ValidationError):
        CapabilitySpec(requires=[], prompt="")


def test_engine_id_pattern() -> None:
    _engine_id_t.validate_python("prefect")  # ok
    with pytest.raises(ValidationError):
        _engine_id_t.validate_python("BAD ENGINE")  # space + uppercase