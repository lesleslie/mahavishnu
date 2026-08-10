"""workflow_get_outcome MCP tool — read-back-and-validate for workflow outcomes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import dhara
from dhara.schema import WorkflowOutcome, from_dict

if TYPE_CHECKING:
    from mcp_common.fastmcp import FastMCP

# Substrate-compat: `dhara.get` is not a module-level attribute on the
# installed dhara package — real callers pass a configured Dhara client
# (e.g. `await self.dhara.get(...)`) or import a configured binding into
# `dhara.get` at integration time. Tests substitute via
# `monkeypatch.setattr("workflow_tools.dhara.get", ...)`; the hasattr
# guard lets that patch land even when the host package has not injected
# a binding.
if not hasattr(dhara, "get"):
    dhara.get = None  # type: ignore[attr-defined]


async def workflow_get_outcome(workflow_id: str) -> WorkflowOutcome | None:
    """Read back the persisted WorkflowOutcome via from_dict, validating the payload.

    Returns ``None`` when no record exists at ``workflow-results/{workflow_id}/``.
    """
    payload = await dhara.get(f"workflow-results/{workflow_id}/")
    if payload is None:
        return None
    return from_dict("workflow_outcome", payload)


def register_workflow_tools(mcp: FastMCP) -> None:
    """Register workflow outcome tools with the FastMCP server.

    Structural C901 suppression: FastMCP's ``@mcp.tool()`` decorator
    requires each tool function to be defined inline so it can introspect
    the function name and signature for the MCP tool schema. The tools
    registered here are intentionally kept inline; the complexity is the
    cost of the FastMCP API contract, not bad code.

    The inner tool function delegates to the module-level
    ``workflow_get_outcome`` coroutine so the implementation stays testable
    in isolation without spinning up a FastMCP server.
    """

    @mcp.tool()
    async def workflow_get_outcome_tool(workflow_id: str) -> WorkflowOutcome | None:
        """Read back the persisted WorkflowOutcome for ``workflow_id``.

        Returns ``None`` when no record exists. Validates the persisted
        payload against the substrate ``workflow_outcome`` schema.
        """
        return await workflow_get_outcome(workflow_id)
