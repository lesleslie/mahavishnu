"""Pool management MCP tools."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import logging
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from mcp_common.fastmcp import FastMCP  # noqa: TC002

from mahavishnu.core.errors import RateLimitError
from mahavishnu.mcp.tools._workflow_id_guard import _validate_workflow_id
from mahavishnu.observability.worker_metrics import WorkerMetrics

# Spec §14 success-criteria instrumentation. Singleton per module; thread-safe.
# Used by ``pool_route_execute``'s durable branch to feed the pool_share
# success criterion (numerator pool_calls / denominator pool_calls + terminal_calls).
_metrics = WorkerMetrics()

# Explicit per-worker_type allowlist for the durable fast path.
# NOT a category-level gate — each worker here has its durable spawn
# template verified. SSH (REMOTE) and AI assistants without explicit
# verification are deliberately excluded. The REMOTE category is rejected
# until the SSH template (host/credential substitution) is verified end
# to end. Add new entries only after their ``_durable_manager.spawn``
# template is audited.
_DURABLE_WORKER_TYPES: frozenset[str] = frozenset(
    {
        "terminal-claude",  # AI_ASSISTANT — explicit allow (template verified)
        "terminal-shell",  # SHELL
        "terminal-python",  # SHELL
        "terminal-ipython",  # SHELL
        "terminal-node",  # SHELL
    }
)


try:
    from mahavishnu.pools.memory_aggregator import MemoryAggregator
except Exception:  # pragma: no cover - optional import for test patching  # noqa: BLE001 - MCP boundary must preserve all operation failures  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
    MemoryAggregator = None

logger = logging.getLogger(__name__)


def _resolve_peer_affinity_allowlist_from_env() -> set[str] | None:
    """Resolve the MCP-side caller pool allowlist from environment.

    Operators set ``MAHAVISHNU_PEER_AFFINITY_ALLOWLIST`` as a
    comma-separated list of pool IDs the MCP tool is authorized to
    dispatch PEER_AFFINITY traffic into. When unset or empty, the
    MCP tool forwards ``None`` so the manager refuses to honor the
    peer hint (the safe default).

    Set ``MAHAVISHNU_PEER_AFFINITY_ALLOWLIST=*`` to opt into
    "all currently-registered pools" — the allowlist is then
    applied dynamically at call time by the manager, which
    intersects the request with its live pool registry. This is
    the documented escape hatch for the rare case where a
    deployment is meant to expose PEER_AFFINITY for every
    registered pool.
    """
    raw = os.environ.get("MAHAVISHNU_PEER_AFFINITY_ALLOWLIST", "").strip()
    if not raw:
        return None
    if raw == "*":
        # Sentinel: caller authorizes dispatch into any
        # currently-registered pool. We pass a set containing the
        # wildcard; the manager recognizes ``"*"`` and treats it
        # as "intersect with the live pool set". This keeps the
        # MCP tool stateless — it does not need to know which
        # pools are currently registered.
        return {"*"}
    return {item.strip() for item in raw.split(",") if item.strip()}


def _authorize_durable_fast_path(
    pool_manager: Any,
    caller_kind: str,
    pool_selector: str,
    caller_pool_allowlist: list[str] | None,
) -> tuple[bool, Any]:
    """Run the auth gates that legacy ``PoolManager.route_task`` enforces.

    The durable fast path bypasses ``pool_manager.route_task`` entirely,
    so without this guard a caller could skip ``coerce_caller_kind``,
    the per-caller_kind quota, and the ADR-014 ``caller_pool_allowlist``
    authorization by routing through the fast path. Mirrors the legacy
    route_task contract so quota buckets and allowlists are honored the
    same way on both paths.

    Args:
        pool_manager: PoolManager instance (or duck-typed test stand-in).
        caller_kind: Caller identity string. Coerced via
            ``coerce_caller_kind`` so unrecognized values land in the
            canonical ``UNKNOWN`` bucket.
        pool_selector: One of the ``PoolSelector`` string values
            (``"least_loaded"``, ``"round_robin"``, ``"random"``,
            ``"affinity"``, ``"peer_affinity"``).
        caller_pool_allowlist: Optional caller-supplied pool allowlist.
            When ``None`` and ``pool_selector`` is a specific-pool
            selector, the helper refuses the fast path so the caller
            cannot bypass ADR-014.

    Returns:
        Tuple ``(allowed, coerced_kind)``. When ``allowed`` is False,
        the caller MUST fall back to the legacy pool-router path.
        ``coerced_kind`` is the result of ``coerce_caller_kind`` for
        downstream use.

    Raises:
        RateLimitError: When the per-caller_kind quota is exhausted.
            Mirrors the legacy ``route_task`` contract; the caller
            surfaces this as a rate-limit response on the MCP boundary.
    """
    from mahavishnu.pools.manager import coerce_caller_kind

    coerced_kind = coerce_caller_kind(caller_kind)

    # Quota enforcement is performed inside ``route_task`` (for the
    # legacy path) and at the durable fast-path spawn site (for the
    # fast path). Performing it here as well would double-count quota
    # for legacy-path callers and surface a spurious ``rate_limited``
    # on the second call against a bucket sized for ``max_per_window=N``.
    # The fast-path spawn site has its own quota gate so a caller
    # cannot bypass rate-limiting by routing through the durable
    # path either.

    # ADR-014: AFFINITY/PEER_AFFINITY require a caller_pool_allowlist.
    # The fast path does not select a pool, but a missing allowlist
    # must still refuse specific-pool routing so a caller cannot bypass
    # the gate by routing through the durable path.
    if pool_selector in ("affinity", "peer_affinity") and not caller_pool_allowlist:
        return False, coerced_kind

    return True, coerced_kind


async def _run_async_dispatch(
    *,
    pool_manager,
    workflow_id: str,
    task: dict[str, Any],
    selector,
    caller_kind,
    parent_session_id: str | None,
) -> None:
    """Run a dispatched task in the background and persist terminal state.

    State machine:
        queued -> running -> {completed, failed}

    Persistence writes ``workflow-results/{workflow_id}/`` via
    ``pool_manager._dhara_state.put(...)``. When the Dhara put itself
    fails (network, schema, serialization), the workflow is
    dead-lettered to ``~/.mahavishnu/async-dead-letter/{safewid}.json``
    so an operator can reconcile later. Two non-fatal failure modes
    are tolerated:

    - Dhara unavailable (``getattr`` returns ``None``): a warning
      is logged and the function returns; the caller has already
      been told the workflow was queued.
    - Dead-letter write also fails: the inner error is logged at
      ``exception`` severity so it surfaces in monitoring, but the
      function still returns (never raises) to keep the
      fire-and-forget contract.

    Limitation: this coroutine is scheduled with
    ``asyncio.create_task`` from inside the MCP request handler. If
    the event loop is closed before the task begins running,
    ``asyncio`` emits ``"Task was destroyed but it is pending!"``.
    Operators should extend with a durable queue (e.g. Arq, RQ,
    Redis Streams) when the workflow lifetime may exceed the
    server-shutdown window.
    """
    dhara = getattr(pool_manager, "_dhara_state", None)

    async def _persist_state(state_value: str, payload: dict[str, Any]) -> None:
        if dhara is None:
            return
        await dhara.put(
            f"workflow-results/{workflow_id}/",
            {
                "workflow_id": workflow_id,
                "status": state_value,
                "updated_at": datetime.now(UTC).isoformat(),
                **payload,
            },
        )

    base_payload: dict[str, Any] = {
        "workflow_id": workflow_id,
        "caller_kind": caller_kind,
        "parent_session_id": parent_session_id,
    }

    await _persist_state("running", base_payload)

    terminal_status = "failed"
    result_payload: dict[str, Any] = {}
    try:
        result = await pool_manager.route_task(
            task,
            selector,
            caller_kind=caller_kind,
            parent_session_id=parent_session_id,
        )
        terminal_status = "completed"
        result_payload = {"result": result}
    except RateLimitError as exc:
        terminal_status = "failed"
        result_payload = {
            "error": str(exc),
            "rate_limited": True,
            "retry_after_seconds": exc.details.get("retry_after_seconds"),
        }
    except Exception as exc:
        logger.exception(
            "dispatch_to_pool: async workflow_id=%s failed",
            workflow_id,
        )
        terminal_status = "failed"
        result_payload = {"error": str(exc)}

    final_payload: dict[str, Any] = {**base_payload, **result_payload}
    if dhara is not None:
        try:
            await _persist_state(terminal_status, final_payload)
            return
        except Exception as exc:  # noqa: BLE001 - MCP boundary must preserve all operation failures
            dead_letter_dir = Path.home() / ".mahavishnu" / "async-dead-letter"
            try:
                dead_letter_dir.mkdir(parents=True, exist_ok=True)
                safe_wid = workflow_id.replace("/", "_").replace("..", "_")[:200]
                dead_letter_path = dead_letter_dir / f"{safe_wid}.json"
                try:
                    dead_letter_path.write_text(
                        json.dumps(
                            {
                                "workflow_id": workflow_id,
                                "intended_terminal_status": terminal_status,
                                "payload": final_payload,
                                "exception": repr(exc),
                                "dead_lettered_at": datetime.now(UTC).isoformat(),
                            },
                            default=str,
                        )
                    )
                except Exception:
                    logger.exception(
                        "dispatch_to_pool: dead-letter write FAILED workflow_id=%s path=%s",
                        workflow_id,
                        dead_letter_path,
                    )
                try:
                    await dhara.put(
                        f"workflow-results/{workflow_id}/",
                        {
                            "workflow_id": workflow_id,
                            "status": "result_write_failed",
                            "intended_terminal_status": terminal_status,
                            "updated_at": datetime.now(UTC).isoformat(),
                            **final_payload,
                        },
                    )
                except Exception:
                    logger.exception(
                        "dispatch_to_pool: marker write FAILED "
                        "workflow_id=%s intended_terminal_status=%s",
                        workflow_id,
                        terminal_status,
                    )
            except Exception:
                logger.exception(
                    "dispatch_to_pool: dead-letter recovery FAILED workflow_id=%s",
                    workflow_id,
                )
        return

    logger.warning(
        "dispatch_to_pool: no _dhara_state configured; workflow_id=%s "
        "terminal status %s will not be persisted",
        workflow_id,
        terminal_status,
    )


def register_pool_tools(
    mcp: FastMCP,
    pool_manager,
    *,
    durable_manager=None,
    dhara=None,
) -> None:
    """Register pool management tools.

    Structural C901 suppression: FastMCP's ``@mcp.tool()`` decorator
    requires each tool function to be defined inline so it can introspect
    the function name and signature for the MCP tool schema. The tools
    registered here are intentionally kept inline; the complexity is the
    cost of the FastMCP API contract, not bad code.

    Args:
        mcp: FastMCP instance
        pool_manager: PoolManager instance
        durable_manager: Optional DurableWorkerManager; when provided,
            ``pool_route_execute`` and ``dispatch_to_pool`` route
            shell-based ``worker_type`` overrides through
            ``durable_manager.spawn`` (F1/F12 contract).
        dhara: Optional Dhara client used by ``dispatch_to_pool`` to
            persist ``worker_id`` at ``workflow-results/{workflow_id}/``
            on the durable path.

    This registers 12 pool management tools:
    - pool_spawn: Create a new pool
    - pool_execute: Execute task on specific pool
    - pool_route_execute: Execute task with automatic routing
    - dispatch_to_pool: Dispatch with caller_kind + parent_session_id audit trail
    - workflow_result: Retrieve the persisted state of an async dispatch
    - pool_list: List all active pools
    - pool_monitor: Monitor pool metrics
    - pool_scale: Scale pool worker count
    - pool_close: Close a specific pool
    - pool_close_all: Close all pools
    - pool_health: Get health status
    - pool_search_memory: Search memory across pools
    """
    # Globals for the nested @mcp.tool() functions to read on the
    # durable-routing fast path. Default ``None`` preserves legacy
    # behavior — the nested tools skip the durable branch when these
    # are unset.
    _durable_manager = durable_manager
    _dhara = dhara

    @mcp.tool()
    async def pool_spawn(
        pool_type: str = "mahavishnu",
        name: str = "default",
        min_workers: int = 1,
        max_workers: int = 10,
        worker_type: str = "terminal-claude",
    ) -> dict[str, Any]:
        """Spawn a new worker pool."""
        from mahavishnu.pools.base import PoolConfig

        config = PoolConfig(
            name=name,
            pool_type=pool_type,
            min_workers=min_workers,
            max_workers=max_workers,
            worker_type=worker_type,
        )

        try:
            pool_id = await pool_manager.spawn_pool(pool_type, config)

            return {
                "pool_id": pool_id,
                "pool_type": pool_type,
                "name": name,
                "status": "created",
                "min_workers": min_workers,
                "max_workers": max_workers,
            }
        except Exception as e:  # noqa: BLE001 - MCP boundary must preserve all operation failures
            logger.error(f"Failed to spawn pool: {e}")
            return {
                "status": "failed",
                "error": str(e),
            }

    @mcp.tool()
    async def pool_execute(
        pool_id: str,
        prompt: str,
        timeout: int = 300,
        caller_kind: str = "unknown",
        parent_session_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a task on a specific Mahavishnu pool by ID.

        Use this when:

        - You already know which pool should run the work (e.g., a pool pinned
          for a specific repo via affinity).
        - You're orchestrating across multiple pools in sequence and need
          explicit pool targeting.
        - The work must run on a dedicated GPU pool (e.g., ``runpod_*`` for ML).

        For most non-trivial work, prefer ``pool_route_execute`` instead — it
        picks the best pool automatically. Use ``pool_execute`` only when you
        have a specific reason to bypass auto-routing.

        Like ``pool_route_execute``, this tool enforces the per-``caller_kind``
        fixed-window quota (60 req / 60s by default). The caller MUST
        declare ``caller_kind`` so the rate limit is attributed correctly;
        unrecognized values are normalized to ``CallerKind.UNKNOWN`` via
        ``coerce_caller_kind``.

        Use ``pool_list`` to discover available pool IDs.

        Args:
            pool_id: The pool to dispatch to (from ``pool_list``).
            prompt: Clear task description.
            timeout: Max seconds to wait. Default 300.
            caller_kind: Identity of the caller for observability/quota
                enforcement. Default ``unknown``; resolved via
                ``coerce_caller_kind`` before reaching the manager.
            parent_session_id: Optional session ID for cross-system
                correlation. Forwarded to ``execute_on_pool``.

        Returns:
            Execution result, rate-limit dict, or error dict.

        Example:
            ```
            result = await pool_execute(
                pool_id="runpod-gpu-pool",
                prompt="Run inference on the embeddings model for this batch.",
                timeout=600,
                caller_kind="ultracode",
                parent_session_id="ses_abc123",
            )
            ```
        """
        from mahavishnu.core.errors import RateLimitError
        from mahavishnu.pools.manager import coerce_caller_kind

        coerced_kind = coerce_caller_kind(caller_kind)
        # Quota gate: enforce BEFORE building the task so a saturated
        # bucket short-circuits cheaply. ``execute_on_pool`` no longer
        # enforces quota (delegated callers like ``route_task`` are
        # gated by ``_authorize_durable_fast_path``), so the gate
        # moved to the tool boundary to keep ``pool_execute`` callers
        # on the same contract as ``pool_route_execute``.
        enforce = getattr(pool_manager, "_enforce_caller_quota", None)
        if enforce is not None:
            enforce(coerced_kind)
        task = {
            "prompt": prompt,
            "timeout": timeout,
            "parent_session_id": parent_session_id,
            "caller_kind": coerced_kind.value,
        }

        try:
            result = await pool_manager.execute_on_pool(
                pool_id,
                task,
                caller_kind=coerced_kind,
                parent_session_id=parent_session_id,
            )
            return result  # type: ignore[no-any-return]
        except RateLimitError as exc:
            logger.exception("pool_execute rate-limited")
            return {
                "pool_id": pool_id,
                "status": "rate_limited",
                "caller_kind": coerced_kind.value,
                "retry_after_seconds": exc.details.get("retry_after_seconds"),
                "error": str(exc),
            }
        except Exception as e:  # noqa: BLE001 - MCP boundary must preserve all operation failures
            logger.error(f"Failed to execute task: {e}")
            return {
                "pool_id": pool_id,
                "status": "failed",
                "error": str(e),
            }

    @mcp.tool()
    async def pool_route_execute(
        prompt: str,
        pool_selector: str = "least_loaded",
        timeout: int = 300,
        caller_pool_allowlist: list[str] | None = None,
        caller_kind: str = "unknown",
        parent_session_id: str | None = None,
        worker_type: str | None = None,
        auto_spawn: bool = False,
    ) -> dict[str, Any]:
        """Route a prompt to the best Mahavishnu worker pool automatically.

        Suitable for non-trivial coding work — multi-file refactors, test
        runs, builds, dependency analysis, cross-repo operations, code
        reviews, and any task that should appear in ecosystem observability.
        The pool handles retry, observability (every operation logged to
        Dhara), and cross-server delegation. Pools span local, delegated
        (Session-Buddy), and GPU-cloud (RunPod) workers.

        **Selector strategies:**
        - ``least_loaded`` (default) — route to the pool with fewest active workers
        - ``round_robin`` — distribute across pools
        - ``random`` — random pool selection
        - ``affinity`` — route to a specific pool (requires ``caller_pool_allowlist``)
        - ``peer_affinity`` — route based on the peer's preferred pool (ADR-014)

        For async/long-running work (refactors, builds, multi-repo sweeps),
        use ``dispatch_to_pool(async_callback=True)`` instead, which returns
        a ``workflow_id`` immediately.

        **ADR-014 caller authorization:**
        When ``pool_selector`` is ``affinity`` or ``peer_affinity``, the
        caller MUST supply ``caller_pool_allowlist`` declaring which pools
        it may dispatch into. Otherwise the manager falls back to
        ``least_loaded``. When the caller (this MCP tool) has a known
        allowlist — typically from
        ``MAHAVISHNU_PEER_AFFINITY_ALLOWLIST`` in the environment — the
        list is forwarded to ``PoolManager.route_task`` so the manager can
        authorize specific-pool selectors (AFFINITY and PEER_AFFINITY)
        against it. When the caller does not supply an allowlist, the
        manager refuses to honor specific-pool selectors and falls back to
        LEAST_LOADED.

        Note: this tool no longer refuses ``peer_affinity`` at the surface.
        The MCP-level refusal has been removed now that caller-side
        authorization is enforced inside ``PoolManager.route_task``. To gate
        PEER_AFFINITY traffic at the deployment boundary, set
        ``MAHAVISHNU_PEER_AFFINITY_ALLOWLIST`` to a comma-separated list of
        pool IDs (or ``*`` to allow all currently-registered pools).

        Args:
            prompt: Clear task description. Be specific about the goal and
                any constraints (paths, file types, expected output).
            pool_selector: Pool selection strategy. Default ``least_loaded``.
            timeout: Max seconds to wait. Default 300.
            caller_pool_allowlist: Optional list of pool IDs the caller is
                authorized to dispatch into (ADR-014).
            caller_kind: Identity of the caller for observability/quota
                enforcement. Default ``unknown``; resolved via
                ``coerce_caller_kind`` before reaching the manager.
            parent_session_id: Optional session ID for cross-system
                correlation (e.g., Claude Code session id, ultracode
                workflow id). Forwarded to ``route_task`` so terminal
                results land under ``workflow-results/{workflow_id}/``.

        Returns:
            Execution result from the worker pool, or rate-limit / failure
            dict on error. ``RateLimitError`` is caught and surfaced as
            ``{"status": "rate_limited", "caller_kind": ..., "retry_after_seconds": ...}``
            so MCP callers can back off without re-trying against the same
            window.

        Example:
            ```
            # Multi-file refactor with auto-routing
            result = await pool_route_execute(
                prompt="Refactor the validation layer to use Pydantic v2 across "
                       "all adapters in mahavishnu/agents/. Run tests after.",
                pool_selector="least_loaded",
                timeout=900,
            )
            ```
        """
        # Durable-routing fast path: when the caller pins a ``worker_type``
        # in the explicit per-worker_type allowlist AND a
        # DurableWorkerManager is configured, spawn via the contract
        # directly and return the worker_id/pane pair without going
        # through the legacy pool router. All auth gates (caller_kind
        # coercion, quota enforcement, ADR-014 allowlist) run BEFORE
        # the fast path so a caller cannot bypass them by routing here.
        try:
            allowed, _coerced_kind = _authorize_durable_fast_path(
                pool_manager,
                caller_kind,
                pool_selector,
                caller_pool_allowlist,
            )
        except RateLimitError as exc:
            return {
                "status": "rate_limited",
                "caller_kind": caller_kind,
                "retry_after_seconds": exc.details.get("retry_after_seconds"),
                "error": str(exc),
            }
        if (
            allowed
            and worker_type is not None
            and _durable_manager is not None
            and worker_type in _DURABLE_WORKER_TYPES
        ):
            # Exercise the per-caller_kind quota on the fast path so a
            # caller cannot bypass ``_enforce_caller_quota`` by routing
            # through the durable branch (Task 24 security review:
            # gate-action-field-mismatch fix). The legacy
            # ``route_task`` path also calls this hook, so the durable
            # fast path mirrors that contract without double-counting
            # for callers who fall through to the legacy path.
            enforce = getattr(pool_manager, "_enforce_caller_quota", None)
            if enforce is not None:
                try:
                    enforce(_coerced_kind)
                except RateLimitError as exc:
                    return {
                        "status": "rate_limited",
                        "caller_kind": caller_kind,
                        "retry_after_seconds": exc.details.get("retry_after_seconds"),
                        "error": str(exc),
                    }
            _metrics.record("pool_route_execute")
            _metrics.record_pool_share(pool_calls=1, terminal_calls=0)
            spawn_result = _durable_manager.spawn(
                worker_type=worker_type,
                backend="claude_tui",
                command=[worker_type],
            )
            return {
                "worker_id": spawn_result.worker_id,
                "pane": spawn_result.pane,
            }

        from mahavishnu.core.config import MahavishnuSettings
        from mahavishnu.pools.manager import PoolSelector, coerce_caller_kind
        from mahavishnu.workers.capabilities import select_routable_workers

        coerced_kind = coerce_caller_kind(caller_kind)

        # Resolve the caller-side allowlist. Explicit
        # ``caller_pool_allowlist`` argument wins over the
        # environment default, so callers (and tests) can
        # override the deployment default on a per-call basis.
        if caller_pool_allowlist is None:
            allowlist = _resolve_peer_affinity_allowlist_from_env()
        else:
            allowlist = set(caller_pool_allowlist)
        # Note: when the allowlist contains the "*" wildcard
        # sentinel, we pass the wildcard set through to the
        # manager. The manager recognizes the sentinel and
        # intersects with its live pool set so the allowlist
        # stays accurate across pool respawns.

        task = {
            "prompt": prompt,
            "timeout": timeout,
            "parent_session_id": parent_session_id,
            "caller_kind": coerced_kind.value,
        }

        # Surface the capability-aware worker snapshot alongside the
        # task. The pool router still picks a pool by selector, but
        # having routable workers in the task payload lets the
        # downstream adapter (and observability) honor the same
        # gating as the CLI and MCP discover_tools surfaces.
        try:
            task["routable_workers"] = select_routable_workers(
                settings=MahavishnuSettings(),
            )
        except Exception as e:  # noqa: BLE001 - MCP boundary must preserve all operation failures
            # Settings may be unavailable in test environments; we
            # never want capability resolution to block routing.
            logger.debug("Routable workers resolution skipped: %s", e)

        try:
            selector = PoolSelector(pool_selector)
            result = await pool_manager.route_task(
                task,
                selector,
                caller_pool_allowlist=allowlist,
                caller_kind=caller_kind,
                parent_session_id=parent_session_id,
                auto_spawn=auto_spawn,
            )
            return result  # type: ignore[no-any-return]
        except RateLimitError as exc:
            logger.exception("pool_route_execute failed")
            return {
                "status": "rate_limited",
                "caller_kind": coerced_kind.value,
                "retry_after_seconds": exc.details.get("retry_after_seconds"),
                "error": str(exc),
            }
        except Exception as e:
            logger.exception("pool_route_execute failed")
            return {
                "status": "failed",
                "error": str(e),
            }

    @mcp.tool()
    async def dispatch_to_pool(
        prompt: str,
        pool_selector: str = "least_loaded",
        caller_kind: str = "unknown",
        parent_session_id: str | None = None,
        timeout: int = 300,
        async_callback: bool = False,
        worker_type: str | None = None,
        workflow_id: str | None = None,
    ) -> dict[str, Any]:
        """Async-callback sibling of pool_route_execute for long-running or multi-step work.

        ``dispatch_to_pool`` routes a prompt through the same pool-selection
        logic as ``pool_route_execute`` but with a caller-side audit trail
        (``caller_kind``, ``parent_session_id``) and an optional
        async-callback mode that returns a ``workflow_id`` immediately so
        the caller (e.g., an ultracode subagent or Claude Code session) is
        not blocked for the full ``timeout`` window.

        Concrete use cases:

        - Multi-repo refactors, full test sweeps, builds, or migrations
          whose work exceeds a few minutes.
        - External agents (ultracode subagent, workflow runner,
          claude_code session) that need an audit trail linking the
          caller's session id to the Mahavishnu ``workflow_id``. Routing
          decisions and quota buckets are recorded under ``caller_kind``
          so operators can attribute load and rate-limit aggressively
          without affecting other callers.
        - Async-callback work where the caller polls
          ``workflow-results/{workflow_id}/`` in Dhara instead of holding
          a request open.

        **Selector strategies:** Same as ``pool_route_execute`` —
        ``least_loaded`` (default), ``round_robin``, ``random``,
        ``affinity``, ``peer_affinity``.

        **Caller kinds:** ``claude_code`` (Claude Code session),
        ``ultracode`` (Workflow-tool subagent), ``workflow`` (in-process
        Mahavishnu workflow), ``cli`` (CLI invocation).

        **Sync path (``async_callback=False``):**
        Returns the ``route_task`` result inline. ``RateLimitError`` is
        caught and surfaced as
        ``{"status": "rate_limited", "caller_kind": ..., "retry_after_seconds": ...}``
        so MCP callers can back off without re-trying against the same
        window. Other failures return ``{"status": "failed", "error": "..."}``.

        **Async path (``async_callback=True``):**
        Returns immediately with a ``workflow_id`` and a
        ``status: "queued"`` marker. The actual routing runs in a
        background task scheduled via ``asyncio.create_task``. Terminal
        state (``completed`` or ``failed``) is persisted to Dhara under
        ``workflow-results/{workflow_id}/`` once the task finishes;
        ``running`` is written before the underlying ``route_task`` is
        awaited so a partial-failure observer can spot hung workflows.

        **Limitation:** the async path uses ``asyncio.create_task``
        (fire-and-forget). If the event loop is closed before the
        background task begins running, asyncio emits
        ``"Task was destroyed but it is pending!"``. Operators needing
        durability past server shutdown should extend the dispatch path
        with a persistent queue (Arq, RQ, Redis Streams). Dhara write
        failures dead-letter to ``~/.mahavishnu/async-dead-letter/{safewid}.json``
        so no terminal state is silently lost.

        Args:
            prompt: Clear task description.
            pool_selector: Pool selection strategy. Default ``least_loaded``.
            caller_kind: Identity of the caller for observability/quota
                enforcement. Default ``ultracode``; one of ``claude_code``,
                ``ultracode``, ``workflow``, ``cli``. Resolved via
                ``coerce_caller_kind`` before reaching the manager.
            parent_session_id: Optional session ID for cross-system
                correlation (e.g., Claude Code session id, ultracode
                workflow id). Forwarded to ``route_task`` so terminal
                results land under
                ``workflow-results/{workflow_id}/``.
            timeout: Max seconds to wait. Default 300.
            async_callback: If True, return ``workflow_id`` immediately
                and write the result to Dhara when complete. Default
                False (sync).

        Returns:
            - ``async_callback=True``: ``{"workflow_id": "...",
              "status": "queued", "caller_kind": ..., "parent_session_id": ...}``
            - ``async_callback=False``: Execution result, rate-limit
              dict, or error dict.

        Example (ultracode subagent):
            ```
            # In an ultracode subagent that needs to wait for a refactor
            result = await dispatch_to_pool(
                prompt="Run the cross-repo dependency update DAG on the auth "
                       "module and produce a summary diff.",
                caller_kind="ultracode",
                parent_session_id="ses_abc123",
                async_callback=True,
            )
            workflow_id = result["workflow_id"]
            # Poll workflow-results/{workflow_id}/ later
            ```
        """
        # Durable-routing fast path: when the caller pins a ``worker_type``
        # in the explicit per-worker_type allowlist AND supplies a
        # ``workflow_id``, spawn via the contract directly and persist
        # worker_id under ``workflow-results/{workflow_id}/`` so
        # downstream pollers can observe the durable assignment. All
        # auth gates (caller_kind coercion, quota enforcement, ADR-014
        # allowlist) run BEFORE the fast path so a caller cannot bypass
        # them by routing here. ``workflow_id`` is also validated
        # against a conservative regex BEFORE splicing into the Dhara
        # key — a caller-supplied ``../../etc/passwd`` would otherwise
        # escape ``workflow-results/``.
        try:
            allowed, _coerced_kind = _authorize_durable_fast_path(
                pool_manager,
                caller_kind,
                pool_selector,
                None,  # dispatch_to_pool does not expose caller_pool_allowlist
            )
        except RateLimitError as exc:
            return {
                "status": "rate_limited",
                "caller_kind": caller_kind,
                "retry_after_seconds": exc.details.get("retry_after_seconds"),
                "error": str(exc),
            }
        if (
            allowed
            and worker_type is not None
            and _durable_manager is not None
            and workflow_id is not None
            and worker_type in _DURABLE_WORKER_TYPES
        ):
            # Path-traversal guard: refuse workflow_ids that don't match
            # the conservative regex BEFORE splicing into the Dhara key.
            if not _validate_workflow_id(workflow_id):
                return {"workflow_id": workflow_id, "status": "invalid_workflow_id"}
            spawn_result = _durable_manager.spawn(
                worker_type=worker_type,
                backend="claude_tui",
                command=[worker_type],
            )
            if _dhara is not None:
                _dhara.put(
                    f"workflow-results/{workflow_id}/",
                    {
                        "worker_id": spawn_result.worker_id,
                        "status": "started",
                    },
                )
            return {
                "worker_id": spawn_result.worker_id,
                "workflow_id": workflow_id,
            }

        from mahavishnu.pools.manager import PoolSelector, coerce_caller_kind

        coerced_kind = coerce_caller_kind(caller_kind)
        task = {
            "prompt": prompt,
            "timeout": timeout,
        }

        if not async_callback:
            try:
                selector = PoolSelector(pool_selector)
                result = await pool_manager.route_task(
                    task,
                    selector,
                    caller_kind=coerced_kind,
                    parent_session_id=parent_session_id,
                )
                return result  # type: ignore[no-any-return]
            except RateLimitError as exc:
                return {
                    "status": "rate_limited",
                    "caller_kind": coerced_kind.value,
                    "retry_after_seconds": exc.details.get("retry_after_seconds"),
                    "error": str(exc),
                }
            except Exception as exc:
                logger.exception("dispatch_to_pool: sync dispatch failed")
                return {
                    "status": "failed",
                    "error": str(exc),
                }

        workflow_id = str(uuid4())
        logger.info(
            "dispatch_to_pool: queued async workflow_id=%s caller_kind=%s parent_session_id=%s",
            workflow_id,
            coerced_kind.value,
            parent_session_id,
        )

        dhara = getattr(pool_manager, "_dhara_state", None)
        if dhara is not None:
            try:
                await dhara.put(
                    f"workflow-results/{workflow_id}/",
                    {
                        "workflow_id": workflow_id,
                        "status": "queued",
                        "caller_kind": coerced_kind.value,
                        "parent_session_id": parent_session_id,
                        "queued_at": datetime.now(UTC).isoformat(),
                    },
                )
            except Exception as exc:  # noqa: BLE001 - MCP boundary must preserve all operation failures
                logger.warning(
                    "dispatch_to_pool: initial queued state write failed workflow_id=%s error=%s",
                    workflow_id,
                    exc,
                )

        selector = PoolSelector(pool_selector)
        asyncio.create_task(
            _run_async_dispatch(
                pool_manager=pool_manager,
                workflow_id=workflow_id,
                task=task,
                selector=selector,
                caller_kind=coerced_kind,
                parent_session_id=parent_session_id,
            )
        )

        return {
            "workflow_id": workflow_id,
            "status": "queued",
            "caller_kind": coerced_kind.value,
            "parent_session_id": parent_session_id,
        }

    @mcp.tool()
    async def workflow_result(
        workflow_id: str,
    ) -> dict[str, Any]:
        """Retrieve the result of an async dispatch_to_pool workflow.

        Reads the persisted state from Dhara at
        ``workflow-results/{workflow_id}/`` and returns the current
        status and result. Returns ``status: "not_found"`` if the
        workflow id is unknown or if Dhara is not configured on the
        pool manager.

        Args:
            workflow_id: The id returned by
                ``dispatch_to_pool(async_callback=True)``.

        Returns:
            Mapping with ``workflow_id``, ``status``, ``result``,
            ``error``, ``rate_limited``, and ``retry_after_seconds``
            when the record exists. ``result`` and ``error`` are
            ``None`` when the corresponding key was not persisted.
            When the workflow is missing or Dhara is unavailable, the
            response is ``{"workflow_id": ..., "status": "not_found"}``.
            When ``workflow_id`` is rejected by the path-traversal guard,
            the response is ``{"workflow_id": ..., "status": "invalid_workflow_id"}``
            and Dhara is never queried.
        """
        # Path-traversal guard: caller-supplied workflow_id is spliced
        # into ``f"workflow-results/{workflow_id}/"`` below, so reject
        # anything outside the conservative regex BEFORE the Dhara read.
        if not _validate_workflow_id(workflow_id):
            return {"workflow_id": workflow_id, "status": "invalid_workflow_id"}
        dhara = getattr(pool_manager, "_dhara_state", None)
        if dhara is None:
            return {"workflow_id": workflow_id, "status": "not_found"}
        # dispatch_to_pool writes under `workflow-results/{id}/`; the
        # trailing slash is part of the key, not a directory hint.
        record = await dhara.get(f"workflow-results/{workflow_id}/")
        if not record:
            return {"workflow_id": workflow_id, "status": "not_found"}
        return {
            "workflow_id": workflow_id,
            "status": record.get("status", "unknown"),
            "result": record.get("result"),
            "error": record.get("error"),
            "rate_limited": bool(record.get("rate_limited", False)),
            "retry_after_seconds": record.get("retry_after_seconds"),
        }

    @mcp.tool()
    async def pool_list() -> list[dict[str, Any]]:
        """List all active pools."""
        try:
            return await pool_manager.list_pools()  # type: ignore[no-any-return]
        except Exception as e:  # noqa: BLE001 - MCP boundary must preserve all operation failures
            logger.error(f"Failed to list pools: {e}")
            return []

    @mcp.tool()
    async def pool_monitor(
        pool_ids: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Monitor pool status and metrics."""
        try:
            return await pool_manager.aggregate_results(pool_ids)  # type: ignore[no-any-return]
        except Exception as e:  # noqa: BLE001 - MCP boundary must preserve all operation failures
            logger.error(f"Failed to monitor pools: {e}")
            return {}

    @mcp.tool()
    async def pool_scale(
        pool_id: str,
        target_workers: int,
    ) -> dict[str, Any]:
        """Scale pool to target worker count."""
        try:
            pool = pool_manager._pools.get(pool_id)
            if not pool:
                return {
                    "pool_id": pool_id,
                    "status": "failed",
                    "error": f"Pool not found: {pool_id}",
                }

            await pool.scale(target_workers)

            return {
                "pool_id": pool_id,
                "target_workers": target_workers,
                "actual_workers": len(pool._workers),
                "status": "scaled",
            }
        except NotImplementedError:
            return {
                "pool_id": pool_id,
                "status": "failed",
                "error": "Pool does not support scaling (e.g., SessionBuddyPool is fixed at 3 workers)",
            }
        except Exception as e:  # noqa: BLE001 - MCP boundary must preserve all operation failures
            logger.error(f"Failed to scale pool: {e}")
            return {
                "pool_id": pool_id,
                "status": "failed",
                "error": str(e),
            }

    @mcp.tool()
    async def pool_close(
        pool_id: str,
    ) -> dict[str, Any]:
        """Close a specific pool."""
        try:
            await pool_manager.close_pool(pool_id)

            return {
                "pool_id": pool_id,
                "status": "closed",
            }
        except Exception as e:  # noqa: BLE001 - MCP boundary must preserve all operation failures
            logger.error(f"Failed to close pool: {e}")
            return {
                "pool_id": pool_id,
                "status": "failed",
                "error": str(e),
            }

    @mcp.tool()
    async def pool_close_all() -> dict[str, Any]:
        """Close all active pools."""
        try:
            pools = await pool_manager.list_pools()
            count = len(pools)

            await pool_manager.close_all()

            return {
                "pools_closed": count,
                "status": "all_closed",
            }
        except Exception as e:  # noqa: BLE001 - MCP boundary must preserve all operation failures
            logger.error(f"Failed to close pools: {e}")
            return {
                "pools_closed": 0,
                "status": "failed",
                "error": str(e),
            }

    @mcp.tool()
    async def pool_health() -> dict[str, Any]:
        """Get health status of all pools."""
        try:
            return await pool_manager.health_check()  # type: ignore[no-any-return]
        except Exception as e:  # noqa: BLE001 - MCP boundary must preserve all operation failures
            logger.error(f"Failed to get health: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
            }

    @mcp.tool()
    async def pool_search_memory(
        query: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Search memory across all pools."""
        try:
            aggregator_cls = MemoryAggregator
            if aggregator_cls is None:
                raise RuntimeError("MemoryAggregator is not available")

            aggregator = aggregator_cls()
            results = await aggregator.cross_pool_search(
                query=query,
                pool_manager=pool_manager,
                limit=limit,
            )

            return results
        except Exception as e:  # noqa: BLE001 - MCP boundary must preserve all operation failures
            logger.error(f"Failed to search memory: {e}")
            return []

    logger.info("Registered 12 pool management tools")
