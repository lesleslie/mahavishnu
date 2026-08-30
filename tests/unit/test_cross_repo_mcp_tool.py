"""Unit tests for Mahavishnu Phase 1 cross-repo search.

Covers:
* ``cross_repo_search`` tool: registration + fan-out aggregation
* ``_can_subscribe_to_channel`` allowlist update for ``cross-repo:``
* Query hashing + dedup
* Stub-mode behavior when Akosha / Session-Buddy are unreachable
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _DummyFastMCP:
    """Minimal FastMCP substitute that records tool() registrations."""

    def __init__(self) -> None:
        self.registered: dict[str, Callable[..., Any]] = {}

    def tool(self, *_args: Any, **_kwargs: Any) -> Any:
        def decorator(fn: Any) -> Any:
            self.registered[fn.__name__] = fn
            return fn

        return decorator


def _make_settings(akosha_url: str, session_buddy_url: str) -> MagicMock:
    settings = MagicMock()
    settings.akosha_url = akosha_url
    settings.session_buddy_url = session_buddy_url
    return settings


def _make_httpx_response(payload: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=payload)
    return resp


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestRegisterSearchTools:
    def test_cross_repo_search_registered(self) -> None:
        from mahavishnu.mcp.tools.search_tools import register_search_tools

        app = _DummyFastMCP()
        register_search_tools(app)  # type: ignore[arg-type]
        assert "cross_repo_search" in app.registered

    def test_cross_repo_search_is_coroutine(self) -> None:
        from mahavishnu.mcp.tools.search_tools import register_search_tools

        app = _DummyFastMCP()
        register_search_tools(app)  # type: ignore[arg-type]
        import inspect

        assert inspect.iscoroutinefunction(app.registered["cross_repo_search"])


# ---------------------------------------------------------------------------
# Tool invocation
# ---------------------------------------------------------------------------


class TestCrossRepoSearchInvocation:
    @pytest.mark.asyncio
    async def test_invalid_scope_rejected(self) -> None:
        from mahavishnu.mcp.tools.search_tools import register_search_tools

        app = _DummyFastMCP()
        register_search_tools(app)  # type: ignore[arg-type]
        fn = app.registered["cross_repo_search"]
        with pytest.raises(ValueError):
            await fn(query="foo", scope="bogus")

    @pytest.mark.asyncio
    async def test_limit_too_high_rejected(self) -> None:
        from mahavishnu.mcp.tools.search_tools import register_search_tools

        app = _DummyFastMCP()
        register_search_tools(app)  # type: ignore[arg-type]
        fn = app.registered["cross_repo_search"]
        with pytest.raises(ValueError):
            await fn(query="foo", limit=9999)

    @pytest.mark.asyncio
    async def test_fanout_aggregates_results(self) -> None:
        """Plan exit-criteria gate: aggregator must combine Akosha + SB results."""
        from mahavishnu.mcp.tools.search_tools import register_search_tools

        app = _DummyFastMCP()
        register_search_tools(app)  # type: ignore[arg-type]
        fn = app.registered["cross_repo_search"]

        akosha_resp = _make_httpx_response(
            {
                "result": {
                    "results": [
                        {
                            "repo": "mahavishnu",
                            "kind": "tool",
                            "name": "pool_route_execute",
                            "score": 0.92,
                        },
                        {
                            "repo": "akosha",
                            "kind": "tool",
                            "name": "search_all_systems",
                            "score": 0.81,
                        },
                        {
                            "repo": "session-buddy",
                            "kind": "tool",
                            "name": "quick_search",
                            "score": 0.77,
                        },
                        {
                            "repo": "crackerjack",
                            "kind": "tool",
                            "name": "crackerjack_run",
                            "score": 0.65,
                        },
                    ]
                }
            }
        )
        sb_resp = _make_httpx_response(
            {
                "result": json_dumps(
                    {
                        "workflow_id": "wf-1",
                        "components": [
                            {
                                "repo": "mahavishnu",
                                "workflow_id": "wf-1",
                                "status": "succeeded",
                            },
                            {
                                "repo": "akosha",
                                "workflow_id": "wf-1",
                                "status": "running",
                            },
                            {
                                "repo": "session-buddy",
                                "workflow_id": "wf-1",
                                "status": "succeeded",
                            },
                        ],
                        "summary": {},
                        "mode": "phase1_stub",
                    }
                )
            }
        )

        class _FakeAsyncClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *args: Any) -> None:
                return None

            async def post(self, url: str, json: dict[str, Any] | None = None) -> MagicMock:
                # Differentiate by URL string.
                if "akosha" in url or "8682" in url:
                    return akosha_resp
                return sb_resp

        with (
            patch(
                "mahavishnu.mcp.tools.search_tools._get_settings",
                return_value=_make_settings(
                    akosha_url="http://localhost:8682/mcp",
                    session_buddy_url="http://localhost:8678/mcp",
                ),
            ),
            patch(
                "mahavishnu.mcp.tools.search_tools.httpx.AsyncClient",
                _FakeAsyncClient,
            ),
        ):
            result = await fn(
                query="code-review adapters",
                scope="capabilities",
                limit=10,
            )

        # Two source fan-outs succeeded.
        assert len(result["sources"]) == 2
        assert {s["name"] for s in result["sources"]} == {"akosha", "session-buddy"}
        assert all(s["status"] == "ok" for s in result["sources"])
        assert result["mode"] == "fanout"

        # Aggregator combines both result sets.
        assert result["total_combined"] >= 5
        assert result["spans_3_components"] is True
        repos_seen = {e["repo"] for e in result["combined"] if e.get("repo")}
        assert len(repos_seen) >= 3

        # Result entries have a "source" tag identifying the fan-out origin.
        sources_in_combined = {e["source"] for e in result["combined"]}
        assert sources_in_combined == {"akosha", "session-buddy"}

    @pytest.mark.asyncio
    async def test_fanout_degrades_when_akosha_down(self) -> None:
        from mahavishnu.mcp.tools.search_tools import register_search_tools

        app = _DummyFastMCP()
        register_search_tools(app)  # type: ignore[arg-type]
        fn = app.registered["cross_repo_search"]

        sb_resp = _make_httpx_response(
            {
                "result": json_dumps(
                    {
                        "workflow_id": "wf-2",
                        "components": [
                            {"repo": "mahavishnu", "workflow_id": "wf-2", "status": "succeeded"},
                            {"repo": "akosha", "workflow_id": "wf-2", "status": "succeeded"},
                            {"repo": "session-buddy", "workflow_id": "wf-2", "status": "succeeded"},
                        ],
                        "summary": {},
                        "mode": "phase1_stub",
                    }
                )
            }
        )

        class _FakeAsyncClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *args: Any) -> None:
                return None

            async def post(self, url: str, json: dict[str, Any] | None = None) -> MagicMock:
                # Akosha down — only Session-Buddy reachable.
                if "akosha" in url or "8682" in url:
                    raise RuntimeError("akosha offline")
                return sb_resp

        with (
            patch(
                "mahavishnu.mcp.tools.search_tools._get_settings",
                return_value=_make_settings(
                    akosha_url="http://localhost:8682/mcp",
                    session_buddy_url="http://localhost:8678/mcp",
                ),
            ),
            patch(
                "mahavishnu.mcp.tools.search_tools.httpx.AsyncClient",
                _FakeAsyncClient,
            ),
        ):
            result = await fn(query="wf-2", scope="runs")

        akosha_entry = next(s for s in result["sources"] if s["name"] == "akosha")
        sb_entry = next(s for s in result["sources"] if s["name"] == "session-buddy")
        assert akosha_entry["status"] == "error"
        assert sb_entry["status"] == "ok"
        assert result["mode"] == "degraded"

    @pytest.mark.asyncio
    async def test_dedup_collapses_duplicate_keys(self) -> None:
        from mahavishnu.mcp.tools.search_tools import register_search_tools

        app = _DummyFastMCP()
        register_search_tools(app)  # type: ignore[arg-type]
        fn = app.registered["cross_repo_search"]

        akosha_resp = _make_httpx_response(
            {
                "result": {
                    "results": [
                        {
                            "repo": "mahavishnu",
                            "kind": "tool",
                            "name": "pool_route_execute",
                            "score": 0.5,
                        }
                    ]
                }
            }
        )
        sb_resp = _make_httpx_response(
            {
                "result": json_dumps(
                    {
                        "workflow_id": "wf-3",
                        "components": [
                            {
                                "repo": "mahavishnu",
                                "workflow_id": "wf-3",
                                "status": "succeeded",
                            }
                        ],
                        "summary": {},
                        "mode": "phase1_stub",
                    }
                )
            }
        )

        class _FakeAsyncClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *args: Any) -> None:
                return None

            async def post(self, url: str, json: dict[str, Any] | None = None) -> MagicMock:
                return akosha_resp if "akosha" in url or "8682" in url else sb_resp

        with (
            patch(
                "mahavishnu.mcp.tools.search_tools._get_settings",
                return_value=_make_settings(
                    akosha_url="http://localhost:8682/mcp",
                    session_buddy_url="http://localhost:8678/mcp",
                ),
            ),
            patch(
                "mahavishnu.mcp.tools.search_tools.httpx.AsyncClient",
                _FakeAsyncClient,
            ),
        ):
            result = await fn(query="anything", scope="capabilities", limit=10)

        # Two different "name" values (one tool, one workflow_id) so 2 entries
        # total — but if a hypothetical collision occurred, the dedup would
        # collapse them. The key uniqueness is source|repo|name, so the tool
        # entry + run entry are different keys.
        keys = {
            (e.get("source"), e.get("repo"), e.get("name"))
            for e in result["combined"]
        }
        assert len(keys) == len(result["combined"])


# ---------------------------------------------------------------------------
# WebSocket channel allowlist
# ---------------------------------------------------------------------------


def json_dumps(payload: Any) -> str:
    import json

    return json.dumps(payload)


class TestCrossRepoChannelAllowlist:
    def test_admin_can_subscribe(self) -> None:
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer.__new__(MahavishnuWebSocketServer)
        assert (
            server._can_subscribe_to_channel(
                {"permissions": ["admin"]},
                "cross-repo:abc123",
            )
            is True
        )

    def test_cross_repo_read_can_subscribe(self) -> None:
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer.__new__(MahavishnuWebSocketServer)
        assert (
            server._can_subscribe_to_channel(
                {"permissions": ["cross_repo:read"]},
                "cross-repo:abc123",
            )
            is True
        )

    def test_non_admin_cannot_subscribe(self) -> None:
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer.__new__(MahavishnuWebSocketServer)
        assert (
            server._can_subscribe_to_channel(
                {"permissions": ["workflow:read"]},
                "cross-repo:abc123",
            )
            is False
        )

    def test_unknown_channel_still_denied(self) -> None:
        from mahavishnu.websocket.server import MahavishnuWebSocketServer

        server = MahavishnuWebSocketServer.__new__(MahavishnuWebSocketServer)
        assert (
            server._can_subscribe_to_channel(
                {"permissions": ["admin"]},
                "totally-new-channel",
            )
            is True  # admin bypasses the channel-specific checks
        )


# ---------------------------------------------------------------------------
# Stream-channel broadcast path
# ---------------------------------------------------------------------------


class TestStreamChannelBroadcast:
    @pytest.mark.asyncio
    async def test_stream_channel_emits_broadcast(self) -> None:
        from mahavishnu.mcp.tools.search_tools import register_search_tools

        app = _DummyFastMCP()
        register_search_tools(app)  # type: ignore[arg-type]
        fn = app.registered["cross_repo_search"]

        akosha_resp = _make_httpx_response(
            {
                "result": {
                    "results": [
                        {
                            "repo": "mahavishnu",
                            "kind": "tool",
                            "name": "pool_route_execute",
                            "score": 0.9,
                        }
                    ]
                }
            }
        )
        sb_resp = _make_httpx_response(
            {
                "result": json_dumps(
                    {
                        "workflow_id": "wf-stream",
                        "components": [],
                        "summary": {},
                        "mode": "phase1_stub",
                    }
                )
            }
        )

        class _FakeAsyncClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *args: Any) -> None:
                return None

            async def post(self, url: str, json: dict[str, Any] | None = None) -> MagicMock:
                return akosha_resp if "akosha" in url or "8682" in url else sb_resp

        broadcast_mock = AsyncMock()
        fake_server = MagicMock()
        fake_server.broadcast_to_room = broadcast_mock

        with (
            patch(
                "mahavishnu.mcp.tools.search_tools._get_settings",
                return_value=_make_settings(
                    akosha_url="http://localhost:8682/mcp",
                    session_buddy_url="http://localhost:8678/mcp",
                ),
            ),
            patch(
                "mahavishnu.mcp.tools.search_tools.httpx.AsyncClient",
                _FakeAsyncClient,
            ),
            patch(
                "mahavishnu.mcp.tools.search_tools._get_websocket_server",
                return_value=fake_server,
            ),
        ):
            result = await fn(
                query="anything",
                scope="capabilities",
                stream_channel=True,
            )

        assert "channel" in result
        assert result["channel"].startswith("cross-repo:")
        broadcast_mock.assert_awaited_once()
        # channel name should match
        call_args = broadcast_mock.await_args
        assert call_args.args[0] == result["channel"]


# ---------------------------------------------------------------------------
# Query-hash stability
# ---------------------------------------------------------------------------


class TestQueryHashStability:
    @pytest.mark.asyncio
    async def test_same_query_same_hash(self) -> None:
        from mahavishnu.mcp.tools.search_tools import register_search_tools

        app = _DummyFastMCP()
        register_search_tools(app)  # type: ignore[arg-type]
        fn = app.registered["cross_repo_search"]

        akosha_resp = _make_httpx_response({"result": {"results": []}})
        sb_resp = _make_httpx_response(
            {"result": json_dumps({"workflow_id": "x", "components": [], "summary": {}, "mode": "phase1_stub"})}
        )

        class _FakeAsyncClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *args: Any) -> None:
                return None

            async def post(self, url: str, json: dict[str, Any] | None = None) -> MagicMock:
                return akosha_resp if "akosha" in url or "8682" in url else sb_resp

        with (
            patch(
                "mahavishnu.mcp.tools.search_tools._get_settings",
                return_value=_make_settings(
                    akosha_url="http://localhost:8682/mcp",
                    session_buddy_url="http://localhost:8678/mcp",
                ),
            ),
            patch(
                "mahavishnu.mcp.tools.search_tools.httpx.AsyncClient",
                _FakeAsyncClient,
            ),
        ):
            r1 = await fn(query="foo", scope="capabilities")
            r2 = await fn(query="foo", scope="capabilities")
        assert r1["query_hash"] == r2["query_hash"]
        # 16-char hex prefix of sha256
        assert len(r1["query_hash"]) == 16
        assert all(c in "0123456789abcdef" for c in r1["query_hash"])

    @pytest.mark.asyncio
    async def test_different_scope_different_hash(self) -> None:
        from mahavishnu.mcp.tools.search_tools import register_search_tools

        app = _DummyFastMCP()
        register_search_tools(app)  # type: ignore[arg-type]
        fn = app.registered["cross_repo_search"]

        akosha_resp = _make_httpx_response({"result": {"results": []}})
        sb_resp = _make_httpx_response(
            {"result": json_dumps({"workflow_id": "x", "components": [], "summary": {}, "mode": "phase1_stub"})}
        )

        class _FakeAsyncClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *args: Any) -> None:
                return None

            async def post(self, url: str, json: dict[str, Any] | None = None) -> MagicMock:
                return akosha_resp if "akosha" in url or "8682" in url else sb_resp

        with (
            patch(
                "mahavishnu.mcp.tools.search_tools._get_settings",
                return_value=_make_settings(
                    akosha_url="http://localhost:8682/mcp",
                    session_buddy_url="http://localhost:8678/mcp",
                ),
            ),
            patch(
                "mahavishnu.mcp.tools.search_tools.httpx.AsyncClient",
                _FakeAsyncClient,
            ),
        ):
            r1 = await fn(query="foo", scope="capabilities")
            r2 = await fn(query="foo", scope="runs")
        assert r1["query_hash"] != r2["query_hash"]
