"""resolve_handle (R8)."""
from __future__ import annotations

import pytest

from mahavishnu.jot.errors import JotAmbiguousHandleError, JotNotFoundError
from mahavishnu.jot.fold import JotSummary
from mahavishnu.jot.handle import resolve_handle


def _s(suffix: str, text: str = "x") -> JotSummary:
    return JotSummary(
        id=(suffix * 8)[:32],
        short_id=suffix[-6:],
        text=text,
        status="open",
        last_modified_ms=0,
    )


def test_resolve_by_exact_full_id() -> None:
    a = _s("a3f9c2")
    assert resolve_handle([a], a.id) is a


def test_resolve_by_exact_short_id() -> None:
    a = _s("a3f9c2")
    assert resolve_handle([a], "a3f9c2") is a


def test_resolve_by_substring_when_unambiguous() -> None:
    a = _s("a3f9c2")
    b = _s("b7e1d4")
    # 'a3f' is a unique substring of a's id.
    assert resolve_handle([a, b], "a3f") is a


def test_resolve_raises_ambiguous_when_two_match() -> None:
    """R8 — substring matching 2+ jots raises explicit error."""
    # Two states with overlapping suffix chars (both end in 'f9c2').
    a = _s("abf9c2")  # both id and short_id contain 'f9c2'
    b = _s("0123f9c2")  # short_id ends in 'f9c2'
    with pytest.raises(JotAmbiguousHandleError) as exc_info:
        resolve_handle([a, b], "f9c2")
    assert exc_info.value.candidates  # at least one candidate listed


def test_resolve_raises_not_found_when_no_match() -> None:
    a = _s("a3f9c2")
    with pytest.raises(JotNotFoundError):
        resolve_handle([a], "z9z9z9")


def test_resolve_raises_not_found_for_empty_handle() -> None:
    a = _s("a3f9c2")
    with pytest.raises(JotNotFoundError):
        resolve_handle([a], "")