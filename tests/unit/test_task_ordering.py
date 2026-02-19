"""Tests for Task Ordering Module.

Tests cover:
- Task prioritization algorithms
- Ordering strategies
- Dependency handling
- Deadline scoring
- Critical path calculation
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from mahavishnu.core.task_ordering import (
    OrderingFactor,
    OrderingStrategy,
    Priority,
    TaskOrderer,
    TaskOrderingConfig,
    TaskOrderingResult,
    TaskOrderRecommendation,
    order_tasks,
)


class TestOrderingConfig:
    """Test ordering configuration."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = TaskOrderingConfig()

        assert config.deadline_weight == 0.25
        assert config.priority_weight == 0.25
        assert config.dependency_weight == 0.20
        assert config.blocker_weight == 0.15
        assert config.duration_weight == 0.15
        assert config.default_deadline_days == 14
        assert config.urgent_deadline_days == 3
        assert config.approaching_deadline_days == 7

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = TaskOrderingConfig(
            deadline_weight=0.4,
            priority_weight=0.3,
            dependency_weight=0.15,
            blocker_weight=0.1,
            duration_weight=0.05,
        )

        assert config.deadline_weight == 0.4
        assert config.priority_weight == 0.3
        assert config.dependency_weight == 0.15


class TestOrderingFactor:
    """Test ordering factor."""

    def test_factor_score(self) -> None:
        """Test factor score calculation."""
        factor = OrderingFactor(name="priority", weight=0.5, value=0.8)

        assert factor.name == "priority"
        assert factor.weight == 0.5
        assert factor.value == 0.8
        assert factor.score == 0.4  # 0.5 * 0.8


class TestTaskOrderRecommendation:
    """Test task order recommendation."""

    def test_create_recommendation(self) -> None:
        """Test creating a recommendation."""
        rec = TaskOrderRecommendation(
            task_id="task-123",
            recommended_position=1,
            score=0.85,
            factors=[{"name": "priority", "score": 0.7}],
            reasoning="High priority task",
            blocked_by=["task-100"],
            blocking=["task-200"],
            should_start_now=True,
            urgency="urgent",
        )

        assert rec.task_id == "task-123"
        assert rec.recommended_position == 1
        assert rec.score == 0.85
        assert len(rec.factors) == 1
        assert len(rec.blocked_by) == 1
        assert len(rec.blocking) == 1

    def test_recommendation_to_dict(self) -> None:
        """Test recommendation serialization."""
        rec = TaskOrderRecommendation(
            task_id="task-123",
            recommended_position=0,
            score=0.9,
            urgency="critical",
        )

        d = rec.to_dict()

        assert d["task_id"] == "task-123"
        assert d["recommended_position"] == 0
        assert d["urgency"] == "critical"


class TestTaskOrderingResult:
    """Test task ordering result."""

    def test_create_result(self) -> None:
        """Test creating an ordering result."""
        rec1 = TaskOrderRecommendation(task_id="task-1", recommended_position=0, score=0.9)
        rec2 = TaskOrderRecommendation(task_id="task-2", recommended_position=1, score=0.8)

        result = TaskOrderingResult(
            strategy=OrderingStrategy.BALANCED,
            recommendations=[rec1, rec2],
            total_tasks=2,
            blocked_tasks=0,
            ready_tasks=2,
            critical_path=["task-1", "task-2"],
            estimated_completion_time=16.0,
        )

        assert result.strategy == OrderingStrategy.BALANCED
        assert len(result.recommendations) == 2
        assert result.total_tasks == 2
        assert result.critical_path == ["task-1", "task-2"]

    def test_get_ordered_task_ids(self) -> None:
        """Test getting ordered task IDs."""
        rec1 = TaskOrderRecommendation(task_id="task-1", recommended_position=0, score=0.9)
        rec2 = TaskOrderRecommendation(task_id="task-2", recommended_position=1, score=0.8)

        result = TaskOrderingResult(
            strategy=OrderingStrategy.BALANCED,
            recommendations=[rec1, rec2],
            total_tasks=2,
            blocked_tasks=0,
            ready_tasks=2,
        )

        ids = result.get_ordered_task_ids()

        assert ids == ["task-1", "task-2"]


