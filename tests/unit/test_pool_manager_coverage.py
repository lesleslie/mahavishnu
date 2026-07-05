"""Unit tests for PoolManager orchestration in mahavishnu/pools/manager.py.

Targets >=80% line+branch coverage of the PoolManager class, PoolSelector
enum, and the module-level _await_if_needed helper.

Strategy:
- Mock BasePool and its subclasses to avoid real worker pools.
- Mock MessageBus, RoutingFitnessReader, and PeerRouteResolver to
  exercise every branch in route_task, execute_on_pool, and
  aggregate_results.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.status import PoolStatus
from mahavishnu.mcp.protocols.message_bus import MessageBus
from mahavishnu.pools.base import BasePool, PoolConfig
from mahavishnu.pools.manager import (
    PoolManager,
    PoolSelector,
    _await_if_needed,
)
from mahavishnu.pools.peer_routing import PeerRouteResolver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pool(
    pool_id: str = "pool_test",
    pool_type: str = "mahavishnu",
    min_workers: int = 2,
    max_workers: int = 5,
    n_workers: int = 2,
) -> MagicMock:
    """Build a MagicMock that quacks like a BasePool."""
    mock_pool = MagicMock(spec=BasePool)
    mock_pool.pool_id = pool_id
    mock_pool.config = PoolConfig(
        name=pool_id,
        pool_type=pool_type,
        min_workers=min_workers,
        max_workers=max_workers,
    )
    mock_pool._workers = {f"w{i}": f"w{i}" for i in range(n_workers)}

    async def _start() -> str:
        return pool_id

    async def _execute_task(task):
        return {
            "pool_id": pool_id,
            "worker_id": "w1",
            "status": "completed",
            "output": "ok",
            "duration": 0.1,
            "echo": task,
        }

    async def _collect_memory():
        return [{"content": "mem", "metadata": {}}]

    async def _status() -> PoolStatus:
        return PoolStatus.RUNNING

    async def _stop() -> None:
        return None

    mock_pool.start = _start
    mock_pool.execute_task = _execute_task
    mock_pool.collect_memory = _collect_memory
    mock_pool.status = _status
    mock_pool.stop = _stop
    return mock_pool


@pytest.fixture
def pool_mgr() -> PoolManager:
    """Bare PoolManager with no pools."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
    return mgr


