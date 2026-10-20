"""Strict-typed input/output models for the per-engine ``emit_node`` dispatch.

These are the wire-shape models that flow between ``mahavishnu/core/conductor.py``
and ``mahavishnu/engines/emit_node_dispatch.py``. They are Pydantic v2
``BaseModel`` with ``model_config = ConfigDict(frozen=True, extra="forbid")``
so the existing ``EngineId`` / ``TraceId`` / ``EnvelopeId`` / ``CapabilityId``
regex constraints in :mod:`mahavishnu.core.capabilities` are honored at
construction time.

The original plan draft proposed ``msgspec.Struct``; we deliberately use
Pydantic instead because ``EngineId`` is an ``Annotated[str, StringConstraints(...)]``
newtype and ``msgspec.Struct`` does not honor Pydantic ``Annotated`` metadata.
The Pydantic choice preserves the regex validation that the conductor depends
on.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from mahavishnu.core.capabilities import (
    # Runtime import (not TYPE_CHECKING): Pydantic resolves field annotations
    # at class-creation time, so these `Annotated[str, StringConstraints(...)]`
    # newtypes must be importable or the models fail to build.
    CapabilityId,
    EngineId,
    EnvelopeId,
    TraceId,
)

_FROZEN_FORBID = ConfigDict(frozen=True, extra="forbid")


class NodeSpec(BaseModel):
    """The input contract for one ``emit_node`` dispatch.

    Frozen + extra='forbid' (Pydantic v2 fields are kw-only by default).
    Each field's runtime regex validation is inherited from the newtype
    ``Annotated[str, StringConstraints(...)]`` in
    :mod:`mahavishnu.core.capabilities`.
    """

    model_config = _FROZEN_FORBID

    node_id: str
    engine_id: EngineId
    capability_id: CapabilityId
    trace_id: TraceId
    prompt: str
    parent_envelope_ids: tuple[EnvelopeId, ...] = ()
    repos: tuple[str, ...] = ()
    timeout_seconds: int = 300


class NodeHandle(BaseModel):
    """The output contract for one ``emit_node`` dispatch.

    Carries the id of the persisted :class:`CapabilityEnvelope` and the
    engine-specific status. ``flow_run_id`` is populated only when the
    engine surfaces one (Prefect ``flow_run.id``, Hatchet ``run_id``).
    """

    model_config = _FROZEN_FORBID

    envelope_id: EnvelopeId
    engine_id: EngineId
    status: str  # "completed" | "failed" | "timeout"
    flow_run_id: str | None = None
    error: str | None = None


__all__ = ["NodeHandle", "NodeSpec"]
