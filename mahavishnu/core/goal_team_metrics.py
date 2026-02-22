"""Prometheus metrics for Goal-Driven Teams.

Metrics Categories:
- Team creation: teams_created_total, team_creation_duration_seconds
- Goal parsing: goals_parsed_total, goals_parsed_by_intent
- Team execution: team_executions_total, team_execution_duration_seconds
- Skill usage: skill_usage_total
- Errors: team_errors_total by error_code
- Learning: outcomes_recorded_total, recommendations_total, feedback_total

Design:
- Prometheus Counter for cumulative tracking
- Prometheus Gauge for current values
- Prometheus Histogram for distributions
- Lazy metric initialization to avoid duplicate registration
- Context manager for timing operations

Created: 2026-02-21
Version: 1.1
Related: Goal-Driven Teams Phase 1 + Phase 3 - Prometheus metrics integration with learning
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator

import logging
import time

# Lazy import - only import if actually used
try:
    from prometheus_client import REGISTRY, Counter, Gauge, Histogram, Info, start_http_server

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

    # Create dummy classes for graceful degradation
    class Counter:
        def __init__(self, *args, **kwargs): pass

        def labels(self, **kwargs):
            return self

        def inc(self, amount=1): pass

        def count(self):
            return 0

    class Gauge:
        def __init__(self, *args, **kwargs): pass

        def labels(self, **kwargs):
            return self

        def set(self, value): pass

        def set_to_current_value(self): pass

        def inc(self, amount=1): pass

        def dec(self, amount=1): pass

    class Histogram:
        def __init__(self, *args, **kwargs): pass

        def labels(self, **kwargs):
            return self

        def observe(self, amount): pass

        def time(self):
            return self

    class Info:
        def __init__(self, *args, **kwargs): pass

        def labels(self, **kwargs):
            return self

        def info(self, val): pass

    def start_http_server(port: int):
        logging.warning(f"prometheus_client not available, metrics server not started on port {port}")
        return None

logger = logging.getLogger(__name__)


class GoalTeamMetrics:
    """Prometheus metrics collector for Goal-Driven Teams.

    Tracks:
    - Team creation metrics (count, duration, mode distribution)
    - Goal parsing metrics (intent, domain, confidence)
    - Skill usage per team
    - Error tracking by error code
    - Active team count gauge
    - Learning system metrics (outcomes, recommendations, feedback)

    Uses lazy metric initialization to avoid duplicate registration errors.

    Example:
        ```python
        from mahavishnu.core.goal_team_metrics import get_goal_team_metrics

        metrics = get_goal_team_metrics()

        # Record team creation
        with metrics.team_creation_duration(mode="coordinate") as timer:
            team_config = await factory.create_team_from_goal(goal)
        metrics.record_team_created(mode="coordinate", skill_count=3)

        # Record skill usage
        for skill in parsed.skills:
            metrics.record_skill_usage(skill)

        # Record errors
        metrics.record_error(error_code="MHV-465")

        # Record learning outcome
        metrics.record_learning_outcome(success=True, mode="coordinate")

        # Record mode recommendation
        metrics.record_mode_recommendation(intent="review", mode="coordinate", confidence=0.85)
        ```
    """

    def __init__(self, server_name: str = "mahavishnu") -> None:
        """Initialize goal team metrics collector.

        Args:
            server_name: Name of server (default: "mahavishnu")
        """
        if not PROMETHEUS_AVAILABLE:
            logger.warning("Prometheus client not available, goal team metrics disabled")
            self._enabled = False
        else:
            self._enabled = True

        self.server_name = server_name

        # Lazy metric instances (cached after creation)
        self._metrics_initialized = False

        # Counter metrics
        self._teams_created_counter: Counter | None = None
        self._goals_parsed_counter: Counter | None = None
        self._skill_usage_counter: Counter | None = None
        self._errors_counter: Counter | None = None

        # Learning counter metrics (Phase 3)
        self._learning_outcomes_counter: Counter | None = None
        self._learning_recommendations_counter: Counter | None = None
        self._learning_feedback_counter: Counter | None = None

        # Gauge metrics
        self._active_teams_gauge: Gauge | None = None

        # Learning gauge metrics (Phase 3)
        self._learning_success_rate_gauge: Gauge | None = None

        # Histogram metrics
        self._team_creation_histogram: Histogram | None = None
        self._parsing_confidence_histogram: Histogram | None = None

        # Learning histogram metrics (Phase 3)
        self._learning_latency_histogram: Histogram | None = None

        # Info metrics
        self._team_info: Info | None = None

    def _initialize_metrics(self) -> None:
        """Initialize all Prometheus metrics (called once).

        This method creates all metric instances at once to avoid
        duplicate registration errors.
        """
        if self._metrics_initialized:
            return

        # Create teams created counter
        try:
            self._teams_created_counter = Counter(
                "mahavishnu_goal_teams_created_total",
                "Total goal-driven teams created",
                ["server", "mode", "skill_count"],
            )
        except ValueError:
            logger.debug(f"Reusing existing teams created counter: {self.server_name}")

        # Create goals parsed counter
        try:
            self._goals_parsed_counter = Counter(
                "mahavishnu_goal_teams_parsed_total",
                "Total goals parsed by intent, domain, and method",
                ["server", "intent", "domain", "method"],
            )
        except ValueError:
            logger.debug(f"Reusing existing goals parsed counter: {self.server_name}")

        # Create skill usage counter
        try:
            self._skill_usage_counter = Counter(
                "mahavishnu_goal_teams_skill_usage_total",
                "Total skill usage in goal-driven teams",
                ["server", "skill_name"],
            )
        except ValueError:
            logger.debug(f"Reusing existing skill usage counter: {self.server_name}")

        # Create errors counter
        try:
            self._errors_counter = Counter(
                "mahavishnu_goal_teams_errors_total",
                "Total goal-driven team errors by error code",
                ["server", "error_code"],
            )
        except ValueError:
            logger.debug(f"Reusing existing errors counter: {self.server_name}")

        # Create active teams gauge
        try:
            self._active_teams_gauge = Gauge(
                "mahavishnu_goal_teams_active",
                "Current number of active goal-driven teams",
                ["server"],
            )
        except ValueError:
            logger.debug(f"Reusing existing active teams gauge: {self.server_name}")

        # Create team creation duration histogram
        try:
            self._team_creation_histogram = Histogram(
                "mahavishnu_goal_team_creation_duration_seconds",
                "Time taken to create goal-driven teams",
                ["server", "mode"],
                buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
            )
        except ValueError:
            logger.debug(f"Reusing existing team creation histogram: {self.server_name}")

        # Create parsing confidence histogram
        try:
            self._parsing_confidence_histogram = Histogram(
                "mahavishnu_goal_teams_parsing_confidence",
                "Distribution of goal parsing confidence scores",
                ["server", "method"],
                buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0),
            )
        except ValueError:
            logger.debug(f"Reusing existing parsing confidence histogram: {self.server_name}")

        # Create team info metric
        try:
            self._team_info = Info(
                "mahavishnu_goal_team",
                "Information about a goal-driven team",
                ["server", "team_id", "mode"],
            )
        except ValueError:
            logger.debug(f"Reusing existing team info metric: {self.server_name}")

        # ====================================================================
        # Learning System Metrics (Phase 3)
        # ====================================================================

        # Create learning outcomes counter
        try:
            self._learning_outcomes_counter = Counter(
                "mahavishnu_goal_teams_learning_outcomes_recorded_total",
                "Total team execution outcomes recorded for learning",
                ["server", "success", "mode"],
            )
        except ValueError:
            logger.debug(f"Reusing existing learning outcomes counter: {self.server_name}")

        # Create learning recommendations counter
        try:
            self._learning_recommendations_counter = Counter(
                "mahavishnu_goal_teams_learning_recommendations_total",
                "Total mode recommendations made by learning system",
                ["server", "intent", "mode", "used"],
            )
        except ValueError:
            logger.debug(f"Reusing existing learning recommendations counter: {self.server_name}")

        # Create learning feedback counter
        try:
            self._learning_feedback_counter = Counter(
                "mahavishnu_goal_teams_learning_feedback_total",
                "Total user feedback recorded for learning",
                ["server", "feedback_type"],
            )
        except ValueError:
            logger.debug(f"Reusing existing learning feedback counter: {self.server_name}")

        # Create learning success rate gauge
        try:
            self._learning_success_rate_gauge = Gauge(
                "mahavishnu_goal_teams_learning_success_rate",
                "Current success rate from learning data",
                ["server"],
            )
        except ValueError:
            logger.debug(f"Reusing existing learning success rate gauge: {self.server_name}")

        # Create learning latency histogram
        try:
            self._learning_latency_histogram = Histogram(
                "mahavishnu_goal_teams_learning_latency_seconds",
                "Distribution of team execution latencies",
                ["server", "mode"],
                buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
            )
        except ValueError:
            logger.debug(f"Reusing existing learning latency histogram: {self.server_name}")

        self._metrics_initialized = True
        logger.info(f"Initialized Prometheus goal team metrics for server: {self.server_name}")

    def _ensure_enabled(self) -> None:
        """Check if metrics are enabled and initialize if needed."""
        if not self._enabled:
            logger.debug(f"Goal team metrics disabled, skipping operation for server: {self.server_name}")
            return

        # Initialize metrics on first use
        self._initialize_metrics()

    # ========================================================================
    # Team Creation Metrics
    # ========================================================================

    def record_team_created(
        self,
        mode: str,
        skill_count: int,
    ) -> None:
        """Record a team creation event.

        Args:
            mode: Team mode (coordinate, route, broadcast, collaborate)
            skill_count: Number of skills/agents in the team
        """
        self._ensure_enabled()
        if self._teams_created_counter:
            self._teams_created_counter.labels(
                server=self.server_name,
                mode=mode,
                skill_count=str(skill_count),
            ).inc()
            logger.debug(f"Recorded team creation: mode={mode}, skills={skill_count}")

    @contextmanager
    def team_creation_duration(
        self,
        mode: str,
    ) -> Generator[None]:
        """Context manager to time team creation.

        Args:
            mode: Team mode being created

        Yields:
            Nothing, just times the block

        Example:
            ```python
            with metrics.team_creation_duration(mode="coordinate"):
                team_config = await factory.create_team_from_goal(goal)
            ```
        """
        self._ensure_enabled()
        start_time = time.perf_counter()
        try:
            yield
        finally:
            if self._team_creation_histogram and self._enabled:
                duration = time.perf_counter() - start_time
                self._team_creation_histogram.labels(
                    server=self.server_name,
                    mode=mode,
                ).observe(duration)
                logger.debug(f"Recorded team creation duration: {duration:.3f}s for mode={mode}")

    # ========================================================================
    # Goal Parsing Metrics
    # ========================================================================

    def record_goal_parsed(
        self,
        intent: str,
        domain: str,
        method: str,
        confidence: float,
    ) -> None:
        """Record a goal parsing event.

        Args:
            intent: Parsed intent (review, build, test, fix, etc.)
            domain: Parsed domain (security, performance, quality, etc.)
            method: Parsing method (pattern, llm)
            confidence: Confidence score (0.0-1.0)
        """
        self._ensure_enabled()

        # Record parsing counter
        if self._goals_parsed_counter:
            self._goals_parsed_counter.labels(
                server=self.server_name,
                intent=intent,
                domain=domain,
                method=method,
            ).inc()

        # Record confidence histogram
        if self._parsing_confidence_histogram:
            self._parsing_confidence_histogram.labels(
                server=self.server_name,
                method=method,
            ).observe(confidence)

        logger.debug(
            f"Recorded goal parsing: intent={intent}, domain={domain}, "
            f"method={method}, confidence={confidence:.2f}"
        )

    # ========================================================================
    # Skill Usage Metrics
    # ========================================================================

    def record_skill_usage(self, skill_name: str) -> None:
        """Record skill usage in a team.

        Args:
            skill_name: Name of the skill used (security, quality, etc.)
        """
        self._ensure_enabled()
        if self._skill_usage_counter:
            self._skill_usage_counter.labels(
                server=self.server_name,
                skill_name=skill_name,
            ).inc()
            logger.debug(f"Recorded skill usage: {skill_name}")

    def record_skills_usage(self, skill_names: list[str]) -> None:
        """Record multiple skill usages.

        Args:
            skill_names: List of skill names used
        """
        for skill_name in skill_names:
            self.record_skill_usage(skill_name)

    # ========================================================================
    # Error Metrics
    # ========================================================================

    def record_error(self, error_code: str) -> None:
        """Record a goal team error.

        Args:
            error_code: Error code (e.g., MHV-460, MHV-465)
        """
        self._ensure_enabled()
        if self._errors_counter:
            self._errors_counter.labels(
                server=self.server_name,
                error_code=error_code,
            ).inc()
            logger.debug(f"Recorded error: {error_code}")

    # ========================================================================
    # Active Teams Gauge
    # ========================================================================

    def set_active_teams(self, count: int) -> None:
        """Set the current number of active teams.

        Args:
            count: Number of active teams
        """
        self._ensure_enabled()
        if self._active_teams_gauge:
            self._active_teams_gauge.labels(server=self.server_name).set(count)
            logger.debug(f"Set active teams count: {count}")

    def increment_active_teams(self) -> None:
        """Increment active teams counter by 1."""
        self._ensure_enabled()
        if self._active_teams_gauge:
            self._active_teams_gauge.labels(server=self.server_name).inc()

    def decrement_active_teams(self) -> None:
        """Decrement active teams counter by 1."""
        self._ensure_enabled()
        if self._active_teams_gauge:
            self._active_teams_gauge.labels(server=self.server_name).dec()

    # ========================================================================
    # Team Info Metric
    # ========================================================================

    def set_team_info(
        self,
        team_id: str,
        mode: str,
        intent: str,
        domain: str,
        skill_count: int,
        confidence: float,
    ) -> None:
        """Set team information metric.

        Args:
            team_id: Unique team identifier
            mode: Team mode
            intent: Parsed intent
            domain: Parsed domain
            skill_count: Number of skills
            confidence: Parsing confidence
        """
        self._ensure_enabled()
        if self._team_info:
            self._team_info.labels(
                server=self.server_name,
                team_id=team_id,
                mode=mode,
            ).info(
                {
                    "intent": intent,
                    "domain": domain,
                    "skill_count": str(skill_count),
                    "confidence": f"{confidence:.2f}",
                }
            )

    # ========================================================================
    # Learning System Metrics (Phase 3)
    # ========================================================================

    def record_learning_outcome(
        self,
        success: bool,
        mode: str,
        latency_ms: float | None = None,
    ) -> None:
        """Record a learning outcome event.

        Args:
            success: Whether the execution succeeded
            mode: Team mode used
            latency_ms: Optional execution latency in milliseconds
        """
        self._ensure_enabled()
        if self._learning_outcomes_counter:
            self._learning_outcomes_counter.labels(
                server=self.server_name,
                success=str(success).lower(),
                mode=mode,
            ).inc()
            logger.debug(f"Recorded learning outcome: success={success}, mode={mode}")

        # Record latency if provided
        if latency_ms is not None and self._learning_latency_histogram:
            self._learning_latency_histogram.labels(
                server=self.server_name,
                mode=mode,
            ).observe(latency_ms / 1000.0)  # Convert to seconds

    def record_mode_recommendation(
        self,
        intent: str,
        mode: str,
        confidence: float,
        used: bool = True,
    ) -> None:
        """Record a mode recommendation event.

        Args:
            intent: Intent the recommendation was for
            mode: Recommended mode
            confidence: Confidence score of the recommendation
            used: Whether the recommendation was used
        """
        self._ensure_enabled()
        if self._learning_recommendations_counter:
            self._learning_recommendations_counter.labels(
                server=self.server_name,
                intent=intent,
                mode=mode,
                used=str(used).lower(),
            ).inc()
            logger.debug(
                f"Recorded mode recommendation: intent={intent}, mode={mode}, "
                f"confidence={confidence:.2f}, used={used}"
            )

    def record_user_feedback(self, feedback_type: str) -> None:
        """Record user feedback event.

        Args:
            feedback_type: Type of feedback ("positive" or "negative")
        """
        self._ensure_enabled()
        if self._learning_feedback_counter:
            self._learning_feedback_counter.labels(
                server=self.server_name,
                feedback_type=feedback_type,
            ).inc()
            logger.debug(f"Recorded user feedback: {feedback_type}")

    def set_learning_success_rate(self, rate: float) -> None:
        """Set the current learning success rate.

        Args:
            rate: Success rate (0.0-1.0)
        """
        self._ensure_enabled()
        if self._learning_success_rate_gauge:
            self._learning_success_rate_gauge.labels(
                server=self.server_name,
            ).set(rate)
            logger.debug(f"Set learning success rate: {rate:.2%}")

    # ========================================================================
    # Utility Methods
    # ========================================================================

    def get_metrics_summary(self) -> dict[str, Any]:
        """Get summary of current metrics.

        Returns:
            Dictionary with metric summaries
        """
        return {
            "server": self.server_name,
            "enabled": self._enabled,
            "initialized": self._metrics_initialized,
            "team_creation_tracking": self._teams_created_counter is not None,
            "goal_parsing_tracking": self._goals_parsed_counter is not None,
            "skill_usage_tracking": self._skill_usage_counter is not None,
            "error_tracking": self._errors_counter is not None,
            "active_teams_tracking": self._active_teams_gauge is not None,
            "duration_tracking": self._team_creation_histogram is not None,
            "confidence_tracking": self._parsing_confidence_histogram is not None,
            "learning_outcomes_tracking": self._learning_outcomes_counter is not None,
            "learning_recommendations_tracking": self._learning_recommendations_counter is not None,
            "learning_feedback_tracking": self._learning_feedback_counter is not None,
            "learning_success_rate_tracking": self._learning_success_rate_gauge is not None,
            "learning_latency_tracking": self._learning_latency_histogram is not None,
        }


class GoalTeamMetricsRecorder:
    """Context manager for timing goal team operations.

    A convenience class that combines timing with metric recording.

    Example:
        ```python
        from mahavishnu.core.goal_team_metrics import GoalTeamMetricsRecorder

        async with GoalTeamMetricsRecorder(
            metrics=metrics,
            operation="team_creation",
            mode="coordinate"
        ) as recorder:
            team_config = await factory.create_team_from_goal(goal)
            recorder.set_metadata(skill_count=len(team_config.members))
        ```
    """

    def __init__(
        self,
        metrics: GoalTeamMetrics,
        operation: str,
        mode: str = "unknown",
    ) -> None:
        """Initialize the metrics recorder.

        Args:
            metrics: GoalTeamMetrics instance
            operation: Operation name (team_creation, goal_parsing, etc.)
            mode: Team mode for labels
        """
        self.metrics = metrics
        self.operation = operation
        self.mode = mode
        self.start_time: float | None = None
        self.metadata: dict[str, Any] = {}

    def __enter__(self) -> GoalTeamMetricsRecorder:
        """Start timing."""
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop timing and record metrics."""
        if self.start_time is None:
            return

        duration = time.perf_counter() - self.start_time

        # Record duration based on operation type
        if self.operation == "team_creation" and self.metrics._team_creation_histogram:
            self.metrics._team_creation_histogram.labels(
                server=self.metrics.server_name,
                mode=self.mode,
            ).observe(duration)

        logger.debug(
            f"Goal team operation completed: {self.operation}, "
            f"mode={self.mode}, duration={duration:.3f}s"
        )

    def set_metadata(self, **kwargs) -> None:
        """Set additional metadata for the operation.

        Args:
            **kwargs: Key-value pairs to store as metadata
        """
        self.metadata.update(kwargs)

    # For async context manager support
    async def __aenter__(self) -> GoalTeamMetricsRecorder:
        """Start timing (async version)."""
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop timing and record metrics (async version)."""
        self.__exit__(exc_type, exc_val, exc_tb)


# ============================================================================
# Module-Level Functions
# ============================================================================


def start_metrics_server(port: int = 9092) -> Any:
    """Start Prometheus metrics HTTP server for goal team metrics.

    Args:
        port: Metrics server port (default: 9092, different from routing metrics)

    Returns:
        Prometheus HTTP server thread (or None if unavailable)

    Example:
        >>> from mahavishnu.core.goal_team_metrics import start_metrics_server
        >>> metrics_server = start_metrics_server(port=9092)
        >>> print("Goal team metrics available on http://localhost:9092")
    """
    if not PROMETHEUS_AVAILABLE:
        logger.warning("Cannot start Prometheus goal team metrics server: prometheus_client not installed")
        logger.warning("Install with: pip install prometheus-client")
        return None

    try:
        return start_http_server(port)
    except OSError as e:
        logger.error(f"Failed to start Prometheus metrics server on port {port}: {e}")
        logger.error(f"Port {port} may already be in use")
        return None


# Metrics instance factory
_instances: dict[str, GoalTeamMetrics] = {}


def get_goal_team_metrics(server_name: str = "mahavishnu") -> GoalTeamMetrics:
    """Get or create goal team metrics instance.

    Args:
        server_name: Name of server (default: "mahavishnu")

    Returns:
        GoalTeamMetrics instance for server

    Example:
        >>> from mahavishnu.core.goal_team_metrics import get_goal_team_metrics
        >>> metrics = get_goal_team_metrics()
        >>> metrics.record_team_created(mode="coordinate", skill_count=3)
    """
    if server_name not in _instances:
        _instances[server_name] = GoalTeamMetrics(server_name)
        logger.info(f"Created goal team metrics instance for server: {server_name}")

    return _instances[server_name]


def reset_goal_team_metrics() -> None:
    """Reset all goal team metrics instances (useful for testing).

    Also clears Prometheus registry to avoid duplicate errors.

    Example:
        >>> from mahavishnu.core.goal_team_metrics import reset_goal_team_metrics
        >>> reset_goal_team_metrics()
        >>> print("All goal team metrics instances and registry cleared")
    """
    global _instances
    _instances.clear()

    # Clear Prometheus registry if available
    if PROMETHEUS_AVAILABLE:
        # Clear all collectors from default registry
        for collector in list(REGISTRY._collector_to_names.keys()):
            REGISTRY.unregister(collector)
        logger.info("Cleared Prometheus registry")

    logger.info("Reset all goal team metrics instances")


__all__ = [
    "GoalTeamMetrics",
    "GoalTeamMetricsRecorder",
    "get_goal_team_metrics",
    "reset_goal_team_metrics",
    "start_metrics_server",
]