class TestTaskOrderer:
    """Test task orderer."""

    @pytest.fixture
    def orderer(self) -> TaskOrderer:
        """Create task orderer."""
        return TaskOrderer()

    @pytest.fixture
    def sample_tasks(self) -> list[dict]:
        """Create sample tasks."""
        now = datetime.utcnow()
        return [
            {
                "id": "task-1",
                "title": "Critical bug fix",
                "priority": "critical",
                "deadline": (now + timedelta(days=1)).isoformat(),
                "estimated_hours": 2.0,
            },
            {
                "id": "task-2",
                "title": "Feature implementation",
                "priority": "high",
                "deadline": (now + timedelta(days=7)).isoformat(),
                "estimated_hours": 8.0,
            },
            {
                "id": "task-3",
                "title": "Documentation update",
                "priority": "low",
                "estimated_hours": 4.0,
            },
            {
                "id": "task-4",
                "title": "Code review",
                "priority": "medium",
                "deadline": (now + timedelta(days=3)).isoformat(),
                "estimated_hours": 1.0,
            },
        ]

    def test_order_tasks_empty(self, orderer: TaskOrderer) -> None:
        """Test ordering with no tasks."""
        result = orderer.order_tasks([])

        assert result.total_tasks == 0
        assert len(result.recommendations) == 0

    def test_order_tasks_basic(
        self, orderer: TaskOrderer, sample_tasks: list[dict]
    ) -> None:
        """Test basic task ordering."""
        result = orderer.order_tasks(sample_tasks)

        assert result.total_tasks == 4
        assert len(result.recommendations) == 4
        assert result.ready_tasks == 4
        assert result.blocked_tasks == 0

    def test_order_tasks_with_predictions(
        self, orderer: TaskOrderer, sample_tasks: list[dict]
    ) -> None:
        """Test ordering with blocker predictions."""
        predictions = {
            "task-1": {"blocker_probability": 0.2, "estimated_hours": 2.0},
            "task-2": {"blocker_probability": 0.6, "estimated_hours": 8.0},
            "task-3": {"blocker_probability": 0.1, "estimated_hours": 4.0},
            "task-4": {"blocker_probability": 0.3, "estimated_hours": 1.0},
        }

        result = orderer.order_tasks(sample_tasks, predictions=predictions)

        assert result.total_tasks == 4
        # Task with high blocker probability should score lower
        task_2_rec = next(r for r in result.recommendations if r.task_id == "task-2")
        task_3_rec = next(r for r in result.recommendations if r.task_id == "task-3")

        # Task-3 has lower blocker probability, should score higher
        assert task_3_rec.score > task_2_rec.score

    def test_order_tasks_with_dependencies(
        self, orderer: TaskOrderer, sample_tasks: list[dict]
    ) -> None:
        """Test ordering with dependencies."""
        dependencies = {
            "task-2": ["task-1"],  # task-2 depends on task-1
            "task-3": ["task-2"],  # task-3 depends on task-2
        }

        result = orderer.order_tasks(
            sample_tasks,
            strategy=OrderingStrategy.DEPENDENCY_AWARE,
            dependencies=dependencies,
        )

        assert result.total_tasks == 4
        assert result.blocked_tasks == 2  # task-2 and task-3 are blocked

        # Check that dependencies are tracked
        task_2_rec = next(r for r in result.recommendations if r.task_id == "task-2")
        assert "task-1" in task_2_rec.blocked_by

    def test_order_by_deadline_first(
        self, orderer: TaskOrderer, sample_tasks: list[dict]
    ) -> None:
        """Test deadline-first ordering strategy."""
        result = orderer.order_tasks(
            sample_tasks,
            strategy=OrderingStrategy.DEADLINE_FIRST,
        )

        # Task-1 has the earliest deadline (1 day)
        # Should be first or very high priority
        task_1_position = next(
            i for i, r in enumerate(result.recommendations) if r.task_id == "task-1"
        )
        assert task_1_position < 2  # Should be in top 2

    def test_order_by_priority_first(
        self, orderer: TaskOrderer, sample_tasks: list[dict]
    ) -> None:
        """Test priority-first ordering strategy."""
        result = orderer.order_tasks(
            sample_tasks,
            strategy=OrderingStrategy.PRIORITY_FIRST,
        )

        # Task-1 has critical priority
        assert result.recommendations[0].task_id == "task-1"

    def test_score_deadline(self, orderer: TaskOrderer) -> None:
        """Test deadline scoring."""
        now = datetime.utcnow()

        # Overdue task
        task = {"deadline": (now - timedelta(days=1)).isoformat()}
        score = orderer._score_deadline(task)
        assert score == 1.0

        # Urgent deadline (1 day)
        task = {"deadline": (now + timedelta(days=1)).isoformat()}
        score = orderer._score_deadline(task)
        assert score == 0.9

        # Approaching deadline (5 days)
        task = {"deadline": (now + timedelta(days=5)).isoformat()}
        score = orderer._score_deadline(task)
        assert 0.5 < score < 0.9

        # No deadline
        task = {}
        score = orderer._score_deadline(task)
        assert score is None

    def test_score_priority(self, orderer: TaskOrderer) -> None:
        """Test priority scoring."""
        assert orderer._score_priority({"priority": "critical"}) == 1.0
        assert orderer._score_priority({"priority": "high"}) == 0.75
        assert orderer._score_priority({"priority": "medium"}) == 0.5
        assert orderer._score_priority({"priority": "low"}) == 0.25
        assert orderer._score_priority({}) == 0.5  # Default medium

    def test_score_dependencies(self, orderer: TaskOrderer) -> None:
        """Test dependency scoring."""
        dep_graph = {
            "blocked_by": {
                "task-1": [],
                "task-2": ["task-1"],
                "task-3": ["task-1", "task-2"],
                "task-4": ["task-1", "task-2", "task-3"],
            }
        }

        # No blockers
        assert orderer._score_dependencies("task-1", dep_graph) == 1.0

        # One blocker
        assert orderer._score_dependencies("task-2", dep_graph) == 0.7

        # Two blockers
        assert orderer._score_dependencies("task-3", dep_graph) == 0.4

        # Three blockers
        assert orderer._score_dependencies("task-4", dep_graph) < 0.4

    def test_score_blocker_prediction(self, orderer: TaskOrderer) -> None:
        """Test blocker prediction scoring."""
        # Low blocker probability = high score
        score = orderer._score_blocker_prediction({"blocker_probability": 0.1})
        assert score == 0.9

        # High blocker probability = low score
        score = orderer._score_blocker_prediction({"blocker_probability": 0.8})
        assert score == 0.2

        # No prediction = medium score
        score = orderer._score_blocker_prediction({})
        assert score == 1.0

    def test_score_duration(self, orderer: TaskOrderer) -> None:
        """Test duration scoring (shorter is better)."""
        # Very short
        score = orderer._score_duration({"estimated_hours": 1.0}, {})
        assert score == 1.0

        # Short
        score = orderer._score_duration({"estimated_hours": 3.0}, {})
        assert score == 0.8

        # Medium
        score = orderer._score_duration({"estimated_hours": 6.0}, {})
        assert score == 0.6

        # Long
        score = orderer._score_duration({"estimated_hours": 12.0}, {})
        assert score == 0.4

        # Very long
        score = orderer._score_duration({"estimated_hours": 24.0}, {})
        assert score == 0.2

    def test_calculate_urgency(self, orderer: TaskOrderer) -> None:
        """Test urgency calculation."""
        now = datetime.utcnow()

        # Overdue = critical
        task = {"deadline": (now - timedelta(days=1)).isoformat()}
        score_data = {"total_score": 0.8}
        assert orderer._calculate_urgency(task, score_data) == "critical"

        # Urgent deadline
        task = {"deadline": (now + timedelta(days=2)).isoformat()}
        assert orderer._calculate_urgency(task, score_data) == "urgent"

        # Critical priority
        task = {"priority": "critical"}
        assert orderer._calculate_urgency(task, score_data) == "urgent"

        # High priority with high score
        task = {"priority": "high"}
        assert orderer._calculate_urgency(task, {"total_score": 0.8}) == "urgent"

        # Normal case
        task = {"priority": "medium"}
        assert orderer._calculate_urgency(task, {"total_score": 0.5}) == "normal"

    def test_calculate_critical_path(
        self, orderer: TaskOrderer, sample_tasks: list[dict]
    ) -> None:
        """Test critical path calculation."""
        dependencies = {
            "task-2": ["task-1"],
            "task-3": ["task-2"],
        }

        dep_graph = orderer._build_dependency_graph(sample_tasks, dependencies)

        critical_path = orderer._calculate_critical_path(sample_tasks, dep_graph, {})

        assert len(critical_path) > 0
        # Critical path should include task-1 (no blockers)
        assert "task-1" in critical_path

    def test_estimate_completion_time(
        self, orderer: TaskOrderer, sample_tasks: list[dict]
    ) -> None:
        """Test completion time estimation."""
        predictions = {
            "task-1": {"estimated_hours": 2.0},
            "task-2": {"estimated_hours": 8.0},
            "task-3": {"estimated_hours": 4.0},
            "task-4": {"estimated_hours": 1.0},
        }

        time_estimate = orderer._estimate_completion_time(sample_tasks, predictions)

        # Total hours = 15, adjusted for parallel work
        assert 0 < time_estimate < 20

    def test_build_dependency_graph(
        self, orderer: TaskOrderer, sample_tasks: list[dict]
    ) -> None:
        """Test dependency graph building."""
        dependencies = {
            "task-2": ["task-1"],
            "task-3": ["task-2"],
        }

        graph = orderer._build_dependency_graph(sample_tasks, dependencies)

        assert "task-1" in graph["blocking"]
        assert "task-2" in graph["blocking"]["task-1"]
        assert "task-2" in graph["blocked_by"]["task-3"]

    def test_build_dependency_graph_from_tasks(
        self, orderer: TaskOrderer
    ) -> None:
        """Test dependency graph building from task data."""
        tasks = [
            {"id": "task-1", "title": "First task"},
            {"id": "task-2", "title": "Second task", "depends_on": ["task-1"]},
            {"id": "task-3", "title": "Third task", "depends_on": ["task-2"]},
        ]

        graph = orderer._build_dependency_graph(tasks, {})

        assert "task-1" in graph["blocked_by"]["task-2"]
        assert "task-2" in graph["blocked_by"]["task-3"]

    def test_topological_sort(
        self, orderer: TaskOrderer
    ) -> None:
        """Test topological sort."""
        tasks = [
            {"id": "task-1", "title": "First", "priority": "low"},
            {"id": "task-2", "title": "Second", "priority": "medium"},
            {"id": "task-3", "title": "Third", "priority": "high"},
        ]

        dependencies = {
            "task-2": ["task-1"],
            "task-3": ["task-2"],
        }

        dep_graph = orderer._build_dependency_graph(tasks, dependencies)

        # Score tasks
        scored = []
        for task in tasks:
            score_data = orderer._calculate_task_score(
                task, OrderingStrategy.DEPENDENCY_AWARE, {}, dep_graph
            )
            scored.append((task, score_data))

        sorted_tasks = orderer._topological_sort(scored, dep_graph)

        # Task-1 should come before task-2, task-2 before task-3
        task_ids = [t[0]["id"] for t in sorted_tasks]
        assert task_ids.index("task-1") < task_ids.index("task-2")
        assert task_ids.index("task-2") < task_ids.index("task-3")


