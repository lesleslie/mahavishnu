"""Unit tests for core.goal_team_metrics."""

from __future__ import annotations

import importlib

import pytest

import mahavishnu.core.goal_team_metrics as gtm


class _Metric:
    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002,ANN003
        self.label_calls: list[dict] = []
        self.inc_calls: list[float] = []
        self.observe_calls: list[float] = []
        self.set_calls: list[float] = []
        self.info_calls: list[dict] = []

    def labels(self, **kwargs):  # noqa: ANN003
        self.label_calls.append(kwargs)
        return self

    def inc(self, amount=1):  # noqa: ANN001
        self.inc_calls.append(amount)

    def dec(self, amount=1):  # noqa: ANN001
        self.inc_calls.append(-amount)

    def observe(self, amount):  # noqa: ANN001
        self.observe_calls.append(amount)

    def set(self, value):  # noqa: ANN001
        self.set_calls.append(value)

    def info(self, val):  # noqa: ANN001
        self.info_calls.append(val)


def test_disabled_mode_noops_and_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gtm, "PROMETHEUS_AVAILABLE", False)
    metrics = gtm.GoalTeamMetrics("s1")
    metrics.record_team_created(mode="coordinate", skill_count=2)
    metrics.record_goal_parsed(intent="review", domain="quality", method="pattern", confidence=0.8)
    metrics.record_skill_usage("security")
    metrics.record_skills_usage(["quality", "performance"])
    metrics.record_error("MHV-465")
    metrics.set_active_teams(1)
    metrics.increment_active_teams()
    metrics.decrement_active_teams()
    metrics.set_team_info("t1", "coordinate", "review", "quality", 2, 0.8)
    metrics.record_learning_outcome(success=True, mode="coordinate", latency_ms=120.0)
    metrics.record_mode_recommendation("review", "coordinate", 0.9, used=False)
    metrics.record_user_feedback("positive")
    metrics.set_learning_success_rate(0.75)
    with metrics.team_creation_duration(mode="coordinate"):
        pass

    summary = metrics.get_metrics_summary()
    assert summary["enabled"] is False
    assert summary["initialized"] is False


def test_enabled_mode_records_all_metric_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gtm, "PROMETHEUS_AVAILABLE", True)
    monkeypatch.setattr(gtm, "Counter", _Metric)
    monkeypatch.setattr(gtm, "Gauge", _Metric)
    monkeypatch.setattr(gtm, "Histogram", _Metric)
    monkeypatch.setattr(gtm, "Info", _Metric)

    metrics = gtm.GoalTeamMetrics("s2")
    assert metrics._metrics_initialized is False

    metrics.record_team_created(mode="coordinate", skill_count=3)
    metrics.record_goal_parsed(intent="review", domain="security", method="llm", confidence=0.91)
    metrics.record_skill_usage("security")
    metrics.record_skills_usage(["quality", "perf"])
    metrics.record_error("MHV-460")
    metrics.set_active_teams(2)
    metrics.increment_active_teams()
    metrics.decrement_active_teams()
    metrics.set_team_info("team-1", "coordinate", "review", "security", 3, 0.91)
    metrics.record_learning_outcome(success=True, mode="coordinate", latency_ms=250.0)
    metrics.record_mode_recommendation("review", "coordinate", 0.88, used=True)
    metrics.record_user_feedback("negative")
    metrics.set_learning_success_rate(0.66)
    with metrics.team_creation_duration(mode="coordinate"):
        pass

    assert metrics._metrics_initialized is True
    assert metrics._teams_created_counter is not None
    assert metrics._team_creation_histogram is not None
    assert metrics._parsing_confidence_histogram is not None
    assert metrics._active_teams_gauge is not None
    assert metrics._team_info is not None
    assert metrics._learning_latency_histogram is not None
    assert metrics.get_metrics_summary()["enabled"] is True


