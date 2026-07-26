from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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
