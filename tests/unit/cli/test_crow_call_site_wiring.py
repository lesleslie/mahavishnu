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
    "call_site_kind",
    ["workers_spawn", "pool_spawn"],
)
def test_call_sites_route_through_helper(reload_main_cli, call_site_kind) -> None:
    """Both ``TerminalManager.create(..., mcp_client=...)`` call sites in
    ``_main_cli.py`` must read ``mcp_client`` from ``_resolve_crow_mcp_client``
    rather than hardcoding ``None``. We verify the wiring by inspecting the
    source — a regression here means the symmetric wiring has drifted.

    The call sites are located by *searching* the source for the helper
    call, not by a pinned line number. A previous version of this test
    hardcoded the line numbers, which broke every time an unrelated
    commit added a line to ``_main_cli.py`` — the drift read as a real
    wiring regression when nothing had changed.

    Two call shapes exist:
    - ``workers_spawn`` resolves the crow client into a local variable
      (``crow_client = _resolve_crow_mcp_client(...)``), then passes it
      to ``TerminalManager.create``.
    - ``pool_spawn`` calls ``_resolve_crow_mcp_client`` inline
      (``mcp_client=_resolve_crow_mcp_client(...)``).
    """
    import inspect

    source_lines = inspect.getsource(reload_main_cli).splitlines()
    matches = [
        (number, line)
        for number, line in enumerate(source_lines, start=1)
        if "_resolve_crow_mcp_client(maha_app.config)" in line
    ]
    assert matches, "no call site routes through _resolve_crow_mcp_client"

    if call_site_kind == "workers_spawn":
        # The local-variable form: the call is on its own statement.
        candidates = [
            (number, line) for number, line in matches if line.strip().startswith("crow_client = ")
        ]
    else:
        # The inline keyword-argument form.
        candidates = [
            (number, line)
            for number, line in matches
            if "mcp_client=_resolve_crow_mcp_client" in line.replace(" ", "")
        ]

    assert candidates, f"no {call_site_kind} call site routes through the helper; found {matches}"
    for number, line in candidates:
        assert "mcp_client=None" not in line, (
            f"call site at line {number} still hardcodes mcp_client=None: {line!r}"
        )
