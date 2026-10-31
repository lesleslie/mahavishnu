"""Approval decision writer — validate-on-write at decision boundary.

Persists :class:`mahavishnu.core.models.persistence.ApprovalLog` records
to the in-process substrate under the ``approval-history/{approval_id}/``
namespace. Validation happens at the decision boundary so bad payloads
never reach the durable store.

Append-only history: the store holds **one value per key**, so each
decision is written under its own key inside the approval's namespace —
``approval-history/{approval_id}/{timestamp}-{nonce}`` — rather than
overwriting a shared key. The reader lists the namespace by prefix, so
every decision for an approval survives.

Feature flag: ``APPROVAL_LOG_V1_ENABLED`` (default True). When False, the
caller is expected to skip ``record_approval_decision`` entirely and fall
back to the legacy delete-on-resolve path.

Substrate contract: writes go through the in-process substrate facade
(:mod:`mahavishnu.core.substrate`), whose ``put`` is synchronous because
this producer is a sync function. The facade lands the payload in the
server's own process-local KV store (:mod:`mahavishnu.core.kv_store`),
the same store the ``mahavishnu_kv_*`` tools expose, so a sibling
component reading the key sees the record. The facade is always bound:
there is no optional dependency to degrade against, so every write lands
and no "substrate unavailable" branch exists.
"""

from __future__ import annotations

from datetime import UTC, datetime
import os
from typing import Any
import uuid

import msgspec
from oneiric.core.logging import get_logger

from mahavishnu.core import substrate  # req: REQ-SUBSTR-001
from mahavishnu.core._producer_metrics import COUNTERS
from mahavishnu.core.models.persistence import ApprovalLog

logger = get_logger(__name__)

# Producer name used for Prometheus label cardinality.
_PRODUCER_NAME = "decision_writer"


def _history_key(approval_id: str, at: datetime) -> str:
    """Build the store key for one approval decision.

    The key lives inside the ``approval-history/{approval_id}/`` namespace
    the reader lists by prefix, and carries a sortable timestamp plus a
    random nonce so two decisions never collide on one key — the store
    holds a single value per key, so a shared key would make the history
    overwrite instead of append.
    """
    stamp = at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"approval-history/{approval_id}/{stamp}-{uuid.uuid4().hex[:8]}"


def record_approval_decision(  # req: REQ-SUBSTR-003
    approval_id: str,
    decision: str,
    rationale: str,
    decided_by: str,
    metadata: dict[str, Any] | None = None,
) -> ApprovalLog:
    """Validate the approval decision payload and persist via the substrate.

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

    # The substrate is this server's own in-process store, so it is always
    # bound: there is no "substrate missing" state left to keep distinct
    # from "not written". The module is imported (not the function) so
    # tests can substitute it via `monkeypatch.setattr(
    # "mahavishnu.core.approval.decision_writer.substrate", ...)`.
    #
    # The key is unique per decision so the history stays append-only: the
    # store is one-value-per-key, so a shared key would let a second
    # decision overwrite the first. The namespace prefix is what the
    # reader lists by.
    COUNTERS.attempted.labels(producer=_PRODUCER_NAME).inc()
    substrate.put(_history_key(approval_id, validated.at), validated)
    COUNTERS.succeeded.labels(producer=_PRODUCER_NAME).inc()

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
