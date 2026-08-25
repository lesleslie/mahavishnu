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
    _bundle_integrity_failure_counter,
    _short_principal,
    _validate_labels,
)

_logger = logging.getLogger(__name__)


# Allowlist of backend kinds — used by the metrics label validation.
# Defined at module scope before helpers so both ``verify_sha256`` and
# ``verify_sha256_streaming`` can validate backend labels against the
# same frozenset (per round-2 BLOCKER R2-19).
ALLOWED_BACKEND_KINDS: Final[frozenset[str]] = frozenset({"local", "s3", "gcs", "azure", "bundle"})


def compute_sha256(blob: bytes) -> str:
    """Return the hex SHA-256 digest of ``blob``."""
    return sha256(blob).hexdigest()


def verify_sha256_streaming(
    actual_sha: str,
    expected_sha: str,
    *,
    backend: str,
    principal_short: str,
) -> None:
    """Compare streamed-hash to expected, raise WorktreeIntegrityError on mismatch.

    Used by ``storage_io.deserialize_worktree_tar`` after the SHA-256
    is finalized over the streamed tar.zst payload (no full blob in
    memory). ``actual_sha`` and ``expected_sha`` are pre-computed hex
    digests; this function only compares, hashes, and emits metrics.

    Emits ``bundle_integrity_failure_total{backend, principal_short}``
    on mismatch via ``record_bundle_integrity_failure_short`` (the
    pre-computed ``principal_short`` is NOT re-hashed — per round-2
    BLOCKER B-DI-03 / R2-22).

    Writes a Dhara audit row for forensic chain-of-custody (per
    round-2 BLOCKER B-DI-11) via ``write_dhara_audit_row``.

    Raises:
        ValueError: If ``backend`` is not in ``ALLOWED_BACKEND_KINDS``.
        WorktreeIntegrityError: If the digests do not match.
    """
    if backend not in ALLOWED_BACKEND_KINDS:
        raise ValueError(f"backend must be one of {sorted(ALLOWED_BACKEND_KINDS)}, got {backend!r}")
    if actual_sha == expected_sha:
        return

    # B-DI-03 fix: pre-computed principal_short; NO re-hash.
    record_bundle_integrity_failure_short(backend=backend, principal_short=principal_short)
    _logger.warning(
        "bundle-integrity-mismatch",
        extra={
            "error_code": "MHV-208",
            "backend": backend,
            "principal_short": principal_short,
            "expected_sha_prefix8": expected_sha[:8],
            "actual_sha_prefix8": actual_sha[:8],
        },
    )
    write_dhara_audit_row(
        kind="bundle_integrity_failure",
        backend=backend,
        principal_short=principal_short,
        expected_sha_prefix8=expected_sha[:8],
        actual_sha_prefix8=actual_sha[:8],
    )
    raise WorktreeIntegrityError(
        f"SHA-256 mismatch for backend={backend}: expected={expected_sha!r}, actual={actual_sha!r}",
        error_code=ErrorCode.WORKTREE_INTEGRITY_FAILED,
    )


def record_bundle_integrity_failure_short(*, backend: str, principal_short: str) -> None:
    """Emit ``bundle_integrity_failure_total{backend, principal_short}`` WITHOUT re-hashing.

    Used by ``verify_sha256_streaming``. The pre-computed ``principal_short``
    is already an 8-char HMAC; calling ``record_bundle_integrity_failure(name=...)``
    would re-hash and corrupt the label set.
    """
    labels = {"backend": backend, "principal_short": principal_short}
    _validate_labels(labels)
    _bundle_integrity_failure_counter.add(1, attributes=labels)


def write_dhara_audit_row(
    *,
    kind: str,
    backend: str,
    principal_short: str,
    expected_sha_prefix8: str,
    actual_sha_prefix8: str,
) -> None:
    """Write a forensic audit row to Dhara (B-DI-11).

    Placeholder until the Dhara orchestrator wires the audit pipeline.
    Currently logs the row at INFO level with the same fields so the
    audit chain is captured in the structured-log surface even before
    Dhara persistence is connected. The Dhara-side write is a no-op
    until the orchestrator ships ``mahavishnu.audit.dhara_writer``.

    The signature is intentionally keyword-only so callers (and
    tests) can monkeypatch by attribute name and forward extra fields
    without positional-arg drift.
    """
    _logger.info(
        "dhara-audit-row-pending",
        extra={
            "kind": kind,
            "backend": backend,
            "principal_short": principal_short,
            "expected_sha_prefix8": expected_sha_prefix8,
            "actual_sha_prefix8": actual_sha_prefix8,
        },
    )


def verify_sha256(
    blob: bytes,
    expected_sha256: str,
    *,
    backend: str,
    principal: object = None,
) -> None:
    """Verify ``blob``'s SHA-256 matches ``expected_sha256``.

    Thin wrapper that delegates to ``verify_sha256_streaming`` after
    hashing the in-memory blob. The streaming variant is the source of
    truth so the metric emission + log shape stay identical regardless
    of whether the SHA was computed over an in-memory blob or a streamed
    tar.zst payload (per round-2 BLOCKER R2-02 / B-DI-03).

    Args:
        blob: The bytes to hash (e.g. a fetched tar.gz bundle).
        expected_sha256: The hex digest recorded in ``WorktreeHandle.sha256``.
        backend: Adapter kind label for the metric. Must be one of
            ``ALLOWED_BACKEND_KINDS``; raises ``ValueError`` otherwise
            so a typo can't sneak into the OTel label set.
        principal: Optional principal name (or any object with a
            ``.name`` attribute — used for principal objects). Hashed
            to a stable 8-char prefix before metric emission AND
            before logging so the full value never enters the
            observability surface.

    Raises:
        ValueError: If ``backend`` is not in ``ALLOWED_BACKEND_KINDS``.
        WorktreeIntegrityError: If the digests do not match. The
            ``bundle_integrity_failure_total{backend, principal_short}``
            counter is incremented before the raise.
    """
    # ``principal`` may be a plain ``str`` or an object with a
    # ``.name`` attribute (e.g. ``Principal``). Use ``getattr`` with
    # an explicit ``None`` default so the type-checker does not
    # have to narrow ``object`` based on ``hasattr``.
    principal_name = (
        getattr(principal, "name", None) or str(principal) if principal is not None else ""
    )
    principal_short = _short_principal(principal_name)
    verify_sha256_streaming(
        compute_sha256(blob),
        expected_sha256,
        backend=backend,
        principal_short=principal_short,
    )
