"""Reviewer identity trust root for the Plan 5 distillation pipeline.

Plan 5 audit finding H6: the distiller trusted whichever string was in
``$MAHAVISHNU_USER_ID`` at the shell layer with no root of trust. Anyone
who could set that environment variable could publish distilled
workflows.

This module introduces a :class:`ReviewerIdentity` value object that:

- Reads ``MAHAVISHNU_USER_ID`` as the canonical reviewer identity.
- Cross-checks it against ``MAHAVISHNU_PUBLISHER_ALLOWLIST`` (a path to
  a newline-delimited allowlist file, OR a comma-separated inline list).
- Returns a structured :class:`ReviewerDecision` describing whether the
  identity is trusted and why.
- Emits a WARNING + audit log entry when no allowlist is configured
  (bootstrap mode). Operators must add an allowlist before promoting
  distillers out of single-tenant development.
- Reserves a path for signed-token verification from a future trust
  root (placeholder only — current implementation always returns
  ``ReviewerSource.NONE`` for that branch).

A CLI flag (e.g. ``--reviewer``) is intentionally NOT a substitute for
the env var. The env var wins; the CLI flag is recorded on the decision
for forensic visibility but never authorizes publication.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from mahavishnu.core.errors import ReviewerNotTrusted

logger = logging.getLogger(__name__)


class ReviewerSource(str, Enum):
    """How a :class:`ReviewerDecision` resolved trust.

    ``ENV_ALLOWLIST`` — env var present and listed in allowlist (HAPPY).
    ``BOOTSTRAP`` — env var present, allowlist missing (WARN + audit).
    ``SIGNED_TOKEN`` — reserved for future RBAC token verification.
    ``NONE`` — no usable identity source.
    """

    ENV_ALLOWLIST = "env_allowlist"
    BOOTSTRAP = "bootstrap"
    SIGNED_TOKEN = "signed_token"
    NONE = "none"


@dataclass(frozen=True)
class ReviewerDecision:
    """Frozen outcome of a :class:`ReviewerIdentity.check` call.

    Attributes:
        allowed: True iff the distiller may proceed with publication.
        source: How trust was (or was not) established.
        reviewer_id: The identity that will be recorded as the publisher.
        cli_reviewer: Optional CLI-supplied reviewer (recorded but
            NEVER authoritative — env wins).
        reason: Human-readable explanation (empty when allowed=True via
            env+allowlist).
    """

    allowed: bool
    source: ReviewerSource
    reviewer_id: str | None
    cli_reviewer: str | None
    reason: str = ""


@dataclass(frozen=True)
class ReviewerIdentity:
    """A reviewer identity captured from the environment at a moment in time.

    Use :meth:`from_env` to construct from the current process env, or
    pass an explicit ``env`` mapping for testing. The captured values
    are immutable so :meth:`check` is pure.
    """

    env_user_id: str | None
    allowlist_spec: str | None
    cli_reviewer: str | None = None
    # Internal: parsed allowlist lines (None when allowlist missing/invalid)
    _allowlist: frozenset[str] | None = field(
        default=None,
        compare=False,
        repr=False,
    )

    # ------------------------------------------------------------------ env

    @classmethod
    def from_env(
        cls,
        *,
        env: Mapping[str, str] | None = None,
        cli_reviewer: str | None = None,
    ) -> ReviewerIdentity:
        """Capture reviewer identity from process environment.

        Args:
            env: Optional env override (defaults to ``os.environ``).
                Test-only escape hatch.
            cli_reviewer: Optional CLI flag value (recorded, NOT authoritative).
        """
        if env is None:
            env = os.environ
        return cls(
            env_user_id=env.get("MAHAVISHNU_USER_ID") or None,
            allowlist_spec=env.get("MAHAVISHNU_PUBLISHER_ALLOWLIST") or None,
            cli_reviewer=cli_reviewer,
        )

    # -------------------------------------------------------------- check

    def check(self) -> ReviewerDecision:
        """Evaluate trust without raising.

        Returns a :class:`ReviewerDecision`. Callers that need to abort
        publication on denial should use :meth:`enforce` instead.
        """
        env_user_id = (self.env_user_id or "").strip()
        cli_reviewer = self.cli_reviewer

        # No env var → no trust root at all
        if not env_user_id:
            return ReviewerDecision(
                allowed=False,
                source=ReviewerSource.NONE,
                reviewer_id=None,
                cli_reviewer=cli_reviewer,
                reason=(
                    "MAHAVISHNU_USER_ID env var is not set; cannot establish "
                    "a reviewer trust root. A CLI flag alone is insufficient "
                    "(env wins)."
                ),
            )

        allowlist = self._load_allowlist()

        # Allowlist missing → bootstrap mode (allow with WARNING)
        if allowlist is None:
            msg = (
                f"MAHAVISHNU_PUBLISHER_ALLOWLIST not configured; allowing "
                f"reviewer {env_user_id!r} under bootstrap mode. Configure an "
                f"allowlist before promoting distillers to multi-tenant use."
            )
            logger.warning(msg, extra={"reviewer_id": env_user_id})
            return ReviewerDecision(
                allowed=True,
                source=ReviewerSource.BOOTSTRAP,
                reviewer_id=env_user_id,
                cli_reviewer=cli_reviewer,
                reason=msg,
            )

        # Allowlist present → strict membership check
        if env_user_id in allowlist:
            return ReviewerDecision(
                allowed=True,
                source=ReviewerSource.ENV_ALLOWLIST,
                reviewer_id=env_user_id,
                cli_reviewer=cli_reviewer,
                reason="",
            )

        return ReviewerDecision(
            allowed=False,
            source=ReviewerSource.ENV_ALLOWLIST,
            reviewer_id=env_user_id,
            cli_reviewer=cli_reviewer,
            reason=(
                f"Reviewer {env_user_id!r} is not in the configured "
                f"MAHAVISHNU_PUBLISHER_ALLOWLIST."
            ),
        )

    # ------------------------------------------------------------ enforce

    def enforce(self) -> ReviewerDecision:
        """Evaluate trust, raising :class:`ReviewerNotTrusted` if denied.

        Returns the decision when allowed, so callers can chain
        ``enforce()`` then proceed with publication.

        Raises:
            ReviewerNotTrusted: when ``check().allowed`` is False.
        """
        decision = self.check()
        if not decision.allowed:
            raise ReviewerNotTrusted(
                decision.reason,
                reviewer_id=decision.reviewer_id or self.env_user_id,
            )
        return decision

    # ----------------------------------------------------------- audit log

    def emit_audit_log(self, decision: ReviewerDecision) -> None:
        """Emit an audit log entry tagged with ``extra={"audit": True}``.

        Audit logs are distinguishable from operational logs so the
        Dhara event bus can ingest them via the audit_log subscriber
        without confusing them with informational messages.
        """
        level = logging.INFO if decision.allowed else logging.WARNING
        logger.log(
            level,
            "reviewer_identity.decision reviewer=%s allowed=%s source=%s "
            "cli_reviewer=%s reason=%s",
            decision.reviewer_id,
            decision.allowed,
            decision.source.value,
            decision.cli_reviewer,
            decision.reason,
            extra={
                "audit": True,
                "reviewer_id": decision.reviewer_id,
                "cli_reviewer": decision.cli_reviewer,
                "decision_source": decision.source.value,
                "decision_allowed": decision.allowed,
            },
        )

    # ----------------------------------------------------------- helpers

    def _load_allowlist(self) -> frozenset[str] | None:
        """Parse MAHAVISHNU_PUBLISHER_ALLOWLIST into a frozenset of usernames.

        Returns ``None`` when the env var is unset, empty, or points at
        a missing path. Returns the parsed set otherwise. Inline CSV
        values are supported for convenience.
        """
        spec = (self.allowlist_spec or "").strip()
        if not spec:
            return None

        # If it looks like a path (starts with / or ./ or ../ or has a
        # path separator), try to read it. Otherwise treat as inline CSV.
        if "/" in spec or spec.startswith("."):
            path = Path(spec).expanduser()
            if not path.is_file():
                return None
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                return None
            tokens = text.replace(",", "\n").splitlines()
        else:
            tokens = spec.split(",")

        names = frozenset(t.strip() for t in tokens if t.strip())
        return names or None


__all__ = [
    "ReviewerDecision",
    "ReviewerIdentity",
    "ReviewerSource",
]
