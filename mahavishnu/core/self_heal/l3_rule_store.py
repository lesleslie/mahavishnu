"""L3 rule extraction and RuleStore (Spec #4, Phase 2).

When an operation ultimately fails (after L1 retries and any L2
intervention), L3 summarises the failure into a ``RuleRecord`` and
records it for future reference. Future heals can consult the rule store
to skip operations known to fail (e.g. a documented ``git push`` rebase
conflict on a protected branch).

Substrate status: ``sql_blocked``. v0 is an in-memory store. When the
``self_heal_audit_log`` Dhara table is unblocked, swap ``RuleStore``
for a Dhara-backed implementation that satisfies the same interface
(``records``, ``record_rule``, ``apply_rule``).

Rule ID contract: ``extract_rule`` returns deterministic IDs derived
from ``(operation, error_type, scrubbed_message)`` so duplicate failures
dedupe naturally. Callers may override by passing an explicit
``rule_id`` on the ``RuleRecord`` constructor.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

# Keys that must never be persisted in a rule's context. Defensive
# default for accidental leak via catch-all ``locals()``-style callers.
_SENSITIVE_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        "authorization",
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "cookie",
        "set_cookie",
    }
)


@dataclass(frozen=True)
class RuleRecord:
    """One L3 audit-log entry recording a known failure.

    Frozen for the same reasons as ``SkillTransition`` in the
    three-zone pipeline (Spec #5): the audit log is append-only and
    history is preserved.
    """

    rule_id: str
    operation: str
    error_type: str
    message: str
    context: dict[str, Any]
    created_at: float


@dataclass
class RuleStore:
    """In-memory v0 audit log. Dhara wiring follows.

    ``records`` is the underlying list, ordered by insertion. ``RuleStore``
    is not thread-safe; concurrent access is the orchestrator's problem
    (and unnecessary in single-process async workflows).
    """

    records: list[RuleRecord] = field(default_factory=list)

    def rules_for(self, operation: str) -> list[RuleRecord]:
        """All rules matching ``operation``, in insertion order."""
        return [r for r in self.records if r.operation == operation]


def extract_rule(
    operation: str,
    exception: BaseException,
    context: dict[str, Any] | None = None,
    *,
    created_at: float | None = None,
) -> RuleRecord:
    """Summarise a failure into a ``RuleRecord``.

    Args:
        operation: stable operation name (e.g. ``"git_push"``).
        exception: the underlying failure. ``type(exception).__name__``
            becomes ``error_type``; ``str(exception)`` becomes ``message``.
        context: optional structured context. Sensitive keys (tokens,
            passwords) are scrubbed defensively before persistence.
        created_at: optional timestamp (seconds). Defaults to
            ``time.time()``; explicit override exists so tests are
            deterministic.

    Returns:
        A ``RuleRecord`` whose ``rule_id`` is a stable hash of
        ``(operation, error_type, message)``. Duplicate failures dedupe.
    """
    scrubbed = _scrub_context(context or {})
    error_type = type(exception).__name__
    message = str(exception)
    rule_id = _compute_rule_id(operation, error_type, message)
    return RuleRecord(
        rule_id=rule_id,
        operation=operation,
        error_type=error_type,
        message=message,
        context=scrubbed,
        created_at=created_at if created_at is not None else time.time(),
    )


def record_rule(store: RuleStore, rule: RuleRecord) -> None:
    """Append ``rule`` to ``store`` unless an entry with the same id exists.

    Idempotent: repeated calls with the same ``rule_id`` are no-ops. This
    is what makes duplicate failures (same op, same exception class, same
    message) collapse into a single audit row.
    """
    if any(r.rule_id == rule.rule_id for r in store.records):
        return
    store.records.append(rule)


def apply_rule(store: RuleStore, operation: str) -> RuleRecord | None:
    """Return the most recent rule for ``operation``, or ``None``.

    "Most recent" is by ``created_at`` descending. If multiple rules
    share the same timestamp the one inserted later wins (stable
    secondary order).
    """
    candidates = store.rules_for(operation)
    if not candidates:
        return None
    return max(candidates, key=lambda r: (r.created_at, candidates.index(r)))


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _scrub_context(context: dict[str, Any]) -> dict[str, Any]:
    """Drop sensitive keys; preserve everything else verbatim."""
    return {k: v for k, v in context.items() if k.lower() not in _SENSITIVE_CONTEXT_KEYS}


def _compute_rule_id(operation: str, error_type: str, message: str) -> str:
    """Stable 16-hex-char id derived from the failure signature."""
    payload = f"{operation}\x00{error_type}\x00{message}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]