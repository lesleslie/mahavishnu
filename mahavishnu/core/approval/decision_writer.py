"""Approval decision writer — validate-on-write at decision boundary.

Persists :class:`dhara.schema.ApprovalLog` records to Dhara at
``approval-history/{approval_id}/``. Validation happens at the decision
boundary so bad payloads never reach the durable store.

Feature flag: ``APPROVAL_LOG_V1_ENABLED`` (default True). When False, the
caller is expected to skip ``record_approval_decision`` entirely and fall
back to the legacy delete-on-resolve path.

Substrate-compat: ``dhara.put`` is a runtime-attached attribute on the
local substrate install, so the module stamps it to ``None`` at import
time if absent. Tests (and any future Dhara substrate builds that expose
``put``) can monkeypatch ``writer.dhara.put`` to a callable.

Substrate contract: ``dhara.put(...)`` is synchronous at the call boundary —
internal async (MemoryOutbox flush, PostgresBackendLock resolution) is the
substrate's concern, not the caller's. See
``dhara/docs/superpowers/specs/2026-08-10-substrate-call-boundary-contract.md``
for the full architectural decision.
"""

from __future__ import annotations

from datetime import UTC, datetime
import os
from typing import Any

import dhara
from dhara.schema import ApprovalLog, validate
from oneiric.core.logging import get_logger

logger = get_logger(__name__)

# Substrate-compat: dhara.put is not part of the static substrate API on
# the local install. Tests monkeypatch this attribute; production builds
# that expose dhara.put will see a real callable at runtime.
if not hasattr(dhara, "put"):  # pragma: no cover - substrate introspection
    dhara.put = None  # type: ignore[attr-defined]


def record_approval_decision(
    approval_id: str,
    decision: str,
    rationale: str,
    decided_by: str,
    metadata: dict[str, Any] | None = None,
) -> ApprovalLog:
    """Validate the approval decision payload and persist via ``dhara.put``.

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
        dhara.schema.SchemaValidationError: If ``decision`` is not in the
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

    validated: ApprovalLog = validate("approval_log", payload)

    # Substrate-compat gate: only persist when dhara.put is exposed.
    put = getattr(dhara, "put", None)
    if put is not None:
        put(f"approval-history/{approval_id}/", validated)
    else:
        logger.warning(
            "approval_log_persistence_skipped",
            extra={
                "approval_id": approval_id,
                "reason": "dhara.put_unbound",
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
