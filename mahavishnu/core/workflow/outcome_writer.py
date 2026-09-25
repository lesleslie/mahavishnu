"""Workflow outcome writer — validate-on-write at completion boundary.

Persists ``workflow_outcome`` records to the Bodai MCP substrate at
``workflow-results/{workflow_id}/``. Validation happens at the completion
boundary so bad payloads never reach the durable store.

Substrate contract: ``mcp.put(...)`` is synchronous at the call boundary.
The substrate's internal handling (MemoryOutbox queue, async flush) is
opaque to callers. This producer is sync by design — see
``mcp/docs/superpowers/specs/2026-08-10-substrate-call-boundary-contract.md``
for the cross-portfolio rationale.

Feature flag: ``WORKFLOW_OUTCOME_V1_ENABLED`` (default True). When False, the
caller is expected to skip ``record_workflow_outcome`` entirely and fall
back to the legacy non-durable completion path.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import msgspec
from oneiric.core.logging import get_logger

from mahavishnu.core._mcp_substrate_compat import mcp_calltime
from mahavishnu.core._producer_metrics import COUNTERS
from mahavishnu.core.models.persistence import WorkflowOutcome

if TYPE_CHECKING:
    from datetime import datetime

# Producer name used for Prometheus label cardinality.
_PRODUCER_NAME = "workflow_outcome_writer"

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
    """Validate the outcome payload, persist via mcp.put, return the typed struct."""
    payload = {
        "workflow_id": workflow_id,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "metadata": metadata or {},
    }
    validated: WorkflowOutcome = msgspec.convert(payload, WorkflowOutcome)  # ty: ignore[invalid-assignment]

    # Substrate-compat gate: only persist when mcp.put is exposed.
    put = mcp_calltime("put")
    COUNTERS.attempted.labels(producer=_PRODUCER_NAME).inc()
    if put is not None:
        put(f"workflow-results/{workflow_id}/", validated)
        COUNTERS.succeeded.labels(producer=_PRODUCER_NAME).inc()
        logger.info(
            "workflow_outcome_recorded",
            extra={
                "workflow_id": workflow_id,
                "status": validated.status,
                "v1_enabled": os.environ.get("WORKFLOW_OUTCOME_V1_ENABLED", "true"),
            },
        )
    else:
        COUNTERS.skipped.labels(producer=_PRODUCER_NAME).inc()
        logger.warning(
            "workflow_outcome_persistence_skipped",
            extra={
                "workflow_id": workflow_id,
                "reason": "mcp.put_unbound",
                "v1_enabled": os.environ.get("WORKFLOW_OUTCOME_V1_ENABLED", "true"),
            },
        )
    return validated
