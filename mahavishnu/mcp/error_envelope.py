"""MCP error envelope for canonical tool responses."""

from __future__ import annotations

from pydantic import BaseModel


class McpErrorEnvelope(BaseModel):
    """Wraps error responses from MCP tools with recovery metadata."""

    error: bool = True
    error_code: str
    message: str
    recovery: list[str] = []
    retryable: bool = False
    retry_after_seconds: int | None = None
    details: dict[str, object] = {}


def wrap_error(
    error_code: str,
    message: str,
    *,
    recovery: list[str] | None = None,
    retryable: bool = False,
    retry_after_seconds: int | None = None,
    details: dict[str, object] | None = None,
) -> McpErrorEnvelope:
    """Create an MCP error envelope."""
    return McpErrorEnvelope(
        error_code=error_code,
        message=message,
        recovery=recovery or [],
        retryable=retryable,
        retry_after_seconds=retry_after_seconds,
        details=details or {},
    )
