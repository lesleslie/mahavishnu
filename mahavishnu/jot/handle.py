"""Handle resolution: substring match with explicit ambiguity (R8)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import JotAmbiguousHandleError, JotNotFoundError

if TYPE_CHECKING:
    from .fold import JotSummary


def resolve_handle(states: list[JotSummary], handle: str) -> JotSummary:
    """Resolve a handle (full ID, short_id, or unambiguous substring) to one JotSummary.

    Match priority:
    1. Exact 32-hex ID
    2. Exact 6-hex short_id
    3. Substring match (any unambiguous prefix/suffix of id or short_id)

    Raises:
        JotNotFoundError: handle matches no jot.
        JotAmbiguousHandleError: handle matches 2+ jots; lists candidate short_ids.
    """
    if not handle:
        raise JotNotFoundError("empty handle")

    # Priority 1: exact full ID.
    for s in states:
        if s.id == handle:
            return s

    # Priority 2: exact short_id.
    for s in states:
        if s.short_id == handle:
            return s

    # Priority 3: substring match.
    matches = [s for s in states if handle in s.id or handle in s.short_id]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        candidates = [s.short_id for s in matches]
        raise JotAmbiguousHandleError(
            f"handle {handle!r} matches {len(matches)} jots",
            candidates=candidates,
        )
    raise JotNotFoundError(f"handle {handle!r} matches no jot")