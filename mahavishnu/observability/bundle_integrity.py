"""Bundle integrity verification (ADR 015 v4 §6).

Pure functions for SHA-256 hashing of worktree bundles. Used by
``LocalWorktreeProvider.fetch`` and ``RemoteWorktreeProvider.fetch`` to
verify bundle hash matches the ``WorktreeHandle.sha256`` field recorded
in the Dhara registry.

Mismatch raises ``WorktreeIntegrityError`` (subclass of ``WorktreeError``
per ``mahavishnu/core/errors.py``) and emits the
``bundle_integrity_failure_total`` counter via
``mahavishnu.observability.metrics``.
"""

from __future__ import annotations

from hashlib import sha256
import logging
from typing import Final

from mahavishnu.core.errors import ErrorCode, WorktreeIntegrityError
from mahavishnu.observability.metrics import (
    _short_principal,
    record_bundle_integrity_failure,
)

_logger = logging.getLogger(__name__)


def compute_sha256(blob: bytes) -> str:
    """Return the hex SHA-256 digest of ``blob``."""
    return sha256(blob).hexdigest()


def verify_sha256(
    blob: bytes,
    expected_sha256: str,
    *,
    backend: str,
    principal: str | None = None,
) -> None:
    """Verify ``blob``'s SHA-256 matches ``expected_sha256``.

    Args:
        blob: The bytes to hash (e.g. a fetched tar.gz bundle).
        expected_sha256: The hex digest recorded in ``WorktreeHandle.sha256``.
        backend: Adapter kind label for the metric. Must be one of
            ``ALLOWED_BACKEND_KINDS``; raises ``ValueError`` otherwise
            so a typo can't sneak into the OTel label set.
        principal: Optional principal name. Hashed to a stable 8-char
            prefix before metric emission AND before logging so the
            full value never enters the observability surface.

    Raises:
        ValueError: If ``backend`` is not in ``ALLOWED_BACKEND_KINDS``.
        WorktreeIntegrityError: If the digests do not match. The
            ``bundle_integrity_failure_total{backend, principal_short}``
            counter is incremented before the raise.
    """
    if backend not in ALLOWED_BACKEND_KINDS:
        raise ValueError(
            f"backend must be one of {sorted(ALLOWED_BACKEND_KINDS)}, "
            f"got {backend!r}"
        )
    actual = compute_sha256(blob)
    if actual == expected_sha256:
        return
    principal_short = _short_principal(principal)
    record_bundle_integrity_failure(backend=backend, principal_short=principal)
    _logger.warning(
        "bundle-integrity-mismatch",
        extra={
            "backend": backend,
            "expected_sha256": expected_sha256,
            "actual_sha256": actual,
            "principal_short": principal_short,
        },
    )
    raise WorktreeIntegrityError(
        f"SHA-256 mismatch for backend={backend}: "
        f"expected={expected_sha256!r}, actual={actual!r}",
        error_code=ErrorCode.WORKTREE_INTEGRITY_FAILED,
    )


# Allowlist of backend kinds — used by the metrics label validation.
ALLOWED_BACKEND_KINDS: Final[frozenset[str]] = frozenset(
    {"local", "s3", "gcs", "azure", "bundle"}
)
