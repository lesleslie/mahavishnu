"""Tests for Query Optimizer - Query analysis and optimization tools."""

import pytest
from datetime import datetime, UTC
from unittest.mock import MagicMock, AsyncMock
from typing import Any

from mahavishnu.core.query_optimizer import (
    QueryAnalyzer,
    QueryPlan,
    IndexRecommendation,
    QueryMetrics,
    NPlusOneDetector,
    QueryType,
)


@pytest.fixture
def sample_query_plan() -> dict[str, Any]:
    """Create a sample query execution plan."""
    return {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "tasks",
            "Alias": "tasks",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 1000,
            "Plan Width": 100,
            "Filter": "(status = 'pending')",
        },
        "Planning Time": 0.5,
        "Execution Time": 10.0,
    }


@pytest.fixture
def sample_index_scan_plan() -> dict[str, Any]:
    """Create an index scan plan."""
    return {
        "Plan": {
            "Node Type": "Index Scan",
            "Index Name": "idx_tasks_status",
            "Relation Name": "tasks",
            "Startup Cost": 0.0,
            "Total Cost": 10.0,
            "Plan Rows": 100,
            "Plan Width": 100,
        },
        "Planning Time": 0.2,
        "Execution Time": 1.0,
    }


class TestQueryType:
    """Tests for QueryType enum."""

    def test_query_types(self) -> None:
        """Test available query types."""
        assert QueryType.SELECT.value == "SELECT"
        assert QueryType.INSERT.value == "INSERT"
        assert QueryType.UPDATE.value == "UPDATE"
        assert QueryType.DELETE.value == "DELETE"


class TestQueryPlan:
    """Tests for QueryPlan class."""

    def test_create_plan(
        self,
        sample_query_plan: dict[str, Any],
    ) -> None:
        """Create a query plan."""
        plan = QueryPlan.from_explain(sample_query_plan)

        assert plan.node_type == "Seq Scan"
        assert plan.relation_name == "tasks"
        assert plan.total_cost == 100.0

    def test_plan_is_sequential_scan(
        self,
        sample_query_plan: dict[str, Any],
    ) -> None:
        """Check if plan uses sequential scan."""
        plan = QueryPlan.from_explain(sample_query_plan)

        assert plan.is_sequential_scan is True

    def test_plan_is_index_scan(
        self,
        sample_index_scan_plan: dict[str, Any],
    ) -> None:
        """Check if plan uses index scan."""
        plan = QueryPlan.from_explain(sample_index_scan_plan)

        assert plan.is_sequential_scan is False
        assert plan.index_name == "idx_tasks_status"

    def test_plan_execution_time(
        self,
        sample_query_plan: dict[str, Any],
    ) -> None:
        """Get execution time from plan."""
        plan = QueryPlan.from_explain(sample_query_plan)

        assert plan.execution_time == 10.0
        assert plan.planning_time == 0.5

    def test_plan_estimated_rows(
        self,
        sample_query_plan: dict[str, Any],
    ) -> None:
        """Get estimated rows from plan."""
        plan = QueryPlan.from_explain(sample_query_plan)

        assert plan.estimated_rows == 1000

    def test_plan_to_dict(
        self,
        sample_query_plan: dict[str, Any],
    ) -> None:
        """Convert plan to dictionary."""
        plan = QueryPlan.from_explain(sample_query_plan)

        d = plan.to_dict()

        assert d["node_type"] == "Seq Scan"
        assert d["total_cost"] == 100.0


class TestIndexRecommendation:
    """Tests for IndexRecommendation class."""

    def test_create_recommendation(self) -> None:
        """Create an index recommendation."""
        rec = IndexRecommendation(
            table="tasks",
            columns=["status", "priority"],
            reason="Frequently filtered columns",
            estimated_improvement=80.0,
        )

        assert rec.table == "tasks"
        assert rec.columns == ["status", "priority"]
        assert rec.reason == "Frequently filtered columns"
        assert rec.estimated_improvement == 80.0

    def test_recommendation_sql(self) -> None:
        """Generate CREATE INDEX SQL."""
        rec = IndexRecommendation(
            table="tasks",
            columns=["status", "priority"],
        )

        sql = rec.to_sql()

        assert "CREATE INDEX" in sql
        assert "tasks_status_priority_idx" in sql
        assert "ON tasks (status, priority)" in sql

    def test_single_column_index_sql(self) -> None:
        """Generate single column index SQL."""
        rec = IndexRecommendation(
            table="tasks",
            columns=["repository"],
        )

        sql = rec.to_sql()

        assert "tasks_repository_idx" in sql
        assert "ON tasks (repository)" in sql

    def test_recommendation_priority(self) -> None:
        """Test recommendation priority."""
        high_priority = IndexRecommendation(
            table="tasks",
            columns=["status"],
            estimated_improvement=90.0,
        )
        low_priority = IndexRecommendation(
            table="tasks",
            columns=["created_at"],
            estimated_improvement=10.0,
        )

        assert high_priority.priority == "high"
        assert low_priority.priority == "low"


