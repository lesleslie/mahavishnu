"""workflow_get_outcome MCP tool — read-back-and-validate for workflow outcomes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import dhara
from dhara.schema import WorkflowOutcome, from_dict
from oneiric.core.logging import get_logger

from mahavishnu.core.permissions import Permission
from mahavishnu.mcp.auth import require_mcp_auth
from mahavishnu.mcp.tools._workflow_id_guard import validate_workflow_id

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

logger = get_logger(__name__)


async def workflow_get_outcome(
    workflow_id: str,
) -> WorkflowOutcome | dict[str, Any] | None:
    """Read back the persisted WorkflowOutcome via from_dict, validating the payload.

    Returns ``None`` when no record exists at ``workflow-results/{workflow_id}/``
    OR when the substrate does not expose ``dhara.get`` (logged WARNING, see
    the substrate-compat gate below).
    Returns ``{"workflow_id": workflow_id, "status": "invalid_workflow_id"}``
    when ``workflow_id`` is rejected by the conservative path-traversal guard
    (mirrors the sibling parity gate in ``pool_tools.workflow_result``);
    Dhara is never queried in that case.
    """
    # Path-traversal guard: caller-supplied workflow_id is spliced into
    # ``f"workflow-results/{workflow_id}/"`` below, so reject anything
    # outside the conservative regex BEFORE the Dhara read.
    if not validate_workflow_id(workflow_id):
        return {"workflow_id": workflow_id, "status": "invalid_workflow_id"}

    # Substrate-compat gate: only read when dhara.get is exposed. Missing
    # substrate → return None and warn (do not conflate with "no record").
    get_fn = getattr(dhara, "get", None)
    if get_fn is None:
        logger.warning(
            "workflow_outcome_read_skipped",
            extra={
                "workflow_id": workflow_id,
                "reason": "dhara.get_unbound",
            },
        )
        return None
    payload = await get_fn(f"workflow-results/{workflow_id}/")
    if payload is None:
        return None
    return from_dict("workflow_outcome", payload)  # ty: ignore[invalid-return-type]


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
    @require_mcp_auth(required_permission=Permission.VIEW_WORKFLOW_STATUS)
    async def workflow_get_outcome_tool(
        workflow_id: str,
        user_id: str | None = None,
    ) -> WorkflowOutcome | dict[str, Any] | None:
        """Read back the persisted WorkflowOutcome for ``workflow_id``.

        Returns ``None`` when no record exists. Returns
        ``{"workflow_id": ..., "status": "invalid_workflow_id"}`` when
        the workflow_id is rejected by the path-traversal guard. Validates
        the persisted payload against the substrate ``workflow_outcome``
        schema.

        Auth: requires ``user_id`` with ``VIEW_WORKFLOW_STATUS`` permission
        (mirror of the ``@require_mcp_auth`` contract). Without ``user_id``
        the tool returns ``{"status": "error", "error_code": "AUTH_REQUIRED", ...}``
        before any substrate access.
        """
        return await workflow_get_outcome(workflow_id)
