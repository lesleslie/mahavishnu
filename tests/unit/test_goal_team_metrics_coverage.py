"""Coverage tests for mahavishnu.core.goal_team_metrics.

Targets >=80% line+branch coverage for the Prometheus metrics module used by
the goal-driven team subsystem. Exercises both the prometheus-available code
path and the graceful-degradation / disabled path.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.core import goal_team_metrics as gtm_module
from mahavishnu.core.goal_team_metrics import (
    GoalTeamMetrics,
    GoalTeamMetricsRecorder,
    get_goal_team_metrics,
    reset_goal_team_metrics,
    start_metrics_server,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_instances() -> None:
    """Ensure module-level instances and Prometheus registry are clean per test."""
    reset_goal_team_metrics()
    yield
    reset_goal_team_metrics()


@pytest.fixture
def fresh_metrics() -> GoalTeamMetrics:
    """Return a freshly-initialised GoalTeamMetrics with prometheus enabled."""
    return GoalTeamMetrics(server_name="test-server")


@pytest.fixture
def disabled_metrics() -> GoalTeamMetrics:
    """Return a GoalTeamMetrics instance with _enabled=False (simulates missing client)."""
    metrics = GoalTeamMetrics(server_name="disabled")
    metrics._enabled = False
    return metrics


# ---------------------------------------------------------------------------
# Construction and init
# ---------------------------------------------------------------------------


def test_init_with_default_server_name() -> None:
    metrics = GoalTeamMetrics()
    assert metrics.server_name == "mahavishnu"
    # All metric slots start as None
    assert metrics._teams_created_counter is None
    assert metrics._goals_parsed_counter is None
    assert metrics._skill_usage_counter is None
    assert metrics._errors_counter is None
    assert metrics._learning_outcomes_counter is None
    assert metrics._learning_recommendations_counter is None
    assert metrics._learning_feedback_counter is None
    assert metrics._active_teams_gauge is None
    assert metrics._learning_success_rate_gauge is None
    assert metrics._team_creation_histogram is None
    assert metrics._parsing_confidence_histogram is None
    assert metrics._learning_latency_histogram is None
    assert metrics._team_info is None
    assert metrics._metrics_initialized is False


def test_init_with_custom_server_name() -> None:
    metrics = GoalTeamMetrics(server_name="custom-server")
    assert metrics.server_name == "custom-server"


def test_initialize_metrics_idempotent(fresh_metrics: GoalTeamMetrics) -> None:
    fresh_metrics._initialize_metrics()
    assert fresh_metrics._metrics_initialized is True
    first_team_counter = fresh_metrics._teams_created_counter

    # Second call should be a no-op
    fresh_metrics._initialize_metrics()
    assert fresh_metrics._teams_created_counter is first_team_counter


def test_initialize_metrics_handles_value_error(fresh_metrics: GoalTeamMetrics) -> None:
    """Re-creating metrics whose names already exist in the registry hits the
    except ValueError branches. We patch a few specific names with a mock
    that always raises to confirm the fallback path works."""
    with (
        patch.object(gtm_module, "Counter", side_effect=ValueError("dup")),
        patch.object(gtm_module, "Gauge", side_effect=ValueError("dup")),
        patch.object(gtm_module, "Histogram", side_effect=ValueError("dup")),
        patch.object(gtm_module, "Info", side_effect=ValueError("dup")),
    ):
        fresh_metrics._initialize_metrics()
    # Initialisation flag should still be set, even though the
    # underlying counter assignments were swallowed.
    assert fresh_metrics._metrics_initialized is True


# ---------------------------------------------------------------------------
# Disabled / unavailable Prometheus
# ---------------------------------------------------------------------------


def test_disabled_branch_warns(caplog: pytest.LogCaptureFixture) -> None:
    """If PROMETHEUS_AVAILABLE is False, the ctor logs a warning and disables."""
    with caplog.at_level(logging.WARNING, logger="mahavishnu.core.goal_team_metrics"):
        with patch.object(gtm_module, "PROMETHEUS_AVAILABLE", False):
            metrics = GoalTeamMetrics(server_name="disabled-srv")
    assert metrics._enabled is False
    assert any("Prometheus client not available" in rec.message for rec in caplog.records)


def test_disabled_metrics_no_op(
    disabled_metrics: GoalTeamMetrics,
) -> None:
    """All record* / set* methods must be safe no-ops when disabled."""
    # No exceptions, and the lazy metrics stay None
    disabled_metrics.record_team_created(mode="coordinate", skill_count=2)
    disabled_metrics.record_goal_parsed("intent", "domain", "method", 0.5)
    disabled_metrics.record_skill_usage("skill")
    disabled_metrics.record_skills_usage(["a", "b"])
    disabled_metrics.record_error("MHV-000")
    disabled_metrics.set_active_teams(5)
    disabled_metrics.increment_active_teams()
    disabled_metrics.decrement_active_teams()
    disabled_metrics.set_team_info("team-1", "coordinate", "intent", "domain", 3, 0.9)
    disabled_metrics.record_learning_outcome(True, "coordinate")
    disabled_metrics.record_learning_outcome(False, "coordinate", latency_ms=12.5)
    disabled_metrics.record_mode_recommendation("intent", "coordinate", 0.7, used=False)
    disabled_metrics.record_user_feedback("positive")
    disabled_metrics.set_learning_success_rate(0.42)

    # Context manager
    with disabled_metrics.team_creation_duration("coordinate"):
        pass

    assert disabled_metrics._teams_created_counter is None


# ---------------------------------------------------------------------------
# Team creation
# ---------------------------------------------------------------------------


def test_record_team_created(fresh_metrics: GoalTeamMetrics) -> None:
    fresh_metrics._initialize_metrics()
    counter = fresh_metrics._teams_created_counter
    assert counter is not None
    before = counter.labels(server="test-server", mode="coordinate", skill_count="3")._value.get()
    fresh_metrics.record_team_created(mode="coordinate", skill_count=3)
    after = counter.labels(server="test-server", mode="coordinate", skill_count="3")._value.get()
    assert after == before + 1


def test_team_creation_duration_context_manager(
    fresh_metrics: GoalTeamMetrics,
) -> None:
    fresh_metrics._initialize_metrics()
    with fresh_metrics.team_creation_duration(mode="route"):
        # Do a tiny bit of work so the timer is non-zero
        sum(range(10))
    histogram = fresh_metrics._team_creation_histogram
    assert histogram is not None
    # We don't assert on bucket counts because that depends on the
    # prometheus_client internals; the fact that the context manager
    # ran without error is the meaningful signal.
    # The histogram's labels for the test-server/route combo must exist.
    samples = list(histogram.collect())[0].samples
    assert any(s.labels.get("mode") == "route" for s in samples)


# ---------------------------------------------------------------------------
# Goal parsing
# ---------------------------------------------------------------------------


def test_record_goal_parsed(fresh_metrics: GoalTeamMetrics) -> None:
    fresh_metrics._initialize_metrics()
    counter = fresh_metrics._goals_parsed_counter
    assert counter is not None
    parsed = counter.labels(
        server="test-server", intent="review", domain="security", method="llm"
    )._value.get()
    fresh_metrics.record_goal_parsed(
        intent="review",
        domain="security",
        method="llm",
        confidence=0.85,
    )
    after = counter.labels(
        server="test-server", intent="review", domain="security", method="llm"
    )._value.get()
    assert after == parsed + 1


# ---------------------------------------------------------------------------
# Skill usage
# ---------------------------------------------------------------------------


def test_record_skill_usage(fresh_metrics: GoalTeamMetrics) -> None:
    fresh_metrics._initialize_metrics()
    counter = fresh_metrics._skill_usage_counter
    assert counter is not None
    before = counter.labels(server="test-server", skill_name="quality")._value.get()
    fresh_metrics.record_skill_usage("quality")
    after = counter.labels(server="test-server", skill_name="quality")._value.get()
    assert after == before + 1


def test_record_skills_usage(fresh_metrics: GoalTeamMetrics) -> None:
    fresh_metrics._initialize_metrics()
    counter = fresh_metrics._skill_usage_counter
    assert counter is not None
    before_a = counter.labels(server="test-server", skill_name="alpha")._value.get()
    before_b = counter.labels(server="test-server", skill_name="beta")._value.get()
    fresh_metrics.record_skills_usage(["alpha", "beta"])
    after_a = counter.labels(server="test-server", skill_name="alpha")._value.get()
    after_b = counter.labels(server="test-server", skill_name="beta")._value.get()
    assert after_a == before_a + 1
    assert after_b == before_b + 1


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_record_error(fresh_metrics: GoalTeamMetrics) -> None:
    fresh_metrics._initialize_metrics()
    counter = fresh_metrics._errors_counter
    assert counter is not None
    before = counter.labels(server="test-server", error_code="MHV-460")._value.get()
    fresh_metrics.record_error("MHV-460")
    after = counter.labels(server="test-server", error_code="MHV-460")._value.get()
    assert after == before + 1


# ---------------------------------------------------------------------------
# Active teams gauge
# ---------------------------------------------------------------------------


def test_set_active_teams(fresh_metrics: GoalTeamMetrics) -> None:
    fresh_metrics._initialize_metrics()
    gauge = fresh_metrics._active_teams_gauge
    assert gauge is not None
    fresh_metrics.set_active_teams(7)
    assert gauge.labels(server="test-server")._value.get() == 7


def test_increment_active_teams(fresh_metrics: GoalTeamMetrics) -> None:
    fresh_metrics._initialize_metrics()
    gauge = fresh_metrics._active_teams_gauge
    assert gauge is not None
    fresh_metrics.set_active_teams(2)
    fresh_metrics.increment_active_teams()
    assert gauge.labels(server="test-server")._value.get() == 3


def test_decrement_active_teams(fresh_metrics: GoalTeamMetrics) -> None:
    fresh_metrics._initialize_metrics()
    gauge = fresh_metrics._active_teams_gauge
    assert gauge is not None
    fresh_metrics.set_active_teams(5)
    fresh_metrics.decrement_active_teams()
    assert gauge.labels(server="test-server")._value.get() == 4


# ---------------------------------------------------------------------------
# Team info
# ---------------------------------------------------------------------------


def test_set_team_info(fresh_metrics: GoalTeamMetrics) -> None:
    fresh_metrics._initialize_metrics()
    # Should not raise; Info.info accepts a dict
    fresh_metrics.set_team_info(
        team_id="team-42",
        mode="coordinate",
        intent="review",
        domain="quality",
        skill_count=4,
        confidence=0.91,
    )


# ---------------------------------------------------------------------------
# Learning system metrics
# ---------------------------------------------------------------------------


def test_record_learning_outcome_without_latency(
    fresh_metrics: GoalTeamMetrics,
) -> None:
    fresh_metrics._initialize_metrics()
    counter = fresh_metrics._learning_outcomes_counter
    assert counter is not None
    before = counter.labels(server="test-server", success="true", mode="coordinate")._value.get()
    fresh_metrics.record_learning_outcome(success=True, mode="coordinate")
    after = counter.labels(server="test-server", success="true", mode="coordinate")._value.get()
    assert after == before + 1


def test_record_learning_outcome_with_latency(
    fresh_metrics: GoalTeamMetrics,
) -> None:
    fresh_metrics._initialize_metrics()
    histogram = fresh_metrics._learning_latency_histogram
    assert histogram is not None
    fresh_metrics.record_learning_outcome(success=False, mode="broadcast", latency_ms=1500.0)
    # No assertion on bucket values, but the call must not raise
    samples = list(histogram.collect())[0].samples
    assert any(s.labels.get("mode") == "broadcast" for s in samples)


def test_record_mode_recommendation_used_true(
    fresh_metrics: GoalTeamMetrics,
) -> None:
    fresh_metrics._initialize_metrics()
    counter = fresh_metrics._learning_recommendations_counter
    assert counter is not None
    before = counter.labels(
        server="test-server",
        intent="review",
        mode="coordinate",
        used="true",
    )._value.get()
    fresh_metrics.record_mode_recommendation(intent="review", mode="coordinate", confidence=0.88)
    after = counter.labels(
        server="test-server",
        intent="review",
        mode="coordinate",
        used="true",
    )._value.get()
    assert after == before + 1


def test_record_mode_recommendation_used_false(
    fresh_metrics: GoalTeamMetrics,
) -> None:
    fresh_metrics._initialize_metrics()
    counter = fresh_metrics._learning_recommendations_counter
    assert counter is not None
    before = counter.labels(
        server="test-server",
        intent="build",
        mode="route",
        used="false",
    )._value.get()
    fresh_metrics.record_mode_recommendation(
        intent="build", mode="route", confidence=0.6, used=False
    )
    after = counter.labels(
        server="test-server",
        intent="build",
        mode="route",
        used="false",
    )._value.get()
    assert after == before + 1


def test_record_user_feedback(fresh_metrics: GoalTeamMetrics) -> None:
    fresh_metrics._initialize_metrics()
    counter = fresh_metrics._learning_feedback_counter
    assert counter is not None
    before = counter.labels(server="test-server", feedback_type="positive")._value.get()
    fresh_metrics.record_user_feedback("positive")
    after = counter.labels(server="test-server", feedback_type="positive")._value.get()
    assert after == before + 1


def test_set_learning_success_rate(fresh_metrics: GoalTeamMetrics) -> None:
    fresh_metrics._initialize_metrics()
    gauge = fresh_metrics._learning_success_rate_gauge
    assert gauge is not None
    fresh_metrics.set_learning_success_rate(0.73)
    assert gauge.labels(server="test-server")._value.get() == 0.73


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def test_get_metrics_summary_uninitialised(fresh_metrics: GoalTeamMetrics) -> None:
    summary = fresh_metrics.get_metrics_summary()
    assert summary["server"] == "test-server"
    assert summary["enabled"] is True
    assert summary["initialized"] is False
    # All tracking flags should be False pre-init
    for key, value in summary.items():
        if key.endswith("_tracking"):
            assert value is False, f"{key} should be False pre-init"


def test_get_metrics_summary_initialised(fresh_metrics: GoalTeamMetrics) -> None:
    fresh_metrics._initialize_metrics()
    summary = fresh_metrics.get_metrics_summary()
    assert summary["initialized"] is True
    for key, value in summary.items():
        if key.endswith("_tracking"):
            assert value is True, f"{key} should be True post-init"


def test_get_metrics_summary_disabled(disabled_metrics: GoalTeamMetrics) -> None:
    summary = disabled_metrics.get_metrics_summary()
    assert summary["enabled"] is False
    assert summary["initialized"] is False


# ---------------------------------------------------------------------------
# Recorder (sync + async)
# ---------------------------------------------------------------------------


def test_recorder_sync_records_team_creation(fresh_metrics: GoalTeamMetrics) -> None:
    fresh_metrics._initialize_metrics()
    with GoalTeamMetricsRecorder(
        metrics=fresh_metrics, operation="team_creation", mode="coordinate"
    ) as recorder:
        assert recorder.start_time is not None
        recorder.set_metadata(skill_count=3)
    assert recorder.metadata == {"skill_count": 3}
    # The histogram for the (test-server, coordinate) labels should now have
    # at least one observation recorded.
    histogram = fresh_metrics._team_creation_histogram
    assert histogram is not None
    samples = list(histogram.collect())[0].samples
    coord_samples = [s for s in samples if s.labels.get("mode") == "coordinate"]
    assert len(coord_samples) > 0


def test_recorder_sync_other_operation_no_recording(
    fresh_metrics: GoalTeamMetrics,
) -> None:
    """For operations other than 'team_creation' the recorder does nothing
    other than log — that branch must execute without raising."""
    fresh_metrics._initialize_metrics()
    with GoalTeamMetricsRecorder(
        metrics=fresh_metrics, operation="goal_parsing", mode="coordinate"
    ) as recorder:
        recorder.set_metadata(extra="value")
    assert recorder.metadata == {"extra": "value"}


def test_recorder_async_context_manager(fresh_metrics: GoalTeamMetrics) -> None:
    fresh_metrics._initialize_metrics()
    recorder_cm = GoalTeamMetricsRecorder(
        metrics=fresh_metrics, operation="team_creation", mode="route"
    )

    async def _run() -> None:
        async with recorder_cm as rec:
            assert rec.start_time is not None

    # Drive the coroutine synchronously since we have no event loop fixture
    import asyncio

    asyncio.run(_run())
    # Sanity: histogram exists
    assert fresh_metrics._team_creation_histogram is not None


# ---------------------------------------------------------------------------
# start_metrics_server
# ---------------------------------------------------------------------------


def test_start_metrics_server_calls_start_http_server() -> None:
    sentinel = MagicMock(name="server_thread")
    with patch.object(gtm_module, "start_http_server", return_value=sentinel) as mock:
        result = start_metrics_server(port=9092)
    assert result is sentinel
    mock.assert_called_once_with(9092)


def test_start_metrics_server_handles_oserror(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger="mahavishnu.core.goal_team_metrics"):
        with patch.object(gtm_module, "start_http_server", side_effect=OSError("in use")):
            result = start_metrics_server(port=9093)
    assert result is None
    assert any("Failed to start Prometheus metrics server" in rec.message for rec in caplog.records)


def test_start_metrics_server_unavailable_returns_none() -> None:
    with patch.object(gtm_module, "PROMETHEUS_AVAILABLE", False):
        result = start_metrics_server(port=9094)
    assert result is None


# ---------------------------------------------------------------------------
# Module-level instance factory
# ---------------------------------------------------------------------------


def test_get_goal_team_metrics_creates_and_reuses() -> None:
    m1 = get_goal_team_metrics(server_name="ec-1")
    m2 = get_goal_team_metrics(server_name="ec-1")
    m3 = get_goal_team_metrics(server_name="ec-2")
    assert m1 is m2
    assert m1 is not m3
    assert m1.server_name == "ec-1"
    assert m3.server_name == "ec-2"


def test_reset_goal_team_metrics_clears_instances() -> None:
    m1 = get_goal_team_metrics(server_name="ec-1")
    assert m1 is get_goal_team_metrics(server_name="ec-1")
    reset_goal_team_metrics()
    # After reset, requesting the same name should produce a new instance
    m2 = get_goal_team_metrics(server_name="ec-1")
    assert m1 is not m2


def test_reset_goal_team_metrics_unavailable() -> None:
    """The reset function's PROMETHEUS_AVAILABLE branch must run when
    the library is missing."""
    with patch.object(gtm_module, "PROMETHEUS_AVAILABLE", False):
        # Should be a no-op for the registry portion; must not raise
        reset_goal_team_metrics()


# ---------------------------------------------------------------------------
# Ensure-enabled path / disabled warnings
# ---------------------------------------------------------------------------


def test_ensure_enabled_disabled_logs(
    caplog: pytest.LogCaptureFixture, disabled_metrics: GoalTeamMetrics
) -> None:
    with caplog.at_level(logging.DEBUG, logger="mahavishnu.core.goal_team_metrics"):
        disabled_metrics._ensure_enabled()
    assert any("disabled" in rec.message for rec in caplog.records)
    # Initialised flag should remain False on disabled
    assert disabled_metrics._metrics_initialized is False
