"""JotError hierarchy (TD-B2)."""
from __future__ import annotations

from mahavishnu.jot.errors import (
    JotAmbiguousHandleError,
    JotError,
    JotLogCorruptError,
    JotNotFoundError,
    JotParseError,
)


def test_jot_error_is_base_exception() -> None:
    assert issubclass(JotError, Exception)


def test_jot_not_found_error_inherits_jot_error() -> None:
    assert issubclass(JotNotFoundError, JotError)


def test_jot_ambiguous_handle_error_inherits_jot_error() -> None:
    assert issubclass(JotAmbiguousHandleError, JotError)


def test_jot_log_corrupt_error_inherits_jot_error() -> None:
    assert issubclass(JotLogCorruptError, JotError)


def test_jot_parse_error_inherits_jot_error() -> None:
    assert issubclass(JotParseError, JotError)


def test_jot_ambiguous_handle_error_carries_candidates() -> None:
    err = JotAmbiguousHandleError("ambiguous", candidates=["a3f9c2", "b7e1d4"])
    assert err.candidates == ["a3f9c2", "b7e1d4"]
    assert "ambiguous" in str(err)
    assert "a3f9c2" in str(err)
    assert "b7e1d4" in str(err)


def test_jot_not_found_error_message_includes_handle() -> None:
    err = JotNotFoundError("not found: a3f9c2")
    assert "a3f9c2" in str(err)


def test_caller_can_catch_all_jot_errors_via_base() -> None:
    """The TD-B2 payoff — one except catches all jot errors."""
    caught: list[JotError] = []
    for exc in [
        JotNotFoundError("nope"),
        JotAmbiguousHandleError("ambiguous", candidates=["x"]),
        JotLogCorruptError("corrupt"),
        JotParseError("parse"),
    ]:
        try:
            raise exc
        except JotError as e:
            caught.append(e)
    assert len(caught) == 4
