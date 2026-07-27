# Pydantic v2 does not auto-resolve string annotations. We import
# `WorkerLifecycleState` at runtime so Pydantic can resolve the
# `state: WorkerLifecycleState` field annotation when validating the
# model. `dt.datetime` is annotation-only, but ruff TC003 insists on
# moving it under TYPE_CHECKING; since we still need `dt.datetime` at
# runtime for Pydantic's field typing, we keep the import at top-level
# with a noqa.

from __future__ import annotations

import datetime as dt  # noqa: TC003  (needed at runtime by Pydantic v2)
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .state import WorkerLifecycleState  # noqa: TC001  (needed at runtime by Pydantic v2)


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
