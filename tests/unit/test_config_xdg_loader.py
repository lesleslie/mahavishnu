"""Tests for the XDG overlay in MahavishnuSettings' loader.

Verifies that ``~/.config/mahavishnu/{config,local}.yaml`` are picked up
by ``get_settings()`` (which routes through Oneiric's ``load_settings``)
and that they sit ABOVE the repo ``settings/mahavishnu.yaml`` in the
merge order (so per-machine XDG overrides win).

Reference: ``mahavishnu/core/config.py:get_settings``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mahavishnu.core.config import MahavishnuSettings, get_settings, reset_settings

if TYPE_CHECKING:
    pass  # noqa


def _clear_mahavishnu_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every env var that could leak in from the test runner."""
    for key in (
        "MAHAVISHNU_OPENSEARCH__ENDPOINT",
        "MAHAVISHNU_AGNO__ENABLED",
        "MAHAVISHNU_LOG_LEVEL",
        "MAHAVISHNU_TERMINAL__ADAPTER_PREFERENCE",
        "MAHAVISHNU_AUTH__ALGORITHM",
        "XDG_CONFIG_HOME",
    ):
        monkeypatch.delenv(key, raising=False)


class TestXDGOverlay:
    """XDG files in ``~/.config/mahavishnu/{config,local}.yaml`` must
    flow through Oneiric's loader and override the repo defaults.

    2026-09-29: rewritten — the previous version inspected the internal
    pydantic-settings source tuple, which is no longer how Mahavishnu's
    loader works. The new loader reads via
    ``oneiric.core.config.load_settings(project_name="mahavishnu")`` and
    passes ``__pydantic_extra__`` to ``MahavishnuSettings(**merged)``.
    These tests assert the *external* contract (XDG values reach the
    constructed settings) rather than the implementation surface.
    """

    def test_xdg_files_included_when_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both XDG files exist → both are loaded; local.yaml wins over config.yaml."""
        _clear_mahavishnu_env(monkeypatch)
        xdg_dir = tmp_path / "mahavishnu"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "config.yaml").write_text("opensearch:\n  endpoint: xdg-config:9200\n")
        (xdg_dir / "local.yaml").write_text("opensearch:\n  endpoint: xdg-local:9200\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        reset_settings()
        s = get_settings()
        # local.yaml (layer 4) wins over config.yaml (layer 3) per Oneiric's
        # documented precedence.
        assert "xdg-local:9200" in s.opensearch.endpoint, (
            f"XDG local.yaml should win over config.yaml; got {s.opensearch.endpoint!r}"
        )

    def test_xdg_absent_is_silent_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No XDG files → repo defaults apply, no crash."""
        _clear_mahavishnu_env(monkeypatch)
        # Don't create the XDG dir; point XDG_CONFIG_HOME at empty tmp_path.
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        reset_settings()
        s = get_settings()
        # No XDG present — falls back to settings/mahavishnu.yaml default.
        # The exact value isn't asserted; just that construction succeeded.
        assert s.opensearch.endpoint is not None

    def test_xdg_only_config_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only config.yaml exists → config.yaml value lands in settings."""
        _clear_mahavishnu_env(monkeypatch)
        xdg_dir = tmp_path / "mahavishnu"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "config.yaml").write_text("opensearch:\n  endpoint: xdg-only-config\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        reset_settings()
        s = get_settings()
        assert "xdg-only-config" in s.opensearch.endpoint, (
            f"XDG config.yaml should be applied; got {s.opensearch.endpoint!r}"
        )

    def test_xdg_only_local_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only local.yaml exists → local.yaml value lands in settings."""
        _clear_mahavishnu_env(monkeypatch)
        xdg_dir = tmp_path / "mahavishnu"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "local.yaml").write_text("opensearch:\n  endpoint: xdg-only-local\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        reset_settings()
        s = get_settings()
        assert "xdg-only-local" in s.opensearch.endpoint, (
            f"XDG local.yaml should be applied; got {s.opensearch.endpoint!r}"
        )

    def test_xdg_overrides_repo_yaml_at_runtime(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end: XDG value wins over repo's settings/mahavishnu.yaml."""
        _clear_mahavishnu_env(monkeypatch)
        xdg_dir = tmp_path / "mahavishnu"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "local.yaml").write_text(
            "opensearch:\n  endpoint: http://xdg-override:9200\n"
        )
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        reset_settings()
        s = get_settings()
        assert "xdg-override" in s.opensearch.endpoint, (
            f"XDG override should win; got opensearch.endpoint={s.opensearch.endpoint!r}"
        )

    def test_xdg_layer_overrides_repo_local(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """XDG local.yaml (layer 4) beats repo settings/local.yaml (layer 2)."""
        _clear_mahavishnu_env(monkeypatch)
        xdg_dir = tmp_path / "mahavishnu"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "local.yaml").write_text("opensearch:\n  endpoint: xdg-beats-repo\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        reset_settings()
        s = get_settings()
        assert "xdg-beats-repo" in s.opensearch.endpoint
