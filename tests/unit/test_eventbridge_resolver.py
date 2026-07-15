"""Tests for mahavishnu.core.events.eventbridge_resolver.

The resolver is the production wiring entry point: given a
``MahavishnuSettings`` and a WebSocketServer, it constructs an
``EventBridgePublisher`` (or None when the operator hasn't opted in)
and sets it on the server's ``_event_publisher`` slot.

Mirrors the parallel tests in Crackerjack and Akosha.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from mahavishnu.core.config import EventBridgeConfig, MahavishnuSettings
from mahavishnu.core.events.eventbridge_adapter import EventBridgePublisher
from mahavishnu.core.events.eventbridge_resolver import resolve_event_publisher


def _settings_with_eventbridge(*, enabled: bool, dry_run: bool = False) -> MahavishnuSettings:
    return MahavishnuSettings(
        eventbridge=EventBridgeConfig(enabled=enabled, dry_run=dry_run)
    )


def test_resolve_returns_none_when_disabled() -> None:
    server = MagicMock()
    bridge = MagicMock()
    settings = _settings_with_eventbridge(enabled=False)
    assert resolve_event_publisher(settings, server=server, bridge=bridge) is None
    server.set_eventbridge_publisher.assert_not_called()


def test_resolve_returns_none_when_dry_run() -> None:
    server = MagicMock()
    bridge = MagicMock()
    settings = _settings_with_eventbridge(enabled=True, dry_run=True)
    assert resolve_event_publisher(settings, server=server, bridge=bridge) is None
    server.set_eventbridge_publisher.assert_not_called()


def test_resolve_sets_publisher_when_enabled_and_live() -> None:
    server = MagicMock()
    bridge = MagicMock()
    settings = _settings_with_eventbridge(enabled=True, dry_run=False)
    publisher = resolve_event_publisher(settings, server=server, bridge=bridge)
    assert isinstance(publisher, EventBridgePublisher)
    server.set_eventbridge_publisher.assert_called_once_with(publisher)


def test_resolve_returns_none_when_enabled_but_no_bridge() -> None:
    """When bridge is None (Oneiric runtime unavailable), no wiring."""
    server = MagicMock()
    settings = _settings_with_eventbridge(enabled=True, dry_run=False)
    assert resolve_event_publisher(settings, server=server, bridge=None) is None
    server.set_eventbridge_publisher.assert_not_called()