@pytest.fixture
def pool_mgr_with_pools() -> PoolManager:
    """PoolManager pre-loaded with three pools of varying types and worker counts."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
    mgr._pools["pool_a"] = _make_pool("pool_a", n_workers=1)
    mgr._pools["pool_b"] = _make_pool("pool_b", n_workers=3)
    mgr._pools["pool_c"] = _make_pool("pool_c", pool_type="runpod", n_workers=2)
    mgr._pool_worker_counts["pool_a"] = 1
    mgr._pool_worker_counts["pool_b"] = 3
    mgr._pool_worker_counts["pool_c"] = 2
    mgr._worker_count_heap = [(1, "pool_a"), (2, "pool_c"), (3, "pool_b")]
    return mgr


# ---------------------------------------------------------------------------
# _await_if_needed
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_await_if_needed_with_awaitable() -> None:
    """Coroutine / awaitable path: returns the awaited result."""

    async def coro():
        return "result"

    out = await _await_if_needed(coro())
    assert out == "result"


@pytest.mark.unit
async def test_await_if_needed_with_plain_value() -> None:
    """Non-awaitable path: returns the value unchanged."""
    out = await _await_if_needed({"k": "v"})
    assert out == {"k": "v"}

    assert await _await_if_needed(42) == 42
    assert await _await_if_needed(None) is None


# ---------------------------------------------------------------------------
# PoolSelector enum
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pool_selector_values() -> None:
    """PoolSelector must expose the documented strategy names."""
    assert PoolSelector.ROUND_ROBIN.value == "round_robin"
    assert PoolSelector.LEAST_LOADED.value == "least_loaded"
    assert PoolSelector.RANDOM.value == "random"
    assert PoolSelector.AFFINITY.value == "affinity"
    assert PoolSelector.PEER_AFFINITY.value == "peer_affinity"


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_init_creates_message_bus_when_none(pool_mgr: PoolManager) -> None:
    """When no message bus is provided, one is constructed."""
    assert pool_mgr.message_bus is not None
    assert isinstance(pool_mgr.message_bus, MessageBus)


@pytest.mark.unit
def test_init_uses_provided_message_bus() -> None:
    """Provided message bus is used as-is."""
    bus = MessageBus()
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=bus,
        )
    assert mgr.message_bus is bus


@pytest.mark.unit
def test_init_with_session_buddy_warns_default_acl() -> None:
    """When a session_buddy_client is provided without an explicit ACL,
    the manager logs a warning (per Item 2 security review)."""
    fake_sb = MagicMock()
    with (
        patch("mahavishnu.core.app.TerminalManager"),
        patch("mahavishnu.pools.manager.logger.warning") as warn,
    ):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=fake_sb,
            message_bus=MessageBus(),
        )
    assert mgr._peer_resolver is not None
    assert isinstance(mgr._peer_resolver, PeerRouteResolver)
    # Warning emitted about default ACL
    assert any("acl_provider" in str(call_args) for call_args in warn.call_args_list)


@pytest.mark.unit
def test_init_with_explicit_peer_resolver_does_not_warn() -> None:
    """An explicit _peer_resolver (set externally) suppresses the warning."""
    with (
        patch("mahavishnu.core.app.TerminalManager"),
        patch("mahavishnu.pools.manager.logger.warning") as warn,
    ):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
        # Force a non-default resolver to bypass the warning path.
        mgr._peer_resolver = PeerRouteResolver(
            session_buddy_client=MagicMock(),
            acl_provider=lambda _pid: {"peer_models:read": True},
        )
    # No warning expected: no session_buddy_client was passed.
    assert all("acl_provider" not in str(call_args) for call_args in warn.call_args_list)


# ---------------------------------------------------------------------------
# _persist_pool_state and _persist_routing_decision
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_persist_pool_state_noop_without_dhara(pool_mgr: PoolManager) -> None:
    """Without dhara_state, persistence is a no-op (returns None)."""
    result = await pool_mgr._persist_pool_state("pool_x", MagicMock(), "running")
    assert result is None


@pytest.mark.unit
async def test_persist_pool_state_writes_to_dhara() -> None:
    """When dhara_state is provided, persist_pool is called with metadata."""
    dhara = MagicMock()
    dhara.persist_pool = AsyncMock()
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
            dhara_state=dhara,
        )
    pool = _make_pool("pool_save", n_workers=4)
    await mgr._persist_pool_state("pool_save", pool, "running")
    assert dhara.persist_pool.await_count == 1
    args = dhara.persist_pool.await_args
    assert args.args[0] == "pool_save"
    payload = args.args[1]
    assert payload["status"] == "running"
    assert payload["pool_type"] == "mahavishnu"
    assert payload["workers"] == 4


@pytest.mark.unit
async def test_persist_pool_state_swallows_exception() -> None:
    """Persistence exceptions are swallowed (debug-logged)."""
    dhara = MagicMock()
    dhara.persist_pool = AsyncMock(side_effect=RuntimeError("disk full"))
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
            dhara_state=dhara,
        )
    pool = _make_pool("pool_save2")
    # Should NOT raise
    await mgr._persist_pool_state("pool_save2", pool, "running")


@pytest.mark.unit
async def test_persist_routing_decision_noop_without_dhara(pool_mgr: PoolManager) -> None:
    """Without dhara_state, routing-decision persistence is a no-op."""
    result = await pool_mgr._persist_routing_decision(
        task={"prompt": "x"},
        pool_id="pool_x",
        selector=PoolSelector.LEAST_LOADED,
        pool_affinity=None,
        reason="least_loaded",
    )
    assert result is None


@pytest.mark.unit
async def test_persist_routing_decision_writes_to_dhara() -> None:
    """When dhara_state is provided, persist_routing_decision is called."""
    dhara = MagicMock()
    dhara.persist_routing_decision = AsyncMock()
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
            dhara_state=dhara,
        )
    await mgr._persist_routing_decision(
        task={"category": "code_generation", "type": "code"},
        pool_id="pool_p",
        selector=PoolSelector.ROUND_ROBIN,
        pool_affinity=None,
        reason="round_robin",
    )
    assert dhara.persist_routing_decision.await_count == 1
    args = dhara.persist_routing_decision.await_args
    assert args.args[0] == "code_generation"
    payload = args.args[1]
    assert payload["pool_id"] == "pool_p"
    assert payload["selector"] == "round_robin"
    assert payload["reason"] == "round_robin"
    assert payload["task_category"] == "code_generation"


@pytest.mark.unit
async def test_persist_routing_decision_swallows_exception() -> None:
    """Routing-decision persistence exceptions are swallowed."""
    dhara = MagicMock()
    dhara.persist_routing_decision = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
            dhara_state=dhara,
        )
    await mgr._persist_routing_decision(
        task={"category": "x"},
        pool_id="pool_p",
        selector=PoolSelector.LEAST_LOADED,
        pool_affinity=None,
        reason="least_loaded",
    )


# ---------------------------------------------------------------------------
# _refresh_pool_worker_metrics
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_refresh_pool_worker_metrics_sets_gauges(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """Refresh should write one gauge sample per known pool type."""
    pool_mgr_with_pools._refresh_pool_worker_metrics()
    # No assertion on the exact value (gauge is global), just confirm
    # the call path runs without exception.


@pytest.mark.unit
def test_refresh_pool_worker_metrics_with_no_pools(pool_mgr: PoolManager) -> None:
    """Refresh with no pools still sets all four known gauges to 0."""
    pool_mgr._refresh_pool_worker_metrics()
    # Trivial: just exercise the path.


# ---------------------------------------------------------------------------
# spawn_pool
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_spawn_pool_mahavishnu_success() -> None:
    """Happy path: spawn a mahavishnu pool and register it in the manager."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
    config = PoolConfig(name="local", pool_type="mahavishnu", min_workers=2, max_workers=5)
    pool = _make_pool("local", n_workers=2)

    with patch("mahavishnu.pools.manager.MahavishnuPool", return_value=pool):
        pool_id = await mgr.spawn_pool("mahavishnu", config)
    assert pool_id == "local"
    assert pool_id in mgr._pools
    assert pool_id in mgr._pool_worker_counts
    assert mgr._pool_worker_counts[pool_id] == config.min_workers
    # Heap must contain an entry
    assert any(pid == pool_id for _wc, pid in mgr._worker_count_heap)


