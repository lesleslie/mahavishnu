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

Authorization: the read is performed **as the caller**, never as the
internal self-call principal. The caller's bearer token is verified
locally against the configured JWT secret — signature and expiry — and
the resulting user id is the principal the server applies RBAC to. A
JWT-*shaped* string is not a credential: the retired substrate's
presence check accepted ``"a.b.c"`` from anyone, and reading the
approval history under the internal principal would have let any caller
who reached this function read every decision.

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


def _verify_caller(token: str | None) -> str | None:
    """Verify the caller's bearer token and return the user id it names.

    The token is verified against the configured JWT secret — signature
    and expiry — so a forged or expired token yields no identity and the
    read is refused. This is what separates a credential from a claim:
    the retired substrate's JWT-shape presence check accepted any
    three-segment string.

    Returns:
        The verified ``user_id``, or ``None`` when the token is missing,
        not a token this server signed, expired, or carries no user id.
    """
    if not token:
        logger.warning("approval_list_skipped", extra={"reason": "missing_token"})
        return None
    try:
        from mahavishnu.core.config import get_settings
        from mahavishnu.core.permissions import JWTManager

        payload = JWTManager(get_settings()).verify_token(token)
    except Exception as exc:  # noqa: BLE001 — a bad token is a refusal, not a crash
        # The exception *type* only — the message can carry the token.
        logger.warning(
            "approval_list_skipped",
            extra={"reason": type(exc).__name__},
        )
        return None
    user_id = payload.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        logger.warning("approval_list_skipped", extra={"reason": "token_without_user_id"})
        return None
    return user_id


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
        token: Optional bearer token. It is **verified** against the
            configured JWT secret; the user id it names is the principal
            the server applies RBAC to, and the read requires that
            principal to hold the approval-read permission. A missing,
            malformed, expired or unsigned token is refused.

    Returns:
        A list of validated :class:`ApprovalLog` structs. Invalid payloads
        are skipped (partial-failure resilience) rather than raising, so a
        single corrupted record does not mask the rest of the history.
        Returns an empty list and emits a WARNING when the token cannot be
        verified, when the substrate cannot be reached, when
        ``approval_id`` fails the path-traversal allowlist check, or when
        the server denies the read.
    """
    # Authorization: verify the caller's credential before anything else.
    # The server denies the read when the principal lacks the permission,
    # and the empty result is logged distinctly (``approval_list_denied``)
    # so a refusal is distinguishable from "no history".
    user_id = _verify_caller(token)
    if user_id is None:
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
    # empty, one. The read is performed as the *caller*, not as the
    # internal self-call principal: the KV tools apply the permission
    # that owns the ``approval-history/`` namespace.
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

    client = MCPClient(base_url=base_url, token=token)
    try:
        pairs = await client.kv_list(f"approval-history/{approval_id}/", user_id=user_id)
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
        # Defence in depth: the record must belong to the approval the
        # caller asked about, whatever the store says.
        if record.approval_id != approval_id:
            logger.warning(
                "approval_list_entry_skipped",
                extra={
                    "approval_id": approval_id,
                    "reason": "approval_id_mismatch",
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
