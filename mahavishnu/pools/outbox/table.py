"""Mahavishnu WAL: row model + status enum.

The WAL captures deferred memory writes destined for Session-Buddy. The
aggregator's existing circuit breaker gates the drainer; this module
defines the row shape and the three terminal states.

Spec: docs/superpowers/specs/2026-07-29-session-buddy-extension-design.md
(Q2: data-plane durability).
"""

from __future__ import annotations

from datetime import (
    datetime,  # noqa: TC003  # Pydantic v2 resolves forward refs at model_rebuild() time
)
from typing import Literal

from pydantic import BaseModel

OutboxStatus = Literal["pending", "drained", "failed"]


class MemoryOutboxRow(BaseModel):
    """A single WAL row representing a deferred memory write to Session-Buddy."""

    id: int
    key: str
    payload: dict[str, object]
    enqueued_at: datetime
    attempts: int = 0
    last_error: str | None = None
    status: OutboxStatus = "pending"
