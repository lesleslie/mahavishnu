"""Tests for the launch_mcp.py PATH bootstrap.

launchd gives a service ONLY the EnvironmentVariables declared in its
plist -- it never sources ~/.zshenv, ~/.zshrc or ~/.profile. The
generated plists therefore handed the MCP server a PATH that omitted
~/.local/bin, where the user-level CLIs live (claude, codex,
deepagents, clai, crow-mcp).

Two failures followed from that gap:

1. ``WorkerManager._validate_required_tool`` calls ``shutil.which`` to
   check the worker backend's ``requires_tool``. With ``claude`` absent
   from PATH it raised "requires tool 'claude' which is not on PATH".
2. The spawned worker command is ``sh -lc 'claude ...'``. A login shell
   reads ~/.profile but NOT ~/.zshenv, so it could not resolve the
   binary either -- even though the operator's interactive shell could.

``augment_path`` closes both gaps by putting ~/.local/bin on the
server's PATH before the server process starts. The tmux worker
session inherits that PATH from the server, so the spawned command
finds the binary too.

The opt-out (``MAHAVISHNU_NO_EXTRA_PATH=1``) is honored because the
worker-manager error message already advertises it to operators.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.launch_mcp import augment_path

pytestmark = pytest.mark.unit


class TestAugmentPath:
    """Pin the PATH augmentation contract."""

    def test_adds_local_bin_when_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """~/.local/bin is added when the inherited PATH lacks it."""
        local_bin = tmp_path / ".local" / "bin"
        local_bin.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("PATH", "/usr/bin:/bin")

        augment_path()

        assert str(local_bin) in os.environ["PATH"]

    def test_is_idempotent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Running twice does not duplicate the entry."""
        local_bin = tmp_path / ".local" / "bin"
        local_bin.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("PATH", "/usr/bin:/bin")

        augment_path()
        first = os.environ["PATH"]
        augment_path()

        assert os.environ["PATH"] == first
        assert os.environ["PATH"].count(str(local_bin)) == 1

    def test_preserves_existing_entries(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Pre-existing PATH entries are kept -- the bootstrap only adds."""
        local_bin = tmp_path / ".local" / "bin"
        local_bin.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("PATH", "/opt/homebrew/bin:/usr/local/bin")

        augment_path()

        assert os.environ["PATH"].startswith("/opt/homebrew/bin:/usr/local/bin")

    def test_no_extra_path_opt_out(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """MAHAVISHNU_NO_EXTRA_PATH=1 skips the augmentation entirely."""
        local_bin = tmp_path / ".local" / "bin"
        local_bin.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        monkeypatch.setenv("MAHAVISHNU_NO_EXTRA_PATH", "1")

        augment_path()

        assert os.environ["PATH"] == "/usr/bin:/bin"

    def test_missing_directory_is_skipped(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A home without ~/.local/bin leaves PATH untouched."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("PATH", "/usr/bin:/bin")

        augment_path()

        assert os.environ["PATH"] == "/usr/bin:/bin"

    def test_empty_path_is_handled(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """An unset PATH does not raise."""
        local_bin = tmp_path / ".local" / "bin"
        local_bin.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("PATH", raising=False)

        augment_path()

        assert str(local_bin) in os.environ["PATH"]