class TestQueryMetrics:
    """Tests for QueryMetrics class."""

    def test_create_metrics(self) -> None:
        """Create query metrics."""
        metrics = QueryMetrics(
            query="SELECT * FROM tasks WHERE status = ?",
            query_type=QueryType.SELECT,
            execution_time_ms=50.0,
            rows_returned=100,
        )

        assert metrics.query_type == QueryType.SELECT
        assert metrics.execution_time_ms == 50.0
        assert metrics.rows_returned == 100

    def test_metrics_is_slow(self) -> None:
        """Check if query is slow."""
        fast_metrics = QueryMetrics(
            query="SELECT * FROM tasks",
            query_type=QueryType.SELECT,
            execution_time_ms=50.0,
        )

        slow_metrics = QueryMetrics(
            query="SELECT * FROM tasks",
            query_type=QueryType.SELECT,
            execution_time_ms=1500.0,
        )

        assert fast_metrics.is_slow(threshold_ms=1000) is False
        assert slow_metrics.is_slow(threshold_ms=1000) is True

    def test_metrics_to_dict(self) -> None:
        """Convert metrics to dictionary."""
        metrics = QueryMetrics(
            query="SELECT * FROM tasks",
            query_type=QueryType.SELECT,
            execution_time_ms=50.0,
            rows_returned=100,
        )

        d = metrics.to_dict()

        assert d["query_type"] == "SELECT"
        assert d["execution_time_ms"] == 50.0

    def test_record_execution(self) -> None:
        """Record multiple executions."""
        metrics = QueryMetrics(
            query="SELECT * FROM tasks",
            query_type=QueryType.SELECT,
            execution_time_ms=50.0,
        )

        metrics.record_execution(100.0)
        metrics.record_execution(150.0)

        assert metrics.execution_count == 3
        assert metrics.avg_execution_time == 100.0  # (50 + 100 + 150) / 3


class TestNPlusOneDetector:
    """Tests for NPlusOneDetector class."""

    def test_create_detector(self) -> None:
        """Create N+1 detector."""
        detector = NPlusOneDetector()

        assert detector is not None
        assert len(detector.detected) == 0

    def test_detect_n_plus_one(self) -> None:
        """Detect N+1 query pattern."""
        detector = NPlusOneDetector(time_window_seconds=60)

        # Record repeated similar queries
        for i in range(10):
            detector.record_query(
                query=f"SELECT * FROM subtasks WHERE task_id = '{i}'",
                table="subtasks",
                timestamp=datetime.now(UTC),
            )

        patterns = detector.get_detected_patterns()

        assert len(patterns) > 0
        assert patterns[0]["table"] == "subtasks"
        assert patterns[0]["count"] == 10

    def test_no_false_positives(self) -> None:
        """Avoid false positives."""
        detector = NPlusOneDetector(time_window_seconds=60)

        # Record diverse queries
        detector.record_query("SELECT * FROM tasks WHERE id = 1", "tasks")
        detector.record_query("SELECT * FROM users WHERE id = 1", "users")
        detector.record_query("SELECT * FROM repos WHERE id = 1", "repos")

        patterns = detector.get_detected_patterns()

        assert len(patterns) == 0

    def test_time_window(self) -> None:
        """Queries outside time window not detected."""
        from datetime import timedelta

        detector = NPlusOneDetector(time_window_seconds=1)

        # Record queries with old timestamps
        old_time = datetime.now(UTC) - timedelta(minutes=5)
        for i in range(10):
            detector.record_query(
                query=f"SELECT * FROM tasks WHERE id = {i}",
                table="tasks",
                timestamp=old_time,
            )

        patterns = detector.get_detected_patterns()

        # Should not detect (outside time window)
        assert len(patterns) == 0

    def test_get_recommendation(self) -> None:
        """Get recommendation for detected pattern."""
        detector = NPlusOneDetector()

        for i in range(10):
            detector.record_query(
                query=f"SELECT * FROM subtasks WHERE task_id = {i}",
                table="subtasks",
                timestamp=datetime.now(UTC),
            )

        rec = detector.get_recommendation()

        assert rec is not None
        assert "JOIN" in rec or "IN" in rec or "batch" in rec.lower()


