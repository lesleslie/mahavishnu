#!/usr/bin/env python
"""Pydantic AI integration with the MahavishnuAgent.

Demonstrates how to wire MahavishnuAgent into a Pydantic AI agent
using typed request/response models and the RunContext dependency
injection pattern. Covers:

1. Basic repository sweep with adaptive routing
2. Task routing with natural-language intent classification
3. Pool status monitoring for capacity-aware orchestration
4. Registering MahavishnuAgent as a Pydantic AI tool via RunContext

Run with:
    python examples/pydantic_ai_agent.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Any

from pydantic_ai import Agent, RunContext

from mahavishnu.agents import MahavishnuAgent, get_mahavishnu_agent
from mahavishnu.agents.mahavishnu_agent import (
    PoolStatusResult,
    RouteTaskRequest,
    RouteTaskResult,
    RoutingInfoResult,
    SweepReposRequest,
    SweepReposResult,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-24s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Basic repository sweep
# ---------------------------------------------------------------------------


async def basic_sweep(agent: MahavishnuAgent) -> None:
    """Execute a dry-run sweep across repos tagged 'backend'.

    Uses the balanced routing strategy with the Agno adapter.
    The dry_run flag means no workflows are actually dispatched;
    it only validates the request and resolves the tag to repos.
    """
    logger.info("=== Basic sweep example ===")

    request = SweepReposRequest(
        tag="backend",
        adapter="agno",
        strategy="balanced",
        dry_run=True,
    )

    result: SweepReposResult = await agent.sweep_repos(request)

    if result.success:
        logger.info(
            "Sweep completed: %d repos processed via %s (workflow %s)",
            result.repos_processed,
            result.adapter_used,
            result.workflow_id,
        )
    else:
        logger.warning("Sweep failed: %s", result.error)


# ---------------------------------------------------------------------------
# 2. Task routing with intent classification
# ---------------------------------------------------------------------------


async def task_routing(agent: MahavishnuAgent) -> None:
    """Route a natural-language task to the optimal adapter.

    MahavishnuAgent classifies the intent string into a TaskType
    enum, selects the best adapter for the chosen strategy, and
    executes with an optional fallback chain.
    """
    logger.info("=== Task routing example ===")

    # --- latency-optimised routing ------------------------------------------
    latency_request = RouteTaskRequest(
        intent="Run security scan on backend repositories",
        strategy="latency",
        enable_fallback=True,
    )
    latency_result: RouteTaskResult = await agent.route_task(latency_request)

    if latency_result.success:
        logger.info(
            "Routed to %s (type=%s) with fallback chain %s",
            latency_result.adapter_used,
            latency_result.task_type,
            latency_result.fallback_chain,
        )
    else:
        logger.warning("Routing failed: %s", latency_result.error)

    # --- cost-optimised routing with context --------------------------------
    cost_request = RouteTaskRequest(
        intent="Generate embeddings for documentation",
        strategy="cost",
        enable_fallback=True,
        context={"budget_remaining": 50.0, "max_latency_ms": 2000},
    )
    cost_result: RouteTaskResult = await agent.route_task(cost_request)

    logger.info(
        "Cost-optimised routing selected adapter '%s' for task type '%s'",
        cost_result.adapter_used,
        cost_result.task_type,
    )


# ---------------------------------------------------------------------------
# 3. Pool status monitoring
# ---------------------------------------------------------------------------


async def pool_status(agent: MahavishnuAgent) -> None:
    """Retrieve current worker pool status.

    Useful for capacity planning and load-balancing decisions
    before dispatching expensive orchestration tasks.
    """
    logger.info("=== Pool status example ===")

    status: PoolStatusResult = await agent.get_pool_status()

    if status.error:
        logger.warning("Pool status unavailable: %s", status.error)
        return

    logger.info(
        "Pools: %d  Active workers: %d",
        status.total_pools,
        status.active_workers,
    )
    for pool in status.pools:
        pool_id = pool.get("pool_id", "unknown")
        health = pool.get("health", "unknown")
        workers = pool.get("active_workers", 0)
        logger.info("  Pool %s: health=%s  workers=%d", pool_id, health, workers)


# ---------------------------------------------------------------------------
# 4. Pydantic AI integration with RunContext
# ---------------------------------------------------------------------------


@dataclass
class MahavishnuDeps:
    """Dependencies injected into the Pydantic AI agent.

    Wraps the MahavishnuAgent so that every tool function can
    access it through RunContext without global state.
    """

    agent: MahavishnuAgent


# Build a Pydantic AI agent whose tools delegate to MahavishnuAgent.
pydantic_agent = Agent[MahavishnuDeps, str](
    model="openai:gpt-4o",
    deps_type=MahavishnuDeps,
    system_prompt=(
        "You are an orchestration assistant that manages repositories "
        "and worker pools via Mahavishnu. Use the available tools to "
        "sweep repos, route tasks, check pool health, and inspect "
        "routing decisions. Summarise results concisely."
    ),
)


@pydantic_agent.tool
async def sweep_repos(
    ctx: RunContext[MahavishnuDeps],
    tag: str,
    adapter: str = "agno",
    strategy: str = "balanced",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sweep repositories matching the given tag.

    Args:
        ctx: Pydantic AI run context carrying the MahavishnuAgent.
        tag: Repository tag to target (e.g. 'backend', 'python').
        adapter: Orchestration adapter ('agno', 'llamaindex', 'prefect').
        strategy: Routing strategy ('cost', 'latency', 'success_rate', 'balanced').
        dry_run: If True, simulate without executing workflows.
    """
    request = SweepReposRequest(
        tag=tag,
        adapter=adapter,  # type: ignore[arg-type]
        strategy=strategy,  # type: ignore[arg-type]
        dry_run=dry_run,
    )
    result = await ctx.deps.agent.sweep_repos(request)
    return result.model_dump()


