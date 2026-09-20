"""Tests for ``mahavishnu acp`` CLI surface (sub-commit 2.D).

Plan §Phase 2 Task 2: register the ``mahavishnu acp serve`` Typer command
and verify it appears in the main CLI's help.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from mahavishnu._main_cli import app as main_app
from mahavishnu.cli.acp_cli import app as acp_app

runner = CliRunner()

pytestmark = pytest.mark.unit


class TestMainCLIRegistration:
    """The ACP sub-app is registered on the main CLI."""

    def test_acp_subcommand_appears_in_main_help(self) -> None:
        result = runner.invoke(main_app, ["--help"])
        assert result.exit_code == 0
        assert "acp" in result.output.lower()

    def test_acp_subcommand_help_lists_serve(self) -> None:
        result = runner.invoke(main_app, ["acp", "--help"])
        assert result.exit_code == 0
        assert "serve" in result.output

    def test_acp_serve_help_describes_command(self) -> None:
        result = runner.invoke(main_app, ["acp", "serve", "--help"])
        assert result.exit_code == 0
        # The help text mentions stdio + JSON-RPC.
        text = result.output.lower()
        assert "stdio" in text
        assert "json-rpc" in text or "jsonrpc" in text


class TestACPAppHelp:
    """Smoke tests against the ACP sub-app directly."""

    def test_serve_help_via_subapp(self) -> None:
        result = runner.invoke(acp_app, ["serve", "--help"])
        assert result.exit_code == 0
        # Bearer option is exposed (envvar binding).
        assert "--bearer-token" in result.output

    def test_subapp_help_renders(self) -> None:
        result = runner.invoke(acp_app, ["--help"])
        assert result.exit_code == 0
        assert "ACP" in result.output or "acp" in result.output.lower()


class TestServeRefusesWithoutBearer:
    """Without a bearer, ``serve`` refuses to start with a clear error.

    The full end-to-end failure path (asyncio pipe plumbing + bearer
    check) is exercised by the Phase 4 subprocess e2e test. Here we
    only verify that ``acquire_bearer()`` correctly returns ``None``
    when neither env var nor file is set — the trigger for the
    dispatcher's fail-closed RuntimeError.
    """

    def test_acquire_bearer_returns_none_without_env_or_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mahavishnu.acp.auth import (
            ENV_BEARER_TOKEN,
            ENV_BEARER_TOKEN_FILE,
            acquire_bearer,
            reset_cached_bearer_for_tests,
        )

        monkeypatch.delenv(ENV_BEARER_TOKEN, raising=False)
        monkeypatch.delenv(ENV_BEARER_TOKEN_FILE, raising=False)
        reset_cached_bearer_for_tests()
        assert acquire_bearer() is None
        reset_cached_bearer_for_tests()
