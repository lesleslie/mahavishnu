"""Unified task routing and state synchronization.

Intelligent dispatcher that routes tasks to appropriate orchestration adapters
based on task type, capabilities, and system state. Enables Prefect, Agno,
and LlamaIndex to work together in coordinated workflows.

Architecture:
    ┌─────────────────┐
    │  Mahavishnu Core          │
    │  • Task Analyzer            │
    │  • Adapter Registry            │
    │  • State Manager             │
    └─────────────────┘
                   ↓
        [Intelligent Routing]
                   ↓
    ┌─────────────────┐
    │ Statistical Router          │
    │  • Success rates            │
    │  • Latency scores          │
    │  • Pareto frontier           │
    │  • Confidence intervals      │
    └─────────────────┘
                   ↓
        [Multi-Objective Optimization]
                   ↓
    ┌─────────────────┐
    │  Cost Optimizer            │
    │  • Budget tracking           │
    │  • Constraint solving       │
    │  • Strategy selection       │
    └─────────────────┘
                   ↓
        [Adapter Execution]
                   ↓
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from mahavishnu.core.adapters.base import (
    AdapterType,
    AdapterCapabilities,
    OrchestratorAdapter,
)
from typing import TYPE_CHECKING

from mahavishnu.core.routing_metrics import RoutingMetrics, get_routing_metrics
from mahavishnu.core.resilience import RetryExhaustedError, RetryPolicy, retry_async

if TYPE_CHECKING:
    from mahavishnu.core.cost_optimizer import CostOptimizer
    from mahavishnu.core.statistical_router import StatisticalRouter

# Import capability routing types (optional - for hybrid registry)
try:
    from mahavishnu.core.task_requirements import (
        TaskRequirements,
        RoutingDecision,
        ResolutionCache,
        TASK_CAPABILITY_REQUIREMENTS,
    )

    CAPABILITY_ROUTING_AVAILABLE = True
except ImportError:
    CAPABILITY_ROUTING_AVAILABLE = False
    TaskRequirements = None  # type: ignore[misc,assignment]
    RoutingDecision = None  # type: ignore[misc,assignment]
    ResolutionCache = None  # type: ignore[misc,assignment]
    TASK_CAPABILITY_REQUIREMENTS = {}  # type: ignore[misc]

logger = logging.getLogger(__name__)


class TaskType(StrEnum):
    """Types of tasks that can be routed."""

    WORKFLOW = "workflow"
    AI_TASK = "ai_task"
    RAG_QUERY = "rag_query"


class RouterMode(StrEnum):
    """Routing modes for adapter selection."""

    STATISTICAL = "statistical"  # Use success rates and latency scores
    COST_OPTIMIZED = "cost_optimized"  # Use cost optimization and budgets
    ADAPTIVE = "adaptive"  # Switch strategies based on performance
    CAPABILITY = "capability"  # Use capability-based routing (hybrid registry)


@dataclass(slots=True)
class AdapterExecutionStats:
    """Per-adapter execution statistics."""

    successes: int = 0
    failures: int = 0
    total_attempts: int = 0

    @property
    def success_rate(self) -> float:
        total = self.successes + self.failures
        return self.successes / total if total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "successes": self.successes,
            "failures": self.failures,
            "total_attempts": self.total_attempts,
            "success_rate": self.success_rate,
        }


class AdapterManager:
    """Minimal adapter registry used by TaskRouter and orchestration tests."""

    def __init__(self) -> None:
        self.adapters: dict[AdapterType, OrchestratorAdapter] = {}
        self._stats: dict[str, AdapterExecutionStats] = {}

    async def register_adapter(self, adapter_type: AdapterType, adapter: OrchestratorAdapter) -> None:
        self.adapters[adapter_type] = adapter
        self._stats.setdefault(adapter_type.value, AdapterExecutionStats())

    def get_adapter(self, adapter: AdapterType | str) -> OrchestratorAdapter | None:
        adapter_type = self._coerce_adapter_type(adapter)
        if adapter_type is None:
            return None
        return self.adapters.get(adapter_type)

    def record_execution(
        self,
        adapter_type: AdapterType,
        success: bool,
    ) -> None:
        stats = self._stats.setdefault(adapter_type.value, AdapterExecutionStats())
        stats.total_attempts += 1
        if success:
            stats.successes += 1
        else:
            stats.failures += 1

    def get_statistics(self) -> dict[str, dict[str, Any]]:
        return {name: stats.to_dict() for name, stats in self._stats.items()}

    @staticmethod
    def _coerce_adapter_type(adapter: AdapterType | str | None) -> AdapterType | None:
        if adapter is None:
            return None
        if isinstance(adapter, AdapterType):
            return adapter
        try:
            return AdapterType(adapter)
        except Exception:
            for adapter_type in AdapterType:
                if adapter_type.value == adapter:
                    return adapter_type
        return None


@dataclass(slots=True)
class WorkflowState:
    workflow_id: str
    adapter_states: dict[str, dict[str, Any]] = field(default_factory=dict)


class StateManager:
    """In-memory workflow state manager used by the unified orchestrator."""

    def __init__(self) -> None:
        self._workflows: dict[str, WorkflowState] = {}

    async def create_workflow_state(
        self,
        workflow_id: str,
        adapter_type: str | AdapterType,
        initial_state: dict[str, Any],
    ) -> WorkflowState:
        state = WorkflowState(workflow_id=workflow_id)
        state.adapter_states[self._adapter_key(adapter_type)] = dict(initial_state)
        self._workflows[workflow_id] = state
        return state

    async def update_adapter_state(
        self,
        workflow_id: str,
        adapter_type: str | AdapterType,
        state: dict[str, Any],
    ) -> WorkflowState:
        workflow_state = self._workflows.setdefault(workflow_id, WorkflowState(workflow_id=workflow_id))
        workflow_state.adapter_states[self._adapter_key(adapter_type)] = dict(state)
        return workflow_state

    async def get_workflow_state(self, workflow_id: str) -> dict[str, Any] | None:
        workflow_state = self._workflows.get(workflow_id)
        if workflow_state is None:
            return None
        return {
            "workflow_id": workflow_state.workflow_id,
            "adapter_states": workflow_state.adapter_states,
        }

    async def list_workflows(self, limit: int = 100) -> list[dict[str, Any]]:
        workflows = [
            {
                "workflow_id": workflow_id,
                "adapter_states": state.adapter_states,
            }
            for workflow_id, state in self._workflows.items()
        ]
        return workflows[:limit]

    @staticmethod
    def _adapter_key(adapter_type: str | AdapterType) -> str:
        return adapter_type.value if isinstance(adapter_type, AdapterType) else str(adapter_type)


class CapabilityRouter:
    """Route tasks based on adapter capabilities, not hardcoded mappings.

    This router uses the HybridAdapterRegistry to find adapters that match
    task requirements based on capabilities. It replaces the hardcoded
    TASK_TYPE_ROUTING dictionary with dynamic capability-based resolution.

    Features:
    - Task type → required capabilities mapping
    - Dynamic adapter discovery based on capabilities
    - Resolution caching for performance
    - Fallback chains for graceful degradation
    - Integration with HybridAdapterRegistry

    Example:
        >>> router = CapabilityRouter(registry)
        >>> decision = await router.route(TaskType.AI_TASK)
        >>> print(decision.adapter_name)  # "agno" or "worker"
    """

    # Task type → required capabilities mapping
    TASK_CAPABILITY_REQUIREMENTS: dict[TaskType, list[str]] = {
        TaskType.RAG_QUERY: ["rag", "vector_search"],
        TaskType.AI_TASK: ["multi_agent", "tool_use"],
        TaskType.WORKFLOW: ["deploy_flows", "monitor_execution"],
    }

    def __init__(
        self,
        registry: Any | None = None,
        cache_ttl_seconds: int = 300,
    ):
        """Initialize CapabilityRouter.

        Args:
            registry: HybridAdapterRegistry for adapter discovery
            cache_ttl_seconds: TTL for resolution cache
        """
        self.registry = registry
        self._cache: ResolutionCache | None = None

        if CAPABILITY_ROUTING_AVAILABLE and ResolutionCache is not None:
            self._cache = ResolutionCache(ttl_seconds=cache_ttl_seconds)

        logger.info(
            f"CapabilityRouter initialized: "
            f"registry={'provided' if registry else 'none'}, "
            f"cache_enabled={self._cache is not None}"
        )

    async def route(
        self,
        task_type: TaskType,
        additional_capabilities: list[str] | None = None,
        domain: str = "orchestration",
    ) -> Any:
        """Find best adapter based on task requirements.

        Args:
            task_type: Type of task to route
            additional_capabilities: Extra capabilities beyond task defaults
            domain: Domain for adapter resolution

        Returns:
            RoutingDecision with selected adapter, or dict with error
        """
        # Check cache first
        cache_key = f"{domain}:{task_type.value}:{additional_capabilities or []}"
        if self._cache:
            cached = self._cache.get(cache_key)
            if cached:
                logger.debug(f"Cache hit for {cache_key}")
                return cached

        # Get required capabilities for task type
        required_caps = list(self.TASK_CAPABILITY_REQUIREMENTS.get(task_type, []))
        if additional_capabilities:
            required_caps.extend(additional_capabilities)

        # If no registry available, return fallback
        if not self.registry:
            return {
                "success": False,
                "error": "No adapter registry configured",
                "task_type": task_type.value,
                "required_capabilities": required_caps,
            }

        # Find adapters matching capabilities
        import time

        start_time = time.time()

        try:
            matching_adapters = await self.registry.find_by_capabilities(required_caps)

            if not matching_adapters:
                return {
                    "success": False,
                    "error": f"No adapter found with capabilities: {required_caps}",
                    "task_type": task_type.value,
                    "required_capabilities": required_caps,
                }

            # Select best adapter (highest priority)
            best_adapter = max(matching_adapters, key=lambda m: m.priority)
            resolution_time_ms = (time.time() - start_time) * 1000

            # Create routing decision
            if CAPABILITY_ROUTING_AVAILABLE and RoutingDecision is not None:
                decision = RoutingDecision(
                    adapter_name=best_adapter.adapter_id,
                    adapter=None,  # Lazy-loaded by registry
                    matched_capabilities=[
                        cap for cap in required_caps if cap in best_adapter.capabilities
                    ],
                    resolution_time_ms=resolution_time_ms,
                    fallback_used=False,
                    explanation=f"Selected {best_adapter.adapter_id} based on capabilities: {required_caps}",
                )

                # Cache the decision
                if self._cache:
                    self._cache.set(cache_key, decision)

                return decision
            else:
                return {
                    "success": True,
                    "adapter": best_adapter.adapter_id,
                    "task_type": task_type.value,
                    "matched_capabilities": [
                        cap for cap in required_caps if cap in best_adapter.capabilities
                    ],
                    "resolution_time_ms": resolution_time_ms,
                }

        except Exception as e:
            logger.error(f"Capability routing failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "task_type": task_type.value,
                "required_capabilities": required_caps,
            }

    def invalidate_cache(self) -> None:
        """Clear the resolution cache."""
        if self._cache:
            self._cache.invalidate()
            logger.info("CapabilityRouter cache invalidated")

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        if self._cache:
            return self._cache.get_stats()
        return {"enabled": False}

    def set_registry(self, registry: Any) -> None:
        """Set or update the adapter registry.

        Args:
            registry: HybridAdapterRegistry instance
        """
        self.registry = registry
        self.invalidate_cache()
        logger.info("CapabilityRouter registry updated")


class TaskRouter:
    """Intelligent task routing with graceful fallback."""

    TASK_PREFERENCE_ORDERS = {
        TaskType.WORKFLOW: [
            AdapterType.PREFECT,
            AdapterType.AGNO,
            AdapterType.LLAMAINDEX,
        ],
        TaskType.AI_TASK: [
            AdapterType.AGNO,
            AdapterType.LLAMAINDEX,
            AdapterType.PREFECT,
        ],
        TaskType.RAG_QUERY: [
            AdapterType.LLAMAINDEX,
            AdapterType.AGNO,
            AdapterType.PREFECT,
        ],
    }

    DEFAULT_PREFERENCE_ORDER = [
        AdapterType.PREFECT,
        AdapterType.AGNO,
        AdapterType.LLAMAINDEX,
    ]

    def __init__(
        self,
        adapter_registry: AdapterManager | None = None,
        state_manager: StateManager | None = None,
        router_mode: RouterMode = RouterMode.STATISTICAL,
        metrics: RoutingMetrics | None = None,
    ) -> None:
        self.adapter_registry = adapter_registry or AdapterManager()
        self.adapter_manager = self.adapter_registry
        self.state_manager = state_manager or StateManager()
        self.router_mode = router_mode
        self.metrics = metrics if metrics is not None else get_routing_metrics()
        self._statistical_router: StatisticalRouter | None = None
        self._cost_optimizer: CostOptimizer | None = None

        logger.info(
            f"TaskRouter initialized: mode={router_mode.value}, "
            f"metrics_enabled={self.metrics is not None}"
        )

    @staticmethod
    def _normalize_task_type(task_type: Any) -> TaskType:
        if isinstance(task_type, TaskType):
            return task_type
        task_type_str = str(task_type or TaskType.WORKFLOW.value)
        for candidate in TaskType:
            if candidate.value == task_type_str:
                return candidate
        return TaskType.WORKFLOW

    @staticmethod
    def _coerce_adapter_type(adapter: AdapterType | str | None) -> AdapterType | None:
        if adapter is None:
            return None
        if isinstance(adapter, AdapterType):
            return adapter
        try:
            return AdapterType(adapter)
        except Exception:
            for adapter_type in AdapterType:
                if adapter_type.value == adapter:
                    return adapter_type
        return None

    def _normalize_preference_order(
        self,
        preference_order: list[AdapterType | str] | None,
    ) -> list[AdapterType]:
        if not preference_order:
            return []
        normalized: list[AdapterType] = []
        for adapter in preference_order:
            adapter_type = self._coerce_adapter_type(adapter)
            if adapter_type is not None and adapter_type not in normalized:
                normalized.append(adapter_type)
        return normalized

    def _default_preference_order(self, task_type: TaskType) -> list[AdapterType]:
        preference_order = self.TASK_PREFERENCE_ORDERS.get(task_type)
        if preference_order is None:
            return list(self.DEFAULT_PREFERENCE_ORDER)
        return list(preference_order)

    async def analyze_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Analyze task requirements and determine optimal routing strategy."""
        task_type = self._normalize_task_type(task.get("task_type"))

        needs_deployment = task.get("needs_deployment", False)
        needs_monitoring = task.get("needs_monitoring", False)
        needs_ai_agents = task_type == TaskType.AI_TASK
        needs_rag = task_type == TaskType.RAG_QUERY

        if task_type == TaskType.WORKFLOW:
            recommended_adapter = AdapterType.PREFECT
        elif task_type == TaskType.AI_TASK:
            recommended_adapter = AdapterType.AGNO
        elif task_type == TaskType.RAG_QUERY:
            recommended_adapter = AdapterType.LLAMAINDEX
        else:
            recommended_adapter = AdapterType.PREFECT

        adapter_health = await self._get_adapter_health(recommended_adapter)

        return {
            "task_type": task_type.value,
            "recommended_adapter": recommended_adapter,
            "adapter_health": adapter_health,
            "routing_mode": self.router_mode.value,
            "analysis": (
                f"Task requires {'deployment' if needs_deployment else 'standard'} processing"
                f"{' with monitoring' if needs_monitoring else ''}"
                f"{' and AI agents' if needs_ai_agents else ''}"
                f"{' and RAG' if needs_rag else ''}"
            ),
        }

    async def route(
        self,
        task: dict[str, Any],
        preference_order: list[AdapterType | str] | None = None,
    ) -> dict[str, Any]:
        """Route task to optimal adapter with metrics tracking."""
        task_type = self._normalize_task_type(task.get("task_type"))
        candidates = self._normalize_preference_order(preference_order or task.get("preference_order"))
        if not candidates:
            analysis = await self.analyze_task(task)
            candidates = [analysis["recommended_adapter"]]
            for adapter_type in self._default_preference_order(task_type):
                if adapter_type not in candidates:
                    candidates.append(adapter_type)

        selected_adapter: AdapterType | None = None
        for adapter_type in candidates:
            adapter = self.adapter_registry.get_adapter(adapter_type)
            if adapter is not None and await adapter.is_available():
                selected_adapter = adapter_type
                break

        if selected_adapter is None:
            return {
                "success": False,
                "error": f"No adapter available for task type {task_type.value}",
                "task_type": task_type.value,
            }

        self.metrics.record_routing_decision(
            adapter=selected_adapter,
            task_type=task_type,
            preference_order=1,
        )

        logger.info(
            f"Routed {task_type.value} to {selected_adapter.value} (mode: {self.router_mode.value})"
        )

        return {
            "success": True,
            "adapter": selected_adapter,
            "task_type": task_type.value,
            "routing_mode": self.router_mode.value,
            "preference_order": [adapter.value for adapter in candidates],
        }

    async def execute_with_fallback(
        self,
        task: dict[str, Any],
        preference_order: list[AdapterType | str] | None = None,
        max_retries: int = 3,
        retry_delay_base: float = 1.0,
    ) -> dict[str, Any]:
        """Execute task with graceful fallback across adapters."""
        task_type = self._normalize_task_type(task.get("task_type"))
        prompt = task.get("prompt", "")
        repos = task.get("repos", [])
        execution_context = {
            "task_type": task_type.value,
            "prompt": prompt,
            "repos": repos,
        }

        candidates = self._normalize_preference_order(preference_order or task.get("preference_order"))
        if not candidates:
            candidates = self._default_preference_order(task_type)

        fallback_chain: list[AdapterType] = []
        total_attempts = 0
        last_error: Exception | None = None

        for adapter_type in candidates:
            adapter = self.adapter_registry.get_adapter(adapter_type)
            if adapter is None:
                continue

            fallback_chain.append(adapter_type)
            retry_policy = RetryPolicy(
                max_attempts=max_retries,
                initial_delay_seconds=retry_delay_base,
                backoff_factor=2.0,
                max_delay_seconds=60.0,
            )

            async def _execute_adapter(adapter: Any = adapter) -> dict[str, Any]:
                return await adapter.execute(task=execution_context, repos=repos)

            try:
                result, attempts = await retry_async(
                    _execute_adapter,
                    policy=retry_policy,
                    operation=f"task_router.{adapter_type.value}",
                    dependency=adapter_type.value,
                )
                total_attempts += attempts

                if isinstance(result, dict) and result.get("success") is False:
                    raise RuntimeError(result.get("error") or "Adapter returned unsuccessful result")

                normalized_result = (
                    result.get("execution_id")
                    if isinstance(result, dict) and "execution_id" in result
                    else result
                )
                latency_ms = result.get("latency_ms", 0) if isinstance(result, dict) else 0
                self.adapter_registry.record_execution(adapter_type, success=True)
                self.metrics.record_adapter_execution(
                    adapter=adapter_type,
                    success=True,
                    latency_ms=latency_ms,
                )
                logger.info(
                    f"Task succeeded on {adapter_type.value} "
                    f"(attempts={attempts}, total_attempts={total_attempts})"
                )
                return {
                    "success": True,
                    "adapter": adapter_type,
                    "result": normalized_result,
                    "fallback_chain": fallback_chain,
                    "total_attempts": total_attempts,
                }

            except RetryExhaustedError as exc:
                total_attempts += exc.attempts
                last_error = exc.last_exception if exc.last_exception is not None else exc
            except Exception as exc:
                last_error = exc

            self.adapter_registry.record_execution(adapter_type, success=False)
            self.metrics.record_adapter_execution(
                adapter=adapter_type,
                success=False,
                latency_ms=0,
            )
            logger.warning(
                f"Adapter {adapter_type.value} failed after retries for task {task_type.value}: {last_error}"
            )

        return {
            "success": False,
            "error": str(last_error) if last_error is not None else "All adapters failed",
            "adapter": None,
            "result": None,
            "task_type": task_type.value,
            "fallback_chain": fallback_chain,
            "total_attempts": total_attempts,
        }

    async def get_adapter_statistics(self) -> dict[str, dict[str, Any]]:
        """Get execution statistics for all adapters."""
        return self.adapter_registry.get_statistics()

    async def get_health(self) -> dict[str, Any]:
        """Get health status of routing system."""
        adapter_health = await self._get_all_adapter_health()
        return {
            "status": "healthy",
            "routing_mode": self.router_mode.value,
            "metrics_enabled": self.metrics is not None,
            "adapters_configured": len(self.adapter_registry.adapters),
            "adapters_healthy": sum(
                1 for h in adapter_health.values() if h.get("status") == "healthy"
            ),
        }

    async def _get_adapter_health(self, adapter_type: AdapterType | str) -> dict[str, Any]:
        adapter_enum = self._coerce_adapter_type(adapter_type)
        if adapter_enum is None:
            return {
                "status": "not_configured",
                "error": f"Adapter {adapter_type} not registered",
            }

        adapter = self.adapter_registry.get_adapter(adapter_enum)
        if not adapter:
            return {
                "status": "not_configured",
                "error": f"Adapter {adapter_enum.value} not registered",
            }

        try:
            if hasattr(adapter, "get_health"):
                health = await adapter.get_health()
                return {"adapter_type": adapter_enum.value, **health}
            return {
                "adapter_type": adapter_enum.value,
                "status": "available_but_no_health_check",
            }
        except Exception as e:
            return {
                "adapter_type": adapter_enum.value,
                "status": "error",
                "error": str(e),
            }

    async def _get_all_adapter_health(self) -> dict[str, dict[str, Any]]:
        health = {}
        for adapter_type in self.adapter_registry.adapters:
            health[adapter_type.value] = await self._get_adapter_health(adapter_type)
        return health


def get_task_router() -> Any:
    """Compatibility alias for the legacy routing singleton.

    The older code path expected ``mahavishnu.core.task_router.get_task_router``.
    Preserve that surface by delegating to the routing module singleton.
    """
    return _legacy_get_task_router()


def reset_task_router() -> None:
    """Compatibility alias for the legacy routing singleton reset."""
    _legacy_reset_task_router()
