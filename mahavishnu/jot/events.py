"""Jot event data model and JSONL codec.

Wire format: one event per line, compact JSON, trailing \\n.
See spec §"Data Model" for field semantics.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Literal, TypedDict

# Sub-plan 3 (drain) extends with 6 new ops: dispatch, dispatch_done,
# dispatch_failed, defer, defer_expired, delete. See spec §4.1.
Op = Literal[
    "capture", "edit", "done", "reopen",                  # sub-plan 1+2
    "dispatch", "dispatch_done", "dispatch_failed",       # NEW (sub-plan 3)
    "defer", "defer_expired", "delete",                    # NEW (sub-plan 3)
]


class CaptureCtx(TypedDict, total=False):
    """Type-safe context fields captured at write-time.

    All keys are optional because context sources (env vars, stdin fields)
    may be missing. See spec §"Capture-time ambient context".
    """

    cwd: str
    session_id: str
    files: list[str]
    env_repo: str | None
    env_branch: str | None


@dataclass(frozen=True)
class HLC:
    """Hybrid Logical Clock for monotonic ordering of events within and across nodes.

    Monotonic per-node via (wall_ms, ctr) tuple ordering; node field breaks ties
    across nodes when comparing HLCs from different sources.
    """

    wall_ms: int
    ctr: int
    node: str


@dataclass(frozen=True)
class JotEvent:
    """A single jot inbox event. See spec §"Wire format"."""

    id: str
    op: Op
    hlc: HLC
    text: str
    # ctx: typed as CaptureCtx at API surface, stored as dict[str, Any] for
    # JSON round-trip simplicity. SFH-L5 fix: TypedDict at the boundary.
    ctx: dict[str, Any]
    created_ms: int


def serialize(event: JotEvent) -> str:
    """Serialize a JotEvent to a single JSONL line (compact, trailing newline).

    Returns a string ending in '\\n'. The caller is responsible for writing
    it to the log file with a looping os.write() (H5 fix).
    """
    payload = asdict(event)
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n"


def deserialize(line: str) -> JotEvent:
    """Deserialize a JSONL line back to a JotEvent.

    Accepts input with or without a trailing newline. Raises json.JSONDecodeError
    on invalid input — the caller is responsible for error handling.
    """
    stripped = line.rstrip("\n")
    payload = json.loads(stripped)
    hlc_dict = payload["hlc"]
    hlc = HLC(wall_ms=hlc_dict["wall_ms"], ctr=hlc_dict["ctr"], node=hlc_dict["node"])
    return JotEvent(
        id=payload["id"],
        op=payload["op"],
        hlc=hlc,
        text=payload["text"],
        ctx=payload["ctx"],
        created_ms=payload["created_ms"],
    )
