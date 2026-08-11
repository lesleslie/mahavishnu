"""Workflow outcome writer — validate-on-write at completion boundary."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import dhara
from dhara.schema import WorkflowOutcome, validate
from oneiric.core.logging import get_logger

if TYPE_CHECKING:
    from datetime import datetime

# Substrate-compat: `dhara.put` is not a module-level attribute on the
# installed dhara package — real callers pass a Dhara client instance
# (e.g. `await self.dhara.put(...)`) or import a configured binding into
# `dhara.put` at integration time. Tests substitute via
# `monkeypatch.setattr("writer.dhara.put", ...)`; the hasattr guard lets
# that patch land even when the host package has not injected a binding.
if not hasattr(dhara, "put"):
    dhara.put = None  # type: ignore[attr-defined]

logger = get_logger(__name__)


def _workflow_outcome_v1_enabled() -> bool:
    """Read the WORKFLOW_OUTCOME_V1_ENABLED env var (default 'true').

    Mirrors ``_approval_log_v1_enabled`` at
    ``mahavishnu/core/approval_manager.py:22-30``. Used at the call site
    (``workflow_execution.py:finalize_workflow_execution``) so this producer
    itself does not need to consult the flag.
    """
    return os.environ.get("WORKFLOW_OUTCOME_V1_ENABLED", "true").lower() != "false"


def record_workflow_outcome(
    workflow_id: str,
    status: str,
    started_at: datetime,
    finished_at: datetime,
    metadata: dict[str, object] | None = None,
) -> WorkflowOutcome:
    """Validate the outcome payload, persist via dhara.put, return the typed struct."""
    payload = {
        "workflow_id": workflow_id,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "metadata": metadata or {},
    }
    validated = validate("workflow_outcome", payload)

    # Substrate-compat gate: only persist when dhara.put is exposed.
    put = getattr(dhara, "put", None)
    if put is not None:
        put(f"workflow-results/{workflow_id}/", validated)
        logger.info(
            "workflow_outcome_recorded",
            extra={
                "workflow_id": workflow_id,
                "status": validated.status,
                "v1_enabled": os.environ.get("WORKFLOW_OUTCOME_V1_ENABLED", "true"),
            },
        )
    else:
        logger.warning(
            "workflow_outcome_persistence_skipped",
            extra={
                "workflow_id": workflow_id,
                "reason": "dhara.put_unbound",
                "v1_enabled": os.environ.get("WORKFLOW_OUTCOME_V1_ENABLED", "true"),
            },
        )
    return validated
