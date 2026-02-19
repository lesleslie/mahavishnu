"""Task Ordering Module for Mahavishnu.

Provides intelligent task prioritization and ordering based on:
- Dependencies between tasks
- Blocker predictions
- Deadlines and time constraints
- Priority levels
- Resource availability
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class OrderingStrategy(str, Enum):
    """Strategy for task ordering."""

    DEADLINE_FIRST = "deadline_first"  # Earliest deadline first
    PRIORITY_FIRST = "priority_first"  # Highest priority first
    DEPENDENCY_AWARE = "dependency_aware"  # Topological sort respecting dependencies
    BLOCKER_AWARE = "blocker_aware"  # Avoid tasks with high blocker probability
    BALANCED = "balanced"  # Balance all factors


class Priority(str, Enum):
    """Task priority levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class OrderingFactor:
    """A factor in task ordering decision."""

    name: str
    weight: float
    value: float  # Normalized 0-1

    @property
    def score(self) -> float:
        """Calculate weighted score."""
        return self.weight * self.value


class TaskOrderingConfig(BaseModel):
    """Configuration for task ordering."""

    # Factor weights (should sum to ~1.0)
    deadline_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    priority_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    dependency_weight: float = Field(default=0.20, ge=0.0, le=1.0)
    blocker_weight: float = Field(default=0.15, ge=0.0, le=1.0)
    duration_weight: float = Field(default=0.15, ge=0.0, le=1.0)

    # Default deadline horizon (days)
    default_deadline_days: int = Field(default=14, ge=1)

    # Urgency thresholds
    urgent_deadline_days: int = Field(default=3, ge=1)
    approaching_deadline_days: int = Field(default=7, ge=1)

    # Priority score mapping
    priority_scores: dict[str, float] = Field(
        default={
            "critical": 1.0,
            "urgent": 0.95,
            "high": 0.75,
            "medium": 0.5,
            "low": 0.25,
        }
    )


class TaskOrderRecommendation(BaseModel):
    """Recommendation for task ordering."""

    task_id: str
    recommended_position: int
    score: float = Field(ge=0.0, le=1.0)
    factors: list[dict[str, Any]] = Field(default_factory=list)
    reasoning: str = ""
    blocked_by: list[str] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
    should_start_now: bool = False
    urgency: str = "normal"  # critical, urgent, normal, low

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "task_id": self.task_id,
            "recommended_position": self.recommended_position,
            "score": self.score,
            "factors": self.factors,
            "reasoning": self.reasoning,
            "blocked_by": self.blocked_by,
            "blocking": self.blocking,
            "should_start_now": self.should_start_now,
            "urgency": self.urgency,
        }


class TaskOrderingResult(BaseModel):
    """Result of task ordering analysis."""

    strategy: OrderingStrategy
    recommendations: list[TaskOrderRecommendation]
    total_tasks: int
    blocked_tasks: int
    ready_tasks: int
    critical_path: list[str] = Field(default_factory=list)
    estimated_completion_time: float = 0.0  # hours
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "strategy": self.strategy.value,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "total_tasks": self.total_tasks,
            "blocked_tasks": self.blocked_tasks,
            "ready_tasks": self.ready_tasks,
            "critical_path": self.critical_path,
            "estimated_completion_time": self.estimated_completion_time,
            "generated_at": self.generated_at.isoformat(),
        }

    def get_ordered_task_ids(self) -> list[str]:
        """Get ordered list of task IDs."""
        return [r.task_id for r in self.recommendations]


