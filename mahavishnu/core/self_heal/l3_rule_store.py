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

Security note: ``extract_rule`` defensively scrubs credential-shaped
patterns from exception messages before persisting them or feeding
them into the deterministic ``rule_id`` hash. This is a best-effort
safety net; callers should still pass already-sanitised context. See
``_scrub_message`` for the recognised patterns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
import time
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

# Upper bound on the persisted message length. Defends against
# log-bombing via pathological exceptions and bounds memory/storage cost.
_MAX_MESSAGE_LENGTH: int = 1024

# Credential-shaped patterns we redact from free-form exception messages.
# Each pattern replaces the matched value with ``[REDACTED]``. Patterns
# are intentionally case-insensitive and overlap-friendly; ordering does
# not matter because each match is replaced individually.
_CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    # GitHub tokens: ghp_, gho_, ghs_, ghu_, ghr_ followed by 36+ alnum chars
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b", re.IGNORECASE),
    # GitLab personal access tokens
    re.compile(r"\bglpat-[A-Za-z0-9_\-]{16,}\b", re.IGNORECASE),
    # AWS access key IDs and STS session tokens
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{12,}\b"),
    # JWT-shaped header.payload.signature triples
    re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),
    # Bearer tokens (consume the value but leave the literal "Bearer " marker)
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{8,}"),
    # Generic key=value credentials: token=, api_key=, password=, secret=
    re.compile(
        r"(?i)\b(?:token|api_key|apikey|access_token|refresh_token|password|passwd|secret)\s*=\s*"
        r"[^\s,;'\"&<>]{4,}"
    ),
    # basic-auth user:password@ in URLs
    re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s/:@]+:[^\s@]+@"),
)

_REDACTED = "[REDACTED]"


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
            The message is scrubbed defensively before persistence and
            before being mixed into the ``rule_id`` hash so credential
            leaks in exception text cannot reach the audit log.
        context: optional structured context. Sensitive keys (tokens,
            passwords) are scrubbed defensively before persistence,
            including nested dict/list values whose key matches the
            sensitive set.
        created_at: optional timestamp (seconds). Defaults to
            ``time.time()``; explicit override exists so tests are
            deterministic.

    Returns:
        A ``RuleRecord`` whose ``rule_id`` is a stable hash of
        ``(operation, error_type, scrubbed_message)``. Duplicate
        failures dedupe.
    """
    scrubbed = _scrub_context(context or {})
    error_type = type(exception).__name__
    raw_message = str(exception)
    message = _scrub_message(raw_message)
    message = _cap_message(message)
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
    """Drop sensitive keys at every nesting level.

    Walks the structure recursively. At each mapping, keys whose
    lower-cased form is in ``_SENSITIVE_CONTEXT_KEYS`` are replaced with
    ``[REDACTED]`` (so the structure survives for debugging while the
    value never reaches storage). For lists/tuples each element is
    walked in turn.
    """
    return _scrub_value(context)


def _scrub_value(value: Any) -> Any:
    """Recursively scrub sensitive keys from mappings / sequences."""
    if isinstance(value, dict):
        scrubbed: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in _SENSITIVE_CONTEXT_KEYS:
                scrubbed[k] = _REDACTED
            else:
                scrubbed[k] = _scrub_value(v)
        return scrubbed
    if isinstance(value, (list, tuple)):
        return [_scrub_value(item) for item in value]
    return value


def _scrub_message(message: str) -> str:
    """Redact credential-shaped patterns from a free-form string.

    Best-effort safety net. Recognises:

    - GitHub tokens (ghp_, gho_, ghs_, ghu_, ghr_)
    - GitLab personal access tokens (glpat-...)
    - AWS access key IDs (AKIA / ASIA prefixes)
    - JWT-shaped ``header.payload.signature`` triples
    - ``Bearer <token>``
    - ``key=value`` for token / api_key / password / secret
    - basic-auth ``user:password@host`` in URLs
    """
    scrubbed = message
    for pattern in _CREDENTIAL_PATTERNS:
        scrubbed = pattern.sub(_REDACTED, scrubbed)
    return scrubbed


def _cap_message(message: str) -> str:
    """Bound the persisted message length to defend against log-bombing."""
    if len(message) <= _MAX_MESSAGE_LENGTH:
        return message
    return message[: _MAX_MESSAGE_LENGTH - 3] + "..."


def _compute_rule_id(operation: str, error_type: str, message: str) -> str:
    """Stable 16-hex-char id derived from the failure signature."""
    payload = f"{operation}\x00{error_type}\x00{message}".encode()
    return hashlib.sha256(payload).hexdigest()[:16]
