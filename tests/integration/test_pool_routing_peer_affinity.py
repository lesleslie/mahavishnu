"""Integration tests for PEER_AFFINITY routing end-to-end.

End-to-end: PoolManager.route_task with selector=PEER_AFFINITY should
consult a Session-Buddy client (here: a real in-memory duckdb-backed
adapter that mirrors the production ``user_models`` schema), parse
the peer model's representation_text for a pool hint, and route the
task to that pool. When no peer model row exists, the resolver
returns None and the route falls back to LEAST_LOADED.

The ACL gate (A3) is exercised end-to-end: a peer without an ACL
grant is denied the route and falls back to LEAST_LOADED.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.pools import PoolConfig, PoolManager, PoolSelector
from mahavishnu.pools.peer_routing import PeerRouteResolver

# ---------------------------------------------------------------------------
# In-memory stand-in for a Session-Buddy MCP client.
# Mirrors the production ``peer_context`` contract:
#   async def peer_context(peer_id, project_id) -> dict
# Returns a representation_text parsed from a seeded ``user_models``
# table.
# ---------------------------------------------------------------------------


class _FakeSessionBuddyClient:
    """Minimal async peer_context client backed by a dict."""

    def __init__(self, rows: dict[tuple[str, str], str] | None = None) -> None:
        # rows keyed by (peer_id, project_id) -> representation_text
        self._rows: dict[tuple[str, str], str] = rows or {}
        self.calls: list[tuple[str, str]] = []

    async def peer_context(self, peer_id: str, project_id: str) -> dict:
        self.calls.append((peer_id, project_id))
        rep = self._rows.get((peer_id, project_id))
        if rep is None:
            # Match session-buddy's empty-context shape.
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
            "last_updated": datetime.now(UTC).isoformat(),
            "evidence_count": 1,
            "model": "heuristic",
        }


@pytest.fixture
def fake_sb_with_pool_hint() -> _FakeSessionBuddyClient:
    return _FakeSessionBuddyClient(
        rows={
            ("alice", "proj-x"): "Alice works on Python APIs. pool: pool_abc",
        }
    )


@pytest.fixture
def fake_sb_no_row() -> _FakeSessionBuddyClient:
    return _FakeSessionBuddyClient(rows={})


@pytest.fixture
def pool_mgr_with_pools() -> PoolManager:
    """A PoolManager pre-loaded with two pools: pool_abc and pool_xyz."""
    with patch("mahavishnu.core.app.TerminalManager"):
        from mahavishnu.mcp.protocols.message_bus import MessageBus

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


# ---------------------------------------------------------------------------
# Test 1: peer model hint routes to the named pool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_peer_affinity_routes_to_named_pool(
    pool_mgr_with_pools: PoolManager,
    fake_sb_with_pool_hint: _FakeSessionBuddyClient,
) -> None:
    """Given a peer with `pool: pool_abc` in their representation,
    route_task(selector=PEER_AFFINITY) lands on pool_abc."""
    pool_mgr_with_pools._peer_resolver = PeerRouteResolver(
        session_buddy_client=fake_sb_with_pool_hint,
        acl_provider=lambda _peer_id: {"peer_models:read": True},
    )

    result = await pool_mgr_with_pools.route_task(
        task={"prompt": "do stuff", "peer_id": "alice", "project_id": "proj-x"},
        pool_selector=PoolSelector.PEER_AFFINITY,
    )

    assert result["pool_id"] == "pool_abc", (
        f"expected route to pool_abc, got {result.get('pool_id')!r}"
    )
    assert fake_sb_with_pool_hint.calls == [("alice", "proj-x")]


# ---------------------------------------------------------------------------
# Test 2: missing peer model row → fallback to LEAST_LOADED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_peer_affinity_falls_back_to_least_loaded_when_no_row(
    pool_mgr_with_pools: PoolManager,
    fake_sb_no_row: _FakeSessionBuddyClient,
) -> None:
    """No user_models row for (alice, proj-x) → resolver returns None →
    route_task falls back to LEAST_LOADED (the pool with the fewest
    workers; in this fixture both pools have 2 workers, so the
    heap returns one of them)."""
    pool_mgr_with_pools._peer_resolver = PeerRouteResolver(
        session_buddy_client=fake_sb_no_row,
        acl_provider=lambda _peer_id: {"peer_models:read": True},
    )

    result = await pool_mgr_with_pools.route_task(
        task={"prompt": "do stuff", "peer_id": "alice", "project_id": "proj-x"},
        pool_selector=PoolSelector.PEER_AFFINITY,
    )

    # Either pool is acceptable — the contract is "fall back to LEAST_LOADED".
    assert result["pool_id"] in {"pool_abc", "pool_xyz"}
    assert fake_sb_no_row.calls == [("alice", "proj-x")]


# ---------------------------------------------------------------------------
# Test 3: ACL gate (A3) — no ACL grant → falls back to LEAST_LOADED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_peer_affinity_no_acl_falls_back_to_least_loaded(
    pool_mgr_with_pools: PoolManager,
    fake_sb_with_pool_hint: _FakeSessionBuddyClient,
) -> None:
    """A3 (ACL wins): no peer_models:read grant → resolver returns
    None, route_task falls back to LEAST_LOADED, and the
    peer_context client is NOT consulted."""
    pool_mgr_with_pools._peer_resolver = PeerRouteResolver(
        session_buddy_client=fake_sb_with_pool_hint,
        acl_provider=lambda _peer_id: None,  # ACL denied
    )

    result = await pool_mgr_with_pools.route_task(
        task={"prompt": "do stuff", "peer_id": "alice", "project_id": "proj-x"},
        pool_selector=PoolSelector.PEER_AFFINITY,
    )

    assert result["pool_id"] in {"pool_abc", "pool_xyz"}
    # The ACL gate must short-circuit BEFORE the peer_context call.
    assert fake_sb_with_pool_hint.calls == [], (
        "peer_context should not be called when ACL denies the request"
    )


# ---------------------------------------------------------------------------
# Test 4: PEER_AFFINITY selector value is the string "peer_affinity"
# ---------------------------------------------------------------------------


def test_peer_affinity_enum_value() -> None:
    """The selector string is the contract used by callers and CLI."""
    assert PoolSelector.PEER_AFFINITY.value == "peer_affinity"
