"""JotError exception hierarchy (TD-B2).

Every jot-specific failure raises a JotError subclass so callers can branch
on type (not message parsing). Base class `JotError` enables a single
`except JotError` to catch every jot failure.
"""
from __future__ import annotations


class JotError(Exception):
    """Base class for all jot-specific errors."""


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
