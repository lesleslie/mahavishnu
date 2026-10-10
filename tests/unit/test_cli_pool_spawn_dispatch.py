"""Test: ``mahavishnu pool spawn`` CLI dispatches into the running
MCP server via JSON-RPC 2.0 — NOT a transient in-process MahavishnuApp.

Architecture: spawn lives on the live MCP server (PoolManager
persists in the server's process); the CLI from a fresh shell
should reach that process over HTTP and call the ``pool_spawn``
MCP tool, the same wire shape that the SessionStart hook uses for
``pool_bootstrap`` (per ``.claude/hooks/mahavishnu-pool-bootstrap.py:67-79``).
The CLI no longer constructs its own ``MahavishnuApp`` +
``PoolManager`` for spawn; doing so creates a transient pool that
dies when the CLI exits, leaving the running server's pool
registry empty.

This test pins the contract before the rewrite so the
regression doesn't return.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from mahavishnu import _main_cli as cli_module

runner = CliRunner()


@pytest.fixture
def captured_post(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace ``httpx.Client.post`` with a recorder that captures
    URL, body, and headers. The CLI handler must lazy-import
    ``httpx`` inside ``_spawn`` for this fixture to intercept the
    HTTP call; the production implementation does so.
    """
    captured: dict[str, Any] = {}
    response = httpx.Response(
        status_code=200,
        json={
            "jsonrpc": "2.0",
            "id": "test",
            "result": {
                "structuredContent": {
                    "status": "spawned",
                    "pool_id": "pool_test_1",
                    "name": "local",
                    "type": "mahavishnu",
                    "min_workers": 1,
                    "max_workers": 3,
                    "worker_type": "shepherd",
                }
            },
        },
        request=httpx.Request(
            "POST",
            "http://localhost:8680/mcp",
            json={"jsonrpc": "2.0", "id": "x", "method": "tools/call", "params": {}},
        ),
    )

    class _RecordingClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

        def __enter__(self) -> _RecordingClient:
            return self

        def __exit__(self, *args: Any) -> bool:
            return False

        def post(
            self,
            url: str,
            json: Any = None,
            headers: Any = None,
            **kwargs: Any,
        ) -> httpx.Response:
            captured["url"] = url
            captured["body"] = json
            captured["headers"] = headers
            return response

    # Replace the top-level httpx.Client so that any lazy
    # ``import httpx`` (and the subsequent ``httpx.Client(...)``
    # call) inside the CLI handler gets the recorder.
    monkeypatch.setattr(httpx, "Client", _RecordingClient)
    return captured


class TestPoolSpawnDispatch:
    """The CLI must dispatch to the live MCP server's pool_spawn
    tool, not construct a transient in-process MahavishnuApp.
    """

    def test_dispatches_via_jsonrpc_to_live_server(
        self, captured_post: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the CLI runs ``mahavishnu pool spawn ...``, it must
        POST JSON-RPC 2.0 ``tools/call {name: pool_spawn, ...}`` to
        the MCP server (not construct a transient MahavishnuApp).
        """
        with patch.object(cli_module, "MahavishnuApp") as mock_app_cls:
            mock_app_cls.return_value = MagicMock()

            result = runner.invoke(
                cli_module.app,
                [
                    "pool", "spawn",
                    "--type", "mahavishnu",
                    "--name", "local",
                    "--min", "1",
                    "--max", "3",
                    "--worker-type", "shepherd",
                ],
            )

        # The transient path MUST NOT have been used.
        mock_app_cls.assert_not_called()

        # The dispatch contract.
        assert captured_post.get("url") == "http://localhost:8680/mcp", (
            f"CLI dispatched to wrong URL: {captured_post.get('url')!r}"
        )
        body = captured_post.get("body")
        assert isinstance(body, dict), (
            f"expected JSON-RPC body dict, got {type(body).__name__}"
        )
        assert body["jsonrpc"] == "2.0"
        assert body["method"] == "tools/call"
        params = body["params"]
        assert params["name"] == "pool_spawn"
        args = params["arguments"]
        assert args["name"] == "local"
        assert args["pool_type"] == "mahavishnu"
        assert args["min_workers"] == 1
        assert args["max_workers"] == 3
        assert args["worker_type"] == "shepherd"

        # CLI exit must surface success.
        assert result.exit_code == 0, result.output
        assert "Spawned" in result.output or "pool_test_1" in result.output

    def test_respects_mcp_url_env(
        self, captured_post: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``MAHAVISHNU_MCP_URL`` must override the default dispatch
        target — same env var the SessionStart bootstrap hook honors.
        """
        monkeypatch.setenv("MAHAVISHNU_MCP_URL", "http://mahavishnu.internal:8680/mcp")

        with patch.object(cli_module, "MahavishnuApp") as mock_app_cls:
            runner.invoke(
                cli_module.app,
                [
                    "pool", "spawn",
                    "--type", "mahavishnu",
                    "--name", "remote",
                    "--worker-type", "shepherd",
                ],
            )
        mock_app_cls.assert_not_called()
        assert captured_post["url"] == "http://mahavishnu.internal:8680/mcp"

    def test_cli_does_not_construct_transient_pool_manager(
        self, captured_post: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pin that the CLI never builds a PoolManager locally for
        the spawn path — that was the original bug (transient pool
        dies when CLI exits).
        """
        with patch.object(cli_module, "MahavishnuApp") as mock_app_cls:
            with patch("mahavishnu.pools.PoolManager") as mock_pm_cls:
                runner.invoke(
                    cli_module.app,
                    [
                        "pool", "spawn",
                        "--type", "mahavishnu",
                        "--name", "x",
                        "--worker-type", "shepherd",
                    ],
                )

        mock_app_cls.assert_not_called()
        mock_pm_cls.assert_not_called()

    def test_falls_back_to_local_when_mcp_unreachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the MCP server is unreachable (no listener), fall back
        to the legacy transient-app spawn so operators can still
        bring up a pool without the MCP server. The fallback emits
        a clear warning so the operator knows the new pool is NOT
        visible to future SessionStart bootstraps.
        """
        # httpx raises immediately (connection refused).
        class _FailingClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def __enter__(self) -> _FailingClient:
                return self

            def __exit__(self, *args: Any) -> bool:
                return False

            def post(self, *args: Any, **kwargs: Any) -> httpx.Response:
                raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr(httpx, "Client", _FailingClient)

        # Patch the legacy transient-app path so the fallback's
        # spawn succeeds locally (avoids booting a real
        # MahavishnuApp).
        with patch.object(cli_module, "MahavishnuApp") as mock_app_cls:
            mock_pm = MagicMock()
            mock_pm.spawn_pool = MagicMock(return_value="pool_fallback_1")
            mock_app = MagicMock()
            mock_app.pool_manager = mock_pm
            mock_app_cls.return_value = mock_app

            result = runner.invoke(
                cli_module.app,
                [
                    "pool", "spawn",
                    "--type", "mahavishnu",
                    "--name", "fallback",
                    "--worker-type", "shepherd",
                ],
            )

        assert result.exit_code in (0, 1), result.output
        assert (
            "fallback" in result.output.lower()
            or "unreachable" in result.output.lower()
            or "local" in result.output.lower()
        )