@pytest.mark.asyncio
async def test_metrics_recorder_sync_and_async(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gtm, "PROMETHEUS_AVAILABLE", True)
    monkeypatch.setattr(gtm, "Counter", _Metric)
    monkeypatch.setattr(gtm, "Gauge", _Metric)
    monkeypatch.setattr(gtm, "Histogram", _Metric)
    monkeypatch.setattr(gtm, "Info", _Metric)

    metrics = gtm.GoalTeamMetrics("s3")
    metrics._initialize_metrics()

    recorder = gtm.GoalTeamMetricsRecorder(metrics, operation="team_creation", mode="route")
    with recorder:
        recorder.set_metadata(repo="x")
    assert recorder.metadata["repo"] == "x"

    async with gtm.GoalTeamMetricsRecorder(metrics, operation="team_creation", mode="broadcast"):
        pass

    assert metrics._team_creation_histogram.observe_calls


def test_start_server_getter_and_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gtm, "PROMETHEUS_AVAILABLE", False)
    assert gtm.start_metrics_server(9099) is None

    monkeypatch.setattr(gtm, "PROMETHEUS_AVAILABLE", True)
    monkeypatch.setattr(gtm, "start_http_server", lambda port: f"server-{port}")
    assert gtm.start_metrics_server(9098) == "server-9098"

    def _boom(_port: int):  # noqa: ANN001
        raise OSError("in use")

    monkeypatch.setattr(gtm, "start_http_server", _boom)
    assert gtm.start_metrics_server(9098) is None

    monkeypatch.setattr(gtm, "PROMETHEUS_AVAILABLE", False)
    gtm.reset_goal_team_metrics()
    a = gtm.get_goal_team_metrics("svc")
    b = gtm.get_goal_team_metrics("svc")
    assert a is b
    gtm.reset_goal_team_metrics()
    c = gtm.get_goal_team_metrics("svc")
    assert c is not a


def test_reset_clears_registry_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    unregistered: list[object] = []

    class _Registry:
        def __init__(self) -> None:
            self._collector_to_names = {object(): {"x"}, object(): {"y"}}

        def unregister(self, collector: object) -> None:
            unregistered.append(collector)

    monkeypatch.setattr(gtm, "PROMETHEUS_AVAILABLE", True)
    monkeypatch.setattr(gtm, "REGISTRY", _Registry())
    gtm._instances["tmp"] = gtm.GoalTeamMetrics("tmp")
    gtm.reset_goal_team_metrics()
    assert gtm._instances == {}
    assert len(unregistered) == 2


def test_fallback_module_import_and_dummy_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001,ANN002,ANN003
        if name == "prometheus_client":
            raise ImportError("no prometheus")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)
    mod = importlib.reload(gtm)
    assert mod.PROMETHEUS_AVAILABLE is False

    c = mod.Counter()
    c.labels(server="x").inc()
    assert c.count() == 0
    g = mod.Gauge()
    g.labels(server="x").set(1)
    g.set_to_current_value()
    g.inc()
    g.dec()
    h = mod.Histogram()
    h.labels(server="x").observe(1.2)
    assert h.time() is h
    i = mod.Info()
    i.labels(server="x").info({"a": "b"})
    assert mod.start_http_server(9999) is None

    monkeypatch.setattr("builtins.__import__", real_import)
    importlib.reload(gtm)


def test_initialize_metrics_valueerror_paths_and_recorder_start_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gtm, "PROMETHEUS_AVAILABLE", True)

    def _raise(*args, **kwargs):  # noqa: ANN002,ANN003
        raise ValueError("dup")

    monkeypatch.setattr(gtm, "Counter", _raise)
    monkeypatch.setattr(gtm, "Gauge", _raise)
    monkeypatch.setattr(gtm, "Histogram", _raise)
    monkeypatch.setattr(gtm, "Info", _raise)

    metrics = gtm.GoalTeamMetrics("vx")
    metrics._initialize_metrics()
    assert metrics._metrics_initialized is True

    recorder = gtm.GoalTeamMetricsRecorder(metrics, operation="team_creation", mode="x")
    recorder.__exit__(None, None, None)