@pydantic_agent.tool
async def route_task(
    ctx: RunContext[MahavishnuDeps],
    intent: str,
    strategy: str = "balanced",
    enable_fallback: bool = True,
) -> dict[str, Any]:
    """Route a task described in natural language to the best adapter.

    Args:
        ctx: Pydantic AI run context carrying the MahavishnuAgent.
        intent: Natural-language description of the task.
        strategy: Routing strategy for adapter selection.
        enable_fallback: Whether to enable fallback chain on failure.
    """
    request = RouteTaskRequest(
        intent=intent,
        strategy=strategy,  # type: ignore[arg-type]
        enable_fallback=enable_fallback,
    )
    result = await ctx.deps.agent.route_task(request)
    return result.model_dump()


@pydantic_agent.tool
async def check_pool_status(
    ctx: RunContext[MahavishnuDeps],
) -> dict[str, Any]:
    """Check the current worker pool status and capacity."""
    result = await ctx.deps.agent.get_pool_status()
    return result.model_dump()


@pydantic_agent.tool
async def get_routing_info(
    ctx: RunContext[MahavishnuDeps],
    task_type: str = "ai_task",
    strategy: str = "balanced",
) -> dict[str, Any]:
    """Get routing decision details for a given task type and strategy.

    Returns the fallback chain, primary adapter, and per-adapter scores.

    Args:
        ctx: Pydantic AI run context carrying the MahavishnuAgent.
        task_type: Task category (e.g. 'ai_task', 'workflow', 'rag_query').
        strategy: Routing strategy to inspect.
    """
    result: RoutingInfoResult = await ctx.deps.agent.get_routing_info(
        task_type=task_type,
        strategy=strategy,
    )
    return result.model_dump()


async def pydantic_ai_example(agent: MahavishnuAgent) -> None:
    """Run the Pydantic AI agent with MahavishnuAgent as a dependency.

    Demonstrates the RunContext pattern: MahavishnuAgent is injected
    once via MahavishnuDeps and accessed by every tool function through
    ctx.deps without coupling to global state.
    """
    logger.info("=== Pydantic AI integration example ===")

    deps = MahavishnuDeps(agent=agent)

    # The LLM will select and invoke the appropriate tool(s) based on
    # the user prompt. Each tool transparently delegates to the
    # MahavishnuAgent via RunContext.
    try:
        result = await pydantic_agent.run(
            "Check pool status, then sweep all 'python' repos with the "
            "balanced strategy as a dry run.",
            deps=deps,
        )
        logger.info("Pydantic AI agent response: %s", result.output)
    except Exception:
        # The agent may fail if no LLM provider is configured, which
        # is fine for demonstration purposes.
        logger.exception(
            "Pydantic AI agent call failed (this is expected without a configured LLM provider)"
        )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    """Run all examples sequentially."""
    logger.info("MahavishnuAgent + Pydantic AI integration examples")
    logger.info("-" * 55)

    # Obtain the singleton agent (or inject a test instance here).
    agent = get_mahavishnu_agent()

    await basic_sweep(agent)
    await task_routing(agent)
    await pool_status(agent)
    await pydantic_ai_example(agent)

    logger.info("-" * 55)
    logger.info("All examples complete.")


if __name__ == "__main__":
    asyncio.run(main())
