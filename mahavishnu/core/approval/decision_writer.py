"""Approval decision writer — validate-on-write at decision boundary.

Persists :class:`mahavishnu.core.models.persistence.ApprovalLog` records
to MCP at ``approval-history/{approval_id}/``. Validation happens at
the decision boundary so bad payloads never reach the durable store.

Feature flag: ``APPROVAL_LOG_V1_ENABLED`` (default True). When False, the
caller is expected to skip ``record_approval_decision`` entirely and fall
back to the legacy delete-on-resolve path.

Substrate-compat: the module calls ``mcp_calltime("put")`` (a
lazy-load helper from ``mahavishnu.core._mcp_substrate_compat``) at
write time; the helper returns ``None`` when no MCP substrate is
installed, so persistence is silently skipped (logged + Prometheus
``skipped`` counter incremented). Tests patch
``decision_writer.mcp_calltime`` with a routing stub that returns the
fake ``put`` callable when asked for ``"put"``.

Substrate contract: ``mcp.put(...)`` is synchronous at the call boundary —
internal async (MemoryOutbox flush, PostgresBackendLock resolution) is the
substrate's concern, not the caller's. See
``mcp/docs/superpowers/specs/2026-08-10-substrate-call-boundary-contract.md``
for the full architectural decision.
"""

from __future__ import annotations

from datetime import UTC, datetime
import os
from typing import Any

import msgspec
from oneiric.core.logging import get_logger

from mahavishnu.core._mcp_substrate_compat import mcp_calltime
from mahavishnu.core._producer_metrics import COUNTERS
from mahavishnu.core.models.persistence import ApprovalLog

logger = get_logger(__name__)

# Producer name used for Prometheus label cardinality.
_PRODUCER_NAME = "decision_writer"


def record_approval_decision(
    approval_id: str,
    decision: str,
    rationale: str,
    decided_by: str,
    metadata: dict[str, Any] | None = None,
) -> ApprovalLog:
    """Validate the approval decision payload and persist via ``mcp.put``.

    Args:
        approval_id: Stable ID of the approval request being resolved.
        decision: One of ``"approved"``, ``"denied"``, ``"requested"`` — enforced
            by the substrate's Literal type.
        rationale: Human-readable explanation of the decision. Stored in the
            ``metadata.rationale`` field rather than a first-class field
            (the schema reserves the top level for typed queryability).
        decided_by: Actor (user or system) that produced the decision.
        metadata: Optional additional context to persist alongside the decision.

    Returns:
        The validated :class:`ApprovalLog` struct that was persisted.

    Raises:
        msgspec.ValidationError: If ``decision`` is not in the
            Literal type or any required field is malformed.
    """
    merged_metadata: dict[str, Any] = dict(metadata) if metadata else {}
    merged_metadata.setdefault("rationale", rationale)

    payload: dict[str, Any] = {
        "approval_id": approval_id,
        "action": decision,
        "actor": decided_by,
        "at": datetime.now(UTC),
        "metadata": merged_metadata,
    }

    validated: ApprovalLog = msgspec.convert(payload, ApprovalLog)  # ty: ignore[invalid-assignment]

    # Substrate-compat gate: only persist when mcp.put is exposed.
    put = mcp_calltime("put")
    COUNTERS.attempted.labels(producer=_PRODUCER_NAME).inc()
    if put is not None:
        put(f"approval-history/{approval_id}/", validated)
        COUNTERS.succeeded.labels(producer=_PRODUCER_NAME).inc()
    else:
        COUNTERS.skipped.labels(producer=_PRODUCER_NAME).inc()
        logger.warning(
            "approval_log_persistence_skipped",
            extra={
                "approval_id": approval_id,
                "reason": "mcp.put_unbound",
                "v1_enabled": os.environ.get("APPROVAL_LOG_V1_ENABLED", "true"),
            },
        )

    logger.info(
        "approval_log_recorded",
        extra={
            "approval_id": approval_id,
            "action": validated.action,
            "actor": validated.actor,
            "v1_enabled": os.environ.get("APPROVAL_LOG_V1_ENABLED", "true"),
        },
    )
    return validated
