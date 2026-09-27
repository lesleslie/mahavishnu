"""Pool management MCP tools."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any

from mcp_common.fastmcp import FastMCP  # noqa: TC002

from mahavishnu.core.budget import BudgetRecord, BudgetSpec, BudgetStateMachine

try:
    from mahavishnu.pools.memory_aggregator import MemoryAggregator
except Exception:  # pragma: no cover - optional import for test patching  # noqa: BLE001 - MCP boundary must preserve all operation failures  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
    MemoryAggregator = None

try:
    # Phase 2m (Plan v3): pool_route_execute needs the selector enum, the
    # caller_kind quota attribution enum, the coerce_caller_kind funnel,
    # and the quota error type. Each is defensive-imported so test patching
    # can inject sentinel versions without instantiating the full pools
    # package on import.
    from mahavishnu.core.errors import RateLimitError
    from mahavishnu.pools.manager import CallerKind, PoolSelector, coerce_caller_kind
except Exception:  # pragma: no cover - optional import for test patching  # noqa: BLE001 - MCP boundary must preserve all operation failures  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
    PoolSelector = None
    CallerKind = None
    RateLimitError = None
    coerce_caller_kind = None

try:
    # C-9: per-TaskCategory concurrency gate (REQ-012, REQ-013).
    # Defensive import so test patching can inject a sentinel gate.
    from mahavishnu.core.config import get_settings
    from mahavishnu.core.concurrency_gate import ConcurrencyGate
    from mahavishnu.core.model_routing import TaskCategory, classify_task
    from mahavishnu.core.rate_limit import _estimate_retry
except Exception:  # pragma: no cover - optional import for test patching  # noqa: BLE001 - MCP boundary must preserve all operation failures
    ConcurrencyGate = None
    TaskCategory = None
    classify_task = None
    _estimate_retry = None
    get_settings = None

logger = logging.getLogger(__name__)


# Module-level singleton gate (per-process scope documented in
# ``docs/runbooks/concurrency-limit-storm.md``). Test suites that want
# isolation call ``set_concurrency_gate()`` to swap this out.
_concurrency_gate: ConcurrencyGate | None = (
    ConcurrencyGate(get_settings().concurrency_limits)
    if ConcurrencyGate is not None and get_settings is not None
    else None
)


def get_concurrency_gate() -> ConcurrencyGate | None:
    """Return the module-level ``ConcurrencyGate`` (None when not configured)."""
    return _concurrency_gate


def set_concurrency_gate(gate: ConcurrencyGate | None) -> None:
    """Override the module-level gate (test seam; resets between cases)."""
    global _concurrency_gate
    _concurrency_gate = gate


async def _enforce_concurrency_limit(
    task_category: TaskCategory, pool_id: str | None
) -> None:
    """Acquire a TaskCategory slot or raise RateLimitError (fail-closed).

    No-op when the gate is unconfigured (defensive-import failure in tests)
    or when no spec is registered for the category. Otherwise the gate
    returns False on saturation and we raise — callers MUST NOT silently
    proceed past a denial (REQ-013 fail-closed default).
    """
    gate = get_concurrency_gate()
    if gate is None or task_category is None:
        return
    if not await gate.try_acquire(task_category, pool_id):
        spec = gate.spec_for(task_category)
        raise RateLimitError(
            limit=spec.concurrency_limit if spec else None,
            retry_after_seconds=_estimate_retry(spec) if _estimate_retry else None,
            domain=f"task_category={task_category.value}",
        )


def register_pool_tools(
    mcp: FastMCP,
    pool_manager,
    *,
    budget_store: Any | None = None,
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
        budget_store: Optional :class:`mahavishnu.core.budget_watchdog.BudgetStore`
            used by ``budget_enforce``. When ``None`` (the default, used
            in tests that don't exercise budgets) ``budget_enforce``
            returns ``{"status": "unconfigured"}`` rather than raising.

    This registers 9 pool management tools:
    - pool_list: List all active pools
    - pool_monitor: Monitor pool metrics
    - pool_scale: Scale pool worker count
    - pool_close: Close a specific pool
    - pool_close_all: Close all pools
    - pool_health: Get health status
    - pool_search_memory: Search memory across pools
    - budget_enforce: Declare a per-workflow budget (Phase 3 v2 plan)
    - pool_route_execute: Ad-hoc single-task dispatch across registered pools (Plan v3 Phase 2m)
    """

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

    @mcp.tool()
    async def budget_enforce(
        workflow_id: str,
        budget_tokens: int | None = None,
        budget_turns: int | None = None,
        budget_wallclock_seconds: float | None = None,
        declared_by: str | None = None,
    ) -> dict[str, Any]:
        """Declare a per-workflow budget; the watchdog enforces it.

        ``workflow_id`` must be unique per call. Re-calling with the
        same ``workflow_id`` re-bases the cap (intentional "pause at
        N" semantics on a running run). The MCP boundary swallows
        MCP failures as ``status: "failed"`` rather than raising —
        the watchdog polls against whatever state was last persisted,
        so a partial write here is acceptable.
        """
        if budget_store is None:
            return {
                "workflow_id": workflow_id,
                "status": "unconfigured",
                "error": "budget_store is not configured on this server",
            }
        spec = BudgetSpec(
            budget_tokens=budget_tokens,
            budget_turns=budget_turns,
            budget_wallclock_seconds=budget_wallclock_seconds,
            declared_by=declared_by,
        )
        try:
            existing_raw = await budget_store.get(f"mahavishni://budgets/{workflow_id}.json")
        except Exception as exc:  # noqa: BLE001 - MCP boundary must persist all failures
            logger.warning("budget_enforce: read failed for %s: %s", workflow_id, exc)
            existing_raw = None
        sm = BudgetStateMachine(
            BudgetRecord.from_dict(existing_raw)
            if isinstance(existing_raw, dict) and existing_raw.get("workflow_id")
            else BudgetRecord(workflow_id=workflow_id)
        )
        sm.declare(spec)
        try:
            sm.start(when=datetime.now(UTC))
        except ValueError as exc:
            return {
                "workflow_id": workflow_id,
                "status": "failed",
                "error": str(exc),
            }
        try:
            await budget_store.put(
                f"mahavishni://budgets/{workflow_id}.json",
                sm.record.to_dict(),
            )
        except Exception as exc:  # noqa: BLE001 - MCP boundary must persist all failures
            logger.warning("budget_enforce: persist failed for %s: %s", workflow_id, exc)
            return {
                "workflow_id": workflow_id,
                "status": "failed",
                "error": f"failed to persist budget: {exc}",
            }
        return {
            "workflow_id": workflow_id,
            "status": "active",
            "spec": spec.to_dict(),
            "state": sm.record.state.value,
            "started_at": (
                sm.record.started_at.isoformat() if sm.record.started_at is not None else None
            ),
        }

    @mcp.tool()
    async def pool_route_execute(  # ty: ignore[invalid-argument-type]
        prompt: str,
        pool_selector: str = "least_loaded",
        timeout: float | None = None,
        pool_affinity: str | None = None,
        caller_kind: str = "claude_code",
        parent_session_id: str | None = None,
        auto_spawn: bool = False,
    ) -> dict[str, Any]:
        """Load-balanced single-task dispatch across registered worker pools.

        Plan v3 Phase 2m — Demo Track. Routes one ad-hoc task to the
        best-fit pool via the configured selector. Mirrors the documented
        primary entry point in ``.claude/agents/mahavishnu-specialist.md``
        and ``skills_catalog/pool-route.md``.

        Anti-bug guard (memory rule ``mahavishnu-dispatch-prompt-mangling``):
        Implementation MUST call ``await pool_manager.route_task(...)``
        directly. Do NOT route through ``dispatch_to_pool()`` — that path
        wraps in ``sh -lc`` and re-introduces the prompt-mangling bug.

        ADR 014 (Honcho/ACL composition contract): ``caller_pool_allowlist``
        is set server-side via ``PoolManager``, not exposed to wire callers.
        The ``caller_kind`` parameter is for QUOTA ATTRIBUTION only (which
        ClientKind bucket the dispatch counts against).

        Returns:
            - On success: the dispatch result dict (carries ``pool_id``,
              ``status``, ``result``, etc.).
            - On quota saturation (RateLimitError):
              ``{"status": "rate_limited", "retry_after_seconds": N, "limit": "caller_kind=..."}``.
            - On timeout (asyncio.TimeoutError):
              ``{"status": "timeout"}``.
            - On invalid selector (ValueError):
              ``{"status": "invalid_selector", "error": "..."}``.
            - On pool registry error (RuntimeError):
              ``{"status": "failed", "error": "..."}``.
        """
        # Selector resolution — bad input is a user error, not a system crash.
        if PoolSelector is not None:
            try:
                selector_enum = PoolSelector(pool_selector)
            except ValueError:
                valid = [s.value for s in PoolSelector]
                return {
                    "status": "invalid_selector",
                    "error": f"Unknown pool_selector: {pool_selector!r}. Valid: {valid}",
                }
        else:
            return {
                "status": "failed",
                "error": "Pool selector subsystem unavailable; pools package not loaded",
            }

        # Caller-kind funnel — coerce_caller_kind is module-level in
        # mahavishnu.pools.manager. Unknown wire-strings map to CallerKind.UNKNOWN
        # (one shared bucket per memory rule indirection).
        if coerce_caller_kind is not None:
            try:
                coerced_kind = coerce_caller_kind(caller_kind)
            except Exception:  # noqa: BLE001 - boundary: coerce is best-effort
                coerced_kind = None
        else:
            coerced_kind = None

        task: dict[str, Any] = {"prompt": prompt}
        if timeout is not None:
            task["timeout"] = timeout

        # C-9: per-TaskCategory concurrency gate. Pool_id is unknown at the
        # dispatch entry point (the selector picks it inside route_task), so
        # we use pool_id=None — the gate falls back to the category-only key.
        # Specs without an explicit limit are pass-through; failure here
        # surfaces as RateLimitError and is caught by the envelope handler
        # below (fail-closed per REQ-013).
        task_category: TaskCategory | None = None
        if classify_task is not None:
            try:
                task_category = classify_task(prompt)
            except Exception:  # noqa: BLE001 - boundary: classify is best-effort
                task_category = None

        gate = get_concurrency_gate()
        acquired = False
        try:
            if gate is not None and task_category is not None:
                acquired = await gate.try_acquire(task_category, None)
                if not acquired:
                    spec = gate.spec_for(task_category)
                    raise RateLimitError(
                        limit=spec.concurrency_limit if spec else None,
                        retry_after_seconds=(
                            _estimate_retry(spec) if _estimate_retry else None
                        ),
                        domain=f"task_category={task_category.value}",
                    )
            return await pool_manager.route_task(  # type: ignore[no-any-return]
                task=task,
                pool_selector=selector_enum,
                pool_affinity=pool_affinity,
                caller_kind=coerced_kind if coerced_kind is not None else caller_kind,
                parent_session_id=parent_session_id,
                auto_spawn=auto_spawn,
            )
        except Exception as exc:
            # ``RateLimitError`` is conditionally imported (None on defensive
            # failure); ``except RateLimitError`` is a ty error + silent no-op
            # in the sentinel branch, so dispatch via isinstance + None guard.
            if RateLimitError is not None and isinstance(exc, RateLimitError):
                details = getattr(exc, "details", {}) or {}
                return {
                    "status": "rate_limited",
                    "retry_after_seconds": details.get("retry_after_seconds", 0),
                    "limit": details.get("limit", "caller_kind=unknown"),
                }
            if isinstance(exc, TimeoutError):
                return {"status": "timeout"}
            if isinstance(exc, ValueError):
                return {
                    "status": "invalid_selector",
                    "error": str(exc),
                }
            if isinstance(exc, RuntimeError):
                return {
                    "status": "failed",
                    "error": str(exc),
                }
            logger.exception("Failed to route task via pool_route_execute — see traceback")
            return {
                "status": "failed",
                "error": str(exc),
            }
        finally:
            # Release the concurrency slot regardless of outcome (success,
            # rate-limit denial, timeout, dispatch failure). Without this,
            # the per-process counter would never decrement and the gate
            # would saturate permanently after one burst.
            if acquired and gate is not None and task_category is not None:
                await gate.release(task_category, None)

    logger.info("Registered 9 pool management tools")
