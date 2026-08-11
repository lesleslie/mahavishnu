"""Approval CLI helpers — consumer read-back of ApprovalLog records.

Provides :func:`list_approval_history`, which reads persisted payloads from the
Dhara substrate and returns validated :class:`ApprovalLog` structs. The
producer counterpart is :func:`mahavishnu.core.approval.decision_writer.record_approval_decision`.

Substrate-compat: ``dhara.list`` is not part of the static substrate API on
the local install. The module stamps it to ``None`` at import time if absent;
tests (and any future Dhara substrate builds that expose ``list``) can
monkeypatch ``approval_cli.dhara.list`` to a callable.
"""

from __future__ import annotations

from typing import Any

import dhara
from dhara.schema import ApprovalLog, SchemaValidationError, from_dict
from oneiric.core.logging import get_logger

from mahavishnu.mcp.tools._workflow_id_guard import validate_approval_id

logger = get_logger(__name__)

# Substrate-compat: dhara.list is not part of the static substrate API on
# the local install. Tests monkeypatch this attribute; production builds
# that expose dhara.list will see a real callable at runtime.
if not hasattr(dhara, "list"):  # pragma: no cover - substrate introspection
    dhara.list = None  # type: ignore[attr-defined]


def list_approval_history(
    approval_id: str,
    since: str | None,
    status: str | None,
    token: str | None = None,
) -> list[ApprovalLog]:
    """Read persisted ApprovalLog payloads for ``approval_id`` from Dhara.

    Args:
        approval_id: Stable ID of the approval request whose history to read.
        since: Optional ISO-8601 timestamp lower bound, forwarded to Dhara.
        status: Optional status filter, forwarded to Dhara.
        token: Optional bearer token. The CLI surface is sync, so the
            check is a JWT-shape presence gate (mirrors the
            ``@require_auth`` contract on the MCP surface): missing or
            non-JWT-shaped tokens are rejected. Full user→role→permission
            mapping is enforced at the async dispatch boundary in
            production; here we block the read before any Dhara call so
            the leaf function can never be exercised without auth.

    Returns:
        A list of validated :class:`ApprovalLog` structs. Invalid payloads
        are skipped (partial-failure resilience) rather than raising, so a
        single corrupted record does not mask the rest of the history.
        Returns an empty list and emits a WARNING when the substrate does
        not expose ``dhara.list``, when ``approval_id`` fails the
        path-traversal allowlist check, or when ``token`` is missing or
        not a JWT-shaped triple.
    """
    # RBAC gate: READ_APPROVAL required (multi-agent review HIGH finding).
    # CLI surface is sync — JWT-shape presence check is the local contract;
    # full RBACManager.check_permission runs at the dispatch boundary.
    if not token or len(token.split(".")) != 3:
        logger.warning(
            "approval_list_skipped",
            extra={
                "approval_id": approval_id,
                "reason": "rbac_denied",
            },
        )
        return []

    # Path-traversal guard: ``approval_id`` is spliced into the Dhara key
    # ``f"approval-history/{approval_id}/"`` below. Reject caller-supplied
    # values that contain traversal characters BEFORE the substrate sees
    # them. Matches the existing convention for the substrate-unbound
    # case (log warning, return []) so callers see a single error shape.
    if not validate_approval_id(approval_id):
        logger.warning(
            "approval_list_skipped",
            extra={
                "approval_id": approval_id,
                "reason": "invalid_approval_id",
            },
        )
        return []

    list_fn = getattr(dhara, "list", None)
    if list_fn is None:
        logger.warning(
            "approval_list_skipped",
            extra={
                "approval_id": approval_id,
                "reason": "dhara.list_unbound",
            },
        )
        return []

    raw_payloads: list[dict[str, Any]] = list_fn(
        f"approval-history/{approval_id}/",
        since=since,
        status=status,
    )

    results: list[ApprovalLog] = []
    for payload in raw_payloads:
        try:
            record: ApprovalLog = from_dict("approval_log", payload)
        except SchemaValidationError as exc:
            # Skip-bad not raise-all: partial-failure resilience so a single
            # corrupted entry does not mask the rest of the history. Log the
            # bound exception's type — never the message, which may carry
            # credentials or connection strings.
            logger.warning(
                "approval_list_entry_skipped",
                extra={
                    "approval_id": approval_id,
                    "reason": type(exc).__name__,
                },
            )
            continue
        results.append(record)
    return results
