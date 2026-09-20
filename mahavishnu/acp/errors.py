"""ACP error types and JSON-RPC error code conventions.

This module owns the project's custom JSON-RPC error codes (the
``-32000`` to ``-32099`` project-defined range) and the ``ACPError``
exception type that wraps them.

## Error code conventions

Standard JSON-RPC 2.0 error codes (defined in the spec):

| Code   | Meaning           | Used by the ACP server                          |
|--------|-------------------|-------------------------------------------------|
| -32700 | Parse error       | JSON-RPC line not parseable (or > 1 MB)         |
| -32600 | Invalid Request   | Batch requests, malformed envelopes              |
| -32601 | Method not found  | Unknown JSON-RPC ``method``                     |
| -32602 | Invalid params    | Pydantic validation rejected the params         |
| -32603 | Internal error    | Unhandled dispatcher exception                   |

Project-defined codes (per plan §Phase 2 Decision 1, bullet "Error code
convention"):

| Code   | Meaning                                |
|--------|----------------------------------------|
| -32001 | Auth required (no prior authenticate)  |
| -32002 | Auth invalid (wrong token)             |
| -32003 | Session persistence not implemented   |
| -32004 | Too many concurrent sessions           |
"""

from __future__ import annotations

from typing import Any

# === Standard JSON-RPC 2.0 error codes ===

PARSE_ERROR: int = -32700
INVALID_REQUEST: int = -32600
METHOD_NOT_FOUND: int = -32601
INVALID_PARAMS: int = -32602
INTERNAL_ERROR: int = -32603

# === Project-defined ACP error codes (plan §Phase 2 Decision 1) ===

AUTH_REQUIRED: int = -32001
AUTH_INVALID: int = -32002
SESSION_PERSISTENCE_NOT_IMPLEMENTED: int = -32003
TOO_MANY_CONCURRENT_SESSIONS: int = -32004


# === Exception type ===


class ACPError(Exception):
    """Protocol-level ACP error. Serializes to a JSON-RPC ``error`` object.

    ``code`` and ``message`` are required; ``data`` is optional additional
    context that the dispatcher will pass through to the wire response.
    The dispatcher (Phase 2) catches ``ACPError`` and emits a
    ``JsonRpcErrorResponse``; any other exception becomes a
    ``-32603 Internal error``.
    """

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-RPC error object as a dict, omitting ``data`` when None."""
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            out["data"] = self.data
        return out

    def __repr__(self) -> str:
        return f"ACPError(code={self.code}, message={self.message!r})"


__all__ = [
    "AUTH_INVALID",
    "AUTH_REQUIRED",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "SESSION_PERSISTENCE_NOT_IMPLEMENTED",
    "TOO_MANY_CONCURRENT_SESSIONS",
    "ACPError",
]