class TestQueryAnalyzer:
    """Tests for QueryAnalyzer class."""

    def test_create_analyzer(self) -> None:
        """Create a query analyzer."""
        analyzer = QueryAnalyzer()

        assert analyzer is not None

    def test_analyze_select_query(self) -> None:
        """Analyze a SELECT query."""
        analyzer = QueryAnalyzer()

        result = analyzer.analyze("SELECT * FROM tasks WHERE status = 'pending'")

        assert result.query_type == QueryType.SELECT
        assert result.tables == ["tasks"]
        assert "status" in result.where_columns

    def test_analyze_insert_query(self) -> None:
        """Analyze an INSERT query."""
        analyzer = QueryAnalyzer()

        result = analyzer.analyze(
            "INSERT INTO tasks (id, title) VALUES ('task-1', 'Test')"
        )

        assert result.query_type == QueryType.INSERT
        assert result.tables == ["tasks"]

    def test_analyze_update_query(self) -> None:
        """Analyze an UPDATE query."""
        analyzer = QueryAnalyzer()

        result = analyzer.analyze(
            "UPDATE tasks SET status = 'done' WHERE id = 'task-1'"
        )

        assert result.query_type == QueryType.UPDATE
        assert result.tables == ["tasks"]
        assert result.where_columns == ["id"]

    def test_analyze_delete_query(self) -> None:
        """Analyze a DELETE query."""
        analyzer = QueryAnalyzer()

        result = analyzer.analyze("DELETE FROM tasks WHERE id = 'task-1'")

        assert result.query_type == QueryType.DELETE
        assert result.tables == ["tasks"]

    def test_analyze_join_query(self) -> None:
        """Analyze a JOIN query."""
        analyzer = QueryAnalyzer()

        result = analyzer.analyze(
            "SELECT t.*, u.name FROM tasks t JOIN users u ON t.assignee = u.id"
        )

        assert "tasks" in result.tables
        assert "users" in result.tables

    def test_detect_full_table_scan(
        self,
        sample_query_plan: dict[str, Any],
    ) -> None:
        """Detect full table scan."""
        analyzer = QueryAnalyzer()

        is_full_scan = analyzer.is_full_table_scan(sample_query_plan)

        assert is_full_scan is True

    def test_detect_no_full_scan(
        self,
        sample_index_scan_plan: dict[str, Any],
    ) -> None:
        """Detect when no full table scan."""
        analyzer = QueryAnalyzer()

        is_full_scan = analyzer.is_full_table_scan(sample_index_scan_plan)

        assert is_full_scan is False

    def test_recommend_index(
        self,
        sample_query_plan: dict[str, Any],
    ) -> None:
        """Recommend index for query."""
        analyzer = QueryAnalyzer()

        recommendations = analyzer.recommend_indexes(
            query="SELECT * FROM tasks WHERE status = 'pending'",
            plan=sample_query_plan,
        )

        assert len(recommendations) > 0
        assert recommendations[0].table == "tasks"
        assert "status" in recommendations[0].columns

    def test_analyze_query_performance(self) -> None:
        """Analyze query performance."""
        analyzer = QueryAnalyzer()

        analyzer.record_query(
            query="SELECT * FROM tasks WHERE status = ?",
            execution_time_ms=50.0,
            rows_returned=100,
        )
        analyzer.record_query(
            query="SELECT * FROM tasks WHERE status = ?",
            execution_time_ms=60.0,
            rows_returned=120,
        )

        stats = analyzer.get_query_stats(
            "SELECT * FROM tasks WHERE status = ?"
        )

        assert stats is not None
        assert stats["execution_count"] == 2
        assert stats["avg_execution_time_ms"] == 55.0

    def test_get_slow_queries(self) -> None:
        """Get list of slow queries."""
        analyzer = QueryAnalyzer()

        analyzer.record_query("SELECT * FROM tasks", execution_time_ms=2000.0)
        analyzer.record_query("SELECT * FROM users", execution_time_ms=50.0)
        analyzer.record_query("SELECT * FROM repos", execution_time_ms=1500.0)

        slow = analyzer.get_slow_queries(threshold_ms=1000.0)

        assert len(slow) == 2

    def test_get_query_fingerprint(self) -> None:
        """Get query fingerprint for grouping."""
        analyzer = QueryAnalyzer()

        fp1 = analyzer.get_fingerprint("SELECT * FROM tasks WHERE id = 1")
        fp2 = analyzer.get_fingerprint("SELECT * FROM tasks WHERE id = 2")
        fp3 = analyzer.get_fingerprint("SELECT * FROM tasks WHERE status = 'done'")

        # Same structure should have same fingerprint
        assert fp1 == fp2
        # Different structure should have different fingerprint
        assert fp1 != fp3
