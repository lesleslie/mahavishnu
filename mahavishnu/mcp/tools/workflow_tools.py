"""workflow_get_outcome MCP tool — read-back-and-validate for workflow outcomes."""

from __future__ import annotations

import dhara
from dhara.schema import WorkflowOutcome, from_dict

# Substrate-compat: `dhara.get` is not a module-level attribute on the
# installed dhara package — real callers pass a configured Dhara client
# (e.g. `await self.dhara.get(...)`) or import a configured binding into
# `dhara.get` at integration time. Tests substitute via
# `monkeypatch.setattr("workflow_tools.dhara.get", ...)`; the hasattr
# guard lets that patch land even when the host package has not injected
# a binding.
if not hasattr(dhara, "get"):
    dhara.get = None  # type: ignore[attr-defined]


def workflow_get_outcome(workflow_id: str) -> WorkflowOutcome | None:
    """Read back the persisted WorkflowOutcome via from_dict, validating the payload.

    Returns ``None`` when no record exists at ``workflow-results/{workflow_id}/``.
    """
    payload = dhara.get(f"workflow-results/{workflow_id}/")
    if payload is None:
        return None
    return from_dict("workflow_outcome", payload)
