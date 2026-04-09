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
    assert is_feature_enabled("enabled") is False
    assert is_feature_enabled("mcp_tools_enabled") is True
    assert is_feature_enabled("unknown_feature") is False


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
