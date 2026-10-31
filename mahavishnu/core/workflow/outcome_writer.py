"""Workflow outcome writer — validate-on-write at completion boundary.

Persists ``workflow_outcome`` records to the in-process substrate at
``workflow-results/{workflow_id}/``. Validation happens at the completion
boundary so bad payloads never reach the durable store.

Substrate contract: writes go through the in-process substrate facade
(:mod:`mahavishnu.core.substrate`), whose ``put`` is synchronous because
this producer is a sync function — a sync write cannot be an HTTP
round-trip without blocking the event loop. The facade lands the payload
in the server's own process-local KV store
(:mod:`mahavishnu.core.kv_store`), the same store the
``mahavishnu_kv_*`` tools expose, so a sibling component reading the key
sees the record. The facade is always bound: there is no optional
dependency to degrade against, so every write lands.

Feature flag: ``WORKFLOW_OUTCOME_V1_ENABLED`` (default True). When False, the
caller is expected to skip ``record_workflow_outcome`` entirely and fall
back to the legacy non-durable completion path.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import msgspec
from oneiric.core.logging import get_logger

from mahavishnu.core import substrate  # req: REQ-SUBSTR-001
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


def record_workflow_outcome(  # req: REQ-SUBSTR-003
    workflow_id: str,
    status: str,
    started_at: datetime,
    finished_at: datetime,
    metadata: dict[str, object] | None = None,
) -> WorkflowOutcome:
    """Validate the outcome payload, persist via the substrate, return the typed struct."""
    payload = {
        "workflow_id": workflow_id,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "metadata": metadata or {},
    }
    validated: WorkflowOutcome = msgspec.convert(payload, WorkflowOutcome)  # ty: ignore[invalid-assignment]

    # The substrate is this server's own in-process store, so it is always
    # bound: there is no "substrate missing" state left to keep distinct
    # from "not written". The module is imported (not the function) so
    # tests can substitute it via `monkeypatch.setattr(
    # "mahavishnu.core.workflow.outcome_writer.substrate", ...)`.
    COUNTERS.attempted.labels(producer=_PRODUCER_NAME).inc()
    if substrate.put(f"workflow-results/{workflow_id}/", validated):
        COUNTERS.succeeded.labels(producer=_PRODUCER_NAME).inc()
    else:
        # The record did not land. Report it as skipped rather than
        # succeeded — a workflow-outcome log that silently lost an
        # outcome is an audit gap, and the counter plus the warning are
        # what make it detectable.
        COUNTERS.skipped.labels(producer=_PRODUCER_NAME).inc()
        logger.warning(
            "workflow_outcome_persistence_skipped",
            extra={
                "workflow_id": workflow_id,
                "reason": "substrate_write_failed",
            },
        )
    logger.info(
        "workflow_outcome_recorded",
        extra={
            "workflow_id": workflow_id,
            "status": validated.status,
            "v1_enabled": os.environ.get("WORKFLOW_OUTCOME_V1_ENABLED", "true"),
        },
    )
    return validated
