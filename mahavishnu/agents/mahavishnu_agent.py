"""Mahavishnu agent for Pydantic AI and external platform integration.

Exports Mahavishnu's orchestration capabilities as typed tools
consumable by Pydantic AI agents, OpenClaw webhooks, and other
frameworks.

Design Reference:
- docs/plans/PRE_IMPLEMENTATION_CHECKLIST.md (P0 prerequisites)
- mahavishnu/factories.py (singleton pattern)
- mahavishnu/core/routing.py (TaskRouter, RoutingStrategy)

Usage:
    from mahavishnu.agents import get_mahavishnu_agent

    agent = get_mahavishnu_agent()

    # Execute sweep across tagged repos
    result = await agent.sweep_repos(tag="backend", adapter="agno")

    # Route task to best adapter
    result = await agent.route_task(
        intent="security scan backend repos",
        strategy="success_rate",
    )

    # Get pool status
    status = await agent.get_pool_status()
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.core.metrics_schema import TaskType
from mahavishnu.core.routing import RoutingStrategy, TaskRouter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class SweepReposRequest(BaseModel):
    """Validated request for sweep_repos."""

    tag: str = Field(
        ...,
        min_length=1,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Repository tag to sweep",
    )
    adapter: Literal["agno", "llamaindex", "prefect"] = Field(
        default="agno",
        description="Orchestration adapter to use",
    )
    strategy: Literal["cost", "latency", "success_rate", "balanced"] = Field(
        default="balanced",
        description="Routing strategy",
    )
    dry_run: bool = Field(
        default=False,
        description="Simulate without executing",
    )


class SweepReposResult(BaseModel):
    """Typed result from sweep_repos."""

    workflow_id: str = ""
    tag: str
    repos_processed: int = 0
    adapter_used: str = ""
    success: bool = False
    results: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class RouteTaskRequest(BaseModel):
    """Validated request for route_task."""

    intent: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Natural language task description",
    )
    strategy: Literal["cost", "latency", "success_rate", "balanced"] = Field(
        default="balanced",
        description="Routing strategy",
    )
    enable_fallback: bool = Field(
        default=True,
        description="Enable fallback chain",
    )
    context: dict[str, Any] | None = Field(
        default=None,
        description="Additional routing context (budget, latency requirements)",
    )


class RouteTaskResult(BaseModel):
    """Typed result from route_task."""

    intent: str
    task_type: str
    adapter_used: str
    fallback_chain: list[str] = Field(default_factory=list)
    success: bool = False
    results: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class PoolStatusResult(BaseModel):
    """Typed result from get_pool_status."""

    pools: list[dict[str, Any]] = Field(default_factory=list)
    total_pools: int = 0
    active_workers: int = 0
    error: str | None = None


class RoutingInfoResult(BaseModel):
    """Typed result from get_routing_info."""

    task_type: str
    strategy: str
    fallback_chain: list[str] = Field(default_factory=list)
    primary_adapter: str | None = None
    adapter_scores: dict[str, float] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------


class MahavishnuAgent:
    """Mahavishnu orchestration agent for external AI platforms.

    Provides a typed, validated API surface over Mahavishnu's
    orchestration capabilities including:

    - sweep_repos: Parallel sweeps across tagged repositories
    - route_task: Adaptive routing with intent classification
    - get_pool_status: Worker pool capacity and health
    - get_routing_info: Routing decision debugging

    The agent wraps MahavishnuApp with dependency injection:
    pass an existing app instance or let one be created from config.

    Example:
        >>> agent = MahavishnuAgent()
        >>> result = await agent.sweep_repos(
        ...     tag="backend",
        ...     adapter="agno",
        ...     strategy="balanced",
        ... )
        >>> print(result.success)
        True
    """

    def __init__(
        self,
        app: MahavishnuApp | None = None,
        config: MahavishnuSettings | None = None,
    ) -> None:
        """Initialize agent with optional dependency injection.

        Args:
            app: Existing MahavishnuApp instance (preferred for testing)
            config: Configuration if app not provided
        """
        if app is not None:
            self._app = app
        elif config is not None:
            self._app = MahavishnuApp(config)
        else:
            settings = MahavishnuSettings()
            self._app = MahavishnuApp(settings)

        self._router = TaskRouter()

    # -- Public API --------------------------------------------------------

    async def sweep_repos(self, request: SweepReposRequest) -> SweepReposResult:
        """Execute AI sweep with adaptive routing across tagged repos.

        Resolves tag -> repo list via repos.yaml, routes to optimal
        adapter based on strategy, and falls back through the adapter
        chain on failure.

        Args:
            request: Validated sweep request with tag, adapter, strategy.

        Returns:
            SweepReposResult with workflow status and per-repo results.
        """
        try:
            repos = self._app.get_repos(tag=request.tag)

            if not repos:
                return SweepReposResult(
                    tag=request.tag,
                    error=f"No repos found with tag '{request.tag}'",
                )

            task = {
                "type": "code_sweep",
                "params": {"tag": request.tag, "dry_run": request.dry_run},
            }

            if request.strategy != "balanced" or request.adapter != "agno":
                result = await self._app.execute_workflow_with_routing(
                    task=task,
                    repos=repos,
                    routing_strategy=request.strategy,
                    enable_fallback=True,
                )
            else:
                result = await self._app.execute_workflow_parallel(
                    task=task,
                    adapter_name=request.adapter,
                    repos=repos,
                )

            return SweepReposResult(
                workflow_id=result.get("workflow_id", ""),
                tag=request.tag,
                repos_processed=len(repos),
                adapter_used=result.get("adapter_used", request.adapter),
                success=result.get("success", False),
                results=result,
            )

        except Exception as e:
            logger.exception("sweep_repos failed for tag=%s", request.tag)
            return SweepReposResult(
                tag=request.tag,
                error=str(e),
            )

    async def route_task(self, request: RouteTaskRequest) -> RouteTaskResult:
        """Route task to optimal adapter using intent classification.

        Classifies natural language intent into TaskType, selects
        the best adapter based on routing strategy, and executes
        with optional fallback chain.

        Args:
            request: Validated routing request with intent and strategy.

        Returns:
            RouteTaskResult with routing decision and execution results.
        """
        try:
            task_type = self._router.classify_intent(request.intent)
            strategy = RoutingStrategy(request.strategy)

            adapter = await self._router.select_adapter(
                task_type=task_type,
                strategy=strategy,
                context=request.context,
            )

            fallback_chain = self._router.generate_fallback_chain(task_type, adapter)
            await self._router.get_adapter_scores(
                task_type,
                request.context,
            )

            repos = self._app.get_repos()
            task = {
                "type": task_type.value,
                "params": {"intent": request.intent},
            }

            if request.enable_fallback:
                result = await self._app.execute_workflow_with_fallback(
                    task=task,
                    repos=repos,
                    routing_strategy=strategy,
                )
            else:
                result = await self._app.execute_workflow_parallel(
                    task=task,
                    adapter_name=adapter.value,
                    repos=repos,
                )

            return RouteTaskResult(
                intent=request.intent,
                task_type=task_type.value,
                adapter_used=result.get("adapter_used", adapter.value),
                fallback_chain=[a.value for a in fallback_chain],
                success=result.get("success", False),
                results=result,
            )

        except Exception as e:
            logger.exception("route_task failed for intent=%s", request.intent[:50])
            return RouteTaskResult(
                intent=request.intent,
                task_type="unknown",
                adapter_used="",
                error=str(e),
            )

    async def get_pool_status(self) -> PoolStatusResult:
        """Get worker pool status for capacity planning.

        Returns pool health, active workers, and capacity
        information for load balancing decisions.

        Returns:
            PoolStatusResult with pool details.
        """
        try:
            from mahavishnu.factories import get_pool_manager

            pool_mgr = get_pool_manager()
            status = await pool_mgr.get_all_pool_status()

            pools_list = []
            active_workers = 0
            if isinstance(status, dict):
                for pool_id, pool_info in status.items():
                    if isinstance(pool_info, dict):
                        pools_list.append(
                            {
                                "pool_id": pool_id,
                                **pool_info,
                            }
                        )
                        active_workers += pool_info.get("active_workers", 0)

            return PoolStatusResult(
                pools=pools_list,
                total_pools=len(pools_list),
                active_workers=active_workers,
            )

        except Exception as e:
            logger.warning("get_pool_status failed: %s", e)
            return PoolStatusResult(error=str(e))

    async def get_routing_info(
        self,
        task_type: str = "ai_task",
        strategy: str = "balanced",
    ) -> RoutingInfoResult:
        """Get routing decision information for debugging.

        Returns the fallback chain, adapter scores, and primary
        adapter for a given task type and strategy. Useful for
        understanding why a particular adapter was selected.

        Args:
            task_type: Task type string (ai_task, workflow, rag_query, etc.)
            strategy: Routing strategy name.

        Returns:
            RoutingInfoResult with routing details.
        """
        try:
            tt = TaskType(task_type)
            rs = RoutingStrategy(strategy)

            self._router.generate_fallback_chain(tt)
            scores = await self._router.get_adapter_scores(tt)
            info = self._router.get_routing_info(tt, rs)

            return RoutingInfoResult(
                task_type=tt.value,
                strategy=rs.value,
                fallback_chain=info["fallback_chain"],
                primary_adapter=info.get("primary_adapter"),
                adapter_scores={a.value: s for a, s in scores.items()},
            )

        except Exception as e:
            logger.warning("get_routing_info failed: %s", e)
            return RoutingInfoResult(
                task_type=task_type,
                strategy=strategy,
                error=str(e),
            )


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_agent: MahavishnuAgent | None = None


def get_mahavishnu_agent(
    app: MahavishnuApp | None = None,
    config: MahavishnuSettings | None = None,
) -> MahavishnuAgent:
    """Get or create the global MahavishnuAgent singleton.

    Args:
        app: Optional existing MahavishnuApp (inject for testing)
        config: Optional config if creating new app

    Returns:
        MahavishnuAgent singleton instance
    """
    global _agent
    if _agent is None:
        _agent = MahavishnuAgent(app=app, config=config)
    return _agent


def reset_agent() -> None:
    """Reset the agent singleton (for testing)."""
    global _agent
    _agent = None


__all__ = [
    "MahavishnuAgent",
    "SweepReposRequest",
    "SweepReposResult",
    "RouteTaskRequest",
    "RouteTaskResult",
    "PoolStatusResult",
    "RoutingInfoResult",
    "get_mahavishnu_agent",
    "reset_agent",
]
