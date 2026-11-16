"""The affinity selector needs a server-side allowlist to be reachable.

ADR-014 keeps the allowlist server-side: a wire caller names a pool and
the router decides whether that pool is authorized. Until the policy was
wired to the server, ``caller_pool_allowlist`` was never set, so
``_route_by_affinity`` refused every pinned pool and fell back to
LEAST_LOADED — a silent no-op that made ``pool_affinity`` unusable.

The policy is the operator's, read from
``MAHAVISHNU_PEER_AFFINITY_ALLOWLIST`` (the name ADR-014 gives) or from
``pools.caller_pool_allowlist`` in the settings. It is deliberately NOT
keyed on ``caller_kind``: that parameter is quota attribution, so keying
authorization on it would let a caller pick its own permissions by
picking a string.

These tests pin the resolution rules (env var precedence, pool names
resolved to ids, the wildcard, an empty policy) and the fail-closed
behaviour when no policy is declared.

Two rules govern what the policy gates, and both are load-bearing:

- A pool reference is resolved to its canonical id on BOTH sides of
  the authorization test. A config file can only name a pool by its
  name (an id is generated per spawn), so a name-based request has to
  resolve for a name-based policy to be satisfiable at all.
- The operator's policy is a PIN gate. It names the pools a caller
  may CHOOSE; it does not restrict where the server routes, because a
  pool the server chose is not the caller's choice. A caller that
  declares its own allowlist is bound by it everywhere.
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


def _with_settings(policy: list[str] | None):
    """Patch the settings so the manager reads ``policy``."""
    settings = MagicMock()
    settings.pools.caller_pool_allowlist = policy
    return patch(
        "mahavishnu.core.config.get_settings",
        return_value=settings,
    )


def _with_env(value: str | None):
    """Patch the ADR-014 env var."""
    if value is None:
        return patch.dict("os.environ", {}, clear=False)
    return patch.dict("os.environ", {"MAHAVISHNU_PEER_AFFINITY_ALLOWLIST": value})


@pytest.mark.unit
async def test_the_policy_lets_affinity_land_on_the_named_pool(
    pool_mgr: PoolManager,
) -> None:
    """The whole point: naming a pool reaches that pool.

    Before the policy was wired, this returned ``pool_a`` — the
    LEAST_LOADED fallback — no matter which pool the caller named.
    """
    with _with_settings(["*"]):
        result = await pool_mgr.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="pool_b",
        )

    assert result["pool_id"] == "pool_b"


@pytest.mark.unit
async def test_no_policy_refuses_the_pinned_pool(pool_mgr: PoolManager) -> None:
    """With no policy declared, the router refuses the caller's choice.

    This is ADR-014's contract and the fail-closed default: the caller
    has not declared which pools it may pin, so the router makes the
    choice itself.
    """
    with _with_settings(None):
        result = await pool_mgr.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="pool_b",
        )

    assert result["pool_id"] == "pool_a"


@pytest.mark.unit
async def test_the_env_var_is_the_source(pool_mgr: PoolManager) -> None:
    """``MAHAVISHNU_PEER_AFFINITY_ALLOWLIST`` is the name ADR-014 gives."""
    with (
        _with_env("beta"),
        _with_settings(["pool_a"]),
    ):
        result = await pool_mgr.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="pool_b",
        )

    assert result["pool_id"] == "pool_b"


@pytest.mark.unit
async def test_the_env_var_overrides_the_settings(pool_mgr: PoolManager) -> None:
    """The env var wins — it is the more specific, per-process statement."""
    with (
        _with_env("pool_a"),
        _with_settings(["pool_b"]),
    ):
        result = await pool_mgr.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="pool_a",
        )

    assert result["pool_id"] == "pool_a"


@pytest.mark.unit
async def test_pool_names_resolve_to_ids(pool_mgr: PoolManager) -> None:
    """A config file names a pool by NAME; pool ids are generated per spawn."""
    with _with_settings(["beta"]):
        result = await pool_mgr.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="pool_b",
        )

    assert result["pool_id"] == "pool_b"


@pytest.mark.unit
async def test_a_name_request_matches_a_name_policy(pool_mgr: PoolManager) -> None:
    """The two sides of the authorization test speak the same namespace.

    A config file can only name a pool by its NAME — a pool id is
    generated per spawn — so a name-based policy is the only kind an
    operator can write. The policy's tokens resolve to ids, so the
    caller's reference has to resolve too.

    Before this, the policy resolved to ``{"pool_a", "pool_b"}`` while
    the request stayed the string ``"beta"``, so the two never met and
    the caller's pinned pool was refused by the very policy that named
    it. The policy here names BOTH pools so the refusal is visible:
    the fallback would land on ``pool_a`` (the least loaded), so
    landing on ``pool_b`` means the pin was honoured.
    """
    with _with_settings(["alpha", "beta"]):
        result = await pool_mgr.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="beta",
        )

    assert result["pool_id"] == "pool_b"


@pytest.mark.unit
async def test_the_wildcard_accepts_a_name_request(pool_mgr: PoolManager) -> None:
    """The wildcard means "every registered pool", not "every id".

    The wildcard test reads ``pool_id in self._pools``, and that
    registry is keyed by id — so a caller that named a pool by name
    was refused even under the wildcard, and the refusal looked like
    a permission problem rather than a namespace mismatch.
    """
    with _with_settings(["*"]):
        result = await pool_mgr.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="beta",
        )

    assert result["pool_id"] == "pool_b"


@pytest.mark.unit
async def test_the_operator_policy_does_not_gate_server_chosen_routing(
    pool_mgr: PoolManager,
) -> None:
    """The operator's policy is a PIN gate, not a dispatch restriction.

    A pool the SERVER chose is not the caller's choice: the caller
    asked for a task, not for that pool. The policy names the pools a
    caller may pin, so it does not restrict where the server routes.

    This is what makes a narrow policy usable at all. Under the older
    semantics the policy also filtered the queueing re-rank's
    candidate set, so a pool it did not name became unroutable and an
    ordinary dispatch failed with an authorization error about a pool
    the caller never asked for. Pools here are spawned on demand by
    name, so no fixed list can name them all.
    """
    with _with_settings(["beta"]):
        result = await pool_mgr.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.LEAST_LOADED,
        )

    # pool_a is the least loaded and is NOT in the policy.
    assert result["pool_id"] == "pool_a"


@pytest.mark.unit
async def test_a_caller_declared_allowlist_still_restricts_dispatch(
    pool_mgr: PoolManager,
) -> None:
    """A caller that declares its own set is bound by it everywhere.

    It said where its tasks may go, so the server's own pick is
    refused when it falls outside — the round-2 security review's
    invariant, and the contract ``route_task`` documents for a
    supplied ``caller_pool_allowlist``.
    """
    with pytest.raises(RuntimeError, match="not in caller_pool_allowlist"):
        await pool_mgr.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.LEAST_LOADED,
            caller_pool_allowlist={"pool_b"},
        )


@pytest.mark.unit
async def test_a_pool_outside_the_policy_is_refused(pool_mgr: PoolManager) -> None:
    """A policy that names one pool does not authorize the other."""
    with _with_settings(["pool_a"]):
        result = await pool_mgr.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="pool_b",
        )

    # Refused, and the fallback stays inside the allowlist.
    assert result["pool_id"] == "pool_a"


@pytest.mark.unit
async def test_an_empty_policy_is_treated_as_no_policy(pool_mgr: PoolManager) -> None:
    """An empty list is a misconfiguration, not "deny everything".

    An empty *set* would fail every pool-selection path with a runtime
    error rather than expressing "nothing is authorized", so an empty
    declared policy means "no policy declared".
    """
    with _with_settings([]):
        result = await pool_mgr.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="pool_b",
        )

    assert result["pool_id"] == "pool_a"


@pytest.mark.unit
async def test_the_wire_caller_kind_cannot_select_the_policy(
    pool_mgr: PoolManager,
) -> None:
    """The wire ``caller_kind`` must not choose the authorization set.

    ``caller_kind`` is quota attribution (ADR-014). A policy keyed on it
    would let a caller pick its own permissions by picking a string, so
    the policy is not keyed on it at all — and the value the wire sends
    changes nothing about which pools are authorized.
    """
    from mahavishnu.mcp.tools.pool_tools import _dispatch_internal

    with _with_settings(["pool_a"]):
        for kind in (CallerKind.CLAUDE_CODE, CallerKind.WORKFLOW, CallerKind.UNKNOWN):
            result = await _dispatch_internal(
                prompt="x",
                pool_selector=PoolSelector.AFFINITY,
                execution_id="exec-1",
                pool_affinity="pool_b",
                coerced_kind=kind,
                parent_session_id=None,
                auto_spawn=False,
                pool_manager=pool_mgr,
            )
            # The policy governed the decision for every kind: pool_b,
            # which the policy excludes, was refused.
            assert result["pool_id"] == "pool_a", (
                f"caller_kind={kind!r} changed the authorization decision"
            )


@pytest.mark.unit
async def test_the_settings_read_failure_refuses_the_pinned_pool(
    pool_mgr: PoolManager,
) -> None:
    """A settings failure must not widen the boundary.

    The no-policy state is the fail-closed one: the router refuses a
    pinned pool. A read failure must not turn that into "every pool is
    authorized".
    """
    with patch(
        "mahavishnu.core.config.get_settings",
        side_effect=RuntimeError("settings unavailable"),
    ):
        result = await pool_mgr.route_task(
            task={"prompt": "x"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="pool_b",
        )

    assert result["pool_id"] == "pool_a"
