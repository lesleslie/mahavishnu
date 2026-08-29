"""Async read-back analogue of the deleted ``workflow_result`` tool."""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP

from mahavishnu.core.capabilities import TraceId
from mahavishnu.core.envelopes import list_envelopes

if TYPE_CHECKING:
    from mahavishnu.core.dhara import DharaClient


def register_get_capability_result(
    server: FastMCP, *, dhara: "DharaClient",
) -> None:
    """Register ``get_capability_result(trace_id: TraceId)`` on ``server``."""

    @server.tool(name="get_capability_result", description="List envelopes for a trace.")
    async def get_capability_result(trace_id: TraceId) -> dict[str, object]:
        addrs = await list_envelopes(trace_id, dhara=dhara)
        return {
            "trace_id": trace_id,
            "status": "completed" if addrs else "pending",
            "envelopes": [a.to_key() for a in addrs],
            "error": None,
        }


__all__ = ["register_get_capability_result"]