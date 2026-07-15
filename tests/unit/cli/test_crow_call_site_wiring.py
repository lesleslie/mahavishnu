"""Tests for the long-term proper fix to crow MCP client wiring.

Covers:
- ``mahavishnu._main_cli._resolve_crow_mcp_client`` returns ``None`` when
  crow is disabled (the default) and a configured client when crow is enabled.
- The three ``TerminalManager.create(...)`` call sites in
  ``mahavishnu._main_cli`` (~1073, 1156, 1381) symmetrically route through
  ``_resolve_crow_mcp_client`` instead of hardcoding ``None``.

See: ``docs/followups/2026-06-29-crow-mcp-client-wiring.md``.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.fixture
def reload_main_cli():
    """Reload ``mahavishnu._main_cli`` so module-level constants and the
    ``_resolve_crow_mcp_client`` helper are picked up fresh between tests
    when monkeypatching ``create_crow_mcp_client``.
    """
    import mahavishnu._main_cli as cli_module

    importlib.reload(cli_module)
    return cli_module


def _make_config(*, crow_enabled: bool, host: str = "127.0.0.1", port: int = 8675):
    """Build a minimal config object exposing ``terminal.{crow_enabled,crow_http_host,crow_http_port}``."""
    terminal = SimpleNamespace(
        crow_enabled=crow_enabled,
        crow_http_host=host,
        crow_http_port=port,
    )
    return SimpleNamespace(terminal=terminal)


@pytest.mark.unit
def test_resolve_crow_mcp_client_returns_none_when_disabled(reload_main_cli) -> None:
    """crow_enabled=false (the default) must keep the existing fall-through-to-mock behavior."""
    config = _make_config(crow_enabled=False)

    with patch.object(
        reload_main_cli, "_resolve_crow_mcp_client", wraps=reload_main_cli._resolve_crow_mcp_client
    ) as spy:
        result = spy(config)

    assert result is None


@pytest.mark.unit
def test_resolve_crow_mcp_client_constructs_client_when_enabled(reload_main_cli) -> None:
    """crow_enabled=true must build a BodaiComponentMCPClient targeting the configured host/port."""
    config = _make_config(crow_enabled=True, host="10.0.0.5", port=9999)

    with patch(
        "mahavishnu.mcp.crow_server.create_crow_mcp_client",
        autospec=True,
    ) as helper:
        result = reload_main_cli._resolve_crow_mcp_client(config)

    helper.assert_called_once_with(host="10.0.0.5", port=9999)
    # ``helper.return_value`` is what gets propagated to TerminalManager.create().
    assert result is helper.return_value


@pytest.mark.unit
def test_resolve_crow_mcp_client_reads_env_overrides(reload_main_cli, monkeypatch) -> None:
    """Env-var overrides must take precedence when explicit host/port are unset."""
    monkeypatch.setenv("MAHAVISHNU_CROW_HTTP_HOST", "env-host")
    monkeypatch.setenv("MAHAVISHNU_CROW_HTTP_PORT", "7777")
    # ``host`` and ``port`` left as None to force env-var fallback in the helper.
    config = SimpleNamespace(
        terminal=SimpleNamespace(
            crow_enabled=True,
            crow_http_host=None,
            crow_http_port=None,
        ),
    )

    with patch(
        "mahavishnu.mcp.crow_server.create_crow_mcp_client",
        autospec=True,
    ) as helper:
        reload_main_cli._resolve_crow_mcp_client(config)

    helper.assert_called_once_with(host=None, port=None)


@pytest.mark.unit
def test_resolve_crow_mcp_client_uses_defaults_when_no_settings() -> None:
    """No terminal section on config → None (defensive against unexpected shapes)."""
    import mahavishnu._main_cli as cli_module

    assert cli_module._resolve_crow_mcp_client(object()) is None
    assert cli_module._resolve_crow_mcp_client(SimpleNamespace(terminal=None)) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "call_site_line",
    [1321, 1404, 1629],
    ids=["workers_spawn", "workers_resolved_dispatch", "pool_spawn"],
)
def test_three_call_sites_route_through_helper(reload_main_cli, call_site_line) -> None:
    """All three ``TerminalManager.create(..., mcp_client=...)`` call sites in
    ``_main_cli.py`` must read ``mcp_client`` from ``_resolve_crow_mcp_client``
    rather than hardcoding ``None``. We verify the wiring by inspecting the
    source — a regression here means the symmetric wiring has drifted.
    """
    import inspect

    source_lines = inspect.getsource(reload_main_cli).splitlines()
    # The line index in the *file* (1-based) corresponds to list index minus 1.
    target = source_lines[call_site_line - 1]
    assert "_resolve_crow_mcp_client(maha_app.config)" in target, (
        f"call site at line {call_site_line} no longer routes through the helper: {target!r}"
    )
    assert "mcp_client=None" not in target, (
        f"call site at line {call_site_line} still hardcodes mcp_client=None: {target!r}"
    )
