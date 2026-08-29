"""Capability schema: types, enums, and Pydantic models for the registry.

This is the single source of truth for what a Capability, EngineRegistration,
ExecutionDAG, etc. look like. Imported by ``capabilities_loader``,
``conductor``, ``envelopes``, and the capability MCP tools.

Schema rules:
- Every model uses ``model_config = ConfigDict(frozen=True, extra="forbid")``
  except ``CapabilityExecutionResult`` which is mutable by design
  (returns are mutated after construction by the executor).
- Newtypes enforce ID patterns at the Pydantic layer (not just docstring).
- No ``Any`` in tool inputs or orchestration state.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

if TYPE_CHECKING:
    from datetime import datetime

# ---------------------------------------------------------------------------
# ID patterns
# ---------------------------------------------------------------------------

CapabilityId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z]+:[a-z0-9._-]+$", min_length=3, max_length=128),
]
EngineId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_-]{1,63}$", min_length=2, max_length=64),
]
# EnvelopeId is a UUIDv4 — format-only validation here; semantic via uuid.UUID.
EnvelopeId = Annotated[
    str,
    StringConstraints(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        min_length=36,
        max_length=36,
    ),
]
TraceId = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{32}$", min_length=32, max_length=32),
]

_FROZEN_FORBID = ConfigDict(frozen=True, extra="forbid")

# TypeAdapters for runtime validation of the Annotated[str, StringConstraints]
# newtypes. Calling them directly (`TraceId(value)`) delegates to str() and
# never validates, so use these adapters when you need to validate outside a
# Pydantic field context (e.g., parsing untrusted input in from_key()).
_TRACE_ID_ADAPTER: TypeAdapter[str] = TypeAdapter(TraceId)
_ENVELOPE_ID_ADAPTER: TypeAdapter[str] = TypeAdapter(EnvelopeId)
_CAPABILITY_ID_ADAPTER: TypeAdapter[str] = TypeAdapter(CapabilityId)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CapabilityKind(StrEnum):
    ENGINE = "engine"
    MODEL = "model"
    WORKER = "worker"
    ADAPTER = "adapter"


class CapabilityState(StrEnum):
    EPHEMERAL = "ephemeral"
    DURABLE = "durable"
    INTERACTIVE = "interactive"  # added per spec §2


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class SelectorStrategy(StrEnum):
    LEAST_LOADED = "least_loaded"
    ROUND_ROBIN = "round_robin"
    CAPABILITY_SCORE = "capability_score"
    RANDOM = "random"
    AFFINITY = "affinity"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TypeSchema(BaseModel):
    """Typed I/O contract. Empty schema means "any".

    Production usage of ``matches()`` lives in conductor.plan() (Phase 3a.2)
    — the schema's structural comparison is what lets the planner emit edges.
    """

    model_config = _FROZEN_FORBID
    fields: dict[str, str] = Field(default_factory=dict)

    def matches(self, other: TypeSchema) -> bool:
        """Structural sub-schema check: every field in self is also in other with a compatible type.

        Empty schema matches anything. Used by ``Conductor.plan()`` to emit DAG edges
        when a downstream node's io_in is satisfied by an upstream node's io_out.
        """
        if not self.fields:
            return True
        return all(other.fields.get(name) == ty for name, ty in self.fields.items())


class CostHint(BaseModel):
    model_config = _FROZEN_FORBID
    estimated_seconds: float = 1.0
    estimated_tokens: int = 0
    has_side_effects: bool = False


class HealthRef(BaseModel):
    model_config = _FROZEN_FORBID
    endpoint: str
    timeout_seconds: float = 5.0


class Capability(BaseModel):
    model_config = _FROZEN_FORBID
    id: CapabilityId
    kind: CapabilityKind
    description: str
    io_in: TypeSchema
    io_out: TypeSchema
    state: CapabilityState = CapabilityState.EPHEMERAL
    cost_hint: CostHint = Field(default_factory=CostHint)
    tags: list[str] = Field(default_factory=list)
    health_ref: HealthRef | None = None


class EngineRegistration(BaseModel):
    model_config = _FROZEN_FORBID
    engine_id: EngineId
    provides: list[Capability]
    consumes: list[Capability] = Field(default_factory=lambda: list[Capability]())
    enabled: bool = True
    version: str = "0.0.0"


class CapabilityEnvelope(BaseModel):
    model_config = _FROZEN_FORBID
    envelope_id: EnvelopeId
    capability_id: CapabilityId
    engine_id: EngineId
    io_out: dict[str, str] = Field(default_factory=dict)  # string-only after redaction
    produced_at: datetime
    trace_id: TraceId
    parent_envelope_ids: list[EnvelopeId] = Field(default_factory=list)
    sensitivity: str = "internal"  # for Phase 4 TTL: public|internal|secret


class EnvelopeAddress(BaseModel):
    model_config = _FROZEN_FORBID
    trace_id: TraceId
    envelope_id: EnvelopeId

    def to_key(self) -> str:
        return f"envelopes/{self.trace_id}/{self.envelope_id}"

    @classmethod
    def from_key(cls, key: str) -> EnvelopeAddress:
        # envelopes/<trace_id:32hex>/<envelope_id:36>
        parts = key.split("/")
        if len(parts) != 3 or parts[0] != "envelopes":
            raise ValueError(f"not an envelope key: {key!r}")
        return cls(
            trace_id=_TRACE_ID_ADAPTER.validate_python(parts[1]),
            envelope_id=_ENVELOPE_ID_ADAPTER.validate_python(parts[2]),
        )


class Candidate(BaseModel):
    model_config = _FROZEN_FORBID
    engine_id: EngineId
    capability_id: CapabilityId
    score: float
    reason: str
    # The resolved Capability object, so plan() can populate DAGNode inputs/outputs
    # from the same source. Set by Conductor.resolve(); required.
    capability: Capability


class DAGNode(BaseModel):
    model_config = _FROZEN_FORBID
    node_id: str
    engine_id: EngineId
    capability_id: CapabilityId
    inputs: TypeSchema
    outputs: TypeSchema


class DAGEdge(BaseModel):
    model_config = _FROZEN_FORBID
    from_node: str
    to_node: str
    via_field: str  # name of the io_out field that flows to io_in[v]


class ExecutionDAG(BaseModel):
    model_config = _FROZEN_FORBID
    nodes: tuple[DAGNode, ...]
    edges: tuple[DAGEdge, ...]
    trace_id: TraceId


class CapabilitySpec(BaseModel):
    model_config = _FROZEN_FORBID
    requires: list[CapabilityId]
    prompt: str = Field(min_length=1)
    selector: SelectorStrategy = SelectorStrategy.CAPABILITY_SCORE
    affinity_pool_id: str | None = None
    trace_id: TraceId | None = None
    timeout_seconds: int = Field(default=300, ge=1, le=3600)


# ---------------------------------------------------------------------------
# Result type for capability_tools.execute_capability (Phase 3a.3)
# ---------------------------------------------------------------------------


class CapabilityExecutionResult(BaseModel):
    """Return type of ``execute_capability``. Replaces dict[str, Any] leakage."""

    model_config = ConfigDict(extra="forbid")  # mutable — set after construction
    status: str  # "planned" | "queued" | "rejected"
    trace_id: TraceId
    dag: ExecutionDAG | None = None
    error: str | None = None


__all__ = [
    "Candidate",
    "Capability",
    "CapabilityEnvelope",
    "CapabilityExecutionResult",
    "CapabilityId",
    "CapabilityKind",
    "CapabilitySpec",
    "CapabilityState",
    "CostHint",
    "DAGEdge",
    "DAGNode",
    "EngineId",
    "EngineRegistration",
    "EnvelopeAddress",
    "EnvelopeId",
    "ExecutionDAG",
    "HealthRef",
    "HealthStatus",
    "SelectorStrategy",
    "TraceId",
    "TypeSchema",
]