class TaskOrderer:
    """Orders tasks optimally based on multiple factors."""

    def __init__(self, config: TaskOrderingConfig | None = None):
        """Initialize task orderer.

        Args:
            config: Optional ordering configuration
        """
        self.config = config or TaskOrderingConfig()

    def order_tasks(
        self,
        tasks: list[dict[str, Any]],
        strategy: OrderingStrategy = OrderingStrategy.BALANCED,
        predictions: dict[str, dict[str, Any]] | None = None,
        dependencies: dict[str, list[str]] | None = None,
    ) -> TaskOrderingResult:
        """Order tasks based on strategy.

        Args:
            tasks: List of tasks to order
            strategy: Ordering strategy to use
            predictions: Optional blocker predictions by task ID
            dependencies: Optional task dependencies (task_id -> blocked_by_ids)

        Returns:
            TaskOrderingResult with ordered recommendations
        """
        if not tasks:
            return TaskOrderingResult(
                strategy=strategy,
                recommendations=[],
                total_tasks=0,
                blocked_tasks=0,
                ready_tasks=0,
            )

        predictions = predictions or {}
        dependencies = dependencies or {}

        # Build dependency graph
        dep_graph = self._build_dependency_graph(tasks, dependencies)

        # Calculate scores for each task
        scored_tasks = []
        for task in tasks:
            task_id = task.get("id", "unknown")
            score_data = self._calculate_task_score(
                task, strategy, predictions.get(task_id, {}), dep_graph
            )
            scored_tasks.append((task, score_data))

        # Sort based on strategy
        sorted_tasks = self._sort_by_strategy(scored_tasks, strategy, dep_graph)

        # Build recommendations
        recommendations = []
        blocked_count = 0
        ready_count = 0

        for position, (task, score_data) in enumerate(sorted_tasks):
            task_id = task.get("id", "unknown")

            # Check if blocked
            blocked_by = dep_graph.get("blocked_by", {}).get(task_id, [])
            is_blocked = len(blocked_by) > 0

            if is_blocked:
                blocked_count += 1
            else:
                ready_count += 1

            # Determine urgency
            urgency = self._calculate_urgency(task, score_data)

            # Determine if should start now
            should_start = (
                not is_blocked
                and position < 3  # Top 3 tasks
                and urgency in ("critical", "urgent")
            )

            recommendation = TaskOrderRecommendation(
                task_id=task_id,
                recommended_position=position,
                score=score_data["total_score"],
                factors=score_data["factors"],
                reasoning=score_data["reasoning"],
                blocked_by=blocked_by,
                blocking=dep_graph.get("blocking", {}).get(task_id, []),
                should_start_now=should_start,
                urgency=urgency,
            )
            recommendations.append(recommendation)

        # Calculate critical path
        critical_path = self._calculate_critical_path(tasks, dep_graph, predictions)

        # Estimate completion time
        completion_time = self._estimate_completion_time(tasks, predictions)

        return TaskOrderingResult(
            strategy=strategy,
            recommendations=recommendations,
            total_tasks=len(tasks),
            blocked_tasks=blocked_count,
            ready_tasks=ready_count,
            critical_path=critical_path,
            estimated_completion_time=completion_time,
        )

    def _build_dependency_graph(
        self, tasks: list[dict[str, Any]], dependencies: dict[str, list[str]]
    ) -> dict[str, Any]:
        """Build dependency graph from tasks and explicit dependencies."""
        graph: dict[str, Any] = {
            "blocked_by": {},  # task_id -> list of blocking task_ids
            "blocking": {},  # task_id -> list of tasks it blocks
        }

        # Add explicit dependencies
        for task_id, blocked_by_ids in dependencies.items():
            graph["blocked_by"][task_id] = list(blocked_by_ids)
            for blocker_id in blocked_by_ids:
                if blocker_id not in graph["blocking"]:
                    graph["blocking"][blocker_id] = []
                graph["blocking"][blocker_id].append(task_id)

        # Detect dependencies from task data
        for task in tasks:
            task_id = task.get("id", "unknown")

            # Check for dependency fields
            if "depends_on" in task:
                deps = task["depends_on"]
                if isinstance(deps, list):
                    if task_id not in graph["blocked_by"]:
                        graph["blocked_by"][task_id] = []
                    for dep_id in deps:
                        if dep_id not in graph["blocked_by"][task_id]:
                            graph["blocked_by"][task_id].append(dep_id)
                        if dep_id not in graph["blocking"]:
                            graph["blocking"][dep_id] = []
                        if task_id not in graph["blocking"][dep_id]:
                            graph["blocking"][dep_id].append(task_id)

        return graph

    def _calculate_task_score(
        self,
        task: dict[str, Any],
        strategy: OrderingStrategy,
        prediction: dict[str, Any],
        dep_graph: dict[str, Any],
    ) -> dict[str, Any]:
        """Calculate ordering score for a task."""
        factors: list[dict[str, Any]] = []
        factor_objs: list[OrderingFactor] = []

        task_id = task.get("id", "unknown")

        # Deadline factor
        deadline_score = self._score_deadline(task)
        if deadline_score is not None:
            factor = OrderingFactor(
                name="deadline",
                weight=self.config.deadline_weight,
                value=deadline_score,
            )
            factor_objs.append(factor)
            factors.append({
                "name": "deadline",
                "weight": factor.weight,
                "value": factor.value,
                "score": factor.score,
                "reason": self._get_deadline_reason(task),
            })

        # Priority factor
        priority_score = self._score_priority(task)
        factor = OrderingFactor(
            name="priority",
            weight=self.config.priority_weight,
            value=priority_score,
        )
        factor_objs.append(factor)
        factors.append({
            "name": "priority",
            "weight": factor.weight,
            "value": factor.value,
            "score": factor.score,
            "reason": f"Priority: {task.get('priority', 'medium')}",
        })

        # Dependency factor (lower is better = fewer blockers)
        dep_score = self._score_dependencies(task_id, dep_graph)
        factor = OrderingFactor(
            name="dependencies",
            weight=self.config.dependency_weight,
            value=dep_score,
        )
        factor_objs.append(factor)
        factors.append({
            "name": "dependencies",
            "weight": factor.weight,
            "value": factor.value,
            "score": factor.score,
            "reason": f"Blocked by {len(dep_graph.get('blocked_by', {}).get(task_id, []))} tasks",
        })

        # Blocker probability factor (lower is better)
        blocker_score = self._score_blocker_prediction(prediction)
        factor = OrderingFactor(
            name="blocker_risk",
            weight=self.config.blocker_weight,
            value=blocker_score,
        )
        factor_objs.append(factor)
        factors.append({
            "name": "blocker_risk",
            "weight": factor.weight,
            "value": factor.value,
            "score": factor.score,
            "reason": f"Blocker probability: {prediction.get('blocker_probability', 0):.0%}",
        })

        # Duration factor (shorter tasks first for quick wins)
        duration_score = self._score_duration(task, prediction)
        factor = OrderingFactor(
            name="duration",
            weight=self.config.duration_weight,
            value=duration_score,
        )
        factor_objs.append(factor)
        factors.append({
            "name": "duration",
            "weight": factor.weight,
            "value": factor.value,
            "score": factor.score,
            "reason": f"Estimated: {prediction.get('estimated_hours', task.get('estimated_hours', 8)):.1f}h",
        })

        # Calculate total score based on strategy
        total_score = self._apply_strategy_weights(factor_objs, strategy)

        # Generate reasoning
        reasoning = self._generate_reasoning(factors, strategy)

        return {
            "total_score": total_score,
            "factors": factors,
            "reasoning": reasoning,
        }

    def _score_deadline(self, task: dict[str, Any]) -> float | None:
        """Score based on deadline urgency (higher = more urgent)."""
        deadline = task.get("deadline") or task.get("due_date")
        if not deadline:
            return None

        try:
            if isinstance(deadline, str):
                deadline_dt = datetime.fromisoformat(deadline)
            else:
                deadline_dt = deadline

            now = datetime.utcnow()
            time_until = deadline_dt - now

            if time_until.total_seconds() < 0:
                # Overdue
                return 1.0
            elif time_until.days <= self.config.urgent_deadline_days:
                # Urgent
                return 0.9
            elif time_until.days <= self.config.approaching_deadline_days:
                # Approaching
                return 0.7
            else:
                # Normal
                days = time_until.days
                # Normalize to 0-0.5 range
                return max(0.1, 0.5 - (days - 7) * 0.02)

        except (ValueError, TypeError):
            return None

    def _get_deadline_reason(self, task: dict[str, Any]) -> str:
        """Get human-readable deadline reason."""
        deadline = task.get("deadline") or task.get("due_date")
        if not deadline:
            return "No deadline"

        try:
            if isinstance(deadline, str):
                deadline_dt = datetime.fromisoformat(deadline)
            else:
                deadline_dt = deadline

            now = datetime.utcnow()
            time_until = deadline_dt - now

            if time_until.total_seconds() < 0:
                return f"Overdue by {abs(time_until.days)} days"
            elif time_until.days == 0:
                return "Due today"
            elif time_until.days == 1:
                return "Due tomorrow"
            else:
                return f"Due in {time_until.days} days"

        except (ValueError, TypeError):
            return "Invalid deadline"

    def _score_priority(self, task: dict[str, Any]) -> float:
        """Score based on priority level."""
        priority = str(task.get("priority", "medium")).lower()
        return self.config.priority_scores.get(priority, 0.5)

    def _score_dependencies(self, task_id: str, dep_graph: dict[str, Any]) -> float:
        """Score based on dependencies (fewer blockers = higher score)."""
        blocked_by = dep_graph.get("blocked_by", {}).get(task_id, [])
        num_blockers = len(blocked_by)

        if num_blockers == 0:
            return 1.0
        elif num_blockers == 1:
            return 0.7
        elif num_blockers == 2:
            return 0.4
        else:
            return max(0.1, 0.4 - (num_blockers - 2) * 0.1)

    def _score_blocker_prediction(self, prediction: dict[str, Any]) -> float:
        """Score based on blocker prediction (lower probability = higher score)."""
        blocker_prob = prediction.get("blocker_probability", 0.0)
        # Invert: lower probability = higher score
        return 1.0 - blocker_prob

    def _score_duration(
        self, task: dict[str, Any], prediction: dict[str, Any]
    ) -> float:
        """Score based on duration (shorter = higher score for quick wins)."""
        hours = prediction.get("estimated_hours") or task.get("estimated_hours", 8.0)

        # Normalize: 0-2h = 1.0, 2-4h = 0.8, 4-8h = 0.6, 8-16h = 0.4, >16h = 0.2
        if hours <= 2:
            return 1.0
        elif hours <= 4:
            return 0.8
        elif hours <= 8:
            return 0.6
        elif hours <= 16:
            return 0.4
        else:
            return 0.2

    def _apply_strategy_weights(
        self, factors: list[OrderingFactor], strategy: OrderingStrategy
    ) -> float:
        """Apply strategy-specific weight adjustments."""
        strategy_multipliers: dict[OrderingStrategy, dict[str, float]] = {
            OrderingStrategy.DEADLINE_FIRST: {
                "deadline": 2.0,
                "priority": 0.5,
                "dependencies": 0.5,
                "blocker_risk": 0.5,
                "duration": 0.3,
            },
            OrderingStrategy.PRIORITY_FIRST: {
                "deadline": 0.5,
                "priority": 2.0,
                "dependencies": 0.5,
                "blocker_risk": 0.5,
                "duration": 0.3,
            },
            OrderingStrategy.DEPENDENCY_AWARE: {
                "deadline": 0.5,
                "priority": 0.5,
                "dependencies": 2.0,
                "blocker_risk": 0.5,
                "duration": 0.3,
            },
            OrderingStrategy.BLOCKER_AWARE: {
                "deadline": 0.5,
                "priority": 0.5,
                "dependencies": 0.5,
                "blocker_risk": 2.0,
                "duration": 0.3,
            },
            OrderingStrategy.BALANCED: {
                "deadline": 1.0,
                "priority": 1.0,
                "dependencies": 1.0,
                "blocker_risk": 1.0,
                "duration": 1.0,
            },
        }

        multipliers = strategy_multipliers.get(strategy, {})

        total_score = 0.0
        total_weight = 0.0

        for factor in factors:
            mult = multipliers.get(factor.name, 1.0)
            total_score += factor.score * mult
            total_weight += factor.weight * mult

        return total_score / total_weight if total_weight > 0 else 0.5

    def _sort_by_strategy(
        self,
        scored_tasks: list[tuple[dict[str, Any], dict[str, Any]]],
        strategy: OrderingStrategy,
        dep_graph: dict[str, Any],
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """Sort tasks based on strategy."""

        if strategy == OrderingStrategy.DEPENDENCY_AWARE:
            # Topological sort with score as tiebreaker
            return self._topological_sort(scored_tasks, dep_graph)
        else:
            # Sort by score (descending)
            return sorted(scored_tasks, key=lambda x: x[1]["total_score"], reverse=True)

    def _topological_sort(
        self,
        scored_tasks: list[tuple[dict[str, Any], dict[str, Any]]],
        dep_graph: dict[str, Any],
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """Perform topological sort respecting dependencies."""
        # Build task map
        task_map = {t[0].get("id", "unknown"): t for t in scored_tasks}

        # Calculate in-degrees
        in_degree: dict[str, int] = defaultdict(int)
        blocked_by = dep_graph.get("blocked_by", {})

        for task_id in task_map:
            in_degree[task_id] = len(blocked_by.get(task_id, []))

        # Start with tasks that have no dependencies
        queue = [
            task_id for task_id, degree in in_degree.items() if degree == 0
        ]
        # Sort queue by score
        queue.sort(key=lambda tid: task_map[tid][1]["total_score"], reverse=True)

        result = []

        while queue:
            # Take highest-scored task with no remaining dependencies
            task_id = queue.pop(0)
            result.append(task_map[task_id])

            # Reduce in-degree for dependent tasks
            blocking = dep_graph.get("blocking", {}).get(task_id, [])
            for dependent_id in blocking:
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    # Insert in sorted position
                    queue.append(dependent_id)
                    queue.sort(
                        key=lambda tid: task_map[tid][1]["total_score"],
                        reverse=True,
                    )

        # Add any remaining tasks (circular dependencies)
        for task_id in task_map:
            if task_map[task_id] not in result:
                result.append(task_map[task_id])

        return result

    def _generate_reasoning(
        self, factors: list[dict[str, Any]], strategy: OrderingStrategy
    ) -> str:
        """Generate human-readable reasoning for task ordering."""
        reasons = []

        # Sort factors by score contribution
        sorted_factors = sorted(
            factors, key=lambda f: f["score"], reverse=True
        )

        for factor in sorted_factors[:3]:  # Top 3 factors
            if factor["score"] > 0.1:  # Only significant factors
                reasons.append(factor["reason"])

        if not reasons:
            reasons.append("Balanced consideration of all factors")

        strategy_names = {
            OrderingStrategy.DEADLINE_FIRST: "deadline-focused",
            OrderingStrategy.PRIORITY_FIRST: "priority-focused",
            OrderingStrategy.DEPENDENCY_AWARE: "dependency-respecting",
            OrderingStrategy.BLOCKER_AWARE: "risk-averse",
            OrderingStrategy.BALANCED: "balanced",
        }

        return f"[{strategy_names[strategy]}] " + "; ".join(reasons)

    def _calculate_urgency(
        self, task: dict[str, Any], score_data: dict[str, Any]
    ) -> str:
        """Calculate task urgency level."""
        score = score_data["total_score"]
        priority = str(task.get("priority", "medium")).lower()

        # Check deadline
        deadline = task.get("deadline") or task.get("due_date")
        if deadline:
            try:
                if isinstance(deadline, str):
                    deadline_dt = datetime.fromisoformat(deadline)
                else:
                    deadline_dt = deadline

                if deadline_dt < datetime.utcnow():
                    return "critical"
                elif (deadline_dt - datetime.utcnow()).days <= 3:
                    return "urgent"
            except (ValueError, TypeError):
                pass

        # Check priority
        if priority in ("critical", "urgent"):
            return "urgent"
        elif priority == "high":
            return "urgent" if score > 0.7 else "normal"

        # Check score
        if score > 0.8:
            return "urgent"
        elif score > 0.6:
            return "normal"
        else:
            return "low"

    def _calculate_critical_path(
        self,
        tasks: list[dict[str, Any]],
        dep_graph: dict[str, Any],
        predictions: dict[str, dict[str, Any]],
    ) -> list[str]:
        """Calculate the critical path through the task graph."""
        if not tasks:
            return []

        # Find tasks with no dependents (end nodes)
        blocking = dep_graph.get("blocking", {})
        all_blocked = set()
        for blocked_list in blocking.values():
            all_blocked.update(blocked_list)

        end_tasks = [
            t.get("id", "unknown")
            for t in tasks
            if t.get("id", "unknown") not in all_blocked
        ]

        if not end_tasks:
            # All tasks are interconnected, pick highest duration
            end_tasks = [tasks[0].get("id", "unknown")]

        # Find longest path to any end task (simplified)
        # For a proper implementation, would use dynamic programming
        critical_path = []

        blocked_by = dep_graph.get("blocked_by", {})

        def get_duration(task_id: str) -> float:
            task = next((t for t in tasks if t.get("id") == task_id), None)
            if task:
                pred = predictions.get(task_id, {})
                return pred.get("estimated_hours") or task.get("estimated_hours", 8.0)
            return 8.0

        def find_path_to(task_id: str, visited: set[str]) -> list[str]:
            if task_id in visited:
                return []
            visited.add(task_id)

            blockers = blocked_by.get(task_id, [])
            if not blockers:
                return [task_id]

            # Find longest blocking path
            best_path: list[str] = []
            best_duration = 0.0

            for blocker_id in blockers:
                path = find_path_to(blocker_id, visited.copy())
                duration = sum(get_duration(t) for t in path)
                if duration > best_duration:
                    best_duration = duration
                    best_path = path

            return best_path + [task_id]

        # Find path to the end task with longest total duration
        best_path: list[str] = []
        best_duration = 0.0

        for end_task in end_tasks:
            path = find_path_to(end_task, set())
            duration = sum(get_duration(t) for t in path)
            if duration > best_duration:
                best_duration = duration
                best_path = path

        return best_path

    def _estimate_completion_time(
        self,
        tasks: list[dict[str, Any]],
        predictions: dict[str, dict[str, Any]],
    ) -> float:
        """Estimate total completion time for all tasks."""
        total = 0.0

        for task in tasks:
            task_id = task.get("id", "unknown")
            pred = predictions.get(task_id, {})
            hours = pred.get("estimated_hours") or task.get("estimated_hours", 8.0)
            total += hours

        # Adjust for parallel work (assume 2 parallel workers)
        # This is a simplification; proper calculation would use critical path
        parallel_factor = 0.6  # Assume 40% parallelization benefit

        return total * parallel_factor


def order_tasks(
    tasks: list[dict[str, Any]],
    strategy: OrderingStrategy = OrderingStrategy.BALANCED,
    predictions: dict[str, dict[str, Any]] | None = None,
    dependencies: dict[str, list[str]] | None = None,
) -> TaskOrderingResult:
    """Convenience function to order tasks.

    Args:
        tasks: List of tasks to order
        strategy: Ordering strategy to use
        predictions: Optional blocker predictions by task ID
        dependencies: Optional task dependencies

    Returns:
        TaskOrderingResult with ordered recommendations
    """
    orderer = TaskOrderer()
    return orderer.order_tasks(tasks, strategy, predictions, dependencies)
