"""Parity between Mahavishnu's two health surfaces.

``GET /health`` (the FastMCP custom route on the MCP server's port) and
the MCP ``get_health`` tool answer the same question about the same
process. Before these tests they were two independent implementations
and they disagreed: the HTTP route hand-rolled a check set from the
signer / plan-index / sweeper feeds and never called the canonical
aggregator, while the MCP tool called ``aggregate_mahavishnu_health``.
One process answered HTTP 200 ``"ok"`` and MCP 503 ``"degraded"``.

Per ``docs/decisions/mcp-backend-wiring-discipline.md`` the two
surfaces must surface the same feed-state aggregates; disagreement
between them is a bug. These tests pin that contract, mirroring
``akosha/tests/unit/test_health_consistency.py``.

The ``storage`` feed gets its own tests because it was the reason the
aggregator reported degraded: it probed ``EncryptedSQLite``, a
decommissioned class with no production consumers, and that probe
demanded a ``SQLCIPHER_KEY`` the server never needed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from fastmcp import Client
import pytest
from starlette.testclient import TestClient

from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.mcp.server_core import FastMCPServer

#: The canonical feeds the aggregator owns.
CANONICAL_FEEDS = frozenset({"storage", "message_bus", "adapters"})

#: Fields that are point-in-time snapshots rather than verdicts. Two
#: calls a few milliseconds apart legitimately differ: the clock moves,
#: and the live KV store's record count can change between them.
VOLATILE_FIELDS = frozenset({"last_updated_timestamp", "entities_count"})


def _stable(checks: dict[str, Any]) -> dict[str, Any]:
    """Drop the point-in-time snapshot fields so two calls can be compared."""
    return {
        name: {key: value for key, value in entry.items() if key not in VOLATILE_FIELDS}
        for name, entry in checks.items()
    }


def _make_settings(**overrides: Any) -> MahavishnuSettings:
    """Build a MahavishnuSettings instance with safe defaults for tests."""
    defaults: dict[str, Any] = {
        "server_name": "mahavishnu",
        "observability_enabled": False,
        "terminal_enabled": False,
        "pools": {"enabled": False},
        "workers": {"enabled": False},
        "otel_storage": {"enabled": False},
    }
    defaults.update(overrides)
    return MahavishnuSettings(**defaults)


@pytest.fixture
def mock_app() -> MagicMock:
    """A MagicMock spec'd to MahavishnuApp for FastMCPServer init."""
    app = MagicMock(spec=MahavishnuApp)
    app.config = _make_settings()
    app.get_repos = MagicMock(return_value=[])
    app.is_healthy = MagicMock(return_value=True)
    app.adapters = {}
    app.workflow_state_manager = MagicMock()
    app.rbac_manager = MagicMock()
    app.observability = MagicMock()
    app.opensearch_integration = MagicMock()
    app.error_recovery_manager = MagicMock()
    app.monitoring_service = MagicMock()
    app.pool_manager = None
    app.worktree_coordinator = None
    return app


@pytest.fixture
def server(mock_app: MagicMock) -> FastMCPServer:
    """A FastMCPServer bound to a mocked MahavishnuApp."""
    return FastMCPServer(app=mock_app)


@pytest.fixture
def fresh_kv_store(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Point the storage probe at a private store.

    ``mahavishnu.core.kv_store.kv_store`` is a process-wide singleton.
    The probe reads it through the module attribute, so replacing the
    attribute gives this test a private store — clearing the global one
    instead would destroy records other tests rely on.
    """
    from mahavishnu.core import kv_store as kv_store_module

    private = kv_store_module.ProcessLocalKV()
    monkeypatch.setattr(kv_store_module, "kv_store", private)
    return private


# ---------------------------------------------------------------------------
# The storage feed must probe the live store.
# ---------------------------------------------------------------------------


def test_storage_feed_is_healthy_without_sqlcipher_key(
    monkeypatch: pytest.MonkeyPatch,
    fresh_kv_store: Any,
) -> None:
    """The storage feed must not require ``SQLCIPHER_KEY``.

    ``EncryptedSQLite`` was decommissioned — the substrate moved to the
    server's own process-local KV — so probing it made the whole service
    report degraded on a machine that never set the key.
    """
    monkeypatch.delenv("SQLCIPHER_KEY", raising=False)

    from mahavishnu.core.health_aggregator import _probe_storage_state

    state = _probe_storage_state()

    assert state.errors_total == 0
    assert state.ingester_running is True
    assert state.cycles_total == 1


def test_storage_feed_counts_the_live_kv_store(
    monkeypatch: pytest.MonkeyPatch,
    fresh_kv_store: Any,
) -> None:
    """``entities_count`` reflects the store the server actually serves.

    The old probe hardcoded ``1 if healthy else 0``, which described
    the probe rather than the feed.
    """
    monkeypatch.delenv("SQLCIPHER_KEY", raising=False)

    from mahavishnu.core.health_aggregator import _probe_storage_state

    assert _probe_storage_state().entities_count == 0
    fresh_kv_store.put("health-probe-key", "value")
    assert _probe_storage_state().entities_count == 1


# ---------------------------------------------------------------------------
# The HTTP route must serve the canonical aggregator's verdict.
# ---------------------------------------------------------------------------


def test_http_health_route_serves_the_canonical_feeds(server: FastMCPServer) -> None:
    """``GET /health`` must aggregate the canonical per-feed state.

    The route used to answer from three hand-picked feeds and never
    called the aggregator, so the canonical feeds were invisible to
    every HTTP consumer.
    """
    client = TestClient(server.server.http_app())
    response = client.get("/health")
    body = response.json()

    assert "canonical_status" in body, (
        f"GET /health must expose the canonical aggregator verdict; got keys {sorted(body)}"
    )
    assert "canonical_checks" in body
    assert CANONICAL_FEEDS.issubset(set(body["canonical_checks"]))


# ---------------------------------------------------------------------------
# Parity — the two surfaces must not disagree.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_get_health_body_matches_http_route(server: FastMCPServer) -> None:
    """MCP body and HTTP body must agree field-for-field.

    ``uptime_seconds`` and ``aggregate_duration_ms`` are excluded: the
    clock advances and the aggregator takes a few microseconds between
    the two calls.
    """
    client = TestClient(server.server.http_app())
    http_response = client.get("/health")
    http_body = http_response.json()

    async with Client(server.server) as mcp_client:
        result = await mcp_client.call_tool("get_health", {})

    assert result.is_error is False
    mcp_body = result.structured_content
    assert mcp_body is not None

    for field in ("status", "service", "version", "canonical_status"):
        assert mcp_body[field] == http_body[field], (
            f"MCP/HTTP drift on {field!r}: MCP={mcp_body[field]!r} HTTP={http_body[field]!r}"
        )

    assert _stable(mcp_body["canonical_checks"]) == _stable(http_body["canonical_checks"])
    assert set(mcp_body["checks"]) == set(http_body["checks"])

    assert mcp_body["http_status"] == http_response.status_code


@pytest.mark.asyncio
async def test_both_surfaces_report_the_same_http_status(
    server: FastMCPServer,
) -> None:
    """The HTTP code the MCP tool mirrors must be the code it serves."""
    client = TestClient(server.server.http_app())
    http_response = client.get("/health")

    async with Client(server.server) as mcp_client:
        result = await mcp_client.call_tool("get_health", {})

    assert result.structured_content is not None
    assert result.structured_content["http_status"] == http_response.status_code