class TestConvenienceFunction:
    """Test convenience function."""

    def test_order_tasks_function(self) -> None:
        """Test order_tasks convenience function."""
        now = datetime.utcnow()
        tasks = [
            {
                "id": "task-1",
                "title": "Critical task",
                "priority": "critical",
                "deadline": (now + timedelta(days=1)).isoformat(),
            },
            {
                "id": "task-2",
                "title": "Normal task",
                "priority": "medium",
            },
        ]

        result = order_tasks(tasks)

        assert isinstance(result, TaskOrderingResult)
        assert result.total_tasks == 2
        # Critical task should be first
        assert result.recommendations[0].task_id == "task-1"


class TestStrategyComparison:
    """Test different ordering strategies."""

    @pytest.fixture
    def orderer(self) -> TaskOrderer:
        """Create task orderer."""
        return TaskOrderer()

    @pytest.fixture
    def complex_tasks(self) -> list[dict]:
        """Create complex task set."""
        now = datetime.utcnow()
        return [
            {
                "id": "urgent-long",
                "title": "Urgent long task",
                "priority": "critical",
                "deadline": (now + timedelta(days=1)).isoformat(),
                "estimated_hours": 16.0,
            },
            {
                "id": "normal-short",
                "title": "Normal short task",
                "priority": "medium",
                "deadline": (now + timedelta(days=14)).isoformat(),
                "estimated_hours": 2.0,
            },
            {
                "id": "high-medium",
                "title": "High priority medium task",
                "priority": "high",
                "deadline": (now + timedelta(days=5)).isoformat(),
                "estimated_hours": 8.0,
            },
            {
                "id": "low-quick",
                "title": "Low priority quick task",
                "priority": "low",
                "estimated_hours": 1.0,
            },
        ]

    def test_deadline_first_strategy(
        self, orderer: TaskOrderer, complex_tasks: list[dict]
    ) -> None:
        """Test deadline-first prioritizes earliest deadline."""
        result = orderer.order_tasks(
            complex_tasks,
            strategy=OrderingStrategy.DEADLINE_FIRST,
        )

        # Urgent task should be first due to deadline
        assert result.recommendations[0].task_id == "urgent-long"

    def test_priority_first_strategy(
        self, orderer: TaskOrderer, complex_tasks: list[dict]
    ) -> None:
        """Test priority-first prioritizes highest priority."""
        result = orderer.order_tasks(
            complex_tasks,
            strategy=OrderingStrategy.PRIORITY_FIRST,
        )

        # Critical task should be first
        assert result.recommendations[0].task_id == "urgent-long"

    def test_blocker_aware_strategy(
        self, orderer: TaskOrderer, complex_tasks: list[dict]
    ) -> None:
        """Test blocker-aware strategy."""
        predictions = {
            "urgent-long": {"blocker_probability": 0.8, "estimated_hours": 16.0},
            "normal-short": {"blocker_probability": 0.1, "estimated_hours": 2.0},
            "high-medium": {"blocker_probability": 0.3, "estimated_hours": 8.0},
            "low-quick": {"blocker_probability": 0.05, "estimated_hours": 1.0},
        }

        result = orderer.order_tasks(
            complex_tasks,
            strategy=OrderingStrategy.BLOCKER_AWARE,
            predictions=predictions,
        )

        # Low-risk tasks should be prioritized
        # Task with lowest blocker prob should score higher
        ids = [r.task_id for r in result.recommendations]
        # low-quick has 0.05 blocker probability
        assert "low-quick" in ids[:2]

    def test_balanced_strategy(
        self, orderer: TaskOrderer, complex_tasks: list[dict]
    ) -> None:
        """Test balanced strategy considers all factors."""
        result = orderer.order_tasks(
            complex_tasks,
            strategy=OrderingStrategy.BALANCED,
        )

        # Should have all tasks
        assert result.total_tasks == 4
        # Each task should have reasoning
        for rec in result.recommendations:
            assert len(rec.reasoning) > 0
            assert len(rec.factors) > 0
