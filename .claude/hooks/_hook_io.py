"""Shared I/O helpers for Claude Code hook scripts in this project.

Centralizes:
- Reading the hook stdin JSON payload
- Extracting the session_id and cwd fields used by the worktree
  isolation hook

Used by:
- ``.claude/hooks/worktree-session-isolation.py`` (SessionStart hook)
- ``.claude/hooks/bodai-activity-subscriber.py`` (reference pattern)

The hook's stdin schema is documented in Claude Code's hook contract;
the relevant fields are:
- ``session_id`` (str | None) — Claude Code session UUID
- ``cwd`` (str | None) — current working directory of the session
- ``tool_name`` (str | None) — for PostToolUse hooks
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HookPayload:
    """The fields we care about from a Claude Code hook stdin payload.

    Other fields may be present in the JSON but are ignored.
    """

    session_id: str
    cwd: str
    raw: dict[str, Any]


def read_session_payload() -> HookPayload:
    """Read and parse the hook stdin JSON payload.

    Tolerates missing or non-JSON input by returning empty defaults
    rather than raising — hooks must never block Claude startup on a
    malformed payload (per the exit-0-always contract).
    """
    try:
        raw_str = sys.stdin.read()
    except OSError:
        return HookPayload(session_id="", cwd="", raw={})

    if not raw_str.strip():
        return HookPayload(session_id="", cwd="", raw={})

    try:
        raw = json.loads(raw_str)
    except json.JSONDecodeError:
        return HookPayload(session_id="", cwd="", raw={})

    if not isinstance(raw, dict):
        return HookPayload(session_id="", cwd="", raw={})

    session_id = raw.get("session_id") or ""
    cwd = raw.get("cwd") or ""
    return HookPayload(session_id=session_id, cwd=cwd, raw=raw)


__all__ = ["HookPayload", "read_session_payload"]
