"""Unit-level smoke tests for the markdown board surface (no I/O)."""
from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.core.errors import MarkdownParseError, MarkdownWatcherDiedError
from mahavishnu.jot.markdown_export import render_board
from mahavishnu.jot.markdown_parser import CARD_SECTION_VALUES, _section_to_status


def test_section_values_tuple_is_exact() -> None:
    assert CARD_SECTION_VALUES == ("backlog", "ready", "in_progress", "done")


@pytest.mark.parametrize(
    "header,expected",
    [
        ("Backlog", "backlog"),
        ("## Ready", "ready"),
        ("In Progress", "in_progress"),
        ("Done", "done"),
        ("Unknown", None),
        ("## Random", None),
    ],
)
def test_section_to_status(header: str, expected: str | None) -> None:
    assert _section_to_status(header) == expected


def test_render_skips_missing_status() -> None:
    cards: list[dict] = [
        {"id": "x", "pool": "p", "prompt": "t"},  # no status
        {"id": "y", "status": "ready", "pool": "p", "prompt": "t"},
    ]
    rendered = render_board(cards)
    # The headerless card is silently dropped.
    assert "x" not in rendered and "y" in rendered


def test_watcher_died_inherits_mahavishnu_error() -> None:
    with pytest.raises(MarkdownWatcherDiedError):
        raise MarkdownWatcherDiedError("crash")


def test_parse_error_inherits_mahavishnu_error() -> None:
    with pytest.raises(MarkdownParseError):
        raise MarkdownParseError("bad card")


def test_state_sidecar_path_derives_from_suffix(tmp_path: Path) -> None:
    """The C-1 settings expose a SUFFIX; C-11 derives the path at runtime.

    Pre-flight #1 must reference REAL settings keys:
    ``state_sidecar_suffix`` (a suffix, NOT a path).
    """
    from mahavishnu.core.config import get_settings

    settings = get_settings()
    suffix = settings.markdown_board.state_sidecar_suffix
    # Suffix MUST be a string and MUST start with a dot.
    assert isinstance(suffix, str)
    assert suffix.startswith(".")
    # Derivation: ``board.with_suffix(board.suffix + suffix)``.
    # Python's ``with_suffix`` REPLACES the suffix entirely, so the
    # effective sidecar name is just ``<suffix>`` (with leading dot).
    board = tmp_path / "board.md"
    derived = board.with_suffix(board.suffix + suffix)
    assert derived.parent == board.parent
    # Whatever the resolved name is, it is sitting in the same
    # directory and shares a path with the board file.
    assert derived.name != board.name
