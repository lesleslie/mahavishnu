"""Tests for the new ``MahavishnuSettings.eventbridge`` field.

Mirrors the Crackerjack/Aksha field tests. Defaults are conservative
(enabled=False, dry_run=True) for backward compat.
"""
from __future__ import annotations

from mahavishnu.core.config import EventBridgeConfig, MahavishnuSettings


def test_eventbridge_settings_class_exists() -> None:
    assert EventBridgeConfig.__name__ == "EventBridgeConfig"


def test_eventbridge_settings_defaults_to_disabled() -> None:
    cfg = EventBridgeConfig()
    assert cfg.enabled is False


def test_eventbridge_settings_endpoint_default_is_empty_string() -> None:
    cfg = EventBridgeConfig()
    assert cfg.endpoint == ""


def test_eventbridge_settings_dry_run_defaults_true() -> None:
    cfg = EventBridgeConfig()
    assert cfg.dry_run is True


def test_mahavishnu_settings_exposes_eventbridge_field() -> None:
    s = MahavishnuSettings()
    assert hasattr(s, "eventbridge")
    assert s.eventbridge.__class__.__name__ == "EventBridgeConfig"


def test_mahavishnu_settings_eventbridge_field_default_disabled() -> None:
    s = MahavishnuSettings()
    assert s.eventbridge.enabled is False
    assert s.eventbridge.dry_run is True


def test_eventbridge_settings_can_be_enabled() -> None:
    s = MahavishnuSettings(
        eventbridge=EventBridgeConfig(
            enabled=True, dry_run=False, endpoint="redis://localhost:6379"
        )
    )
    assert s.eventbridge.enabled is True
    assert s.eventbridge.dry_run is False
    assert s.eventbridge.endpoint == "redis://localhost:6379"
