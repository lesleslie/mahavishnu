"""Coverage-push test for the 1 missed line in mahavishnu/shell/adapter.py"""

from __future__ import annotations

import pytest

from mahavishnu.core.app import MahavishnuApp
from mahavishnu.shell.adapter import MahavishnuShell


def test_register_magics_raises_when_shell_uninitialized() -> None:
    """Line 65: raise when InteractiveShellEmbed was never set by start()."""
    shell = MahavishnuShell(MahavishnuApp())
    assert shell.shell is None
    with pytest.raises(RuntimeError, match="InteractiveShellEmbed was not initialized"):
        shell._register_magics()