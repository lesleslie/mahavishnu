"""JotError exception hierarchy (TD-B2).

Every jot-specific failure raises a JotError subclass so callers can branch
on type (not message parsing). Base class `JotError` enables a single
`except JotError` to catch every jot failure.

The base carries a stable ``error_id`` correlation tag so downstream
consumers (tier-2 reconciler, Sentry, Dhara) can key off a stable string
without message parsing. The base default is ``"ERROR_JOT"``; drain-specific
subclasses (sub-plan 3) accept their own keyword-only ``error_id`` with a
sensible default.
"""

from __future__ import annotations


class JotError(Exception):
    """Base class for all jot-specific errors.

    Attributes:
        error_id: Stable correlation tag for downstream systems.
    """

    def __init__(self, message: str, *, error_id: str = "ERROR_JOT") -> None:
        super().__init__(message)
        self.error_id = error_id


class JotNotFoundError(JotError):
    """Handle didn't match any jot (resolve_handle + fold consumers)."""


class JotAmbiguousHandleError(JotError):
    """Handle matched 2+ jots; caller must use longer handle or full ID.

    Attributes:
        candidates: short_ids that matched the ambiguous handle, in fold order.
    """

    def __init__(self, message: str, *, candidates: list[str]) -> None:
        joined = ", ".join(candidates)
        super().__init__(f"{message} (candidates: {joined})")
        self.candidates: list[str] = candidates


class JotLogCorruptError(JotError):
    """Log file unreadable or has structural errors that prevent fold."""


class JotParseError(JotError):
    """Single JotEvent line failed to deserialize; logged to errors.log."""


# --- Drain sub-plan errors (sub-plan 3) ---


class JotDispatchError(JotError):
    """Raised when dispatch_jot fails to trigger a workflow (network, auth,
    upstream). Carries .error_id for Sentry/Dhara correlation.
    """

    def __init__(self, message: str, *, error_id: str = "ERROR_JOT_DISPATCH") -> None:
        super().__init__(f"{message} [{error_id}]", error_id=error_id)


class JotRetryError(JotError):
    """Raised by retry_dispatch when the target jot is not in FAILED state."""


class JotDeferError(JotError):
    """Raised by defer_jot when until_ms <= now_ms (would immediately expire)."""


class JotValidationError(JotError):
    """Raised by _append_event when ctx fails per-op TypedDict validation.

    Attributes:
        field: The failing ctx path (e.g., 'events[3].ctx.attempt') so fold
            can log a precise warning instead of crashing.
    """

    def __init__(
        self,
        message: str,
        *,
        field: str = "<unknown>",
        error_id: str = "ERROR_JOT_VALIDATION",
    ) -> None:
        super().__init__(f"{message} (field={field})", error_id=error_id)
        self.field = field


class JotLogUnwritableError(JotError):
    """Raised by _append_event on disk write failure (read-only HOME, full disk).

    Attributes:
        path: The unwritable file path.
    """

    def __init__(self, message: str, *, path: str = "<unknown>") -> None:
        super().__init__(
            f"{message} (path={path})", error_id="ERROR_JOT_LOG_UNWRITABLE"
        )
        self.path = path


class JotSurfaceThrottled(JotError):
    """Internal marker — _Throttle raises this to skip a surfacing fire.

    Not part of the public API; only surface_relevant's caller (the hook
    wrapper) should observe it.
    """
