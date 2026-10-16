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


class TestProjectRelativeLocalYamlAnchor:
    """``get_settings(project_root=...)`` must anchor Oneiric at the
    repo root, not at the inner package directory.

    2026-10-16 regression test for the anchor bug at
    ``mahavishnu/core/config.py:3319`` (was
    ``Path(__file__).resolve().parent.parent`` = the inner
    ``mahavishnu/mahavishnu/`` directory, which does not contain a
    ``settings/`` subdir). The wrong anchor made
    ``settings/local.yaml`` (project-relative layer 2) silently
    un-loadable, and a stray key in any operator's local.yaml would
    also crash construction with a `ValidationError` on the
    corresponding sub-config. Both failures are now caught here.
    """

    def test_local_yaml_overrides_reach_settings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A key in ``<project_root>/settings/local.yaml`` must land in
        ``MahavishnuSettings.<field>`` after construction.

        The test bypasses the XDG layer by pointing ``XDG_CONFIG_HOME``
        at an empty directory, then passes ``project_root=tmp_path``
        so Oneiric's loader anchors at the test's own settings tree.
        """
        _clear_mahavishnu_env(monkeypatch)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "settings").mkdir()
        # Minimal mahavishnu.yaml — required by the loader.
        (project_root / "settings" / "mahavishnu.yaml").write_text(
            "server_name: test\n"
        )
        # The local.yaml override under test.
        (project_root / "settings" / "local.yaml").write_text(
            "goal_teams:\n  enabled: true\n"
        )

        reset_settings()
        s = get_settings(project_root=project_root)
        assert s.goal_teams.enabled is True, (
            f"settings/local.yaml override should reach "
            f"goal_teams.enabled; got {s.goal_teams.enabled!r}"
        )
        assert "goal_teams" in s.model_fields_set, (
            "goal_teams should be reported as explicitly set after "
            "a local.yaml override; if this fails, the anchor at "
            "mahavishnu/core/config.py:3319 has regressed."
        )

    def test_stray_subconfig_key_does_not_crash_construction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A key in the operator's ``local.yaml`` that the target
        Pydantic sub-config doesn't declare is dropped (not raised).

        Before this fix, ``health: { feed_halflife_seconds: 60, ... }``
        raised ``ValidationError: health.feed_halflife_seconds - Extra
        inputs are not permitted`` because ``HealthConfig`` declares
        only 5 fields with ``extra="forbid"``. The per-subconfig
        filter in :func:`_filter_subconfig_keys` strips the unknown
        key so construction succeeds with the operator's known
        keys still in effect.
        """
        _clear_mahavishnu_env(monkeypatch)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "settings").mkdir()
        (project_root / "settings" / "mahavishnu.yaml").write_text(
            "server_name: test\n"
        )
        # `feed_halflife_seconds` is NOT declared on HealthConfig;
        # the filter must drop it without raising.
        (project_root / "settings" / "local.yaml").write_text(
            "health:\n"
            "  enabled: true\n"
            "  check_timeout_seconds: 7\n"
            "  feed_halflife_seconds: 60\n"  # undeclared on HealthConfig
        )

        reset_settings()
        s = get_settings(project_root=project_root)  # must not raise
        assert s.health.enabled is True
        assert s.health.check_timeout_seconds == 7
        # The known key is honored; the unknown key is silently dropped
        # (no attribute access attempted — `getattr` with default
        # rather than attribute access is intentional).
        assert getattr(s.health, "feed_halflife_seconds", None) != 60

    def test_resolve_pydantic_model_cls_handles_optional(
        self,
    ) -> None:
        """``_resolve_pydantic_model_cls`` returns the model class
        for plain types and PEP 604 ``X | None``; returns ``None``
        for non-model annotations and ``None``. Both ``Optional[X]``
        and PEP 604 ``X | None`` are handled because they share the
        same ``typing.get_args`` surface."""
        from mahavishnu.core.config import (
            HealthConfig,
            _resolve_pydantic_model_cls,
        )

        # Plain model
        assert _resolve_pydantic_model_cls(HealthConfig) is HealthConfig
        # PEP 604 X | None — covers typing.Optional[X] too (same get_args surface)
        assert _resolve_pydantic_model_cls(HealthConfig | None) is HealthConfig
        # Non-model
        assert _resolve_pydantic_model_cls(str) is None
        assert _resolve_pydantic_model_cls(None) is None
        assert _resolve_pydantic_model_cls(42) is None
        # Union of two non-models
        assert _resolve_pydantic_model_cls(str | int) is None

    def test_filter_subconfig_keys_strips_undeclared(
        self,
    ) -> None:
        """``_filter_subconfig_keys`` keeps only keys declared on the
        target ``BaseModel`` and drops everything else, including
        nested dict values (one level deep — Mahavishnu's sub-configs
        are flat). Non-dict inputs are returned unchanged.
        """
        from mahavishnu.core.config import (
            HealthConfig,
            _filter_subconfig_keys,
        )

        # Dict input with mix of declared + undeclared keys
        result = _filter_subconfig_keys(
            {
                "enabled": True,
                "check_timeout_seconds": 7,
                "feed_halflife_seconds": 60,  # undeclared
                "totally_unknown_key": "x",  # undeclared
            },
            HealthConfig,
        )
        assert result == {
            "enabled": True,
            "check_timeout_seconds": 7,
        }

        # Non-dict input passes through
        assert _filter_subconfig_keys("not a dict", HealthConfig) == "not a dict"
        assert _filter_subconfig_keys(None, HealthConfig) is None

        # Dict with non-model annotation passes through
        assert _filter_subconfig_keys({"any": "thing"}, str) == {"any": "thing"}