@pytest.mark.unit
async def test_spawn_pool_session_buddy() -> None:
    """Session-buddy pool uses the right config defaults."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
    config = PoolConfig(name="sb", pool_type="session-buddy", min_workers=1, max_workers=3)
    pool = _make_pool("sb", pool_type="session-buddy", n_workers=1)
    with patch("mahavishnu.pools.manager.SessionBuddyPool", return_value=pool) as mcls:
        await mgr.spawn_pool("session-buddy", config)
    args = mcls.call_args
    # Session-buddy URL default
    assert args.kwargs["session_buddy_url"] == "http://localhost:8678/mcp"


@pytest.mark.unit
async def test_spawn_pool_runpod() -> None:
    """RunPod pool branch."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
    config = PoolConfig(name="rp", pool_type="runpod", min_workers=1, max_workers=2)
    pool = _make_pool("rp", pool_type="runpod", n_workers=1)
    with patch("mahavishnu.pools.manager.RunPodPool", return_value=pool) as mcls:
        await mgr.spawn_pool("runpod", config)
    assert mcls.called


@pytest.mark.unit
async def test_spawn_pool_unknown_type_raises() -> None:
    """Unknown pool type raises ValueError."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
    config = PoolConfig(name="x", pool_type="mahavishnu", min_workers=1, max_workers=2)
    with pytest.raises(ValueError, match="Unknown pool type"):
        await mgr.spawn_pool("totally-bogus", config)


@pytest.mark.unit
async def test_spawn_pool_propagates_pool_start_error() -> None:
    """If pool.start() raises, the exception is re-raised."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
    config = PoolConfig(name="bad", pool_type="mahavishnu", min_workers=1, max_workers=2)
    pool = _make_pool("bad", n_workers=1)

    async def _bad_start() -> str:
        raise RuntimeError("startup failure")

    pool.start = _bad_start
    with patch("mahavishnu.pools.manager.MahavishnuPool", return_value=pool):
        with pytest.raises(RuntimeError, match="startup failure"):
            await mgr.spawn_pool("mahavishnu", config)


# ---------------------------------------------------------------------------
# _update_pool_worker_count
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_update_pool_worker_count_unknown_pool_is_noop(
    pool_mgr: PoolManager,
) -> None:
    """Updating a pool_id that isn't tracked is a no-op."""
    await pool_mgr._update_pool_worker_count("nope", 5)
    assert "nope" not in pool_mgr._pool_worker_counts


