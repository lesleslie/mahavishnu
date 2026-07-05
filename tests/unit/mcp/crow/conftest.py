"""Shared fixtures for the crow-server unit tests."""
from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from mahavishnu.mcp.crow.settings import CrowSettings


def mock_settings(workspace_root: Path | None = None, **overrides) -> CrowSettings:
    """Plain factory — call with tmp_path: mock_settings(tmp_path)."""
    root = workspace_root or Path("/tmp/crow-test-workspace")
    root.mkdir(parents=True, exist_ok=True)
    return CrowSettings(workspace_root=root, **overrides)


def _real_rg_path() -> str | None:
    """Return the real rg path if installed; used by fixtures to avoid
    hard-coding a path that may not exist on this host."""
    return shutil.which("rg")


@pytest.fixture
def settings_with_rg(tmp_path, monkeypatch):
    rg_path = _real_rg_path()
    if rg_path is None:
        pytest.skip("ripgrep (rg) is not installed on this host")
    monkeypatch.setattr("shutil.which", lambda name: rg_path if name == "rg" else None)
    return CrowSettings(workspace_root=tmp_path)


@pytest.fixture
def settings_no_rg(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    return CrowSettings(workspace_root=tmp_path)
