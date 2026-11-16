"""The affinity selector needs a server-side allowlist to be reachable.

ADR-014 keeps the allowlist server-side: a wire caller names a pool and
the router decides whether that caller kind may use it. Until the policy
was wired to the settings, ``caller_pool_allowlist`` was never set, so
``_route_by_affinity`` refused every pinned pool and fell back to
LEAST_LOADED — a silent no-op that made ``pool_affinity`` unusable.

These tests pin the resolution rules (per caller kind, pool names
resolved to ids, exact match beating the wildcard) and the fail-closed
behaviour when the policy cannot be read.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.status import PoolStatus
from mahavishnu.mcp.protocols.message_bus import MessageBus
from mahavishnu.pools.base import BasePool, PoolConfig
from mahavishnu.pools.manager import CallerKind, PoolManager, PoolSelector


def _make_pool(pool_id: str, name: str, n_workers: int = 1) -> MagicMock:
    """A pool stand-in the router can select and dispatch into."""
    pool = MagicMock(spec=BasePool)
    pool.pool_id = pool_id
    pool.config = PoolConfig(name=name, pool_type="mahavishnu")
    pool._workers = {f"w{i}": f"w{i}" for i in range(n_workers)}

    async def _execute_task(task: dict[str, Any]) -> dict[str, Any]:
        return {"pool_id": pool_id, "worker_id": "w1", "status": "completed"}

    pool.execute_task = _execute_task
    pool.status = AsyncMock(return_value=PoolStatus.RUNNING)
    return pool


@pytest.fixture
def pool_mgr() -> PoolManager:
    """A manager holding two named pools."""
    with patch("mahavishnu.core.app.TerminalManager"):
        mgr = PoolManager(
            terminal_manager=MagicMock(),
            session_buddy_client=None,
            message_bus=MessageBus(),
        )
    mgr._pools["pool_a"] = _make_pool("pool_a", "alpha")
    mgr._pools["pool_b"] = _make_pool("pool_b", "beta")
    mgr._pools_by_name["alpha"] = "pool_a"
    mgr._pools_by_name["beta"] = "pool_b"
    mgr._pool_worker_counts["pool_a"] = 1
    mgr._pool_worker_counts["pool_b"] = 2
    mgr._worker_count_heap = [(1, "pool_a"), (2, "pool_b")]
    return mgr


def _with_policy(policy: dict[str, list[str]] | None):
    """Patch the settings so the manager reads ``policy``.

    ``None`` stands for "the settings cannot be read", which is the
    fail-closed path.
    """
    if policy is None:
        return patch(
            "mahavishnu.core.config.get_settings",
            side_effect=RuntimeError("settings unavailable"),
        )
    settings = MagicMock()
    settings.pools.caller_pool_allowlist = policy
    return patch(
        "mahavishnu.core.config.get_settings",
        return_value=settings,
    )


@pytest.mark.unit
async def test_the_default_policy_lets_affinity_land_on_the_named_pool(
    pool_mgr: PoolManager,
) -> None:
    """The whole point: naming a pool reaches that pool.

    Before the policy was wired, this returned ``pool_a`` — the
    LEAST_LOADED fallback — no matter which pool the caller named.
    """
    with _with_policy({"*": ["*"]}):
        result = await pool_mgr.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="pool_b",
        )

    assert result["pool_id"] == "pool_b"


@pytest.mark.unit
async def test_a_pool_outside_the_policy_is_refused(pool_mgr: PoolManager) -> None:
    """A policy that names one pool does not authorize the other."""
    with _with_policy({"*": ["pool_a"]}):
        result = await pool_mgr.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="pool_b",
        )

    # Refused, and the fallback stays inside the allowlist.
    assert result["pool_id"] == "pool_a"


@pytest.mark.unit
async def test_pool_names_in_the_policy_resolve_to_ids(pool_mgr: PoolManager) -> None:
    """A config file names a pool by NAME; pool ids are generated per spawn."""
    with _with_policy({"*": ["beta"]}):
        result = await pool_mgr.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="pool_b",
        )

    assert result["pool_id"] == "pool_b"


@pytest.mark.unit
async def test_an_exact_caller_kind_entry_beats_the_wildcard(
    pool_mgr: PoolManager,
) -> None:
    """A caller's own entry wins over the catch-all."""
    with _with_policy({"*": ["pool_a"], "claude_code": ["pool_b"]}):
        result = await pool_mgr.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="pool_b",
            caller_kind=CallerKind.CLAUDE_CODE,
        )

    assert result["pool_id"] == "pool_b"


@pytest.mark.unit
async def test_the_wildcard_entry_applies_to_an_unlisted_caller_kind(
    pool_mgr: PoolManager,
) -> None:
    """A caller kind with no entry of its own falls back to the wildcard."""
    with _with_policy({"*": ["pool_a"], "claude_code": ["pool_b"]}):
        result = await pool_mgr.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="pool_b",
            caller_kind=CallerKind.WORKFLOW,
        )

    assert result["pool_id"] == "pool_a"


@pytest.mark.unit
async def test_an_unreadable_policy_fails_closed(pool_mgr: PoolManager) -> None:
    """A settings failure must not open the boundary.

    The pre-policy behaviour was the safe one: no declared allowlist, so
    the router refuses a pinned pool. A read failure must not turn that
    into "every pool is authorized".
    """
    with _with_policy(None):
        result = await pool_mgr.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="pool_b",
        )

    assert result["pool_id"] == "pool_a"


@pytest.mark.unit
async def test_the_caller_cannot_supply_its_own_allowlist(
    pool_mgr: PoolManager,
) -> None:
    """ADR-014: the allowlist is server-side.

    A wire caller names a pool; it never names the set of pools it may
    use. The MCP dispatch helper passes no allowlist, so the policy is
    the only source — and pool_b, which the policy excludes, is refused.
    """
    from mahavishnu.mcp.tools.pool_tools import _dispatch_internal

    with _with_policy({"*": ["pool_a"]}):
        result = await _dispatch_internal(
            prompt="x",
            pool_selector=PoolSelector.AFFINITY,
            execution_id="exec-1",
            pool_affinity="pool_b",
            coerced_kind=CallerKind.CLAUDE_CODE,
            parent_session_id=None,
            auto_spawn=False,
            pool_manager=pool_mgr,
        )

    assert result["pool_id"] == "pool_a"
