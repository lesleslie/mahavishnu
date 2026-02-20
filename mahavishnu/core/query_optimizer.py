"""Query Optimizer - Query analysis and optimization tools.

Provides tools for analyzing and optimizing database queries:

- Query plan parsing from EXPLAIN ANALYZE
- Index recommendations
- N+1 query detection
- Query performance metrics

Usage:
    from mahavishnu.core.query_optimizer import QueryAnalyzer, NPlusOneDetector

    analyzer = QueryAnalyzer()

    # Analyze query
    result = analyzer.analyze("SELECT * FROM tasks WHERE status = 'pending'")

    # Detect N+1
    detector = NPlusOneDetector()
    for task in tasks:
        detector.record_query(f"SELECT * FROM subtasks WHERE task_id = {task.id}")
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class QueryType(str, Enum):
    """SQL query types."""

    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    OTHER = "OTHER"


@dataclass
class QueryPlan:
    """Parsed query execution plan.

    Attributes:
        node_type: Type of scan node
        relation_name: Table being scanned
        index_name: Index being used (if any)
        total_cost: Estimated total cost
        startup_cost: Estimated startup cost
        estimated_rows: Estimated rows returned
        planning_time: Time spent planning (ms)
        execution_time: Time spent executing (ms)
        filter: Filter condition
    """

    node_type: str
    relation_name: str | None = None
    index_name: str | None = None
    total_cost: float = 0.0
    startup_cost: float = 0.0
    estimated_rows: int = 0
    planning_time: float = 0.0
    execution_time: float = 0.0
    filter: str | None = None

    @property
    def is_sequential_scan(self) -> bool:
        """Check if this is a sequential (full table) scan."""
        return self.node_type.lower() in ("seq scan", "sequential scan")

    @property
    def is_index_scan(self) -> bool:
        """Check if this is an index scan."""
        return "index" in self.node_type.lower()

    @classmethod
    def from_explain(cls, explain_result: dict[str, Any]) -> QueryPlan:
        """Create from EXPLAIN ANALYZE result.

        Args:
            explain_result: Output from EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)

        Returns:
            Parsed QueryPlan
        """
        plan = explain_result.get("Plan", {})

        return cls(
            node_type=plan.get("Node Type", ""),
            relation_name=plan.get("Relation Name"),
            index_name=plan.get("Index Name"),
            total_cost=float(plan.get("Total Cost", 0)),
            startup_cost=float(plan.get("Startup Cost", 0)),
            estimated_rows=int(plan.get("Plan Rows", 0)),
            planning_time=float(explain_result.get("Planning Time", 0)),
            execution_time=float(explain_result.get("Execution Time", 0)),
            filter=plan.get("Filter"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "node_type": self.node_type,
            "relation_name": self.relation_name,
            "index_name": self.index_name,
            "total_cost": self.total_cost,
            "startup_cost": self.startup_cost,
            "estimated_rows": self.estimated_rows,
            "planning_time": self.planning_time,
            "execution_time": self.execution_time,
            "filter": self.filter,
        }


@dataclass
class IndexRecommendation:
    """Recommendation for a new index.

    Attributes:
        table: Table to index
        columns: Columns to include in index
        reason: Why this index is recommended
        estimated_improvement: Estimated performance improvement (%)
    """

    table: str
    columns: list[str]
    reason: str = ""
    estimated_improvement: float = 0.0

    @property
    def priority(self) -> str:
        """Get recommendation priority."""
        if self.estimated_improvement >= 70:
            return "high"
        elif self.estimated_improvement >= 30:
            return "medium"
        return "low"

    def to_sql(self) -> str:
        """Generate CREATE INDEX SQL.

        Returns:
            SQL statement to create index
        """
        index_name = f"{self.table}_{'_'.join(self.columns)}_idx"
        columns_str = ", ".join(self.columns)
        return f"CREATE INDEX {index_name} ON {self.table} ({columns_str});"


@dataclass
class QueryMetrics:
    """Metrics for a query.

    Attributes:
        query: SQL query text
        query_type: Type of query
        execution_time_ms: Execution time in milliseconds
        rows_returned: Number of rows returned
        execution_count: Number of times executed
    """

    query: str
    query_type: QueryType
    execution_time_ms: float = 0.0
    rows_returned: int = 0
    execution_count: int = 1
    _total_time_ms: float = 0.0

    def __post_init__(self) -> None:
        """Initialize total time."""
        self._total_time_ms = self.execution_time_ms

    def record_execution(self, execution_time_ms: float) -> None:
        """Record another execution.

        Args:
            execution_time_ms: Execution time in milliseconds
        """
        self.execution_count += 1
        self._total_time_ms += execution_time_ms
        self.execution_time_ms = execution_time_ms

    @property
    def avg_execution_time(self) -> float:
        """Get average execution time."""
        if self.execution_count == 0:
            return 0.0
        return self._total_time_ms / self.execution_count

    def is_slow(self, threshold_ms: float = 1000.0) -> bool:
        """Check if query is slow.

        Args:
            threshold_ms: Threshold in milliseconds

        Returns:
            True if slow
        """
        return self.execution_time_ms > threshold_ms

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query": self.query,
            "query_type": self.query_type.value,
            "execution_time_ms": self.execution_time_ms,
            "avg_execution_time_ms": self.avg_execution_time,
            "rows_returned": self.rows_returned,
            "execution_count": self.execution_count,
        }


@dataclass
class QueryAnalysis:
    """Result of query analysis.

    Attributes:
        query: Original query
        query_type: Type of query
        tables: Tables referenced
        where_columns: Columns in WHERE clause
        join_tables: Tables joined
    """

    query: str
    query_type: QueryType
    tables: list[str] = field(default_factory=list)
    where_columns: list[str] = field(default_factory=list)
    join_tables: list[str] = field(default_factory=list)


class NPlusOneDetector:
    """Detects N+1 query patterns.

    Tracks repeated similar queries within a time window
    to detect potential N+1 query problems.

    Example:
        detector = NPlusOneDetector(time_window_seconds=60)

        # These will be detected as N+1
        for task in tasks:
            detector.record_query(
                query=f"SELECT * FROM subtasks WHERE task_id = {task.id}",
                table="subtasks",
            )
    """

    def __init__(self, time_window_seconds: int = 60, threshold: int = 5) -> None:
        """Initialize detector.

        Args:
            time_window_seconds: Time window for detection
            threshold: Minimum queries to consider N+1
        """
        self.time_window = timedelta(seconds=time_window_seconds)
        self.threshold = threshold
        self._queries: dict[str, list[datetime]] = defaultdict(list)
        self.detected: list[dict[str, Any]] = []

    def record_query(
        self,
        query: str,
        table: str,
        timestamp: datetime | None = None,
    ) -> None:
        """Record a query execution.

        Args:
            query: SQL query
            table: Table being queried
            timestamp: Query timestamp
        """
        timestamp = timestamp or datetime.now(UTC)

        # Create fingerprint for query pattern
        fingerprint = self._fingerprint(query, table)
        self._queries[fingerprint].append(timestamp)

        # Check for N+1 pattern
        self._check_pattern(fingerprint, table)

    def _fingerprint(self, query: str, table: str) -> str:
        """Create fingerprint for query pattern."""
        # Normalize query by replacing values with placeholders
        normalized = re.sub(r"'[^']*'", "?", query)
        normalized = re.sub(r"\b\d+\b", "?", normalized)
        return f"{table}:{normalized}"

    def _check_pattern(self, fingerprint: str, table: str) -> None:
        """Check if pattern indicates N+1."""
        timestamps = self._queries[fingerprint]
        cutoff = datetime.now(UTC) - self.time_window

        # Filter to recent queries
        recent = [ts for ts in timestamps if ts > cutoff]

        if len(recent) >= self.threshold:
            # Check if we already detected this pattern
            for detected in self.detected:
                if detected["fingerprint"] == fingerprint:
                    detected["count"] = len(recent)
                    return

            self.detected.append({
                "fingerprint": fingerprint,
                "table": table,
                "count": len(recent),
                "detected_at": datetime.now(UTC),
            })

    def get_detected_patterns(self) -> list[dict[str, Any]]:
        """Get detected N+1 patterns.

        Returns:
            List of detected patterns
        """
        cutoff = datetime.now(UTC) - self.time_window
        return [
            p for p in self.detected
            if p["detected_at"] > cutoff
        ]

    def get_recommendation(self) -> str | None:
        """Get recommendation for detected patterns.

        Returns:
            Recommendation string or None
        """
        patterns = self.get_detected_patterns()
        if not patterns:
            return None

        # Return recommendation for most severe pattern
        pattern = max(patterns, key=lambda p: p["count"])
        table = pattern["table"]

        return (
            f"N+1 query detected on table '{table}'. "
            f"Consider using a JOIN or batch query with IN clause instead of "
            f"{pattern['count']} individual queries."
        )


class QueryAnalyzer:
    """Analyzes SQL queries for optimization.

    Features:
    - Query parsing and classification
    - Full table scan detection
    - Index recommendations
    - Performance metrics tracking

    Example:
        analyzer = QueryAnalyzer()

        # Analyze query
        result = analyzer.analyze("SELECT * FROM tasks WHERE status = ?")

        # Get recommendations
        recommendations = analyzer.recommend_indexes(query, plan)
    """

    def __init__(self) -> None:
        """Initialize analyzer."""
        self._metrics: dict[str, QueryMetrics] = {}
        self._fingerprint_cache: dict[str, str] = {}

    def analyze(self, query: str) -> QueryAnalysis:
        """Analyze a SQL query.

        Args:
            query: SQL query to analyze

        Returns:
            QueryAnalysis result
        """
        # Determine query type
        query_upper = query.strip().upper()
        if query_upper.startswith("SELECT"):
            query_type = QueryType.SELECT
        elif query_upper.startswith("INSERT"):
            query_type = QueryType.INSERT
        elif query_upper.startswith("UPDATE"):
            query_type = QueryType.UPDATE
        elif query_upper.startswith("DELETE"):
            query_type = QueryType.DELETE
        else:
            query_type = QueryType.OTHER

        # Extract tables
        tables = self._extract_tables(query)

        # Extract WHERE columns
        where_columns = self._extract_where_columns(query)

        # Extract JOIN tables
        join_tables = self._extract_join_tables(query)

        return QueryAnalysis(
            query=query,
            query_type=query_type,
            tables=tables,
            where_columns=where_columns,
            join_tables=join_tables,
        )

    def _extract_tables(self, query: str) -> list[str]:
        """Extract table names from query."""
        tables = []

        # FROM clause
        from_match = re.search(
            r"\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            query,
            re.IGNORECASE
        )
        if from_match:
            tables.append(from_match.group(1))

        # JOIN clauses
        join_matches = re.findall(
            r"\bJOIN\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            query,
            re.IGNORECASE
        )
        tables.extend(join_matches)

        # INSERT INTO
        insert_match = re.search(
            r"\bINTO\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            query,
            re.IGNORECASE
        )
        if insert_match:
            tables.append(insert_match.group(1))

        # UPDATE
        update_match = re.search(
            r"\bUPDATE\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            query,
            re.IGNORECASE
        )
        if update_match:
            tables.append(update_match.group(1))

        # DELETE FROM
        delete_match = re.search(
            r"\bDELETE\s+FROM\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            query,
            re.IGNORECASE
        )
        if delete_match:
            tables.append(delete_match.group(1))

        return list(set(tables))

    def _extract_where_columns(self, query: str) -> list[str]:
        """Extract columns from WHERE clause."""
        columns = []

        # Find WHERE clause
        where_match = re.search(
            r"\bWHERE\s+(.+?)(?:ORDER|GROUP|LIMIT|$)",
            query,
            re.IGNORECASE | re.DOTALL
        )

        if where_match:
            where_clause = where_match.group(1)

            # Find column references
            col_matches = re.findall(
                r"([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:=|>|<|>=|<=|<>|!=|LIKE|IN|IS)",
                where_clause,
                re.IGNORECASE
            )
            columns.extend(col_matches)

        return list(set(columns))

    def _extract_join_tables(self, query: str) -> list[str]:
        """Extract tables from JOIN clauses."""
        tables = []

        join_matches = re.findall(
            r"\bJOIN\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            query,
            re.IGNORECASE
        )
        tables.extend(join_matches)

        return list(set(tables))

    def is_full_table_scan(self, plan: dict[str, Any]) -> bool:
        """Check if plan indicates full table scan.

        Args:
            plan: EXPLAIN result

        Returns:
            True if full table scan
        """
        query_plan = QueryPlan.from_explain(plan)
        return query_plan.is_sequential_scan

    def recommend_indexes(
        self,
        query: str,
        plan: dict[str, Any],
    ) -> list[IndexRecommendation]:
        """Recommend indexes for query.

        Args:
            query: SQL query
            plan: EXPLAIN result

        Returns:
            List of index recommendations
        """
        recommendations = []
        query_plan = QueryPlan.from_explain(plan)

        # Only recommend for sequential scans
        if not query_plan.is_sequential_scan:
            return recommendations

        # Get WHERE columns
        analysis = self.analyze(query)

        if analysis.where_columns and query_plan.relation_name:
            # Estimate improvement based on cost
            estimated_improvement = min(90, 50 + query_plan.total_cost / 10)

            recommendations.append(IndexRecommendation(
                table=query_plan.relation_name,
                columns=analysis.where_columns,
                reason="Query uses sequential scan with filter on these columns",
                estimated_improvement=estimated_improvement,
            ))

        return recommendations

    def record_query(
        self,
        query: str,
        execution_time_ms: float,
        rows_returned: int = 0,
    ) -> None:
        """Record query execution.

        Args:
            query: SQL query
            execution_time_ms: Execution time in milliseconds
            rows_returned: Number of rows returned
        """
        fingerprint = self.get_fingerprint(query)

        if fingerprint in self._metrics:
            self._metrics[fingerprint].record_execution(execution_time_ms)
        else:
            analysis = self.analyze(query)
            self._metrics[fingerprint] = QueryMetrics(
                query=query,
                query_type=analysis.query_type,
                execution_time_ms=execution_time_ms,
                rows_returned=rows_returned,
            )

    def get_fingerprint(self, query: str) -> str:
        """Get fingerprint for query.

        Args:
            query: SQL query

        Returns:
            Fingerprint string
        """
        if query in self._fingerprint_cache:
            return self._fingerprint_cache[query]

        # Normalize query
        normalized = query.strip().upper()
        normalized = re.sub(r"'[^']*'", "?", normalized)
        normalized = re.sub(r"\b\d+\b", "?", normalized)
        normalized = re.sub(r"\s+", " ", normalized)

        fingerprint = hashlib.md5(normalized.encode()).hexdigest()[:16]
        self._fingerprint_cache[query] = fingerprint
        return fingerprint

    def get_query_stats(self, query: str) -> dict[str, Any] | None:
        """Get statistics for a query.

        Args:
            query: SQL query

        Returns:
            Statistics dictionary or None
        """
        fingerprint = self.get_fingerprint(query)
        metrics = self._metrics.get(fingerprint)

        if metrics is None:
            return None

        return metrics.to_dict()

    def get_slow_queries(
        self,
        threshold_ms: float = 1000.0,
    ) -> list[QueryMetrics]:
        """Get list of slow queries.

        Args:
            threshold_ms: Threshold in milliseconds

        Returns:
            List of slow query metrics
        """
        return [
            metrics for metrics in self._metrics.values()
            if metrics.is_slow(threshold_ms)
        ]


__all__ = [
    "QueryAnalyzer",
    "QueryPlan",
    "IndexRecommendation",
    "QueryMetrics",
    "NPlusOneDetector",
    "QueryType",
]
