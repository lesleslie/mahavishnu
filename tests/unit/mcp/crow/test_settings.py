"""Tests for CrowSettings — config schema + ripgrep auto-resolution."""
from __future__ import annotations

from pathlib import Path

from mahavishnu.mcp.crow.settings import CrowSettings


def test_settings_defaults_to_cwd_workspace_root():
    s = CrowSettings()
    assert s.workspace_root == Path.cwd()
    assert s.http_port == 8675
    assert s.max_redirect_hops == 5
    assert s.max_batch_urls == 20


def test_settings_accepts_workspace_root_override(tmp_path):
    s = CrowSettings(workspace_root=tmp_path)
    assert s.workspace_root == tmp_path


def test_settings_resolves_rg_when_path_present(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/rg" if name == "rg" else None)
    s = CrowSettings()
    assert s.rg_path == Path("/usr/bin/rg")


def test_settings_rg_path_none_when_not_installed(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    s = CrowSettings()
    assert s.rg_path is None


def test_settings_explicit_rg_path_overrides_which(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/rg")
    s = CrowSettings(rg_path=Path("/opt/rg"))
    assert s.rg_path == Path("/opt/rg")
