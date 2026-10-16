# Pydantic v2 does not auto-resolve string annotations. We import
# ``WorkerLifecycleState`` at runtime (NOT under ``TYPE_CHECKING``)
# so Pydantic can resolve the ``state: WorkerLifecycleState`` field
# annotation when validating the model. Earlier this import was
# incorrectly placed under ``TYPE_CHECKING`` — a regression surfaced
# when the SHELL dispatch path (Phase D) began exercising the
# durable worker record at runtime, hitting the
# ``not fully defined; you should define WorkerLifecycleState, then
# call DurableWorkerRecord.model_rebuild()`` pydantic error.
# ``dt.datetime`` is annotation-only; ruff TC003 pushes it under
# TYPE_CHECKING, and Pydantic's runtime field typing handles the
# string ``dt.datetime`` fine — so we keep it there.

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    pass

from .state import WorkerLifecycleState


class TmuxTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    socket: str
    session: str
    window: str
    pane: str
    attach_command: str | None = None


class DurableWorkerRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    worker_id: str
    worker_type: str
    backend: str
    tmux: TmuxTarget | None
    state: WorkerLifecycleState
    created_at: dt.datetime
    last_seen_at: dt.datetime
    last_output_offset: int = 0
    claude_session: str | None = None
    last_exit_code: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DurableWorkerRecord:
        return cls.model_validate(data)
