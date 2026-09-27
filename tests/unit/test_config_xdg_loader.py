"""Tests for the XDG overlay in MahavishnuSettings' loader.

Added 2026-09-27. Verifies that ``~/.config/mahavishnu/{config,local}.yaml``
are picked up by ``settings_customise_sources`` and that they sit ABOVE
the repo ``settings/mahavishnu.yaml`` + ``settings/local.yaml`` in the
merge order (so per-machine XDG overrides win).

Reference: mahavishnu/core/config.py:3077 settings_customise_sources.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mahavishnu.core.config import MahavishnuSettings

if TYPE_CHECKING:
    pass


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
    """The new XDG layer must appear in the settings sources tuple.

    ``settings_customise_sources`` returns a tuple of (init_settings,
    *yaml_sources, env_settings, dotenv_settings, file_secret_settings) —
    so the total tuple length is 4 + len(yaml_sources). For the test repo
    with both settings/mahavishnu.yaml and settings/local.yaml present,
    ``len(yaml_sources)`` is 2 + (number of XDG files present).
    """

    def _yaml_sources_only(self, sources) -> list:
        """Filter the tuple down to just the YamlConfigSettingsSource entries."""
        from pydantic_settings.sources import YamlConfigSettingsSource

        return [s for s in sources if isinstance(s, YamlConfigSettingsSource)]

    def test_xdg_files_included_when_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both XDG files exist → both YamlConfigSettingsSource returned."""
        _clear_mahavishnu_env(monkeypatch)
        xdg_dir = tmp_path / "mahavishnu"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "config.yaml").write_text("opensearch:\n  endpoint: xdg-config:9200\n")
        (xdg_dir / "local.yaml").write_text("opensearch:\n  endpoint: xdg-local:9200\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        sources = MahavishnuSettings.settings_customise_sources(
            MahavishnuSettings, None, None, None, None,
        )

        yaml_sources = self._yaml_sources_only(sources)
        # 1 repo (settings/mahavishnu.yaml) + 2 XDG = 3 YAML sources
        # (settings/local.yaml was deleted 2026-09-27 in the migration
        # to XDG; see test_xdg_overrides_repo_yaml_at_runtime for the
        # end-to-end runtime test that proves the XDG layer still wins
        # against the remaining repo file.)
        assert len(yaml_sources) == 3, f"Expected 3 YAML sources, got {len(yaml_sources)}"

    def test_xdg_absent_is_silent_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No XDG files → only the 1 repo file appears (no crash)."""
        _clear_mahavishnu_env(monkeypatch)
        # Don't create the XDG dir; point XDG_CONFIG_HOME at empty tmp_path.
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        sources = MahavishnuSettings.settings_customise_sources(
            MahavishnuSettings, None, None, None, None,
        )

        yaml_sources = self._yaml_sources_only(sources)
        # Exactly 1 repo source (settings/mahavishnu.yaml — settings/local.yaml
        # was deleted 2026-09-27 in the XDG migration).
        assert len(yaml_sources) == 1, f"Expected 1 YAML source, got {len(yaml_sources)}"

    def test_xdg_only_config_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only ``config.yaml`` exists (no ``local.yaml``) → 2 YAML sources."""
        _clear_mahavishnu_env(monkeypatch)
        xdg_dir = tmp_path / "mahavishnu"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "config.yaml").write_text("opensearch:\n  endpoint: xdg-only\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        sources = MahavishnuSettings.settings_customise_sources(
            MahavishnuSettings, None, None, None, None,
        )

        yaml_sources = self._yaml_sources_only(sources)
        # 1 repo + 1 XDG config = 2
        assert len(yaml_sources) == 2, f"Expected 2 YAML sources, got {len(yaml_sources)}"

    def test_xdg_only_local_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only ``local.yaml`` exists (no ``config.yaml``) → 2 YAML sources."""
        _clear_mahavishnu_env(monkeypatch)
        xdg_dir = tmp_path / "mahavishnu"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "local.yaml").write_text("opensearch:\n  endpoint: xdg-local\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        sources = MahavishnuSettings.settings_customise_sources(
            MahavishnuSettings, None, None, None, None,
        )

        yaml_sources = self._yaml_sources_only(sources)
        # 1 repo + 1 XDG local = 2
        assert len(yaml_sources) == 2, f"Expected 2 YAML sources, got {len(yaml_sources)}"

    def test_xdg_appended_after_repo_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Contract: XDG files come AFTER repo files in the sources tuple.

        This is what gives them "later wins" precedence under the
        ``_settings_build_values`` override.
        """
        _clear_mahavishnu_env(monkeypatch)
        xdg_dir = tmp_path / "mahavishnu"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "config.yaml").write_text("opensearch:\n  endpoint: xdg-c\n")
        (xdg_dir / "local.yaml").write_text("opensearch:\n  endpoint: xdg-l\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        sources = MahavishnuSettings.settings_customise_sources(
            MahavishnuSettings, None, None, None, None,
        )

        yaml_sources = self._yaml_sources_only(sources)
        # Verify ordering: last 2 entries should be XDG config + local
        # (the implementation appends XDG AFTER repo files).
        # pydantic-settings exposes the underlying path as ``yaml_file_path``
        # on the ``YamlConfigSettingsSource`` instance.
        second_last_path = str(yaml_sources[-2].yaml_file_path)
        last_path = str(yaml_sources[-1].yaml_file_path)
        assert "config.yaml" in second_last_path, (
            f"Second-to-last should be XDG config.yaml; got {second_last_path}"
        )
        assert "local.yaml" in last_path, (
            f"Last should be XDG local.yaml; got {last_path}"
        )

    def test_xdg_overrides_repo_yaml_at_runtime(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end: XDG value overrides repo value in constructed settings.

        Anchors the contract that XDG sits *after* the repo files in the
        sources tuple (so it wins under ``_settings_build_values``).
        """
        _clear_mahavishnu_env(monkeypatch)
        # XDG override value
        xdg_dir = tmp_path / "mahavishnu"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "local.yaml").write_text(
            "opensearch:\n  endpoint: http://xdg-override:9200\n"
        )
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        # Anchor CWD at the test repo so settings/mahavishnu.yaml is found.
        repo_root = Path(__file__).resolve().parents[2]
        monkeypatch.chdir(repo_root)

        s = MahavishnuSettings()
        # XDG wins over the repo's value (which is https://localhost:9200
        # per settings/mahavishnu.yaml defaults).
        assert "xdg-override" in s.opensearch.endpoint, (
            f"XDG override should win; got opensearch.endpoint={s.opensearch.endpoint!r}"
        )
