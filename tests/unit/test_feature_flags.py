"""Unit tests for core.feature_flags."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mahavishnu.core.errors import FeatureDisabledError
from mahavishnu.core.feature_flags import (
    _config,
    check_feature,
    get_all_feature_flags,
    get_config,
    is_feature_enabled,
    require_feature,
    set_config,
)


@pytest.fixture(autouse=True)
def reset_feature_flag_context() -> None:
    """Reset ContextVar between tests to avoid cross-test leakage."""
    _config.set(None)


def test_get_config_raises_when_not_set() -> None:
    with pytest.raises(RuntimeError, match="Configuration not set in context"):
        get_config()


def test_set_and_get_config_roundtrip() -> None:
    cfg = SimpleNamespace(goal_teams=SimpleNamespace(enabled=True))
    set_config(cfg)
    assert get_config() is cfg


def test_is_feature_enabled_defaults_when_config_missing() -> None:
    # 2026-10-15 wire-up fix: when the ContextVar is None, the
    # fallback path now calls get_settings() so production CLI/MCP
    # processes read live settings instead of always-defaulting. If
    # get_settings() itself raises (e.g. malformed Oneiric config),
    # the path falls back to Pydantic defaults — the test patches
    # the source module to raise to exercise that branch.
    from unittest.mock import patch

    with patch(
        "mahavishnu.core.config.get_settings",
        side_effect=Exception("no settings available"),
    ):
        assert is_feature_enabled("enabled") is False
        assert is_feature_enabled("mcp_tools_enabled") is True
        assert is_feature_enabled("unknown_feature") is False


def test_is_feature_enabled_loads_live_settings_when_contextvar_none() -> None:
    # 2026-10-15 wire-up fix: when no config is in the ContextVar,
    # the function reads live settings via get_settings(). Master
    # switch + per-feature values come from settings/mahavishnu.yaml.
    # This test exercises the load path with a MagicMock stand-in
    # for the settings object.
    from unittest.mock import MagicMock, patch

    fake_settings = MagicMock()
    fake_settings.goal_teams.enabled = True
    fake_settings.goal_teams.feature_flags.mcp_tools_enabled = True

    with patch("mahavishnu.core.config.get_settings", return_value=fake_settings):
        assert is_feature_enabled("enabled") is True
        assert is_feature_enabled("mcp_tools_enabled") is True


def test_is_feature_enabled_respects_live_master_switch_when_off() -> None:
    # Companion to test_loads_live_settings: when live settings has the
    # master switch off, every individual flag reads False.
    from unittest.mock import MagicMock, patch

    fake_settings = MagicMock()
    fake_settings.goal_teams.enabled = False
    fake_settings.goal_teams.feature_flags.mcp_tools_enabled = True

    with patch("mahavishnu.core.config.get_settings", return_value=fake_settings):
        assert is_feature_enabled("enabled") is False
        # Master switch off disables all non-master features.
        assert is_feature_enabled("mcp_tools_enabled") is False


def test_is_feature_enabled_defaults_when_goal_teams_missing() -> None:
    set_config(SimpleNamespace())
    assert is_feature_enabled("enabled") is False
    assert is_feature_enabled("cli_commands_enabled") is True


def test_is_feature_enabled_respects_master_switch() -> None:
    cfg = SimpleNamespace(
        goal_teams=SimpleNamespace(
            enabled=False,
            feature_flags=SimpleNamespace(mcp_tools_enabled=True),
        )
    )
    set_config(cfg)
    assert is_feature_enabled("enabled") is False
    # Master switch off disables all non-master features.
    assert is_feature_enabled("mcp_tools_enabled") is False


def test_is_feature_enabled_with_master_on_uses_individual_flags() -> None:
    cfg = SimpleNamespace(
        goal_teams=SimpleNamespace(
            enabled=True,
            feature_flags=SimpleNamespace(
                mcp_tools_enabled=False,
                cli_commands_enabled=True,
            ),
        )
    )
    set_config(cfg)
    assert is_feature_enabled("enabled") is True
    assert is_feature_enabled("mcp_tools_enabled") is False
    assert is_feature_enabled("cli_commands_enabled") is True
    assert is_feature_enabled("missing_flag") is False


def test_is_feature_enabled_defaults_when_feature_flags_missing() -> None:
    cfg = SimpleNamespace(goal_teams=SimpleNamespace(enabled=True, feature_flags=None))
    set_config(cfg)
    assert is_feature_enabled("learning_system_enabled") is False
    assert is_feature_enabled("auto_mode_selection_enabled") is True


def test_is_feature_enabled_handles_internal_exceptions() -> None:
    class BrokenConfig:
        @property
        def goal_teams(self) -> object:
            raise ValueError("boom")

    set_config(BrokenConfig())
    assert is_feature_enabled("mcp_tools_enabled") is True
    assert is_feature_enabled("enabled") is False


def test_check_feature_raises_when_disabled() -> None:
    cfg = SimpleNamespace(
        goal_teams=SimpleNamespace(
            enabled=True,
            feature_flags=SimpleNamespace(mcp_tools_enabled=False),
        )
    )
    set_config(cfg)

    with pytest.raises(FeatureDisabledError) as exc:
        check_feature("mcp_tools_enabled")

    assert exc.value.error_code.value == "MHV-468"
    assert "config_path" in exc.value.details


def test_check_feature_noop_when_enabled() -> None:
    cfg = SimpleNamespace(
        goal_teams=SimpleNamespace(
            enabled=True,
            feature_flags=SimpleNamespace(mcp_tools_enabled=True),
        )
    )
    set_config(cfg)
    check_feature("mcp_tools_enabled")


def test_require_feature_sync_function_enabled_and_disabled() -> None:
    cfg = SimpleNamespace(
        goal_teams=SimpleNamespace(
            enabled=True,
            feature_flags=SimpleNamespace(cli_commands_enabled=True),
        )
    )
    set_config(cfg)

    @require_feature("cli_commands_enabled")
    def add(a: int, b: int) -> int:
        return a + b

    assert add(2, 3) == 5

    cfg.goal_teams.feature_flags.cli_commands_enabled = False
    with pytest.raises(FeatureDisabledError):
        add(1, 1)


@pytest.mark.asyncio
async def test_require_feature_async_function_enabled_and_disabled() -> None:
    cfg = SimpleNamespace(
        goal_teams=SimpleNamespace(
            enabled=True,
            feature_flags=SimpleNamespace(mcp_tools_enabled=True),
        )
    )
    set_config(cfg)

    @require_feature("mcp_tools_enabled")
    async def do_work(value: int) -> int:
        return value * 2

    assert await do_work(7) == 14

    cfg.goal_teams.feature_flags.mcp_tools_enabled = False
    with pytest.raises(FeatureDisabledError):
        await do_work(7)


def test_get_all_feature_flags_returns_master_and_all_fields() -> None:
    cfg = SimpleNamespace(
        goal_teams=SimpleNamespace(
            enabled=True,
            feature_flags=SimpleNamespace(
                mcp_tools_enabled=True,
                cli_commands_enabled=False,
                llm_fallback_enabled=True,
                websocket_broadcasts_enabled=True,
                prometheus_metrics_enabled=True,
                learning_system_enabled=False,
                auto_mode_selection_enabled=True,
                custom_skills_enabled=False,
            ),
        )
    )
    set_config(cfg)

    flags = get_all_feature_flags()
    assert flags["enabled"] is True
    assert flags["mcp_tools_enabled"] is True
    assert flags["cli_commands_enabled"] is False
    assert "custom_skills_enabled" in flags
