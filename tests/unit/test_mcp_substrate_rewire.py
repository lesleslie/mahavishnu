"""Pin the substrate rewire: the substrate reaches a live server.

The retired storage service's port was the default for every substrate
client in mahavishnu, and it spoke that service's tool API
(``put``, ``get``, ``query_time_series``) — an API no live server in the
fleet exposes. These tests pin the replacement:

* the substrate URL resolves to mahavishnu's own MCP server;
* the KV tools are registered at every tool-profile tier;
* the durable-state backend calls the tools that actually exist;
* the analytics paths say that no component writes their series.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mahavishnu.core.bootstrap import resolve_mcp_url
from mahavishnu.core.mcp_adapter import (
    DEFAULT_SUBSTRATE_MCP_URL,
    INTERNAL_SERVICE_USER_ID,
    MCPAdapter,
    NoAnalyticsWriterError,
)


class TestResolveMcpUrl:
    """The substrate URL must not be the decommissioned service's port."""

    def test_falls_back_to_the_own_server_url(self) -> None:
        config = SimpleNamespace(
            health=SimpleNamespace(dependencies={}),
            tools=SimpleNamespace(mcp_server_url="http://localhost:8680/mcp"),
        )

        assert resolve_mcp_url(config) == "http://localhost:8680/mcp"

    def test_health_dependency_overrides_the_own_server_url(self) -> None:
        config = SimpleNamespace(
            health=SimpleNamespace(
                dependencies={
                    "mcp": SimpleNamespace(host="mcp.internal", port=9999, use_tls=True)
                }
            ),
            tools=SimpleNamespace(mcp_server_url="http://localhost:8680/mcp"),
        )

        assert resolve_mcp_url(config) == "https://mcp.internal:9999/mcp"

    def test_never_returns_the_retired_port(self) -> None:
        """The retired service held 8683. No default may point at it."""
        config = SimpleNamespace(
            health=SimpleNamespace(dependencies={}),
            tools=SimpleNamespace(mcp_server_url="http://localhost:8680/mcp"),
        )

        assert "8683" not in resolve_mcp_url(config)
        assert "8683" not in DEFAULT_SUBSTRATE_MCP_URL


class TestKvToolRegistration:
    """The KV tools must be reachable at every tier, not just registered."""

    def test_kv_tools_are_in_the_mandatory_groups(self) -> None:
        from mahavishnu.mcp.tools.profiles import MAHAVISHNU_MANDATORY_GROUPS

        assert "_register_kv_tools" in MAHAVISHNU_MANDATORY_GROUPS


class TestInternalServicePrincipal:
    """The self-call needs an identity the KV tools' auth gate accepts."""

    def test_the_role_grants_only_the_ecosystem_state_permissions(self) -> None:
        from mahavishnu.core.permissions import Permission, RBACManager

        manager = RBACManager(SimpleNamespace())
        role = manager.roles["internal_service"]

        assert set(role.permissions) == {
            Permission.READ_ECOSYSTEM_STATE,
            Permission.WRITE_ECOSYSTEM_STATE,
        }

    def test_the_principal_is_registered_with_that_role(self) -> None:
        from mahavishnu.core.bootstrap import _register_internal_service_user
        from mahavishnu.core.permissions import RBACManager

        manager = RBACManager(SimpleNamespace())
        _register_internal_service_user(manager)

        user = manager.users[INTERNAL_SERVICE_USER_ID]
        assert [role.name for role in user.roles] == ["internal_service"]


class TestAnalyticsHasNoWriter:
    """An empty series reads as "no data yet"; a missing writer is different."""

    @pytest.mark.asyncio
    async def test_query_time_series_names_the_missing_metric(self) -> None:
        adapter = MCPAdapter(base_url="http://localhost:8680/mcp")

        with pytest.raises(NoAnalyticsWriterError) as excinfo:
            await adapter.query_time_series(
                metric_type="git_velocity", entity_id="/repo"
            )

        assert "git_velocity" in str(excinfo.value)
        assert "writer" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_aggregate_patterns_reports_the_missing_feed(self) -> None:
        adapter = MCPAdapter(base_url="http://localhost:8680/mcp")

        with pytest.raises(NoAnalyticsWriterError) as excinfo:
            await adapter.aggregate_patterns(start_date="2026-10-01")

        assert "pattern" in str(excinfo.value)


class TestStateBackendCallsLiveTools:
    """The durable-state backend must name the tools that exist."""

    @pytest.mark.asyncio
    async def test_put_uses_the_kv_put_tool(self) -> None:
        from mahavishnu.core.state_backends.mcp import MCPStateBackend

        backend = MCPStateBackend(base_url="http://localhost:8680/mcp")
        backend._client.call_tool = AsyncMock(return_value={"ok": True, "key": "k"})

        await backend.put("workflow/v1/abc", {"status": "queued"})

        name, args = backend._client.call_tool.call_args[0]
        assert name == "mahavishnu_kv_put"
        assert args["key"] == "workflow/v1/abc"
        assert args["user_id"] == INTERNAL_SERVICE_USER_ID

    @pytest.mark.asyncio
    async def test_get_returns_the_decoded_payload(self) -> None:
        from mahavishnu.core.state_backends.mcp import MCPStateBackend

        backend = MCPStateBackend(base_url="http://localhost:8680/mcp")
        backend._client.call_tool = AsyncMock(
            return_value={"ok": True, "value": '{"status": "queued"}'}
        )

        result = await backend.get("workflow/v1/abc")

        assert result == {"status": "queued"}
