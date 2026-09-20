"""Mahavishnu ACP server — Agent Client Protocol surface.

This package exposes Mahavishnu as an ACP server (stdio JSON-RPC 2.0) so any
ACP client (Toad, Zed, JetBrains, future ACP tooling) can drive Mahavishnu
directly without the Claude Code layer between.

Module layout (filled in across Phase 1 → Phase 2):
- ``protocol`` — Pydantic wire-format models (every message type we send or
  receive). Phase 1.
- ``events`` — EventBridge-to-ACP-shape synthesizer. Phase 1.
- ``server`` — stdio JSON-RPC 2.0 dispatcher with security hardening. Phase 2.
- ``topics`` — canonical EventBridge topic names emitted by worker boundaries.
  Phase 1.

Sibling modules are re-exported from this package only when their public
surface stabilizes (currently only ``topics`` re-exports). Per the plan,
``serve`` / ``ACPError`` / ``ACPSession`` will be re-exported after Phase 2.
"""

from __future__ import annotations

from mahavishnu.acp.events import EventSynthesizer
from mahavishnu.acp.protocol import SessionUpdate
from mahavishnu.acp.topics import (
    ACP_TOPICS,
    TOOL_CALL_COMPLETED,
    TOOL_CALL_STARTED,
)

__all__ = [
    "ACP_TOPICS",
    "TOOL_CALL_COMPLETED",
    "TOOL_CALL_STARTED",
    "EventSynthesizer",
    "SessionUpdate",
]
