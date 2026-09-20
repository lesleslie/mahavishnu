"""Mahavishnu ACP server — Agent Client Protocol surface.

This package exposes Mahavishnu as an ACP server (stdio JSON-RPC 2.0) so any
ACP client (Toad, Zed, JetBrains, future ACP tooling) can drive Mahavishnu
directly without the Claude Code layer between.

Module layout (filled in across Phase 1 → Phase 2):
- ``protocol`` — Pydantic wire-format models (every message type we send or
  receive). Phase 1.
- ``events`` — EventBridge-to-ACP-shape synthesizer. Phase 1.
- ``topics`` — canonical EventBridge topic names emitted by worker boundaries.
  Phase 1.
- ``errors`` — ``ACPError`` exception + JSON-RPC error code constants. Phase 2.
- ``auth`` — bearer auth gate (env-var/file, ``compare_digest``, redaction).
  Phase 2.
- ``server`` — stdio JSON-RPC 2.0 dispatcher with security hardening. Phase 2.
"""

from __future__ import annotations

from mahavishnu.acp.auth import (
    ENV_BEARER_TOKEN,
    ENV_BEARER_TOKEN_FILE,
    BearerRedactionFilter,
    acquire_bearer,
    verify_token,
)
from mahavishnu.acp.errors import (
    AUTH_INVALID,
    AUTH_REQUIRED,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    SESSION_PERSISTENCE_NOT_IMPLEMENTED,
    TOO_MANY_CONCURRENT_SESSIONS,
    ACPError,
)
from mahavishnu.acp.events import EventSynthesizer
from mahavishnu.acp.observability import session_span
from mahavishnu.acp.protocol import SessionUpdate
from mahavishnu.acp.topics import (
    ACP_TOPICS,
    TOOL_CALL_COMPLETED,
    TOOL_CALL_STARTED,
)

__all__ = [
    "ACP_TOPICS",
    "AUTH_INVALID",
    "AUTH_REQUIRED",
    "ENV_BEARER_TOKEN",
    "ENV_BEARER_TOKEN_FILE",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "SESSION_PERSISTENCE_NOT_IMPLEMENTED",
    "TOOL_CALL_COMPLETED",
    "TOOL_CALL_STARTED",
    "TOO_MANY_CONCURRENT_SESSIONS",
    "ACPError",
    "BearerRedactionFilter",
    "EventSynthesizer",
    "SessionUpdate",
    "acquire_bearer",
    "session_span",
    "verify_token",
]
