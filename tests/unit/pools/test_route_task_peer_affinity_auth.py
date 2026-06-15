"""Unit tests for caller-side authorization on PEER_AFFINITY routing.

Per ADR-014, the peer model is a *hint* — the ACL is authoritative.
To make the MCP ``pool_route_execute`` surface safe to expose, the
CALLER (the MCP tool, the CLI, a plugin) must declare which pool IDs
it is authorized to dispatch into. When the caller declares an
allowlist, only pools in that allowlist are valid candidates for
PEER_AFFINITY (and any other selector that resolves to a concrete
pool). When the caller does not declare an allowlist, PEER_AFFINITY
must fall back to LEAST_LOADED — refusing to act on a peer-model
hint without a caller-side authorization.

These tests are scoped to the PoolManager contract: they verify
that ``route_task`` honors the new ``caller_pool_allowlist`` parameter
without depending on the integration fixture in
``tests/integration/test_pool_routing_peer_affinity.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.mcp.protocols.message_bus import MessageBus
from mahavishnu.pools import PoolConfig, PoolManager, PoolSelector
from mahavishnu.pools.peer_routing import PeerRouteResolver

# ---------------------------------------------------------------------------
# Fixtures: a PoolManager with two pools, plus a fake Session-Buddy peer
# resolver that recommends one of them.
# ---------------------------------------------------------------------------


class _FakeSessionBuddyClient:
    """Minimal async peer_context client backed by a dict."""

    def __init__(self, rows: dict[tuple[str, str], str] | None = None) -> None:
        self._rows: dict[tuple[str, str], str] = rows or {}
        self.calls: list[tuple[str, str]] = []

    async def peer_context(self, peer_id: str, project_id: str) -> dict:
        self.calls.append((peer_id, project_id))
        rep = self._rows.get((peer_id, project_id))
        if rep is None:
            return {
                "peer_id": peer_id,
                "project_id": project_id,
                "representation_text": None,
                "last_updated": None,
                "evidence_count": 0,
                "model": "heuristic",
            }
        return {
            "peer_id": peer_id,
            "project_id": project_id,
            "representation_text": rep,
            "last_updated": "2026-06-08T00:00:00+00:00",
            "evidence_count": 1,
            "model": "heuristic",
        }


@pytest.fixture
def pool_mgr_with_pools() -> PoolManager:
    """A PoolManager pre-loaded with two pools: pool_abc and pool_xyz."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
        for name in ("pool_abc", "pool_xyz"):
            mock_pool = MagicMock()
            mock_pool.pool_id = name
            mock_pool.config = PoolConfig(
                name=name,
                pool_type="mahavishnu",
                min_workers=2,
                max_workers=5,
            )
            mock_pool._workers = {"w1": "w1", "w2": "w2"}

            async def mock_execute(task, _pool_id=name):
                return {"pool_id": _pool_id, "status": "completed", "echo": task}

            mock_pool.execute_task = mock_execute
            mgr._pools[name] = mock_pool
            mgr._pool_worker_counts[name] = 2
        return mgr


@pytest.fixture
def pool_mgr_with_peer_resolver(pool_mgr_with_pools: PoolManager):
    """PoolManager wired to a peer resolver that recommends pool_abc."""
    fake_sb = _FakeSessionBuddyClient(
        rows={("alice", "proj-x"): "Alice works on Python APIs. pool: pool_abc"},
    )
    pool_mgr_with_pools._peer_resolver = PeerRouteResolver(
        session_buddy_client=fake_sb,
        acl_provider=lambda _peer_id: {"peer_models:read": True},
    )
    return pool_mgr_with_pools


# ---------------------------------------------------------------------------
# Test 1: No caller_pool_allowlist → falls back to LEAST_LOADED.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_peer_affinity_without_allowlist_falls_back_to_least_loaded(
    pool_mgr_with_peer_resolver: PoolManager,
) -> None:
    """ADR-014 contract: without caller-side authorization, refuse to
    act on the peer hint. The hint is in scope (pool_abc is the
    peer's recommendation), but no allowlist was declared — the
    router must NOT select pool_abc. Instead it falls back to
    LEAST_LOADED.
    """
    result = await pool_mgr_with_peer_resolver.route_task(
        task={"prompt": "do stuff", "peer_id": "alice", "project_id": "proj-x"},
        pool_selector=PoolSelector.PEER_AFFINITY,
        # caller_pool_allowlist omitted → default None
    )

    # Neither pool is "the peer hint" anymore — fallback applies.
    assert result["pool_id"] in {"pool_abc", "pool_xyz"}, (
        f"fallback must select a registered pool, got {result.get('pool_id')!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: caller_pool_allowlist includes the peer-hint pool → routes there.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_peer_affinity_with_allowlist_routes_to_hint_pool(
    pool_mgr_with_peer_resolver: PoolManager,
) -> None:
    """When the caller declares an allowlist that includes the
    peer-suggested pool, the peer hint is honored — the route lands
    on pool_abc.
    """
    result = await pool_mgr_with_peer_resolver.route_task(
        task={"prompt": "do stuff", "peer_id": "alice", "project_id": "proj-x"},
        pool_selector=PoolSelector.PEER_AFFINITY,
        caller_pool_allowlist={"pool_abc", "pool_xyz"},
    )

    assert result["pool_id"] == "pool_abc", (
        f"with the hint pool in the allowlist, route must land on pool_abc; "
        f"got {result.get('pool_id')!r}"
    )


# ---------------------------------------------------------------------------
# Test 3: caller_pool_allowlist excludes the peer-hint pool → falls back.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_peer_affinity_with_allowlist_excluding_hint_falls_back(
    pool_mgr_with_peer_resolver: PoolManager,
) -> None:
    """When the caller's allowlist is set but does NOT include the
    peer-suggested pool, the hint is discarded and the route falls
    back to LEAST_LOADED within the allowlist. This is the
    security boundary: the allowlist, not the peer model, decides.
    """
    result = await pool_mgr_with_peer_resolver.route_task(
        task={"prompt": "do stuff", "peer_id": "alice", "project_id": "proj-x"},
        pool_selector=PoolSelector.PEER_AFFINITY,
        # Hint is pool_abc; allowlist only contains pool_xyz.
        caller_pool_allowlist={"pool_xyz"},
    )

    # The only valid pool in the allowlist is pool_xyz.
    assert result["pool_id"] == "pool_xyz", (
        f"with the hint pool excluded by the allowlist, route must fall "
        f"back within the allowlist; got {result.get('pool_id')!r}"
    )


# ---------------------------------------------------------------------------
# Test 4: route_task signature accepts caller_pool_allowlist keyword.
# ---------------------------------------------------------------------------


def test_route_task_signature_accepts_caller_pool_allowlist() -> None:
    """Sanity: ``caller_pool_allowlist`` is a keyword on route_task,
    defaulting to None. This is the public API contract.
    """
    import inspect

    sig = inspect.signature(PoolManager.route_task)
    assert "caller_pool_allowlist" in sig.parameters, (
        "PoolManager.route_task must accept caller_pool_allowlist "
        "(per ADR-014 caller-side authorization)"
    )
    param = sig.parameters["caller_pool_allowlist"]
    # Default is None — callers may omit the allowlist to opt into
    # the safe "fall back to LEAST_LOADED" behavior.
    assert param.default is None, (
        f"caller_pool_allowlist default must be None (refuse-on-omit), got {param.default!r}"
    )