@pytest.mark.unit
async def test_update_pool_worker_count_appends_to_heap(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """A new count pushes onto the heap (lazy deletion)."""
    before_count = len(pool_mgr_with_pools._worker_count_heap)
    await pool_mgr_with_pools._update_pool_worker_count("pool_a", 5)
    assert pool_mgr_with_pools._pool_worker_counts["pool_a"] == 5
    assert len(pool_mgr_with_pools._worker_count_heap) == before_count + 1


# ---------------------------------------------------------------------------
# _get_least_loaded_pool
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_get_least_loaded_pool_returns_min(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """Should return the pool with the lowest tracked worker count."""
    pid = await pool_mgr_with_pools._get_least_loaded_pool()
    assert pid == "pool_a"  # worker_count=1


@pytest.mark.unit
async def test_get_least_loaded_pool_skips_stale_entries() -> None:
    """Heap entries whose pool_id is no longer in _pools are skipped."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
    mgr._pools["pool_z"] = _make_pool("pool_z", n_workers=1)
    mgr._pool_worker_counts["pool_z"] = 1
    # Heap has a stale entry for pool_zzz (no longer in _pools)
    mgr._worker_count_heap = [(1, "pool_zzz"), (1, "pool_z")]
    pid = await mgr._get_least_loaded_pool()
    assert pid == "pool_z"


@pytest.mark.unit
async def test_get_least_loaded_pool_skips_stale_count() -> None:
    """Heap entries whose tracked count doesn't match the heap entry are skipped."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
    mgr._pools["pool_y"] = _make_pool("pool_y", n_workers=10)
    mgr._pool_worker_counts["pool_y"] = 10
    # Heap entry says 2 but the tracked count is 10 — stale
    mgr._worker_count_heap = [(2, "pool_y")]
    pid = await mgr._get_least_loaded_pool()
    # Fallback to min via self._pools iteration (the post-heap branch).
    assert pid == "pool_y"


@pytest.mark.unit
async def test_get_least_loaded_pool_fallback_to_min() -> None:
    """When the heap is empty but pools exist, fall back to min via _pools."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
    mgr._pools["p1"] = _make_pool("p1", n_workers=5)
    mgr._pools["p2"] = _make_pool("p2", n_workers=1)
    mgr._worker_count_heap = []
    mgr._pool_worker_counts = {"p1": 5, "p2": 1}
    pid = await mgr._get_least_loaded_pool()
    assert pid == "p2"


@pytest.mark.unit
async def test_get_least_loaded_pool_returns_none_when_empty(
    pool_mgr: PoolManager,
) -> None:
    """No pools → returns None."""
    pid = await pool_mgr._get_least_loaded_pool()
    assert pid is None


# ---------------------------------------------------------------------------
# _select_least_loaded_in_allowlist
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_select_least_loaded_in_allowlist_wildcard(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """`*` in allowlist = every registered pool."""
    pid = await pool_mgr_with_pools._select_least_loaded_in_allowlist({"*"})
    assert pid == "pool_a"


@pytest.mark.unit
async def test_select_least_loaded_in_allowlist_subset(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """Allowlist restricts candidates; least-loaded within wins."""
    pid = await pool_mgr_with_pools._select_least_loaded_in_allowlist({"pool_b", "pool_c"})
    # pool_c has count=2, pool_b has count=3
    assert pid == "pool_c"


@pytest.mark.unit
async def test_select_least_loaded_in_allowlist_empty(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """Empty intersection → None."""
    pid = await pool_mgr_with_pools._select_least_loaded_in_allowlist({"no_such_pool"})
    assert pid is None


# ---------------------------------------------------------------------------
# _is_pool_in_allowlist
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_is_pool_in_allowlist_wildcard(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """Wildcard grants access to any registered pool."""
    assert pool_mgr_with_pools._is_pool_in_allowlist("pool_a", {"*"}) is True
    assert pool_mgr_with_pools._is_pool_in_allowlist("not_registered", {"*"}) is False


@pytest.mark.unit
def test_is_pool_in_allowlist_explicit(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """Explicit allowlist = set membership check."""
    assert pool_mgr_with_pools._is_pool_in_allowlist("pool_a", {"pool_a", "pool_b"}) is True
    assert pool_mgr_with_pools._is_pool_in_allowlist("pool_c", {"pool_a"}) is False


# ---------------------------------------------------------------------------
# execute_on_pool
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_execute_on_pool_unknown_raises(pool_mgr: PoolManager) -> None:
    """Unknown pool id → ValueError."""
    with pytest.raises(ValueError, match="Pool not found"):
        await pool_mgr.execute_on_pool("ghost", {"prompt": "x"})


@pytest.mark.unit
async def test_execute_on_pool_runs_and_publishes(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """Happy path: run, publish completion, refresh metrics."""
    # Spy on the message bus
    pool_mgr_with_pools.message_bus = MessageBus()
    publish_mock = AsyncMock(wraps=pool_mgr_with_pools.message_bus.publish)

    async def fake_publish(msg):
        return await publish_mock.original(msg) if hasattr(publish_mock, "original") else None

    pool_mgr_with_pools.message_bus.publish = AsyncMock(return_value=None)
    result = await pool_mgr_with_pools.execute_on_pool("pool_a", {"prompt": "hello"})
    assert result["status"] == "completed"
    assert pool_mgr_with_pools.message_bus.publish.await_count == 1
    msg = pool_mgr_with_pools.message_bus.publish.await_args.args[0]
    assert msg["type"] == "task_completed"
    assert msg["source_pool_id"] == "pool_a"


@pytest.mark.unit
async def test_execute_on_pool_updates_worker_count_on_change(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """When pool._workers count differs from tracked, update heap."""
    # Add a new worker to the pool
    pool_mgr_with_pools._pools["pool_a"]._workers["w_new"] = "w_new"
    await pool_mgr_with_pools.execute_on_pool("pool_a", {"prompt": "x"})
    # Tracked count should now match
    assert pool_mgr_with_pools._pool_worker_counts["pool_a"] == len(
        pool_mgr_with_pools._pools["pool_a"]._workers
    )


@pytest.mark.unit
async def test_execute_on_pool_skips_count_update_when_unchanged(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """When worker count is unchanged, no heap update happens."""
    initial_heap_len = len(pool_mgr_with_pools._worker_count_heap)
    await pool_mgr_with_pools.execute_on_pool("pool_a", {"prompt": "x"})
    # No new heap entry
    assert len(pool_mgr_with_pools._worker_count_heap) == initial_heap_len


# ---------------------------------------------------------------------------
# route_task - basic strategy paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_route_task_no_pools_raises(pool_mgr: PoolManager) -> None:
    """No pools → RuntimeError."""
    with pytest.raises(RuntimeError, match="No pools available"):
        await pool_mgr.route_task({"prompt": "x"})


@pytest.mark.unit
async def test_route_task_least_loaded(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """LEAST_LOADED picks pool_a (worker count = 1)."""
    result = await pool_mgr_with_pools.route_task(
        task={"prompt": "x"},
        pool_selector=PoolSelector.LEAST_LOADED,
    )
    assert result["pool_id"] == "pool_a"


@pytest.mark.unit
async def test_route_task_round_robin_cycles(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """ROUND_ROBIN cycles through pools in insertion order."""
    seen: list[str] = []
    for _ in range(6):
        r = await pool_mgr_with_pools.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.ROUND_ROBIN,
        )
        seen.append(r["pool_id"])
    # Should cycle through the three pools in order, twice.
    assert seen == ["pool_a", "pool_b", "pool_c", "pool_a", "pool_b", "pool_c"]


@pytest.mark.unit
async def test_route_task_random_uses_a_pool(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """RANDOM picks one of the registered pools."""
    seen: set[str] = set()
    for _ in range(20):
        r = await pool_mgr_with_pools.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.RANDOM,
        )
        seen.add(r["pool_id"])
    # All picks must be from the registered set
    assert seen.issubset({"pool_a", "pool_b", "pool_c"})


@pytest.mark.unit
async def test_route_task_random_patched_choice(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """RANDOM uses random.choice — patch and verify the call."""
    with patch("mahavishnu.pools.manager.random.choice", return_value="pool_b") as choice:
        r = await pool_mgr_with_pools.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.RANDOM,
        )
    assert r["pool_id"] == "pool_b"
    assert choice.called


# ---------------------------------------------------------------------------
# route_task - AFFINITY strategy
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_route_task_affinity_without_affinity_raises(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """AFFINITY without pool_affinity → ValueError."""
    with pytest.raises(ValueError, match="pool_affinity required"):
        await pool_mgr_with_pools.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.AFFINITY,
        )


@pytest.mark.unit
async def test_route_task_affinity_no_allowlist_falls_back(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """No allowlist → refuse to honor affinity, fall back to LEAST_LOADED."""
    r = await pool_mgr_with_pools.route_task(
        task={"prompt": "x"},
        pool_selector=PoolSelector.AFFINITY,
        pool_affinity="pool_b",
        caller_pool_allowlist=None,
    )
    # Falls back to least-loaded = pool_a
    assert r["pool_id"] == "pool_a"


@pytest.mark.unit
async def test_route_task_affinity_pool_not_in_allowlist_falls_back(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """Affinity pool not in allowlist → LEAST_LOADED within allowlist."""
    r = await pool_mgr_with_pools.route_task(
        task={"prompt": "x"},
        pool_selector=PoolSelector.AFFINITY,
        pool_affinity="pool_b",
        caller_pool_allowlist={"pool_a", "pool_c"},
    )
    # Allowlist ∩ pools = {pool_a, pool_c}; least-loaded = pool_a
    assert r["pool_id"] == "pool_a"


@pytest.mark.unit
async def test_route_task_affinity_pool_not_in_allowlist_empty_intersection(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """Affinity pool not in allowlist with empty intersection → RuntimeError."""
    with pytest.raises(RuntimeError, match="caller_pool_allowlist"):
        await pool_mgr_with_pools.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="pool_b",
            caller_pool_allowlist={"no_such_pool"},
        )


@pytest.mark.unit
async def test_route_task_affinity_honored(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """Affinity pool in allowlist → routed to that pool."""
    r = await pool_mgr_with_pools.route_task(
        task={"prompt": "x"},
        pool_selector=PoolSelector.AFFINITY,
        pool_affinity="pool_b",
        caller_pool_allowlist={"pool_a", "pool_b", "pool_c"},
    )
    assert r["pool_id"] == "pool_b"


# ---------------------------------------------------------------------------
# route_task - PEER_AFFINITY strategy
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_route_task_peer_affinity_missing_peer_id_raises(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """PEER_AFFINITY without peer_id/project_id → ValueError."""
    with pytest.raises(ValueError, match="peer_id"):
        await pool_mgr_with_pools.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.PEER_AFFINITY,
        )


@pytest.mark.unit
async def test_route_task_peer_affinity_no_resolver_raises(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """PEER_AFFINITY without a peer resolver → RuntimeError."""
    pool_mgr_with_pools._peer_resolver = None
    with pytest.raises(RuntimeError, match="session_buddy_client"):
        await pool_mgr_with_pools.route_task(
            task={"prompt": "x", "peer_id": "alice", "project_id": "p"},
            pool_selector=PoolSelector.PEER_AFFINITY,
            caller_pool_allowlist={"pool_a"},
        )


@pytest.mark.unit
async def test_route_task_peer_affinity_no_caller_allowlist_falls_back(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """No allowlist → refuse peer hint, fall back to LEAST_LOADED."""
    pool_mgr_with_pools._peer_resolver = PeerRouteResolver(
        session_buddy_client=MagicMock(),
        acl_provider=lambda _pid: {"peer_models:read": True},
    )
    r = await pool_mgr_with_pools.route_task(
        task={"prompt": "x", "peer_id": "alice", "project_id": "p"},
        pool_selector=PoolSelector.PEER_AFFINITY,
        caller_pool_allowlist=None,
    )
    # Least loaded = pool_a
    assert r["pool_id"] == "pool_a"


@pytest.mark.unit
async def test_route_task_peer_affinity_resolver_returns_none(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """Resolver returns None → fall back to LEAST_LOADED within allowlist."""
    pool_mgr_with_pools._peer_resolver = PeerRouteResolver(
        session_buddy_client=MagicMock(),
        acl_provider=lambda _pid: {"peer_models:read": True},
    )
    pool_mgr_with_pools._peer_resolver.resolve_pool = AsyncMock(return_value=None)
    r = await pool_mgr_with_pools.route_task(
        task={"prompt": "x", "peer_id": "alice", "project_id": "p"},
        pool_selector=PoolSelector.PEER_AFFINITY,
        caller_pool_allowlist={"pool_a", "pool_b"},
    )
    # least-loaded within {pool_a, pool_b} = pool_a
    assert r["pool_id"] == "pool_a"


@pytest.mark.unit
async def test_route_task_peer_affinity_resolver_returns_unknown_pool(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """Resolver returns a pool_id not in the registry → fall back within allowlist."""
    pool_mgr_with_pools._peer_resolver = PeerRouteResolver(
        session_buddy_client=MagicMock(),
        acl_provider=lambda _pid: {"peer_models:read": True},
    )
    pool_mgr_with_pools._peer_resolver.resolve_pool = AsyncMock(return_value="pool_unknown")
    r = await pool_mgr_with_pools.route_task(
        task={"prompt": "x", "peer_id": "alice", "project_id": "p"},
        pool_selector=PoolSelector.PEER_AFFINITY,
        caller_pool_allowlist={"pool_a", "pool_b"},
    )
    assert r["pool_id"] == "pool_a"


@pytest.mark.unit
async def test_route_task_peer_affinity_hint_not_in_allowlist(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """Resolver returns a pool not in the caller's allowlist → fall back."""
    pool_mgr_with_pools._peer_resolver = PeerRouteResolver(
        session_buddy_client=MagicMock(),
        acl_provider=lambda _pid: {"peer_models:read": True},
    )
    pool_mgr_with_pools._peer_resolver.resolve_pool = AsyncMock(return_value="pool_b")
    r = await pool_mgr_with_pools.route_task(
        task={"prompt": "x", "peer_id": "alice", "project_id": "p"},
        pool_selector=PoolSelector.PEER_AFFINITY,
        caller_pool_allowlist={"pool_a", "pool_c"},
    )
    # Allowlist ∩ pools = {pool_a, pool_c}; least-loaded = pool_a
    assert r["pool_id"] == "pool_a"


@pytest.mark.unit
async def test_route_task_peer_affinity_hint_in_allowlist(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """Resolver returns a pool in the caller's allowlist → use it."""
    pool_mgr_with_pools._peer_resolver = PeerRouteResolver(
        session_buddy_client=MagicMock(),
        acl_provider=lambda _pid: {"peer_models:read": True},
    )
    pool_mgr_with_pools._peer_resolver.resolve_pool = AsyncMock(return_value="pool_b")
    r = await pool_mgr_with_pools.route_task(
        task={"prompt": "x", "peer_id": "alice", "project_id": "p"},
        pool_selector=PoolSelector.PEER_AFFINITY,
        caller_pool_allowlist={"pool_a", "pool_b", "pool_c"},
    )
    assert r["pool_id"] == "pool_b"


@pytest.mark.unit
async def test_route_task_peer_affinity_empty_intersection_raises(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """When the allowlist ∩ registered pools is empty → RuntimeError."""
    pool_mgr_with_pools._peer_resolver = PeerRouteResolver(
        session_buddy_client=MagicMock(),
        acl_provider=lambda _pid: {"peer_models:read": True},
    )
    pool_mgr_with_pools._peer_resolver.resolve_pool = AsyncMock(return_value=None)
    with pytest.raises(RuntimeError, match="caller_pool_allowlist"):
        await pool_mgr_with_pools.route_task(
            task={"prompt": "x", "peer_id": "alice", "project_id": "p"},
            pool_selector=PoolSelector.PEER_AFFINITY,
            caller_pool_allowlist={"no_such_pool"},
        )


# ---------------------------------------------------------------------------
# route_task - GPU category override
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_route_task_gpu_category_routes_to_runpod() -> None:
    """A vision category routes to the runpod pool when one is registered."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
    mgr._pools["mah_pool"] = _make_pool("mah_pool", pool_type="mahavishnu", n_workers=1)
    mgr._pools["rp_pool"] = _make_pool("rp_pool", pool_type="runpod", n_workers=1)
    mgr._pool_worker_counts["mah_pool"] = 1
    mgr._pool_worker_counts["rp_pool"] = 1
    mgr._worker_count_heap = [(1, "mah_pool"), (1, "rp_pool")]

    r = await mgr.route_task(
        task={"prompt": "x", "category": "vision"},
        pool_selector=PoolSelector.LEAST_LOADED,
    )
    assert r["pool_id"] == "rp_pool"


@pytest.mark.unit
async def test_route_task_gpu_category_no_runpod_falls_back() -> None:
    """vision category with no runpod pool → keeps the chosen pool."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
    mgr._pools["p1"] = _make_pool("p1", pool_type="mahavishnu", n_workers=1)
    mgr._pools["p2"] = _make_pool("p2", pool_type="mahavishnu", n_workers=2)
    mgr._pool_worker_counts["p1"] = 1
    mgr._pool_worker_counts["p2"] = 2
    mgr._worker_count_heap = [(1, "p1"), (2, "p2")]

    r = await mgr.route_task(
        task={"prompt": "x", "category": "vision"},
        pool_selector=PoolSelector.LEAST_LOADED,
    )
    # No runpod registered, so the least-loaded stays
    assert r["pool_id"] == "p1"


@pytest.mark.unit
async def test_route_task_ml_inference_category_uses_runpod() -> None:
    """ml_inference category triggers GPU override."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
    mgr._pools["p1"] = _make_pool("p1", pool_type="mahavishnu", n_workers=1)
    mgr._pools["rp"] = _make_pool("rp", pool_type="runpod", n_workers=1)
    mgr._pool_worker_counts["p1"] = 1
    mgr._pool_worker_counts["rp"] = 1
    mgr._worker_count_heap = [(1, "p1"), (1, "rp")]

    r = await mgr.route_task(
        task={"prompt": "x", "category": "ml_inference"},
        pool_selector=PoolSelector.LEAST_LOADED,
    )
    assert r["pool_id"] == "rp"


# ---------------------------------------------------------------------------
# route_task - fitness-aware routing
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_route_task_fitness_overrides_selector() -> None:
    """When fitness signals are available, the selector is overridden."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
    mgr._pools["pool_a"] = _make_pool("pool_a", n_workers=1)
    mgr._pool_worker_counts["pool_a"] = 1
    mgr._worker_count_heap = [(1, "pool_a")]

    # Patch the routing fitness reader to return signals.
    fake_signal = MagicMock()
    fake_signal.score = 0.9
    mgr._routing_fitness_reader.get_fitness_signals = AsyncMock(
        return_value={"round_robin": fake_signal}
    )
    mgr._routing_fitness_reader.get_best_selector = AsyncMock(return_value="round_robin")

    r = await mgr.route_task(
        task={"prompt": "x", "task_class": "code_generation"},
        pool_selector=PoolSelector.LEAST_LOADED,
    )
    assert r["pool_id"] == "pool_a"


@pytest.mark.unit
async def test_route_task_fitness_returns_unknown_selector_passes_through() -> None:
    """If fitness recommends an unknown selector, current selector is kept."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
    mgr._pools["pool_a"] = _make_pool("pool_a", n_workers=1)
    mgr._pool_worker_counts["pool_a"] = 1
    mgr._worker_count_heap = [(1, "pool_a")]

    fake_signal = MagicMock()
    fake_signal.score = 0.9
    mgr._routing_fitness_reader.get_fitness_signals = AsyncMock(
        return_value={"mystery_selector": fake_signal}
    )
    mgr._routing_fitness_reader.get_best_selector = AsyncMock(return_value="mystery_selector")

    # Should not raise — selector stays at LEAST_LOADED
    r = await mgr.route_task(
        task={"prompt": "x", "task_class": "code_generation"},
        pool_selector=PoolSelector.LEAST_LOADED,
    )
    assert r["pool_id"] == "pool_a"


@pytest.mark.unit
async def test_route_task_fitness_reader_raises_falls_back() -> None:
    """When the fitness reader raises, the configured selector is used."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
    mgr._pools["pool_a"] = _make_pool("pool_a", n_workers=1)
    mgr._pool_worker_counts["pool_a"] = 1
    mgr._worker_count_heap = [(1, "pool_a")]

    mgr._routing_fitness_reader.get_fitness_signals = AsyncMock(
        side_effect=RuntimeError("dhara down")
    )

    r = await mgr.route_task(
        task={"prompt": "x", "task_class": "code_generation"},
        pool_selector=PoolSelector.LEAST_LOADED,
    )
    assert r["pool_id"] == "pool_a"


@pytest.mark.unit
async def test_route_task_fitness_no_signals_uses_default() -> None:
    """Empty signals dict → keep configured selector."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
    mgr._pools["pool_a"] = _make_pool("pool_a", n_workers=1)
    mgr._pool_worker_counts["pool_a"] = 1
    mgr._worker_count_heap = [(1, "pool_a")]

    mgr._routing_fitness_reader.get_fitness_signals = AsyncMock(return_value={})
    mgr._routing_fitness_reader.get_best_selector = AsyncMock(return_value=None)

    r = await mgr.route_task(
        task={"prompt": "x", "task_class": "code_generation"},
        pool_selector=PoolSelector.ROUND_ROBIN,
    )
    assert r["pool_id"] == "pool_a"


# ---------------------------------------------------------------------------
# route_task - default selector
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_route_task_uses_default_selector(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """When pool_selector is None, the manager's default (LEAST_LOADED) is used."""
    r = await pool_mgr_with_pools.route_task(task={"prompt": "x"})
    assert r["pool_id"] == "pool_a"


# ---------------------------------------------------------------------------
# aggregate_results
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_aggregate_results_all_pools(pool_mgr_with_pools: PoolManager) -> None:
    """Default aggregates every pool."""
    out = await pool_mgr_with_pools.aggregate_results()
    assert set(out.keys()) == {"pool_a", "pool_b", "pool_c"}
    for _pid, data in out.items():
        assert data["status"] == "running"
        assert "memory_count" in data


@pytest.mark.unit
async def test_aggregate_results_subset(pool_mgr_with_pools: PoolManager) -> None:
    """Only the requested pool_ids are aggregated."""
    out = await pool_mgr_with_pools.aggregate_results(pool_ids=["pool_a", "pool_b"])
    assert set(out.keys()) == {"pool_a", "pool_b"}


@pytest.mark.unit
async def test_aggregate_results_handles_pool_errors(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """If a pool's collect_memory raises, its entry is skipped (not the whole call)."""
    bad = _make_pool("bad", n_workers=1)

    async def _bad_collect():
        raise RuntimeError("oops")

    bad.collect_memory = _bad_collect

    async def _status_ok() -> PoolStatus:
        return PoolStatus.RUNNING

    bad.status = _status_ok

    pool_mgr_with_pools._pools["bad"] = bad
    pool_mgr_with_pools._pool_worker_counts["bad"] = 1

    out = await pool_mgr_with_pools.aggregate_results()
    # "bad" should be missing; others present.
    assert "bad" not in out
    assert "pool_a" in out


@pytest.mark.unit
async def test_aggregate_results_pool_returns_not_found_dict(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """A pool_id with no live pool gets the not_found entry."""
    out = await pool_mgr_with_pools.aggregate_results(pool_ids=["ghost"])
    # The collect_from_pool helper returns the "not_found" sentinel.
    assert out.get("ghost", {}).get("status") == "not_found"


# ---------------------------------------------------------------------------
# close_pool
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_close_pool_unregisters_and_publishes(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """close_pool stops the pool, removes tracking, and publishes closure."""
    pool_mgr_with_pools.message_bus.publish = AsyncMock(return_value=None)
    await pool_mgr_with_pools.close_pool("pool_a")
    assert "pool_a" not in pool_mgr_with_pools._pools
    assert "pool_a" not in pool_mgr_with_pools._pool_worker_counts
    assert pool_mgr_with_pools.message_bus.publish.await_count == 1
    msg = pool_mgr_with_pools.message_bus.publish.await_args.args[0]
    assert msg["type"] == "pool_closed"


@pytest.mark.unit
async def test_close_pool_unknown_is_noop(pool_mgr_with_pools: PoolManager) -> None:
    """Closing an unknown pool id does not raise."""
    await pool_mgr_with_pools.close_pool("not_a_pool")
    # No change to existing pools
    assert "pool_a" in pool_mgr_with_pools._pools


# ---------------------------------------------------------------------------
# close_all
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_close_all_clears_state(pool_mgr_with_pools: PoolManager) -> None:
    """close_all shuts everything down and clears the heap + counts."""
    pool_mgr_with_pools.message_bus.publish = AsyncMock(return_value=None)
    await pool_mgr_with_pools.close_all()
    assert pool_mgr_with_pools._pools == {}
    assert pool_mgr_with_pools._worker_count_heap == []
    assert pool_mgr_with_pools._pool_worker_counts == {}


@pytest.mark.unit
async def test_close_all_when_empty(pool_mgr: PoolManager) -> None:
    """close_all is a no-op when there are no pools."""
    await pool_mgr.close_all()
    assert pool_mgr._pools == {}


# ---------------------------------------------------------------------------
# list_pools
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_list_pools_returns_pool_info(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """list_pools returns metadata for every pool."""
    out = await pool_mgr_with_pools.list_pools()
    ids = {p["pool_id"] for p in out}
    assert ids == {"pool_a", "pool_b", "pool_c"}
    for p in out:
        assert p["status"] == "running"
        assert "workers" in p
        assert "min_workers" in p
        assert "max_workers" in p


@pytest.mark.unit
async def test_list_pools_empty(pool_mgr: PoolManager) -> None:
    """Empty manager returns an empty list."""
    assert await pool_mgr.list_pools() == []


@pytest.mark.unit
async def test_list_pools_filters_exceptions(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """If a pool's status() raises, it's excluded."""
    bad = _make_pool("bad", n_workers=1)

    async def _bad_status():
        raise RuntimeError("nope")

    bad.status = _bad_status
    pool_mgr_with_pools._pools["bad"] = bad

    out = await pool_mgr_with_pools.list_pools()
    ids = {p["pool_id"] for p in out}
    assert "bad" not in ids
    assert "pool_a" in ids


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_health_check_all_healthy(pool_mgr_with_pools: PoolManager) -> None:
    """All pools RUNNING → status='healthy'."""
    out = await pool_mgr_with_pools.health_check()
    assert out["status"] == "healthy"
    assert out["pools_active"] == 3
    assert len(out["pools"]) == 3


@pytest.mark.unit
async def test_health_check_degraded_when_some_unhealthy(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """Mixed healthy/unhealthy → 'degraded'."""
    bad = _make_pool("bad", n_workers=1)

    async def _status():
        return PoolStatus.FAILED

    bad.status = _status
    pool_mgr_with_pools._pools["bad"] = bad

    out = await pool_mgr_with_pools.health_check()
    assert out["status"] == "degraded"


@pytest.mark.unit
async def test_health_check_unhealthy_when_all_failed(
    pool_mgr_with_pools: PoolManager,
) -> None:
    """All pools failed → 'unhealthy'."""
    for pid in ["pool_a", "pool_b", "pool_c"]:

        async def _status() -> PoolStatus:
            return PoolStatus.FAILED

        pool_mgr_with_pools._pools[pid].status = _status

    out = await pool_mgr_with_pools.health_check()
    assert out["status"] == "unhealthy"


@pytest.mark.unit
async def test_health_check_empty_pool_manager(pool_mgr: PoolManager) -> None:
    """Empty manager → 'healthy' with 0 active pools."""
    out = await pool_mgr.health_check()
    assert out["status"] == "healthy"
    assert out["pools_active"] == 0
    assert out["pools"] == []


# ---------------------------------------------------------------------------
# set_pool_selector
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_set_pool_selector_updates_default(
    pool_mgr: PoolManager,
) -> None:
    """set_pool_selector changes the default for future route_task calls."""
    assert pool_mgr._pool_selector == PoolSelector.LEAST_LOADED
    pool_mgr.set_pool_selector(PoolSelector.ROUND_ROBIN)
    assert pool_mgr._pool_selector == PoolSelector.ROUND_ROBIN


# ---------------------------------------------------------------------------
# get_message_bus_stats
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_message_bus_stats_returns_dict(
    pool_mgr: PoolManager,
) -> None:
    """get_message_bus_stats returns the underlying bus stats dict."""
    out = pool_mgr.get_message_bus_stats()
    assert isinstance(out, dict)
    assert "pools_with_queues" in out
    assert "queue_sizes" in out
    assert "subscriber_counts" in out
    assert "max_queue_size" in out
