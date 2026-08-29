"""Unit tests for the `tmux` entry in `mahavishnu.terminal.backends.BUILTIN_BACKENDS`."""

from __future__ import annotations

from mahavishnu.terminal.backends import BUILTIN_BACKENDS


def test_tmux_backend_registered() -> None:
    assert "tmux" in BUILTIN_BACKENDS
    entry = BUILTIN_BACKENDS["tmux"]
    assert entry.name == "tmux"
    assert "tmux" in entry.command  # binary, not "npx ..."
    assert "tmux" in entry.requires
