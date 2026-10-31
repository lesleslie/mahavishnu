"""Approval CLI helpers — consumer read-back of ApprovalLog records.

Provides :func:`list_approval_history`, which reads persisted payloads from the
MCP substrate and returns validated :class:`ApprovalLog` structs. The
producer counterpart is :func:`mahavishnu.core.approval.decision_writer.record_approval_decision`.

Substrate: this reader is the one call site that runs **outside** the
server process — a CLI invocation is its own process, and the approval
records live in the server's process-local store. So it reads them
through the server's public KV surface over HTTP, the same way
:mod:`mahavishnu.metrics_cli` reads the substrate. The in-process
facade (:mod:`mahavishnu.core.substrate`) would answer from the CLI's
own — empty — store.

The retired substrate applied the ``since`` / ``status`` filters
server-side. The live KV surface lists by prefix only, so the filters
are applied here, on the returned payloads.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json

import msgspec
from oneiric.core.logging import get_logger

# req: REQ-SUBSTR-001
from mahavishnu.core.models.persistence import ApprovalLog
from mahavishnu.mcp.tools._workflow_id_guard import validate_approval_id

logger = get_logger(__name__)


def _parse_since(value: str | None) -> datetime | None:
    """Parse the ``since`` bound into a comparable datetime, or ``None``.

    A date-only bound (``"2026-08-01"``) is naive; the records it is
    compared against are timezone-aware, so a naive bound is read as
    UTC. A malformed bound is treated as "no lower bound" rather than an
    error — the caller asked for history, and a bad bound should widen
    the result rather than hide it.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        logger.warning("approval_list_since_unparsed", extra={"reason": "invalid_since"})
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


# req: REQ-SUBSTR-005
async def list_approval_history(
    approval_id: str,
    since: str | None,
    status: str | None,
    token: str | None = None,
) -> list[ApprovalLog]:
    """Read persisted ApprovalLog payloads for ``approval_id`` from MCP.

    Args:
        approval_id: Stable ID of the approval request whose history to read.
        since: Optional ISO-8601 timestamp lower bound. Applied to the
            returned records here — the live KV surface lists by prefix
            only.
        status: Optional status filter, matched against the record's
            ``action``. Applied here for the same reason.
        token: Optional bearer token. The check is a JWT-shape presence
            gate (mirrors the ``@require_auth`` contract on the MCP
            surface): missing or non-JWT-shaped tokens are rejected.
            Full user→role→permission mapping is enforced at the async
            dispatch boundary in production; here we block the read
            before any MCP call so the leaf function can never be
            exercised without auth.

    Returns:
        A list of validated :class:`ApprovalLog` structs. Invalid payloads
        are skipped (partial-failure resilience) rather than raising, so a
        single corrupted record does not mask the rest of the history.
        Returns an empty list and emits a WARNING when the substrate
        cannot be reached, when ``approval_id`` fails the path-traversal
        allowlist check, or when ``token`` is missing or not a
        JWT-shaped triple.
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

    # Path-traversal guard: ``approval_id`` is spliced into the MCP key
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

    # Read through the server's public KV surface. This process does not
    # host the substrate — the approval records live in the server's
    # store — so the in-process facade would answer from the CLI's own,
    # empty, one.
    from mahavishnu.core.bootstrap import resolve_mcp_url
    from mahavishnu.core.config import get_settings
    from mahavishnu.core.mcp_adapter import MCPClient

    try:
        base_url = resolve_mcp_url(get_settings())
    except Exception as exc:  # noqa: BLE001 — CLI entry point, broad catch is the contract
        logger.warning(
            "approval_list_skipped",
            extra={
                "approval_id": approval_id,
                "reason": type(exc).__name__,
            },
        )
        return []

    client = MCPClient(base_url=base_url, internal=True)
    try:
        pairs = await client.kv_list(f"approval-history/{approval_id}/")
    except Exception as exc:  # noqa: BLE001 — CLI entry point, broad catch is the contract
        logger.warning(
            "approval_list_skipped",
            extra={
                "approval_id": approval_id,
                "reason": type(exc).__name__,
            },
        )
        return []
    finally:
        await client.aclose()

    cutoff = _parse_since(since)

    results: list[ApprovalLog] = []
    for _key, raw in pairs:
        try:
            payload = json.loads(raw)
            record: ApprovalLog = msgspec.convert(payload, ApprovalLog)  # ty: ignore[invalid-assignment]
        except (json.JSONDecodeError, TypeError, msgspec.ValidationError) as exc:
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
        if cutoff is not None and record.at < cutoff:
            continue
        if status and record.action != status:
            continue
        results.append(record)
    # Chronological order regardless of the store's insertion order.
    results.sort(key=lambda record: record.at)
    return results
